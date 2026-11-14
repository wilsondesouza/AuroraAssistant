import json
import logging
import time
from typing import Optional, Dict, Any, Tuple

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    MODEL_CONVERSA,
    MODEL_CLASSIFICADOR,
    MODEL_HA,
    sanitize_for_log,
)
from refatored.prompts import PROMPT_CONVERSA, PROMPT_HA, PROMPT_CLASSIFICADOR
from refatored.home_assistant import (
    DEVICE_REGISTRY,
    parse_home_assistant_local,
    extrair_json,
    validar_esquema_intencao,
    resolver_comando,
    executar_comando_ha,
)
from refatored.music import music_player, parse_music_local
from refatored.local_intents import get_time_response, get_weather_response
from refatored.speech_output import falar, play_confirmation, play_error
from refatored.llm_client import llm_client

logger = logging.getLogger(__name__)

# ==========================================
# CLIENTE LLM (PLUGGÁVEL VIA LLM_CLIENT)
# ==========================================

def chamar_modelo(
    modelo: str,
    system_prompt: str,
    mensagem_usuario: str,
    retries: int = 2,
    timeout: int = 15
) -> Optional[str]:
    """
    Chama modelo LLM através do cliente universal pluggável.
    Suporta OpenRouter, Groq, Gemini, Cerebras, Ollama ou endpoints customizados.
    """
    return llm_client.chamar(
        modelo=modelo,
        system_prompt=system_prompt,
        mensagem_usuario=mensagem_usuario,
        retries=retries,
        timeout=timeout
    )


def classificar_mensagem_llm(mensagem: str) -> Optional[str]:
    """
    Classifica a intenção via LLM.
    CORREÇÃO CRÍTICA: Não usa apenas substring flexível que aceitava texto espúrio.
    Retorna estritamente 'home_assistant', 'music', 'conversation' ou None.
    """
    prompt = PROMPT_CLASSIFICADOR
    resposta = chamar_modelo(MODEL_CLASSIFICADOR, prompt, mensagem, retries=1, timeout=8)
    if not resposta:
        return None

    limpo = resposta.strip().lower()

    # Validação exata ou normalizada
    if "home_assistant" in limpo or "homeassistant" in limpo:
        return "home_assistant"
    elif "music" in limpo or "musica" in limpo:
        return "music"
    elif "conversation" in limpo or "conversa" in limpo:
        return "conversation"

    return "conversation"


def extrair_intencao_ha_llm(mensagem: str) -> Dict[str, Any]:
    """Usa LLM para extrair intenção estruturada de Home Assistant com validação."""
    lista_nomes = ", ".join(DEVICE_REGISTRY.keys())
    prompt_completo = f"{PROMPT_HA}\n\nDispositivos e automações disponíveis:\n{lista_nomes}"

    logger.info("Extraindo intenção Home Assistant via LLM...")
    resposta = chamar_modelo(MODEL_HA, prompt_completo, mensagem, retries=1, timeout=12)
    if not resposta:
        logger.error("Sem resposta do modelo de Home Assistant.")
        return {"error": "no_response"}

    json_str = extrair_json(resposta)
    if not json_str:
        logger.error(f"Não foi possível extrair JSON válido de: {resposta[:150]}")
        return {"error": "invalid_json"}

    try:
        dados = json.loads(json_str)
        valido, motivo = validar_esquema_intencao(dados)
        if not valido:
            logger.error(f"Esquema JSON rejeitado: {motivo}")
            return {"error": "invalid_schema"}
        return dados
    except Exception as e:
        logger.error(f"Erro ao fazer parse do JSON: {e}")
        return {"error": "invalid_json"}


# ==========================================
# ROTEADOR DE INTENÇÃO E ORQUESTRADOR
# ==========================================

