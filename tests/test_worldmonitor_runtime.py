from __future__ import annotations

from dataclasses import dataclass

from src.integrations.worldmonitor.models import WorldMonitorBatch, WorldMonitorCoverage
from src.integrations.worldmonitor.runtime import WorldMonitorRuntime
from src.integrations.worldmonitor import runtime as runtime_module


@dataclass
class FakeClient:
    calls: int = 0

    def fetch_digest(self):
        self.calls += 1
        return WorldMonitorBatch(items=[], categories={}, coverage=WorldMonitorCoverage(state="fresh"))


def test_runtime_reuses_single_probe_for_one_collection_cycle():
    client = FakeClient()
    runtime = WorldMonitorRuntime(client=client)

    first = runtime.ensure_ready()
    second = runtime.ensure_ready()

    assert first.ready is True
    assert second.ready is True
    assert client.calls == 1
    assert first.reused is False
    assert second.reused is True


def test_runtime_resolves_windows_npm_cmd_for_subprocess(monkeypatch):
    monkeypatch.setattr(runtime_module.os, "name", "nt")
    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: "D:/nodejs/npm.cmd" if name == "npm.cmd" else None)

    assert runtime_module._npm_executable() == "D:/nodejs/npm.cmd"


def test_runtime_releases_windows_process_tree(monkeypatch):
    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

    calls = []
    monkeypatch.setattr(runtime_module.os, "name", "nt")
    monkeypatch.setattr(
        runtime_module.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    runtime = WorldMonitorRuntime(client=FakeClient())
    runtime._process = FakeProcess()

    runtime.release()

    assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    assert runtime._process is None
