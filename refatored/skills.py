import json
import os
import re
import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable

from refatored.config import CURRENT_SONG_FILE
from refatored.local_intents import format_time_ptbr, get_weather_response
from refatored.music import music_player
from refatored.home_assistant import (
    DEVICE_REGISTRY,
    resolver_comando,
    executar_comando_ha,
    consultar_estado_dispositivo_ha,
    listar_dispositivos_ligados_ha,
)
from refatored.memory_store import memory_store
from refatored.conversation_memory import conversation_memory
from refatored.speech_output import play_confirmation, falar

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. GERENCIADOR DE TIMERS E LEMBRETES FALADOS EM THREAD (BAIXO CONSUMO)
# ==============================================================================

_WORD_NUMBERS_PT: Dict[str, int] = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "quinze": 15, "vinte": 20,
    "trinta": 30, "quarenta": 40, "quarenta e cinco": 45, "cinquenta": 50,
}

_RE_TIMER_CANCEL = re.compile(
    r"\b(?:cancela(?:r)?|para(?:r)?|desativa(?:r)?|apaga(?:r)?|remove(?:r)?)\s+"
    r"(?:todos?\s+os\s+|o\s+|os\s+)?(?:timers?|cron[ôo]metros?|alarmes?|lembretes?\s+de\s+tempo)\b",
    re.IGNORECASE,
)

_RE_TIMER_STATUS = re.compile(
    r"\b(?:quanto\s+tempo\s+falta(?:\s+(?:no|pro|para\s+o)\s+(?:timer|cron[ôo]metro|alarme))?|"
    r"tem\s+algum\s+timer(?:\s+ativo|\s+rodando)?|quais\s+timers?\s+(?:est[ãa]o\s+)?ativos)\b",
    re.IGNORECASE,
)

_RE_TIMER_CREATE = re.compile(
    r"\b(?:coloca(?:r)?\s+um\s+timer|marca(?:r)?\s+um\s+timer|inicia(?:r)?\s+(?:um\s+)?timer|"
    r"cria(?:r)?\s+(?:um\s+)?timer|define\s+um\s+timer|timer\s+de|"
    r"cron[ôo]metro\s+de|me\s+avisa(?:r)?\s+(?:daqui\s+a|em)|"
    r"me\s+lembra(?:r)?\s+(?:daqui\s+a|em)|avisa(?:r)?\s+daqui\s+a)\b",
    re.IGNORECASE,
)


def _format_duration_ptbr(seconds: int) -> str:
    """Converte segundos em expressão falada natural em português."""
    seconds = max(1, int(seconds))
    horas, resto = divmod(seconds, 3600)
    minutos, segs = divmod(resto, 60)

    partes: List[str] = []
    if horas:
        partes.append(f"{horas} {'hora' if horas == 1 else 'horas'}")
    if minutos:
        if horas and minutos == 30 and segs == 0:
            return f"{horas} {'hora' if horas == 1 else 'horas'} e meia"
        partes.append(f"{minutos} {'minuto' if minutos == 1 else 'minutos'}")
    if segs and not horas:
        partes.append(f"{segs} {'segundo' if segs == 1 else 'segundos'}")

    if not partes:
        return "alguns segundos"
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + f" e {partes[-1]}"


def _extract_duration_and_reason(texto: str) -> Optional[tuple[int, str]]:
    """Extrai duração em segundos e motivo opcional de uma frase em pt-BR."""
    low = texto.lower().strip()

    # Caso especial: "meia hora"
    if re.search(r"\bmeia\s+hora\b", low):
        total_sec = 1800
    elif re.search(r"\b(?:1|uma)\s+hora\s+e\s+meia\b", low):
        total_sec = 5400
    else:
        # Substituir números por extenso simples antes de unidades de tempo
        normalizado = low
        for palavra, valor in sorted(_WORD_NUMBERS_PT.items(), key=lambda kv: len(kv[0]), reverse=True):
            normalizado = re.sub(
                rf"\b{re.escape(palavra)}\b(?=\s*(?:horas?|minutos?|min|segundos?|seg)\b)",
                str(valor),
                normalizado,
            )

        total_sec = 0
        for m in re.finditer(
            r"(\d+)\s*(horas?|h|minutos?|min|segundos?|seg|s)\b",
            normalizado,
            flags=re.IGNORECASE,
        ):
            qtd = int(m.group(1))
            unidade = m.group(2).lower()
            if unidade.startswith("h"):
                total_sec += qtd * 3600
            elif unidade.startswith("m"):
                total_sec += qtd * 60
            else:
                total_sec += qtd

    if total_sec <= 0:
        return None

    # Extrair motivo opcional após "pra / para / de / sobre"
    motivo = ""
    m_reason = re.search(
        r"(?:horas?|minutos?|min|segundos?|seg|meia\s+hora|hora\s+e\s+meia)\s+"
        r"(?:pra|para|pro|de|sobre)\s+(.+)$",
        texto.strip(),
        flags=re.IGNORECASE,
    )
    if m_reason:
        motivo = m_reason.group(1).strip().rstrip(".!?")

    return total_sec, motivo


