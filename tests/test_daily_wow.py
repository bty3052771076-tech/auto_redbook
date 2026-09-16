import json
import re
from dataclasses import replace

import pytest

from src.config import LLMConfig
from src.news import daily_wow
from src.news.daily_news import NewsItem
from src.workflow import create_post
from src.workflow.news_discovery import DailyNewsDiscovery

# 2026-09-15（周三）在栏目的 1/2/3/5 天窗口内，保证日期门禁通过。
WOW_DATE = "2026-09-15"


def _wow_item(index: int, *, title: str, description: str, domain: str = "example.com"):
    return NewsItem(
        title=title,
        url=f"https://{domain}/wow-{index}",
        source=domain.split(".")[0],
        domain=domain,
        seendate=WOW_DATE,
        description=description,
        content=description,
    )


def _wow_body(content: str, comment: str) -> str:
    return (
        f"内容：\n{content}\n\n"
        f"评价：\n{comment}\n\n"
        f"日期：{WOW_DATE}\n\n"
        "来源：example.com"
    )


def test_query_groups_put_user_keywords_first_and_stay_distinct():
    queries = daily_wow.daily_wow_queries("马拉松 失禁 夺冠")

    assert queries[0] == "马拉松 失禁 夺冠"
    assert len(queries) == len(set(queries))
    assert any("赛事意外" in query for query in queries)


def test_eligible_requires_a_contrast_signal_or_user_keyword():
    contrast = _wow_item(1, title="选手意外夺冠", description="赛事出现意外结果。")
    ordinary = _wow_item(2, title="公司发布季度财报", description="营收同比增长。")

    assert daily_wow.daily_wow_eligible(contrast) is True
    assert daily_wow.daily_wow_eligible(ordinary) is False
    assert daily_wow.daily_wow_eligible(ordinary, "公司财报") is True


def test_candidate_pool_keeps_date_valid_items_for_model_and_drops_only_fiction():
    items = [
        _wow_item(1, title="选手意外夺冠", description="赛事出现意外结果。"),
        _wow_item(2, title="公司发布季度财报", description="营收同比增长。"),
        _wow_item(3, title="洋葱新闻：编造事件", description="纯属虚构，仅供娱乐。"),
    ]

    kept, meta = daily_wow.daily_wow_candidate_pool(items, "")

    # The model judges contrast from evidence, so an ordinary-looking headline
    # stays available instead of being deleted before it can be reviewed.
    assert [item.title for item in kept] == ["选手意外夺冠", "公司发布季度财报"]
    assert meta["column"] == "daily_wow"
    assert meta["input_count"] == 3
    assert meta["pool_count"] == 2
    assert meta["hard_reject_count"] == 1


def test_offline_strict_fallback_requires_a_contrast_signal():
    items = [
        _wow_item(1, title="选手意外夺冠", description="赛事出现意外结果。"),
        _wow_item(2, title="公司发布季度财报", description="营收同比增长。"),
    ]

    strict, meta = daily_wow.daily_wow_strict_candidates(items, "")

    assert [item.title for item in strict] == ["选手意外夺冠"]
    assert meta["mode"] == "offline_strict"
    assert meta["strict_count"] == 1


def test_comment_rules_allow_one_mild_profanity_and_block_short_or_fabricated():
    assert daily_wow.daily_wow_comment_is_valid("退钱还得先交钱，真他妈会做生意") is True
    assert daily_wow.daily_wow_comment_is_valid("订阅一键直达，退订像在考古") is True
    assert daily_wow.daily_wow_comment_is_valid("真离谱") is False
    assert daily_wow.daily_wow_comment_is_valid("卧槽卧槽，这也太离谱了吧") is False
    assert daily_wow.daily_wow_comment_is_valid("裁判当场吓傻了") is False


def test_image_prompt_keeps_style_and_forbids_disgusting_detail():
    prompt = daily_wow.daily_wow_image_prompt(
        image_event="选手完赛后登上领奖台",
        contrast="比赛中出现突发状况，选手仍夺冠",
        visual_plan="领奖台旁立着一本困惑的巨型规则册",
        comment="跑完全程还拿冠军，我去，这体能。",
    )

    assert "竖版3:4" in prompt
    assert "领奖台" in prompt
    assert "排泄物" in prompt
    assert "不要文字" in prompt


