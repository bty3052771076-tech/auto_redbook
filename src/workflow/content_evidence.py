"""Deterministic content evidence and publication policy helpers.

The helpers in this module deliberately do not call a model or fetch a page.
They protect the boundaries around model output and platform delivery.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.ai_digest.models import AIUpdateItem


BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_QUESTION_RUN_RE = re.compile(r"\?{2,}")
_REPLACEMENT_CHAR = "\ufffd"


def text_integrity_issues(title: str, body: str) -> tuple[str, ...]:
    """Return hard errors for text that was damaged before publication.

    A single question mark can be valid prose. Repeated ASCII question marks
    and U+FFFD are strong signals of an encoding or replacement failure and
    must never be silently repaired by guessing.
    """

    issues: list[str] = []
    values = (str(title or ""), str(body or ""))
    if any(_REPLACEMENT_CHAR in value for value in values):
        issues.append("replacement_character")
    if any(_QUESTION_RUN_RE.search(value) for value in values):
        issues.append("question_mark_corruption")
    return tuple(issues)


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _published_beijing_date(value: Any) -> tuple[date | None, bool]:
    """Return (Beijing date, has_time_precision) without inventing a time."""

    text = str(value or "").strip()
    parsed_date = _parse_date(text)
    if parsed_date is None:
        return None, False
    if not re.search(r"[T ]\d{1,2}:\d{2}", text):
        return parsed_date, False
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return parsed_date, False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ).date(), True


def _normalize_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.lower()
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"source", "ref", "fbclid", "gclid"}
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower().removeprefix("www."),
            parsed.path.rstrip("/") or "/",
            urlencode(query),
            "",
        )
    )


def _item_key(item: AIUpdateItem) -> str:
    from src.ai_digest.rank import ai_update_history_key

    # Prefer the shared semantic event key so mirrored official/aggregator
    # URLs cannot bypass the final publication dedupe gate. The history key
    # falls back to a normalized URL for records without enough event facts.
    history_key = ai_update_history_key(item)
    if history_key and not history_key.startswith(("http://", "https://")):
        return f"history:{history_key}"
    normalized_url = _normalize_url(item.url)
    if normalized_url:
        return f"url:{normalized_url}"
    return f"history:{history_key}" if history_key else ""


def ai_digest_items_in_beijing_window(
    items: Iterable[AIUpdateItem],
    *,
    publication_date: str,
    now: datetime | None = None,
) -> tuple[list[AIUpdateItem], dict[str, int | str]]:
    """Filter and dedupe AI items for publication day and the preceding day.

    This is deliberately stricter than the historical adaptive lookback used
    by the collector. Wider windows may be used to research history, but they
    cannot enter the final publishing set.
    """

    publish_day = _parse_date(publication_date)
    if publish_day is None:
        raise ValueError(f"invalid publication date: {publication_date}")
    earliest = publish_day - timedelta(days=1)
    current_time = now.astimezone(BEIJING_TZ) if now is not None else None
    selected: list[AIUpdateItem] = []
    seen: set[str] = set()
    dropped_out_of_window = 0
    dropped_future = 0
    dropped_unknown_date = 0
    duplicate_removed = 0
    for item in items:
        item_date, has_time = _published_beijing_date(item.published_at)
        if item_date is None:
            dropped_unknown_date += 1
            continue
        if item_date > publish_day:
            dropped_future += 1
            continue
        if item_date < earliest:
            dropped_out_of_window += 1
            continue
        if has_time and current_time is not None and item_date == publish_day:
            try:
                raw = str(item.published_at).strip().replace("Z", "+00:00")
                timestamp = datetime.fromisoformat(raw)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=BEIJING_TZ)
                if timestamp.astimezone(BEIJING_TZ) > current_time:
                    dropped_future += 1
                    continue
            except ValueError:
                pass
        key = _item_key(item)
        if key in seen:
            duplicate_removed += 1
            continue
        seen.add(key)
        selected.append(item)
    return selected, {
        "publication_date": publish_day.isoformat(),
        "earliest_date": earliest.isoformat(),
        "dropped_out_of_window": dropped_out_of_window,
        "dropped_future": dropped_future,
        "dropped_unknown_date": dropped_unknown_date,
        "duplicate_removed": duplicate_removed,
    }


def ai_digest_item_is_current(
    item: AIUpdateItem,
    *,
    publication_date: str,
) -> bool:
    selected, _meta = ai_digest_items_in_beijing_window(
        [item], publication_date=publication_date
    )
    return bool(selected)
