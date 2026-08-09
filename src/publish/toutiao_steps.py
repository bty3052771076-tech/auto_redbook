from __future__ import annotations

import os
import re
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from playwright.sync_api import sync_playwright

from src.storage.files import evidence_dir, save_execution
from src.storage.models import Execution, Post, StepResult, now_iso


TOUTIAO_PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
TOUTIAO_MANAGE_URL = "https://mp.toutiao.com/profile_v4/manage/content/all"
TOUTIAO_DRAFT_URL = "https://mp.toutiao.com/profile_v4/manage/draft"
TOUTIAO_TITLE_MAX_LENGTH = 30
TOUTIAO_WAIT_TIMEOUT_MS = 300_000
TOUTIAO_NAVIGATION_TIMEOUT_MS = 60_000
TOUTIAO_SAVE_ENDPOINT_HINTS = (
    "/mp/agw/article/publish",
    "/mp/agw/draft/save_ugc_draft",
)
TOUTIAO_TITLE_SELECTORS = (
    "textarea[placeholder*='标题']",
    "input[placeholder*='标题']",
    "textarea",
)
TOUTIAO_BODY_SELECTORS = (
    ".ProseMirror[contenteditable='true']",
    "div[contenteditable='true'][role='textbox']",
    "div[contenteditable='true']",
)
TOUTIAO_IMAGE_INPUT_SELECTORS = (
    "input[type='file'][accept*='image']",
    "input[type='file']",
)
TOUTIAO_IMAGE_TOOL_SELECTORS = (
    ".syl-toolbar-tool.image.static button",
    ".syl-toolbar-tool.image button",
)
TOUTIAO_LOGIN_HINTS = (
    "扫码登录",
    "手机号登录",
    "验证码登录",
    "登录头条号",
    "请登录",
)
TOUTIAO_SAVE_TEXTS = ("存草稿", "保存草稿")
TOUTIAO_SAVED_HINTS = ("已保存", "保存成功", "草稿已保存")
TOUTIAO_SMS_VERIFICATION_HINTS = (
    "头条号身份校验",
    "短信验证码",
    "验证码已发送",
    "绑定手机",
)
TOUTIAO_ACCOUNT_INCOMPLETE_HINT = "请完善账号信息，解锁发布文章、视频等权益功能"
TOUTIAO_MANAGE_READY_HINTS = ("作品管理", "草稿箱", "全部文章")


@dataclass(frozen=True)
class ToutiaoArticle:
    title: str
    body: str
    assets: tuple[str, ...]


@dataclass(frozen=True)
class ToutiaoDraftVerification:
    found: bool
    title_ok: bool
    body_ok: bool
    images_ok: bool
    cover_ok: bool
    expected_images: int
    actual_images: int
    actual_title: str = ""
    cover_source: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(
            self.found
            and self.title_ok
            and self.body_ok
            and self.images_ok
            and self.cover_ok
        )

    @property
    def failed_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        if not self.found:
            fields.append("草稿")
        if not self.title_ok:
            fields.append("标题")
        if not self.body_ok:
            fields.append("正文")
        if not self.images_ok:
            fields.append("图片")
        if not self.cover_ok:
            fields.append("封面")
        return tuple(fields)

    @property
    def detail(self) -> str:
        passed = lambda value: "通过" if value else "失败"
        parts = [
            f"草稿={passed(self.found)}",
            f"标题={passed(self.title_ok)}",
            f"正文={passed(self.body_ok)}",
            f"图片={passed(self.images_ok)}({self.actual_images}/{self.expected_images})",
            f"封面={passed(self.cover_ok)}",
        ]
        if self.actual_title:
            parts.append(f"回读标题={self.actual_title}")
        if self.cover_source:
            parts.append(f"封面依据={self.cover_source}")
        if self.error:
            parts.append(f"最后错误={self.error[:160]}")
        return " ".join(parts)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_toutiao_profile_config() -> tuple[Path, str | None, list[str]]:
    user_data_dir = (
        os.getenv("TOUTIAO_CHROME_USER_DATA_DIR")
        or os.getenv("XHS_CHROME_USER_DATA_DIR")
    )
    profile_dir = (
        Path(user_data_dir).expanduser()
        if user_data_dir
        else _repo_root() / "data" / "browser" / "chrome-profile"
    )
    channel = (
        os.getenv("TOUTIAO_BROWSER_CHANNEL")
        or os.getenv("XHS_BROWSER_CHANNEL")
        or "chrome"
    )
    profile_name = (
        os.getenv("TOUTIAO_CHROME_PROFILE")
        or os.getenv("XHS_CHROME_PROFILE")
        or ""
    ).strip()
    args = [f"--profile-directory={profile_name}"] if profile_name else []
    return profile_dir, channel, args


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_toutiao_headless(headless: Optional[bool]) -> bool:
    if headless is not None:
        return bool(headless)
    if os.getenv("TOUTIAO_HEADLESS") is not None:
        return _env_flag("TOUTIAO_HEADLESS")
    return _env_flag("XHS_HEADLESS")


def _resolve_toutiao_cdp_url() -> str | None:
    raw = (os.getenv("TOUTIAO_CDP_URL") or os.getenv("XHS_CDP_URL") or "").strip()
    if raw:
        if raw.isdigit():
            return f"http://127.0.0.1:{raw}"
        return raw
    if not _env_flag("TOUTIAO_AUTO_ATTACH_CDP", True):
        return None
    raw_port = (os.getenv("TOUTIAO_CDP_PORT") or "9223").strip()
    try:
        port = int(raw_port)
    except ValueError:
        return None
    if not 1024 <= port <= 65535:
        return None
    local_url = f"http://127.0.0.1:{port}"
    return local_url if _is_toutiao_cdp_available(local_url) else None


def _is_toutiao_cdp_available(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url.rstrip('/')}/json/version", timeout=0.4) as response:
            return int(getattr(response, "status", 200) or 200) == 200
    except Exception:
        return False


def _resolve_toutiao_sms_wait_seconds(*, login_hold: int, cdp_url: str | None) -> int:
    requested = max(0, int(login_hold or 0))
    if requested > 0 or not cdp_url:
        return requested
    raw = (os.getenv("TOUTIAO_SMS_WAIT_SECONDS") or "600").strip()
    try:
        return max(0, min(3600, int(raw)))
    except ValueError:
        return 600


def _emit_progress(
    callback: Optional[Callable[[str], None]],
    name: str,
    status: str,
    detail: str = "",
) -> None:
    if not callback:
        return
    message = f"[toutiao-upload] {name}: {status}"
    if detail:
        message += f" | {detail}"
    try:
        callback(message)
    except Exception:
        pass


def _visible_locator(page, selectors: tuple[str, ...], field_name: str):
    for selector in selectors:
        locator = page.locator(selector)
        count = locator.count()
        for index in range(count):
            item = locator.nth(index)
            try:
                if item.is_visible() and item.is_enabled():
                    return item, selector
            except Exception:
                continue
    raise RuntimeError(f"头条号编辑器未找到可用的{field_name}输入框")


