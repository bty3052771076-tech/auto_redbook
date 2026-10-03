from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class KnowledgeDocument:
    record_id: str
    record_type: str
    account_namespace: str = "local"
    title: str = ""
    body: str = ""
    source_url: str = ""
    source_published_at: str = ""
    observed_at: str = ""
    status: str = ""
    visibility: str = "unknown"
    allowed_purposes: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = {
            "title": self.title,
            "body": self.body,
            "source_url": self.source_url,
            "source_published_at": self.source_published_at,
            "metadata": self.metadata,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def to_record(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "account_namespace": self.account_namespace,
            "title": self.title,
            "body": self.body,
            "source_url": self.source_url,
            "source_published_at": self.source_published_at,
            "observed_at": self.observed_at,
            "status": self.status,
            "visibility": self.visibility,
            "allowed_purposes": list(self.allowed_purposes),
            "metadata": self.metadata,
            "content_hash": self.content_hash,
        }
