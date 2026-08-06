from __future__ import annotations

from pathlib import Path

import pytest

from src.publish.targets import normalize_publish_platform, publish_targets
from src.publish import toutiao_steps
from src.publish.toutiao_steps import (
    adapt_post_for_toutiao,
    resolve_toutiao_profile_config,
    run_save_toutiao_draft_sync,
)
from src.storage.models import AssetInfo, Execution, Post


def test_publish_target_normalization_keeps_xhs_default_and_supports_both():
    assert normalize_publish_platform("") == "xhs"
    assert normalize_publish_platform("小红书") == "xhs"
    assert normalize_publish_platform("今日头条") == "toutiao"
    assert normalize_publish_platform("小红书 + 今日头条") == "both"
    assert publish_targets("both") == ("xhs", "toutiao")


def test_toutiao_profile_defaults_to_the_shared_xhs_profile(monkeypatch):
    for name in (
        "TOUTIAO_CHROME_USER_DATA_DIR",
        "TOUTIAO_BROWSER_CHANNEL",
        "TOUTIAO_CHROME_PROFILE",
        "XHS_CHROME_USER_DATA_DIR",
        "XHS_BROWSER_CHANNEL",
        "XHS_CHROME_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    profile_dir, channel, args = resolve_toutiao_profile_config()

    assert profile_dir == Path(__file__).resolve().parents[1] / "data" / "browser" / "chrome-profile"
    assert channel == "chrome"
    assert args == []


def test_toutiao_profile_accepts_platform_specific_override(monkeypatch, tmp_path: Path):
    profile_dir = tmp_path / "toutiao-profile"
    monkeypatch.setenv("TOUTIAO_CHROME_USER_DATA_DIR", str(profile_dir))
    monkeypatch.setenv("TOUTIAO_BROWSER_CHANNEL", "chromium")
    monkeypatch.setenv("TOUTIAO_CHROME_PROFILE", "Profile 2")

    resolved_dir, channel, args = resolve_toutiao_profile_config()

    assert resolved_dir == profile_dir
    assert channel == "chromium"
    assert args == ["--profile-directory=Profile 2"]


def test_daily_news_is_adapted_to_a_toutiao_article_without_inventing_facts():
    post = Post(
        title="每日新闻｜某公司公布新的芯片量产计划和后续市场安排",
        body=(
            "内容：\n某公司公布新的芯片量产计划，首批产品将在国内工厂生产。\n\n"
            "评价：\n当前披露仍以产能规划为主，实际交付节奏有待后续确认。\n\n"
            "日期：2026-08-04\n\n来源：测试官方来源"
        ),
        topics=["每日新闻", "芯片产业"],
        assets=[AssetInfo(path="cover.png", kind="image")],
    )

    article = adapt_post_for_toutiao(post)

    assert 2 <= len(article.title) <= 30
    assert "事件概况" in article.body
    assert "观察与评价" in article.body
    assert "2026-08-04" in article.body
    assert "测试官方来源" in article.body
    assert "具体进展以相关机构后续披露为准" in article.body
    assert article.assets == ("cover.png",)


def test_ai_digest_uses_structured_items_instead_of_only_copying_xhs_caption():
    post = Post(
        title="每日AI|模型与工具更新",
        body="每日AI讯息\n\n来源链接：\n1. 示例官网 https://example.com/news",
        assets=[AssetInfo(path="digest.png", kind="image")],
        platform={
            "ai_digest": {
                "items": [
                    {
                        "title": "示例模型发布新版本",
                        "summary": "新版本提升了代码生成与工具调用能力。",
                        "published_at": "2026-08-04 09:00",
                        "source": "示例模型官网",
                        "url": "https://example.com/news",
                    }
                ]
            }
        },
    )

    article = adapt_post_for_toutiao(post)

    assert "示例模型发布新版本" in article.body
    assert "新版本提升了代码生成与工具调用能力" in article.body
    assert "2026-08-04 09:00" in article.body
    assert "示例模型官网" in article.body
    assert "https://example.com/news" not in article.body


def test_toutiao_image_upload_closes_ai_drawer_and_uses_dynamic_toolbar_input(
    monkeypatch,
    tmp_path: Path,
):
    asset = tmp_path / "cover.png"
    asset.write_bytes(b"image")
    calls: list[str] = []

    class EmptyLocator:
        @property
        def first(self):
            return self

        def count(self):
            return 0

    class DrawerLocator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def is_visible(self):
            return True

        def wait_for(self, *, state, timeout):
            calls.append(f"drawer-wait:{state}")

    class CloseLocator(DrawerLocator):
        def click(self):
            calls.append("drawer-close")

    class ToolLocator(DrawerLocator):
        def is_enabled(self):
            return True

        def click(self):
            calls.append("image-tool-click")
            page.input_ready = True

    class InputLocator(DrawerLocator):
        def set_input_files(self, files):
            calls.append(f"set-files:{len(files)}")

    class ConfirmLocator(DrawerLocator):
        def is_enabled(self):
            return True

        def click(self):
            calls.append("image-confirm")

    class ImageCountLocator:
        def count(self):
            return 1

    class BodyLocator:
        def locator(self, selector):
            assert selector == "img"
            return ImageCountLocator()

    class FakePage:
        input_ready = False

        def locator(self, selector):
            if selector == ".ai-assistant-drawer":
                return DrawerLocator()
            if selector == ".ai-assistant-drawer .close-btn":
                return CloseLocator()
            if selector in {
                ".syl-toolbar-tool.image.static button",
                ".syl-toolbar-tool.image button",
            }:
                return ToolLocator()
            if selector.startswith("input[type='file']"):
                return InputLocator() if self.input_ready else EmptyLocator()
            return EmptyLocator()

        def get_by_role(self, role, *, name, exact):
            assert role == "button"
            if name == "确定" and exact:
                return ConfirmLocator()
            return EmptyLocator()

    page = FakePage()
    monkeypatch.setattr(
        toutiao_steps,
        "_visible_locator",
        lambda *_args, **_kwargs: (BodyLocator(), "body"),
    )
    monkeypatch.setattr(
        toutiao_steps,
        "_place_toutiao_cursor_at_body_end",
        lambda *_args, **_kwargs: calls.append("cursor:end") or True,
    )

    uploaded = toutiao_steps._upload_toutiao_images(
        page,
        [str(asset)],
        wait_timeout_ms=30_000,
    )

    assert uploaded == 1
    assert calls == [
        "drawer-close",
        "drawer-wait:hidden",
        "cursor:end",
        "image-tool-click",
        "set-files:1",
        "image-confirm",
    ]


def test_toutiao_readback_ignores_image_controls_and_duplicate_template_image():
    class BodyLocator:
        def evaluate(self, script):
            if "cloneNode" in script:
                return "完整正文"
            if "new Set" in script:
                return 1
            raise AssertionError(script)

    body = BodyLocator()

    assert toutiao_steps._read_toutiao_body_text(body) == "完整正文"
    assert toutiao_steps._count_toutiao_body_images(body) == 1


def test_toutiao_draft_gid_is_read_from_the_official_draft_list_api():
    class FakePage:
        def evaluate(self, script, title):
            assert "creator_center/draft_list" in script
            assert title == "目标草稿"
            return {
                "gid": "7670112153559269924",
                "title": title,
                "cover_image": {
                    "image_uri": "tos-cn/example",
                    "image_url": "https://example.invalid/cover.jpg",
                },
            }

    assert (
        toutiao_steps._find_toutiao_draft_gid(FakePage(), "目标草稿")
        == "7670112153559269924"
    )


def test_toutiao_official_draft_record_confirms_cover_when_dom_is_lazy():
    assert toutiao_steps._toutiao_draft_record_has_cover(
        {
            "cover_image": {
                "image_uri": "tos-cn/example",
                "image_url": "https://example.invalid/cover.jpg",
            }
        }
    )
    assert not toutiao_steps._toutiao_draft_record_has_cover({"cover_image": {}})


def test_toutiao_draft_verification_reports_each_failed_field():
    result = toutiao_steps.ToutiaoDraftVerification(
        found=True,
        title_ok=True,
        body_ok=True,
        images_ok=True,
        cover_ok=False,
        expected_images=1,
        actual_images=1,
        actual_title="目标草稿",
    )

    assert not result.ok
    assert result.failed_fields == ("封面",)
    assert "封面=失败" in result.detail
    assert "图片=通过(1/1)" in result.detail


def test_toutiao_account_check_explains_required_app_verification():
    class BodyLocator:
        def inner_text(self, timeout):
            return "请完善账号信息，解锁发布文章、视频等权益功能"

    class FakePage:
        url = "https://mp.toutiao.com/profile_v4/manage/content/all"

        def goto(self, url, **_kwargs):
            self.url = url

        def locator(self, selector):
            assert selector == "body"
            return BodyLocator()

    with pytest.raises(RuntimeError) as exc_info:
        toutiao_steps._ensure_toutiao_account_ready(
            FakePage(),
            wait_timeout_ms=30_000,
        )

    message = str(exc_info.value)
    assert "文章发布权益" in message
    assert "今日头条 App" in message
    assert "扫一扫" in message


def test_toutiao_device_check_does_not_block_on_stale_phone_permission_flag():
    class FakePage:
        def evaluate(self, _script):
            return {
                "code": 0,
                "data": {
                    "phone_permission": False,
                    "media": {
                        "content_cache": {
                            "send_not_authentication_sms": 1,
                        },
                        "verify_time": 1_588_682_090,
                    },
                },
            }

    detail = toutiao_steps._ensure_toutiao_device_verified(FakePage())

    assert "phone_permission=False" in detail
    assert "sms_verification_required=True" in detail
    assert "实际保存响应" in detail


def test_toutiao_save_failure_explains_sms_identity_verification():
    message = toutiao_steps._toutiao_save_failure_message(
        [
            {
                "endpoint": "/mp/agw/article/publish",
                "http_status": 200,
                "code": 7050,
                "message": "need authentication sms",
            }
        ]
    )

    assert "短信身份校验" in message
    assert "7050" in message
    assert "不会绕过" in message


def test_toutiao_save_failure_includes_official_api_diagnostic():
    message = toutiao_steps._toutiao_save_failure_message(
        [
            {
                "endpoint": "/mp/agw/draft/save_ugc_draft",
                "http_status": 400,
                "code": 1009,
                "message": "cover invalid",
            }
        ]
    )

    assert "save_ugc_draft" in message
    assert "1009" in message
    assert "cover invalid" in message


def test_toutiao_save_waits_for_a_new_official_success_response():
    records = [
        {
            "endpoint": "/mp/agw/article/publish",
            "http_status": 200,
            "code": 0,
            "message": "success",
        }
    ]

    class EmptyLocator:
        def count(self):
            return 0

    class SaveLocator:
        def count(self):
            return 1

        def is_visible(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            records.append(
                {
                    "endpoint": "/mp/agw/article/publish",
                    "http_status": 200,
                    "code": 0,
                    "message": "success",
                }
            )

    class FakePage:
        def get_by_role(self, role, *, name, exact):
            assert role == "button"
            assert exact is True
            return SaveLocator() if name == "存草稿" else EmptyLocator()

        def locator(self, selector):
            assert selector == "body"

            class Body:
                def inner_text(self, timeout):
                    return "草稿已保存"

            return Body()

    detail = toutiao_steps._save_toutiao_draft(
        FakePage(),
        wait_timeout_ms=30_000,
        response_records=records,
        response_start_index=1,
    )

    assert detail == "存草稿；官方保存接口已确认"
    assert len(records) == 2


def test_toutiao_sms_overlay_uses_only_official_send_and_validate_endpoints():
    captured: list[str] = []

    class FakePage:
        def evaluate(self, script):
            captured.append(script)
            return {"ok": True, "mobile": "186****39"}

    detail = toutiao_steps._show_toutiao_sms_verification_overlay(FakePage())

    assert detail == "校验窗口已显示；绑定手机=186****39"
    assert "/passport/web/send_code/" in captured[0]
    assert "/passport/web/validate_code/" in captured[0]
    assert "type: 22" in captured[0]
    assert "cookie" not in captured[0].lower()
    assert "token" not in captured[0].lower()


def test_toutiao_declarations_disable_exclusive_and_disclose_sources():
    states = {
        ".exclusive-checkbox-wraper input[type='checkbox']": True,
        ".source-info-wrap label:has-text('取材网络') input[type='checkbox']": True,
        ".source-info-wrap label:has-text('引用AI') input[type='checkbox']": False,
    }
    controls = {
        ".exclusive-checkbox-wraper label:has-text('头条首发')": ".exclusive-checkbox-wraper input[type='checkbox']",
        ".source-info-wrap label:has-text('取材网络')": ".source-info-wrap label:has-text('取材网络') input[type='checkbox']",
        ".source-info-wrap label:has-text('引用AI')": ".source-info-wrap label:has-text('引用AI') input[type='checkbox']",
    }
    calls: list[str] = []

    class CheckboxLocator:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        def count(self):
            return 1

        def is_checked(self):
            return states[self.selector]

        def click(self, **_kwargs):
            raise AssertionError("hidden checkbox input must not be clicked")

    class ControlLocator:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        def count(self):
            return 1

        def click(self):
            input_selector = controls[self.selector]
            states[input_selector] = not states[input_selector]
            calls.append(self.selector)

    class FakePage:
        def locator(self, selector):
            if selector in controls:
                return ControlLocator(selector)
            return CheckboxLocator(selector)

    detail = toutiao_steps._configure_toutiao_content_declarations(FakePage())

    assert states == {
        ".exclusive-checkbox-wraper input[type='checkbox']": False,
        ".source-info-wrap label:has-text('取材网络') input[type='checkbox']": False,
        ".source-info-wrap label:has-text('引用AI') input[type='checkbox']": True,
    }
    assert calls == list(controls)
    assert "exclusive=False" in detail
    assert "network_source=False" in detail
    assert "ai_assisted=True" in detail


def test_toutiao_declarations_close_blocking_drawer_and_bound_click_timeout():
    states = {
        ".exclusive-checkbox-wraper input[type='checkbox']": False,
        ".source-info-wrap label:has-text('取材网络') input[type='checkbox']": False,
        ".source-info-wrap label:has-text('引用AI') input[type='checkbox']": False,
    }
    controls = {
        ".source-info-wrap label:has-text('引用AI')": ".source-info-wrap label:has-text('引用AI') input[type='checkbox']",
    }
    observed = {"drawer_closed": False, "click_timeout": None}

    class CheckboxLocator:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        def count(self):
            return 1

        def is_checked(self):
            return states[self.selector]

    class ControlLocator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def click(self, *, timeout):
            observed["click_timeout"] = timeout
            assert observed["drawer_closed"] is True
            states[controls[".source-info-wrap label:has-text('引用AI')"]] = True

    class FakePage:
        def evaluate(self, script):
            assert ".byte-drawer-wrapper" in script
            observed["drawer_closed"] = True
            return {"visible": 1, "clicked": 1}

        def locator(self, selector):
            if selector in controls:
                return ControlLocator()
            return CheckboxLocator(selector)

    detail = toutiao_steps._configure_toutiao_content_declarations(FakePage())

    assert observed == {"drawer_closed": True, "click_timeout": 10_000}
    assert "ai_assisted=True" in detail


def test_toutiao_cover_uses_first_body_image_and_verifies_cover(monkeypatch):
    state = {"covered": False}
    calls: list[str] = []

    class CoverImageLocator:
        @property
        def first(self):
            return self

        def count(self):
            return 1 if state["covered"] else 0

        def is_visible(self):
            return state["covered"]

    class CoverAddLocator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def click(self, *, force):
            assert force is True
            state["covered"] = True
            calls.append("cover-add")

    class FakePage:
        def locator(self, selector):
            if selector == ".article-cover-img-wrap img[alt='cover']":
                return CoverImageLocator()
            assert selector == ".article-cover-add"
            return CoverAddLocator()

    monkeypatch.setattr(
        toutiao_steps,
        "_dismiss_toutiao_ai_assistant",
        lambda *_a, **_k: calls.append("dismiss-assistant"),
    )

    detail = toutiao_steps._configure_toutiao_cover(
        FakePage(),
        has_images=True,
        wait_timeout_ms=30_000,
    )

    assert detail == "single_image=True"
    assert calls == ["dismiss-assistant", "cover-add"]


def test_toutiao_runner_saves_and_verifies_platform_draft(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOUTIAO_CDP_URL", raising=False)
    monkeypatch.delenv("XHS_CDP_URL", raising=False)
    asset = tmp_path / "cover.png"
    asset.write_bytes(b"image")
    post = Post(
        title="头条草稿链路测试",
        body="内容：测试正文。\n\n评价：测试评价。\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    calls: list[str] = []

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            calls.append("timeout")

        def close(self):
            calls.append("close")

    class FakeChromium:
        def launch_persistent_context(self, _profile, **_kwargs):
            calls.append("launch")
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager(), raising=False)
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: calls.append("open"), raising=False)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: calls.append("ready") or "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: calls.append("account") or "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_device_verified", lambda *_a, **_k: calls.append("device") or "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_fill_toutiao_editor", lambda *_a, **_k: calls.append("fill") or (True, True), raising=False)
    monkeypatch.setattr(toutiao_steps, "_upload_toutiao_images", lambda *_a, **_k: calls.append("images") or 1, raising=False)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_cover", lambda *_a, **_k: calls.append("cover") or "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_save_toutiao_draft", lambda *_a, **_k: calls.append("save") or "存草稿", raising=False)
    monkeypatch.setattr(toutiao_steps, "_verify_toutiao_draft", lambda *_a, **_k: calls.append("verify") or True, raising=False)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_content_declarations", lambda *_a, **_k: calls.append("declarations") or "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_capture_toutiao_evidence", lambda *_a, **_k: [], raising=False)
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda execution: calls.append(f"record:{execution.result}"), raising=False)

    execution = run_save_toutiao_draft_sync(
        post,
        assets=[str(asset)],
        headless=True,
        wait_timeout_ms=30_000,
        execution=Execution(post_id=post.id),
    )

    assert execution.result == "saved_draft"
    assert [step.name for step in execution.steps] == [
        "launch",
        "open_page",
        "login_check",
        "account_check",
        "device_check",
        "fill_title_body",
        "upload_images",
        "configure_cover",
        "configure_declarations",
        "save_draft",
        "verify_draft",
    ]
    assert calls == [
        "launch",
        "timeout",
        "open",
        "ready",
        "account",
        "open",
        "ready",
        "device",
        "fill",
        "images",
        "cover",
        "declarations",
        "save",
        "verify",
        "close",
        "record:saved_draft",
    ]


def test_toutiao_runner_reports_verification_failure_in_plain_chinese(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("TOUTIAO_CDP_URL", raising=False)
    monkeypatch.delenv("XHS_CDP_URL", raising=False)
    post = Post(title="未回读草稿", body="内容：测试正文。")

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            pass

        def close(self):
            pass

    class FakeChromium:
        def launch_persistent_context(self, _profile, **_kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager(), raising=False)
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_device_verified", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_fill_toutiao_editor", lambda *_a, **_k: (True, True), raising=False)
    monkeypatch.setattr(toutiao_steps, "_upload_toutiao_images", lambda *_a, **_k: 0, raising=False)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_cover", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_save_toutiao_draft", lambda *_a, **_k: "自动保存", raising=False)
    verification = toutiao_steps.ToutiaoDraftVerification(
        found=True,
        title_ok=True,
        body_ok=True,
        images_ok=True,
        cover_ok=False,
        expected_images=1,
        actual_images=1,
        actual_title=post.title,
    )
    monkeypatch.setattr(
        toutiao_steps,
        "_verify_toutiao_draft",
        lambda *_a, **_k: verification,
        raising=False,
    )
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_content_declarations", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_capture_toutiao_evidence", lambda *_a, **_k: [], raising=False)
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda _execution: None, raising=False)

    execution = run_save_toutiao_draft_sync(post, headless=True, wait_timeout_ms=30_000)

    assert execution.result == "failed"
    assert "头条号草稿回读不完整" in execution.error["message"]
    assert "失败项=封面" in execution.error["message"]
    assert "图片=通过(1/1)" in execution.error["message"]


