"""CA/servidor descartáveis, sem credenciais reais, sem rede fora de loopback."""
import contextlib
import io
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from refatored import home_assistant as ha, verificar_tls_ha as diag


@unittest.skipUnless(ha.requests and shutil.which('openssl'), 'Requer requests e openssl')
class TestHATLS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        d = cls.tmp = Path(temp.name)

        def openssl(*args):
            subprocess.run(['openssl', *args], cwd=d, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Teste Raiz',
                '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', 'raiz.key', '-out', 'raiz.pem')
        for name, subject, issuer, extensions in [
                ('int', 'Teste Intermediaria', 'raiz', 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n'),
                ('servidor', 'localhost', 'int', 'basicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n')]:
            (d/'ext').write_text(extensions)
            openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', f'/CN={subject}',
                    '-keyout', name + '.key', '-out', name + '.csr')
            openssl('x509', '-req', '-in', name + '.csr', '-CA', issuer + '.pem', '-CAkey', issuer + '.key',
                    '-CAcreateserial', '-days', '2', '-extfile', 'ext', '-out', name + '.pem')
        (d/'chain.pem').write_bytes((d/'servidor.pem').read_bytes() + (d/'int.pem').read_bytes())

    def start(self, chain='chain.pem'):
        calls = self.calls = []
        outer = self

        class HA(BaseHTTPRequestHandler):
            def do_GET(self):
                auth = self.headers.get('Authorization')
                body = self.rfile.read(int(self.headers.get('content-length', '0')))
                calls.append((self.command, self.path, auth, body))
                if outer.redirect:
                    self.send_response(307)
                    self.send_header('Location', '/fora')
                else:
                    self.send_response(200 if auth else 401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                obj = {'entity_id': 'switch.sala', 'state': 'on'}
                self.wfile.write(json.dumps([obj] if self.path.endswith('/states') else obj).encode())
            do_POST = do_GET
            def log_message(self, *args):
                pass

        self.redirect = False
        server = ThreadingHTTPServer(('127.0.0.1', 0), HA)
        self.addCleanup(server.server_close)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.tmp/chain, self.tmp/'servidor.key')
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f'https://localhost:{server.server_port}'
        def use(patcher):
            patcher.start()
            self.addCleanup(patcher.stop)
        use(patch.multiple(ha, HA_URL=self.base, HA_CA_BUNDLE=str(self.tmp/'raiz.pem'),
                                        HEADERS_HA={'Authorization': 'Bearer teste-local'}))
        use(patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*', 'REQUESTS_CA_BUNDLE': '', 'CURL_CA_BUNDLE': ''}))
        use(patch.object(ha, 'conversation_memory'))

    cmd = {'domain': 'switch', 'service': 'turn_on', 'entity_id': 'switch.sala'}

    def test_trusts_chain_and_checks_list_single_and_write(self):
        self.start()
        self.assertIn('sala', ha.listar_dispositivos_ligados_ha())
        self.assertIn('acesa', ha.consultar_estado_dispositivo_ha('luz da sala'))
        self.assertTrue(ha.executar_comando_ha(self.cmd)[0])
        self.assertEqual([(m, p) for m, p, _, _ in self.calls], [('GET', '/api/states'), ('GET', '/api/states/switch.sala'), ('POST', '/api/services/switch/turn_on')])
        self.assertTrue(all(auth == 'Bearer teste-local' for _, _, auth, _ in self.calls))
        self.assertEqual(json.loads(self.calls[-1][-1]), {'entity_id': 'switch.sala'})
        # Nenhuma mudança de confiança no requests usado por web/música/TTS.
        with self.assertRaises(ha.requests.exceptions.SSLError):
            ha.requests.get(self.base, timeout=2)

    def test_unknown_ca_wrong_san_and_missing_file_no_authenticated_request(self):
        self.start()
        with patch.object(ha, 'HA_CA_BUNDLE', ''):
            self.assertIn('TLS', ha.listar_dispositivos_ligados_ha())
        with patch.object(ha, 'HA_URL', self.base.replace('localhost', '127.0.0.1')):
            self.assertIn('TLS', ha.consultar_estado_dispositivo_ha('luz da sala'))
            self.assertFalse(ha.executar_comando_ha(self.cmd)[0])
        for invalid in (str(self.tmp/'ausente.pem'), 'False', 'relativo.crt'):
            with patch.object(ha, 'HA_CA_BUNDLE', invalid):
                self.assertIn('HA_CA_BUNDLE', ha.listar_dispositivos_ligados_ha())
        self.assertEqual(self.calls, [])

    def test_server_omits_intermediate(self):
        self.start('servidor.pem')
        self.assertIn('TLS', ha.listar_dispositivos_ligados_ha())
        self.assertEqual(self.calls, [])

    def test_diag_uses_venv_trust_and_never_sends_token_even_with_netrc(self):
        self.start()
        creds = self.tmp/'dummy.netrc'
        creds.write_text('machine localhost login simulado password simulado\n')
        with patch.dict(os.environ, {'NETRC': str(creds)}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(diag.main(), 0)
            self.assertIn('401', out.getvalue())
            self.assertNotIn('Bearer', out.getvalue())
        self.assertEqual(self.calls, [('GET', '/api/', None, b'')])

    def test_no_redirect_no_automatic_downgrade(self):
        self.start()
        self.redirect = True
        self.assertFalse(ha.executar_comando_ha(self.cmd)[0])
        with patch.object(ha, 'HA_URL', 'http://ha.home'), patch.object(ha, 'HA_CA_BUNDLE', ''):
            self.assertIn('HTTPS', ha.listar_dispositivos_ligados_ha())
        with patch.object(ha, 'HA_URL', 'http://127.0.0.1:8123'):
            self.assertFalse(ha.executar_comando_ha(self.cmd)[0])  # CA informada exige HTTPS até em loopback
            with patch.object(ha, 'HA_CA_BUNDLE', ''):
                self.assertIs(ha._transport_options()['verify'], True)
        self.assertEqual(len(self.calls), 1)
