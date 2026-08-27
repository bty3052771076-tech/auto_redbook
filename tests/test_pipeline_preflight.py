from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.workflow.pipeline import (
    FreeQuotaUnavailableError,
    build_free_model_plan,
    load_latest_quota_snapshot,
    load_quota_records,
    temporary_environment,
)


def _write_snapshot(
    root: Path,
    provider: str,
    records: list[dict],
    *,
    captured_at: datetime | None = None,
) -> Path:
    path = root / f"{provider}_quota_20260728_120000.json"
    payload: dict[str, object] = {"provider": provider, "records": records}
    if captured_at is not None:
        payload["captured_at"] = captured_at.isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_snapshot_freshness_uses_file_timestamp_when_payload_has_no_time(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    path = _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 100,
                "total": 100,
            }
        ],
    )
    timestamp = (now - timedelta(minutes=30)).timestamp()
    os.utime(path, (timestamp, timestamp))

    snapshot = load_latest_quota_snapshot(
        "aliyun",
        quota_dir=tmp_path,
        now=now,
        max_age=timedelta(hours=2),
    )

    assert snapshot is not None
    assert snapshot.fresh is True
    assert snapshot.captured_at == datetime.fromtimestamp(timestamp, tz=timezone.utc)
    assert snapshot.age == timedelta(minutes=30)


def test_latest_snapshot_skips_newer_empty_sync_result(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    valid = _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 100,
                "total": 100,
            }
        ],
        captured_at=now - timedelta(hours=1),
    )
    valid = valid.rename(tmp_path / "aliyun_quota_20260728_110000.json")
    valid_timestamp = (now - timedelta(hours=1)).timestamp()
    os.utime(valid, (valid_timestamp, valid_timestamp))
    empty = tmp_path / "aliyun_quota_20260728_120000.json"
    empty.write_text(
        json.dumps(
            {
                "provider": "aliyun",
                "captured_at": now.isoformat(),
                "records": [],
                "errors": ["login required"],
            }
        ),
        encoding="utf-8",
    )
    os.utime(empty, (now.timestamp(), now.timestamp()))

    snapshot = load_latest_quota_snapshot(
        "aliyun",
        quota_dir=tmp_path,
        now=now,
        max_age=timedelta(hours=2),
    )

    assert snapshot is not None
    assert snapshot.path.name == "aliyun_quota_20260728_110000.json"


def test_load_quota_records_rejects_unavailable_expired_and_wrong_kind(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "volcengine",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "deepseek-v4-pro",
                "kind": "llm",
                "status": "quota_not_returned",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "old-model",
                "kind": "llm",
                "status": "available",
                "remaining": 50,
                "total": 100,
                "expires_at": "2026-07-27T00:00:00+00:00",
            },
            {
                "model": "doubao-embedding",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seedream-4-5-251128",
                "kind": "image",
                "status": "available",
                "remaining": 129,
                "total": 200,
            },
        ],
        captured_at=now - timedelta(minutes=5),
    )

    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("volcengine",),
        now=now,
        max_age=timedelta(hours=2),
        provider_keys={"volcengine": True},
    )

    assert {record.model for record in records} == {
        "glm-5.2",
        "doubao-seedream-4-5-251128",
    }
    assert any("deepseek-v4-pro" in reason and "status" in reason for reason in rejected)
    assert any("old-model" in reason and "expired" in reason for reason in rejected)
    assert any("doubao-embedding" in reason and "unsupported" in reason for reason in rejected)


def test_model_plan_prefers_explicit_free_model_then_high_remaining_image(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "qwen3.7-max",
                "kind": "llm",
                "status": "available",
                "remaining": 1_000_000,
                "total": 1_000_000,
            },
            {
                "model": "qwen-image-2.0-pro-2026-06-22",
                "kind": "image",
                "status": "available",
                "remaining": 6,
                "total": 100,
            },
        ],
        captured_at=now,
    )
    _write_snapshot(
        tmp_path,
        "volcengine",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seed-1-6-vision",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-1-5-vision-lite",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seedream-4-5-251128",
                "kind": "image",
                "status": "available",
                "remaining": 129,
                "total": 200,
            },
            {
                "model": "doubao-seedream-3-0-t2i",
                "kind": "image",
                "status": "available",
                "remaining": 200,
                "total": 200,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        now=now,
        max_age=timedelta(hours=2),
        provider_keys={"aliyun": True, "volcengine": True},
    )

    plan = build_free_model_plan(
        records,
        explicit_llm_model="qwen3.7-max",
        rejected=rejected,
    )

    assert plan.llm.provider == "aliyun"
    assert plan.llm.model == "qwen3.7-max"
    assert plan.image.provider == "volcengine"
    assert plan.image.model == "doubao-seedream-3-0-t2i"
    assert plan.vision is None


