from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ai_digest.sources import default_ai_digest_sources
from src.sources.health import (
    SourceAttempt,
    SourceHealthSnapshot,
    is_source_in_cooldown,
    load_source_health_snapshot,
    save_source_health_snapshot,
)


def test_source_health_marks_timeout_in_cooldown_until_expiry():
    checked_at = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    attempt = SourceAttempt(
        collection="ai_digest",
        source_name="slow-official-feed",
        source_url="https://example.com/feed.xml",
        tier="official_stream",
        status="timeout",
        checked_at=checked_at.isoformat(),
        elapsed_seconds=8.0,
    )

    assert is_source_in_cooldown(
        attempt,
        now=checked_at + timedelta(minutes=4),
        cooldown_seconds=300,
    )
    assert not is_source_in_cooldown(
        attempt,
        now=checked_at + timedelta(minutes=6),
        cooldown_seconds=300,
    )


def test_successful_official_stream_is_not_cooled_down():
    checked_at = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    attempt = SourceAttempt(
        collection="ai_digest",
        source_name="official-feed",
        source_url="https://example.com/feed.xml",
        tier="official_stream",
        status="success",
        checked_at=checked_at.isoformat(),
        elapsed_seconds=0.4,
        item_count=4,
        dated_count=4,
        url_count=4,
    )

    assert not is_source_in_cooldown(
        attempt,
        now=checked_at + timedelta(seconds=1),
        cooldown_seconds=300,
    )


def test_stale_or_missing_date_source_is_cooled_down_briefly():
    checked_at = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    stale_attempt = SourceAttempt(
        collection="ai_digest",
        source_name="stale-page",
        source_url="https://example.com/news",
        tier="official_page",
        status="stale",
        checked_at=checked_at.isoformat(),
    )
    missing_date_attempt = SourceAttempt(
        collection="ai_digest",
        source_name="undated-page",
        source_url="https://example.com/updates",
        tier="official_page",
        status="missing_date",
        checked_at=checked_at.isoformat(),
    )

    assert is_source_in_cooldown(stale_attempt, now=checked_at + timedelta(minutes=2), cooldown_seconds=300)
    assert is_source_in_cooldown(missing_date_attempt, now=checked_at + timedelta(minutes=2), cooldown_seconds=300)


def test_source_health_snapshot_round_trips_without_workspace_global_state(tmp_path):
    snapshot = SourceHealthSnapshot(
        collection="daily_news",
        generated_at="2026-07-10T08:00:00Z",
        attempts=[
            SourceAttempt(
                collection="daily_news",
                source_name="google-rss",
                source_url="https://news.google.com/rss/search",
                tier="dated_rss",
                status="success",
                checked_at="2026-07-10T08:00:00Z",
                elapsed_seconds=0.8,
                item_count=20,
                dated_count=20,
                url_count=20,
            )
        ],
    )
    path = tmp_path / "source_health.json"

    save_source_health_snapshot(snapshot, path)
    loaded = load_source_health_snapshot(path)

    assert loaded is not None
    assert loaded.collection == "daily_news"
    assert loaded.attempts[0].source_name == "google-rss"
    assert loaded.attempts[0].dated_count == 20


def test_source_catalog_distinguishes_stream_page_and_aggregator_tiers():
    by_name = {source.name: source for source in default_ai_digest_sources()}

    assert by_name["deepseek"].tier == "official_stream"
    assert by_name["deepseek"].url == "https://api-docs.deepseek.com/updates"
    assert by_name["bytedance-seed"].tier == "official_stream"
    assert by_name["bytedance-seed"].url == "https://seed.bytedance.com/blog"
    assert by_name["huggingface"].tier == "aggregator"
    assert by_name["x"].tier == "social_backfill"
