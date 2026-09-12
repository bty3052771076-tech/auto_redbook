from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.news import daily_news
from src.news.daily_news import NewsItem
from src.workflow import create_post


@pytest.mark.parametrize("title", [
    "US and Iranian forces fire at vessels near Iran",
    "US ambassador condemns Palestinian West Bank settler violence",
    "Witkoff and Kushner discuss Ukraine peace",
    "Lebanese students displaced by war",
])
def test_conflict_actions_are_recognized(title):
    assert daily_news.is_international_conflict_news(NewsItem(title=title, url="https://example.org/story"))


@pytest.mark.parametrize("title", [
    "US factory fire forces evacuation",
    "US company fires workers after merger",
    "US stocks rise as investors assess war in Iran",
    "Lebanese football team wins match",
])
def test_non_conflict_headlines_are_excluded(title):
    assert not daily_news.is_international_conflict_news(NewsItem(title=title, url="https://example.org/war"))


def test_required_queries_survive_limit_and_record_target(monkeypatch):
    monkeypatch.setenv("NEWS_EXHAUSTIVE_PROVIDER_QUERY_LIMIT", "2")
    monkeypatch.setattr(daily_news, "_load_newsapi_config", lambda: ("test-key", "https://example.org"))
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs["query"])
        return [NewsItem(title=kwargs["query"], url=f"https://example.org/{len(calls)}")]

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fetch)
    required = ["domestic policy", "international conflict", "ceasefire negotiations"]
    result = daily_news._fetch_news_provider(
        "newsapi", queries=["general news", "technology"], default_queries=[], hint_query="general news",
        from_iso="2026-09-06T00:00:00Z", to_iso="2026-09-06T12:00:00Z",
        start_dt=datetime(2026, 9, 6, tzinfo=timezone.utc),
        end_dt=datetime(2026, 9, 6, 12, tzinfo=timezone.utc),
        max_records=1, timeout_s=1, aggregate_empty_prompt=False, exhaustive_sources=True,
        auto_provider_selection=True, manual_materials_file="", required_queries=required,
    )
    assert result.error is None
    assert calls == required


def test_bbc_mixed_prompt_preserves_world_and_interleaves(monkeypatch):
    def rss(**kwargs):
        name = kwargs["source_name"]
        return [NewsItem(title=f"{name} {i}", url=f"https://example.org/{name}/{i}") for i in range(2)]

    monkeypatch.setattr(daily_news, "_rss_fetch_articles", rss)
    items = daily_news._bbc_rss_fetch_articles(prompt_hint="国际 体育 财经 科技", max_records=4, timeout_s=1)
    assert len(items) == 4
    assert "World" in items[0].title
    assert any("Sport" in item.title for item in items)
    assert any("Business" in item.title for item in items)
    assert any("Technology" in item.title for item in items)


def test_repeated_headline_is_not_substantive_context():
    title = "Example company announces a new chip"
    item = NewsItem(title=title, url="https://example.org", description=(title + ". ") * 20)
    assert create_post._daily_news_context_is_incomplete(item)


def test_sufficient_context_skips_network_but_keeps_focus(monkeypatch):
    item = NewsItem(title="Factory expansion", url="https://example.org", description=(
        "The company will open a second production line in its existing factory in November. "
        "The project includes equipment replacement, worker training and an independent inspection before operations begin."
    ))
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda _: pytest.fail("Unneeded network lookup"))
    monkeypatch.setattr(create_post, "_focus_daily_news_item", lambda value: (replace(value, title="Focused factory expansion"), {}))
    result = create_post._prefetch_daily_news_context([item])[1]
    assert result[0].title == "Focused factory expansion"
    assert result[1]["source_lookup"]["skipped"] == "sufficient_api_context"