def _open_toutiao_publish_page(page, *, wait_timeout_ms: int) -> None:
    timeout_ms = min(
        TOUTIAO_NAVIGATION_TIMEOUT_MS,
        max(30_000, int(wait_timeout_ms or 0)),
    )
    page.goto(TOUTIAO_PUBLISH_URL, wait_until="commit", timeout=timeout_ms)


def _page_visible_text(page) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=5_000) or "")
    except Exception:
        return ""


def _wait_for_toutiao_editor(
    page,
    *,
    login_hold: int,
    headless: bool,
    wait_timeout_ms: int,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    deadline = time.time() + max(30.0, wait_timeout_ms / 1000.0)
    login_deadline = time.time() + max(0, int(login_hold or 0))
    last_state = "页面加载中"
    while time.time() < deadline:
        try:
            _visible_locator(page, TOUTIAO_TITLE_SELECTORS, "标题")
            _visible_locator(page, TOUTIAO_BODY_SELECTORS, "正文")
            return f"state=ready url={page.url} title={page.title()}"
        except RuntimeError:
            text = _page_visible_text(page)
            login_required = any(hint in text for hint in TOUTIAO_LOGIN_HINTS)
            if login_required:
                last_state = "需要登录头条号"
                if headless:
                    raise RuntimeError(
                        "头条号登录状态无效：无窗口模式无法扫码或输入验证码；"
                        "请用共享 Profile 登录后关闭浏览器，再重试"
                    )
                if login_hold <= 0 or time.time() >= login_deadline:
                    raise RuntimeError("头条号登录状态无效，请完成登录后重试")
            else:
                last_state = f"等待图文编辑器 url={page.url}"
            _emit_progress(progress_callback, "login_check", "in_progress", last_state)
            time.sleep(1)
    raise RuntimeError(f"头条号图文编辑器等待超时：{last_state}")


def _ensure_toutiao_account_ready(page, *, wait_timeout_ms: int) -> str:
    timeout_ms = min(
        TOUTIAO_NAVIGATION_TIMEOUT_MS,
        max(30_000, int(wait_timeout_ms or 0)),
    )
    page.goto(TOUTIAO_MANAGE_URL, wait_until="commit", timeout=timeout_ms)
    deadline = time.time() + min(max(10.0, wait_timeout_ms / 1000.0), 30.0)
    last_text = ""
    while time.time() < deadline:
        last_text = _page_visible_text(page)
        if TOUTIAO_ACCOUNT_INCOMPLETE_HINT in last_text:
            raise RuntimeError(
                "头条号尚未开通文章发布权益：请在账号完善页面选择“大陆作者”，"
                "再使用今日头条 App 的“我的 → 设置 → 扫一扫”完成作者信息"
            )
        if any(hint in last_text for hint in TOUTIAO_LOGIN_HINTS):
            raise RuntimeError("头条号登录状态无效，请重新登录后再检查账号权益")
        if any(hint in last_text for hint in TOUTIAO_MANAGE_READY_HINTS):
            return f"state=ready url={page.url}"
        time.sleep(0.5)
    detail = re.sub(r"\s+", " ", last_text).strip()[:160]
    raise RuntimeError(f"头条号账号权益检查超时：{detail or page.url}")


def _ensure_toutiao_device_verified(page) -> str:
    try:
        skeleton = page.locator(".publish-draft-tip-wrapper.byte-skeleton")
        if skeleton.count() > 0:
            skeleton.first.wait_for(state="hidden", timeout=30_000)
    except Exception:
        pass
    try:
        result = page.evaluate(
            """
            async () => {
              const response = await fetch(
                '/mp/agw/article/new?article_type=0&format=json&compat=1&column_no=',
                { credentials: 'include' }
              );
              return await response.json();
            }
            """
        )
    except Exception as exc:
        return f"phone_permission=unknown error={str(exc)[:120]}"

    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return "phone_permission=unknown"
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    content_cache = (
        media.get("content_cache")
        if isinstance(media.get("content_cache"), dict)
        else {}
    )
    phone_permission = data.get("phone_permission")
    needs_sms = content_cache.get("send_not_authentication_sms") == 1
    if phone_permission is False and needs_sms:
        return (
            "phone_permission=False sms_verification_required=True; "
            "平台可能在保存时要求短信校验，且校验成功后该字段不会立即刷新；"
            "继续以实际保存响应和草稿箱回读为准"
        )
    return f"phone_permission={phone_permission} sms_verification_required={needs_sms}"


def _fill_toutiao_editor(page, title: str, body: str) -> tuple[bool, bool]:
    title_input, _ = _visible_locator(page, TOUTIAO_TITLE_SELECTORS, "标题")
    body_input, _ = _visible_locator(page, TOUTIAO_BODY_SELECTORS, "正文")
    title_input.fill(title)
    body_input.fill(body)
    try:
        title_ok = str(title_input.input_value() or "").strip() == title.strip()
    except Exception:
        title_ok = True
    try:
        body_text = str(body_input.inner_text() or body_input.text_content() or "")
        body_ok = re.sub(r"\s+", "", body) in re.sub(r"\s+", "", body_text)
    except Exception:
        body_ok = True
    return title_ok, body_ok


def _dismiss_toutiao_ai_assistant(page, *, wait_timeout_ms: int) -> None:
    drawer = page.locator(".ai-assistant-drawer")
    if drawer.count() == 0 or not drawer.first.is_visible():
        return
    close = page.locator(".ai-assistant-drawer .close-btn")
    if close.count() == 0 or not close.first.is_visible():
        raise RuntimeError("头条创作助手遮挡编辑器，且未找到关闭按钮")
    close.first.click()
    drawer.first.wait_for(
        state="hidden",
        timeout=min(max(3_000, wait_timeout_ms), 15_000),
    )


def _dismiss_toutiao_blocking_drawers(page) -> str:
    """Close visible creator drawers that can intercept declaration controls."""
    try:
        result = page.evaluate(
            """
            () => {
              const visible = node => {
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                  Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
              };
              const wrappers = [...document.querySelectorAll(
                '.byte-drawer-wrapper, .ai-assistant-drawer'
              )].filter(visible);
              let clicked = 0;
              for (const wrapper of wrappers) {
                const close = wrapper.querySelector([
                  '.byte-drawer-close-icon',
                  '.byte-drawer-header .byte-icon-close',
                  '.close-btn',
                  'button[aria-label="关闭"]',
                  '[class*="drawer-close"]'
                ].join(','));
                if (close && visible(close)) {
                  close.click();
                  clicked += 1;
                }
              }
              return { visible: wrappers.length, clicked };
            }
            """
        )
    except Exception:
        return "visible=unknown clicked=0"
    visible = int(result.get("visible") or 0) if isinstance(result, dict) else 0
    clicked = int(result.get("clicked") or 0) if isinstance(result, dict) else 0
    if clicked:
        time.sleep(0.5)
    return f"visible={visible} clicked={clicked}"


def _place_toutiao_cursor_at_body_end(page) -> bool:
    body_input, _ = _visible_locator(page, TOUTIAO_BODY_SELECTORS, "正文")
    try:
        return bool(
            body_input.evaluate(
                """
                editor => {
                  editor.focus();
                  const selection = window.getSelection();
                  if (!selection) return false;
                  const range = document.createRange();
                  range.selectNodeContents(editor);
                  range.collapse(false);
                  selection.removeAllRanges();
                  selection.addRange(range);
                  return selection.anchorNode === editor || editor.contains(selection.anchorNode);
                }
                """
            )
        )
    except Exception:
        try:
            body_input.focus()
            body_input.press("End")
            return True
        except Exception:
            return False


def _read_toutiao_body_text(body_input) -> str:
    try:
        return str(
            body_input.evaluate(
                """
                editor => {
                  const clone = editor.cloneNode(true);
                  clone.querySelectorAll('templ, [contenteditable="false"]').forEach(node => node.remove());
                  return clone.innerText || clone.textContent || '';
                }
                """
            )
            or ""
        )
    except Exception:
        return str(body_input.inner_text() or body_input.text_content() or "")


def _count_toutiao_body_images(body_input) -> int:
    try:
        return int(
            body_input.evaluate(
                """
                editor => new Set(
                  [...editor.querySelectorAll('img')]
                    .map(img => img.getAttribute('web_uri') || img.currentSrc || img.src)
                    .filter(Boolean)
                ).size
                """
            )
            or 0
        )
    except Exception:
        return int(body_input.locator("img").count())


def _wait_for_toutiao_image_input(page, *, wait_timeout_ms: int):
    deadline = time.time() + min(max(3.0, wait_timeout_ms / 1000.0), 15.0)
    while time.time() < deadline:
        for selector in TOUTIAO_IMAGE_INPUT_SELECTORS:
            locator = page.locator(selector)
            if locator.count() > 0:
                return locator.first
        time.sleep(0.1)
    return None


def _confirm_toutiao_image_selection(page, *, wait_timeout_ms: int) -> None:
    deadline = time.time() + min(max(10.0, wait_timeout_ms / 1000.0), 120.0)
    while time.time() < deadline:
        confirm = page.get_by_role("button", name="确定", exact=True)
        if confirm.count() == 1:
            confirm = confirm.first
            if confirm.is_visible() and confirm.is_enabled():
                confirm.click()
                return
        text = _page_visible_text(page)
        if "上传失败" in text:
            raise RuntimeError("头条号图片上传失败，请检查图片格式、大小或网络状态")
        time.sleep(0.25)
    raise RuntimeError("头条号图片已上传，但图片选择窗口未出现可用的“确定”按钮")


def _configure_toutiao_content_declarations(page) -> str:
    drawer_detail = _dismiss_toutiao_blocking_drawers(page)
    declarations = (
        (
            ".exclusive-checkbox-wraper input[type='checkbox']",
            ".exclusive-checkbox-wraper label:has-text('头条首发')",
            False,
            "exclusive",
        ),
        (
            ".source-info-wrap label:has-text('取材网络') input[type='checkbox']",
            ".source-info-wrap label:has-text('取材网络')",
            False,
            "network_source",
        ),
        (
            ".source-info-wrap label:has-text('引用AI') input[type='checkbox']",
            ".source-info-wrap label:has-text('引用AI')",
            True,
            "ai_assisted",
        ),
    )
    configured: dict[str, tuple[Any, bool] | None] = {}
    for input_selector, control_selector, desired, name in declarations:
        locator = page.locator(input_selector)
        if locator.count() == 0:
            configured[name] = None
            continue
        checkbox = locator.first
        if checkbox.is_checked() != desired:
            control = page.locator(control_selector)
            if control.count() == 0:
                raise RuntimeError(f"头条号作品声明控件不可用：{name}")
            try:
                control.first.click(timeout=10_000)
            except TypeError:
                # Lightweight test doubles and older Playwright wrappers may
                # not accept an explicit timeout.
                control.first.click()
            except Exception as exc:
                _dismiss_toutiao_blocking_drawers(page)
                try:
                    checkbox.set_checked(desired, force=True, timeout=5_000)
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"头条号作品声明控件被弹层遮挡：{name}；"
                        f"已限制等待10秒并尝试关闭抽屉，仍无法设置（{fallback_exc}）"
                    ) from exc
        deadline = time.time() + 5.0
        while time.time() < deadline and checkbox.is_checked() != desired:
            time.sleep(0.1)
        actual = checkbox.is_checked()
        if actual != desired:
            raise RuntimeError(f"头条号作品声明设置失败：{name}={actual}")
        configured[name] = (checkbox, desired)

    details: list[str] = []
    for *_selectors, desired, name in declarations:
        state = configured[name]
        if state is None:
            details.append(f"{name}=not_available")
            continue
        checkbox, _ = state
        actual = checkbox.is_checked()
        if actual != desired:
            raise RuntimeError(f"头条号作品声明最终状态不符合要求：{name}={actual}")
        details.append(f"{name}={actual}")
    return f"{drawer_detail} " + " ".join(details)


