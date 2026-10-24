"""Offline workflow integration: no live models, database, jobs or uploads."""
import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from src.ai_digest import generate as digest
from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.config import LLMConfig
from src.workflow import create_post as workflow


TITLE = "Juniper AI\u65b0\u589e\u6587\u4ef6\u5ba1\u9605"
SUMMARY = "Juniper AI\u5728\u56e2\u961f\u5de5\u4f5c\u533a\u65b0\u589e\u6587\u4ef6\u5ba1\u9605\uff0c\u7528\u6237\u53ef\u6279\u6ce8\u6587\u6863\u5e76\u67e5\u770b\u4fee\u6539\u8bb0\u5f55\u3002"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REDBOOK_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_DIGEST_IMPACT_SUPERVISOR", "0")
    monkeypatch.setenv("AI_DIGEST_HIGH_IMPACT_SCORE", "0")
    for key in ("AI_DIGEST_TARGET_ITEMS", "AI_DIGEST_MAX_ITEMS", "AI_DIGEST_LOOKBACK_DAYS"):
        monkeypatch.delenv(key, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("offline test attempted network/model initialization")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(digest, "init_chat_model", forbidden)
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    good = AIUpdateItem(
        title="Cedar AI\u65b0\u589e\u6587\u6863\u6279\u6ce8",
        summary="Cedar AI\u5728\u56e2\u961f\u5de5\u4f5c\u533a\u65b0\u589e\u6587\u6863\u6279\u6ce8\uff0c\u7528\u6237\u53ef\u4ee5\u67e5\u770b\u4fee\u6539\u8bb0\u5f55\u3002",
        raw_excerpt="Cedar AI adds document annotations and revision history in the team workspace.",
        source_name="Cedar", vendor="Cedar", product="Cedar",
        url="https://cedar.test/annotations", published_at=now.isoformat(),
        tags=["AI\u52a8\u6001"],
    )
    english = AIUpdateItem(
        title="Juniper AI adds document review",
        summary="Juniper AI adds document review. Teams can annotate documents and view revision history.",
        raw_excerpt="Juniper AI adds document review. Teams can annotate documents and view revision history.",
        source_name="Juniper", vendor="Juniper", product="Juniper",
        url="https://juniper.test/review", published_at=now.isoformat(),
        evidence_urls=["https://evidence.test/juniper-review"], tags=["AI\u52a8\u6001"],
    )
    cfg = LLMConfig(provider="test", model="offline", api_key="offline", base_url="https://invalid.test")
    state = {
        "pool": [good, english], "collects": 0, "writes": 0,
        "prompts": [], "saved": [], "repairs": [], "mode": "fallback",
        "responses": [], "generated": False, "quota_checked": False,
    }
    def collect(**kwargs):
        state["collects"] += 1
        return state["pool"], {}

    def generate(cfgs, selected, **kwargs):
        state["writes"] += 1
        state["generated"] = True
        if state["mode"] == "partial":
            partial = AIDigestBrief(date="1999-01-01", items=[
                x.model_copy(update={"summary": x.summary + "团队可查看文档版本。"}) if x.vendor == "Cedar" else x
                for x in selected
            ])
            state["partial"] = partial
            raise digest.AIDigestGenerationError("one failed item", partial_brief=partial)
        if state["mode"] == "fallback":
            raise RuntimeError("offline initial writer failure")
        if state["mode"] == "valid":
            selected = [x.model_copy(update={"title": TITLE, "summary": SUMMARY})
                        if x.url == english.url else x for x in selected]
        elif state["mode"] == "unknown_url":
            selected = [x.model_copy(update={"url": "https://unselected.test/event"})
                        if x.url == english.url else x for x in selected]
        return AIDigestBrief(date="1999-01-01", items=selected)

    def invoke(messages):
        state["prompts"].append(messages[-1].content)
        response = state["responses"].pop(0) if state["responses"] else {
            "items": [{"url": english.url, "title": TITLE, "summary": SUMMARY,
                       "published_at": "2099-01-01", "evidence_urls": ["https://invented.test"]}],
        }
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))

    def repair(cfgs, brief, source_items):
        state["repairs"].append((brief.model_dump(), [x.model_dump() for x in source_items]))
        return digest.repair_ai_digest_brief_with_llm(cfgs, brief, source_items)

    monkeypatch.setattr(workflow, "collect_ai_digest_updates", collect)
    monkeypatch.setattr(workflow, "_uploaded_ai_digest_history_keys", lambda **kwargs: set())
    monkeypatch.setattr(workflow, "load_llm_configs", lambda: [cfg])
    monkeypatch.setattr(workflow, "evaluate_ai_digest_impact_with_llm", lambda cfgs, items, **kw: (
        {x.dedupe_key: {"high_impact": True, "impact_score": 90, "llm_score": 90} for x in items},
        {"mode": "offline_fixture", "evaluated_count": len(items), "error": ""},
    ))
    monkeypatch.setattr(workflow, "generate_ai_digest_brief_with_llm", generate)
    monkeypatch.setattr(workflow, "repair_ai_digest_brief_with_llm", repair, raising=False)
    monkeypatch.setattr(digest, "init_chat_model", lambda *a, **k: SimpleNamespace(invoke=invoke))
    card = tmp_path / "card.png"
    Image.new("RGB", (2, 2)).save(card)
    monkeypatch.setattr(workflow, "render_ai_digest_cards", lambda *a, **k: [card])
    monkeypatch.setattr(workflow, "post_dir", lambda post_id: tmp_path / post_id)
    monkeypatch.setattr(workflow, "save_post", state["saved"].append)
    monkeypatch.setattr(workflow, "save_revision", lambda revision: None)
    return state


