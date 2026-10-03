"""Source-neutral models for the unified news collection tool.

The models deliberately separate the discovery channel from the original
publisher.  A Google RSS query, for example, is a transport dependency; it is
not evidence that Google authored the article.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    adapter: str
    publisher_id: str
    publisher_family: str
    source_name: str
    source_url: str = ""
    endpoint_ref: str = ""
    discovery_kind: str = "api"
    network_group: str = "direct"
    source_packs: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    authority_class: str = "secondary"
    enabled: bool = True
    upstream_ref: str = ""
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceSpec":
        def _strings(name: str) -> tuple[str, ...]:
            raw = value.get(name) or ()
            if isinstance(raw, str):
                raw = (raw,)
            return tuple(str(item).strip() for item in raw if str(item).strip())

        source_id = str(value.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("source_id is required")
        adapter = str(value.get("adapter") or "").strip().lower()
        if adapter not in {"rss", "api", "worldmonitor_digest"}:
            raise ValueError(f"unsupported source adapter: {adapter}")
        if adapter == "rss" and not str(value.get("source_url") or "").strip():
            raise ValueError(f"RSS source {source_id} requires source_url")
        if adapter == "api" and not str(value.get("endpoint_ref") or "").strip():
            raise ValueError(f"API source {source_id} requires endpoint_ref")
        return cls(
            source_id=source_id,
            adapter=adapter,
            publisher_id=str(value.get("publisher_id") or source_id).strip(),
            publisher_family=str(value.get("publisher_family") or value.get("publisher_id") or source_id).strip(),
            source_name=str(value.get("source_name") or source_id).strip(),
            source_url=str(value.get("source_url") or "").strip(),
            endpoint_ref=str(value.get("endpoint_ref") or "").strip(),
            discovery_kind=str(value.get("discovery_kind") or adapter).strip(),
            network_group=str(value.get("network_group") or "direct").strip(),
            source_packs=_strings("source_packs"),
            languages=_strings("languages"),
            regions=_strings("regions"),
            authority_class=str(value.get("authority_class") or "secondary").strip(),
            enabled=bool(value.get("enabled", True)),
            upstream_ref=str(value.get("upstream_ref") or "").strip(),
            capabilities=_strings("capabilities"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "source_packs": list(self.source_packs),
            "languages": list(self.languages),
            "regions": list(self.regions),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class SourceRequest:
    request_id: str
    run_id: str
    purpose: str
    prompt: str
    as_of: datetime
    timezone_name: str = "Asia/Shanghai"
    target_count: int = 10
    search_days: int = 1
    timeout_s: float = 30.0
    source_packs: tuple[str, ...] = ("daily_news",)
    additional_queries: tuple[str, ...] = ()
    max_records: int = 50

    def __post_init__(self) -> None:
        if not self.request_id or not self.run_id:
            raise ValueError("request_id and run_id are required")
        if self.purpose not in {"daily_news", "daily_ai_digest", "daily_wow", "daily_global_map"}:
            raise ValueError(f"unsupported source purpose: {self.purpose}")
        if self.target_count < 1 or self.max_records < 1:
            raise ValueError("target_count and max_records must be positive")
        if self.search_days < 1:
            raise ValueError("search_days must be positive")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["as_of"] = self.as_of.isoformat()
        value["source_packs"] = list(self.source_packs)
        value["additional_queries"] = list(self.additional_queries)
        return value


@dataclass(frozen=True)
class SourceArticle:
    article_id: str
    title: str
    url: str
    publisher_id: str
    publisher_family: str
    discovery_source_id: str
    discovery_kind: str
    network_group: str
    description: str = ""
    content: str = ""
    published_at: str = ""
    language: str = ""
    category: str = ""
    stale: bool = False
    evidence_status: str = "lead"
    discovery_paths: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["discovery_paths"] = list(self.discovery_paths)
        return value


@dataclass(frozen=True)
class SourceDecision:
    article_id: str
    status: str
    reason_code: str
    evidence_refs: tuple[str, ...] = ()
    matched_article_id: str = ""
    matched_post_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    request: SourceRequest
    status: str
    items: tuple[SourceArticle, ...]
    decisions: tuple[SourceDecision, ...]
    coverage: dict[str, Any]
    gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    timings: dict[str, float] = field(default_factory=dict)
    parent_snapshot_id: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "parent_snapshot_id": self.parent_snapshot_id,
            "request": self.request.to_dict(),
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "coverage": self.coverage,
            "gaps": list(self.gaps),
            "warnings": list(self.warnings),
            "timings": self.timings,
        }
