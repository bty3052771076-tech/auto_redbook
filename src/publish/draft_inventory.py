"""Pure helpers for matching local drafts with a live creator-center list.

The browser layer deliberately stays separate from this module.  This keeps
matching deterministic and makes it possible to fail closed when the platform
list is incomplete or two drafts cannot be distinguished safely.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class LocalDraftRecord:
    post_id: str
    title: str
    saved_at: str = ""
    draft_type: str = "image"
    alternate_titles: tuple[str, ...] = ()

    @property
    def title_keys(self) -> tuple[str, ...]:
        values = (self.title, *self.alternate_titles)
        result: list[str] = []
        for value in values:
            key = normalize_draft_title(value)
            if key and key not in result:
                result.append(key)
        return tuple(result)


@dataclass(frozen=True)
class PlatformDraftRecord:
    title: str
    saved_at: str = ""
    draft_type: str = "image"
    index: int = -1
    cover_ready: bool = False

    @property
    def title_key(self) -> str:
        return normalize_draft_title(self.title)


@dataclass(frozen=True)
class DraftMatch:
    local: LocalDraftRecord
    platform: PlatformDraftRecord


@dataclass
class DraftInventoryResult:
    matched: list[DraftMatch] = field(default_factory=list)
    local_missing_on_platform: list[LocalDraftRecord] = field(default_factory=list)
    platform_without_local: list[PlatformDraftRecord] = field(default_factory=list)
    ambiguous: list[LocalDraftRecord] = field(default_factory=list)

    @property
    def publishable_post_ids(self) -> list[str]:
        return [match.local.post_id for match in self.matched]


def normalize_draft_title(value: str) -> str:
    """Normalize display noise without turning matching into substring search."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = text.translate(
        str.maketrans(
            {
                "，": ",",
                "。": ".",
                "：": ":",
                "；": ";",
                "！": "!",
                "？": "?",
                "（": "(",
                "）": ")",
                "【": "[",
                "】": "]",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "—": "-",
                "－": "-",
                "／": "/",
                "、": ",",
            }
        )
    )
    return re.sub(r"\s+", "", text)


def _parse_time(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text.replace("Z", "+00:00")]
    if " " in text and "T" not in text:
        candidates.append(text.replace(" ", "T", 1))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _time_distance(local: LocalDraftRecord, platform: PlatformDraftRecord) -> float | None:
    left = _parse_time(local.saved_at)
    right = _parse_time(platform.saved_at)
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds())


def _nearest_unique(
    local: LocalDraftRecord,
    candidates: list[PlatformDraftRecord],
) -> PlatformDraftRecord | None:
    distances = [(candidate, _time_distance(local, candidate)) for candidate in candidates]
    if any(distance is None for _, distance in distances):
        return None
    ordered = sorted(distances, key=lambda item: float(item[1]))
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return None
    return ordered[0][0]


def match_draft_inventory(
    local_records: Iterable[LocalDraftRecord],
    platform_records: Iterable[PlatformDraftRecord],
) -> DraftInventoryResult:
    """Match records one-to-one using exact normalized titles.

    Duplicate titles are only resolved by a unique nearest save time.  Missing
    or tied times are ambiguous and are intentionally excluded from publishing.
    """

    locals_list = list(local_records)
    platform_list = list(platform_records)
    result = DraftInventoryResult()
    used_platform_indexes: set[int] = set()

    candidates_by_local: dict[int, list[PlatformDraftRecord]] = {}
    for local_index, local in enumerate(locals_list):
        keys = set(local.title_keys)
        candidates_by_local[local_index] = [
            platform
            for platform in platform_list
            if platform.title_key and platform.title_key in keys
        ]

    # Resolve constrained rows first so a unique row is not consumed by a
    # duplicate row that has several alternatives.
    order = sorted(
        range(len(locals_list)),
        key=lambda index: (len(candidates_by_local[index]) or 10**6, index),
    )
    for local_index in order:
        local = locals_list[local_index]
        candidates = [
            candidate
            for candidate in candidates_by_local[local_index]
            if candidate.index not in used_platform_indexes
        ]
        if not candidates:
            if candidates_by_local[local_index]:
                result.ambiguous.append(local)
            else:
                result.local_missing_on_platform.append(local)
            continue

        selected: PlatformDraftRecord | None
        if len(candidates) == 1:
            selected = candidates[0]
        else:
            selected = _nearest_unique(local, candidates)
        if selected is None:
            result.ambiguous.append(local)
            continue
        used_platform_indexes.add(selected.index)
        result.matched.append(DraftMatch(local=local, platform=selected))

    result.platform_without_local = [
        platform
        for platform in platform_list
        if platform.index not in used_platform_indexes
    ]
    result.matched.sort(key=lambda item: item.platform.index)
    result.local_missing_on_platform.sort(key=lambda item: item.post_id)
    result.ambiguous.sort(key=lambda item: item.post_id)
    return result


def local_record_from_post(post: Any, *, draft_type: str = "image") -> LocalDraftRecord:
    """Build a local record from a Pydantic Post or a mapping."""

    if isinstance(post, Mapping):
        data = post
    elif hasattr(post, "model_dump"):
        data = post.model_dump()
    else:
        data = {
            "id": getattr(post, "id", ""),
            "title": getattr(post, "title", ""),
            "uploaded_at": getattr(post, "uploaded_at", ""),
            "platform": getattr(post, "platform", {}),
        }
    platform = data.get("platform") if isinstance(data.get("platform"), Mapping) else {}
    xhs = platform.get("xhs_draft") if isinstance(platform.get("xhs_draft"), Mapping) else {}
    platform_title = str(xhs.get("title") or "").strip()
    title = platform_title or str(data.get("title") or "").strip()
    aliases = tuple(
        value
        for value in (str(data.get("title") or "").strip(),)
        if value and value != title
    )
    saved_at = str(
        xhs.get("saved_at")
        or data.get("uploaded_at")
        or data.get("updated_at")
        or data.get("created_at")
        or ""
    ).strip()
    return LocalDraftRecord(
        post_id=str(data.get("id") or "").strip(),
        title=title,
        saved_at=saved_at,
        draft_type=draft_type,
        alternate_titles=aliases,
    )


def platform_records_from_items(
    items: Iterable[Mapping[str, Any]],
    *,
    draft_type: str = "image",
) -> list[PlatformDraftRecord]:
    records: list[PlatformDraftRecord] = []
    for fallback_index, item in enumerate(items):
        try:
            index = int(item.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index
        records.append(
            PlatformDraftRecord(
                title=str(item.get("title") or "").strip(),
                saved_at=str(item.get("saved_at") or "").strip(),
                draft_type=str(item.get("draft_type") or draft_type).strip() or draft_type,
                index=index,
                cover_ready=bool(item.get("cover_ready", False)),
            )
        )
    return records