@pytest.mark.parametrize("mode", ["fallback", "returned", "quota_fallback"])
def test_final_content_repair_handles_all_generation_paths_without_recollection(setup, monkeypatch, mode):
    state = setup
    state["mode"] = mode
    if mode == "quota_fallback":
        original = workflow._ai_digest_selection_error
        def selection_error(items, **kwargs):
            if state["generated"] and not state["quota_checked"]:
                state["quota_checked"] = True
                return "offline injected quota failure"
            return original(items, **kwargs)
        monkeypatch.setattr(workflow, "_ai_digest_selection_error", selection_error)

    post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    result = post.platform["ai_digest"]["brief"]
    assert state["collects"] == state["writes"] == 1
    assert len(state["repairs"]) == len(state["prompts"]) == 1
    before, original_sources = state["repairs"][0]
    assert [x["url"] for x in result["items"]] == [x["url"] for x in before["items"]]
    good = next(x for x in result["items"] if x["vendor"] == "Cedar")
    assert good == next(x for x in before["items"] if x["vendor"] == "Cedar")
    repaired = next(x for x in result["items"] if x["vendor"] == "Juniper")
    source = next(x for x in original_sources if x["url"] == repaired["url"])
    assert source["title"] == "Juniper AI adds document review"
    assert source["summary"].startswith("Juniper AI adds document review.")
    assert repaired["title"] == TITLE and repaired["summary"] == SUMMARY
    assert repaired["published_at"] == source["published_at"]
    assert repaired["evidence_urls"] == ["https://evidence.test/juniper-review"]
    assert result["date"] == datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    assert "https://cedar.test/annotations" not in state["prompts"][0]
    assert len(post.body) <= 800
    assert state["saved"] == [post]
    assert post.platform["ai_digest"]["generation_mode"] == (
        "llm_quota_fallback" if mode == "quota_fallback" else "llm" if mode == "returned" else "fallback"
    )


def test_valid_generated_content_never_requests_a_repair(setup):
    setup["mode"] = "valid"
    post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    assert len(post.platform["ai_digest"]["items"]) == 2
    assert setup["repairs"] == setup["prompts"] == []
    assert setup["collects"] == 1


def test_failed_generation_hands_successful_copy_to_bounded_final_repair(setup):
    setup["mode"] = "partial"
    post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    good = next(item for item in post.platform["ai_digest"]["items"] if item["vendor"] == "Cedar")
    original = next(item for item in setup["partial"].items if item.vendor == "Cedar")
    assert good["summary"] == original.summary
    assert setup["collects"] == setup["writes"] == len(setup["prompts"]) == 1
    assert "https://cedar.test/annotations" not in setup["prompts"][0]
    assert len(post.body) <= 800