def test_toutiao_runner_waits_for_visible_sms_verification_then_retries_save(
    monkeypatch,
):
    monkeypatch.delenv("TOUTIAO_CDP_URL", raising=False)
    monkeypatch.delenv("XHS_CDP_URL", raising=False)
    post = Post(title="短信校验后保存", body="内容：测试正文。")
    calls: list[str] = []
    responses = [
        {
            "endpoint": "/mp/agw/article/publish",
            "http_status": 200,
            "code": 7050,
            "message": "need authentication sms",
        }
    ]

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            pass

        def close(self):
            calls.append("close")

    class FakeChromium:
        def launch_persistent_context(self, _profile, **_kwargs):
            assert _kwargs["headless"] is False
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    save_calls = {"count": 0}

    def fake_save(*_args, **_kwargs):
        save_calls["count"] += 1
        calls.append(f"save:{save_calls['count']}")
        if save_calls["count"] == 1:
            raise RuntimeError(toutiao_steps._toutiao_save_failure_message(responses))
        assert _kwargs["response_records"] == []
        return "存草稿；保存成功"

    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager())
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: None)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_device_verified", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_start_toutiao_save_response_capture", lambda _page: responses)
    monkeypatch.setattr(toutiao_steps, "_fill_toutiao_editor", lambda *_a, **_k: (True, True))
    monkeypatch.setattr(toutiao_steps, "_upload_toutiao_images", lambda *_a, **_k: 0)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_cover", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_content_declarations", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_save_toutiao_draft", fake_save)
    monkeypatch.setattr(
        toutiao_steps,
        "_show_toutiao_sms_verification_overlay",
        lambda *_a, **_k: calls.append("sms-overlay") or "校验窗口已显示",
        raising=False,
    )
    monkeypatch.setattr(
        toutiao_steps,
        "_wait_for_toutiao_sms_verification",
        lambda *_a, **_k: calls.append("sms-verified") or "用户已完成短信身份校验",
        raising=False,
    )
    monkeypatch.setattr(toutiao_steps, "_verify_toutiao_draft", lambda *_a, **_k: True)
    monkeypatch.setattr(toutiao_steps, "_capture_toutiao_evidence", lambda *_a, **_k: [])
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda _execution: None)

    execution = run_save_toutiao_draft_sync(
        post,
        headless=False,
        login_hold=600,
        wait_timeout_ms=30_000,
    )

    assert execution.result == "saved_draft"
    assert calls == ["save:1", "sms-overlay", "sms-verified", "save:2", "close"]
    assert [step.name for step in execution.steps][-3:] == [
        "sms_verification",
        "save_draft",
        "verify_draft",
    ]


