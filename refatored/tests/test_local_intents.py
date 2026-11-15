import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from refatored.local_intents import (
    number_to_words_ptbr,
    format_time_ptbr,
    get_time_response,
    get_weather_response
)


class TestLocalIntents(unittest.TestCase):
    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    @staticmethod
    def _api_response(payload, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.text = ""
        response.json.return_value = payload
        return response

    @staticmethod
    def _current_weather():
        return {
            "coord": {"lat": -22.8, "lon": -43.4},
            "main": {
                "temp": 24.6,
                "feels_like": 27.2,
                "humidity": 68,
            },
            "weather": [{"id": 803, "description": "extensive translated text"}],
            "wind": {"speed": 3},
        }

    def _mock_weather_requests(self, *responses):
        client = Mock()
        client.get.side_effect = responses
        client.exceptions.Timeout = self.Timeout
        client.exceptions.RequestException = self.RequestException
        return client

    def test_numeros_por_extenso(self):
        self.assertEqual(number_to_words_ptbr(0), "zero")
        self.assertEqual(number_to_words_ptbr(1), "um")
        self.assertEqual(number_to_words_ptbr(12), "doze")
        self.assertEqual(number_to_words_ptbr(15), "quinze")
        self.assertEqual(number_to_words_ptbr(20), "vinte")
        self.assertEqual(number_to_words_ptbr(35), "trinta e cinco")
        self.assertEqual(number_to_words_ptbr(42), "quarenta e dois")
        self.assertEqual(number_to_words_ptbr(59), "cinquenta e nove")

    def test_formatacao_hora(self):
        # 10:00 da manhã
        dt1 = datetime(2026, 1, 1, 10, 0)
        resp1 = format_time_ptbr(dt1)
        self.assertIn("dez horas da manhã", resp1)

        # 14:30 (2h30 da tarde)
        dt2 = datetime(2026, 1, 1, 14, 30)
        resp2 = format_time_ptbr(dt2)
        self.assertIn("duas e trinta da tarde", resp2)

        # 21:15 (9h15 da noite)
        dt3 = datetime(2026, 1, 1, 21, 15)
        resp3 = format_time_ptbr(dt3)
        self.assertIn("nove e quinze da noite", resp3)

        # 01:05 (1h05 da madrugada)
        dt4 = datetime(2026, 1, 1, 1, 5)
        resp4 = format_time_ptbr(dt4)
        self.assertIn("uma e cinco da madrugada", resp4)

    def test_reconhecimento_intencao_hora(self):
        frases_hora = [
            "que horas são",
            "que horas e",
            "qual a hora",
            "diga a hora certa",
            "sabe que horas são"
        ]
        for f in frases_hora:
            with self.subTest(frase=f):
                self.assertIsNotNone(get_time_response(f))

    def test_falsos_positivos_hora(self):
        """Palavras que contêm 'hora' ou contextos não relacionados não devem ativar resposta de relógio."""
        frases_nao_hora = [
            "precisamos melhorar isso",
            "vamos embora",
            "agora não",
            "estou trabalhando sem demora"
        ]
        for f in frases_nao_hora:
            with self.subTest(frase=f):
                self.assertIsNone(get_time_response(f))

    def test_reconhecimento_intencao_clima(self):
        requests_client = self._mock_weather_requests(
            *[
                self._api_response(self._current_weather()),
                self._api_response({"data": [{"uvi": 4.2}]}),
            ] * 3,
        )
        with patch("refatored.local_intents.OPENWEATHER_KEY", "test-key"), patch(
            "refatored.local_intents.requests", requests_client
        ):
            self.assertIsNotNone(get_weather_response("como está o tempo"))
            self.assertIsNotNone(get_weather_response("previsão do tempo"))
            self.assertIsNotNone(get_weather_response("qual a temperatura hoje"))

    def test_resposta_clima_localizada_com_dados_extras(self):
        requests_client = self._mock_weather_requests(
            self._api_response(self._current_weather()),
            self._api_response({"data": [{"uvi": 6.2}]}),
        )
        with patch("refatored.local_intents.OPENWEATHER_KEY", "test-key"), patch(
            "refatored.local_intents.OPENWEATHER_CITY", "Nilópolis"
        ), patch("refatored.local_intents.requests", requests_client):
            resposta = get_weather_response("como está o tempo")

        self.assertEqual(
            resposta,
            "Em Nilópolis, o céu está muito nublado. A temperatura está em 25 graus, "
            "com sensação térmica de 27 graus. A umidade relativa do ar está em 68%. "
            "Os ventos estão a 11 quilômetros por hora. O índice UV está em 6,2 (alto).",
        )
        self.assertNotIn("extensive translated text", resposta)
        self.assertEqual(requests_client.get.call_count, 2)
        self.assertEqual(
            requests_client.get.call_args_list[1].kwargs["params"],
            {
                "lat": -22.8,
                "lon": -43.4,
                "appid": "test-key",
                "units": "metric",
                "lang": "pt_br",
            },
        )

    def test_resposta_clima_sem_assinatura_one_call(self):
        requests_client = self._mock_weather_requests(
            self._api_response(self._current_weather()),
            self._api_response({}, status_code=401),
        )
        with patch("refatored.local_intents.OPENWEATHER_KEY", "test-key"), patch(
            "refatored.local_intents.OPENWEATHER_CITY", "Nilópolis"
        ), patch("refatored.local_intents.requests", requests_client):
            resposta = get_weather_response("como está o tempo")

        self.assertIn("A umidade relativa do ar está em 68%.", resposta)
        self.assertIn("O índice UV não está disponível no momento.", resposta)

    def test_falsos_positivos_clima(self):
        self.assertIsNone(get_weather_response("quanto tempo você vai demorar"))
        self.assertIsNone(get_weather_response("faz muito tempo que não te vejo"))


if __name__ == "__main__":
    unittest.main()
