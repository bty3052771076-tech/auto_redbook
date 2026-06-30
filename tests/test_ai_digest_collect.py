from __future__ import annotations

from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.sources import AIDigestSource


def _item(title: str, source_type: str = "official") -> AIUpdateItem:
    return AIUpdateItem(
        title=title,
        summary=f"{title} summary",
        source_name="fixture",
        source_type=source_type,
        url=f"https://example.com/{title}",
        published_at="2026-06-30T08:00:00Z",
        vendor="Fixture",
        raw_excerpt=f"{title} raw",
    )


def test_collect_ai_digest_updates_skips_social_when_official_sources_are_enough():
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
        AIDigestSource("x", "social", "https://x.com/search", "X", "social_html"),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.kind == "official":
            return [_item(f"official-{i}") for i in range(8)]
        return [_item("social-1", "social")]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=10,
        min_official_count=6,
    )

    assert calls == ["official"]
    assert len(items) == 8
    assert meta["official_count"] == 8
    assert meta["social_backfill_used"] is False


def test_collect_ai_digest_updates_uses_social_backfill_when_official_sources_are_few():
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
        AIDigestSource("x", "social", "https://x.com/search", "X", "social_html"),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.kind == "official":
            return [_item(f"official-{i}") for i in range(3)]
        return [_item(f"social-{i}", "social") for i in range(10)]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=10,
        min_official_count=6,
    )

    assert calls == ["official", "x"]
    assert len(items) == 10
    assert meta["official_count"] == 3
    assert meta["social_backfill_used"] is True
    assert any(item.source_type == "social" for item in items)
