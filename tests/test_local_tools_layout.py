import importlib
from pathlib import Path

import src.ai_digest.rsshub_local as rsshub


def test_rsshub_default_is_inside_workflow(monkeypatch):
    monkeypatch.delenv("RSSHUB_DIR", raising=False)
    importlib.reload(rsshub)
    assert rsshub.RSSHUB_DIR == Path(__file__).resolve().parents[1] / "tools/RSSHub"


def test_rsshub_log_is_in_data_not_tool_root(monkeypatch, tmp_path):
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setattr(rsshub, "rsshub_alive", lambda *a, **k: False)
    root = tmp_path / "tools/RSSHub"
    (root / "dist").mkdir(parents=True)
    (root / "dist/index.mjs").touch()
    monkeypatch.setattr(rsshub, "RSSHUB_DIR", root)
    captured = {}

    def spawn(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(rsshub.subprocess, "Popen", spawn)
    monkeypatch.setattr(rsshub.time, "sleep", lambda *_: None)
    assert rsshub.start_rsshub_if_needed() is False
    assert Path(captured["stdout"].name) == tmp_path / "data/logs/rsshub/stdout.log"
    assert captured["env"]["NODE_ENV"] == "production"
    assert captured["env"]["LISTEN_INADDR_ANY"] == "0"
    assert captured["env"]["PORT"] == str(rsshub.RSSHUB_PORT)
    assert not (root / "rsshub-stdout.log").exists()
