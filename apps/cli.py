from __future__ import annotations

import glob
import sys
from pathlib import Path

import typer

from src.publish.playwright_steps import run_save_draft_sync
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
    no_copy: bool = typer.Option(False, help="不复制素材到 data/posts/<id>/assets"),
):
    """生成草稿并落盘（post.json + revision）。"""
    asset_paths = [p for p in glob.glob(assets_glob) if Path(p).is_file()]
    if not asset_paths:
        typer.echo("未找到素材文件，请检查 assets_glob")
        raise typer.Exit(code=1)

    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()

    if title_norm == "每日新闻" and not prompt_norm:
        posts = create_daily_news_posts(
            prompt_hint="",
            asset_paths=asset_paths,
            copy_assets=not no_copy,
            count=3,
        )
        typer.echo(f"创建完成：posts={len(posts)}")
        for p in posts:
            typer.echo(f"- post_id={p.id} | 标题：{p.title}")
    else:
        post = create_post_with_draft(
            title_hint=title,
            prompt_hint=prompt,
            asset_paths=asset_paths,
            copy_assets=not no_copy,
        )
        typer.echo(f"创建完成：post_id={post.id}")
        typer.echo(f"标题：{post.title}")
        typer.echo(f"正文（前60字）：{post.body[:60]}{'...' if len(post.body) > 60 else ''}")


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
        typer.echo("未找到素材文件，请检查 assets_glob")
        raise typer.Exit(code=1)

    title_norm = (title or "").strip()
    prompt_norm = (prompt or "").strip()

    if title_norm == "每日新闻" and not prompt_norm:
        posts = create_daily_news_posts(
            prompt_hint="",
            asset_paths=asset_paths,
            copy_assets=not no_copy,
            count=3,
        )
    else:
        posts = [
            create_post_with_draft(
                title_hint=title,
                prompt_hint=prompt,
                asset_paths=asset_paths,
                copy_assets=not no_copy,
            )
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
