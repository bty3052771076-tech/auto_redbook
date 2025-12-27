from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.storage.files import evidence_dir, save_execution
from src.storage.models import Execution, Post, StepResult

TARGET_URL = "https://creator.xiaohongshu.com/publish/publish?target=image"
WAIT_TEXTS = [
    "\u4e0a\u4f20\u56fe\u6587",
    "\u53d1\u5e03\u56fe\u6587",
    "\u53d1\u5e03\u7b14\u8bb0",
    "\u53d1\u5e03",
    "\u56fe\u6587",
]
TITLE_HINTS = ["\u586b\u5199\u6807\u9898", "\u6807\u9898", "\u66f4\u591a\u8d5e"]
BODY_HINTS = ["\u8f93\u5165\u6b63\u6587", "\u6b63\u6587", "\u586b\u5199\u6b63\u6587"]
DRAFT_TEXTS = [
    "\u6682\u5b58\u79bb\u5f00",
    "\u6682\u5b58\u5e76\u79bb\u5f00",
    "\u6682\u5b58",
    "\u4fdd\u5b58\u8349\u7a3f",
    "\u5b58\u8349\u7a3f",
    "\u5b58\u4e3a\u8349\u7a3f",
]
PROCESSING_TEXTS = ["\u6b63\u5728\u5904\u7406\u4e2d", "\u5904\u7406\u4e2d", "\u4e0a\u4f20\u4e2d"]
DRAFT_TAB_TEXTS = ["\u56fe\u6587\u7b14\u8bb0", "\u56fe\u6587"]
COVER_HINT_TEXTS = ["\u83b7\u53d6\u5c01\u9762\u5efa\u8bae", "\u5c01\u9762\u5efa\u8bae", "\u9009\u62e9\u5c01\u9762", "\u8bbe\u7f6e\u5c01\u9762"]
COVER_CONFIRM_TEXTS = ["\u5b8c\u6210", "\u786e\u5b9a", "\u4fdd\u5b58", "\u4f7f\u7528", "\u786e\u8ba4"]
COVER_IMAGE_SELECTORS = [
    ".el-dialog__body img",
    ".cover-dialog img",
    ".cover-list img",
    ".cover-item img",
    "div[role='dialog'] img",
]
UPLOAD_INPUT_SELECTORS = [
    "input.upload-input[type='file']",
    "input[type='file'][accept*='.jpg']",
    "input[type='file'][accept*='.jpeg']",
    "input[type='file'][accept*='.png']",
    "input[type='file'][accept*='.webp']",
    "input[type='file'][accept*='image']",
    "input[type='file'][multiple]",
    "input[type='file']",
]
UPLOAD_BUTTON_SELECTORS = [
    "button.upload-button",
    "button:has-text('\u4e0a\u4f20\u56fe\u7247')",
]
SAVE_OK_TEXTS = [
    "\u4fdd\u5b58\u6210\u529f",
    "\u5df2\u4fdd\u5b58",
    "\u8349\u7a3f\u5df2\u4fdd\u5b58",
    "\u5df2\u5b58\u8349\u7a3f",
    "\u5df2\u6682\u5b58",
]
DRAFT_BOX_TEXT = "\u8349\u7a3f\u7bb1"
DRAFT_ITEM_SELECTOR = ".draft-item"
WAIT_TIMEOUT_MS = 300000
UPLOAD_COUNT_PATTERN = re.compile(r"(\\d+)\\s*/\\s*18")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_profile_config() -> tuple[Path, Optional[str], list[str]]:
    user_data_dir = os.getenv("XHS_CHROME_USER_DATA_DIR")
    profile_dir = (
        Path(user_data_dir)
        if user_data_dir
        else _repo_root() / "data" / "browser" / "chrome-profile"
    )
    channel = os.getenv("XHS_BROWSER_CHANNEL")
    if not channel and not user_data_dir:
        channel = "chrome"
    profile_name = os.getenv("XHS_CHROME_PROFILE")
    args: list[str] = []
    if profile_name:
        args.append(f"--profile-directory={profile_name}")
    return profile_dir, channel, args


