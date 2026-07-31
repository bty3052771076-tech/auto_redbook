from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

import apps.cli as cli
from src.storage.models import AssetInfo, Execution, Post
from src.workflow.pipeline import FreeQuotaUnavailableError
from src.workflow.vision_review import VisionReviewResult


def _write_quota(
    root: Path,
    provider: str,
    records: list[dict],
    captured_at: datetime,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{provider}_quota_20260728_120000.json"
    path.write_text(
        json.dumps(
            {
                "provider": provider,
                "captured_at": captured_at.isoformat(),
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return path


def _free_records() -> list[dict]:
    return [
        {
            "model": "glm-5.2",
            "kind": "llm",
            "status": "available",
            "remaining": 500_000,
            "total": 500_000,
            "unit": "token",
        },
        {
            "model": "doubao-seed-1-6-vision",
            "kind": "llm",
            "status": "available",
            "remaining": 500_000,
            "total": 500_000,
            "unit": "token",
        },
        {
            "model": "doubao-seedream-4-5-251128",
            "kind": "image",
            "status": "available",
            "remaining": 129,
            "total": 200,
            "unit": "张",
        },
    ]


def test_prepare_auto_pipeline_reuses_fresh_metrics_and_quota(monkeypatch, tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    metrics = tmp_path / "data" / "analytics" / "published_metrics_latest.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("title,likes\n测试,1\n", encoding="utf-8")
    os.utime(metrics, (now.timestamp(), now.timestamp()))
    quota_dir = tmp_path / "data" / "quota"
    _write_quota(quota_dir, "volcengine", _free_records(), now)
    called = {"metrics": 0, "quotas": 0}
    monkeypatch.setattr(
        cli,
        "_refresh_metrics_for_preflight",
        lambda **_kwargs: called.__setitem__("metrics", called["metrics"] + 1),
    )
    monkeypatch.setattr(
        cli,
        "_refresh_quotas_for_preflight",
        lambda **_kwargs: called.__setitem__("quotas", called["quotas"] + 1),
    )

    report = cli._prepare_auto_pipeline(
        headless=True,
        login_hold=0,
        wait_timeout=30,
        metrics_max_age_hours=24,
        quota_max_age_hours=2,
        require_image=True,
        metrics_path=metrics,
        quota_dir=quota_dir,
        provider_keys={"aliyun": False, "volcengine": True},
        now=now,
    )

    assert called == {"metrics": 0, "quotas": 0}
    assert report.metrics_mode == "fresh"
    assert report.quota_mode == "fresh"
    assert report.model_plan.llm.model == "glm-5.2"
    assert report.model_plan.image.model == "doubao-seedream-4-5-251128"


def test_prepare_auto_pipeline_refreshes_stale_snapshots(monkeypatch, tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    metrics = tmp_path / "data" / "analytics" / "published_metrics_latest.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("title,likes\n旧数据,1\n", encoding="utf-8")
    old = now - timedelta(days=2)
    os.utime(metrics, (old.timestamp(), old.timestamp()))
    quota_dir = tmp_path / "data" / "quota"
    _write_quota(quota_dir, "volcengine", _free_records(), old)
    called = {"metrics": 0, "quotas": 0}

    def refresh_metrics(**_kwargs):
        called["metrics"] += 1
        os.utime(metrics, (now.timestamp(), now.timestamp()))
        return metrics

    def refresh_quotas(**_kwargs):
        called["quotas"] += 1
        _write_quota(quota_dir, "volcengine", _free_records(), now)
        return []

    monkeypatch.setattr(cli, "_refresh_metrics_for_preflight", refresh_metrics)
    monkeypatch.setattr(cli, "_refresh_quotas_for_preflight", refresh_quotas)

    report = cli._prepare_auto_pipeline(
        headless=True,
        login_hold=0,
        wait_timeout=30,
        metrics_max_age_hours=24,
        quota_max_age_hours=2,
        require_image=True,
        metrics_path=metrics,
        quota_dir=quota_dir,
        provider_keys={"aliyun": False, "volcengine": True},
        now=now,
    )

    assert called == {"metrics": 1, "quotas": 1}
    assert report.metrics_mode == "refreshed"
    assert report.quota_mode == "refreshed"


def test_prepare_auto_pipeline_uses_stale_metrics_with_warning(monkeypatch, tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    metrics = tmp_path / "data" / "analytics" / "published_metrics_latest.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("title,likes\n可回退数据,1\n", encoding="utf-8")
    old = now - timedelta(days=2)
    os.utime(metrics, (old.timestamp(), old.timestamp()))
    quota_dir = tmp_path / "data" / "quota"
    _write_quota(quota_dir, "volcengine", _free_records(), now)
    monkeypatch.setattr(
        cli,
        "_refresh_metrics_for_preflight",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("creator center timeout")),
    )

    report = cli._prepare_auto_pipeline(
        headless=True,
        login_hold=0,
        wait_timeout=30,
        metrics_max_age_hours=24,
        quota_max_age_hours=2,
        require_image=True,
        metrics_path=metrics,
        quota_dir=quota_dir,
        provider_keys={"aliyun": False, "volcengine": True},
        now=now,
    )

    assert report.metrics_mode == "stale_fallback"
    assert any("creator center timeout" in warning for warning in report.warnings)


def test_prepare_auto_pipeline_blocks_when_quota_refresh_has_no_free_models(
    monkeypatch,
    tmp_path,
):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    metrics = tmp_path / "data" / "analytics" / "published_metrics_latest.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("title,likes\n测试,1\n", encoding="utf-8")
    os.utime(metrics, (now.timestamp(), now.timestamp()))
    quota_dir = tmp_path / "data" / "quota"
    monkeypatch.setattr(cli, "_refresh_quotas_for_preflight", lambda **_kwargs: [])

    try:
        cli._prepare_auto_pipeline(
            headless=True,
            login_hold=0,
            wait_timeout=30,
            metrics_max_age_hours=24,
            quota_max_age_hours=2,
            require_image=True,
            metrics_path=metrics,
            quota_dir=quota_dir,
            provider_keys={"aliyun": True, "volcengine": True},
            now=now,
        )
    except FreeQuotaUnavailableError as exc:
        assert "没有可信的免费 LLM 额度" in str(exc)
    else:
        raise AssertionError("missing free quota must block before generation")


def test_auto_applies_selected_models_only_for_current_invocation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc)
    metrics = tmp_path / "data" / "analytics" / "published_metrics_latest.csv"
    metrics.parent.mkdir(parents=True)
    metrics.write_text("title,likes\n测试,1\n", encoding="utf-8")
    quota_dir = tmp_path / "data" / "quota"
    _write_quota(quota_dir, "volcengine", _free_records(), now)
    asset = tmp_path / "asset.png"
    image = Image.new("RGB", (320, 420), (20, 80, 160))
    for x in range(60, 260):
        for y in range(160, 260):
            image.putpixel((x, y), (230, 80, 50))
    image.save(asset)
    post = Post(
        title="财经政策出现重要变化",
        body="内容：这是经过来源核验的测试新闻正文。\n\n评价：关注实际执行。\n\n日期：2026-07-28\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    seen: dict[str, str | None] = {}

    def fake_create_daily_news_posts(**_kwargs):
        seen["provider"] = os.getenv("LLM_PROVIDER")
        seen["llm"] = os.getenv("VOLCENGINE_LLM_MODEL")
        seen["image"] = os.getenv("VOLCENGINE_IMAGE_MODEL")
        return [post]

    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.delenv("VOLCENGINE_LLM_MODEL", raising=False)
    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(
        cli,
        "review_post_image",
        lambda *_args, **_kwargs: VisionReviewResult(
            ok=True,
            score=92,
            issues=(),
            retry_prompt="",
            provider="volcengine",
            model="doubao-seed-1-6-vision",
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: Execution(post_id=post_arg.id, result="saved_draft"),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == {
        "provider": "volcengine",
        "llm": "glm-5.2",
        "image": "doubao-seedream-4-5-251128",
    }
    assert os.environ["LLM_PROVIDER"] == "auto"
    assert "VOLCENGINE_LLM_MODEL" not in os.environ
