import os
import wave
import io
import unittest
from unittest.mock import patch, MagicMock

from refatored.tts_client import (
    TTSClient,
    prepare_text_for_speech,
    _wrap_pcm_as_wav,
)
from refatored.speech_output import (
    clean_text_for_speech,
    TextToSpeechManager,
)
from refatored.prompts import (
    get_prompt_conversa,
    PROMPT_CONVERSA_EXPRESSIVO_RJ,
    PROMPT_CONVERSA_NEUTRO,
)


class TestProsodyTextPreparation(unittest.TestCase):
    """Garante que a pontuação expressiva para atuação no TTS seja preservada."""

    def test_preserves_wilson_reference_sentence_prosody(self):
        frase = (
            "Olha, eu até tentei sair mais cedo hoje, mas quando vi o trânsito na "
            "Avenida Brasil, pensei: 'não vai dar tempo nem pro cafezinho!' — "
            "acredita que eu demorei quase uma hora e meia pra chegar aqui?"
        )
        limpo = clean_text_for_speech(frase)
        self.assertEqual(limpo, frase)
        self.assertIn(" — ", limpo)
        self.assertIn("pensei: 'não vai dar tempo nem pro cafezinho!'", limpo)
        self.assertTrue(limpo.endswith("?"))

    def test_strips_markdown_and_emojis_without_losing_compound_hyphens(self):
        bruto = "**Olha só**, pegue o *guarda-chuva* e ligue o `ar-condicionado` 😄... tá 28°C e 85% de umidade!"
        limpo = prepare_text_for_speech(bruto)
        self.assertNotIn("*", limpo)
        self.assertNotIn("`", limpo)
        self.assertNotIn("😄", limpo)
        self.assertIn("guarda-chuva", limpo)
        self.assertIn("ar-condicionado", limpo)
        self.assertIn("...", limpo)
        self.assertIn("28 graus", limpo)
        self.assertIn("85 por cento", limpo)

    def test_expands_compact_hours_units_and_currency(self):
        bruto = "Levei 1h30 a 60 km/h e gastei R$ 15,50 no pedágio (acredita nisso?)."
        limpo = prepare_text_for_speech(bruto)
        self.assertIn("1 hora e meia", limpo)
        self.assertIn("60 quilômetros por hora", limpo)
        self.assertIn("15 reais e 50 centavos", limpo)
        self.assertIn(" — acredita nisso?", limpo)
        self.assertFalse(limpo.endswith("?."))


