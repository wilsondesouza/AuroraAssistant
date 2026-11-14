import os
import re
import json
import random
import string
import hashlib
import logging
import shutil
import subprocess
import tempfile
import threading
import sys
import time
from urllib.parse import urlsplit
from typing import Optional, List, Dict, Any, Tuple

try:
    import requests
except ImportError:
    requests = None

from refatored.config import (
    NAVIDROME_API_URL,
    NAVIDROME_USER,
    NAVIDROME_PASSWORD,
    NAVIDROME_TIMEOUT,
    PLAYLIST_FILE,
    LEGACY_PLAYLIST_FILE,
    CURRENT_SONG_FILE,
    SMARTLUME_STATUS_FILE,
    AUDIO_OUTPUT_DRIVER,
    AUDIO_OUTPUT_DEVICE,
    sanitize_for_log,
)

logger = logging.getLogger(__name__)


def _write_json_atomically(path: str, payload: Dict[str, Any]) -> None:
    destination = os.path.abspath(path)
    directory = os.path.dirname(destination)
    os.makedirs(directory, exist_ok=True)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as temporary_file:
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = temporary_file.name

        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def _save_current_song(song: Optional[Dict[str, Any]]) -> None:
    safe_info = {
        "title": (song or {}).get("title") or None,
        "artist": (song or {}).get("artist") or None,
        "album": (song or {}).get("album") or None,
    }

    for path in dict.fromkeys((CURRENT_SONG_FILE, SMARTLUME_STATUS_FILE)):
        if not path:
            continue
        try:
            _write_json_atomically(path, safe_info)
        except OSError as error:
            logger.warning("Não foi possível salvar o status da música em %s: %s", path, error)


# ==========================================
# PARSER LOCAL DETERMINÍSTICO DE MÚSICA
# ==========================================

RE_MUSIC_STOP = re.compile(
    r'\b(parar(?:\s+a)?\s+m[úu]sica|para(?:\s+a)?\s+m[úu]sica|desligar(?:\s+a)?\s+m[úu]sica|desliga(?:\s+a)?\s+m[úu]sica|pause|pausar|pare|interromper|stop)\b',
    re.IGNORECASE
)

RE_MUSIC_NEXT = re.compile(
    r'\b(pr[óo]xima(?:\s+a)?(?:\s+m[úu]sica|\s+faixa)?|pula(?:\s+a)?(?:\s+m[úu]sica|\s+faixa)?|passa(?:\s+a)?(?:\s+m[úu]sica|\s+faixa)?|avan[çc]a|avancar|pular|passar)\b',
    re.IGNORECASE
)

RE_MUSIC_CONTINUOUS = re.compile(
    r'\b(modo\s+cont[íi]nuo|reprodu[çc][ãa]o\s+cont[íi]nua|tocar\s+sem\s+parar|tocar\s+direto|modo\s+repetir)\b',
    re.IGNORECASE
)

RE_MUSIC_PLAY = re.compile(
    r'\b(tocar(?:\s+uma)?\s+m[úu]sica|toca(?:\s+uma)?\s+m[úu]sica|ouvir(?:\s+uma)?\s+m[úu]sica|reproduzir(?:\s+uma)?\s+m[úu]sica|coloca(?:\s+uma)?\s+m[úu]sica|solta\s+o\s+som|iniciar\s+m[úu]sica|play)\b',
    re.IGNORECASE
)


def parse_music_local(mensagem: str) -> Optional[str]:
    """
    Parser determinístico local para comandos de música.
    Evita falsos positivos como 'música para dormir' ativando parada.
    Retorna: 'stop', 'next', 'continuous', 'play' ou None.
    """
    if not mensagem:
        return None

    texto = mensagem.lower().strip()

    # Checar Parar primeiro
    if RE_MUSIC_STOP.search(texto):
        return "stop"

    # Checar Próxima
    if RE_MUSIC_NEXT.search(texto):
        return "next"

    # Checar Modo Contínuo
    if RE_MUSIC_CONTINUOUS.search(texto):
        return "continuous"

    # Checar Tocar
    if RE_MUSIC_PLAY.search(texto) or texto in ("música", "musica"):
        return "play"

    return None


# ==========================================
# GERENCIADOR E CONTROLADOR DO PLAYER DE MÚSICA
# ==========================================

