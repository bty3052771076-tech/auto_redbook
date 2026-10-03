from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.storage.files import list_posts
from src.storage.models import Post

from .models import KnowledgeDocument
from .store import KnowledgeStore


def _purposes(post: Post) -> tuple[str, ...]:
    visibility = str((post.platform or {}).get("publish", {}).get("visibility") or "unknown").lower()
    status = str(post.status.value if hasattr(post.status, "value") else post.status)
    purposes = ["duplicate_reference", "operational_case"]
    if status in {"published", "saved_as_draft"} and visibility not in {"private", "unknown"}:
        purposes.append("performance")
    if status not in {"failed", "canceled"}:
        purposes.append("style_example")
    # Generated copy is useful for duplicate/style checks, never factual evidence.
    return tuple(purposes)


def document_from_post(post: Post) -> KnowledgeDocument:
    status = str(post.status.value if hasattr(post.status, "value") else post.status)
    visibility = str((post.platform or {}).get("publish", {}).get("visibility") or "unknown")
    metadata = {
        "post_type": str(post.type.value if hasattr(post.type, "value") else post.type),
        "topics": list(post.topics or []),
        "asset_count": len(post.assets or []),
        "platform_keys": sorted(str(key) for key in (post.platform or {}).keys()),
    }
    return KnowledgeDocument(
        record_id=f"post-{post.id}",
        record_type="post",
        title=post.title,
        body=post.body,
        source_url=str((post.platform or {}).get("news", {}).get("source_url") or ""),
        source_published_at=str((post.platform or {}).get("news", {}).get("published_at") or ""),
        observed_at=post.updated_at or post.created_at,
        status=status,
        visibility=visibility,
        allowed_purposes=_purposes(post),
        metadata=metadata,
    )


def ingest_posts(store: KnowledgeStore, *, data_root: Path = Path("data")) -> dict[str, Any]:
    documents = [document_from_post(post) for post in list_posts(base=data_root)]
    counts = store.upsert_documents(documents)
    return {
        "domain": "posts",
        "input_count": len(documents),
        "documents": len(documents),
        **counts,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
