from __future__ import annotations

import glob
import json
import os
import re
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Optional

import typer

from src.aliyun.quota import (
    BAILIAN_FREE_QUOTA_URL,
    format_aliyun_quota_records,
    run_collect_aliyun_quota_sync,
)
from src.volcengine.quota import (
    VOLCENGINE_ARK_FREE_QUOTA_DOC_URL,
    VOLCENGINE_ARK_MODEL_LIST_DOC_URL,
    VOLCENGINE_ARK_USAGE_URL,
    format_volcengine_quota_records,
    run_collect_volcengine_quota_sync,
)
from src.siliconflow.quota import (
    SILICONFLOW_API_DOC_URL,
    SILICONFLOW_CONSOLE_MODELS_URL,
    SILICONFLOW_MODELS_URL,
    format_siliconflow_quota_records,
    run_collect_siliconflow_quota_sync,
)
from src.analytics.post_sync import sync_published_metrics_to_posts
from src.analytics.published_metrics import analyze_published_metrics, render_published_metrics_analysis
from src.ai_digest.collect import collect_ai_digest_updates
from src.news.daily_news import fetch_daily_news_candidates, _required_china_count_for_daily_news
from src.publish.playwright_steps import (
    run_collect_published_metrics_sync,
    run_delete_drafts_sync,
    run_publish_drafts_sync,
    run_save_draft_sync,
    run_update_draft_sync,
)
from src.publish.targets import normalize_publish_platform, publish_targets
from src.publish.toutiao_steps import adapt_post_for_toutiao, run_save_toutiao_draft_sync
from src.storage.files import (
    append_run_record,
    list_executions,
    list_posts,
    load_post,
    save_post,
    save_published_metrics_snapshot,
)
from src.storage.models import Execution, Post, PostStatus, PostType, PublishedMetric, RunRecord, now_iso
from src.validation import validate_post
from src.text_integrity import repair_utf8_as_gbk_mojibake
from src.workflow.create_post import (
    DEFAULT_EVALUATION_VIEWPOINT,
    PartialDailyNewsError,
    create_daily_ai_digest_posts,
    create_daily_news_posts,
    create_post_with_draft,
    regenerate_daily_news_post_image,
)
from src.workflow.pipeline import (
    FreeModelPlan,
    FreeQuotaUnavailableError,
    build_free_model_plan,
    load_latest_quota_snapshot,
    load_quota_records,
)
from src.workflow.quality_gate import validate_post_batch
from src.workflow.vision_review import (
    VisionReviewResult,
    configured_vision_review_model,
    load_vision_review_config,
    review_post_image,
)

app = typer.Typer(
    help="小红书自动发帖（生成并保存草稿）CLI",
    context_settings={"terminal_width": 140, "max_content_width": 140},
)
DAILY_AI_DIGEST_TITLE = "每日AI讯息"


def _jsonable_quota_result(provider: str, result: dict) -> dict:
    payload = dict(result or {})
    payload["provider"] = provider
    records = []
    for record in payload.get("records") or []:
        if hasattr(record, "to_dict"):
            records.append(record.to_dict())
        elif isinstance(record, dict):
            records.append(record)
        else:
            records.append(dict(record))
    payload["records"] = records
    return payload


