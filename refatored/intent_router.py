import json
import os
import re
import logging
from typing import Optional, Dict, Any, List, Tuple

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    MODEL_CONVERSA,
    MODEL_CLASSIFICADOR,
    MODEL_HA,
    LLM_ENABLE_TOOLS,
    LLM_STREAM_TTS,
    sanitize_for_log,
)
from refatored.prompts import PROMPT_CONVERSA, PROMPT_HA, PROMPT_CLASSIFICADOR
from refatored.home_assistant import (
    DEVICE_REGISTRY,
    parse_home_assistant_local,
    parse_home_assistant_multi_local,
    parse_ha_state_query_local,
    extrair_json,
    validar_esquema_intencao,
    resolver_comando,
    resolver_lista_comandos,
    executar_comando_ha,
)
from refatored.music import music_player, parse_music_local
from refatored.local_intents import get_time_response, get_weather_response
from refatored.speech_output import falar, falar_em_stream, play_confirmation, play_error
from refatored.llm_client import llm_client
from refatored.conversation_memory import (
    conversation_memory,
    is_dismissal_phrase,
    should_expect_followup,
)
from refatored.memory_store import memory_store, handle_memory_command_local
from refatored.skills import (
    parse_timer_local,
    parse_music_query_local,
    TOOLS_SPEC,
    execute_tool_call,
)

logger = logging.getLogger(__name__)

# Gatilho leve para ativar Tool Calling apenas quando a frase sugerir ação/consulta híbrida,
# economizando ~650 tokens de schema em conversas casuais e preservando o streaming de voz!
_RE_HYBRID_TOOL_HINT = re.compile(
    r"\b(?:clima|tempo|temperatura|chover|calor|frio|graus|horas?|hor[áa]rio|"
    r"luz(?:es)?|tv|televis[ãa]o|ar[\s-]?condicionado|sala|quarto|varanda|garagem|banheiro|[áa]rea|"
    r"ligad[oa]s?|aces[oa]s?|desligad[oa]s?|apagad[oa]s?|liga(?:r)?|desliga(?:r)?|acende(?:r)?|apaga(?:r)?|"
    r"m[úu]sica|tocando|faixa|som|timer|cron[ôo]metro|alarme|avisa(?:r)?|daqui\s+a|"
    r"lembr(?:a|ar|e|ete)|esquec(?:e|er|a)|mem[óo]ria|guard(?:a|ar|e|ei)|anot(?:a|ar|e)|"
    r"salv(?:a|ar|e)|grav(?:a|ar|e)|registr(?:a|ar|e)|nota|recado|senha|rem[ée]dio|forno|panela)\b",
    re.IGNORECASE,
)

# Confirmações ou referências curtas logo após conferir estado de um dispositivo ("quero sim", "pode fazer isso")
_RE_CONTEXTUAL_HA_FOLLOWUP = re.compile(
    r"\b(?:sim|quero|pode|por\s+favor|isso|faz|fa[çc]a|inverte|inverter|contr[áa]rio|"
    r"ela|ele|elas|eles|todas|tudo)\b",
    re.IGNORECASE,
)

# Nuances de memória, obrigação futura, timer ou pergunta que NUNCA devem morrer em 'unknown_device' do HA
_RE_NUANCED_MEMORY_OR_CHAT = re.compile(
    r"\b(?:lembr|esquec|mem[óo]ria|guard|anot|grav|registr|salv|avisa|timer|alarme|"
    r"tenho\s+que|tinha\s+que|preciso|forno|panela|rem[ée]dio|senha|onde|quando|qual|como)\b|\?",
    re.IGNORECASE,
)


def _may_require_tools(mensagem: str, has_recent_ha_context: bool = False) -> bool:
    if not mensagem:
        return False
    if _RE_HYBRID_TOOL_HINT.search(mensagem):
        return True
    if has_recent_ha_context and len(mensagem.split()) <= 8 and _RE_CONTEXTUAL_HA_FOLLOWUP.search(mensagem):
        return True
    return False


# ==========================================
# CLIENTE LLM (PLUGGÁVEL VIA LLM_CLIENT)
# ==========================================

def chamar_modelo(
    modelo: str,
    system_prompt: str,
    mensagem_usuario: str,
    retries: int = 2,
    timeout: int = 15,
    messages_override: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = False,
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
        timeout=timeout,
        messages_override=messages_override,
        json_mode=json_mode,
    )


