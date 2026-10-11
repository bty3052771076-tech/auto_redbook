from datetime import datetime, timezone

import pytest

from src.ai_digest import collect, fetchers
from src.ai_digest.rank import ai_digest_official_count, ai_update_history_key
from src.ai_digest.sources import AIDigestSource, resolve_ai_digest_sources
from src.sources.health import SourceAttempt, SourceHealthSnapshot, save_source_health_snapshot


NOW = datetime(2026, 10, 11, 5, tzinfo=timezone.utc)
URL = "https://sierra.ai/blog/poppy"
CARDS = '''<header><h3>Weekly highlights</h3></header>
<article id="r-one"><div>OpenAI Newsroom</div>
<h3><a href="/items/one">OpenAI research leader responds to departures</a></h3>
<p>This statement describes the research team's response to employee departures.</p>
<a href="https://openai.com/index/statement/" target="_blank">Original</a></article>
<article id="r-two"><div>Sierra Blog</div>
<h3><a href="/items/two">Sierra releases Personal Agent Protocol Poppy draft</a></h3>
<p>Sierra publishes a personal agent protocol draft and adds 35 design partners.</p>
<a href="https://sierra.ai/blog/poppy" target="_blank">Original</a></article>'''
ARTICLE = '''<meta content="2026-10-09T19:56:06.371Z" property="article:published_time">
<meta name="description" content="Today we publish the Personal Agent Protocol Poppy draft for AI agents and announce additional design partners.">
<h1>Personal Agent Protocol</h1>'''


def parsed():
    return fetchers.parse_aihot_daily_html(CARDS, source_name="AI HOT", vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-10-10", published_date="2026-10-10")


def test_default_discovery_includes_public_daily_but_respects_whitelist():
    assert "aihot-daily" in {s.name for s in resolve_ai_digest_sources({})}
    sources = resolve_ai_digest_sources({"AI_DIGEST_PRIMARY_SOURCES": "deepseek"})
    assert "aihot-daily" not in {s.name for s in sources}


def test_rendered_articles_keep_title_summary_and_original_link_together():
    items = parsed()
    assert len(items) == 2
    assert items[1].title == "Sierra releases Personal Agent Protocol Poppy draft"
    assert items[1].summary.startswith("Sierra publishes")
    assert items[1].url == URL
    assert items[1].evidence_urls == ["https://aihot.virxact.com/items/two"]
    assert items[1].published_at == ""
    assert items[1].source_type == "aggregator"


@pytest.mark.parametrize("metadata", [ARTICLE,
    '<script type="application/ld+json">{"@type":"NewsArticle",'
    '"datePublished":"2026-10-09T19:56:06.371Z",'
    '"description":"Personal Agent Protocol Poppy draft for AI agents and additional design partners."}</script>'])
def test_original_metadata_preserves_timestamp_across_beijing_midnight(monkeypatch, metadata):
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: metadata)
    item = collect.resolve_ai_digest_discovery_source(parsed()[1])
    assert item.source_type == "official"
    assert item.vendor == "sierra"
    assert item.published_at == "2026-10-09T19:56:06.371Z"
    assert item.verification_status == "aggregator_confirmed"
    assert "Personal Agent Protocol" in item.raw_excerpt


@pytest.mark.parametrize("metadata", [
    '<meta property="article:modified_time" content="2026-10-11">',
    '<time datetime="2026-10-11">Related article</time>',
    '<script type="application/ld+json">{"@type":"WebSite","datePublished":"2026-10-11"}</script>',
])
def test_missing_original_publication_date_never_uses_daily_date(monkeypatch, metadata):
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: metadata)
    item = collect.resolve_ai_digest_discovery_source(parsed()[1])
    assert item.published_at == ""
    assert item.source_type == "aggregator"


def test_unknown_or_private_original_is_not_fetched(monkeypatch):
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: pytest.fail("Untrusted URL fetched"))
    for url in ["http://127.0.0.1/internal", "https://sierra.ai.evil.test/blog/poppy"]:
        item = parsed()[1].model_copy(update={"url": url})
        assert collect.resolve_ai_digest_discovery_source(item).source_type == "aggregator"


