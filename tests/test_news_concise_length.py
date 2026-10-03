import json
import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.config import LLMConfig
from src.llm import generate as llm
from src.news.daily_news import NewsItem
from src.workflow import create_post as w


LEAD = "市交通局公布周末公交夜间班次调整方案，计划在中心城区试行。"
DETAILS = [
    "运营公司将调整末班车时刻，并在正式上线前完成车辆设备调试。",
    "交通部门表示新增班次覆盖通勤线路与换乘站，现有交通专项资金承担试行支出。",
    "工会代表提出司机轮班需要协商，乘客协会要求同步改善站点照明安全设施。",
    "试行阶段将收集客流与投诉数据，议会委员会据此审查后续实施安排。",
    "当地高校协助开展客流调查，运营公司根据调查结果评估站点服务需求。",
    "交通局要求公布线路调整清单，避免乘客因新旧时刻混淆而错过末班车。",
    "相关部门将在试行结束后统一汇总反馈，确定是否延续新增的夜间服务。",
    "公交站工作人员会更新站牌信息，并告知乘客试行安排尚未全面实施。",
    "换乘站将开展设备巡检，运营单位也会检查夜间车辆的维护与调度情况。",
    "乘客协会将跟踪郊区接驳需求，要求评估通勤线路之间的衔接条件。",
    "运营公司与工会继续讨论轮班安排，双方尚未公布最终协商结果。",
]
SHORT = LEAD + "".join(DETAILS[:4])
LONG = LEAD + "".join(DETAILS)
COMMENT = "此次调整增加夜间出行选择，具体实施效果仍待试行数据验证。"


def article(content, comment=COMMENT):
    return f"内容：\n{content}\n\n评价：\n{comment}\n\n日期：2026-10-03\n\n来源：市交通局"


def source(content=LONG):
    return NewsItem(title="市交通局公布周末公交夜间班次调整方案",
                    url="https://example.invalid/bus", content=content,
                    description="", source="市交通局", domain="example.invalid",
                    seendate="2026-10-03 08:00:00", language="zh")


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise AssertionError("length tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("size,complexity,reason,evidence,expected_limit,expected_issue", [
    (220, "normal", "", [], 220, ""),
    (221, "normal", "", [], 220, "content_too_long"),
    (300, "complex", "需交代资金来源及司机轮班两项执行条件", ["司机轮班需要协商", "站点照明安全设施"], 300, ""),
    (301, "complex", "需交代资金来源及司机轮班两项执行条件", ["司机轮班需要协商", "站点照明安全设施"], 300, "content_too_long"),
    (250, "complex", "", ["司机轮班需要协商", "站点照明安全设施"], 220, "content_too_long"),
    (250, "complex", "只是原文较长所以希望延长", ["原文不存在的说明", "另一条无依据说明"], 220, "content_too_long"),
])
def test_length_limits_require_grounded_complexity(size, complexity, reason, evidence, expected_limit, expected_issue):
    from src.news.length_policy import assess_news_length

    review = assess_news_length("事" * (size - 1) + "。", COMMENT,
                                {"complexity": complexity, "complexity_reason": reason,
                                 "complexity_evidence": evidence}, source())
    assert review["content_limit"] == expected_limit
    assert review["issue"] == expected_issue


def test_comment_upper_bound_and_sparse_facts_do_not_require_padding():
    from src.news.length_policy import assess_news_length

    assert assess_news_length("机构宣布暂停服务。", "后续安排仍待确认。", {}, source())["issue"] == ""
    assert assess_news_length(SHORT, "评" * 40 + "。", {}, source())["issue"] == "comment_too_long"
    assert assess_news_length(SHORT, "评" * 39 + "。", {}, source())["issue"] == ""


def test_normalization_retains_complete_overlong_single_sentence_for_resummary():
    content = "市交通局公布夜间公交服务方案，" + "公交服务设施" * 220 + "仍需按原计划逐步完成。"
    picked = source(content)
    result = w._finalize_daily_news_body(article(content), picked, "公交", preserve_length=True)
    result = w._repair_daily_news_mismatched_comment(result, picked, "公交", preserve_length=True)
    assert w._daily_news_body_quality_fields(result)["内容"] == content
    assert result.endswith("来源：市交通局")
    assert "…" not in result


