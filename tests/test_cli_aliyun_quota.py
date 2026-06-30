from __future__ import annotations

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
