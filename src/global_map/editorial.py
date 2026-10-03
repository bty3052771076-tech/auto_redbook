from __future__ import annotations

from .models import MapSnapshot


def build_global_map_editorial(snapshot: MapSnapshot) -> dict[str, object]:
    """Return a structured brief; source URLs remain in the local snapshot only."""
    return {
        "title": f"今日全球事件关注图｜{snapshot.target_date}",
        "summary": snapshot.warning or "以下内容仅代表已采集公开信源中的事件关注度。",
        "events": [
            {
                "event_id": event.event_key,
                "title": event.title,
                "summary": event.summary,
                "country": event.country,
                "publisher_count": event.publisher_count,
                "evidence_count": len(event.evidence),
            }
            for event in snapshot.events[:8]
        ],
        "cutoff": snapshot.cutoff,
        "upload_allowed": snapshot.upload_allowed,
    }
