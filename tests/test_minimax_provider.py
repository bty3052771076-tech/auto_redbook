from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config import (
    DEFAULT_MINIMAX_LLM_BASE_URL,
    DEFAULT_MINIMAX_LLM_MODEL,
    load_llm_configs,
)
from src.images.minimax_images import MiniMaxImageConfig, generate_minimax_image
from src.minimax import quota as minimax_quota
from src.workflow.pipeline import (
    QuotaModelRecord,
    build_free_model_plan,
    load_quota_records,
)


def _clear_minimax_env(monkeypatch):
    for name in (
        "MINIMAX_TOKEN_PLAN_API_KEY",
        "MINIMAX_BASE_URL",
        "MINIMAX_LLM_BASE_URL",
        "MINIMAX_LLM_MODEL",
        "MINIMAX_LLM_MODELS",
        "MINIMAX_IMAGE_BASE_URL",
        "MINIMAX_IMAGE_MODEL",
        "MINIMAX_IMAGE_MODELS",
        "MINIMAX_BILLING_MODE",
        "MINIMAX_ALLOW_PAID_CREDITS",
        "MINIMAX_ALLOW_PAYGO",
        "MINIMAX_USE_SUBSCRIPTION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_minimax_llm_is_explicit_subscription_provider(monkeypatch):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "dummy-minimax-key")

    configs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [(cfg.provider, cfg.model) for cfg in configs] == [
        ("minimax", DEFAULT_MINIMAX_LLM_MODEL)
    ]
    assert configs[0].base_url == DEFAULT_MINIMAX_LLM_BASE_URL
    assert configs[0].cost_class == "subscription_included"
    assert configs[0].account_scope == "token_plan"


def test_minimax_auto_mode_does_not_opt_in_from_key_alone(monkeypatch):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "dummy-minimax-key")
    monkeypatch.setenv("MINIMAX_LLM_MODEL", "MiniMax-M3")

    configs = load_llm_configs(llm_file=Path("does_not_exist"))
    assert all(config.provider != "minimax" for config in configs)


def test_minimax_auto_mode_ignores_empty_opt_in_slot(monkeypatch):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("MINIMAX_USE_SUBSCRIPTION", "1")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODEL", "aliyun-free")

    configs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [(config.provider, config.model) for config in configs] == [("aliyun", "aliyun-free")]


def test_minimax_quota_parser_keeps_shared_usage_numbers_and_status():
    parsed = minimax_quota.parse_minimax_shared_quota(
        {
            "data": {
                "remaining": "8,000",
                "used": 2_000,
                "total": 10_000,
                "unit": "tokens",
                "expires_at": "2026-09-30T00:00:00Z",
            }
        }
    )

    assert parsed["remaining"] == 8_000
    assert parsed["used"] == 2_000
    assert parsed["total"] == 10_000
    assert parsed["status"] == "available"
    assert parsed["unit"] == "tokens"


def test_minimax_quota_parser_understands_actual_model_remains_windows():
    parsed = minimax_quota.parse_minimax_shared_quota(
        {
            "model_remains": [
                {
                    "model_name": "general",
                    "current_interval_total_count": 0,
                    "current_interval_usage_count": 0,
                    "current_interval_remaining_percent": 100,
                    "current_weekly_total_count": 0,
                    "current_weekly_usage_count": 0,
                    "current_weekly_remaining_percent": 99,
                    "end_time": 1788573600000,
                    "weekly_end_time": 1788710400000,
                },
                {
                    "model_name": "video",
                    "current_interval_total_count": 3,
                    "current_interval_usage_count": 1,
                    "current_interval_remaining_percent": 66,
                    "current_weekly_total_count": 21,
                    "current_weekly_usage_count": 5,
                    "current_weekly_remaining_percent": 76,
                },
            ]
        }
    )

    assert parsed["status"] == "available"
    assert parsed["remaining"] == 99
    assert parsed["total"] == 100
    assert parsed["used"] == 1
    assert parsed["unit"] == "percent"
    assert parsed["pools"]["video"]["remaining"] == 2
    assert parsed["pools"]["video"]["total"] == 3


def test_minimax_quota_sync_uses_catalog_and_shared_pool_without_inference(monkeypatch):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "dummy-minimax-key")
    responses = {
        minimax_quota.MINIMAX_MODELS_URL: {
            "data": [
                {"id": "MiniMax-M3"},
                {"id": "image-01"},
                {"id": "MiniMax-M3"},
            ]
        },
        minimax_quota.MINIMAX_TOKEN_PLAN_REMAINS_URL: {
            "model_remains": [
                {
                    "model_name": "general",
                    "current_interval_remaining_percent": 100,
                    "current_weekly_remaining_percent": 99,
                }
            ]
        },
    }
    calls: list[str] = []

    def fake_get_json(*, url: str, api_key: str, timeout_s: float):
        calls.append(url)
        assert api_key == "dummy-minimax-key"
        return responses[url]

    monkeypatch.setattr(minimax_quota, "_api_get_json", fake_get_json)

    result = minimax_quota.run_collect_minimax_quota_sync()

    assert calls == [
        minimax_quota.MINIMAX_MODELS_URL,
        minimax_quota.MINIMAX_TOKEN_PLAN_REMAINS_URL,
    ]
    assert result["errors"] == []
    records = result["records"]
    assert any(item["model"] == "MiniMax-M3" and item["kind"] == "llm" for item in records)
    assert any(item["model"] == "image-01" and item["kind"] == "image" for item in records)
    assert all(item["cost_class"] == "subscription_included" for item in records)
    assert all(item["quota_pool"] == minimax_quota.MINIMAX_POOL_ID for item in records)