def _wait_for_any_text(page, texts: List[str], timeout_ms: int) -> str:
    per = max(1000, timeout_ms // max(1, len(texts)))
    for text in texts:
        try:
            page.get_by_text(text, exact=False).first.wait_for(timeout=per)
            return text
        except PlaywrightTimeoutError:
            continue
    raise PlaywrightTimeoutError(f"timeout waiting for any of: {texts}")


def _first_visible(locator):
    if locator.count() == 0:
        return None
    for i in range(locator.count()):
        item = locator.nth(i)
        if item.is_visible():
            return item
    return locator.first


def _wait_for_any_locator(page, selectors: List[str], timeout_ms: int) -> str:
    per = max(1000, timeout_ms // max(1, len(selectors)))
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=per)
            return sel
        except PlaywrightTimeoutError:
            continue
    raise PlaywrightTimeoutError(f"timeout waiting for any selector: {selectors}")


def _first_matching_locator(ctx, selectors: List[str]):
    for sel in selectors:
        loc = ctx.locator(sel)
        if loc.count() > 0:
            return loc
    return None


def _fill_if_found(locator, value: str) -> bool:
    if locator is None or locator.count() == 0:
        return False
    target = _first_visible(locator)
    if target is None:
        return False
    if target.get_attribute("type") == "file":
        return False
    try:
        target.scroll_into_view_if_needed()
    except Exception:
        pass
    target.click()
    target.fill(value)
    try:
        target.press("Tab")
    except Exception:
        pass
    if _matches_value(_read_target_value(target), value):
        return True
    target.click()
    try:
        target.fill("")
        target.type(value, delay=20)
        target.press("Tab")
    except Exception:
        pass
    return _matches_value(_read_target_value(target), value)


def _fill_with_selectors(ctx, selectors: List[str], value: str) -> bool:
    for sel in selectors:
        if _fill_if_found(ctx.locator(sel), value):
            return True
    return False


def _try_upload_with_button(page, assets: list[str]) -> tuple[bool, str]:
    for sel in UPLOAD_BUTTON_SELECTORS:
        btn = page.locator(sel)
        if btn.count() == 0:
            btn = page.get_by_role("button", name="\u4e0a\u4f20\u56fe\u7247")
        if btn.count() == 0:
            continue
        try:
            with page.expect_file_chooser(timeout=3000) as fc_info:
                if not _click_first(btn):
                    continue
            fc_info.value.set_files(assets)
            return True, f"button:{sel}"
        except Exception:
            continue
    return False, "button:none"


def _try_upload_with_input(page, assets: list[str]) -> tuple[bool, str]:
    file_input = _first_matching_locator(page, UPLOAD_INPUT_SELECTORS)
    if file_input is None:
        return False, "input:none"
    file_input.first.set_input_files(assets)
    return True, "input"


def _maybe_select_cover(page) -> tuple[bool, str]:
    opened = False
    for text in COVER_HINT_TEXTS:
        candidates = [
            page.get_by_role("button", name=text),
            page.locator(f"button:has-text('{text}')"),
            page.locator(f"text={text}"),
            page.get_by_text(text, exact=False),
        ]
        for cand in candidates:
            if _click_first(cand, force=True):
                opened = True
                break
        if opened:
            break
    if not opened:
        try:
            opened = bool(
                page.evaluate(
                    """
                    (texts) => {
                      const nodes = Array.from(document.querySelectorAll('*'));
                      for (const text of texts) {
                        const target = nodes.find(el => el.textContent && el.textContent.includes(text));
                        if (target) {
                          target.click();
                          return true;
                        }
                      }
                      return false;
                    }
                    """,
                    COVER_HINT_TEXTS,
                )
            )
        except Exception:
            opened = False
    if not opened:
        return False, "skipped"

    dialog = page.locator(".el-dialog, [role='dialog'], .cover-dialog")
    root = dialog if dialog.count() > 0 else page
    try:
        _wait_for_any_locator(page, COVER_IMAGE_SELECTORS + ["[role='dialog']", ".el-dialog"], 10000)
    except Exception:
        pass

    time.sleep(1)
    selected = False
    for sel in COVER_IMAGE_SELECTORS:
        loc = root.locator(sel)
        if loc.count() == 0:
            continue
        target = None
        for i in range(loc.count()):
            item = loc.nth(i)
            if item.is_visible():
                target = item
                break
        if target is None:
            continue
        target.click()
        selected = True
        break
    if not selected:
        try:
            selected = bool(
                page.evaluate(
                    """
                    () => {
                      const dialog = document.querySelector('.el-dialog, [role="dialog"], .cover-dialog');
                      const root = dialog || document;
                      const imgs = Array.from(root.querySelectorAll('img')).filter(el => el.offsetParent !== null);
                      if (imgs.length) {
                        imgs[0].click();
                        return true;
                      }
                      const withBg = Array.from(root.querySelectorAll('*')).find(el => {
                        const bg = window.getComputedStyle(el).backgroundImage || '';
                        return bg && bg !== 'none';
                      });
                      if (withBg) {
                        withBg.click();
                        return true;
                      }
                      return false;
                    }
                    """
                )
            )
        except Exception:
            selected = False

    confirmed = False
    if selected:
        for text in COVER_CONFIRM_TEXTS:
            if _click_first(page.get_by_role("button", name=text)):
                confirmed = True
                break
            if _click_first(page.locator(f"button:has-text('{text}')")):
                confirmed = True
                break
    return True, f"selected={selected} confirmed={confirmed}"


def _locators_for_title(ctx) -> List[str]:
    selectors: List[str] = []
    for hint in TITLE_HINTS:
        selectors.append(f"input[placeholder*='{hint}']")
    selectors.extend(
        [
            "input[aria-label*='\u6807\u9898']",
            "input[type='text']",
            "input:not([type='file'])",
        ]
    )
    return selectors


def _locators_for_body(ctx) -> List[str]:
    selectors: List[str] = []
    for hint in BODY_HINTS:
        selectors.append(f"textarea[placeholder*='{hint}']")
    selectors.extend(
        [
            "textarea",
            "[contenteditable='true']",
        ]
    )
    return selectors


def _fill_text_fields(page, title: str, body: str) -> tuple[bool, bool]:
    def _fill_in_context(ctx) -> tuple[bool, bool]:
        title_ok = _fill_with_selectors(ctx, _locators_for_title(ctx), title)
        body_ok = _fill_with_selectors(ctx, _locators_for_body(ctx), body)
        return title_ok, body_ok

    title_ok, body_ok = _fill_in_context(page)
    if title_ok and body_ok:
        return title_ok, body_ok
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        f_title, f_body = _fill_in_context(frame)
        title_ok = title_ok or f_title
        body_ok = body_ok or f_body
        if title_ok and body_ok:
            break
    return title_ok, body_ok


def _find_content_sections(page) -> List:
    sections: List = []
    for sel in ("section:has-text('\u6b63\u6587\u5185\u5bb9')", "div:has-text('\u6b63\u6587\u5185\u5bb9')"):
        loc = page.locator(sel)
        for i in range(loc.count()):
            item = loc.nth(i)
            try:
                if item.locator("textarea, [contenteditable='true'], input[placeholder*='\u6807\u9898']").count() > 0:
                    sections.append(item)
            except Exception:
                continue
    return sections


def _verify_filled(ctx, selectors: List[str], expected: str) -> bool:
    for sel in selectors:
        loc = ctx.locator(sel)
        count = min(loc.count(), 6)
        for i in range(count):
            try:
                if _matches_value(_read_target_value(loc.nth(i)), expected):
                    return True
            except Exception:
                continue
    return False


def _verify_title_body(page, title: str, body: str) -> tuple[bool, bool]:
    contexts = [page]
    contexts.extend(_find_content_sections(page))
    title_ok = False
    body_ok = False
    for ctx in contexts:
        title_ok = title_ok or _verify_filled(ctx, _locators_for_title(ctx), title)
        body_ok = body_ok or _verify_filled(ctx, _locators_for_body(ctx), body)
        if title_ok and body_ok:
            break
    if not (title_ok and body_ok):
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            title_ok = title_ok or _verify_filled(frame, _locators_for_title(frame), title)
            body_ok = body_ok or _verify_filled(frame, _locators_for_body(frame), body)
            if title_ok and body_ok:
                break
    return title_ok, body_ok


def _click_draft(page) -> tuple[bool, str]:
    page.evaluate("window.scrollTo(0, 0)")
    for text in DRAFT_TEXTS:
        if _click_first(page.get_by_role("button", name=text)):
            return True, f"button:{text}"
    for text in DRAFT_TEXTS:
        if _click_first(page.locator(f"button:has-text('{text}')")):
            return True, f"button-text:{text}"

    publish_candidates = [
        page.get_by_role("button", name="\u53d1\u5e03"),
        page.get_by_role("button", name="\u53d1\u5e03\u7b14\u8bb0"),
        page.locator("button:has-text('\u53d1\u5e03')"),
    ]
    for cand in publish_candidates:
        _click_first(cand)
    for text in DRAFT_TEXTS:
        if _click_first(page.locator(f"button:has-text('{text}')")):
            return True, f"menu:{text}"
    return False, "draft button not found"


def _click_first(locator, *, force: bool = False) -> bool:
    if locator is None or locator.count() == 0:
        return False
    target = _first_visible(locator)
    if target is None:
        return False
    target.click(force=force)
    return True


def _open_draft_box(page) -> bool:
    page.evaluate("window.scrollTo(0, 0)")
    candidates = [
        page.locator(".draft-title-box"),
        page.locator(".draft-title"),
        page.get_by_text("\u8349\u7a3f\u7bb1", exact=False),
        page.get_by_role("button", name="\u8349\u7a3f\u7bb1"),
        page.get_by_role("link", name="\u8349\u7a3f\u7bb1"),
    ]
    for cand in candidates:
        if _click_first(cand, force=True):
            return True
    try:
        return bool(
            page.evaluate(
                """
                () => {
                  const el = document.querySelector('.draft-title-box, .draft-title');
                  if (!el) return false;
                  el.click();
                  return true;
                }
                """
            )
        )
    except Exception:
        return False
    return False


def _open_image_draft_tab(page) -> bool:
    for text in DRAFT_TAB_TEXTS:
        loc = page.get_by_text(text, exact=False)
        if _click_first(loc, force=True):
            return True
    try:
        return bool(
            page.evaluate(
                """
                () => {
                  const tabs = Array.from(document.querySelectorAll('*'))
                    .filter(el => el.textContent && (el.textContent.includes('图文笔记') || el.textContent.includes('图文')));
                  if (!tabs.length) return false;
                  tabs[0].click();
                  return true;
                }
                """
            )
        )
    except Exception:
        return False
    return False


def _verify_draft_item(page, title: str) -> bool:
    return _draft_item_has_cover(page, title)


def _extract_draft_count(page) -> Optional[int]:
    try:
        texts = page.get_by_text(DRAFT_BOX_TEXT, exact=False).all_text_contents()
    except Exception:
        return None
    for text in texts:
        if DRAFT_BOX_TEXT not in text:
            continue
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return int(digits)
    return None


def _extract_upload_count(page) -> Optional[int]:
    try:
        loc = page.locator("text=/\\b\\d+\\s*\\/\\s*18\\b/")
        if loc.count() == 0:
            return None
        text = loc.first.text_content() or ""
    except Exception:
        return None
    match = UPLOAD_COUNT_PATTERN.search(text)
    if not match:
        return None
    return int(match.group(1))


def _count_uploaded_images(page) -> int:
    total = 0
    for sel in ("img[src^='blob:']", "img[src^='data:']"):
        try:
            total += page.locator(sel).count()
        except Exception:
            continue
    return total


def _wait_for_upload_ready(page, expected: int, timeout_ms: int = 120000) -> bool:
    if expected <= 0:
        return True
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        count = _extract_upload_count(page)
        if count is not None and count >= expected:
            return True
        if _count_uploaded_images(page) >= expected:
            return True
        time.sleep(1)
    return False


def _draft_item_has_cover(page, title: str) -> bool:
    snippet = (title or "").strip()[:6]
    return bool(
        page.evaluate(
            """
            (snippet) => {
              const items = Array.from(document.querySelectorAll('.draft-item'));
              if (!items.length) return false;
              const match = snippet
                ? items.filter(item => item.textContent && item.textContent.includes(snippet))
                : [];
              if (snippet && !match.length) return false;
              const candidates = match.length ? match : [items[0]];
              const hasCover = (item) => {
                const img = item.querySelector('img.content, .draft-cover img');
                const src = img ? (img.currentSrc || img.getAttribute('src') || '') : '';
                if (src && /^https?:/.test(src)) return true;
                const bg = item.querySelector('.media-bg');
                if (!bg) return false;
                const bgImage = window.getComputedStyle(bg).backgroundImage || '';
                return bgImage && bgImage !== 'none' && bgImage.includes('http');
              };
              return candidates.some(hasCover);
            }
            """,
            snippet,
        )
    )


def _wait_for_draft_cover(page, title: str, timeout_ms: int = 120000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if _draft_item_has_cover(page, title):
            return True
        time.sleep(1)
    return False


def _read_target_value(target) -> str:
    try:
        if target.get_attribute("contenteditable") == "true":
            return (target.inner_text() or "").strip()
    except Exception:
        pass
    try:
        return (target.input_value() or "").strip()
    except Exception:
        try:
            return (target.text_content() or "").strip()
        except Exception:
            return ""


def _matches_value(actual: str, expected: str) -> bool:
    if not actual:
        return False
    expected = (expected or "").strip()
    if not expected:
        return True
    snippet = expected[:4]
    return snippet in actual


def _processing_visible(page) -> bool:
    for text in PROCESSING_TEXTS:
        try:
            loc = page.get_by_text(text, exact=False)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 5)):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


