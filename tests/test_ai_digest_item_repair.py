"""Offline regressions for item-local AI digest repair; never opens Workbench."""
import json
import socket
from types import SimpleNamespace

import pytest

from src.ai_digest import generate as digest
from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.config import LLMConfig


DATE = "2026-10-23"
CFGS = [LLMConfig(model="offline-model", api_key="offline", base_url="https://invalid.test", provider="test")]
GOOD_TITLE = "Cedar\u65b0\u589e\u6587\u4ef6\u5ba1\u9605"
GOOD_SUMMARY = "Cedar\u65b0\u589e\u6587\u4ef6\u5ba1\u9605\u529f\u80fd\uff0c\u56e2\u961f\u53ef\u5728\u5de5\u4f5c\u533a\u6279\u6ce8\u6587\u6863\u5e76\u67e5\u770b\u4fee\u6539\u8bb0\u5f55\u3002"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network/model initialization must be stubbed")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(digest, "init_chat_model", forbidden)


def source(index, *, english=False):
    return AIUpdateItem(
        title="Cedar adds document review" if english else GOOD_TITLE,
        summary="Teams can annotate documents and view revision history in the workspace." if english else GOOD_SUMMARY,
        raw_excerpt="Cedar adds document review. Teams can annotate documents and view revision history in the workspace.",
        url=f"https://source{index}.test/article",
        evidence_urls=[f"https://evidence{index}.test/report"],
        source_name=f"Source{index}", vendor="Cedar", product="Cedar",
        published_at="2026-10-22T20:10:00Z" if index % 2 else "",
        verification_status="aggregator_confirmed", confidence_score=0.91, tags=["\u5de5\u5177"],
    )


def row(item, *, title=GOOD_TITLE, summary=GOOD_SUMMARY, **extra):
    return {"url": item.url, "title": title, "summary": summary, **extra}


def install_model(monkeypatch, responses):
    calls = []
    def invoke(messages):
        calls.append(messages[-1].content)
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response if isinstance(response, str) else json.dumps(response, ensure_ascii=False))
    monkeypatch.setattr(digest, "init_chat_model", lambda *a, **k: SimpleNamespace(invoke=invoke))
    return calls


def repair(cfgs, brief, sources):
    helper = getattr(digest, "repair_ai_digest_brief_with_llm", None)
    assert callable(helper), "selected/fallback brief repair helper is missing"
    return helper(cfgs, brief, sources)


def test_qualified_partition_retains_copy_and_rejects_invented_facts():
    sources = [source(1), source(2, english=True), source(3)]
    brief = AIDigestBrief(date=DATE, items=[sources[0], sources[1],
        sources[2].model_copy(update={"summary": GOOD_SUMMARY + "性能提高99%。"})])
    before = brief.model_dump()
    kept, dropped = digest.retain_valid_ai_digest_items(brief, sources)
    assert [x.url for x in kept] == [sources[0].url]
    assert kept[0].model_dump() == sources[0].model_dump()
    assert [x["url"] for x in dropped] == [sources[1].url, sources[2].url]
    assert all(x["reason"] for x in dropped)
    assert brief.model_dump() == before


@pytest.mark.parametrize("kind", ["unknown", "ambiguous", "duplicate"])
def test_qualified_partition_does_not_guess_evidence_identity(kind):
    sources = [source(1), source(2)]
    selected = list(sources)
    if kind == "unknown":
        selected[1] = selected[1].model_copy(update={"url": "https://unknown.test/item"})
    elif kind == "ambiguous":
        sources.append(sources[1])
    else:
        selected[1] = selected[0]
    with pytest.raises(ValueError):
        digest.retain_valid_ai_digest_items(AIDigestBrief(date=DATE, items=selected), sources)


def test_exhausted_repair_retains_successful_copy_for_workflow_fallback(monkeypatch):
    sources = [source(1), source(2, english=True)]
    brief = AIDigestBrief(date=DATE, items=sources)
    calls = install_model(monkeypatch, [{"items": []}, {"items": []}])
    with pytest.raises(RuntimeError) as caught:
        repair(CFGS, brief, sources)
    partial = getattr(caught.value, "partial_brief", None)
    assert partial is not None
    assert partial.items[0].model_dump() == sources[0].model_dump()
    assert [item.url for item in partial.items] == [item.url for item in sources]
    assert len(calls) == 2
    assert all(sources[0].url not in prompt for prompt in calls)


