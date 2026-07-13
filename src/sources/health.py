from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any


COOLDOWN_STATUSES = frozenset(
    {"timeout", "transport_error", "http_error", "error", "empty", "missing_date", "stale"}
)


def _parse_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SourceAttempt:
    collection: str
    source_name: str
    source_url: str
    tier: str
    status: str
    checked_at: str
    elapsed_seconds: float = 0.0
    item_count: int = 0
    dated_count: int = 0
    url_count: int = 0
    error: str = ""
    http_status: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "tier": self.tier,
            "status": self.status,
            "checked_at": self.checked_at,
            "elapsed_seconds": self.elapsed_seconds,
            "item_count": self.item_count,
            "dated_count": self.dated_count,
            "url_count": self.url_count,
            "error": self.error,
            "http_status": self.http_status,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceAttempt":
        return cls(
            collection=str(value.get("collection") or ""),
            source_name=str(value.get("source_name") or ""),
            source_url=str(value.get("source_url") or ""),
            tier=str(value.get("tier") or ""),
            status=str(value.get("status") or "unknown"),
            checked_at=str(value.get("checked_at") or ""),
            elapsed_seconds=float(value.get("elapsed_seconds") or 0.0),
            item_count=int(value.get("item_count") or 0),
            dated_count=int(value.get("dated_count") or 0),
            url_count=int(value.get("url_count") or 0),
            error=str(value.get("error") or ""),
            http_status=(int(value["http_status"]) if value.get("http_status") is not None else None),
        )


@dataclass(frozen=True)
class SourceHealthSnapshot:
    collection: str
    generated_at: str
    attempts: list[SourceAttempt] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "collection": self.collection,
            "generated_at": self.generated_at,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceHealthSnapshot":
        raw_attempts = value.get("attempts")
        attempts = [
            SourceAttempt.from_dict(item)
            for item in raw_attempts
            if isinstance(item, dict)
        ] if isinstance(raw_attempts, list) else []
        return cls(
            collection=str(value.get("collection") or ""),
            generated_at=str(value.get("generated_at") or ""),
            attempts=attempts,
            version=int(value.get("version") or 1),
        )


def is_source_in_cooldown(
    attempt: SourceAttempt | None,
    *,
    now: datetime | None = None,
    cooldown_seconds: int = 300,
) -> bool:
    if attempt is None or attempt.status not in COOLDOWN_STATUSES:
        return False
    checked_at = _parse_datetime(attempt.checked_at)
    if checked_at is None:
        return False
    reference = now or _utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc) < checked_at + timedelta(seconds=max(0, int(cooldown_seconds)))


def save_source_health_snapshot(snapshot: SourceHealthSnapshot, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def load_source_health_snapshot(path: str | Path) -> SourceHealthSnapshot | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    try:
        return SourceHealthSnapshot.from_dict(value)
    except (TypeError, ValueError):
        return None
