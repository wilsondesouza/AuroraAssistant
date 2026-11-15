import os
import re
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

# Diretórios base
REFATORED_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REFATORED_DIR.parent

# 1. Carregar .env na raiz do projeto (se existir)
root_env = PROJECT_ROOT / ".env"
if root_env.exists():
    load_dotenv(dotenv_path=root_env)

# 2. Carregar chaves do gTTS/OpenRouter/HA
keys_env = PROJECT_ROOT / "config" / "gTTS" / "keys.env"
if keys_env.exists():
    load_dotenv(dotenv_path=keys_env)

# 3. Carregar configurações do Navidrome
navidrome_env_parent = PROJECT_ROOT.parent / "AuroraMusic" / "navidrome.env"
navidrome_env_local = PROJECT_ROOT / "navidrome.env"
if navidrome_env_parent.exists():
    load_dotenv(dotenv_path=navidrome_env_parent)
elif navidrome_env_local.exists():
    load_dotenv(dotenv_path=navidrome_env_local)

# 4. Configurar credenciais do Google Cloud TTS
default_gcp_creds = PROJECT_ROOT / "config" / "gTTS" / "gtts-file.json"
if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and default_gcp_creds.exists():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(default_gcp_creds)

# ==========================================
# CONFIGURAÇÕES DE SERVIÇOS EXTERNOS
# ==========================================

# LLM (Provedor Pluggável: openrouter, groq, gemini, cerebras, ollama, custom)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").lower().strip()
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_FALLBACK_PROVIDER = os.getenv("LLM_FALLBACK_PROVIDER", "").lower().strip()

# Chaves específicas de provedores (retrocompatibilidade)
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY") or LLM_API_KEY
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")

# Modelos
MODEL_CONVERSA = os.getenv("MODEL_CONVERSA", "meta-llama/llama-3.3-70b-instruct:free")
MODEL_CLASSIFICADOR = os.getenv("MODEL_CLASSIFICADOR", "meta-llama/llama-3.2-3b-instruct:free")
MODEL_HA = os.getenv("MODEL_HA", "google/gemma-3-12b-it:free")

# Home Assistant
HA_URL = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_TIMEOUT = int(os.getenv("HA_TIMEOUT", "8"))
HEADERS_HA = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

# Navidrome / Subsonic
NAVIDROME_API_URL = (os.getenv("NAVIDROME_API_URL") or "").rstrip("/")
NAVIDROME_USER = os.getenv("NAVIDROME_USER", "")
NAVIDROME_PASSWORD = os.getenv("NAVIDROME_PASSWORD", "")
NAVIDROME_TIMEOUT = int(os.getenv("NAVIDROME_TIMEOUT", "10"))

# OpenWeather
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "")
OPENWEATHER_CITY = os.getenv("OPENWEATHER_CITY", "Nilópolis")
OPENWEATHER_TIMEOUT = int(os.getenv("OPENWEATHER_TIMEOUT", "8"))

# Síntese de Voz (TTS Pluggável: google, elevenlabs, openrouter)
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "google").lower().strip()
TTS_FALLBACK_PROVIDER = os.getenv("TTS_FALLBACK_PROVIDER", "").lower().strip()
TTS_FALLBACK_PROVIDERS = os.getenv("TTS_FALLBACK_PROVIDERS", "").strip()
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", "15"))

# Estilo de fala / prosódia na geração de respostas da LLM ("expressive_rj" ou "neutral")
AURORA_SPEECH_STYLE = os.getenv("AURORA_SPEECH_STYLE", "expressive_rj").lower().strip()

# Google Cloud TTS (ex: pt-BR-Chirp3-HD-Erinome)
TTS_VOICE_NAME = os.getenv("TTS_VOICE_NAME", "pt-BR-Chirp3-HD-Erinome")
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "pt-BR")

# ElevenLabs TTS
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "Xb7hH8MSUJpSbSDYk0k2").strip()
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128").strip()
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.38"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.40"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower().strip() in (
    "1", "true", "yes", "on"
)

# OpenRouter TTS (/api/v1/audio/speech)
OPENROUTER_TTS_API_KEY = (os.getenv("OPENROUTER_TTS_API_KEY") or OPENROUTER_KEY or "").strip()
OPENROUTER_TTS_URL = os.getenv(
    "OPENROUTER_TTS_URL",
    "https://openrouter.ai/api/v1/audio/speech",
).strip()
OPENROUTER_TTS_MODEL = os.getenv(
    "OPENROUTER_TTS_MODEL",
    "openai/gpt-4o-mini-tts-2025-12-15",
).strip()
OPENROUTER_TTS_VOICE = os.getenv("OPENROUTER_TTS_VOICE", "coral").strip()
OPENROUTER_TTS_SPEED = float(os.getenv("OPENROUTER_TTS_SPEED", "1.0"))
OPENROUTER_TTS_INSTRUCTIONS = os.getenv(
    "OPENROUTER_TTS_INSTRUCTIONS",
    (
        "Fale em português brasileiro natural do Rio de Janeiro, com sotaque carioca leve, "
        "caloroso e espontâneo. Use ritmo conversacional humano, pequenas variações de tom "
        "e atuação sutil em trechos entre aspas, faça uma pausa expressiva nos travessões e "
        "capriche na entonação ascendente e simpática nas perguntas finais."
    ),
).strip()

