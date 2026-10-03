from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.global_map.models import GlobalMapRequest
from src.global_map.service import build_global_map_preview


def test_global_map_request_freezes_scope_and_rejects_multiple_posts():
    request = GlobalMapRequest.from_mapping(
        {
            "target_date": "2026-09-18",
            "cutoff_at": "2026-09-18T12:00:00+08:00",
            "delivery": "local",
            "map_mode": "coordinate-grid",
        }
    )

    assert request.target_date == "2026-09-18"
    assert request.timezone_name == "Asia/Shanghai"
    assert request.cutoff_at.tzinfo is not None
    assert request.cutoff_at.isoformat() == "2026-09-18T12:00:00+08:00"
    assert request.count == 1

    with pytest.raises(ValueError, match="count.*1"):
        GlobalMapRequest.from_mapping({"count": 2})


def test_global_map_request_accepts_only_supported_delivery_and_map_modes():
    with pytest.raises(ValueError, match="delivery"):
        GlobalMapRequest.from_mapping({"delivery": "publish"})
    with pytest.raises(ValueError, match="map_mode"):
        GlobalMapRequest.from_mapping({"map_mode": "ai-art"})


def test_global_map_preview_reports_coverage_without_creating_post():
    class FakeRuntime:
        def ensure_ready(self):
            return type("Probe", (), {"ready": True, "error_code": "", "message": ""})()

        def release(self):
            return None

    class FakeClient:
        def fetch_digest(self, **_kwargs):
            from src.integrations.worldmonitor.models import WorldMonitorBatch, WorldMonitorCoverage, WorldMonitorItem

            return WorldMonitorBatch(
                items=[
                    WorldMonitorItem(
                        item_id="1",
                        title="Event A",
                        url="https://example.test/a",
                        source="Official A",
                        published_at=datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc),
                        snippet="Concrete A",
                        location_name="A City",
                        latitude=10,
                        longitude=10,
                        raw={"originPublisher": "Official A", "country": "A"},
                    ),
                    WorldMonitorItem(
                        item_id="2",
                        title="Event B",
                        url="https://example.test/b",
                        source="Official B",
                        published_at=datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc),
                        snippet="Concrete B",
                        location_name="B City",
                        latitude=20,
                        longitude=20,
                        raw={"originPublisher": "Official B", "country": "B"},
                    ),
                ],
                categories={},
                coverage=WorldMonitorCoverage(state="fresh"),
            )

    result = build_global_map_preview(
        client=FakeClient(),
        runtime=FakeRuntime(),
        request=GlobalMapRequest.from_mapping({
            "target_date": "2026-09-18",
            "cutoff_at": "2026-09-18T12:00:00+08:00",
        }),
    )

    assert result["quality_state"] == "low"
    assert result["coverage"]["raw_items"] == 2
    assert result["coverage"]["located_events"] == 2
    assert result["upload_allowed"] is False
    assert "post" not in result
