from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import apps.cli as cli
from src.aliyun.quota import AliyunQuotaRecord


def test_aliyun_quota_cli_prints_records_from_console_reader(monkeypatch):
    def fake_collect(**kwargs):
        return {
            "source_url": "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance",
            "records": [
                AliyunQuotaRecord(
                    model="qwen3.7-plus",
                    kind="llm",
                    total=1000,
                    used=200,
                    remaining=800,
                    unit="Token",
                    expires_at="2026-07-31",
                    raw_text="qwen3.7-plus Token 1000 200 800 2026-07-31",
                )
            ],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        ["aliyun-quota", "--model", "qwen3.7-plus", "--login-hold", "0", "--wait-timeout", "60"],
    )

    assert result.exit_code == 0
    assert "Aliyun Bailian quota" in result.output
    assert "qwen3.7-plus" in result.output
    assert "800" in result.output
    assert "costing-balance" in result.output


def test_aliyun_quota_cli_can_save_raw_snapshot(monkeypatch, tmp_path):
    def fake_collect(**kwargs):
        return {
            "source_url": "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance",
            "records": [
                AliyunQuotaRecord(
                    model="qwen3.7-plus",
                    kind="llm",
                    total=1000,
                    used=200,
                    remaining=800,
                    unit="Token",
                    expires_at="2026-07-31",
                    raw_text="qwen3.7-plus Token 1000 200 800 2026-07-31",
                    status="available",
                )
            ],
            "raw_text": "visible console text",
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        [
            "aliyun-quota",
            "--model",
            "qwen3.7-plus",
            "--save-raw",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "snapshot:" in result.output
    files = list(tmp_path.glob("aliyun_quota_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["provider"] == "aliyun"
    assert payload["raw_text"] == "visible console text"
    assert payload["records"][0]["status"] == "available"


def test_aliyun_quota_cli_passes_visible_only(monkeypatch):
    captured: dict[str, object] = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "source_url": "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance",
            "records": [],
            "raw_text": "visible page text",
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        ["aliyun-quota", "--model", "glm-5.2", "--visible-only", "--login-hold", "0"],
    )

    assert result.exit_code == 0
    assert captured["visible_only"] is True


def test_aliyun_quota_open_only_uses_workspace_profile_script(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        cli.webbrowser,
        "open",
        lambda *_args, **_kwargs: pytest.fail("open-only must not use the default browser"),
    )

    result = CliRunner().invoke(cli.app, ["aliyun-quota", "--open-only"])

    assert result.exit_code == 0
    assert calls
    command = [str(item) for item in calls[0][0][0]]
    assert command[0].lower() in {"powershell.exe", "powershell"}
    expected_script = Path(cli.__file__).resolve().parents[1] / "scripts" / "open_aliyun_console.ps1"
    assert command[-2:] == ["-File", str(expected_script)]
