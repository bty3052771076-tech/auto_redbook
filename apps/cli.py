from __future__ import annotations

import glob
import json
import os
import sys
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

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
from src.analytics.post_sync import sync_published_metrics_to_posts
from src.analytics.published_metrics import analyze_published_metrics, render_published_metrics_analysis
from src.publish.playwright_steps import (
    run_collect_published_metrics_sync,
    run_delete_drafts_sync,
    run_publish_drafts_sync,
    run_save_draft_sync,
)
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
from src.workflow.create_post import (
    DEFAULT_EVALUATION_VIEWPOINT,
    PartialDailyNewsError,
    create_daily_ai_digest_posts,
    create_daily_news_posts,
    create_post_with_draft,
)

app = typer.Typer(help="小红书自动发帖（生成并保存草稿）CLI")
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
    glob_pattern = assets_glob or f"data/posts/{post.id}/assets/*"
    asset_paths = [p for p in glob.glob(glob_pattern) if Path(p).is_file()]
    if not asset_paths:
        asset_paths = [a.path for a in post.assets if Path(a.path).is_file()]
    return asset_paths


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
        llm_provider=_env_first("LLM_PROVIDER") or "auto",
        llm_models=_env_first("ALIYUN_LLM_MODELS", "ALIYUN_LLM_MODEL", "LLM_MODEL"),
        image_provider=_env_first("IMAGE_PROVIDER") or "local/auto",
        image_models=_env_first("ALIYUN_IMAGE_MODELS", "ALIYUN_IMAGE_MODEL"),
        news_provider=_env_first("NEWS_PROVIDER") or "auto",
        post_ids=post_ids,
        errors=errors,
        extra={
            "auto_image": _env_first("AUTO_IMAGE"),
            "news_candidates_file": _env_first("NEWS_CANDIDATES_FILE"),
            "news_materials_file": _env_first("NEWS_MATERIALS_FILE"),
            "single_news_material_file": _env_first("SINGLE_NEWS_MATERIAL_FILE"),
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
    prompt: str = typer.Option("", help="提示词/要点（可选）"),
    evaluation_viewpoint: str = typer.Option(
        DEFAULT_EVALUATION_VIEWPOINT,
        "--evaluation-viewpoint",
        help="每日新闻评价视角；默认无视角评价",
    ),
    lookback_days: Optional[int] = typer.Option(
        None,
        "--lookback-days",
        help="每日新闻/每日AI讯息候选回溯天数；留空则按 3/7/14 天自动扩展",
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
        help="每日新闻单条材料文件；提供后只生成 1 条，并忽略提示词/数量/回溯筛选",
        show_default=False,
    ),
    assets_glob: str = typer.Option("assets/pics/*", help="素材路径（glob）"),
    count: int = typer.Option(1, help="生成草稿数量（>=1）"),
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
):
    """生成草稿并落盘（post.json + revision）。"""
    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()
    news_materials_file_norm = (news_materials_file or "").strip()
    single_news_material_file_norm = (single_news_material_file or "").strip()
    if news_materials_file_norm and single_news_material_file_norm:
        typer.echo("error: --single-news-material-file and --news-materials-file are mutually exclusive")
        raise typer.Exit(code=1)
    if title_norm == "每日新闻" and single_news_material_file_norm:
        prompt_norm = ""
        lookback_days = None
        count = 1
    asset_paths = [p for p in glob.glob(assets_glob) if Path(p).is_file()]
    if not asset_paths:
        _emit_missing_assets_hint(title_norm)

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    requested_count = 1 if _is_daily_ai_digest_title(title_norm) else count
    if requested_count != count:
        typer.echo("note: 每日AI讯息会生成 1 条简报草稿；动态数量请用 AI_DIGEST_TARGET_ITEMS 控制。")

    started_at = now_iso()
    run_errors: list[str] = []
    generation_failed_count = 0
    generation_stage = _generation_stage_for_title(title_norm)
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
            generation_failed_count = max(0, exc.requested_count - len(posts), exc.failed_count)
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
        help="assets glob; default is data/posts/<post_id>/assets/*",
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
    force: bool = typer.Option(False, help="run even if not approved or validation fails"),
):
    """Save a draft via Playwright."""
    _emit_progress_event("run", "读取草稿", "in_progress", f"post_id={post_id}")
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)

    _emit_progress_event("run", "读取草稿", "success", f"post_id={post.id}")
    if post.status != PostStatus.approved and not force:
        typer.echo("post 未审批，请先运行 approve 或使用 --force")
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
    attempt = _next_attempt(post_id)
    exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
    _emit_progress_event("run", "上传草稿", "in_progress", f"post_id={post.id}")
    exec_rec = run_save_draft_sync(
        post,
        assets=asset_paths,
        dry_run=dry_run,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        execution=exec_rec,
        headless=_headless_option_value(headless),
        progress_callback=_upload_progress(post.id),
    )

    post.status = _apply_execution_status(post.status, exec_rec.result)
    _mark_post_uploaded(post, exec_rec.result)
    post.updated_at = now_iso()
    save_post(post)

    typer.echo(f"result: {exec_rec.result}")
    for s in exec_rec.steps:
        detail = f" | {s.detail}" if s.detail else ""
        typer.echo(f"- {s.name}: {s.status}{detail}")
    if exec_rec.error:
        typer.echo(_format_stage_error("上传", exec_rec.error))


    if exec_rec.error:
        _emit_progress_event("run", "上传草稿", "failed", f"post_id={post.id} error={exec_rec.error}")
    elif exec_rec.result == "saved_draft" or dry_run:
        _emit_progress_event("run", "上传草稿", "success", f"post_id={post.id} result={exec_rec.result}")
    else:
        _emit_progress_event("run", "上传草稿", exec_rec.result or "failed", f"post_id={post.id}")


