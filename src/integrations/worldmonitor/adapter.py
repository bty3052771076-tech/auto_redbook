from __future__ import annotations

from .models import WorldMonitorBatch


def batch_to_source_records(batch: WorldMonitorBatch) -> list[dict[str, object]]:
    """Convert the external schema to the project's source-neutral record shape."""
    return [
        {
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "description": item.snippet,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "provider": "worldmonitor",
            "category": item.category,
            "importance_score": item.importance_score,
            "credibility_score": item.credibility_score,
            "coverage_state": batch.coverage.state,
            "served_stale": batch.coverage.served_stale,
            "location_name": item.location_name,
            "latitude": item.latitude,
            "longitude": item.longitude,
        }
        for item in batch.items
    ]
