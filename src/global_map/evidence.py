from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .geography import verified_location
from .models import EvidenceArticle, EventCandidate, VerifiedEvent


def build_verified_events(candidates: Iterable[EventCandidate], *, target_date: str, cutoff: datetime) -> list[VerifiedEvent]:
    groups: dict[str, list[EventCandidate]] = defaultdict(list)
    for candidate in candidates:
        if not _is_current(candidate.published_at, target_date, cutoff):
            continue
        if not candidate.title.strip() or not candidate.url.strip():
            continue
        groups[candidate.event_key or _normalise_key(candidate.title)].append(candidate)

    events = []
    for event_key, members in groups.items():
        representative = max(members, key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc))
        lat, lon, precision = verified_location(
            representative.latitude,
            representative.longitude,
            representative.location_name,
            representative.location_precision,
        )
        evidence = [
            EvidenceArticle(
                title=item.title,
                source=item.source,
                url=item.url,
                published_at=item.published_at,
                summary=item.summary,
                authority=float(item.authority),
            )
            for item in members
        ]
        events.append(VerifiedEvent(
            event_key=event_key,
            title=representative.title,
            summary=representative.summary,
            country=representative.country,
            location_name=representative.location_name,
            latitude=lat,
            longitude=lon,
            evidence=evidence,
            publisher_count=len({item.publisher_family or item.source for item in members}),
            location_precision=precision,
            location_method=representative.location_method,
        ))
    return events


def _is_current(published_at: datetime | None, target_date: str, cutoff: datetime) -> bool:
    if published_at is None:
        return False
    instant = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
    limit = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    if instant > limit:
        return False
    return instant.astimezone(timezone(timedelta(hours=8))).date().isoformat() == target_date


def _normalise_key(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", title.lower()).strip()
