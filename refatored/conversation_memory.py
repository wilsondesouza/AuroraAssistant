import os
import re
import time
import logging
import threading
from collections import deque
from typing import List, Dict, Optional, Tuple

from refatored.config import (
    CONVERSATION_HISTORY_TURNS,
    CONVERSATION_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

# Frases curtas de encerramento/recusa educada durante o modo de conversa contínua (follow-up)
_RE_DISMISSAL = re.compile(
    r"^\s*(?:"
    r"n[ãa]o|n[ãa]o\s+precisa|agora\s+n[ãa]o|deixa\s+assim(?:\s+mesmo)?|"
    r"deixa\s+quieto|deixa\s+aces[oa]|deixa\s+ligad[oa]|deixa\s+apagad[oa]|deixa\s+desligad[oa]|pode\s+deixar(?:\s+assim)?|"
    r"(?:n[ãa]o\s*,?\s*)?(?:muito\s+)?(?:obrigad[oa]|valeu|brigad[oa]|s[óo]\s+isso|era\s+s[óo]\s+isso|"
    r"por\s+enquanto\s+[ée]\s+s[óo]|nada\s+n[ãa]o|t[áa]\s+[óo]timo|t[áa]\s+bom|"
    r"beleza(?:\s*,?\s*obrigad[oa])?|tchau|at[ée]\s+mais|at[ée]\s+logo|pode\s+parar|encerrar)"
    r")\s*[.!]*\s*$",
    re.IGNORECASE,
)


def is_dismissal_phrase(texto: str) -> bool:
    """
    Identifica respostas curtas de encerramento educado no modo follow-up
    (ex: 'Não, obrigado!', 'Só isso', 'Valeu'), sem bloquear frases longas
    que contenham um novo pedido real (ex: 'Obrigado, agora apaga a luz').
    """
    if not texto:
        return False
    limpo = texto.strip()
    if len(limpo.split()) > 6:
        return False
    return bool(_RE_DISMISSAL.match(limpo))


def should_expect_followup(resposta_assistente: str) -> bool:
    """
    Retorna True quando a resposta da Aurora termina com uma pergunta ('?'),
    sinalizando que o modo de voz pode abrir escuta automática de continuação.
    """
    if not resposta_assistente:
        return False
    limpo = resposta_assistente.strip().rstrip("\"'”’ ")
    return limpo.endswith("?")


class ConversationMemory:
    """
    Gerenciador leve de memória de curto prazo em RAM (~2 KB), ideal para Orange Pi 3 LTS:
      - Janela deslizante curta (ex: últimos 3 pares usuário/assistente)
      - Expiração automática por inatividade (TTL em segundos)
      - Memória do último dispositivo acionado no Home Assistant (resolução de 'ela'/'isso')
      - Montagem de mensagens amigável a Prompt Caching / KV-Cache (system prompt fixo no índice 0)
    """

    def __init__(
        self,
        max_turns: Optional[int] = None,
        ttl_seconds: Optional[float] = None,
    ):
        self._lock = threading.RLock()
        turns = max_turns or int(
            os.getenv("CONVERSATION_HISTORY_TURNS", str(CONVERSATION_HISTORY_TURNS))
        )
        self._max_turns = max(1, turns)
        self._ttl_seconds = float(
            ttl_seconds
            if ttl_seconds is not None
            else os.getenv("CONVERSATION_TTL_SECONDS", str(CONVERSATION_TTL_SECONDS))
        )
        self._messages: deque[Dict[str, str]] = deque(maxlen=self._max_turns * 2)
        self._last_interaction_ts: float = 0.0
        self._last_ha_target: Optional[str] = None
        self._last_ha_state: Optional[str] = None
        self._last_ha_targets_list: List[str] = []
        self._last_ha_ts: float = 0.0

    def _expire_if_needed(self, now: Optional[float] = None) -> None:
        current = now if now is not None else time.monotonic()
        if (
            self._messages
            and self._last_interaction_ts > 0
            and (current - self._last_interaction_ts) > self._ttl_seconds
        ):
            logger.debug("Janela de contexto expirada por inatividade; limpando histórico curto.")
            self._messages.clear()

        if (
            (self._last_ha_target or self._last_ha_targets_list)
            and self._last_ha_ts > 0
            and (current - self._last_ha_ts) > self._ttl_seconds
        ):
            self._last_ha_target = None
            self._last_ha_state = None
            self._last_ha_targets_list = []

    def clear(self) -> None:
        """Limpa imediatamente histórico conversacional e referência de dispositivo."""
        with self._lock:
            self._messages.clear()
            self._last_interaction_ts = 0.0
            self._last_ha_target = None
            self._last_ha_state = None
            self._last_ha_targets_list = []
            self._last_ha_ts = 0.0

    def add_turn(self, user_message: str, assistant_message: str) -> None:
        """Registra um par de turno (usuário -> Aurora) na janela deslizante."""
        if not user_message or not assistant_message:
            return
        with self._lock:
            now = time.monotonic()
            self._expire_if_needed(now)
            self._messages.append({"role": "user", "content": user_message.strip()})
            self._messages.append({"role": "assistant", "content": assistant_message.strip()})
            self._last_interaction_ts = now

    def get_history(self) -> List[Dict[str, str]]:
        """Retorna cópia dos turnos ativos dentro do TTL."""
        with self._lock:
            self._expire_if_needed()
            return list(self._messages)

    def record_ha_target(
        self,
        target_name: str,
        state: Optional[str] = None,
    ) -> None:
        """Salva o último dispositivo canônico do HA consultado ou acionado recentemente."""
        if not target_name:
            return
        with self._lock:
            now = time.monotonic()
            self._last_ha_target = target_name.strip().lower()
            if state is not None:
                self._last_ha_state = state.strip().lower()
            self._last_ha_targets_list = [self._last_ha_target]
            self._last_ha_ts = now
            self._last_interaction_ts = now

    def record_ha_targets_list(
        self,
        targets: List[str],
        state: Optional[str] = "on",
    ) -> None:
        """Salva múltiplos dispositivos observados em uma conferência geral de estado."""
        limpos = [t.strip().lower() for t in targets if t and t.strip()]
        with self._lock:
            now = time.monotonic()
            self._last_ha_targets_list = limpos
            self._last_ha_target = limpos[0] if len(limpos) == 1 else (limpos[-1] if limpos else None)
            self._last_ha_state = state.strip().lower() if state else None
            self._last_ha_ts = now
            self._last_interaction_ts = now

    def get_last_ha_target(self) -> Optional[str]:
        """Recupera o último dispositivo do Home Assistant caso ainda dentro do TTL."""
        with self._lock:
            self._expire_if_needed()
            return self._last_ha_target

    def get_last_ha_context(self) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Retorna (ultimo_dispositivo, ultimo_estado_observado, lista_dispositivos_recentes)."""
        with self._lock:
            self._expire_if_needed()
            return (
                self._last_ha_target,
                self._last_ha_state,
                list(self._last_ha_targets_list),
            )

    def build_messages(
        self,
        static_system_prompt: str,
        user_message: str,
        rag_facts: Optional[List[str]] = None,
        ha_context_hint: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Constrói o array OpenAI Chat Completions mantendo o system_prompt estático
        intacto na posição 0 (otimizado para KV-Cache do Ollama e Prompt Caching em nuvem).
        """
        history = self.get_history()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": static_system_prompt}
        ]
        messages.extend(history)

        blocos_dinamicos: List[str] = []
        if rag_facts:
            linhas = "\n".join(f"- {fato}" for fato in rag_facts if fato)
            if linhas:
                blocos_dinamicos.append(
                    "Memórias e informações pessoais registradas na casa relevantes "
                    "para apoiar sua resposta caso o usuário esteja perguntando sobre elas:\n"
                    f"{linhas}"
                )
        if ha_context_hint:
            blocos_dinamicos.append(ha_context_hint)

        if blocos_dinamicos:
            messages.append(
                {
                    "role": "system",
                    "content": "\n\n".join(blocos_dinamicos),
                }
            )

        messages.append({"role": "user", "content": user_message})
        return messages


# Instância global singleton da memória de curto prazo
conversation_memory = ConversationMemory()