class MusicPlayer:
    """Controlador central de reprodução de música, thread-safe e protegido."""

    def __init__(self):
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._play_continuously: bool = False
        self._current_song: Optional[Dict[str, Any]] = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    @property
    def is_continuous(self) -> bool:
        with self._lock:
            return self._play_continuously

    def _generate_auth_params(self) -> Dict[str, str]:
        """Gera parâmetros de autenticação com salt e token (Subsonic standard)."""
        if not NAVIDROME_USER or not NAVIDROME_PASSWORD:
            return {}

        salt = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        token = hashlib.md5((NAVIDROME_PASSWORD + salt).encode('utf-8')).hexdigest()

        return {
            "u": NAVIDROME_USER,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "aurora_assistant"
        }

    def update_playlist(self) -> List[Dict[str, Any]]:
        """Busca faixas aleatórias no Navidrome e atualiza o arquivo local da playlist."""
        if not NAVIDROME_API_URL or not NAVIDROME_USER:
            logger.warning("Navidrome não configurado; pulando atualização da playlist.")
            return self._load_cached_playlist()

        if requests is None:
            logger.error("Biblioteca 'requests' não instalada.")
            return self._load_cached_playlist()

        logger.info("Atualizando playlist a partir do Navidrome...")
        try:
            url = f"{NAVIDROME_API_URL}/rest/getRandomSongs.view"
            params = self._generate_auth_params()
            params["f"] = "json"
            params["size"] = 15

            resp = requests.get(url, params=params, timeout=NAVIDROME_TIMEOUT)
            if resp.status_code != 200:
                logger.error(f"Erro HTTP {resp.status_code} ao contatar Navidrome.")
                return self._load_cached_playlist()

            data = resp.json()
            subsonic_resp = data.get("subsonic-response", {})
            if subsonic_resp.get("status") != "ok":
                logger.error(f"Erro na resposta da API Subsonic: {subsonic_resp.get('error')}")
                return self._load_cached_playlist()

            songs = subsonic_resp.get("randomSongs", {}).get("song", [])
            playlist = []

            for s in songs:
                song_id = s.get("id")
                if not song_id:
                    continue

                # URL de streaming autenticada com token/salt
                auth = self._generate_auth_params()
                stream_url = (
                    f"{NAVIDROME_API_URL}/rest/stream.view?"
                    f"u={auth['u']}&t={auth['t']}&s={auth['s']}&v={auth['v']}&c={auth['c']}&f=mp3&id={song_id}"
                )

                playlist.append({
                    "id": song_id,
                    "title": s.get("title") or "Desconhecida",
                    "artist": s.get("artist") or "Desconhecido",
                    "album": s.get("album") or "Desconhecido",
                    "url": stream_url
                })

            if playlist:
                # Gravação segura do JSON
                with open(PLAYLIST_FILE, "w", encoding="utf-8") as f:
                    json.dump(playlist, f, ensure_ascii=False, indent=2)
                logger.info(f"Playlist atualizada com sucesso: {len(playlist)} músicas.")
                return playlist

        except Exception as e:
            logger.error(f"Falha ao atualizar playlist: {e}")

        return self._load_cached_playlist()

    def _load_cached_playlist(self) -> List[Dict[str, Any]]:
        """Carrega apenas faixas em URLs HTTP(S) ou arquivos locais existentes."""
        for path in (PLAYLIST_FILE, LEGACY_PLAYLIST_FILE):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and data:
                            valid_tracks = []
                            for track in data:
                                if not isinstance(track, dict):
                                    continue
                                location = track.get("url")
                                if not isinstance(location, str) or not location.strip():
                                    continue
                                location = location.strip()
                                try:
                                    parsed = urlsplit(location)
                                    is_url = (
                                        parsed.scheme in {"http", "https"}
                                        and bool(parsed.netloc)
                                    )
                                except ValueError:
                                    is_url = False
                                if is_url or os.path.isfile(location):
                                    track["url"] = location
                                    valid_tracks.append(track)
                            invalid_count = len(data) - len(valid_tracks)
                            if invalid_count:
                                logger.warning(
                                    "Ignorando %s faixa(s) inválida(s) no cache %s.",
                                    invalid_count,
                                    path,
                                )
                            if valid_tracks:
                                return valid_tracks
                except Exception as e:
                    logger.debug(f"Erro ao ler cache {path}: {e}")
        return []

    def _stop_process_internal(self):
        """Para o processo de áudio com encerramento gracioso e timeout."""
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.5)
            except Exception:
                try:
                    self._process.kill()
                    self._process.wait(timeout=0.5)
                except Exception:
                    pass
        self._process = None

    def stop(self) -> str:
        """Para a reprodução e desativa o modo contínuo."""
        with self._lock:
            self._play_continuously = False
            self._stop_process_internal()
            _save_current_song(None)
            logger.info("Reprodução de música finalizada.")
            return "Música parada."

    def play_random_music(self) -> Tuple[bool, str]:
        """Toca uma música aleatória da playlist."""
        with self._lock:
            playlist = self._load_cached_playlist()
            if not playlist:
                playlist = self.update_playlist()

            if not playlist:
                logger.warning("Nenhuma música disponível na playlist.")
                return False, "Nenhuma música disponível na playlist."

            self._stop_process_internal()

            song = random.choice(playlist)
            song["title"] = song.get("title") or "Desconhecida"
            self._current_song = song
            url = song.get("url")

            _save_current_song(song)

            logger.info(f"Tocando agora: '{song.get('title')}' de '{song.get('artist')}'")
            logger.debug(f"Stream URL: {sanitize_for_log(url)}")

            # Selecionar player em ordem de preferência
            player_cmd = None
            if shutil.which("mpg123"):
                player_cmd = ["mpg123"]
                if AUDIO_OUTPUT_DRIVER:
                    player_cmd.extend(["-o", AUDIO_OUTPUT_DRIVER])
                if AUDIO_OUTPUT_DEVICE:
                    player_cmd.extend(["-a", AUDIO_OUTPUT_DEVICE])
                player_cmd.append(url)
            elif shutil.which("ffplay"):
                player_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "panic", url]
            elif shutil.which("vlc"):
                player_cmd = ["vlc", "--intf", "dummy", "--play-and-exit", url]

            if player_cmd:
                try:
                    self._process = subprocess.Popen(
                        player_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        errors="replace",
                    )
                except Exception as e:
                    logger.error(f"Erro ao iniciar player externo: {e}")
                    return False, "Erro ao iniciar reprodutor de áudio."
            else:
                # Fallback por plataforma
                if sys.platform.startswith("win"):
                    try:
                        os.startfile(url)
                        self._process = None
                    except Exception as e:
                        logger.error(f"Erro ao usar os.startfile: {e}")
                        return False, "Falha ao abrir stream no Windows."
                else:
                    try:
                        self._process = subprocess.Popen(["xdg-open", url])
                    except Exception as e:
                        logger.error(f"Erro ao usar xdg-open: {e}")
                        return False, "Falha ao abrir stream no Linux."

            # Drenar o stderr do player para evitar bloqueio e registrar falhas.
            if self._process is not None:
                self._ensure_monitor_running()

            return True, f"Tocando {song['title']}."

    def start_continuous_play(self) -> Tuple[bool, str]:
        """Inicia o modo contínuo tocando música atrás de música."""
        with self._lock:
            self._play_continuously = True
            success, msg = self.play_random_music()
            if success:
                self._ensure_monitor_running()
                return True, "Modo contínuo ativado."
            return False, msg

    def next_music(self) -> Tuple[bool, str]:
        """
        Avança para a próxima música preservando o estado do modo contínuo.
        Resolve o bug onde next_music sempre forçava play_continuously = True.
        """
        with self._lock:
            current_continuous = self._play_continuously
            self._stop_process_internal()
            time.sleep(0.3)
            # Mantém o modo contínuo anterior
            self._play_continuously = current_continuous
            success, msg = self.play_random_music()
            if success:
                return True, "Tocando próxima música."
            return False, msg

    def _ensure_monitor_running(self):
        """Garante que a thread monitora do modo contínuo esteja ativa."""
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
            self._monitor_thread.start()

    def _monitor_worker(self):
        """Registra falhas do player e avança a playlist no modo contínuo."""
        while True:
            with self._lock:
                proc = self._process
                if proc is None:
                    return

            try:
                _, stderr = proc.communicate()
            except (OSError, ValueError) as error:
                logger.error("Erro ao monitorar o reprodutor de música: %s", error)
                return

            with self._lock:
                if self._process is not proc:
                    continue
                return_code = proc.returncode
                self._process = None
                if return_code:
                    message = (stderr or "").strip()[:1000]
                    logger.error(
                        "Reprodutor de música terminou com código %s: %s",
                        return_code,
                        sanitize_for_log(message) or "sem detalhes",
                    )
                if not self._play_continuously:
                    return
                success, message = self.play_random_music()
                if not success:
                    logger.error("Não foi possível iniciar a próxima faixa: %s", message)
                    self._play_continuously = False
                    return


# Instância global singleton do controlador de música
music_player = MusicPlayer()
