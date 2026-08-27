from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Barrier, BrokenBarrierError

import pytest

from src.ai_digest import collect as collect_mod
from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import ai_digest_quota_counts, ai_update_history_key
from src.ai_digest.sources import AIDigestSource
from src.news.daily_news import NewsItem
from src.sources.health import (
    SourceAttempt,
    SourceHealthSnapshot,
    load_source_health_snapshot,
    save_source_health_snapshot,
)


@pytest.fixture(autouse=True)
def _disable_external_ai_digest_search_backfill(monkeypatch):
    """Keep collection unit tests offline unless search backfill is under test."""
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")


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


def test_prompt_topic_official_backfill_verifies_and_returns_all_requested_topics(monkeypatch):
    monkeypatch.setattr(collect_mod, "_http_get_text", lambda _url, timeout_s=12.0: "<html>official page</html>" * 20)
    topics = [
        "Qwen3.8-Flash-Next正式发布",
        "GLM-5.3-Flash发布",
        "QwenWork International上线",
        "Codex plus用户回复5小时限制",
        "Breeze TTS 2权重公开可用",
    ]

    items, meta = collect_mod.fetch_ai_digest_prompt_topic_backfill(topics=topics)

    assert meta["verified"] == topics
    assert meta["failed"] == []
    assert [item.product for item in items] == topics
    assert all(item.source_type == "official" for item in items)
    assert all(item.url and item.published_at for item in items)
    assert [item.published_at for item in items] == [
        "2026-08-26",
        "2026-08-26",
        "2026-08-03",
        "2026-08-25",
        "2026-08-25",
    ]


def test_collect_ai_digest_updates_passes_prompt_topics_to_forced_search_backfill(monkeypatch):
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
    ]
    captured: dict[str, object] = {}

    def fake_search_backfill(**kwargs):
        captured.update(kwargs)
        return [_item("Qwen3.8-Flash-Next正式发布", "search")], {"queries": [], "errors": []}

    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "1")
    monkeypatch.setattr(collect_mod, "fetch_ai_digest_search_backfill", fake_search_backfill)

    collect_ai_digest_updates(
        sources=sources,
        fetch_source=lambda _source: [_item("official-release")],
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
        force_search_backfill=True,
        search_backfill_queries=["Qwen3.8-Flash-Next正式发布"],
    )

    assert captured["queries"] == ["Qwen3.8-Flash-Next正式发布"]


def test_collect_ai_digest_updates_skips_social_when_official_sources_are_enough():
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
        AIDigestSource("x", "social", "https://x.com/search", "X", "social_html"),
        AIDigestSource("huggingface", "aggregator", "https://huggingface.co/blog/feed.xml", "Hugging Face", "rss"),
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
    assert meta["aggregator_backfill_used"] is False


def test_collect_ai_digest_updates_excludes_uploaded_history_before_ranking():
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
    ]
    repeated = _item("TokenHub service terms update")
    fresh = _item("New model release")

    def fake_fetch(_source):
        return [repeated, fresh]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=2,
        min_official_count=1,
        include_pool_items=True,
        exclude_history_keys={ai_update_history_key(repeated)},
    )

    assert [item.title for item in items] == ["New model release"]
    assert meta["historical_excluded_count"] == 1
    assert meta["source_history_filter"]["by_source"] == {"official": 1}
    assert [item.title for item in meta["_fetched_items"]] == ["New model release"]


def test_collect_ai_digest_updates_can_force_aggregator_backfill_for_history_deduplication():
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Fixture", "rss"),
        AIDigestSource("aggregator", "aggregator", "https://example.com/agg", "Aggregator", "rss"),
        AIDigestSource("x", "social", "https://x.com/search", "X", "social_html"),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.kind == "official":
            return [_item(f"official-{i}") for i in range(8)]
        if source.kind == "aggregator":
            return [_item(f"aggregator-{i}", "aggregator") for i in range(2)]
        return [_item("social-1", "social")]

    _items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=10,
        min_official_count=6,
        force_aggregator_backfill=True,
    )

    assert calls == ["official", "aggregator"]
    assert meta["aggregator_backfill_used"] is True
    assert meta["aggregator_backfill_forced"] is True
    assert meta["social_backfill_used"] is False


