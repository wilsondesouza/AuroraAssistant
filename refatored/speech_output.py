import os
import re
import sys
import logging
import tempfile
import subprocess
import threading
import shutil
from contextlib import contextmanager
from typing import Generator

from refatored.config import (
    CONFIRMATION_SOUND,
    ERROR_SOUND,
    FALHA_TTS_SOUND,
    TTS_VOICE_NAME,
    TTS_LANGUAGE_CODE,
    TTS_VOLUME_LEVEL,
    TTS_VOLUME_CONTROL,
    TTS_VOLUME_CARD,
    AUDIO_OUTPUT_DRIVER,
    AUDIO_OUTPUT_DEVICE,
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
        players = []
        if shutil.which("mpg123"):
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
# SÍNTESE DE VOZ (TTS)
# ==========================================

def clean_text_for_speech(texto: str) -> str:
    """Remove caracteres Markdown, formatação e símbolos que prejudicam a fala."""
    if not texto:
        return ""
    # Remove marcações Markdown
    t = re.sub(r'[*_#`~\[\]\(\)\{\}]', '', texto)
    t = re.sub(r'[-–—]\s+', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


class GoogleCloudTTS:
    """Motor de síntese de voz usando Google Cloud Text-to-Speech."""

    def __init__(self):
        self._client = None
        self._initialized = False

    def _ensure_client(self):
        if not self._initialized:
            try:
                from google.cloud import texttospeech
                self._client = texttospeech.TextToSpeechClient()
                self._texttospeech = texttospeech
                self._initialized = True
                logger.info("Google Cloud TTS inicializado com sucesso.")
            except Exception as e:
                logger.error(f"Não foi possível inicializar Google Cloud TTS: {e}")
                self._client = None
                self._initialized = True

    def synthesize_and_play(self, texto: str) -> bool:
        """Sintetiza texto com Google TTS e reproduz."""
        self._ensure_client()
        if self._client is None:
            return False

        texto_limpo = clean_text_for_speech(texto)
        if not texto_limpo:
            return False

        temp_path = None
        try:
            tts = self._texttospeech
            synthesis_input = tts.SynthesisInput(text=texto_limpo)
            voice = tts.VoiceSelectionParams(
                language_code=TTS_LANGUAGE_CODE,
                name=TTS_VOICE_NAME
            )
            audio_config = tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3)

            logger.info(f"Sintetizando voz (Google TTS, voz={TTS_VOICE_NAME}): '{texto_limpo[:60]}...'")
            response = self._client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )

            # Gravar em arquivo temporário com limpeza garantida
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name
                f.write(response.audio_content)

            # Reproduz de forma bloqueante para sincronizar a fala com a resposta
            return play_audio_file(temp_path, blocking=True)

        except Exception as e:
            logger.error(f"Erro na síntese com Google Cloud TTS: {e}")
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass


class TextToSpeechManager:
    """Gerenciador central de TTS com fallback de áudio estático."""

    def __init__(self):
        self.gcp_tts = GoogleCloudTTS()

    def falar(self, texto: str):
        """Tenta usar Google Cloud TTS; se falhar, reproduz o áudio estático de erro."""
        if not texto or not texto.strip():
            return

        with _temporarily_boost_tts_volume():
            if not self.gcp_tts.synthesize_and_play(texto):
                logger.error("Google Cloud TTS indisponível; reproduzindo fala gravada.")
                play_falha_tts()


# Instância global singleton
tts_manager = TextToSpeechManager()

def falar(texto: str):
    """Função utilitária global para fala da Aurora."""
    tts_manager.falar(texto)
