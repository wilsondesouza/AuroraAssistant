import os
import re
import json
import time
import logging
from typing import Optional, Dict, Any, Tuple, List, Callable, Iterator

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    OPENROUTER_KEY,
    LLM_USE_JSON_MODE,
    LLM_TOOL_MAX_STEPS,
    LLM_STREAM_MIN_CHARS,
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
        self.last_call_rejected_tools = False

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

    def _build_headers_and_endpoint(
        self,
        modelo: str,
        provider_override: Optional[str] = None,
    ) -> Optional[Tuple[str, str, str, Dict[str, str]]]:
        """Prepara provedor ativo, endpoint, modelo adaptado e cabeçalhos HTTP."""
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

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key and preset.get("auth_prefix"):
            headers["Authorization"] = f"{preset['auth_prefix']}{api_key}"
        headers.update(preset.get("extra_headers", {}))

        return active_provider, endpoint, adapted_model, headers

    def chamar(
        self,
        modelo: str,
        system_prompt: str,
        mensagem_usuario: str,
        retries: int = 2,
        timeout: int = 15,
        provider_override: Optional[str] = None,
        messages_override: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False,
    ) -> Optional[str]:
        """
        Executa uma requisição de Chat Completion com suporte a retentativas,
        histórico de janela deslizante, Structured Output (json_object) e fallback.
        """
        if requests is None:
            logger.error("Biblioteca 'requests' ausente.")
            return None

        prep = self._build_headers_and_endpoint(modelo, provider_override)
        if prep is None:
            return None
        active_provider, endpoint, adapted_model, headers = prep

        messages = messages_override or [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": mensagem_usuario},
        ]

        use_json_env = os.getenv("LLM_USE_JSON_MODE")
        json_enabled = (
            use_json_env.lower().strip() in ("1", "true", "yes", "on")
            if use_json_env is not None
            else LLM_USE_JSON_MODE
        )
        apply_json_format = bool(json_mode and json_enabled)

        logger.debug(
            f"Chamando LLM [{active_provider.upper()}] modelo='{adapted_model}' em {endpoint}..."
        )

        for attempt in range(retries + 1):
            payload: Dict[str, Any] = {
                "model": adapted_model,
                "messages": messages,
            }
            if apply_json_format:
                payload["response_format"] = {"type": "json_object"}

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
                        modelo,
                        system_prompt,
                        mensagem_usuario,
                        retries=1,
                        timeout=timeout,
                        provider_override=self.fallback_provider,
                        messages_override=messages_override,
                        json_mode=json_mode,
                    )
                return None

            if resp.status_code == 401:
                logger.error(
                    f"Erro 401 no [{active_provider.upper()}]: Chave de API inválida ou não autorizada."
                )
                return None

            # Se um modelo gratuito rejeitar response_format (HTTP 400), desativa json_mode e retenta:
            if resp.status_code == 400 and apply_json_format:
                logger.info(
                    f"Modelo '{adapted_model}' não aceitou response_format json_object; "
                    f"retentando em modo texto padrão..."
                )
                apply_json_format = False
                if attempt == retries:
                    return self.chamar(
                        modelo,
                        system_prompt,
                        mensagem_usuario,
                        retries=0,
                        timeout=timeout,
                        provider_override=active_provider,
                        messages_override=messages_override,
                        json_mode=False,
                    )
                continue

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
                        modelo,
                        system_prompt,
                        mensagem_usuario,
                        retries=1,
                        timeout=timeout,
                        provider_override=self.fallback_provider,
                        messages_override=messages_override,
                        json_mode=json_mode,
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

    def chamar_com_tools(
        self,
        modelo: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executor: Callable[[str, Any], str],
        max_steps: Optional[int] = None,
        timeout: int = 15,
        provider_override: Optional[str] = None,
        fallback_on_unsupported: bool = True,
    ) -> Tuple[Optional[str], bool]:
        """
        Executa chamada com Tool Calling limitado (max_steps <= 3 para proteger o Free-Tier).
        Retorna (resposta_final, usou_alguma_tool).
        Se o modelo não suportar 'tools' (HTTP 400/404/422), faz fallback transparente para chamar()
        quando fallback_on_unsupported=True.
        """
        self.last_call_rejected_tools = False
        if requests is None:
            logger.error("Biblioteca 'requests' ausente.")
            return None, False

        prep = self._build_headers_and_endpoint(modelo, provider_override)
        if prep is None:
            return None, False
        active_provider, endpoint, adapted_model, headers = prep

        steps_limit = min(
            3,
            max(1, max_steps or int(os.getenv("LLM_TOOL_MAX_STEPS", str(LLM_TOOL_MAX_STEPS)))),
        )
        working_messages: List[Dict[str, Any]] = [dict(m) for m in messages]
        used_any_tool = False

        # Passo extra final (+1) apenas para sintetizar a resposta falada após executar tools
        for step in range(steps_limit + 1):
            allow_tools_now = bool(tools and step < steps_limit)
            payload: Dict[str, Any] = {
                "model": adapted_model,
                "messages": working_messages,
            }
            if allow_tools_now:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Erro de rede em Tool Calling [{active_provider.upper()}]: {e}")
                if self.fallback_provider and active_provider != self.fallback_provider and not used_any_tool:
                    return self.chamar_com_tools(
                        modelo,
                        messages,
                        tools,
                        tool_executor,
                        max_steps=steps_limit,
                        timeout=timeout,
                        provider_override=self.fallback_provider,
                    )
                return None, used_any_tool

            # Modelo gratuito sem suporte a function calling -> sinaliza ou degrada suavemente
            if resp.status_code in (400, 404, 422) and allow_tools_now and not used_any_tool:
                self.last_call_rejected_tools = True
                logger.info(
                    f"Modelo '{adapted_model}' não aceitou 'tools' (HTTP {resp.status_code})."
                )
                if not fallback_on_unsupported:
                    return None, False
                texto_fallback = self.chamar(
                    modelo,
                    "",
                    "",
                    retries=1,
                    timeout=timeout,
                    provider_override=active_provider,
                    messages_override=messages,
                )
                return texto_fallback, False

            if resp.status_code == 429 and self.fallback_provider and active_provider != self.fallback_provider and not used_any_tool:
                logger.info(f"Rate limit em {active_provider}. Fallback {self.fallback_provider.upper()}...")
                return self.chamar_com_tools(
                    modelo,
                    messages,
                    tools,
                    tool_executor,
                    max_steps=steps_limit,
                    timeout=timeout,
                    provider_override=self.fallback_provider,
                )

            if resp.status_code != 200:
                logger.warning(
                    f"[{active_provider.upper()}] retornou HTTP {resp.status_code} em chamar_com_tools: "
                    f"{sanitize_for_log(resp.text[:250])}"
                )
                return None, used_any_tool

            try:
                data = resp.json()
                choices = data.get("choices", []) if isinstance(data, dict) else []
                if not choices:
                    return None, used_any_tool
                msg = choices[0].get("message", {})
            except Exception as e:
                logger.error(f"Erro JSON em chamar_com_tools: {e}")
                return None, used_any_tool

            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list) and allow_tools_now:
                used_any_tool = True
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for tc in tool_calls[:4]:
                    tc_id = tc.get("id") or f"call_{step}"
                    fn_obj = tc.get("function") or {}
                    fn_name = fn_obj.get("name") or ""
                    fn_args = fn_obj.get("arguments") or "{}"
                    resultado_tool = tool_executor(fn_name, fn_args)
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": fn_name,
                            "content": str(resultado_tool),
                        }
                    )
                continue

            content = (msg.get("content") or "").strip()
            return (content if content else None), used_any_tool

        return None, used_any_tool

    @staticmethod
    def _extract_ready_sentence(buffer: str, min_chars: int) -> Optional[Tuple[str, str]]:
        """
        Extrai a primeira frase completa pronta para TTS (terminada em ., ! ou ? seguido de espaço)
        desde que tenha pelo menos min_chars caracteres, preservando interjeições curtas ('Olha só!')
        junto à frase seguinte para não quebrar a prosódia.
        """
        for match in re.finditer(r"([.!?]+[\"']?)\s+", buffer):
            end_pos = match.end(1)
            candidato = buffer[:end_pos].strip()
            restante = buffer[match.end():]
            if len(candidato) >= min_chars:
                return candidato, restante
        return None

    def chamar_stream_frases(
        self,
        modelo: str,
        messages: List[Dict[str, Any]],
        min_chars: Optional[int] = None,
        timeout: int = 20,
        provider_override: Optional[str] = None,
    ) -> Iterator[str]:
        """
        Realiza streaming SSE da resposta da LLM e emite frases completas assim que ficam prontas,
        permitindo iniciar a fala no TTS na metade do tempo sem perder a prosódia natural.
        """
        if requests is None:
            return

        prep = self._build_headers_and_endpoint(modelo, provider_override)
        if prep is None:
            return
        active_provider, endpoint, adapted_model, headers = prep

        chunk_min = min_chars or int(os.getenv("LLM_STREAM_MIN_CHARS", str(LLM_STREAM_MIN_CHARS)))
        payload: Dict[str, Any] = {
            "model": adapted_model,
            "messages": messages,
            "stream": True,
        }

        emitted_any = False
        buffer = ""

        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
                stream=True,
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Falha ao abrir stream SSE em [{active_provider.upper()}]: {e}")
            fallback_txt = self.chamar(
                modelo, "", "", retries=1, timeout=timeout,
                provider_override=self.fallback_provider or active_provider,
                messages_override=messages,
            )
            if fallback_txt:
                yield fallback_txt
            return

        if resp.status_code != 200:
            resp.close()
            logger.info(
                f"Stream SSE indisponível em [{active_provider.upper()}] (HTTP {resp.status_code}); "
                f"usando modo síncrono."
            )
            next_prov = (
                self.fallback_provider
                if (resp.status_code == 429 and self.fallback_provider and self.fallback_provider != active_provider)
                else active_provider
            )
            fallback_txt = self.chamar(
                modelo, "", "", retries=1, timeout=timeout,
                provider_override=next_prov,
                messages_override=messages,
            )
            if fallback_txt:
                yield fallback_txt
            return

        resp.encoding = "utf-8"
        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk_json = json.loads(data_str)
                    choices = chunk_json.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if not piece:
                        continue
                    buffer += piece

                    while True:
                        split_res = self._extract_ready_sentence(buffer, chunk_min)
                        if not split_res:
                            break
                        frase_pronta, buffer = split_res
                        emitted_any = True
                        yield frase_pronta
                except Exception:
                    continue

            resto = buffer.strip()
            if resto:
                emitted_any = True
                yield resto
        except Exception as e:
            logger.warning(f"Interrupção durante leitura SSE: {e}")
            resto = buffer.strip()
            if resto:
                emitted_any = True
                yield resto
            elif not emitted_any:
                fallback_txt = self.chamar(
                    modelo, "", "", retries=1, timeout=timeout,
                    provider_override=active_provider,
                    messages_override=messages,
                )
                if fallback_txt:
                    yield fallback_txt
        finally:
            resp.close()


# Instância global singleton do cliente LLM
llm_client = LLMClient()