@app.command()
def auto(
    title: str = typer.Option(..., help="初始标题/题目"),
    prompt: str = typer.Option("", help="提示词要点（可选）"),
    evaluation_viewpoint: str = typer.Option(
        DEFAULT_EVALUATION_VIEWPOINT,
        "--evaluation-viewpoint",
        help="每日新闻评价视角；默认无视角评价",
    ),
    lookback_days: Optional[int] = typer.Option(
        None,
        "--lookback-days",
        help="每日新闻/每日AI讯息候选回溯天数；留空则按 3/7/14 天自动扩展",
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
        help="每日新闻单条材料文件；提供后只生成 1 条，并忽略提示词/数量/回溯筛选",
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
    force: bool = typer.Option(False, help="run even if validation fails"),
):
    """Generate content then save draft in one command."""
    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()
    news_materials_file_norm = (news_materials_file or "").strip()
    single_news_material_file_norm = (single_news_material_file or "").strip()
    if news_materials_file_norm and single_news_material_file_norm:
        typer.echo("error: --single-news-material-file and --news-materials-file are mutually exclusive")
        raise typer.Exit(code=1)
    if title_norm == "每日新闻" and single_news_material_file_norm:
        prompt_norm = ""
        lookback_days = None
        count = 1
    asset_paths = [p for p in glob.glob(assets_glob) if Path(p).is_file()]
    if not asset_paths:
        _emit_missing_assets_hint(title_norm, dry_run=dry_run)

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    requested_count = 1 if _is_daily_ai_digest_title(title_norm) else count
    if requested_count != count:
        typer.echo("note: 每日AI讯息会生成 1 条简报草稿；动态数量请用 AI_DIGEST_TARGET_ITEMS 控制。")

    started_at = now_iso()
    run_errors: list[str] = []
    generation_failed_count = 0

    _warn_headless_login_hold(headless, login_hold)
    generation_stage = _generation_stage_for_title(title_norm)
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
            generation_failed_count = max(0, exc.requested_count - len(posts), exc.failed_count)
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

    _emit_progress_event("auto", generation_stage, "success", f"posts={len(posts)}")
    continue_on_invalid = requested_count > 1
    skipped_invalid = 0
    uploaded = 0
    upload_failed = 0

    total_posts = len(posts)
    for idx, post in enumerate(posts, start=1):
        _emit_progress_event("auto", "校验草稿", "in_progress", f"post_id={post.id} index={idx}/{total_posts}")
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

        post.status = PostStatus.approved
        post.updated_at = now_iso()
        save_post(post)
        _emit_progress_event("auto", "校验草稿", "success", f"post_id={post.id}")

        resolved_assets = _resolve_asset_paths(post, "")
        attempt = _next_attempt(post.id)
        exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
        try:
            _emit_progress_event("auto", "上传草稿", "in_progress", f"post_id={post.id} index={idx}/{total_posts}")
            exec_rec = run_save_draft_sync(
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
            # Defensive: run_save_draft_sync catches most exceptions, but avoid aborting the batch
            # if something leaks out.
            post.status = PostStatus.failed
            post.updated_at = now_iso()
            save_post(post)
            upload_failed += 1
            run_errors.append(f"upload exception post_id={post.id}: {exc}")
            _emit_progress_event("auto", "上传草稿", "failed", f"post_id={post.id} error={exc}")
            typer.echo(_format_stage_error("上传", f"post_id={post.id} upload exception: {exc}"))
            continue

        post.status = _apply_execution_status(post.status, exec_rec.result)
        _mark_post_uploaded(post, exec_rec.result)
        post.updated_at = now_iso()
        save_post(post)

        typer.echo(f"post_id={post.id} result: {exec_rec.result}")
        for s in exec_rec.steps:
            detail = f" | {s.detail}" if s.detail else ""
            typer.echo(f"- {s.name}: {s.status}{detail}")
        if exec_rec.error:
            typer.echo(_format_stage_error("上传", exec_rec.error))
            run_errors.append(f"upload failed post_id={post.id}: {exec_rec.error}")
            _emit_progress_event("auto", "上传草稿", "failed", f"post_id={post.id} error={exec_rec.error}")
        if exec_rec.result == "saved_draft":
            uploaded += 1
            _emit_progress_event("auto", "上传草稿", "success", f"post_id={post.id}")
        elif not dry_run:
            upload_failed += 1
            _emit_progress_event("auto", "上传草稿", exec_rec.result or "failed", f"post_id={post.id}")

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
    _emit_progress_event("auto", "完成", "success", f"generated={len(posts)} uploaded={uploaded} failed={failed_total}")


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
    """Synchronize Aliyun and Volcengine free-quota snapshots for the GUI dashboard."""
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
        _emit_progress_event("delete-drafts", "预览草稿", "in_progress", f"type={t} limit={limit or 'all'}")
        preview = run_delete_drafts_sync(
            draft_type=t,
            draft_location=location,
            draft_url=draft_url,
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
        help="assets glob; default is data/posts/<post_id>/assets/*",
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
