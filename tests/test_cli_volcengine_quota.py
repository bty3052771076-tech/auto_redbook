from __future__ import annotations

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
