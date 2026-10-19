"""Ensure the AI digest auto flow starts a local RSSHub when needed."""

import os
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RSSHUB_DIR = Path(os.getenv("RSSHUB_DIR") or PROJECT_ROOT / "tools/RSSHub")
RSSHUB_PORT = int(os.getenv("RSSHUB_PORT", "1200"))
RSSHUB_URL = f"http://127.0.0.1:{RSSHUB_PORT}"


def rsshub_alive(timeout_s: float = 1.0) -> bool:
    connection = HTTPConnection("127.0.0.1", RSSHUB_PORT, timeout=timeout_s)
    try:
        # Loopback health must not inherit an outbound HTTP proxy or render
        # RSSHub's homepage. The deployed server exposes a cheap healthz route.
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        return response.status == 200 and response.read(3) == b"ok"
    except (OSError, HTTPException):
        return False
    finally:
        connection.close()


def start_rsshub_if_needed() -> bool:
    """Start RSSHub on demand; never scheduled, never autostarted."""
    deadline = time.monotonic() + 15.0
    if rsshub_alive():
        os.environ.setdefault("AI_DIGEST_RSSHUB_BASE_URL", RSSHUB_URL)
        return True
    if not (RSSHUB_DIR / "dist" / "index.mjs").exists():
        return False
    try:
        with socket.create_connection(("127.0.0.1", RSSHUB_PORT), timeout=0.2):
            print("[rsshub] local port occupied but unhealthy; skipping optional source")
            return False
    except OSError:
        pass
    runtime_root = Path(os.getenv("REDBOOK_RUNTIME_ROOT") or PROJECT_ROOT)
    log_path = runtime_root / "data/logs/rsshub/stdout.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                ["node", "dist/index.mjs"],
                cwd=str(RSSHUB_DIR),
                env={**os.environ, "NODE_ENV": "production", "LISTEN_INADDR_ANY": "0", "PORT": str(RSSHUB_PORT)},
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except OSError:
        return False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if rsshub_alive(timeout_s=min(1.0, remaining)):
            os.environ.setdefault("AI_DIGEST_RSSHUB_BASE_URL", RSSHUB_URL)
            return True
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    # Only terminate the child we created, never an existing user's service.
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    return False


if __name__ == "__main__":
    ok = start_rsshub_if_needed()
    print(f"[rsshub] local service: {'ready' if ok else 'unavailable'} at {RSSHUB_URL}")
    sys.exit(0 if ok else 0)  # never block the digest on the optional source