def _prepare_toutiao_save_retry(page, *, wait_timeout_ms: int) -> str:
    drawer_detail = _dismiss_toutiao_blocking_drawers(page)
    deadline = time.time() + min(max(2.0, wait_timeout_ms / 1000.0), 8.0)
    cleared = False
    while time.time() < deadline:
        try:
            notices = page.locator(
                ".byte-message-notice-content:has-text('保存失败'), "
                ".byte-message-content:has-text('保存失败')"
            )
            visible = any(
                notices.nth(index).is_visible()
                for index in range(notices.count())
            )
        except Exception:
            visible = False
        if not visible:
            cleared = True
            break
        time.sleep(0.25)
    return f"{drawer_detail}; failure_toast_cleared={cleared}"


def _configure_toutiao_cover(page, *, has_images: bool, wait_timeout_ms: int) -> str:
    cover_selector = ".article-cover-img-wrap img[alt='cover']"

    def cover_is_ready() -> bool:
        covers = page.locator(cover_selector)
        return covers.count() > 0 and covers.first.is_visible()

    if cover_is_ready():
        return "single_image=True"

    if not has_images:
        no_cover_input = page.locator(
            ".article-cover-radio-group label:has-text('无封面') input[type='radio']"
        )
        no_cover_control = page.locator(
            ".article-cover-radio-group label:has-text('无封面')"
        )
        if no_cover_input.count() == 0 or no_cover_control.count() == 0:
            raise RuntimeError("头条号无图文章未找到“无封面”选项")
        radio = no_cover_input.first
        if not radio.is_checked():
            no_cover_control.first.click()
        if not radio.is_checked():
            raise RuntimeError("头条号无图文章的“无封面”选项未生效")
        return "no_cover=True"

    _dismiss_toutiao_ai_assistant(page, wait_timeout_ms=wait_timeout_ms)
    add_cover = page.locator(".article-cover-add")
    if add_cover.count() == 0:
        raise RuntimeError("头条号封面未设置，且页面没有显示添加封面入口")
    add_cover.first.click(force=True)

    deadline = time.time() + min(max(5.0, wait_timeout_ms / 1000.0), 30.0)
    while time.time() < deadline:
        if cover_is_ready():
            return "single_image=True"
        time.sleep(0.2)
    raise RuntimeError("头条号封面设置失败：正文图片已上传，但单图封面仍为空")


