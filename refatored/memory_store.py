import json
import math
import os
import re
import sqlite3
import logging
import threading
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    MEMORY_DB_PATH,
    MEMORY_TOP_K,
    MEMORY_USE_EMBEDDINGS,
    GEMINI_EMBEDDING_MODEL,
    GEMINI_API_KEY,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)

# Stopwords comuns em português + palavras meta de memória para filtragem de busca/exclusão
_STOPWORDS_PT = {
    "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "pro", "com", "sem", "que",
    "qual", "quais", "quem", "onde", "como", "quando", "quanto", "quantos", "foi",
    "era", "ser", "estar", "esta", "está", "tá", "ta", "sao", "são", "tem", "ter",
    "tenho", "tinha", "preciso", "precisa",
    "eu", "voce", "você", "ele", "ela", "eles", "elas", "meu", "minha", "meus",
    "minhas", "seu", "sua", "seus", "suas", "isso", "isto", "aquilo", "aurora",
    "esse", "essa", "este", "esta", "aquele", "aquela",
    "me", "te", "se", "lhe", "ai", "aí", "la", "lá", "aqui", "mesmo", "sobre",
    "sabe", "lembra", "lembrar", "lembre", "lembrete", "lembretes",
    "memoria", "memorias", "nota", "notas", "recado", "recados", "informacao",
    "dizer", "fala", "falar", "conta", "contar", "favor", "pode", "poderia",
}

# Prefixos naturais da fala coloquial antes do verbo de memória
_OPT_PREFIX = (
    r"^\s*(?:(?:ei|oi|olha(?:\s+s[óo])?|escuta)\s*,?\s*)?"
    r"(?:aurora\s*,?\s*)?"
    r"(?:por\s+favor\s*,?\s*)?"
    r"(?:(?:voc[êe]\s+)?pode(?:ria)?\s+|faz\s+um\s+favor\s*,?\s*|quero\s+que\s+(?:voc[êe]\s+)?)?"
)

# Padrões naturais ricos em português brasileiro para SALVAR na Memória da Casa
# (Evita capturar perguntas como "lembra qual é..." ou timers relativos "daqui a 5 min")
_RE_MEMORY_SAVE = re.compile(
    _OPT_PREFIX
    + r"(?:"
    r"(?:me\s+)?lembr(?:a|ar|e)(?:-me)?(?:\s+pra\s+mim|\s+a[íi])?\s+(?:que|de)\b|"
    r"n[ãa]o\s+(?:me\s+)?deix(?:a|e)(?:\s+eu)?\s+esquecer\s+(?:que|de)\b|"
    r"n[ãa]o\s+quero\s+esquecer\s+(?:que|de)\b|"
    r"(?:me\s+)?ajuda\s+a\s+lembrar\s+(?:que|de)\b|"
    r"guard(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim|\s+isso)?(?:\s+na\s+mem[óo]ria)?\s*(?:que|:)?|"
    r"memoriz(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim|\s+isso)?\s*(?:que|:)?|"
    r"salv(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim)?\s+na\s+mem[óo]ria\s*(?:que|:)?|"
    r"grav(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim)?(?:\s+na\s+mem[óo]ria)?\s*(?:que|:)?|"
    r"registr(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim)?(?:\s+na\s+mem[óo]ria)?\s*(?:que|:)?|"
    r"anot(?:a|ar|e)(?:\s+a[íi]|\s+pra\s+mim)?(?:\s+na\s+mem[óo]ria)?\s*(?:que|:)?"
    r")\s*"
    r"(?!(?:qual|quais|onde|como|quando|quem|que\s+horas|que\s+dia|se)\b)"
    r"(?!(?:daqui\s+a|em)\s+\d+\s*(?:segundos?|minutos?|horas?)\b)"
    r"(.+)$",
    re.IGNORECASE,
)

_RE_MEMORY_FORGET = re.compile(
    _OPT_PREFIX
    + r"(?:"
    r"esquec(?:e|er|a)\s+(?:(?:aquel[ea]|ess[ea]|o|a)\s+)?(?:(?:nota|mem[óo]ria|lembrete|recado|informa[çc][ãa]o)\s+)?|"
    r"(?:apag(?:a|ar|ue)|remov(?:a|e|er)|delet(?:a|ar|e))\s+(?:da\s+mem[óo]ria\s+|(?:(?:aquel[ea]|ess[ea]|o|a)\s+)?(?:nota|mem[óo]ria|lembrete|recado|informa[çc][ãa]o)\s+)"
    r")"
    r"(?:sobre\s+|do\s+|da\s+|de\s+|que\s+)?"
    r"(.+)$",
    re.IGNORECASE,
)

