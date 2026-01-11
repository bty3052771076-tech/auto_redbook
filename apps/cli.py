from __future__ import annotations

import glob
import sys
from pathlib import Path

import typer

from src.publish.playwright_steps import run_delete_drafts_sync, run_save_draft_sync
from src.storage.files import list_executions, list_posts, load_post, save_post
from src.storage.models import Execution, PostStatus, PostType, now_iso
from src.validation import validate_post
from src.workflow.create_post import create_daily_news_posts, create_post_with_draft

app = typer.Typer(help="小红书自动发帖（生成并保存草稿）CLI")


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


def _emit_validation(result) -> None:
    for err in result.errors:
        typer.echo(f"error: {err}")
    for warn in result.warnings:
        typer.echo(f"warn: {warn}")


@app.command()
def create(
    title: str = typer.Option(..., help="初始标题/题目"),
    prompt: str = typer.Option("", help="提示词/要点（可选）"),
    assets_glob: str = typer.Option("assets/pics/*", help="素材路径（glob）"),
    count: int = typer.Option(1, help="生成草稿数量（>=1）"),
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
):
    """生成草稿并落盘（post.json + revision）。"""
    asset_paths = [p for p in glob.glob(assets_glob) if Path(p).is_file()]
    if not asset_paths:
        typer.echo("未找到素材文件，将自动查找配图（如已启用 AUTO_IMAGE 且配置了图片 API）。")

    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    if title_norm == "每日新闻":
        posts = create_daily_news_posts(
            prompt_hint=prompt_norm,
            asset_paths=asset_paths,
            copy_assets=not no_copy,
            count=count,
            auto_image=True,
        )
    else:
        posts = [
            create_post_with_draft(
                title_hint=title,
                prompt_hint=prompt,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                auto_image=True,
            )
            for _ in range(count)
        ]

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
        typer.echo(f"{p.id} | {p.type} | {p.status} | 标题:{p.title}")


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
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
    force: bool = typer.Option(False, help="run even if not approved or validation fails"),
):
    """Save a draft via Playwright."""
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post 不存在")
        raise typer.Exit(code=1)

    if post.status != PostStatus.approved and not force:
        typer.echo("post 未审批，请先运行 approve 或使用 --force")
        raise typer.Exit(code=1)

    result = validate_post(post)
    _emit_validation(result)
    if result.errors and not force:
        raise typer.Exit(code=1)

    asset_paths = _resolve_asset_paths(post, assets_glob)
    if post.type == PostType.image and not asset_paths and not dry_run:
        typer.echo("未找到素材文件，请检查 assets_glob 或 data/posts/<id>/assets")
        raise typer.Exit(code=1)

    attempt = _next_attempt(post_id)
    exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
    exec_rec = run_save_draft_sync(
        post,
        assets=asset_paths,
        dry_run=dry_run,
        login_hold=login_hold,
        wait_timeout_ms=wait_timeout * 1000,
        execution=exec_rec,
    )

    post.status = _apply_execution_status(post.status, exec_rec.result)
    post.updated_at = now_iso()
    save_post(post)

    typer.echo(f"result: {exec_rec.result}")
    for s in exec_rec.steps:
        detail = f" | {s.detail}" if s.detail else ""
        typer.echo(f"- {s.name}: {s.status}{detail}")
    if exec_rec.error:
        typer.echo(f"error: {exec_rec.error}")


@app.command()
def auto(
    title: str = typer.Option(..., help="初始标题/题目"),
    prompt: str = typer.Option("", help="提示词要点（可选）"),
    assets_glob: str = typer.Option("assets/pics/*", help="素材路径（glob）"),
    count: int = typer.Option(1, help="生成草稿数量（>=1）"),
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
    dry_run: bool = typer.Option(
        False, help="open page and capture evidence only; skip upload/fill/save"
    ),
    login_hold: int = typer.Option(0, help="seconds to wait for manual login"),
    wait_timeout: int = typer.Option(300, help="seconds to wait for publish UI"),
    force: bool = typer.Option(False, help="run even if validation fails"),
):
    """Generate content then save draft in one command."""
    asset_paths = [p for p in glob.glob(assets_glob) if Path(p).is_file()]
    if not asset_paths and not dry_run:
        typer.echo("未找到素材文件，将自动查找配图（如已启用 AUTO_IMAGE 且配置了图片 API）。")

    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()

    if count <= 0:
        typer.echo("count 必须 >= 1")
        raise typer.Exit(code=1)

    if title_norm == "每日新闻":
        posts = create_daily_news_posts(
            prompt_hint=prompt_norm,
            asset_paths=asset_paths,
            copy_assets=not no_copy,
            count=count,
            auto_image=True,
        )
    else:
        posts = [
            create_post_with_draft(
                title_hint=title,
                prompt_hint=prompt,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
                auto_image=True,
            )
            for _ in range(count)
        ]

    typer.echo(f"创建完成：posts={len(posts)}")
    for p in posts:
        typer.echo(f"- post_id={p.id} | 标题：{p.title}")

    for post in posts:
        result = validate_post(post)
        _emit_validation(result)
        if result.errors and not force:
            raise typer.Exit(code=1)

        post.status = PostStatus.approved
        post.updated_at = now_iso()
        save_post(post)

        resolved_assets = _resolve_asset_paths(post, "")
        attempt = _next_attempt(post.id)
        exec_rec = Execution(post_id=post.id, attempt=attempt, result="pending")
        exec_rec = run_save_draft_sync(
            post,
            assets=resolved_assets,
            dry_run=dry_run,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
            execution=exec_rec,
        )

        post.status = _apply_execution_status(post.status, exec_rec.result)
        post.updated_at = now_iso()
        save_post(post)

        typer.echo(f"post_id={post.id} result: {exec_rec.result}")
        for s in exec_rec.steps:
            detail = f" | {s.detail}" if s.detail else ""
            typer.echo(f"- {s.name}: {s.status}{detail}")
        if exec_rec.error:
            typer.echo(f"error: {exec_rec.error}")


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

    def _print_preview(res: dict) -> None:
        typer.echo(f"type={res.get('draft_type')} total={res.get('total')}")
        for item in res.get("items", [])[:5]:
            title = item.get("title") or "(无标题)"
            saved_at = item.get("saved_at") or ""
            typer.echo(f"- {title} {saved_at}".rstrip())
        if res.get("total", 0) > 5:
            typer.echo("... (仅显示前 5 条)")

    previews: list[dict] = []
    for t in types:
        preview = run_delete_drafts_sync(
            draft_type=t,
            draft_location=location,
            draft_url=draft_url,
            limit=limit,
            dry_run=True,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
        )
        previews.append(preview)
        _print_preview(preview)

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
        res = run_delete_drafts_sync(
            draft_type=t,
            draft_location=location,
            draft_url=draft_url,
            limit=limit,
            dry_run=False,
            login_hold=login_hold,
            wait_timeout_ms=wait_timeout * 1000,
        )
        typer.echo(
            f"deleted {res.get('deleted', 0)}/{res.get('total', 0)} drafts "
            f"({res.get('draft_type')})"
        )
        if res.get("event_path"):
            typer.echo(f"event: {res['event_path']}")
        if res.get("errors"):
            typer.echo(f"errors: {res['errors']}")


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
        login_hold=login_hold,
        wait_timeout=wait_timeout,
        force=True,
    )


if __name__ == "__main__":
    app(windows_expand_args=False)
