from __future__ import annotations

import glob
import sys
from pathlib import Path

import typer

from src.publish.playwright_steps import run_save_draft_sync
from src.storage.files import load_post

app = typer.Typer(help="Use Playwright to open the publish page and save a draft.")


def _ensure_utf8_output() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


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
    login_hold: int = typer.Option(
        0, help="seconds to wait for manual login before proceeding"
    ),
    login_only: bool = typer.Option(
        False, help="only wait for login/publish UI then exit"
    ),
    wait_timeout: int = typer.Option(
        300, help="seconds to wait for publish UI before failing"
    ),
):
    _ensure_utf8_output()
    try:
        post = load_post(post_id)
    except FileNotFoundError:
        typer.echo("post not found")
        raise typer.Exit(code=1)

    glob_pattern = assets_glob or f"data/posts/{post_id}/assets/*"
    asset_paths = [p for p in glob.glob(glob_pattern) if Path(p).is_file()]

    exec_rec = run_save_draft_sync(
        post,
        assets=asset_paths,
        dry_run=dry_run,
        login_hold=login_hold,
        login_only=login_only,
        wait_timeout_ms=wait_timeout * 1000,
    )
    typer.echo(f"result: {exec_rec.result}")
    for s in exec_rec.steps:
        detail = f" | {s.detail}" if s.detail else ""
        typer.echo(f"- {s.name}: {s.status}{detail}")
    if exec_rec.error:
        try:
            typer.echo(f"error: {exec_rec.error}")
        except UnicodeEncodeError:
            typer.echo(f"error: {exec_rec.error!r}")


if __name__ == "__main__":
    app(windows_expand_args=False)
