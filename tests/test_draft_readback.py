from __future__ import annotations

from src.publish import playwright_steps
from src.publish.playwright_steps import (
    DraftReadbackResult,
    _read_back_saved_draft,
    _verify_draft_readback_snapshot,
)
from src.storage.models import AssetInfo, Post


def _post() -> Post:
    return Post(
        title="芯片企业发布新方案",
        body="内容：企业发布新一代芯片制造方案。\n\n评价：需要关注量产进展。",
        assets=[
            AssetInfo(path="first.png", kind="image"),
            AssetInfo(path="second.png", kind="image"),
        ],
    )


def test_readback_compares_full_title_body_and_image_count():
    post = _post()

    result = _verify_draft_readback_snapshot(
        {
            "actual_title": "芯片企业发布新方案",
            "actual_body": "内容：企业发布新一代芯片制造方案。\n评价：需要关注量产进展。",
        },
        post,
        actual_image_count=2,
    )

    assert result == DraftReadbackResult(
        ok=True,
        title_ok=True,
        body_ok=True,
        image_ok=True,
        actual_title="芯片企业发布新方案",
        actual_body="内容：企业发布新一代芯片制造方案。\n评价：需要关注量产进展。",
        actual_image_count=2,
        expected_image_count=2,
    )


def test_readback_rejects_partial_body_or_missing_image():
    post = _post()

    result = _verify_draft_readback_snapshot(
        {
            "actual_title": post.title,
            "actual_body": "内容：企业发布新一代芯片。",
        },
        post,
        actual_image_count=1,
    )

    assert not result.ok
    assert result.title_ok
    assert not result.body_ok
    assert not result.image_ok


def test_readback_normalizes_html_entities_in_source_urls():
    post = Post(
        title="AI source",
        body="Source https://example.test/news?a=1&amp;b=2",
        assets=[],
    )

    result = _verify_draft_readback_snapshot(
        {
            "actual_title": "AI source",
            "actual_body": "Source https://example.test/news?a=1&b=2",
        },
        post,
        actual_image_count=0,
    )

    assert result.ok


def test_read_back_saved_draft_reopens_editor_and_reads_snapshot(monkeypatch):
    post = _post()
    calls: list[str] = []
    monkeypatch.setattr(
        playwright_steps,
        "_open_draft_editor_for_post",
        lambda _page, _post: calls.append("open") or {"saved_at": "刚刚"},
    )
    monkeypatch.setattr(
        playwright_steps,
        "_wait_for_any_locator",
        lambda *_args, **_kwargs: calls.append("wait") or "input",
    )
    monkeypatch.setattr(
        playwright_steps,
        "_read_editor_draft_snapshot",
        lambda _page: {
            "actual_title": post.title,
            "actual_body": post.body,
        },
    )
    monkeypatch.setattr(playwright_steps, "_count_editor_images", lambda _page: 2)

    result = _read_back_saved_draft(object(), post, wait_timeout_ms=60_000)

    assert result.ok
    assert calls == ["open", "wait"]