# Controle de Volume ALSA durante o TTS
TTS_VOLUME_LEVEL = int(os.getenv("TTS_VOLUME_LEVEL", "100"))
if not 0 <= TTS_VOLUME_LEVEL <= 100:
    raise ValueError("TTS_VOLUME_LEVEL deve estar entre 0 e 100.")
TTS_VOLUME_CONTROL = os.getenv("TTS_VOLUME_CONTROL", "Master").strip()
if not TTS_VOLUME_CONTROL:
    raise ValueError("TTS_VOLUME_CONTROL não pode estar vazio.")
TTS_VOLUME_CARD = os.getenv("TTS_VOLUME_CARD", "").strip()

# Dispositivo e Driver de Saída de Áudio (ALSA / PulseAudio / mpg123)
AUDIO_OUTPUT_DRIVER = os.getenv("AUDIO_OUTPUT_DRIVER", "").strip()  # ex: 'alsa', 'pulse'
AUDIO_OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "").strip()  # ex: 'default', 'hw:1,0', 'plughw:1,0'

# Áudios e Arquivos
MUSIC_DIR = PROJECT_ROOT / "config" / "music"
CONFIRMATION_SOUND = str(MUSIC_DIR / "confirmation.mp3")
ERROR_SOUND = str(MUSIC_DIR / "error.mp3")
FALHA_TTS_SOUND = str(MUSIC_DIR / "falha_tts.wav")
PLAYLIST_FILE = str(MUSIC_DIR / "music_playlist.json")
LEGACY_PLAYLIST_FILE = str(MUSIC_DIR / "music_playlist.txt")
CURRENT_SONG_FILE = str(MUSIC_DIR / "current_song.json")
SMARTLUME_STATUS_FILE = os.getenv(
    "SMARTLUME_STATUS_FILE",
    str(PROJECT_ROOT.parent.parent / "SmartLume" / "ultima_musica.json"),
)


# Reconhecimento de Voz
WAKE_WORD = os.getenv("WAKE_WORD", "aurora").lower()


# ==========================================
# LOGGING E SANITIZAÇÃO
# ==========================================

def sanitize_for_log(text: str) -> str:
    """Remove tokens, senhas e chaves sensíveis de mensagens para log."""
    if not text:
        return ""
    # Ocultar valores de senha ou token em URLs
    cleaned = re.sub(r'([?&](?:p|password|t|token|key|appid)=)[^&]+', r'\1***', text, flags=re.IGNORECASE)
    # Ocultar Authorization Bearer
    cleaned = re.sub(r'(Bearer\s+)[A-Za-z0-9\-_.]+', r'\1***', cleaned, flags=re.IGNORECASE)
    # Ocultar xi-api-key (ElevenLabs) caso apareça em headers serializados
    cleaned = re.sub(r'(xi-api-key["\']?\s*[:=]\s*["\']?)[A-Za-z0-9\-_.]+', r'\1***', cleaned, flags=re.IGNORECASE)
    return cleaned

def setup_logging(level=logging.INFO):
    """Configura logging formatado e padronizado para todo o assistente."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=log_format, datefmt=date_format)
    # Reduz ruído de bibliotecas terceiras
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

def validate_config() -> dict:
    """Valida as configurações carregadas e retorna status de cada serviço."""
    has_llm = bool(
        LLM_API_KEY
        or OPENROUTER_KEY
        or GROQ_API_KEY
        or GEMINI_API_KEY
        or CEREBRAS_API_KEY
        or LLM_PROVIDER == "ollama"
    )
    has_google_tts = bool(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        and Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).exists()
    )
    has_elevenlabs_tts = bool(os.getenv("ELEVENLABS_API_KEY") or ELEVENLABS_API_KEY)
    has_openrouter_tts = bool(
        os.getenv("OPENROUTER_TTS_API_KEY")
        or os.getenv("OPENROUTER_KEY")
        or OPENROUTER_TTS_API_KEY
    )

    tts_provider_norm = (os.getenv("TTS_PROVIDER", TTS_PROVIDER) or "google").lower().strip()
    if tts_provider_norm in ("google", "gtts", "gcp", "chirp", "chirp3"):
        active_tts_ok = has_google_tts
    elif tts_provider_norm in ("elevenlabs", "eleven", "11labs"):
        active_tts_ok = has_elevenlabs_tts
    elif tts_provider_norm in ("openrouter", "or"):
        active_tts_ok = has_openrouter_tts
    else:
        active_tts_ok = False

    status = {
        f"llm ({LLM_PROVIDER})": has_llm,
        "home_assistant": bool(HA_TOKEN and HA_URL),
        "navidrome": bool(NAVIDROME_API_URL and NAVIDROME_USER and NAVIDROME_PASSWORD),
        "openweather": bool(OPENWEATHER_KEY),
        f"tts ({tts_provider_norm})": active_tts_ok,
        "google_tts": has_google_tts,
        "elevenlabs_tts": has_elevenlabs_tts,
        "openrouter_tts": has_openrouter_tts,
    }
    return status