_DEFAULT_CHAMAR_MODELO = chamar_modelo
_DEFAULT_PARSE_HA_LOCAL = parse_home_assistant_local


def classificar_mensagem_llm(mensagem: str) -> Optional[str]:
    """
    Classifica a intenção via LLM.
    Retorna estritamente 'home_assistant', 'music', 'conversation' ou None.
    """
    prompt = PROMPT_CLASSIFICADOR
    resposta = chamar_modelo(MODEL_CLASSIFICADOR, prompt, mensagem, retries=1, timeout=8)
    if not resposta:
        return None

    limpo = resposta.strip().lower()

    if "home_assistant" in limpo or "homeassistant" in limpo:
        return "home_assistant"
    elif "music" in limpo or "musica" in limpo:
        return "music"
    elif "conversation" in limpo or "conversa" in limpo:
        return "conversation"

    return "conversation"


def extrair_intencao_ha_llm(mensagem: str) -> Dict[str, Any]:
    """Usa LLM (com Structured Output json_object) para extrair 1 ou N intenções HA validadas."""
    lista_nomes = ", ".join(DEVICE_REGISTRY.keys())
    ultimo_alvo = conversation_memory.get_last_ha_target()
    contexto_extra = (
        f"\nÚltimo dispositivo acionado recentemente (use se o usuário disser 'ela'/'isso'): {ultimo_alvo}"
        if ultimo_alvo
        else ""
    )
    prompt_completo = (
        f"{PROMPT_HA}\n\nDispositivos e automações disponíveis:\n{lista_nomes}{contexto_extra}"
    )

    logger.info("Extraindo intenção Home Assistant via LLM (Structured Output)...")
    if chamar_modelo is _DEFAULT_CHAMAR_MODELO:
        resposta = chamar_modelo(
            MODEL_HA,
            prompt_completo,
            mensagem,
            retries=1,
            timeout=12,
            json_mode=True,
        )
    else:
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
    """
    Roteador central da Aurora Assistant:
      1. Fast-Path determinístico local (Hora, Clima, Timers, Memória, Status HA/Música, HA Simples/Multi/Anafórico, Música)
      2. Roteamento inteligente com LLM + Janela Deslizante + Mini-RAG SQLite + Tool Calling + Streaming TTS
    """

    def _executar_comandos_ha_validados(
        self, comandos: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Executa 1 ou múltiplos comandos HA registrando o último alvo e estado na memória curta."""
        def _inferred_state(service: Optional[str]) -> Optional[str]:
            if service == "turn_on":
                return "on"
            if service == "turn_off":
                return "off"
            return None

        if len(comandos) == 1:
            sucesso, msg_ha = executar_comando_ha(comandos[0])
            if sucesso and comandos[0].get("target_name"):
                conversation_memory.record_ha_target(
                    comandos[0]["target_name"],
                    state=_inferred_state(comandos[0].get("service")),
                )
            return sucesso, msg_ha

        sucessos = 0
        ultimo_erro = "Não foi possível executar os comandos."
        for cmd in comandos:
            ok, msg = executar_comando_ha(cmd)
            if ok:
                sucessos += 1
                if cmd.get("target_name"):
                    conversation_memory.record_ha_target(
                        cmd["target_name"],
                        state=_inferred_state(cmd.get("service")),
                    )
            else:
                ultimo_erro = msg

        if sucessos == len(comandos):
            return True, f"Todos os {sucessos} comandos foram executados com sucesso."
        if sucessos > 0:
            return True, f"Executei {sucessos} de {len(comandos)} comandos."
        return False, ultimo_erro

    def processar_mensagem(
        self,
        mensagem: str,
        is_followup: bool = False,
    ) -> Dict[str, Any]:
        """
        Processa a mensagem do usuário em etapas otimizadas.
        Inclui sinalizador 'expect_followup' quando a Aurora encerra com pergunta ('?').
        """
        if not mensagem or not mensagem.strip():
            return {
                "intent": "empty",
                "success": False,
                "message": "Mensagem vazia.",
                "expect_followup": False,
            }

        logger.info(f"=== Processando mensagem: '{mensagem}' (followup={is_followup}) ===")

        # 0. Encerramento natural no modo de conversa contínua ("Não, obrigado!", "Só isso")
        if is_followup and is_dismissal_phrase(mensagem):
            despedida = "Beleza! Qualquer coisa é só me chamar."
            falar(despedida)
            conversation_memory.add_turn(mensagem, despedida)
            return {
                "intent": "followup_end",
                "success": True,
                "message": despedida,
                "expect_followup": False,
            }

        # ----------------------------------------------------
        # ETAPA 1: VERIFICAÇÃO LOCAL DETERMINÍSTICA (FAST PATH)
        # ----------------------------------------------------

        # 1.1. Hora
        resp_hora = get_time_response(mensagem)
        if resp_hora:
            logger.info("Intenção local detectada: HORA")
            play_confirmation()
            falar(resp_hora)
            conversation_memory.add_turn(mensagem, resp_hora)
            return {
                "intent": "time",
                "success": True,
                "message": resp_hora,
                "expect_followup": False,
            }

        # 1.2. Clima / Previsão do tempo
        resp_clima = get_weather_response(mensagem)
        if resp_clima:
            logger.info("Intenção local detectada: CLIMA")
            play_confirmation()
            falar(resp_clima)
            conversation_memory.add_turn(mensagem, resp_clima)
            return {
                "intent": "weather",
                "success": True,
                "message": resp_clima,
                "expect_followup": False,
            }

        # 1.3. Timers e Lembretes Rápidos por Voz
        resp_timer = parse_timer_local(mensagem)
        if resp_timer:
            logger.info("Intenção local detectada: TIMER")
            play_confirmation()
            falar(resp_timer)
            conversation_memory.add_turn(mensagem, resp_timer)
            return {
                "intent": "timer",
                "success": True,
                "message": resp_timer,
                "expect_followup": False,
            }

        # 1.4. Memória da Casa / Família (Salvar, Listar ou Esquecer fatos no SQLite)
        resp_memoria = handle_memory_command_local(mensagem)
        if resp_memoria:
            logger.info("Intenção local detectada: MEMÓRIA DA CASA")
            play_confirmation()
            falar(resp_memoria)
            conversation_memory.add_turn(mensagem, resp_memoria)
            return {
                "intent": "memory",
                "success": True,
                "message": resp_memoria,
                "expect_followup": False,
            }

        # 1.5. Consulta de Música Atual ("que música tá tocando?")
        resp_musica_info = parse_music_query_local(mensagem)
        if resp_musica_info:
            logger.info("Intenção local detectada: CONSULTA MÚSICA ATUAL")
            play_confirmation()
            falar(resp_musica_info)
            conversation_memory.add_turn(mensagem, resp_musica_info)
            return {
                "intent": "music_info",
                "success": True,
                "message": resp_musica_info,
                "expect_followup": False,
            }

        # 1.6. Consulta de Estado no Home Assistant ("a área tá acesa?", "tem luz ligada?")
        resp_estado_ha = parse_ha_state_query_local(mensagem)
        if resp_estado_ha:
            logger.info("Intenção local detectada: CONSULTA ESTADO HA")
            play_confirmation()
            falar(resp_estado_ha)
            conversation_memory.add_turn(mensagem, resp_estado_ha)
            return {
                "intent": "home_assistant_state",
                "success": True,
                "message": resp_estado_ha,
                "expect_followup": should_expect_followup(resp_estado_ha),
            }

        # 1.7. Parser local de Home Assistant (Simples, Multi-comando e Anafórico Singular/Plural)
        ultimo_alvo_ha, _, ultimos_alvos_lista = conversation_memory.get_last_ha_context()
        if parse_home_assistant_local is not _DEFAULT_PARSE_HA_LOCAL:
            unico_mock = parse_home_assistant_local(mensagem)
            intencoes_ha_locais = [unico_mock] if unico_mock else None
        else:
            intencoes_ha_locais = parse_home_assistant_multi_local(
                mensagem,
                last_target=ultimo_alvo_ha,
                last_targets_list=ultimos_alvos_lista,
            )

        if intencoes_ha_locais:
            primeira = intencoes_ha_locais[0]
            if "error" in primeira:
                play_error()
                return {
                    "intent": "home_assistant_local",
                    "success": False,
                    "message": primeira["error"],
                    "expect_followup": False,
                }

            logger.info(
                f"Intenção local detectada: HOME ASSISTANT DETERMINÍSTICO "
                f"({len(intencoes_ha_locais)} ação/ações)"
            )
            comandos = [resolver_comando(item) for item in intencoes_ha_locais]
            sucesso, msg_ha = self._executar_comandos_ha_validados(comandos)
            if sucesso:
                play_confirmation()
            else:
                play_error()
                falar(msg_ha)
            return {
                "intent": "home_assistant_local",
                "success": sucesso,
                "message": msg_ha,
                "expect_followup": False,
            }

        # 1.8. Parser local de Música
        acao_musica = parse_music_local(mensagem)
        if acao_musica:
            logger.info(f"Intenção local detectada: MÚSICA ({acao_musica})")
            res_musica = self._executar_acao_musica(acao_musica)
            res_musica["expect_followup"] = False
            return res_musica

        # ----------------------------------------------------
        # ETAPA 2: FALLBACK PARA CLASSIFICAÇÃO E CONVERSA VIA LLM
        # ----------------------------------------------------
        logger.info("Comando não identificado localmente. Consultando classificador LLM...")
        modo = classificar_mensagem_llm(mensagem)

        if modo is None:
            logger.warning("Classificador remoto indisponível.")
            play_error()
            msg_erro = "Desculpe, estou com dificuldades de conexão aos servidores no momento."
            falar(msg_erro)
            return {
                "intent": "classifier_unavailable",
                "success": False,
                "message": msg_erro,
                "expect_followup": False,
            }

        logger.info(f"Classificador remoto definiu modo: '{modo}'")

        if modo == "home_assistant":
            intencao_llm = extrair_intencao_ha_llm(mensagem)
            comandos = resolver_lista_comandos(intencao_llm)

            # Rede de segurança: se o classificador confundiu um pedido de memória/recado/pergunta
            # com home_assistant (ex: por conter a palavra 'desligar' em 'desligar o forno') e deu
            # unknown_device, redireciona de forma transparente para a conversa com Tools e Mini-RAG!
            if (
                all(c.get("error") == "unknown_device" for c in comandos)
                and _RE_NUANCED_MEMORY_OR_CHAT.search(mensagem)
            ):
                logger.info(
                    "Dispositivo desconhecido em frase com nuance de memória/conversa; "
                    "redirecionando para LLM com Tools e Mini-RAG..."
                )
                return self._processar_conversa_llm(mensagem, force_tools=True)

            sucesso, msg_ha = self._executar_comandos_ha_validados(comandos)
            if sucesso:
                play_confirmation()
            else:
                play_error()
                falar(msg_ha)
            return {
                "intent": "home_assistant_llm",
                "success": sucesso,
                "message": msg_ha,
                "expect_followup": False,
            }

        elif modo == "music":
            acao_secundaria = parse_music_local(mensagem) or "play"
            res_musica = self._executar_acao_musica(acao_secundaria)
            res_musica["expect_followup"] = False
            return res_musica

        else:
            # Modo conversa inteligente (com Memória Curta + Mini-RAG SQLite + Tools + Streaming TTS)
            return self._processar_conversa_llm(mensagem)

    def _processar_conversa_llm(
        self,
        mensagem: str,
        force_tools: bool = False,
    ) -> Dict[str, Any]:
        """Executa o fluxo de conversa enriquecido com contexto, RAG doméstico, Tools e Streaming."""
        logger.info("Executando fluxo de conversa com LLM...")

        # 1. Buscar fatos relevantes na Memória da Casa (SQLite FTS5 + Embeddings opcionais)
        fatos_relevantes = memory_store.search(mensagem)
        if fatos_relevantes:
            logger.info(f"Mini-RAG injetou {len(fatos_relevantes)} memória(s) da casa no contexto.")

        # 2. Verificar se há contexto recente de conferência/acionamento de dispositivo HA
        ultimo_alvo_ha, ultimo_estado_ha, ultimos_alvos_lista = (
            conversation_memory.get_last_ha_context()
        )
        precisa_tools = force_tools or _may_require_tools(
            mensagem, has_recent_ha_context=bool(ultimo_alvo_ha)
        )

        ha_hint: Optional[str] = None
        if precisa_tools and ultimo_alvo_ha:
            alvos_txt = (
                ", ".join(ultimos_alvos_lista)
                if len(ultimos_alvos_lista) > 1
                else ultimo_alvo_ha
            )
            estado_txt = f" (último estado observado: {ultimo_estado_ha})" if ultimo_estado_ha else ""
            ha_hint = (
                f"Contexto recente da casa: dispositivo(s) em foco na interação anterior: "
                f"{alvos_txt}{estado_txt}. Se a mensagem atual do usuário confirmar ou pedir "
                f"uma ação sobre esse(s) dispositivo(s) (ex: 'sim', 'quero', 'pode apagar', "
                f"'acende ela', 'inverte'), execute controlar_dispositivo_casa. Se o usuário "
                f"mudou de assunto e não há relação com o dispositivo, ignore este aviso e "
                f"responda normalmente."
            )

        # 3. Montar mensagens mantendo PROMPT_CONVERSA fixo na posição 0 (Prompt Caching friendly)
        messages = conversation_memory.build_messages(
            static_system_prompt=PROMPT_CONVERSA,
            user_message=mensagem,
            rag_facts=fatos_relevantes,
            ha_context_hint=ha_hint,
        )

        # Compatibilidade total caso chamar_modelo tenha sido substituído por mock em testes:
        if chamar_modelo is not _DEFAULT_CHAMAR_MODELO:
            resposta = chamar_modelo(MODEL_CONVERSA, PROMPT_CONVERSA, mensagem)
            if resposta:
                falar(resposta)
                conversation_memory.add_turn(mensagem, resposta)
                return {
                    "intent": "conversation",
                    "success": True,
                    "message": resposta,
                    "expect_followup": should_expect_followup(resposta),
                }
            return self._falha_conversa()

        tools_enabled_env = os.getenv("LLM_ENABLE_TOOLS")
        use_tools = (
            tools_enabled_env.lower().strip() in ("1", "true", "yes", "on")
            if tools_enabled_env is not None
            else LLM_ENABLE_TOOLS
        )

        stream_enabled_env = os.getenv("LLM_STREAM_TTS")
        use_stream = (
            stream_enabled_env.lower().strip() in ("1", "true", "yes", "on")
            if stream_enabled_env is not None
            else LLM_STREAM_TTS
        )

        # 4a. Se a mensagem sugerir ação híbrida ou confirmação pós-consulta de estado HA, usa Tool Calling (max_steps<=2)
        if use_tools and precisa_tools:
            resposta, _ = llm_client.chamar_com_tools(
                modelo=MODEL_CONVERSA,
                messages=messages,
                tools=TOOLS_SPEC,
                tool_executor=execute_tool_call,
            )
            if resposta:
                logger.info(f"Resposta IA (com suporte a tools): '{resposta[:80]}...'")
                falar(resposta)
                conversation_memory.add_turn(mensagem, resposta)
                return {
                    "intent": "conversation",
                    "success": True,
                    "message": resposta,
                    "expect_followup": should_expect_followup(resposta),
                }
            return self._falha_conversa()

        # 3b. Conversa direta com Streaming por Frase Completa (menor latência até a voz sair)
        if use_stream:
            frases_iter = llm_client.chamar_stream_frases(
                modelo=MODEL_CONVERSA,
                messages=messages,
            )
            resposta_stream = falar_em_stream(frases_iter)
            if resposta_stream:
                logger.info(f"Resposta IA transmitida em stream: '{resposta_stream[:80]}...'")
                conversation_memory.add_turn(mensagem, resposta_stream)
                return {
                    "intent": "conversation",
                    "success": True,
                    "message": resposta_stream,
                    "expect_followup": should_expect_followup(resposta_stream),
                }
            return self._falha_conversa()

        # 3c. Conversa síncrona tradicional (quando LLM_STREAM_TTS=false)
        resposta = chamar_modelo(
            MODEL_CONVERSA,
            PROMPT_CONVERSA,
            mensagem,
            messages_override=messages,
        )
        if resposta:
            logger.info(f"Resposta IA gerada: '{resposta[:80]}...'")
            falar(resposta)
            conversation_memory.add_turn(mensagem, resposta)
            return {
                "intent": "conversation",
                "success": True,
                "message": resposta,
                "expect_followup": should_expect_followup(resposta),
            }
        return self._falha_conversa()

    @staticmethod
    def _falha_conversa() -> Dict[str, Any]:
        play_error()
        msg_erro = "Não consegui responder agora."
        falar(msg_erro)
        return {
            "intent": "conversation",
            "success": False,
            "message": msg_erro,
            "expect_followup": False,
        }

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
