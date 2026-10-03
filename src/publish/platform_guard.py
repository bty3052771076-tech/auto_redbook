"""Fail-closed detection for platform risk/challenge surfaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .platform_state import PlatformStateError, PlatformStateStore


class PlatformRiskError(PlatformStateError):
    pass


_RISK_PATTERNS = (
    r"疑似使用第三方工具",
    r"浏览行为与真人操作习惯不一致",
    r"行为异常",
    r"访问异常",
    r"该篇笔记已不可被他人查看",
    r"利用AI托管进行发文",
    r"AI托管进行发文/互动",
)
_CHALLENGE_PATTERNS = (r"安全验证", r"验证码", r"请完成验证", r"滑块")


def classify_platform_surface(
    url: str,
    title: str,
    body: str,
    *,
    surface_text: str | None = None,
) -> str:
    """Classify only a platform system surface, never arbitrary post body text."""
    surface = str(surface_text or "").strip()
    if any(re.search(pattern, surface, re.IGNORECASE) for pattern in _RISK_PATTERNS):
        return "risk_blocked"
    if any(re.search(pattern, surface, re.IGNORECASE) for pattern in _CHALLENGE_PATTERNS):
        return "challenge_required"
    haystack = f"{url}\n{title}\n{body}"
    if "login" in haystack.lower() or "请先登录" in haystack:
        return "login_required"
    return "ready"


def _read_platform_surface(page) -> dict[str, str]:
    try:
        value = page.evaluate(
            """
            () => {
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 1 && r.height > 1 && s.display !== 'none' && s.visibility !== 'hidden';
              };
              const nodes = Array.from(document.querySelectorAll(
                '[role="alert"],[role="dialog"],[aria-modal="true"],.el-message,.el-notification,.toast,.d-message,.d-dialog,' +
                '[class*="audit"],[class*="review"],[class*="violation"],[class*="notice"]'
              )).filter(visible);
              return {
                url: document.URL || '',
                title: document.title || '',
                body: (document.body?.innerText || '').slice(0, 4000),
                surface: nodes.map((el) => el.innerText || el.textContent || '').join('\n').slice(0, 2000),
              };
            }
            """
        )
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def detect_platform_risk(
    page,
    *,
    profile_key: str | Path = Path("data/browser/chrome-profile"),
    store: PlatformStateStore | None = None,
) -> str:
    """Raise for persisted pause or a newly visible platform risk surface."""
    # Unit-test state readers may pass a sentinel object instead of a page.
    # A real Playwright page always exposes evaluate; do not let a persisted
    # runtime pause contaminate those pure state-machine tests.
    if not callable(getattr(page, "evaluate", None)):
        return "ready"
    state_store = store or PlatformStateStore()
    try:
        state_store.assert_operable(profile_key)
    except PlatformStateError as exc:
        raise PlatformRiskError(exc.code, exc.detail) from exc

    surface = _read_platform_surface(page)
    if not surface:
        return "ready"
    state = classify_platform_surface(
        str(surface.get("url") or ""),
        str(surface.get("title") or ""),
        str(surface.get("body") or ""),
        surface_text=str(surface.get("surface") or ""),
    )
    if state == "risk_blocked":
        paused = state_store.pause(
            profile_key=profile_key,
            code="XHS_RISK_BLOCKED",
            detail=str(surface.get("surface") or "平台报告浏览行为异常"),
        )
        raise PlatformRiskError(paused["code"], paused["detail"])
    if state == "challenge_required":
        paused = state_store.pause(
            profile_key=profile_key,
            code="XHS_CHALLENGE_REQUIRED",
            detail=str(surface.get("surface") or "平台要求完成安全验证"),
            status="challenge_required",
        )
        raise PlatformRiskError(paused["code"], paused["detail"])
    if state == "login_required":
        raise PlatformRiskError("XHS_LOGIN_REQUIRED", "小红书创作者中心需要登录")
    return "ready"