def _upload_toutiao_images(page, assets: list[str], *, wait_timeout_ms: int) -> int:
    valid_assets = [str(Path(path).resolve()) for path in assets if Path(path).is_file()]
    if not valid_assets:
        return 0
    max_images = max(1, int(os.getenv("TOUTIAO_MAX_IMAGES") or 9))
    selected_assets = valid_assets[:max_images]
    _dismiss_toutiao_ai_assistant(page, wait_timeout_ms=wait_timeout_ms)
    if not _place_toutiao_cursor_at_body_end(page):
        raise RuntimeError("头条号正文光标无法移动到末尾，为避免图片拆开正文，已停止上传")
    file_input = None
    picker_requires_confirmation = False
    for selector in TOUTIAO_IMAGE_INPUT_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            file_input = locator.first
            break
    if file_input is None:
        for selector in TOUTIAO_IMAGE_TOOL_SELECTORS:
            button = page.locator(selector)
            if button.count() == 0:
                continue
            button = button.first
            if not button.is_visible() or not button.is_enabled():
                continue
            button.click()
            file_input = _wait_for_toutiao_image_input(
                page,
                wait_timeout_ms=wait_timeout_ms,
            )
            if file_input is not None:
                picker_requires_confirmation = True
                break
    uploaded_via_chooser = False
    if file_input is None:
        for label in ("图片", "插入图片"):
            button = page.get_by_role("button", name=label, exact=True)
            if button.count() != 1 or not button.is_visible():
                continue
            with page.expect_file_chooser(timeout=min(wait_timeout_ms, 30_000)) as chooser_info:
                button.click()
            chooser_info.value.set_files(selected_assets)
            uploaded_via_chooser = True
            break
    if file_input is None and not uploaded_via_chooser:
        raise RuntimeError("头条号编辑器未找到图片上传入口")
    if file_input is not None:
        file_input.set_input_files(selected_assets)
        if picker_requires_confirmation:
            _confirm_toutiao_image_selection(
                page,
                wait_timeout_ms=wait_timeout_ms,
            )

    deadline = time.time() + min(max(15.0, wait_timeout_ms / 1000.0), 180.0)
    while time.time() < deadline:
        try:
            body_input, _ = _visible_locator(page, TOUTIAO_BODY_SELECTORS, "正文")
            image_count = _count_toutiao_body_images(body_input)
            if image_count >= len(selected_assets):
                return image_count
        except Exception:
            pass
        text = _page_visible_text(page)
        if "上传失败" in text:
            raise RuntimeError("头条号图片上传失败，请检查图片格式、大小或网络状态")
        time.sleep(1)
    raise RuntimeError(
        f"头条号图片上传未完成：期望 {len(selected_assets)} 张，编辑器未确认足够图片"
    )


def _first_toutiao_payload_value(payload: Any, keys: tuple[str, ...]) -> Any:
    queue = [payload]
    visited = 0
    while queue and visited < 40:
        current = queue.pop(0)
        visited += 1
        if isinstance(current, dict):
            for key in keys:
                value = current.get(key)
                if value not in (None, ""):
                    return value
            queue.extend(value for value in current.values() if isinstance(value, (dict, list)))
        elif isinstance(current, list):
            queue.extend(value for value in current if isinstance(value, (dict, list)))
    return None


def _start_toutiao_save_response_capture(page) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def on_response(response) -> None:
        url = str(getattr(response, "url", "") or "")
        if not any(endpoint in url for endpoint in TOUTIAO_SAVE_ENDPOINT_HINTS):
            return
        try:
            payload = response.json()
        except Exception:
            payload = {}
        records.append(
            {
                "endpoint": urlsplit(url).path or url,
                "http_status": int(getattr(response, "status", 0) or 0),
                "code": _first_toutiao_payload_value(
                    payload,
                    ("code", "err_no", "errno", "error_code", "status_code"),
                ),
                "message": re.sub(
                    r"\s+",
                    " ",
                    str(
                        _first_toutiao_payload_value(
                            payload,
                            ("message", "msg", "errmsg", "err_msg", "error_message", "description"),
                        )
                        or ""
                    ),
                ).strip()[:240],
            }
        )

    try:
        page.on("response", on_response)
    except (AttributeError, TypeError):
        pass
    return records


def _toutiao_save_response_failed(record: dict[str, Any]) -> bool:
    code = record.get("code")
    status = int(record.get("http_status") or 0)
    return status >= 400 or code not in (None, "", 0, "0", 200, "200")


def _toutiao_save_response_succeeded(record: dict[str, Any]) -> bool:
    status = int(record.get("http_status") or 0)
    return 200 <= status < 400 and not _toutiao_save_response_failed(record)


def _toutiao_save_requires_sms(records: list[dict[str, Any]]) -> bool:
    for record in reversed(records):
        if not _toutiao_save_response_failed(record):
            continue
        code = record.get("code")
        auth_text = f"{code} {record.get('message') or ''}".lower()
        return str(code) == "7050" or any(
            token in auth_text
            for token in ("authentication sms", "verify sms", "短信", "验证")
        )
    return False


def _toutiao_save_failure_message(records: list[dict[str, Any]]) -> str:
    record = next(
        (item for item in reversed(records) if _toutiao_save_response_failed(item)),
        records[-1] if records else {},
    )
    endpoint = str(record.get("endpoint") or "unknown")
    status = int(record.get("http_status") or 0)
    code = record.get("code")
    message = str(record.get("message") or "").strip()
    diagnostic = (
        f"endpoint={endpoint} http={status or 'unknown'} "
        f"code={code if code not in (None, '') else 'unknown'}"
    )
    if message:
        diagnostic += f" message={message}"
    if _toutiao_save_requires_sms(records):
        return (
            f"头条号要求完成绑定手机短信身份校验（{diagnostic}）。"
            "请在共享 Profile 的可见头条编辑页按提示完成验证；"
            "程序不会绕过平台安全校验"
        )
    return (
        f"头条号草稿保存失败（{diagnostic}）。"
        "请根据平台返回信息检查标题、正文、封面或账号权限"
    )