def test_fallback_repair_is_bounded_and_cannot_publish_invented_facts(setup, monkeypatch):
    monkeypatch.setenv("AI_DIGEST_ADAPTIVE_COUNT", "0")
    monkeypatch.setenv("AI_DIGEST_TARGET_ITEMS", "2")
    bad = {"items": [{"url": setup["pool"][1].url, "title": TITLE,
                       "summary": SUMMARY + "\u5904\u7406\u901f\u5ea6\u63d0\u534799%\u3002"}]}
    setup["responses"] = [bad, bad]
    with pytest.raises(RuntimeError, match="repair"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert setup["collects"] == setup["writes"] == 1
    assert len(setup["repairs"]) == 1 and len(setup["prompts"]) == 2
    assert setup["saved"] == []


def test_repair_does_not_reintroduce_stale_undated_or_duplicate_sources(setup):
    item = setup["pool"][1]
    setup["pool"] += [
        setup["pool"][0].model_copy(deep=True),
        item.model_copy(update={"url": "https://old.test/review",
                                "published_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}),
        item.model_copy(update={"url": "https://undated.test/review", "published_at": ""}),
    ]
    post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    assert {x["url"] for x in post.platform["ai_digest"]["items"]} == {
        "https://cedar.test/annotations", "https://juniper.test/review",
    }
    assert len(post.platform["ai_digest"]["items"]) == 2
    assert setup["collects"] == 1
    assert "https://old.test" not in setup["prompts"][0]
    assert "https://undated.test" not in setup["prompts"][0]


def test_unmatched_final_url_fails_closed_without_guessing_source(setup):
    setup["mode"] = "unknown_url"
    with pytest.raises(RuntimeError, match="source|URL"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert len(setup["repairs"]) == 1
    assert setup["prompts"] == setup["saved"] == []
    assert setup["collects"] == 1


def test_body_hard_cap_is_rechecked_after_repair(setup, monkeypatch):
    original = workflow.render_ai_digest_body
    def oversized_after_repair(brief, **kwargs):
        return "x" * 801 if setup["prompts"] else original(brief, **kwargs)
    monkeypatch.setattr(workflow, "render_ai_digest_body", oversized_after_repair)
    with pytest.raises(RuntimeError, match="801 > 800"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert len(setup["repairs"]) == 1
    assert setup["collects"] == 1 and setup["saved"] == []


def test_missing_configs_cannot_cause_unbound_variable_or_silent_acceptance(setup, monkeypatch):
    def unavailable():
        raise RuntimeError("offline missing config")
    monkeypatch.setattr(workflow, "load_llm_configs", unavailable)
    with pytest.raises(RuntimeError, match="config missing"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert setup["collects"] == 1 and setup["saved"] == []
    assert len(setup["repairs"]) == 1 and setup["prompts"] == []


def test_adaptive_exhaustion_keeps_good_copy_and_audits_dropped_item(setup):
    setup["mode"] = "partial"
    setup["responses"] = [{"items": []}, {"items": []}]
    post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    items = post.platform["ai_digest"]["items"]
    assert len(items) == 1 and items[0]["vendor"] == "Cedar"
    original = next(x for x in setup["partial"].items if x.vendor == "Cedar")
    assert items[0]["summary"] == original.summary
    assert setup["collects"] == setup["writes"] == 1
    assert len(setup["prompts"]) == 2
    assert len(post.body) <= 800 and setup["saved"] == [post]
    metadata = post.platform["ai_digest"]
    assert "qualified_subset" in json.dumps(metadata, ensure_ascii=False)
    assert "Juniper" in json.dumps(metadata, ensure_ascii=False)


def test_adaptive_exhaustion_cannot_accept_an_empty_brief(setup):
    setup["pool"] = [setup["pool"][1]]
    setup["responses"] = [{"items": []}, {"items": []}]
    with pytest.raises(RuntimeError, match="repair"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert setup["saved"] == []


def test_adaptive_subset_still_checks_explicit_topics(setup, monkeypatch):
    setup["responses"] = [{"items": []}, {"items": []}]
    original = workflow._missing_ai_digest_prompt_topics
    def missing(items, topics):
        if setup["prompts"] and not any(x.vendor == "Juniper" for x in items):
            return ["Juniper"]
        return original(items, topics)
    monkeypatch.setattr(workflow, "_missing_ai_digest_prompt_topics", missing)
    with pytest.raises(RuntimeError, match="requested topics"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert setup["saved"] == []


def test_adaptive_subset_still_checks_final_selection(setup, monkeypatch):
    setup["responses"] = [{"items": []}, {"items": []}]
    original = workflow._ai_digest_selection_error
    def selection(items, **kwargs):
        if setup["prompts"] and len(items) == 1:
            return "required quota lost"
        return original(items, **kwargs)
    monkeypatch.setattr(workflow, "_ai_digest_selection_error", selection)
    with pytest.raises(RuntimeError, match="required quota lost"):
        workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert setup["saved"] == []
