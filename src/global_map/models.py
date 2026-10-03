from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class EventCandidate:
    event_key: str
    title: str
    summary: str
    source: str
    url: str
    published_at: datetime | None
    country: str = ""
    location_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    location_precision: str = "unknown"
    location_method: str = ""
    authority: float = 0.5
    new_development: bool = True
    publisher_family: str = ""


@dataclass(frozen=True)
class GlobalMapRequest:
    """Immutable scope for one daily global-map run.

    The cutoff is frozen before collection starts so a long-running job cannot
    silently change its editorial time window while it is running.
    """

    target_date: str
    cutoff_at: datetime
    timezone_name: str = "Asia/Shanghai"
    source_profile: str = "worldmonitor"
    map_mode: str = "coordinate-grid"
    delivery: str = "local"
    max_events: int = 8
    count: int = 1

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None = None) -> "GlobalMapRequest":
        payload = dict(value or {})
        timezone_name = str(payload.get("timezone") or payload.get("timezone_name") or "Asia/Shanghai").strip()
        if timezone_name != "Asia/Shanghai":
            raise ValueError("timezone 目前只能使用 Asia/Shanghai")
        raw_cutoff = payload.get("cutoff_at") or payload.get("cutoff")
        if raw_cutoff in {None, "", "now"}:
            cutoff = datetime.now(timezone.utc)
        elif isinstance(raw_cutoff, datetime):
            cutoff = raw_cutoff
        else:
            try:
                cutoff = datetime.fromisoformat(str(raw_cutoff).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("cutoff_at 必须是 ISO 8601 时间") from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff = cutoff.astimezone(timezone(timedelta(hours=8)))
        target_date = str(payload.get("target_date") or payload.get("date") or "auto").strip()
        if target_date == "auto":
            target_date = cutoff.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("target_date 必须是 YYYY-MM-DD 或 auto") from exc
        count = int(payload.get("count", 1))
        if count != 1:
            raise ValueError("每日全球事件关注图 count 只能为1；count表示地图笔记数量")
        map_mode = str(payload.get("map_mode") or "coordinate-grid").strip().lower()
        if map_mode not in {"coordinate-grid", "approved-boundaries"}:
            raise ValueError("map_mode 只能是 coordinate-grid 或 approved-boundaries")
        delivery = str(payload.get("delivery") or "local").strip().lower()
        if delivery not in {"local", "xhs", "toutiao", "both"}:
            raise ValueError("delivery 只能是 local、xhs、toutiao 或 both")
        max_events = int(payload.get("max_events", 8))
        if not 1 <= max_events <= 8:
            raise ValueError("max_events 必须为1至8")
        source_profile = str(payload.get("source_profile") or "worldmonitor").strip().lower()
        if source_profile != "worldmonitor":
            raise ValueError("source_profile 目前只能使用 worldmonitor")
        return cls(
            target_date=target_date,
            cutoff_at=cutoff,
            timezone_name=timezone_name,
            source_profile=source_profile,
            map_mode=map_mode,
            delivery=delivery,
            max_events=max_events,
            count=count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "timezone": self.timezone_name,
            "cutoff_at": self.cutoff_at.isoformat(),
            "source_profile": self.source_profile,
            "map_mode": self.map_mode,
            "delivery": self.delivery,
            "max_events": self.max_events,
            "count": self.count,
        }


@dataclass(frozen=True)
class EvidenceArticle:
    title: str
    source: str
    url: str
    published_at: datetime | None
    summary: str
    authority: float


@dataclass
class VerifiedEvent:
    event_key: str
    title: str
    summary: str
    country: str
    location_name: str
    latitude: float | None
    longitude: float | None
    evidence: list[EvidenceArticle] = field(default_factory=list)
    score: float = 0.0
    recency: float = 0.0
    publisher_count: int = 0
    location_precision: str = "unknown"
    location_method: str = ""


@dataclass(frozen=True)
class MapSnapshot:
    target_date: str
    cutoff: str
    events: list[VerifiedEvent]
    coverage_status: str
    upload_allowed: bool
    located_event_count: int
    country_count: int
    warning: str = ""
    raw_item_count: int = 0
    independent_event_count: int = 0
    publisher_count: int = 0
    source_state: str = "unknown"
    map_mode: str = "coordinate-grid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "cutoff": self.cutoff,
            "coverage_status": self.coverage_status,
            "upload_allowed": self.upload_allowed,
            "located_event_count": self.located_event_count,
            "country_count": self.country_count,
            "warning": self.warning,
            "raw_item_count": self.raw_item_count,
            "independent_event_count": self.independent_event_count,
            "publisher_count": self.publisher_count,
            "source_state": self.source_state,
            "map_mode": self.map_mode,
            "events": [
                {
                    "event_key": event.event_key,
                    "title": event.title,
                    "summary": event.summary,
                    "country": event.country,
                    "location_name": event.location_name,
                    "latitude": event.latitude,
                    "longitude": event.longitude,
                    "publisher_count": event.publisher_count,
                    "score": event.score,
                    "recency": event.recency,
                    "location_precision": event.location_precision,
                    "location_method": event.location_method,
                    "evidence": [
                        {"title": item.title, "source": item.source, "url": item.url,
                         "published_at": item.published_at.isoformat() if item.published_at else None,
                         "summary": item.summary, "authority": item.authority}
                        for item in event.evidence
                    ],
                }
                for event in self.events
            ],
        }