def _default_timer_alert(motivo: str) -> None:
    """
    Alerta sonoro padrão ao disparar um timer:
    Toca o bip de confirmação + fala o aviso em voz alta (com boost ALSA automático).
    """
    play_confirmation(blocking=True)
    if motivo:
        falar(f"Olha só, já deu o tempo que você pediu pra {motivo}!")
    else:
        falar("Atenção! O tempo do seu timer acabou!")


class TimerManager:
    """Controlador thread-safe de timers e lembretes rápidos em memória."""

    def __init__(self, alert_callback: Optional[Callable[[str], None]] = None):
        self._lock = threading.RLock()
        self._timers: Dict[int, Dict[str, Any]] = {}
        self._next_id = 1
        self._alert_callback = alert_callback or _default_timer_alert

    def schedule(self, seconds: int, reason: str = "") -> tuple[int, str]:
        duracao = max(1, min(86400, int(seconds)))
        motivo_limpo = (reason or "").strip()

        with self._lock:
            tid = self._next_id
            self._next_id += 1
            deadline = time.monotonic() + duracao
            timer_obj = threading.Timer(duracao, self._fire, args=(tid,))
            timer_obj.daemon = True
            self._timers[tid] = {
                "id": tid,
                "reason": motivo_limpo,
                "deadline": deadline,
                "duration": duracao,
                "timer": timer_obj,
            }
            timer_obj.start()

        dur_txt = _format_duration_ptbr(duracao)
        logger.info(f"Timer #{tid} agendado para {duracao}s (motivo='{motivo_limpo}')")
        if motivo_limpo:
            msg = f"Combinado! Marquei {dur_txt} aqui pra te avisar de {motivo_limpo}."
        else:
            msg = f"Combinado! Timer de {dur_txt} iniciado."
        return tid, msg

    def _fire(self, timer_id: int) -> None:
        motivo = ""
        with self._lock:
            entry = self._timers.pop(timer_id, None)
            if entry is None:
                return
            motivo = entry.get("reason", "")

        logger.info(f"Disparando Timer #{timer_id} (motivo='{motivo}')!")
        try:
            self._alert_callback(motivo)
        except Exception as e:
            logger.error(f"Erro ao reproduzir alerta do timer #{timer_id}: {e}")

    def cancel_all(self) -> int:
        with self._lock:
            ativos = list(self._timers.values())
            self._timers.clear()
        for entry in ativos:
            try:
                entry["timer"].cancel()
            except Exception:
                pass
        return len(ativos)

    def status_message(self) -> str:
        now = time.monotonic()
        with self._lock:
            ativos = list(self._timers.values())

        if not ativos:
            return "Não tem nenhum timer rodando no momento."

        descricoes: List[str] = []
        for entry in ativos:
            restante = max(1, int(round(entry["deadline"] - now)))
            tempo_txt = _format_duration_ptbr(restante)
            if entry["reason"]:
                descricoes.append(f"{tempo_txt} pra {entry['reason']}")
            else:
                descricoes.append(tempo_txt)

        if len(descricoes) == 1:
            return f"Faltam {descricoes[0]}."
        return "Timers ativos: faltam " + "; e ".join(descricoes) + "."


# Instância global singleton de timers
timer_manager = TimerManager()