def test_minimax_subscription_snapshot_is_opt_in_for_model_selection(tmp_path: Path):
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    payload = {
        "provider": "minimax",
        "captured_at": now.isoformat(),
        "records": [
            {
                "model": "MiniMax-M3",
                "kind": "llm",
                "status": "available",
                "remaining": 8000,
                "total": 10000,
                "unit": "tokens",
                "cost_class": "subscription_included",
                "quota_pool": "token_plan_shared",
            },
            {
                "model": "image-01",
                "kind": "image",
                "status": "available",
                "remaining": 8000,
                "total": 10000,
                "unit": "tokens",
                "cost_class": "subscription_included",
                "quota_pool": "token_plan_shared",
            },
        ],
    }
    path = tmp_path / "minimax_quota_20260905_120000.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("minimax",),
        provider_keys={"minimax": True},
        now=now,
        max_age=timedelta(hours=2),
    )
    assert {item.model for item in records} == {"MiniMax-M3", "image-01"}
    assert all(item.cost_class == "subscription_included" for item in records)
    assert all(item.quota_pool == "token_plan_shared" for item in records)
    assert rejected == []


def test_minimax_plan_environment_marks_subscription_and_disables_paid_fallback(tmp_path: Path):
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    llm = QuotaModelRecord(
        provider="minimax",
        model="MiniMax-M3",
        kind="llm",
        status="available",
        remaining=8000,
        total=10000,
        unit="tokens",
        expires_at=None,
        snapshot_path=tmp_path / "quota.json",
        captured_at=now,
        cost_class="subscription_included",
        quota_pool="token_plan_shared",
    )
    image = QuotaModelRecord(
        provider="minimax",
        model="image-01",
        kind="image",
        status="available",
        remaining=8000,
        total=10000,
        unit="tokens",
        expires_at=None,
        snapshot_path=tmp_path / "quota.json",
        captured_at=now,
        cost_class="subscription_included",
        quota_pool="token_plan_shared",
    )

    with pytest.raises(RuntimeError, match="免费 LLM 额度"):
        build_free_model_plan([llm, image], require_image=True)
    plan = build_free_model_plan([llm, image], require_image=True, allow_subscription=True)
    env = plan.environment()

    assert env["LLM_PROVIDER"] == "minimax"
    assert env["MINIMAX_LLM_MODEL"] == "MiniMax-M3"
    assert env["IMAGE_PROVIDER"] == "minimax"
    assert env["MINIMAX_IMAGE_MODEL"] == "image-01"
    assert env["MINIMAX_BILLING_MODE"] == "subscription_only"
    assert env["MINIMAX_ALLOW_PAID_CREDITS"] == "0"
    assert env["MINIMAX_ALLOW_PAYGO"] == "0"


def test_minimax_image_adapter_sends_openai_compatible_request_and_writes_result(tmp_path, monkeypatch):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "dummy-minimax-key")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "src.images.minimax_images.load_minimax_image_config",
        lambda: MiniMaxImageConfig(
            api_key="dummy-minimax-key",
            base_url="https://api.minimax.cn/v1",
        ),
    )

    def fake_request_json(*, cfg, payload, timeout_s):
        captured.update(payload)
        assert cfg.api_key == "dummy-minimax-key"
        assert timeout_s == 12.0
        return {"id": "request-1", "data": {"image_urls": ["https://example.test/image.png"]}}

    def fake_download(*, url, path, timeout_s):
        assert url == "https://example.test/image.png"
        assert timeout_s == 7.0
        path.write_bytes(b"fake-image-content-1234")

    monkeypatch.setattr("src.images.minimax_images._request_json", fake_request_json)
    monkeypatch.setattr("src.images.minimax_images._download", fake_download)

    result = generate_minimax_image(
        post_id="post-1",
        prompt="一张用于财经新闻的简洁信息图",
        dest_dir=tmp_path,
        timeout_s=12,
        download_timeout_s=7,
        model="image-01",
    )

    assert result.path.is_file()
    assert captured["model"] == "image-01"
    assert captured["aspect_ratio"] == "3:4"
    assert captured["response_format"] == "url"
    assert result.meta["provider"] == "minimax"
    assert result.meta["request_id"] == "request-1"


def test_minimax_image_adapter_rejects_overlong_prompt(monkeypatch, tmp_path):
    _clear_minimax_env(monkeypatch)
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "dummy-minimax-key")

    with pytest.raises(ValueError, match="1500"):
        generate_minimax_image(post_id="post-1", prompt="x" * 1501, dest_dir=tmp_path)


def test_daily_news_ai_image_provider_resolves_minimax(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "minimax")
    monkeypatch.delenv("SINGLE_NEWS_AI_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("DAILY_NEWS_AI_IMAGE_PROVIDER", raising=False)

    from src.workflow.create_post import _daily_news_ai_first_provider

    assert _daily_news_ai_first_provider() == "minimax"


def test_gui_builds_a_minimax_quota_command_without_browser_only_flags():
    from apps.gui import build_cli_args

    args = build_cli_args(
        "minimax-quota",
        params={"models": ["MiniMax-M3", "image-01"], "save_raw": True, "headless": True},
    )

    assert "--model" in args
    assert args.count("--model") == 2
    assert "--save-raw" in args
    assert "--headless" not in args
    assert "--wait-timeout" not in args
