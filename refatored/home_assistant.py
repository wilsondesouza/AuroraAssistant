import re
import json
import logging
import os
from urllib.parse import urlsplit
from typing import Dict, Any, Optional, Tuple, List

try:
    import requests
except ImportError:
    requests = None

from refatored.config import HA_CA_BUNDLE, HA_URL, HEADERS_HA, HA_TIMEOUT, sanitize_for_log
from refatored.conversation_memory import conversation_memory

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
# Cobre os auxiliares mais comuns do português falado: "não PRECISA ligar",
# "não QUERO acender", "não VOU desligar", "não É PRA apagar", "sem ligar", "nunca abrir".
RE_NEGACAO = re.compile(
    r"\bn(?:ã|a)o\s+"
    r"(?:(?:precis\w*|quer\w*|vou|vai|vamos|va|deve\w*|pode\w*|podia|tem|tenho|"
    r"é|e|era|estou|est\w*|consegue|conseguiu|adianta|dá|da|pra|para|mesmo|nem)\s+)*"
    r"(?:ligar|desligar|acender|apagar|ativar|desativar|tocar|abrir|fechar|"
    r"liga|desliga|acende|apaga|ativa|desativa|toca|abre|fecha)\b"
    r"|\b(?:sem|evita|evite|jamais|nunca)\s+"
    r"(?:ligar|desligar|acender|apagar|ativar|desativar|tocar|abrir|fechar)\b",
    re.IGNORECASE,
)

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
_RE_ANAPHORA_PLURAL = re.compile(
    r"^(?:ent[aã]o\s+|agora\s+)?(?:pode\s+)?(?:desligar|apagar|ligar|acender|desliga|apaga|liga|acende)"
    r"\s+(?:elas|eles|todas(?:\s+elas)?|tudo)(?:\s+por\s+favor|\s+pra\s+mim)?$",
    re.IGNORECASE,
)
_RE_PURE_CONTEXTUAL_ACTION = re.compile(
    r"^(?:sim\s+|isso\s+|ent[aã]o\s+|agora\s+|a[ií]\s+)*(?:pode\s+)?"
    r"(?:ligar|desligar|acender|apagar|liga|desliga|acende|apaga|alternar|inverter)"
    r"(?:\s+(?:ela|ele|isso|l[aá]|a[ií]|pra\s+mim|por\s+favor|ent[aã]o|de\s+novo|novamente))*$",
    re.IGNORECASE,
)
_RE_NON_HA_OBJECT = re.compile(
    r"\b(musica|som|faixa|timer|cronometro|alarme|lembrete|memoria|forno|panela|fogao)\b",
    re.IGNORECASE,
)
_RE_NOT_DIRECT_ACTUATION = re.compile(
    r"\b(lembr(?:a|ar|e)|esquec(?:e|er|a)|memoriz|anot(?:a|ar|e)|guard(?:a|ar|e)|"
    r"tenho\s+que|tinha\s+que|preciso\s+(?:ligar|desligar|apagar|acender)|"
    r"que\s+horas|quando\s+eu|se\s+(?:tiver|estiver|fizer|passar)|"
    r"(?:vou|vamos|pretendo|quero)\s+(?:ligar|desligar|apagar|acender))\b",
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


def _find_action_end(texto: str) -> Optional[int]:
    """Retorna a posição final do primeiro verbo de ação encontrado."""
    match = None
    for regex in (RE_DESLIGAR, RE_LIGAR, RE_TOGGLE):
        encontrado = regex.search(texto)
        if encontrado and (match is None or encontrado.start() < match.start()):
            match = encontrado
    return match.end() if match else None


def _match_target_device_apos_acao(texto: str) -> Optional[str]:
    """
    Resolve o dispositivo priorizando o trecho POSTERIOR ao verbo de ação, e só então
    a frase inteira. Corrige o caso "a luz da sala está queimada, liga a da varanda",
    em que o parser antigo escolhia o primeiro dispositivo mencionado (a sala).
    """
    action_end = _find_action_end(texto)
    if action_end is not None:
        trecho = texto[action_end:].strip()
        achado = _match_target_device(trecho) if trecho else None
        if achado:
            return achado
    return _match_target_device(texto)


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

    # 1.b. Ignorar frases de lembrete, obrigação futura, pergunta de horário ou condicional
    #      (ex: 'me lembra que tenho que desligar o forno' ou 'se estiver calor liga o ar')
    if _RE_NOT_DIRECT_ACTUATION.search(texto) or mensagem.strip().endswith("?"):
        return None

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

    # 3. Identificar dispositivo ou automação (prioriza o alvo citado após o verbo)
    target_name = _match_target_device_apos_acao(texto)

    # 4. Resolução anafórica contextual ("acende/apaga ela", "pode apagar por favor")
    #    Exige que não haja objeto estranho ('forno', 'música') e que a frase seja uma ação
    #    contextual pura ou contenha pronome anafórico explícito.
    if (
        not target_name
        and last_target
        and last_target in DEVICE_REGISTRY
        and action is not None
        and not _RE_NON_HA_OBJECT.search(texto)
        and _RE_PURE_CONTEXTUAL_ACTION.match(texto)
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
    last_targets_list: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Parser determinístico local com suporte a múltiplos comandos na mesma frase
    (ex: 'apaga a luz da sala e liga o ar condicionado' ou 'apaga a luz da sala e a luz da varanda'),
    além de anáfora plural ('apaga elas') após consultar vários dispositivos ligados.
    Retorna lista de intenções ou None se nenhum comando HA determinístico for detectado.
    """
    if not mensagem:
        return None

    texto_inteiro = normalize_text(mensagem)
    if RE_NEGACAO.search(texto_inteiro):
        logger.warning(f"Comando composto com negação detectado: '{mensagem}'. Ignorando.")
        return [{"error": "negation_detected"}]

    if _RE_NOT_DIRECT_ACTUATION.search(texto_inteiro) or mensagem.strip().endswith("?"):
        return None

    # Anáfora plural ("apaga elas", "desliga todas") após listar dispositivos ligados
    if (
        last_targets_list
        and len(last_targets_list) >= 2
        and _RE_ANAPHORA_PLURAL.match(texto_inteiro)
    ):
        acao_plural = "turn_off" if RE_DESLIGAR.search(texto_inteiro) else "turn_on"
        return [
            {"action": acao_plural, "target_name": alvo, "parameters": {}}
            for alvo in last_targets_list
            if alvo in DEVICE_REGISTRY
        ]

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

class HAConfigError(ValueError):
    pass


def _transport_options(*, authenticated=True):
    """Escopo HA apenas: nunca alterar confiança de Navidrome, LLM, Web ou TTS."""
    try:
        uri = urlsplit(HA_URL)
        _ = uri.port  # validar inclusive uma porta explícita inválida
    except ValueError as exc:
        raise HAConfigError("HA_URL inválida.") from exc
    if (uri.scheme not in {'https', 'http'} or not uri.hostname or uri.username is not None
            or uri.password is not None or uri.query or uri.fragment):
        raise HAConfigError('Confira HA_URL: use a base HTTPS do Home Assistant.')
    if uri.scheme == 'http' and (HA_CA_BUNDLE or uri.hostname not in {'localhost', '127.0.0.1', '::1'}):
        raise HAConfigError('Use HTTPS para o Home Assistant. O token não foi enviado.')
    if HA_CA_BUNDLE and not (os.path.isabs(HA_CA_BUNDLE) and os.path.isfile(HA_CA_BUNDLE)
                               and os.access(HA_CA_BUNDLE, os.R_OK)):
        raise HAConfigError('HA_CA_BUNDLE deve apontar para um arquivo PEM absoluto e legível pelo serviço.')
    options = dict(headers=HEADERS_HA if authenticated else {}, timeout=HA_TIMEOUT,
                   verify=HA_CA_BUNDLE or True, allow_redirects=False)
    if not authenticated:
        options['auth'] = lambda prepared: prepared  # não deixar ~/.netrc injetar Authorization no diagnóstico
    if uri.scheme == 'http':
        # Compatibilidade com o HA local, sem encaminhar HTTP por proxy de ambiente.
        options['proxies'] = {'http': '', 'all': ''}
    return options


def _trust_failure(exc):
    if isinstance(exc, HAConfigError):
        logger.error('Configuração do cliente HA: %s', exc)
        return str(exc)
    logger.error('TLS do HA falhou; confira CA, cadeia e SAN de HA_URL. Detalhe: %s', sanitize_for_log(str(exc)))
    return 'Não consegui validar a conexão TLS com o Home Assistant. Confira a CA e o nome do servidor no Orange Pi.'


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
    logger.info("Enviando para HA: serviço %s.%s, entidade %s", domain, service, entity_id)

    if requests is None:
        logger.error("Biblioteca 'requests' não instalada.")
        return False, "Biblioteca de requisições HTTP ausente."

    try:
        resp = requests.post(
            url,
            json=payload,
            **_transport_options(),
        )
        logger.debug(f"Resposta HA: HTTP {resp.status_code}")

        if resp.status_code in (200, 201, 204):
            return True, "Comando executado com sucesso."
        else:
            logger.error(f"Erro HA: status={resp.status_code}, corpo={sanitize_for_log(resp.text[:300])}")
            return False, "O Home Assistant retornou um erro ao executar a ação."
    except (HAConfigError, requests.exceptions.SSLError) as e:
        return False, _trust_failure(e)
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
        resp = requests.get(url, **_transport_options())
        if resp.status_code != 200:
            logger.warning(f"Consulta de estado HA retornou HTTP {resp.status_code} para {entity_id}")
            return f"Não consegui conferir o estado de {canonico} no Home Assistant agora."

        dados = resp.json()
        state = str(dados.get("state", "")).lower()
        eh_luz = canonico.startswith("luz")

        if state in ("on", "playing", "idle", "paused"):
            conversation_memory.record_ha_target(canonico, state="on")
            estado_fala = "acesa" if eh_luz else "ligada"
            verbo_oposto = "apague" if eh_luz else "desligue"
            return (
                f"Dei uma olhada aqui e a {canonico} tá {estado_fala} "
                f"— quer que eu {verbo_oposto}?"
            )
        elif state in ("off", "standby"):
            conversation_memory.record_ha_target(canonico, state="off")
            estado_fala = "apagada" if eh_luz else "desligada"
            verbo_oposto = "acenda" if eh_luz else "ligue"
            return (
                f"Conferi aqui: a {canonico} tá {estado_fala} "
                f"— quer que eu {verbo_oposto}?"
            )
        elif state in ("unavailable", "unknown"):
            conversation_memory.record_ha_target(canonico, state=state)
            return f"Olha, a {canonico} aparece como indisponível ou sem sinal no Home Assistant agora."
        conversation_memory.record_ha_target(canonico, state=state)
        return f"O estado atual de {canonico} no Home Assistant é {state}."
    except (HAConfigError, requests.exceptions.SSLError) as e:
        return _trust_failure(e)
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
        resp = requests.get(url, **_transport_options())
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

        conversation_memory.record_ha_targets_list(ligados, state="on")
        if len(ligados) == 1:
            eh_luz = ligados[0].startswith("luz")
            verbo = "apague" if eh_luz else "desligue"
            return f"Olha, no momento só a {ligados[0]} tá ligada — quer que eu {verbo} ela?"
        lista_txt = ", ".join(ligados[:-1]) + f" e {ligados[-1]}"
        return f"Conferi aqui em casa e estão ligadas: {lista_txt} — quer que eu desligue elas?"
    except (HAConfigError, requests.exceptions.SSLError) as e:
        return _trust_failure(e)
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
