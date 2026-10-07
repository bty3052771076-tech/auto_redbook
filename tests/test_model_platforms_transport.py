import datetime
import json
import select
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.model_platforms import PlatformStore, RuntimeClient
from src.model_platforms import runtime


def test_https_proxy_connect_uses_checked_ip_and_verified_original_hostname(tmp_path, monkeypatch):
    hostname = 'model-api.example.test'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1)).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'fixture-cert.pem', tmp_path / 'fixture-key.pem'
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    observed = {'connect': [], 'sni': [], 'host': []}

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            observed['host'].append(self.headers['Host'])
            body = json.dumps({'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    tls.set_servername_callback(lambda sock, name, ctx: observed['sni'].append(name))
    upstream.socket = tls.wrap_socket(upstream.socket, server_side=True)

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_CONNECT(self):
            observed['connect'].append(self.path)
            assert self.path == f'127.0.0.1:{upstream.server_port}'
            with socket.create_connection(('127.0.0.1', upstream.server_port), timeout=5) as remote:
                self.send_response(200)
                self.end_headers()
                self.wfile.flush()
                sockets = [self.connection, remote]
                while True:
                    ready, _, _ = select.select(sockets, [], [], 5)
                    if not ready:
                        break
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (remote if source is self.connection else self.connection).sendall(data)

    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    for server in (upstream, proxy):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    original_init = runtime.OriginTLSContext.__init__

    def trust_fixture(self, host):
        original_init(self, host)
        self.load_verify_locations(cafile=str(cert_path))

    monkeypatch.setattr(runtime.OriginTLSContext, '__init__', trust_fixture)
    monkeypatch.setattr(runtime, 'pinned_address', lambda *args: '127.0.0.1')
    monkeypatch.setattr(runtime, 'proxy_bypass', lambda *args: False)
    monkeypatch.setattr(runtime, 'getproxies', lambda: {'https': f'http://127.0.0.1:{proxy.server_port}'})
    store = PlatformStore(tmp_path / 'registry', env={'FIXTURE_KEY': 'synthetic-proxy-canary'})
    conn = store.add_connection({'name': 'TLS fixture', 'base_url': f'https://{hostname}:{upstream.server_port}/v1',
                                 'credential_env': 'FIXTURE_KEY'})
    model = store.add_model({'connection_id': conn['connection_id'], 'upstream_model_id': 'fixture', 'enabled': True}, store.state()['revision'])
    store.authorize(conn['connection_id'], {'roles': ['writer'], 'max_requests': 1, 'risk_accepted': True,
                    'expires_at': now.timestamp() + 60}, store.state()['revision'])
    try:
        snapshot = store.resolve('writer', model['model_ref'], require_verified=False)
        assert RuntimeClient(store).call(snapshot, [{'role': 'user', 'content': 'hello'}]).text == 'OK'
        assert observed == {'connect': [f'127.0.0.1:{upstream.server_port}'], 'sni': [hostname],
                            'host': [f'{hostname}:{upstream.server_port}']}
    finally:
        for server in (proxy, upstream):
            server.shutdown()
            server.server_close()


def test_interrupted_operation_is_failed_without_automatic_request(tmp_path):
    from src.model_platforms.service import read_operation
    from src.model_platforms.store import atomic_json
    from src.model_platforms.security import file_lock
    path = tmp_path / 'operation.json'
    atomic_json(path, {'status': 'running', 'operation_id': 'a' * 32})
    with file_lock(path.with_suffix('.lease')):
        assert read_operation(path)['status'] == 'running'
    recovered = read_operation(path)
    assert recovered['status'] == 'failed' and recovered['code'] == 'OPERATION_INTERRUPTED'


def test_cross_process_cas_and_shared_model_queue(tmp_path):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path
    env = {name: os.environ[name] for name in ('SYSTEMROOT', 'WINDIR', 'PATH') if name in os.environ}
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    create_script = '''
import sys
from src.model_platforms import PlatformStore, PlatformError
try:
    PlatformStore(sys.argv[1], env={}).add_connection({'name':'local','base_url':'http://127.0.0.1:11434/v1','network':'local','auth_mode':'none'}, 0)
    print('created')
except PlatformError as exc:
    print(exc.code)
'''
    workers = [subprocess.Popen([sys.executable, '-c', create_script, str(tmp_path)], env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = [worker.communicate(timeout=15) for worker in workers]
    assert sorted(out.strip() for out, err in outputs) == ['REVISION_CONFLICT', 'created'], outputs
    assert all(worker.returncode == 0 for worker in workers)
    store = PlatformStore(tmp_path, env={})
    connection = store.state()['connections'][0]
    store.edit_connection(connection['connection_id'], {'concurrency': 1}, store.state()['revision'])
    model = store.add_model({'connection_id': connection['connection_id'], 'upstream_model_id': 'fixture', 'enabled': True}, store.state()['revision'])
    store.authorize(connection['connection_id'], {'roles': ['writer'], 'max_requests': 2, 'risk_accepted': True,
        'expires_at': time.time() + 60}, store.state()['revision'])
    queue_script = '''
import json, sys, time, httpx
from src.model_platforms import PlatformStore, RuntimeClient
store = PlatformStore(sys.argv[1], env={})
def reply(request):
    start = time.time()
    time.sleep(.3)
    print(json.dumps([start, time.time()]), flush=True)
    return httpx.Response(200, json={'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]})
snapshot = store.resolve('writer', sys.argv[2], require_verified=False)
RuntimeClient(store, transport=httpx.MockTransport(reply)).call(snapshot, [{'role':'user','content':'hello'}])
'''
    workers = [subprocess.Popen([sys.executable, '-c', queue_script, str(tmp_path), model['model_ref']], env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = [worker.communicate(timeout=15) for worker in workers]
    assert all(worker.returncode == 0 for worker in workers), outputs
    intervals = sorted(json.loads(out) for out, err in outputs)
    assert intervals[1][0] >= intervals[0][1]
    assert sum(json.loads((tmp_path / 'usage.json').read_text()).values()) == 2
