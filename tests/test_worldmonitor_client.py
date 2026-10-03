from __future__ import annotations

import json

import pytest

from src.integrations.worldmonitor.client import WorldMonitorClient, WorldMonitorError
from src.news import daily_news


def _payload() -> dict:
    return {
        "items": [
            {
                "id": "wm-1",
                "title": "Official report on a new event",
                "link": "https://example.com/news/1",
                "source": "Example Official",
                "publishedAt": 1779100800000,
                "description": "A concrete update with a named place.",
                "category": "world",
            }
        ],
        "categories": {"world": 1},
        "coverage": {"state": "fresh", "servedStale": False},
    }


def test_worldmonitor_client_parses_digest_and_preserves_coverage():
    body = json.dumps(_payload()).encode("utf-8")

    def fetcher(url: str, timeout: float):
        assert "list-feed-digest" in url
        assert timeout == 3.0
        return 200, {"content-type": "application/json"}, body

    result = WorldMonitorClient("http://127.0.0.1:3000", timeout=3.0, fetcher=fetcher).fetch_digest()

    assert result.items[0].title == "Official report on a new event"
    assert result.items[0].url == "https://example.com/news/1"
    assert result.coverage.state == "fresh"


def test_worldmonitor_client_rejects_html_and_reports_actionable_code():
    def fetcher(_url: str, _timeout: float):
        return 200, {"content-type": "text/html"}, b"<html>login</html>"

    with pytest.raises(WorldMonitorError, match="WM_INVALID_RESPONSE"):
        WorldMonitorClient("http://127.0.0.1:3000", fetcher=fetcher).fetch_digest()


def test_worldmonitor_client_cache_is_keyed_by_variant_and_language():
    calls = []

    def fetcher(url: str, _timeout: float):
        calls.append(url)
        query = url.split("?", 1)[1]
        return 200, {"content-type": "application/json"}, json.dumps({
            "items": [{
                "id": query,
                "title": query,
                "link": f"https://example.com/{len(calls)}",
                "source": "Example",
            }],
            "categories": {},
            "coverage": {"state": "fresh", "servedStale": False},
        }).encode()

    client = WorldMonitorClient("http://127.0.0.1:3000", fetcher=fetcher)
    full_zh = client.fetch_digest(variant="full", lang="zh")
    tech_zh = client.fetch_digest(variant="tech", lang="zh")
    again_full_zh = client.fetch_digest(variant="full", lang="zh")

    assert len(calls) == 2
    assert full_zh is again_full_zh
    assert tech_zh is not full_zh


def test_news_adapter_converts_worldmonitor_items(monkeypatch):
    body = json.dumps(_payload()).encode("utf-8")

    def fetcher(_url: str, _timeout: float):
        return 200, {"content-type": "application/json"}, body

    monkeypatch.setattr(daily_news, "WorldMonitorClient", lambda *_args, **_kwargs: WorldMonitorClient("x", fetcher=fetcher))
    monkeypatch.setenv("WORLDMONITOR_AUTO_START", "0")
    result = daily_news._worldmonitor_fetch_articles(base_url="http://127.0.0.1:3000", max_records=5, timeout_s=3)

    assert result[0].provider == "worldmonitor"
    assert result[0].url == "https://example.com/news/1"
