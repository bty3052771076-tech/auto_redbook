from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.storage.files import evidence_dir

CHATGPT_IMAGES_URL = "https://chatgpt.com/images"

DEFAULT_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_PROFILE_DIRNAME = "Default1"


@dataclass(frozen=True)
class ChatGPTImageResult:
    path: Path
    meta: dict[str, Any]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _truthy_env(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def _resolve_profile_name() -> str:
    name = (os.getenv("CHATGPT_CHROME_PROFILE") or DEFAULT_PROFILE_DIRNAME).strip()
    return name or DEFAULT_PROFILE_DIRNAME


def _resolve_cdp_url() -> str | None:
    """
    Optional: attach to an existing user-launched Chrome via CDP.

    Use cases:
    - User opens https://chatgpt.com/images manually (and passes any checks).
    - Script attaches and continues without re-triggering checks by relaunching.

    Env:
      - CHATGPT_CDP_URL: e.g. "http://127.0.0.1:9222" (or just "9222")
    """
    raw = (os.getenv("CHATGPT_CDP_URL") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return f"http://127.0.0.1:{raw}"
    return raw


def _resolve_profile() -> tuple[Path, str, list[str], Optional[str]]:
    """
    Resolve persistent Chrome profile settings for ChatGPT Images.

    Returns:
      - user_data_dir path
      - channel name (optional; "chrome" is typical on Windows)
      - extra args (profile-directory)
      - executable_path (optional)
    """
    user_data_dir = (os.getenv("CHATGPT_CHROME_USER_DATA_DIR") or "").strip()
    profile_dir = (
        Path(user_data_dir)
        if user_data_dir
        else _repo_root() / "data" / "browser" / "chrome-profile"
    )

    profile_name = _resolve_profile_name()
    args = [f"--profile-directory={profile_name}"] if profile_name else []

    # Prefer an explicit executable_path when provided, otherwise fall back to Playwright channel.
    exe = (os.getenv("CHATGPT_CHROME_EXECUTABLE") or "").strip()
    if not exe:
        if Path(DEFAULT_CHROME_EXE).is_file():
            exe = DEFAULT_CHROME_EXE

    channel = (os.getenv("CHATGPT_BROWSER_CHANNEL") or "chrome").strip() if not exe else ""
    return profile_dir, channel, args, exe or None


def build_chatgpt_image_prompt(
    *,
    title: str,
    body: str,
    topics: list[str],
    prompt_hint: str,
) -> str:
    """
    Build a safe, stable prompt for ChatGPT Images.

    Goal: relevance to the news topic while avoiding invented facts and
    recognizable real-person likeness.
    """
    title_norm = (title or "").strip()
    hint_norm = (prompt_hint or "").strip()
    topic_norm = "、".join([t.strip() for t in topics if t.strip()][:6])

    # Reduce "每日新闻" noise if present.
    for noise in ("每日新闻｜", "每日新闻", "每日假新闻"):
        if title_norm.startswith(noise):
            title_norm = title_norm[len(noise) :].strip(" ｜-—:：")
            break
    if hint_norm in ("每日新闻", "每日假新闻"):
        hint_norm = ""

    core = hint_norm or title_norm or "当日热点新闻"
    extra = f"话题：{topic_norm}" if topic_norm else ""

    return "\n".join(
        [
            "请生成一张与以下新闻主题高度相关的竖版配图（3:4）。",
            f"新闻主题：{core}",
            extra,
            "",
            "风格：现代新闻插画 / editorial illustration，清爽、专业、适合资讯类封面。",
            "构图：主体居中，留白适中，画面信息明确但不拥挤。",
            "要求：",
            "- 不要出现任何文字、字幕、水印、logo、品牌标识",
            "- 不要生成可识别的真实人物肖像（如涉及公众人物，用抽象符号/剪影/背影表达）",
            "- 不要捏造具体数字/地点/时间线等细节；用象征元素表达主题即可",
            "- 画面干净，高清，细节清晰",
        ]
    ).strip()


def _is_login_required(page) -> bool:
    try:
        btn = page.get_by_role("button", name="登录")
        if btn.count() > 0 and btn.first.is_visible():
            return True
    except Exception:
        pass
    return False


def _is_cloudflare_challenge(page) -> bool:
    # If the prompt box is visible and enabled, we are not blocked.
    try:
        if _find_prompt_box(page) is not None:
            return False
    except Exception:
        pass

    try:
        url = (page.url or "").lower()
        if "__cf_chl" in url or "/cdn-cgi/" in url:
            return True
    except Exception:
        pass

    # Cloudflare interstitials often use a distinct title.
    try:
        title = (page.title() or "").lower()
        if "cloudflare" in title or "just a moment" in title or "attention required" in title:
            return True
    except Exception:
        pass

    # Common Cloudflare challenge DOM markers.
    try:
        markers = [
            "input[name='cf-turnstile-response']",
            "iframe[src*='turnstile']",
            "#cf-challenge-running",
            "#cf-please-wait",
            "form#challenge-form",
            ".cf-challenge",
            ".challenge-form",
        ]
        for sel in markers:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                return True
    except Exception:
        pass
    try:
        html = page.content()
        # Avoid false positives: some sites embed Cloudflare scripts even when not blocked.
        if "__cf_chl" in html:
            return True
    except Exception:
        pass
    return False


def _find_prompt_box(page):
    # Prefer ChatGPT Images prompt box (contenteditable ProseMirror).
    selectors = [
        "#prompt-textarea",
        "div.ProseMirror[contenteditable='true']",
        "div[contenteditable='true']",
        "textarea",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 8)):
                item = loc.nth(i)
                if item.is_visible() and item.is_enabled():
                    return item
        except Exception:
            continue
    return None


def _find_existing_images_page(context):
    try:
        pages = list(context.pages)
    except Exception:
        pages = []
    for pg in pages:
        try:
            if (pg.url or "").startswith(CHATGPT_IMAGES_URL):
                return pg
        except Exception:
            continue
    return None


def _box_text(locator) -> str:
    if locator is None:
        return ""
    try:
        tag = (locator.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag = ""
    if tag == "textarea":
        try:
            return (locator.input_value() or "").strip()
        except Exception:
            return ""
    try:
        return (locator.inner_text() or "").strip()
    except Exception:
        try:
            return (locator.text_content() or "").strip()
        except Exception:
            return ""


def _click_send_if_present(page) -> bool:
    candidates = [
        "button[aria-label*='Send']",
        "button[aria-label*='Send message']",
        "button[aria-label*='发送']",
        "button[aria-label*='发送消息']",
        "button[data-testid='send-button']",
        "button:has-text('发送')",
        "button:has-text('Send')",
        "button:has-text('生成')",
        "button:has-text('创建')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            for i in range(min(loc.count(), 6)):
                btn = loc.nth(i)
                if not btn.is_visible() or not btn.is_enabled():
                    continue
                btn.click()
                return True
        except Exception:
            continue
    return False


def _snapshot(page, *, post_id: str, run_id: str, name: str) -> None:
    if page is None:
        return
    ev = evidence_dir(post_id, run_id)
    ev.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(ev / f"{name}.png"), full_page=True)
    except Exception:
        pass
    try:
        (ev / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def _open_images_in_normal_chrome(*, exe: str, profile_dir: Path, profile_name: str) -> None:
    """
    Open ChatGPT Images in a normal Chrome window (not controlled by Playwright).

    This does NOT bypass security checks; it simply opens the page for manual use.
    """
    cmd = [
        exe,
        f"--user-data-dir={str(profile_dir)}",
    ]
    if profile_name:
        cmd.append(f"--profile-directory={profile_name}")
    cmd.append(CHATGPT_IMAGES_URL)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Best effort only; the caller will still print prompt and wait for user input.
        return


def _wait_for_manual_image(
    *,
    dest_dir: Path,
    baseline: set[Path],
    timeout_s: float,
) -> Path | None:
    deadline = time.time() + max(1.0, timeout_s)
    patterns = ["*.png", "*.jpg", "*.jpeg", "*.webp"]
    min_size = 10_000
    while time.time() < deadline:
        candidates: list[Path] = []
        for pat in patterns:
            candidates.extend(dest_dir.glob(pat))
        new_files = [
            p
            for p in candidates
            if p.is_file() and p.resolve() not in baseline and p.stat().st_size >= min_size
        ]
        if new_files:
            return max(new_files, key=lambda p: p.stat().st_mtime)
        time.sleep(1)
    return None


def generate_chatgpt_image_manual(
    *,
    post_id: str,
    prompt: str,
    dest_dir: Path,
    timeout_s: float = 1800.0,
) -> ChatGPTImageResult:
    """
    Manual fallback: open ChatGPT Images in a normal Chrome window and wait for the user to
    generate/download an image into dest_dir.

    This is used when automation is blocked by Cloudflare or similar checks.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"ai_{uuid.uuid4().hex}"

    profile_dir, _channel, _args, exe = _resolve_profile()
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_name = _resolve_profile_name()

    ev = evidence_dir(post_id, run_id)
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "manual_prompt.txt").write_text(prompt, encoding="utf-8")

    baseline: set[Path] = set()
    for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        baseline.update([p.resolve() for p in dest_dir.glob(pat) if p.is_file()])

    if not exe:
        exe = DEFAULT_CHROME_EXE if Path(DEFAULT_CHROME_EXE).is_file() else ""
    if exe:
        _open_images_in_normal_chrome(exe=exe, profile_dir=profile_dir, profile_name=profile_name)

    msg = "\n".join(
        [
            "",
            "ChatGPT Images 自动化被拦截，进入【手动生图】模式：",
            f"- 已打开：{CHATGPT_IMAGES_URL}（使用 profile: {profile_name}）",
            f"- 请将下面提示词粘贴到页面并生成图片：",
            "",
            prompt,
            "",
            f"- 生成后请把下载的图片（png/jpg/webp，>=10KB）放到目录：{dest_dir}",
            f"- 我会等待你放入图片（最多 {int(timeout_s)} 秒）...",
            "",
        ]
    )
    print(msg, file=sys.stderr, flush=True)

    picked = _wait_for_manual_image(dest_dir=dest_dir, baseline=baseline, timeout_s=timeout_s)
    if picked is None:
        raise RuntimeError("手动生图超时：未在目标目录检测到新图片文件")

    meta: dict[str, Any] = {
        "mode": "chatgpt_images_manual",
        "provider": "chatgpt_images",
        "prompt": prompt,
        "downloaded_path": str(picked),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "method": "manual",
        "evidence_dir": str(ev),
        "source_url": CHATGPT_IMAGES_URL,
        "profile": {"user_data_dir": str(profile_dir), "profile_directory": profile_name},
    }
    return ChatGPTImageResult(path=picked, meta=meta)


def _pick_new_image_locator(page, before_srcs: set[str]):
    # Fast path: mark the "best" new image in the DOM and return it.
    # ChatGPT Images pages may contain many <img> nodes; the generated image is usually the largest visible one.
    try:
        src = page.evaluate(
            """
            (before) => {
              const beforeSet = new Set(before || []);
              const imgs = Array.from(document.querySelectorAll('img'));
              for (const img of imgs) img.removeAttribute('data-rb-pick');

              let best = null;
              let bestScore = 0;
              for (const img of imgs) {
                const src = (img.currentSrc || img.src || '').trim();
                if (!src || beforeSet.has(src)) continue;

                const rect = img.getBoundingClientRect();
                if ((rect.width || 0) < 120 || (rect.height || 0) < 120) continue;

                const style = window.getComputedStyle(img);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                const nw = img.naturalWidth || 0;
                const nh = img.naturalHeight || 0;
                if (nw < 256 || nh < 256) continue;

                const score = rect.width * rect.height;
                if (score > bestScore) {
                  best = img;
                  bestScore = score;
                }
              }

              if (!best) return '';
              best.setAttribute('data-rb-pick', '1');
              return (best.currentSrc || best.src || '').trim();
            }
            """,
            list(before_srcs),
        )
        if isinstance(src, str) and src.strip() and not _is_placeholder_src(src):
            loc = page.locator("img[data-rb-pick='1']")
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
    except Exception:
        pass

    # Fallback: scan images (limit to a reasonable tail to avoid huge pages).
    try:
        imgs = page.locator("img").all()
    except Exception:
        return None
    for img in reversed(imgs[-300:]):
        try:
            src = (img.evaluate("el => el.currentSrc || el.src || ''") or "").strip()
            if not src or src in before_srcs:
                continue
            if _is_placeholder_src(src):
                continue
            if not img.is_visible():
                continue
            try:
                loaded = bool(img.evaluate("el => !!el.complete && (el.naturalWidth || 0) > 0"))
            except Exception:
                continue
            if not loaded:
                continue
            try:
                dims = img.evaluate("el => [el.naturalWidth || 0, el.naturalHeight || 0]") or [0, 0]
                w = int(dims[0] or 0)
                h = int(dims[1] or 0)
                if w < 256 or h < 256:
                    continue
            except Exception:
                continue
            return img
        except Exception:
            continue
    return None


def _collect_img_srcs(page, *, limit: int = 200) -> set[str]:
    out: set[str] = set()
    try:
        values = page.evaluate(
            f"""() => Array.from(document.querySelectorAll('img'))
              .map(img => img.currentSrc || img.src || '')
              .filter(Boolean)
              .slice(0, {int(limit)})"""
        )
        for src in values or []:
            if isinstance(src, str) and src.strip():
                out.add(src.strip())
    except Exception:
        return out
    return out


def _fill_prompt(page, box, prompt: str) -> bool:
    prompt = (prompt or "").strip()
    if not prompt:
        return False

    try:
        tag = (box.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag = ""
    try:
        is_contenteditable = bool(box.evaluate("el => !!el.isContentEditable"))
    except Exception:
        is_contenteditable = False

    box.click()
    filled = False

    if tag in ("textarea", "input"):
        try:
            box.fill(prompt)
            filled = bool(_box_text(box))
        except Exception:
            filled = False

    if not filled and is_contenteditable:
        try:
            # Prefer real typing for ChatGPT's ProseMirror editor; direct DOM assignment
            # may not update the app state (the submit button can stay in "voice" mode).
            box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            try:
                # Insert text like paste (doesn't press Enter). This avoids accidentally
                # sending the prompt early when it contains newlines.
                page.keyboard.insert_text(prompt)
            except Exception:
                page.keyboard.type(prompt, delay=5)
            filled = bool(_box_text(box))
        except Exception:
            filled = False

    if not filled:
        try:
            page.keyboard.press("Control+A")
            page.keyboard.type(prompt, delay=5)
            filled = bool(_box_text(box))
        except Exception:
            filled = False

    return filled


def _send_prompt(page, box) -> None:
    before = _box_text(box)
    if not before:
        raise RuntimeError("提示词为空，无法发送")

    # 先尝试按钮发送（部分页面 Enter 只换行）。
    if _click_send_if_present(page):
        return

    try:
        box.press("Enter")
    except Exception:
        pass

    time.sleep(0.6)
    after = _box_text(box)
    if after and after.strip() == before.strip():
        # 再尝试 Ctrl+Enter + 兜底按钮
        try:
            box.press("Control+Enter")
        except Exception:
            pass
        time.sleep(0.6)
        after2 = _box_text(box)
        if after2 and after2.strip() == before.strip():
            if not _click_send_if_present(page):
                raise RuntimeError("未能触发生成（发送按钮/快捷键均失败）")


def _wait_for_prompt_box(page, *, timeout_s: float) -> Any | None:
    deadline = time.time() + max(1.0, timeout_s)
    while time.time() < deadline:
        box = _find_prompt_box(page)
        if box is not None:
            return box
        time.sleep(1)
    return None


def _guess_ext_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"
    return ".png"


def _looks_like_html(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or head.startswith(b"<script")


def _parse_data_url(data_url: str) -> tuple[str, bytes] | None:
    raw = (data_url or "").strip()
    if not raw.startswith("data:"):
        return None
    try:
        header, payload = raw.split(",", 1)
    except ValueError:
        return None

    header = header[5:]
    is_base64 = ";base64" in header.lower()
    mime = header.split(";", 1)[0].strip() or "application/octet-stream"
    try:
        if is_base64:
            data = base64.b64decode(payload)
        else:
            data = urllib.parse.unquote_to_bytes(payload)
    except Exception:
        return None
    return mime, data


def _download_image_via_request(
    *,
    context,
    src_url: str,
    dest_dir: Path,
    base_name: str,
    timeout_s: float,
    min_bytes: int = 30_000,
) -> tuple[Path, dict[str, Any]]:
    """
    Download the generated image via Playwright APIRequestContext using auth cookies.

    This avoids capturing "blurred/in-progress" UI screenshots.
    """
    deadline = time.time() + max(5.0, timeout_s)
    last_err: Optional[str] = None

    # Some ChatGPT "src" values are placeholders (e.g. static cookie thumbnails). Reject known ones.
    blocked_substrings = [
        "persistent.oaistatic.com/images-app/",
        "sugar-cookie",
        "cookie.webp",
    ]
    if any(s in (src_url or "") for s in blocked_substrings):
        raise RuntimeError(f"blocked_placeholder_src: {src_url}")

    while time.time() < deadline:
        resp = None
        try:
            resp = context.request.get(src_url, timeout=30_000)
            status = resp.status
            ct = (resp.headers.get("content-type") or "").strip()
            data = resp.body()

            if status != 200:
                last_err = f"status={status}"
                time.sleep(1)
                continue

            if not data or len(data) < min_bytes:
                last_err = f"too_small={len(data) if data else 0}"
                time.sleep(1)
                continue

            if _looks_like_html(data):
                last_err = "got_html"
                time.sleep(1)
                continue

            ext = _guess_ext_from_content_type(ct)
            out_path = dest_dir / f"{base_name}{ext}"
            out_path.write_bytes(data)

            meta = {
                "method": "request_download",
                "content_type": ct,
                "bytes": len(data),
                "src_url": src_url,
            }
            return out_path, meta
        except Exception as exc:
            last_err = str(exc)
            time.sleep(1)
        finally:
            try:
                if resp is not None:
                    resp.dispose()
            except Exception:
                pass

    raise RuntimeError(f"下载生成图片超时（{int(timeout_s)}s）：{last_err or 'unknown'}")


def _download_image_via_page_fetch(
    *,
    page,
    src_url: str,
    dest_dir: Path,
    base_name: str,
    timeout_s: float,
    min_bytes: int = 30_000,
) -> tuple[Path, dict[str, Any]]:
    """
    Download the generated image by fetching its URL inside the page context.

    This supports blob: and data: URLs (where APIRequestContext cannot fetch).
    """
    parsed = _parse_data_url(src_url)
    if parsed is not None:
        ct, data = parsed
        if not data or len(data) < min_bytes:
            raise RuntimeError(f"data URL too small: {len(data) if data else 0}")
        ext = _guess_ext_from_content_type(ct)
        out_path = dest_dir / f"{base_name}{ext}"
        out_path.write_bytes(data)
        return out_path, {
            "method": "page_fetch_data_url",
            "content_type": ct,
            "bytes": len(data),
            "src_url": src_url,
        }

    deadline = time.time() + max(5.0, timeout_s)
    last_err: Optional[str] = None
    while time.time() < deadline:
        try:
            result = page.evaluate(
                """
                async (src) => {
                  try {
                    const res = await fetch(src);
                    const ct = res.headers.get('content-type') || '';
                    const buf = await res.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    const chunk = 8192;
                    for (let i = 0; i < bytes.length; i += chunk) {
                      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
                    }
                    const b64 = btoa(binary);
                    return { ok: true, ct, b64, size: bytes.length };
                  } catch (e) {
                    return { ok: false, error: String(e) };
                  }
                }
                """,
                src_url,
            )
            if not isinstance(result, dict) or not result.get("ok"):
                last_err = str(result.get("error") if isinstance(result, dict) else result)
                time.sleep(1)
                continue
            ct = str(result.get("ct") or "").strip()
            b64 = str(result.get("b64") or "")
            data = base64.b64decode(b64) if b64 else b""
            if not data or len(data) < min_bytes:
                last_err = f"too_small={len(data) if data else 0}"
                time.sleep(1)
                continue
            if _looks_like_html(data):
                last_err = "got_html"
                time.sleep(1)
                continue
            ext = _guess_ext_from_content_type(ct)
            out_path = dest_dir / f"{base_name}{ext}"
            out_path.write_bytes(data)
            return out_path, {
                "method": "page_fetch",
                "content_type": ct,
                "bytes": len(data),
                "src_url": src_url,
            }
        except Exception as exc:
            last_err = str(exc)
            time.sleep(1)

    raise RuntimeError(f"页面 fetch 下载超时（{int(timeout_s)}s）：{last_err or 'unknown'}")


def _is_placeholder_src(src_url: str) -> bool:
    src = (src_url or "").strip()
    if not src:
        return True
    if src.startswith("data:image/gif"):
        return True
    if src.startswith("data:image/svg"):
        return True
    if "persistent.oaistatic.com/images-app/" in src:
        return True
    if "sugar-cookie" in src or "cookie.webp" in src:
        return True
    return False


def generate_chatgpt_image(
    *,
    post_id: str,
    prompt: str,
    dest_dir: Path,
    timeout_s: float = 180.0,
) -> ChatGPTImageResult:
    """
    Generate a single image on https://chatgpt.com/images and save it to dest_dir.

    This uses a persistent Chrome profile; you must be logged in already.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"ai_{uuid.uuid4().hex}"

    profile_dir, channel, args, exe = _resolve_profile()
    profile_dir.mkdir(parents=True, exist_ok=True)

    headless = _truthy_env("CHATGPT_HEADLESS", default=False)
    cdp_url = _resolve_cdp_url()
    with sync_playwright() as p:
        browser = None
        context = None
        should_close_context = True
        if cdp_url:
            # Attach to an existing Chrome instance. Do NOT close the browser/context on exit.
            browser = p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            should_close_context = False
        else:
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "accept_downloads": True,
                "downloads_path": str(dest_dir),
            }
            if exe:
                launch_kwargs["executable_path"] = exe
            elif channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = args
            context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
        page = None
        try:
            context.set_default_timeout(30000)
            page = _find_existing_images_page(context) or (context.pages[0] if context.pages else context.new_page())

            # In CDP mode, prefer reusing an already opened images page to avoid re-triggering checks.
            if not cdp_url or not (page.url or "").startswith(CHATGPT_IMAGES_URL):
                try:
                    page.goto(CHATGPT_IMAGES_URL, wait_until="domcontentloaded")
                except Exception as exc:
                    if not cdp_url:
                        raise
                    _snapshot(page, post_id=post_id, run_id=run_id, name="goto_failed")
                    # Retry by reusing any existing images page or opening a fresh tab.
                    fallback = _find_existing_images_page(context)
                    if fallback is not None:
                        page = fallback
                    else:
                        page = context.new_page()
                        try:
                            page.goto(CHATGPT_IMAGES_URL, wait_until="domcontentloaded")
                        except Exception:
                            _snapshot(page, post_id=post_id, run_id=run_id, name="goto_failed_retry")
                            raise exc
            _snapshot(page, post_id=post_id, run_id=run_id, name="opened")

            if _is_cloudflare_challenge(page):
                _snapshot(page, post_id=post_id, run_id=run_id, name="cf_challenge")
                challenge_timeout_s = float(os.getenv("CHATGPT_CHALLENGE_TIMEOUT_S") or 180.0)
                deadline = time.time() + challenge_timeout_s
                while time.time() < deadline and _is_cloudflare_challenge(page):
                    time.sleep(2)
                if _is_cloudflare_challenge(page):
                    _snapshot(
                        page,
                        post_id=post_id,
                        run_id=run_id,
                        name="cf_challenge_timeout",
                    )
                    manual_timeout_s = float(os.getenv("CHATGPT_MANUAL_TIMEOUT_S") or 180.0)
                    if _truthy_env("CHATGPT_FALLBACK_MANUAL_ON_CHALLENGE", default=True):
                        # Close automation context first; then guide the user to generate the image manually.
                        if should_close_context:
                            try:
                                context.close()
                            except Exception:
                                pass
                        return generate_chatgpt_image_manual(
                            post_id=post_id,
                            prompt=prompt,
                            dest_dir=dest_dir,
                            timeout_s=manual_timeout_s,
                        )
                    raise RuntimeError(
                        "ChatGPT Images 被 Cloudflare 校验拦截：请在弹出的 Chrome 窗口里完成校验后重试。"
                    )

            if _is_login_required(page):
                _snapshot(page, post_id=post_id, run_id=run_id, name="login_required")
                raise RuntimeError(
                    "ChatGPT 未登录：请使用指定的 Chrome profile 手动登录后重试。"
                )

            box = _wait_for_prompt_box(
                page,
                timeout_s=float(os.getenv("CHATGPT_PROMPTBOX_TIMEOUT_S") or 60.0),
            )
            if box is None:
                _snapshot(page, post_id=post_id, run_id=run_id, name="no_prompt_box")
                raise RuntimeError("未找到 ChatGPT Images 提示词输入框（可能页面结构变更）")

            before_srcs = _collect_img_srcs(page)
            if not _fill_prompt(page, box, prompt):
                _snapshot(page, post_id=post_id, run_id=run_id, name="prompt_fill_failed")
                raise RuntimeError("提示词写入失败：输入框仍为空")

            try:
                _send_prompt(page, box)
            except Exception:
                _snapshot(page, post_id=post_id, run_id=run_id, name="send_failed")
                raise

            # Wait for new image to appear.
            deadline = time.time() + timeout_s
            picked = None
            last_err: Optional[str] = None
            while time.time() < deadline:
                try:
                    picked = _pick_new_image_locator(page, before_srcs)
                    if picked is not None:
                        break
                except Exception as exc:
                    last_err = str(exc)
                time.sleep(1)
            if picked is None:
                _snapshot(page, post_id=post_id, run_id=run_id, name="no_image")
                raise RuntimeError(f"等待生成图片超时（{timeout_s}s）：{last_err or 'no image'}")

            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            base_name = f"ai_chatgpt_{ts}"

            # Prefer downloading the real image bytes via authenticated request.
            src_url = ""
            try:
                src_url = (
                    picked.evaluate("el => el.currentSrc || el.src || ''") or ""
                ).strip()
            except Exception:
                src_url = ""

            download_timeout_s = max(30.0, float(os.getenv("CHATGPT_DOWNLOAD_TIMEOUT_S") or 120.0))

            method = "request_download"
            download_meta: dict[str, Any] = {"src_url": src_url}
            out_path: Path | None = None
            try:
                if src_url.startswith("http"):
                    out_path, download_meta2 = _download_image_via_request(
                        context=context,
                        src_url=src_url,
                        dest_dir=dest_dir,
                        base_name=base_name,
                        timeout_s=download_timeout_s,
                    )
                    download_meta.update(download_meta2)
                elif src_url.startswith(("blob:", "data:")):
                    out_path, download_meta2 = _download_image_via_page_fetch(
                        page=page,
                        src_url=src_url,
                        dest_dir=dest_dir,
                        base_name=base_name,
                        timeout_s=download_timeout_s,
                    )
                    method = str(download_meta2.get("method") or "page_fetch")
                    download_meta.update(download_meta2)
                else:
                    method = "screenshot"
                    out_path = dest_dir / f"{base_name}.png"
                    picked.screenshot(path=str(out_path))
            except Exception as exc:
                _snapshot(page, post_id=post_id, run_id=run_id, name="download_failed")
                method = "screenshot_fallback"
                out_path = dest_dir / f"{base_name}.png"
                try:
                    picked.screenshot(path=str(out_path))
                except Exception as exc2:
                    _snapshot(page, post_id=post_id, run_id=run_id, name="screenshot_failed")
                    raise RuntimeError(f"保存生成图片失败：{exc2}") from exc2
                download_meta["download_error"] = str(exc)

            if out_path is None or not out_path.exists() or out_path.stat().st_size < 10_000:
                _snapshot(page, post_id=post_id, run_id=run_id, name="file_too_small")
                raise RuntimeError("生成图片落盘异常：文件不存在或过小（可能仍在生成中）")

            meta: dict[str, Any] = {
                "mode": "chatgpt_images",
                "provider": "chatgpt_images",
                "prompt": prompt,
                "downloaded_path": str(out_path),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "method": method,
                **download_meta,
                "evidence_dir": str(evidence_dir(post_id, run_id)),
                "source_url": page.url,
            }
            _snapshot(page, post_id=post_id, run_id=run_id, name="done")
            return ChatGPTImageResult(path=out_path, meta=meta)
        except PlaywrightTimeoutError as exc:
            _snapshot(page, post_id=post_id, run_id=run_id, name="timeout")
            raise RuntimeError(f"ChatGPT Images 超时：{exc}") from exc
        finally:
            if should_close_context:
                try:
                    context.close()
                except Exception:
                    pass
