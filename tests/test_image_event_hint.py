from __future__ import annotations

from src.storage.models import Post, PostStatus
from src.workflow import create_post


def test_preferred_image_hint_uses_image_event():
    post = Post(
        type="image",
        status=PostStatus.draft,
        title="t",
        body="b",
        topics=[],
        platform={"news": {"image_event": "安踏入股彪马推进全球化"}},
    )
    assert create_post._preferred_image_hint(post, "fallback") == "安踏入股彪马推进全球化"


def test_normalize_image_event_strips_prefix_words_and_urls():
    raw = "每日新闻｜新闻报道：安踏拟入股彪马 https://example.com"
    out = create_post._normalize_image_event(raw, fallback="")
    assert "每日新闻" not in out
    assert "新闻" not in out
    assert "报道" not in out
    assert "http" not in out


def test_ensure_news_publish_date_inserts_when_missing():
    body = "要点摘要：简述事件。\n新闻内容：\n这是一段新闻正文。\n\n点评：\n这里是点评。"
    out = create_post._ensure_news_publish_date(body, "2025-01-02T00:00:00Z")
    assert out.endswith("发布时间：2025-01-02")