_RE_MEMORY_LIST = re.compile(
    r"\b(?:o\s+que\s+(?:voc[êe]\s+)?tem\s+(?:salvo\s+|guardado\s+)?na\s+mem[óo]ria|"
    r"quais\s+(?:s[ãa]o\s+)?(?:as\s+|os\s+)?(?:mem[óo]rias|lembretes|notas|recados)(?:\s+salv[oa]s?)?|"
    r"listar?\s+(?:as\s+|os\s+)?(?:mem[óo]rias|lembretes|notas)|"
    r"o\s+que\s+(?:voc[êe]\s+guardou|eu\s+pedi\s+pra\s+(?:voc[êe]\s+)?(?:lembrar|guardar|anotar))|"
    r"tem\s+algum(?:a)?\s+(?:lembrete|mem[óo]ria|nota|recado)\s+(?:salv[oa]|guardad[oa]|pra\s+mim))\b",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    """
    Remove acentos, converte para minúsculas e padroniza horários compactos ('04h' -> '4 horas')
    para indexação tolerante a variações de fala e transcrição.
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    sem_acento = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Padronizar '04h' / '4h' -> '4 horas' no índice de busca para casar '4 horas' com '04h'
    sem_acento = re.sub(r"\b0*(\d{1,2})h(\d{2})?\b", lambda m: f"{int(m.group(1))} horas {m.group(2) or ''}".strip(), sem_acento)
    return sem_acento


def _extract_keywords(text: str) -> List[str]:
    """Extrai termos significativos sem acentos e sem stopwords."""
    norm = _strip_accents(text)
    tokens = re.findall(r"[a-z0-9]{2,}", norm)
    return [tok for tok in tokens if tok not in _STOPWORDS_PT]


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Similaridade de cosseno em Python puro (0 dependências externas, ~1ms para centenas de itens)."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryStore:
    """
    Mini-RAG Doméstico ("Memória da Casa e da Família") ultra-leve baseado em SQLite nativo.
    Projetado especificamente para o Orange Pi 3 LTS:
      - Zero bibliotecas pesadas (sem ChromaDB, sem PyTorch, sem NumPy)
      - PRAGMAs otimizados (WAL + temp_store=MEMORY) para poupar escrita no cartão SD/eMMC
      - Busca híbrida: FTS5 / palavras-chave offline + Embeddings Semânticos opcionais via API gratuita Gemini
    """

    def __init__(self, db_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._db_path = db_path or os.getenv("MEMORY_DB_PATH", MEMORY_DB_PATH)
        self._fts_available = False
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        path_obj = Path(self._db_path)
        # O banco guarda dados pessoais e de saúde da família: diretório 700 e arquivo 600
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path_obj.parent, 0o700)
        except OSError:
            pass
        conn = sqlite3.connect(str(path_obj), timeout=5.0)
        try:
            os.chmod(path_obj, 0o600)
        except OSError:
            pass
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        content_norm TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'geral',
                        created_at TEXT NOT NULL,
                        embedding_json TEXT
                    );
                    """
                )
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                        USING fts5(content_norm, category);
                        """
                    )
                    self._fts_available = True
                except sqlite3.OperationalError:
                    logger.debug("SQLite FTS5 indisponível nesta compilação; usando busca lexical direta.")
                    self._fts_available = False
                conn.commit()
                self._initialized = True
            finally:
                conn.close()

    def _should_use_embeddings(self) -> bool:
        use_emb_env = os.getenv("MEMORY_USE_EMBEDDINGS")
        enabled = (
            use_emb_env.lower().strip() in ("1", "true", "yes", "on")
            if use_emb_env is not None
            else MEMORY_USE_EMBEDDINGS
        )
        if not enabled or requests is None:
            return False
        api_key = (os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()
        if not api_key or api_key.lower().startswith("suachave"):
            return False
        return True

    def _fetch_gemini_embedding(self, text: str, timeout: float = 4.0) -> Optional[List[float]]:
        """Obtém vetor de embedding via API gratuita do Google AI Studio (sem pesar CPU local)."""
        if not self._should_use_embeddings() or not text.strip():
            return None

        api_key = (os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()
        model = (os.getenv("GEMINI_EMBEDDING_MODEL") or GEMINI_EMBEDDING_MODEL).strip()
        model_slug = model if model.startswith("models/") else f"models/{model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_slug}:embedContent"

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        payload = {
            "model": model_slug,
            "content": {"parts": [{"text": text[:1500]}]},
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code != 200:
                logger.debug(
                    "Gemini Embedding HTTP %s: %s",
                    resp.status_code,
                    sanitize_for_log(resp.text[:200]),
                )
                return None
            data = resp.json()
            values = data.get("embedding", {}).get("values")
            if isinstance(values, list) and values:
                return [float(x) for x in values]
        except Exception as e:
            logger.debug("Falha ao consultar embedding Gemini (usando busca local SQLite): %s", e)
        return None

    def add_memory(self, content: str, category: str = "geral") -> int:
        """Salva um fato/lembrete permanente na Memória da Casa e retorna o ID."""
        texto = (content or "").strip().rstrip(".")
        if not texto:
            raise ValueError("Conteúdo da memória não pode ser vazio.")

        # Higienização: a memória é reinserida no prompt da LLM depois — nada de
        # caracteres de controle, quebras de linha ou textos gigantes (anti-poisoning).
        texto = re.sub(r"[\x00-\x1f\x7f]", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()[:500]
        if not texto:
            raise ValueError("Conteúdo da memória não pode ser vazio.")

        self._ensure_schema()
        texto_norm = _strip_accents(texto)
        cat = (category or "geral").strip().lower()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        embedding = self._fetch_gemini_embedding(texto)
        emb_json = json.dumps(embedding) if embedding else None

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO memories (content, content_norm, category, created_at, embedding_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (texto, texto_norm, cat, created_at, emb_json),
                )
                row_id = int(cur.lastrowid)
                if self._fts_available:
                    conn.execute(
                        "INSERT INTO memories_fts(rowid, content_norm, category) VALUES (?, ?, ?)",
                        (row_id, texto_norm, _strip_accents(cat)),
                    )
                conn.commit()
                logger.info(f"Nova memória salva (id={row_id}, cat='{cat}'): '{texto[:70]}'")
                return row_id
            finally:
                conn.close()

    def count(self) -> int:
        """Retorna total de memórias armazenadas (evita chamadas desnecessárias se vazio)."""
        if not os.path.exists(self._db_path):
            return 0
        self._ensure_schema()
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute("SELECT COUNT(*) AS total FROM memories").fetchone()
                return int(row["total"]) if row else 0
            finally:
                conn.close()

    def list_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Lista as memórias mais recentes salvas na casa."""
        if not os.path.exists(self._db_path):
            return []
        self._ensure_schema()
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, content, category, created_at FROM memories ORDER BY id DESC LIMIT ?",
                    (max(1, limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def delete_matching(self, query: str) -> int:
        """Remove memórias que correspondam aos termos informados pelo usuário."""
        if not os.path.exists(self._db_path):
            return 0
        keywords = _extract_keywords(query)
        if not keywords:
            return 0

        self._ensure_schema()
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("SELECT id, content_norm FROM memories").fetchall()
                ids_to_delete = [
                    int(r["id"])
                    for r in rows
                    if all(kw in r["content_norm"] for kw in keywords)
                ]
                if not ids_to_delete:
                    return 0

                placeholders = ",".join("?" for _ in ids_to_delete)
                conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", ids_to_delete)
                if self._fts_available:
                    conn.execute(
                        f"DELETE FROM memories_fts WHERE rowid IN ({placeholders})",
                        ids_to_delete,
                    )
                conn.commit()
                logger.info(f"{len(ids_to_delete)} memória(s) removida(s) para '{query}'.")
                return len(ids_to_delete)
            finally:
                conn.close()

    def search(self, query: str, top_k: Optional[int] = None) -> List[str]:
        """
        Busca híbrida (FTS5 + sobreposição lexical + similaridade semântica opcional).
        Se o banco estiver vazio, retorna [] em < 0.1ms sem chamadas externas.
        """
        if not query or not query.strip():
            return []
        if self.count() == 0:
            return []

        k = top_k or int(os.getenv("MEMORY_TOP_K", str(MEMORY_TOP_K)))
        keywords = _extract_keywords(query)

        with self._lock:
            conn = self._get_connection()
            try:
                fts_scores: Dict[int, float] = {}
                if self._fts_available and keywords:
                    fts_expr = " OR ".join(f'"{kw}"*' for kw in keywords[:8])
                    try:
                        fts_rows = conn.execute(
                            """
                            SELECT rowid, bm25(memories_fts) AS rank_score
                            FROM memories_fts
                            WHERE memories_fts MATCH ?
                            LIMIT 20
                            """,
                            (fts_expr,),
                        ).fetchall()
                        for r in fts_rows:
                            # bm25 no SQLite retorna valores negativos (quanto menor, mais relevante)
                            fts_scores[int(r["rowid"])] = max(0.2, min(1.0, -float(r["rank_score"]) * 0.25 + 0.4))
                    except sqlite3.OperationalError:
                        pass

                all_rows = conn.execute(
                    "SELECT id, content, content_norm, embedding_json FROM memories ORDER BY id DESC LIMIT 500"
                ).fetchall()
            finally:
                conn.close()

        has_any_embedding = any(bool(r["embedding_json"]) for r in all_rows)
        query_vec = (
            self._fetch_gemini_embedding(query)
            if (has_any_embedding and self._should_use_embeddings())
            else None
        )

        scored: List[tuple[float, str]] = []
        for row in all_rows:
            row_id = int(row["id"])
            content_norm = row["content_norm"]

            # 1. Pontuação lexical (palavras-chave e prefixos / radicais simples)
            lex_score = fts_scores.get(row_id, 0.0)
            if keywords:
                hits = 0.0
                for kw in keywords:
                    if kw in content_norm:
                        hits += 1.0
                    elif len(kw) >= 5 and kw[:4] in content_norm:
                        hits += 0.5
                overlap = hits / len(keywords)
                lex_score = max(lex_score, overlap)

            # 2. Pontuação semântica (cosseno via embedding) se disponível
            sem_score = 0.0
            if query_vec and row["embedding_json"]:
                try:
                    mem_vec = json.loads(row["embedding_json"])
                    sim = cosine_similarity(query_vec, mem_vec)
                    if sim >= 0.62:
                        sem_score = sim
                except Exception:
                    pass

            # Fusão híbrida: aceita match lexical forte OU match semântico forte
            final_score = max(lex_score, sem_score, (0.55 * lex_score + 0.45 * sem_score))
            if final_score >= 0.34:
                scored.append((final_score, row["content"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [content for _, content in scored[:k]]


# Instância global singleton do banco de memórias da casa
memory_store = MemoryStore()


def handle_memory_command_local(
    mensagem: str,
    store: Optional[MemoryStore] = None,
) -> Optional[str]:
    """
    Trata comandos explícitos de voz para salvar, listar ou apagar memórias da casa
    diretamente no Fast-Path local (sem gastar tokens de LLM!).
    """
    if not mensagem:
        return None

    target_store = store or memory_store
    texto = mensagem.strip()

    # 1. Salvar fato na memória (apenas afirmações/pedidos, nunca perguntas com '?')
    if not texto.endswith("?"):
        m_save = _RE_MEMORY_SAVE.match(texto)
        if m_save:
            fato = m_save.group(1).strip().rstrip(".!")
            if len(fato) >= 3:
                target_store.add_memory(fato)
                return f"Pode deixar, já guardei na memória: {fato}."

    # 2. Esquecer / apagar memória
    m_forget = _RE_MEMORY_FORGET.match(texto)
    if m_forget:
        termo = m_forget.group(1).strip().rstrip(".!?")
        removidos = target_store.delete_matching(termo)
        if removidos > 0:
            return "Prontinho, apaguei essa informação da minha memória."
        return "Olha, procurei aqui e não achei nenhuma memória salva com esses termos."

    # 3. Listar memórias salvas
    if _RE_MEMORY_LIST.search(texto):
        itens = target_store.list_memories(limit=5)
        if not itens:
            return "Por enquanto eu ainda não tenho nenhuma informação guardada na memória da casa."
        resumo = "; ".join(item["content"] for item in itens)
        return f"Olha, as últimas informações que você pediu pra eu guardar foram: {resumo}."

    return None