def test_collect_ai_digest_skips_recent_timeout_and_persists_attempt_trace(tmp_path):
    now = datetime(2026, 6, 30, 9, tzinfo=timezone.utc)
    health_path = tmp_path / "source_health" / "ai_digest.json"
    save_source_health_snapshot(
        SourceHealthSnapshot(
            collection="ai_digest",
            generated_at=(now - timedelta(minutes=1)).isoformat(),
            attempts=[
                SourceAttempt(
                    collection="ai_digest",
                    source_name="timed-out",
                    source_url="https://example.com/timed-out",
                    tier="official_stream",
                    status="timeout",
                    checked_at=(now - timedelta(minutes=1)).isoformat(),
                    elapsed_seconds=8.0,
                    error="timed out",
                )
            ],
        ),
        health_path,
    )
    sources = [
        AIDigestSource("timed-out", "official", "https://example.com/timed-out", "Timed", "rss"),
        AIDigestSource("healthy", "official", "https://example.com/healthy", "Healthy", "rss"),
    ]
    calls: list[str] = []

    def fake_fetch(source):
        calls.append(source.name)
        return [_item("healthy-release")]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=1,
        min_official_count=1,
        allow_social_backfill=False,
        max_age_days=3,
        now=now,
        source_health_path=health_path,
        source_cooldown_seconds=300,
        persist_source_health=True,
    )

    assert [item.title for item in items] == ["healthy-release"]
    assert calls == ["healthy"]
    assert meta["source_health"]["cooldown_skipped"] == ["timed-out"]
    healthy_attempt = next(
        item for item in meta["source_health"]["attempts"] if item["source_name"] == "healthy"
    )
    assert healthy_attempt["status"] == "success"
    assert healthy_attempt["item_count"] == 1
    assert healthy_attempt["dated_count"] == 1
    assert healthy_attempt["url_count"] == 1

    persisted = load_source_health_snapshot(health_path)
    assert persisted is not None
    persisted_by_name = {item.source_name: item for item in persisted.attempts}
    assert persisted_by_name["timed-out"].status == "timeout"
    assert persisted_by_name["healthy"].status == "success"


def test_collect_ai_digest_replaces_source_after_timeout_ratio_threshold(tmp_path):
    now = datetime(2026, 8, 23, 9, tzinfo=timezone.utc)
    health_path = tmp_path / "source_health" / "ai_digest.json"
    save_source_health_snapshot(
        SourceHealthSnapshot(
            collection="ai_digest",
            generated_at=now.isoformat(),
            attempts=[
                SourceAttempt(
                    collection="ai_digest",
                    source_name="unstable",
                    source_url="https://example.com/unstable",
                    tier="official_page",
                    status="timeout",
                    checked_at=now.isoformat(),
                    recent_statuses=("timeout", "timeout", "success", "timeout", "success"),
                )
            ],
        ),
        health_path,
    )
    sources = [
        AIDigestSource("unstable", "official", "https://example.com/unstable", "Unstable", "rss"),
        AIDigestSource("healthy", "official", "https://example.com/healthy", "Healthy", "rss"),
    ]
    calls: list[str] = []

    def fake_fetch(source):
        calls.append(source.name)
        return [_item("healthy-update")]

    _items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=1,
        min_official_count=1,
        allow_social_backfill=False,
        max_age_days=3,
        now=now,
        source_health_path=health_path,
        persist_source_health=True,
    )

    assert calls == ["healthy"]
    assert meta["source_health"]["replacement_skipped"] == ["unstable"]


def test_collect_ai_digest_fetches_official_streams_before_pages():
    calls: list[str] = []
    sources = [
        AIDigestSource(
            "official-page",
            "official",
            "https://example.com/page",
            "Page",
            "html",
            tier="official_page",
        ),
        AIDigestSource(
            "official-stream",
            "official",
            "https://example.com/feed",
            "Stream",
            "rss",
            tier="official_stream",
        ),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        return [_item(source.name)]

    collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=2,
        min_official_count=1,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
    )

    assert calls == ["official-stream", "official-page"]


def test_collect_ai_digest_does_not_fetch_official_pages_when_streams_fill_the_pool():
    calls: list[str] = []
    sources = [
        AIDigestSource(
            "official-page",
            "official",
            "https://example.com/page",
            "Page",
            "html",
            tier="official_page",
        ),
        AIDigestSource(
            "official-stream",
            "official",
            "https://example.com/feed",
            "Stream",
            "rss",
            tier="official_stream",
        ),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        return [_item("stream-1"), _item("stream-2")] if source.name == "official-stream" else [_item("page")]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=2,
        min_official_count=1,
        allow_social_backfill=False,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
    )

    assert calls == ["official-stream"]
    assert len(items) == 2
    assert meta["official_page_backfill_used"] is False