def test_selection_prompt_covers_every_id_and_forbids_invention():
    prompt = daily_wow.daily_wow_selection_system_prompt(2)

    assert "accept" in prompt and "needs_evidence" in prompt and "reject" in prompt
    assert "恰好出现一次" in prompt
    assert "不补充材料之外的事实" in prompt


def test_discovery_uses_wow_column_quotas_and_queries(monkeypatch):
    captured: dict[str, object] = {}
    items = [
        _wow_item(1, title="选手意外夺冠", description="赛事出现意外结果。"),
        _wow_item(2, title="机构乌龙处罚", description="处罚决定出现乌龙后撤销。"),
        _wow_item(3, title="公司发布季度财报", description="营收同比增长。"),
    ]

    def fake_fetch(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["additional_queries"] = kwargs.get("additional_queries")
        return items, {"provider": "fake"}

    def fake_prepare(pending, **kwargs):
        return {index: (item, {}, {}, item) for index, item in enumerate(pending, 1)}

    discovery = DailyNewsDiscovery(
        prompt="",
        count=2,
        windows=[3],
        window_meta={"mode": "fixed"},
        raw_target=40,
        preferred_target=20,
        budget_seconds=5.0,
        fetch=fake_fetch,
        prepare=fake_prepare,
        incomplete=lambda _item: False,
        column="daily_wow",
    )

    picks = discovery.take(initial=True)

    assert discovery.china == 0
    assert discovery.conflict == 0
    assert discovery.column == "daily_wow"
    queries = [str(query) for query in (captured["additional_queries"] or [])]
    assert any("赛事意外" in query for query in queries)
    # Contrast-ranked items lead; the remaining date-valid item stays as reserve.
    assert [item.title for item in picks[:2]] == ["选手意外夺冠", "机构乌龙处罚"]
    assert "公司发布季度财报" in [item.title for item in picks]


def test_wow_column_requests_the_odd_news_supply(monkeypatch):
    """The column must ask for its own odd-news feed, not only generic RSS."""
    captured: dict[str, object] = {}
    items = [_wow_item(1, title="村里禁用了滚轮垃圾桶", description="一只垃圾桶滚走撞车后，整条街被禁用。")]

    def fake_fetch(prompt, **kwargs):
        captured.update(kwargs)
        return items, {"provider": "fake"}

    def fake_prepare(pending, **kwargs):
        return {index: (item, {}, {}, item) for index, item in enumerate(pending, 1)}

    discovery = DailyNewsDiscovery(
        prompt="",
        count=1,
        windows=[3],
        window_meta={"mode": "fixed"},
        raw_target=20,
        preferred_target=10,
        budget_seconds=5.0,
        fetch=fake_fetch,
        prepare=fake_prepare,
        incomplete=lambda _item: False,
        column="daily_wow",
    )
    discovery.take(initial=True)

    assert "odd_news_rss" in tuple(captured.get("preferred_providers") or ())


def test_ordinary_news_does_not_request_the_odd_news_supply(monkeypatch):
    captured: dict[str, object] = {}
    items = [_wow_item(1, title="公司发布季度财报", description="营收同比增长。")]

    def fake_fetch(prompt, **kwargs):
        captured.update(kwargs)
        return items, {"provider": "fake"}

    def fake_prepare(pending, **kwargs):
        return {index: (item, {}, {}, item) for index, item in enumerate(pending, 1)}

    discovery = DailyNewsDiscovery(
        prompt="财经产业",
        count=1,
        windows=[3],
        window_meta={"mode": "fixed"},
        raw_target=20,
        preferred_target=10,
        budget_seconds=5.0,
        fetch=fake_fetch,
        prepare=fake_prepare,
        incomplete=lambda _item: False,
    )
    discovery.take(initial=True)

    assert tuple(captured.get("preferred_providers") or ()) == ()


def test_odd_beat_source_outranks_generic_headline():
    """The column's own odd-news beat should lead, since supply is scarce."""
    odd = _wow_item(1, title="Mint coin marks UFO sighting", description="A coin marks a local legend.")
    odd = replace(odd, provider="odd_news_rss")
    generic = _wow_item(2, title="Treasury publishes quarterly report", description="The report covers the quarter.")
    generic = replace(generic, provider="bbc_rss")

    assert daily_wow.daily_wow_score(odd, "") > daily_wow.daily_wow_score(generic, "")

    pool, _meta = daily_wow.daily_wow_candidate_pool([generic, odd], "")
    assert [item.title for item in pool][0] == "Mint coin marks UFO sighting"


def test_create_daily_wow_posts_skips_quota_and_uses_wow_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    candidate = _wow_item(
        1,
        title="选手突发状况仍夺冠，赛事方回应规则争议",
        description="比赛中选手出现突发状况仍然完赛夺冠，赛后赛事规则引发讨论。",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([candidate], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(create_post, "_focus_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(create_post, "_daily_news_context_is_incomplete", lambda _item: False)
    captured: dict[str, str] = {}

    def fake_generate_draft(*_args, **_kwargs):
        captured["prompt"] = str(_kwargs.get("prompt_hint") or "")
        return {
            "title": "选手突发状况仍夺冠",
            "body": _wow_body(
                "比赛中选手出现突发状况，仍然完成全部赛程并拿到冠军，赛后赛事规则引发讨论。",
                "跑完全程还拿冠军，我去，这体能。",
            ),
            "topics": ["每日我去"],
            "image_event": "选手完赛后站在领奖台上",
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="",
        asset_paths=[],
        count=1,
        auto_image=False,
        column="daily_wow",
    )

    post = posts[0]
    assert post.platform["news"]["content_type"] == "daily_wow"
    assert post.platform["news"]["column"] == "daily_wow"
    assert post.platform["news"]["image_policy"] == "ai_required"
    assert "每日我去" in post.topics
    assert "每日我去" in captured["prompt"]
    assert "评价风格" in captured["prompt"]
    assert "原文标题" not in post.body
    assert "跑完全程还拿冠军" in post.body


def test_wow_comment_with_fabricated_reaction_is_replaced(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    candidate = _wow_item(
        1,
        title="机构乌龙处罚后被撤销",
        description="处罚决定出现乌龙，被上级机构撤销并向当事人致歉。",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([candidate], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(create_post, "_focus_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(create_post, "_daily_news_context_is_incomplete", lambda _item: False)
    monkeypatch.setattr(
        create_post,
        "generate_draft",
        lambda *_args, **_kwargs: {
            "title": "机构乌龙处罚被撤销",
            "body": _wow_body(
                "处罚决定出现乌龙，被上级机构撤销并向当事人致歉。",
                "官方连夜认怂，后台关系很硬。",
            ),
            "topics": ["每日我去"],
            "image_event": "机构办公室内的处罚文件被撤回",
        },
    )

    posts = create_post.create_daily_news_posts(
        prompt_hint="",
        asset_paths=[],
        count=1,
        auto_image=False,
        column="daily_wow",
    )

    body = posts[0].body
    assert "连夜" not in body
    assert "后台关系很硬" not in body
    assert "评价：" in body


def test_wow_body_without_usable_comment_fails_quality_gate():
    issue = create_post._daily_wow_quality_issue(
        "机构乌龙处罚被撤销",
        _wow_body("处罚决定出现乌龙，被上级机构撤销并向当事人致歉。", "真离谱"),
    )

    assert issue == "wow_comment_unusable"


def test_image_event_strips_model_narration_and_json_leak():
    raw = '内罗毕赢得2029年世界田径锦标赛主办权，伦敦落选" } Let me check'

    cleaned = daily_wow.daily_wow_clean_image_event(raw)

    assert "Let me" not in cleaned
    assert "}" not in cleaned
    assert cleaned.startswith("内罗毕赢得2029年世界田径锦标赛主办权")


def test_column_keeps_the_full_platform_title_budget():
    full_title = "内罗毕击败伦敦获2029田径世锦赛主办权"

    normalized = create_post._normalize_daily_news_title(
        full_title, None, "", max_len=daily_wow.daily_wow_title_max_len()
    )

    assert len(full_title) <= daily_wow.daily_wow_title_max_len()
    assert normalized == full_title
    assert not normalized.endswith("主")


def test_rejected_candidates_never_fall_back_to_ordinary_ranking(monkeypatch):
    """A judge that rejects everything must shortfall instead of publishing noise."""
    monkeypatch.setattr(
        create_post,
        "_daily_news_llm_supervisor_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        create_post,
        "generate_json",
        lambda *a, **k: {"decisions": [], "reason": "无可用的真实反差事件"},
    )
    ordinary = [
        _wow_item(1, title="公司发布季度财报", description="营收同比增长。"),
        _wow_item(2, title="球队夏季完成引援", description="俱乐部公布新赛季阵容。"),
    ]
    cfgs = [LLMConfig(model="real-model", api_key="k", base_url="https://example.com")]

    kept, meta = create_post._supervise_daily_news_candidates(
        ordinary,
        cfgs=cfgs,
        prompt_hint="",
        target_count=1,
        required_china_count=0,
        progress_callback=None,
        column="daily_wow",
    )

    assert kept == []
    assert meta["status"] == "offline_strict_after_review_failure"


def test_draft_generator_carries_column_extras():
    from src.llm.generate import generate_draft

    monkeypatch_free = {
        "title": "机构乌龙处罚被撤销",
        "body": _wow_body("处罚决定出现乌龙，被上级机构撤销并向当事人致歉。", "退钱还得先交钱"),
        "topics": ["每日我去"],
        "image_event": "机构办公室内一份处罚文件被撤回",
        "verified_contrast": "处罚作出后被同一机构撤销",
        "visual_plan": {"subject": "办公桌", "props": "被撤回的处罚文件", "composition": "居中", "contrast": "文件与撤销章", "avoid": []},
    }

    # The shared parser must not silently drop these keys.
    from src.llm import generate as generate_mod

    parsed = generate_mod._parse_json_text(json.dumps(monkeypatch_free, ensure_ascii=False))

    assert parsed is not None
    assert parsed["visual_plan"]["subject"] == "办公桌"
    assert parsed["verified_contrast"] == "处罚作出后被同一机构撤销"


def test_parser_survives_model_narration_and_raw_newlines():
    """MiniMax-M3 narrates before its JSON and emits real newlines in strings."""
    from src.llm.generate import _parse_json_text

    noisy = (
        "Let me check the character count of body.\n"
        'I will consider {"note":"intermediate"} before answering.\n\n'
        '{"title":"少年篮球赛滑倒闯入全美搞笑三强",'
        '"body":"内容：\n比赛出现球员滑倒。\n\n评价：球没打赢。",'
        '"topics":["每日我去"],"image_event":"篮球场上少年滑倒"}'
    )

    parsed = _parse_json_text(noisy)

    assert parsed is not None
    assert parsed["title"] == "少年篮球赛滑倒闯入全美搞笑三强"
    assert parsed["body"].startswith("内容：")
    assert "评分" not in parsed["body"]
    assert '"topics"' not in parsed["body"]
    assert parsed["image_event"] == "篮球场上少年滑倒"


def test_low_contrast_accept_is_not_published():
    """A judge that accepts its own '荒诞性一般' item must not publish it."""
    result = {
        "decisions": [
            {
                "id": 1,
                "decision": "accept",
                "contrast": "国脚撞护栏并认罪",
                "score": 2,
                "reason": "荒诞性一般",
            }
        ],
        "reason": "ok",
    }

    accepted, rejected, decisions = create_post._daily_wow_decisions_from_result(
        result, pool_size=1
    )

    assert accepted == []
    assert rejected == [1]
    assert decisions[0]["below_contrast_floor"] is True


def test_high_contrast_accept_is_honoured():
    result = {
        "decisions": [
            {"id": 1, "decision": "accept", "contrast": "整条街被禁用垃圾桶", "score": 4}
        ]
    }

    accepted, rejected, _decisions = create_post._daily_wow_decisions_from_result(
        result, pool_size=1
    )

    assert accepted == [1]
    assert rejected == []


def test_placeholder_contrast_values_are_treated_as_absent():
    for value in ("无", "None", "n/a", "  无。 "):
        assert daily_wow.daily_wow_clean_image_event(value) == ""


def test_schema_echo_accept_is_rejected():
    """A model that echoes the prompt's example did not judge the story."""
    result = {
        "decisions": [
            {
                "id": 1,
                "decision": "accept",
                "contrast": "不超过60字的可检查反差点",
                "score": 3,
            }
        ]
    }

    accepted, rejected, decisions = create_post._daily_wow_decisions_from_result(
        result, pool_size=1
    )

    assert accepted == []
    assert rejected == [1]
    assert decisions[0]["schema_echo"] is True


def test_generic_news_voice_comment_is_not_accepted():
    generic = "围绕社会事件出现进展的实际影响，仍需结合后续公开的执行细节和可核验反馈判断。"
    playful = "球没打赢，跤摔进了全美决赛三强。"

    assert daily_wow.daily_wow_comment_is_valid(generic) is False
    assert daily_wow.daily_wow_comment_is_valid(playful) is True


def test_conflict_and_disaster_stories_are_hard_rejected():
    """Military confrontation is ordinary news, not this column's material."""
    conflict = NewsItem(
        title="Denmark says Russian warship fired flares at military helicopter",
        url="https://example.com/conflict",
        source="BBC World",
        domain="bbc.co.uk",
        seendate=WOW_DATE,
        description="Nato member Denmark summoned the Russian ambassador after the incident.",
        content="A Russian warship fired flares at a Danish military helicopter in the Baltic Sea.",
        sourcecountry="Denmark",
    )
    absurd = _wow_item(9, title="村子禁用了滚轮垃圾桶", description="一只垃圾桶滚走撞车后，整条街被禁用。")

    assert daily_wow.daily_wow_is_hard_reject(conflict) is True
    assert daily_wow.daily_wow_is_hard_reject(absurd) is False

    kept, meta = daily_wow.daily_wow_candidate_pool([conflict, absurd], "")
    assert [item.title for item in kept] == ["村子禁用了滚轮垃圾桶"]
    assert meta["hard_reject_count"] == 1


def test_serious_crime_and_casualty_stories_are_hard_rejected():
    sabotage = _wow_item(
        11,
        title="铁路疑遭蓄意破坏，全国列车大面积停运",
        description="多条轨道被人放置管道和电缆，警方已启动刑事调查。",
    )
    silly = _wow_item(
        12,
        title="村子禁用了滚轮垃圾桶",
        description="一只垃圾桶滚走撞车后，整条街被禁用。",
    )

    assert daily_wow.daily_wow_is_hard_reject(sabotage) is True
    assert daily_wow.daily_wow_is_hard_reject(silly) is False


def test_comment_rejects_english_leak_and_fallback_avoids_it():
    leaked = "就这结果，Suspected sabotage cause，挺行。"

    assert daily_wow.daily_wow_comment_is_valid(leaked) is False

    english_item = NewsItem(
        title="Suspected sabotage causes major Netherlands rail disruption",
        url="https://example.com/en",
        source="BBC World",
        domain="bbc.co.uk",
        seendate=WOW_DATE,
        description="Rail services were disrupted across the country.",
    )
    fallback = daily_wow.daily_wow_fallback_comment(english_item, "Rail services were disrupted.")

    assert re.search(r"[\u4e00-\u9fff]", fallback)
    assert not re.search(r"[A-Za-z]{3,}", fallback)
    assert daily_wow.daily_wow_comment_is_valid(fallback)


def test_political_statement_is_hard_rejected_but_absurd_official_case_is_kept():
    statement = _wow_item(
        21,
        title="Trump says AI safety fears a 'hoax' as he rejects calls for greater safeguards",
        description="The president rejected calls for new AI rules.",
    )
    scandal = _wow_item(
        22,
        title="Colombian ex-foreign minister charged over nanny's lie detector test",
        description="A former foreign minister is charged after a lie detector test over a missing watch.",
    )

    assert daily_wow.daily_wow_is_political_statement(statement) is True
    assert daily_wow.daily_wow_is_hard_reject(statement) is True
    # A real event involving an official must survive the narrow guard.
    assert daily_wow.daily_wow_is_political_statement(scandal) is False
