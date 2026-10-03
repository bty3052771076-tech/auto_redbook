from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import WorldMonitorClient, WorldMonitorError


def _npm_executable() -> str:
    """Resolve npm for subprocess use; PowerShell's npm.ps1 is not executable by Popen."""
    if os.name == "nt":
        return shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
    return shutil.which("npm") or "npm"


def _node_executable() -> str:
    return shutil.which("node.exe" if os.name == "nt" else "node") or ("node.exe" if os.name == "nt" else "node")


@dataclass(frozen=True)
class RuntimeProbe:
    ready: bool
    reused: bool = False
    started: bool = False
    error_code: str = ""
    message: str = ""


class WorldMonitorRuntime:
    """On-demand local service lifecycle; it never starts at application boot."""

    def __init__(self, client: WorldMonitorClient, *, root: Path | None = None, auto_start: bool = False, port: int = 3000):
        self.client = client
        self.root = Path(root).resolve() if root else None
        self.auto_start = bool(auto_start)
        self.port = int(port)
        self._process: subprocess.Popen | None = None
        self._probe: RuntimeProbe | None = None

    def ensure_ready(self) -> RuntimeProbe:
        if self._probe is not None and self._probe.ready:
            return RuntimeProbe(**{**self._probe.__dict__, "reused": True})
        try:
            self.client.fetch_digest()
            self._probe = RuntimeProbe(ready=True)
            return self._probe
        except WorldMonitorError as first_error:
            if not self.auto_start or not self.root or not (self.root / "package.json").is_file():
                self._probe = RuntimeProbe(False, error_code=first_error.code, message=str(first_error))
                return self._probe
            try:
                launcher = Path(__file__).resolve().parents[3] / "scripts" / "worldmonitor_headless.mjs"
                if not launcher.is_file():
                    raise OSError(f"headless launcher missing: {launcher}")
                self._process = subprocess.Popen(
                    [_node_executable(), str(launcher), "--root", str(self.root), "--port", str(self.port)],
                    cwd=str(self.root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    ),
                    env={**os.environ, "BROWSER": "none"},
                )
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    try:
                        self.client.fetch_digest(reuse_cycle=False)
                        self._probe = RuntimeProbe(True, started=True)
                        return self._probe
                    except WorldMonitorError:
                        time.sleep(0.4)
            except OSError as exc:
                self._probe = RuntimeProbe(False, error_code="WM_NOT_READY", message=str(exc))
                return self._probe
            self.release()
            self._probe = RuntimeProbe(False, error_code="WM_NOT_READY", message="local service did not become ready")
            return self._probe

    def release(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if os.name == "nt" and getattr(process, "pid", None):
            # npm.cmd leaves Vite's node child alive after the wrapper exits.
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired:
                return
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
