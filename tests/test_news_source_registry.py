from __future__ import annotations

import json

import pytest

from src.sources.models import SourceSpec
from src.sources.registry import SourceRegistry


def test_registry_loads_reviewed_public_sources():
    registry = SourceRegistry.load("config/news_sources.json")

    assert registry.version.startswith("worldmonitor-")
    assert registry.get("wm_bbc_world").adapter == "rss"
    assert registry.get("api_tianapi").endpoint_ref == "tianapi"
    assert registry.get("worldmonitor_digest").adapter == "worldmonitor_digest"
    assert "global_map" in registry.get("wm_bbc_world").source_packs


def test_registry_rejects_duplicate_ids_and_missing_endpoint(tmp_path):
    target = tmp_path / "sources.json"
    target.write_text(json.dumps({"sources": [
        {"source_id": "same", "adapter": "api", "endpoint_ref": "x"},
        {"source_id": "same", "adapter": "api", "endpoint_ref": "y"},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        SourceRegistry.load(target)

    with pytest.raises(ValueError, match="requires source_url"):
        SourceSpec.from_mapping({"source_id": "rss", "adapter": "rss"})


def test_registry_selects_by_source_pack():
    registry = SourceRegistry([
        SourceSpec.from_mapping({"source_id": "a", "adapter": "rss", "source_url": "https://a.test/rss", "source_packs": ["world"]}),
        SourceSpec.from_mapping({"source_id": "b", "adapter": "rss", "source_url": "https://b.test/rss", "source_packs": ["ai_industry"]}),
    ])

    assert [item.source_id for item in registry.select(("world",))] == ["a"]
