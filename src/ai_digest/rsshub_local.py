"""Ensure the AI digest auto flow starts a local RSSHub when needed."""

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RSSHUB_DIR = Path(os.getenv("RSSHUB_DIR") or PROJECT_ROOT / "tools/RSSHub")
RSSHUB_PORT = int(os.getenv("RSSHUB_PORT", "1200"))
RSSHUB_URL = f"http://127.0.0.1:{RSSHUB_PORT}"


def rsshub_alive(timeout_s: float = 3.0) -> bool:
    try:
        with urlopen(RSSHUB_URL, timeout=timeout_s):
            return True
    except Exception:
        return False


def start_rsshub_if_needed() -> bool:
    """Start RSSHub on demand; never scheduled, never autostarted."""
    if rsshub_alive():
        os.environ.setdefault("AI_DIGEST_RSSHUB_BASE_URL", RSSHUB_URL)
        return True
    if not (RSSHUB_DIR / "dist" / "index.mjs").exists():
        return False
    runtime_root = Path(os.getenv("REDBOOK_RUNTIME_ROOT") or PROJECT_ROOT)
    log_path = runtime_root / "data/logs/rsshub/stdout.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen(
            ["node", "dist/index.mjs"],
            cwd=str(RSSHUB_DIR),
            env={**os.environ, "NODE_ENV": "production", "LISTEN_INADDR_ANY": "0", "PORT": str(RSSHUB_PORT)},
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    for _ in range(30):
        time.sleep(1)
        if rsshub_alive():
            os.environ.setdefault("AI_DIGEST_RSSHUB_BASE_URL", RSSHUB_URL)
            return True
    return False


if __name__ == "__main__":
    ok = start_rsshub_if_needed()
    print(f"[rsshub] local service: {'ready' if ok else 'unavailable'} at {RSSHUB_URL}")
    sys.exit(0 if ok else 0)  # never block the digest on the optional source
