"""Persistent, fail-closed state for one platform/profile binding.

This module deliberately uses a small local JSON ledger so unit tests and a
fresh checkout do not need a database connection just to stop a risky browser
run. The ledger is local runtime data under ``data/`` and is not content
knowledge. A later PostgreSQL migration can keep the same state contract.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Iterator


_LOCK = Lock()


class PlatformStateError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}")


def _profile_key(value: str | os.PathLike[str]) -> str:
    return str(Path(value).expanduser().resolve())


class PlatformStateStore:
    """Atomic local state store with versioned clear operations."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.getenv("XHS_PLATFORM_STATE_PATH") or "data/runs/platform/platform-state.json")

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise PlatformStateError("XHS_STATE_STORE_UNAVAILABLE", str(exc)) from exc
            else:
                payload = {"profiles": {}}
            if not isinstance(payload, dict):
                raise PlatformStateError("XHS_STATE_STORE_UNAVAILABLE", "状态文件不是对象")
            payload.setdefault("profiles", {})
            yield payload
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)

    def get(self, profile_key: str | os.PathLike[str]) -> dict[str, Any]:
        key = _profile_key(profile_key)
        with self._locked() as payload:
            value = dict(payload["profiles"].get(key) or {})
            return value or {"profile_key": key, "status": "ready", "version": 0}

    def assert_operable(self, profile_key: str | os.PathLike[str]) -> None:
        state = self.get(profile_key)
        status = str(state.get("status") or "unknown")
        if status != "ready":
            code = str(state.get("code") or "XHS_PLATFORM_PAUSED")
            detail = str(state.get("detail") or "平台会话已暂停")
            raise PlatformStateError(code, detail)

    def pause(
        self,
        *,
        profile_key: str | os.PathLike[str],
        code: str,
        detail: str,
        evidence_ref: str = "",
        status: str = "risk_blocked",
    ) -> dict[str, Any]:
        key = _profile_key(profile_key)
        with self._locked() as payload:
            previous = dict(payload["profiles"].get(key) or {})
            value = {
                "profile_key": key,
                "status": status,
                "code": str(code),
                "detail": str(detail),
                "evidence_ref": str(evidence_ref or ""),
                "version": int(previous.get("version") or 0) + 1,
            }
            payload["profiles"][key] = value
            return dict(value)

    def clear(self, profile_key: str | os.PathLike[str], *, expected_version: int) -> dict[str, Any]:
        key = _profile_key(profile_key)
        with self._locked() as payload:
            previous = dict(payload["profiles"].get(key) or {"version": 0})
            current_version = int(previous.get("version") or 0)
            if current_version != int(expected_version):
                raise PlatformStateError(
                    "XHS_STATE_VERSION_CONFLICT",
                    f"expected version={expected_version}, current version={current_version}",
                )
            value = {
                "profile_key": key,
                "status": "ready",
                "code": "",
                "detail": "",
                "evidence_ref": "",
                "version": current_version + 1,
            }
            payload["profiles"][key] = value
            return dict(value)
