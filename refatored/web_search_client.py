import html
import os
import re
import time
import logging
import threading
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    WEB_SEARCH_ENABLED,
    WEB_SEARCH_PROVIDER,
    WEB_SEARCH_FALLBACK_PROVIDERS,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_TIMEOUT,
    SERPER_API_KEY,
    TAVILY_API_KEY,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# ALIASES E PRESETS DE BUSCADORES SUPORTADOS
# ==============================================================================

SEARCH_PROVIDER_ALIASES: Dict[str, str] = {
    "auto": "auto",
    "serper": "serper",
    "google": "serper",
    "serper.dev": "serper",
    "tavily": "tavily",
    "free": "free",
    "ddg": "free",
    "duckduckgo": "free",
    "rss": "free",
    "gratuito": "free",
}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _clean_html_text(raw_html: str, max_len: int = 260) -> str:
    """Remove tags HTML, decodifica entidades e compacta espaços."""
    if not raw_html:
        return ""
    sem_tags = re.sub(r"<[^>]+>", " ", raw_html)
    decodificado = html.unescape(sem_tags)
    limpo = re.sub(r"\s+", " ", decodificado).strip()
    if len(limpo) > max_len:
        return limpo[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return limpo


def _is_valid_key(key_val: str) -> bool:
    if not key_val:
        return False
    low = key_val.strip().lower()
    return bool(low) and not low.startswith("suachave") and low not in ("none", "changeme")


class WebSearchClient:
    """
    Cliente universal e pluggável de Busca na Web em Tempo Real (Web Grounding / RAG Web),
    seguindo a mesma arquitetura modular do LLMClient e do TTSClient.

    Provedores suportados (100% Free-Tier friendly e leves para o Orange Pi 3 LTS):
      - 'serper' : Google Brasil em tempo real via Serper.dev (2.500 buscas grátis, inclui placares/AnswerBox)
      - 'tavily' : Tavily AI Search (1.000 buscas grátis/mês renováveis sem cartão)
      - 'free'   : Modo 100% gratuito sem API Key (DuckDuckGo Brasil + Google News RSS Brasil via stdlib)
      - 'auto'   : Usa automaticamente chaves configuradas (serper -> tavily) e cai para 'free' como garantia!
    """

    def __init__(self, cache_ttl_seconds: int = 120):
        self._lock = threading.RLock()
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Tuple[float, List[Dict[str, str]], str]] = {}

    @staticmethod
    def normalize_provider(name: str) -> str:
        raw = (name or "auto").lower().strip()
        return SEARCH_PROVIDER_ALIASES.get(raw, raw)

    def is_enabled(self) -> bool:
        env_val = os.getenv("WEB_SEARCH_ENABLED")
        if env_val is not None:
            return env_val.lower().strip() in ("1", "true", "yes", "on")
        return WEB_SEARCH_ENABLED

    def get_provider_chain(self, provider_override: Optional[str] = None) -> List[str]:
        """
        Determina a ordem de provedores a consultar sem duplicatas.
        No modo 'auto', prioriza provedores com chave válida configurada e garante 'free' no final.
        """
        primary = self.normalize_provider(
            provider_override or os.getenv("WEB_SEARCH_PROVIDER", WEB_SEARCH_PROVIDER)
        )
        has_serper = _is_valid_key(os.getenv("SERPER_API_KEY", SERPER_API_KEY))
        has_tavily = _is_valid_key(os.getenv("TAVILY_API_KEY", TAVILY_API_KEY))

        chain: List[str] = []
        if primary == "auto":
            if has_serper:
                chain.append("serper")
            if has_tavily:
                chain.append("tavily")
            chain.append("free")
        else:
            chain.append(primary)

        raw_fallbacks = os.getenv(
            "WEB_SEARCH_FALLBACK_PROVIDERS", WEB_SEARCH_FALLBACK_PROVIDERS
        )
        if raw_fallbacks:
            for item in raw_fallbacks.split(","):
                norm = self.normalize_provider(item)
                if norm == "auto" or not norm:
                    continue
                if norm == "serper" and not has_serper and primary != "serper":
                    continue
                if norm == "tavily" and not has_tavily and primary != "tavily":
                    continue
                if norm not in chain:
                    chain.append(norm)

        if "free" not in chain:
            chain.append("free")

        return chain

    # ------------------------------------------------------------------
    # PROVEDOR 1: SERPER.DEV (GOOGLE SEARCH BRASIL + PLACARES ESPORTIVOS)
    # ------------------------------------------------------------------

    def _search_serper(
        self, query: str, max_results: int, timeout: int
    ) -> Optional[List[Dict[str, str]]]:
        if requests is None:
            return None

        api_key = os.getenv("SERPER_API_KEY", SERPER_API_KEY).strip()
        if not _is_valid_key(api_key):
            logger.debug("SERPER_API_KEY não configurada; pulando Serper.")
            return None

        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "gl": "br",
            "hl": "pt-br",
            "num": max_results,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code != 200:
                logger.warning(
                    f"[SERPER] HTTP {resp.status_code}: {sanitize_for_log(resp.text[:200])}"
                )
                return None

            data = resp.json()
            if not isinstance(data, dict):
                return None

            results: List[Dict[str, str]] = []

            # 1. Placar esportivo direto do Google (Sports Results)
            sports = data.get("sportsResults")
            if isinstance(sports, dict):
                titulo_esp = sports.get("title") or "Placar Esportivo"
                spotlight = sports.get("gameSpotlight")
                if isinstance(spotlight, dict):
                    home = spotlight.get("homeTeam", {})
                    away = spotlight.get("awayTeam", {})
                    resumo_jogo = (
                        f"{home.get('name', '')} {home.get('score', '')} x "
                        f"{away.get('score', '')} {away.get('name', '')} "
                        f"({spotlight.get('stage', '')} {spotlight.get('date', '')})"
                    ).strip()
                    results.append({"title": str(titulo_esp), "snippet": resumo_jogo})
                for game in (sports.get("games") or [])[:2]:
                    if isinstance(game, dict):
                        t1 = game.get("homeTeam", {})
                        t2 = game.get("awayTeam", {})
                        txt = (
                            f"{t1.get('name', '')} {t1.get('score', '')} x "
                            f"{t2.get('score', '')} {t2.get('name', '')} "
                            f"- {game.get('status', '')} {game.get('date', '')}"
                        ).strip()
                        results.append({"title": str(titulo_esp), "snippet": txt})

            # 2. Answer Box oficial do Google (cotações, respostas diretas, placares rápidos)
            ans = data.get("answerBox")
            if isinstance(ans, dict):
                ans_title = ans.get("title") or "Resposta Direta Google"
                ans_body = ans.get("answer") or ans.get("snippet") or ""
                if ans_body:
                    results.append(
                        {"title": str(ans_title), "snippet": _clean_html_text(str(ans_body))}
                    )

            # 3. Knowledge Graph
            kg = data.get("knowledgeGraph")
            if isinstance(kg, dict) and kg.get("description"):
                results.append(
                    {
                        "title": str(kg.get("title") or "Resumo"),
                        "snippet": _clean_html_text(str(kg.get("description"))),
                    }
                )

            # 4. Resultados orgânicos
            for item in (data.get("organic") or [])[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = _clean_html_text(str(item.get("title") or ""), max_len=120)
                snippet = _clean_html_text(str(item.get("snippet") or ""))
                date_str = str(item.get("date") or "").strip()
                if date_str:
                    snippet = f"[{date_str}] {snippet}"
                if title or snippet:
                    results.append({"title": title, "snippet": snippet})

            return results[: max_results + 1] if results else None
        except Exception as e:
            logger.warning(f"Erro ao pesquisar via Serper: {sanitize_for_log(str(e))}")
            return None

    # ------------------------------------------------------------------
    # PROVEDOR 2: TAVILY AI SEARCH (1.000 CRÉDITOS GRÁTIS / MÊS)
    # ------------------------------------------------------------------

    def _search_tavily(
        self, query: str, max_results: int, timeout: int
    ) -> Optional[List[Dict[str, str]]]:
        if requests is None:
            return None

        api_key = os.getenv("TAVILY_API_KEY", TAVILY_API_KEY).strip()
        if not _is_valid_key(api_key):
            logger.debug("TAVILY_API_KEY não configurada; pulando Tavily.")
            return None

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": max_results,
        }

        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                logger.warning(
                    f"[TAVILY] HTTP {resp.status_code}: {sanitize_for_log(resp.text[:200])}"
                )
                return None

            data = resp.json()
            if not isinstance(data, dict):
                return None

            results: List[Dict[str, str]] = []
            direct_answer = (data.get("answer") or "").strip()
            if direct_answer:
                results.append(
                    {
                        "title": "Síntese Direta",
                        "snippet": _clean_html_text(direct_answer, max_len=320),
                    }
                )

            for item in (data.get("results") or [])[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = _clean_html_text(str(item.get("title") or ""), max_len=120)
                content = _clean_html_text(str(item.get("content") or ""))
                pub_date = str(item.get("published_date") or "").strip()
                if pub_date:
                    content = f"[{pub_date}] {content}"
                if title or content:
                    results.append({"title": title, "snippet": content})

            return results[: max_results + 1] if results else None
        except Exception as e:
            logger.warning(f"Erro ao pesquisar via Tavily: {sanitize_for_log(str(e))}")
            return None

    # ------------------------------------------------------------------
    # PROVEDOR 3: MODO 100% GRATUITO SEM CHAVE (DDG BRASIL + GOOGLE NEWS RSS BR)
    # ------------------------------------------------------------------

    def _fetch_duckduckgo_html_br(
        self, query: str, max_results: int, timeout: int
    ) -> List[Dict[str, str]]:
        if requests is None:
            return []

        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        }
        data = {"q": query, "kl": "br-pt"}

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=timeout)
            if resp.status_code != 200 or not resp.text:
                return []

            html_body = resp.text
            titles = re.findall(
                r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
                html_body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            snippets = re.findall(
                r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|'
                r'<div[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>',
                html_body,
                flags=re.IGNORECASE | re.DOTALL,
            )

            extracted: List[Dict[str, str]] = []
            for idx, raw_title in enumerate(titles[:max_results]):
                t_clean = _clean_html_text(raw_title, max_len=120)
                s_clean = ""
                if idx < len(snippets):
                    pair = snippets[idx]
                    raw_snip = pair[0] or pair[1]
                    s_clean = _clean_html_text(raw_snip)
                if t_clean or s_clean:
                    extracted.append({"title": t_clean, "snippet": s_clean})
            return extracted
        except Exception as e:
            logger.debug(f"DuckDuckGo HTML BR indisponível: {e}")
            return []

    def _fetch_google_news_rss_br(
        self, query: str, max_results: int, timeout: int
    ) -> List[Dict[str, str]]:
        if requests is None:
            return []

        eh_consulta_esportiva = bool(
            re.search(
                r"\b(?:jogo|partida|rodada|placar|campeonato|copa|sele[çc][ãa]o|amistoso)\b",
                query,
                re.IGNORECASE,
            )
        )
        tem_ano_explicito = bool(re.search(r"\b(?:19|20)\d{2}\b", query))
        # Remove prefixos conversacionais ('quanto foi o', 'qual foi o', '?') para melhorar precisão no RSS
        rss_query = re.sub(
            r"^\s*(?:aurora[\s,]+)?(?:me\s+(?:diz|fala|conta)\s+)?(?:quanto\s+(?:foi|ficou|t[áa]|est[áa])|qual\s+(?:foi|é|[ée]))\s+(?:o\s+|a\s+)?",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip(" ?!.") or query
        if eh_consulta_esportiva and "placar" not in rss_query.lower():
            rss_query = f"placar {rss_query}"
        if not tem_ano_explicito and "when:" not in rss_query.lower():
            rss_query = f"{rss_query} when:14d"

        encoded_q = quote_plus(rss_query)
        url = (
            f"https://news.google.com/rss/search?q={encoded_q}"
            f"&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        )
        headers = {"User-Agent": _USER_AGENT}

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200 or not resp.content:
                return []

            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            items_xml = channel.findall("item") if channel is not None else []

            # Se a janela recente de 14 dias não achou nada, tenta sem restrição de data
            if not items_xml and " when:14d" in rss_query:
                url_broad = (
                    f"https://news.google.com/rss/search?q={quote_plus(rss_query.replace(' when:14d', ''))}"
                    f"&hl=pt-BR&gl=BR&ceid=BR:pt-419"
                )
                resp_b = requests.get(url_broad, headers=headers, timeout=timeout)
                if resp_b.status_code == 200 and resp_b.content:
                    root_b = ET.fromstring(resp_b.content)
                    ch_b = root_b.find("channel")
                    items_xml = ch_b.findall("item") if ch_b is not None else []

            if not items_xml:
                return []

            candidates: List[Dict[str, str]] = []
            scan_limit = max(max_results * 3, 10)
            for item in items_xml[:scan_limit]:
                title = _clean_html_text(item.findtext("title") or "", max_len=160)
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = _clean_html_text(item.findtext("description") or "")
                # Remover repetição exata do título dentro da descrição do RSS
                if desc and title and desc.startswith(title[:40]):
                    desc = ""
                data_curta = pub_date[:16] if pub_date else ""
                resumo = f"[{data_curta}] {desc}".strip() if (data_curta or desc) else ""
                if title:
                    candidates.append({"title": title, "snippet": resumo})

            # Se for consulta esportiva, prioriza manchetes da equipe principal com placar explícito ('3 x 2', '3-2')
            if eh_consulta_esportiva and candidates:
                re_placar = re.compile(r"\b\d{1,2}\s*(?:[xX×\-–]|a)\s*\d{1,2}\b")
                pediu_base = bool(re.search(r"\bsub[\s-]?\d{2}\b", query, re.IGNORECASE))

                def _score_rank(item_dict: Dict[str, str]) -> int:
                    txt = f"{item_dict['title']} {item_dict['snippet']}"
                    tem_num = bool(re_placar.search(txt))
                    eh_base = bool(re.search(r"\bsub[\s-]?\d{2}\b", txt, re.IGNORECASE))
                    if tem_num and (pediu_base or not eh_base):
                        return 0
                    if not eh_base:
                        return 1
                    return 2

                candidates.sort(key=_score_rank)

            return candidates[:max_results]
        except Exception as e:
            logger.debug(f"Google News RSS BR indisponível: {e}")
            return []

    def _search_free(
        self, query: str, max_results: int, timeout: int
    ) -> Optional[List[Dict[str, str]]]:
        """
        Combina resultados orgânicos da web (DuckDuckGo BR) com manchetes frescas do
        Google Notícias Brasil (RSS oficial), funcionando sem nenhuma chave de API.
        """
        ddg_items = self._fetch_duckduckgo_html_br(query, max_results=max_results, timeout=timeout)
        rss_items = self._fetch_google_news_rss_br(query, max_results=max_results, timeout=timeout)

        combined: List[Dict[str, str]] = []
        seen_titles = set()

        # Intercalar para garantir tanto fatos gerais da web quanto notícias de última hora (jogos, placares)
        max_len = max(len(ddg_items), len(rss_items))
        for i in range(max_len):
            for source_list in (ddg_items, rss_items):
                if i < len(source_list):
                    entry = source_list[i]
                    norm_t = entry.get("title", "").lower()[:60]
                    if norm_t and norm_t not in seen_titles:
                        seen_titles.add(norm_t)
                        combined.append(entry)
                    if len(combined) >= max_results + 1:
                        return combined

        return combined if combined else None

    # ------------------------------------------------------------------
    # ORQUESTRADOR COM CACHE CURTO E CADEIA DE FALLBACK
    # ------------------------------------------------------------------

    def buscar(
        self,
        query: str,
        provider_override: Optional[str] = None,
    ) -> Optional[Tuple[List[Dict[str, str]], str]]:
        """
        Executa a pesquisa na web percorrendo a cadeia de provedores configurada.
        Retorna (lista_de_resultados, provedor_usado) ou None.
        """
        if not self.is_enabled():
            logger.info("Busca na web desativada via WEB_SEARCH_ENABLED=false.")
            return None

        consulta = (query or "").strip()
        if not consulta:
            return None

        cache_key = f"{provider_override or 'default'}::{consulta.lower()}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) <= self._cache_ttl:
                logger.debug(f"Retornando busca web do cache em RAM para: '{consulta}'")
                return cached[1], cached[2]

        max_res = max(
            1,
            min(6, int(os.getenv("WEB_SEARCH_MAX_RESULTS", str(WEB_SEARCH_MAX_RESULTS)))),
        )
        timeout = int(os.getenv("WEB_SEARCH_TIMEOUT", str(WEB_SEARCH_TIMEOUT)))
        chain = self.get_provider_chain(provider_override=provider_override)

        for idx, prov in enumerate(chain):
            if idx > 0:
                logger.info(f"Fallback de busca web ({idx}/{len(chain) - 1}): [{prov.upper()}]...")
            else:
                logger.info(f"Pesquisando na web [{prov.upper()}]: '{consulta}'")

            resultados: Optional[List[Dict[str, str]]] = None
            if prov == "serper":
                resultados = self._search_serper(consulta, max_res, timeout)
            elif prov == "tavily":
                resultados = self._search_tavily(consulta, max_res, timeout)
            elif prov == "free":
                resultados = self._search_free(consulta, max_res, timeout)
            else:
                logger.warning(f"Provedor de busca web desconhecido: '{prov}'")

            if resultados:
                with self._lock:
                    if len(self._cache) >= 32:
                        self._cache.clear()
                    self._cache[cache_key] = (now, resultados, prov)
                return resultados, prov

        logger.warning(f"Nenhum resultado encontrado na web para: '{consulta}'")
        return None

    def buscar_contexto_formatado(
        self,
        query: str,
        provider_override: Optional[str] = None,
    ) -> str:
        """
        Executa a busca e devolve um bloco enxuto (~250-350 tokens) pronto para
        a LLM transformar em resposta falada natural para o sintetizador de voz.
        """
        res = self.buscar(query, provider_override=provider_override)
        hoje = datetime.now().strftime("%d/%m/%Y")

        if not res:
            return (
                f"Data atual: {hoje}. Não foi possível obter resultados na internet "
                f"para '{query}' no momento."
            )

        itens, provedor = res
        linhas = [
            f"Resultados atualizados da internet (Fonte: {provedor}, Data de hoje: {hoje}):"
        ]
        for idx, item in enumerate(itens, start=1):
            titulo = item.get("title", "").strip()
            trecho = item.get("snippet", "").strip()
            if titulo and trecho:
                linhas.append(f"{idx}. {titulo} — {trecho}")
            elif titulo:
                linhas.append(f"{idx}. {titulo}")
            elif trecho:
                linhas.append(f"{idx}. {trecho}")

        linhas.append(
            "Instrução para fala: sintetize o resultado mais relevante e recente em 1 a 3 frases "
            "naturais para voz, sem citar links, dizendo placares por extenso (ex: 'três a dois')."
        )
        return "\n".join(linhas)


# Instância global singleton do cliente de busca web
web_search_client = WebSearchClient()