def parse_timer_local(
    mensagem: str,
    manager: Optional[TimerManager] = None,
) -> Optional[str]:
    """Trata criação, consulta e cancelamento de timers diretamente no Fast-Path local."""
    if not mensagem:
        return None

    mgr = manager or timer_manager

    if _RE_TIMER_CANCEL.search(mensagem):
        qtd = mgr.cancel_all()
        if qtd == 0:
            return "Não havia nenhum timer ativo pra cancelar."
        if qtd == 1:
            return "Prontinho, cancelei o timer."
        return f"Pronto, cancelei os {qtd} timers ativos."

    if _RE_TIMER_STATUS.search(mensagem):
        return mgr.status_message()

    if _RE_TIMER_CREATE.search(mensagem):
        extraido = _extract_duration_and_reason(mensagem)
        if extraido:
            segundos, motivo = extraido
            _, resposta = mgr.schedule(segundos, motivo)
            return resposta

    return None


# ==============================================================================
# 2. CONSULTA DE MÚSICA ATUAL (NAVIDROME / CURRENT_SONG.JSON)
# ==============================================================================

_RE_MUSIC_QUERY = re.compile(
    r"\b(?:que\s+m[úu]sica\s+(?:est[áa]|t[áa])\s+tocando|"
    r"qual\s+(?:[ée]\s+)?(?:o\s+nome\s+dessa|a)\s+m[úu]sica|"
    r"quem\s+(?:est[áa]|t[áa])\s+cantando|"
    r"qual\s+faixa\s+(?:est[áa]|t[áa])\s+tocando)\b",
    re.IGNORECASE,
)


def get_current_song_response() -> str:
    """Lê o estado atual do player e o arquivo current_song.json de forma segura."""
    if not music_player.is_playing and not os.path.exists(CURRENT_SONG_FILE):
        return "No momento não tem nenhuma música tocando por aqui."

    info: Dict[str, Any] = {}
    if os.path.exists(CURRENT_SONG_FILE):
        try:
            with open(CURRENT_SONG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    info = loaded
        except Exception as e:
            logger.debug(f"Erro ao ler {CURRENT_SONG_FILE}: {e}")

    title = info.get("title")
    artist = info.get("artist")
    album = info.get("album")

    if not music_player.is_playing and not title:
        return "Olha, agora não tem nenhuma música tocando."

    if title and artist and artist.lower() != "desconhecido":
        if album and album.lower() != "desconhecido":
            return f"Olha só, agora tá tocando {title}, de {artist}, do álbum {album}."
        return f"Agora tá tocando {title}, na voz de {artist}."
    if title:
        return f"Agora tá tocando a faixa {title}."
    return "Tem música rolando no player, mas ela está sem título cadastrado."


def parse_music_query_local(mensagem: str) -> Optional[str]:
    """Identifica perguntas sobre a música atual no Fast-Path local."""
    if not mensagem:
        return None
    if _RE_MUSIC_QUERY.search(mensagem):
        return get_current_song_response()
    return None


# ==============================================================================
# 3. REGISTRO DE TOOLS (OPENAI FUNCTION CALLING) PARA ROTEAMENTO HÍBRIDO DA LLM
# ==============================================================================

TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "consultar_clima",
            "description": "Obtém temperatura, sensação térmica, umidade e condição atual do tempo na cidade.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_hora_atual",
            "description": "Retorna o horário atual exato em português.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_musica_atual",
            "description": "Informa qual música e artista estão tocando agora no player local.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "controlar_musica",
            "description": "Inicia, para, avança ou coloca o player de música local em modo contínuo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "acao": {
                        "type": "string",
                        "enum": ["play", "stop", "next", "continuous"],
                        "description": "Ação desejada no player de música.",
                    }
                },
                "required": ["acao"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_estado_casa",
            "description": "Verifica se uma luz/TV específica está ligada ou lista todos os dispositivos ligados na casa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_dispositivo": {
                        "type": "string",
                        "description": "Nome do dispositivo (ex: 'luz da sala') ou 'todos' para listar o que está ligado.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "controlar_dispositivo_casa",
            "description": (
                "Aciona um dispositivo ou automação residencial autorizado. "
                f"Nomes válidos: {', '.join(DEVICE_REGISTRY.keys())}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "acao": {
                        "type": "string",
                        "enum": ["turn_on", "turn_off", "toggle", "set_brightness", "trigger"],
                    },
                    "nome_dispositivo": {
                        "type": "string",
                        "description": "Nome exato do dispositivo na lista autorizada.",
                    },
                    "brilho_pct": {
                        "type": "integer",
                        "description": "Percentual de brilho de 0 a 100 (apenas para set_brightness).",
                    },
                },
                "required": ["acao", "nome_dispositivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_timer",
            "description": "Agenda um timer ou lembrete falado daqui a X segundos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segundos": {
                        "type": "integer",
                        "description": "Duração em segundos até disparar o alerta.",
                    },
                    "motivo": {
                        "type": "string",
                        "description": "Descrição curta do motivo do lembrete (ex: 'desligar o forno').",
                    },
                },
                "required": ["segundos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "salvar_memoria_casa",
            "description": "Guarda permanentemente uma informação, nota, horário de remédio, senha ou recado da família.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fato": {
                        "type": "string",
                        "description": "Informação clara para lembrar futuramente.",
                    },
                    "categoria": {
                        "type": "string",
                        "description": "Categoria opcional (ex: 'saude', 'casa', 'wifi', 'geral').",
                    },
                },
                "required": ["fato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_memoria_casa",
            "description": "Pesquisa informações pessoais ou notas da casa guardadas anteriormente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Termos ou pergunta para buscar na memória da casa.",
                    }
                },
                "required": ["consulta"],
            },
        },
    },
]