def run_candidate(monkeypatch, drafts, *, column="daily_news", auto_image_enabled=False):
    calls = []
    saved = []
    progress = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return deepcopy(drafts[min(len(calls) - 1, len(drafts) - 1)])

    monkeypatch.setattr(w, "generate_draft", generate)
    monkeypatch.setattr(w, "save_post", lambda post: saved.append(post))
    monkeypatch.setattr(w, "save_revision", lambda revision: None)
    picked = source()
    queue = w.ModelWorkQueues(llm_workers=1, image_workers=1)
    try:
        result = w._prepare_daily_news_candidate(
            candidate_index=1, picked=picked, cfgs=[LLMConfig("fake", "test", provider="fake")],
            asset_paths=[], copy_assets=False, auto_image_enabled=auto_image_enabled,
            prompt_norm="公交", viewpoint_norm="无视角评价", target_count=1,
            single_material_mode=False, base_meta={},
            progress_callback=lambda stage, status, details: progress.append((stage, status, details)),
            model_queues=queue, post_quality_callback=None, prepared=(picked, {}, {}, picked), column=column,
        )
    finally:
        queue.close()
    return result, calls, saved


def draft(content, comment=COMMENT, **extras):
    return {"title": "市交通局调整周末夜间公交班次", "body": article(content, comment),
            "topics": ["每日新闻"], **extras}


def test_long_initial_copy_is_resummarized_once_and_retains_core_facts(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [draft(LONG), draft(SHORT)])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 2
    assert LONG in calls[1]["prompt_hint"]  # do not feed a previously sliced version
    assert result.post.body.startswith("内容：\n" + LEAD)
    assert "计划在中心城区试行" in result.post.body
    assert "尚未全面实施" not in result.post.body
    assert "现有交通专项资金" in result.post.body
    assert result.post.platform["news"]["length_review"]["rewrite_count"] == 1
    assert calls[0]["preserve_body"] is True
    assert all(call.get("concise_news") is True for call in calls)

