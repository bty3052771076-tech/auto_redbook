"""Local evidence used to make platform draft delivery idempotent.

The platform does not expose a stable draft identifier through every editor
path. A content revision fingerprint gives the local workflow a conservative
no-op check without pretending that an old remote draft is the current one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.storage.models import Post


def _asset_digest(asset: Any) -> str:
    declared = str(getattr(asset, "sha256", None) or "").strip().lower()
    if declared:
        return declared
    path = Path(str(getattr(asset, "path", "") or ""))
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        # Missing assets will be rejected by the normal validation gate. Keep
        # their path in the fingerprint so a later replacement is a change.
        return f"missing:{path.as_posix()}"


def _revision_payload(post: Post) -> dict[str, Any]:
    return {
        "type": str(getattr(post.type, "value", post.type)),
        "title": post.title or "",
        "body": post.body or "",
        "topics": list(post.topics or []),
        "assets": [
            {
                "kind": str(getattr(asset, "kind", "image") or "image"),
                "digest": _asset_digest(asset),
            }
            for asset in post.assets or []
        ],
    }


def content_revision_fingerprint(post: Post) -> str:
    """Return a stable SHA-256 for publishable text and ordered asset bytes."""

    encoded = json.dumps(
        _revision_payload(post),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def has_current_draft_receipt(post: Post, *, platform: str) -> bool:
    """Whether a platform receipt proves this exact local revision was saved."""

    key = f"{str(platform or '').strip().lower()}_draft"
    receipt = post.platform.get(key) if isinstance(post.platform, Mapping) else None
    if not isinstance(receipt, Mapping):
        return False
    recorded = str(receipt.get("revision_fingerprint") or "").strip().lower()
    return bool(recorded) and recorded == content_revision_fingerprint(post)