def test_generation_repairs_only_failed_item_with_feedback(monkeypatch):
    sources = [source(1), source(2), source(3, english=True)]
    rows = [row(sources[0]), row(sources[1]), row(sources[2], title="Cedar\u62ab\u9732\u76f8\u5173\u53d8\u5316",
                                               summary="Cedar\u62ab\u9732\u76f8\u5173\u53d8\u5316\uff0c\u5177\u4f53\u80fd\u529b\u4ee5\u6765\u6e90\u94fe\u63a5\u4e3a\u51c6\u3002")]
    calls = install_model(monkeypatch, [
        {"date": DATE, "items": rows},
        {"items": [row(sources[2])]},
    ])
    result = digest.generate_ai_digest_brief_with_llm(CFGS, sources, target_count=3, date=DATE)
    assert [item.url for item in result.items] == [item.url for item in sources]
    assert result.items[0].summary == GOOD_SUMMARY
    assert result.items[1].summary == GOOD_SUMMARY
    assert result.items[2].summary == GOOD_SUMMARY
    assert len(calls) == 2
    assert sources[2].url in calls[1] and sources[0].url not in calls[1]
    assert "\u7a7a\u6cdb" in calls[1] or "\u4e2d\u6587\u6539\u5199" in calls[1]
    assert len(digest.render_ai_digest_body(result)) <= 800


def test_fallback_repair_preserves_all_non_copy_fields_and_successful_items(monkeypatch):
    sources = [source(1), source(2, english=True), source(3, english=True)]
    brief = AIDigestBrief(date=DATE, subtitle="\u539f\u6709\u526f\u6807\u9898", generated_at="original",
                          source_summary="\u539f\u6709\u6765\u6e90", items=sources)
    before = brief.model_dump()
    calls = install_model(monkeypatch, [
        {"date": "2099-01-01", "items": [row(sources[2]), row(sources[1], published_at="2099",
                                                          evidence_urls=["https://invented.test"])]},
    ])
    result = repair(CFGS, brief, sources)
    assert result.items[0].model_dump() == before["items"][0]
    for i in (1, 2):
        assert result.items[i].title == GOOD_TITLE
        assert result.items[i].summary == GOOD_SUMMARY
        for field in before["items"][i].keys() - {"title", "summary"}:
            assert getattr(result.items[i], field) == before["items"][i][field]
    assert result.model_dump(exclude={"items"}) == brief.model_dump(exclude={"items"})
    assert brief.model_dump() == before
    assert len(calls) == 1
    assert sources[0].url not in calls[0]
    assert sources[1].raw_excerpt in calls[0]
    assert len(digest.render_ai_digest_body(result)) <= 800


def test_repair_keeps_partial_success_and_sends_remaining_error(monkeypatch):
    sources = [source(1, english=True), source(2, english=True)]
    brief = AIDigestBrief(date=DATE, items=sources)
    calls = install_model(monkeypatch, [
        {"items": [row(sources[0]), row(sources[1], summary="Cedar\u65b0\u589e\u6587\u4ef6\u5ba1\u9605\u529f\u80fd\uff0c\u5904\u7406\u901f\u5ea6\u63d0\u534799%\u3002")]},
        {"items": [row(sources[1])]},
    ])
    result = repair(CFGS, brief, sources)
    assert [item.summary for item in result.items] == [GOOD_SUMMARY, GOOD_SUMMARY]
    assert len(calls) == 2
    assert sources[0].url not in calls[1]
    assert "99%" in calls[1] or "\u539f\u59cb\u6750\u6599" in calls[1]


@pytest.mark.parametrize("bad_response", [
    {"items": []},
    {"items": [{"url": "https://unknown.test", "title": GOOD_TITLE, "summary": GOOD_SUMMARY}]},
    {"items": [row(source(1)), row(source(1))]},
    {"items": [row(source(1), summary="Cedar\u65b0\u589e\u6587\u4ef6\u5ba1\u9605\u529f\u80fd\uff0c\u5904\u7406\u901f\u5ea6\u63d0\u534799%\u3002")]},
    {"items": [row(source(1), title="Cedar\u62ab\u9732\u76f8\u5173\u53d8\u5316", summary="Cedar\u62ab\u9732\u76f8\u5173\u53d8\u5316\uff0c\u5177\u4f53\u80fd\u529b\u4ee5\u94fe\u63a5\u4e3a\u51c6\u3002")]},
    '{"items": [',
])
def test_repair_is_bounded_and_does_not_accept_invalid_corrections(monkeypatch, bad_response):
    sources = [source(1, english=True)]
    brief = AIDigestBrief(date=DATE, items=sources)
    before = brief.model_dump()
    calls = install_model(monkeypatch, [bad_response, bad_response])
    with pytest.raises(RuntimeError, match="repair|generation"):
        repair(CFGS, brief, sources)
    assert len(calls) == 2
    assert brief.model_dump() == before