class TestTTSClientProvidersAndFallback(unittest.TestCase):
    """Testa seleção de provedores, adaptação de payload e cadeia de fallback."""

    def test_provider_chain_deduplication_and_aliases(self):
        client = TTSClient()
        with patch.dict(
            os.environ,
            {
                "TTS_PROVIDER": "gtts",
                "TTS_FALLBACK_PROVIDERS": "11labs, openrouter, google",
            },
            clear=False,
        ):
            self.assertEqual(
                client.get_provider_chain(),
                ["google", "elevenlabs", "openrouter"],
            )

    @patch("refatored.tts_client.requests")
    def test_elevenlabs_omits_language_code_for_multilingual_v2(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ID3_FAKE_MP3_ELEVEN"
        mock_requests.post.return_value = mock_resp
        mock_requests.exceptions.RequestException = Exception

        client = TTSClient()
        with patch.dict(
            os.environ,
            {
                "TTS_PROVIDER": "elevenlabs",
                "ELEVENLABS_API_KEY": "el_test_key",
                "ELEVENLABS_VOICE_ID": "voice_rj_123",
                "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2",
            },
            clear=False,
        ):
            res = client.sintetizar("Oi, tudo bem por aí?")
            self.assertIsNotNone(res)
            audio_bytes, ext, prov = res
            self.assertEqual(audio_bytes, b"ID3_FAKE_MP3_ELEVEN")
            self.assertEqual(ext, ".mp3")
            self.assertEqual(prov, "elevenlabs")

            _, kwargs = mock_requests.post.call_args
            self.assertNotIn("language_code", kwargs["json"])

    @patch("refatored.tts_client.requests")
    def test_elevenlabs_includes_pt_language_code_for_flash_v2_5(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ID3_FAKE_MP3_FLASH"
        mock_requests.post.return_value = mock_resp
        mock_requests.exceptions.RequestException = Exception

        client = TTSClient()
        with patch.dict(
            os.environ,
            {
                "TTS_PROVIDER": "elevenlabs",
                "ELEVENLABS_API_KEY": "el_test_key",
                "ELEVENLABS_MODEL_ID": "eleven_flash_v2_5",
            },
            clear=False,
        ):
            res = client.sintetizar("Testando latência baixa!")
            self.assertIsNotNone(res)
            _, kwargs = mock_requests.post.call_args
            self.assertEqual(kwargs["json"].get("language_code"), "pt")

    @patch("refatored.tts_client.requests")
    def test_openrouter_mp3_and_pcm_auto_fallback_to_wav(self, mock_requests):
        # Simula modelo que rejeita mp3 com HTTP 400 e aceita pcm retornando audio/pcm
        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.text = "mp3 not supported for this model"

        raw_pcm = b"\x00\x01" * 240  # 240 amostras 16-bit mono
        resp_pcm = MagicMock()
        resp_pcm.status_code = 200
        resp_pcm.headers = {"Content-Type": "audio/pcm;rate=24000;channels=1"}
        resp_pcm.content = raw_pcm

        mock_requests.post.side_effect = [resp_400, resp_pcm]
        mock_requests.exceptions.RequestException = Exception

        client = TTSClient()
        with patch.dict(
            os.environ,
            {
                "TTS_PROVIDER": "openrouter",
                "OPENROUTER_KEY": "or_test_key",
                "OPENROUTER_TTS_MODEL": "google/gemini-2.5-flash-tts",
            },
            clear=False,
        ):
            res = client.sintetizar("Olha, que dia lindo no Rio!")
            self.assertIsNotNone(res)
            audio_bytes, ext, prov = res
            self.assertEqual(ext, ".wav")
            self.assertEqual(prov, "openrouter")
            self.assertTrue(audio_bytes.startswith(b"RIFF"))

            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                self.assertEqual(wf.getframerate(), 24000)
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)

    @patch("refatored.tts_client.requests")
    def test_automatic_fallback_from_google_to_elevenlabs_to_openrouter(self, mock_requests):
        # ElevenLabs retorna 429 (quota), OpenRouter retorna 200 com MP3
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "quota exceeded"

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.headers = {"Content-Type": "audio/mpeg"}
        resp_ok.content = b"ID3_OPENROUTER_RESCUE"

        # 2 tentativas no ElevenLabs (retries=1 -> 2 posts) + 1 post no OpenRouter
        mock_requests.post.side_effect = [resp_429, resp_429, resp_ok]
        mock_requests.exceptions.RequestException = Exception

        client = TTSClient()
        # Força falha no Google TTS
        with patch.object(client, "_synthesize_google", return_value=None):
            with patch.dict(
                os.environ,
                {
                    "TTS_PROVIDER": "google",
                    "TTS_FALLBACK_PROVIDERS": "elevenlabs,openrouter",
                    "ELEVENLABS_API_KEY": "el_key",
                    "OPENROUTER_KEY": "or_key",
                },
                clear=False,
            ):
                with patch("refatored.tts_client.time.sleep"):
                    res = client.sintetizar("Testando cadeia completa de fallback!")
                    self.assertIsNotNone(res)
                    audio_bytes, ext, prov = res
                    self.assertEqual(prov, "openrouter")
                    self.assertEqual(ext, ".mp3")
                    self.assertEqual(audio_bytes, b"ID3_OPENROUTER_RESCUE")

    def test_manager_plays_static_falha_tts_when_all_providers_fail(self):
        fake_client = MagicMock()
        fake_client.sintetizar.return_value = None
        manager = TextToSpeechManager(client=fake_client)

        with patch("refatored.speech_output._temporarily_boost_tts_volume"):
            with patch("refatored.speech_output.play_falha_tts") as mock_falha:
                manager.falar("Alô?")
                mock_falha.assert_called_once()


class TestPromptsProsodySelection(unittest.TestCase):
    def test_prompt_selection_expressive_vs_neutral(self):
        self.assertEqual(get_prompt_conversa("expressive_rj"), PROMPT_CONVERSA_EXPRESSIVO_RJ)
        self.assertEqual(get_prompt_conversa("neutral"), PROMPT_CONVERSA_NEUTRO)
        self.assertIn("Avenida Brasil", PROMPT_CONVERSA_EXPRESSIVO_RJ)


if __name__ == "__main__":
    unittest.main()
