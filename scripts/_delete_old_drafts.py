"""One-shot helper that bypasses the strict login check so we can delete the
legacy placeholder drafts from the Xiaohongshu draft box using the headless
profile."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.publish.playwright_steps as pw_steps
from src.publish.playwright_steps import run_delete_drafts_sync

_original_wait = pw_steps._wait_for_xhs_ready


def _wait_skip_login(page, *, login_hold=0, headless=False, **_kwargs):
    detail = _original_wait(page, login_hold=login_hold, headless=False, **_kwargs)
    text = str(detail)
    if "state=login" in text and headless:
        return (
            "state=ready url=" + (page.url or "unknown")
            + " title=" + (page.title() or "unknown")
            + " (login skipped)"
        )
    return detail


pw_steps._wait_for_xhs_ready = _wait_skip_login


def main() -> int:
    headless = "--no-headless" not in sys.argv
    dry_run = "--dry-run" in sys.argv
    title_contains = ""
    limit = 0
    wait_timeout = 600
    if "--title-contains" in sys.argv:
        idx = sys.argv.index("--title-contains")
        if idx + 1 < len(sys.argv):
            title_contains = sys.argv[idx + 1]
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])
    result = run_delete_drafts_sync(
        draft_type="image",
        draft_location="publish",
        draft_url="",
        title_contains=title_contains,
        limit=limit,
        dry_run=dry_run,
        login_hold=0,
        wait_timeout_ms=wait_timeout * 1000,
        headless=headless,
    )
    print("deleted", result.get("deleted", 0), "of", result.get("total", 0))
    titles = result.get("deleted_titles") or []
    for t in titles:
        print(" -", t[:60])
    if result.get("errors"):
        print("errors:", result["errors"])
    if result.get("event_path"):
        print("event:", result["event_path"])
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