def test_repair_rejects_missing_source_identity_before_request():
    brief = AIDigestBrief(date=DATE, items=[source(1, english=True)])
    with pytest.raises(ValueError, match="source|URL"):
        repair(CFGS, brief, [source(2, english=True)])


def test_valid_selected_brief_needs_no_model_or_config():
    sources = [source(1)]
    brief = AIDigestBrief(date=DATE, items=sources)
    result = repair([], brief, sources)
    assert result.model_dump() == brief.model_dump()


def test_repair_retains_progress_across_provider_failure(monkeypatch):
    sources = [source(1, english=True), source(2, english=True)]
    calls = install_model(monkeypatch, [
        {"items": [row(sources[0])]}, RuntimeError("offline provider failure"),
        {"items": [row(sources[1])]},
    ])
    result = repair(CFGS * 2, AIDigestBrief(date=DATE, items=sources), sources)
    assert [item.summary for item in result.items] == [GOOD_SUMMARY, GOOD_SUMMARY]
    assert len(calls) == 3
    assert sources[0].url not in calls[1] and sources[0].url not in calls[2]


def test_valid_copy_is_not_reopened_by_approximate_claim_tokenization():
    original = source(1, english=True).model_copy(update={
        "raw_excerpt": "Cedar sets document review latency to 30.4 s. Teams can view revision history.",
    })
    item = original.model_copy(update={
        "title": "Cedar\u8c03\u6574\u6587\u6863\u5ba1\u9605\u5ef6\u8fdf",
        "summary": "Cedar\u5c06\u6587\u6863\u5ba1\u9605\u5ef6\u8fdf\u8bbe\u4e3a30.4s\uff0c\u56e2\u961f\u53ef\u4ee5\u67e5\u770b\u4fee\u6539\u8bb0\u5f55\u3002",
        "raw_excerpt": "Cedar sets document review latency to 30.4 s. Teams can view revision history.",
    })
    brief = AIDigestBrief(date=DATE, items=[item])
    assert repair([], brief, [original]).model_dump() == brief.model_dump()


def test_eleven_selected_items_survive_repair_and_body_compaction(monkeypatch):
    sources = [source(i, english=True) for i in range(11)]
    title = "Cedar\u65b0\u589e\u56e2\u961f\u6587\u4ef6\u5ba1\u9605\u529f\u80fd\u5e76\u652f\u6301\u5de5\u4f5c\u533a\u6587\u6863\u6279\u6ce8\u4e0e\u4fee\u6539\u8bb0\u5f55\u67e5\u770b"
    rows = [row(item, title=title) for item in sources]
    install_model(monkeypatch, [{"items": rows}])
    brief = AIDigestBrief(date=DATE, items=sources)
    result = repair(CFGS, brief, sources)
    assert len(result.items) == 11
    assert [item.url for item in result.items] == [item.url for item in sources]
    assert all(item.title == title for item in result.items)
    assert all(item.summary == GOOD_SUMMARY for item in result.items)
    assert len(digest.render_ai_digest_body(result)) <= 800


@pytest.mark.parametrize("sources", [[source(1), source(1)], []])
def test_ambiguous_or_missing_original_source_is_not_guessed(sources):
    brief = AIDigestBrief(date=DATE, items=[source(1, english=True)])
    with pytest.raises(ValueError, match="source|URL"):
        repair(CFGS, brief, sources)


def test_malformed_patch_retries_with_parser_feedback(monkeypatch):
    sources = [source(1, english=True)]
    calls = install_model(monkeypatch, ['{"items": [', {"items": [row(sources[0])]}])
    result = repair(CFGS, AIDigestBrief(date=DATE, items=sources), sources)
    assert result.items[0].summary == GOOD_SUMMARY
    assert len(calls) == 2
    assert "\u9519\u8bef" in calls[1]
