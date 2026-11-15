import io
import os
import re
import time
import wave
import logging
from typing import Optional, Dict, Any, List, Tuple

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    TTS_PROVIDER,
    TTS_FALLBACK_PROVIDER,
    TTS_FALLBACK_PROVIDERS,
    TTS_TIMEOUT,
    TTS_VOICE_NAME,
    TTS_LANGUAGE_CODE,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    ELEVENLABS_STABILITY,
    ELEVENLABS_SIMILARITY_BOOST,
    ELEVENLABS_STYLE,
    ELEVENLABS_SPEAKER_BOOST,
    OPENROUTER_TTS_API_KEY,
    OPENROUTER_TTS_URL,
    OPENROUTER_TTS_MODEL,
    OPENROUTER_TTS_VOICE,
    OPENROUTER_TTS_SPEED,
    OPENROUTER_TTS_INSTRUCTIONS,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# PRESETS E ALIASES DE PROVEDORES DE TTS
# ==============================================================================

TTS_PROVIDER_ALIASES: Dict[str, str] = {
    "google": "google",
    "gtts": "google",
    "gcp": "google",
    "chirp": "google",
    "chirp3": "google",
    "pt-br-chirp3-hd": "google",
    "elevenlabs": "elevenlabs",
    "eleven": "elevenlabs",
    "11labs": "elevenlabs",
    "openrouter": "openrouter",
    "or": "openrouter",
}

TTS_PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "google": {
        "label": "Google Cloud TTS (Chirp3-HD)",
        "default_voice": "pt-BR-Chirp3-HD-Erinome",
        "default_language": "pt-BR",
        "audio_ext": ".mp3",
    },
    "elevenlabs": {
        "label": "ElevenLabs TTS",
        "base_url": "https://api.elevenlabs.io/v1/text-to-speech",
        "default_voice_id": "Xb7hH8MSUJpSbSDYk0k2",
        "default_model_id": "eleven_multilingual_v2",
        "default_output_format": "mp3_44100_128",
        "audio_ext": ".mp3",
    },
    "openrouter": {
        "label": "OpenRouter Audio Speech",
        "url": "https://openrouter.ai/api/v1/audio/speech",
        "default_model": "openai/gpt-4o-mini-tts-2025-12-15",
        "default_voice": "coral",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/wilsondesouza/AuroraAssistant",
            "X-Title": "Aurora Assistant",
        },
        "audio_ext": ".mp3",
    },
}


# ==============================================================================
# PREPARAÇÃO FONÉTICA E PROSÓDICA DE TEXTO PARA SÍNTESE DE VOZ (PT-BR)
# ==============================================================================

_RE_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\uFE0F"
    "\u200D"
    "]+",
    flags=re.UNICODE,
)


def _expand_compact_hours_ptbr(match: re.Match) -> str:
    """Converte horários compactos (ex: '1h30', '2h15', '14h') para fala natural."""
    horas = int(match.group(1))
    minutos_str = match.group(2)
    palavra_hora = "hora" if horas == 1 else "horas"

    if not minutos_str:
        return f"{horas} {palavra_hora}"

    minutos = int(minutos_str)
    if minutos == 0:
        return f"{horas} {palavra_hora}"
    if minutos == 30:
        return f"{horas} {palavra_hora} e meia"
    return f"{horas} {palavra_hora} e {minutos}"


def _expand_currency_brl(match: re.Match) -> str:
    """Converte 'R$ 50' ou 'R$ 1,00' para leitura fluida em português."""
    inteiro = int(match.group(1))
    centavos = match.group(2)
    moeda = "real" if inteiro == 1 else "reais"
    if centavos and int(centavos) > 0:
        cent_num = int(centavos)
        cent_palavra = "centavo" if cent_num == 1 else "centavos"
        return f"{inteiro} {moeda} e {cent_num} {cent_palavra}"
    return f"{inteiro} {moeda}"