class IntentRouter:
    """Roteador principal de mensagens, priorizando parsers locais e chamando IA sob demanda."""

    def processar_mensagem(self, mensagem: str) -> Dict[str, Any]:
        """
        Processa a mensagem do usuário em etapas otimizadas:
        1. Regras locais determinísticas (Hora, Clima, HA local, Música local)
        2. Se não resolvido localmente, consulta classificador e modelos remotos
        """
        if not mensagem or not mensagem.strip():
            return {"intent": "empty", "success": False, "message": "Mensagem vazia."}

        logger.info(f"=== Processando mensagem: '{mensagem}' ===")

        # ----------------------------------------------------
        # ETAPA 1: VERIFICAÇÃO LOCAL DETERMINÍSTICA (FAST PATH)
        # ----------------------------------------------------

        # 1.1. Hora
        resp_hora = get_time_response(mensagem)
        if resp_hora:
            logger.info("Intenção local detectada: HORA")
            play_confirmation()
            falar(resp_hora)
            return {"intent": "time", "success": True, "message": resp_hora}

        # 1.2. Clima / Previsão do tempo
        resp_clima = get_weather_response(mensagem)
        if resp_clima:
            logger.info("Intenção local detectada: CLIMA")
            play_confirmation()
            falar(resp_clima)
            return {"intent": "weather", "success": True, "message": resp_clima}

        # 1.3. Parser local de Home Assistant
        # CORREÇÃO CRÍTICA: Não espera o classificador remoto para comandos HA claros!
        intencao_ha_local = parse_home_assistant_local(mensagem)
        if intencao_ha_local:
            if "error" in intencao_ha_local:
                play_error()
                return {"intent": "home_assistant_local", "success": False, "message": intencao_ha_local["error"]}

            logger.info("Intenção local detectada: HOME ASSISTANT DETERMINÍSTICO")
            comando = resolver_comando(intencao_ha_local)
            sucesso, msg_ha = executar_comando_ha(comando)
            if sucesso:
                play_confirmation()
            else:
                play_error()
                falar(msg_ha)
            return {"intent": "home_assistant_local", "success": sucesso, "message": msg_ha}

        # 1.4. Parser local de Música
        acao_musica = parse_music_local(mensagem)
        if acao_musica:
            logger.info(f"Intenção local detectada: MÚSICA ({acao_musica})")
            return self._executar_acao_musica(acao_musica)

        # ----------------------------------------------------
        # ETAPA 2: FALLBACK PARA CLASSIFICAÇÃO VIA LLM
        # ----------------------------------------------------
        logger.info("Comando não identificado localmente. Consultando classificador LLM...")
        modo = classificar_mensagem_llm(mensagem)

        if modo is None:
            logger.warning("Classificador remoto indisponível.")
            play_error()
            msg_erro = "Desculpe, estou com dificuldades de conexão aos servidores no momento."
            falar(msg_erro)
            return {"intent": "classifier_unavailable", "success": False, "message": msg_erro}

        logger.info(f"Classificador remoto definiu modo: '{modo}'")

        if modo == "home_assistant":
            intencao_llm = extrair_intencao_ha_llm(mensagem)
            comando = resolver_comando(intencao_llm)
            sucesso, msg_ha = executar_comando_ha(comando)
            if sucesso:
                play_confirmation()
            else:
                play_error()
                falar(msg_ha)
            return {"intent": "home_assistant_llm", "success": sucesso, "message": msg_ha}

        elif modo == "music":
            # Tentar novamente identificar ação ou tocar por padrão
            acao_secundaria = parse_music_local(mensagem) or "play"
            return self._executar_acao_musica(acao_secundaria)

        else:
            # Modo conversa geral
            logger.info("Executando fluxo de conversa com LLM...")
            resposta = chamar_modelo(MODEL_CONVERSA, PROMPT_CONVERSA, mensagem)
            if resposta:
                logger.info(f"Resposta IA gerada: '{resposta[:80]}...'")
                falar(resposta)
                return {"intent": "conversation", "success": True, "message": resposta}
            else:
                play_error()
                msg_erro = "Não consegui responder agora."
                falar(msg_erro)
                return {"intent": "conversation", "success": False, "message": msg_erro}

    def _executar_acao_musica(self, acao: str) -> Dict[str, Any]:
        """Executa ações de música e gerencia feedback auditivo."""
        if acao == "stop":
            msg = music_player.stop()
            play_confirmation()
            return {"intent": "music", "action": "stop", "success": True, "message": msg}

        elif acao == "next":
            sucesso, msg = music_player.next_music()
            if sucesso:
                play_confirmation()
            else:
                play_error()
            return {"intent": "music", "action": "next", "success": sucesso, "message": msg}

        elif acao == "continuous":
            sucesso, msg = music_player.start_continuous_play()
            if sucesso:
                play_confirmation()
            else:
                play_error()
            return {"intent": "music", "action": "continuous", "success": sucesso, "message": msg}

        else:  # 'play'
            sucesso, msg = music_player.play_random_music()
            if sucesso:
                play_confirmation()
            else:
                play_error()
            return {"intent": "music", "action": "play", "success": sucesso, "message": msg}


# Instância global singleton do roteador
intent_router = IntentRouter()
