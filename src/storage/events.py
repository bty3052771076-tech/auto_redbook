from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .files import DATA_ROOT, ensure_dirs


def save_event(event: dict[str, Any], *, base: Path = DATA_ROOT) -> Path:
    ensure_dirs(base)
    payload = dict(event)
    payload["id"] = payload.get("id") or uuid4().hex
    payload["created_at"] = payload.get("created_at") or datetime.now(timezone.utc).isoformat()
    path = base / "events" / f"{payload['id']}.json"

    def _default(obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        return str(obj)

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_default),
        encoding="utf-8",
    )
    return path
