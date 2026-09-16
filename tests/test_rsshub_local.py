"""On-demand RSSHub local start must never autostart."""

import importlib

import src.ai_digest.rsshub_local as mod


def test_rsshub_module_exposes_on_demand_only_api():
    importlib.reload(mod)
    assert callable(mod.start_rsshub_if_needed)
    assert callable(mod.rsshub_alive)
    assert "RSSHUB_DIR" in mod.__dict__


def test_rsshub_start_returns_true_when_already_running(monkeypatch):
    monkeypatch.setattr(mod, "rsshub_alive", lambda *a, **k: True)
    assert mod.start_rsshub_if_needed() is True


def test_rsshub_start_returns_false_without_install(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "rsshub_alive", lambda *a, **k: False)
    monkeypatch.setattr(mod, "RSSHUB_DIR", tmp_path)
    assert mod.start_rsshub_if_needed() is False
