"""Deterministic planning primitives for managing live creator-center drafts.

Browser access stays in ``playwright_steps``.  This module only models and
checks data so the agent can be tested without a live account or a model.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


_MARKUP_RE = re.compile(r"</?[a-z][^>]*>|(?:src|referrerpolicy)=['\"]", re.IGNORECASE)
_VAGUE_RE = re.compile(r"(?:披露|发布)\s*(?:AI产品变化|产品变化|XX内容|相关变化|最新变化)$")
_PLACEHOLDER_RE = re.compile(r"(?:动态\s*\d+|\?{2,}|？{2,}|内容摘要|暂无具体内容)")


def inspection_completeness(
    *, total: int, inspected: int, requested_limit: int, errors: Iterable[Any]
) -> dict[str, Any]:
    """Separate complete list enumeration from complete detail inspection."""

    total = max(0, int(total))
    inspected = max(0, int(inspected))
    limit = max(0, int(requested_limit))
    error_list = list(errors or [])
    limited = bool(limit and total > limit)
    detail_complete = not error_list and inspected >= min(total, limit or total) and not limited
    if error_list:
        stop_reason = "inspection_error"
    elif limited:
        stop_reason = "detail_limit"
    else:
        stop_reason = "end_of_list"
    return {
        "enumeration_complete": True,
        "inspection_complete": detail_complete,
        "complete": bool(detail_complete),
        "stop_reason": stop_reason,
    }


def _normal_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _without_markup(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", _normal_text(value)).strip()


def _parse_time(value: str) -> datetime | None:
    text = _normal_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_display_time(value: str, captured_at: datetime | None) -> datetime | None:
    parsed = _parse_time(value)
    if parsed is not None:
        return parsed
    text = _normal_text(value)
    if not text:
        return None
    reference = captured_at or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    local = reference.astimezone(timezone(timedelta(hours=8)))
    match = re.search(r"(?:(今天|昨天|前天)\s*)?(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    day = match.group(1) or "今天"
    offset = {"今天": 0, "昨天": 1, "前天": 2}.get(day)
    if offset is None:
        return None
    current = local - timedelta(days=offset)
    return current.replace(hour=int(match.group(2)), minute=int(match.group(3)), second=0, microsecond=0)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class DraftImage:
    source: str
    sha256: str = ""
    alt: str = ""


@dataclass(frozen=True)
class PlatformDraftSnapshot:
    snapshot_id: str
    platform_draft_id: str = ""
    local_post_id: str = ""
    account_id: str = ""
    profile_fingerprint: str = ""
    captured_at: str = ""
    draft_type: str = "image"
    title: str = ""
    body: str = ""
    saved_at: str = ""
    saved_at_raw: str = ""
    images: tuple[DraftImage, ...] = ()
    read_status: str = "complete"
    scan_complete: bool = True
    identity_confidence: str = "unknown"
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def content_fingerprint(self) -> str:
        payload = {
            "title": _normal_text(self.title),
            "body": _normal_text(self.body),
            "images": [asdict(image) for image in self.images],
        }
        return hashlib.sha256(_json_bytes(payload)).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["images"] = [asdict(image) for image in self.images]
        data["content_fingerprint"] = self.content_fingerprint
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlatformDraftSnapshot":
        images = tuple(
            DraftImage(
                source=_normal_text(item.get("source")),
                sha256=_normal_text(item.get("sha256")),
                alt=_normal_text(item.get("alt")),
            )
            for item in data.get("images", [])
            if isinstance(item, dict)
        )
        return cls(
            snapshot_id=_normal_text(data.get("snapshot_id")),
            platform_draft_id=_normal_text(data.get("platform_draft_id")),
            local_post_id=_normal_text(data.get("local_post_id")),
            account_id=_normal_text(data.get("account_id")),
            profile_fingerprint=_normal_text(data.get("profile_fingerprint")),
            captured_at=_normal_text(data.get("captured_at")),
            draft_type=_normal_text(data.get("draft_type")) or "image",
            title=_normal_text(data.get("title")),
            body=_normal_text(data.get("body")),
            saved_at=_normal_text(data.get("saved_at")),
            saved_at_raw=_normal_text(data.get("saved_at_raw")),
            images=images,
            read_status=_normal_text(data.get("read_status")) or "complete",
            scan_complete=bool(data.get("scan_complete", True)),
            identity_confidence=_normal_text(data.get("identity_confidence")) or "unknown",
            errors=tuple(_normal_text(item) for item in data.get("errors", []) if _normal_text(item)),
            metadata=dict(data.get("metadata") or {}),
        )


def build_platform_snapshot(
    *,
    item: dict[str, Any],
    editor: dict[str, Any] | None = None,
    image_sources: Iterable[str] = (),
    snapshot_id: str,
    account_id: str = "",
    profile_fingerprint: str = "",
    captured_at: str = "",
) -> PlatformDraftSnapshot:
    """Combine a draft-list row and an editor read into an auditable snapshot."""

    editor = editor or {}
    title = _normal_text(editor.get("actual_title") or item.get("title"))
    body = _normal_text(editor.get("actual_body"))
    raw_time = _normal_text(item.get("saved_at"))
    captured = _parse_time(captured_at) if captured_at else None
    parsed_time = _parse_display_time(raw_time, captured)
    errors: list[str] = []
    if not parsed_time:
        errors.append("saved_time_unknown")
    if not title:
        errors.append("title_read_failed")
    if not body:
        errors.append("body_read_failed")
    images = tuple(DraftImage(source=_normal_text(source)) for source in image_sources if _normal_text(source))
    read_status = "complete" if title and body and parsed_time else "partial"
    platform_id = _normal_text(item.get("platform_draft_id") or item.get("draft_id"))
    identity_confidence = "ambiguous" if item.get("identity_ambiguous") else ("platform_id" if platform_id else "title_time")
    captured_value = captured.isoformat() if captured is not None else _normal_text(captured_at)
    return PlatformDraftSnapshot(
        snapshot_id=_normal_text(snapshot_id),
        platform_draft_id=platform_id,
        account_id=_normal_text(account_id),
        profile_fingerprint=_normal_text(profile_fingerprint),
        captured_at=captured_value,
        draft_type=_normal_text(item.get("draft_type")) or "image",
        title=title,
        body=body,
        saved_at=parsed_time.isoformat() if parsed_time else "",
        saved_at_raw=raw_time,
        images=images,
        read_status=read_status,
        scan_complete=True,
        identity_confidence=identity_confidence,
        errors=tuple(dict.fromkeys(errors)),
        metadata={"list_index": _normal_text(item.get("index"))},
    )


@dataclass(frozen=True)
class DraftReviewPolicy:
    require_images: bool = True
    max_age_days: int | None = None
    exclude_terms: tuple[str, ...] = ()
    allowed_types: tuple[str, ...] = ("image",)


@dataclass(frozen=True)
class DraftReview:
    snapshot_id: str
    decision: str
    score: float
    issues: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    duplicate_of: str = ""
    content_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftAuthorization:
    account_id: str
    allowed_actions: tuple[str, ...]
    max_items: int
    expires_at: str
    policy_version: str = "1"

    def allows(self, action: str, count: int, *, now: datetime | None = None) -> bool:
        if action not in set(self.allowed_actions):
            return False
        if count < 0 or count > max(0, int(self.max_items)):
            return False
        expiry = _parse_time(self.expires_at)
        current = now or datetime.now(timezone.utc)
        if expiry is not None and current.astimezone(timezone.utc) > expiry.astimezone(timezone.utc):
            return False
        return True


@dataclass(frozen=True)
class DraftActionItem:
    snapshot_id: str
    rank: int
    expected_fingerprint: str
    reason: str


@dataclass(frozen=True)
class DraftActionPlan:
    action: str
    items: tuple[DraftActionItem, ...]
    authorization_valid: bool
    errors: tuple[str, ...] = ()
    policy_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "items": [asdict(item) for item in self.items],
            "authorization_valid": self.authorization_valid,
            "errors": list(self.errors),
            "policy_version": self.policy_version,
        }


def review_snapshot(
    snapshot: PlatformDraftSnapshot,
    *,
    policy: DraftReviewPolicy | None = None,
    now: datetime | None = None,
    published_fingerprints: Iterable[str] = (),
    batch_fingerprints: Iterable[str] = (),
) -> DraftReview:
    policy = policy or DraftReviewPolicy()
    issues: list[str] = []
    reasons: list[str] = []
    title = _normal_text(snapshot.title)
    body = _normal_text(snapshot.body)
    fingerprint = snapshot.content_fingerprint

    if not snapshot.scan_complete or snapshot.read_status != "complete":
        issues.append("incomplete_snapshot")
    if snapshot.identity_confidence == "ambiguous":
        issues.append("identity_ambiguous")
    if not title:
        issues.append("missing_title")
    if not body:
        issues.append("missing_body")
    if _MARKUP_RE.search(title) or _MARKUP_RE.search(body):
        issues.append("body_contains_markup")
    if _PLACEHOLDER_RE.search(title) or _PLACEHOLDER_RE.search(body):
        issues.append("placeholder_or_truncated_text")
    if _VAGUE_RE.search(_without_markup(title)) or _VAGUE_RE.search(_without_markup(body)):
        issues.append("body_is_vague")
    if policy.require_images and not snapshot.images:
        issues.append("missing_images")
    if snapshot.draft_type not in policy.allowed_types:
        issues.append("unsupported_draft_type")
    lowered = f"{title}\n{body}".casefold()
    if any(_normal_text(term).casefold() in lowered for term in policy.exclude_terms if _normal_text(term)):
        issues.append("excluded_by_policy")

    published = set(published_fingerprints)
    batch = set(batch_fingerprints)
    duplicate_of = ""
    if fingerprint in published:
        duplicate_of = "published"
        issues.append("duplicate_published")
    elif fingerprint in batch:
        duplicate_of = "batch"
        issues.append("duplicate_batch")

    if policy.max_age_days is not None:
        saved = _parse_time(snapshot.saved_at)
        current = now or datetime.now(timezone.utc)
        if saved is None:
            issues.append("saved_time_unknown")
        elif current.astimezone(timezone.utc) - saved.astimezone(timezone.utc) > timedelta(days=max(0, policy.max_age_days)):
            issues.append("stale_saved_draft")

    if "stale_saved_draft" in issues or "excluded_by_policy" in issues or duplicate_of:
        decision = "excluded"
    elif issues:
        decision = "needs_review"
    else:
        decision = "accepted"
        reasons.append("snapshot_complete")
        reasons.append("content_readable")
        reasons.append("image_set_available")

    score = 0.0 if decision == "excluded" else (0.5 if decision == "needs_review" else 1.0)
    return DraftReview(
        snapshot_id=snapshot.snapshot_id,
        decision=decision,
        score=score,
        issues=tuple(dict.fromkeys(issues)),
        reasons=tuple(reasons),
        duplicate_of=duplicate_of,
        content_fingerprint=fingerprint,
    )


def rank_reviews(reviews: Iterable[DraftReview], *, limit: int = 0) -> list[DraftReview]:
    accepted = [review for review in reviews if review.decision == "accepted"]
    accepted.sort(key=lambda review: (-review.score, review.snapshot_id))
    return accepted[: max(0, int(limit))] if limit else accepted


def build_action_plan(
    reviews: Iterable[DraftReview],
    *,
    action: str,
    authorization: DraftAuthorization,
    limit: int = 0,
    now: datetime | None = None,
) -> DraftActionPlan:
    action = _normal_text(action).lower()
    selected = rank_reviews(reviews, limit=limit)
    max_items = min(len(selected), max(0, int(authorization.max_items)))
    selected = selected[:max_items]
    if not authorization.allows(action, len(selected), now=now):
        error = "action_not_authorized" if action not in set(authorization.allowed_actions) else "authorization_limit_or_expired"
        return DraftActionPlan(
            action=action,
            items=(),
            authorization_valid=False,
            errors=(error,),
            policy_version=authorization.policy_version,
        )
    items = tuple(
        DraftActionItem(
            snapshot_id=review.snapshot_id,
            rank=index,
            expected_fingerprint=review.content_fingerprint,
            reason=";".join(review.reasons) or "accepted",
        )
        for index, review in enumerate(selected, start=1)
    )
    return DraftActionPlan(
        action=action,
        items=items,
        authorization_valid=True,
        policy_version=authorization.policy_version,
    )


def idempotency_key(snapshot: PlatformDraftSnapshot, action: str) -> str:
    value = f"{snapshot.account_id}|{snapshot.platform_draft_id}|{snapshot.snapshot_id}|{snapshot.content_fingerprint}|{_normal_text(action).lower()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class DraftManagementStore:
    """Small JSON store for resumable draft management runs."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.snapshots_dir = self.root / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def save_snapshot(self, snapshot: PlatformDraftSnapshot) -> Path:
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, snapshot.to_dict())
        return path

    def load_snapshot(self, snapshot_id: str) -> PlatformDraftSnapshot:
        path = self.snapshots_dir / f"{_normal_text(snapshot_id)}.json"
        return PlatformDraftSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_review(self, review: DraftReview) -> Path:
        path = self.root / "reviews.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(review.to_dict(), ensure_ascii=False) + "\n")
        return path

    def load_reviews(self) -> list[DraftReview]:
        path = self.root / "reviews.jsonl"
        if not path.exists():
            return []
        result: list[DraftReview] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            result.append(DraftReview(**data))
        return result

    def save_checkpoint(self, payload: dict[str, Any]) -> Path:
        path = self.root / "checkpoint.json"
        self._write_json(path, payload)
        return path

    def load_checkpoint(self) -> dict[str, Any]:
        return json.loads((self.root / "checkpoint.json").read_text(encoding="utf-8"))