def test_toutiao_runner_retries_one_transient_save_failure_headlessly(monkeypatch):
    monkeypatch.delenv("TOUTIAO_CDP_URL", raising=False)
    monkeypatch.delenv("XHS_CDP_URL", raising=False)
    post = Post(title="无窗口重试保存", body="内容：测试正文。")
    calls: list[str] = []

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            pass

        def close(self):
            calls.append("close")

    class FakeChromium:
        def launch_persistent_context(self, _profile, **_kwargs):
            assert _kwargs["headless"] is True
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    save_calls = {"count": 0}

    def fake_save(*_args, **kwargs):
        save_calls["count"] += 1
        calls.append(f"save:{save_calls['count']}:{kwargs['response_start_index']}")
        if save_calls["count"] == 1:
            raise RuntimeError("头条号草稿保存失败，请检查标题、正文和封面提示")
        return "存草稿；官方保存接口已确认"

    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager())
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: None)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_device_verified", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_start_toutiao_save_response_capture", lambda _page: [])
    monkeypatch.setattr(toutiao_steps, "_fill_toutiao_editor", lambda *_a, **_k: (True, True))
    monkeypatch.setattr(toutiao_steps, "_upload_toutiao_images", lambda *_a, **_k: 0)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_cover", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_content_declarations", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_save_toutiao_draft", fake_save)
    monkeypatch.setattr(
        toutiao_steps,
        "_prepare_toutiao_save_retry",
        lambda *_a, **_k: calls.append("prepare-retry") or "旧保存失败提示已清理",
        raising=False,
    )
    monkeypatch.setattr(toutiao_steps, "_verify_toutiao_draft", lambda *_a, **_k: True)
    monkeypatch.setattr(toutiao_steps, "_capture_toutiao_evidence", lambda *_a, **_k: [])
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda _execution: None)

    execution = run_save_toutiao_draft_sync(
        post,
        headless=True,
        login_hold=0,
        wait_timeout_ms=30_000,
    )

    assert execution.result == "saved_draft"
    assert calls == ["save:1:0", "prepare-retry", "save:2:0", "close"]
    assert [step.name for step in execution.steps][-3:] == [
        "save_draft",
        "save_draft_retry",
        "verify_draft",
    ]


