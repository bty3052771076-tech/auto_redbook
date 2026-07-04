from __future__ import annotations

from datetime import datetime, timezone

from src.ai_digest import collect as collect_mod
from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import ai_digest_quota_counts
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


def test_collect_ai_digest_updates_uses_search_backfill_for_daily_digest_quotas(monkeypatch):
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "OpenAI", "rss"),
    ]

    def fake_fetch(_source):
        return [
            AIUpdateItem(
                title=f"OpenAI GPT 工具更新{i}",
                summary="OpenAI 发布 GPT API 和开发者工具更新。",
                source_name="OpenAI",
                source_type="official",
                url=f"https://openai.com/news/{i}",
                published_at="2026-07-02T08:00:00Z",
                vendor="OpenAI",
                product=f"GPT-{i}",
                raw_excerpt="OpenAI GPT API update.",
            )
            for i in range(3)
        ]

    search_items = [
        AIUpdateItem(
            title="GLM-5.2 模型发布",
            summary="智谱发布 GLM-5.2 模型更新。",
            source_name="搜索",
            source_type="search",
            url="https://example.com/glm",
            published_at="2026-07-02T09:00:00Z",
            vendor="智谱 GLM",
            product="GLM-5.2",
            raw_excerpt="智谱发布 GLM-5.2 模型更新。",
        ),
        AIUpdateItem(
            title="Qwen3-Coder API 升级",
            summary="阿里云百炼更新 Qwen3-Coder API。",
            source_name="搜索",
            source_type="search",
            url="https://example.com/qwen",
            published_at="2026-07-02T09:10:00Z",
            vendor="阿里云百炼",
            product="Qwen3-Coder",
            raw_excerpt="阿里云百炼更新 Qwen3-Coder API。",
        ),
        AIUpdateItem(
            title="豆包 Doubao-Seed 模型更新",
            summary="火山方舟更新豆包模型能力。",
            source_name="搜索",
            source_type="search",
            url="https://example.com/doubao",
            published_at="2026-07-02T09:20:00Z",
            vendor="火山方舟",
            product="Doubao-Seed",
            raw_excerpt="火山方舟更新豆包模型能力。",
        ),
        AIUpdateItem(
            title="Anthropic Claude Code 工具更新",
            summary="Anthropic 更新 Claude Code。",
            source_name="搜索",
            source_type="search",
            url="https://example.com/claude",
            published_at="2026-07-02T09:30:00Z",
            vendor="Anthropic",
            product="Claude Code",
            raw_excerpt="Anthropic updates Claude Code.",
        ),
        AIUpdateItem(
            title="Google Gemini 推理更新",
            summary="Google 更新 Gemini 推理能力。",
            source_name="搜索",
            source_type="search",
            url="https://example.com/gemini",
            published_at="2026-07-02T09:40:00Z",
            vendor="Google DeepMind",
            product="Gemini",
            raw_excerpt="Google updates Gemini reasoning.",
        ),
    ]
    calls: list[dict] = []

    def fake_search_backfill(**kwargs):
        calls.append(kwargs)
        return search_items, {"queries": [{"query": "fixture"}], "errors": []}

    monkeypatch.setattr(collect_mod, "fetch_ai_digest_search_backfill", fake_search_backfill)

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=8,
        min_official_count=6,
        allow_social_backfill=True,
        max_age_days=3,
        now=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        min_domestic_model_count=3,
        min_foreign_ai_count=3,
    )

    counts = ai_digest_quota_counts(items)
    assert calls
    assert len(items) == 8
    assert counts["domestic_model"] >= 3
    assert counts["foreign_ai"] >= 3
    assert meta["search_backfill_used"] is True
    assert meta["quota_counts"] == counts
