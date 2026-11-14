import os
import time
import logging
from typing import Optional, Dict, Any, Tuple

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    OPENROUTER_KEY,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# CONFIGURAÇÃO DE PRESETS DE PROVEDORES
# ==============================================================================

PROVIDER_PRESETS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "default_model_conversa": "meta-llama/llama-3.3-70b-instruct:free",
        "default_model_classifier": "meta-llama/llama-3.2-3b-instruct:free",
        "default_model_ha": "google/gemma-3-12b-it:free",
        "auth_prefix": "Bearer ",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/wilsondesouza/aurora-assistant",
            "X-Title": "Aurora Assistant"
        }
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model_conversa": "llama-3.3-70b-versatile",
        "default_model_classifier": "llama-3.1-8b-instant",
        "default_model_ha": "llama-3.1-8b-instant",
        "auth_prefix": "Bearer ",
        "extra_headers": {}
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model_conversa": "gemini-2.0-flash",
        "default_model_classifier": "gemini-1.5-flash",
        "default_model_ha": "gemini-1.5-flash",
        "auth_prefix": "Bearer ",
        "extra_headers": {}
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "default_model_conversa": "llama3.1-70b",
        "default_model_classifier": "llama3.1-8b",
        "default_model_ha": "llama3.1-8b",
        "auth_prefix": "Bearer ",
        "extra_headers": {}
    },
    "ollama": {
        "url": "http://localhost:11434/v1/chat/completions",
        "default_model_conversa": "llama3.2:3b",
        "default_model_classifier": "llama3.2:3b",
        "default_model_ha": "llama3.2:3b",
        "auth_prefix": "",
        "extra_headers": {}
    },
    "custom": {
        "url": "",
        "default_model_conversa": "",
        "default_model_classifier": "",
        "default_model_ha": "",
        "auth_prefix": "Bearer ",
        "extra_headers": {}
    }
}


class LLMClient:
    """
    Cliente universal de LLM compatível com a especificação OpenAI Chat Completions.
    Permite alternar entre provedores (OpenRouter, Groq, Gemini, Ollama, Cerebras)
    simplesmente alterando a variável LLM_PROVIDER no arquivo .env.
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openrouter").lower().strip()
        self.custom_base_url = os.getenv("LLM_BASE_URL", "").strip()
        self.fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "").lower().strip()

    def get_api_key_for_provider(self, provider_name: str) -> str:
        """Recupera a chave de API apropriada para o provedor selecionado."""
        p = provider_name.lower()
        if p == "groq":
            return os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY", "")
        elif p == "gemini":
            return os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY", "")
        elif p == "cerebras":
            return os.getenv("CEREBRAS_API_KEY") or os.getenv("LLM_API_KEY", "")
        elif p == "openrouter":
            return os.getenv("OPENROUTER_KEY") or os.getenv("LLM_API_KEY", "")
        elif p == "ollama":
            return "ollama"  # Ollama local não requer chave
        else:
            return os.getenv("LLM_API_KEY", "")

    def get_endpoint_for_provider(self, provider_name: str) -> str:
        """Retorna o endpoint HTTP do provedor."""
        p = provider_name.lower()
        if self.custom_base_url and p == "custom":
            return self.custom_base_url
        if p == "ollama":
            return os.getenv("OLLAMA_BASE_URL", PROVIDER_PRESETS["ollama"]["url"])
        preset = PROVIDER_PRESETS.get(p, PROVIDER_PRESETS["openrouter"])
        return preset["url"]

    def _adapt_model_name(self, model: str, provider_name: str) -> str:
        """
        Adapta o nome do modelo para evitar falhas se o usuário trocar de provedor
        sem alterar os nomes específicos de tags (ex: remover ':free' fora do OpenRouter).
        """
        p = provider_name.lower()
        if p != "openrouter" and ":free" in model:
            # Ex: se o modelo era 'meta-llama/llama-3.3-70b-instruct:free' e mudou para Groq:
            preset = PROVIDER_PRESETS.get(p)
            if preset and preset["default_model_conversa"]:
                logger.info(
                    f"Adaptando modelo '{model}' para o padrão do provedor {p.upper()}: "
                    f"'{preset['default_model_conversa']}'"
                )
                return preset["default_model_conversa"]
        return model

    def chamar(
        self,
        modelo: str,
        system_prompt: str,
        mensagem_usuario: str,
        retries: int = 2,
        timeout: int = 15,
        provider_override: Optional[str] = None
    ) -> Optional[str]:
        """
        Executa uma requisição de Chat Completion com suporte a retentativas e fallback.
        """
        if requests is None:
            logger.error("Biblioteca 'requests' ausente.")
            return None

        active_provider = (provider_override or self.provider).lower()
        api_key = self.get_api_key_for_provider(active_provider)
        endpoint = self.get_endpoint_for_provider(active_provider)

        if not api_key and active_provider != "ollama":
            logger.error(
                f"Chave de API ausente para o provedor '{active_provider}'. "
                f"Defina LLM_API_KEY ou {active_provider.upper()}_API_KEY no .env."
            )
            return None

        adapted_model = self._adapt_model_name(modelo, active_provider)
        preset = PROVIDER_PRESETS.get(active_provider, PROVIDER_PRESETS["openrouter"])

        headers = {
            "Content-Type": "application/json"
        }
        if api_key and preset.get("auth_prefix"):
            headers["Authorization"] = f"{preset['auth_prefix']}{api_key}"
        headers.update(preset.get("extra_headers", {}))

        payload = {
            "model": adapted_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": mensagem_usuario}
            ]
        }

        logger.debug(
            f"Chamando LLM [{active_provider.upper()}] modelo='{adapted_model}' em {endpoint}..."
        )

        for attempt in range(retries + 1):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Erro de conexão com [{active_provider.upper()}]: {e} "
                    f"(tentativa {attempt + 1}/{retries + 1})"
                )
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                # Se falhar e houver fallback configurado:
                if self.fallback_provider and active_provider != self.fallback_provider:
                    logger.info(f"Tentando provedor de fallback: {self.fallback_provider.upper()}...")
                    return self.chamar(
                        modelo, system_prompt, mensagem_usuario,
                        retries=1, timeout=timeout, provider_override=self.fallback_provider
                    )
                return None

            if resp.status_code == 401:
                logger.error(
                    f"Erro 401 no [{active_provider.upper()}]: Chave de API inválida ou não autorizada."
                )
                return None

            if resp.status_code != 200:
                logger.warning(
                    f"Provedor [{active_provider.upper()}] retornou HTTP {resp.status_code}: "
                    f"{sanitize_for_log(resp.text[:300])}"
                )
                # Rate limit (429) ou erro temporário do servidor
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(1 + attempt * 1.5)
                    continue

                # Se esgotou tentativas no primário por rate limit, tenta fallback:
                if resp.status_code == 429 and self.fallback_provider and active_provider != self.fallback_provider:
                    logger.info(f"Rate limit em {active_provider}. Ativando fallback {self.fallback_provider.upper()}...")
                    return self.chamar(
                        modelo, system_prompt, mensagem_usuario,
                        retries=1, timeout=timeout, provider_override=self.fallback_provider
                    )
                return None

            try:
                data = resp.json()
                if isinstance(data, dict):
                    choices = data.get("choices", [])
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message", {})
                        content = msg.get("content")
                        if content:
                            return content.strip()
            except Exception as e:
                logger.error(f"Erro ao processar JSON de [{active_provider.upper()}]: {e}")
                return None

        return None


# Instância global singleton do cliente LLM
llm_client = LLMClient()