def _wait_for_processing_done(page, timeout_ms: int = 120000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if not _processing_visible(page):
            return True
        time.sleep(1)
    return False


def run_save_draft_sync(
    post: Post,
    *,
    assets: Optional[list[str]] = None,
    dry_run: bool = False,
    login_hold: int = 0,
    login_only: bool = False,
    wait_timeout_ms: int = WAIT_TIMEOUT_MS,
    execution: Optional[Execution] = None,
) -> Execution:
    exec_rec = execution or Execution(post_id=post.id, result="pending")
    steps: List[StepResult] = []

    def _step(name: str, status: str, detail: str = ""):
        steps.append(StepResult(name=name, status=status, detail=detail))

    assets = [str(Path(p)) for p in (assets or []) if Path(p).is_file()]
    context = None

    try:
        profile_dir, channel, args = _resolve_profile_config()
        profile_dir.mkdir(parents=True, exist_ok=True)

        _step("launch", "in_progress", str(profile_dir))
        with sync_playwright() as p:
            launch_kwargs = {"headless": False}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = args
            context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
            context.set_default_timeout(30000)
            steps[-1].status = "success"
            try:
                page = context.pages[0] if context.pages else context.new_page()
                _step("open_page", "in_progress", TARGET_URL)
                page.goto(TARGET_URL, wait_until="domcontentloaded")
                steps[-1].status = "success"

                if login_hold > 0:
                    _step("login_hold", "in_progress", f"wait {login_hold}s for login")
                    time.sleep(login_hold)
                    steps[-1].status = "success"

                ev_dir = evidence_dir(post.id, exec_rec.id)
                ev_dir.mkdir(parents=True, exist_ok=True)

                _step("page_state", "in_progress", "")
                steps[-1].detail = json.dumps(
                    {"url": page.url, "title": page.title()},
                    ensure_ascii=False,
                )
                steps[-1].status = "success"

                _step("screenshot_before_wait", "in_progress", "")
                shot_path = ev_dir / "before_wait.png"
                page.screenshot(path=str(shot_path), full_page=True)
                steps[-1].detail = f"saved to {shot_path}"
                steps[-1].status = "success"

                _step("html_before_wait", "in_progress", "")
                html_path = ev_dir / "before_wait.html"
                html_path.write_text(page.content(), encoding="utf-8")
                steps[-1].detail = f"saved to {html_path}"
                steps[-1].status = "success"

                _step("frame_info", "in_progress", "")
                frame_urls = [f.url for f in page.frames]
                steps[-1].detail = json.dumps(frame_urls, ensure_ascii=False)
                steps[-1].status = "success"

                _step("wait_for_publish_ui", "in_progress", "")
                matched = _wait_for_any_text(page, WAIT_TEXTS, wait_timeout_ms)
                steps[-1].detail = f"matched {matched}"
                steps[-1].status = "success"

                _step("wait_for_editor", "in_progress", "")
                editor_sel = _wait_for_any_locator(
                    page,
                    [
                        "input[type='file']",
                        "input[placeholder*='\u6807\u9898']",
                        "textarea",
                        "[contenteditable='true']",
                    ],
                    120000,
                )
                steps[-1].detail = f"matched {editor_sel}"
                steps[-1].status = "success"

                if login_only:
                    exec_rec.result = "login_ready"
                    return exec_rec

                if dry_run:
                    _step("upload_images", "skipped", "dry_run")
                    _step("fill_title_body", "skipped", "dry_run")
                    _step("save_draft", "skipped", "dry_run")
                    exec_rec.result = "pending"
                    return exec_rec

                if assets:
                    _step("upload_images", "in_progress", f"{len(assets)} files")
                    uploaded, method = _try_upload_with_button(page, assets)
                    if not uploaded:
                        uploaded, method = _try_upload_with_input(page, assets)
                    steps[-1].detail = f"{len(assets)} files via {method}"
                    if not uploaded:
                        raise RuntimeError("file input not found")
                    try:
                        page.wait_for_load_state("networkidle", timeout=60000)
                    except Exception:
                        pass
                    steps[-1].status = "success"
                    _step("wait_for_upload_complete", "in_progress", "")
                    confirmed = _wait_for_upload_ready(page, len(assets))
                    steps[-1].detail = f"confirmed={confirmed}"
                    if not confirmed:
                        raise RuntimeError("upload count not ready")
                    steps[-1].status = "success"
                    _step("wait_for_processing_done", "in_progress", "")
                    processed = _wait_for_processing_done(page)
                    steps[-1].detail = f"processed={processed}"
                    if not processed:
                        raise RuntimeError("upload processing not finished")
                    steps[-1].status = "success"
                    _step("select_cover", "in_progress", "")
                    cover_applied, cover_detail = _maybe_select_cover(page)
                    steps[-1].detail = cover_detail
                    steps[-1].status = "success"
                else:
                    _step("upload_images", "skipped", "no assets")

                _step("snapshot_after_upload", "in_progress", "")
                after_shot = ev_dir / "after_upload.png"
                page.screenshot(path=str(after_shot), full_page=True)
                steps[-1].detail = f"saved to {after_shot}"
                steps[-1].status = "success"

                _step("wait_for_editor_after_upload", "in_progress", "")
                editor_sel = _wait_for_any_locator(
                    page,
                    [
                        "input[placeholder*='\u6807\u9898']",
                        "textarea",
                        "[contenteditable='true']",
                    ],
                    60000,
                )
                steps[-1].detail = f"matched {editor_sel}"
                steps[-1].status = "success"

                _step("fill_title_body", "in_progress", "")
                title_ok, body_ok = _fill_text_fields(page, post.title, post.body)
                steps[-1].detail = f"title={title_ok} body={body_ok}"
                steps[-1].status = "success"

                _step("verify_title_body", "in_progress", "")
                v_title, v_body = _verify_title_body(page, post.title, post.body)
                steps[-1].detail = f"title={v_title} body={v_body}"
                if not (v_title and v_body):
                    raise RuntimeError("title/body not filled")
                steps[-1].status = "success"

                _step("save_draft", "in_progress", "")
                clicked, detail = _click_draft(page)
                steps[-1].detail = detail
                if not clicked:
                    raise RuntimeError(detail)
                steps[-1].status = "success"

                _step("confirm_leave", "in_progress", "")
                leave_clicked = False
                for text in ("\u6682\u5b58\u79bb\u5f00", "\u786e\u5b9a", "\u7ee7\u7eed\u79bb\u5f00"):
                    if _click_first(page.get_by_role("button", name=text)):
                        leave_clicked = True
                        break
                    if _click_first(page.locator(f"button:has-text('{text}')")):
                        leave_clicked = True
                        break
                steps[-1].detail = f"clicked={leave_clicked}"
                steps[-1].status = "success"
                before_count = _extract_draft_count(page)

                _step("snapshot_after_save", "in_progress", "")
                after_save = ev_dir / "after_save.png"
                page.screenshot(path=str(after_save), full_page=True)
                steps[-1].detail = f"saved to {after_save}"
                steps[-1].status = "success"

                _step("verify_draft_saved", "in_progress", "")
                ok = False
                toast = ""
                try:
                    toast = _wait_for_any_text(page, SAVE_OK_TEXTS, 20000)
                    ok = True
                except PlaywrightTimeoutError:
                    pass
                after_count = before_count
                for _ in range(10):
                    after_count = _extract_draft_count(page)
                    if (
                        before_count is not None
                        and after_count is not None
                        and after_count > before_count
                    ):
                        ok = True
                        break
                    time.sleep(1)
                steps[-1].detail = (
                    f"toast={toast or 'none'} before={before_count} after={after_count}"
                )
                if not ok:
                    raise RuntimeError("draft save verification failed")
                steps[-1].status = "success"

                _step("open_draft_box", "in_progress", "")
                opened = _open_draft_box(page)
                steps[-1].detail = f"opened={opened}"
                if not opened:
                    raise RuntimeError("draft box entry not found")
                steps[-1].status = "success"

                _step("open_draft_tab", "in_progress", "")
                opened_tab = _open_image_draft_tab(page)
                steps[-1].detail = f"opened={opened_tab}"
                if not opened_tab:
                    raise RuntimeError("image draft tab not found")
                steps[-1].status = "success"

                _step("wait_for_draft_items", "in_progress", "")
                try:
                    page.locator(DRAFT_ITEM_SELECTOR).first.wait_for(timeout=30000)
                    steps[-1].detail = "ready"
                    steps[-1].status = "success"
                except PlaywrightTimeoutError:
                    steps[-1].detail = "timeout"
                    raise

                _step("wait_for_draft_cover", "in_progress", "")
                cover_ready = _wait_for_draft_cover(page, post.title)
                steps[-1].detail = f"ready={cover_ready}"
                steps[-1].status = "success"

                _step("snapshot_draft_box", "in_progress", "")
                draft_shot = ev_dir / "draft_box.png"
                page.screenshot(path=str(draft_shot), full_page=True)
                steps[-1].detail = f"saved to {draft_shot}"
                steps[-1].status = "success"

                _step("html_draft_box", "in_progress", "")
                draft_html = ev_dir / "draft_box.html"
                draft_html.write_text(page.content(), encoding="utf-8")
                steps[-1].detail = f"saved to {draft_html}"
                steps[-1].status = "success"

                _step("verify_draft_box_item", "in_progress", "")
                verified = _verify_draft_item(page, post.title)
                steps[-1].detail = f"verified={verified}"
                if not (verified and cover_ready):
                    raise RuntimeError("draft box item missing title or image")
                steps[-1].status = "success"

                exec_rec.result = "saved_draft"
            finally:
                context.close()
    except Exception as exc:  # pragma: no cover
        exec_rec.result = "failed"
        exec_rec.error = {"message": str(exc)}
    finally:
        exec_rec.steps = steps
        save_execution(exec_rec)

    return exec_rec