def test_health_snapshot_uses_verified_original_dates(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: ARTICLE)
    source = AIDigestSource("aihot-daily", "aggregator", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily")
    path = tmp_path / "health.json"
    _, meta = collect.collect_ai_digest_updates(sources=[source],
        fetch_source=lambda s: parsed()[1:], target_count=1, min_official_count=1,
        max_age_days=2, now=NOW, source_health_path=path)
    attempt = meta["source_health"]["attempts"][0]
    assert attempt["status"] == "success"
    assert attempt["dated_count"] == 1
    assert attempt["recent_statuses"] == ["success"]


def test_verified_discovery_passes_the_actual_adaptive_selector(monkeypatch):
    from src.ai_digest import rank
    from src.workflow.create_post import _select_adaptive_ai_digest_items

    original_clock = rank._as_datetime
    monkeypatch.setattr(rank, "_as_datetime", lambda value: NOW if value is None else original_clock(value))
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: ARTICLE)
    verified = collect.resolve_ai_digest_discovery_source(parsed()[1])
    selected, meta = _select_adaptive_ai_digest_items([verified],
        impact_scores={verified.dedupe_key: {"high_impact": True}}, historical_keys=set(),
        min_items=1, max_items=20, min_official_count=6,
        min_domestic_model_count=2, min_foreign_ai_count=3)
    assert selected == [verified]
    assert meta["effective_min_official_items"] == 1


@pytest.mark.parametrize("date,expected", [
    ("2026-10-09T19:56:06.371Z", 1),
    ("2026-09-03T19:56:06Z", 0),
    ("2026-10-12T19:56:06Z", 0),
])
def test_collection_resolves_current_original_before_date_and_history_gates(monkeypatch, date, expected):
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    monkeypatch.setattr(collect, "_http_get_text", lambda *a, **k: ARTICLE.replace("2026-10-09T19:56:06.371Z", date))
    source = AIDigestSource("aihot-daily", "aggregator", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily")
    items, meta = collect.collect_ai_digest_updates(sources=[source],
        fetch_source=lambda s: parsed()[1:], target_count=1, min_official_count=1,
        include_pool_items=True, max_age_days=2, now=NOW, persist_source_health=False)
    assert len(items) == expected
    assert ai_digest_official_count(items) == expected
    assert meta["discovery_source_resolution"]["official"] == 1
    if expected:
        verified = items[0]
        repeated, meta = collect.collect_ai_digest_updates(sources=[source],
            fetch_source=lambda s: parsed()[1:], target_count=1, min_official_count=1,
            include_pool_items=True, max_age_days=2, now=NOW, persist_source_health=False,
            exclude_history_keys={ai_update_history_key(verified)})
        assert repeated == []
        assert meta["source_history_filter"]["by_source"]["discovery_resolution"] == 1


@pytest.mark.parametrize("age_hours,expected", [(7, True), (1, False)])
def test_replaced_github_feed_reprobes_after_cooldown(monkeypatch, tmp_path, age_hours, expected):
    from datetime import timedelta
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    source = AIDigestSource("qwen-github", "github", "https://api.github.com/repos/QwenLM/Qwen3/releases", "Qwen", "github_releases")
    path = tmp_path / "health.json"
    save_source_health_snapshot(SourceHealthSnapshot(collection="ai_digest", generated_at=NOW.isoformat(), attempts=[
        SourceAttempt(collection="ai_digest", source_name=source.name, source_url=source.url,
            tier=source.tier, status="empty", checked_at=(NOW - timedelta(hours=age_hours)).isoformat(),
            recent_statuses=("empty",) * 5)]), path)
    calls = []
    collect.collect_ai_digest_updates(sources=[source], fetch_source=lambda s: calls.append(s.name) or [],
        target_count=1, max_age_days=2, now=NOW, source_health_path=path, persist_source_health=False)
    assert bool(calls) is expected
