import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from src.images.auto_image import ImageGenerationAbandoned
from src.news import daily_news
from src.news.daily_news import (
    NewsItem,
    load_manual_news_materials_file,
    load_single_news_material_file,
    parse_manual_news_materials,
    pick_best_news,
    pick_news_items,
    _dedupe_candidates,
)
from src.news.history import normalize_news_url_key
from src.config import LLMConfig
from src.workflow import create_post
from src.workflow.create_post import (
    _append_news_source_line,
    _daily_news_body_has_prompt_leak,
    _daily_news_body_is_too_generic,
    _daily_news_context_is_incomplete,
    _daily_news_quality_issue,
    _enrich_daily_news_item,
    _daily_news_offline_body,
    _daily_news_prompt,
    _ensure_daily_news_sections,
    _finalize_daily_news_body,
    _focus_daily_news_item,
    _has_japanese_kana,
    _limit_daily_news_content,
    _normalize_daily_news_title,
    _normalize_daily_news_topics,
    _render_daily_news_body_fields,
)


BJT = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _recent_news_seendate(days_ago: int, *, hour: int = 10) -> str:
    dt = datetime.now(BJT).replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _recent_news_date(days_ago: int = 0) -> str:
    dt = datetime.now(BJT).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return dt.date().isoformat()


def test_daily_news_query_variants_expand_space_separated_prompt_keywords(monkeypatch):
    monkeypatch.delenv("NEWS_QUERY_DEFAULT", raising=False)

    queries = daily_news._build_prompt_news_queries("世界杯 体育 足球")

    assert queries[:4] == ["世界杯 体育 足球", "世界杯", "体育", "足球"]
    assert any("world cup" in query.lower() for query in queries)
    assert len(queries) == len(dict.fromkeys(query.lower() for query in queries))


