"""IPC real em loopback, roteador real; sem HA, provedores, áudio ou dados da casa."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from refatored import app, domus_bridge as bridge, speech_output
from refatored.memory_store import MemoryStore


class TestDomusBridge(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        use = self.resources.enter_context
        tmp = use(tempfile.TemporaryDirectory())
        store = MemoryStore(str(Path(tmp) / 'notes.db'))
        use(patch.object(store, '_fetch_gemini_embedding', return_value=None))
        for module in ('domus_bridge', 'memory_store', 'skills', 'intent_router'):
            use(patch('refatored.' + module + '.memory_store', store))
        bridge.conversation_memory.clear()
        bridge.timer_manager.cancel_all()
        self.addCleanup(bridge.timer_manager.cancel_all)
        self.addCleanup(bridge.conversation_memory.clear)
        self.say = use(patch.object(speech_output.tts_manager, 'falar'))
        self.bip = use(patch.object(speech_output, 'play_audio_file', return_value=True))
        self.env = use(patch.dict(os.environ, {'DOMUS_BRIDGE_ENABLED': 'true', 'DOMUS_SHARE_NOTES': 'true'}))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.Handler)
        self.port = self.server.server_port
        use(patch.object(bridge, 'ThreadingHTTPServer', return_value=self.server))
        use(bridge.running_bridge())

    def call(self, method='GET', route='state', profile='1', payload=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        headers = {'Content-Type': 'application/json'}
        if profile is not None:
            headers['x-domus-profile'] = profile
        try:
            conn.request(method, bridge.PREFIX + route,
                         None if payload is None else json.dumps(payload).encode(), headers)
            res = conn.getresponse()
            if res.headers.get_content_type().startswith("audio/"):
                return res.status, (res.headers, res.read())
            return res.status, json.load(res)
        finally:
            conn.close()

    def send(self, text, speak=False):
        code, body = self.call('POST', 'messages', payload={'text': text, 'speak_on_pi': speak})
        self.assertEqual(code, 200, body)
        return body['text']

    def test_voice_timer_visible_to_both_profiles_and_cancelled_via_http(self):
        self.assertIs(app.intent_router, bridge.intent_router)
        with app.TURN_LOCK:
            app.intent_router.processar_mensagem('coloca um timer de 3 minutos para o chá')
        self.say.assert_called_once()
        code, snapshot = self.call(profile='2')
        self.assertEqual((code, snapshot['profile_id'], snapshot['version']), (200, 2, 1))
        self.assertEqual(len(snapshot['timers']), 1)
        timer = snapshot['timers'][0]
        self.assertIn('chá', timer['label'])
        delta = datetime.fromisoformat(timer['ends_at']) - datetime.now(timezone.utc)
        self.assertTrue(170 < delta.total_seconds() <= 181)
        self.assertEqual(self.call()[1]['timers'][0]['id'], timer['id'])
        self.assertIn('chá', snapshot['history'][0]['content'])
        self.assertIn('cancel', self.send('cancela o timer'))
        self.assertEqual(app.timer_manager.snapshot(), [])
        self.say.assert_called_once()  # nenhuma fala da resposta móvel silenciosa

    def test_voice_then_mobile_anaphora_uses_same_ha_target(self):
        with patch('refatored.intent_router.executar_comando_ha', return_value=(True, 'Confirmado.')) as ha:
            with app.TURN_LOCK:
                app.intent_router.processar_mensagem('acender a luz da sala')
            first = ha.call_args.args[0]
            self.assertIn(first['target_name'], self.call()[1]['context'])
            self.assertEqual(self.send('apaga ela', True), 'Confirmado.')
            self.assertEqual(ha.call_count, 2)
            last = ha.call_args.args[0]
            self.assertEqual(last['target_name'], first['target_name'])
            self.assertEqual(last['service'], 'turn_off')
            self.say.assert_called_once_with('Confirmado.')

    def test_mobile_notes_shared_sqlite_not_scheduled_events(self):
        self.send('Lembra que comprar café para a casa')
        self.assertEqual(self.call(profile='2')[1]['agenda'], [{'title': 'comprar café para a casa', 'at': None}])
        with patch.dict(os.environ, {'DOMUS_SHARE_NOTES': 'false'}):
            self.assertIsNone(self.call()[1]['agenda'])

    def test_ttl_context_and_real_primary_model_configuration(self):
        mem = bridge.conversation_memory
        with patch('refatored.conversation_memory.time') as clock, patch.dict(os.environ, {
                'TTS_PROVIDER': '11labs', 'ELEVENLABS_MODEL_ID': 'modelo-teste', 'ELEVENLABS_VOICE_ID': 'voz-teste'}):
            clock.monotonic.return_value = 100
            mem.record_ha_target('sala', 'on')
            mem.add_turn('E a sala?', 'Ligada.')
            snap = self.call()[1]
            self.assertIn('sala', snap['context'])
            self.assertEqual(snap['models']['tts'], {'provider': 'elevenlabs', 'model': 'modelo-teste', 'voice': 'voz-teste'})
            self.assertEqual(snap['models']['llm']['provider'], bridge.llm_client.provider)
            clock.monotonic.return_value += mem._ttl_seconds + 1
            expired = self.call()[1]
            self.assertEqual(expired['history'], [])
            self.assertNotIn('sala', expired['context'])

    def test_streaming_text_and_speech_once_never_starts_inline_audio_worker(self):
        with patch('refatored.intent_router.classificar_mensagem_llm', return_value='conversation'), \
             patch.dict(os.environ, {'LLM_STREAM_TTS': 'true', 'LLM_ENABLE_TOOLS': 'false'}), \
             patch.object(bridge.llm_client, 'chamar_stream_frases', side_effect=lambda **kw: iter(['Uma.', 'Duas.'])), \
             patch.object(speech_output.tts_manager, 'falar_em_stream') as inline_audio:
            self.assertEqual(self.send('Conta uma história de girassóis'), 'Uma. Duas.')
            self.say.assert_not_called()
            self.assertEqual(self.send('Conta outra história de girassóis', True), 'Uma. Duas.')
            self.say.assert_called_once_with('Uma. Duas.')
            inline_audio.assert_not_called()
            self.bip.assert_not_called()

    def test_future_timer_alert_not_muted_by_request_scope(self):
        heard = threading.Event()
        self.say.side_effect = lambda _: heard.set()
        self.send('coloca um timer de 1 segundo')
        # O silêncio está ativo nesta thread; o Timer real usa sua própria thread.
        with speech_output.text_only_response():
            speech_output.falar('não deve tocar')
            self.assertTrue(heard.wait(3))
        self.say.assert_called_once_with('Atenção! O tempo do seu timer acabou!')

    def test_bad_profile_payload_and_busy_do_not_route(self):
        with patch.object(bridge.intent_router, 'processar_mensagem') as router:
            for profile in (None, '0', 'outra'):
                self.assertEqual(self.call(profile=profile)[0], 400)
            for body in ([], {'text': '   '}, {'text': 'x' * 4001}, {'text': 'Oi', 'speak_on_pi': 1},
                         {'text': 'Oi', 'system_prompt': 'x'}):
                self.assertEqual(self.call('POST', 'messages', payload=body)[0], 400)
            with app.TURN_LOCK:  # uma escuta/continuação de voz já está em andamento
                self.assertEqual(self.call('POST', 'messages', payload={'text': 'Oi'})[0], 503)
            router.assert_not_called()

    def test_broken_output_does_not_change_confirmed_text(self):
        self.say.side_effect = OSError('alto-falante simulado indisponível')
        with self.assertLogs(bridge.logger, level='ERROR'):
            self.assertTrue(self.send('Que horas são?', True))
        self.assertEqual(len(self.call()[1]['history']), 2)

    def test_new_store_sanitizes_mobile_note_before_it_appears_in_agenda(self):
        self.send('Lembra que levar café\t\x01   moído ' + 'x' * 550)
        note, = self.call()[1]['agenda']
        self.assertEqual(note, {'title': ('levar café moído ' + 'x' * 550)[:500], 'at': None})

    def test_web_turn_from_phone_uses_restricted_tools_of_new_router(self):
        def simulate_model(*, tools, tool_executor, **_):
            names = {t['function']['name'] for t in tools}
            self.assertIn('pesquisar_na_web', names)
            self.assertNotIn('agendar_timer', names)
            self.assertNotIn('controlar_dispositivo_casa', names)
            self.assertIn('não está disponível', tool_executor('agendar_timer', {'segundos': 600}))
            return 'Consulta de teste concluída.', True

        with patch.dict(os.environ, {'LLM_ENABLE_TOOLS': 'true'}), \
             patch('refatored.intent_router.web_search_client.is_enabled', return_value=True), \
             patch('refatored.intent_router.classificar_mensagem_llm', return_value='conversation'), \
             patch.object(bridge.llm_client, 'chamar_com_tools', side_effect=simulate_model) as llm:
            self.assertEqual(self.send('Pesquisa na web as notícias sobre café.'), 'Consulta de teste concluída.')
            llm.assert_called_once()
        self.assertEqual(bridge.timer_manager.snapshot(), [])

    def test_stop_drains_accepted_post_before_cancelling_timers_and_refuses_new_posts(self):
        entered, finish = threading.Event(), threading.Event()
        real = bridge.intent_router.processar_mensagem

        def hold(text, **kw):
            entered.set()
            if not finish.wait(3):
                raise RuntimeError('A barreira do teste não abriu')
            return real(text, **kw)

        with patch.object(bridge.intent_router, 'processar_mensagem', side_effect=hold) as router, \
             patch.object(app.music_player, 'stop') as stop, ThreadPoolExecutor(2) as workers:
            accepted = workers.submit(self.send, 'Coloca um timer de 3 minutos')
            try:
                self.assertTrue(entered.wait(1))
                shutdown = workers.submit(app._shutdown_services)
                self.assertTrue(bridge._draining.wait(1))
                self.assertEqual(self.call('POST', 'messages', payload={'text': 'Oi'})[0], 503)
                stop.assert_not_called()
            finally:
                finish.set()
            self.assertIn('minuto', accepted.result(timeout=2))
            shutdown.result(timeout=2)
            self.assertEqual(bridge.timer_manager.snapshot(), [])
            self.assertEqual(self.call('POST', 'messages', payload={'text': 'Oi'})[0], 503)
            router.assert_called_once()
            stop.assert_called_once()

    def test_phone_speech_is_separate_audio_not_a_second_command_or_pi_playback(self):
        self.assertTrue(self.call()[1]['capabilities']['reply_audio'])
        with patch.object(bridge.reply_audio, 'synthesize', return_value=(b'RIFF-simulado', '.wav', 'teste')) as synth:
            code, reply = self.call('POST', 'messages', payload={'text': 'Coloca um timer de 3 minutos', 'speak_on_pi': False})
            self.assertEqual(code, 200)
            ref = {'reply_id': reply['reply_id']}
            self.assertRegex(ref['reply_id'], r'^[a-f0-9]{32}$')
            synth.assert_not_called()
            for payload in ({'text': 'texto arbitrário'}, {**ref, 'text': 'outro'}, {'reply_id': 'xx'}):
                self.assertEqual(self.call('POST', 'speech', payload=payload)[0], 400)
            self.assertEqual(self.call('POST', 'speech', profile='2', payload=ref)[0], 410)
            with app.TURN_LOCK:  # a voz da casa pode estar em outro turno
                for _ in range(2):
                    status, (headers, data) = self.call('POST', 'speech', payload=ref)
                    self.assertEqual((status, headers['Content-Type'], headers['x-domus-profile'], data),
                                     (200, 'audio/wav', '1', b'RIFF-simulado'))
            synth.assert_called_once_with(reply['text'])
            self.assertEqual(len(bridge.timer_manager.snapshot()), 1)
            self.say.assert_not_called()
            self.bip.assert_not_called()

    def test_disabled_listener_never_binds(self):
        with patch.dict(os.environ, {'DOMUS_BRIDGE_ENABLED': 'false'}), patch.object(bridge, 'ThreadingHTTPServer') as bind:
            with bridge.running_bridge():
                bind.assert_not_called()
