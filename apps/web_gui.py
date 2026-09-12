"""Loopback-only HTTP host for the built React workbench and JSON adapter."""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import os
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from apps.web_service import ROOT, Workbench, read_json, valid_id


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, dev_origin=None):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        self.dev_origin = dev_origin
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, fmt, *args):
        pass

    def reply(self, data, status=200, mime="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if self.headers.get("Origin") == self.server.dev_origin:
            self.send_header("Access-Control-Allow-Origin", self.server.dev_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def guard(self, authenticate=True):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != host:
            raise PermissionError("仅允许通过本机 127.0.0.1 访问")
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}", self.server.dev_origin}:
            raise PermissionError("已拒绝外部网页访问")
        if self.headers.get("Sec-Fetch-Site") == "cross-site" and origin != self.server.dev_origin:
            raise PermissionError("已拒绝跨站请求")
        if authenticate:
            bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
            cookie = self.headers.get("Cookie", "")
            cookie_token = next((s.strip()[8:] for s in cookie.split(";") if s.strip().startswith("web_gui=")), "")
            if not (secrets.compare_digest(bearer, self.server.token) or secrets.compare_digest(cookie_token, self.server.token)):
                raise PermissionError("会话已失效，请刷新界面")
            if self.command != "GET" and self.headers.get("X-Workbench") != "1":
                raise PermissionError("缺少请求校验头")

    def do_OPTIONS(self):
        try:
            self.guard(False)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", ""))
            self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type,X-Workbench,Idempotency-Key")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
            self.end_headers()
        except PermissionError as exc:
            self.reply({"error": str(exc)}, 403)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.dispatch()

    def dispatch(self):
        try:
            path = urlsplit(self.path).path
            service = self.server.service
            self.guard(False)
            if path == "/api/session" and self.command == "POST":
                if self.headers.get("X-Workbench") != "1":
                    raise PermissionError("缺少会话校验头")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Set-Cookie", f"web_gui={self.server.token}; HttpOnly; SameSite=Strict; Path=/")
                if self.headers.get("Origin") == self.server.dev_origin:
                    self.send_header("Access-Control-Allow-Origin", self.server.dev_origin)
                self.end_headers()
                self.wfile.write(json.dumps({"token": self.server.token}).encode())
                return
            if not path.startswith("/api/"):
                if self.command != "GET":
                    raise ValueError("不支持的请求")
                dist = (ROOT / "frontend/dist").resolve()
                file = (dist / (path.lstrip("/") or "index.html")).resolve()
                if not file.is_relative_to(dist):
                    raise PermissionError("路径不合法")
                if not file.exists():
                    file = dist / "index.html"
                if not file.exists():
                    self.reply({"error": "React GUI 尚未构建，请在 frontend 运行 npm run build"}, 503)
                    return
                mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8"}.get(file.suffix)
                self.reply(file.read_bytes(), mime=mime or mimetypes.guess_type(file.name)[0] or "application/octet-stream")
                return
            self.guard()
            data = {}
            if self.command in {"POST", "PUT"}:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2 * 1024 * 1024:
                    raise ValueError("请求为空或超过2MiB")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求格式错误")
            if path == "/api/bootstrap" and self.command == "GET":
                result = service.bootstrap()
            elif path == "/api/models" and self.command == "GET":
                result = service.models()
            elif path == "/api/settings" and self.command == "PUT":
                result = service.save_settings(data)
            elif path == "/api/configuration" and self.command in {"GET", "PUT"}:
                result = service.save_configuration(data) if self.command == "PUT" else service.configuration()
            elif path == "/api/sources" and self.command == "GET":
                result = service.sources()
            elif path == "/api/analysis" and self.command == "GET":
                result = service.analysis()
            elif path == "/api/posts" and self.command == "GET":
                result = service.posts()
            elif path.startswith("/api/posts/"):
                parts = path.split("/")
                if len(parts) == 6 and parts[4] == "images" and self.command == "GET":
                    file = service.image(parts[3], int(parts[5]))
                    self.reply(file.read_bytes(), mime=mimetypes.guess_type(file.name)[0] or "image/png")
                    return
                if len(parts) != 4 or self.command not in {"GET", "PUT"}:
                    raise ValueError("草稿操作无效")
                result = service.edit_post(parts[3], data) if self.command == "PUT" else service.post(parts[3])
            elif path == "/api/metrics" and self.command == "GET":
                result = service.metrics()
            elif path == "/api/remote" and self.command == "GET":
                result = read_json(service.directory / "remote.json", {"rows": [], "captured_at": None, "complete": None})
            elif path == "/api/jobs":
                result = service.submit(data, self.headers.get("Idempotency-Key", "")) if self.command == "POST" else service.list_jobs()
            elif path.startswith("/api/jobs/"):
                parts = path.split("/")
                job_id = valid_id(parts[3])
                if len(parts) == 5 and parts[4] == "stop" and self.command == "POST":
                    result = service.stop(job_id)
                elif len(parts) == 4 and self.command == "GET":
                    result = service.job_detail(job_id)
                else:
                    raise ValueError("任务操作无效")
            else:
                self.reply({"error": "接口不存在"}, 404)
                return
            self.reply(result)
        except PermissionError as exc:
            self.reply({"error": str(exc)}, 403)
        except (ValueError, RuntimeError, KeyError, FileNotFoundError) as exc:
            self.reply({"error": self.server.service.redact(str(exc))}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.reply({"error": self.server.service.redact(f"操作失败：{exc}")}, 500)


@contextmanager
def single_server():
    path = ROOT / "data/web_gui/server.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有工作台服务正在运行，请使用已有窗口；禁止重复服务占用同一 profile") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dev-origin", default=None)
    parser.add_argument("--open-browser", action="store_true", help="服务启动后使用系统默认浏览器打开本地工作台")
    args = parser.parse_args()
    if args.dev_origin and args.dev_origin != "http://127.0.0.1:5173":
        parser.error("开发来源仅允许 http://127.0.0.1:5173")
    with single_server():
        server = Server(("127.0.0.1", args.port), Workbench(), args.dev_origin)
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"React GUI: {url}", flush=True)
        if args.open_browser:
            webbrowser.open_new_tab(url)
            print(f"Default browser opened: {url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