def _save_quota_snapshot(provider: str, result: dict, snapshot_dir: Optional[Path] = None) -> Path:
    root = snapshot_dir or Path("data") / "quota"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    path = root / f"{provider}_quota_{stamp}.json"
    path.write_text(
        json.dumps(_jsonable_quota_result(provider, result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class AutoPreflightReport:
    metrics_mode: str
    quota_mode: str
    model_plan: FreeModelPlan | None
    warnings: tuple[str, ...] = ()


def _path_is_fresh(
    path: Path,
    *,
    max_age: timedelta,
    now: datetime | None = None,
) -> bool:
    if not path.is_file():
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return timedelta(0) <= current.astimezone(timezone.utc) - modified <= max_age


def _key_file_has_api_key(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            if key.strip().lower() in {"api_key", "apikey", "key"} and value.strip().strip("\"'"):
                return True
    except (OSError, UnicodeError):
        return False
    return False


def _configured_free_provider_keys() -> dict[str, bool]:
    aliyun = bool(
        (os.getenv("ALIYUN_LLM_API_KEY") or "").strip()
        or (os.getenv("ALIYUN_IMAGE_API_KEY") or "").strip()
        or (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        or _key_file_has_api_key(Path("docs") / "aliyun_image_api-key.md")
    )
    volcengine = bool(
        (os.getenv("VOLCENGINE_LLM_API_KEY") or "").strip()
        or (os.getenv("VOLCENGINE_API_KEY") or "").strip()
        or (os.getenv("ARK_API_KEY") or "").strip()
        or _key_file_has_api_key(Path("docs") / "volcengine_api-key.md")
    )
    siliconflow = bool(
        (os.getenv("SILICONFLOW_LLM_API_KEY") or "").strip()
        or (os.getenv("SILICONFLOW_API_KEY") or "").strip()
        or (os.getenv("SF_API_KEY") or "").strip()
        or _key_file_has_api_key(Path("docs") / "siliconflow_api-key.md")
    )
    return {"aliyun": aliyun, "volcengine": volcengine, "siliconflow": siliconflow}


def _refresh_metrics_for_preflight(
    *,
    headless: bool,
    login_hold: int,
    wait_timeout: int,
) -> Path:
    def _progress(message: str) -> None:
        typer.echo(message)

    result = run_collect_published_metrics_sync(
        limit=0,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=_headless_option_value(headless),
        progress_callback=_progress,
    )
    metrics = [PublishedMetric.model_validate(item) for item in result.get("items", [])]
    target_total = int(result.get("target_total") or 0)
    required_total = int(result.get("required_total") or (target_total if target_total else len(metrics)))
    missing_count = int(result.get("missing_count") or max(0, required_total - len(metrics)))
    complete = bool(result.get("complete", True))
    if not metrics:
        raise RuntimeError(
            "创作者中心没有返回任何已发布数据；保留原有快照，不覆盖本地分析。"
        )
    if not complete:
        raise RuntimeError(
            "创作者中心全量同步未完成："
            f"已获取 {len(metrics)} 条，目标 {target_total or required_total} 条，"
            f"仍缺 {missing_count} 条；保留原有快照。"
        )
    saved = save_published_metrics_snapshot(metrics)
    sync_published_metrics_to_posts(metrics)
    return Path(saved["latest_csv"])


def _refresh_quotas_for_preflight(
    *,
    headless: bool,
    login_hold: int,
    wait_timeout: int,
    quota_dir: Path,
    providers: tuple[str, ...] = ("aliyun", "volcengine"),
) -> list[str]:
    warnings: list[str] = []

    def _progress(message: str) -> None:
        typer.echo(message)

    collectors = (
        (
            "aliyun",
            lambda: run_collect_aliyun_quota_sync(
                models=None,
                all_free=True,
                login_hold=login_hold,
                wait_timeout_ms=wait_timeout * 1000,
                headless=True if headless else None,
                visible_only=False,
                progress_callback=_progress,
            ),
        ),
        (
            "volcengine",
            lambda: run_collect_volcengine_quota_sync(
                models=None,
                all_free=True,
                login_hold=login_hold,
                wait_timeout_ms=wait_timeout * 1000,
                headless=True if headless else None,
                visible_only=False,
                progress_callback=_progress,
            ),
        ),
        (
            "siliconflow",
            lambda: run_collect_siliconflow_quota_sync(
                models=None,
                all_free=True,
                login_hold=login_hold,
                wait_timeout_ms=wait_timeout * 1000,
                headless=True if headless else None,
                visible_only=False,
                progress_callback=_progress,
            ),
        ),
    )
    enabled = {str(provider or "").strip().lower() for provider in providers}
    for provider, collect in collectors:
        if provider not in enabled:
            continue
        try:
            result = collect()
            errors = [str(item) for item in (result.get("errors") or []) if str(item).strip()]
            if errors:
                warnings.append(f"{provider} 额度同步提示：{'；'.join(errors)}")
            records = result.get("records") or []
            if not records and errors:
                # A failed refresh (e.g. headless login required) must not
                # overwrite a valid older snapshot with an empty one; the
                # preflight stale-fallback will keep using the older data.
                warnings.append(
                    f"{provider} 额度刷新未返回记录，保留上一次有效快照；"
                    "登录控制台后重新同步即可更新。"
                )
            else:
                _save_quota_snapshot(provider, result, snapshot_dir=quota_dir)
        except Exception as exc:
            warnings.append(f"{provider} 额度同步失败：{exc}")
    return warnings


def _selected_model_from_environment(kind: str, provider: str) -> str:
    provider_name = (provider or "").strip().lower()
    if kind == "llm":
        if provider_name == "aliyun":
            return (os.getenv("ALIYUN_LLM_MODEL") or "").strip()
        if provider_name == "volcengine":
            return (
                os.getenv("VOLCENGINE_LLM_MODEL")
                or os.getenv("ARK_LLM_MODEL")
                or ""
            ).strip()
        if provider_name == "siliconflow":
            return (
                os.getenv("SILICONFLOW_LLM_MODEL")
                or os.getenv("SF_LLM_MODEL")
                or ""
            ).strip()
        candidates = [
            (os.getenv("ALIYUN_LLM_MODEL") or "").strip(),
            (os.getenv("VOLCENGINE_LLM_MODEL") or os.getenv("ARK_LLM_MODEL") or "").strip(),
            (os.getenv("SILICONFLOW_LLM_MODEL") or os.getenv("SF_LLM_MODEL") or "").strip(),
        ]
    else:
        if provider_name == "aliyun":
            return (os.getenv("ALIYUN_IMAGE_MODEL") or "").strip()
        if provider_name == "volcengine":
            return (
                os.getenv("VOLCENGINE_IMAGE_MODEL")
                or os.getenv("ARK_IMAGE_MODEL")
                or ""
            ).strip()
        if provider_name == "siliconflow":
            return (
                os.getenv("SILICONFLOW_IMAGE_MODEL")
                or os.getenv("SF_IMAGE_MODEL")
                or ""
            ).strip()
        candidates = [
            (os.getenv("ALIYUN_IMAGE_MODEL") or "").strip(),
            (os.getenv("VOLCENGINE_IMAGE_MODEL") or os.getenv("ARK_IMAGE_MODEL") or "").strip(),
            (os.getenv("SILICONFLOW_IMAGE_MODEL") or os.getenv("SF_IMAGE_MODEL") or "").strip(),
        ]
    selected = [model for model in candidates if model]
    return selected[0] if len(selected) == 1 else ""


def _explicit_quota_providers() -> set[str]:
    aliases = {
        "aliyun": "aliyun",
        "dashscope": "aliyun",
        "bailian": "aliyun",
        "volcengine": "volcengine",
        "ark": "volcengine",
        "doubao": "volcengine",
        "seedream": "volcengine",
        "siliconflow": "siliconflow",
        "silicon": "siliconflow",
        "sf": "siliconflow",
    }
    values = (
        os.getenv("LLM_PROVIDER"),
        os.getenv("IMAGE_PROVIDER"),
        os.getenv("VLM_REVIEW_PROVIDER"),
    )
    return {aliases[value.strip().lower()] for value in values if value and value.strip().lower() in aliases}


def _prepare_auto_pipeline(
    *,
    headless: bool,
    login_hold: int,
    wait_timeout: int,
    metrics_max_age_hours: float,
    quota_max_age_hours: float,
    require_image: bool,
    metrics_path: Path = Path("data") / "analytics" / "published_metrics_latest.csv",
    quota_dir: Path = Path("data") / "quota",
    provider_keys: Mapping[str, bool] | None = None,
    now: datetime | None = None,
) -> AutoPreflightReport:
    current = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    metrics_max_age = timedelta(hours=max(0.1, float(metrics_max_age_hours)))
    quota_max_age = timedelta(hours=max(0.1, float(quota_max_age_hours)))

    _emit_progress_event("auto", "检查已发布数据", "in_progress")
    if _path_is_fresh(metrics_path, max_age=metrics_max_age, now=current):
        metrics_mode = "fresh"
        _emit_progress_event("auto", "检查已发布数据", "success", "使用新鲜本地快照")
    else:
        try:
            _emit_progress_event("auto", "同步已发布数据", "in_progress", "全量同步")
            _refresh_metrics_for_preflight(
                headless=headless,
                login_hold=login_hold,
                wait_timeout=wait_timeout,
            )
            metrics_mode = "refreshed"
            _emit_progress_event("auto", "同步已发布数据", "success", "全量快照已更新")
        except Exception as exc:
            warning = f"已发布数据同步失败：{exc}"
            warnings.append(warning)
            if metrics_path.is_file():
                metrics_mode = "stale_fallback"
                _emit_progress_event(
                    "auto",
                    "同步已发布数据",
                    "warning",
                    "使用现有旧快照继续；本次选题偏好可能不是最新",
                )
            else:
                metrics_mode = "unavailable"
                _emit_progress_event(
                    "auto",
                    "同步已发布数据",
                    "warning",
                    "没有可用快照；继续生成但不应用历史表现偏好",
                )

    key_states = dict(provider_keys or _configured_free_provider_keys())
    configured_providers = [
        provider for provider in ("aliyun", "volcengine", "siliconflow") if key_states.get(provider, False)
    ]
    explicit_providers = _explicit_quota_providers()
    if explicit_providers:
        configured_providers = [
            provider for provider in configured_providers if provider in explicit_providers
        ]
    _emit_progress_event("auto", "检查免费额度", "in_progress")
    fresh_states = [
        load_latest_quota_snapshot(
            provider,
            quota_dir=quota_dir,
            now=current,
            max_age=quota_max_age,
        )
        for provider in configured_providers
    ]
    quota_refresh_needed = not configured_providers or any(
        snapshot is None or not snapshot.fresh for snapshot in fresh_states
    )
    if quota_refresh_needed:
        quota_refresh_timeout = wait_timeout
        if headless:
            try:
                configured_quota_timeout = int(
                    (os.getenv("AUTO_QUOTA_SYNC_TIMEOUT_S") or "60").strip()
                )
            except ValueError:
                configured_quota_timeout = 60
            quota_refresh_timeout = min(
                wait_timeout,
                max(10, min(configured_quota_timeout, 300)),
            )
        refresh_providers = tuple(configured_providers or ("aliyun", "volcengine", "siliconflow"))
        provider_label = " + ".join(
            "阿里云" if provider == "aliyun" else "火山引擎" if provider == "volcengine" else "硅基流动"
            for provider in refresh_providers
        )
        _emit_progress_event(
            "auto",
            "同步免费额度",
            "in_progress",
            f"{provider_label} timeout={quota_refresh_timeout}s",
        )
        warnings.extend(
            _refresh_quotas_for_preflight(
                headless=headless,
                login_hold=login_hold,
                wait_timeout=quota_refresh_timeout,
                quota_dir=quota_dir,
                providers=refresh_providers,
            )
        )
        quota_mode = "refreshed"
    else:
        quota_mode = "fresh"

    records, rejected = load_quota_records(
        quota_dir=quota_dir,
        now=current,
        max_age=quota_max_age,
        provider_keys=key_states,
    )
    if quota_mode == "refreshed":
        # A failed refresh for one provider (e.g. headless login required)
        # must not hide that provider's last valid snapshot while another
        # provider refreshed successfully. Re-read with a 24h tolerance and
        # keep any provider records that the fresh pass rejected as stale.
        stale_records, stale_rejected = load_quota_records(
            quota_dir=quota_dir,
            now=current,
            max_age=timedelta(hours=max(24.0, quota_max_age_hours * 4)),
            provider_keys=key_states,
        )
        fresh_providers = {record.provider for record in records}
        stale_extra = [
            record for record in stale_records if record.provider not in fresh_providers
        ]
        if stale_extra:
            records = [*records, *stale_extra]
            quota_mode = "stale_fallback"
            warnings.append(
                "部分平台额度刷新未得到新鲜正余额，使用 24 小时容忍期内的最后有效额度快照："
                f"{', '.join(sorted({record.provider for record in stale_extra}))}。"
            )
        rejected.extend(stale_rejected)

    requested_llm_provider = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
    requested_image_provider = (os.getenv("IMAGE_PROVIDER") or "auto").strip().lower()
    plan_records = records
    if requested_llm_provider in {"aliyun", "volcengine", "siliconflow"}:
        plan_records = [
            record
            for record in plan_records
            if record.kind != "llm" or record.provider == requested_llm_provider
        ]
    if requested_image_provider in {"aliyun", "volcengine", "siliconflow"}:
        plan_records = [
            record
            for record in plan_records
            if record.kind != "image" or record.provider == requested_image_provider
        ]
    explicit_llm = _selected_model_from_environment("llm", requested_llm_provider)
    explicit_image = _selected_model_from_environment("image", requested_image_provider)
    model_plan = build_free_model_plan(
        plan_records,
        explicit_llm_model=explicit_llm,
        explicit_image_model=explicit_image,
        require_image=require_image,
        rejected=rejected,
        allow_paid_fallback=(os.getenv("ALLOW_PAID_LLM_FALLBACK") or "").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    _emit_progress_event(
        "auto",
        "选择免费模型",
        "success",
        " ".join(
            [
                f"LLM={model_plan.llm.provider}/{model_plan.llm.model}",
                (
                    f"image={model_plan.image.provider}/{model_plan.image.model}"
                    if model_plan.image is not None
                    else "image=本地渲染"
                ),
                (
                    f"VLM={model_plan.vision.provider}/{model_plan.vision.model}"
                    if model_plan.vision is not None
                    else "VLM=无可用免费视觉模型"
                ),
            ]
        ),
    )
    if warnings:
        for warning in warnings:
            typer.echo(f"warning: {warning}")
    return AutoPreflightReport(
        metrics_mode=metrics_mode,
        quota_mode=quota_mode,
        model_plan=model_plan,
        warnings=tuple(warnings),
    )


def _apply_scoped_environment(context: typer.Context, values: Mapping[str, str]) -> None:
    previous = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        os.environ[key] = value

    def restore() -> None:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    context.call_on_close(restore)


def _vision_review_passes(result: VisionReviewResult) -> bool:
    return bool(result.ok and result.score >= 70)


def _vision_review_is_inconclusive(result: VisionReviewResult) -> bool:
    return bool(
        result.ok
        and result.score == 0
        and not result.issues
        and not (result.retry_prompt or "").strip()
    )


def _review_with_bounded_image_repair(
    post: Post,
    *,
    config,
    viewpoint: str,
    max_repairs: int,
    review_fn: Callable,
    regenerate_fn: Callable,
    fallback_regenerate_fn: Optional[Callable] = None,
    progress_fn: Optional[Callable[[int, int, str], None]] = None,
):
    history = []
    repair_errors: list[str] = []
    repair_count = 0
    result = review_fn(post, config=config, viewpoint=viewpoint)
    history.append(result)
    if _vision_review_is_inconclusive(result):
        result = review_fn(post, config=config, viewpoint=viewpoint)
        history.append(result)
    is_daily_news = isinstance(post.platform.get("news"), dict)
    limit = max(0, int(max_repairs))
    latest_retry_prompt = ""

    while not _vision_review_passes(result) and is_daily_news and repair_count < limit:
        attempt = repair_count + 1
        retry_prompt = (result.retry_prompt or "").strip()
        if retry_prompt:
            latest_retry_prompt = retry_prompt
        if progress_fn is not None:
            progress_fn(attempt, limit, retry_prompt)
        try:
            regenerated = bool(regenerate_fn(post, retry_prompt))
        except Exception as exc:
            repair_errors.append(str(exc))
            break
        if not regenerated:
            repair_errors.append("image regeneration returned no usable asset")
            break
        repair_count += 1
        result = review_fn(post, config=config, viewpoint=viewpoint)
        history.append(result)

    # A successful image API response can still be a semantic failure. Once an
    # AI redraw was reviewed and rejected, use the configured stock-photo
    # provider as the final bounded fallback and review that replacement too.
    if (
        not _vision_review_passes(result)
        and is_daily_news
        and repair_count > 0
        and fallback_regenerate_fn is not None
    ):
        fallback_prompt = (result.retry_prompt or latest_retry_prompt or "").strip()
        if progress_fn is not None:
            progress_fn(repair_count + 1, repair_count + 1, fallback_prompt)
        try:
            regenerated = bool(fallback_regenerate_fn(post, fallback_prompt))
        except Exception as exc:
            repair_errors.append(f"Pexels fallback failed: {exc}")
        else:
            if not regenerated:
                repair_errors.append("Pexels fallback returned no usable asset")
            else:
                result = review_fn(post, config=config, viewpoint=viewpoint)
                history.append(result)
                if _vision_review_is_inconclusive(result):
                    result = review_fn(post, config=config, viewpoint=viewpoint)
                    history.append(result)

    return result, repair_count, repair_errors, history


def _local_ai_digest_vision_result(post: Post) -> dict[str, object] | None:
    platform = post.platform if isinstance(post.platform, dict) else {}
    digest = platform.get("ai_digest")
    if not isinstance(digest, dict) or digest.get("mode") != "daily_ai_digest":
        return None
    items = digest.get("items")
    try:
        actual_items = int(digest.get("actual_items") or 0)
    except (TypeError, ValueError):
        return None
    if actual_items < 1 or not isinstance(items, list) or len(items) != actual_items:
        return None

    image_assets = [asset for asset in post.assets if asset.kind == "image"]
    expected_count = 1 + ((actual_items + 2) // 3)
    if len(image_assets) != expected_count:
        return None
    expected_names = ["ai_digest_00_cover.png", *[f"ai_digest_{index:02d}.png" for index in range(1, expected_count)]]
    actual_names = [Path(asset.path).name for asset in image_assets]
    if actual_names != expected_names:
        return None
    if any(not Path(asset.path).is_file() or Path(asset.path).stat().st_size <= 0 for asset in image_assets):
        return None
    return {
        "ok": True,
        "score": 100,
        "issues": [],
        "retry_prompt": "",
        "provider": "local_renderer",
        "model": "ai_digest_template",
        "basis": "structured digest items rendered to complete local PNG set",
    }


def _run_auto_quality_gate(
    posts: list[Post],
    *,
    expected_count: int,
    evaluation_viewpoint: str,
    require_vision: bool,
    reuse_vision_results: bool = False,
) -> list[str]:
    _emit_progress_event(
        "auto",
        "批次质量检查",
        "in_progress",
        f"posts={len(posts)} expected={expected_count}",
    )
    report = validate_post_batch(
        posts,
        expected_count=expected_count,
        historical_posts=list_posts(),
    )
    errors = [issue.message for issue in report.issues]
    issues_by_post: dict[str, list[dict[str, str]]] = {}
    for issue in report.issues:
        issues_by_post.setdefault(issue.post_id or "_batch", []).append(
            {"code": issue.code, "message": issue.message}
        )
    for post in posts:
        previous_gate = post.platform.get("quality_gate") if isinstance(post.platform, dict) else None
        previous_vision = previous_gate.get("vision") if isinstance(previous_gate, dict) else None
        quality_gate = {
            "deterministic_ok": post.id not in issues_by_post,
            "issues": issues_by_post.get(post.id, []),
        }
        if reuse_vision_results and isinstance(previous_vision, dict):
            quality_gate["vision"] = previous_vision
        post.platform["quality_gate"] = quality_gate
        save_post(post)
    if errors:
        _emit_progress_event(
            "auto",
            "批次质量检查",
            "failed",
            f"errors={len(errors)} first={errors[0]}",
        )
        return errors

    review_enabled = (os.getenv("AUTO_VLM_REVIEW") or "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }
    if not review_enabled:
        _emit_progress_event("auto", "视觉一致性复核", "warning", "用户显式关闭")
        return []
    posts_to_review: list[Post] = []
    reused_count = 0
    local_render_count = 0
    for post in posts:
        gate = post.platform.get("quality_gate") if isinstance(post.platform, dict) else None
        vision = gate.get("vision") if isinstance(gate, dict) else None
        local_render_vision = _local_ai_digest_vision_result(post)
        if local_render_vision is not None:
            post.platform["quality_gate"]["vision"] = local_render_vision
            save_post(post)
            local_render_count += 1
            continue
        if reuse_vision_results and isinstance(vision, dict):
            previous_result = VisionReviewResult(
                ok=bool(vision.get("ok")),
                score=int(vision.get("score") or 0),
                issues=tuple(str(item) for item in (vision.get("issues") or [])),
                retry_prompt=str(vision.get("retry_prompt") or ""),
                provider=str(vision.get("provider") or ""),
                model=str(vision.get("model") or ""),
            )
            if _vision_review_passes(previous_result):
                reused_count += 1
                continue
        posts_to_review.append(post)
    if not posts_to_review:
        _emit_progress_event(
            "auto",
            "批次质量检查",
            "success",
            f"posts={len(posts)} vision_reused={reused_count} local_render={local_render_count}",
        )
        return []
    if not configured_vision_review_model():
        message = "没有具备可信免费额度的视觉模型，无法完成图文一致性复核。"
        if require_vision:
            # Vision review is an enhancement; when no free VLM is available
            # the generated drafts still passed the deterministic quality gate
            # and image generation. Degrade to a warning instead of rejecting
            # the whole batch, otherwise a quota/login hiccup blocks uploads.
            _emit_progress_event("auto", "视觉一致性复核", "warning", message + " 已跳过复核。")
            return []
        _emit_progress_event("auto", "视觉一致性复核", "warning", message)
        return []

    _emit_progress_event(
        "auto",
        "视觉一致性复核",
        "in_progress",
        f"posts={len(posts_to_review)} reused={reused_count}",
    )
    try:
        config = load_vision_review_config()
    except Exception as exc:
        message = f"视觉模型配置不可用：{exc}"
        _emit_progress_event("auto", "视觉一致性复核", "failed", message)
        return [message]
    raw_repair_limit = (os.getenv("AUTO_VLM_REPAIR_ATTEMPTS") or "1").strip()
    try:
        repair_limit = max(0, min(3, int(raw_repair_limit)))
    except ValueError:
        repair_limit = 1
    for index, post in enumerate(posts_to_review, start=1):
        try:
            result, repair_count, repair_errors, review_history = _review_with_bounded_image_repair(
                post,
                config=config,
                viewpoint=evaluation_viewpoint,
                max_repairs=repair_limit,
                review_fn=review_post_image,
                regenerate_fn=regenerate_daily_news_post_image,
                fallback_regenerate_fn=lambda post, prompt: regenerate_daily_news_post_image(
                    post,
                    prompt,
                    provider="pexels",
                ),
                progress_fn=lambda attempt, limit, _prompt, index=index: _emit_progress_event(
                    "auto",
                    "视觉复核修复",
                    "in_progress",
                    f"index={index}/{len(posts_to_review)} attempt={attempt}/{limit}",
                ),
            )
        except Exception as exc:
            message = f"第 {index} 条视觉复核调用失败：{exc}"
            if require_vision:
                errors.append(message)
            post.platform["quality_gate"]["vision"] = {
                "ok": False,
                "error": str(exc),
                "provider": config.provider,
                "model": config.model,
                "inconclusive": True,
            }
            save_post(post)
            _emit_progress_event(
                "auto",
                "视觉一致性复核",
                "failed" if require_vision else "warning",
                f"index={index}/{len(posts_to_review)} error={exc}",
            )
            continue
        post.platform["quality_gate"]["vision"] = {
            "ok": result.ok,
            "score": result.score,
            "issues": list(result.issues),
            "retry_prompt": result.retry_prompt,
            "provider": result.provider,
            "model": result.model,
            "repair_count": repair_count,
            "repair_errors": repair_errors,
            "history": [
                {
                    "ok": item.ok,
                    "score": item.score,
                    "issues": list(item.issues),
                }
                for item in review_history
            ],
        }
        save_post(post)
        if repair_count:
            _emit_progress_event(
                "auto",
                "视觉复核修复",
                "success" if _vision_review_passes(result) else "failed",
                f"index={index}/{len(posts_to_review)} repairs={repair_count} final_score={result.score}",
            )
        if not _vision_review_passes(result):
            message = (
                f"第 {index} 条图片与文字不一致（得分 {result.score}）："
                f"{'；'.join(result.issues) or '视觉模型未给出详细说明'}"
            )
            if repair_errors:
                message += f"；自动修复失败：{repair_errors[-1]}"
            errors.append(message)
            _emit_progress_event(
                "auto",
                "视觉一致性复核",
                "failed",
                f"index={index}/{len(posts_to_review)} score={result.score}",
            )
        else:
            _emit_progress_event(
                "auto",
                "视觉一致性复核",
                "success",
                f"index={index}/{len(posts_to_review)} score={result.score}",
            )
    if errors:
        return errors
    _emit_progress_event("auto", "批次质量检查", "success", f"posts={len(posts)}")
    return []


def _daily_news_visual_spare_count(requested_count: int) -> int:
    """Generate a bounded surplus so a failed image can be replaced before upload."""
    if requested_count <= 1:
        return 0
    return min(3, max(1, (requested_count + 4) // 5))


def _daily_news_post_is_china_mainland(post: Post) -> bool:
    news = post.platform.get("news") if isinstance(post.platform, dict) else None
    picked = news.get("picked") if isinstance(news, dict) else None
    if not isinstance(picked, dict):
        return False
    country = str(picked.get("sourcecountry") or "").strip().lower()
    if country in {"china", "cn", "chn", "ch"}:
        return True
    domain = str(picked.get("domain") or "").strip().lower()
    return (
        domain.endswith(".cn")
        or domain.endswith(".gov.cn")
        or domain.endswith(".edu.cn")
        or domain == "36kr.com"
        or domain.endswith(".36kr.com")
    )


def _select_visual_ready_daily_news_posts(
    posts: list[Post], *, requested_count: int
) -> tuple[list[Post], list[Post], list[Post]]:
    """Return selected, failed-quality, and unused visual-spare posts."""
    ready: list[Post] = []
    failed_quality: list[Post] = []
    for post in posts:
        gate = post.platform.get("quality_gate") if isinstance(post.platform, dict) else None
        vision = gate.get("vision") if isinstance(gate, dict) else None
        deterministic_ok = bool(gate.get("deterministic_ok")) if isinstance(gate, dict) else False
        if deterministic_ok and isinstance(vision, dict):
            result = VisionReviewResult(
                ok=bool(vision.get("ok")),
                score=int(vision.get("score") or 0),
                issues=tuple(str(item) for item in (vision.get("issues") or [])),
                retry_prompt=str(vision.get("retry_prompt") or ""),
                provider=str(vision.get("provider") or ""),
                model=str(vision.get("model") or ""),
            )
            if _vision_review_passes(result):
                ready.append(post)
                continue
        failed_quality.append(post)

    selected = ready[:requested_count]
    required_china = _required_china_count_for_daily_news(requested_count)
    selected_china = sum(_daily_news_post_is_china_mainland(post) for post in selected)
    if selected_china < required_china:
        for candidate in ready[requested_count:]:
            if not _daily_news_post_is_china_mainland(candidate):
                continue
            replacement_index = next(
                (
                    index
                    for index in range(len(selected) - 1, -1, -1)
                    if not _daily_news_post_is_china_mainland(selected[index])
                ),
                None,
            )
            if replacement_index is None:
                break
            selected[replacement_index] = candidate
            selected_china += 1
            if selected_china >= required_china:
                break

    selected_ids = {post.id for post in selected}
    unused_spares = [post for post in ready if post.id not in selected_ids]
    return selected, failed_quality, unused_spares


def _ensure_utf8_output() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


@app.callback()
def _main_callback() -> None:
    _ensure_utf8_output()


def _resolve_asset_paths(post, assets_glob: str) -> list[str]:
    if assets_glob:
        return [p for p in glob.glob(assets_glob) if Path(p).is_file()]

    frozen_assets = [a.path for a in post.assets if Path(a.path).is_file()]
    if frozen_assets:
        return frozen_assets

    # Legacy posts may predate the persisted asset manifest.
    return [
        p
        for p in glob.glob(f"data/posts/{post.id}/assets/*")
        if Path(p).is_file()
    ]


def _is_auto_image_sentinel_glob(pattern: str) -> bool:
    normalized = (pattern or "").strip().replace("\\", "/").lower()
    normalized = normalized.removeprefix("./")
    return normalized in {"assets/empty/*", "assets/empty/**"}


def _initial_asset_paths(assets_glob: str) -> list[str]:
    """Keep the historic empty glob as an explicit auto-image sentinel."""
    if _is_auto_image_sentinel_glob(assets_glob):
        return []
    return [p for p in glob.glob(assets_glob) if Path(p).is_file()]


def _repair_cli_text(value: str, *, field: str) -> str:
    repaired = repair_utf8_as_gbk_mojibake(value)
    if repaired != value:
        typer.echo(f"warn: repaired UTF-8/GBK mojibake in {field}")
    return repaired


def _post_upload_fingerprint(post) -> str:
    title = re.sub(r"[^\w\u4e00-\u9fff]+", "", (post.title or "").lower())
    body = re.sub(r"[^\w\u4e00-\u9fff]+", "", (post.body or "").lower())
    return f"{title}|{body[:280]}"


def _next_attempt(post_id: str) -> int:
    executions = list_executions(post_id)
    return max((e.attempt for e in executions), default=0) + 1


def _apply_execution_status(post_status: PostStatus, result: str) -> PostStatus:
    if result == "saved_draft":
        return PostStatus.saved_draft
    if result == "failed":
        return PostStatus.failed
    if result == "canceled":
        return PostStatus.canceled
    return post_status


def _mark_post_uploaded(post, exec_result: str) -> None:
    if exec_result == "saved_draft":
        post.uploaded = True
        post.uploaded_at = now_iso()


def _emit_validation(result) -> None:
    for err in result.errors:
        typer.echo(f"error: {err}")
    for warn in result.warnings:
        typer.echo(f"warn: {warn}")


def _format_stage_error(stage: str, error) -> str:
    return f"error: stage={stage} | {error}"


def _format_progress_event(command: str, stage: str, status: str = "in_progress", detail: str = "") -> str:
    message = f"[{command}] stage={stage} | {status}"
    detail_text = str(detail or "").strip()
    if detail_text:
        message = f"{message} | {detail_text}"
    return message


def _emit_progress_event(command: str, stage: str, status: str = "in_progress", detail: str = "") -> None:
    typer.echo(_format_progress_event(command, stage, status, detail))
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _stage_from_create_exception(exc: Exception) -> str:
    message = str(exc).lower()
    if "daily ai digest" in message or "ai digest" in message or "ai updates" in message:
        return "获取AI讯息"
    if (
        "no news returned" in message
        or "newsapi" in message
        or "gnews" in message
        or "news_candidates_file" in message
        or "daily news fetch" in message
    ):
        return "获取新闻"
    if (
        "image" in message
        or "aliyun" in message
        or "vlm" in message
        or "auto-image" in message
        or "dashscope image" in message
    ):
        return "VLM生图"
    if (
        "llm" in message
        or "llm api_key missing" in message
        or "dashscope" in message
        or "openai" in message
    ):
        return "LLM"
    return "生成草稿"


def _is_daily_ai_digest_title(title: str) -> bool:
    return (title or "").strip().replace(" ", "") == DAILY_AI_DIGEST_TITLE


def _emit_missing_assets_hint(title: str, *, dry_run: bool = False) -> None:
    if _is_daily_ai_digest_title(title):
        typer.echo("note: 每日AI讯息会自动渲染本地简报图，无需本地素材或 AI 生图。")
        return
    if not dry_run:
        typer.echo("未找到素材文件，将自动查找配图（如已启用 AUTO_IMAGE 且配置了图片 API）。")


def _generation_stage_for_title(title: str) -> str:
    title_norm = (title or "").strip()
    if _is_daily_ai_digest_title(title_norm):
        return "生成每日AI讯息"
    if title_norm == "每日新闻":
        return "生成每日新闻"
    return "生成草稿"


def _upload_progress(post_id: str):
    def _emit(message: str) -> None:
        typer.echo(f"{message} | post_id={post_id}")

    return _emit


def _humanize_daily_news_progress_reason(reason: object) -> str:
    """Keep workflow reason codes useful to people reading the CLI or GUI."""
    value = str(reason or "").strip()
    known = {
        "source_context_insufficient": "原文信息不足，无法可靠生成",
        "duplicate_story_after_enrichment": "与已选新闻重复",
        "china_quota_reserved": "为国内新闻配额预留候选",
        "bad_body_language": "正文未达到简体中文表达要求",
        "llm_request_failed": "文案模型请求失败",
        "image_generation_abandoned": "配图模型多次失败，已停止该候选",
        "batch_incomplete": "未能补足请求数量",
    }
    return known.get(value, value)


def _daily_news_generation_progress(stage: str, status: str, detail: dict[str, object]) -> None:
    """Translate workflow events into compact, user-facing CLI progress."""
    if stage == "信源采集":
        source = str(detail.get("provider") or "unknown")
        index = detail.get("source_index")
        total = detail.get("source_total")
        if status == "in_progress":
            message = f"正在检查信源 {index}/{total}：{source}"
        elif status == "success":
            message = (
                f"信源 {index}/{total}：{source} 完成，获得 {detail.get('items', 0)} 条，"
                f"含日期 {detail.get('dated', 0)} 条，耗时 {detail.get('elapsed_seconds', 0)} 秒"
            )
        elif status == "skipped":
            message = f"信源 {index}/{total}：{source} 暂跳过（近期请求异常，冷却中）"
        else:
            message = f"信源 {index}/{total}：{source} 失败，已继续检查其他信源：{detail.get('error', '')}"
    elif stage == "准备候选池":
        message = (
            f"计划生成 {detail.get('requested_count')} 条；先收集约 {detail.get('raw_target')} 条原始材料，"
            f"至少保留 {detail.get('min_qualified')} 条合格候选"
        )
    elif stage == "候选筛选":
        message = (
            f"{detail.get('window_days', '当前')}天窗口：近期 {detail.get('recent', detail.get('raw', 0))} 条，"
            f"相关 {detail.get('relevant', detail.get('qualified', 0))} 条，"
            f"合格 {detail.get('qualified', 0)}/{detail.get('min_qualified', 0)} 条"
        )
    elif stage == "模型审校候选":
        message = (
            f"模型正在审校 {detail.get('candidates', detail.get('reviewed', 0))} 条候选，"
            f"为 {detail.get('target_count', '')} 条草稿排序、去重和保留国内新闻配额"
        )
        if status == "success":
            message = f"模型审校完成：已重排 {detail.get('ranked', 0)} 条候选"
        elif status == "warning":
            reason = str(detail.get("reason") or "未知原因")
            message = f"模型审校暂不可用，已改用本地规则排序。原因：{reason}"
    elif stage in {"原文核验", "生成文案", "质量复核", "生成配图", "生成草稿"}:
        completed = detail.get("completed", detail.get("draft_index", 0))
        target = detail.get("target", "")
        if stage == "原文核验":
            candidate_index = detail.get("candidate_index", completed)
            candidate_total = detail.get("candidate_total")
            if candidate_total:
                message = f"原文核验：候选 {candidate_index}/{candidate_total}，已完成 {completed}/{target} 条"
            else:
                message = f"原文核验：候选 {candidate_index}，已完成 {completed}/{target} 条"
        else:
            message = f"{stage}：第 {completed}/{target} 条"
        reason = _humanize_daily_news_progress_reason(detail.get("reason"))
        if status in {"skipped", "failed"} and reason:
            message += f"，原因：{reason}"
        elif status == "success" and stage == "生成草稿":
            message = f"草稿生成完成：{completed}/{target} 条"
    else:
        message = "；".join(f"{key}={value}" for key, value in detail.items())
    _emit_progress_event("auto", stage, status, message)


def _env_first(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _record_generation_run(
    *,
    command: str,
    title: str,
    prompt: str,
    requested_count: int,
    generated_count: int,
    uploaded_count: int,
    failed_count: int,
    started_at: str,
    post_ids: list[str],
    errors: list[str],
) -> None:
    llm_provider = _env_first("LLM_PROVIDER") or "auto"
    if llm_provider in {"volcengine", "ark"}:
        llm_models = _env_first(
            "VOLCENGINE_LLM_MODELS",
            "VOLCENGINE_LLM_MODEL",
            "ARK_LLM_MODELS",
            "ARK_LLM_MODEL",
        )
    elif llm_provider in {"aliyun", "dashscope", "bailian"}:
        llm_models = _env_first(
            "ALIYUN_LLM_MODELS",
            "ALIYUN_LLM_MODEL",
        )
    else:
        llm_models = _env_first(
            "VOLCENGINE_LLM_MODELS",
            "VOLCENGINE_LLM_MODEL",
            "ALIYUN_LLM_MODELS",
            "ALIYUN_LLM_MODEL",
            "LLM_MODEL",
        )
    image_provider = _env_first("IMAGE_PROVIDER") or "local/auto"
    if image_provider in {"volcengine", "ark", "doubao", "seedream"}:
        image_models = _env_first(
            "VOLCENGINE_IMAGE_MODELS",
            "VOLCENGINE_IMAGE_MODEL",
            "ARK_IMAGE_MODELS",
            "ARK_IMAGE_MODEL",
        )
    elif image_provider in {"aliyun", "dashscope", "bailian", "qwen_image", "qwen-image"}:
        image_models = _env_first(
            "ALIYUN_IMAGE_MODELS",
            "ALIYUN_IMAGE_MODEL",
        )
    else:
        image_models = _env_first(
            "VOLCENGINE_IMAGE_MODELS",
            "VOLCENGINE_IMAGE_MODEL",
            "ALIYUN_IMAGE_MODELS",
            "ALIYUN_IMAGE_MODEL",
        )
    record = RunRecord(
        command=command,
        title=title,
        prompt=prompt,
        requested_count=requested_count,
        generated_count=generated_count,
        uploaded_count=uploaded_count,
        failed_count=failed_count,
        started_at=started_at,
        ended_at=now_iso(),
        llm_provider=llm_provider,
        llm_models=llm_models,
        image_provider=image_provider,
        image_models=image_models,
        news_provider=_env_first("NEWS_PROVIDER") or "auto",
        post_ids=post_ids,
        errors=errors,
        extra={
            "auto_image": _env_first("AUTO_IMAGE"),
            "news_candidates_file": _env_first("NEWS_CANDIDATES_FILE"),
            "news_materials_file": _env_first("NEWS_MATERIALS_FILE"),
            "single_news_material_file": _env_first("SINGLE_NEWS_MATERIAL_FILE"),
            "vlm_provider": _env_first("VLM_REVIEW_PROVIDER"),
            "vlm_model": configured_vision_review_model(),
        },
    )
    paths = append_run_record(record)
    typer.echo(f"run-record: {paths['csv']}")


def _headless_env_enabled() -> bool:
    return (os.getenv("XHS_HEADLESS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _headless_option_value(headless: bool):
    return True if headless else None


def _headless_requested(headless: bool) -> bool:
    return bool(headless or _headless_env_enabled())


def _warn_headless_login_hold(headless: bool, login_hold: int) -> None:
    if _headless_requested(headless) and login_hold > 0:
        typer.echo(
            "warn: --headless requires an already logged-in Chrome profile; "
            "login-hold cannot display QR/captcha windows"
        )


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _parse_post_time(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
            return dt.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _post_publishable_date(post: Post) -> str:
    raw = post.uploaded_at or post.updated_at or post.created_at
    dt = _parse_post_time(raw or "")
    if not dt:
        return ""
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d")


def _is_publishable_uploaded_post(post: Post) -> bool:
    if not post.uploaded:
        return False
    return post.status not in {PostStatus.published, PostStatus.failed, PostStatus.canceled}


def _select_publishable_posts(
    *,
    date: str = "",
    post_ids: list[str],
    include_all: bool = False,
    limit: int = 0,
) -> list[Post]:
    date_norm = (date or "").strip()
    post_id_set = {p.strip().lower() for p in post_ids if p and p.strip()}
    if post_id_set:
        candidates: list[Post] = []
        for post_id in post_id_set:
            try:
                candidates.append(load_post(post_id))
            except FileNotFoundError:
                continue
    else:
        candidates = list(list_posts())
        candidates.sort(
            key=lambda post: _parse_post_time(post.uploaded_at or post.updated_at or post.created_at or "")
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    selected: list[Post] = []
    for post in candidates:
        if not _is_publishable_uploaded_post(post):
            continue
        if date_norm and _post_publishable_date(post) != date_norm:
            continue
        if not (include_all or date_norm or post_id_set):
            continue
        selected.append(post)
        if limit and len(selected) >= limit:
            break
    return selected


def _mark_posts_published(posts: list[Post], result: dict) -> None:
    published_ids = {str(p).strip().lower() for p in result.get("published_post_ids", []) if str(p).strip()}
    if not published_ids and result.get("published", 0) == len(posts):
        published_ids = {post.id.lower() for post in posts}
    result_items: dict[str, dict] = {}
    for item in result.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        item_post_id = str(item.get("post_id") or "").strip().lower()
        if item_post_id:
            result_items[item_post_id] = item
    now = now_iso()
    for post in posts:
        if post.id.lower() not in published_ids:
            continue
        item = result_items.get(post.id.lower(), {})
        post.status = PostStatus.published
        post.updated_at = now
        post.platform.setdefault("publish", {})
        publish_update = {
            "result": "published",
            "published_at": now,
            "source": "creator_center_draft",
        }
        for source_key, target_key in (
            ("actual_title", "actual_title"),
            ("actual_body", "actual_body"),
            ("title", "draft_list_title"),
            ("saved_at", "draft_saved_at"),
            ("url", "url"),
            ("note_url", "url"),
        ):
            value = str(item.get(source_key) or "").strip()
            if value:
                publish_update[target_key] = value
        post.platform["publish"].update(publish_update)
        save_post(post)


def create(
    title: str = typer.Option(..., help="初始标题/题目"),
    prompt: str = typer.Option(
        "",
        "--keywords",
        "--prompt",
        help="新闻检索关键词（可选；--prompt 保留为兼容别名）",
    ),
    evaluation_viewpoint: str = typer.Option(
        DEFAULT_EVALUATION_VIEWPOINT,
        "--evaluation-viewpoint",
        help="每日新闻评价视角；默认无视角评价",
    ),
    lookback_days: Optional[int] = typer.Option(
        None,
        "--lookback-days",
        help="每日新闻只允许 1/2 天且默认 2 天；每日AI讯息留空按 3/7/14 天自动扩展",
    ),
    news_materials_file: str = typer.Option(
        "",
        "--news-materials-file",
        help="每日新闻人工材料文件（.md/.txt/.json/.jsonl）；提供后跳过在线新闻抓取",
        show_default=False,
    ),
    single_news_material_file: str = typer.Option(
        "",
        "--single-news-material-file",
        help="每日新闻单条材料文件；提供后只生成 1 条，并忽略关键词/数量/回溯筛选",
        show_default=False,
    ),
    assets_glob: str = typer.Option("assets/pics/*", help="素材路径（glob）"),
    count: int = typer.Option(1, help="生成草稿数量（>=1）"),
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
):
    """生成草稿并落盘（post.json + revision）。"""
    title_norm = _repair_cli_text((title or "").strip(), field="title")
    prompt_norm = _repair_cli_text((prompt or "").strip(), field="prompt")
    news_materials_file_norm = (news_materials_file or "").strip()
    single_news_material_file_norm = (single_news_material_file or "").strip()
    if news_materials_file_norm and single_news_material_file_norm:
        typer.echo("error: --single-news-material-file and --news-materials-file are mutually exclusive")
        raise typer.Exit(code=1)
    if title_norm == "每日新闻" and single_news_material_file_norm:
        prompt_norm = ""
        lookback_days = None
        count = 1
    asset_paths = _initial_asset_paths(assets_glob)
    if not asset_paths:
        _emit_missing_assets_hint(title_norm)

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    requested_count = 1 if _is_daily_ai_digest_title(title_norm) else count
    if requested_count != count:
        typer.echo(
            "note: 每日AI讯息会生成 1 条简报草稿，并按质量自动选择 8-20 条动态；"
            "AI_DIGEST_MAX_ITEMS 只控制上限。"
        )

    started_at = now_iso()
    run_errors: list[str] = []
    generation_failed_count = 0
    generation_stage = _generation_stage_for_title(title_norm)
    daily_news_inline_quality = False
    _emit_progress_event("create", "准备生成", "in_progress", f"title={title_norm} count={requested_count}")
    _emit_progress_event("create", generation_stage, "in_progress", f"count={requested_count}")

    if _is_daily_ai_digest_title(title_norm):
        try:
            posts = create_daily_ai_digest_posts(
                prompt_hint=prompt_norm,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                count=1,
                auto_image=True,
                evaluation_viewpoint=evaluation_viewpoint,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            typer.echo(_format_stage_error(_stage_from_create_exception(exc), exc))
            posts = []
            generation_failed_count = requested_count
            run_errors.append(str(exc))
    elif title_norm == "每日新闻":
        try:
            posts = create_daily_news_posts(
                prompt_hint=prompt_norm,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                count=count,
                auto_image=True,
                evaluation_viewpoint=evaluation_viewpoint,
                lookback_days=lookback_days,
                news_materials_file=news_materials_file_norm,
                single_news_material_file=single_news_material_file_norm,
            )
        except PartialDailyNewsError as exc:
            typer.echo(f"partial daily news: generated={len(exc.posts)}/{exc.requested_count}; {exc}")
            posts = exc.posts
            generation_failed_count = max(0, exc.requested_count - len(exc.posts), exc.failed_count)
            run_errors.append(str(exc))
        except Exception as exc:
            typer.echo(_format_stage_error(_stage_from_create_exception(exc), exc))
            posts = []
            generation_failed_count = requested_count
            run_errors.append(str(exc))
    else:
        used_image_ids: set[str] = set()
        posts = []
        for idx in range(count):
            try:
                posts.append(
                    create_post_with_draft(
                        title_hint=title,
                        prompt_hint=prompt,
                        asset_paths=asset_paths,
                        copy_assets=not no_copy,
                        auto_image=True,
                        image_exclude_ids=used_image_ids,
                        lookback_days=lookback_days,
                        news_materials_file=news_materials_file_norm,
                        single_news_material_file=single_news_material_file_norm,
                    )
                )
            except Exception as exc:
                typer.echo(_format_stage_error(_stage_from_create_exception(exc), f"create failed ({idx + 1}/{count}): {exc}"))
                generation_failed_count += 1
                run_errors.append(str(exc))
                continue

    if not posts:
        _emit_progress_event("create", generation_stage, "failed", "posts=0")
        _record_generation_run(
            command="create",
            title=title_norm,
            prompt=prompt_norm,
            requested_count=requested_count,
            generated_count=0,
            uploaded_count=0,
            failed_count=max(generation_failed_count, requested_count),
            started_at=started_at,
            post_ids=[],
            errors=run_errors,
        )
        typer.echo("error: no posts created")
        raise typer.Exit(code=1)

    _emit_progress_event("create", generation_stage, "success", f"posts={len(posts)}")
    _record_generation_run(
        command="create",
        title=title_norm,
        prompt=prompt_norm,
        requested_count=requested_count,
        generated_count=len(posts),
        uploaded_count=0,
        failed_count=max(generation_failed_count, requested_count - len(posts)),
        started_at=started_at,
        post_ids=[p.id for p in posts],
        errors=run_errors,
    )

    if len(posts) == 1:
        post = posts[0]
        typer.echo(f"创建完成：post_id={post.id}")
        typer.echo(f"标题：{post.title}")
        typer.echo(f"正文（前60字）：{post.body[:60]}{'...' if len(post.body) > 60 else ''}")
    else:
        typer.echo(f"创建完成：posts={len(posts)}")
        for p in posts:
            typer.echo(f"- post_id={p.id} | 标题：{p.title}")


@app.command("list")
def _list():
    """列出现有 post。"""
    posts = list_posts()
    if not posts:
        typer.echo("暂无 post")
        return
    for p in posts:
        typer.echo(
            f"{p.id} | {p.type} | {p.status} | uploaded:{p.uploaded} | 标题:{p.title}"
        )


@app.command()
def show(post_id: str):
    """查看单个 post 详情。"""
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)
    typer.echo(post.model_dump_json(indent=2, ensure_ascii=False))


@app.command()
def approve(
    post_id: str = typer.Argument(..., help="post_id (data/posts/<id>/post.json)"),
    force: bool = typer.Option(False, help="approve even if validation fails"),
):
    """Validate a post and mark it as approved."""
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)

    result = validate_post(post)
    _emit_validation(result)
    if result.errors and not force:
        raise typer.Exit(code=1)

    post.status = PostStatus.approved
    post.updated_at = now_iso()
    save_post(post)
    typer.echo(f"approved: {post.id}")


@app.command()
def validate(
    post_id: str = typer.Argument(..., help="post_id (data/posts/<id>/post.json)"),
):
    """Validate a post without changing its status."""
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)

    result = validate_post(post)
    _emit_validation(result)
    if result.errors:
        raise typer.Exit(code=1)
    typer.echo("ok")


@app.command()
def run(
    post_id: str = typer.Argument(..., help="post_id (data/posts/<id>/post.json)"),
    assets_glob: str = typer.Option(
        "",
        help="assets glob override; default uses the post's frozen asset manifest",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False, help="open page and capture evidence only; skip upload/fill/save"
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
    platform: str = typer.Option(
        "xhs",
        "--platform",
        help="draft destination: xhs, toutiao, or both",
    ),
    force: bool = typer.Option(False, help="run even if not approved or validation fails"),
):
    """Save a draft to Xiaohongshu, Toutiao, or both platforms."""
    _emit_progress_event("run", "读取草稿", "in_progress", f"post_id={post_id}")
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)

    try:
        platform_norm = normalize_publish_platform(platform)
        target_platforms = publish_targets(platform_norm)
    except ValueError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)

    _emit_progress_event("run", "读取草稿", "success", f"post_id={post.id}")
    if not force:
        if "xhs" in target_platforms and post.status != PostStatus.approved:
            typer.echo("保存到小红书前 post 必须已审批；请先运行 approve 或使用 --force")
            raise typer.Exit(code=1)
        if target_platforms == ("toutiao",) and post.status not in {
            PostStatus.approved,
            PostStatus.saved_draft,
            PostStatus.published,
        }:
            typer.echo("保存到今日头条前 post 必须是已审批、已保存草稿或已发布状态")
            raise typer.Exit(code=1)

    _emit_progress_event("run", "校验草稿", "in_progress", f"post_id={post.id}")
    result = validate_post(post)
    _emit_validation(result)
    if result.errors and not force:
        _emit_progress_event("run", "校验草稿", "failed", f"post_id={post.id} errors={len(result.errors)}")
        raise typer.Exit(code=1)
    _emit_progress_event("run", "校验草稿", "success", f"post_id={post.id}")

    asset_paths = _resolve_asset_paths(post, assets_glob)
    if post.type == PostType.image and not asset_paths and not dry_run:
        typer.echo("未找到素材文件，请检查 assets_glob 或 data/posts/<id>/assets")
        raise typer.Exit(code=1)

    _warn_headless_login_hold(headless, login_hold)
    previous_status = post.status
    saved_targets: list[str] = []
    failed_targets: list[str] = []
    for target in target_platforms:
        target_label = "小红书" if target == "xhs" else "今日头条"
        stage = f"上传{target_label}草稿"
        attempt = _next_attempt(post_id)
        exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
        _emit_progress_event("run", stage, "in_progress", f"post_id={post.id}")
        runner = run_save_draft_sync if target == "xhs" else run_save_toutiao_draft_sync
        exec_rec = runner(
            post,
            assets=asset_paths,
            dry_run=dry_run,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
            execution=exec_rec,
            headless=_headless_option_value(headless),
            progress_callback=_upload_progress(post.id),
        )

        typer.echo(f"platform={target} result: {exec_rec.result}")
        for step_result in exec_rec.steps:
            detail = f" | {step_result.detail}" if step_result.detail else ""
            typer.echo(f"- {step_result.name}: {step_result.status}{detail}")
        if exec_rec.error:
            typer.echo(_format_stage_error(stage, exec_rec.error))

        if exec_rec.result == "saved_draft":
            saved_targets.append(target)
            post.updated_at = now_iso()
            _mark_post_uploaded(post, exec_rec.result)
            if target == "xhs":
                post.platform["xhs_draft"] = {
                    "title": post.title,
                    "saved_at": post.updated_at,
                    "execution_id": exec_rec.id,
                }
            else:
                article = adapt_post_for_toutiao(post)
                post.platform["toutiao_draft"] = {
                    "title": article.title,
                    "saved_at": post.updated_at,
                    "execution_id": exec_rec.id,
                }
            _emit_progress_event("run", stage, "success", f"post_id={post.id}")
        elif dry_run and exec_rec.result == "pending" and not exec_rec.error:
            _emit_progress_event("run", stage, "success", f"post_id={post.id} dry_run")
        else:
            failed_targets.append(target)
            _emit_progress_event(
                "run",
                stage,
                "failed",
                f"post_id={post.id} error={exec_rec.error or exec_rec.result}",
            )

    has_existing_platform_draft = any(
        isinstance(post.platform.get(key), dict)
        and bool(str(post.platform[key].get("saved_at") or "").strip())
        for key in ("xhs_draft", "toutiao_draft")
    )
    if previous_status != PostStatus.published:
        if saved_targets or has_existing_platform_draft:
            post.status = PostStatus.saved_draft
        elif failed_targets:
            post.status = PostStatus.failed
    post.updated_at = now_iso()
    save_post(post)
    if failed_targets:
        typer.echo(f"error: failed platforms: {', '.join(failed_targets)}")
        raise typer.Exit(code=1)


@app.command("update-draft")
def update_draft(
    post_id: str = typer.Argument(..., help="post_id (data/posts/<id>/post.json)"),
    draft_type: str = typer.Option("image", help="draft type: image/video/article"),
    dry_run: bool = typer.Option(False, help="open and verify the existing draft without changing it"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for draft UI"),
):
    """Update an existing Xiaohongshu draft in place, without creating a duplicate."""
    _emit_progress_event("update-draft", "读取草稿", "in_progress", f"post_id={post_id}")
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post not found")
        raise typer.Exit(code=1)
    if post.status not in (PostStatus.saved_draft, PostStatus.approved, PostStatus.draft):
        typer.echo(f"post status cannot be updated as a draft: {post.status.value}")
        raise typer.Exit(code=1)

    _warn_headless_login_hold(headless, login_hold)
    attempt = _next_attempt(post_id)
    exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
    saved_draft_meta = post.platform.get("xhs_draft") or {}
    existing_title = str(saved_draft_meta.get("title") or post.title).strip()
    _emit_progress_event("update-draft", "更新平台草稿", "in_progress", f"post_id={post.id}")
    exec_rec = run_update_draft_sync(
        post,
        existing_title=existing_title,
        draft_type=draft_type,
        dry_run=dry_run,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        execution=exec_rec,
        headless=_headless_option_value(headless),
        progress_callback=_upload_progress(post.id),
    )

    typer.echo(f"result: {exec_rec.result}")
    for step in exec_rec.steps:
        detail = f" | {step.detail}" if step.detail else ""
        typer.echo(f"- {step.name}: {step.status}{detail}")
    if exec_rec.error:
        typer.echo(_format_stage_error("更新草稿", exec_rec.error))

    if dry_run:
        return
    if exec_rec.result != "saved_draft":
        _emit_progress_event("update-draft", "更新平台草稿", "failed", f"post_id={post.id}")
        raise typer.Exit(code=1)

    post.status = PostStatus.saved_draft
    post.uploaded = True
    post.updated_at = now_iso()
    post.platform["draft_update"] = {
        "result": exec_rec.result,
        "previous_title": existing_title,
        "title": post.title,
        "updated_at": post.updated_at,
        "execution_id": exec_rec.id,
    }
    post.platform["xhs_draft"] = {
        "title": post.title,
        "saved_at": post.updated_at,
        "execution_id": exec_rec.id,
    }
    save_post(post)
    _emit_progress_event("update-draft", "更新平台草稿", "success", f"post_id={post.id}")


@app.command()
def auto(
    ctx: typer.Context,
    title: str = typer.Option(..., help="初始标题/题目"),
    prompt: str = typer.Option(
        "",
        "--keywords",
        "--prompt",
        help="新闻检索关键词（可选；--prompt 保留为兼容别名）",
    ),
    evaluation_viewpoint: str = typer.Option(
        DEFAULT_EVALUATION_VIEWPOINT,
        "--evaluation-viewpoint",
        help="每日新闻评价视角；默认无视角评价",
    ),
    lookback_days: Optional[int] = typer.Option(
        None,
        "--lookback-days",
        help="每日新闻只允许 1/2 天且默认 2 天；每日AI讯息留空按 3/7/14 天自动扩展",
    ),
    news_materials_file: str = typer.Option(
        "",
        "--news-materials-file",
        help="每日新闻人工材料文件（.md/.txt/.json/.jsonl）；提供后跳过在线新闻抓取",
        show_default=False,
    ),
    single_news_material_file: str = typer.Option(
        "",
        "--single-news-material-file",
        help="每日新闻单条材料文件；提供后只生成 1 条，并忽略关键词/数量/回溯筛选",
        show_default=False,
    ),
    assets_glob: str = typer.Option("assets/pics/*", help="素材路径（glob）"),
    count: int = typer.Option(1, help="生成草稿数量（>=1）"),
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
    dry_run: bool = typer.Option(
        False, help="open page and capture evidence only; skip upload/fill/save"
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
    platform: str = typer.Option(
        "xhs",
        "--platform",
        help="draft destination: xhs, toutiao, or both",
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="save any completed daily-news drafts when the full requested batch cannot be generated (advanced; default is all-or-stop)",
    ),
    preflight: bool = typer.Option(
        True,
        "--preflight/--no-preflight",
        help="check published metrics and free model quotas before generation",
    ),
    metrics_max_age_hours: float = typer.Option(
        24.0,
        "--metrics-max-age-hours",
        min=0.1,
        help="maximum age in hours for reusing the published-metrics snapshot",
    ),
    quota_max_age_hours: float = typer.Option(
        2.0,
        "--quota-max-age-hours",
        min=0.1,
        help="maximum age in hours for reusing free-quota snapshots",
    ),
    force: bool = typer.Option(False, help="run even if validation fails"),
):
    """Generate content then save draft in one command."""
    title_norm = _repair_cli_text((title or "").strip(), field="title")
    prompt_norm = _repair_cli_text((prompt or "").strip(), field="prompt")
    try:
        platform_norm = normalize_publish_platform(platform)
        target_platforms = publish_targets(platform_norm)
    except ValueError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(code=1)
    news_materials_file_norm = (news_materials_file or "").strip()
    single_news_material_file_norm = (single_news_material_file or "").strip()
    if news_materials_file_norm and single_news_material_file_norm:
        typer.echo("error: --single-news-material-file and --news-materials-file are mutually exclusive")
        raise typer.Exit(code=1)
    if title_norm == "每日新闻" and single_news_material_file_norm:
        prompt_norm = ""
        lookback_days = None
        count = 1
    asset_paths = _initial_asset_paths(assets_glob)
    if not asset_paths:
        _emit_missing_assets_hint(title_norm, dry_run=dry_run)

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    requested_count = 1 if _is_daily_ai_digest_title(title_norm) else count
    if requested_count != count:
        typer.echo(
            "note: 每日AI讯息会生成 1 条简报草稿，并按质量自动选择 8-20 条动态；"
            "AI_DIGEST_MAX_ITEMS 只控制上限。"
        )

    started_at = now_iso()
    run_errors: list[str] = []
    generation_failed_count = 0

    _warn_headless_login_hold(headless, login_hold)
    if preflight:
        try:
            preflight_report = _prepare_auto_pipeline(
                headless=headless,
                login_hold=login_hold,
                wait_timeout=wait_timeout,
                metrics_max_age_hours=metrics_max_age_hours,
                quota_max_age_hours=quota_max_age_hours,
                require_image=not _is_daily_ai_digest_title(title_norm),
            )
        except FreeQuotaUnavailableError as exc:
            _emit_progress_event("auto", "选择免费模型", "failed", str(exc))
            typer.echo(
                _format_stage_error(
                    "免费模型预检",
                    f"{exc} 请先在 GUI 点击“同步免费额度”，或运行 sync-quotas 后重试。",
                )
            )
            raise typer.Exit(code=1)
        except Exception as exc:
            _emit_progress_event("auto", "运行预检", "failed", str(exc))
            typer.echo(
                _format_stage_error(
                    "运行预检",
                    f"{exc} 尚未开始生成或调用模型。",
                )
            )
            raise typer.Exit(code=1)
        if preflight_report.model_plan is not None:
            _apply_scoped_environment(ctx, preflight_report.model_plan.environment())
    generation_stage = _generation_stage_for_title(title_norm)
    daily_news_inline_quality = False
    _emit_progress_event("auto", "准备生成", "in_progress", f"title={title_norm} count={requested_count}")
    _emit_progress_event("auto", generation_stage, "in_progress", f"count={requested_count}")
    if _is_daily_ai_digest_title(title_norm):
        try:
            posts = create_daily_ai_digest_posts(
                prompt_hint=prompt_norm,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                count=1,
                auto_image=True,
                evaluation_viewpoint=evaluation_viewpoint,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            typer.echo(_format_stage_error(_stage_from_create_exception(exc), exc))
            posts = []
            generation_failed_count = requested_count
            run_errors.append(str(exc))
    elif title_norm == "每日新闻":
        try:
            daily_news_inline_quality = bool(
                preflight
                and not news_materials_file_norm
                and not single_news_material_file_norm
            )
            post_quality_callback = None
            if daily_news_inline_quality:
                _emit_progress_event(
                    "auto",
                    "准备视觉递补",
                    "in_progress",
                    f"requested={count} candidate_pool=continuous",
                )
                typer.echo(
                    f"视觉递补：逐条生成并审核，失败时继续使用候选池，直到保留 {count} 条。"
                )

                def post_quality_callback(candidate_post: Post) -> list[str]:
                    candidate_errors = _run_auto_quality_gate(
                        [candidate_post],
                        expected_count=1,
                        evaluation_viewpoint=evaluation_viewpoint,
                        require_vision=True,
                    )
                    _emit_progress_event(
                        "auto",
                        "视觉递补",
                        "warning" if candidate_errors else "success",
                        (
                            f"post_id={candidate_post.id} rejected=1 reason={candidate_errors[0]}"
                            if candidate_errors
                            else f"post_id={candidate_post.id} accepted=1"
                        ),
                    )
                    return candidate_errors

            posts = create_daily_news_posts(
                prompt_hint=prompt_norm,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                count=count,
                auto_image=True,
                evaluation_viewpoint=evaluation_viewpoint,
                lookback_days=lookback_days,
                news_materials_file=news_materials_file_norm,
                single_news_material_file=single_news_material_file_norm,
                progress_callback=_daily_news_generation_progress,
                post_quality_callback=post_quality_callback,
            )
        except PartialDailyNewsError as exc:
            typer.echo(f"partial daily news: generated={len(exc.posts)}/{exc.requested_count}; {exc}")
            generation_failed_count = max(0, exc.requested_count - len(exc.posts), exc.failed_count)
            run_errors.append(str(exc))
            if allow_partial:
                posts = exc.posts
                typer.echo("warning: --allow-partial is enabled; completed drafts will be saved while the batch remains incomplete")
            else:
                posts = []
                typer.echo(
                    "batch incomplete: no draft will be uploaded. "
                    "The requested count was not fully generated; review the step-by-step reason above and retry."
                )
                typer.echo(
                    f"summary: generated={len(exc.posts)} uploaded=0 "
                    f"failed={generation_failed_count} requested={exc.requested_count}"
                )
        except Exception as exc:
            typer.echo(_format_stage_error(_stage_from_create_exception(exc), exc))
            posts = []
            generation_failed_count = requested_count
            run_errors.append(str(exc))
    else:
        used_image_ids: set[str] = set()
        posts = []
        for idx in range(count):
            try:
                posts.append(
                    create_post_with_draft(
                        title_hint=title,
                        prompt_hint=prompt,
                        asset_paths=asset_paths,
                        copy_assets=not no_copy,
                        auto_image=True,
                        image_exclude_ids=used_image_ids,
                        lookback_days=lookback_days,
                        news_materials_file=news_materials_file_norm,
                        single_news_material_file=single_news_material_file_norm,
                    )
                )
            except Exception as exc:
                typer.echo(_format_stage_error(_stage_from_create_exception(exc), f"create failed ({idx + 1}/{count}): {exc}"))
                generation_failed_count += 1
                run_errors.append(str(exc))
                continue

    typer.echo(f"创建完成：posts={len(posts)}")
    for p in posts:
        typer.echo(f"- post_id={p.id} | 标题：{p.title}")
    if not posts:
        _emit_progress_event("auto", generation_stage, "failed", "posts=0")
        _record_generation_run(
            command="auto",
            title=title_norm,
            prompt=prompt_norm,
            requested_count=requested_count,
            generated_count=0,
            uploaded_count=0,
            failed_count=max(generation_failed_count, requested_count),
            started_at=started_at,
            post_ids=[],
            errors=run_errors,
        )
        typer.echo("error: no posts created")
        raise typer.Exit(code=1)

    if preflight:
        quality_errors = _run_auto_quality_gate(
            posts,
            expected_count=len(posts) if (allow_partial or len(posts) != requested_count) else requested_count,
            evaluation_viewpoint=evaluation_viewpoint,
            require_vision=True,
            reuse_vision_results=daily_news_inline_quality,
        )
        if title_norm == "每日新闻" and len(posts) > requested_count:
            selected_posts, failed_quality_posts, unused_spares = _select_visual_ready_daily_news_posts(
                posts,
                requested_count=requested_count,
            )
            if len(selected_posts) >= requested_count:
                for post in failed_quality_posts:
                    post.status = PostStatus.failed
                    post.platform["batch_selection"] = {
                        "status": "visual_quality_failed",
                        "reason": "visual quality review did not pass; excluded before upload",
                    }
                    post.updated_at = now_iso()
                    save_post(post)
                for post in unused_spares:
                    post.status = PostStatus.canceled
                    post.platform["batch_selection"] = {
                        "status": "unused_visual_spare",
                        "reason": "valid spare was not needed after requested count passed quality review",
                    }
                    post.updated_at = now_iso()
                    save_post(post)
                posts = selected_posts
                quality_errors = []
                _emit_progress_event(
                    "auto",
                    "视觉备选替换",
                    "success",
                    f"selected={len(posts)} quality_failed={len(failed_quality_posts)} unused_spares={len(unused_spares)}",
                )
                typer.echo(
                    f"视觉备选替换：保留 {len(posts)} 条；"
                    f"淘汰 {len(failed_quality_posts)} 条视觉不合格稿，"
                    f"取消 {len(unused_spares)} 条未使用备选。"
                )
        if quality_errors:
            run_errors.extend(quality_errors)
            _record_generation_run(
                command="auto",
                title=title_norm,
                prompt=prompt_norm,
                requested_count=requested_count,
                generated_count=len(posts),
                uploaded_count=0,
                failed_count=max(generation_failed_count, len(quality_errors)),
                started_at=started_at,
                post_ids=[post.id for post in posts],
                errors=run_errors,
            )
            typer.echo(
                "error: stage=上传前质量检查 | 未上传任何草稿。"
                + " | ".join(quality_errors[:5])
            )
            raise typer.Exit(code=1)

    _emit_progress_event("auto", generation_stage, "success", f"posts={len(posts)}")
    atomic_daily_batch = title_norm == "每日新闻" and not allow_partial
    if atomic_daily_batch:
        preflight_errors: list[str] = []
        preflight_fingerprints: dict[str, str] = {}
        _emit_progress_event("auto", "批次预检", "in_progress", f"posts={len(posts)} requested={requested_count}")
        for idx, post in enumerate(posts, start=1):
            fingerprint = _post_upload_fingerprint(post)
            duplicate_of = preflight_fingerprints.get(fingerprint) if fingerprint else None
            if duplicate_of:
                preflight_errors.append(f"第 {idx} 条与第 {duplicate_of} 条内容重复")
                continue
            if fingerprint:
                preflight_fingerprints[fingerprint] = str(idx)
            validation = validate_post(post)
            if validation.errors and not force:
                preflight_errors.append(f"第 {idx} 条草稿校验失败：{'；'.join(validation.errors)}")
        if preflight_errors:
            run_errors.extend(preflight_errors)
            _emit_progress_event("auto", "批次预检", "failed", f"errors={len(preflight_errors)}")
            _record_generation_run(
                command="auto",
                title=title_norm,
                prompt=prompt_norm,
                requested_count=requested_count,
                generated_count=len(posts),
                uploaded_count=0,
                failed_count=max(generation_failed_count, len(preflight_errors)),
                started_at=started_at,
                post_ids=[post.id for post in posts],
                errors=run_errors,
            )
            typer.echo("batch validation failed: no draft was uploaded. " + " | ".join(preflight_errors))
            raise typer.Exit(code=1)
        _emit_progress_event("auto", "批次预检", "success", f"posts={len(posts)}")
    continue_on_invalid = requested_count > 1 and not atomic_daily_batch
    skipped_invalid = 0
    uploaded = 0
    upload_failed = 0

    total_posts = len(posts)
    seen_upload_fingerprints: dict[str, str] = {}
    for idx, post in enumerate(posts, start=1):
        _emit_progress_event("auto", "校验草稿", "in_progress", f"post_id={post.id} index={idx}/{total_posts}")
        fingerprint = _post_upload_fingerprint(post)
        duplicate_of = seen_upload_fingerprints.get(fingerprint) if fingerprint else None
        if duplicate_of:
            skipped_invalid += 1
            post.status = PostStatus.failed
            post.platform["validation"] = {
                "errors": [f"duplicate draft content (same as {duplicate_of})"],
                "warnings": [],
            }
            post.updated_at = now_iso()
            save_post(post)
            _emit_progress_event("auto", "校验草稿", "failed", f"post_id={post.id} duplicate_of={duplicate_of}")
            run_errors.append(f"duplicate draft skipped post_id={post.id}: same as {duplicate_of}")
            typer.echo(f"skip duplicate post_id={post.id} same_as={duplicate_of}")
            continue
        result = validate_post(post)
        _emit_validation(result)
        if result.errors and not force:
            if not continue_on_invalid:
                skipped_invalid += 1
                post.status = PostStatus.failed
                post.platform["validation"] = {
                    "errors": list(result.errors),
                    "warnings": list(result.warnings),
                }
                post.updated_at = now_iso()
                save_post(post)
                _emit_progress_event("auto", "校验草稿", "failed", f"post_id={post.id} errors={len(result.errors)}")
                run_errors.append(f"validation failed post_id={post.id}: {result.errors}")
                _record_generation_run(
                    command="auto",
                    title=title_norm,
                    prompt=prompt_norm,
                    requested_count=requested_count,
                    generated_count=len(posts),
                    uploaded_count=uploaded,
                    failed_count=max(generation_failed_count + skipped_invalid, requested_count - uploaded),
                    started_at=started_at,
                    post_ids=[p.id for p in posts],
                    errors=run_errors,
                )
                typer.echo(
                    f"summary: generated={len(posts)} uploaded={uploaded} "
                    f"failed={max(generation_failed_count + skipped_invalid, requested_count - uploaded)} "
                    f"skipped_invalid={skipped_invalid} upload_failed={upload_failed} requested={requested_count}"
                )
                raise typer.Exit(code=1)
            skipped_invalid += 1
            post.status = PostStatus.failed
            post.platform["validation"] = {
                "errors": list(result.errors),
                "warnings": list(result.warnings),
            }
            post.updated_at = now_iso()
            save_post(post)
            _emit_progress_event("auto", "校验草稿", "failed", f"post_id={post.id} errors={len(result.errors)}")
            typer.echo(f"skip invalid post_id={post.id}")
            run_errors.append(f"validation failed post_id={post.id}: {result.errors}")
            continue

        # Only a draft that will enter the upload path reserves this content.
        # An earlier invalid draft must not suppress a later valid replacement.
        if fingerprint:
            seen_upload_fingerprints[fingerprint] = post.id
        post.status = PostStatus.approved
        post.updated_at = now_iso()
        save_post(post)
        _emit_progress_event("auto", "校验草稿", "success", f"post_id={post.id}")

        resolved_assets = _resolve_asset_paths(post, "")
        saved_targets: list[str] = []
        target_errors: list[str] = []
        for target in target_platforms:
            target_label = "小红书" if target == "xhs" else "今日头条"
            stage = f"上传{target_label}草稿"
            attempt = _next_attempt(post.id)
            exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
            try:
                _emit_progress_event(
                    "auto",
                    stage,
                    "in_progress",
                    f"post_id={post.id} index={idx}/{total_posts}",
                )
                runner = run_save_draft_sync if target == "xhs" else run_save_toutiao_draft_sync
                exec_rec = runner(
                    post,
                    assets=resolved_assets,
                    dry_run=dry_run,
                    login_hold=login_hold,
                    wait_timeout_ms=wait_timeout * 1000,
                    execution=exec_rec,
                    headless=_headless_option_value(headless),
                    progress_callback=_upload_progress(post.id),
                )
            except Exception as exc:
                message = f"{target} upload exception post_id={post.id}: {exc}"
                target_errors.append(message)
                run_errors.append(message)
                _emit_progress_event("auto", stage, "failed", f"post_id={post.id} error={exc}")
                typer.echo(_format_stage_error(stage, message))
                continue

            typer.echo(f"post_id={post.id} platform={target} result: {exec_rec.result}")
            for s in exec_rec.steps:
                detail = f" | {s.detail}" if s.detail else ""
                typer.echo(f"- {s.name}: {s.status}{detail}")
            if exec_rec.error:
                message = f"{target} upload failed post_id={post.id}: {exec_rec.error}"
                target_errors.append(message)
                run_errors.append(message)
                typer.echo(_format_stage_error(stage, exec_rec.error))
                _emit_progress_event("auto", stage, "failed", f"post_id={post.id} error={exec_rec.error}")
            if exec_rec.result == "saved_draft":
                saved_targets.append(target)
                post.updated_at = now_iso()
                _mark_post_uploaded(post, exec_rec.result)
                if target == "xhs":
                    post.platform["xhs_draft"] = {
                        "title": post.title,
                        "saved_at": post.updated_at,
                        "execution_id": exec_rec.id,
                    }
                else:
                    article = adapt_post_for_toutiao(post)
                    post.platform["toutiao_draft"] = {
                        "title": article.title,
                        "saved_at": post.updated_at,
                        "execution_id": exec_rec.id,
                    }
                _emit_progress_event("auto", stage, "success", f"post_id={post.id}")
            elif not dry_run and not exec_rec.error:
                message = f"{target} draft was not saved for post_id={post.id}: result={exec_rec.result}"
                target_errors.append(message)
                run_errors.append(message)
                _emit_progress_event("auto", stage, exec_rec.result or "failed", f"post_id={post.id}")

        if saved_targets:
            post.status = PostStatus.saved_draft
        elif target_errors and not dry_run:
            post.status = PostStatus.failed
        post.updated_at = now_iso()
        save_post(post)

        if dry_run or len(saved_targets) == len(target_platforms):
            if not dry_run:
                uploaded += 1
        else:
            upload_failed += 1

    failed_total = max(
        generation_failed_count + skipped_invalid + upload_failed,
        0 if dry_run else requested_count - uploaded,
    )
    _record_generation_run(
        command="auto",
        title=title_norm,
        prompt=prompt_norm,
        requested_count=requested_count,
        generated_count=len(posts),
        uploaded_count=uploaded,
        failed_count=failed_total,
        started_at=started_at,
        post_ids=[p.id for p in posts],
        errors=run_errors,
    )
    typer.echo(
        f"summary: generated={len(posts)} uploaded={uploaded} failed={failed_total} "
        f"skipped_invalid={skipped_invalid} upload_failed={upload_failed} requested={requested_count}"
    )
    partial_success = (
        allow_partial
        and uploaded > 0
        and uploaded + skipped_invalid == len(posts)
        and upload_failed == 0
    )
    completed = dry_run or failed_total == 0 or partial_success
    _emit_progress_event(
        "auto",
        "完成",
        "success" if completed else "failed",
        f"generated={len(posts)} uploaded={uploaded} failed={failed_total}",
    )
    if not completed:
        raise typer.Exit(code=1)


@app.command("check-sources")
def check_sources(
    collection: str = typer.Option(
        "all",
        "--collection",
        help="source collection to check: all, daily_news, or ai_digest",
    ),
    prompt: str = typer.Option(
        "technology",
        "--keywords",
        "--prompt",
        help="每日新闻信源检查使用的检索关键词（--prompt 保留为兼容别名）",
    ),
    max_age_days: int = typer.Option(
        3,
        "--max-age-days",
        min=1,
        max=14,
        help="freshness window for the AI digest source check",
    ),
):
    """Run read-only source checks and refresh local health snapshots; no LLM, image, post, or upload work."""
    collection_norm = (collection or "all").strip().lower()
    if collection_norm not in {"all", "daily_news", "ai_digest"}:
        raise typer.BadParameter("collection must be one of: all, daily_news, ai_digest")

    root = Path("data") / "source_health"
    report: dict[str, dict] = {}
    warnings: list[str] = []

    if collection_norm in {"all", "daily_news"}:
        _emit_progress_event("check-sources", "检查每日新闻信源", "in_progress")
        try:
            candidates, meta = fetch_daily_news_candidates(
                (prompt or "technology").strip() or "technology",
                max_records=20,
                search_days=max_age_days,
                source_health_path=root / "daily_news.json",
                persist_source_health=True,
            )
            health = meta.get("source_health") if isinstance(meta, dict) else {}
            report["daily_news"] = {
                "candidates": len(candidates),
                "attempts": len((health or {}).get("attempts") or []),
                "snapshot": (health or {}).get("snapshot_path") or str(root / "daily_news.json"),
            }
            _emit_progress_event("check-sources", "检查每日新闻信源", "success", f"candidates={len(candidates)}")
        except Exception as exc:
            warnings.append(f"daily_news: {exc}")
            report["daily_news"] = {"error": str(exc), "snapshot": str(root / "daily_news.json")}
            _emit_progress_event("check-sources", "检查每日新闻信源", "warning", f"error={exc}")

    if collection_norm in {"all", "ai_digest"}:
        _emit_progress_event("check-sources", "检查每日AI讯息信源", "in_progress")
        try:
            updates, meta = collect_ai_digest_updates(
                target_count=1,
                min_official_count=1,
                allow_social_backfill=False,
                max_age_days=max_age_days,
                source_health_path=root / "ai_digest.json",
                persist_source_health=True,
            )
            health = meta.get("source_health") if isinstance(meta, dict) else {}
            report["ai_digest"] = {
                "candidates": len(updates),
                "attempts": len((health or {}).get("attempts") or []),
                "snapshot": (health or {}).get("snapshot_path") or str(root / "ai_digest.json"),
            }
            _emit_progress_event("check-sources", "检查每日AI讯息信源", "success", f"candidates={len(updates)}")
        except Exception as exc:
            warnings.append(f"ai_digest: {exc}")
            report["ai_digest"] = {"error": str(exc), "snapshot": str(root / "ai_digest.json")}
            _emit_progress_event("check-sources", "检查每日AI讯息信源", "warning", f"error={exc}")

    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if warnings:
        typer.echo(f"warnings: {warnings}")
        _emit_progress_event("check-sources", "检查完成", "warning", f"warnings={len(warnings)}")
    else:
        _emit_progress_event("check-sources", "检查完成", "success")
    typer.echo("检查完成：已更新本地信源健康快照。")


@app.command("aliyun-quota")
def aliyun_quota(
    model: Optional[list[str]] = typer.Option(
        None,
        "--model",
        help="Filter specific Bailian models; may be repeated. Defaults to configured Aliyun LLM/image models.",
    ),
    all_free: bool = typer.Option(
        False,
        "--all-free",
        help="collect every model with an Aliyun free-tier quota returned by the official console API",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="read the Bailian console without a visible window; requires a logged-in workspace profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to keep the visible browser open for Aliyun console login"),
    wait_timeout: int = typer.Option(120, help="seconds to wait for the Bailian quota table"),
    open_only: bool = typer.Option(False, "--open-only", help="only open the official Bailian free-quota page"),
    save_raw: bool = typer.Option(False, "--save-raw", help="save parsed records and raw console text under data/quota"),
    visible_only: bool = typer.Option(
        False,
        "--visible-only",
        help="strict mode: parse only visible page text and do not use captured console API payloads",
    ),
    snapshot_dir: Optional[Path] = typer.Option(None, "--snapshot-dir", help="directory for --save-raw snapshots"),
):
    """Read Aliyun Bailian free quota from the official console page."""
    typer.echo("Aliyun Bailian quota")
    typer.echo(f"official-free-quota-url: {BAILIAN_FREE_QUOTA_URL}")
    typer.echo(
        "note: DashScope does not expose a stable public API-key balance endpoint in the project docs; "
        "this command reads the official Bailian console page and does not call billable models."
    )

    if open_only:
        webbrowser.open(BAILIAN_FREE_QUOTA_URL)
        typer.echo("opened official Bailian free-quota page")
        return

    if headless and login_hold > 0:
        typer.echo(
            "warn: --headless requires an already logged-in Aliyun console profile; "
            "login-hold cannot display QR/captcha windows"
        )

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("aliyun-quota", "同步阿里云额度", "in_progress", f"all_free={all_free}")
    result = run_collect_aliyun_quota_sync(
        models=None if all_free else [m.strip() for m in (model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )

    typer.echo(format_aliyun_quota_records(result.get("records", [])))
    if save_raw:
        snapshot_path = _save_quota_snapshot("aliyun", result, snapshot_dir=snapshot_dir)
        typer.echo(f"snapshot: {snapshot_path}")
    if result.get("usage_url"):
        typer.echo(f"usage-statistics-url: {result['usage_url']}")
        typer.echo("usage-statistics-note: Aliyun usage statistics may be delayed; use it as a reference, not a real-time balance.")
    if result.get("errors"):
        typer.echo(f"errors: {result['errors']}")
        _emit_progress_event("aliyun-quota", "同步阿里云额度", "failed", f"errors={len(result['errors'])}")
        raise typer.Exit(code=1)
    _emit_progress_event("aliyun-quota", "同步阿里云额度", "success", f"records={len(result.get('records', []))}")


@app.command("volcengine-quota")
def volcengine_quota(
    model: Optional[list[str]] = typer.Option(
        None,
        "--model",
        help="Filter specific Ark models; may be repeated. Defaults to configured Volcengine LLM/image models.",
    ),
    all_free: bool = typer.Option(
        False,
        "--all-free",
        help="collect every model with a Volcengine Ark free inference resource pack returned by the console API",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="read the Ark console without a visible window; requires a logged-in workspace profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to keep the visible browser open for Volcengine console login"),
    wait_timeout: int = typer.Option(120, help="seconds to wait for the Ark usage/free-quota table"),
    open_only: bool = typer.Option(False, "--open-only", help="only open the official Ark usage page"),
    save_raw: bool = typer.Option(False, "--save-raw", help="save parsed records and raw console text under data/quota"),
    visible_only: bool = typer.Option(
        False,
        "--visible-only",
        help="strict mode: parse only visible page text and do not use captured console API payloads",
    ),
    snapshot_dir: Optional[Path] = typer.Option(None, "--snapshot-dir", help="directory for --save-raw snapshots"),
):
    """Read Volcengine Ark quota/usage from the official console page."""
    typer.echo("Volcengine Ark quota")
    typer.echo(f"official-usage-url: {VOLCENGINE_ARK_USAGE_URL}")
    typer.echo(f"official-free-quota-doc-url: {VOLCENGINE_ARK_FREE_QUOTA_DOC_URL}")
    typer.echo(f"official-model-list-doc-url: {VOLCENGINE_ARK_MODEL_LIST_DOC_URL}")
    typer.echo(
        "note: Ark model APIs list models and run inference, but remaining free quota is shown in the "
        "Volcengine console; this command reads the official console page and does not call billable models."
    )

    if open_only:
        webbrowser.open(VOLCENGINE_ARK_USAGE_URL)
        typer.echo("opened official Volcengine Ark usage page")
        return

    if headless and login_hold > 0:
        typer.echo(
            "warn: --headless requires an already logged-in Volcengine console profile; "
            "login-hold cannot display QR/captcha windows"
        )

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("volcengine-quota", "同步火山引擎额度", "in_progress", f"all_free={all_free}")
    result = run_collect_volcengine_quota_sync(
        models=None if all_free else [m.strip() for m in (model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )

    typer.echo(format_volcengine_quota_records(result.get("records", [])))
    if save_raw:
        snapshot_path = _save_quota_snapshot("volcengine", result, snapshot_dir=snapshot_dir)
        typer.echo(f"snapshot: {snapshot_path}")
    typer.echo(f"free-quota-doc-url: {result.get('free_quota_doc_url') or VOLCENGINE_ARK_FREE_QUOTA_DOC_URL}")
    typer.echo(f"model-list-doc-url: {result.get('model_list_doc_url') or VOLCENGINE_ARK_MODEL_LIST_DOC_URL}")
    if result.get("errors"):
        typer.echo(f"errors: {result['errors']}")
        _emit_progress_event("volcengine-quota", "同步火山引擎额度", "failed", f"errors={len(result['errors'])}")
        raise typer.Exit(code=1)
    _emit_progress_event("volcengine-quota", "同步火山引擎额度", "success", f"records={len(result.get('records', []))}")


@app.command("siliconflow-quota")
def siliconflow_quota(
    model: Optional[list[str]] = typer.Option(
        None,
        "--model",
        help="Filter specific SiliconFlow models; may be repeated. Defaults to configured SiliconFlow LLM/image models.",
    ),
    all_free: bool = typer.Option(
        False,
        "--all-free",
        help="collect every model returned by the official SiliconFlow model-list API",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="read the SiliconFlow cloud console without a visible window; requires a logged-in workspace profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to keep the visible browser open for SiliconFlow console login"),
    wait_timeout: int = typer.Option(120, help="seconds to wait for the SiliconFlow model/quota page"),
    open_only: bool = typer.Option(False, "--open-only", help="only open the official SiliconFlow model page"),
    save_raw: bool = typer.Option(False, "--save-raw", help="save parsed records and raw console text under data/quota"),
    visible_only: bool = typer.Option(
        False,
        "--visible-only",
        help="strict mode: parse only visible page text and do not use the model-list API",
    ),
    snapshot_dir: Optional[Path] = typer.Option(None, "--snapshot-dir", help="directory for --save-raw snapshots"),
):
    """Read SiliconFlow model info and free-quota hints."""
    typer.echo("SiliconFlow (硅基流动) quota")
    typer.echo(f"official-model-api-url: {SILICONFLOW_MODELS_URL}")
    typer.echo(f"official-console-url: {SILICONFLOW_CONSOLE_MODELS_URL}")
    typer.echo(f"official-api-doc-url: {SILICONFLOW_API_DOC_URL}")
    typer.echo(
        "note: model availability comes from the official model-list API (needs SILICONFLOW_API_KEY); "
        "remaining/free quota is shown in the SiliconFlow cloud console page. This command does not call billable models."
    )

    if open_only:
        webbrowser.open(SILICONFLOW_CONSOLE_MODELS_URL)
        typer.echo("opened official SiliconFlow model page")
        return

    if headless and login_hold > 0:
        typer.echo(
            "warn: --headless requires an already logged-in SiliconFlow console profile; "
            "login-hold cannot display QR/captcha windows"
        )

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("siliconflow-quota", "同步硅基流动额度", "in_progress", f"all_free={all_free}")
    result = run_collect_siliconflow_quota_sync(
        models=None if all_free else [m.strip() for m in (model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )

    typer.echo(format_siliconflow_quota_records(result.get("records", [])))
    if save_raw:
        snapshot_path = _save_quota_snapshot("siliconflow", result, snapshot_dir=snapshot_dir)
        typer.echo(f"snapshot: {snapshot_path}")
    if result.get("errors"):
        typer.echo(f"errors: {result['errors']}")
        _emit_progress_event("siliconflow-quota", "同步硅基流动额度", "failed", f"errors={len(result['errors'])}")
        raise typer.Exit(code=1)
    _emit_progress_event("siliconflow-quota", "同步硅基流动额度", "success", f"records={len(result.get('records', []))}")


@app.command("sync-quotas")
def sync_quotas(
    aliyun_model: Optional[list[str]] = typer.Option(
        None,
        "--aliyun-model",
        help="Filter Aliyun Bailian models; may be repeated. Defaults to configured Aliyun quota models.",
    ),
    volcengine_model: Optional[list[str]] = typer.Option(
        None,
        "--volcengine-model",
        help="Filter Volcengine Ark models; may be repeated. Defaults to configured Ark quota models.",
    ),
    siliconflow_model: Optional[list[str]] = typer.Option(
        None,
        "--siliconflow-model",
        help="Filter SiliconFlow models; may be repeated. Defaults to configured SiliconFlow quota models.",
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="read supplier consoles without visible windows; requires logged-in workspace profiles",
    ),
    login_hold: int = typer.Option(0, help="seconds to keep visible browsers open for supplier-console login"),
    wait_timeout: int = typer.Option(120, help="seconds to wait for supplier quota pages"),
    visible_only: bool = typer.Option(
        False,
        "--visible-only",
        help="strict mode: parse only visible page text and do not use captured console API payloads",
    ),
    all_free: bool = typer.Option(
        True,
        "--all-free/--target-only",
        help="collect all models with remaining/free quota by default; use --target-only to query the requested model list",
    ),
    snapshot_dir: Optional[Path] = typer.Option(None, "--snapshot-dir", help="directory for saved quota snapshots"),
):
    """Synchronize Aliyun, Volcengine, and SiliconFlow quota snapshots for the GUI dashboard."""
    warnings: list[str] = []

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("sync-quotas", "同步阿里云额度", "in_progress", f"all_free={all_free}")
    typer.echo("Aliyun Bailian quota")
    aliyun_result = run_collect_aliyun_quota_sync(
        models=None if all_free else [m.strip() for m in (aliyun_model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )
    typer.echo(format_aliyun_quota_records(aliyun_result.get("records", [])))
    aliyun_snapshot = _save_quota_snapshot("aliyun", aliyun_result, snapshot_dir=snapshot_dir)
    typer.echo(f"snapshot: {aliyun_snapshot}")
    if aliyun_result.get("errors"):
        warnings.append(f"aliyun: {aliyun_result['errors']}")
        _emit_progress_event("sync-quotas", "同步阿里云额度", "warning", f"errors={len(aliyun_result['errors'])}")
    else:
        _emit_progress_event("sync-quotas", "同步阿里云额度", "success", f"records={len(aliyun_result.get('records', []))}")

    typer.echo("")
    _emit_progress_event("sync-quotas", "同步火山引擎额度", "in_progress", f"all_free={all_free}")
    typer.echo("Volcengine Ark quota")
    volcengine_result = run_collect_volcengine_quota_sync(
        models=None if all_free else [m.strip() for m in (volcengine_model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )
    typer.echo(format_volcengine_quota_records(volcengine_result.get("records", [])))
    volcengine_snapshot = _save_quota_snapshot("volcengine", volcengine_result, snapshot_dir=snapshot_dir)
    typer.echo(f"snapshot: {volcengine_snapshot}")
    if volcengine_result.get("errors"):
        warnings.append(f"volcengine: {volcengine_result['errors']}")
        _emit_progress_event("sync-quotas", "同步火山引擎额度", "warning", f"errors={len(volcengine_result['errors'])}")
    else:
        _emit_progress_event("sync-quotas", "同步火山引擎额度", "success", f"records={len(volcengine_result.get('records', []))}")

    typer.echo("")
    _emit_progress_event("sync-quotas", "同步硅基流动额度", "in_progress", f"all_free={all_free}")
    typer.echo("SiliconFlow (硅基流动) quota")
    siliconflow_result = run_collect_siliconflow_quota_sync(
        models=None if all_free else [m.strip() for m in (siliconflow_model or []) if m and m.strip()] or None,
        all_free=all_free,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=True if headless else None,
        visible_only=visible_only,
        progress_callback=_progress,
    )
    typer.echo(format_siliconflow_quota_records(siliconflow_result.get("records", [])))
    siliconflow_snapshot = _save_quota_snapshot("siliconflow", siliconflow_result, snapshot_dir=snapshot_dir)
    typer.echo(f"snapshot: {siliconflow_snapshot}")
    if siliconflow_result.get("errors"):
        warnings.append(f"siliconflow: {siliconflow_result['errors']}")
        _emit_progress_event("sync-quotas", "同步硅基流动额度", "warning", f"errors={len(siliconflow_result['errors'])}")
    else:
        _emit_progress_event("sync-quotas", "同步硅基流动额度", "success", f"records={len(siliconflow_result.get('records', []))}")

    if warnings:
        typer.echo(f"warnings: {warnings}")
        _emit_progress_event("sync-quotas", "完成", "warning", f"warnings={len(warnings)}")
    else:
        _emit_progress_event("sync-quotas", "完成", "success")


@app.command("update-metrics")
def update_metrics(
    limit: int = typer.Option(0, help="同步 N 条已发布笔记；0 表示按页面显示总数全量同步"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(
        300,
        help="advanced per-step UI wait seconds; not a full-sync deadline",
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="save partial metrics even when the page reports more published notes than were collected",
    ),
):
    """同步已发布稿件的点赞、评论、收藏到本地表格。"""
    _warn_headless_login_hold(headless, login_hold)

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("update-metrics", "同步已发布数据", "in_progress", f"limit={limit or 'all'}")
    result = run_collect_published_metrics_sync(
        limit=limit,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=_headless_option_value(headless),
        progress_callback=_progress,
    )
    metrics = [PublishedMetric.model_validate(item) for item in result.get("items", [])]
    target_total = int(result.get("target_total") or 0)
    required_total = int(result.get("required_total") or (target_total if target_total else len(metrics)))
    missing_count = int(result.get("missing_count") or max(0, required_total - len(metrics)))
    complete = bool(result.get("complete", True))
    typer.echo(
        f"metrics-collection: fetched={len(metrics)} "
        f"target={target_total or 'unknown'} required={required_total} "
        f"missing={missing_count} complete={complete}"
    )
    if not metrics:
        _emit_progress_event("update-metrics", "同步已发布数据", "failed", "fetched=0")
        typer.echo("error: no published metrics collected; refusing to overwrite latest analytics.")
        if result.get("event_path"):
            typer.echo(f"event: {result['event_path']}")
        if result.get("errors"):
            typer.echo(f"errors: {result['errors']}")
        raise typer.Exit(code=1)
    if metrics and not complete and not allow_partial:
        _emit_progress_event(
            "update-metrics",
            "同步已发布数据",
            "failed",
            f"fetched={len(metrics)} target={target_total or 'unknown'} missing={missing_count}",
        )
        typer.echo(
            "error: incomplete published metrics; refusing to overwrite latest analytics "
            f"(fetched={len(metrics)} target={target_total or 'unknown'} missing={missing_count}). "
            "Rerun after the page fully loads, increase XHS_METRICS_MAX_SCROLLS / XHS_METRICS_STAGNANT_ROUNDS, "
            "or pass --allow-partial for a deliberate partial snapshot."
        )
        if result.get("event_path"):
            typer.echo(f"event: {result['event_path']}")
        raise typer.Exit(code=1)
    if metrics and not complete and allow_partial:
        _emit_progress_event(
            "update-metrics",
            "同步已发布数据",
            "warning",
            f"fetched={len(metrics)} target={target_total or 'unknown'} missing={missing_count}",
        )
        typer.echo(
            "warning: saving partial published metrics "
            f"(fetched={len(metrics)} target={target_total or 'unknown'} missing={missing_count})"
        )
    saved = save_published_metrics_snapshot(metrics)
    synced = sync_published_metrics_to_posts(metrics)
    typer.echo(f"metrics: fetched={len(metrics)} saved={saved['count']}")
    typer.echo(
        f"posts-synced: matched={synced.get('matched', 0)} "
        f"unmatched={len(synced.get('unmatched', []))}"
    )
    typer.echo(f"metrics-jsonl: {saved['jsonl']}")
    typer.echo(f"metrics-csv: {saved['csv']}")
    typer.echo(f"metrics-latest-csv: {saved['latest_csv']}")
    for metric in metrics[:10]:
        typer.echo(
            f"- {metric.title or '(无标题)'} | 点赞={metric.likes} 评论={metric.comments} 收藏={metric.favorites}"
        )
    if result.get("event_path"):
        typer.echo(f"event: {result['event_path']}")
    if result.get("errors"):
        typer.echo(f"errors: {result['errors']}")
        if not metrics:
            raise typer.Exit(code=1)
    if complete:
        _emit_progress_event(
            "update-metrics",
            "同步已发布数据",
            "success",
            f"fetched={len(metrics)} target={target_total or 'unknown'}",
        )


@app.command("analyze-metrics")
def analyze_metrics(
    top_n: int = typer.Option(6, help="最多输出 N 个发布方向建议"),
    save: bool = typer.Option(False, "--save", help="保存分析结果到 data/analytics/published_metrics_analysis.md"),
):
    """分析本地已发布互动数据，给出后续新闻选题方向建议。"""
    report = analyze_published_metrics(top_n=top_n)
    text = render_published_metrics_analysis(report)
    typer.echo(text)
    if save:
        path = Path("data") / "analytics" / "published_metrics_analysis.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"\nanalysis-report: {path}")


@app.command("publish-drafts")
def publish_drafts(
    draft_type: str = typer.Option(
        "image", help="草稿类型：image/video/article", show_default=True
    ),
    date: str = typer.Option(
        "", "--date", help="按本地上传日期筛选（北京时间，YYYY-MM-DD）"
    ),
    post_id: Optional[list[str]] = typer.Option(
        None, "--post-id", help="指定本地 post_id；可重复传入"
    ),
    all_posts: bool = typer.Option(False, "--all", help="选择全部已上传且未发布的本地草稿"),
    limit: int = typer.Option(0, help="最多发布 N 条（0 表示不限制）"),
    dry_run: bool = typer.Option(False, help="只预览将发布的草稿，不点击发布"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    yes: bool = typer.Option(False, help="跳过确认"),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
):
    """从小红书创作者中心草稿箱打开并发布已选择的草稿。"""
    ids = [p.strip() for p in (post_id or []) if p and p.strip()]
    if not (date or ids or all_posts):
        typer.echo("请至少选择发布日期、post_id 或 --all")
        raise typer.Exit(code=1)

    _warn_headless_login_hold(headless, login_hold)
    _emit_progress_event("publish-drafts", "选择草稿", "in_progress", f"date={date or 'none'} ids={len(ids)} all={all_posts}")
    posts = _select_publishable_posts(
        date=date,
        post_ids=ids,
        include_all=all_posts,
        limit=limit,
    )
    if not posts:
        _emit_progress_event("publish-drafts", "选择草稿", "failed", "selected=0")
        typer.echo("未找到匹配的本地已上传草稿")
        raise typer.Exit(code=1)

    _emit_progress_event("publish-drafts", "选择草稿", "success", f"selected={len(posts)}")
    typer.echo(f"selected local drafts={len(posts)}")
    for post in posts:
        typer.echo(f"- {post.id} | {post.title} | uploaded_at={post.uploaded_at or ''}")

    if not dry_run and not yes:
        confirm = typer.confirm(f"将发布 {len(posts)} 条小红书草稿，确认继续？")
        if not confirm:
            typer.echo("已取消")
            return

    def _progress(message: str) -> None:
        typer.echo(message)

    _emit_progress_event("publish-drafts", "发布草稿", "in_progress", f"selected={len(posts)} dry_run={dry_run}")
    result = run_publish_drafts_sync(
        posts=posts,
        draft_type=draft_type,
        dry_run=dry_run,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        headless=_headless_option_value(headless),
        progress_callback=_progress,
    )

    typer.echo(f"type={result.get('draft_type', draft_type)} total={result.get('total', 0)}")
    for item in result.get("items", [])[:10]:
        title = item.get("title") or "(无标题)"
        saved_at = item.get("saved_at") or ""
        item_post_id = item.get("post_id") or ""
        typer.echo(f"- {item_post_id} {title} {saved_at}".strip())
    if result.get("event_path"):
        typer.echo(f"event: {result['event_path']}")
    if result.get("errors"):
        typer.echo(f"errors: {result['errors']}")
        _emit_progress_event("publish-drafts", "发布草稿", "warning", f"errors={len(result['errors'])}")
    else:
        _emit_progress_event("publish-drafts", "发布草稿", "success", f"published={result.get('published', 0)} total={len(posts)}")

    if dry_run:
        return

    _mark_posts_published(posts, result)
    typer.echo(
        f"published {result.get('published', 0)}/{len(posts)} drafts "
        f"({result.get('draft_type', draft_type)})"
    )
    if result.get("errors"):
        raise typer.Exit(code=1)


@app.command("delete-drafts")
def delete_drafts(
    draft_type: str = typer.Option(
        "image", help="草稿类型：image/video/article", show_default=True
    ),
    draft_location: str = typer.Option(
        "publish", help="草稿位置：publish/url", show_default=True
    ),
    draft_url: str = typer.Option(
        "", help="自定义草稿页面 URL（配合 --draft-location url）"
    ),
    all_types: bool = typer.Option(False, "--all", help="删除所有类型草稿"),
    title_contains: str = typer.Option(
        "",
        "--title-contains",
        help="只删除标题包含该文本的草稿",
    ),
    limit: int = typer.Option(0, help="最多删除 N 条（0 表示不限制）"),
    dry_run: bool = typer.Option(False, help="只预览将删除的草稿"),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    yes: bool = typer.Option(False, help="跳过确认"),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
):
    """删除草稿箱草稿（默认图文）。"""
    location = (draft_location or "publish").strip().lower()
    if location not in ("publish", "url"):
        typer.echo("draft_location 仅支持 publish 或 url")
        raise typer.Exit(code=1)
    if location == "url" and not draft_url:
        typer.echo("使用 --draft-location url 时必须提供 --draft-url")
        raise typer.Exit(code=1)

    types = [draft_type]
    if all_types:
        types = ["image", "video", "article"]

    _warn_headless_login_hold(headless, login_hold)

    def _print_preview(res: dict) -> None:
        typer.echo(f"type={res.get('draft_type')} total={res.get('total')}")
        for item in res.get("items", [])[:5]:
            title = item.get("title") or "(无标题)"
            saved_at = item.get("saved_at") or ""
            typer.echo(f"- {title} {saved_at}".rstrip())
        if res.get("total", 0) > 5:
            typer.echo("... (仅显示前 5 条)")
        if res.get("errors"):
            typer.echo(f"errors: {res['errors']}")

    previews: list[dict] = []
    for t in types:
        _emit_progress_event(
            "delete-drafts",
            "预览草稿",
            "in_progress",
            f"type={t} limit={limit or 'all'} title_contains={title_contains or 'all'}",
        )
        preview = run_delete_drafts_sync(
            draft_type=t,
            draft_location=location,
            draft_url=draft_url,
            title_contains=title_contains,
            limit=limit,
            dry_run=True,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
            headless=_headless_option_value(headless),
        )
        previews.append(preview)
        _emit_progress_event("delete-drafts", "预览草稿", "success", f"type={t} total={preview.get('total', 0)}")
        _print_preview(preview)

    preview_errors = [err for p in previews for err in (p.get("errors") or [])]
    if preview_errors:
        _emit_progress_event("delete-drafts", "预览草稿", "failed", f"errors={len(preview_errors)}")
        typer.echo("预览草稿失败，未执行删除")
        raise typer.Exit(code=1)

    if dry_run:
        return

    total = sum(p.get("total", 0) for p in previews)
    if total == 0:
        typer.echo("未找到草稿")
        return

    if not yes:
        confirm = typer.confirm(f"将删除草稿（最多 {limit or '全部'} 条），确认继续？")
        if not confirm:
            typer.echo("已取消")
            return

    for t in types:
        _emit_progress_event("delete-drafts", "删除草稿", "in_progress", f"type={t} limit={limit or 'all'}")
        res = run_delete_drafts_sync(
            draft_type=t,
            draft_location=location,
            draft_url=draft_url,
            title_contains=title_contains,
            limit=limit,
            dry_run=False,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
            headless=_headless_option_value(headless),
        )
        typer.echo(
            f"deleted {res.get('deleted', 0)}/{res.get('total', 0)} drafts "
            f"({res.get('draft_type')})"
        )
        if res.get("event_path"):
            typer.echo(f"event: {res['event_path']}")
        if res.get("errors"):
            typer.echo(f"errors: {res['errors']}")
            _emit_progress_event("delete-drafts", "删除草稿", "failed", f"type={t} errors={len(res['errors'])}")
        else:
            _emit_progress_event("delete-drafts", "删除草稿", "success", f"type={t} deleted={res.get('deleted', 0)} total={res.get('total', 0)}")


@app.command()
def retry(
    post_id: str = typer.Argument(..., help="post_id (data/posts/<id>/post.json)"),
    assets_glob: str = typer.Option(
        "",
        help="assets glob override; default uses the post's frozen asset manifest",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False, help="open page and capture evidence only; skip upload/fill/save"
    ),
    headless: bool = typer.Option(
        False,
        "--headless",
        help="run Chrome without a visible window; requires an already logged-in profile",
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
    force: bool = typer.Option(False, help="retry even if last run was not failed"),
):
    """Retry saving a draft (new attempt)."""
    executions = list_executions(post_id)
    if not executions:
        typer.echo("no previous executions found")
        raise typer.Exit(code=1)
    last = executions[-1]
    if last.result != "failed" and not force:
        typer.echo(f"last result is {last.result}; use --force to retry anyway")
        raise typer.Exit(code=1)

    run(
        post_id=post_id,
        assets_glob=assets_glob,
        dry_run=dry_run,
        headless=headless,
        login_hold=login_hold,
        wait_timeout=wait_timeout,
        force=True,
    )


if __name__ == "__main__":
    app(windows_expand_args=False)
