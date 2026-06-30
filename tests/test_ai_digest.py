from __future__ import annotations

from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import rank_ai_updates


def _item(
    title: str,
    *,
    url: str = "",
    source_type: str = "official",
    source_name: str = "OpenAI",
    evidence_urls: list[str] | None = None,
) -> AIUpdateItem:
    return AIUpdateItem(
        title=title,
        summary=f"{title} summary",
        source_name=source_name,
        source_type=source_type,
        url=url or f"https://example.com/{title}",
        published_at="2026-06-30T08:00:00Z",
        vendor=source_name,
        product="AI",
        raw_excerpt=f"{title} raw excerpt",
        evidence_urls=evidence_urls or [],
        tags=["AI"],
    )


def test_ai_update_item_normalizes_url_key_and_source_type():
    item = _item(
        "OpenAI 发布新功能",
        url="https://openai.com/news/example/?utm_source=x#section",
    )

    assert item.source_type == "official"
    assert item.dedupe_key == "url:https://openai.com/news/example/"
    assert item.verification_status == "official_only"


def test_rank_ai_updates_dedupes_by_url_and_title_prefers_official():
    official = _item("Claude Code 更新", url="https://anthropic.com/news/code", source_name="Anthropic")
    social_duplicate = _item(
        "Claude Code 更新",
        url="https://x.com/AnthropicAI/status/1",
        source_type="social",
        source_name="X",
    )
    same_url = _item("Claude Code 更新细节", url="https://anthropic.com/news/code")

    ranked = rank_ai_updates([social_duplicate, same_url, official], target_count=10)

    assert len(ranked) == 1
    assert ranked[0].source_type == "official"
    assert ranked[0].source_name == "Anthropic"
    assert ranked[0].verification_status == "social_confirmed"
    assert "https://x.com/AnthropicAI/status/1" in ranked[0].evidence_urls


def test_rank_ai_updates_backfills_with_social_when_official_sources_are_too_few():
    official = [_item(f"官方动态{i}", source_name="OpenAI") for i in range(3)]
    social = [
        _item(f"社交动态{i}", source_type="social", source_name="X", url=f"https://x.com/a/{i}")
        for i in range(12)
    ]

    ranked = rank_ai_updates(
        official + social,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
    )

    assert len(ranked) == 10
    assert sum(1 for item in ranked if item.source_type == "official") == 3
    assert sum(1 for item in ranked if item.source_type == "social") == 7


def test_rank_ai_updates_excludes_social_only_when_official_sources_are_enough():
    official = [_item(f"官方动态{i}", source_name="OpenAI") for i in range(10)]
    social = [
        _item(f"社交动态{i}", source_type="social", source_name="X", url=f"https://x.com/a/{i}")
        for i in range(4)
    ]

    ranked = rank_ai_updates(
        official + social,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
    )

    assert len(ranked) == 10
    assert all(item.source_type == "official" for item in ranked)
