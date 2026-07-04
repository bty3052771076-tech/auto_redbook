from __future__ import annotations

import json

from typer.testing import CliRunner

import apps.cli as cli
from src.volcengine.quota import VolcengineQuotaRecord


def test_volcengine_quota_cli_prints_records_from_console_reader(monkeypatch):
    def fake_collect(**kwargs):
        return {
            "source_url": "https://console.volcengine.com/ark/region:cn-beijing/usage",
            "records": [
                VolcengineQuotaRecord(
                    model="doubao-seed-2-1-turbo-260628",
                    kind="llm",
                    total=500000,
                    used=12000,
                    remaining=488000,
                    unit="token",
                    expires_at="2026-08-01",
                    raw_text="doubao-seed-2-1-turbo-260628 token 500000 12000 488000 2026-08-01",
                )
            ],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        [
            "volcengine-quota",
            "--model",
            "doubao-seed-2-1-turbo-260628",
            "--login-hold",
            "0",
            "--wait-timeout",
            "60",
        ],
    )

    assert result.exit_code == 0
    assert "Volcengine Ark quota" in result.output
    assert "doubao-seed-2-1-turbo-260628" in result.output
    assert "488000" in result.output
    assert "usage" in result.output


def test_volcengine_quota_cli_can_save_raw_snapshot(monkeypatch, tmp_path):
    def fake_collect(**kwargs):
        return {
            "source_url": "https://console.volcengine.com/ark/region:cn-beijing/usage",
            "records": [
                VolcengineQuotaRecord(
                    model="glm-5.2",
                    kind="llm",
                    total=140000,
                    used=15000,
                    remaining=125000,
                    unit="token",
                    expires_at="2026-08-31",
                    raw_text="glm-5.2 token 140000 15000 125000 2026-08-31",
                    status="available",
                )
            ],
            "raw_text": "visible ark console text",
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        [
            "volcengine-quota",
            "--model",
            "glm-5.2",
            "--save-raw",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "snapshot:" in result.output
    files = list(tmp_path.glob("volcengine_quota_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["provider"] == "volcengine"
    assert payload["raw_text"] == "visible ark console text"
    assert payload["records"][0]["status"] == "available"


def test_volcengine_quota_cli_passes_visible_only(monkeypatch):
    captured: dict[str, object] = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "source_url": "https://console.volcengine.com/ark/region:cn-beijing/usage",
            "records": [],
            "raw_text": "visible page text",
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_collect)

    result = CliRunner().invoke(
        cli.app,
        ["volcengine-quota", "--model", "glm-5.2", "--visible-only", "--login-hold", "0"],
    )

    assert result.exit_code == 0
    assert captured["visible_only"] is True