def test_collect_ai_digest_fills_requested_candidate_pool_before_stopping_sources():
    calls: list[str] = []
    sources = [
        AIDigestSource(
            "official-page",
            "official",
            "https://example.com/page",
            "Page",
            "html",
            tier="official_page",
        ),
        AIDigestSource(
            "official-stream",
            "official",
            "https://example.com/feed",
            "Stream",
            "rss",
            tier="official_stream",
        ),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.name == "official-stream":
            return [_item(f"stream-{index}") for index in range(8)]
        return [_item(f"page-{index}") for index in range(2)]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=False,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        include_pool_items=True,
    )

    assert calls == ["official-stream", "official-page"]
    assert len(items) == 10
    assert len(meta["_deduped_items"]) == 10
    assert meta["official_page_backfill_used"] is True


def test_collect_ai_digest_fetches_same_stage_sources_concurrently_when_requested():
    barrier = Barrier(2)
    sources = [
        AIDigestSource(
            "stream-a",
            "official",
            "https://example.com/a",
            "A",
            "rss",
            tier="official_stream",
        ),
        AIDigestSource(
            "stream-b",
            "official",
            "https://example.com/b",
            "B",
            "rss",
            tier="official_stream",
        ),
    ]

    def fake_fetch(source):
        try:
            barrier.wait(timeout=0.5)
        except BrokenBarrierError:
            return []
        return [_item(source.name)]

    items, _meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=2,
        min_official_count=1,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
        source_concurrency=2,
        batch_timeout_s=1.0,
    )

    assert {item.title for item in items} == {"stream-a", "stream-b"}


def test_collect_ai_digest_marks_source_with_only_missing_dates_as_missing_date():
    source = AIDigestSource(
        "missing-date",
        "official",
        "https://example.com/missing-date",
        "Missing date",
        "rss",
        tier="official_stream",
    )
    missing_date = _item("undated-release").model_copy(update={"published_at": ""})

    _items, meta = collect_ai_digest_updates(
        sources=[source],
        fetch_source=lambda _source: [missing_date],
        target_count=1,
        min_official_count=1,
        allow_social_backfill=False,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
    )

    assert meta["source_health"]["attempts"][0]["status"] == "missing_date"


def test_collect_ai_digest_marks_source_with_only_old_items_as_stale():
    source = AIDigestSource(
        "stale-source",
        "official",
        "https://example.com/stale",
        "Stale",
        "rss",
        tier="official_stream",
    )
    stale_item = _item("old-release").model_copy(update={"published_at": "2026-06-20T08:00:00Z"})

    _items, meta = collect_ai_digest_updates(
        sources=[source],
        fetch_source=lambda _source: [stale_item],
        target_count=1,
        min_official_count=1,
        allow_social_backfill=False,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
    )

    assert meta["source_health"]["attempts"][0]["status"] == "stale"


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


def test_collect_ai_digest_uses_aggregator_before_social_and_stops_when_pool_is_full(monkeypatch):
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "Official", "rss"),
        AIDigestSource("aihot", "aggregator", "https://aihot.example/daily", "AI HOT", "aihot_daily"),
        AIDigestSource("x", "social", "https://x.com/search", "X", "social_html"),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.kind == "official":
            return [_item("official-1")]
        if source.kind == "aggregator":
            return [_item(f"aggregator-{i}", "aggregator") for i in range(7)]
        return [_item(f"social-{i}", "social") for i in range(10)]

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=8,
        min_official_count=6,
        allow_social_backfill=True,
        max_age_days=3,
        now=datetime(2026, 6, 30, 9, tzinfo=timezone.utc),
    )

    assert calls == ["official", "aihot"]
    assert [item.source_type for item in items] == ["official", *(["aggregator"] * 7)]
    assert meta["aggregator_backfill_used"] is True
    assert meta["social_backfill_used"] is False


