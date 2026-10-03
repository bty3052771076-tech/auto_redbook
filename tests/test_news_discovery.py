import pytest
from datetime import datetime, timezone

from src.news import daily_news
from src.news.daily_news import NewsFetchSession, NewsItem, daily_news_soft_preferences_enabled
from src.workflow.news_discovery import (
    DailyNewsDiscovery,
    feasible_news_batch,
    news_story_identity_keys,
    resolve_news_windows,
)


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


def test_daily_news_category_mix_is_soft_only_when_agent_policy_is_enabled(monkeypatch):
    monkeypatch.delenv("DAILY_NEWS_SELECTION_POLICY", raising=False)
    assert daily_news_soft_preferences_enabled() is False

    monkeypatch.setenv("DAILY_NEWS_SELECTION_POLICY", "soft")
    assert daily_news_soft_preferences_enabled() is True


def test_discovery_keeps_hard_quotas_by_default_and_disables_them_for_agent(monkeypatch):
    kwargs = dict(
        prompt="technology",
        count=10,
        windows=[1],
        window_meta={},
        raw_target=20,
        preferred_target=10,
        budget_seconds=1,
        fetch=lambda **kwargs: ([], {}),
        prepare=lambda items, progress_callback=None: {},
        incomplete=lambda item: False,
    )
    monkeypatch.delenv("DAILY_NEWS_SELECTION_POLICY", raising=False)
    strict = DailyNewsDiscovery(**kwargs)
    assert (strict.china, strict.conflict) == (2, 2)

    monkeypatch.setenv("DAILY_NEWS_SELECTION_POLICY", "agent")
    adaptive = DailyNewsDiscovery(**kwargs)
    assert (adaptive.china, adaptive.conflict) == (0, 0)


def test_discovery_excludes_existing_story_identities_before_selection(monkeypatch):
    now = datetime.now(timezone.utc)
    old = NewsItem(
        title="Old event reused by syndicated source",
        url="https://example.com/old-event?utm_source=feed",
        domain="example.com",
        seendate=now.isoformat(),
    )
    fresh = NewsItem(
        title="Fresh technology event for replenishment",
        url="https://example.com/fresh-event",
        domain="example.com",
        seendate=now.isoformat(),
    )
    discovery = DailyNewsDiscovery(
        prompt="technology",
        count=1,
        windows=[1],
        window_meta={},
        raw_target=2,
        preferred_target=1,
        budget_seconds=1,
        fetch=lambda prompt, **kwargs: ([old, fresh], {}),
        prepare=lambda items, progress_callback=None: {
            index: (item, {}, {}, item) for index, item in enumerate(items, 1)
        },
        incomplete=lambda item: False,
        excluded_story_keys={"title:oldeventreusedbysyndicatedsource"},
    )

    selected = discovery.take(initial=True)

    assert [item.title for item in selected] == [fresh.title]


def test_news_story_identity_keys_are_stable_for_batch_metadata():
    item = {
        "title": "A repeated event: update",
        "url": "https://example.com/repeated?utm_source=feed",
    }

    assert news_story_identity_keys(item) == {
        "url:https://example.com/repeated",
        "title:arepeatedeventupdate",
    }


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


def test_feasible_news_batch_relaxes_domain_cap_when_two_reachable_publishers_cannot_cover_target():
    items = [
        NewsItem(
            title=f"BBC story {index}",
            url=f"https://bbc.example/story-{index}",
            domain="bbc.example",
        )
        for index in range(5)
    ] + [
        NewsItem(
            title=f"Guardian story {index}",
            url=f"https://guardian.example/story-{index}",
            domain="guardian.example",
        )
        for index in range(5)
    ]

    selected = feasible_news_batch(items, 10, china=0, conflict=0)

    assert len(selected) == 10
    assert {item.domain for item in selected} == {"bbc.example", "guardian.example"}


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
