import os
import re
import sys
import queue
import logging
import tempfile
import subprocess
import threading
import shutil
from contextlib import contextmanager
from typing import Generator, Iterable

from refatored.config import (
    CONFIRMATION_SOUND,
    ERROR_SOUND,
    FALHA_TTS_SOUND,
    TTS_VOLUME_LEVEL,
    TTS_VOLUME_CONTROL,
    TTS_VOLUME_CARD,
    AUDIO_OUTPUT_DRIVER,
    AUDIO_OUTPUT_DEVICE,
)
from refatored.tts_client import (
    TTSClient,
    tts_client,
    prepare_text_for_speech,
)

logger = logging.getLogger(__name__)
_tts_volume_lock = threading.RLock()


def _build_mpg123_command(target: str) -> list[str]:
    """Monta a linha de comando do mpg123 respeitando drivers e dispositivos configurados."""
    cmd = ["mpg123"]
    if AUDIO_OUTPUT_DRIVER:
        cmd.extend(["-o", AUDIO_OUTPUT_DRIVER])
    if AUDIO_OUTPUT_DEVICE:
        cmd.extend(["-a", AUDIO_OUTPUT_DEVICE])
    cmd.append(target)
    return cmd


def _build_aplay_command(target: str) -> list[str]:
    """Monta a linha de comando do aplay (ALSA) para arquivos WAV."""
    cmd = ["aplay", "-q"]
    if AUDIO_OUTPUT_DEVICE and AUDIO_OUTPUT_DRIVER in ("", "alsa"):
        cmd.extend(["-D", AUDIO_OUTPUT_DEVICE])
    cmd.append(target)
    return cmd


# ==========================================
# REPRODUÇÃO DE ÁUDIO (SONS DE FEEDBACK)
# ==========================================