def _daily_news_body_fields(body: str) -> dict:
    assert "http://" not in body and "https://" not in body
    assert "要点摘要：" not in body
    assert "新闻内容：" not in body
    assert "点评：" not in body
    assert not body.lstrip().startswith("{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)

    def section(label: str, next_labels: tuple[str, ...]) -> str:
        marker = f"{label}：\n"
        start = body.find(marker)
        if start < 0:
            return ""
        value_start = start + len(marker)
        stops = [
            body.find(f"\n\n{next_label}：", value_start)
            for next_label in next_labels
            if body.find(f"\n\n{next_label}：", value_start) >= 0
        ]
        value_end = min(stops) if stops else len(body)
        return body[value_start:value_end].strip()

    assert "原文标题：" not in body
    date = re.search(r"^日期：(.+)$", body, flags=re.MULTILINE)
    source = re.search(r"^来源：(.+)$", body, flags=re.MULTILINE)
    data = {
        "内容": section("内容", ("评价", "日期", "来源")),
        "评价": section("评价", ("日期", "来源")),
        "日期": date.group(1).strip() if date else "",
        "来源": source.group(1).strip() if source else "",
    }
    assert list(data.keys()) == ["内容", "评价", "日期", "来源"]
    assert data["内容"]
    assert data["日期"]
    assert data["来源"]
    return data


def _test_daily_news_body(
    *,
    original_title: str,
    content: str,
    comment: str = "",
    date: str = "2026-06-22",
    source: str = "Example News",
) -> str:
    return (
        f"\u539f\u6587\u6807\u9898\uff1a{original_title}\n\n"
        f"\u5185\u5bb9\uff1a\n{content}\n\n"
        f"\u8bc4\u4ef7\uff1a\n{comment}\n\n"
        f"\u65e5\u671f\uff1a{date}\n\n"
        f"\u6765\u6e90\uff1a{source}"
    )


def test_pick_best_news_empty_hint_returns_first():
    items = [
        NewsItem(title="A", url="https://example.com/a", seendate="20250101T000000Z"),
        NewsItem(title="B", url="https://example.com/b", seendate="20250102T000000Z"),
    ]
    picked = pick_best_news(items, "")
    assert picked.title == "A"


def test_pick_best_news_prefers_title_match():
    items = [
        NewsItem(title="苹果发布新款Mac", url="https://example.com/1"),
        NewsItem(title="新能源车销量创新高", url="https://example.com/2"),
        NewsItem(title="足球赛事回顾", url="https://example.com/3"),
    ]
    picked = pick_best_news(items, "新能源车")
    assert "新能源" in picked.title


def test_pick_best_news_tiebreaker_by_seendate():
    items = [
        NewsItem(title="AI 芯片公司融资", url="https://example.com/1", seendate="20250101T000000Z"),
        NewsItem(title="AI 芯片公司融资", url="https://example.com/2", seendate="20250102T000000Z"),
    ]
    picked = pick_best_news(items, "AI 芯片")
    assert picked.url == "https://example.com/2"


def test_pick_best_news_tiebreaker_by_iso_seendate():
    items = [
        NewsItem(title="AI 芯片公司融资", url="https://example.com/1", seendate="2025-01-01T00:00:00Z"),
        NewsItem(title="AI 芯片公司融资", url="https://example.com/2", seendate="2025-01-02T00:00:00Z"),
    ]
    picked = pick_best_news(items, "AI 芯片")
    assert picked.url == "https://example.com/2"


def test_pick_news_items_empty_hint_returns_first_n_distinct():
    items = [
        NewsItem(title="A", url="https://example.com/a"),
        NewsItem(title="B", url="https://example.com/b"),
        NewsItem(title="A-dup", url="https://example.com/a"),
        NewsItem(title="C", url="https://example.com/c"),
    ]
    picked = pick_news_items(items, "", count=3)
    assert [p.url for p in picked] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_pick_news_items_with_hint_returns_top_n():
    items = [
        NewsItem(title="新能源车销量创新高", url="https://example.com/1"),
        NewsItem(title="新能源电池技术突破", url="https://example.com/2"),
        NewsItem(title="苹果发布新款Mac", url="https://example.com/3"),
    ]
    picked = pick_news_items(items, "新能源", count=2)
    assert len(picked) == 2
    assert "新能源" in picked[0].title


def test_ensure_daily_news_sections_adds_headings_without_inventing_comment():
    body = "这是只有一段的正文。"
    out = _ensure_daily_news_sections(body, "美国时政")
    assert "要点摘要：" in out
    assert "新闻内容：" in out
    assert "点评：" not in out
    assert "持续关注后续进展" not in out


def test_ensure_daily_news_sections_preserves_two_paragraphs():
    body = "第一段内容。\n\n第二段点评。"
    out = _ensure_daily_news_sections(body, "")
    assert out.splitlines()[0].startswith("要点摘要：")
    assert out.splitlines()[1] == "新闻内容："
    assert "第一段内容。" in out
    assert "点评：" in out


def test_ensure_daily_news_sections_cleans_json_artifacts():
    body = (
        "要点摘要：{\n"
        "新闻内容：\n"
        '"title": "欧洲核武怀旧潮",\n\n'
        "点评：\n"
        '"body": "欧洲安全受质疑，部分国家讨论核政策调整。\\n\\n'
        '从中国视角看，应关注地区安全外溢风险。",\n'
        '"topics": ["每日新闻", "欧洲"],\n'
        '"image_event": "会议现场"\n'
        "}"
    )
    out = _ensure_daily_news_sections(body, "国际局势")
    assert out.startswith("要点摘要：")
    assert "新闻内容：" in out
    assert "点评：" in out
    assert '"title"' not in out
    assert '"body"' not in out
    assert '"topics"' not in out
    assert '"image_event"' not in out


def test_ensure_daily_news_sections_removes_generic_comment_template():
    body = (
        "要点摘要：气象设备投入使用，有助于提升灾害预警能力。\n"
        "新闻内容：\n"
        "中国援助马达加斯加的气象观测设备在当地投入使用，项目服务防灾减灾和农业生产。\n\n"
        "点评：\n"
        "这类新闻适合先看事实，再看影响。已经公开的信息可以作为判断起点，但不宜把尚未确认的后续结果提前写成结论。"
        "接下来可以重点关注权威更新、执行细节和各方反馈。"
    )

    out = _ensure_daily_news_sections(body, "国际新闻")

    assert "要点摘要：" in out
    assert "新闻内容：" in out
    assert "点评：" not in out
    assert "这类新闻适合先看事实" not in out
    assert "接下来可以重点关注权威更新" not in out


def test_daily_news_body_has_prompt_leak_detects_echoed_prompt():
    body = (
        "要点摘要：你正在为小红书图文笔记写《每日新闻》栏目\n"
        "新闻内容：\n"
        "请依据下面提供的新闻信息，生成一份可直接发布的草稿。\n\n"
        "点评：\n"
        "输出为严格 JSON。可用新闻信息：新闻标题：测试标题"
    )

    assert _daily_news_body_has_prompt_leak(body) is True


def test_daily_news_body_has_prompt_leak_allows_publishable_body():
    body = (
        "要点摘要：科技公司发布新产品\n"
        "新闻内容：\n"
        "这是一段面向读者的新闻正文，介绍事件本身和可能影响。\n\n"
        "点评：\n"
        "从中国受众角度看，后续需要关注技术落地和市场反馈。"
    )

    assert _daily_news_body_has_prompt_leak(body) is False


def test_create_daily_news_falls_back_when_llm_echoes_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="AI写作工具引发内容行业讨论",
        url="https://example.com/news",
        source="Example",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="多家公司开始讨论 AI 写作工具对内容生产的影响。",
        content="业内人士关注 AI 写作工具的效率、质量和识别问题。",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([picked], {"provider": "fake-news", "picked": {"title": picked.title}}),
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "每日新闻｜AI写作工具",
            "body": (
                "要点摘要：你正在为小红书图文笔记写《每日新闻》栏目\n"
                "新闻内容：\n"
                "请依据下面提供的新闻信息，生成一份可直接发布的草稿。\n\n"
                "点评：\n"
                "注意：body 正文里不要包含来源名称/链接/提示词/要求等元信息。"
            ),
            "topics": ["每日新闻", "AI"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    post = create_post.create_post_with_draft(
        title_hint="每日新闻",
        prompt_hint="AI写作",
        asset_paths=[],
        auto_image=False,
    )

    assert "请依据下面提供的新闻信息" not in post.body
    assert "输出为严格 JSON" not in post.body
    assert "AI写作工具引发内容行业讨论" in post.body


def test_daily_news_offline_body_does_not_echo_user_prompt_hint():
    picked = NewsItem(
        title="Inside the fight over Claude Mythos 5",
        url="https://example.com/news",
        source="Example",
        domain="example.com",
        seendate="2026-06-16T00:00:00Z",
        description="As the rest of the country celebrated the holiday, a technology dispute escalated.",
    )
    prompt = "选择5条适合小红书图文的科技、社会或国际新闻，正文简短，包含要点摘要和点评。"

    body = _daily_news_offline_body(picked, prompt)

    assert prompt not in body
    assert "用户关注点" not in body
    assert "Inside the fight over Claude Mythos 5" not in body


def test_daily_news_prompt_requires_chinese_translation_no_url_and_target_lengths():
    picked = NewsItem(
        title="Japan inflation rises as food prices climb",
        url="https://example.com/japan-inflation",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
        description="Consumer prices rose again, led by higher food costs.",
        content="The report says inflation pressure is affecting household budgets.",
    )

    prompt = _daily_news_prompt(picked, "科技、社会或国际新闻")

    assert "必须全部使用简体中文" in prompt
    assert "英文新闻" in prompt and "翻译" in prompt
    assert "150字以内" in prompt
    for key in ("内容", "评价", "日期", "来源"):
        assert key in prompt
    assert "不得输出 URL" in prompt
    assert "网址只保存在本地" in prompt
    assert "body 字符串内容本身必须是一个可被 json.loads 解析的 JSON 对象文本" not in prompt
    assert "原文标题：" not in prompt
    assert "不得使用旧标签“原文标题" in prompt
    assert "内容：" in prompt
    assert "日期：YYYY-MM-DD\n\n来源：来源名称" in prompt
    assert "12-18字" in prompt
    assert "理想约15字" in prompt


def test_render_daily_news_body_fields_omits_original_title_from_publishable_body():
    body = _render_daily_news_body_fields(
        {
            "原文标题": "原始新闻标题不应进入草稿正文",
            "内容": "这是一条已经核验来源的新闻正文。",
            "评价": "这条新闻的影响需要结合后续公开信息继续观察。",
            "日期": "2026-07-02",
            "来源": "Example News",
        }
    )

    assert "原文标题" not in body
    assert "原始新闻标题不应进入草稿正文" not in body
    assert body.startswith("内容：\n")
    assert "日期：2026-07-02" in body
    assert "来源：Example News" in body


def test_focus_daily_news_item_selects_important_story_from_generic_bundle():
    picked = NewsItem(
        title="今日要闻",
        url="https://example.com/mixed",
        source="Example Hot",
        domain="example.com",
        seendate="2026-07-02",
        description=(
            "明星综艺录制花絮曝光\n"
            "国务院发布超龄劳动者权益保障新规\n"
            "地方文旅夜市活动开幕"
        ),
        content=(
            "明星综艺录制花絮曝光\n"
            "国务院发布超龄劳动者权益保障新规\n"
            "地方文旅夜市活动开幕"
        ),
    )

    focused, meta = _focus_daily_news_item(picked)

    assert focused.title == "国务院发布超龄劳动者权益保障新规"
    assert focused.description == "国务院发布超龄劳动者权益保障新规"
    assert focused.content == "国务院发布超龄劳动者权益保障新规"
    assert meta["multi_story_filter"]["applied"] is True
    assert meta["multi_story_filter"]["selected_title"] == "国务院发布超龄劳动者权益保障新规"


def test_create_daily_news_posts_stores_simplified_body_without_original_title(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="臺灣AI產業發佈新規",
        url="https://example.com/tw-ai",
        source="聯合新聞網",
        domain="example.com",
        seendate="2026-07-02",
        description="臺灣AI產業發佈新規，資訊服務與平台門戶同步調整。",
        content="臺灣AI產業發佈新規，資訊服務與平台門戶同步調整。",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "臺灣AI產業發佈新規",
            "body": _test_daily_news_body(
                original_title="臺灣AI產業發佈新規",
                content="臺灣AI產業發佈新規，資訊服務與平台門戶同步調整。",
                comment="這項規則的重點在於資訊透明、平台責任與產業協同。",
                date="2026-07-02",
                source="聯合新聞網",
            ),
            "topics": ["每日新闻", "臺灣AI", "資訊服務"],
            "image_event": "臺灣AI產業發佈新規",
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="科技产业",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    post = posts[0]
    assert "原文标题" not in post.body
    assert all(ch not in f"{post.title}\n{post.body}\n{' '.join(post.topics)}" for ch in "臺灣發佈資訊聯門戶項規則責產業協")
    assert "台湾AI产业发布新规" in post.title
    assert "台湾AI产业发布新规" in post.body


def test_daily_news_prompt_makes_comment_optional_and_forbids_generic_comment():
    picked = NewsItem(
        title="Madagascar receives weather monitoring equipment",
        url="https://example.com/weather",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
        description="The equipment is intended to improve weather monitoring and disaster warning.",
        content="The report mentions automatic weather stations and data transmission devices.",
    )

    prompt = _daily_news_prompt(picked, "国际新闻")

    assert "评价" in prompt
    assert "可为空字符串" in prompt
    assert "没有可核验影响时省略点评" in prompt
    assert "不得写“这类新闻适合先看事实，再看影响”" in prompt
    assert "正文必须通顺" in prompt


def test_daily_news_prompt_defaults_to_no_viewpoint_and_accepts_custom_viewpoint():
    picked = NewsItem(
        title="New factory opens in Shanghai",
        url="https://example.com/factory",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
        description="A factory opening is expected to affect local jobs and suppliers.",
        content="The report describes the factory opening and local employment plans.",
    )

    default_prompt = _daily_news_prompt(picked, "")

    assert "评价视角：无视角评价" in default_prompt
    assert "坚持中国立场" not in default_prompt
    assert "中国国家利益" not in default_prompt

    custom_prompt = _daily_news_prompt(picked, "", "产业政策视角")

    assert "评价视角：产业政策视角" in custom_prompt
    assert "评价视角：无视角评价" not in custom_prompt


def test_finalize_daily_news_body_removes_incomplete_comment_tail_before_publish_time():
    picked = NewsItem(
        title='LG Display OLED becomes world\'s first to achieve "Perfect Color/Brightness" certification',
        url="https://example.com/lg-oled",
        source="PRNewswire",
        domain="prnewswire.com",
        seendate=_recent_news_seendate(0),
        description="LG Display said its OLED panels received perfect color and brightness certification.",
        content="LG Display announced its large-sized OLED panels received Perfect Color/Brightness certification.",
    )
    body = _test_daily_news_body(
        original_title="LG显示OLED首获认证",
        content="LG Display宣布其全系列大尺寸OLED面板成为全球首个获得完美色彩/亮度认证的产品线。",
        comment="此次认证体现了LG Display在OLED技术研发上的 发布时间：2026-06-22",
        date="2026-06-22",
        source="PRNewswire",
    )

    out = _finalize_daily_news_body(body, picked, "科技新闻")
    data = _daily_news_body_fields(out)

    assert "发布时间" not in data["评价"]
    assert not data["评价"].endswith(("的", "上的", "在", "体现了"))
    assert "OLED" in data["内容"]


def test_daily_news_title_normalization_removes_japanese_and_prefix():
    picked = NewsItem(
        title="今年1～5月 中国西部地域の貿易が拡大",
        url="https://example.com/jp",
        source="Example",
        domain="example.com",
        description="中国西部地区外贸增长，跨境物流保持活跃。",
    )

    title = _normalize_daily_news_title("每日新闻｜今年1～5月 中国西部地域の貿", picked, "经济新闻")

    assert len(title) <= 20
    assert not title.startswith("每日新闻")
    assert not _has_japanese_kana(title)
    assert "の" not in title
    assert "外贸" in title or "中国西部" in title


def test_daily_news_title_fallback_maps_japanese_trade_title_to_chinese_summary():
    picked = NewsItem(
        title="今年1～5月 中国西部地域の貿易が拡大",
        url="https://example.com/jp",
        source="Example",
        domain="example.com",
    )

    title = _normalize_daily_news_title(picked.title, picked, "")

    assert title == "外贸数据出现变化"
    assert len(title) <= 20
    assert not _has_japanese_kana(title)


def test_daily_news_title_does_not_treat_french_importe_as_import_trade():
    picked = NewsItem(
        title="En faveur de l'action pour le climat ? Peu importe le pays, le message compte",
        url="https://example.com/fr-climate",
        source="Example",
        domain="example.com",
        description="A survey compares attitudes toward climate action across European countries.",
    )

    title = _normalize_daily_news_title(picked.title, picked, "")

    assert title == "气候行动分歧受关注"
    assert title != "外贸数据出现变化"
    assert len(title) <= 20


def test_daily_news_title_normalization_rejects_prompt_like_title():
    picked = NewsItem(
        title="US agency updates sunscreen approval process",
        url="https://example.com/sunscreen",
        source="Example",
        domain="example.com",
        description="美国相关机构拟调整防晒产品审批流程，市场关注后续落地节奏。",
    )
    prompt = "选择一条适合小红书图文的科技、社会或国际新闻；摘要约50字；正文约200字。"

    title = _normalize_daily_news_title(prompt, picked, prompt)

    assert len(title) <= 20
    assert "选择一条" not in title
    assert "适合小红书" not in title
    assert "摘要" not in title
    assert "正文" not in title
    assert "防晒" in title or "审批" in title


def test_daily_news_title_normalization_rejects_person_name_only():
    picked = NewsItem(
        title="谢晖：国足4年后就能进世界杯 留洋球员增信心_新闻频道_中华网",
        url="https://news.china.com/socialgd/10000169/20260620/49559130.html",
        source="中华网",
        domain="news.china.com",
    )

    title = _normalize_daily_news_title("谢晖", picked, "")

    assert title != "谢晖"
    assert "国足" in title or "世界杯" in title
    assert "新闻频道" not in title
    assert len(title) <= 20


def test_daily_news_title_prefers_summary_phrase_not_blind_truncation():
    picked = NewsItem(
        title="公益宝贝科技兴农战略项目一周年 打造多元主体参与的产业发展服务生态",
        url="https://news.cau.edu.cn/example",
        source="中国农业大学新闻网",
        domain="news.cau.edu.cn",
        description="公益宝贝科技兴农战略项目运行一周年，项目介绍产业发展服务生态建设情况。",
    )

    title = _normalize_daily_news_title(picked.title, picked, "")

    assert title == "公益宝贝科技兴农战略项目一周年"
    assert 12 <= len(title) <= 18
    assert "打造多" not in title


def test_daily_news_title_rewrites_truncated_llm_candidates_from_source_title():
    samples = [
        (
            "山东移动泰安分公司圆满完成因你而来",
            "山东移动泰安分公司圆满完成《因你而来》演唱会通信保障",
            "演唱会通信保障完成",
        ),
        (
            "手慢无！“苏新消费·品质数码”手机补",
            "手慢无！“苏新消费·品质数码”手机补贴来了！单台最高可补1000元",
            "江苏数码消费补贴启动",
        ),
        (
            "碧芭宝贝所有已检测纸尿裤产品甲酰胺项",
            "碧芭宝贝：所有已检测纸尿裤产品甲酰胺项目结果均为未检出",
            "纸尿裤甲酰胺未检出",
        ),
        (
            "进账“一个比尔·盖茨”！马斯克行权获",
            "进账“一个比尔·盖茨”！马斯克行权获7800亿元账面收益",
            "马斯克获巨额账面收益",
        ),
        (
            "欧洲化工寒冬持续赢创全球再裁320",
            "欧洲化工寒冬持续：赢创全球再裁3200人，关停聚酯业务",
            "赢创全球再裁3200人",
        ),
    ]
    for llm_title, source_title, expected in samples:
        picked = NewsItem(
            title=source_title,
            url="https://example.com/news",
            source="示例来源",
            domain="example.com",
            description=source_title,
            content=source_title,
        )

        title = _normalize_daily_news_title(llm_title, picked, "")

        assert title == expected
        assert len(title) <= 18


def test_daily_news_title_compresses_human_rights_governance_without_cutting_word():
    picked = NewsItem(
        title="中国举办人权理事会边会共商全球人权治理",
        url="https://www.news.cn/world/example-human-rights",
        source="新华网",
        domain="news.cn",
        description="中国联合国协会和中国常驻日内瓦代表团举办边会，与会嘉宾表示国际社会应团结合作，共同促进和保障人权。",
    )

    title = _normalize_daily_news_title(picked.title, picked, "国际新闻")

    assert title == "中国共商全球人权治理"
    assert not title.endswith("治")
    assert len(title) <= 18


def test_daily_news_title_rewrites_short_source_title_instead_of_copying_original():
    picked = NewsItem(
        title="古巴外长称美国无权评判古巴改革",
        url="https://www.xinhuanet.com/world/example-cuba",
        source="新华网",
        domain="xinhuanet.com",
        description="古巴外长罗德里格斯表示，美国政府没有政治、法律或道义上的权威来评判古巴采取的改革措施。",
    )

    title = _normalize_daily_news_title(picked.title, picked, "国际新闻")

    assert title == "古巴回应美国评判改革"
    assert title != picked.title
    assert 8 <= len(title) <= 18


def test_daily_news_topics_filter_irrelevant_social_tags_and_add_contextual_tags():
    topics = _normalize_daily_news_topics(
        ["每日新闻", "饭局", "职场中的人情世故", "凝聚力提升"],
        "人权治理",
        context="中国共商全球人权治理。国际社会应团结合作，共同促进和保障人权。",
    )

    assert "每日新闻" in topics
    assert "全球人权治理" in topics
    assert "国际合作" in topics
    assert "饭局" not in topics
    assert "职场中的人情世故" not in topics
    assert "凝聚力提升" not in topics


def test_daily_news_title_expands_over_short_llm_title_from_source_title():
    picked = NewsItem(
        title="美伊谈判在即，记者瑞士比尔根山现场直击",
        url="https://www.xinhuanet.com/example",
        source="新华社",
        domain="xinhuanet.com",
        description="美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。",
    )

    title = _normalize_daily_news_title("美伊谈判在即", picked, "国际新闻")

    assert title != "美伊谈判在即"
    assert title.startswith("美伊谈判在即")
    assert "瑞士" in title or "现场" in title
    assert 10 <= len(title) <= 18


def test_daily_news_title_repairs_condition_half_sentence():
    picked = NewsItem(
        title="特朗普：如与伊朗不能达成协议 美或收取海峡通行费",
        url="https://www.xinhuanet.com/world/example",
        source="新华网",
        domain="xinhuanet.com",
        description="美国总统特朗普称，如果与伊朗不能达成协议，美国或考虑收取霍尔木兹海峡通行费。",
    )

    title = _normalize_daily_news_title("如与伊朗不能达成协议", picked, "国际新闻")

    assert not title.startswith(("如", "如果", "若", "一旦"))
    assert "通行费" in title
    assert "特朗普" in title or "美或" in title
    assert 10 <= len(title) <= 18


def test_daily_news_title_strips_column_prefix_and_preserves_balanced_quotes():
    picked = NewsItem(
        title="香港故事丨在香江细读潮汕“情书”",
        url="https://www.xinhuanet.com/gangao/example",
        source="新华网",
        domain="xinhuanet.com",
        description="电影《给阿嬷的情书》在香港上映，勾起在港潮汕人对侨批和文化传承的记忆。",
    )

    title = _normalize_daily_news_title(picked.title, picked, "文化新闻")

    assert not title.startswith("香港故事")
    assert title.count("“") == title.count("”")
    assert "潮汕" in title and "情书" in title
    assert 10 <= len(title) <= 18


def test_daily_news_title_strips_finance_column_and_summarizes_water_transport():
    picked = NewsItem(
        title="财经聚焦｜多个重大水运工程缘何按下“快进键”",
        url="https://h.xinhuaxmt.com/example",
        source="澎湃新闻",
        domain="h.xinhuaxmt.com",
        description="多个重大水运工程建设提速，相关基础设施项目进入关键阶段。",
    )

    title = _normalize_daily_news_title(picked.title, picked, "财经新闻")

    assert title == "多项重大水运工程提速"
    assert "财经聚焦" not in title
    assert "缘何" not in title


def test_daily_news_title_strips_activity_column_and_summarizes_little_giants():
    picked = NewsItem(
        title="活力中国调研行｜上天、入海，“小巨人”们为何坚定布局最前沿",
        url="https://www.thepaper.cn/example-little-giants",
        source="澎湃新闻",
        domain="thepaper.cn",
        description="专精特新“小巨人”企业布局水下机器人、商业航天等最前沿领域。",
    )

    title = _normalize_daily_news_title("活力中国调研行｜上天、入海", picked, "")

    assert title == "小巨人企业布局前沿"
    body = (
        "原文标题：活力中国调研行｜上天、入海，“小巨人”们为何坚定布局最前沿\n\n"
        "内容：\n专精特新“小巨人”企业布局水下机器人、商业航天等前沿领域。\n\n"
        "日期：2026-06-21 12:18:57\n\n"
        "来源：澎湃新闻"
    )
    assert _daily_news_quality_issue("活力中国调研行｜上天、入海", body, "") == "title_column_prefix"


def test_daily_news_title_rewrites_ai_travel_detail_as_summary():
    picked = NewsItem(
        title="AI伴你游，旅程更省心（新生活新体验）",
        url="https://mini.eastday.com/mobile/example-travel-ai.html",
        source="东方资讯河北频道",
        domain="mini.eastday.com",
        description="贵州的黄小西、浙江的杭小忆等文旅小程序提供数字导游服务，帮助游客规划路线。",
    )

    title = _normalize_daily_news_title("游客在手机上打开“杭小忆”", picked, "")

    assert title == "AI数字导游助力出游"


def test_daily_news_title_repairs_truncated_forum_title():
    picked = NewsItem(
        title="第八届上海科幻影视产业论坛在浦东正式启幕",
        url="https://example.com/scifi-forum",
        source="北青网",
        domain="ynet.com",
        description="6月20日，第八届上海科幻影视产业论坛在上海申迪文化中心开幕，围绕科幻影视产业发展展开交流。",
    )

    title = _normalize_daily_news_title("第八届上海科幻影视产业论坛在浦东正式", picked, "")

    assert title == "上海科幻影视论坛启幕"
    assert "正式" not in title
    assert _daily_news_quality_issue(
        "第八届上海科幻影视产业论坛在浦东正式",
        (
            "原文标题：第八届上海科幻影视产业论坛在浦东正式启幕\n\n"
            "内容：\n第八届上海科幻影视产业论坛在浦东正式启幕。\n\n"
            "日期：2026-06-21\n\n"
            "来源：北青网"
        ),
        "",
    ) == "incomplete_title"


def test_daily_news_title_summarizes_big_bay_area_and_korea_tech_titles():
    bay_picked = NewsItem(
        title="科创资源深度融合 前沿技术在大湾区加速落地",
        url="https://example.com/bay-tech",
        source="21st Century Business Herald",
        domain="example.com",
        content="依托城市群区域协同一体化发展，粤港澳大湾区正在成为科技成果商业化应用的世界级高技术产业集聚区。",
    )
    korea_picked = NewsItem(
        title="资金狂涌！全球科技升温，公募加速布局韩国赛道",
        url="https://example.com/korea-tech",
        source="21st Century Business Herald",
        domain="example.com",
        content="全球AI产业景气度持续攀升，韩国科技赛道吸引跨境资金流入，基金公司推出韩国主题ETF。",
    )

    assert _normalize_daily_news_title("依托城市群区域协同一体化发展粤港澳大", bay_picked, "") == "大湾区前沿技术落地"
    assert _normalize_daily_news_title("资金狂涌！全球科技升温", korea_picked, "") == "全球资金布局韩国科技"


def test_daily_news_body_preserves_chinese_source_original_title():
    picked = NewsItem(
        title="特朗普：如与伊朗不能达成协议 美或收取海峡通行费",
        url="https://www.xinhuanet.com/world/example",
        source="新华网",
        domain="xinhuanet.com",
        seendate="2026-06-21T04:35:59+08:00",
    )
    body = json.dumps(
        {
            "原文标题": "如与伊朗不能达成协议",
            "内容": "美国总统特朗普称，如果与伊朗不能达成协议，美国或考虑收取霍尔木兹海峡通行费。",
            "评价": "",
            "日期": "2026-06-21",
            "来源": "新华网",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际新闻")
    fields = _daily_news_body_fields(out)

    assert "原文标题：" not in out
    assert "霍尔木兹" in fields["内容"]
    assert fields["日期"] == "2026-06-21"


def test_finalize_daily_news_body_replaces_unsupported_content_and_irrelevant_comment():
    picked = NewsItem(
        title="古巴外长称美国无权评判古巴改革",
        url="https://www.xinhuanet.com/world/example-cuba",
        source="新华网",
        domain="xinhuanet.com",
        seendate="2026-06-21T07:55:32+08:00",
        description="古巴外长罗德里格斯表示，美国政府没有政治、法律或道义上的权威来评判古巴采取的改革措施。",
        content=(
            "古巴出台的措施基于国家主权和自决权，以应对极端经济打压带来的冲击。"
            "古巴将继续捍卫主权，同时反对外国干涉。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "古巴外长称美国无权评判古巴改革",
            "内容": "今年相继对委内瑞拉、伊朗发起军事行动后，美国总统特朗普又对古巴发出威胁，称“下一个是古巴”，并进一步加大对古巴施压，实行石油封锁。",
            "评价": "这类经贸变化需要同时看订单、物流、政策和企业成本。对中国企业而言，稳定供应链和分散市场风险仍是重点。",
            "日期": "2026-06-21",
            "来源": "新华网",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际新闻")
    fields = _daily_news_body_fields(out)

    assert "对委内瑞拉" not in fields["内容"]
    assert "下一个是古巴" not in fields["内容"]
    assert "石油封锁" not in fields["内容"]
    assert "美国政府没有政治、法律或道义上的权威" in fields["内容"]
    assert "订单" not in fields.get("评价", "")
    assert "供应链" not in fields.get("评价", "")
    assert "国家主权" in fields.get("评价", "") or "外部干预" in fields.get("评价", "")


def test_finalize_daily_news_body_removes_recommendation_noise_and_ai_comment_for_culture_news():
    picked = NewsItem(
        title="香港故事丨在香江细读潮汕“情书”",
        url="https://www.xinhuanet.com/gangao/example",
        source="新华网",
        domain="xinhuanet.com",
        seendate="2026-06-21T09:36:39+08:00",
        description="电影《给阿嬷的情书》在香港上映，勾起在港潮汕人对侨批、红头船和潮汕文化传承的记忆。",
        content=(
            "电影《给阿嬷的情书》在香港上映，银幕上一纸泛黄的侨批远渡重洋。"
            "潮汕文化协会陈列侨批、工夫茶具、潮绣摆件和英歌舞脸谱，讲述潮汕人在香港的生活与传承。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "香港故事丨在香江细读潮汕“情书",
            "内容": (
                "电影《给阿嬷的情书》在香港上映，勾起在港潮汕人对侨批、红头船和潮汕文化传承的记忆。"
                "香港故事丨在香江细读潮汕“情书。权威数读丨一周“靓”数。新华视点丨。特色产业赋能陇原富民兴农。"
                "记者手记丨从赛场到市场。中国摩托加速“驶入”欧洲。"
            ),
            "评价": "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要。",
            "日期": "2026-06-21",
            "来源": "新华网",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "文化新闻")
    fields = _daily_news_body_fields(out)

    assert "原文标题：" not in out
    assert "权威数读" not in fields["内容"]
    assert "新华视点" not in fields["内容"]
    assert "特色产业赋能" not in fields["内容"]
    assert "记者手记" not in fields["内容"]
    assert "中国摩托" not in fields["内容"]
    assert not fields["内容"].startswith("在香江细读潮汕")
    assert fields["内容"].count("电影《给阿嬷的情书》") == 1
    assert "AI 使用边界" not in fields.get("评价", "")
    assert "文化传承" in fields.get("评价", "") or "文化记忆" in fields.get("评价", "")


def test_daily_news_body_removes_navigation_noise_from_original_excerpt():
    picked = NewsItem(
        title="谢晖：国足4年后就能进世界杯 留洋球员增信心_新闻频道_中华网",
        url="https://news.china.com/socialgd/10000169/20260620/49559130.html",
        source="中华网",
        domain="news.china.com",
        seendate="2026-06-20T10:17:16Z",
        content=(
            "原文摘录：谢晖：国足4年后就能进世界杯 留洋球员增信心_新闻频道_中华网 "
            "首页 资讯 军事 财经 娱乐 汽车 游戏 文化 更多 注册 登录 中华网 "
            "国内 国际 社会 体育 专题 军事 财经 滚动 谢晖：国足4年后就能进世界杯 留洋球员增信心 "
            "小 大 用微信扫描二维码 分享至好友和朋友圈 关键词： "
            "2026-06-20 10:17:16 风过乡足球精华 6月20日，世界杯小组赛继续进行，"
            "中国球迷已经连续24年未能看到自己的队伍出现在世界杯决赛圈的舞台上。"
            "前国脚谢晖表示国足非常有希望打进2030年世界杯。"
        ),
    )

    body = _daily_news_offline_body(picked, "")

    assert "首页 资讯 军事 财经" not in body
    assert "新闻频道" not in body
    assert "国足" in body
    assert "世界杯" in body


def test_clean_original_news_text_removes_browser_and_navigation_noise():
    raw = (
        "本站不再支持您的浏览器，请使用360浏览器8及以上（极速模式）、IE9及以上、Chrome5、"
        "Safari6、Firefox 3.6及以上、 Opera 10.5及以上浏览器观看。请升级您的浏览器到 更高的版本 ！"
        "以获得更好的观看效果。 学习 学习时间 头条 头条关注 综合 综合新闻 媒体 媒体农。"
        "公益宝贝科技兴农战略项目一周年 打造多元主体参与的产业发展服务生态。"
        "项目通过多元主体协同，服务农业创新和乡村产业发展。"
    )

    cleaned = create_post._clean_original_news_text(raw)

    assert "本站不再支持您的浏览器" not in cleaned
    assert "360浏览器" not in cleaned
    assert "学习 学习时间" not in cleaned
    assert "头条 头条关注" not in cleaned
    assert "媒体 媒体农" not in cleaned
    assert "公益宝贝科技兴农战略项目一周年" in cleaned


def test_enrich_daily_news_fetches_original_even_when_summary_exists(monkeypatch):
    picked = NewsItem(
        title="公益宝贝科技兴农战略项目一周年",
        url="https://news.cau.edu.cn/example",
        source="中国农业大学新闻网",
        domain="news.cau.edu.cn",
        description="项目运行一周年，介绍产业发展服务生态建设情况，这段摘要已经超过默认最短阈值。",
        content="项目介绍多元主体参与、产业发展服务生态和农业创新支持，内容已经足够长但仍需抓取原文。",
    )
    calls: list[str] = []

    def fake_fetch(url: str, *, timeout_s: float = 8.0, max_chars: int = 1200) -> str:
        calls.append(url)
        return "原文显示，项目围绕科技兴农、公益参与和产业服务展开，形成多元主体协同机制。"

    monkeypatch.setattr(create_post, "_fetch_original_news_excerpt", fake_fetch)

    enriched, meta = _enrich_daily_news_item(picked)

    assert calls == ["https://news.cau.edu.cn/example"]
    assert meta["source_lookup"]["needed"] is True
    assert meta["source_lookup"]["ok"] is True
    assert "原文显示" in (enriched.content or "")


def test_daily_news_generic_offline_body_is_rejected_by_quality_gate():
    picked = NewsItem(
        title="Sparse source title",
        url="https://example.com/news",
        source="Example",
        domain="example.com",
        description="too short",
    )

    body = _daily_news_offline_body(picked, "")

    assert _daily_news_body_is_too_generic(body)
    assert _daily_news_quality_issue("国际议题出现进展", body, "") == "generic_title"


def test_daily_news_quality_gate_rejects_english_phrase_in_content():
    body = _test_daily_news_body(
        original_title="\u004e\u0041\u0053\u0041\u6708\u7403\u57fa\u5730\u8ba1\u5212",
        content=(
            "Taking the 2026 Professional honors in the Consumer Tec "
            "\u0053\u0050\u0041\u0043\u0045\u6708\u7403\u57fa\u5730\u8ba1\u5212\uff0c"
            "\u539f\u59cb\u6750\u6599\u63d0\u5230\u76f8\u5173\u6280\u672f\u4e89\u8bae\u51fa\u73b0\u5347\u7ea7\uff0c"
            "\u4f46\u672a\u63d0\u4f9b\u8db3\u591f\u7ec6\u8282\u652f\u6491\u66f4\u8fdb\u4e00\u6b65\u5224\u65ad\u3002"
        ),
        comment="",
        source="Core77.com",
    )

    assert _daily_news_quality_issue("\u004e\u0041\u0053\u0041\u6708\u7403\u57fa\u5730\u8ba1\u5212", body, "") == "bad_body_language"


def test_daily_news_quality_gate_rejects_generic_ai_progress_title():
    body = _test_daily_news_body(
        original_title="\u90e8\u5206\u4f5c\u5bb6\u516c\u5f00\u8ba8\u8bbaAI\u5199\u4f5c\u4f7f\u7528",
        content="\u51fa\u7248\u4e1a\u56f4\u7ed5AI\u5199\u4f5c\u7684\u521b\u610f\u8fb9\u754c\u548c\u900f\u660e\u5ea6\u5c55\u5f00\u8ba8\u8bba\uff0c\u90e8\u5206\u4f5c\u5bb6\u627f\u8ba4\u4f7f\u7528\u76f8\u5173\u5de5\u5177\u8f85\u52a9\u6784\u601d\u3001\u6574\u7406\u548c\u4fee\u6539\u3002",
        comment="\u8fd9\u7c7b\u8ba8\u8bba\u7684\u91cd\u70b9\u5728\u4e8e\u7248\u6743\u8d23\u4efb\u3001\u5e73\u53f0\u62ab\u9732\u548c\u8bfb\u8005\u77e5\u60c5\u6743\u5982\u4f55\u843d\u5230\u660e\u786e\u89c4\u5219\u3002",
        source="Designboom",
    )

    assert _daily_news_quality_issue("AI\u8bae\u9898\u51fa\u73b0\u8fdb\u5c55", body, "") == "generic_title"


def test_daily_news_offline_body_with_context_passes_quality_gate():
    picked = NewsItem(
        title="中方敦促国际社会采取有力人道主义行动",
        url="https://example.com/humanitarian-action",
        source="人民网",
        domain="world.people.com.cn",
        seendate="2026-06-20T03:30:00Z",
        description=(
            "中方在联合国相关会议上表示，国际社会应采取更有力的人道主义行动，"
            "推动冲突地区停火止战，保障平民基本生存需求。"
        ),
    )

    title = _normalize_daily_news_title(picked.title, picked, "")
    body = _finalize_daily_news_body(_daily_news_offline_body(picked, ""), picked, "")

    assert "人道主义" in body
    assert not _daily_news_body_is_too_generic(body)
    assert _daily_news_quality_issue(title, body, "") == ""
    content = _daily_news_body_fields(body)["内容"]
    assert len(content) <= 150
    assert "目前可以确认的信息主要来自" not in body
    assert "对读者来说，判断这条新闻" not in body


def test_daily_news_offline_body_uses_specific_comment_when_facts_support_it():
    picked = NewsItem(
        title="中国援助马达加斯加气象设备投入使用",
        url="https://example.com/weather-aid",
        source="新华社",
        domain="xinhuanet.com",
        seendate="2026-06-20T07:30:00Z",
        description="中国援助马达加斯加的气象观测设备在当地投入使用，项目服务防灾减灾和农业生产。",
        content=(
            "原文摘录：项目包括自动气象站和数据传输设备，帮助提升台风、暴雨等灾害预警能力。"
            "当地部门表示，设备将改善气象监测覆盖，为农业安排和公共安全提供参考。"
        ),
    )

    body = _daily_news_offline_body(picked, "")
    comment = body.split("点评：", 1)[1].split("发布时间：", 1)[0].strip()

    assert "气象" in comment
    assert "防灾减灾" in comment or "灾害预警" in comment
    assert "农业" in comment or "公共安全" in comment
    assert "这类新闻适合先看事实" not in body
    assert "接下来可以重点关注权威更新" not in body


def test_daily_news_specific_offline_body_uses_available_facts():
    picked = NewsItem(
        title="What Makes the Seawater Battery a Breakthrough for Sustainability",
        url="https://example.com/seawater",
        source="Geeky Gadgets",
        domain="example.com",
        seendate="2026-06-19T06:13:00Z",
        description=(
            "The seawater battery, developed by Professor Kim Young-sik and his team "
            "at Korea's Ulsan National Institute of Science and Technology, integrates "
            "energy storage, desalination and carbon capture."
        ),
    )

    title = _normalize_daily_news_title(picked.title, picked, "")
    body = _finalize_daily_news_body(_daily_news_offline_body(picked, ""), picked, "")

    assert title == "海水电池技术突破"
    assert "海水电池" in body
    assert "海水淡化" in body
    assert "碳捕集" in body
    assert not _daily_news_body_is_too_generic(body)
    assert _daily_news_quality_issue(title, body, "") == ""


def test_daily_news_context_lookup_fetches_original_when_context_incomplete(monkeypatch):
    picked = NewsItem(
        title="Sparse source title",
        url="https://example.com/original",
        source="Example",
        domain="example.com",
        description="too short",
        content="",
    )
    calls: list[str] = []

    def fake_fetch(url: str, *, timeout_s: float = 8.0, max_chars: int = 1200) -> str:
        calls.append(url)
        return "原新闻显示，相关机构公布了更完整的事实背景、时间线和影响范围。"

    monkeypatch.setattr(create_post, "_fetch_original_news_excerpt", fake_fetch)

    enriched, meta = _enrich_daily_news_item(picked)

    assert _daily_news_context_is_incomplete(picked) is True
    assert calls == ["https://example.com/original"]
    assert "原新闻显示" in (enriched.content or "")
    assert meta["source_lookup"]["ok"] is True


def test_daily_news_prompt_requires_source_lookup_before_evaluation():
    picked = NewsItem(
        title="Sparse source title",
        url="https://example.com/original",
        source="Example",
        domain="example.com",
        description="too short",
        content="原新闻显示，相关机构公布了更完整的事实背景、时间线和影响范围。",
    )

    prompt = _daily_news_prompt(picked, "国际新闻")

    assert "内容不完整时" in prompt
    assert "先查阅原新闻" in prompt
    assert "不得推测" in prompt
    assert "12-18字" in prompt
    assert "理想约15字" in prompt
    assert "不得出现日文假名" in prompt


def test_daily_news_offline_body_for_english_item_uses_chinese_publishable_shell():
    picked = NewsItem(
        title="Inside the fight over Claude Mythos 5",
        url="https://example.com/news",
        source="Example",
        domain="example.com",
        seendate="2026-06-16T00:00:00Z",
        description="As the rest of the country celebrated the holiday, a technology dispute escalated.",
    )

    body = _daily_news_offline_body(picked, "科技新闻")
    summary = body.split("要点摘要：", 1)[1].splitlines()[0].strip()
    content = body.split("新闻内容：", 1)[1].split("点评：", 1)[0].strip()

    assert "Inside the fight over Claude Mythos 5" not in body
    assert "technology dispute" not in body
    assert 35 <= len(summary) <= 70
    assert 40 <= len(content) <= 150
    assert "发布时间：2026-06-16" in body


def test_create_daily_news_single_stores_url_locally_but_not_in_body(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Global chip company announces new AI accelerator",
        url="https://example.com/source",
        source="Example News",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="The chip company said the product targets inference workloads.",
        content="The company described performance and energy-efficiency updates.",
    )
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return [picked], {"provider": "hotnews", "provider_attempts": ["hotnews"]}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "AI芯片新品发布",
            "body": (
                "要点摘要：AI芯片企业发布新品，强调推理算力与能效提升。\n"
                "新闻内容：\n"
                "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景，并强调能效、部署成本和生态适配等指标。"
                "从已给信息看，事件仍处在产品发布层面，具体量产、客户采用和商业效果仍需等待后续权威披露。"
                "这类硬件更新可能影响云服务、终端智能和企业算力采购节奏，但目前不能把发布会表述直接等同于市场结果。\n\n"
                "点评：\n"
                "从中国受众视角看，AI芯片竞争会继续影响算力供给、产业链安全和应用成本。更值得关注的是技术指标能否转化为稳定供应，"
                "以及不同市场在合规、生态和价格上的后续变化。你更关注性能还是供应稳定性？\n\n"
                f"发布时间：{_recent_news_date()}\n\n"
                "来源：Example News https://example.com/source"
            ),
            "topics": ["每日新闻", "AI芯片", "科技"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    post = create_post.create_post_with_draft(
        title_hint="每日新闻",
        prompt_hint="科技新闻",
        asset_paths=[],
        auto_image=False,
    )

    assert "https://example.com/source" not in post.body
    assert "http://" not in post.body and "https://" not in post.body
    data = _daily_news_body_fields(post.body)
    assert data["来源"] == "Example News"
    assert data["日期"] == _recent_news_date()
    assert post.platform["news"]["source_url"] == "https://example.com/source"
    assert post.platform["news"]["picked"]["url"] == "https://example.com/source"
    assert post.platform["news"]["api_source"] == "hotnews"
    assert post.platform["news"]["source_api"]["provider"] == "hotnews"
    assert post.platform["news"]["source_api"]["item_source"] == "Example News"
    assert fetch_kwargs["max_records"] == 20
    assert post.platform["news"]["selection_pool"]["target_fetch_count"] == 1
    assert post.platform["news"]["selection_pool"]["raw_fetch_count"] == 20


def test_create_daily_news_single_outputs_fixed_body_fields(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Global chip company announces new AI accelerator",
        url="https://example.com/source",
        source="Example News",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="The chip company said the product targets inference workloads.",
        content="The company described performance and energy-efficiency updates.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([picked], {"provider": "fake-news"}),
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "AI芯片新品发布",
            "body": (
                "要点摘要：AI芯片企业发布新品，强调推理算力与能效提升。\n"
                "新闻内容：\n"
                "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景，并强调能效、部署成本和生态适配等指标。"
                "从已给信息看，事件仍处在产品发布层面，具体量产、客户采用和商业效果仍需等待后续披露。\n\n"
                "点评：\n"
                "AI芯片竞争会继续影响算力供给、产业链安全和应用成本，关键是技术指标能否转化为稳定供应。\n\n"
                f"发布时间：{_recent_news_date()}\n\n"
                "来源：Example News https://example.com/source"
            ),
            "topics": ["每日新闻", "AI芯片", "科技"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    post = create_post.create_post_with_draft(
        title_hint="每日新闻",
        prompt_hint="科技新闻",
        asset_paths=[],
        auto_image=False,
    )

    data = _daily_news_body_fields(post.body)
    assert "原文标题：" not in post.body
    assert post.title == "AI芯片新品发布"
    assert "AI芯片" in data["内容"]
    assert "算力供给" in data["评价"]
    assert data["日期"] == _recent_news_date()
    assert data["来源"] == "Example News"
    assert "http" not in post.body
    assert "https://example.com/source" == post.platform["news"]["source_url"]


def test_create_daily_news_posts_scrubs_url_and_persists_source_url(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="EU signs a new technology cooperation deal",
        url="https://example.com/eu-tech",
        source="Example Wire",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="Officials announced a technology cooperation framework.",
        content="The framework focuses on standards, investment and supply chain dialogue.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "hotnews", "provider_attempts": ["hotnews"]}),
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "欧盟科技合作框架",
            "body": (
                "要点摘要：欧盟披露新的科技合作框架，强调标准、投资和供应链沟通。\n"
                "新闻内容：\n"
                "相关方面公布新的科技合作安排，重点围绕技术标准、产业投资和供应链对话展开。"
                "从已给资料看，这一安排仍属于框架性进展，具体执行节奏、参与主体和实际约束力仍需进一步观察。"
                "对企业而言，后续影响可能体现在合规要求、跨境合作成本和市场准入预期上，但不能脱离公开信息作扩大判断。\n\n"
                "点评：\n"
                "从中国受众视角看，国际科技规则变化会影响企业出海、供应链合作和产业竞争节奏。"
                "更稳妥的判断方式，是持续跟踪正式文本和后续执行细节，而不是只看标题作结论。你认为企业最需要关注哪一项？\n\n"
                f"发布时间：{_recent_news_date()}\n\n"
                "来源：Example Wire https://example.com/eu-tech"
            ),
            "topics": ["每日新闻", "科技合作", "国际"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="国际科技",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    assert len(posts) == 1
    assert "https://example.com/eu-tech" not in posts[0].body
    data = _daily_news_body_fields(posts[0].body)
    assert data["来源"] == "Example Wire"
    assert data["日期"] == _recent_news_date()
    assert posts[0].platform["news"]["source_url"] == "https://example.com/eu-tech"
    assert posts[0].platform["news"]["picked"]["url"] == "https://example.com/eu-tech"
    assert posts[0].platform["news"]["api_source"] == "hotnews"
    assert posts[0].platform["news"]["source_api"]["provider"] == "hotnews"
    assert posts[0].platform["news"]["source_api"]["item_source"] == "Example Wire"


def test_create_daily_news_posts_replaces_cross_candidate_title_and_image_event(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title='LG Display OLED becomes world\'s first to achieve "Perfect Color/Brightness" certification',
        url="https://example.com/lg-oled",
        source="PRNewswire",
        domain="prnewswire.com",
        seendate=_recent_news_seendate(0),
        description="LG Display said its large-sized OLED panels received perfect color and brightness certification.",
        content=(
            "LG Display announced its large-sized OLED panels for monitors and TVs became the first "
            "product lineup to receive Perfect Color/Brightness certification."
        ),
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "LG显示OLED首获认证",
            "body": _test_daily_news_body(
                original_title="锂提取技术获进展",
                content=(
                    "LG Display宣布其大尺寸OLED面板获得完美色彩/亮度认证，"
                    "该认证覆盖显示器和电视用OLED面板，突出色彩还原和亮度表现。"
                ),
                comment="这项认证的意义在于显示面板性能有了更明确的行业评价维度。",
                date=_recent_news_date(),
                source="PRNewswire",
            ),
            "topics": ["每日新闻", "OLED", "显示技术"],
            "image_event": "锂提取技术获进展",
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="科技新闻",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    post = posts[0]
    fields = _daily_news_body_fields(post.body)
    image_event = post.platform["news"]["image_event"]

    assert "锂提取" not in post.body
    assert "锂提取" not in image_event
    assert any(token in f"{post.title} {fields['内容']}" for token in ("LG", "OLED", "显示"))
    assert any(token in image_event for token in ("LG", "OLED", "显示"))


def test_create_daily_news_posts_trims_multi_story_source_before_llm_and_image(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="长鑫存储一季度暴赚合肥十年赌局翻盘",
        url="https://example.com/mixed-hot-list",
        source="Example Hot",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description=(
            "长鑫存储一季度利润大增，合肥早期产业投资进入收获期。\n"
            "苹果涨价英伟达返现OpenAI发芯片\n"
            "泡泡玛特暴涨段永平赚十亿港元"
        ),
        content=(
            "长鑫存储一季度暴赚合肥十年赌局翻盘\n"
            "苹果涨价英伟达返现OpenAI发芯片\n"
            "泡泡玛特暴涨段永平赚十亿港元\n"
            "全球6.55亿人无电可用"
        ),
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    seen: dict[str, str] = {}

    def fake_generate_draft(*_args, **kwargs):
        seen["llm_prompt"] = kwargs["prompt_hint"]
        return {
            "title": "长鑫存储盈利翻盘",
            "body": _test_daily_news_body(
                original_title="长鑫存储一季度暴赚合肥十年赌局翻盘",
                content="长鑫存储一季度利润大增，合肥早期产业投资进入收获期。",
                comment="这条新闻的重点在于地方产业投资进入回报观察期。",
                date=_recent_news_date(),
                source="Example Hot",
            ),
            "topics": ["每日新闻", "芯片产业"],
            "image_event": "长鑫存储一季度利润大增",
        }

    def fake_images(*, title, body, topics, prompt_hint, dest_dir, **_kwargs):
        seen["image_title"] = title
        seen["image_prompt"] = prompt_hint
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "image.jpg"
        out.write_bytes(b"image")
        return [out], [{"provider": "fake", "query_original": prompt_hint}]

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(create_post, "fetch_and_download_related_images", fake_images)

    posts = create_post.create_daily_news_posts(
        prompt_hint="财经产业",
        asset_paths=[],
        count=1,
        auto_image=True,
    )

    post = posts[0]
    fields = _daily_news_body_fields(post.body)
    blocked = ("苹果涨价", "OpenAI发芯片", "泡泡玛特", "全球6.55亿人无电")

    assert "长鑫存储" in seen["llm_prompt"]
    assert all(text not in seen["llm_prompt"] for text in blocked)
    assert all(text not in fields["内容"] for text in blocked)
    assert all(text not in post.platform["news"]["picked"]["content"] for text in blocked)
    assert "长鑫存储" in seen["image_prompt"]
    assert all(text not in seen["image_prompt"] for text in blocked)


def test_create_daily_news_posts_keeps_normal_multi_paragraph_source(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="长鑫存储披露一季度盈利改善",
        url="https://example.com/normal-article",
        source="Example News",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description=(
            "长鑫存储披露一季度盈利改善，产线利用率继续回升。\n"
            "公司称产品结构调整带动毛利率改善。\n"
            "业内人士认为国产存储供应链仍需观察需求周期。"
        ),
        content=(
            "长鑫存储披露一季度盈利改善，产线利用率继续回升。\n"
            "公司称产品结构调整带动毛利率改善。\n"
            "业内人士认为国产存储供应链仍需观察需求周期。"
        ),
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    seen: dict[str, str] = {}

    def fake_generate_draft(*_args, **kwargs):
        seen["llm_prompt"] = kwargs["prompt_hint"]
        return {
            "title": "长鑫存储盈利改善",
            "body": _test_daily_news_body(
                original_title="长鑫存储披露一季度盈利改善",
                content="长鑫存储一季度盈利改善，产品结构调整带动毛利率改善。",
                comment="这条新闻的重点在于国产存储企业经营质量改善。",
                date=_recent_news_date(),
                source="Example News",
            ),
            "topics": ["每日新闻", "芯片产业"],
            "image_event": "长鑫存储一季度盈利改善",
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="财经产业",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    post = posts[0]
    assert "产品结构调整带动毛利率改善" in seen["llm_prompt"]
    assert "国产存储供应链仍需观察需求周期" in seen["llm_prompt"]
    assert "产品结构调整带动毛利率改善" in post.platform["news"]["picked"]["content"]
    assert "国产存储供应链仍需观察需求周期" in post.platform["news"]["picked"]["content"]
    assert post.platform["news"]["multi_story_filter"]["applied"] is False


def test_create_daily_news_posts_fetches_double_pool_and_diversifies_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    candidates = [
        NewsItem(
            title="36氪公司政策新闻一",
            url="https://36kr.com/p/1",
            source="36氪",
            domain="36kr.com",
            seendate="2026-07-02T09:00:00Z",
            description="公司政策调整引发行业关注。",
            content="公司政策调整引发行业关注。",
            sourcecountry="cn",
        ),
        NewsItem(
            title="36氪公司政策新闻二",
            url="https://36kr.com/p/2",
            source="36氪",
            domain="36kr.com",
            seendate="2026-07-02T08:50:00Z",
            description="平台企业发布新举措。",
            content="平台企业发布新举措。",
            sourcecountry="cn",
        ),
        NewsItem(
            title="新华社发布超龄劳动者权益新规",
            url="https://news.cn/politics/1",
            source="新华社",
            domain="news.cn",
            seendate="2026-07-02T08:40:00Z",
            description="超龄劳动者权益保障新规施行。",
            content="超龄劳动者权益保障新规施行。",
            sourcecountry="cn",
        ),
        NewsItem(
            title="央视关注暑运客流增长",
            url="https://news.cctv.com/china/1",
            source="央视新闻",
            domain="news.cctv.com",
            seendate="2026-07-02T08:30:00Z",
            description="铁路暑运客流进入高峰。",
            content="铁路暑运客流进入高峰。",
            sourcecountry="cn",
        ),
    ]
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return candidates, {"provider": "fake-news"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    def fake_generate_draft(*_args, **kwargs):
        prompt = kwargs["prompt_hint"]
        match = re.search(r"- 新闻标题：(.+)", prompt)
        source_match = re.search(r"- 来源名称：(.+)", prompt)
        source_title = match.group(1).strip() if match else "候选新闻标题"
        source = source_match.group(1).strip() if source_match else "Example"
        return {
            "title": source_title[:18],
            "body": _test_daily_news_body(
                original_title=source_title,
                content=f"{source_title}，相关公开信息已经披露，后续影响仍需观察。",
                comment="这条新闻的价值在于提供了清晰的公共议题入口。",
                date="2026-07-02",
                source=source,
            ),
            "topics": ["每日新闻"],
            "image_event": source_title,
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="公司政策 市场变化",
        asset_paths=[],
        count=2,
        auto_image=False,
    )

    picked_domains = [post.platform["news"]["picked"]["domain"] for post in posts]
    assert fetch_kwargs["max_records"] == 40
    assert len(posts) == 2
    assert picked_domains.count("36kr.com") <= 1
    assert len(set(picked_domains)) == 2
    for post in posts:
        assert post.platform["news"]["selection_pool"]["target_fetch_count"] == 2
        assert post.platform["news"]["selection_pool"]["raw_fetch_count"] == 40
        assert post.platform["news"]["selection_pool"]["requested_count"] == 2


def test_daily_news_upload_filters_candidates_to_beijing_three_day_window(monkeypatch):
    candidates = [
        NewsItem(
            title="今天的财经政策新闻",
            url="https://example.com/today",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(0),
        ),
        NewsItem(
            title="昨天的公司政策新闻",
            url="https://example.com/yesterday",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(1),
        ),
        NewsItem(
            title="前天的市场变化新闻",
            url="https://example.com/before-yesterday",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(2),
        ),
        NewsItem(
            title="三天前的旧新闻不应进入候选池",
            url="https://example.com/old",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(3),
        ),
        NewsItem(
            title="缺少发布时间的新闻不应进入候选池",
            url="https://example.com/missing-date",
            source="Example",
            domain="example.com",
            seendate="",
        ),
    ]
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return candidates, {"provider": "fake-news", "tz": "Asia/Shanghai"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    filtered, meta = create_post._fetch_daily_news_candidates_for_upload("新闻", count=2)

    assert fetch_kwargs["max_records"] == 40
    assert [item.url for item in filtered] == [
        "https://example.com/today",
        "https://example.com/yesterday",
        "https://example.com/before-yesterday",
    ]
    pool = meta["selection_pool"]
    assert pool["requested_count"] == 2
    assert pool["target_fetch_count"] == 2
    assert pool["raw_fetch_count"] == 40
    assert pool["raw_candidate_count"] == 5
    assert pool["recent_candidate_count"] == 3
    assert pool["actual_candidate_count"] == 3
    assert pool["dropped_out_of_window_count"] == 2
    assert pool["date_window"]["max_age_days"] == 3
    assert pool["date_window"]["tz"] == "Asia/Shanghai"


def test_daily_news_upload_fetches_twenty_times_and_filters_to_prompt_relevance(monkeypatch):
    candidates = [
        NewsItem(
            title="AI startup raises new funding",
            url="https://example.com/ai",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="A technology company announced a new funding round.",
            attention=999,
        ),
        NewsItem(
            title="World Cup ticket resale rules draw scrutiny",
            url="https://example.com/world-cup-rules",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="Sports regulators are reviewing World Cup ticket resale rules.",
            attention=5,
        ),
        NewsItem(
            title="World Cup sponsors prepare new fan campaign",
            url="https://example.org/world-cup-sponsors",
            source="Example",
            domain="example.org",
            seendate=_recent_news_seendate(1),
            description="Sports brands are preparing a World Cup fan campaign.",
            attention=20,
        ),
        NewsItem(
            title="Old World Cup story should be excluded",
            url="https://example.net/old-world-cup",
            source="Example",
            domain="example.net",
            seendate=_recent_news_seendate(3),
            description="Sports story outside the three-day window.",
            attention=100,
        ),
    ]
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return candidates, {"provider": "fake-news", "tz": "Asia/Shanghai"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    selected, meta = create_post._fetch_daily_news_candidates_for_upload("World Cup sports", count=2)

    assert fetch_kwargs["max_records"] == 40
    assert fetch_kwargs["search_days"] == 14
    assert [item.url for item in selected] == [
        "https://example.org/world-cup-sponsors",
        "https://example.com/world-cup-rules",
    ]
    pool = meta["selection_pool"]
    assert pool["requested_count"] == 2
    assert pool["target_fetch_count"] == 2
    assert pool["raw_fetch_count"] == 40
    assert pool["recent_candidate_count"] == 3
    assert pool["prompt_relevant_candidate_count"] == 2
    assert pool["actual_candidate_count"] == 2
    assert pool["lookback"]["mode"] == "auto_expand"
    assert pool["lookback"]["selected_max_age_days"] == 3


def test_daily_news_upload_auto_expands_to_seven_day_window(monkeypatch):
    candidates = [
        NewsItem(
            title="World Cup match schedule update",
            url="https://example.com/world-cup-today",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="Sports organizers updated the World Cup match schedule.",
            attention=20,
        ),
        NewsItem(
            title="World Cup broadcast rights deal advances",
            url="https://example.org/world-cup-rights",
            source="Example",
            domain="example.org",
            seendate=_recent_news_seendate(4),
            description="A sports broadcaster advanced a World Cup rights deal.",
            attention=100,
        ),
        NewsItem(
            title="World Cup travel rules from older report",
            url="https://example.net/world-cup-old",
            source="Example",
            domain="example.net",
            seendate=_recent_news_seendate(10),
            description="Older sports report that should not be needed after seven-day expansion.",
            attention=500,
        ),
    ]
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return candidates, {"provider": "fake-news", "tz": "Asia/Shanghai"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    selected, meta = create_post._fetch_daily_news_candidates_for_upload("World Cup sports", count=2)

    assert fetch_kwargs["max_records"] == 40
    assert fetch_kwargs["search_days"] == 14
    assert {item.url for item in selected} == {
        "https://example.com/world-cup-today",
        "https://example.org/world-cup-rights",
    }
    pool = meta["selection_pool"]
    assert pool["date_window"]["max_age_days"] == 7
    assert pool["lookback"]["mode"] == "auto_expand"
    assert pool["lookback"]["selected_max_age_days"] == 7
    assert [attempt["max_age_days"] for attempt in pool["lookback"]["attempts"]] == [3, 7]
    assert [attempt["actual_candidate_count"] for attempt in pool["lookback"]["attempts"]] == [1, 2]


def test_daily_news_upload_fixed_lookback_days_does_not_expand(monkeypatch):
    candidates = [
        NewsItem(
            title="World Cup match schedule update",
            url="https://example.com/world-cup-today",
            source="Example",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="Sports organizers updated the World Cup match schedule.",
            attention=20,
        ),
        NewsItem(
            title="World Cup broadcast rights deal advances",
            url="https://example.org/world-cup-rights",
            source="Example",
            domain="example.org",
            seendate=_recent_news_seendate(4),
            description="A sports broadcaster advanced a World Cup rights deal.",
            attention=100,
        ),
    ]
    fetch_kwargs: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        fetch_kwargs.update(kwargs)
        return candidates, {"provider": "fake-news", "tz": "Asia/Shanghai"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    with pytest.raises(RuntimeError, match="daily news material insufficient"):
        create_post._fetch_daily_news_candidates_for_upload("World Cup sports", count=2, lookback_days=3)

    assert fetch_kwargs["max_records"] == 40
    assert fetch_kwargs["search_days"] == 3


def test_create_daily_news_posts_replaces_generic_original_title_with_post_title(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Insecure Neighbor Shocks Guy With His Audacity, Comes Up With A Plan To Annoy Him Even More",
        url="https://example.com/shirtless-neighbor",
        source="Boredpanda.com",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description=(
            "A 34-year-old man had been mowing his lawn shirtless for years. "
            "A neighbor's husband later demanded he cover up while mowing."
        ),
        content=(
            "A man said he had mowed his lawn shirtless for years without issue. "
            "After a friendly chat with his neighbor, her husband sent a message demanding he cover up."
        ),
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "男子光膀除草遭要求穿衣",
            "body": _test_daily_news_body(
                original_title="科技议题出现进展",
                content="一名男子多年光膀修剪自家草坪，邻居丈夫随后私信要求他除草时穿上衣。",
                comment="这起邻里纠纷的重点在于私人空间边界和沟通方式。",
                date=_recent_news_date(),
                source="Boredpanda.com",
            ),
            "topics": ["每日新闻", "邻里关系"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    post = posts[0]
    _daily_news_body_fields(post.body)
    assert "原文标题：" not in post.body
    assert post.title == "男子光膀除草遭要求穿衣"
    assert "出现进展" not in post.body


def test_create_daily_news_posts_prefers_post_title_over_mismatched_original_summary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Cisco Secure Access と Island ブラウザで場所を問わずゼロトラストを実現",
        url="https://example.com/cisco-zero-trust",
        source="Cisco.com",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="Cisco Secure Access と Island Enterprise Browser の統合によりゼロトラストを実現。",
        content="Cisco Secure Access and Island Browser combine browser controls with secure access.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "思科与Island浏览器实现零信任",
            "body": _test_daily_news_body(
                original_title="平台封锁VPN用户",
                content="思科Secure Access与Island企业浏览器整合，把访问控制延伸到用户会话和数据操作。",
                comment="这一整合回应了远程办公和非托管设备接入中的安全管理难题。",
                date=_recent_news_date(),
                source="Cisco.com",
            ),
            "topics": ["每日新闻", "网络安全"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    posts = create_post.create_daily_news_posts(
        prompt_hint="",
        asset_paths=[],
        count=1,
        auto_image=False,
    )

    post = posts[0]
    _daily_news_body_fields(post.body)
    assert "原文标题：" not in post.body
    assert post.title == "思科与Island浏览器实现零信任"
    assert "VPN" not in post.body


def test_create_daily_news_posts_uses_backup_candidates_after_quality_skips(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    candidates = [
        NewsItem(
            title=f"\u79d1\u6280\u9879\u76ee{i}\u53d6\u5f97\u8fdb\u5c55",
            url=f"https://example.com/news/{i}",
            source="Example News",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="\u516c\u5f00\u4fe1\u606f\u663e\u793a\u76f8\u5173\u9879\u76ee\u51fa\u73b0\u65b0\u8fdb\u5c55\u3002",
            content="\u76f8\u5173\u673a\u6784\u56f4\u7ed5\u6280\u672f\u843d\u5730\u3001\u4ea7\u4e1a\u534f\u540c\u548c\u5e94\u7528\u573a\u666f\u516c\u5e03\u4e86\u66f4\u591a\u7ec6\u8282\u3002",
        )
        for i in range(40)
    ]
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: (candidates, {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))
    pick_args: dict[str, int] = {}

    def fake_pick_news_items(items, _prompt, *, count=1):
        pick_args["count"] = count
        return items[:count]

    monkeypatch.setattr(create_post, "pick_news_items", fake_pick_news_items)

    calls = {"count": 0}
    good_titles = [
        "\u6e7e\u533a\u7b97\u529b\u5e73\u53f0\u5347\u7ea7",
        "\u7eff\u8272\u822a\u8fd0\u9879\u76ee\u843d\u5730",
        "\u667a\u80fd\u533b\u7597\u7cfb\u7edf\u8bd5\u70b9",
    ]

    def fake_generate_draft(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] <= 15:
            return {
                "title": f"\u5019\u9009\u65b0\u95fb{calls['count']}\u8df3\u8fc7",
                "body": _test_daily_news_body(
                    original_title="\u5f85\u8df3\u8fc7\u5019\u9009",
                    content=f"SKIP_MARKER \u8fd9\u6761\u5019\u9009\u7528\u4e8e\u6a21\u62df\u8d28\u91cf\u95e8\u69db\u8df3\u8fc7\u3002",
                    comment="\u4ec5\u7528\u4e8e\u6d4b\u8bd5\u8df3\u8fc7\u903b\u8f91\u3002",
                ),
                "topics": ["\u6bcf\u65e5\u65b0\u95fb"],
            }
        idx = calls["count"] - 16
        title = good_titles[idx]
        return {
            "title": title,
            "body": _test_daily_news_body(
                original_title=title,
                content="\u9879\u76ee\u56f4\u7ed5\u6280\u672f\u843d\u5730\u548c\u4ea7\u4e1a\u534f\u540c\u5c55\u5f00\uff0c\u76ee\u524d\u5df2\u516c\u5e03\u660e\u786e\u7684\u5e94\u7528\u65b9\u5411\u548c\u53c2\u4e0e\u4e3b\u4f53\u3002",
                comment="\u8fd9\u7c7b\u9879\u76ee\u7684\u4ef7\u503c\u8981\u770b\u540e\u7eed\u5e94\u7528\u89c4\u6a21\u3001\u6210\u672c\u6536\u76ca\u548c\u7528\u6237\u53cd\u9988\u3002",
            ),
            "topics": ["\u6bcf\u65e5\u65b0\u95fb", "\u79d1\u6280"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(
        create_post,
        "_daily_news_quality_issue",
        lambda _title, body, _prompt: "body_site_noise" if "SKIP_MARKER" in body else "",
    )

    posts = create_post.create_daily_news_posts(
        prompt_hint="",
        asset_paths=[],
        count=3,
        auto_image=False,
    )

    assert len(posts) == 3
    assert pick_args["count"] == 3
    assert calls["count"] >= 18


def test_create_daily_news_posts_raises_instead_of_returning_partial_posts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    candidates = [
        NewsItem(
            title=f"\u5019\u9009\u65b0\u95fb{i}",
            url=f"https://example.com/partial/{i}",
            source="Example News",
            domain="example.com",
            seendate=_recent_news_seendate(0),
            description="\u6d4b\u8bd5\u5019\u9009\u63cf\u8ff0\u3002",
            content="\u6d4b\u8bd5\u5019\u9009\u6b63\u6587\u3002",
        )
        for i in range(6)
    ]
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: (candidates, {"provider": "fake-news"}),
    )
    monkeypatch.setattr(create_post, "_enrich_daily_news_item", lambda item: (item, {}))
    monkeypatch.setattr(create_post, "pick_news_items", lambda items, _prompt, *, count=1: items[:count])
    calls = {"count": 0}

    def fake_generate_draft(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "title": "\u9996\u6761\u65b0\u95fb\u6b63\u5e38\u901a\u8fc7",
                "body": _test_daily_news_body(
                    original_title="\u9996\u6761\u65b0\u95fb\u6b63\u5e38\u901a\u8fc7",
                    content="\u8fd9\u6761\u65b0\u95fb\u5305\u542b\u5b8c\u6574\u4e8b\u5b9e\u548c\u53ef\u9a8c\u8bc1\u6765\u6e90\uff0c\u53ef\u4ee5\u4f5c\u4e3a\u6709\u6548\u8349\u7a3f\u4fdd\u5b58\u3002",
                    comment="\u8bc4\u4ef7\u9700\u7ed3\u5408\u540e\u7eed\u516c\u5f00\u4fe1\u606f\u89c2\u5bdf\u5b9e\u9645\u843d\u5730\u6548\u679c\u3002",
                ),
                "topics": ["\u6bcf\u65e5\u65b0\u95fb"],
            }
        return {
            "title": f"\u65e0\u6548\u5019\u9009{calls['count']}",
            "body": _test_daily_news_body(
                original_title="\u65e0\u6548\u5019\u9009",
                content="SKIP_MARKER \u7528\u4e8e\u6a21\u62df\u540e\u7eed\u5019\u9009\u5168\u90e8\u88ab\u8d28\u91cf\u95e8\u69db\u8df3\u8fc7\u3002",
                comment="\u4ec5\u7528\u4e8e\u56de\u5f52\u6d4b\u8bd5\u3002",
            ),
            "topics": ["\u6bcf\u65e5\u65b0\u95fb"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(
        create_post,
        "_daily_news_quality_issue",
        lambda _title, body, _prompt: "body_site_noise" if "SKIP_MARKER" in body else "",
    )

    with pytest.raises(RuntimeError, match="created only 1/3"):
        create_post.create_daily_news_posts(
            prompt_hint="",
            asset_paths=[],
            count=3,
            auto_image=False,
        )

    assert calls["count"] == 6
    assert len(list((tmp_path / "data" / "posts").glob("*/post.json"))) == 1


def test_create_daily_news_fallback_does_not_publish_prompt_as_topic(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Inside the fight over Claude Mythos 5",
        url="https://example.com/news",
        source="Example",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="A technology dispute escalated.",
        content="The report described a policy dispute around advanced AI model access.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([picked], {"provider": "fake-news", "picked": {"title": picked.title}}),
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "每日新闻",
            "body": "你正在为小红书图文笔记写《每日新闻》栏目。\n请依据下面提供的新闻信息。",
            "topics": ["每日新闻"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    prompt = "选择5条适合小红书图文的科技、社会或国际新闻，正文简短，包含要点摘要和点评。"

    post = create_post.create_post_with_draft(
        title_hint="每日新闻",
        prompt_hint=prompt,
        asset_paths=[],
        auto_image=False,
    )

    assert prompt not in post.body
    assert all(prompt not in topic for topic in post.topics)


def test_create_daily_news_rejects_prompt_topic_title_and_generic_body(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )
    picked = NewsItem(
        title="Our long national sunscreen nightmare is almost over",
        url="https://example.com/sunscreen",
        source="The Verge",
        domain="example.com",
        seendate=_recent_news_seendate(0),
        description="Other countries have used newer sunscreen ingredients for years.",
        content="The article discusses FDA review of bemotrizinol and sunscreen access.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt, **_kwargs: ([picked], {"provider": "fake-news", "picked": {"title": picked.title}}),
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "科技、社会或国际新闻",
            "body": (
                "要点摘要：原始来源披露一项科技议题出现新进展，现有信息仍有限，后续需关注权威更新与实际影响。\n"
                "新闻内容：\n"
                "根据原始来源提供的公开信息，一项科技议题出现新进展。目前能够确认的内容主要来自原始新闻的标题、摘要和正文片段。"
                "在信息仍有限的情况下，读者可以先把它视为一个需要继续跟踪的进展，而不是已经定论的结果。\n\n"
                "点评：\n"
                "从中国受众视角看，越是跨地区、跨产业的新闻，越需要区分已确认事实和外界推测。\n\n"
                f"发布时间：{_recent_news_date()}\n\n"
                "来源：The Verge"
            ),
            "topics": ["每日新闻"],
        }

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    post = create_post.create_post_with_draft(
        title_hint="每日新闻",
        prompt_hint="科技、社会或国际新闻；摘要约50字；正文约200字。",
        asset_paths=[],
        auto_image=False,
    )

    assert post.title != "科技、社会或国际新闻"
    assert "防晒" in post.title or "审批" in post.title
    assert "一项科技议题" not in post.body
    assert "防晒" in post.body or "审批" in post.body
    data = _daily_news_body_fields(post.body)
    assert data["来源"] == "The Verge"
    assert data["日期"] == _recent_news_date()


def test_daily_news_english_defense_item_ignores_prompt_category_for_fallback():
    picked = NewsItem(
        title="Hegseth attacks NATO allies and announces a review of US forces in Europe",
        url="https://example.com/nato",
        source="The Times of India",
        domain="example.com",
        seendate="2026-06-19T03:11:59Z",
        description=(
            "U.S. Defense Secretary Pete Hegseth announced a six-month review "
            "of American troop deployments in Europe."
        ),
        content="The Pentagon review concerns American forces in Europe and NATO allies.",
    )
    prompt = (
        "technology, social, or international news; write Simplified Chinese; "
        "summary about 50 Chinese chars; body about 200 Chinese chars."
    )

    title = _normalize_daily_news_title("科技议题出现进展", picked, prompt)
    body = _daily_news_offline_body(picked, prompt)

    assert title != "科技议题出现进展"
    assert "美军" in title or "北约" in title
    assert "一项科技议题" not in body
    assert "美军" in body or "北约" in body


def test_fetch_daily_news_candidates_auto_tries_configured_gnews_when_newsapi_times_out(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.setenv("GNEWS_API_KEY", "fake-gnews-key")
    monkeypatch.setattr(daily_news, "_maybe_translate_hint_to_en", lambda _hint: "technology")

    def fake_newsapi_fetch_articles(**_kwargs):
        raise TimeoutError("timed out")

    gnews_calls = []

    def fake_gnews_fetch_articles(**kwargs):
        gnews_calls.append(kwargs)
        return [
            NewsItem(
                title="AI芯片公司发布新进展",
                url="https://example.cn/ai-chip",
                source="Example",
                domain="example.cn",
                seendate="20260619080000",
                description="一家AI芯片公司披露产品进展。",
            )
        ]

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fake_newsapi_fetch_articles)
    monkeypatch.setattr(daily_news, "_gnews_fetch_articles", fake_gnews_fetch_articles)

    candidates, meta = daily_news.fetch_daily_news_candidates("科技", timeout_s=1)

    assert candidates[0].title == "AI芯片公司发布新进展"
    assert meta["provider"] == "gnews"
    assert meta["provider_attempts"] == ["newsapi", "gnews"]
    assert any("timed out" in err for err in meta["provider_errors"])
    assert gnews_calls


def test_hotnews_provider_maps_platform_items(monkeypatch):
    calls = []

    def fake_hotnews_request_json(*, base_url, platform, timeout_s):
        calls.append((base_url, platform, timeout_s))
        return {
            "status": 200,
            "data": [
                {
                    "title": "AI产业链融资升温",
                    "url": "https://www.toutiao.com/article/123",
                    "desc": "多家AI产业链企业披露新一轮融资。",
                    "score": "9876",
                },
                {"title": "缺少链接的热榜项", "url": "", "desc": "应跳过"},
            ],
        }

    monkeypatch.setattr(daily_news, "_hotnews_request_json", fake_hotnews_request_json, raising=False)

    items = daily_news._hotnews_fetch_articles(
        base_url="https://orz.ai/api/v1/dailynews",
        platforms=["jinritoutiao"],
        max_records=5,
        timeout_s=2,
    )

    assert calls == [("https://orz.ai/api/v1/dailynews", "jinritoutiao", 2)]
    assert len(items) == 1
    assert items[0].title == "AI产业链融资升温"
    assert items[0].url == "https://www.toutiao.com/article/123"
    assert items[0].source == "hotnews:jinritoutiao"
    assert items[0].domain == "www.toutiao.com"
    assert items[0].description == "多家AI产业链企业披露新一轮融资。"
    assert items[0].content == "多家AI产业链企业披露新一轮融资。"
    assert items[0].language == "zh"
    assert items[0].sourcecountry == "cn"


def test_fetch_daily_news_candidates_auto_uses_hotnews_when_no_keyed_provider(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.delenv("NEWS_CANDIDATES_FILE", raising=False)
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_TOKEN", raising=False)
    monkeypatch.delenv("JUHE_NEWS_APPKEY", raising=False)
    monkeypatch.delenv("JUHE_FINANCE_NEWS_APPKEY", raising=False)
    monkeypatch.setattr(daily_news, "_load_newsapi_config", lambda: (_ for _ in ()).throw(RuntimeError("missing newsapi")))
    monkeypatch.setattr(daily_news, "_load_gnews_config", lambda: (_ for _ in ()).throw(RuntimeError("missing gnews")))
    monkeypatch.setattr(daily_news, "_load_juhe_config", lambda: (_ for _ in ()).throw(RuntimeError("missing juhe")))
    monkeypatch.setattr(daily_news, "_default_news_queries", lambda: ["technology", "world"])
    calls = []

    def fake_hotnews_fetch_articles(**kwargs):
        calls.append(kwargs)
        return [
            NewsItem(
                title="国内AI治理规则更新",
                url="https://example.cn/ai-governance",
                source="hotnews:jinritoutiao",
                domain="example.cn",
                seendate="2026-06-29T08:00:00Z",
                description="相关部门披露AI治理规则更新。",
                language="zh",
                sourcecountry="cn",
            )
        ]

    monkeypatch.setattr(daily_news, "_hotnews_fetch_articles", fake_hotnews_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("", max_records=5)

    assert candidates[0].title == "国内AI治理规则更新"
    assert meta["provider"] == "hotnews"
    assert meta["api_source"] == "hotnews"
    assert meta["provider_plan"] == ["hotnews"]
    assert meta["provider_attempts"] == ["hotnews"]
    assert meta["source_api"]["provider"] == "hotnews"
    assert meta["source_api"]["base_url"] == "https://orz.ai/api/v1/dailynews"
    assert calls[0]["platforms"]
    assert len(calls) == 1


def test_fetch_daily_news_candidates_auto_uses_hotnews_after_keyed_provider_failure(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.delenv("NEWS_CANDIDATES_FILE", raising=False)
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_TOKEN", raising=False)
    monkeypatch.delenv("JUHE_NEWS_APPKEY", raising=False)
    monkeypatch.delenv("JUHE_FINANCE_NEWS_APPKEY", raising=False)
    monkeypatch.setattr(daily_news, "_load_gnews_config", lambda: (_ for _ in ()).throw(RuntimeError("missing gnews")))
    monkeypatch.setattr(daily_news, "_load_juhe_config", lambda: (_ for _ in ()).throw(RuntimeError("missing juhe")))

    def fake_newsapi_fetch_articles(**_kwargs):
        raise TimeoutError("newsapi timed out")

    def fake_hotnews_fetch_articles(**_kwargs):
        return [
            NewsItem(
                title="国际科技企业发布新服务",
                url="https://example.com/tech-service",
                source="hotnews:hackernews",
                domain="example.com",
                seendate="2026-06-29T09:00:00Z",
                description="一家科技企业发布新服务。",
                language="en",
            )
        ]

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fake_newsapi_fetch_articles)
    monkeypatch.setattr(daily_news, "_hotnews_fetch_articles", fake_hotnews_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("technology", max_records=5, timeout_s=1)

    assert candidates[0].title == "国际科技企业发布新服务"
    assert meta["provider"] == "hotnews"
    assert meta["provider_plan"] == ["newsapi", "hotnews"]
    assert meta["provider_attempts"] == ["newsapi", "hotnews"]
    assert any("newsapi timed out" in err for err in meta["provider_errors"])


def test_fetch_daily_news_candidates_auto_does_not_fallback_to_gdelt(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_TOKEN", raising=False)
    monkeypatch.setattr(daily_news, "_load_gnews_config", lambda: (_ for _ in ()).throw(RuntimeError("missing gnews")))
    monkeypatch.setattr(daily_news, "_load_juhe_config", lambda: (_ for _ in ()).throw(RuntimeError("missing juhe")))

    def fake_newsapi_fetch_articles(**_kwargs):
        raise RuntimeError("newsapi timeout")

    def fake_gdelt_fetch_articles(**_kwargs):
        raise AssertionError("gdelt should not be called")

    def fake_hotnews_fetch_articles(**_kwargs):
        return [
            NewsItem(
                title="Hot fallback headline",
                url="https://example.com/hot-fallback",
                source="hotnews:jinritoutiao",
                domain="example.com",
                description="HotNews fallback item.",
            )
        ]

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fake_newsapi_fetch_articles)
    monkeypatch.setattr(daily_news, "_gdelt_fetch_articles", fake_gdelt_fetch_articles, raising=False)
    monkeypatch.setattr(daily_news, "_hotnews_fetch_articles", fake_hotnews_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("technology", max_records=5)

    assert candidates[0].title == "Hot fallback headline"
    assert meta["provider"] == "hotnews"
    assert "gdelt" not in meta["provider_plan"]
    assert "gdelt" not in meta["provider_attempts"]


def test_news_provider_gdelt_is_no_longer_supported(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "gdelt")

    with pytest.raises(RuntimeError, match="unsupported NEWS_PROVIDER='gdelt'"):
        daily_news.fetch_daily_news_candidates("", max_records=1, timeout_s=0.01)


def test_default_news_queries_without_prompt_are_not_single_china(monkeypatch):
    monkeypatch.delenv("NEWS_QUERY_DEFAULT", raising=False)

    queries = daily_news._default_news_queries()

    assert len(queries) >= 4
    assert queries != ["china"]
    assert "china" not in [q.lower() for q in queries]


def test_fetch_daily_news_candidates_without_prompt_aggregates_default_queries(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "gnews")
    monkeypatch.setenv("GNEWS_API_KEY", "fake-gnews-key")
    monkeypatch.delenv("NEWS_QUERY_DEFAULT", raising=False)
    monkeypatch.setattr(daily_news, "_default_news_queries", lambda: ["technology", "world"])
    calls: list[str] = []

    def fake_gnews_fetch_articles(**kwargs):
        query = kwargs["query"]
        calls.append(query)
        return [
            NewsItem(
                title=f"{query.title()} headline",
                url=f"https://example.com/{query}",
                source="Example",
                domain="example.com",
                seendate="20260619080000",
            )
        ]

    monkeypatch.setattr(daily_news, "_gnews_fetch_articles", fake_gnews_fetch_articles)

    candidates, meta = daily_news.fetch_daily_news_candidates("", max_records=10)

    assert calls == ["technology", "world"]
    assert [item.title for item in candidates] == ["Technology headline", "World headline"]
    assert meta["query_variants"] == ["technology", "world"]
    assert meta["queries_used"] == ["technology", "world"]


def test_fetch_daily_news_candidates_with_prompt_uses_default_fallback_without_name_error(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "newsapi")
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.setattr(daily_news, "_maybe_translate_hint_to_en", lambda _hint: "technology")

    def fake_newsapi_fetch_articles(**kwargs):
        if kwargs["query"] == "technology":
            return [
                NewsItem(
                    title="AI chip company announces new production plan",
                    url="https://example.com/ai-chip",
                    domain="example.com",
                    seendate="2026-06-19T00:00:00Z",
                )
            ]
        return []

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fake_newsapi_fetch_articles)

    candidates, meta = daily_news.fetch_daily_news_candidates("科技", max_records=5)

    assert candidates[0].title == "AI chip company announces new production plan"
    assert "technology" in meta["queries_used"]


def test_fetch_daily_news_candidates_with_multi_prompt_aggregates_query_variants(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "newsapi")
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.delenv("NEWS_QUERY_DEFAULT", raising=False)
    calls: list[str] = []

    def fake_newsapi_fetch_articles(**kwargs):
        query = kwargs["query"]
        calls.append(query)
        if query == "世界杯 体育 足球":
            return [
                NewsItem(
                    title="Old combined query story",
                    url="https://example.com/old-combined",
                    domain="example.com",
                    seendate="2026-06-01T00:00:00Z",
                    description="Old World Cup story.",
                )
            ]
        if query == "世界杯":
            return [
                NewsItem(
                    title="世界杯赞助商发布最新球迷活动",
                    url="https://example.com/world-cup-fresh",
                    domain="example.com",
                    seendate=_recent_news_seendate(0),
                    description="这是一条三日内的世界杯体育足球新闻。",
                )
            ]
        return []

    monkeypatch.setattr(daily_news, "_newsapi_fetch_articles", fake_newsapi_fetch_articles)

    candidates, meta = daily_news.fetch_daily_news_candidates("世界杯 体育 足球", max_records=10)

    assert "世界杯 体育 足球" in calls
    assert "世界杯" in calls
    assert any(item.url == "https://example.com/world-cup-fresh" for item in candidates)
    assert "世界杯" in meta["queries_used"]


def test_fetch_daily_news_candidates_gnews_provider_maps_articles(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "gnews")
    monkeypatch.setenv("GNEWS_API_KEY", "fake-gnews-key")

    def fake_gnews_fetch_articles(**kwargs):
        assert kwargs["api_key"] == "fake-gnews-key"
        assert kwargs["query"] == "technology"
        return [
            NewsItem(
                title="AI startup launches new safety tool",
                url="https://example.com/ai-safety",
                source="Example News",
                domain="example.com",
                seendate="2026-06-19T01:02:03Z",
                description="A technology company launched an AI safety tool.",
            )
        ]

    monkeypatch.setattr(daily_news, "_gnews_fetch_articles", fake_gnews_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("technology", max_records=5)

    assert candidates[0].title == "AI startup launches new safety tool"
    assert meta["provider"] == "gnews"
    assert "gnews" in meta["provider_attempts"]


def test_fetch_daily_news_candidates_juhe_toutiao_maps_articles_and_detail(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "juhe")
    monkeypatch.setenv("JUHE_NEWS_APPKEY", "fake-juhe-news-key")
    monkeypatch.delenv("JUHE_FINANCE_NEWS_APPKEY", raising=False)

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_juhe_request_json(*, url, params, timeout_s):
        calls.append((url, params))
        assert timeout_s == 1
        if url.endswith("/index"):
            assert params["key"] == "fake-juhe-news-key"
            assert params["type"] == "keji"
            return {
                "error_code": 0,
                "result": {
                    "data": [
                        {
                            "title": "AI chip supply chain update",
                            "url": "https://example.cn/aichip",
                            "author_name": "Example News",
                            "date": "2026-06-21 08:00:00",
                            "category": "keji",
                            "thumbnail_pic_s": "https://example.cn/a.jpg",
                            "uniquekey": "abc123",
                            "is_content": "1",
                        }
                    ]
                },
            }
        if url.endswith("/content"):
            assert params["key"] == "fake-juhe-news-key"
            assert params["uniquekey"] == "abc123"
            return {
                "error_code": 0,
                "result": {
                    "content": "Full source article content from Juhe detail endpoint.",
                    "detail": {
                        "title": "AI chip supply chain update",
                        "url": "https://example.cn/aichip",
                    },
                },
            }
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(daily_news, "_juhe_request_json", fake_juhe_request_json, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("technology", max_records=5, timeout_s=1)

    assert candidates[0].title == "AI chip supply chain update"
    assert candidates[0].content == "Full source article content from Juhe detail endpoint."
    assert candidates[0].source == "Example News"
    assert candidates[0].domain == "example.cn"
    assert candidates[0].socialimage == "https://example.cn/a.jpg"
    assert meta["provider"] == "juhe"
    assert calls[0][0].endswith("/index")
    assert calls[1][0].endswith("/content")


def test_fetch_daily_news_candidates_juhe_uses_finance_endpoint_for_business_query(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "juhe")
    monkeypatch.setenv("JUHE_NEWS_APPKEY", "fake-juhe-news-key")
    monkeypatch.setenv("JUHE_FINANCE_NEWS_APPKEY", "fake-juhe-finance-key")

    def fake_juhe_request_json(*, url, params, timeout_s):
        assert url.endswith("/query")
        assert params["key"] == "fake-juhe-finance-key"
        assert params["num"] == "5"
        return {
            "error_code": 0,
            "result": {
                "list": [
                    {
                        "title": "Listed company reports quarterly revenue growth",
                        "url": "https://finance.example.cn/report",
                        "source": "Finance Example",
                        "content": "The company reported revenue growth in the quarter.",
                        "ctime": "2026-06-21 09:30:00",
                        "picUrl": "https://finance.example.cn/img.jpg",
                    }
                ]
            },
        }

    monkeypatch.setattr(daily_news, "_juhe_request_json", fake_juhe_request_json, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("business", max_records=5, timeout_s=1)

    assert candidates[0].title == "Listed company reports quarterly revenue growth"
    assert candidates[0].source == "Finance Example"
    assert candidates[0].content == "The company reported revenue growth in the quarter."
    assert candidates[0].domain == "finance.example.cn"
    assert meta["provider"] == "juhe"


def test_fetch_daily_news_candidates_auto_uses_juhe_when_other_keys_missing(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_TOKEN", raising=False)
    monkeypatch.setenv("JUHE_NEWS_APPKEY", "fake-juhe-news-key")
    monkeypatch.setattr(daily_news, "_load_newsapi_config", lambda: (_ for _ in ()).throw(RuntimeError("missing newsapi")))
    monkeypatch.setattr(daily_news, "_load_gnews_config", lambda: (_ for _ in ()).throw(RuntimeError("missing gnews")))

    def fake_juhe_fetch_articles(**kwargs):
        assert kwargs["news_key"] == "fake-juhe-news-key"
        return [
            NewsItem(
                title="Domestic science program reaches milestone",
                url="https://example.cn/science",
                source="Example",
                domain="example.cn",
                seendate="2026-06-21 08:00:00",
            )
        ]

    monkeypatch.setattr(daily_news, "_juhe_fetch_articles", fake_juhe_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("science", max_records=5)

    assert candidates[0].title == "Domestic science program reaches milestone"
    assert meta["provider_attempts"] == ["juhe"]


def test_juhe_provider_errors_do_not_leak_appkey(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDER", "juhe")
    monkeypatch.setenv("JUHE_NEWS_APPKEY", "super-secret-juhe-key")

    def fake_juhe_request_json(*, url, params, timeout_s):
        raise RuntimeError("Juhe request failed")

    monkeypatch.setattr(daily_news, "_juhe_request_json", fake_juhe_request_json, raising=False)

    with pytest.raises(RuntimeError) as exc:
        daily_news.fetch_daily_news_candidates("technology", max_records=5)

    message = str(exc.value)
    assert "Juhe request failed" in message
    assert "super-secret-juhe-key" not in message


def test_fetch_daily_news_candidates_auto_uses_gnews_when_newsapi_missing(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.setenv("GNEWS_API_KEY", "fake-gnews-key")
    monkeypatch.setattr(daily_news, "_load_newsapi_config", lambda: (_ for _ in ()).throw(RuntimeError("missing newsapi")))

    def fake_gnews_fetch_articles(**_kwargs):
        return [
            NewsItem(
                title="Climate policy update",
                url="https://example.com/climate",
                source="Example",
                domain="example.com",
                seendate="2026-06-19T01:02:03Z",
            )
        ]

    monkeypatch.setattr(daily_news, "_gnews_fetch_articles", fake_gnews_fetch_articles, raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates("climate", max_records=5)

    assert candidates[0].title == "Climate policy update"
    assert meta["provider_attempts"][0] == "gnews"


def test_fetch_daily_news_candidates_file_provider_reads_json(monkeypatch, tmp_path):
    news_file = tmp_path / "news.json"
    news_file.write_text(
        """
        {
          "items": [
            {
              "title": "科技公司发布新芯片",
              "url": "https://example.com/chip",
              "source": "Example News",
              "description": "一家科技公司发布面向AI应用的新芯片。",
              "published_at": "2026-06-19"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWS_PROVIDER", "file")
    monkeypatch.setenv("NEWS_CANDIDATES_FILE", str(news_file))

    candidates, meta = daily_news.fetch_daily_news_candidates("科技", max_records=5)

    assert candidates[0].title == "科技公司发布新芯片"
    assert candidates[0].domain == "example.com"
    assert meta["provider"] == "file"


def test_parse_manual_news_materials_reads_markdown_blocks():
    text = """
    标题：央行发布支付便利化新举措
    时间：2026-07-05 09:30
    来源：中国新闻网
    链接：https://example.cn/payments
    热度：8765
    内容：央行表示将优化重点场景支付服务，提升境内外人员支付便利性。

    ---

    新闻：国际足联公布世界杯票务安排
    发布时间：2026-07-04
    来源：新华社
    url: https://example.cn/worldcup
    摘要：世界杯相关票务安排发布，多个阶段将分批开放申请。
    正文：赛事组织方提醒球迷关注官方渠道。
    """

    items = parse_manual_news_materials(text)

    assert [item.title for item in items] == ["央行发布支付便利化新举措", "国际足联公布世界杯票务安排"]
    assert items[0].source == "中国新闻网"
    assert items[0].seendate == "2026-07-05 09:30"
    assert items[0].domain == "example.cn"
    assert items[0].attention == 8765
    assert "重点场景支付服务" in (items[0].content or "")
    assert items[1].description == "世界杯相关票务安排发布，多个阶段将分批开放申请。"


def test_load_manual_news_materials_file_reads_json_aliases(tmp_path):
    news_file = tmp_path / "manual_news.json"
    news_file.write_text(
        json.dumps(
            {
                "news": [
                    {
                        "新闻": "国内算力项目落地西部园区",
                        "时间": "2026-07-05",
                        "来源": "证券时报",
                        "链接": "https://example.cn/compute",
                        "正文": "项目将服务AI训练和产业数字化场景。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = load_manual_news_materials_file(news_file, max_records=5)

    assert len(items) == 1
    assert items[0].title == "国内算力项目落地西部园区"
    assert items[0].source == "证券时报"
    assert items[0].content == "项目将服务AI训练和产业数字化场景。"


def test_load_manual_news_materials_file_reads_jsonl(tmp_path):
    news_file = tmp_path / "manual_news.jsonl"
    news_file.write_text(
        "\n".join(
            [
                json.dumps({"标题": "暑期文旅市场热度上升", "时间": "2026-07-05", "来源": "央视新闻"}, ensure_ascii=False),
                json.dumps({"标题": "体育赛事带动周边消费", "时间": "2026-07-05", "来源": "人民网"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    items = load_manual_news_materials_file(news_file, max_records=10)

    assert [item.title for item in items] == ["暑期文旅市场热度上升", "体育赛事带动周边消费"]


def test_load_single_news_material_file_requires_exactly_one_item(tmp_path):
    news_file = tmp_path / "single_news.md"
    news_file.write_text(
        """
        title: Central bank announces payment policy update
        time: 2026-01-05 09:30
        source: Example News
        url: https://example.com/payment-policy
        content: The central bank announced a policy update with details for payment services.
        """,
        encoding="utf-8",
    )

    item = load_single_news_material_file(news_file)

    assert item.title == "Central bank announces payment policy update"
    assert item.source == "Example News"
    assert item.seendate == "2026-01-05 09:30"
    assert item.domain == "example.com"

    multi_file = tmp_path / "multi_news.md"
    multi_file.write_text(
        """
        title: First item
        content: first body
        ---
        title: Second item
        content: second body
        """,
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="single news material file must contain exactly one"):
        load_single_news_material_file(multi_file)


def test_fetch_daily_news_candidates_uses_manual_materials_file(monkeypatch, tmp_path):
    news_file = tmp_path / "manual_news.md"
    news_file.write_text(
        f"""
        标题：体育品牌公布世界杯合作计划
        时间：{_recent_news_date()}
        来源：界面新闻
        链接：https://example.cn/worldcup-brand
        内容：一家体育品牌围绕世界杯推出合作计划，覆盖门店活动和线上互动。
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.delenv("NEWS_CANDIDATES_FILE", raising=False)

    candidates, meta = daily_news.fetch_daily_news_candidates(
        "世界杯 品牌",
        max_records=5,
        materials_file=str(news_file),
    )

    assert candidates[0].title == "体育品牌公布世界杯合作计划"
    assert meta["provider"] == "manual"
    assert meta["source_api"]["file_path"] == str(news_file)
    assert meta["manual_materials"]["count"] == 1


def test_daily_news_upload_passes_manual_materials_file_to_fetcher(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    materials_file = tmp_path / "manual_news.md"
    materials_file.write_text("标题：测试新闻\n时间：2026-07-05\n来源：测试源\n内容：测试内容", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_fetch(_prompt, **kwargs):
        seen.update(kwargs)
        return [
            NewsItem(
                title="测试新闻",
                url="manual://测试新闻",
                source="测试源",
                domain="manual.local",
                seendate=_recent_news_seendate(0),
                description="测试内容",
                content="测试内容",
            )
        ], {"provider": "manual", "tz": "Asia/Shanghai"}

    monkeypatch.setattr(create_post, "fetch_daily_news_candidates", fake_fetch)

    candidates, meta = create_post._fetch_daily_news_candidates_for_upload(
        "测试",
        count=1,
        news_materials_file=str(materials_file),
    )

    assert candidates[0].title == "测试新闻"
    assert seen["materials_file"] == str(materials_file)
    assert meta["selection_pool"]["raw_candidate_count"] == 1


def test_fetch_single_daily_news_candidate_ignores_prompt_and_lookback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    news_file = tmp_path / "single_news.md"
    news_file.write_text(
        """
        title: Single material policy story
        time: 2026-01-05
        source: Example News
        url: https://example.com/single-policy-story
        content: A complete single news material that should be used directly.
        """,
        encoding="utf-8",
    )

    candidates, meta = create_post._fetch_daily_news_candidates_for_upload(
        "sports football prompt that does not match",
        count=8,
        lookback_days=3,
        single_news_material_file=str(news_file),
    )

    assert [item.title for item in candidates] == ["Single material policy story"]
    assert meta["provider"] == "manual_single"
    assert meta["selection_pool"]["requested_count"] == 1
    assert meta["selection_pool"]["target_fetch_count"] == 1
    assert meta["selection_pool"]["lookback"]["mode"] == "ignored_for_single_news_material"
    assert meta["selection_pool"]["prompt_relevance"]["mode"] == "ignored_for_single_news_material"


def test_single_news_material_prefers_ai_image_before_pexels(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMAGE_PROVIDER", "pexels")
    news_file = tmp_path / "single_news.md"
    news_file.write_text(
        """
        标题：社交巨头拟出租算力引发市场波动
        时间：2026-07-05
        来源：证券时报
        链接：https://example.com/meta-compute
        内容：社交巨头拟把闲置人工智能算力对外出租，市场重新评估人工智能基建公司的增长预期。
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "社交巨头出租算力引发市场震荡",
            "body": _test_daily_news_body(
                original_title="社交巨头拟出租算力引发市场波动",
                content="社交巨头拟将闲置人工智能算力对外出租，引发市场对人工智能基建资产利用率的重新定价。",
                comment="这说明人工智能基建投资开始从扩张叙事进入现金流验证阶段。",
                date="2026-07-05",
                source="证券时报",
            ),
            "topics": ["每日新闻", "人工智能"],
            "image_event": "社交巨头人工智能算力出租引发市场波动",
        }

    providers: list[str | None] = []

    def fake_images(*, dest_dir, provider=None, **_kwargs):
        providers.append(provider)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"{provider or 'none'}.jpg"
        out.write_bytes(b"image")
        return [out], [{"provider": provider, "mode": "auto_image"}]

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(create_post, "fetch_and_download_related_images", fake_images)

    posts = create_post.create_daily_news_posts(
        prompt_hint="should be ignored",
        asset_paths=[],
        count=9,
        auto_image=True,
        single_news_material_file=str(news_file),
    )

    assert len(posts) == 1
    assert providers == ["aliyun"]
    assert posts[0].platform["images"][0]["provider"] == "aliyun"


def test_single_news_material_falls_back_to_pexels_when_ai_image_fails(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    news_file = tmp_path / "single_news.md"
    news_file.write_text(
        """
        标题：社交巨头拟出租算力引发市场波动
        时间：2026-07-05
        来源：证券时报
        链接：https://example.com/meta-compute
        内容：社交巨头拟把闲置人工智能算力对外出租，市场重新评估人工智能基建公司的增长预期。
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: [LLMConfig(model="fake", api_key="fake-key", base_url="https://example.com")],
    )

    def fake_generate_draft(*_args, **_kwargs):
        return {
            "title": "社交巨头出租算力引发市场震荡",
            "body": _test_daily_news_body(
                original_title="社交巨头拟出租算力引发市场波动",
                content="社交巨头拟将闲置人工智能算力对外出租，引发市场对人工智能基建资产利用率的重新定价。",
                comment="这说明人工智能基建投资开始从扩张叙事进入现金流验证阶段。",
                date="2026-07-05",
                source="证券时报",
            ),
            "topics": ["每日新闻", "人工智能"],
            "image_event": "社交巨头人工智能算力出租引发市场波动",
        }

    providers: list[str | None] = []

    def fake_images(*, dest_dir, provider=None, **_kwargs):
        providers.append(provider)
        if provider == "aliyun":
            raise ImageGenerationAbandoned(provider="aliyun", attempts=3, errors=["timed out"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "pexels.jpg"
        out.write_bytes(b"image")
        return [out], [{"provider": provider, "mode": "auto_image"}]

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)
    monkeypatch.setattr(create_post, "fetch_and_download_related_images", fake_images)

    posts = create_post.create_daily_news_posts(
        prompt_hint="should be ignored",
        asset_paths=[],
        count=1,
        auto_image=True,
        single_news_material_file=str(news_file),
    )

    assert len(posts) == 1
    assert providers == ["aliyun", "pexels"]
    assert posts[0].platform["images"][0]["provider"] == "pexels"
    assert posts[0].platform["image_fallback"]["from_provider"] == "aliyun"
    assert posts[0].platform["image_fallback"]["to_provider"] == "pexels"


def test_normalize_news_url_key_removes_tracking_params_and_fragment():
    assert normalize_news_url_key(
        "HTTPS://Example.com/news/123/?utm_source=x&b=2&a=1#comments"
    ) == "https://example.com/news/123?a=1&b=2"


def test_fetch_daily_news_candidates_skips_urls_used_by_previous_posts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    old_post_dir = tmp_path / "data" / "posts" / "old"
    old_post_dir.mkdir(parents=True)
    old_post_dir.joinpath("post.json").write_text(
        """
        {
          "id": "old",
          "title": "Old news",
          "platform": {
            "news": {
              "source_url": "https://example.com/news/123?utm_source=old",
              "picked": {
                "url": "https://example.com/news/123?utm_source=old"
              }
            }
          }
        }
        """,
        encoding="utf-8",
    )
    news_file = tmp_path / "news.json"
    news_file.write_text(
        """
        {
          "items": [
            {
              "title": "Duplicate news",
              "url": "https://example.com/news/123?utm_campaign=new#section",
              "source": "Example"
            },
            {
              "title": "Fresh news",
              "url": "https://example.com/news/456",
              "source": "Example"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("NEWS_PROVIDER", "file")
    monkeypatch.setenv("NEWS_CANDIDATES_FILE", str(news_file))

    candidates, meta = daily_news.fetch_daily_news_candidates("", max_records=10)

    assert [item.title for item in candidates] == ["Fresh news"]
    assert meta["history_dedupe"]["enabled"] is True
    assert meta["history_dedupe"]["skipped_count"] == 1


def test_create_daily_news_posts_raises_when_all_news_sources_fail(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [])
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: (_ for _ in ()).throw(RuntimeError("no news returned")),
    )
    generate_called = False

    def fake_generate_draft(*_args, **_kwargs):
        nonlocal generate_called
        generate_called = True
        return {"title": "每日新闻", "body": "should not be used", "topics": []}

    monkeypatch.setattr(create_post, "generate_draft", fake_generate_draft)

    with pytest.raises(RuntimeError, match="no news returned"):
        create_post.create_daily_news_posts(
            prompt_hint="科技",
            asset_paths=[],
            count=5,
            auto_image=False,
        )

    assert generate_called is False
    assert not (tmp_path / "data" / "posts").exists()


def test_pick_news_items_prefers_cross_domain_duplicates():
    items = [
        NewsItem(title="Event Other Topic", url="https://b.com/1"),
        NewsItem(title="Event Alpha Beta", url="https://a.com/1"),
        NewsItem(title="Event Alpha Beta", url="https://c.com/1"),
    ]
    picked = pick_news_items(items, "", count=1)
    assert picked[0].title == "Event Alpha Beta"


def test_pick_best_news_boosts_cross_domain_matches():
    items = [
        NewsItem(title="Event Alpha Beta", url="https://a.com/1", seendate="20250101T000000Z"),
        NewsItem(title="Event Alpha Beta", url="https://b.com/1", seendate="20250102T000000Z"),
        NewsItem(title="Event Alpha Gamma", url="https://c.com/1", seendate="20250103T000000Z"),
    ]
    picked = pick_best_news(items, "Event Alpha")
    assert picked.url == "https://b.com/1"


def test_append_news_source_line_is_last_line():
    picked = NewsItem(title="A", url="https://example.com/a", source="Example")
    body = "News content\n\nMy comment"
    out = _append_news_source_line(body, picked)
    assert out.splitlines()[-1] == "来源：Example"
    assert "https://example.com/a" not in out


def test_finalize_daily_news_body_clamps_without_breaking_json():
    picked = NewsItem(
        title="Global chip company announces new AI accelerator",
        url="https://example.com/source",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
        description="The chip company said the product targets inference workloads.",
    )
    long_content = "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景，并强调能效和部署成本。" * 30
    body = (
        "要点摘要：AI芯片企业发布新品，强调推理算力与能效提升。\n"
        "新闻内容：\n"
        f"{long_content}\n\n"
        "点评：\n"
        "AI芯片竞争会继续影响算力供给和应用成本，关键是技术指标能否转化为稳定供应。\n\n"
        "发布时间：2026-06-19\n\n"
        "来源：Example News https://example.com/source"
    )

    out = _finalize_daily_news_body(body, picked, "科技新闻")
    data = _daily_news_body_fields(out)

    assert len(out) <= 1000
    assert data["来源"] == "Example News"
    assert data["日期"] == "2026-06-19"
    assert len(data["内容"]) <= 150


def test_limit_daily_news_content_drops_incomplete_tail_sentence():
    text = (
        "新华社消息显示，美伊谈判在即。"
        "新华社报道，美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。"
        "瑞士外交部20日称伊朗代表团已抵达"
    )

    out = _limit_daily_news_content(text)

    assert out.endswith("。")
    assert "瑞士外交部20日称伊朗代表团已抵达" not in out
    assert len(out) <= 150


def test_limit_daily_news_content_removes_source_boilerplate_and_duplicate_fact():
    text = (
        "新华网消息显示，美国康涅狄格州枪击事件致2死1伤。"
        "新华网报道，美国康涅狄格州西黑文市一家酒吧外发生枪击事件，造成两人死亡、一人受伤。"
        "新华社纽约6月20日电（记者施春）据当地警方消息，美国康涅狄格州西黑文市一家酒吧外20日凌晨发生枪击事件，造成两人死亡、一人受伤。"
    )

    out = _limit_daily_news_content(text)

    assert "消息显示" not in out
    assert "新华社纽约6月20日电" not in out
    assert out.count("造成两人死亡") == 1
    assert "20日凌晨" in out
    assert len(out) <= 150


def test_limit_daily_news_content_replaces_cjk_sentence_space_with_period():
    out = _limit_daily_news_content("伊朗代表团已抵达瑞士 美伊谈判在即。瑞士外交部称代表团已抵达。")

    assert "瑞士 美伊" not in out
    assert "抵达美伊" not in out
    assert "。美伊谈判在即" in out


def test_limit_daily_news_content_dedupes_non_adjacent_repeated_sentence():
    text = (
        "美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。"
        "美伊谈判在即。"
        "美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。"
        "瑞士外交部20日称伊朗代表团已抵达。"
    )

    out = _limit_daily_news_content(text)

    assert out.count("美国副总统万斯启程前往瑞士") == 1
    assert len(out) <= 150


def test_limit_daily_news_content_removes_photo_credit_tail():
    out = _limit_daily_news_content("瑞士外交部20日在社交平台上发文欢迎伊朗代表团抵达瑞士。摄。新华社/美联社。")

    assert not out.endswith("摄。")
    assert "新华社/美联社" not in out
    assert out.endswith("瑞士。")


def test_limit_daily_news_content_removes_standalone_photo_agency_tail():
    out = _limit_daily_news_content("瑞士外交部20日在社交平台上发文欢迎伊朗代表团抵达瑞士。新华社/美联社。")

    assert "新华社/美联社" not in out
    assert out == "瑞士外交部20日在社交平台上发文欢迎伊朗代表团抵达瑞士。"


def test_limit_daily_news_content_removes_xinhua_photo_caption_credit():
    text = (
        "美国洛杉矶市一处大型商业仓储设施火灾持续数日并产生大量刺激性烟雾，洛杉矶市长宣布该市进入紧急状态。"
        "新华社发（曾慧摄） 巴斯当天表示，宣布紧急状态是为确保洛杉矶应对灾情期间获得所需资源并保障社区安全。"
    )

    out = _limit_daily_news_content(text)

    assert "新华社发" not in out
    assert "曾慧摄" not in out
    assert "保障社区安全" in out


def test_limit_daily_news_content_removes_broken_xinhua_dateline_fragments():
    text = (
        "李林欣）由日本有识之士组成的“中国文物返还运动推进会”20日在东京举行研讨会，"
        "呼吁日本政府正视侵略历史，返还战争期间从中国掠夺的文物。"
        "新华社东京6月20日电（记者李子越。"
    )

    out = _limit_daily_news_content(text)

    assert "李林欣）" not in out
    assert "新华社东京" not in out
    assert "记者李子越" not in out
    assert out.startswith("由日本有识之士组成")
    assert "返还战争期间从中国掠夺的文物" in out


def test_limit_daily_news_content_removes_audio_column_noise_and_broken_tail():
    text = (
        "∙ 能见度 > 听全文。从光伏组件、风机、逆变器，再到储能PCS，欧美对中国清洁能源及储能产品的贸易保护正加速。"
        "海外市场复杂多变。陆川对澎湃新闻表示，全球范围内，纯光伏项目已日益稀少，光储一体化正成为海外市场的主流形态。"
        "昨天，第二。"
    )

    out = _limit_daily_news_content(text)

    assert "听全文" not in out
    assert "能见度" not in out
    assert "活力。昨天，第二" not in out
    assert "海外市场复杂多变" in out


def test_limit_daily_news_content_removes_short_repeated_broken_tail_with_period():
    text = (
        "昨天，第二十四届中国·海峡创新项目成果交易会（简称“海创会”）在福州圆满落下帷幕，我市除在厦门展区展示了10家重点产业领域的代表企业与创新平台外，"
        "还有多家企业亮相海创会的未来产业典型应用场景专区、推动科技创新和产业创新深度融合重大成果展等展区，全方位展示厦门科技创新实力与产业创新活力。昨天，第二。"
    )

    out = _limit_daily_news_content(text)

    assert "活力。昨天，第二" not in out
    assert out.endswith("产业创新活力。")


def test_limit_daily_news_content_removes_local_site_reporter_byline():
    text = (
        "厦门网讯（厦门日报记者。近日，新海达码头流动机械360度全景监控系统正式投用，"
        "以科技赋能筑牢港区安全防线。码头流动机械作业环境复杂，车身盲区大。"
    )

    out = _limit_daily_news_content(text)

    assert "厦门网讯" not in out
    assert "厦门日报记者" not in out
    assert out.startswith("近日")


def test_limit_daily_news_content_removes_dateline_and_broken_quote_fragments():
    text = (
        "江南时报讯。正值毕业升学、端午、暑期消费黄金节点，记者从省商务厅了解到，"
        "6月18日，江苏正式发布“苏新消费·品。"
        "本次活动自2026年6月18日18时起正式启动，无固定截止日期，以补贴额度申领完毕为活动终止节点。"
    )

    out = _limit_daily_news_content(text)

    assert "江南时报讯" not in out
    assert "苏新消费·品" not in out
    assert "补贴额度" in out


def test_limit_daily_news_content_separates_brand_paragraph_after_standard_fragment():
    text = (
        "好奇品牌纸尿裤未检出“甲酰胺”成分，各项指标符合我国婴儿纸尿裤相关 "
        "Babycare发布回应称，已第一时间成立专项小组启动内部核查工作。"
    )

    out = _limit_daily_news_content(text)

    assert "相关 Babycare发布" not in out
    assert "相关标准。Babycare发布" in out


def test_finalize_daily_news_body_renders_json_as_publishable_text():
    picked = NewsItem(
        title="Global chip company announces new AI accelerator",
        url="https://example.com/source",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
    )
    body = json.dumps(
        {
            "原文标题": "AI芯片新品发布",
            "内容": "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景。",
            "评价": "AI芯片竞争会继续影响算力供给和应用成本。",
            "日期": "2026-06-19",
            "来源": "Example News",
        },
        ensure_ascii=False,
        indent=2,
    )

    out = _finalize_daily_news_body(body, picked, "科技新闻")

    assert not out.lstrip().startswith("{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
    assert "原文标题：AI芯片新品发布" not in out
    assert "内容：\n这家芯片企业披露新一代人工智能加速器" in out
    assert "评价：\nAI芯片竞争会继续影响算力供给" in out
    assert (
        out
        == "内容：\n"
        "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景。\n\n"
        "评价：\n"
        "AI芯片竞争会继续影响算力供给和应用成本。\n\n"
        "日期：2026-06-19\n\n"
        "来源：Example News"
    )
    assert "http" not in out


def test_finalize_daily_news_body_preserves_rendered_five_field_text():
    picked = NewsItem(
        title="Global chip company announces new AI accelerator",
        url="https://example.com/source",
        source="Example News",
        domain="example.com",
        seendate="2026-06-19T08:00:00Z",
    )
    body = (
        "原文标题：AI芯片新品发布\n\n"
        "内容：\n"
        "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景。\n\n"
        "评价：\n"
        "AI芯片竞争会继续影响算力供给和应用成本。\n\n"
        "日期：2026-06-19\n"
        "来源：Example News"
    )

    out = _finalize_daily_news_body(body, picked, "科技新闻")
    data = _daily_news_body_fields(out)

    assert "原文标题：" not in out
    assert data["内容"] == "这家芯片企业披露新一代人工智能加速器，重点面向推理计算场景。"
    assert data["评价"] == "AI芯片竞争会继续影响算力供给和应用成本。"
    assert data["日期"] == "2026-06-19"
    assert data["来源"] == "Example News"


def test_finalize_daily_news_body_strips_protocol_relative_image_urls():
    picked = NewsItem(
        title="浙江嘉兴开通至匈牙利布达佩斯国际货运航线",
        url="https://news.china.com.cn/example",
        source="news.china.com.cn",
        domain="news.china.com.cn",
        seendate="2026-06-20",
    )
    body = (
        "原文标题：浙江嘉兴开通至匈牙利布达佩斯国际货运航线\n\n"
        "内容：\n"
        "浙江嘉兴开通至匈牙利布达佩斯国际货运航线。"
        "//images.china.cn/site1000/2026-06/21/example.jpg\n\n"
        "评价：\n"
        "这类物流通道变化需要结合订单、政策和企业成本继续观察。\n\n"
        "日期：2026-06-20\n\n"
        "来源：news.china.com.cn"
    )

    out = _finalize_daily_news_body(body, picked, "国际物流")

    assert "//images.china.cn" not in out
    assert "example.jpg" not in out
    assert "内容：\n浙江嘉兴开通至匈牙利布达佩斯国际货运航线" in out


def test_finalize_daily_news_body_strips_broken_html_image_tag_from_json_fields():
    picked = NewsItem(
        title="昆山农商银行“员工六维全景画像”系统上线",
        url="https://example.com/bank-profile-system",
        source="江南时报",
        domain="jntimes.cn",
        seendate="2026-06-22 00:16:00",
        description="昆山农商银行员工六维全景画像系统上线，用于内部员工能力画像和管理支持。",
    )
    body = json.dumps(
        {
            "原文标题": "昆山农商银行“员工六维全景画像”系统上线",
            "内容": "<p > <img referrerpolicy='no-referrer' width='100%' src 昆山农商银行“员工六维全景画像”系统上线。",
            "评价": "",
            "日期": "2026-06-22 00:16:00",
            "来源": "江南时报",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "财经新闻")
    data = _daily_news_body_fields(out)

    assert "<p" not in out
    assert "<img" not in out
    assert "referrerpolicy" not in out
    assert "width=" not in out
    assert data["内容"] == "昆山农商银行“员工六维全景画像”系统上线。"
    assert _daily_news_quality_issue("昆山农商银行员工画像系统上线", out, "") == ""


def test_daily_news_quality_rejects_raw_html_artifacts():
    body = (
        "原文标题：昆山农商银行“员工六维全景画像”系统上线\n\n"
        "内容：\n<p > <img referrerpolicy='no-referrer' width='100%' src 昆山农商银行“员工六维全景画像”系统上线。\n\n"
        "日期：2026-06-22 00:16:00\n\n"
        "来源：江南时报"
    )

    assert _daily_news_quality_issue("昆山农商银行员工画像系统上线", body, "") == "body_html_artifacts"


def test_finalize_daily_news_body_replaces_21jingji_sidebar_noise_with_source_lead():
    picked = NewsItem(
        title="科技赋能 全国夏播粮食进度近七成",
        url="https://www.21jingji.com/article/example.html",
        source="21st Century Business Herald",
        domain="www.21jingji.com",
        seendate="2026-06-21",
        content=(
            "农业农村部最新农情调度显示，目前全国夏播粮食进度近七成。今年，粮食主产区大力推广种肥同播技术，"
            "有效提升种植质量。夏播粮食近七成，种肥同播助力提质增效。在山东邹平明集镇的高标准农田里，"
            "旋耕机、整地机、播种机接力奔跑。\n"
            "打开微信，点击底部的“发现”，使用“扫一扫”即可将网页分享至朋友圈。"
            "热文排行 1 证监会原副主席方星海：建议编制覆盖沪深港三地的中国指数。"
            "查看全部 --> 财经日历。今日要点。全球大事。每日智库看点。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "科技赋能 全国夏播粮食进度近七成",
            "内容": "中字头牛股年内大涨131% 6 伊朗军方宣布关闭霍尔木兹海峡｜21早新闻。查看全部 --> 财经日历。今日要点。",
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21",
            "来源": "21st Century Business Herald",
        },
        ensure_ascii=False,
    )

    context = create_post._compact_daily_news_context(picked, max_chars=150)
    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "夏播粮食" in context
    assert "财经日历" not in context
    assert "热文排行" not in context
    assert "夏播粮食" in data["内容"]
    assert "种肥同播" in data["内容"]
    assert "财经日历" not in data["内容"]
    assert "21早新闻" not in data["内容"]
    assert "AI 使用边界" not in data["评价"]
    assert "版权和信任" not in data["评价"]
    assert "粮食" in data["评价"] or "农业" in data["评价"]
    assert _daily_news_quality_issue("科技赋能 全国夏播粮食进度近七成", out, "") == ""


def test_daily_news_quality_rejects_sidebar_noise_in_rendered_body():
    body = (
        "原文标题：科技赋能 全国夏播粮食进度近七成\n\n"
        "内容：\n打开微信，点击底部的“发现”，使用“扫一扫”即可将网页分享至朋友圈。查看全部 --> 财经日历。今日要点。\n\n"
        "日期：2026-06-21\n\n"
        "来源：21st Century Business Herald"
    )

    assert _daily_news_quality_issue("科技赋能 全国夏播粮食进度近七成", body, "") == "body_site_noise"


def test_finalize_daily_news_body_replaces_mismatched_us_stock_comment_for_big_bay_area():
    picked = NewsItem(
        title="科创资源深度融合 前沿技术在大湾区加速落地",
        url="https://example.com/bay-tech",
        source="21st Century Business Herald",
        domain="example.com",
        seendate="2026-06-21",
        content=(
            "依托城市群区域协同一体化发展，粤港澳大湾区正在成为科技成果商业化应用的世界级高技术产业集聚区。"
            "在世界知识产权组织2025年发布的榜单上，深圳-香港-广州创新集群位列全球创新指数榜首。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "科创资源深度融合 前沿技术在大湾区加速落地",
            "内容": "科创资源深度融合。依托城市群区域协同一体化发展，粤港澳大湾区正在成为科技成果商业化应用的世界级高技术产业集聚区。",
            "评价": "美股科技资金快速流入说明市场风险偏好正在升温，但也意味着估值和波动压力同步累积。",
            "日期": "2026-06-21",
            "来源": "21st Century Business Herald",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "美股" not in data["评价"]
    assert "半导体设备" not in data["评价"]
    assert "大湾区" in data["评价"] or "科创" in data["评价"]
    assert _daily_news_quality_issue("大湾区前沿技术落地", out, "") == ""


def test_daily_news_quality_rejects_mismatched_us_stock_comment():
    body = (
        "原文标题：科创资源深度融合 前沿技术在大湾区加速落地\n\n"
        "内容：\n粤港澳大湾区正在成为科技成果商业化应用的高技术产业集聚区。\n\n"
        "评价：\n美股科技资金快速流入说明市场风险偏好正在升温，半导体设备股受 AI 需求拉动。\n\n"
        "日期：2026-06-21\n\n"
        "来源：21st Century Business Herald"
    )

    assert _daily_news_quality_issue("大湾区前沿技术落地", body, "") == "comment_mismatch"


def test_finalize_daily_news_body_uses_korea_tech_comment_not_us_stock_comment():
    picked = NewsItem(
        title="资金狂涌！全球科技升温，公募加速布局韩国赛道",
        url="https://example.com/korea-tech",
        source="21st Century Business Herald",
        domain="example.com",
        seendate="2026-06-20",
        content=(
            "全球科技产业互通背景下，投资者对韩股的需求刺激着基金公司持续加码布局。"
            "随着全球AI产业景气度持续攀升，韩国科技赛道以自身特色持续吸引全球跨境资金流入，基金公司推出韩国主题ETF。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "资金狂涌！全球科技升温，公募加速布局韩国赛道",
            "内容": "全球科技产业互通背景下，投资者对韩股的需求刺激着基金公司持续加码布局。",
            "评价": "美股科技资金快速流入说明市场风险偏好正在升温，半导体设备股受 AI 需求拉动。",
            "日期": "2026-06-20",
            "来源": "21st Century Business Herald",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "美股" not in data["评价"]
    assert "半导体设备" not in data["评价"]
    assert "韩国科技" in data["评价"] or "跨境基金" in data["评价"]
    assert _daily_news_quality_issue("全球资金布局韩国科技", out, "") == ""


def test_finalize_daily_news_body_strips_protocol_relative_urls_inside_json_fields():
    picked = NewsItem(
        title="浙江嘉兴开通至匈牙利布达佩斯国际货运航线",
        url="https://news.china.com.cn/example",
        source="news.china.com.cn",
        domain="news.china.com.cn",
        seendate="2026-06-20",
    )
    body = json.dumps(
        {
            "原文标题": "浙江嘉兴开通至匈牙利布达佩斯国际货运航线",
            "内容": (
                "浙江嘉兴开通至匈牙利布达佩斯国际货运航线。"
                "//images.china.cn/site1000/2026-06/21/example.jpg"
            ),
            "评价": "这类物流通道变化需要结合订单、政策和企业成本继续观察。",
            "日期": "2026-06-20",
            "来源": "news.china.com.cn",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际物流")

    assert not out.lstrip().startswith("{")
    assert "//images.china.cn" not in out
    assert "example.jpg" not in out
    assert "内容：\n浙江嘉兴开通至匈牙利布达佩斯国际货运航线" in out
    assert "\n\n日期：2026-06-20\n\n来源：news.china.com.cn" in out


def test_finalize_daily_news_body_limits_content_to_150_and_removes_generic_methodology():
    picked = NewsItem(
        title="公益宝贝科技兴农战略项目一周年 打造多元主体参与的产业发展服务生态",
        url="https://news.cau.edu.cn/example",
        source="news.cau.edu.cn",
        domain="news.cau.edu.cn",
        seendate="2026-06-20",
    )
    body = json.dumps(
        {
            "原文标题": "公益宝贝科技兴农战略项目一周年 打造多元主体参与的产业发展服务生态",
            "内容": (
                "原始来源消息显示，公益宝贝科技兴农战略项目一周年。"
                "目前可以确认的信息主要来自新闻标题、摘要和原文摘录，因此正文只整理已经出现的主体、动作和影响范围。"
                "若报道提到机构、企业或公共部门，更应区分其已公布安排与尚未发生的结果，避免把单一片段扩大成确定趋势。"
                "对读者来说，判断这条新闻时可以先看它影响的是民生服务、产业运行、公共安全还是国际关系。"
            ),
            "评价": "这类项目的价值需要看实际服务对象、协同机制和长期投入。",
            "日期": "2026-06-20",
            "来源": "news.cau.edu.cn",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "公益农业")
    data = _daily_news_body_fields(out)

    assert len(data["内容"]) <= 150
    assert "目前可以确认的信息主要来自" not in data["内容"]
    assert "对读者来说，判断这条新闻" not in data["内容"]
    assert "公益宝贝科技兴农战略项目一周年" in data["内容"]


def test_daily_news_quality_rejects_foreign_excerpt_title_and_limited_fallback_body():
    body = (
        "原文标题：原文摘录جامعة القاهرةنواصل التقدم في تصنيف U\n\n"
        "内容：\n"
        "在信息仍有限的情况下，读者可以先把它视为一个需要继续跟踪的进展，而不是已经定论的结果。\n\n"
        "日期：2026-06-21\n\n"
        "来源：shorouknews.com"
    )

    assert _daily_news_quality_issue("原文摘录جامعة القاهرةن", body, "") == "bad_title_language"


def test_daily_news_quality_rejects_missing_content_section():
    body = (
        "原文标题：财经聚焦｜多个重大水运工程缘何按下“快进键”\n\n"
        "日期：2026-06-21 09:59:57\n\n"
        "来源：澎湃新闻"
    )

    assert _daily_news_quality_issue("多项重大水运工程提速", body, "") == "missing_body_fields"


def test_daily_news_quality_rejects_incomplete_tail_title():
    body = (
        "原文标题：进账“一个比尔·盖茨”！马斯克行权获7800亿元账面收益\n\n"
        "内容：\n马斯克行使股票期权，账面收益约合人民币7840亿元。\n\n"
        "日期：2026-06-21 10:46:37\n\n"
        "来源：澎湃新闻"
    )

    assert _daily_news_quality_issue("进账“一个比尔·盖茨”！马斯克行权获", body, "") == "incomplete_title"


def test_finalize_daily_news_body_removes_site_navigation_noise_and_unrelated_ai_comment():
    picked = NewsItem(
        title="陳茂波 ： 香港是內地科企通往世界的門戶 - 香港",
        url="https://www.wenweipo.com/example",
        source="wenweipo.com",
        domain="wenweipo.com",
        seendate="2026-06-21",
        description="财政司司长陈茂波表示，香港是内地科企通往世界的门户。",
        content=(
            "财政司司长陈茂波在网志表示，内地科企正把香港作为连接国际市场、资本、治理、"
            "人才、研发和产供链的平台。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "陳茂波 ： 香港是內地科企通往世界的門戶 - 香港",
            "内容": (
                "小 6月21日，財政司司長陳茂波於網誌表示，對內地科企而言，香港是。"
                "普通話。廣東話。字號。超大。標準。香港是內地科企通往世界的門戶 - 香港。"
                "讓人印象深刻的是，相繼有科企管理人進一步表示，他們錨定的是發展成為跨國企業。"
            ),
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要。"
            ),
            "日期": "2026-06-21",
            "来源": "wenweipo.com",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际新闻")
    data = _daily_news_body_fields(out)

    assert "普通話" not in data["内容"]
    assert "廣東話" not in data["内容"]
    assert "字號" not in data["内容"]
    assert "超大" not in data["内容"]
    assert "標準" not in data["内容"]
    assert "AI 使用边界" not in data["评价"]
    assert "披露义务" not in data["评价"]


def test_finalize_daily_news_body_removes_thepaper_footer_and_rewrites_product_safety_comment():
    picked = NewsItem(
        title="碧芭宝贝：所有已检测纸尿裤产品甲酰胺项目结果均为未检出",
        url="https://www.thepaper.cn/example-diaper",
        source="澎湃新闻",
        domain="thepaper.cn",
        seendate="2026-06-21 10:59:40",
        description="碧芭宝贝称所有已检测纸尿裤产品甲酰胺项目结果均为未检出。",
        content="碧芭宝贝：所有已检测纸尿裤产品甲酰胺项目结果均为未检出_10%公司_澎湃新闻-The Paper 下载客户端。责任编辑： 王卉。",
    )
    body = json.dumps(
        {
            "原文标题": "碧芭宝贝：所有已检测纸尿裤产品甲酰胺项目结果均为未检出",
            "内容": "碧芭宝贝：所有已检测纸尿裤产品甲酰胺项目结果均为未检出_10%公司_澎湃新闻-The Paper 下载客户端。责任编辑： 王卉。",
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21 10:59:40",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "The Paper" not in data["内容"]
    assert "下载客户端" not in data["内容"]
    assert "责任编辑" not in data["内容"]
    assert "AI 使用边界" not in data["评价"]
    assert "披露义务" not in data["评价"]
    assert "消费品安全" in data["评价"] or "检测" in data["评价"]


def test_finalize_daily_news_body_rewrites_ai_copyright_comment_for_wechat_assistant():
    picked = NewsItem(
        title="微信原生AI助手“小微”小范围内测：支持操作原生功能，调用小程序完成服务",
        url="https://www.thepaper.cn/example-wechat-ai",
        source="澎湃新闻",
        domain="thepaper.cn",
        seendate="2026-06-21 11:19:17",
        description="微信“小微”是正在小范围内测的原生AI助手，可操作微信原生功能并调起小程序完成服务。",
        content=(
            "微信“小微”支持通过文字或语音对话，帮助用户操作设置调整、消息发送、发布朋友圈等原生功能，"
            "并可调起小程序完成挂号、买咖啡等服务。微信支付AI专属卡强调用户许可、专款专用和笔笔确认。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": picked.title,
            "内容": (
                "微信“小微”支持通过文字或语音对话，帮助用户操作设置调整、消息发送、发布朋友圈等原生功能，"
                "并可调起小程序完成挂号、买咖啡等服务。"
            ),
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21 11:19:17",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "AI 使用边界" not in data["评价"]
    assert "披露义务" not in data["评价"]
    assert "版权和信任" not in data["评价"]
    assert "授权" in data["评价"] or "支付安全" in data["评价"] or "用户可控" in data["评价"]


def test_finalize_daily_news_body_cleans_ai_travel_excerpt_and_rewrites_comment():
    picked = NewsItem(
        title="AI伴你游，旅程更省心（新生活新体验）",
        url="https://mini.eastday.com/mobile/example-travel-ai.html",
        source="东方资讯河北频道",
        domain="mini.eastday.com",
        seendate="2026-06-21 11:40:00",
        description="各地文旅小程序提供数字导游服务，帮助游客规划路线、获取景区信息并提升旅游服务效率。",
        content=(
            "游客在手机上打开“杭小忆”。周佳月摄（人民视觉） "
            "一趟个性化旅程开始前，往往需要耗费一番功夫“做攻略”：路线规 AI伴你游。"
            "贵州的“黄小西”、浙江的“杭小忆”等文旅小程序能提供数字导游服务。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "AI伴你游，旅程更省心（新生活新体验）",
            "内容": (
                "游客在手机上打开“杭小忆”。周佳月摄（人民视觉） "
                "一趟个性化旅程开始前，往往需要耗费一番功夫“做攻略”：路线规 AI伴你游。"
            ),
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21 11:40:00",
            "来源": "东方资讯河北频道",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "原文标题：" not in out
    assert "周佳月摄" not in data["内容"]
    assert "路线规 AI伴你游" not in data["内容"]
    assert "AI 使用边界" not in data["评价"]
    assert "数字导游" in data["评价"] or "文旅" in data["评价"]


def test_finalize_daily_news_body_rewrites_musk_stock_award_comment():
    picked = NewsItem(
        title="进账“一个比尔·盖茨”！马斯克行权获7800亿元账面收益",
        url="https://www.thepaper.cn/example-musk-award",
        source="澎湃新闻",
        domain="thepaper.cn",
        seendate="2026-06-21 10:46:37",
        description="特斯拉文件显示，马斯克行使薪酬方案授予的股票期权，账面收益约合人民币7840亿元。",
        content="马斯克此次行权提升了其在特斯拉的投票权比例，也关系到人工智能、自动驾驶和机器人等战略方向控制力。",
    )
    body = json.dumps(
        {
            "原文标题": picked.title,
            "内容": "马斯克希望拥有超25%的特斯拉投票权，以长期主导人工智能、自动驾驶、人形机器人等关键业务。",
            "评价": "这类监管处罚的核心在于维护证券市场公平交易和信息披露秩序。对投资者来说，处罚结果本身只是起点，还应关注公司治理整改、责任落实和后续经营风险",
            "日期": "2026-06-21 10:46:37",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "监管处罚" not in data["评价"]
    assert "账面收益" in data["评价"] or "投票权" in data["评价"] or "公司治理" in data["评价"]


def test_finalize_daily_news_body_rewrites_option_mechanism_comment():
    picked = NewsItem(
        title="上交所拟推出单边平仓功能？暂不实施",
        url="https://www.thepaper.cn/example-options",
        source="澎湃新闻",
        domain="thepaper.cn",
        seendate="2026-06-21 07:52:16",
        description="上交所正在进行股票期权组合策略单边平仓功能技术开发，业务上该功能仍暂不实施。",
        content="近日有消息称，上交所拟完善股票期权组合策略业务，推出单边平仓功能。该功能目前仍暂不实施。",
    )
    body = json.dumps(
        {
            "原文标题": picked.title,
            "内容": "张淑贤/证券时报网 2026-06-21 近日有消息称，上交所拟完善股票期权组合策略业务，推出单边平仓功能。",
            "评价": "这类监管处罚的核心在于维护证券市场公平交易和信息披露秩序。对投资者来说，处罚结果本身只是起点，还应关注公司治理整改、责任落实和后续经营风险。",
            "日期": "2026-06-21 07:52:16",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "张淑贤/证券时报网" not in data["内容"]
    assert "监管处罚" not in data["评价"]
    assert "期权" in data["评价"] or "风险控制" in data["评价"]


def test_finalize_daily_news_body_cleans_evonik_restructuring_excerpt():
    picked = NewsItem(
        title="欧洲化工寒冬持续：赢创全球再裁3200人，关停聚酯业务",
        url="https://www.thepaper.cn/example-evonik",
        source="澎湃新闻",
        domain="thepaper.cn",
        seendate="2026-06-20 22:31:13",
        description="德国化工巨头赢创宣布将进一步推进结构优化与降本措施，计划全球削减约3200个岗位。",
        content="来源 德国化工巨头赢创工业集团6月18日宣布，将在全球范围内进一步推进结。欧洲化工寒冬持续：赢创全球再裁3200人。",
    )
    body = json.dumps(
        {
            "原文标题": picked.title,
            "内容": "来源。德国化工巨头赢创工业集团6月18日宣布，将在全球范围内进一步推进结。欧洲化工寒冬持续：赢创全球再裁3200人。",
            "评价": "",
            "日期": "2026-06-20 22:31:13",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "来源。" not in data["内容"]
    assert "推进结" not in data["内容"]
    assert "裁3200人" in data["内容"] or "削减约3200个岗位" in data["内容"]
    assert "欧洲化工" in data["评价"] or "降本" in data["评价"]


def test_finalize_daily_news_body_rewrites_ai_copyright_comment_for_industrial_ai_news():
    picked = NewsItem(
        title="第二十四届海创会落幕 厦门智造重构未来生活场景",
        url="https://mini.eastday.com/mobile/example.html",
        source="厦门日报",
        domain="mini.eastday.com",
        seendate="2026-06-21 08:47:00",
        description="海创会展示厦门智慧养老、脑电科技、陶瓷刀具和智能金融风控等产业应用场景。",
        content=(
            "第二十四届中国·海峡创新项目成果交易会在福州落幕。厦门企业展示毫米波雷达智慧养老、"
            "脑电科技、航空航天陶瓷刀具和智能金融风控平台等成果，体现科技创新和产业创新融合。"
            "部分产品使用人工智能、大数据和监测设备服务养老、教育、公共服务与企业风控。"
        ),
    )
    body = json.dumps(
        {
            "原文标题": "第二十四届海创会落幕 “厦门智造”重构未来生活场景",
            "内容": (
                "第二十四届海创会在福州落幕，厦门企业集中展示智慧养老、脑电监测、陶瓷刀具和智能风控等应用，"
                "突出科技创新与产业场景融合。"
            ),
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21",
            "来源": "厦门日报",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "AI 使用边界" not in data["评价"]
    assert "披露义务" not in data["评价"]
    assert "版权和信任" not in data["评价"]
    assert data["评价"]
    assert "产业" in data["评价"] or "应用" in data["评价"] or "落地" in data["评价"]


def test_finalize_daily_news_body_rewrites_ai_copyright_comment_for_finance_trade_news():
    picked = NewsItem(
        title="海外市场复杂多变，正泰陆川谈新能源出海新生存法则",
        url="https://www.thepaper.cn/example",
        source="澎湃新闻",
        domain="www.thepaper.cn",
        seendate="2026-06-21 16:39:06",
        description="欧美对中国清洁能源及储能产品的贸易保护加速，光储一体化成为海外市场主流形态。",
        content="正泰相关负责人谈到新能源出海、海外市场、贸易保护、光伏组件、储能和供应链布局。",
    )
    body = json.dumps(
        {
            "原文标题": "海外市场复杂多变，正泰陆川谈新能源出海“新生存法则”",
            "内容": "欧美对中国清洁能源及储能产品的贸易保护加速，光储一体化成为海外市场主流形态。",
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "AI 使用边界" not in data["评价"]
    assert "披露义务" not in data["评价"]
    assert "版权和信任" not in data["评价"]
    assert "供应链" in data["评价"] or "市场" in data["评价"] or "企业" in data["评价"]


def test_finalize_daily_news_body_rewrites_ai_copyright_comment_for_securities_penalty_news():
    picked = NewsItem(
        title="涉嫌操纵自家股票，倍轻松实控人马学军被罚逾千万元",
        url="https://www.thepaper.cn/example-penalty",
        source="澎湃新闻",
        domain="www.thepaper.cn",
        seendate="2026-06-21 13:49:32",
        description="倍轻松及实际控制人收到监管处罚，涉及操纵自家股票和证券市场禁入。",
        content="监管决定显示，相关人员因涉嫌操纵自家股票被罚款，并被采取证券市场禁入措施。",
    )
    body = json.dumps(
        {
            "原文标题": "涉嫌操纵自家股票，倍轻松实控人马学军被罚逾千万元、5年证券市场禁入",
            "内容": "倍轻松及实际控制人一周内收到监管处罚，涉及操纵自家股票和证券市场禁入。",
            "评价": (
                "这件事值得关注的不是单个工具本身，而是 AI 使用边界、披露义务和责任归属。"
                "对内容平台、出版机构和普通用户来说，透明规则比简单禁止更重要，否则创作效率提升可能反过来损害版权和信任。"
            ),
            "日期": "2026-06-21",
            "来源": "澎湃新闻",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "")
    data = _daily_news_body_fields(out)

    assert "AI 使用边界" not in data["评价"]
    assert "版权和信任" not in data["评价"]
    assert "监管" in data["评价"] or "证券" in data["评价"] or "市场" in data["评价"]


def test_finalize_daily_news_body_rewrites_nasa_world_cup_comment_instead_of_sports_template():
    picked = NewsItem(
        title="世界杯官方用球上太空，NASA将三重浪带上空间站",
        url="https://www.163.com/example",
        source="163.com",
        domain="163.com",
        seendate="2026-06-20",
        description="国际足联世界杯官方用球被带上国际空间站，NASA宣布相关航天传播活动。",
        content="国际足联世界杯官方用球被带上国际空间站，NASA还宣布阿耳忒弥斯2号任务成员将参与世界杯相关活动。",
    )
    body = json.dumps(
        {
            "原文标题": "世界杯官方用球上太空 ， NASA将 三重浪 ‌带上空间站",
            "内容": (
                "北京。举报 0 分享至。用微信扫码二维码。分享至好友和朋友圈。"
                "国际足联世界杯官方用球被带上了国际空间站，NASA还宣布阿耳忒弥斯2号任务的成员也将参与与世界杯相关的活动。"
            ),
            "评价": (
                "体育新闻的评价重点应放在竞技表现、人才梯队和长期训练体系，"
                "而不是一次成绩带来的情绪波动。"
            ),
            "日期": "2026-06-20",
            "来源": "163.com",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际新闻")
    data = _daily_news_body_fields(out)

    assert "举报 0" not in data["内容"]
    assert "用微信扫码二维码" not in data["内容"]
    assert "竞技表现" not in data["评价"]
    assert "人才梯队" not in data["评价"]
    assert "航天" in data["评价"] or "空间站" in data["评价"]


def test_finalize_daily_news_body_replaces_unsupported_humanitarian_comment():
    picked = NewsItem(
        title="美伊谈判在即，记者瑞士比尔根山现场直击",
        url="https://www.xinhuanet.com/example",
        source="新华社",
        domain="xinhuanet.com",
        seendate="2026-06-21",
        description="美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。",
        content="瑞士外交部称伊朗代表团已抵达，相关方将在瑞士举行技术层面谈判。",
    )
    body = json.dumps(
        {
            "原文标题": "美伊谈判在即",
            "内容": "美国副总统万斯启程前往瑞士出席与伊朗方面的谈判，伊朗代表团已抵达瑞士。",
            "评价": "这条新闻的关键在平民保护、救援通道和停火安排能否形成可执行结果。",
            "日期": "2026-06-21",
            "来源": "新华社",
        },
        ensure_ascii=False,
    )

    out = _finalize_daily_news_body(body, picked, "国际新闻")
    data = _daily_news_body_fields(out)

    assert "平民保护" not in data["评价"]
    assert "救援通道" not in data["评价"]
    assert "停火安排" not in data["评价"]
    assert "谈判" in data["评价"]
    assert "后续" in data["评价"] or "正式" in data["评价"]


def test_pick_news_items_dedupes_similar_titles_with_hint():
    items = [
        NewsItem(title="EU signs Mercosur trade deal", url="https://a.com/1"),
        NewsItem(title="Mercosur trade deal signed by EU", url="https://b.com/1"),
        NewsItem(title="Japan inflation rises", url="https://c.com/1"),
    ]
    picked = pick_news_items(items, "trade deal", count=2)
    assert len(picked) == 2
    assert picked[0].title != picked[1].title
    assert any("Japan" in item.title for item in picked)


def test_pick_news_items_dedupes_similar_titles_without_hint():
    items = [
        NewsItem(title="EU signs Mercosur trade deal", url="https://a.com/1"),
        NewsItem(title="Mercosur trade deal signed by EU", url="https://b.com/1"),
        NewsItem(title="Global oil prices fall", url="https://c.com/1"),
    ]
    picked = pick_news_items(items, "", count=2)
    assert len(picked) == 2
    assert picked[0].title != picked[1].title


def test_dedupe_candidates_removes_similar_titles():
    items = [
        NewsItem(title="Apple releases new Mac", url="https://a.com/1"),
        NewsItem(title="Apple releases new Mac", url="https://b.com/1"),
        NewsItem(title="Global oil prices fall", url="https://c.com/1"),
    ]
    deduped = _dedupe_candidates(items)
    assert len(deduped) == 2


def test_dedupe_candidates_filters_package_release_noise():
    items = [
        NewsItem(title="axprism added to PyPI", url="https://pypi.org/project/axprism/", domain="pypi.org"),
        NewsItem(title="Watch: Mayor delivers victory speech", url="https://example.com/video", domain="example.com"),
        NewsItem(title="Channel catch-up: News in brief", url="https://example.com/brief", domain="example.com"),
        NewsItem(title="Global climate talks resume", url="https://example.com/climate", domain="example.com"),
    ]

    deduped = _dedupe_candidates(items)

    assert [item.title for item in deduped] == ["Global climate talks resume"]


def test_pick_news_items_prefers_china_ratio():
    items = [
        NewsItem(title="CN1", url="https://a.cn/1"),
        NewsItem(title="US1", url="https://a.com/1"),
        NewsItem(title="CN2", url="https://b.cn/1"),
        NewsItem(title="US2", url="https://b.com/1"),
        NewsItem(title="CN3", url="https://c.cn/1"),
        NewsItem(title="US3", url="https://c.com/1"),
    ]
    picked = pick_news_items(items, "", count=5)
    china_count = sum(1 for it in picked if ".cn/" in it.url)
    # Default 6:4 => ~60% China, count=5 => 3 China + 2 foreign.
    assert china_count == 3


def test_pick_news_items_dedupes_cross_language_by_entities():
    items = [
        NewsItem(
            title="China verurteilt Demokratie-Aktivist Jimmy Lai zu 20 Jahren Haft",
            url="https://a.com/1",
        ),
        NewsItem(
            title="Hong Kong Sentences Jimmy Lai to 20 Years in Landmark Case",
            url="https://b.com/1",
        ),
        NewsItem(title="Japan inflation rises", url="https://c.com/1"),
    ]
    picked = pick_news_items(items, "", count=2)
    assert len(picked) == 2
    assert any(item.title == "Japan inflation rises" for item in picked)
    assert sum("Jimmy Lai" in item.title for item in picked) == 1


def test_pick_news_items_keeps_distinct_same_source_same_date_stories():
    items = [
        NewsItem(
            title="法国总统呼吁美国共享前沿AI并推动民主国家协同监管",
            url="https://apnews.com/a",
            description="AP报道，法国总统在G7期间讨论AI监管。",
            seendate="2026-06-18",
        ),
        NewsItem(
            title="东京小学火灾约300名师生疏散或获救",
            url="https://apnews.com/b",
            description="AP报道，东京一所小学6月19日发生火灾。",
            seendate="2026-06-19",
        ),
        NewsItem(
            title="世界杯今日看点：美国对阵澳大利亚，巴西力争反弹",
            url="https://apnews.com/c",
            description="AP梳理6月19日世界杯赛程。",
            seendate="2026-06-19",
        ),
        NewsItem(
            title="桑德斯提出让公众直接持有AI公司股份的方案",
            url="https://apnews.com/d",
            description="AP独家报道，桑德斯提出AI公司公众持股方案。",
            seendate="2026-06-17",
        ),
        NewsItem(
            title="英国要求Google允许发布者退出AI摘要抓取",
            url="https://apnews.com/e",
            description="AP报道，英国监管机构要求Google提供AI抓取退出选项。",
            seendate="2026-06-03",
        ),
    ]

    picked = pick_news_items(items, "科技、社会或国际新闻", count=5)

    assert len(picked) == 5


def test_pick_news_items_limits_single_domain_when_alternatives_exist():
    items = [
        NewsItem(
            title=f"36氪公司政策新闻{i}",
            url=f"https://36kr.com/p/{i}",
            domain="36kr.com",
            source="36氪",
            seendate=f"2026-07-02T09:0{i}:00Z",
            description="公司政策调整引发市场关注。",
            sourcecountry="cn",
        )
        for i in range(4)
    ] + [
        NewsItem(
            title="新华社发布劳动者权益新规",
            url="https://news.cn/politics/1",
            domain="news.cn",
            source="新华社",
            seendate="2026-07-02T08:50:00Z",
            description="劳动者权益新规施行。",
            sourcecountry="cn",
        ),
        NewsItem(
            title="央视关注暑运客流增长",
            url="https://news.cctv.com/china/1",
            domain="news.cctv.com",
            source="央视新闻",
            seendate="2026-07-02T08:40:00Z",
            description="铁路暑运客流进入高峰。",
            sourcecountry="cn",
        ),
    ]

    picked = pick_news_items(items, "", count=4)

    domains = [item.domain for item in picked]
    assert domains.count("36kr.com") <= 2
    assert len(set(domains)) >= 3
