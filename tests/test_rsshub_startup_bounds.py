import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

from src.ai_digest import rsshub_local as local


def entrypoint(tmp_path, monkeypatch):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/index.mjs").write_text("// offline fixture", encoding="utf-8")
    monkeypatch.setattr(local, "RSSHUB_DIR", tmp_path)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))


def test_health_probe_uses_healthz_and_never_uses_proxy(monkeypatch):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200 if self.path == "/healthz" else 503)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(local, "RSSHUB_PORT", server.server_port)
    monkeypatch.setattr(local, "RSSHUB_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        assert local.rsshub_alive(timeout_s=0.5)
        assert paths == ["/healthz"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_occupied_unhealthy_port_does_not_spawn_another_server(tmp_path, monkeypatch):
    entrypoint(tmp_path, monkeypatch)
    monkeypatch.setattr(local, "rsshub_alive", lambda **kw: False)
    monkeypatch.setattr(local.subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("duplicate server")))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setattr(local, "RSSHUB_PORT", listener.getsockname()[1])
        assert local.start_rsshub_if_needed() is False


def test_failed_child_exits_without_thirty_health_poll_rounds(tmp_path, monkeypatch):
    entrypoint(tmp_path, monkeypatch)
    monkeypatch.setattr(local, "rsshub_alive", lambda **kw: False)
    monkeypatch.setattr(local.socket, "create_connection", lambda *a, **kw: (_ for _ in ()).throw(ConnectionRefusedError()))
    monkeypatch.setattr(local.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(poll=lambda: 1))
    sleeps = []
    monkeypatch.setattr(local.time, "sleep", sleeps.append)
    assert local.start_rsshub_if_needed() is False
    assert sleeps == []


def test_startup_deadline_stops_only_the_child_it_started(tmp_path, monkeypatch):
    entrypoint(tmp_path, monkeypatch)
    now, terminated = [0.0], []
    monkeypatch.setattr(local.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(local.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(local.socket, "create_connection", lambda *a, **kw: (_ for _ in ()).throw(ConnectionRefusedError()))

    def unhealthy(**kwargs):
        now[0] += kwargs.get("timeout_s", 3)
        return False

    monkeypatch.setattr(local, "rsshub_alive", unhealthy)
    child = SimpleNamespace(poll=lambda: None, terminate=lambda: terminated.append(True), wait=lambda **kw: 0)
    monkeypatch.setattr(local.subprocess, "Popen", lambda *a, **kw: child)
    assert local.start_rsshub_if_needed() is False
    assert now[0] <= 15
    assert terminated == [True]