@contextmanager
def _temporarily_boost_tts_volume() -> Generator[None, None, None]:
    """Aumenta temporariamente o mixer ALSA durante a reprodução do TTS."""
    with _tts_volume_lock:
        mixer = shutil.which("amixer")
        if not mixer:
            logger.debug("amixer indisponível; o volume do TTS não será alterado.")
            yield
            return

        cmd_base = [mixer]
        if TTS_VOLUME_CARD:
            cmd_base.extend(["-c", TTS_VOLUME_CARD])

        try:
            current = subprocess.run(
                [*cmd_base, "get", TTS_VOLUME_CONTROL],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Não foi possível consultar o volume ALSA: %s", exc)
            yield
            return

        if current.returncode != 0:
            logger.warning(
                "Não foi possível consultar o controle ALSA '%s': %s",
                TTS_VOLUME_CONTROL,
                current.stderr.strip(),
            )
            yield
            return

        match = re.search(r"\[(\d{1,3})%\]", current.stdout)
        if not match:
            logger.warning(
                "Não foi possível identificar o volume atual do controle ALSA '%s'.",
                TTS_VOLUME_CONTROL,
            )
            yield
            return

        original_volume = int(match.group(1))
        mute_match = re.search(r"\[(on|off)\]", current.stdout, re.IGNORECASE)
        was_muted = bool(mute_match and mute_match.group(1).lower() == "off")
        if original_volume >= TTS_VOLUME_LEVEL:
            if not was_muted:
                yield
                return

        try:
            set_volume = [
                *cmd_base,
                "set",
                TTS_VOLUME_CONTROL,
                f"{TTS_VOLUME_LEVEL}%",
            ]
            if was_muted:
                set_volume.append("unmute")
            changed = subprocess.run(
                set_volume,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Não foi possível aumentar o volume ALSA: %s", exc)
            yield
            return

        if changed.returncode != 0:
            logger.warning(
                "Não foi possível aumentar o volume do controle ALSA '%s': %s",
                TTS_VOLUME_CONTROL,
                changed.stderr.strip(),
            )
            yield
            return

        try:
            yield
        finally:
            try:
                restored = subprocess.run(
                    [*cmd_base, "set", TTS_VOLUME_CONTROL, f"{original_volume}%"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if restored.returncode != 0:
                    logger.error(
                        "Não foi possível restaurar o volume ALSA do controle '%s': %s",
                        TTS_VOLUME_CONTROL,
                        restored.stderr.strip(),
                    )
                elif was_muted:
                    remuted = subprocess.run(
                        [*cmd_base, "set", TTS_VOLUME_CONTROL, "mute"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    if remuted.returncode != 0:
                        logger.error(
                            "Não foi possível restaurar o estado mudo do controle ALSA '%s': %s",
                            TTS_VOLUME_CONTROL,
                            remuted.stderr.strip(),
                        )
            except (OSError, subprocess.SubprocessError) as exc:
                logger.error("Erro ao restaurar o volume ALSA: %s", exc)


def play_audio_file(caminho: str, blocking: bool = False) -> bool:
    """
    Reproduz arquivo de áudio local usando player disponível no sistema.
    Se blocking=False, roda em thread separada.
    """
    if not caminho or not os.path.exists(caminho):
        logger.warning(f"Arquivo de áudio não encontrado: '{caminho}'")
        return False

    def _play() -> bool:
        is_wav = caminho.lower().endswith(".wav")
        players = []
        if is_wav and shutil.which("aplay"):
            players.append(("aplay", _build_aplay_command(caminho)))
        if not is_wav and shutil.which("mpg123"):
            players.append(("mpg123", _build_mpg123_command(caminho)))
        if shutil.which("ffplay"):
            players.append(
                ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", caminho])
            )
        if shutil.which("vlc"):
            players.append(
                ("vlc", ["vlc", "--intf", "dummy", "--play-and-exit", caminho])
            )

        for player, command in players:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as error:
                logger.warning("Não foi possível reproduzir com %s: %s", player, error)
                continue
            if result.returncode == 0:
                return True
            logger.warning(
                "%s falhou (código %s): %s",
                player,
                result.returncode,
                result.stderr.strip() or "erro desconhecido",
            )

        if players:
            return False

        try:
            if sys.platform.startswith("win"):
                os.startfile(caminho)
                return True
            if shutil.which("xdg-open"):
                result = subprocess.run(
                    ["xdg-open", caminho],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0:
                    return True
                logger.warning("xdg-open falhou (código %s): %s", result.returncode, result.stderr.strip())
                return False
            logger.error("Nenhum reprodutor de áudio disponível para '%s'.", caminho)
            return False
        except (OSError, subprocess.SubprocessError) as error:
            logger.error("Erro ao reproduzir áudio '%s': %s", caminho, error)
            return False

    if blocking:
        return _play()
    else:
        threading.Thread(target=_play, daemon=True).start()
        return True


def play_confirmation(blocking: bool = False):
    """Toca o som de confirmação; permite aguardar antes de abrir o microfone."""
    play_audio_file(CONFIRMATION_SOUND, blocking=blocking)


def play_error():
    """Toca som de erro/falha."""
    play_audio_file(ERROR_SOUND, blocking=True)
    
def play_falha_tts():
    """Toca som de falha na síntese de voz."""
    play_audio_file(FALHA_TTS_SOUND, blocking=True)


# ==========================================
# SÍNTESE DE VOZ (TTS PLUGGÁVEL COM FALLBACK)
# ==========================================

def clean_text_for_speech(texto: str) -> str:
    """
    Prepara texto para síntese de voz: remove Markdown/emojis e preserva
    pontuação prosódica (travessões '—', reticências '...', aspas, '!' e '?')
    além de expandir unidades/horários abreviados em português brasileiro.
    """
    return prepare_text_for_speech(texto)


def _play_synthesized_bytes(audio_bytes: bytes, ext: str = ".mp3") -> bool:
    """Salva bytes de áudio sintetizado em arquivo temporário seguro, reproduz e limpa."""
    if not audio_bytes:
        return False

    suffix = ext if ext.startswith(".") else f".{ext}"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            temp_path = f.name
            f.write(audio_bytes)

        return play_audio_file(temp_path, blocking=True)
    except Exception as e:
        logger.error(f"Erro ao gravar/reproduzir áudio temporário de TTS: {e}")
        return False
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


class GoogleCloudTTS:
    """
    Adaptador retrocompatível específico do Google Cloud Text-to-Speech,
    delegando para o cliente pluggável TTSClient.
    """

    def __init__(self, client: TTSClient | None = None):
        self._tts_client = client or tts_client

    def synthesize_and_play(self, texto: str) -> bool:
        """Sintetiza texto especificamente via Google TTS e reproduz."""
        resultado = self._tts_client.sintetizar(texto, provider_override="google")
        if not resultado:
            return False
        audio_bytes, ext, _ = resultado
        return _play_synthesized_bytes(audio_bytes, ext=ext)


class TextToSpeechManager:
    """
    Gerenciador central de TTS multi-provedor (Google Chirp3-HD, ElevenLabs, OpenRouter)
    com cadeia de fallback configurável via .env e áudio estático de contingência final.
    """

    def __init__(self, client: TTSClient | None = None):
        self.client = client or tts_client
        self.gcp_tts = GoogleCloudTTS(self.client)

    def synthesize_and_play(self, texto: str, provider_override: str | None = None) -> bool:
        """Sintetiza usando o provedor ativo (e seus fallbacks) e reproduz."""
        resultado = self.client.sintetizar(texto, provider_override=provider_override)
        if not resultado:
            return False
        audio_bytes, ext, used_provider = resultado
        logger.debug(f"Reproduzindo fala sintetizada via [{used_provider.upper()}] ({ext})...")
        return _play_synthesized_bytes(audio_bytes, ext=ext)

    def falar(self, texto: str, provider_override: str | None = None):
        """
        Sintetiza e reproduz a fala com aumento temporário de volume ALSA;
        se todos os provedores de TTS falharem, reproduz o áudio estático de erro.
        """
        if not texto or not texto.strip():
            return

        with _temporarily_boost_tts_volume():
            if not self.synthesize_and_play(texto, provider_override=provider_override):
                logger.error(
                    "Todos os provedores de TTS falharam; reproduzindo áudio estático de contingência."
                )
                play_falha_tts()

    def falar_em_stream(
        self,
        frases_iter: Iterable[str],
        provider_override: str | None = None,
    ) -> str:
        """
        Pipeline produtor-consumidor de baixa latência (Sentence-Level Streaming):
        Enquanto a frase N está tocando no alto-falante, uma thread em background já
        sintetiza o áudio da frase N+1 no TTS, eliminando o silêncio entre frases
        e mantendo o boost ALSA contínuo durante toda a resposta.
        Retorna o texto completo concatenado que foi gerado.
        """
        fila_audio: queue.Queue = queue.Queue(maxsize=3)
        frases_coletadas: list[str] = []

        def _producer():
            try:
                for frase in frases_iter:
                    trecho = (frase or "").strip()
                    if not trecho:
                        continue
                    frases_coletadas.append(trecho)
                    sintese = self.client.sintetizar(
                        trecho, provider_override=provider_override
                    )
                    fila_audio.put((trecho, sintese))
            except Exception as exc:
                logger.error(f"Erro no produtor de streaming TTS: {exc}")
            finally:
                fila_audio.put(None)

        worker = threading.Thread(target=_producer, daemon=True)
        worker.start()

        primeiro_item = fila_audio.get()
        if primeiro_item is None:
            worker.join(timeout=1.0)
            return ""

        falha_acionada = False
        with _temporarily_boost_tts_volume():
            item = primeiro_item
            while item is not None:
                _, sintese = item
                ok = False
                if sintese is not None:
                    audio_bytes, ext, used_prov = sintese
                    logger.debug(
                        f"Streaming TTS reproduzindo trecho via [{used_prov.upper()}] ({ext})..."
                    )
                    ok = _play_synthesized_bytes(audio_bytes, ext=ext)
                if not ok and not falha_acionada:
                    logger.error(
                        "Falha ao sintetizar/reproduzir trecho em streaming; tocando contingência."
                    )
                    play_falha_tts()
                    falha_acionada = True
                item = fila_audio.get()

        worker.join(timeout=2.0)
        return " ".join(frases_coletadas).strip()


# Instância global singleton
tts_manager = TextToSpeechManager()


def falar(texto: str):
    """Função utilitária global para fala da Aurora."""
    tts_manager.falar(texto)


def falar_em_stream(frases_iter: Iterable[str]) -> str:
    """Função utilitária global para fala em streaming por frases completas."""
    return tts_manager.falar_em_stream(frases_iter)
