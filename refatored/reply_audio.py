"""Recurso de áudio efêmero. Não aceita texto livre, não chama o roteador nem toca áudio."""
import secrets
import threading
import time
from collections import OrderedDict

from refatored.tts_client import TTSClient

MAX_AUDIO = 6 * 1024 * 1024


class AudioUnavailable(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class ReplyAudio:
    def __init__(self, synthesize, clock=time.monotonic):
        self.synthesize = synthesize
        self.clock = clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self._rendering = threading.Lock()
        self._last = None  # só um áudio em RAM, nunca um arquivo público

    def _prune(self):
        now = self.clock()
        while self._entries:
            key, (until, _) = next(iter(self._entries.items()))
            if until > now and len(self._entries) <= 32:
                break
            self._entries.pop(key)
        if self._last and self._last[0] not in self._entries:
            self._last = None

    def remember(self, profile, text):
        # Não cortar/falar meia resposta quando o limite do sintetizador é excedido.
        if len(text.encode('utf-8')) > 4500:
            return None
        ticket = secrets.token_hex(16)
        with self._lock:
            self._entries[profile, ticket] = (self.clock() + 600, text)
            self._prune()
        return ticket

    def get(self, profile, ticket):
        key = (profile, ticket)
        if not self._rendering.acquire(blocking=False):
            raise AudioUnavailable(503, 'Síntese móvel ocupada.')
        try:
            with self._lock:
                self._prune()
                if key not in self._entries:
                    raise AudioUnavailable(410, 'Áudio expirado ou indisponível para este perfil.')
                if self._last and self._last[0] == key:
                    return self._last[1]
                text = self._entries[key][1]
            generated = self.synthesize(text)
            if not generated:
                raise AudioUnavailable(503, 'Nenhum provedor de voz respondeu.')
            data, ext, _ = generated
            mime = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav'}.get(ext)
            if not mime or not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO:
                raise AudioUnavailable(502, 'Formato ou tamanho de áudio incompatível.')
            with self._lock:
                self._prune()
                if key not in self._entries:
                    raise AudioUnavailable(410, 'Áudio expirado.')
                self._last = (key, (mime, data))
            return mime, data
        finally:
            self._rendering.release()


# Mesma configuração/cadeia de vozes. Cliente separado para não concorrer na
# inicialização do SDK com o pipeline de áudio físico; só inicializa sob demanda.
reply_audio = ReplyAudio(TTSClient().sintetizar)
