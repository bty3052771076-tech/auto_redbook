"""Durable action state for platform delivery.

The browser is an external side effect, so a boolean ``uploaded`` flag is not
enough.  This small adapter keeps a versioned action record and makes an
unresolved submission require reconciliation before another write can happen.
The file backend is deliberately explicit and local; a PostgreSQL backend can
implement the same contract without changing callers.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import RLock
from typing import Any, Iterator
from uuid import uuid4

from .reconcile import classify_publication_observation


_LOCK = RLock()
_TERMINAL = {
    "saved_draft",
    "published",
    "pending_review",
    "platform_restricted",
    "failed_definite",
}


class DeliveryStateError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


@dataclass(frozen=True)
class DeliveryAction:
    action_id: str
    idempotency_key: str
    account_id: str
    profile_key: str
    post_id: str
    content_version: str
    action: str
    visibility: str
    status: str = "prepared"
    next_action: str = "submit"
    platform_id: str = ""
    observed_visibility: str = "unknown"
    version: int = 1
    attempts: int = 0
    evidence_ref: str = ""
    last_error: str = ""


def terminal_action_block_reason(action: DeliveryAction, *, stage: str) -> str:
    """Return a stable no-write reason for a terminal external outcome."""

    normalized_stage = str(stage or "publish").strip().lower()
    if action.status == "pending_review":
        return "XHS_PENDING_REVIEW: 平台仍在审核，禁止再次提交"
    if action.status == "platform_restricted":
        return "XHS_PLATFORM_RESTRICTED: 平台限制仍未解除，禁止再次写入"
    if action.status == "failed_definite":
        return f"XHS_PLATFORM_REJECTED: {normalized_stage} 已被平台明确拒绝，禁止自动重试"
    return ""


def _key(request: dict[str, Any]) -> str:
    fields = (
        request.get("account_id", ""), request.get("profile_key", ""),
        request.get("post_id", ""), request.get("content_version", ""),
        request.get("action", ""), request.get("visibility", ""),
    )
    return "|".join(str(item).strip() for item in fields)


def _from_record(value: dict[str, Any]) -> DeliveryAction:
    return DeliveryAction(**{field: value.get(field, default) for field, default in {
        "action_id": "", "idempotency_key": "", "account_id": "", "profile_key": "",
        "post_id": "", "content_version": "", "action": "", "visibility": "",
        "status": "prepared", "next_action": "submit", "platform_id": "",
        "observed_visibility": "unknown", "version": 1, "attempts": 0,
        "evidence_ref": "", "last_error": "",
    }.items()})


class DeliveryStateStore:
    """Versioned local action ledger with an in-memory test constructor."""

    def __init__(self, path: Path | str | None = None, *, _memory: bool = False):
        self.path = Path(path or os.getenv(
            "DELIVERY_STATE_PATH", "data/runs/platform/delivery-actions.json"
        ))
        self._memory = _memory
        self._records: dict[str, dict[str, Any]] = {}

    @classmethod
    def in_memory(cls) -> "DeliveryStateStore":
        return cls(_memory=True)

    @contextmanager
    def _transaction(self) -> Iterator[dict[str, dict[str, Any]]]:
        with _LOCK:
            if self._memory:
                payload = self._records
            else:
                if self.path.exists():
                    try:
                        payload = json.loads(self.path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise DeliveryStateError("DELIVERY_STATE_UNAVAILABLE", str(exc)) from exc
                else:
                    payload = {}
                if not isinstance(payload, dict):
                    raise DeliveryStateError("DELIVERY_STATE_UNAVAILABLE", "动作账本格式无效")
            yield payload
            if not self._memory:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.path)

    def prepare_action(self, request: dict[str, Any]) -> DeliveryAction:
        required = ("account_id", "profile_key", "post_id", "content_version", "action", "visibility")
        missing = [name for name in required if not str(request.get(name, "")).strip()]
        if missing:
            raise DeliveryStateError("DELIVERY_ACTION_INVALID", f"缺少字段：{','.join(missing)}")
        key = _key(request)
        with self._transaction() as records:
            existing = records.get(key)
            if existing:
                return _from_record(existing)
            action = DeliveryAction(
                action_id=uuid4().hex,
                idempotency_key=key,
                account_id=str(request["account_id"]),
                profile_key=str(request["profile_key"]),
                post_id=str(request["post_id"]),
                content_version=str(request["content_version"]),
                action=str(request["action"]),
                visibility=str(request["visibility"]),
            )
            records[key] = asdict(action)
            return action

    def _find(self, action_id: str, records: dict[str, dict[str, Any]]) -> tuple[str, DeliveryAction]:
        for key, value in records.items():
            if str(value.get("action_id")) == str(action_id):
                return key, _from_record(value)
        raise DeliveryStateError("DELIVERY_ACTION_NOT_FOUND", f"未找到动作：{action_id}")

    def mark_submitting(self, action_id: str, *, expected_version: int) -> DeliveryAction:
        with self._transaction() as records:
            key, action = self._find(action_id, records)
            if action.version != int(expected_version):
                raise DeliveryStateError("DELIVERY_STATE_VERSION_CONFLICT", f"expected={expected_version}, current={action.version}")
            if action.status in _TERMINAL:
                return action
            if action.status in {"submitting", "uncertain"}:
                raise DeliveryStateError("DELIVERY_ACTION_RECONCILE_REQUIRED", "动作已经可能提交，必须先核对")
            updated = action.__class__(**{**asdict(action), "status": "submitting", "next_action": "reconcile", "attempts": action.attempts + 1, "version": action.version + 1})
            records[key] = asdict(updated)
            return updated

    def record_observation(self, action_id: str, evidence: dict[str, Any]) -> DeliveryAction:
        with self._transaction() as records:
            key, action = self._find(action_id, records)
            observation = classify_publication_observation(
                evidence,
                requested_visibility=action.visibility,
            )
            status, next_action = observation.status, observation.next_action
            if action.action == "save_draft" and observation.status == "uncertain" and str(evidence.get("stage") or "").lower() in {"saved_draft", "draft_saved"}:
                status, next_action = "saved_draft", "none"
            updated = action.__class__(**{**asdict(action), "status": status, "next_action": next_action,
                "platform_id": observation.platform_id or action.platform_id,
                "observed_visibility": observation.observed_visibility,
                "evidence_ref": str(evidence.get("evidence_ref") or action.evidence_ref),
                "last_error": str(evidence.get("error") or ""), "version": action.version + 1})
            records[key] = asdict(updated)
            return updated

    def get_resume_decision(self, action_id: str) -> DeliveryAction:
        with self._transaction() as records:
            _, action = self._find(action_id, records)
            if action.status in {"submitting", "uncertain"}:
                return action.__class__(**{**asdict(action), "status": "uncertain", "next_action": "reconcile"})
            return action
