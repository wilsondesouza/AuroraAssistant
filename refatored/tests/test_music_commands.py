import unittest
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from refatored.music import parse_music_local, MusicPlayer

class TestMusicCommands(unittest.TestCase):

    def test_comandos_de_tocar(self):
        frases = [
            "tocar música",
            "toca uma música",
            "ouvir música",
            "tocar musica",
            "solta o som",
            "play"
        ]
        for f in frases:
            with self.subTest(frase=f):
                self.assertEqual(parse_music_local(f), "play")

    def test_comandos_de_parar(self):
        frases = [
            "parar a música",
            "para a música",
            "parar música",
            "para música",
            "desligar a música",
            "pausar",
            "pause",
            "pare",
            "stop"
        ]
        for f in frases:
            with self.subTest(frase=f):
                self.assertEqual(parse_music_local(f), "stop")

    def test_comandos_de_proxima(self):
        frases = [
            "próxima música",
            "proxima musica",
            "próxima faixa",
            "pula a música",
            "passa a música",
            "próxima",
            "proxima",
            "pula",
            "passa"
        ]
        for f in frases:
            with self.subTest(frase=f):
                self.assertEqual(parse_music_local(f), "next")

    def test_comandos_de_modo_continuo(self):
        frases = [
            "modo contínuo",
            "modo continuo",
            "reprodução contínua",
            "reproducao continua",
            "tocar sem parar",
            "tocar direto"
        ]
        for f in frases:
            with self.subTest(frase=f):
                self.assertEqual(parse_music_local(f), "continuous")

    def test_evitar_falsos_positivos_com_para(self):
        """
        CORREÇÃO: Frases como 'música para dormir' ou 'música para relaxar'
        NÃO devem ser interpretadas como comando de parar!
        """
        frases_nao_parar = [
            "música para dormir",
            "música para relaxar",
            "música para trabalhar",
            "uma música para festa"
        ]
        for f in frases_nao_parar:
            with self.subTest(frase=f):
                acao = parse_music_local(f)
                self.assertNotEqual(
                    acao,
                    "stop",
                    f"Frase '{f}' não deveria ser identificada como stop!"
                )

    def test_next_music_preserva_estado_continuo(self):
        """Testa a correção do bug onde next_music sempre forçava modo contínuo = True."""
        player = MusicPlayer()
        # Se contínuo estava desligado
        player._play_continuously = False
        # Simula playlist vazia para não rodar subprocesso real
        player._load_cached_playlist = lambda: []
        player.update_playlist = lambda: []

        player.next_music()
        self.assertFalse(player.is_continuous, "Modo contínuo deveria permanecer False após next_music!")

    def test_play_sincroniza_status_sem_gravar_url_e_com_titulo_vazio(self):
        player = MusicPlayer()
        player._load_cached_playlist = lambda: [{
            "title": "",
            "artist": "Artista",
            "album": "Álbum",
            "url": "https://music.example/stream?t=segredo",
        }]

        with tempfile.TemporaryDirectory() as temp_dir:
            aurora_file = Path(temp_dir) / "current_song.json"
            smartlume_file = Path(temp_dir) / "ultima_musica.json"
            with patch("refatored.music.CURRENT_SONG_FILE", str(aurora_file)), \
                    patch("refatored.music.SMARTLUME_STATUS_FILE", str(smartlume_file)), \
                    patch("refatored.music.shutil.which", return_value="mpg123"), \
                    patch("refatored.music.subprocess.Popen") as mock_popen, \
                    patch.object(player, "_ensure_monitor_running"):
                success, message = player.play_random_music()

            self.assertTrue(success)
            self.assertEqual(message, "Tocando Desconhecida.")
            self.assertEqual(
                mock_popen.call_args.args[0],
                ["mpg123", "https://music.example/stream?t=segredo"],
            )
            self.assertEqual(mock_popen.call_args.kwargs["stderr"], subprocess.PIPE)
            for status_file in (aurora_file, smartlume_file):
                with status_file.open(encoding="utf-8") as file:
                    status = json.load(file)
                self.assertEqual(status["title"], "Desconhecida")
                self.assertEqual(status["artist"], "Artista")
                self.assertEqual(status["album"], "Álbum")
                self.assertNotIn("url", status)

    def test_cache_descarta_caminho_local_inexistente(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_song = Path(temp_dir) / "existing.mp3"
            local_song.touch()
            playlist_file = Path(temp_dir) / "playlist.json"
            playlist_file.write_text(
                json.dumps([
                    {"title": "local", "url": str(local_song)},
                    {"title": "stream", "url": "https://music.example/stream?id=1"},
                    {"title": "missing", "url": str(Path(temp_dir) / "missing.mp3")},
                    {"title": "invalid", "url": "ftp://music.example/song.mp3"},
                    {"title": "malformed", "url": "http://[invalid"},
                ]),
                encoding="utf-8",
            )
            player = MusicPlayer()

            with patch("refatored.music.PLAYLIST_FILE", str(playlist_file)), \
                    patch("refatored.music.LEGACY_PLAYLIST_FILE", str(Path(temp_dir) / "legacy.txt")):
                cached = player._load_cached_playlist()

        self.assertEqual([song["title"] for song in cached], ["local", "stream"])

    def test_comando_mpg123_usa_dispositivo_configurado(self):
        player = MusicPlayer()
        player._load_cached_playlist = lambda: [{
            "title": "Faixa",
            "url": "https://music.example/stream?id=2",
        }]

        with patch("refatored.music.shutil.which", side_effect=lambda name: "mpg123" if name == "mpg123" else None), \
                patch("refatored.music.AUDIO_OUTPUT_DRIVER", "alsa"), \
                patch("refatored.music.AUDIO_OUTPUT_DEVICE", "plughw:2,0"), \
                patch("refatored.music.subprocess.Popen") as mock_popen, \
                patch.object(player, "_ensure_monitor_running"):
            success, _ = player.play_random_music()

        self.assertTrue(success)
        self.assertEqual(
            mock_popen.call_args.args[0],
            ["mpg123", "-o", "alsa", "-a", "plughw:2,0", "https://music.example/stream?id=2"],
        )


if __name__ == "__main__":
    unittest.main()
