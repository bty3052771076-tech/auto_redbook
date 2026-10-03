from __future__ import annotations

import math
from datetime import datetime, timezone

from .models import MapSnapshot, VerifiedEvent


def score_event(event: VerifiedEvent, cutoff: datetime) -> float:
    support = min(math.log1p(max(event.publisher_count, 1)) / math.log(6), 1.0)
    authority = max((item.authority for item in event.evidence), default=0.5)
    published = max((item.published_at for item in event.evidence if item.published_at), default=None)
    if published is None:
        recency = 0.5
    else:
        age_hours = max(0.0, (cutoff - published).total_seconds() / 3600)
        recency = max(0.0, 1.0 - age_hours / 24.0)
    event.recency = recency
    event.score = 0.5 * support + 0.3 * authority + 0.2 * recency
    return event.score


def select_events(
    events: list[VerifiedEvent],
    *,
    max_events: int = 8,
    target_date: str = "",
    cutoff: datetime | None = None,
    raw_item_count: int = 0,
    source_state: str = "unknown",
    map_mode: str = "coordinate-grid",
) -> MapSnapshot:
    cutoff = cutoff or datetime.now(timezone.utc)
    ranked_all = sorted(events, key=lambda item: score_event(item, cutoff), reverse=True)
    # Unknown-location items may remain in the audit list, but must not crowd
    # out events that can actually be drawn on the map.
    located_first = [item for item in ranked_all if item.latitude is not None and item.longitude is not None]
    unlocated = [item for item in ranked_all if item.latitude is None or item.longitude is None]
    ranked = (located_first + unlocated)[:max_events]
    located = [item for item in ranked if item.latitude is not None and item.longitude is not None]
    countries = {item.country for item in located if item.country}
    if source_state in {"stale", "error", "failed"}:
        status, allowed = "blocked", False
        warning = "主数据源不是新鲜有效状态，不能生成可投稿地图。"
    elif len(located) < 3 or len(countries) < 2:
        status, allowed = "low", False
        warning = "已核验坐标事件不足3条或覆盖国家不足2个，不自动上传全球热力图。"
    elif len(located) < 6:
        status, allowed = "limited", True
        warning = "覆盖有限：地图仅代表当前可获取信源中的事件关注度。"
    else:
        status, allowed, warning = "adequate", True, ""
    publisher_count = len({
        item.source
        for event in ranked
        for item in event.evidence
        if item.source
    })
    return MapSnapshot(
        target_date=target_date,
        cutoff=cutoff.isoformat(),
        events=ranked,
        coverage_status=status,
        upload_allowed=allowed,
        located_event_count=len(located),
        country_count=len(countries),
        warning=warning,
        raw_item_count=max(0, int(raw_item_count)),
        independent_event_count=len(events),
        publisher_count=publisher_count,
        source_state=source_state or "unknown",
        map_mode=map_mode or "coordinate-grid",
    )
