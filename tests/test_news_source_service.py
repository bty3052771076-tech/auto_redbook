from __future__ import annotations

from datetime import datetime, timezone
import json

from src.sources.models import SourceRequest, SourceSpec
from src.sources.registry import SourceRegistry
from src.sources.service import UnifiedNewsSourceService, parse_feed_bytes


def _request(**overrides):
    value = {
        "request_id": "req-1",
        "run_id": "run-1",
        "purpose": "daily_news",
        "prompt": "technology",
        "as_of": datetime(2026, 9, 21, tzinfo=timezone.utc),
        "timeout_s": 5,
        "target_count": 2,
        "max_records": 10,
        "source_packs": ("daily_news",),
    }
    value.update(overrides)
    return SourceRequest(**value)


def test_parse_rss_and_atom_preserve_publisher_and_date():
    rss = b'''<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Concrete update</title><link>https://publisher.test/a</link>
      <pubDate>Mon, 21 Sep 2026 02:00:00 GMT</pubDate><description>Details</description>
    </item></channel></rss>'''
    spec = SourceSpec.from_mapping({
        "source_id": "publisher-rss", "adapter": "rss", "publisher_id": "publisher",
        "publisher_family": "publisher", "source_url": "https://publisher.test/rss",
    })
    result = parse_feed_bytes(rss, source=spec)
    assert result[0].publisher_id == "publisher"
    assert result[0].published_at == "2026-09-21T02:00:00+00:00"

    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Atom update</title><link href="https://publisher.test/b"/>
      <updated>2026-09-21T03:00:00Z</updated><summary>Summary</summary>
    </entry></feed>'''
    atom_result = parse_feed_bytes(atom, source=spec)
    assert atom_result[0].url.endswith("/b")
    assert atom_result[0].published_at == "2026-09-21T03:00:00+00:00"


def test_service_merges_legacy_api_and_rss_without_duplicate_articles(tmp_path, monkeypatch):
    rss_spec = SourceSpec.from_mapping({
        "source_id": "publisher-rss", "adapter": "rss", "publisher_id": "publisher",
        "publisher_family": "publisher", "source_url": "https://publisher.test/rss",
        "source_packs": ["daily_news"],
    })
    registry = SourceRegistry([rss_spec])
    service = UnifiedNewsSourceService(registry, snapshot_dir=tmp_path)

    def fake_fetch(_url, _timeout):
        body = b'''<rss version="2.0"><channel><item>
          <title>Same event</title><link>https://publisher.test/a</link>
          <pubDate>Mon, 21 Sep 2026 02:00:00 GMT</pubDate><description>RSS detail</description>
        </item><item><title>RSS only</title><link>https://publisher.test/c</link></item></channel></rss>'''
        return 200, {"content-type": "application/rss+xml"}, body

    monkeypatch.setattr(service, "_fetch_rss", lambda spec, timeout: service_result(spec, fake_fetch))

    def legacy(*_args, **_kwargs):
        return [
            {"title": "Same event", "url": "https://publisher.test/a", "source": "Aggregator", "provider": "tianapi"},
            {"title": "API only", "url": "https://api.test/b", "source": "API", "provider": "tianapi"},
        ], {"provider_plan": ["tianapi"]}

    snapshot = service.search(_request(), legacy_fetcher=legacy)
    assert snapshot.status == "ready"
    assert {item.url for item in snapshot.items} == {
        "https://publisher.test/a", "https://publisher.test/c", "https://api.test/b",
    }
    same = next(item for item in snapshot.items if item.url.endswith("/a"))
    assert same.discovery_paths == ("publisher-rss", "tianapi") or same.discovery_paths == ("tianapi", "publisher-rss")
    assert (tmp_path / "run-1" / f"{snapshot.snapshot_id}.json").exists()


def service_result(spec, fetcher):
    from src.sources.service import parse_feed_bytes
    status, _headers, body = fetcher(spec.source_url, 3)
    assert status == 200
    items = parse_feed_bytes(body, source=spec)
    return items, {"source_id": spec.source_id, "status": "success", "item_count": len(items)}


def test_service_marks_partial_without_fabricating_missing_items(tmp_path):
    service = UnifiedNewsSourceService(SourceRegistry([]), snapshot_dir=tmp_path)
    snapshot = service.search(_request(target_count=3), legacy_fetcher=lambda *_a, **_k: ([], {}))

    assert snapshot.status == "unavailable"
    assert snapshot.gaps == ("usable_events<3",)
    payload = json.loads((tmp_path / "run-1" / f"{snapshot.snapshot_id}.json").read_text(encoding="utf-8"))
    assert payload["coverage"]["selected_articles"] == 0
