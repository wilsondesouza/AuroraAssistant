import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from refatored.reply_audio import AudioUnavailable, MAX_AUDIO, ReplyAudio


class TestReplyAudio(unittest.TestCase):
    def store(self):
        self.now = 0
        self.synth = Mock(return_value=(b'voz de teste', '.mp3', 'simulado'))
        return ReplyAudio(self.synth, lambda: self.now)

    def test_profile_format_expiry_and_lazy_bounded_cache(self):
        store = self.store()
        id1 = store.remember(1, 'Primeira resposta')
        self.synth.assert_not_called()
        with self.assertRaises(AudioUnavailable) as other:
            store.get(2, id1)
        self.assertEqual(other.exception.status, 410)
        self.assertEqual(store.get(1, id1), ('audio/mpeg', b'voz de teste'))
        self.assertEqual(store.get(1, id1), ('audio/mpeg', b'voz de teste'))
        self.synth.assert_called_once_with('Primeira resposta')
        for i in range(32):
            id2 = store.remember(2, f'Outra resposta {i}')
        with self.assertRaises(AudioUnavailable):
            store.get(1, id1)
        self.synth.return_value = (b'RIFF', '.wav', 'simulado')
        self.assertEqual(store.get(2, id2), ('audio/wav', b'RIFF'))
        self.now = 601
        with self.assertRaises(AudioUnavailable) as expired:
            store.get(2, id2)
        self.assertEqual(expired.exception.status, 410)
        self.assertIsNone(store.remember(1, 'á' * 2251))

    def test_failure_limits_and_busy_do_not_render_in_parallel(self):
        store = self.store()
        ticket = store.remember(1, 'Olá')
        for output in [None, (b'', '.mp3', 'x'), (b'x', '.zip', 'x'), (b'x'*(MAX_AUDIO+1), '.wav', 'x')]:
            self.synth.return_value = output
            with self.assertRaises(AudioUnavailable):
                store.get(1, ticket)
        entered, finish = threading.Event(), threading.Event()
        def wait(_):
            entered.set()
            self.assertTrue(finish.wait(3))
            return b'ok', '.mp3', 'teste'
        self.synth.side_effect = wait
        with ThreadPoolExecutor(1) as worker:
            first = worker.submit(store.get, 1, ticket)
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(AudioUnavailable) as busy:
                    store.get(1, ticket)
                self.assertEqual(busy.exception.status, 503)
                self.assertIsNotNone(store.remember(2, 'Texto não bloqueado'))
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=2), ('audio/mpeg', b'ok'))