def _expand_currency_usd(match: re.Match) -> str:
    """Converte 'US$ 5,80' para leitura fluida em português."""
    inteiro = int(match.group(1))
    centavos = match.group(2)
    moeda = "dólar" if inteiro == 1 else "dólares"
    if centavos and int(centavos) > 0:
        cent_num = int(centavos)
        cent_palavra = "centavo" if cent_num == 1 else "centavos"
        return f"{inteiro} {moeda} e {cent_num} {cent_palavra}"
    return f"{inteiro} {moeda}"


def prepare_text_for_speech(texto: str) -> str:
    """
    Limpa artefatos visuais (Markdown, emojis, URLs) MAS preserva integralmente
    a pontuação expressiva que guia prosódia, pausas dramáticas e atuação vocal
    nos motores neurais (travessão '—', reticências '...', dois-pontos ':',
    aspas simples/duplas, exclamação '!' e interrogação '?').

    Também aplica normalizações fonéticas do português brasileiro para evitar
    leituras robóticas de unidades, siglas de medida e horários abreviados.
    """
    if not texto:
        return ""

    t = texto

    # 1. Links Markdown [texto](url) -> mantém apenas o texto falável
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)

    # 2. Remover blocos/marcadores Markdown sem destruir pontuação expressiva
    t = re.sub(r"^\s*#{1,6}\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"[*_`~#\[\]\{\}]", "", t)

    # 3. Remover emojis e pictogramas gráficos
    t = _RE_EMOJI.sub("", t)

    # 4. Converter parênteses explicativos em incisos prosódicos com travessão
    #    (induz queda natural de tom nos modelos neurais em vez de colar palavras)
    t = re.sub(r"\(\s*([^()]+?)\s*\)", r" — \1 — ", t)

    # 5. Normalizar hífens espaçados / duplos para travessão dramático (—),
    #    preservando hífens internos de palavras compostas (ex: guarda-chuva, ar-condicionado)
    t = re.sub(r"(?<=\s)(?:--|[-–—])(?=\s)", "—", t)
    t = re.sub(r"\s*—\s*", " — ", t)
    # Evitar travessão duplicado ou colado antes de pontuação final
    t = re.sub(r"(?:\s*—\s*){2,}", " — ", t)
    t = re.sub(r"\s*—\s*([,.;:!?])", r"\1", t)

    # 6. Normalizar reticências ('…' ou '..') para '...' (pausa pensativa)
    t = t.replace("…", "...")
    t = re.sub(r"\.{2,}", "...", t)

    # 7. Normalizações fonéticas pt-BR (placares esportivos, unidades, moedas e horários)
    # Ex: '3x2', '3 x 2' ou 'Japão 3-2 Brasil' -> '3 a 2' (evita o TTS ler 'três xis dois' ou 'três menos dois'!)
    t = re.sub(r"\b(\d{1,2})\s*[xX×]\s*(\d{1,2})\b", r"\1 a \2", t)
    t = re.sub(
        r"(?<=[A-Za-zÀ-ÿ]\s)(\d{1,2})\s*[-–]\s*(\d{1,2})(?=\s+[A-Za-zÀ-ÿ:])",
        r"\1 a \2",
        t,
    )
    t = re.sub(r"US\$\s*(\d+)(?:[.,](\d{2}))?\b", _expand_currency_usd, t)
    t = re.sub(r"R\$\s*(\d+)(?:,(\d{2}))?\b", _expand_currency_brl, t)
    t = re.sub(r"(-?\d+)\s*[°º]\s*[cC]\b", r"\1 graus", t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 por cento", t)
    t = re.sub(r"\bkm/h\b", "quilômetros por hora", t, flags=re.IGNORECASE)
    t = re.sub(
        r"\b(\d{1,2})\s*h(?:\s*(\d{1,2}))?(?:\s*min)?\b",
        _expand_compact_hours_ptbr,
        t,
        flags=re.IGNORECASE,
    )

    # 8. Ajustar espaços residuais sem colar pontuação
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"([!?])\.(?!\.)", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" —")


def _wrap_pcm_as_wav(pcm_bytes: bytes, content_type: str = "") -> bytes:
    """
    Empacota bytes de áudio PCM linear 16-bit em um container WAV padrão em memória.
    Útil para modelos no OpenRouter (ex: Gemini TTS) que retornam 'audio/pcm'.
    """
    sample_rate = 24000
    channels = 1

    if content_type:
        rate_match = re.search(r"rate=(\d+)", content_type, re.IGNORECASE)
        if rate_match:
            sample_rate = int(rate_match.group(1))
        ch_match = re.search(r"channels=(\d+)", content_type, re.IGNORECASE)
        if ch_match:
            channels = int(ch_match.group(1))

    # Garantir alinhamento de 2 bytes (16-bit PCM)
    frame_align = 2 * max(1, channels)
    usable_len = (len(pcm_bytes) // frame_align) * frame_align
    aligned_pcm = pcm_bytes[:usable_len]

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(aligned_pcm)
    return buf.getvalue()


# ==============================================================================
# CLIENTE UNIVERSAL DE TTS COM CADEIA DE FALLBACK
# ==============================================================================

class TTSClient:
    """
    Cliente universal e pluggável de síntese de voz (Text-to-Speech), seguindo
    a mesma filosofia arquitetural do LLMClient.

    Suporta nativamente:
      - 'google'     : Google Cloud TTS (ex: pt-BR-Chirp3-HD-Erinome)
      - 'elevenlabs' : ElevenLabs API v1 (eleven_multilingual_v2, eleven_flash_v2_5, eleven_v3)
      - 'openrouter' : OpenRouter Audio Speech API (/api/v1/audio/speech)

    Permite trocar o provedor primário via TTS_PROVIDER no .env e definir uma
    cadeia ordenada de contingência via TTS_FALLBACK_PROVIDERS (ex: 'elevenlabs,openrouter').
    """

    def __init__(self):
        self._gcp_client = None
        self._gcp_module = None
        self._gcp_initialized = False

    @staticmethod
    def normalize_provider(provider_name: str) -> str:
        """Normaliza apelidos de provedores ('gtts', 'chirp3', '11labs', etc.)."""
        raw = (provider_name or "google").lower().strip()
        return TTS_PROVIDER_ALIASES.get(raw, raw)

    def get_active_provider(self) -> str:
        return self.normalize_provider(os.getenv("TTS_PROVIDER", TTS_PROVIDER))

    def get_provider_chain(self, provider_override: Optional[str] = None) -> List[str]:
        """
        Monta a lista ordenada e sem duplicatas de provedores a tentar:
        [primário, fallback_1, fallback_2, ...].
        """
        primary = self.normalize_provider(
            provider_override or os.getenv("TTS_PROVIDER", TTS_PROVIDER)
        )
        chain: List[str] = [primary]

        raw_fallbacks = os.getenv("TTS_FALLBACK_PROVIDERS", TTS_FALLBACK_PROVIDERS)
        single_fallback = os.getenv("TTS_FALLBACK_PROVIDER", TTS_FALLBACK_PROVIDER)

        candidates: List[str] = []
        if raw_fallbacks:
            candidates.extend(p.strip() for p in raw_fallbacks.split(",") if p.strip())
        if single_fallback:
            candidates.append(single_fallback.strip())

        for cand in candidates:
            norm = self.normalize_provider(cand)
            if norm and norm not in chain:
                chain.append(norm)

        return chain

    # ------------------------------------------------------------------
    # PROVEDOR 1: GOOGLE CLOUD TTS (pt-BR-Chirp3-HD)
    # ------------------------------------------------------------------

    def _ensure_google_client(self) -> bool:
        if not self._gcp_initialized:
            try:
                from google.cloud import texttospeech
                self._gcp_client = texttospeech.TextToSpeechClient()
                self._gcp_module = texttospeech
                self._gcp_initialized = True
                logger.info("Google Cloud TTS inicializado com sucesso.")
            except Exception as e:
                logger.warning(f"Não foi possível inicializar Google Cloud TTS: {e}")
                self._gcp_client = None
                self._gcp_module = None
                self._gcp_initialized = True
        return self._gcp_client is not None

    def reset_google_client(self):
        """Permite reinicializar o cliente GCP (útil em testes ou troca de credenciais)."""
        self._gcp_client = None
        self._gcp_module = None
        self._gcp_initialized = False

    def _synthesize_google(self, texto_limpo: str) -> Optional[Tuple[bytes, str]]:
        if not self._ensure_google_client():
            return None

        voice_name = os.getenv("TTS_VOICE_NAME", TTS_VOICE_NAME).strip()
        lang_code = os.getenv("TTS_LANGUAGE_CODE", TTS_LANGUAGE_CODE).strip()

        try:
            tts = self._gcp_module
            synthesis_input = tts.SynthesisInput(text=texto_limpo)
            voice = tts.VoiceSelectionParams(
                language_code=lang_code,
                name=voice_name,
            )
            audio_config = tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3)

            logger.info(
                f"Sintetizando voz [GOOGLE TTS | voz={voice_name}]: '{texto_limpo[:65]}...'"
            )
            response = self._gcp_client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
            if response and getattr(response, "audio_content", None):
                return response.audio_content, ".mp3"
            logger.warning("Google Cloud TTS retornou áudio vazio.")
            return None
        except Exception as e:
            logger.error(f"Erro na síntese com Google Cloud TTS: {e}")
            return None

    # ------------------------------------------------------------------
    # PROVEDOR 2: ELEVENLABS TTS API v1
    # ------------------------------------------------------------------

    def _synthesize_elevenlabs(
        self,
        texto_limpo: str,
        retries: int = 1,
        timeout: Optional[int] = None,
    ) -> Optional[Tuple[bytes, str]]:
        if requests is None:
            logger.error("Biblioteca 'requests' ausente para ElevenLabs TTS.")
            return None

        api_key = (os.getenv("ELEVENLABS_API_KEY") or ELEVENLABS_API_KEY or "").strip()
        if not api_key:
            logger.warning("Chave ELEVENLABS_API_KEY ausente no ambiente.")
            return None

        voice_id = (
            os.getenv("ELEVENLABS_VOICE_ID")
            or ELEVENLABS_VOICE_ID
            or TTS_PROVIDER_PRESETS["elevenlabs"]["default_voice_id"]
        ).strip()
        model_id = (
            os.getenv("ELEVENLABS_MODEL_ID")
            or ELEVENLABS_MODEL_ID
            or TTS_PROVIDER_PRESETS["elevenlabs"]["default_model_id"]
        ).strip()
        output_format = (
            os.getenv("ELEVENLABS_OUTPUT_FORMAT")
            or ELEVENLABS_OUTPUT_FORMAT
            or TTS_PROVIDER_PRESETS["elevenlabs"]["default_output_format"]
        ).strip()

        stability = float(os.getenv("ELEVENLABS_STABILITY", str(ELEVENLABS_STABILITY)))
        similarity_boost = float(
            os.getenv("ELEVENLABS_SIMILARITY_BOOST", str(ELEVENLABS_SIMILARITY_BOOST))
        )
        style = float(os.getenv("ELEVENLABS_STYLE", str(ELEVENLABS_STYLE)))
        speaker_boost_env = os.getenv("ELEVENLABS_SPEAKER_BOOST")
        speaker_boost = (
            speaker_boost_env.lower().strip() in ("1", "true", "yes", "on")
            if speaker_boost_env is not None
            else ELEVENLABS_SPEAKER_BOOST
        )

        req_timeout = timeout or int(os.getenv("TTS_TIMEOUT", str(TTS_TIMEOUT)))
        base_url = TTS_PROVIDER_PRESETS["elevenlabs"]["base_url"]
        endpoint = f"{base_url}/{voice_id}"
        params = {"output_format": output_format}

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload: Dict[str, Any] = {
            "text": texto_limpo,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": speaker_boost,
            },
        }
        # A API da ElevenLabs aceita language_code em modelos Flash/Turbo v2.5 e v3,
        # mas rejeita/ignora explicitamente em eleven_multilingual_v2.
        if "multilingual_v2" not in model_id.lower():
            payload["language_code"] = "pt"

        logger.info(
            f"Sintetizando voz [ELEVENLABS | modelo={model_id} | voz={voice_id}]: "
            f"'{texto_limpo[:65]}...'"
        )

        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    endpoint,
                    params=params,
                    headers=headers,
                    json=payload,
                    timeout=req_timeout,
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Erro de conexão com [ELEVENLABS]: {sanitize_for_log(str(e))} "
                    f"(tentativa {attempt + 1}/{retries + 1})"
                )
                if attempt < retries:
                    time.sleep(0.8 + attempt)
                    continue
                return None

            if resp.status_code in (401, 403):
                logger.error(
                    f"Erro {resp.status_code} no [ELEVENLABS]: Chave inválida ou sem permissão/cota."
                )
                return None

            if resp.status_code != 200:
                logger.warning(
                    f"[ELEVENLABS] retornou HTTP {resp.status_code}: "
                    f"{sanitize_for_log(resp.text[:250])}"
                )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
                return None

            if resp.content:
                ext = ".pcm" if output_format.startswith("pcm_") else ".mp3"
                if ext == ".pcm":
                    rate_match = re.search(r"pcm_(\d+)", output_format)
                    ct = f"audio/pcm;rate={rate_match.group(1)}" if rate_match else "audio/pcm"
                    return _wrap_pcm_as_wav(resp.content, ct), ".wav"
                return resp.content, ".mp3"

            logger.warning("[ELEVENLABS] retornou corpo de áudio vazio.")
            return None

        return None

    # ------------------------------------------------------------------
    # PROVEDOR 3: OPENROUTER AUDIO SPEECH API (/api/v1/audio/speech)
    # ------------------------------------------------------------------

    def _synthesize_openrouter(
        self,
        texto_limpo: str,
        retries: int = 1,
        timeout: Optional[int] = None,
    ) -> Optional[Tuple[bytes, str]]:
        if requests is None:
            logger.error("Biblioteca 'requests' ausente para OpenRouter TTS.")
            return None

        api_key = (
            os.getenv("OPENROUTER_TTS_API_KEY")
            or os.getenv("OPENROUTER_KEY")
            or OPENROUTER_TTS_API_KEY
            or os.getenv("LLM_API_KEY", "")
        ).strip()

        if not api_key:
            logger.warning(
                "Chave OPENROUTER_TTS_API_KEY / OPENROUTER_KEY ausente para OpenRouter TTS."
            )
            return None

        endpoint = (
            os.getenv("OPENROUTER_TTS_URL")
            or OPENROUTER_TTS_URL
            or TTS_PROVIDER_PRESETS["openrouter"]["url"]
        ).strip()
        model = (
            os.getenv("OPENROUTER_TTS_MODEL")
            or OPENROUTER_TTS_MODEL
            or TTS_PROVIDER_PRESETS["openrouter"]["default_model"]
        ).strip()
        voice = (
            os.getenv("OPENROUTER_TTS_VOICE")
            or OPENROUTER_TTS_VOICE
            or TTS_PROVIDER_PRESETS["openrouter"]["default_voice"]
        ).strip()
        speed = float(os.getenv("OPENROUTER_TTS_SPEED", str(OPENROUTER_TTS_SPEED)))
        instructions = os.getenv(
            "OPENROUTER_TTS_INSTRUCTIONS", OPENROUTER_TTS_INSTRUCTIONS
        ).strip()
        req_timeout = timeout or int(os.getenv("TTS_TIMEOUT", str(TTS_TIMEOUT)))

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **TTS_PROVIDER_PRESETS["openrouter"]["extra_headers"],
        }

        response_format = "mp3"

        logger.info(
            f"Sintetizando voz [OPENROUTER TTS | modelo={model} | voz={voice}]: "
            f"'{texto_limpo[:65]}...'"
        )

        for attempt in range(retries + 1):
            payload: Dict[str, Any] = {
                "model": model,
                "input": texto_limpo,
                "response_format": response_format,
            }
            if voice:
                payload["voice"] = voice
            if instructions:
                payload["instructions"] = instructions
            if speed != 1.0:
                payload["speed"] = speed

            try:
                resp = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=req_timeout,
                )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Erro de conexão com [OPENROUTER TTS]: {sanitize_for_log(str(e))} "
                    f"(tentativa {attempt + 1}/{retries + 1})"
                )
                if attempt < retries:
                    time.sleep(0.8 + attempt)
                    continue
                return None

            if resp.status_code == 401:
                logger.error("Erro 401 no [OPENROUTER TTS]: Chave de API inválida.")
                return None

            # Alguns modelos de TTS no OpenRouter (ex: Gemini TTS) aceitam apenas 'pcm'
            # e retornam HTTP 400 quando solicitado 'mp3'. Fazemos adaptação automática:
            if resp.status_code == 400 and response_format == "mp3":
                logger.info(
                    f"Modelo '{model}' no OpenRouter rejeitou mp3; retentando em formato PCM..."
                )
                response_format = "pcm"
                if attempt == retries:
                    # Garante uma tentativa extra específica em PCM
                    try:
                        payload["response_format"] = "pcm"
                        resp = requests.post(
                            endpoint, headers=headers, json=payload, timeout=req_timeout
                        )
                    except requests.exceptions.RequestException as e:
                        logger.warning(
                            f"Falha ao retentar OpenRouter TTS em PCM: {sanitize_for_log(str(e))}"
                        )
                        return None
                else:
                    continue

            if resp.status_code != 200:
                logger.warning(
                    f"[OPENROUTER TTS] retornou HTTP {resp.status_code}: "
                    f"{sanitize_for_log(resp.text[:250])}"
                )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
                return None

            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in content_type:
                logger.warning(
                    f"[OPENROUTER TTS] retornou JSON inesperado em vez de áudio: "
                    f"{sanitize_for_log(resp.text[:250])}"
                )
                return None

            if not resp.content:
                logger.warning("[OPENROUTER TTS] retornou stream de áudio vazio.")
                return None

            if "audio/pcm" in content_type or response_format == "pcm":
                wav_bytes = _wrap_pcm_as_wav(resp.content, content_type)
                return wav_bytes, ".wav"

            return resp.content, ".mp3"

        return None

    # ------------------------------------------------------------------
    # ORQUESTRAÇÃO E FALLBACK ENTRE PROVEDORES
    # ------------------------------------------------------------------

    def sintetizar_com_provedor(
        self,
        provedor: str,
        texto_limpo: str,
    ) -> Optional[Tuple[bytes, str]]:
        """Executa a síntese em um único provedor específico já normalizado."""
        p = self.normalize_provider(provedor)
        if p == "google":
            return self._synthesize_google(texto_limpo)
        elif p == "elevenlabs":
            return self._synthesize_elevenlabs(texto_limpo)
        elif p == "openrouter":
            return self._synthesize_openrouter(texto_limpo)
        else:
            logger.error(
                f"Provedor de TTS desconhecido: '{provedor}'. "
                f"Use 'google', 'elevenlabs' ou 'openrouter'."
            )
            return None

    def sintetizar(
        self,
        texto: str,
        provider_override: Optional[str] = None,
    ) -> Optional[Tuple[bytes, str, str]]:
        """
        Prepara o texto e percorre a cadeia de provedores (primário + fallbacks).
        Retorna uma tupla (audio_bytes, extensao_arquivo, provedor_utilizado) ou None.
        """
        texto_limpo = prepare_text_for_speech(texto)
        if not texto_limpo:
            return None

        chain = self.get_provider_chain(provider_override=provider_override)
        for idx, provider_name in enumerate(chain):
            if idx > 0:
                logger.info(
                    f"Acionando fallback de TTS ({idx}/{len(chain) - 1}): "
                    f"[{provider_name.upper()}]..."
                )

            resultado = self.sintetizar_com_provedor(provider_name, texto_limpo)
            if resultado is not None:
                audio_bytes, ext = resultado
                if audio_bytes:
                    return audio_bytes, ext, provider_name

            logger.warning(f"Provedor de TTS [{provider_name.upper()}] indisponível ou falhou.")

        return None


# Instância global singleton do cliente TTS
tts_client = TTSClient()
