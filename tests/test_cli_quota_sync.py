from __future__ import annotations

import json

from typer.testing import CliRunner

import apps.cli as cli
from src.aliyun.quota import AliyunQuotaRecord
from src.volcengine.quota import VolcengineQuotaRecord


def test_sync_quotas_collects_both_platforms_and_saves_snapshots(monkeypatch, tmp_path):
    captured: dict[str, dict[str, object]] = {}

    def fake_aliyun_collect(**kwargs):
        captured["aliyun"] = kwargs
        return {
            "source_url": "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance",
            "source_mode": "visible_page_only",
            "records": [
                AliyunQuotaRecord(
                    model="glm-5.2",
                    kind="llm",
                    status="available",
                    total=1000,
                    used=200,
                    remaining=800,
                    unit="Token",
                )
            ],
            "errors": [],
        }

    def fake_volcengine_collect(**kwargs):
        captured["volcengine"] = kwargs
        return {
            "source_url": "https://console.volcengine.com/ark/region:cn-beijing/usage",
            "source_mode": "visible_page_only",
            "records": [
                VolcengineQuotaRecord(
                    model="doubao-seedream-5-0-lite-260128",
                    kind="image",
                    status="not_visible_on_page",
                )
            ],
            "errors": ["free quota not visible on the Volcengine page"],
        }

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_aliyun_collect)
    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_volcengine_collect)

    result = CliRunner().invoke(
        cli.app,
        [
            "sync-quotas",
            "--aliyun-model",
            "glm-5.2",
            "--volcengine-model",
            "doubao-seedream-5-0-lite-260128",
            "--visible-only",
            "--headless",
            "--login-hold",
            "0",
            "--wait-timeout",
            "120",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert captured["aliyun"]["visible_only"] is True
    assert captured["volcengine"]["visible_only"] is True
    assert captured["aliyun"]["headless"] is True
    assert captured["volcengine"]["headless"] is True
    assert "Aliyun Bailian quota" in result.output
    assert "Volcengine Ark quota" in result.output
    assert "warnings:" in result.output

    aliyun_files = list(tmp_path.glob("aliyun_quota_*.json"))
    volcengine_files = list(tmp_path.glob("volcengine_quota_*.json"))
    assert len(aliyun_files) == 1
    assert len(volcengine_files) == 1
    assert json.loads(aliyun_files[0].read_text(encoding="utf-8"))["provider"] == "aliyun"
    assert json.loads(volcengine_files[0].read_text(encoding="utf-8"))["provider"] == "volcengine"


def test_sync_quotas_defaults_to_all_free_mode(monkeypatch, tmp_path):
    captured: dict[str, dict[str, object]] = {}

    def fake_aliyun_collect(**kwargs):
        captured["aliyun"] = kwargs
        return {"records": [], "errors": []}

    def fake_volcengine_collect(**kwargs):
        captured["volcengine"] = kwargs
        return {"records": [], "errors": []}

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_aliyun_collect)
    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_volcengine_collect)

    result = CliRunner().invoke(
        cli.app,
        ["sync-quotas", "--headless", "--login-hold", "0", "--snapshot-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert captured["aliyun"]["all_free"] is True
    assert captured["volcengine"]["all_free"] is True
    assert captured["aliyun"]["models"] is None
    assert captured["volcengine"]["models"] is None


def test_sync_quotas_target_only_passes_requested_models(monkeypatch, tmp_path):
    captured: dict[str, dict[str, object]] = {}

    def fake_aliyun_collect(**kwargs):
        captured["aliyun"] = kwargs
        return {"records": [], "errors": []}

    def fake_volcengine_collect(**kwargs):
        captured["volcengine"] = kwargs
        return {"records": [], "errors": []}

    monkeypatch.setattr(cli, "run_collect_aliyun_quota_sync", fake_aliyun_collect)
    monkeypatch.setattr(cli, "run_collect_volcengine_quota_sync", fake_volcengine_collect)

    result = CliRunner().invoke(
        cli.app,
        [
            "sync-quotas",
            "--target-only",
            "--aliyun-model",
            "glm-5.2",
            "--volcengine-model",
            "deepseek-v4-pro",
            "--headless",
            "--login-hold",
            "0",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert captured["aliyun"]["all_free"] is False
    assert captured["volcengine"]["all_free"] is False
    assert captured["aliyun"]["models"] == ["glm-5.2"]
    assert captured["volcengine"]["models"] == ["deepseek-v4-pro"]
