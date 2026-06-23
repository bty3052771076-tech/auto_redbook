from pathlib import Path

import pytest

from src.publish import playwright_steps
from src.publish.playwright_steps import (
    _classify_xhs_page_state,
    _format_progress_message,
    _html_for_contenteditable_text,
    _locators_for_body,
    _matches_body_value,
    _resolve_headless,
    _resolve_profile_config,
    _wait_for_xhs_ready,
    _wait_for_upload_ready,
)


def test_custom_profile_keeps_system_chrome_channel_by_default(monkeypatch, tmp_path: Path):
    custom_profile = tmp_path / "chrome-profile"
    monkeypatch.setenv("XHS_CHROME_USER_DATA_DIR", str(custom_profile))
    monkeypatch.delenv("XHS_BROWSER_CHANNEL", raising=False)
    monkeypatch.delenv("XHS_CHROME_PROFILE", raising=False)

    profile_dir, channel, args = _resolve_profile_config()

    assert profile_dir == custom_profile
    assert channel == "chrome"
    assert args == []


def test_resolve_headless_defaults_to_visible_browser(monkeypatch):
    monkeypatch.delenv("XHS_HEADLESS", raising=False)

    assert _resolve_headless(None) is False


def test_resolve_headless_accepts_env_flag(monkeypatch):
    monkeypatch.setenv("XHS_HEADLESS", "1")

    assert _resolve_headless(None) is True


def test_resolve_headless_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("XHS_HEADLESS", "1")

    assert _resolve_headless(False) is False


def test_format_progress_message_includes_detail():
    assert (
        _format_progress_message("upload_images", "in_progress", "2 files")
        == "[xhs-upload] upload_images: in_progress | 2 files"
    )


def test_body_locators_include_rich_text_editors():
    selectors = _locators_for_body(object())

    assert "[role='textbox']" in selectors
    assert ".ProseMirror" in selectors
    assert ".ql-editor" in selectors
    assert "[data-placeholder*='正文']" in selectors
    assert selectors.index("textarea") < selectors.index("[data-placeholder*='正文']")


def test_matches_body_value_accepts_json_field_terms():
    expected = (
        '{\n'
        '  "原文标题": "海水电池技术突破",\n'
        '  "内容": "韩国团队研发海水电池，将储能、海水淡化和碳捕集整合到同一系统。",\n'
        '  "评价": "",\n'
        '  "日期": "2026-06-19",\n'
        '  "来源": "Example"\n'
        '}'
    )
    actual = "海水电池技术突破\n韩国团队研发海水电池，将储能、海水淡化和碳捕集整合到同一系统。"

    assert _matches_body_value(actual, expected)


def test_html_for_contenteditable_text_preserves_blank_lines():
    body = (
        "原文标题：AI芯片新品发布\n\n"
        "内容：\n"
        "这家芯片企业披露新一代人工智能加速器。\n\n"
        "评价：\n"
        "AI芯片竞争会影响算力供给。\n\n"
        "日期：2026-06-19\n\n"
        "来源：Example News"
    )

    html = _html_for_contenteditable_text(body)

    assert "<p>原文标题：AI芯片新品发布</p>" in html
    assert "<p><br></p><p>内容：</p>" in html
    assert "<p><br></p><p>来源：Example News</p>" in html
    assert "{" not in html and "}" not in html


def test_wait_for_upload_ready_reports_incremental_progress(monkeypatch):
    image_counts = iter([0, 1, 2])
    messages: list[str] = []

    monkeypatch.setattr(playwright_steps, "_extract_upload_count", lambda _page: None)
    monkeypatch.setattr(
        playwright_steps,
        "_count_uploaded_images",
        lambda _page: next(image_counts),
    )
    monkeypatch.setattr(playwright_steps.time, "sleep", lambda _seconds: None)

    assert _wait_for_upload_ready(
        object(),
        2,
        timeout_ms=5000,
        progress_callback=messages.append,
    )
    assert "[xhs-upload] wait_for_upload_complete: in_progress | uploaded=1/2" in messages
    assert messages[-1] == "[xhs-upload] wait_for_upload_complete: success | uploaded=2/2"


def test_classify_xhs_page_state_detects_login_page():
    assert (
        _classify_xhs_page_state(
            "https://creator.xiaohongshu.com/login",
            "小红书创作服务平台",
            "手机号登录\n扫码登录\n发送验证码",
        )
        == "login"
    )


def test_classify_xhs_page_state_detects_ready_publish_editor():
    assert (
        _classify_xhs_page_state(
            "https://creator.xiaohongshu.com/publish/publish?target=image",
            "小红书创作服务平台",
            "上传图文\n填写标题\n输入正文\n草稿箱",
        )
        == "ready"
    )


def test_classify_xhs_page_state_prefers_login_overlay_over_background_editor():
    assert (
        _classify_xhs_page_state(
            "https://creator.xiaohongshu.com/publish/publish?target=image",
            "小红书创作服务平台",
            "上传图文\n填写标题\n扫码登录\n发送验证码",
        )
        == "login"
    )


def test_wait_for_xhs_ready_returns_immediately_when_already_ready():
    calls: list[str] = []

    def reader(_page):
        calls.append("read")
        return "ready", "state=ready url=https://creator.xiaohongshu.com/publish/publish?target=image"

    def sleep(_seconds):
        raise AssertionError("ready pages must not sleep for login_hold")

    detail = _wait_for_xhs_ready(
        object(),
        login_hold=600,
        headless=False,
        state_reader=reader,
        sleep_fn=sleep,
    )

    assert "state=ready" in detail
    assert calls == ["read"]


def test_wait_for_xhs_ready_fails_fast_when_headless_needs_login():
    def reader(_page):
        return "login", "state=login url=https://creator.xiaohongshu.com/login"

    with pytest.raises(RuntimeError, match="headless"):
        _wait_for_xhs_ready(
            object(),
            login_hold=600,
            headless=True,
            state_reader=reader,
            sleep_fn=lambda _seconds: None,
        )


def test_wait_for_xhs_ready_waits_until_manual_login_finishes():
    states = iter(
        [
            ("login", "state=login url=https://creator.xiaohongshu.com/login"),
            ("unknown", "state=unknown url=https://creator.xiaohongshu.com/publish/publish?target=image"),
            ("ready", "state=ready url=https://creator.xiaohongshu.com/publish/publish?target=image"),
        ]
    )
    clock = {"value": 0.0}

    def reader(_page):
        return next(states)

    def sleep(seconds):
        clock["value"] += seconds

    detail = _wait_for_xhs_ready(
        object(),
        login_hold=10,
        headless=False,
        state_reader=reader,
        sleep_fn=sleep,
        monotonic_fn=lambda: clock["value"],
    )

    assert "state=ready" in detail
    assert clock["value"] == 2.0