def test_single_post_entry_resummarizes_before_saving(monkeypatch):
    picked = source()
    calls, saved = [], []
    scene = LEAD + "市交通局公布公交夜间班次调整方案的概念示意，以市交通局的非写实侧影表达计划立场，背景为纯色色面，所有物面留白。"
    versions = [draft(LONG, image_event=scene), draft(SHORT, image_event=scene)]

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return deepcopy(versions[min(len(calls) - 1, 1)])

    monkeypatch.setattr(w, "generate_draft", generate)
    monkeypatch.setattr(w, "load_llm_configs", lambda: [LLMConfig("fake", "test", provider="fake")])
    monkeypatch.setattr(w, "_fetch_daily_news_candidates_for_upload", lambda *a, **kw: ([picked], {}))
    monkeypatch.setattr(w, "_enrich_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(w, "_focus_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(w, "save_post", lambda post: saved.append(post))
    monkeypatch.setattr(w, "save_revision", lambda revision: None)
    post = w.create_post_with_draft(
        title_hint="每日新闻", prompt_hint="公交", asset_paths=[], copy_assets=False, auto_image=False,
    )
    assert len(calls) == 2
    assert saved == [post]
    assert w._daily_news_body_quality_fields(post.body)["内容"] == SHORT
    assert post.platform["news"]["length_review"]["rewrite_count"] == 1
    assert post.platform["news"]["image_event"].startswith(LEAD)


def test_single_length_rewrite_rechecks_unfinished_comment(monkeypatch):
    initial = draft(SHORT, COMMENT + "公交司机轮班安排仍需")
    calls = []
    monkeypatch.setattr(w, "generate_draft", lambda *a, **kw: (calls.append(kw) or draft(SHORT)))
    revised, issue = w._resummarize_daily_news_length_once(
        initial, cfgs=[LLMConfig("fake", "test", provider="fake")],
        picked=source(), prompt_norm="公交", news_prompt=w._daily_news_prompt(source(), "公交"), asset_paths=[],
    )
    assert not issue
    assert len(calls) == 1
    assert w._daily_news_body_quality_fields(revised["body"])["评价"] == COMMENT


def test_llm_default_body_limit_is_unchanged_for_other_columns(monkeypatch):
    content = LEAD + "公交服务设施" * 220 + "仍需按原计划逐步完成。"
    monkeypatch.setattr(llm, "init_chat_model", lambda *args, **kwargs: SimpleNamespace(
        invoke=lambda messages: SimpleNamespace(content=json.dumps(draft(content), ensure_ascii=False),
                                                response_metadata={"finish_reason": "stop"}, usage_metadata={})
    ))
    result = llm.generate_draft(LLMConfig("fake", "test", provider="fake"),
                                title_hint="其他栏目", prompt_hint="已提供材料", asset_paths=[])
    assert len(result["body"]) <= 1000



def test_fit_copy_does_not_add_a_model_call(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [draft(SHORT)])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 1
    assert result.post.platform["news"]["length_review"]["content_chars"] <= 220
    assert result.post.platform["news"]["length_review"]["rewrite_count"] == 0


def test_second_overlong_copy_is_rejected_without_third_call_or_clipping(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [draft(LONG), draft(LONG)])
    assert result.status == "skipped"
    assert result.reason == "content_too_long"
    assert len(calls) == 2
    assert w._daily_news_body_quality_fields(result.draft["body"])["内容"] == LONG
    assert result.post is None or not result.post.assets


def test_long_comment_is_rewritten_without_cutting_it(monkeypatch):
    long_comment = "新增的夜间公交服务有利于乘客出行，但司机轮班、站点照明以及线路之间的衔接条件仍需要相关部门继续协商并依据试行数据评估。"
    result, calls, _ = run_candidate(monkeypatch, [draft(SHORT, long_comment), draft(SHORT)])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 2
    assert long_comment in calls[1]["prompt_hint"]
    assert w._daily_news_body_quality_fields(result.post.body)["评价"] == COMMENT


def test_complete_llm_body_is_kept_when_caller_requests_resummary(monkeypatch):
    content = LEAD + "公交服务设施" * 220 + "仍需按原计划逐步完成。"
    monkeypatch.setattr(llm, "init_chat_model", lambda *args, **kwargs: SimpleNamespace(
        invoke=lambda messages: SimpleNamespace(content=json.dumps(draft(content), ensure_ascii=False),
                                                response_metadata={"finish_reason": "stop"}, usage_metadata={})
    ))
    result = llm.generate_draft(LLMConfig("fake", "test", provider="fake"),
                                title_hint="每日新闻", prompt_hint="已提供原始材料",
                                asset_paths=[], preserve_body=True)
    assert result["body"] == article(content)

def test_preserved_comment_does_not_discard_an_unfinished_tail():
    comment = COMMENT + "公交司机轮班安排仍需"
    result = w._finalize_daily_news_body(article(SHORT, comment), source(), "公交", preserve_length=True)
    assert w._daily_news_body_quality_fields(result)["评价"] == comment


def test_complete_comment_missing_period_is_punctuated_without_model_call(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [draft(SHORT, COMMENT.rstrip("。"))])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 1
    assert w._daily_news_body_quality_fields(result.post.body)["评价"] == COMMENT


def test_legacy_date_metadata_is_not_counted_as_comment():
    candidate = {"body": f"内容：\n{SHORT}\n\n评价：\n{COMMENT}\n\n发布时间：2026-10-03 08:00:00"}
    assert w._review_daily_news_length(candidate, source()) == ""
    assert candidate["_length_review"]["comment_chars"] == len(COMMENT)


def test_prompt_uses_new_targets_without_changing_daily_wow():
    prompt = w._daily_news_prompt(source(), "公交")
    assert "150–220" in prompt
    assert "20–40" in prompt
    assert "220-350" not in prompt
    wow_prompt = w._daily_news_prompt(source(), "公交", column=w.DAILY_WOW_CONTENT_TYPE)
    assert "220-350" in wow_prompt
    assert "concise-news" not in wow_prompt


def test_complexity_with_real_evidence_allows_bounded_extension(monkeypatch):
    content = LEAD + "".join(DETAILS[:7])
    assert 220 < len(content) <= 300
    result, calls, _ = run_candidate(monkeypatch, [draft(
        content, complexity="complex",
        complexity_reason="需交代资金来源、司机轮班及试行评估三个执行环节",
        complexity_evidence=["司机轮班需要协商", "现有交通专项资金承担试行支出"],
    )])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 1
    assert result.post.platform["news"]["length_review"]["content_limit"] == 300


def test_unknown_complexity_cannot_skip_resummary(monkeypatch):
    content = LEAD + "".join(DETAILS[:7])
    result, calls, _ = run_candidate(monkeypatch, [
        draft(content, complexity="complex", complexity_reason="原文很长", complexity_evidence=["虚构依据"]),
        draft(SHORT),
    ])
    assert result.status == "success", (result.reason, result.draft)
    assert len(calls) == 2

def test_length_audit_excludes_labels_dates_and_sources():
    candidate = draft(SHORT)
    assert w._review_daily_news_length(candidate, source()) == ""
    assert candidate["_length_review"]["content_chars"] == len(SHORT)
    assert candidate["_length_review"]["comment_chars"] == len(COMMENT)


def test_second_overlong_copy_never_starts_image_generation(monkeypatch):
    monkeypatch.setattr(w, "_fetch_daily_news_related_images",
                        lambda *a, **kw: pytest.fail("rejected copy must not generate an image"))
    result, calls, _ = run_candidate(monkeypatch, [draft(LONG), draft(LONG)], auto_image_enabled=True)
    assert result.status == "skipped"
    assert len(calls) == 2


def test_failed_resummary_keeps_original_copy_without_third_call(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [
        draft(LONG), {"_fallback_error": "simulated model unavailable"},
    ])
    assert result.status in {"skipped", "failed"}
    assert len(calls) == 2
    assert w._daily_news_body_quality_fields(result.draft["body"])["内容"] == LONG


def test_initial_candidate_enables_concise_writer_before_first_request(monkeypatch):
    result, calls, _ = run_candidate(monkeypatch, [draft(SHORT)])
    assert result.status == "success"
    assert calls[0].get("concise_news") is True
    assert "180–200字" in calls[0]["prompt_hint"]
    assert "25–30字" in calls[0]["prompt_hint"]


def test_daily_wow_does_not_enable_concise_news_writer(monkeypatch):
    _, calls, _ = run_candidate(monkeypatch, [draft(SHORT)], column=w.DAILY_WOW_CONTENT_TYPE)
    assert calls and not calls[0].get("concise_news", False)
    assert "180–200字" not in calls[0]["prompt_hint"]


def test_length_resummary_uses_same_front_loaded_writer_policy(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "generate_draft", lambda *a, **kw: (calls.append(kw) or draft(SHORT)))
    _, issue = w._resummarize_daily_news_length_once(
        draft(LONG), cfgs=[LLMConfig("fake", "test", provider="fake")],
        picked=source(), prompt_norm="公交", news_prompt=w._daily_news_prompt(source(), "公交"), asset_paths=[],
    )
    assert not issue
    assert len(calls) == 1 and calls[0].get("concise_news") is True


def test_single_post_enables_concise_writer_at_actual_request_boundary(monkeypatch):
    requests = []
    cfg = LLMConfig("fake", "test", provider="fake")
    scene = LEAD + "市交通局公布公交夜间班次调整方案的概念示意，以非写实侧影表达计划立场，背景为纯色色面，所有物面留白。"

    def invoke(messages):
        requests.append(messages)
        return SimpleNamespace(content=json.dumps(draft(SHORT, image_event=scene), ensure_ascii=False),
                               response_metadata={"finish_reason": "stop"}, usage_metadata={})

    monkeypatch.setattr(llm, "init_chat_model", lambda *a, **kw: SimpleNamespace(invoke=invoke))
    monkeypatch.setattr(w, "load_llm_configs", lambda: [cfg])
    monkeypatch.setattr(w, "_fetch_daily_news_candidates_for_upload", lambda *a, **kw: ([source()], {}))
    monkeypatch.setattr(w, "_enrich_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(w, "_focus_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(w, "save_post", lambda post: None)
    monkeypatch.setattr(w, "save_revision", lambda revision: None)
    post = w.create_post_with_draft(
        title_hint="每日新闻", prompt_hint="公交", asset_paths=[], copy_assets=False, auto_image=False,
    )
    assert post.platform["news"]["length_review"]["rewrite_count"] == 0
    assert len(requests) == 1
    system, user = (str(message.content) for message in requests[0])
    for text in (system, user):
        assert "180–200字" in text and "25–30字" in text
        assert "150–220字" in text and "20–40字" in text
    assert "Body <= 1000" not in system
    assert "at least 200" not in system
    assert "expand it" not in system
    assert "<= 900" not in user


def test_concise_writer_keeps_full_overlong_response_for_rejection(monkeypatch):
    content = LEAD + "公交服务设施" * 220 + "仍需按原计划逐步完成。"
    monkeypatch.setattr(llm, "init_chat_model", lambda *a, **kw: SimpleNamespace(
        invoke=lambda messages: SimpleNamespace(content=json.dumps(draft(content), ensure_ascii=False),
                                                response_metadata={"finish_reason": "stop"}, usage_metadata={})
    ))
    result = llm.generate_draft(LLMConfig("fake", "test", provider="fake"),
                                title_hint="每日新闻", prompt_hint="已提供原始材料", asset_paths=[],
                                concise_news=True)
    assert result["body"] == article(content)
    assert w._review_daily_news_length(result, source(content)) == "content_too_long"
