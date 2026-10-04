"""Boot only local news services for a smoke check and close owned processes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen


def smoke(root: Path, runtime: Path, port: int) -> None:
    if (root / "apps").is_dir():
        sys.path.insert(0, str(root))
    from src.integrations.worldmonitor.client import WorldMonitorClient
    from src.integrations.worldmonitor.runtime import WorldMonitorRuntime
    logs = runtime / "data/logs/local-tools"
    logs.mkdir(parents=True, exist_ok=True)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is missing")
    rss_env = {**os.environ, "PORT": str(port), "NODE_ENV": "production", "LISTEN_INADDR_ANY": "0"}
    with (logs / "rsshub-smoke.log").open("ab") as log:
        rss = subprocess.Popen([node, "dist/index.mjs"], cwd=root / "tools/RSSHub",
            env=rss_env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 30
            ready = False
            while time.monotonic() < deadline and rss.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except OSError:
                    time.sleep(0.3)
            if not ready:
                raise RuntimeError(f"RSSHub copy did not start; inspect {logs / 'rsshub-smoke.log'}")
            print("RSSHub copy responded HTTP 200")
        finally:
            if rss.poll() is None:
                rss.terminate()
                try:
                    rss.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    rss.kill()
                    rss.wait(timeout=5)
    client = WorldMonitorClient(f"http://127.0.0.1:{port + 1}", timeout=8)
    world = WorldMonitorRuntime(client, root=root / "tools/worldmonitor", auto_start=True, port=port + 1)
    try:
        probe = world.ensure_ready()
        if not probe.ready:
            raise RuntimeError(f"World Monitor copy failed: {probe.error_code}: {probe.message}")
        batch = client.fetch_digest()
        print(json.dumps({"worldmonitor_ready": True, "items": len(batch.items),
                          "coverage": batch.coverage.state}, ensure_ascii=False))
    finally:
        world.release()
    print("Smoke services closed; no generation or publishing invoked")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--port", type=int, default=12110)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    smoke(root, args.runtime_root or root, args.port)