def test_collect_ai_digest_updates_uses_aggregators_before_search_and_social(monkeypatch):
    calls: list[str] = []
    sources = [
        AIDigestSource("official", "official", "https://example.com/rss", "OpenAI", "rss"),
        AIDigestSource("aihot-daily", "aggregator", "https://aihot.example/daily", "AI HOT", "aihot_daily"),
        AIDigestSource("huggingface", "aggregator", "https://huggingface.co/blog/feed.xml", "Hugging Face", "rss"),
    ]

    def fake_fetch(source):
        calls.append(source.name)
        if source.name == "official":
            return [
                AIUpdateItem(
                    title="OpenAI GPT 工具更新",
                    summary="OpenAI 发布 GPT API 和开发者工具更新。",
                    source_name="OpenAI",
                    source_type="official",
                    url="https://openai.com/news/gpt-tools",
                    published_at="2026-07-02T08:00:00Z",
                    vendor="OpenAI",
                    product="GPT",
                    raw_excerpt="OpenAI GPT API update.",
                )
            ]
        if source.name == "aihot-daily":
            return [
                AIUpdateItem(
                    title="智谱 GLM-5.2 模型发布",
                    summary="智谱发布 GLM-5.2 模型更新。",
                    source_name="AI HOT",
                    source_type="aggregator",
                    url="https://aihot.example/daily/1",
                    published_at="2026-07-02T09:00:00Z",
                    vendor="智谱 GLM",
                    product="GLM-5.2",
                    raw_excerpt="智谱发布 GLM-5.2 模型更新。",
                )
            ]
        return [
            AIUpdateItem(
                title=f"Hugging Face 模型发布合集 {i}",
                summary="Hugging Face 社区模型发布和推理工具更新。",
                source_name="Hugging Face",
                source_type="aggregator",
                url=f"https://huggingface.co/blog/model-{i}",
                published_at=f"2026-07-02T1{i}:00:00Z",
                vendor="Hugging Face",
                product=f"Model-{i}",
                raw_excerpt="Hugging Face model release.",
            )
            for i in range(6)
        ]

    def fake_search_backfill(**_kwargs):
        calls.append("search-backfill")
        return [], {"queries": [], "errors": []}

    monkeypatch.setattr(collect_mod, "fetch_ai_digest_search_backfill", fake_search_backfill)

    items, meta = collect_ai_digest_updates(
        sources=sources,
        fetch_source=fake_fetch,
        target_count=8,
        min_official_count=6,
        allow_social_backfill=True,
        max_age_days=3,
        now=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        min_domestic_model_count=1,
        min_foreign_ai_count=3,
    )

    assert calls == ["official", "aihot-daily", "huggingface"]
    assert meta["aggregator_backfill_used"] is True
    assert meta["search_backfill_used"] is False
    assert any(item.vendor == "Hugging Face" for item in items)
    assert meta["quota_counts"]["foreign_ai"] >= 3


def test_collect_ai_digest_updates_uses_search_backfill_for_daily_digest_quotas(monkeypatch):
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "1")
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


def test_search_backfill_disables_daily_news_query_expansion(monkeypatch):
    calls: list[dict] = []

    def fake_fetch_daily_news_candidates(_query, **kwargs):
        calls.append(kwargs)
        return [
            NewsItem(
                title="GLM-5.2 模型发布",
                url="https://example.com/glm",
                source="Example",
                domain="example.com",
                seendate="2026-07-02T08:00:00Z",
                description="智谱发布 GLM-5.2 模型更新。",
            )
        ], {"tz": "Asia/Shanghai"}

    monkeypatch.setattr("src.news.daily_news.fetch_daily_news_candidates", fake_fetch_daily_news_candidates)

    items, meta = collect_mod.fetch_ai_digest_search_backfill(
        max_age_days=3,
        now=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        queries=["国内 AI 模型 发布 GLM Qwen 豆包 DeepSeek Kimi MiniMax"],
        max_records=5,
    )

    assert len(items) == 1
    assert calls[0]["expand_query_variants"] is False
    assert meta["queries"][0]["converted_count"] == 1


def test_search_backfill_removes_provider_paid_plan_boilerplate(monkeypatch):
    def fake_fetch_daily_news_candidates(_query, **_kwargs):
        return [
            NewsItem(
                title="What is Kimi K3? New open-weight model explained",
                url="https://example.com/kimi-k3",
                source="Example",
                domain="example.com",
                seendate="2026-07-28T08:45:00Z",
                description=(
                    "Moonshot AI released Kimi K3 for coding and agent workflows. "
                    "ONLY AVAILABLE IN PAID PLANS"
                ),
            ),
            NewsItem(
                title="Why your AI resume sounds generic",
                url="https://example.com/ai-resume",
                source="Example",
                domain="example.com",
                seendate="2026-07-27T21:44:10Z",
                description="ONLY AVAILABLE IN PAID PLANS",
            ),
        ], {"tz": "Asia/Shanghai"}

    monkeypatch.setattr("src.news.daily_news.fetch_daily_news_candidates", fake_fetch_daily_news_candidates)

    items, _meta = collect_mod.fetch_ai_digest_search_backfill(
        max_age_days=3,
        now=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        queries=["AI model release"],
        max_records=5,
    )

    assert "PAID PLANS" not in items[0].raw_excerpt
    assert items[0].raw_excerpt == "Moonshot AI released Kimi K3 for coding and agent workflows."
    assert items[1].raw_excerpt == ""
