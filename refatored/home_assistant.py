import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, List

try:
    import requests
except ImportError:
    requests = None

from refatored.config import HA_URL, HEADERS_HA, HA_TIMEOUT, sanitize_for_log

logger = logging.getLogger(__name__)

# ==========================================
# REGISTRO DE DISPOSITIVOS E AUTOMAÇÕES
# ==========================================

DEVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    # Switches / Luzes
    "luz da sala": {
        "entity_id": "switch.sala",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle", "set_brightness"]
    },
    "luz da varanda": {
        "entity_id": "switch.varanda",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "luz da garagem": {
        "entity_id": "switch.garagem",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "luz da área": {
        "entity_id": "switch.area_de_servico_switch_1",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "luz do meu quarto": {
        "entity_id": "switch.meu_quarto_switch_1",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "luz do banheiro": {
        "entity_id": "switch.banheiro_switch_1",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "luz do quarto": {
        "entity_id": "switch.quarto_switch_1",
        "domain": "switch",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    # TVs (Media Players)
    "tv do quarto": {
        "entity_id": "media_player.tv_samsung",
        "domain": "media_player",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    "tv da sala": {
        "entity_id": "media_player.philco_smart_tv",
        "domain": "media_player",
        "allowed_actions": ["turn_on", "turn_off", "toggle"]
    },
    # Automações Ar-Condicionado
    "ligar ar condicionado": {
        "entity_id": "automation.ligar_ar_condicionado",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "desligar ar condicionado": {
        "entity_id": "automation.desligar_ar_condicionado",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    # Automações Samsung TV (Quarto)
    "youtube no quarto": {
        "entity_id": "automation.samsung_tv_youtube",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "record no quarto": {
        "entity_id": "automation.samsung_tv_record",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "sbt no quarto": {
        "entity_id": "automation.samsung_tv_sbt",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "globo no quarto": {
        "entity_id": "automation.samsung_tv_globo",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "record news no quarto": {
        "entity_id": "automation.samsung_tv_record_news",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "manual do mundo no quarto": {
        "entity_id": "automation.samsung_tv_manual_do_mundo",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "nickelodeon no quarto": {
        "entity_id": "automation.samsung_tv_nickelodeon",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "três palavrinhas no quarto": {
        "entity_id": "automation.samsung_tv_3_palavrinhas",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "pinkfong no quarto": {
        "entity_id": "automation.samsung_tv_pinkfong",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "pocoyo no quarto": {
        "entity_id": "automation.samsung_tv_pocoyo",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "moranguinho no quarto": {
        "entity_id": "automation.samsung_tv_moranguinho",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "caze tv no quarto": {
        "entity_id": "automation.samsung_tv_caze_tv",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "ge tv no quarto": {
        "entity_id": "automation.samsung_tv_ge_tv",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "jovem pan news no quarto": {
        "entity_id": "automation.samsung_tv_jovem_pan_news",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    # Automações Android TV (Sala)
    "youtube na sala": {
        "entity_id": "automation.android_tv_youtube",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "aurora tv na sala": {
        "entity_id": "automation.android_tv_aurora_tv",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "tv live na sala": {
        "entity_id": "automation.android_tv_tv_live",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "stremio na sala": {
        "entity_id": "automation.android_tv_stremio",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
    "smart tube na sala": {
        "entity_id": "automation.android_tv_smart_tube",
        "domain": "automation",
        "allowed_actions": ["trigger"]
    },
}

# Sinônimos e variações naturais comuns
DEVICE_ALIASES: Dict[str, str] = {
    "luz de servico": "luz da área",
    "luz de serviço": "luz da área",
    "luz da area": "luz da área",
    "serviço": "luz da área",
    "servico": "luz da área",
    "area": "luz da área",
    "área": "luz da área",
    "lampada da sala": "luz da sala",
    "lâmpada da sala": "luz da sala",
    "sala": "luz da sala",
    "luz sala": "luz da sala",
    "quarto": "luz do quarto",
    "luz quarto": "luz do quarto",
    "banheiro": "luz do banheiro",
    "meu quarto": "luz do meu quarto",
    "meu": "luz do meu quarto",
    "varanda": "luz da varanda",
    "garagem": "luz da garagem",
    "televisao da sala": "tv da sala",
    "televisão da sala": "tv da sala",
    "televisao do quarto": "tv do quarto",
    "televisão do quarto": "tv do quarto",
    "cazé tv no quarto": "caze tv no quarto",
    "tres palavrinhas no quarto": "três palavrinhas no quarto",
}

# ==========================================
# PARSER LOCAL DETERMINÍSTICO (HA)
# ==========================================

# Regex para comandos de negação (devem ser rejeitados para evitar acionamentos acidentais)
RE_NEGACAO = re.compile(r'\bn(?:ã|a)o\s+(?:(?:vai\s+)?(?:ligar|desligar|acender|apagar|ativar|desativar|tocar|abrir|fechar)|liga|desliga|acende|apaga)\b', re.IGNORECASE)

# Regex para DESLIGAR (prioritário sobre ligar, com limites de palavra \b)
RE_DESLIGAR = re.compile(r'\b(desligar(?:\s+a)?|apagar(?:\s+a)?|desativar(?:\s+a)?|desliga(?:\s+a)?|apaga(?:\s+a)?|desativa(?:\s+a)?|fechar(?:\s+a)?|fecha(?:\s+a)?)\b', re.IGNORECASE)

# Regex para LIGAR (com limites de palavra \b)
RE_LIGAR = re.compile(r'\b(ligar(?:\s+a)?|acender(?:\s+a)?|ativar(?:\s+a)?|liga(?:\s+a)?|acende(?:\s+a)?|ativa(?:\s+a)?|abrir(?:\s+a)?|abre(?:\s+a)?)\b', re.IGNORECASE)

# Regex para TOGGLE (alternar)
RE_TOGGLE = re.compile(r'\b(alternar|inverter|mudar o estado)\b', re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Normaliza texto para facilitar correspondência determinística."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text


_RE_ANAPHORA_PRONOUN = re.compile(
    r"\b(ela|ele|isso|mesma|mesmo|de\s+novo|novamente)\b",
    re.IGNORECASE,
)
_RE_NON_HA_OBJECT = re.compile(
    r"\b(musica|som|faixa|timer|cronometro|alarme|lembrete|memoria)\b",
    re.IGNORECASE,
)
_RE_COMPOUND_SPLIT = re.compile(
    r"\s*(?:,|;|\be\s+tamb[ée]m\b|\be\s+depois\b|\bdepois\b|\be\b)\s*",
    re.IGNORECASE,
)


def _match_target_device(texto: str) -> Optional[str]:
    """Localiza o nome canônico de um dispositivo ou alias no trecho normalizado."""
    todos_dispositivos = sorted(DEVICE_REGISTRY.keys(), key=len, reverse=True)
    for nome in todos_dispositivos:
        if nome in texto:
            return nome

    for alias, canonico in sorted(DEVICE_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", texto):
            return canonico

    return None


def parse_home_assistant_local(
    mensagem: str,
    last_target: Optional[str] = None,
    inherited_action: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Parser determinístico local para comandos simples do Home Assistant.
    Resolve o bug crítico onde 'desligar' continha 'ligar' e suporta anáfora
    de curto prazo ('agora apaga ela') quando last_target está disponível.
    Retorna dicionário de intenção ou None se não identificado.
    """
    if not mensagem:
        return None

    texto = normalize_text(mensagem)
    if not texto:
        return None

    # 1. Se contiver negação ("não ligar a luz", "não desligar"), rejeita
    if RE_NEGACAO.search(texto):
        logger.warning(f"Comando com negação detectado: '{mensagem}'. Ignorando por segurança.")
        return {"error": "negation_detected"}

    # 2. Identificar ação com prioridade para DESLIGAR e com limites de palavra (\b)
    action = None
    if RE_DESLIGAR.search(texto):
        action = "turn_off"
    elif RE_LIGAR.search(texto):
        action = "turn_on"
    elif RE_TOGGLE.search(texto):
        action = "toggle"
    elif inherited_action:
        action = inherited_action

    # Caso especial: ar condicionado ("ligar o ar condicionado" / "desligar o ar condicionado")
    if "ar condicionado" in texto or "ar" in texto.split():
        if action == "turn_off" or "desligar" in texto or "desliga" in texto:
            return {"action": "trigger", "target_name": "desligar ar condicionado", "parameters": {}}
        elif action == "turn_on" or "ligar" in texto or "liga" in texto:
            return {"action": "trigger", "target_name": "ligar ar condicionado", "parameters": {}}

    # 3. Identificar dispositivo ou automação
    target_name = _match_target_device(texto)

    # 4. Resolução anafórica contextual ("agora apaga ela", "desliga isso")
    if (
        not target_name
        and last_target
        and last_target in DEVICE_REGISTRY
        and action is not None
        and not _RE_NON_HA_OBJECT.search(texto)
        and (
            _RE_ANAPHORA_PRONOUN.search(texto)
            or len(texto.split()) <= 2
        )
    ):
        if last_target in ("ligar ar condicionado", "desligar ar condicionado"):
            ar_target = (
                "desligar ar condicionado"
                if action == "turn_off"
                else "ligar ar condicionado"
            )
            return {"action": "trigger", "target_name": ar_target, "parameters": {}}
        target_name = last_target
        logger.info(f"parse_local resolveu referência contextual para '{target_name}'")

    if not target_name:
        logger.debug(f"parse_local: nenhum dispositivo reconhecido em '{mensagem}'")
        return None

    device_info = DEVICE_REGISTRY[target_name]

    # Se for uma automação (ex: TV canais, apps), o comando é disparado com 'trigger'
    if device_info["domain"] == "automation":
        action = "trigger"
    elif not action:
        # Se encontrou o dispositivo mas não encontrou ação clara
        logger.debug(f"parse_local: dispositivo '{target_name}' encontrado, mas sem ação clara")
        return None

    logger.info(f"parse_local sucesso: action={action}, target={target_name}")
    return {
        "action": action,
        "target_name": target_name,
        "parameters": {}
    }


def parse_home_assistant_multi_local(
    mensagem: str,
    last_target: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Parser determinístico local com suporte a múltiplos comandos na mesma frase
    (ex: 'apaga a luz da sala e liga o ar condicionado' ou 'apaga a luz da sala e a luz da varanda').
    Retorna lista de intenções ou None se nenhum comando HA determinístico for detectado.
    """
    if not mensagem:
        return None

    texto_inteiro = normalize_text(mensagem)
    if RE_NEGACAO.search(texto_inteiro):
        logger.warning(f"Comando composto com negação detectado: '{mensagem}'. Ignorando.")
        return [{"error": "negation_detected"}]

    partes = [p.strip() for p in _RE_COMPOUND_SPLIT.split(mensagem) if p and p.strip()]
    if len(partes) >= 2:
        intencoes: List[Dict[str, Any]] = []
        acao_herdada: Optional[str] = None
        todos_validos = True

        for parte in partes:
            parsed = parse_home_assistant_local(
                parte,
                last_target=None,
                inherited_action=acao_herdada,
            )
            if parsed and "error" not in parsed:
                intencoes.append(parsed)
                if parsed["action"] in ("turn_on", "turn_off", "toggle"):
                    acao_herdada = parsed["action"]
            else:
                todos_validos = False
                break

        if todos_validos and len(intencoes) >= 2:
            # Remover duplicatas exatas consecutivas preservando ordem
            unicas: List[Dict[str, Any]] = []
            vistas = set()
            for item in intencoes:
                chave = (item["action"], item["target_name"])
                if chave not in vistas:
                    vistas.add(chave)
                    unicas.append(item)
            logger.info(f"parse_multi_local detectou {len(unicas)} comandos compostos.")
            return unicas

    unico = parse_home_assistant_local(mensagem, last_target=last_target)
    return [unico] if unico else None


# ==========================================
# EXTRAÇÃO E VALIDAÇÃO DE JSON
# ==========================================

def extrair_json(texto: str) -> Optional[str]:
    """
    Extrai JSON da resposta da LLM de forma balanceada.
    Resolve o bug crítico onde regex cortava o JSON no primeiro '}' em objetos aninhados.
    """
    if not texto:
        return None

    texto = texto.strip()

    # 1. Se estiver encapsulado em bloco de código Markdown ```json ... ```
    md_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, re.IGNORECASE)
    bloco = md_match.group(1).strip() if md_match else texto

    # 2. Tentar decodificar diretamente o bloco limpo
    try:
        json.loads(bloco)
        return bloco
    except Exception:
        pass

    # 3. Parser balanceador de chaves para encontrar o objeto JSON mais externo
    start_idx = bloco.find('{')
    if start_idx == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_idx, len(bloco)):
        char = bloco[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\':
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    candidato = bloco[start_idx:i + 1].strip()
                    try:
                        json.loads(candidato)
                        return candidato
                    except Exception:
                        pass

    return None


def _validar_item_intencao(item: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(item, dict):
        return False, "invalid_type_not_dict"

    action = item.get("action")
    target_name = item.get("target_name")
    parameters = item.get("parameters", {})

    if not isinstance(action, str) or not action.strip():
        return False, "missing_or_invalid_action"

    if not isinstance(target_name, str) or not target_name.strip():
        return False, "missing_or_invalid_target_name"

    if not isinstance(parameters, dict):
        return False, "parameters_must_be_dict"

    return True, None


def validar_esquema_intencao(intencao_data: Any) -> Tuple[bool, Optional[str]]:
    """
    Valida rigorosamente o esquema retornado da LLM.
    Aceita objeto único {"action", "target_name", "parameters"} OU lote em passo único
    {"actions": [{"action", "target_name", "parameters"}, ...]}, além de {"error": ...}.
    Garante que não aceitaremos tipos inesperados, listas soltas na raiz ou campos malformados.
    """
    if not isinstance(intencao_data, dict):
        return False, "invalid_type_not_dict"

    if "error" in intencao_data:
        return True, None  # Objeto de erro esperado (ex: unknown_device)

    if "actions" in intencao_data:
        actions_list = intencao_data.get("actions")
        if not isinstance(actions_list, list) or not actions_list:
            return False, "actions_must_be_non_empty_list"
        if len(actions_list) > 8:
            return False, "too_many_actions"
        for item in actions_list:
            ok, motivo = _validar_item_intencao(item)
            if not ok:
                return False, motivo
        return True, None

    return _validar_item_intencao(intencao_data)


# ==========================================
# RESOLUÇÃO SEGURA DE COMANDOS HA
# ==========================================

def resolver_comando(intencao: Dict[str, Any]) -> Dict[str, Any]:
    """
    Valida e resolve a intenção abstrata em comando concreto para a API do HA.
    CORREÇÃO CRÍTICA: Os parâmetros da LLM NUNCA podem sobrescrever o entity_id.
    """
    if not isinstance(intencao, dict):
        return {"error": "invalid_format"}

    if "error" in intencao:
        return intencao

    target_name = (intencao.get("target_name") or "").lower().strip()
    action = (intencao.get("action") or "").lower().strip()
    parameters = intencao.get("parameters", {})

    # Resolver aliases se necessário
    if target_name in DEVICE_ALIASES:
        target_name = DEVICE_ALIASES[target_name]

    # Validar se o alvo existe no registro autorizado
    if target_name not in DEVICE_REGISTRY:
        logger.warning(f"resolver_comando: Dispositivo não encontrado: '{target_name}'")
        return {"error": "unknown_device"}

    device = DEVICE_REGISTRY[target_name]
    entity_id = device["entity_id"]
    domain = device["domain"]
    allowed_actions = device["allowed_actions"]

    # Mapear automações de forma consistente
    if domain == "automation":
        action = "trigger"
        service = "trigger"
    elif action == "set_brightness":
        # No Home Assistant, brilho geralmente usa light.turn_on com brightness_pct
        service = "turn_on"
    else:
        service = action

    # Validar se a ação é permitida para este dispositivo
    if action not in allowed_actions:
        logger.warning(f"resolver_comando: Ação '{action}' não permitida para '{target_name}'. Permitidas: {allowed_actions}")
        return {"error": "action_not_allowed"}

    # CONSTRUÇÃO SEGURA DO PAYLOAD:
    # Whitelist de campos permitidos conforme o domínio. 'entity_id' NUNCA vem do payload da LLM.
    safe_data: Dict[str, Any] = {}

    if action == "set_brightness":
        # Validação do brilho
        if "brightness_pct" in parameters:
            try:
                pct = int(parameters["brightness_pct"])
                safe_data["brightness_pct"] = max(0, min(100, pct))
            except (ValueError, TypeError):
                pass
        elif "brightness" in parameters:
            try:
                b = int(parameters["brightness"])
                safe_data["brightness"] = max(0, min(255, b))
            except (ValueError, TypeError):
                pass

    comando = {
        "domain": domain,
        "service": service,
        "entity_id": entity_id,
        "data": safe_data,
        "target_name": target_name
    }

    logger.debug(f"resolver_comando sucesso: {comando}")
    return comando


# ==========================================
# EXECUÇÃO HTTP NO HOME ASSISTANT
# ==========================================

def executar_comando_ha(comando: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Envia o comando resolvido para a REST API do Home Assistant.
    Retorna (sucesso: bool, mensagem_resposta: str).
    """
    if "error" in comando:
        erro = comando["error"]
        mensagens_erro = {
            "unknown_device": "Dispositivo não encontrado no registro.",
            "action_not_allowed": "Ação não permitida para esse dispositivo.",
            "negation_detected": "Comando cancelado por conter negação.",
            "invalid_json": "Não foi possível interpretar o comando.",
            "no_response": "Sem resposta do serviço de automação."
        }
        return False, mensagens_erro.get(erro, "Erro ao processar comando.")

    domain = comando["domain"]
    service = comando["service"]
    entity_id = comando["entity_id"]
    data = comando.get("data", {})

    # Garantia final: payload contém rigorosamente o entity_id validado
    payload = {"entity_id": entity_id}
    if data:
        # data já foi higienizada pela whitelist em resolver_comando
        payload.update(data)

    url = f"{HA_URL}/api/services/{domain}/{service}"
    logger.info(f"Enviando para HA: POST {url} | payload={payload}")

    if requests is None:
        logger.error("Biblioteca 'requests' não instalada.")
        return False, "Biblioteca de requisições HTTP ausente."

    try:
        resp = requests.post(
            url,
            headers=HEADERS_HA,
            json=payload,
            timeout=HA_TIMEOUT
        )
        logger.debug(f"Resposta HA: HTTP {resp.status_code}")

        if resp.status_code in (200, 201, 204):
            return True, "Comando executado com sucesso."
        else:
            logger.error(f"Erro HA: status={resp.status_code}, corpo={sanitize_for_log(resp.text[:300])}")
            return False, "O Home Assistant retornou um erro ao executar a ação."
    except requests.exceptions.Timeout:
        logger.error("Timeout ao comunicar com Home Assistant.")
        return False, "Tempo de resposta esgotado no Home Assistant."
    except Exception as e:
        logger.error(f"Exceção ao comunicar com Home Assistant: {e}")
        return False, "Falha de conexão com o Home Assistant."


def resolver_lista_comandos(intencao_ou_lote: Any) -> List[Dict[str, Any]]:
    """
    Converte uma intenção única, um dicionário {'actions': [...]} ou uma lista de intenções
    em uma lista de comandos resolvidos e validados via DEVICE_REGISTRY.
    """
    if isinstance(intencao_ou_lote, list):
        return [resolver_comando(item) for item in intencao_ou_lote]

    if isinstance(intencao_ou_lote, dict):
        if "actions" in intencao_ou_lote and isinstance(intencao_ou_lote["actions"], list):
            return [resolver_comando(item) for item in intencao_ou_lote["actions"]]
        return [resolver_comando(intencao_ou_lote)]

    return [{"error": "invalid_format"}]


def executar_lote_ha(
    comandos: List[Dict[str, Any]],
) -> Tuple[bool, str, Optional[str]]:
    """
    Executa 1 ou múltiplos comandos validados no Home Assistant em sequência.
    Retorna (sucesso_geral, mensagem_resumo, ultimo_target_acionado).
    """
    if not comandos:
        return False, "Nenhum comando válido para executar.", None

    if len(comandos) == 1:
        ok, msg = executar_comando_ha(comandos[0])
        ultimo = comandos[0].get("target_name") if ok else None
        return ok, msg, ultimo

    sucessos = 0
    erros: List[str] = []
    ultimo_target: Optional[str] = None

    for cmd in comandos:
        ok, msg = executar_comando_ha(cmd)
        if ok:
            sucessos += 1
            if cmd.get("target_name"):
                ultimo_target = cmd["target_name"]
        else:
            erros.append(msg)

    if sucessos == len(comandos):
        return True, f"Todos os {sucessos} comandos foram executados com sucesso.", ultimo_target
    if sucessos > 0:
        return (
            True,
            f"Consegui executar {sucessos} de {len(comandos)} comandos, mas um deles falhou.",
            ultimo_target,
        )
    return False, erros[0] if erros else "Não consegui executar os comandos.", None


# ==========================================
# CONSULTA DE ESTADO NO HOME ASSISTANT (GET /api/states)
# ==========================================

_RE_HA_STATE_QUERY_SINGLE = re.compile(
    r"\b(?:est[áa]|t[áa]|ficou|continua)\s+(?:ligad[oa]|desligad[oa]|aces[oa]|apagad[oa])\b|"
    r"\b(?:como\s+(?:est[áa]|t[áa])\s+(?:a|o)\s+(?:luz|tv|televis[ãa]o))\b",
    re.IGNORECASE,
)

_RE_HA_STATE_QUERY_ALL = re.compile(
    r"\b(?:quais\s+(?:s[ãa]o\s+as\s+)?(?:luzes|tvs|coisas)\s+(?:que\s+)?(?:est[ãa]o|t[ãa]o|ficaram)\s+(?:ligad[oa]s|acesas)|"
    r"tem\s+alguma\s+(?:luz|tv|coisa)\s+(?:ligada|acesa)|"
    r"ficou\s+alguma\s+(?:luz|tv|coisa)\s+(?:ligada|acesa)|"
    r"o\s+que\s+(?:est[áa]|t[áa]|ficou)\s+(?:ligado|aceso)(?:\s+em\s+casa)?)\b",
    re.IGNORECASE,
)


def consultar_estado_dispositivo_ha(nome_dispositivo: str) -> str:
    """Consulta o estado atual ('on'/'off'/etc.) de um dispositivo registrado no HA."""
    alvo_norm = normalize_text(nome_dispositivo or "")
    canonico = (
        alvo_norm
        if alvo_norm in DEVICE_REGISTRY
        else DEVICE_ALIASES.get(alvo_norm) or _match_target_device(alvo_norm)
    )
    if not canonico or canonico not in DEVICE_REGISTRY:
        return "Olha, não encontrei esse dispositivo no meu cadastro da casa."

    device = DEVICE_REGISTRY[canonico]
    if device["domain"] == "automation":
        return f"O item {canonico} é uma automação de disparo rápido, então não guarda estado ligado ou desligado."

    if requests is None:
        return "A biblioteca de conexão não está disponível para consultar o Home Assistant."

    entity_id = device["entity_id"]
    url = f"{HA_URL}/api/states/{entity_id}"

    try:
        resp = requests.get(url, headers=HEADERS_HA, timeout=HA_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"Consulta de estado HA retornou HTTP {resp.status_code} para {entity_id}")
            return f"Não consegui conferir o estado de {canonico} no Home Assistant agora."

        dados = resp.json()
        state = str(dados.get("state", "")).lower()
        eh_luz = canonico.startswith("luz")

        if state in ("on", "playing", "idle", "paused"):
            estado_fala = "acesa" if eh_luz else "ligada"
            return f"Dei uma olhada aqui e a {canonico} tá {estado_fala} nesse momento."
        elif state in ("off", "standby"):
            estado_fala = "apagada" if eh_luz else "desligada"
            return f"Conferi aqui: a {canonico} tá {estado_fala}."
        elif state in ("unavailable", "unknown"):
            return f"Olha, a {canonico} aparece como indisponível ou sem sinal no Home Assistant agora."
        return f"O estado atual de {canonico} no Home Assistant é {state}."
    except Exception as e:
        logger.error(f"Erro ao consultar estado de {entity_id}: {e}")
        return "Tive um probleminha de conexão ao consultar o Home Assistant agora."


def listar_dispositivos_ligados_ha() -> str:
    """Lista quais interruptores/luzes/TVs registrados no DEVICE_REGISTRY estão ligados."""
    if requests is None:
        return "A biblioteca de conexão não está disponível no momento."

    # Mapear entity_id -> nome amigável apenas para entidades com estado real (não automações)
    mapa_entidades = {
        info["entity_id"]: nome
        for nome, info in DEVICE_REGISTRY.items()
        if info.get("domain") != "automation"
    }

    url = f"{HA_URL}/api/states"
    try:
        resp = requests.get(url, headers=HEADERS_HA, timeout=HA_TIMEOUT)
        if resp.status_code != 200:
            return "Não consegui consultar a lista de estados do Home Assistant agora."

        estados = resp.json()
        if not isinstance(estados, list):
            return "Recebi uma resposta inesperada do Home Assistant."

        ligados: List[str] = []
        for item in estados:
            if not isinstance(item, dict):
                continue
            eid = item.get("entity_id")
            if eid in mapa_entidades:
                st = str(item.get("state", "")).lower()
                if st in ("on", "playing", "idle", "paused"):
                    ligados.append(mapa_entidades[eid])

        if not ligados:
            return "Dei uma geral aqui e tá tudo desligado em casa no momento."
        if len(ligados) == 1:
            return f"Olha, no momento só a {ligados[0]} tá ligada."
        lista_txt = ", ".join(ligados[:-1]) + f" e {ligados[-1]}"
        return f"Conferi aqui em casa e estão ligadas: {lista_txt}."
    except Exception as e:
        logger.error(f"Erro ao listar estados do Home Assistant: {e}")
        return "Não consegui verificar os dispositivos do Home Assistant no momento."


def parse_ha_state_query_local(mensagem: str) -> Optional[str]:
    """
    Identifica perguntas locais sobre estado da casa ('tem alguma luz acesa?',
    'a luz da garagem tá ligada?') sem acionar dispositivos por engano.
    """
    if not mensagem:
        return None

    if _RE_HA_STATE_QUERY_ALL.search(mensagem):
        return listar_dispositivos_ligados_ha()

    if _RE_HA_STATE_QUERY_SINGLE.search(mensagem):
        texto_norm = normalize_text(mensagem)
        alvo = _match_target_device(texto_norm)
        if alvo:
            return consultar_estado_dispositivo_ha(alvo)

    return None
