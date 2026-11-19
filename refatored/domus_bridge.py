"""Interface local do processo de voz. Não iniciar como servidor independente."""
import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from refatored.config import MODEL_CONVERSA
from refatored.conversation_memory import conversation_memory, should_expect_followup
from refatored.intent_router import intent_router
from refatored.llm_client import llm_client
from refatored.memory_store import memory_store
from refatored.reply_audio import AudioUnavailable, reply_audio
from refatored.skills import timer_manager
from refatored.speech_output import falar, text_only_response
from refatored.tts_client import tts_client

logger = logging.getLogger(__name__)
# O handler de SIGTERM/SIGINT pode interromper a thread de voz enquanto ela já
# detém este lock. A reentrada é só da mesma thread; voz e HTTP continuam exclusivos.
TURN_LOCK = threading.RLock()
_draining = threading.Event()
PREFIX = "/api/v1/assistant/"
MAX_BODY = 32 * 1024


def stop_mobile_intake():
    """Recusar novos turnos antes de parar música/timers; não abandonar um POST aceito."""
    _draining.set()
    # Barreira: ao retornar, nenhum turno HTTP anterior continua no roteador.
    with TURN_LOCK:
        pass


def _enabled(name):
    return os.getenv(name, "").strip().lower() in {"true", "yes", "1", "on"}


def snapshot(profile_id):
    target, state, targets = conversation_memory.get_last_ha_context()
    names = ", ".join(targets) or target
    context = ("Último alvo HA: " + names + (f" · estado na memória: {state}" if state else "")
               if names else "Sem dispositivo recente no contexto do HA.")
    return {
        "version": 1,
        "capabilities": {"reply_audio": True},
        "profile_id": profile_id,
        "session_label": "Casa · sessão compartilhada entre os perfis",
        "context": context,
        "history": conversation_memory.get_history(),
        "agenda": ([{"title": row["content"], "at": None}
                    for row in memory_store.list_memories(limit=20)]
                   if _enabled("DOMUS_SHARE_NOTES") else None),
        "timers": timer_manager.snapshot(),
        "models": {"llm": llm_client.describe_primary_model(MODEL_CONVERSA),
                   "tts": tts_client.describe_model()},
    }


def message(profile_id, body):
    # Nada de injetar histórico, modelo ou instruções especiais da camada HTTP.
    if not isinstance(body, dict) or body.keys() - {"text", "speak_on_pi"}:
        raise BadRequest()
    text = body.get("text")
    speak = body.get("speak_on_pi", False)
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000 or type(speak) is not bool:
        raise BadRequest()
    history = conversation_memory.get_history()
    followup = bool(history and history[-1]["role"] == "assistant"
                    and should_expect_followup(history[-1]["content"]))
    # Consumir inclusive o LLM em streaming, sem bips/TTS inline. Mesmo roteador,
    # mesmas ferramentas. O comando de tocar música e o alarme futuro não são TTS de resposta.
    with text_only_response():
        result = intent_router.processar_mensagem(text.strip(), is_followup=followup)
    reply = result["message"]
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("Resposta sem texto")
    if speak:
        try:
            falar(reply)  # única saída de voz do turno móvel, até nas rotas que só bipavam
        except Exception:
            logger.exception("Falhou a saída de voz móvel após o processamento do turno")
    return {"profile_id": profile_id, "text": reply, "reply_id": reply_audio.remember(profile_id, reply)}


class BadRequest(ValueError):
    pass


class Handler(BaseHTTPRequestHandler):
    timeout = 5  # leitura de headers/corpo vindos do proxy local

    def log_request(self, *args):
        pass  # não registrar conversas ou dados de consulta/acesso

    def _write_bytes(self, code, mime, data, profile=None):
        try:
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            if profile is not None:
                self.send_header("x-domus-profile", profile)
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # telefone/proxy já saiu; nunca repetir o comando nem a síntese

    def _write_json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._write_bytes(code, "application/json; charset=utf-8", data)

    def _handle(self):
        route = self.path
        if (self.command, route) not in {("GET", PREFIX + "state"), ("POST", PREFIX + "messages"), ("POST", PREFIX + "speech")}:
            return self._write_json(404, {"error": "Rota desconhecida"})
        profile = self.headers.get("x-domus-profile")
        if profile not in {"1", "2"}:
            return self._write_json(400, {"error": "Perfil Domus inválido"})
        body = None
        if self.command == "POST":
            if self.headers.get_content_type() != "application/json":
                return self._write_json(415, {"error": "Esperado application/json"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size > MAX_BODY:
                    return self._write_json(413, {"error": "Mensagem grande demais"})
                if size <= 0:
                    raise ValueError()
                body = json.loads(self.rfile.read(size).decode("utf-8"))
            except (ValueError, RecursionError):
                return self._write_json(400, {"error": "JSON inválido"})
        if route == PREFIX + "speech":
            if (not isinstance(body, dict) or set(body) != {'reply_id'} or
                    not isinstance(body['reply_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', body['reply_id'])):
                return self._write_json(400, {'error': 'Identificador de resposta inválido'})
            if _draining.is_set():
                return self._write_json(503, {'error': 'Assistant em encerramento'})
            # Não reexecutar mensagem nem bloquear voz/consultas enquanto sintetiza.
            try:
                mime, data = reply_audio.get(int(profile), body['reply_id'])
            except AudioUnavailable as e:
                return self._write_json(e.status, {'error': str(e)})
            except Exception:
                logger.error('Falha ao sintetizar áudio para o Domus')
                return self._write_json(503, {'error': 'Falha de síntese'})
            return self._write_bytes(200, mime, data, profile)
        # Não enfileirar um POST que poderia executar depois do timeout do celular.
        if not TURN_LOCK.acquire(blocking=False):
            return self._write_json(503, {"error": "Assistant ocupada com outro turno"})
        try:
            # Sob o mesmo lock da barreira de shutdown, antes de qualquer efeito.
            if _draining.is_set():
                status, payload = 503, {"error": "Assistant em encerramento"}
            elif self.command == "POST":
                status, payload = 200, message(int(profile), body)
            else:
                status, payload = 200, snapshot(int(profile))
        except BadRequest:
            status, payload = 400, {"error": "Esperados text (1–4000 caracteres) e speak_on_pi booleano"}
        except Exception:
            logger.exception("Falha na interface local do Domus")
            status, payload = 500, {"error": "Falha ao processar a solicitação"}
        finally:
            TURN_LOCK.release()
        self._write_json(status, payload)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()


@contextmanager
def running_bridge():
    """Ciclo de vida da thread está contido no main do serviço existente."""
    server = None
    if _enabled("DOMUS_BRIDGE_ENABLED"):
        try:
            port = int(os.getenv("DOMUS_BRIDGE_PORT", "8765"))
            if not 1 <= port <= 65535:
                raise ValueError("DOMUS_BRIDGE_PORT fora da faixa")
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except (OSError, ValueError):
            logger.exception("Ponte Domus indisponível; voz/CLI permanece independente")
    if server is None:
        yield
        return
    _draining.clear()
    thread = threading.Thread(target=server.serve_forever, name="Domus IPC", daemon=True)
    thread.start()
    logger.info("Ponte Domus v1 em 127.0.0.1:%d (sessão doméstica compartilhada)", port)
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