def test_toutiao_runner_reports_official_sms_requirement_in_headless_mode(monkeypatch):
    monkeypatch.delenv("TOUTIAO_CDP_URL", raising=False)
    monkeypatch.delenv("XHS_CDP_URL", raising=False)
    post = Post(title="需要短信校验", body="内容：测试正文。")
    responses = [
        {
            "endpoint": "/mp/agw/article/publish",
            "http_status": 200,
            "code": 7050,
            "message": "need authentication sms",
        }
    ]

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            pass

        def close(self):
            pass

    class FakeChromium:
        def launch_persistent_context(self, _profile, **_kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager())
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: None)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_device_verified", lambda *_a, **_k: "sms")
    monkeypatch.setattr(toutiao_steps, "_start_toutiao_save_response_capture", lambda _page: responses)
    monkeypatch.setattr(toutiao_steps, "_fill_toutiao_editor", lambda *_a, **_k: (True, True))
    monkeypatch.setattr(toutiao_steps, "_upload_toutiao_images", lambda *_a, **_k: 0)
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_cover", lambda *_a, **_k: "ready")
    monkeypatch.setattr(toutiao_steps, "_configure_toutiao_content_declarations", lambda *_a, **_k: "ready")
    monkeypatch.setattr(
        toutiao_steps,
        "_save_toutiao_draft",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("保存失败")),
    )
    monkeypatch.setattr(toutiao_steps, "_capture_toutiao_evidence", lambda *_a, **_k: [])
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda _execution: None)

    execution = run_save_toutiao_draft_sync(
        post,
        headless=True,
        login_hold=0,
        wait_timeout_ms=30_000,
    )

    assert execution.result == "failed"
    assert "短信身份校验" in execution.error["message"]
    assert "code=7050" in execution.error["message"]
    assert execution.steps[-1].name == "save_draft"
    assert execution.steps[-1].status == "failed"


