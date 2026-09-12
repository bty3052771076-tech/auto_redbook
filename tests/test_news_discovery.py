import pytest
from datetime import datetime, timezone

from src.news import daily_news
from src.news.daily_news import NewsFetchSession, NewsItem
from src.workflow.news_discovery import feasible_news_batch, resolve_news_windows


def test_resolve_news_windows_defaults_to_adaptive_sequence():
    windows, meta = resolve_news_windows()

    assert windows == [1, 2, 3, 5]
    assert meta["mode"] == "auto"
    assert meta["max_allowed_days"] == 5


def test_resolve_news_windows_accepts_fixed_range_and_rejects_old_ranges():
    windows, meta = resolve_news_windows("4")

    assert windows == [4]
    assert meta["mode"] == "fixed"

    with pytest.raises(ValueError, match="auto.*整数1至5"):
        resolve_news_windows("7")


def test_feasible_news_batch_solves_count_china_and_source_capacity_together():
    items = [
        NewsItem(
            title="国内产业政策落地",
            url="https://china.example/policy",
            domain="china.example",
            sourcecountry="cn",
        ),
        NewsItem(
            title="Global market policy changes",
            url="https://global.example/policy",
            domain="global.example",
            language="en",
        ),
    ]

    selected = feasible_news_batch(items, 2, china=1, conflict=0)

    assert [item.url for item in selected] == [
        "https://china.example/policy",
        "https://global.example/policy",
    ]


def test_feasible_news_batch_returns_empty_when_required_category_is_absent():
    items = [
        NewsItem(
            title="Domestic technology update",
            url="https://china.example/technology",
            domain="china.example",
            sourcecountry="cn",
        ),
    ]

    assert feasible_news_batch(items, 2, china=1, conflict=0) == []


def test_fetch_session_uses_windows_timezone_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEWS_PROVIDER", "newsapi")
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)

    items, meta = daily_news.fetch_daily_news_candidates(
        "technology",
        tz_name="Asia/Shanghai",
        max_records=1,
        search_days=1,
        session=NewsFetchSession(
            now=datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc),
            remaining_seconds=1,
        ),
    )

    assert isinstance(items, list)
    assert "No time zone found with key Asia/Shanghai" not in str(meta)
