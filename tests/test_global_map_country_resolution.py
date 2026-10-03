from __future__ import annotations

from datetime import datetime, timezone

from src.global_map.evidence import build_verified_events
from src.global_map.geography import resolve_explicit_country_location
from src.global_map.models import EventCandidate


def test_explicit_country_name_resolves_to_country_level_label_only():
    location = resolve_explicit_country_location(
        "Tusk warns of possible drone strikes on Poland and other allies"
    )

    assert location is not None
    assert location.country == "Poland"
    assert location.precision == "country"
    assert location.method == "explicit_country_name"
    assert location.latitude is not None
    assert location.longitude is not None


def test_country_level_resolution_is_used_when_worldmonitor_has_no_coordinates():
    events = build_verified_events(
        [
            EventCandidate(
                event_key="iran-event",
                title="Iran talks with Gulf leaders next week",
                summary="Diplomatic efforts continue after the regional crisis.",
                source="Reuters",
                url="https://reuters.example/iran",
                published_at=datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc),
                country="Iran",
                location_name="Iran（国家级）",
                latitude=32.4279,
                longitude=53.6880,
                location_precision="country",
                location_method="explicit_country_name",
            )
        ],
        target_date="2026-09-18",
        cutoff=datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc),
    )

    assert len(events) == 1
    assert events[0].location_precision == "country"
    assert events[0].location_method == "explicit_country_name"


def test_ambiguous_multi_country_text_is_not_mapped_to_an_arbitrary_country():
    assert resolve_explicit_country_location("US tariffs on Russian oil") is None
