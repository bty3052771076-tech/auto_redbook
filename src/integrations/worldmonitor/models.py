from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        stamp = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class WorldMonitorCoverage:
    state: str = "unknown"
    served_stale: bool = False
    stale_age_seconds: float = 0.0
    items_served: int = 0
    publisher_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "WorldMonitorCoverage":
        value = dict(payload or {})
        return cls(
            state=str(value.get("state") or "unknown"),
            served_stale=bool(value.get("servedStale", value.get("served_stale", False))),
            stale_age_seconds=float(value.get("staleAgeSeconds", value.get("stale_age_seconds", 0)) or 0),
            items_served=int(value.get("itemsServed", 0) or 0),
            publisher_count=int(value.get("publisherCount", 0) or 0),
            raw=value,
        )


@dataclass(frozen=True)
class WorldMonitorItem:
    item_id: str
    title: str
    url: str
    source: str
    published_at: datetime | None
    snippet: str = ""
    category: str = ""
    location_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    importance_score: float | None = None
    credibility_score: float | None = None
    corroboration_count: int = 0
    is_alert: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "WorldMonitorItem":
        raw = dict(value)
        return cls(
            item_id=str(raw.get("id") or raw.get("itemId") or raw.get("hash") or ""),
            title=str(raw.get("title") or "").strip(),
            url=str(raw.get("link") or raw.get("url") or "").strip(),
            source=str(raw.get("source") or raw.get("publisher") or "").strip(),
            published_at=_parse_datetime(raw.get("publishedAt", raw.get("published_at"))),
            snippet=str(raw.get("snippet") or raw.get("description") or "").strip(),
            category=str(raw.get("category") or raw.get("threat", {}).get("category") or "").strip(),
            location_name=str(raw.get("locationName") or raw.get("location_name") or "").strip(),
            latitude=_as_float(raw.get("latitude") or raw.get("lat")),
            longitude=_as_float(raw.get("longitude") or raw.get("lon") or raw.get("lng")),
            importance_score=_as_float(raw.get("importanceScore") or raw.get("importance_score")),
            credibility_score=_as_float(raw.get("credibilityScore") or raw.get("credibility_score")),
            corroboration_count=int(raw.get("corroborationCount") or raw.get("corroboration_count") or 0),
            is_alert=bool(raw.get("isAlert", raw.get("is_alert", False))),
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "snippet": self.snippet,
            "category": self.category,
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "importance_score": self.importance_score,
            "credibility_score": self.credibility_score,
            "corroboration_count": self.corroboration_count,
            "is_alert": self.is_alert,
        }


@dataclass(frozen=True)
class WorldMonitorBatch:
    items: list[WorldMonitorItem]
    categories: dict[str, int]
    coverage: WorldMonitorCoverage
    generated_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