def execute_tool_call(tool_name: str, raw_arguments: Any) -> str:
    """
    Executa de forma segura uma ferramenta solicitada pela LLM e retorna string de resultado.
    Todas as chamadas residenciais passam obrigatoriamente pela whitelist do DEVICE_REGISTRY.
    """
    if isinstance(raw_arguments, str):
        try:
            args = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except Exception:
            args = {}
    elif isinstance(raw_arguments, dict):
        args = raw_arguments
    else:
        args = {}

    logger.info(f"Executando Tool Call da LLM: {tool_name}({args})")

    try:
        if tool_name == "consultar_clima":
            return get_weather_response("previsão do tempo") or "Clima indisponível."

        elif tool_name == "consultar_hora_atual":
            return format_time_ptbr(datetime.now())

        elif tool_name == "consultar_musica_atual":
            return get_current_song_response()

        elif tool_name == "controlar_musica":
            acao = str(args.get("acao", "play")).lower().strip()
            if acao == "stop":
                return music_player.stop()
            elif acao == "next":
                _, msg = music_player.next_music()
                return msg
            elif acao == "continuous":
                _, msg = music_player.start_continuous_play()
                return msg
            else:
                _, msg = music_player.play_random_music()
                return msg

        elif tool_name == "consultar_estado_casa":
            alvo = str(args.get("nome_dispositivo", "")).strip()
            if not alvo or alvo.lower() in ("todos", "todas", "casa", "tudo"):
                return listar_dispositivos_ligados_ha()
            return consultar_estado_dispositivo_ha(alvo)

        elif tool_name == "controlar_dispositivo_casa":
            acao = str(args.get("acao", "")).strip()
            alvo = str(args.get("nome_dispositivo", "")).strip()
            params: Dict[str, Any] = {}
            if "brilho_pct" in args and args["brilho_pct"] is not None:
                params["brightness_pct"] = args["brilho_pct"]

            comando = resolver_comando(
                {"action": acao, "target_name": alvo, "parameters": params}
            )
            ok, msg = executar_comando_ha(comando)
            if ok and comando.get("target_name"):
                conversation_memory.record_ha_target(comando["target_name"])
            return f"Sucesso: {msg}" if ok else f"Falha: {msg}"

        elif tool_name == "agendar_timer":
            segundos = int(args.get("segundos", 60))
            motivo = str(args.get("motivo", "")).strip()
            _, msg = timer_manager.schedule(segundos, motivo)
            return msg

        elif tool_name == "salvar_memoria_casa":
            fato = str(args.get("fato", "")).strip()
            cat = str(args.get("categoria", "geral")).strip() or "geral"
            if not fato:
                return "Nenhum fato informado para salvar."
            memory_store.add_memory(fato, category=cat)
            return f"Memória salva com sucesso: {fato}"

        elif tool_name == "buscar_memoria_casa":
            consulta = str(args.get("consulta", "")).strip()
            achados = memory_store.search(consulta)
            if not achados:
                return "Nenhuma memória encontrada sobre esse assunto."
            return "Memórias encontradas: " + " | ".join(achados)

        return f"Ferramenta '{tool_name}' não reconhecida."
    except Exception as e:
        logger.error(f"Erro ao executar tool '{tool_name}': {e}")
        return f"Erro ao executar ferramenta {tool_name}."
