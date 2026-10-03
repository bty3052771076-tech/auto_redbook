"""Reviewed, public source registry used by the unified source service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from .models import SourceSpec


DEFAULT_REGISTRY_PATH = Path("config") / "news_sources.json"


class SourceRegistry:
    def __init__(self, specs: Iterable[SourceSpec], *, version: str = "unknown", path: Path | None = None):
        values = list(specs)
        ids = [item.source_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("source_id values must be unique")
        self.specs = tuple(values)
        self.version = str(version or "unknown")
        self.path = Path(path) if path else None

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SourceRegistry":
        target = Path(path or os.getenv("NEWS_SOURCE_REGISTRY") or DEFAULT_REGISTRY_PATH)
        if not target.exists():
            raise FileNotFoundError(f"news source registry not found: {target}")
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("news source registry must be an object")
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            raise ValueError("news source registry sources must be a list")
        specs = [SourceSpec.from_mapping(item) for item in raw_sources if isinstance(item, dict)]
        return cls(specs, version=str(payload.get("version") or "unknown"), path=target)

    def select(self, packs: Iterable[str], *, include_disabled: bool = False) -> tuple[SourceSpec, ...]:
        wanted = {str(value).strip() for value in packs if str(value).strip()}
        values = []
        for spec in self.specs:
            if not include_disabled and not spec.enabled:
                continue
            if wanted and not wanted.intersection(spec.source_packs):
                continue
            values.append(spec)
        return tuple(values)

    def get(self, source_id: str) -> SourceSpec | None:
        return next((item for item in self.specs if item.source_id == source_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "sources": [item.to_dict() for item in self.specs]}
