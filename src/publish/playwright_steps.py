from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.storage.events import save_event
from src.storage.files import evidence_dir, save_execution
from src.storage.models import Execution, Post, PublishedMetric, StepResult

TARGET_URL = "https://creator.xiaohongshu.com/publish/publish?target=image"
WAIT_TEXTS = [
    "\u4e0a\u4f20\u56fe\u6587",
    "\u53d1\u5e03\u56fe\u6587",
    "\u53d1\u5e03\u7b14\u8bb0",
    "\u53d1\u5e03",
    "\u56fe\u6587",
]
TITLE_HINTS = ["\u586b\u5199\u6807\u9898", "\u6807\u9898", "\u66f4\u591a\u8d5e"]
BODY_HINTS = [
    "\u8f93\u5165\u6b63\u6587",
    "\u6b63\u6587",
    "\u586b\u5199\u6b63\u6587",
    "\u6dfb\u52a0\u6b63\u6587",
    "\u8f93\u5165\u6b63\u6587\u63cf\u8ff0",
    "\u7b14\u8bb0\u5185\u5bb9",
    "\u5206\u4eab\u4f60\u7684\u60f3\u6cd5",
    "\u771f\u8bda\u6709\u4ef7\u503c",
]
DRAFT_TEXTS = [
    "\u6682\u5b58\u79bb\u5f00",
    "\u6682\u5b58\u5e76\u79bb\u5f00",
    "\u6682\u5b58",
    "\u4fdd\u5b58\u8349\u7a3f",
    "\u5b58\u8349\u7a3f",
    "\u5b58\u4e3a\u8349\u7a3f",
]
DRAFT_TEXT_PRIORITY = {text: idx for idx, text in enumerate(DRAFT_TEXTS)}
# Upload/processing hints shown around image thumbnails. Keep the more specific
# ones first so we don't miss them when there are many partial matches.
PROCESSING_TEXTS = [
    "\u56fe\u7247\u4e0a\u4f20\u4e2d",  # 图片上传中，上传完成后可使用
    "\u4e0a\u4f20\u5b8c\u6210\u540e\u53ef\u4f7f\u7528",
    "\u6b63\u5728\u5904\u7406\u4e2d",
    "\u5904\u7406\u4e2d",
    "\u4e0a\u4f20\u4e2d",
]
DRAFT_TAB_TEXTS_IMAGE = ["\u56fe\u6587\u7b14\u8bb0", "\u56fe\u6587"]
DRAFT_TAB_TEXTS_VIDEO = ["\u89c6\u9891\u7b14\u8bb0", "\u89c6\u9891"]
DRAFT_TAB_TEXTS_ARTICLE = ["\u957f\u6587\u7b14\u8bb0", "\u957f\u6587"]
DRAFT_TAB_TEXTS = DRAFT_TAB_TEXTS_IMAGE
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
UPLOAD_COUNT_PATTERN = re.compile(r"(\d+)\s*/\s*18")
GENERIC_DRAFT_TITLES = {"", "\u6682\u65e0\u7b14\u8bb0\u6807\u9898", "\u65e0\u6807\u9898"}
READY_PAGE_HINTS = [
    "\u4e0a\u4f20\u56fe\u6587",
    "\u53d1\u5e03\u56fe\u6587",
    "\u586b\u5199\u6807\u9898",
    "\u8f93\u5165\u6b63\u6587",
    DRAFT_BOX_TEXT,
    "\u56fe\u6587\u7b14\u8bb0",
]
LOGIN_PAGE_HINTS = [
    "\u626b\u7801\u767b\u5f55",
    "\u9a8c\u8bc1\u7801\u767b\u5f55",
    "\u624b\u673a\u53f7\u767b\u5f55",
    "\u5bc6\u7801\u767b\u5f55",
    "\u5c0f\u7ea2\u4e66\u53f7\u767b\u5f55",
    "\u53d1\u9001\u9a8c\u8bc1\u7801",
    "\u8bf7\u5148\u767b\u5f55",
    "\u767b\u5f55\u540e",
    "\u8bf7\u5b8c\u6210\u5b89\u5168\u9a8c\u8bc1",
]
PUBLISHED_PAGE_TEXTS = [
    "\u7b14\u8bb0\u7ba1\u7406",
    "\u5df2\u53d1\u5e03",
    "\u53d1\u5e03\u65f6\u95f4",
    "\u70b9\u8d5e",
    "\u8bc4\u8bba",
    "\u6536\u85cf",
]
PUBLISHED_URL_CANDIDATES = [
    "https://creator.xiaohongshu.com/new/note-manager",
    "https://creator.xiaohongshu.com/creator/notes",
    "https://creator.xiaohongshu.com/creator/notes?source=publish",
    "https://creator.xiaohongshu.com/publish/publish?target=image",
]
EDITOR_READY_SELECTORS = (
    UPLOAD_BUTTON_SELECTORS
    + [
        "input[placeholder*='\u6807\u9898']",
        "textarea",
        "[contenteditable='true']",
    ]
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_profile_config() -> tuple[Path, Optional[str], list[str]]:
    user_data_dir = os.getenv("XHS_CHROME_USER_DATA_DIR")
    profile_dir = (
        Path(user_data_dir)
        if user_data_dir
        else _repo_root() / "data" / "browser" / "chrome-profile"
    )
    channel = os.getenv("XHS_BROWSER_CHANNEL") or "chrome"
    profile_name = os.getenv("XHS_CHROME_PROFILE")
    args: list[str] = []
    if profile_name:
        args.append(f"--profile-directory={profile_name}")
    return profile_dir, channel, args


def _resolve_cdp_url() -> Optional[str]:
    """
    Optional: attach to an existing user-launched Chrome via CDP.

    Env:
      - XHS_CDP_URL: e.g. "http://127.0.0.1:9222" (or just "9222")
    """
    raw = (os.getenv("XHS_CDP_URL") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return f"http://127.0.0.1:{raw}"
    return raw


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_headless(headless: Optional[bool] = None) -> bool:
    if headless is not None:
        return bool(headless)
    return _env_flag("XHS_HEADLESS", False)


def _format_progress_message(name: str, status: str, detail: str = "") -> str:
    message = f"[xhs-upload] {name}: {status}"
    if detail:
        message += f" | {detail}"
    return message


def _emit_progress(
    progress_callback: Optional[Callable[[str], None]],
    name: str,
    status: str,
    detail: str = "",
) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(_format_progress_message(name, status, detail))
    except Exception:
        # Progress reporting must never break the browser automation itself.
        pass


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
    return None


def _wait_for_any_locator(
    page, selectors: List[str], timeout_ms: int, *, state: str = "visible"
) -> str:
    per = max(1000, timeout_ms // max(1, len(selectors)))
    for sel in selectors:
        try:
            page.locator(sel).first.wait_for(state=state, timeout=per)
            return sel
        except PlaywrightTimeoutError:
            continue
    raise PlaywrightTimeoutError(
        f"timeout waiting for any selector (state={state}): {selectors}"
    )


def _locator_has_visible(page, selector: str) -> bool:
    try:
        locator = page.locator(selector)
        count = locator.count()
    except Exception:
        return False
    for idx in range(count):
        try:
            if locator.nth(idx).is_visible():
                return True
        except Exception:
            continue
    return False


def _page_has_ready_selector(page) -> bool:
    return any(_locator_has_visible(page, selector) for selector in EDITOR_READY_SELECTORS)


def _read_page_body_text(page, *, timeout_ms: int = 1000, max_chars: int = 8000) -> str:
    try:
        text = page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        return ""
    return str(text or "")[:max_chars]


def _parse_metric_number(value: str) -> Optional[int]:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([万wWkK]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"万", "w"}:
        number *= 10000
    elif unit == "k":
        number *= 1000
    return int(round(number))


def _parse_metric_from_text(text: str, labels: list[str]) -> Optional[int]:
    label_re = "|".join(re.escape(label) for label in labels)
    number_re = r"([0-9][0-9,]*(?:\.[0-9]+)?\s*(?:万|w|W|k|K)?)"
    patterns = [
        rf"(?:{label_re})\s*[:：]?\s*{number_re}",
        rf"{number_re}\s*(?:{label_re})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            number_text = match.group(1)
            parsed = _parse_metric_number(number_text)
            if parsed is not None:
                return parsed
    return None


def _is_published_metric_title_line(line: str) -> bool:
    text = re.sub(r"\s+", " ", line or "").strip()
    if not text:
        return False
    if len(text) > 80:
        return False
    if re.search(r"(点赞|评论|收藏|浏览|分享|发布时间|发布于|编辑|删除|置顶)", text):
        return False
    if re.fullmatch(r"[\d\s:：/\-.,万wWkK]+", text):
        return False
    return True


def _parse_note_manager_stats_row(lines: list[str]) -> dict[str, Any]:
    for idx, line in enumerate(lines):
        if not re.fullmatch(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2})?", line):
            continue
        title = ""
        for prev in reversed(lines[:idx]):
            if _is_published_metric_title_line(prev):
                title = prev
                break
        stats: list[int] = []
        for candidate in lines[idx + 1 :]:
            parsed = _parse_metric_number(candidate)
            if parsed is None:
                if stats:
                    break
                continue
            stats.append(parsed)
            if len(stats) >= 5:
                break
        if title and len(stats) >= 4:
            return {
                "title": title,
                "published_at": line[:10].replace("/", "-").replace(".", "-"),
                "views": stats[0] if len(stats) > 0 else None,
                "likes": stats[1] if len(stats) > 1 else None,
                "comments": stats[2] if len(stats) > 2 else None,
                "favorites": stats[3] if len(stats) > 3 else None,
                "shares": stats[4] if len(stats) > 4 else None,
                "stats": stats,
            }
    return {}


def _parse_published_metric_text(text: str) -> dict[str, Any]:
    normalized = re.sub(r"\r\n?", "\n", text or "")
    compact = re.sub(r"[ \t]+", " ", normalized)
    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    stats_row = _parse_note_manager_stats_row(lines)
    title = ""
    for line in lines:
        if _is_published_metric_title_line(line):
            title = line
            break
    full_text = "\n".join(lines)
    date_match = re.search(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", full_text)
    return {
        "title": stats_row.get("title") or title,
        "published_at": stats_row.get("published_at")
        or (date_match.group(1).replace("/", "-").replace(".", "-") if date_match else ""),
        "likes": stats_row.get("likes") if stats_row else _parse_metric_from_text(full_text, ["点赞", "赞", "赞数"]),
        "comments": stats_row.get("comments") if stats_row else _parse_metric_from_text(full_text, ["评论", "评论数"]),
        "favorites": stats_row.get("favorites") if stats_row else _parse_metric_from_text(full_text, ["收藏", "收藏数"]),
        "stats": stats_row.get("stats", []),
        "views": stats_row.get("views"),
        "shares": stats_row.get("shares"),
        "raw_text": full_text,
    }


def _published_url_candidates() -> list[str]:
    raw = (os.getenv("XHS_PUBLISHED_URL") or "").strip()
    if raw:
        return [raw]
    return list(PUBLISHED_URL_CANDIDATES)


def _collect_published_metric_cards(page) -> list[dict[str, str]]:
    try:
        data = page.evaluate(
            r"""
            () => {
              const selectors = [
                'article',
                'li',
                'tr',
                '[class*="note"]',
                '[class*="card"]',
                '[class*="item"]',
                '[class*="list"] > div'
              ];
              const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
              const seen = new Set();
              const out = [];
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 20 && rect.height > 10;
              };
              for (const node of nodes) {
                if (!visible(node)) continue;
                const text = (node.innerText || node.textContent || '').trim();
                if (!text || text.length < 4) continue;
                const link = node.querySelector('a[href]');
                const href = link ? link.href : '';
                const hasMetric = /点赞|赞数|评论|收藏/.test(text);
                const looksLikeNote = /xiaohongshu\.com\/(explore|discovery|user\/profile)/.test(href || '');
                const className = String(node.className || '');
                const looksLikeNoteManagerCard = /note-card/.test(className) && /20\d{2}-\d{2}-\d{2}/.test(text);
                if (!hasMetric && !looksLikeNote && !looksLikeNoteManagerCard) continue;
                const key = (href || '') + '|' + text.slice(0, 120);
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({ text, href });
                if (out.length >= 300) break;
              }
              return out;
            }
            """
        )
    except Exception:
        return []
    return [item for item in data if isinstance(item, dict)]


def _merge_published_metric_cards(cards: list[dict[str, str]], *, limit: int = 0) -> list[PublishedMetric]:
    items: list[PublishedMetric] = []
    seen: set[str] = set()
    for card in cards:
        text = str(card.get("text") or "")
        href = str(card.get("href") or "")
        parsed = _parse_published_metric_text(text)
        title = str(parsed.get("title") or "").strip()
        likes = parsed.get("likes")
        comments = parsed.get("comments")
        favorites = parsed.get("favorites")
        if not title and not href:
            continue
        if likes is None and comments is None and favorites is None:
            continue
        key = href or title
        if key in seen:
            continue
        seen.add(key)
        items.append(
            PublishedMetric(
                title=title,
                url=href,
                published_at=str(parsed.get("published_at") or ""),
                likes=likes,
                comments=comments,
                favorites=favorites,
                raw={
                    "text": parsed.get("raw_text") or text,
                    "stats": parsed.get("stats") or [],
                    "views": parsed.get("views"),
                    "shares": parsed.get("shares"),
                },
            )
        )
        if limit and len(items) >= limit:
            break
    return items


def _classify_xhs_page_state(url: str, title: str, body_text: str) -> str:
    """
    Return ready/login/unknown for the current creator page.

    Login overlays can leave publish-page text in the background, so strong login
    hints deliberately win over ready hints.
    """
    haystack = "\n".join([url or "", title or "", body_text or ""]).lower()
    if "login" in haystack or any(hint in haystack for hint in LOGIN_PAGE_HINTS):
        return "login"
    if any(hint in (body_text or "") for hint in READY_PAGE_HINTS):
        return "ready"
    if "creator.xiaohongshu.com/publish" in haystack and "target=" in haystack:
        return "unknown"
    return "unknown"


def _detect_xhs_page_state(page) -> tuple[str, str]:
    url = ""
    title = ""
    try:
        url = str(page.url or "")
    except Exception:
        pass
    try:
        title = str(page.title() or "")
    except Exception:
        pass
    body_text = _read_page_body_text(page)
    state = _classify_xhs_page_state(url, title, body_text)
    if state != "login" and _page_has_ready_selector(page):
        state = "ready"
    detail = f"state={state} url={url or 'unknown'} title={title or 'unknown'}"
    return state, detail


def _wait_for_xhs_ready(
    page,
    *,
    login_hold: int = 0,
    headless: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
    state_reader: Optional[Callable[[object], tuple[str, str]]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> str:
    """
    Wait only while login is actually needed or the creator app is still loading.

    A non-zero login_hold is now an upper bound for manual login, not an
    unconditional sleep. In headless mode, a detected login page fails fast
    because the user cannot scan a QR/captcha in an invisible browser.
    """
    reader = state_reader or _detect_xhs_page_state
    state, detail = reader(page)
    if state == "ready":
        _emit_progress(progress_callback, "login_check", "success", detail)
        return detail
    if headless and state == "login":
        raise RuntimeError(
            "xiaohongshu login required but browser is headless; "
            "open GUI '登录/检查Profile' or run once without --headless"
        )
    if login_hold <= 0:
        _emit_progress(progress_callback, "login_check", "skipped", detail)
        return detail

    deadline = monotonic_fn() + max(0, login_hold)
    _emit_progress(
        progress_callback,
        "login_check",
        "in_progress",
        f"{detail} timeout={login_hold}s",
    )
    next_report = monotonic_fn() + 15
    last_detail = detail
    while monotonic_fn() < deadline:
        sleep_fn(1)
        state, detail = reader(page)
        last_detail = detail
        if state == "ready":
            _emit_progress(progress_callback, "login_check", "success", detail)
            return detail
        if headless and state == "login":
            raise RuntimeError(
                "xiaohongshu login required but browser is headless; "
                "open GUI '登录/检查Profile' or run once without --headless"
            )
        now = monotonic_fn()
        if now >= next_report:
            remain = max(0, int(deadline - now))
            _emit_progress(
                progress_callback,
                "login_check",
                "in_progress",
                f"{detail} remaining={remain}s",
            )
            next_report = now + 15

    if state == "login":
        raise RuntimeError(
            f"xiaohongshu login not completed within {login_hold}s; {last_detail}"
        )
    return last_detail


def _first_matching_locator(ctx, selectors: List[str]):
    for sel in selectors:
        loc = ctx.locator(sel)
        if loc.count() > 0:
            return loc
    return None


def _html_for_contenteditable_text(value: str) -> str:
    lines = (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        return "<p><br></p>"
    parts: list[str] = []
    for line in lines:
        text = html.escape(line, quote=False)
        parts.append(f"<p>{text}</p>" if text else "<p><br></p>")
    return "".join(parts)


def _commit_input_value(target, value: str) -> None:
    """
    Make framework-controlled fields observe the final value.

    Some XHS inputs can read back correctly after Playwright.fill(), while the
    Vue state that is persisted to drafts is still stale. Dispatching native
    input/change/blur events after setting the DOM value keeps both layers in sync.
    """
    try:
        editable_html = _html_for_contenteditable_text(value)
        target.evaluate(
            """
            (el, payload) => {
              const [value, editableHtml] = payload;
              const fire = (name, event) => el.dispatchEvent(event || new Event(name, { bubbles: true }));
              const editable = el.getAttribute && (
                el.getAttribute('contenteditable') === 'true' ||
                el.getAttribute('role') === 'textbox' ||
                el.classList.contains('ProseMirror') ||
                el.classList.contains('ql-editor')
              );
              if (editable) {
                el.focus();
                el.innerHTML = editableHtml;
                fire('input', new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                fire('beforeinput', new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: value }));
                fire('keyup', new KeyboardEvent('keyup', { bubbles: true, key: 'Process' }));
                fire('change');
                fire('blur');
                return;
              }
              const tag = (el.tagName || '').toLowerCase();
              const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
              el.focus();
              if (setter) setter.call(el, value);
              else el.value = value;
              fire('input', new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
              fire('change');
              fire('blur');
            }
            """,
            [value, editable_html],
        )
    except Exception:
        pass


def _trusted_type_value(target, value: str) -> bool:
    """
    Prefer real keyboard events for framework-controlled editors.

    XHS can render Playwright.fill() values in the DOM/preview while the Vue state
    used for draft persistence is still stale. Selecting all and typing the final
    value produces trusted keyboard/input events, which makes the saved draft title
    match the visible editor much more reliably.
    """
    try:
        target.click(timeout=3000)
        target.press("Control+A")
        delay_ms = int(os.getenv("XHS_TYPE_DELAY_MS") or 5)
        target.type(value, delay=max(0, delay_ms))
        _commit_input_value(target, value)
        target.press("Tab")
    except Exception:
        return False
    return _matches_value(_read_target_value(target), value)


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

    if len(value or "") <= 1200 and _trusted_type_value(target, value):
        return True

    try:
        target.click(timeout=3000)
    except Exception:
        return False
    target.fill(value)
    _commit_input_value(target, value)
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
        _commit_input_value(target, value)
        target.press("Tab")
    except Exception:
        pass
    return _matches_value(_read_target_value(target), value)


def _fill_with_selectors(ctx, selectors: List[str], value: str) -> bool:
    for sel in selectors:
        if _fill_if_found(ctx.locator(sel), value):
            return True
    return False


def _fill_body_by_placeholder_text(page, body: str) -> bool:
    placeholder_texts = [
        "\u8f93\u5165\u6b63\u6587\u63cf\u8ff0",
        "\u771f\u8bda\u6709\u4ef7\u503c",
        "\u5206\u4eab\u4e88\u4eba\u6e29\u6696",
        "\u8f93\u5165\u6b63\u6587",
    ]
    for text in placeholder_texts:
        try:
            loc = page.get_by_text(text, exact=False)
            target = _first_visible(loc)
            if target is None:
                continue
            target.click(timeout=3000)
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(body)
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
            if _matches_body_value(page.locator("body").inner_text(timeout=3000), body):
                return True
        except Exception:
            continue
    try:
        editable_html = _html_for_contenteditable_text(body)
        return bool(
            page.evaluate(
                """
                ({ value, editableHtml }) => {
                  const hints = ['输入正文描述', '真诚有价值', '分享予人温暖', '输入正文'];
                  const nodes = Array.from(document.querySelectorAll('*')).filter(el => {
                    const text = (el.textContent || '').trim();
                    if (!text || !hints.some(h => text.includes(h))) return false;
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                  });
                  const target = nodes.sort((a, b) => {
                    const ar = a.getBoundingClientRect();
                    const br = b.getBoundingClientRect();
                    return (ar.width * ar.height) - (br.width * br.height);
                  })[0];
                  if (!target) return false;
                  target.click();
                  const active = document.activeElement;
                  const editor = active && active !== document.body ? active : target;
                  if (editor.getAttribute && editor.getAttribute('contenteditable') === 'true') {
                    editor.innerHTML = editableHtml;
                    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                    editor.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                  }
                  return false;
                }
                """,
                {"value": body, "editableHtml": editable_html},
            )
        )
    except Exception:
        return False


def _fill_body_by_title_offset(page, body: str) -> bool:
    title_loc = page.locator("input[placeholder*='\u6807\u9898']").first
    try:
        box = title_loc.bounding_box(timeout=3000)
    except Exception:
        box = None
    if not box:
        return False
    # XHS places the body editor directly below the title input in the same card.
    x = box["x"] + 24
    y = box["y"] + max(48, box["height"] + 22)
    try:
        page.mouse.click(x, y)
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(body)
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        return _matches_body_value(page.locator("body").inner_text(timeout=3000), body)
    except Exception:
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
            "[role='textbox']",
            ".ProseMirror",
            ".ql-editor",
        ]
    )
    for hint in BODY_HINTS:
        selectors.append(f"[data-placeholder*='{hint}']")
        selectors.append(f"[aria-label*='{hint}']")
    return selectors


def _fill_text_fields(page, title: str, body: str) -> tuple[bool, bool]:
    def _fill_in_context(ctx) -> tuple[bool, bool]:
        title_ok = _fill_with_selectors(ctx, _locators_for_title(ctx), title)
        body_ok = _fill_with_selectors(ctx, _locators_for_body(ctx), body)
        return title_ok, body_ok

    title_ok, body_ok = _fill_in_context(page)
    if not body_ok:
        body_ok = _fill_body_by_placeholder_text(page, body)
    if not body_ok:
        body_ok = _fill_body_by_title_offset(page, body)
    if title_ok and body_ok:
        return title_ok, body_ok
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        f_title, f_body = _fill_in_context(frame)
        title_ok = title_ok or f_title
        body_ok = body_ok or f_body
        if not body_ok:
            body_ok = _fill_body_by_placeholder_text(page, body)
        if not body_ok:
            body_ok = _fill_body_by_title_offset(page, body)
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
        if not body_ok:
            try:
                body_ok = _matches_body_value(page.locator("body").inner_text(timeout=3000), body)
            except Exception:
                body_ok = False
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


def _pick_draft_click_candidate(candidates: list[dict]) -> Optional[dict]:
    def _priority(item: dict) -> tuple[int, int, int]:
        text = str(item.get("text") or "")
        text_rank = min(
            [rank for draft_text, rank in DRAFT_TEXT_PRIORITY.items() if draft_text in text]
            or [len(DRAFT_TEXT_PRIORITY)]
        )
        bottom = int(item.get("bottom") or item.get("y") or 0)
        area = int(item.get("width") or 0) * int(item.get("height") or 0)
        # Prefer the current sticky action bar near the bottom, then smaller clickable target.
        return (text_rank, -bottom, area)

    usable = []
    for item in candidates or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if not any(draft_text in text for draft_text in DRAFT_TEXTS):
            continue
        try:
            int(item.get("x") or 0)
            int(item.get("y") or 0)
        except Exception:
            continue
        usable.append(item)
    if not usable:
        return None
    return sorted(usable, key=_priority)[0]


def _bottom_draft_click_point(viewport_size: Optional[dict]) -> tuple[int, int]:
    size = viewport_size or {}
    width = int(size.get("width") or 1280)
    height = int(size.get("height") or 720)
    x = max(120, min(width - 120, int(width * 0.43)))
    y = max(80, height - 45)
    return x, y


def _click_draft(page) -> tuple[bool, str]:
    def _visible_button_texts() -> list[str]:
        script = """
        () => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none'
              && rect.width > 0 && rect.height > 0;
          };
          const nodes = Array.from(document.querySelectorAll('button, [role="button"], .d-button, .btn'));
          return nodes
            .filter(visible)
            .map(el => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' '))
            .filter(Boolean)
            .slice(0, 40);
        }
        """
        try:
            values = page.evaluate(script)
        except Exception:
            return []
        return [str(v) for v in values if str(v).strip()]

    def _collect_draft_text_candidates() -> list[dict]:
        script = """
        (texts) => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none'
              && rect.width > 0 && rect.height > 0;
          };
          const out = [];
          const nodes = Array.from(document.querySelectorAll('body *'));
          for (const el of nodes) {
            if (!visible(el)) continue;
            const value = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
            if (!value || value.includes('发布') && !texts.some(t => value.includes(t))) continue;
            const matched = texts.find(t => value.includes(t));
            if (!matched) continue;
            const target = el.closest('button,[role="button"],a,[class*="button"],[class*="btn"]') || el;
            if (!visible(target)) continue;
            const rect = target.getBoundingClientRect();
            out.push({
              text: matched,
              x: Math.round(rect.left + rect.width / 2),
              y: Math.round(rect.top + rect.height / 2),
              bottom: Math.round(rect.bottom),
              width: Math.round(rect.width),
              height: Math.round(rect.height)
            });
          }
          return out.slice(0, 80);
        }
        """
        try:
            values = page.evaluate(script, DRAFT_TEXTS)
        except Exception:
            return []
        return [v for v in values if isinstance(v, dict)]

    def _click_ranked_candidate(prefix: str) -> tuple[bool, str]:
        picked = _pick_draft_click_candidate(_collect_draft_text_candidates())
        if not picked:
            return False, ""
        try:
            x = int(picked.get("x") or 0)
            y = int(picked.get("y") or 0)
            page.mouse.click(x, y)
            return True, f"{prefix}:ranked-text:{picked.get('text')}:x={x},y={y}"
        except Exception:
            return False, ""

    def _click_direct_candidates(prefix: str) -> tuple[bool, str]:
        for text in DRAFT_TEXTS:
            if _click_first(page.get_by_role("button", name=text)):
                return True, f"{prefix}:role-button:{text}"
        for text in DRAFT_TEXTS:
            selectors = [
                f"button:has-text('{text}')",
                f"[role='button']:has-text('{text}')",
                f".d-button:has-text('{text}')",
            ]
            for sel in selectors:
                if _click_first(page.locator(sel)):
                    return True, f"{prefix}:{sel}"
        return False, ""

    def _click_by_text_js(prefix: str) -> tuple[bool, str]:
        script = """
        (texts) => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style && style.visibility !== 'hidden' && style.display !== 'none'
              && rect.width > 0 && rect.height > 0;
          };
          const selectors = ['button', '[role="button"]', '.d-button', '.btn'];
          const candidates = Array.from(document.querySelectorAll(selectors.join(',')));
          for (const text of texts) {
            for (const el of candidates) {
              const value = (el.innerText || el.textContent || '').trim();
              if (!value.includes(text) || !visible(el)) continue;
              el.scrollIntoView({ block: 'center', inline: 'center' });
              el.click();
              return text;
            }
            const textMatches = Array.from(document.querySelectorAll('body *'))
              .filter(el => {
                const value = (el.innerText || el.textContent || '').trim();
                if (!value.includes(text) || !visible(el)) return false;
                return true;
              })
              .sort((a, b) => {
                const ar = a.getBoundingClientRect();
                const br = b.getBoundingClientRect();
                return (ar.width * ar.height) - (br.width * br.height);
              });
            if (textMatches.length) {
              const el = textMatches[0];
              const target = el.closest('button,[role="button"],a,[class*="button"],[class*="btn"]') || el;
              target.scrollIntoView({ block: 'center', inline: 'center' });
              target.click();
              return text;
            }
          }
          return '';
        }
        """
        try:
            clicked = page.evaluate(script, DRAFT_TEXTS)
        except Exception:
            clicked = ""
        if clicked:
            return True, f"{prefix}:js-text:{clicked}"
        return False, ""

    try:
        x, y = _bottom_draft_click_point(page.viewport_size)
        page.mouse.click(x, y)
        return True, f"coordinate-bottom-draft:x={x},y={y}"
    except Exception:
        pass

    ok, detail = _click_ranked_candidate("current")
    if ok:
        return True, detail
    ok, detail = _click_direct_candidates("current")
    if ok:
        return True, detail
    ok, detail = _click_by_text_js("current")
    if ok:
        return True, detail

    for prefix, scroll_script in (
        (
            "bottom",
            """
            (() => {
              const root = document.scrollingElement || document.documentElement || document.body;
              if (root) root.scrollTop = root.scrollHeight;
              window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));
              for (const el of Array.from(document.querySelectorAll('*'))) {
                if (el.scrollHeight > el.clientHeight + 20) {
                  el.scrollTop = el.scrollHeight;
                }
              }
            })()
            """,
        ),
        ("top", "window.scrollTo(0, 0)"),
    ):
        try:
            page.evaluate(scroll_script)
            page.wait_for_timeout(300)
        except Exception:
            pass
        ok, detail = _click_ranked_candidate(prefix)
        if ok:
            return True, detail
        ok, detail = _click_direct_candidates(prefix)
        if ok:
            return True, detail
        ok, detail = _click_by_text_js(prefix)
        if ok:
            return True, detail

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
    try:
        x, y = _bottom_draft_click_point(page.viewport_size)
        page.mouse.click(x, y)
        return True, f"coordinate-bottom-draft:x={x},y={y}"
    except Exception:
        pass
    return False, f"draft button not found; visible_buttons={_visible_button_texts()}"


def _click_first(locator, *, force: bool = False, timeout_ms: int | None = None) -> bool:
    if locator is None or locator.count() == 0:
        return False
    target = _first_visible(locator)
    if target is None:
        return False
    try:
        if timeout_ms is None:
            target.click(force=force)
        else:
            target.click(force=force, timeout=timeout_ms)
        return True
    except Exception:
        return False


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


def _open_draft_tab(page, draft_type: str) -> bool:
    draft_type = (draft_type or "image").strip().lower()
    if draft_type == "image":
        return _open_image_draft_tab(page)
    texts = DRAFT_TAB_TEXTS_IMAGE
    if draft_type == "video":
        texts = DRAFT_TAB_TEXTS_VIDEO
    elif draft_type in ("article", "long"):
        texts = DRAFT_TAB_TEXTS_ARTICLE
    for text in texts:
        loc = page.get_by_text(text, exact=False)
        if _click_first(loc, force=True):
            return True
    return False


def _collect_draft_items(page, *, limit: Optional[int] = None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    locator = page.locator(DRAFT_ITEM_SELECTOR)
    count = locator.count()
    if limit is not None:
        count = min(count, max(0, int(limit)))
    for i in range(count):
        item = locator.nth(i)
        title = ""
        saved_at = ""
        try:
            title = (item.locator(".draft-title-text").first.text_content() or "").strip()
        except Exception:
            title = ""
        try:
            saved_at = (item.locator(".draft-time").first.text_content() or "").strip()
        except Exception:
            saved_at = ""
        items.append({"title": title, "saved_at": saved_at})
    return items


def _confirm_delete_dialog(page, timeout_s: float = 3.0) -> bool:
    selectors = [
        ".draft-delete-popconfirm .btn-footer-confirm",
        ".d-popconfirm .btn-footer-confirm",
        ".d-popconfirm-footer .btn-footer-confirm",
        ".d-popover .btn-footer-confirm",
        ".el-popconfirm:visible button:has-text('删除')",
        ".el-popconfirm:visible button:has-text('确定')",
        ".el-popconfirm:visible button:has-text('确认')",
        ".el-popover:visible button:has-text('删除')",
        ".el-popover:visible button:has-text('确定')",
        ".el-popover:visible button:has-text('确认')",
        ".el-popper:visible button:has-text('删除')",
        ".el-popper:visible button:has-text('确定')",
        ".el-popper:visible button:has-text('确认')",
        "[role='dialog'] button:has-text('删除')",
        "[role='dialog'] button:has-text('确定')",
        "[role='dialog'] button:has-text('确认')",
        ".el-dialog__wrapper:visible button:has-text('删除')",
        ".el-dialog__wrapper:visible button:has-text('确定')",
        ".el-dialog__wrapper:visible button:has-text('确认')",
        ".d-dialog:visible button:has-text('删除')",
        ".d-dialog:visible button:has-text('确定')",
        ".d-dialog:visible button:has-text('确认')",
        ".modal:visible button:has-text('删除')",
        ".modal:visible button:has-text('确定')",
        ".modal:visible button:has-text('确认')",
        "[aria-modal='true'] button:has-text('删除')",
        "[aria-modal='true'] button:has-text('确定')",
        "[aria-modal='true'] button:has-text('确认')",
        "[role='dialog'] span:has-text('删除')",
        ".el-popover:visible span:has-text('删除')",
        ".el-popper:visible span:has-text('删除')",
        ".modal:visible span:has-text('删除')",
        "[aria-modal='true'] span:has-text('删除')",
    ]
    deadline = time.time() + max(0.0, timeout_s)
    while time.time() < deadline:
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            target = _first_visible(loc)
            if target is None:
                continue
            try:
                target.click(force=True)
                return True
            except Exception:
                continue
        try:
            if page.evaluate(
                """
                () => {
                  const containers = Array.from(document.querySelectorAll(
                    '.el-popconfirm,.el-popover,.el-popper,.d-popconfirm,.d-popover,.draft-delete-popconfirm,[role="dialog"],[aria-modal="true"],.el-dialog__wrapper,.modal,.d-dialog,[class*="dialog"],[class*="modal"],[class*="popper"]'
                  ));
                  const scope = containers.find(el => {
                    const style = window.getComputedStyle(el);
                    if (!style || style.visibility === 'hidden' || style.display === 'none') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  });
                  if (!scope) return false;
                  const btns = Array.from(scope.querySelectorAll('button, .btn, [role="button"], a, .btn-footer-confirm'));
                  const target = btns.find(el => {
                    if (!el.textContent) return false;
                    const txt = el.textContent;
                    if (txt.includes('删除') || txt.includes('确定') || txt.includes('确认')) {
                      return !el.closest('.draft-actions');
                    }
                    return false;
                  });
                  if (!target) return false;
                  target.click();
                  return true;
                }
                """
            ):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _verify_draft_item(page, title: str) -> bool:
    return _draft_item_exists(page, title) and _draft_item_has_cover(page, title)


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


def _title_match_terms(title: str) -> list[str]:
    text = (title or "").strip()
    if not text:
        return []
    for sep in ("｜", "|", " - ", "—", "：", ":"):
        if sep in text:
            tail = text.split(sep, 1)[1].strip()
            if tail:
                text = tail
                break
    text = re.sub(r"^(?:每日新闻|每日假新闻)[\s｜|:：\-—]*", "", text).strip()
    parts = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", text)
    terms: list[str] = []
    for part in parts:
        value = part.strip()
        if not value or value in ("每日新闻", "每日假新闻"):
            continue
        if value not in terms:
            terms.append(value)
    if not terms and text and text not in ("每日新闻", "每日假新闻"):
        terms.append(text)
    return terms[:4]


def _draft_title_matches_expected(actual: str, expected: str) -> bool:
    actual_text = (actual or "").strip()
    if actual_text in GENERIC_DRAFT_TITLES:
        return False
    expected_text = (expected or "").strip()
    if not actual_text or not expected_text:
        return False
    if actual_text == expected_text:
        return True
    terms = _title_match_terms(expected_text)
    if not terms:
        return expected_text[:6] in actual_text
    return any(term and term in actual_text for term in terms)


def _count_uploaded_images(page) -> int:
    total = 0
    for sel in ("img[src^='blob:']", "img[src^='data:']"):
        try:
            total += page.locator(sel).count()
        except Exception:
            continue
    return total


def _wait_for_upload_ready(
    page,
    expected: int,
    timeout_ms: int = 120000,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    if expected <= 0:
        _emit_progress(
            progress_callback,
            "wait_for_upload_complete",
            "success",
            "uploaded=0/0",
        )
        return True
    deadline = time.time() + timeout_ms / 1000
    last_detail = ""
    while time.time() < deadline:
        count = _extract_upload_count(page)
        if count is None:
            count = _count_uploaded_images(page)
        shown_count = max(0, min(int(count or 0), expected))
        detail = f"uploaded={shown_count}/{expected}"
        if detail != last_detail:
            _emit_progress(
                progress_callback,
                "wait_for_upload_complete",
                "in_progress",
                detail,
            )
            last_detail = detail
        if count >= expected:
            _emit_progress(
                progress_callback,
                "wait_for_upload_complete",
                "success",
                f"uploaded={expected}/{expected}",
            )
            return True
        time.sleep(1)
    _emit_progress(
        progress_callback,
        "wait_for_upload_complete",
        "failed",
        last_detail or f"uploaded=0/{expected}",
    )
    return False


def _draft_item_has_cover(page, title: str) -> bool:
    return bool(
        page.evaluate(
            """
            ({expected, terms, genericTitles}) => {
              const items = Array.from(document.querySelectorAll('.draft-item'));
              if (!items.length) return false;
              const generic = new Set(genericTitles || []);
              const titleMatches = (item) => {
                const titleEl = item.querySelector('.draft-title-text');
                const title = titleEl ? (titleEl.textContent || '').trim() : '';
                if (!title || generic.has(title)) return false;
                if (expected && title === expected) return true;
                return (terms || []).some(term => term && title.includes(term));
              };
              const match = items.filter(titleMatches);
              if (!match.length) return false;
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
            {
                "expected": (title or "").strip(),
                "terms": _title_match_terms(title),
                "genericTitles": sorted(GENERIC_DRAFT_TITLES),
            },
        )
    )


def _draft_item_exists(page, title: str) -> bool:
    return bool(
        page.evaluate(
            """
            ({expected, terms, genericTitles}) => {
              const items = Array.from(document.querySelectorAll('.draft-item'));
              if (!items.length) return false;
              const generic = new Set(genericTitles || []);
              return items.some(item => {
                const titleEl = item.querySelector('.draft-title-text');
                const title = titleEl ? (titleEl.textContent || '').trim() : '';
                if (!title || generic.has(title)) return false;
                if (expected && title === expected) return true;
                return (terms || []).some(term => term && title.includes(term));
              });
            }
            """,
            {
                "expected": (title or "").strip(),
                "terms": _title_match_terms(title),
                "genericTitles": sorted(GENERIC_DRAFT_TITLES),
            },
        )
    )


def _draft_item_key(page) -> str:
    try:
        title = (
            page.locator(DRAFT_ITEM_SELECTOR)
            .first.locator(".draft-title-text")
            .first.text_content()
            or ""
        ).strip()
    except Exception:
        title = ""
    try:
        saved_at = (
            page.locator(DRAFT_ITEM_SELECTOR)
            .first.locator(".draft-time")
            .first.text_content()
            or ""
        ).strip()
    except Exception:
        saved_at = ""
    if not title and not saved_at:
        return ""
    return f"{title}|{saved_at}"


def _wait_for_draft_cover(page, title: str, timeout_ms: int = 120000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if _draft_item_has_cover(page, title):
            return True
        time.sleep(1)
    return False


def _delete_first_draft_item(page) -> tuple[bool, str]:
    locator = page.locator(DRAFT_ITEM_SELECTOR)
    if locator.count() == 0:
        return False, "no draft items"
    item = locator.first
    title = ""
    try:
        title = (item.locator(".draft-title-text").first.text_content() or "").strip()
    except Exception:
        title = ""
    btn = item.locator(".draft-actions .btn", has_text="删除")
    if btn.count() == 0:
        btn = item.locator(".btn", has_text="删除")
    if btn.count() == 0:
        return False, "delete button not found"
    click_error = None
    clicked = False
    try:
        item.scroll_into_view_if_needed()
        item.hover()
        page.once("dialog", lambda dialog: dialog.accept())
        btn.first.scroll_into_view_if_needed()
        btn.first.click(force=True)
        clicked = True
    except Exception as exc:
        click_error = exc

    if not clicked:
        try:
            clicked = bool(
                page.evaluate(
                    """
                    () => {
                      const items = Array.from(document.querySelectorAll('.draft-item'));
                      if (!items.length) return false;
                      const item = items[0];
                      const btns = Array.from(item.querySelectorAll('.draft-actions .btn, .draft-actions button, .draft-actions a'));
                      const target = btns.find(btn => btn.textContent && btn.textContent.includes('删除'));
                      if (!target) return false;
                      target.click();
                      return true;
                    }
                    """
                )
            )
        except Exception:
            clicked = False
        if not clicked:
            return False, f"click delete failed: {click_error or 'unknown'}"

    confirmed = _confirm_delete_dialog(page, timeout_s=5.0)
    if not confirmed:
        try:
            confirm_clicked = page.evaluate(
                """
                () => {
                  const selectors = [
                    '[role="dialog"] button',
                    '[role="dialog"] .btn',
                    '[role="dialog"] [role="button"]',
                    '[aria-modal="true"] button',
                    '[aria-modal="true"] .btn',
                    '[aria-modal="true"] [role="button"]',
                    '.el-popover button',
                    '.el-popover .btn',
                    '.el-popper button',
                    '.el-popper .btn',
                    '.modal button',
                    '.modal .btn',
                    '.d-dialog button',
                    '.d-dialog .btn',
                    'div[role="dialog"] button',
                  ];
                  const btns = selectors.flatMap(sel => Array.from(document.querySelectorAll(sel)));
                  const target = btns.find(el => {
                    const txt = (el.textContent || '').trim();
                    return txt.includes('删除') || txt.includes('确定') || txt.includes('确认');
                  });
                  if (!target) return false;
                  target.click();
                  return true;
                }
                """
            )
            if confirm_clicked:
                confirmed = True
        except Exception:
            pass
    if not confirmed:
        return False, "delete confirm not found"
    return True, title or "draft"


def _wait_for_draft_list_change(
    page,
    *,
    before_count: int,
    before_title: str,
    before_key: str = "",
    before_total: Optional[int] = None,
    timeout_s: int = 10,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            after_count = page.locator(DRAFT_ITEM_SELECTOR).count()
        except Exception:
            after_count = before_count
        if after_count < before_count:
            return True
        if before_total is not None:
            after_total = _extract_draft_count(page)
            if after_total is not None and after_total < before_total:
                return True
        if before_key:
            after_key = _draft_item_key(page)
            if after_key and after_key != before_key:
                return True
        try:
            first_title = (
                page.locator(DRAFT_ITEM_SELECTOR)
                .first.locator(".draft-title-text")
                .first.text_content()
                or ""
            ).strip()
        except Exception:
            first_title = ""
        if first_title and before_title and first_title != before_title:
            return True
        time.sleep(0.5)
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


def _body_match_terms(body: str) -> list[str]:
    terms: list[str] = []
    try:
        obj = json.loads(body)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        for key in ("\u539f\u6587\u6807\u9898", "\u5185\u5bb9", "\u8bc4\u4ef7", "\u6765\u6e90"):
            value = str(obj.get(key) or "").strip()
            if value:
                terms.append(value[: min(12, len(value))])
    if not terms and body:
        terms.append(body[: min(12, len(body))])
    return [term for term in terms if term]


def _matches_body_value(actual: str, expected: str) -> bool:
    if _matches_value(actual, expected):
        return True
    return any(term in (actual or "") for term in _body_match_terms(expected))


def _processing_visible(page) -> bool:
    for text in PROCESSING_TEXTS:
        try:
            loc = page.get_by_text(text, exact=False)
            count = loc.count()
            if count == 0:
                continue
            # Some pages contain many hidden/template matches. Scan more than a
            # handful and also check the tail where transient toasts often live.
            head = min(count, 30)
            for i in range(head):
                if loc.nth(i).is_visible():
                    return True
            tail_start = max(0, count - 10)
            for i in range(count - 1, tail_start - 1, -1):
                if i < head:
                    break
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


def _upload_in_progress(page) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                () => {
                  const selectors = [
                    '.upload-item .loading-box',
                    '.upload-item .loading-container',
                    '.upload-item .loading-spinner',
                    '.upload-item .upload-layer',
                    '.bg-loading',
                    '.loading-box',
                    '.loading-container',
                    '.loading-spinner'
                  ];
                  const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                      return false;
                    }
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                  };
                  for (const sel of selectors) {
                    const nodes = Array.from(document.querySelectorAll(sel));
                    if (nodes.some(isVisible)) return true;
                  }
                  return false;
                }
                """
            )
        )
    except Exception:
        return False


def _wait_for_processing_done(page, timeout_ms: int = 120000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if not _processing_visible(page) and not _upload_in_progress(page):
            return True
        time.sleep(1)
    return False


def _wait_for_upload_settle(
    page, *, settle_s: int = 5, timeout_ms: int = 180000
) -> bool:
    if settle_s <= 0:
        return True
    deadline = time.time() + timeout_ms / 1000
    stable = 0
    while time.time() < deadline:
        if _upload_in_progress(page) or _processing_visible(page):
            stable = 0
        else:
            stable += 1
            if stable >= settle_s:
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
    headless: Optional[bool] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Execution:
    exec_rec = execution or Execution(post_id=post.id, result="pending")
    steps: List[StepResult] = []

    def _step(name: str, status: str, detail: str = ""):
        steps.append(StepResult(name=name, status=status, detail=detail))
        _emit_progress(progress_callback, name, status, detail)

    assets = [str(Path(p)) for p in (assets or []) if Path(p).is_file()]
    context = None
    should_close_context = True

    try:
        profile_dir, channel, args = _resolve_profile_config()
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless_value = _resolve_headless(headless)
        if headless_value and login_hold > 0:
            _emit_progress(
                progress_callback,
                "headless_login",
                "warning",
                "headless requires an already logged-in profile; login_hold cannot show QR/captcha",
            )

        _step("launch", "in_progress", f"{profile_dir} | headless={headless_value}")
        with sync_playwright() as p:
            cdp_url = _resolve_cdp_url()
            if cdp_url:
                # Attach to an existing Chrome instance (recommended when the profile is already open).
                context = None
                browser = p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                should_close_context = False
                steps[-1].detail = f"cdp={cdp_url}"
            else:
                launch_kwargs = {"headless": headless_value}
                if channel:
                    launch_kwargs["channel"] = channel
                if args:
                    launch_kwargs["args"] = args
                context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
            context.set_default_timeout(30000)
            steps[-1].status = "success"
            try:
                # In CDP mode, avoid hijacking an existing tab (e.g. ChatGPT page); open a new one.
                page = context.new_page() if not should_close_context else (context.pages[0] if context.pages else context.new_page())
                _step("open_page", "in_progress", TARGET_URL)
                page.goto(TARGET_URL, wait_until="domcontentloaded")
                steps[-1].status = "success"

                _step("login_check", "in_progress", f"login_hold={login_hold}s")
                steps[-1].detail = _wait_for_xhs_ready(
                    page,
                    login_hold=login_hold,
                    headless=headless_value,
                    progress_callback=progress_callback,
                )
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
                editor_visible_selectors = EDITOR_READY_SELECTORS + ["input[type='file']"]
                try:
                    editor_sel = _wait_for_any_locator(
                        page, editor_visible_selectors, 120000
                    )
                except PlaywrightTimeoutError:
                    # New publish page keeps file input hidden; accept attached
                    # input as a valid ready signal when visible controls are delayed.
                    attached_sel = _wait_for_any_locator(
                        page, UPLOAD_INPUT_SELECTORS, 30000, state="attached"
                    )
                    editor_sel = f"{attached_sel} (attached)"
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
                    confirmed = _wait_for_upload_ready(
                        page,
                        len(assets),
                        progress_callback=progress_callback,
                    )
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
                    settle_s = int(os.getenv("XHS_UPLOAD_SETTLE_S") or 5)
                    settle_timeout_s = float(os.getenv("XHS_UPLOAD_SETTLE_TIMEOUT_S") or 180.0)
                    _step(
                        "wait_for_upload_settle",
                        "in_progress",
                        f"{settle_s}s timeout={int(settle_timeout_s)}s",
                    )
                    settled = _wait_for_upload_settle(
                        page,
                        settle_s=settle_s,
                        timeout_ms=int(max(1.0, settle_timeout_s) * 1000),
                    )
                    steps[-1].detail = f"settled={settled}"
                    if not settled:
                        raise RuntimeError("upload not settled")
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
                fill_settle_s = float(os.getenv("XHS_FILL_SETTLE_S") or 2.0)
                if v_title and v_body and fill_settle_s > 0:
                    time.sleep(fill_settle_s)
                    v_title, v_body = _verify_title_body(page, post.title, post.body)
                steps[-1].detail = f"title={v_title} body={v_body}"
                if not (v_title and v_body):
                    raise RuntimeError("title/body not filled")
                steps[-1].status = "success"

                _step("snapshot_after_fill", "in_progress", "")
                after_fill = ev_dir / "after_fill.png"
                page.screenshot(path=str(after_fill), full_page=True)
                steps[-1].detail = f"saved to {after_fill}"
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
                    if _click_first(page.get_by_role("button", name=text), timeout_ms=2000):
                        leave_clicked = True
                        break
                    if _click_first(page.locator(f"button:has-text('{text}')"), timeout_ms=2000):
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
                for _ in range(30):
                    after_count = _extract_draft_count(page)
                    if (
                        before_count is not None
                        and after_count is not None
                        and after_count > before_count
                    ):
                        ok = True
                        break
                    time.sleep(1)
                fallback_opened = False
                fallback_exists = False
                if not ok:
                    try:
                        fallback_opened = _open_draft_box(page)
                        if fallback_opened:
                            _open_image_draft_tab(page)
                            page.locator(DRAFT_ITEM_SELECTOR).first.wait_for(timeout=30000)
                            fallback_exists = _draft_item_exists(page, post.title)
                            ok = fallback_exists
                    except Exception:
                        fallback_exists = False
                steps[-1].detail = (
                    f"toast={toast or 'none'} before={before_count} after={after_count} "
                    f"fallback_opened={fallback_opened} fallback_exists={fallback_exists}"
                )
                if not ok:
                    raise RuntimeError("draft save verification failed")
                steps[-1].status = "success"

                _step("open_draft_box", "in_progress", "")
                opened = _open_draft_box(page)
                steps[-1].detail = f"opened={opened}"
                if not opened:
                    raise RuntimeError("draft box not opened after save")
                steps[-1].status = "success"

                _step("open_draft_tab", "in_progress", "")
                opened_tab = _open_image_draft_tab(page)
                steps[-1].detail = f"opened={opened_tab}"
                if not opened_tab:
                    raise RuntimeError("image draft tab not opened after save")
                steps[-1].status = "success"

                _step("wait_for_draft_items", "in_progress", "")
                try:
                    page.locator(DRAFT_ITEM_SELECTOR).first.wait_for(timeout=30000)
                    steps[-1].detail = "ready"
                    steps[-1].status = "success"
                except PlaywrightTimeoutError:
                    raise RuntimeError("draft items not visible after save")

                _step("wait_for_draft_cover", "in_progress", "")
                cover_ready = False
                try:
                    cover_ready = _wait_for_draft_cover(page, post.title)
                    steps[-1].detail = f"ready={cover_ready}"
                    steps[-1].status = "success" if cover_ready else "skipped"
                except Exception as exc:
                    steps[-1].detail = f"error: {exc}"
                    steps[-1].status = "skipped"

                _step("snapshot_draft_box", "in_progress", "")
                try:
                    draft_shot = ev_dir / "draft_box.png"
                    page.screenshot(path=str(draft_shot), full_page=True)
                    steps[-1].detail = f"saved to {draft_shot}"
                    steps[-1].status = "success"
                except Exception as exc:
                    steps[-1].detail = f"error: {exc}"
                    steps[-1].status = "skipped"

                _step("html_draft_box", "in_progress", "")
                try:
                    draft_html = ev_dir / "draft_box.html"
                    draft_html.write_text(page.content(), encoding="utf-8")
                    steps[-1].detail = f"saved to {draft_html}"
                    steps[-1].status = "success"
                except Exception as exc:
                    steps[-1].detail = f"error: {exc}"
                    steps[-1].status = "skipped"

                _step("verify_draft_box_item", "in_progress", "")
                verified_title = _draft_item_exists(page, post.title)
                verified_cover = _draft_item_has_cover(page, post.title) if verified_title else False
                steps[-1].detail = f"verified_title={verified_title} cover_ready={verified_cover}"
                if not verified_title:
                    raise RuntimeError("draft title not found after save")
                steps[-1].status = "success"
                exec_rec.result = "saved_draft"
                _emit_progress(progress_callback, "save_draft_chain", "success", post.id)
            finally:
                if should_close_context:
                    context.close()
    except Exception as exc:  # pragma: no cover
        exec_rec.result = "failed"
        exec_rec.error = {"message": str(exc)}
        _emit_progress(progress_callback, "save_draft_chain", "failed", str(exc))
    finally:
        exec_rec.steps = steps
        save_execution(exec_rec)

    return exec_rec


def run_delete_drafts_sync(
    *,
    draft_type: str = "image",
    draft_location: str = "publish",
    draft_url: str = "",
    limit: int = 0,
    dry_run: bool = False,
    login_hold: int = 0,
    wait_timeout_ms: int = WAIT_TIMEOUT_MS,
    headless: Optional[bool] = None,
) -> dict:
    result = {
        "draft_type": draft_type,
        "draft_location": draft_location,
        "draft_url": draft_url or "",
        "total": 0,
        "deleted": 0,
        "items": [],
        "errors": [],
    }
    evidence_dir: Optional[Path] = None

    profile_dir, channel, args = _resolve_profile_config()
    profile_dir.mkdir(parents=True, exist_ok=True)
    headless_value = _resolve_headless(headless)

    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": headless_value}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = args
            context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
            context.set_default_timeout(30000)
            page = context.pages[0] if context.pages else context.new_page()
            location = (draft_location or "publish").strip().lower()
            failure_count = 0

            def _ensure_evidence_dir() -> Path:
                nonlocal evidence_dir
                if evidence_dir is None:
                    evidence_dir = _repo_root() / "data" / "events" / f"delete_{uuid.uuid4().hex}"
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                return evidence_dir

            def _capture_delete_failure(label: str) -> None:
                nonlocal failure_count
                failure_count += 1
                ev_dir = _ensure_evidence_dir()
                tag = f"{label}_{failure_count}"
                try:
                    page.screenshot(path=str(ev_dir / f"{tag}.png"), full_page=True)
                except Exception:
                    pass
                try:
                    (ev_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
                except Exception:
                    pass

            def _goto_draft_page(dtype: str) -> None:
                if location == "publish":
                    if dtype == "image":
                        page.goto(TARGET_URL, wait_until="domcontentloaded")
                    elif dtype == "video":
                        page.goto(
                            "https://creator.xiaohongshu.com/publish/publish?target=video",
                            wait_until="domcontentloaded",
                        )
                    else:
                        page.goto(
                            "https://creator.xiaohongshu.com/publish/publish?target=article",
                            wait_until="domcontentloaded",
                        )
                    return
                if not draft_url:
                    raise RuntimeError("draft_url is required when draft_location != publish")
                page.goto(draft_url, wait_until="domcontentloaded")

            def _collect_for_type(dtype: str) -> list[dict[str, str]]:
                _goto_draft_page(dtype)

                _wait_for_xhs_ready(
                    page,
                    login_hold=login_hold,
                    headless=headless_value,
                )
                if location == "publish":
                    _wait_for_any_text(page, WAIT_TEXTS, wait_timeout_ms)
                    if not _open_draft_box(page):
                        raise RuntimeError("draft box not found")
                    if not _open_draft_tab(page, dtype):
                        raise RuntimeError(f"draft tab not found for type={dtype}")
                else:
                    try:
                        _wait_for_any_text(page, WAIT_TEXTS, min(wait_timeout_ms, 15000))
                    except PlaywrightTimeoutError:
                        pass
                    opened_box = _open_draft_box(page)
                    opened_tab = _open_draft_tab(page, dtype)
                    if not opened_tab and page.locator(DRAFT_ITEM_SELECTOR).count() == 0:
                        if opened_box:
                            raise RuntimeError(f"draft tab not found for type={dtype}")
                deadline = time.time() + 30
                while time.time() < deadline:
                    if page.locator(DRAFT_ITEM_SELECTOR).count() > 0:
                        break
                    time.sleep(1)
                return _collect_draft_items(page, limit=None)

            if dry_run:
                total_items = _collect_for_type(draft_type)
                result["total"] = len(total_items)
                if limit and limit > 0:
                    result["items"] = total_items[:limit]
                else:
                    result["items"] = total_items
                return result

            def _delete_for_type(dtype: str) -> None:
                total_items = _collect_for_type(dtype)
                result["total"] = len(total_items)
                if limit and limit > 0:
                    result["items"] = total_items[:limit]
                else:
                    result["items"] = total_items

                target = len(result["items"])
                deleted_titles: list[str] = []
                for _ in range(target):
                    before = page.locator(DRAFT_ITEM_SELECTOR).count()
                    if before == 0:
                        break
                    try:
                        before_title = (
                            page.locator(DRAFT_ITEM_SELECTOR)
                            .first.locator(".draft-title-text")
                            .first.text_content()
                            or ""
                        ).strip()
                    except Exception:
                        before_title = ""
                    try:
                        before_time = (
                            page.locator(DRAFT_ITEM_SELECTOR)
                            .first.locator(".draft-time")
                            .first.text_content()
                            or ""
                        ).strip()
                    except Exception:
                        before_time = ""
                    before_key = f"{before_title}|{before_time}" if before_title or before_time else ""
                    before_total = _extract_draft_count(page)
                    ok, title = _delete_first_draft_item(page)
                    if not ok:
                        result["errors"].append(title)
                        _capture_delete_failure("delete_error")
                        break
                    changed = _wait_for_draft_list_change(
                        page,
                        before_count=before,
                        before_title=before_title,
                        before_key=before_key,
                        before_total=before_total,
                        timeout_s=10,
                    )
                    if not changed and title:
                        if not _draft_item_exists(page, title):
                            changed = True
                    if not changed:
                        result["errors"].append(f"delete timeout: {title}")
                        _capture_delete_failure("delete_timeout")
                        break
                    deleted_titles.append(title)
                result["deleted"] = len(deleted_titles)
                result["deleted_titles"] = deleted_titles

            _delete_for_type(draft_type)
            if evidence_dir is not None:
                result["evidence_dir"] = str(evidence_dir)

            event_path = save_event(
                {
                    "type": "delete_drafts",
                    "draft_type": draft_type,
                    "dry_run": dry_run,
                    "profile_dir": str(profile_dir),
                    "summary": result,
                }
            )
            result["event_path"] = str(event_path)
            return result
    except Exception as exc:
        result["errors"].append(str(exc))
        return result


def run_collect_published_metrics_sync(
    *,
    limit: int = 0,
    login_hold: int = 0,
    wait_timeout_ms: int = WAIT_TIMEOUT_MS,
    headless: Optional[bool] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    result: dict[str, Any] = {
        "total": 0,
        "items": [],
        "errors": [],
        "urls_tried": [],
    }
    profile_dir, channel, args = _resolve_profile_config()
    profile_dir.mkdir(parents=True, exist_ok=True)
    headless_value = _resolve_headless(headless)
    max_scrolls = max(1, int(os.getenv("XHS_METRICS_MAX_SCROLLS") or "30"))

    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": headless_value}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = args
            context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
            context.set_default_timeout(30000)
            page = context.pages[0] if context.pages else context.new_page()
            collected_cards: list[dict[str, str]] = []

            try:
                for url in _published_url_candidates():
                    result["urls_tried"].append(url)
                    _emit_progress(progress_callback, "open_metrics_page", "in_progress", url)
                    page.goto(url, wait_until="domcontentloaded")
                    _wait_for_xhs_ready(
                        page,
                        login_hold=login_hold,
                        headless=headless_value,
                        progress_callback=progress_callback,
                    )
                    try:
                        _wait_for_any_text(page, PUBLISHED_PAGE_TEXTS, min(wait_timeout_ms, 30000))
                    except PlaywrightTimeoutError:
                        # Some creator pages render metrics without the exact Chinese labels above.
                        pass

                    previous_height = 0
                    for scroll_idx in range(max_scrolls):
                        cards = _collect_published_metric_cards(page)
                        if cards:
                            collected_cards.extend(cards)
                            metrics = _merge_published_metric_cards(collected_cards, limit=limit)
                            _emit_progress(
                                progress_callback,
                                "collect_metrics",
                                "in_progress",
                                f"items={len(metrics)} scroll={scroll_idx + 1}/{max_scrolls}",
                            )
                            if limit and len(metrics) >= limit:
                                break
                        try:
                            current_height = int(page.evaluate("() => document.body.scrollHeight") or 0)
                            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                            if current_height and current_height == previous_height and scroll_idx >= 2:
                                break
                            previous_height = current_height
                        except Exception:
                            break
                        time.sleep(1)

                    metrics = _merge_published_metric_cards(collected_cards, limit=limit)
                    if metrics:
                        result["items"] = [metric.model_dump() for metric in metrics]
                        result["total"] = len(metrics)
                        break

                if not result["items"]:
                    result["errors"].append(
                        "no published metrics found; check login profile or set XHS_PUBLISHED_URL to the note management page"
                    )
                event_path = save_event(
                    {
                        "type": "published_metrics",
                        "profile_dir": str(profile_dir),
                        "headless": headless_value,
                        "summary": {
                            "total": result["total"],
                            "urls_tried": result["urls_tried"],
                            "errors": result["errors"],
                        },
                    }
                )
                result["event_path"] = str(event_path)
                _emit_progress(progress_callback, "collect_metrics", "success", f"total={result['total']}")
                return result
            finally:
                context.close()
    except Exception as exc:
        result["errors"].append(str(exc))
        _emit_progress(progress_callback, "collect_metrics", "failed", str(exc))
        return result