def _show_toutiao_sms_verification_overlay(page) -> str:
    result = page.evaluate(
        r"""
        async () => {
          const stateKey = '__autoRedbookToutiaoSmsState';
          const rootId = 'auto-redbook-toutiao-sms';
          const network = window.Garr && window.Garr.network;
          if (!network || typeof network.get !== 'function' || typeof network.post !== 'function') {
            return { ok: false, message: '头条页面未加载官方网络方法' };
          }

          document.getElementById(rootId)?.remove();
          window[stateKey] = { status: 'ready', message: '等待获取验证码' };

          const root = document.createElement('div');
          root.id = rootId;
          Object.assign(root.style, {
            position: 'fixed', inset: '0', zIndex: '2147483647',
            display: 'grid', placeItems: 'center', background: 'rgba(0,0,0,.38)',
            fontFamily: 'Arial, Microsoft YaHei, sans-serif'
          });
          const panel = document.createElement('div');
          Object.assign(panel.style, {
            width: '420px', maxWidth: 'calc(100vw - 32px)', background: '#fff',
            border: '1px solid #ddd', borderRadius: '6px', padding: '24px',
            boxShadow: '0 18px 50px rgba(0,0,0,.22)', color: '#222'
          });
          const title = document.createElement('h2');
          title.textContent = '头条号身份校验';
          Object.assign(title.style, { margin: '0 0 12px', fontSize: '21px' });
          const desc = document.createElement('p');
          desc.textContent = '平台要求在写入草稿前校验绑定手机。验证码只提交给头条官方接口。';
          Object.assign(desc.style, { margin: '0 0 18px', color: '#555', lineHeight: '1.6' });
          const mobile = document.createElement('div');
          mobile.textContent = '绑定手机：读取中';
          Object.assign(mobile.style, { marginBottom: '12px', fontSize: '14px' });
          const row = document.createElement('div');
          Object.assign(row.style, { display: 'grid', gridTemplateColumns: '1fr 116px', gap: '10px' });
          const input = document.createElement('input');
          input.placeholder = '输入4位短信验证码';
          input.inputMode = 'numeric';
          input.maxLength = 4;
          Object.assign(input.style, {
            height: '40px', border: '1px solid #bbb', borderRadius: '4px',
            padding: '0 10px', fontSize: '16px', boxSizing: 'border-box'
          });
          input.addEventListener('input', () => {
            input.value = input.value.replace(/\D/g, '').slice(0, 4);
          });
          const send = document.createElement('button');
          send.type = 'button';
          send.textContent = '获取验证码';
          const status = document.createElement('div');
          Object.assign(status.style, { minHeight: '22px', marginTop: '12px', color: '#666', fontSize: '13px' });
          const actions = document.createElement('div');
          Object.assign(actions.style, { display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '16px' });
          const cancel = document.createElement('button');
          cancel.type = 'button';
          cancel.textContent = '取消';
          const verify = document.createElement('button');
          verify.type = 'button';
          verify.textContent = '立即校验';
          for (const button of [send, cancel, verify]) {
            Object.assign(button.style, {
              height: '40px', border: '1px solid #bbb', borderRadius: '4px',
              padding: '0 16px', background: '#fff', cursor: 'pointer', fontSize: '14px'
            });
          }
          Object.assign(verify.style, { background: '#f04444', color: '#fff', borderColor: '#f04444' });

          let countdown = 0;
          const startCountdown = (seconds) => {
            countdown = Math.max(1, Number(seconds) || 60);
            send.disabled = true;
            const tick = () => {
              send.textContent = countdown > 0 ? `${countdown}s` : '重新获取';
              if (countdown <= 0) {
                send.disabled = false;
                return;
              }
              countdown -= 1;
              window.setTimeout(tick, 1000);
            };
            tick();
          };

          send.addEventListener('click', async () => {
            send.disabled = true;
            status.textContent = '正在请求验证码';
            try {
              const response = await network.post('/passport/web/send_code/', { aid: 1231, type: 22 });
              if (response && response.message === 'success') {
                window[stateKey] = { status: 'sent', message: '验证码已发送' };
                status.textContent = '验证码已发送，请查看绑定手机短信';
                startCountdown(response.data?.retryTime || 60);
                input.focus();
              } else {
                const message = response?.data?.description || response?.message || '发送失败';
                window[stateKey] = { status: 'error', message: String(message) };
                status.textContent = String(message);
                send.disabled = false;
              }
            } catch (error) {
              const message = error?.message || '发送验证码失败';
              window[stateKey] = { status: 'error', message: String(message) };
              status.textContent = String(message);
              send.disabled = false;
            }
          });

          verify.addEventListener('click', async () => {
            if (!/^\d{4}$/.test(input.value)) {
              status.textContent = '请输入4位短信验证码';
              return;
            }
            verify.disabled = true;
            status.textContent = '正在校验';
            try {
              const response = await network.post('/passport/web/validate_code/', {
                code: input.value, type: 22, need_record: 1,
                account_sdk_source: 'web', aid: 1231
              });
              input.value = '';
              if (response && response.message === 'success') {
                window[stateKey] = { status: 'success', message: '验证成功' };
                status.textContent = '验证成功，程序将继续保存草稿';
                window.setTimeout(() => root.remove(), 800);
              } else {
                const message = response?.data?.description || response?.message || '校验失败';
                window[stateKey] = { status: 'error', message: String(message) };
                status.textContent = String(message);
                verify.disabled = false;
              }
            } catch (error) {
              input.value = '';
              const message = error?.message || '校验失败';
              window[stateKey] = { status: 'error', message: String(message) };
              status.textContent = String(message);
              verify.disabled = false;
            }
          });
          cancel.addEventListener('click', () => {
            input.value = '';
            window[stateKey] = { status: 'canceled', message: '用户取消短信身份校验' };
            root.remove();
          });

          row.append(input, send);
          actions.append(cancel, verify);
          panel.append(title, desc, mobile, row, status, actions);
          root.append(panel);
          document.body.append(root);

          let maskedMobile = '未知';
          try {
            const response = await network.get('/mp/agw/general/user/get_mosaic_mobile');
            maskedMobile = String(response?.data?.Mobile || response?.data?.mobile || '未知');
          } catch (_) {}
          mobile.textContent = `绑定手机：${maskedMobile}`;
          return { ok: true, mobile: maskedMobile };
        }
        """
    )
    if not isinstance(result, dict) or not result.get("ok"):
        message = result.get("message") if isinstance(result, dict) else "未知错误"
        raise RuntimeError(f"无法显示头条短信身份校验窗口：{message}")
    masked_mobile = str(result.get("mobile") or "未知")
    return f"校验窗口已显示；绑定手机={masked_mobile}"