def test_automatic_model_plan_prefers_callable_volcengine_glm_display_name(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "volcengine",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "deepseek-v4-flash",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seedream-4-5-251128",
                "kind": "image",
                "status": "available",
                "remaining": 129,
                "total": 200,
            },
            {
                "model": "doubao-seed-1-6-251015",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("volcengine",),
        now=now,
        provider_keys={"volcengine": True},
    )

    plan = build_free_model_plan(records, rejected=rejected, require_image=False)

    assert plan.llm.model == "glm-5.2"
    assert plan.vision is not None
    assert plan.vision.model == "doubao-seed-1-6-251015"


def test_automatic_model_plan_combines_capability_and_free_quota(tmp_path):
    now = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "qwen3.8-max",
                "kind": "llm",
                "status": "available",
                "remaining": 1_000_000,
                "total": 1_000_000,
            },
            {
                "model": "qwen3.8-27b",
                "kind": "llm",
                "status": "available",
                "remaining": 1_000_000,
                "total": 1_000_000,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("aliyun",),
        now=now,
        provider_keys={"aliyun": True},
    )

    plan = build_free_model_plan(records, rejected=rejected, require_image=False)

    assert plan.llm.model == "qwen3.8-max"
    assert plan.llm.capability_score > 0
    assert plan.llm.quota_score == 100
    assert plan.llm.selection_score > 0
    assert "能力" in plan.llm.selection_reason
    assert "额度" in plan.llm.selection_reason


def test_automatic_model_plan_can_trade_capability_for_sufficient_quota_headroom(tmp_path):
    now = datetime(2026, 8, 24, 4, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "qwen3.8-max",
                "kind": "llm",
                "status": "available",
                "remaining": 100_000,
                "total": 1_000_000,
            },
            {
                "model": "deepseek-v4-pro-0813",
                "kind": "llm",
                "status": "available",
                "remaining": 711_426,
                "total": 1_000_000,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("aliyun",),
        now=now,
        provider_keys={"aliyun": True},
    )

    plan = build_free_model_plan(records, rejected=rejected, require_image=False)

    assert plan.llm.model == "deepseek-v4-pro-0813"
    assert plan.llm.selection_score > 0


def test_automatic_model_plan_prefers_verified_callable_vision_model_over_display_alias(tmp_path):
    now = datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "volcengine",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "available",
                "remaining": 20_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seed-1-6-251015",
                "kind": "llm",
                "status": "available",
                "remaining": 47_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seed-1-6-vision",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seedream-4-0-250828",
                "kind": "image",
                "status": "available",
                "remaining": 51,
                "total": 200,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("volcengine",),
        now=now,
        provider_keys={"volcengine": True},
    )

    plan = build_free_model_plan(records, rejected=rejected)

    assert plan.vision is not None
    assert plan.vision.model == "doubao-seed-1-6-251015"


def test_automatic_model_plan_skips_unverified_vision_display_alias(tmp_path):
    now = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "volcengine",
        [
            {
                "model": "deepseek-v4-flash",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seed-1-6-vision",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-1-5-vision-lite",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "qwen3.5-ocr",
                "kind": "llm",
                "status": "available",
                "remaining": 500_000,
                "total": 500_000,
            },
            {
                "model": "doubao-seedream-4-0-250828",
                "kind": "image",
                "status": "available",
                "remaining": 100,
                "total": 200,
            },
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        providers=("volcengine",),
        now=now,
        provider_keys={"volcengine": True},
    )

    plan = build_free_model_plan(records, rejected=rejected)

    # OCR-only models cannot perform image-content consistency review, so they
    # are excluded from vision-review selection even when free quota exists.
    assert plan.vision is None


def test_model_plan_never_adds_ppinfra_without_paid_opt_in(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        now=now,
        provider_keys={"aliyun": False, "volcengine": False, "ppinfra": True},
    )

    with pytest.raises(FreeQuotaUnavailableError) as exc:
        build_free_model_plan(records, rejected=rejected, allow_paid_fallback=False)

    assert "PPInfra" in str(exc.value)
    assert "显式" in str(exc.value)


def test_quota_unknown_blocks_automatic_model_selection(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    _write_snapshot(
        tmp_path,
        "aliyun",
        [
            {
                "model": "glm-5.2",
                "kind": "llm",
                "status": "quota_not_returned",
                "remaining": None,
                "total": None,
            }
        ],
        captured_at=now,
    )
    records, rejected = load_quota_records(
        quota_dir=tmp_path,
        now=now,
        provider_keys={"aliyun": True},
    )

    with pytest.raises(FreeQuotaUnavailableError) as exc:
        build_free_model_plan(records, rejected=rejected)

    assert "没有可信的免费 LLM 额度" in str(exc.value)


def test_temporary_environment_restores_previous_values(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.delenv("VOLCENGINE_LLM_MODEL", raising=False)

    with temporary_environment(
        {
            "LLM_PROVIDER": "volcengine",
            "VOLCENGINE_LLM_MODEL": "glm-5.2",
        }
    ):
        assert os.environ["LLM_PROVIDER"] == "volcengine"
        assert os.environ["VOLCENGINE_LLM_MODEL"] == "glm-5.2"

    assert os.environ["LLM_PROVIDER"] == "auto"
    assert "VOLCENGINE_LLM_MODEL" not in os.environ
