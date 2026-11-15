import unittest
from unittest.mock import patch, MagicMock
from refatored.llm_client import LLMClient

class TestLLMClient(unittest.TestCase):

    def setUp(self):
        self.client = LLMClient()

    def test_presets_endpoints(self):
        self.assertEqual(
            self.client.get_endpoint_for_provider("openrouter"),
            "https://openrouter.ai/api/v1/chat/completions"
        )
        self.assertEqual(
            self.client.get_endpoint_for_provider("groq"),
            "https://api.groq.com/openai/v1/chat/completions"
        )
        self.assertEqual(
            self.client.get_endpoint_for_provider("gemini"),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )
        self.assertEqual(
            self.client.get_endpoint_for_provider("cerebras"),
            "https://api.cerebras.ai/v1/chat/completions"
        )

    def test_adaptacao_modelo_fora_do_openrouter(self):
        # No OpenRouter, mantém o modelo original com tag :free
        modelo_or = self.client._adapt_model_name(
            "meta-llama/llama-3.3-70b-instruct:free",
            "openrouter"
        )
        self.assertEqual(modelo_or, "meta-llama/llama-3.3-70b-instruct:free")

        # No Groq, adapta para o modelo padrão equivalente
        modelo_groq = self.client._adapt_model_name(
            "meta-llama/llama-3.3-70b-instruct:free",
            "groq"
        )
        self.assertEqual(modelo_groq, "llama-3.3-70b-versatile")

    @patch("refatored.llm_client.requests")
    def test_chamada_sucesso(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Olá, tudo bem?"}}]
        }
        mock_requests.post.return_value = mock_resp

        with patch.object(self.client, "get_api_key_for_provider", return_value="fake_key"):
            resposta = self.client.chamar("any-model", "sys prompt", "user msg")
            self.assertEqual(resposta, "Olá, tudo bem?")

    @patch("refatored.llm_client.requests")
    def test_fallback_automatico_em_rate_limit(self, mock_requests):
        # Primeiro mock: 429 Rate Limit no OpenRouter
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Rate limit reached"

        # Segundo mock: 200 Sucesso no provedor de fallback (ex: Groq)
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Resposta do fallback!"}}]
        }

        mock_requests.post.side_effect = [resp_429, resp_200]

        client_com_fallback = LLMClient()
        client_com_fallback.provider = "openrouter"
        client_com_fallback.fallback_provider = "groq"

        with patch.object(client_com_fallback, "get_api_key_for_provider", return_value="fake_key"):
            resposta = client_com_fallback.chamar("model", "sys", "user", retries=0)
            self.assertEqual(resposta, "Resposta do fallback!")


if __name__ == "__main__":
    unittest.main()
