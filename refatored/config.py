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
HA_CA_BUNDLE = os.getenv("HA_CA_BUNDLE", "").strip()  # PEM público exclusivo deste cliente HA
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


# Reconhecimento de Voz & Conversa Contínua (Follow-up sem Wake Word)
WAKE_WORD = os.getenv("WAKE_WORD", "aurora").lower()

# Privacidade de logs: grava o TEXTO da fala do usuário apenas se explicitamente ativado
LOG_TRANSCRIPTS = os.getenv("AURORA_LOG_TRANSCRIPTS", "false").lower().strip() in (
    "1", "true", "yes", "on"
)

# Motor de STT. Default 'google' preserva o comportamento atual (SpeechRecognition),
CONTINUOUS_CONVERSATION = os.getenv("CONTINUOUS_CONVERSATION", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
CONTINUOUS_MAX_TURNS = max(1, int(os.getenv("CONTINUOUS_MAX_TURNS", "3")))
CONTINUOUS_LISTEN_TIMEOUT = float(os.getenv("CONTINUOUS_LISTEN_TIMEOUT", "5.0"))

# Memória de Curto Prazo (Janela de Contexto Deslizante com Expiração)
CONVERSATION_HISTORY_TURNS = max(1, int(os.getenv("CONVERSATION_HISTORY_TURNS", "3")))
CONVERSATION_TTL_SECONDS = max(15, int(os.getenv("CONVERSATION_TTL_SECONDS", "180")))

# Memória de Longo Prazo da Casa / Mini-RAG em SQLite + Embeddings Gemini Opcionais
MEMORY_DB_PATH = os.getenv(
    "MEMORY_DB_PATH",
    str(PROJECT_ROOT / "config" / "memory" / "aurora_memory.db"),
).strip()
MEMORY_TOP_K = max(1, int(os.getenv("MEMORY_TOP_K", "3")))
MEMORY_USE_EMBEDDINGS = os.getenv("MEMORY_USE_EMBEDDINGS", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").strip()

# Busca na Web em Tempo Real / Grounding Pluggável (auto, serper, tavily, free)
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "auto").lower().strip()
WEB_SEARCH_FALLBACK_PROVIDERS = os.getenv(
    "WEB_SEARCH_FALLBACK_PROVIDERS", "serper,tavily,free"
).strip()
WEB_SEARCH_MAX_RESULTS = max(1, min(6, int(os.getenv("WEB_SEARCH_MAX_RESULTS", "4"))))
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "6"))
# Orçamento TOTAL de tempo por pesquisa (todos os provedores somados).
WEB_SEARCH_TOTAL_DEADLINE = float(os.getenv("WEB_SEARCH_TOTAL_DEADLINE", "7.0"))
# Tamanho máximo aceito de uma resposta HTTP de buscador/RSS (proteção de RAM no H6).
WEB_SEARCH_MAX_BYTES = int(os.getenv("WEB_SEARCH_MAX_BYTES", str(2 * 1024 * 1024)))
# Filtro de conteúdo: evita que resultados impróprios sejam falados para crianças/idosos.
WEB_SEARCH_SAFE = os.getenv("WEB_SEARCH_SAFE", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# Capacidades Avançadas de LLM (Structured Output, Tool Calling & Streaming TTS)
LLM_USE_JSON_MODE = os.getenv("LLM_USE_JSON_MODE", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
LLM_ENABLE_TOOLS = os.getenv("LLM_ENABLE_TOOLS", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
LLM_TOOL_MAX_STEPS = min(3, max(1, int(os.getenv("LLM_TOOL_MAX_STEPS", "2"))))
LLM_STREAM_TTS = os.getenv("LLM_STREAM_TTS", "true").lower().strip() in (
    "1", "true", "yes", "on"
)
LLM_STREAM_MIN_CHARS = max(20, int(os.getenv("LLM_STREAM_MIN_CHARS", "55")))


# ==========================================
# LOGGING E SANITIZAÇÃO
# ==========================================

_SENSITIVE_KEYS = (
    r"senha|password|passwd|pwd|token|secret|api[_-]?key|apikey|access[_-]?key|"
    r"authorization|auth|credential|credencial|xi-api-key|x-goog-api-key|x-api-key|"
    r"api_key|appid|ha_token|navidrome_password|elevenlabs_api_key|openweather_key|"
    r"groq_api_key|gemini_api_key|cerebras_api_key|openrouter_key|llm_api_key|"
    r"serper_api_key|tavily_api_key"
)

# Formatos longos e reconhecíveis de credenciais (JWT, chaves Google, Groq, OpenRouter, Tavily)
_RE_SECRET_BLOB = re.compile(
    r"(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"  # JWT
    r"|AIza[0-9A-Za-z_-]{20,}"                                        # Google API key
    r"|gsk_[A-Za-z0-9]{20,}"                                          # Groq
    r"|tvly-[A-Za-z0-9_-]{10,}"                                       # Tavily
    r"|sk-[A-Za-z0-9_-]{16,})"                                        # OpenAI/OpenRouter/ElevenLabs
)


def sanitize_for_log(text: str) -> str:
    """
    Remove tokens, senhas, chaves e identificadores sensíveis de mensagens para log.

    Cobre: parâmetros de query (Subsonic `p`, `t`, `s`, `u`; OpenWeather `appid`),
    cabeçalhos `Authorization`, chaves em formato `CHAVE=valor` / `'chave': 'valor'`,
    segredos declarados em linguagem natural e blobs reconhecíveis (JWT, AIza…, gsk_…,
    tvly-…, sk-…).
    """
    if not text:
        return ""

    cleaned = str(text)

    # 1. Parâmetros sensíveis em URLs (Subsonic usa 'u' para usuário e 's' para salt)
    cleaned = re.sub(
        r"([?&](?:p|u|t|s|token|password|passwd|key|appid|api_key)=)[^&\s'\"]+",
        r"\1***",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 2. Authorization: Bearer / Basic
    cleaned = re.sub(
        r"(Bearer\s+|Basic\s+)[A-Za-z0-9\-_.=+/]+",
        r"\1***",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 3. Pares chave/valor sensíveis em texto, dicionários Python ou JSON
    cleaned = re.sub(
        rf"((?:{_SENSITIVE_KEYS})[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}}]+",
        r"\1***",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 4. Segredos declarados em linguagem natural ("a senha é X", "o token do wifi é Y")
    cleaned = re.sub(
        r"\b(senha|password|passwd|token|chave|credencial)\b([^.,;!?\n]{0,40}?)(?:é|e|:|=)\s+\S+",
        r"\1\2<segredo oculto>",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 5. Blobs de credencial mesmo sem rótulo (ex: chave colada no meio de uma mensagem)
    cleaned = _RE_SECRET_BLOB.sub("***", cleaned)

    return cleaned


def redact_transcript(texto: str, max_chars: int = 0) -> str:
    """
    Prepara uma transcrição de voz (ou uma consulta de busca) para log.

    Por padrão (AURORA_LOG_TRANSCRIPTS=false) NÃO grava o conteúdo da fala, apenas
    o tamanho — evita deixar senhas, dados de saúde e conversas da família em texto
    claro nos logs/journal. Ative com AURORA_LOG_TRANSCRIPTS=true para depurar.
    """
    if not texto:
        return ""
    if not LOG_TRANSCRIPTS:
        return f"<conteúdo oculto: {len(texto)} caracteres>"
    trecho = sanitize_for_log(texto)
    if max_chars and len(trecho) > max_chars:
        return trecho[:max_chars] + "..."
    return trecho

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

    web_enabled = os.getenv("WEB_SEARCH_ENABLED", str(WEB_SEARCH_ENABLED)).lower().strip() in (
        "1", "true", "yes", "on"
    )
    web_prov = (os.getenv("WEB_SEARCH_PROVIDER", WEB_SEARCH_PROVIDER) or "auto").lower().strip()

    status = {
        f"llm ({LLM_PROVIDER})": has_llm,
        "home_assistant": bool(HA_TOKEN and HA_URL),
        "navidrome": bool(NAVIDROME_API_URL and NAVIDROME_USER and NAVIDROME_PASSWORD),
        "openweather": bool(OPENWEATHER_KEY),
        f"web_search ({web_prov})": web_enabled,
        f"tts ({tts_provider_norm})": active_tts_ok,
        "google_tts": has_google_tts,
        "elevenlabs_tts": has_elevenlabs_tts,
        "openrouter_tts": has_openrouter_tts,
    }
    return status
