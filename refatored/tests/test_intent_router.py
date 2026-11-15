import unittest
from unittest.mock import patch, MagicMock
from refatored.intent_router import IntentRouter

class TestIntentRouter(unittest.TestCase):

    def setUp(self):
        self.router = IntentRouter()

    @patch("refatored.intent_router.falar")
    @patch("refatored.intent_router.play_confirmation")
    def test_rota_rapida_hora(self, mock_play_conf, mock_falar):
        res = self.router.processar_mensagem("que horas são")
        self.assertEqual(res.get("intent"), "time")
        self.assertTrue(res.get("success"))
        mock_play_conf.assert_called_once()
        mock_falar.assert_called_once()

    @patch("refatored.intent_router.executar_comando_ha")
    @patch("refatored.intent_router.play_confirmation")
    def test_rota_rapida_home_assistant(self, mock_play_conf, mock_ha_exec):
        mock_ha_exec.return_value = (True, "Comando executado.")
        res = self.router.processar_mensagem("desligar a luz da sala")

        self.assertEqual(res.get("intent"), "home_assistant_local")
        self.assertTrue(res.get("success"))
        mock_ha_exec.assert_called_once()
        mock_play_conf.assert_called_once()

    @patch("refatored.intent_router.music_player.stop")
    @patch("refatored.intent_router.play_confirmation")
    def test_rota_rapida_musica(self, mock_play_conf, mock_music_stop):
        mock_music_stop.return_value = "Música parada."
        res = self.router.processar_mensagem("parar a música")

        self.assertEqual(res.get("intent"), "music")
        self.assertEqual(res.get("action"), "stop")
        self.assertTrue(res.get("success"))
        mock_music_stop.assert_called_once()
        mock_play_conf.assert_called_once()

    @patch("refatored.intent_router.chamar_modelo")
    @patch("refatored.intent_router.falar")
    def test_fallback_conversa_llm(self, mock_falar, mock_chamar_modelo):
        # Primeiro mock: classificador retorna "conversation"
        # Segundo mock: modelo de conversa retorna a resposta do assistente
        mock_chamar_modelo.side_effect = [
            "conversation",
            "O céu é azul devido ao espalhamento Rayleigh da luz solar."
        ]

        res = self.router.processar_mensagem("Por que o céu é azul?")
        self.assertEqual(res.get("intent"), "conversation")
        self.assertTrue(res.get("success"))
        mock_falar.assert_called_once_with("O céu é azul devido ao espalhamento Rayleigh da luz solar.")

    @patch("refatored.intent_router.chamar_modelo")
    @patch("refatored.intent_router.falar")
    @patch("refatored.intent_router.play_error")
    def test_fallback_classificador_indisponivel(self, mock_play_err, mock_falar, mock_chamar_modelo):
        # Simula indisponibilidade de rede no classificador
        mock_chamar_modelo.return_value = None

        res = self.router.processar_mensagem("comando complexo desconhecido")
        self.assertEqual(res.get("intent"), "classifier_unavailable")
        self.assertFalse(res.get("success"))
        mock_play_err.assert_called_once()
        mock_falar.assert_called_once()


if __name__ == "__main__":
    unittest.main()