def test_toutiao_runner_does_not_close_a_user_managed_cdp_browser(monkeypatch):
    post = Post(title="CDP 草稿测试", body="内容：测试正文。")
    calls: list[str] = []

    class FakePage:
        def close(self):
            calls.append("page-close")

    class FakeContext:
        pages = [object()]

        def set_default_timeout(self, _timeout):
            calls.append("timeout")

        def new_page(self):
            calls.append("new-page")
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self):
            calls.append("browser-close")

    class FakeChromium:
        def connect_over_cdp(self, url):
            calls.append(f"connect:{url}")
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("TOUTIAO_CDP_URL", "9223")
    monkeypatch.setattr(toutiao_steps, "sync_playwright", lambda: FakePlaywrightManager(), raising=False)
    monkeypatch.setattr(toutiao_steps, "_open_toutiao_publish_page", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(toutiao_steps, "_wait_for_toutiao_editor", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "_ensure_toutiao_account_ready", lambda *_a, **_k: "ready", raising=False)
    monkeypatch.setattr(toutiao_steps, "save_execution", lambda _execution: None, raising=False)

    execution = run_save_toutiao_draft_sync(
        post,
        dry_run=True,
        headless=False,
        wait_timeout_ms=30_000,
    )

    assert execution.result == "pending"
    assert calls == [
        "connect:http://127.0.0.1:9223",
        "timeout",
        "new-page",
        "page-close",
    ]
