import os
import unittest
from unittest.mock import patch, MagicMock

from refatored.web_search_client import WebSearchClient
from refatored.tts_client import prepare_text_for_speech
from refatored.skills import execute_tool_call
from refatored.intent_router import IntentRouter


class TestWebSearchClientAndPhonetics(unittest.TestCase):
    """Testa cliente pluggável de busca web, placares esportivos e fallback gratuito."""

    def setUp(self):
        from refatored.conversation_memory import conversation_memory
        from refatored.llm_client import llm_client
        conversation_memory.clear()
        llm_client.last_call_rejected_tools = False

    def test_score_and_usd_phonetics_for_tts(self):
        bruto = "O Brasil perdeu para o Japão. O Placar foi 3x2 e o ingresso custou US$ 45,50!"
        limpo = prepare_text_for_speech(bruto)
        self.assertIn("3 a 2", limpo)
        self.assertNotIn("3x2", limpo)
        self.assertIn("45 dólares e 50 centavos", limpo)

    def test_auto_provider_skips_placeholder_keys_and_uses_free(self):
        client = WebSearchClient()
        with patch.dict(
            os.environ,
            {
                "WEB_SEARCH_PROVIDER": "auto",
                "SERPER_API_KEY": "SuaChaveSerper",
                "TAVILY_API_KEY": "SuaChaveTavily",
            },
            clear=False,
        ):
            self.assertEqual(client.get_provider_chain(), ["free"])

        with patch.dict(
            os.environ,
            {
                "WEB_SEARCH_PROVIDER": "auto",
                "SERPER_API_KEY": "real_serper_123",
                "TAVILY_API_KEY": "tvly-real_456",
            },
            clear=False,
        ):
            self.assertEqual(client.get_provider_chain(), ["serper", "tavily", "free"])

    @patch("refatored.web_search_client.requests")
    def test_serper_extracts_google_sports_scoreboard_and_caches(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sportsResults": {
                "title": "Amistoso Internacional",
                "gameSpotlight": {
                    "homeTeam": {"name": "Japão", "score": "3"},
                    "awayTeam": {"name": "Brasil", "score": "2"},
                    "stage": "Encerrado",
                    "date": "Ontem",
                },
            },
            "organic": [
                {
                    "title": "Japão vira sobre o Brasil e vence por 3 a 2",
                    "snippet": "Seleção brasileira abriu vantagem, mas sofreu a virada no segundo tempo.",
                }
            ],
        }
        mock_requests.post.return_value = mock_resp

        client = WebSearchClient()
        with patch.dict(
            os.environ,
            {"WEB_SEARCH_PROVIDER": "serper", "SERPER_API_KEY": "serper_real_key"},
            clear=False,
        ):
            contexto = client.buscar_contexto_formatado("quanto foi o jogo do Brasil")
            self.assertIn("Japão 3 x 2 Brasil", contexto)
            self.assertIn("sofreu a virada", contexto)

            # Segunda chamada idêntica usa cache em RAM sem nova requisição HTTP
            _ = client.buscar_contexto_formatado("quanto foi o jogo do Brasil")
            self.assertEqual(mock_requests.post.call_count, 1)

    @patch("refatored.web_search_client.requests")
    def test_fallback_from_tavily_failure_to_free_google_news_rss(self, mock_requests):
        # 1. Tavily falha com HTTP 429
        resp_tavily_429 = MagicMock()
        resp_tavily_429.status_code = 429
        resp_tavily_429.text = "monthly quota exceeded"

        # 2. DDG HTML retorna 1 resultado
        resp_ddg = MagicMock()
        resp_ddg.status_code = 200
        resp_ddg.text = (
            '<a class="result__a" href="#">Brasil perde amistoso para o Japão</a>'
            '<a class="result__snippet">Placar terminou em 3 a 2 em Tóquio.</a>'
        )

        # 3. Google News RSS BR retorna XML válido
        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Jap\xc3\xa3o vence Brasil por 3 a 2 de virada - ge.globo</title>
            <pubDate>Sat, 14 Nov 2026 22:00:00 GMT</pubDate>
            <description>Partida movimentada terminou 3x2.</description>
          </item>
        </channel></rss>"""
        resp_rss = MagicMock()
        resp_rss.status_code = 200
        resp_rss.content = rss_xml

        mock_requests.post.side_effect = [resp_tavily_429, resp_ddg]
        mock_requests.get.return_value = resp_rss

        client = WebSearchClient()
        with patch.dict(
            os.environ,
            {
                "WEB_SEARCH_PROVIDER": "tavily",
                "TAVILY_API_KEY": "tvly-key123",
                "WEB_SEARCH_FALLBACK_PROVIDERS": "free",
            },
            clear=False,
        ):
            res = client.buscar("resultado jogo do Brasil")
            self.assertIsNotNone(res)
            itens, prov_usado = res
            self.assertEqual(prov_usado, "free")
            self.assertTrue(any("3 a 2" in i["title"] or "3 a 2" in i["snippet"] for i in itens))

    @patch("refatored.intent_router.falar")
    @patch("refatored.intent_router.classificar_mensagem_llm", return_value="conversation")
    def test_end_to_end_jogo_do_brasil_via_tool_calling(self, mock_clf, mock_falar):
        with patch.object(
            WebSearchClient,
            "buscar",
            return_value=(
                [{"title": "Japão 3 x 2 Brasil", "snippet": "Brasil perdeu de virada por 3 a 2."}],
                "free",
            ),
        ):
            # Testa a execução direta da tool 'pesquisar_na_web'
            tool_out = execute_tool_call("pesquisar_na_web", {"consulta": "jogo do Brasil"})
            self.assertIn("Japão 3 x 2 Brasil", tool_out)

            # Testa roteamento completo no IntentRouter com Tool Calling
            with patch(
                "refatored.intent_router.llm_client.chamar_com_tools",
                return_value=(
                    "Olha, o Brasil acabou perdendo pro Japão. O placar foi 3x2 — acredita nessa virada?",
                    True,
                ),
            ) as mock_tools:
                router = IntentRouter()
                res = router.processar_mensagem("Quanto foi o jogo do Brasil?")
                self.assertEqual(res["intent"], "conversation")
                self.assertTrue(res["success"])
                self.assertTrue(res["expect_followup"])
                mock_tools.assert_called_once()

    @patch("refatored.intent_router.falar")
    @patch("refatored.intent_router.classificar_mensagem_llm", return_value="conversation")
    @patch("refatored.intent_router.chamar_modelo")
    def test_direct_web_rag_fallback_when_free_model_rejects_tools(
        self, mock_chamar_modelo, mock_clf, mock_falar
    ):
        # Mantém _DEFAULT_CHAMAR_MODELO alinhado apenas para testar o ramo real de tools rejeitadas
        import refatored.intent_router as ir_mod
        with patch.object(ir_mod, "_DEFAULT_CHAMAR_MODELO", mock_chamar_modelo):
            mock_chamar_modelo.return_value = "O Brasil perdeu para o Japão por três a dois."

            def fake_tools_rejected(*args, **kwargs):
                ir_mod.llm_client.last_call_rejected_tools = True
                return None, False

            with patch.object(ir_mod.llm_client, "chamar_com_tools", side_effect=fake_tools_rejected):
                with patch.object(
                    ir_mod.web_search_client,
                    "buscar_contexto_formatado",
                    return_value="Resultados atualizados: Japão 3 x 2 Brasil.",
                ) as mock_web_rag:
                    router = IntentRouter()
                    res = router.processar_mensagem("Quanto foi o jogo do Brasil?")
                    self.assertTrue(res["success"])
                    self.assertIn("três a dois", res["message"])
                    mock_web_rag.assert_called_once()


if __name__ == "__main__":
    unittest.main()