def _wait_for_toutiao_sms_verification(
    page,
    *,
    login_hold: int,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    if login_hold <= 0:
        raise RuntimeError("头条号需要短信身份校验，但当前没有设置可见等待时间")

    deadline = time.time() + max(1, int(login_hold))
    challenge_seen = False
    last_progress_at = 0.0
    while time.time() < deadline:
        try:
            text = _page_visible_text(page)
            state = page.evaluate(
                "() => window.__autoRedbookToutiaoSmsState || null"
            )
        except Exception as exc:
            raise RuntimeError(f"等待头条短信校验时浏览器页面不可用：{exc}") from exc
        status = str(state.get("status") or "") if isinstance(state, dict) else ""
        if status == "success":
            return "用户已通过头条官方短信身份校验，准备在原编辑页重试保存"
        if status == "canceled":
            raise RuntimeError("用户取消了头条短信身份校验，草稿未保存")
        challenge_visible = any(hint in text for hint in TOUTIAO_SMS_VERIFICATION_HINTS)
        challenge_seen = challenge_seen or challenge_visible
        if challenge_seen and not challenge_visible:
            return "用户已完成短信身份校验，准备在原编辑页重试保存"
        now = time.time()
        if now - last_progress_at >= 15:
            remaining = max(0, int(deadline - now))
            _emit_progress(
                progress_callback,
                "sms_verification",
                "in_progress",
                f"请在可见页面获取并输入短信验证码；remaining={remaining}s",
            )
            last_progress_at = now
        time.sleep(0.5)

    if not challenge_seen:
        raise RuntimeError("头条号返回短信校验要求，但可见页面没有显示校验窗口，请重新打开编辑页后重试")
    raise RuntimeError("等待头条号短信身份校验超时，请完成验证后重新执行保存")


def _save_toutiao_draft(
    page,
    *,
    wait_timeout_ms: int,
    response_records: Optional[list[dict[str, Any]]] = None,
    response_start_index: int = 0,
) -> str:
    has_response_capture = response_records is not None
    response_records = response_records if response_records is not None else []
    clicked = ""
    for label in TOUTIAO_SAVE_TEXTS:
        button = page.get_by_role("button", name=label, exact=True)
        if button.count() == 1 and button.is_visible() and button.is_enabled():
            button.click()
            clicked = label
            break

    deadline = time.time() + min(max(10.0, wait_timeout_ms / 1000.0), 180.0)
    while time.time() < deadline:
        current_records = response_records[max(0, int(response_start_index)) :]
        if any(_toutiao_save_response_failed(item) for item in current_records):
            raise RuntimeError(_toutiao_save_failure_message(current_records))
        if any(_toutiao_save_response_succeeded(item) for item in current_records):
            return f"{clicked or '自动保存'}；官方保存接口已确认"
        text = _page_visible_text(page)
        matched = next((hint for hint in TOUTIAO_SAVED_HINTS if hint in text), "")
        if matched and not has_response_capture:
            return f"{clicked or '自动保存'}；{matched}"
        if "保存失败" in text:
            raise RuntimeError("头条号草稿保存失败，请检查标题、正文和封面提示")
        time.sleep(0.5)
    if has_response_capture:
        raise RuntimeError(
            "头条号页面虽可能显示旧的“已保存”，但封面等最终变更没有获得新的官方保存接口成功响应"
        )
    if clicked:
        return clicked
    raise RuntimeError("头条号页面没有显示“存草稿”按钮或“已保存”状态")


def _find_toutiao_draft_record(page, title: str) -> dict[str, Any]:
    try:
        result = page.evaluate(
            """
            async expectedTitle => {
              const response = await fetch(
                '/mp/agw/creator_center/draft_list?type=0&count=100&app_id=1231',
                { credentials: 'include' }
              );
              const payload = await response.json();
              const drafts = Array.isArray(payload?.draft_list) ? payload.draft_list : [];
              const item = drafts.find(draft => String(draft?.title || '').trim() === expectedTitle.trim());
              return item || {};
            }
            """,
            title,
        )
    except Exception:
        return {}
    return dict(result) if isinstance(result, Mapping) else {}


def _find_toutiao_draft_gid(page, title: str) -> str:
    return str(_find_toutiao_draft_record(page, title).get("gid") or "").strip()


def _toutiao_draft_record_has_cover(record: Mapping[str, Any]) -> bool:
    cover = record.get("cover_image")
    if not isinstance(cover, Mapping):
        return False
    return bool(str(cover.get("image_uri") or cover.get("image_url") or "").strip())


def _verify_toutiao_draft(
    page,
    article: ToutiaoArticle,
    *,
    wait_timeout_ms: int,
) -> ToutiaoDraftVerification:
    expected_images = min(
        len(article.assets),
        max(1, int(os.getenv("TOUTIAO_MAX_IMAGES") or 9)),
    )
    empty_result = ToutiaoDraftVerification(
        found=False,
        title_ok=False,
        body_ok=False,
        images_ok=False,
        cover_ok=False,
        expected_images=expected_images,
        actual_images=0,
    )
    timeout_ms = min(
        TOUTIAO_NAVIGATION_TIMEOUT_MS,
        max(30_000, int(wait_timeout_ms or 0)),
    )
    page.goto(TOUTIAO_DRAFT_URL, wait_until="commit", timeout=timeout_ms)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass

    draft_gid = ""
    draft_record: dict[str, Any] = {}
    gid_deadline = time.time() + min(max(10.0, wait_timeout_ms / 1000.0), 45.0)
    while time.time() < gid_deadline and not draft_gid:
        draft_record = _find_toutiao_draft_record(page, article.title)
        draft_gid = str(draft_record.get("gid") or "").strip()
        if not draft_gid:
            time.sleep(0.5)
    if not draft_gid:
        return empty_result
    page.goto(
        f"{TOUTIAO_PUBLISH_URL}?pgc_id={draft_gid}",
        wait_until="commit",
        timeout=timeout_ms,
    )

    last_result = empty_result
    deadline = time.time() + min(max(10.0, wait_timeout_ms / 1000.0), 60.0)
    while time.time() < deadline:
        try:
            title_input, _ = _visible_locator(page, TOUTIAO_TITLE_SELECTORS, "标题")
            body_input, _ = _visible_locator(page, TOUTIAO_BODY_SELECTORS, "正文")
            actual_title = str(title_input.input_value() or "").strip()
            actual_body = _read_toutiao_body_text(body_input)
            title_ok = actual_title == article.title.strip()
            body_ok = re.sub(r"\s+", "", actual_body) == re.sub(r"\s+", "", article.body)
            image_count = _count_toutiao_body_images(body_input)
            images_ok = image_count >= expected_images
            cover = page.locator(".article-cover-img-wrap img[alt='cover']")
            cover_dom_ok = cover.count() > 0 and cover.first.is_visible()
            cover_api_ok = _toutiao_draft_record_has_cover(draft_record)
            cover_ok = not expected_images or cover_dom_ok or cover_api_ok
            last_result = ToutiaoDraftVerification(
                found=True,
                title_ok=title_ok,
                body_ok=body_ok,
                images_ok=images_ok,
                cover_ok=cover_ok,
                expected_images=expected_images,
                actual_images=image_count,
                actual_title=actual_title,
                cover_source=(
                    "dom"
                    if cover_dom_ok
                    else "official_api"
                    if cover_api_ok
                    else ""
                ),
            )
            if last_result.ok:
                return last_result
            time.sleep(0.25)
        except Exception as exc:
            last_result = ToutiaoDraftVerification(
                found=True,
                title_ok=False,
                body_ok=False,
                images_ok=False,
                cover_ok=False,
                expected_images=expected_images,
                actual_images=0,
                error=str(exc),
            )
            time.sleep(0.25)
    return last_result


def _capture_toutiao_evidence(page, post: Post, execution: Execution, label: str) -> list[str]:
    folder = evidence_dir(post.id, execution.id)
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    try:
        screenshot = folder / f"toutiao_{label}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        paths.append(str(screenshot))
    except Exception:
        pass
    try:
        html_path = folder / f"toutiao_{label}.html"
        html_path.write_text(page.content(), encoding="utf-8")
        paths.append(str(html_path))
    except Exception:
        pass
    return paths


def _clean_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip().replace("|", "｜")
    if len(title) > TOUTIAO_TITLE_MAX_LENGTH:
        title = title[:TOUTIAO_TITLE_MAX_LENGTH].rstrip("，、：；｜—- ")
    if len(title) < 2:
        return "今日资讯"
    return title


def _plain_section_body(body: str) -> str:
    text = str(body or "").replace("\r\n", "\n").strip()
    replacements = (
        (r"(?m)^\s*内容[：:]\s*$", "事件概况"),
        (r"(?m)^\s*内容[：:]\s*", "事件概况\n"),
        (r"(?m)^\s*评价[：:]\s*$", "观察与评价"),
        (r"(?m)^\s*评价[：:]\s*", "观察与评价\n"),
        (r"(?m)^\s*日期[：:]\s*$", "信息时间"),
        (r"(?m)^\s*日期[：:]\s*", "信息时间\n"),
        (r"(?m)^\s*来源[：:]\s*$", "资料来源"),
        (r"(?m)^\s*来源[：:]\s*", "资料来源\n"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    disclaimer = "本文基于公开信息整理，具体进展以相关机构后续披露为准。"
    if disclaimer not in text:
        text = f"{text}\n\n{disclaimer}" if text else disclaimer
    return text


def _ai_digest_items(post: Post) -> list[dict[str, Any]]:
    digest = post.platform.get("ai_digest") if isinstance(post.platform, dict) else None
    if not isinstance(digest, dict):
        return []
    items = digest.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _ai_digest_body(post: Post, items: list[dict[str, Any]]) -> str:
    lines = [f"今天整理了 {len(items)} 条值得关注的 AI 模型、工具与产业动态。"]
    for index, item in enumerate(items, start=1):
        title = str(item.get("title") or f"AI 动态 {index}").strip()
        summary = str(item.get("summary") or item.get("raw_excerpt") or "").strip()
        published_at = str(item.get("published_at") or "时间待来源确认").strip()
        source = str(
            item.get("source_name")
            or item.get("source")
            or item.get("vendor")
            or "公开来源"
        ).strip()
        lines.extend(
            [
                "",
                f"{index}. {title}",
                summary,
                f"发布时间：{published_at}",
                f"资料来源：{source}",
            ]
        )
    lines.extend(
        [
            "",
            "以上内容按公开来源整理，不替代相关机构的正式公告；具体能力、开放范围与上线节奏以官方后续披露为准。",
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip()


def adapt_post_for_toutiao(post: Post) -> ToutiaoArticle:
    items = _ai_digest_items(post)
    body = _ai_digest_body(post, items) if items else _plain_section_body(post.body)
    assets = tuple(
        str(asset.path)
        for asset in post.assets
        if str(getattr(asset, "kind", "image")) == "image" and str(asset.path).strip()
    )
    return ToutiaoArticle(title=_clean_title(post.title), body=body, assets=assets)


def run_save_toutiao_draft_sync(
    post: Post,
    *,
    assets: Optional[list[str]] = None,
    dry_run: bool = False,
    login_hold: int = 0,
    login_only: bool = False,
    wait_timeout_ms: int = TOUTIAO_WAIT_TIMEOUT_MS,
    execution: Optional[Execution] = None,
    headless: Optional[bool] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Execution:
    exec_rec = execution or Execution(post_id=post.id, result="pending")
    steps: list[StepResult] = []
    article = adapt_post_for_toutiao(post)
    asset_paths = [str(path) for path in (assets or list(article.assets)) if Path(path).is_file()]
    context = None
    browser = None
    should_close_context = True
    page = None
    should_close_page = False

    def step(name: str, status: str, detail: str = "") -> StepResult:
        item = StepResult(name=name, status=status, detail=detail)
        steps.append(item)
        _emit_progress(progress_callback, name, status, detail)
        return item

    try:
        profile_dir, channel, args = resolve_toutiao_profile_config()
        profile_dir.mkdir(parents=True, exist_ok=True)
        headless_value = _resolve_toutiao_headless(headless)
        launch_step = step("launch", "in_progress", f"{profile_dir} | headless={headless_value}")
        with sync_playwright() as playwright:
            cdp_url = _resolve_toutiao_cdp_url()
            if cdp_url:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                should_close_context = False
                launch_step.detail = f"cdp={cdp_url}"
            else:
                launch_kwargs: dict[str, Any] = {"headless": headless_value}
                if channel:
                    launch_kwargs["channel"] = channel
                if args:
                    launch_kwargs["args"] = args
                context = playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    **launch_kwargs,
                )
            context.set_default_timeout(max(30_000, int(wait_timeout_ms or 0)))
            launch_step.status = "success"
            try:
                if cdp_url:
                    page = context.new_page()
                    should_close_page = True
                else:
                    page = context.pages[0] if context.pages else context.new_page()

                open_step = step("open_page", "in_progress", TOUTIAO_PUBLISH_URL)
                _open_toutiao_publish_page(page, wait_timeout_ms=wait_timeout_ms)
                open_step.status = "success"

                login_step = step("login_check", "in_progress", f"login_hold={login_hold}s")
                login_step.detail = _wait_for_toutiao_editor(
                    page,
                    login_hold=login_hold,
                    headless=headless_value and not bool(cdp_url),
                    wait_timeout_ms=wait_timeout_ms,
                    progress_callback=progress_callback,
                )
                login_step.status = "success"

                if login_only:
                    exec_rec.result = "login_ready"
                    return exec_rec

                account_step = step("account_check", "in_progress", TOUTIAO_MANAGE_URL)
                account_detail = _ensure_toutiao_account_ready(
                    page,
                    wait_timeout_ms=wait_timeout_ms,
                )
                _open_toutiao_publish_page(page, wait_timeout_ms=wait_timeout_ms)
                editor_detail = _wait_for_toutiao_editor(
                    page,
                    login_hold=0,
                    headless=headless_value and not bool(cdp_url),
                    wait_timeout_ms=wait_timeout_ms,
                    progress_callback=progress_callback,
                )
                account_step.detail = f"{account_detail}; editor={editor_detail}"
                account_step.status = "success"

                device_step = step("device_check", "in_progress", "")
                device_step.detail = _ensure_toutiao_device_verified(page)
                device_step.status = "success"

                if dry_run:
                    step("fill_title_body", "skipped", "dry_run")
                    step("upload_images", "skipped", "dry_run")
                    step("configure_cover", "skipped", "dry_run")
                    step("configure_declarations", "skipped", "dry_run")
                    step("save_draft", "skipped", "dry_run")
                    step("verify_draft", "skipped", "dry_run")
                    exec_rec.result = "pending"
                    return exec_rec

                save_responses = _start_toutiao_save_response_capture(page)
                fill_step = step("fill_title_body", "in_progress", f"title={article.title}")
                title_ok, body_ok = _fill_toutiao_editor(page, article.title, article.body)
                fill_step.detail = f"title={title_ok} body={body_ok}"
                if not title_ok or not body_ok:
                    raise RuntimeError(
                        f"头条号标题或正文写入后回读不一致：title={title_ok} body={body_ok}"
                    )
                fill_step.status = "success"

                upload_step = step("upload_images", "in_progress", f"files={len(asset_paths)}")
                uploaded_images = _upload_toutiao_images(
                    page,
                    asset_paths,
                    wait_timeout_ms=wait_timeout_ms,
                )
                upload_step.detail = f"confirmed={uploaded_images}/{len(asset_paths)}"
                if asset_paths and uploaded_images < min(len(asset_paths), max(1, int(os.getenv("TOUTIAO_MAX_IMAGES") or 9))):
                    raise RuntimeError(
                        f"头条号图片数量回读不足：confirmed={uploaded_images} expected={len(asset_paths)}"
                    )
                upload_step.status = "success" if asset_paths else "skipped"

                cover_step = step(
                    "configure_cover",
                    "in_progress",
                    f"has_images={uploaded_images > 0}",
                )
                cover_step.detail = _configure_toutiao_cover(
                    page,
                    has_images=uploaded_images > 0,
                    wait_timeout_ms=wait_timeout_ms,
                )
                cover_step.status = "success"

                declaration_step = step("configure_declarations", "in_progress", "")
                declaration_step.detail = _configure_toutiao_content_declarations(page)
                declaration_step.status = "success"
                final_save_response_index = len(save_responses)
                exec_rec.evidence.extend(
                    _capture_toutiao_evidence(page, post, exec_rec, "after_fill")
                )

                save_step = step("save_draft", "in_progress", "")
                try:
                    save_step.detail = _save_toutiao_draft(
                        page,
                        wait_timeout_ms=wait_timeout_ms,
                        response_records=save_responses,
                        response_start_index=final_save_response_index,
                    )
                    save_step.status = "success"
                except RuntimeError as first_save_error:
                    interactive_headless = headless_value and not bool(cdp_url)
                    if _toutiao_save_requires_sms(save_responses):
                        sms_wait_seconds = _resolve_toutiao_sms_wait_seconds(
                            login_hold=login_hold,
                            cdp_url=cdp_url,
                        )
                        if interactive_headless or sms_wait_seconds <= 0:
                            save_step.status = "failed"
                            save_step.detail = _toutiao_save_failure_message(save_responses)
                            raise RuntimeError(save_step.detail) from first_save_error
                        save_step.status = "waiting"
                        save_step.detail = _toutiao_save_failure_message(save_responses)
                        sms_step = step(
                            "sms_verification",
                            "in_progress",
                            "请在可见头条页面完成绑定手机短信校验",
                        )
                        sms_step.detail = _show_toutiao_sms_verification_overlay(page)
                        sms_step.detail = _wait_for_toutiao_sms_verification(
                            page,
                            login_hold=sms_wait_seconds,
                            progress_callback=progress_callback,
                        )
                        sms_step.status = "success"
                        save_responses.clear()
                        retry_step = step("save_draft", "in_progress", "短信校验后重试")
                        retry_step.detail = _save_toutiao_draft(
                            page,
                            wait_timeout_ms=wait_timeout_ms,
                            response_records=save_responses,
                            response_start_index=0,
                        )
                        retry_step.status = "success"
                    else:
                        save_step.status = "retrying"
                        save_step.detail = str(first_save_error)[:240]
                        retry_step = step(
                            "save_draft_retry",
                            "in_progress",
                            "首次保存失败，清理页面状态后自动重试一次",
                        )
                        prepare_detail = _prepare_toutiao_save_retry(
                            page,
                            wait_timeout_ms=wait_timeout_ms,
                        )
                        retry_response_index = len(save_responses)
                        try:
                            retry_detail = _save_toutiao_draft(
                                page,
                                wait_timeout_ms=wait_timeout_ms,
                                response_records=save_responses,
                                response_start_index=retry_response_index,
                            )
                        except Exception:
                            retry_step.status = "failed"
                            retry_step.detail = prepare_detail
                            raise
                        retry_step.detail = f"{prepare_detail}; {retry_detail}"
                        retry_step.status = "success"

                verify_step = step("verify_draft", "in_progress", article.title)
                verification = _verify_toutiao_draft(
                    page,
                    article,
                    wait_timeout_ms=wait_timeout_ms,
                )
                verified = (
                    verification.ok
                    if isinstance(verification, ToutiaoDraftVerification)
                    else bool(verification)
                )
                verification_detail = (
                    verification.detail
                    if isinstance(verification, ToutiaoDraftVerification)
                    else f"title_body_images_cover={verified}"
                )
                verify_step.detail = f"{verification_detail} title={article.title}"
                if not verified:
                    failed_fields = (
                        "、".join(verification.failed_fields)
                        if isinstance(verification, ToutiaoDraftVerification)
                        else "标题、正文、图片或封面"
                    )
                    raise RuntimeError(
                        f"头条号草稿回读不完整：失败项={failed_fields}；"
                        f"{verification_detail}；标题={article.title}"
                    )
                verify_step.status = "success"
                exec_rec.evidence.extend(
                    _capture_toutiao_evidence(page, post, exec_rec, "draft_verified")
                )
                exec_rec.result = "saved_draft"
                _emit_progress(progress_callback, "save_draft_chain", "success", post.id)
            finally:
                if page is not None and should_close_page:
                    try:
                        page.close()
                    except Exception:
                        pass
                if context is not None and should_close_context:
                    context.close()
    except Exception as exc:
        exec_rec.result = "failed"
        exec_rec.error = {"message": str(exc), "platform": "toutiao"}
        if page is not None:
            exec_rec.evidence.extend(
                _capture_toutiao_evidence(page, post, exec_rec, "failed")
            )
        _emit_progress(progress_callback, "save_draft_chain", "failed", str(exc))
    finally:
        exec_rec.ended_at = now_iso()
        exec_rec.steps = steps
        save_execution(exec_rec)
        # A CDP browser is owned by the user-facing launcher; leaving the
        # Playwright scope disconnects automation without closing that window.
    return exec_rec
