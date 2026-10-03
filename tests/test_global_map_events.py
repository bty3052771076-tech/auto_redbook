from __future__ import annotations

import json
from datetime import datetime, timezone

from src.global_map.evidence import build_verified_events
from src.global_map.models import EventCandidate
from src.global_map.select import select_events
from src.global_map.render import render_global_map
from src.global_map.workflow import create_global_map_post
from src.integrations.worldmonitor.models import WorldMonitorBatch, WorldMonitorCoverage, WorldMonitorItem
from src.validation.rules import validate_post


def _basemap(path):
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Testland"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-30, -20], [30, -20], [30, 20], [-30, 20], [-30, -20]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _candidate(title: str, source: str, *, country: str, lat: float, lon: float, score: float = 0.8):
    return EventCandidate(
        event_key="shared-event" if "same" in title else title,
        title=title,
        summary="Concrete event summary",
        source=source,
        url=f"https://{source.lower()}.example/{title.replace(' ', '-')}",
        published_at=datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc),
        country=country,
        location_name=f"{country} city",
        latitude=lat,
        longitude=lon,
        authority=score,
    )


def test_events_cluster_by_event_key_and_keep_independent_sources():
    events = build_verified_events(
        [
            _candidate("same event", "Official", country="A", lat=10, lon=10),
            _candidate("same event", "Reviewed", country="A", lat=10, lon=10),
            _candidate("second event", "Other", country="B", lat=20, lon=20),
        ],
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )

    assert len(events) == 2
    shared = next(item for item in events if item.event_key == "shared-event")
    assert shared.publisher_count == 2
    assert len(shared.evidence) == 2


def test_selection_marks_low_coverage_instead_of_faking_global_heatmap():
    candidates = [
        _candidate("one", "Official", country="A", lat=10, lon=10),
        _candidate("two", "Reviewed", country="A", lat=11, lon=11),
    ]
    events = build_verified_events(
        candidates,
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )

    snapshot = select_events(events, max_events=8)

    assert snapshot.coverage_status == "low"
    assert snapshot.upload_allowed is False
    assert snapshot.located_event_count == 2


def test_render_is_fixed_mobile_size_and_non_blank(tmp_path):
    events = build_verified_events(
        [
            _candidate("one", "Official", country="A", lat=10, lon=10),
            _candidate("two", "Reviewed", country="B", lat=20, lon=20),
            _candidate("three", "Other", country="C", lat=-20, lon=80),
        ],
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )
    snapshot = select_events(events, max_events=8, target_date="2026-09-18", cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc))
    path = render_global_map(snapshot, tmp_path / "map.png", basemap_path=_basemap(tmp_path / "world.geojson"))

    from PIL import Image

    image = Image.open(path)
    assert image.size == (1080, 1440)
    assert image.getbbox() is not None


def test_render_keeps_eight_long_event_rows_on_one_mobile_canvas(tmp_path):
    events = build_verified_events(
        [
            _candidate(
                f"event {index} with a long verified headline about a concrete event",
                f"Source{index}",
                country=f"Country{index}",
                lat=-30 + index * 7,
                lon=-140 + index * 35,
            )
            for index in range(8)
        ],
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )
    snapshot = select_events(
        events,
        max_events=8,
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )
    path = render_global_map(snapshot, tmp_path / "map-eight.png", basemap_path=_basemap(tmp_path / "world-eight.geojson"))

    from PIL import Image

    assert Image.open(path).size == (1080, 1440)


def test_render_rejects_missing_basemap(tmp_path):
    events = build_verified_events(
        [_candidate("one", "Official", country="A", lat=10, lon=10)],
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )
    snapshot = select_events(events, max_events=8, target_date="2026-09-18", cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc))

    import pytest

    with pytest.raises(RuntimeError, match="MAP_ASSET"):
        render_global_map(snapshot, tmp_path / "map.png", basemap_path=tmp_path / "missing.geojson")


def test_global_map_post_body_is_bounded_and_lists_only_located_events(tmp_path):
    items = [
        WorldMonitorItem(
            item_id=str(index),
            title=f"{country} event with a deliberately long title " + ("x" * 160),
            url=f"https://example.test/{index}",
            source="Official",
            published_at=datetime(2026, 9, 18, index, 0, tzinfo=timezone.utc),
            snippet="A long factual summary " + ("y" * 240),
            latitude=lat,
            longitude=lon,
            raw={"country": country},
        )
        for index, (country, lat, lon) in enumerate(
            [("Japan", 36.2, 138.2), ("Nigeria", 9.0, 8.6), ("France", 46.2, 2.2)],
        )
    ]
    post = create_global_map_post(
        WorldMonitorBatch(
            items=items,
            categories={},
            coverage=WorldMonitorCoverage(state="partial"),
        ),
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
        output_dir=tmp_path,
        basemap_path=_basemap(tmp_path / "world.geojson"),
    )

    assert post is not None
    assert len(post.body) <= 1000
    assert validate_post(post).ok
    assert "Japan" in post.body and "Nigeria" in post.body and "France" in post.body
