from __future__ import annotations

import time
import uuid
from pathlib import Path

import typer
from playwright.sync_api import sync_playwright

from src.images.chatgpt_images import CHATGPT_IMAGES_URL, _find_prompt_box, _is_login_required, _resolve_profile
from src.storage.files import evidence_dir

app = typer.Typer(add_completion=False, help="探测 ChatGPT Images 页面（登录态/输入框/留证）")


@app.command()
def main(
    post_id: str = typer.Option(
        "chatgpt_images_inspect",
        help="用于 evidence 目录命名（data/posts/<post_id>/evidence/...)",
    ),
    hold: int = typer.Option(0, help="保持窗口打开 N 秒（便于人工观察）"),
):
    profile_dir, channel, args, exe = _resolve_profile()
    profile_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"inspect_{uuid.uuid4().hex}"
    ev = evidence_dir(post_id, run_id)
    ev.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = {"headless": False}
        if exe:
            launch_kwargs["executable_path"] = exe
        elif channel:
            launch_kwargs["channel"] = channel
        if args:
            launch_kwargs["args"] = args

        context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(CHATGPT_IMAGES_URL, wait_until="domcontentloaded")

            (ev / "page_url.txt").write_text(page.url, encoding="utf-8")
            (ev / "page_title.txt").write_text(page.title(), encoding="utf-8")
            (ev / "page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(ev / "page.png"), full_page=True)

            login_required = _is_login_required(page)
            prompt_box = _find_prompt_box(page)
            typer.echo(f"url={page.url}")
            typer.echo(f"login_required={login_required}")
            typer.echo(f"prompt_box_found={prompt_box is not None}")
            typer.echo(f"evidence={ev}")

            if hold > 0:
                time.sleep(hold)
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == "__main__":
    app()

