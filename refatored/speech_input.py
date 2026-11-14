import os
import re
import sys
import logging
import tempfile

from refatored.config import (
    WAKE_WORD,
)

logger = logging.getLogger(__name__)

# Regex para wake word com limites de palavra
RE_WAKE_WORD = re.compile(rf'\b{re.escape(WAKE_WORD)}\b', re.IGNORECASE)

# Handler C persistente para evitar garbage collection
_c_alsa_error_handler = None


def suppress_alsa_errors():
    """Opcionalmente silencia mensagens da biblioteca C do ALSA no Linux."""
    global _c_alsa_error_handler
    if (
        not sys.platform.startswith("linux")
        or os.getenv("SUPPRESS_ALSA_ERRORS", "").strip().lower()
        not in {"1", "true", "yes"}
    ):
        return

    try:
        import ctypes
        ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(
            None,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p
        )

        def _null_error_handler(filename, line, function, err, fmt):
            del filename, line, function, err, fmt

        _c_alsa_error_handler = ERROR_HANDLER_FUNC(_null_error_handler)
        asound = ctypes.cdll.LoadLibrary("libasound.so.2")
        asound.snd_lib_error_set_handler(_c_alsa_error_handler)
        logger.warning(
            "Mensagens da biblioteca C do ALSA estão silenciadas por configuração; "
            "isso também pode ocultar erros reais de áudio."
        )
    except Exception as exc:
        logger.debug("Não foi possível registrar o silenciador do ALSA: %s", exc)


# Ativar supressão assim que o módulo for carregado
suppress_alsa_errors()


class SpeechInputManager:
    """Gerenciador de entrada de voz, microfone e transcrição local Whisper."""

    def __init__(self):
        self._recognizer = None
        self._whisper_model = None
        self._sr_module = None
        self._initialized = False

    def initialize(self) -> bool:
        """Inicializa módulos de áudio e modelo Whisper."""
        try:
            import speech_recognition as sr
            self._sr_module = sr
            self._recognizer = sr.Recognizer()

            # Configurações otimizadas do recognizer para baixa latência
            self._recognizer.energy_threshold = 3500
            self._recognizer.dynamic_energy_threshold = False
            self._recognizer.pause_threshold = 0.5
            self._recognizer.non_speaking_duration = 0.3
            self._recognizer.phrase_threshold = 0.2
        except ImportError:
            logger.error("speech_recognition não instalado.")
            return False

        self._initialized = True
        return True

    def calibrate_ambient_noise(self, duration: float = 0.6):
        """Calibra ruído de fundo do ambiente uma única vez na inicialização."""
        if not self._recognizer or not self._sr_module:
            return

        try:
            logger.info("Calibrando ruído ambiente do microfone...")
            with self._sr_module.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=duration)
            logger.info("Calibração de ruído ambiente concluída.")
        except Exception as e:
            logger.warning(f"Não foi possível calibrar ruído ambiente: {e}")

    def transcribe_audio(self, audio_data) -> str:
        """
        Transcreve o áudio gravado.
        CORREÇÃO CRÍTICA: Garante que arquivos temporários são SEMPRE excluídos em bloco finally.
        """
        if self._whisper_model:
            temp_path = None
            try:
                # Criar arquivo temporário de forma segura
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    temp_path = f.name
                    f.write(audio_data.get_wav_data())

                segments, _ = self._whisper_model.transcribe(
                    temp_path,
                    language="pt",
                    beam_size=1
                )
                texto = " ".join([seg.text for seg in segments]).strip()
                return texto
            except Exception as e:
                logger.error(f"Erro na transcrição Whisper: {e}")
                raise
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
        else:
            # Fallback Google Speech
            try:
                return self._recognizer.recognize_google(audio_data, language="pt-BR").strip()
            except Exception as e:
                logger.debug(f"Erro no Google Speech fallback: {e}")
                raise

    def aguardar_ativacao(self, timeout: float = 5, phrase_time_limit: float = 2.5) -> bool:
        """Escuta continuamente aguardando a palavra de ativação ('aurora')."""
        if not self._initialized:
            self.initialize()

        sr = self._sr_module
        if not sr or not self._recognizer:
            return False

        try:
            with sr.Microphone() as source:
                try:
                    audio = self._recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit
                    )
                except sr.WaitTimeoutError:
                    return False
        except Exception as e:
            logger.debug(f"Erro ao abrir microfone para ativação: {e}")
            return False

        try:
            texto = self.transcribe_audio(audio)
            if texto:
                logger.debug(f"Texto detectado na escuta de ativação: '{texto}'")
                if RE_WAKE_WORD.search(texto):
                    logger.info("Wake word 'aurora' reconhecida!")
                    return True
        except Exception:
            return False

        return False

    def escutar_comando(self, timeout: float = 6, phrase_time_limit: float = 8) -> str:
        """Escuta o comando do usuário após a detecção da palavra de ativação."""
        if not self._initialized:
            self.initialize()

        sr = self._sr_module
        if not sr or not self._recognizer:
            return ""

        try:
            with sr.Microphone() as source:
                try:
                    audio = self._recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit
                    )
                except sr.WaitTimeoutError:
                    logger.debug("Timeout aguardando comando do usuário.")
                    return ""
        except Exception as e:
            logger.error(f"Erro ao abrir microfone para escutar comando: {e}")
            return ""

        try:
            texto = self.transcribe_audio(audio)
            logger.info(f"Comando transcrito: '{texto}'")
            return texto
        except sr.UnknownValueError:
            logger.debug("Não foi possível decodificar o áudio.")
            return ""
        except sr.RequestError as e:
            logger.error(f"Erro no serviço de reconhecimento de voz: {e}")
            return ""
        except Exception as e:
            logger.error(f"Erro ao transcrever comando: {e}")
            return ""


# Instância global singleton
speech_input = SpeechInputManager()
