from datetime import datetime, timedelta, timezone
import json

import pytest

from src.ai_digest import collect
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.search_plan import build_search_plan
from src.sources.health import SourceAttempt, SourceHealthSnapshot, save_source_health_snapshot
from src.ai_digest.sources import AIDigestSource
from src.ai_digest.rank import ai_update_category
from src.workflow import create_post


def release(name, source_type="official"):
    return AIUpdateItem(
        title=f"{name} model release with native vision",
        summary=f"{name} introduces native image input and open weights for developers.",
        source_name=name, source_type=source_type,
        url=f"https://example.com/{name}", product=name, vendor=name,
        published_at=datetime.now(timezone.utc).isoformat(),
        raw_excerpt=f"{name} model release: native image input and open weights.",
    )


def select(items, scores, **kwargs):
    return create_post._select_adaptive_ai_digest_items(
        items, impact_scores=scores, historical_keys=set(), min_items=1,
        min_domestic_model_count=0, min_foreign_ai_count=0, **kwargs,
    )


def test_official_release_not_lost_when_another_candidate_passes_llm():
    first, missed = release("GPT-99"), release("DeepSeek-V99.1-Flash")
    items, meta = select([first, missed], {
        first.dedupe_key: {"high_impact": True},
        missed.dedupe_key: {"high_impact": False},
    })
    assert {item.url for item in items} == {first.url, missed.url}
    assert meta["impact_rescue_count"] == 1


def test_zero_official_pool_cannot_be_published_as_complete_digest():
    item = release("GPT-99", "aggregator")
    with pytest.raises(RuntimeError, match="official.*insufficient"):
        select([item], {item.dedupe_key: {"high_impact": True}})


def test_speed_queries_cover_current_vendor_releases_without_old_events(monkeypatch):
    monkeypatch.delenv("AI_DIGEST_SEARCH_QUERIES", raising=False)
    queries = build_search_plan(collect.DEFAULT_SEARCH_BACKFILL_QUERIES, performance_mode="speed").queries
    combined = " ".join(queries)
    for vendor in ("DeepSeek", "Qwen", "OpenAI", "Anthropic", "Gemini"):
        assert vendor in combined
    assert "HY4 preview" not in combined
    assert "wind down" not in combined


def test_official_replacement_gets_bounded_recovery_probe(tmp_path):
    now = datetime.now(timezone.utc)
    source = AIDigestSource("deepseek", "official", "https://example.com/releases", "DeepSeek", "rss")
    health_path = tmp_path / "health.json"
    save_source_health_snapshot(SourceHealthSnapshot(
        collection="ai_digest", generated_at=now.isoformat(), attempts=[SourceAttempt(
            collection="ai_digest", source_name=source.name, source_url=source.url,
            tier="official_page", status="timeout", checked_at=(now-timedelta(days=1)).isoformat(),
            recent_statuses=("timeout",)*5,
        )],
    ), health_path)
    calls = []
    def fetch(src):
        calls.append(src.name)
        return [release("DeepSeek-V99.1-Flash")]
    collect.collect_ai_digest_updates(
        sources=[source], fetch_source=fetch, target_count=1, min_official_count=1,
        allow_social_backfill=False, max_age_days=3, now=now,
        source_health_path=health_path, persist_source_health=True,
    )
    assert calls == ["deepseek"]


def test_opinion_cannot_become_release_by_mentioning_old_models():
    item = release("DeepSeek-V99.1-Flash", "search").model_copy(update={
        "title": "观点：AI互动叙事为什么没有爆发",
        "raw_excerpt": "历史背景：DeepSeek V99.1 Flash模型发布，PixVerse R2发布。本文探讨行业趋势。",
    })
    assert ai_update_category(item) == "discussion"


def test_research_material_requires_real_official_host(tmp_path):
    path = tmp_path / "research.json"
    item = release("DeepSeek-V99.1-Flash").model_copy(update={
        "vendor": "DeepSeek", "evidence_urls": ["https://example.com/claim"],
    })
    path.write_text(json.dumps([item.model_dump()]), encoding="utf-8")
    with pytest.raises(ValueError, match="official host"):
        collect.load_ai_digest_research_items(path)


def test_research_material_enters_normal_dedupe_and_date_gates(tmp_path, monkeypatch):
    item = release("DeepSeek-V99.1-Flash", "aggregator")
    item = item.model_copy(update={"evidence_urls": [item.url]})
    path = tmp_path / "research.json"
    path.write_text(json.dumps([item.model_dump()]), encoding="utf-8")
    monkeypatch.setenv("AI_DIGEST_RESEARCH_ITEMS_FILE", str(path))
    selected, meta = collect.collect_ai_digest_updates(
        sources=[AIDigestSource("test", "official", "https://example.com", "test")],
        fetch_source=lambda _: [], target_count=1, min_official_count=0,
        max_age_days=3, allow_social_backfill=False,
        include_pool_items=True, persist_source_health=False,
        exclude_history_keys={create_post.ai_update_history_key(item)},
    )
    assert selected == []
    assert meta["research_materials"]["loaded"] == 1
    assert meta["research_materials"]["retained"] == 0
