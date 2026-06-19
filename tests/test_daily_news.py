import pytest

from src.news import daily_news
from src.news.daily_news import NewsItem, pick_best_news, pick_news_items, _dedupe_candidates
from src.config import LLMConfig
from src.workflow import create_post
from src.workflow.create_post import (
    _append_news_source_line,
    _daily_news_body_has_prompt_leak,
    _daily_news_offline_body,
    _daily_news_prompt,
    _ensure_daily_news_sections,
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


def test_ensure_daily_news_sections_adds_headings():
    body = "这是只有一段的正文。"
    out = _ensure_daily_news_sections(body, "美国时政")
    assert "要点摘要：" in out
    assert "新闻内容：" in out
    assert "点评：" in out


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
        seendate="2026-06-19T00:00:00Z",
        description="多家公司开始讨论 AI 写作工具对内容生产的影响。",
        content="业内人士关注 AI 写作工具的效率、质量和识别问题。",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_and_pick_daily_news",
        lambda _prompt: (picked, {"provider": "fake-news", "picked": {"title": picked.title}}),
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
    assert "约50字" in prompt
    assert "约200字" in prompt
    assert "不得输出 URL" in prompt
    assert "网址只保存在本地" in prompt


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
    assert 180 <= len(content) <= 260
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
        seendate="2026-06-19T08:00:00Z",
        description="The chip company said the product targets inference workloads.",
        content="The company described performance and energy-efficiency updates.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_and_pick_daily_news",
        lambda _prompt: (picked, {"provider": "fake-news"}),
    )

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
                "发布时间：2026-06-19\n\n"
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
    assert post.body.splitlines()[-1] == "来源：Example News"
    assert post.platform["news"]["source_url"] == "https://example.com/source"
    assert post.platform["news"]["picked"]["url"] == "https://example.com/source"


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
        seendate="2026-06-19",
        description="Officials announced a technology cooperation framework.",
        content="The framework focuses on standards, investment and supply chain dialogue.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_daily_news_candidates",
        lambda _prompt: ([picked], {"provider": "fake-news"}),
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
                "发布时间：2026-06-19\n\n"
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
    assert posts[0].body.splitlines()[-1] == "来源：Example Wire"
    assert posts[0].platform["news"]["source_url"] == "https://example.com/eu-tech"
    assert posts[0].platform["news"]["picked"]["url"] == "https://example.com/eu-tech"


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
        seendate="2026-06-16T00:00:00Z",
        description="A technology dispute escalated.",
        content="The report described a policy dispute around advanced AI model access.",
    )
    monkeypatch.setattr(
        create_post,
        "fetch_and_pick_daily_news",
        lambda _prompt: (picked, {"provider": "fake-news", "picked": {"title": picked.title}}),
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


def test_fetch_daily_news_candidates_auto_falls_back_to_gdelt_when_newsapi_times_out(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDER", raising=False)
    monkeypatch.setenv("NEWS_API_KEY", "fake-newsapi-key")
    monkeypatch.setattr(daily_news, "_maybe_translate_hint_to_en", lambda _hint: "technology")

    def fake_newsapi_fetch_articles(**_kwargs):
        raise TimeoutError("timed out")

    gdelt_calls = []

    def fake_gdelt_fetch_articles(**kwargs):
        gdelt_calls.append(kwargs)
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
    monkeypatch.setattr(daily_news, "_gdelt_fetch_articles", fake_gdelt_fetch_articles)

    candidates, meta = daily_news.fetch_daily_news_candidates("科技", timeout_s=1)

    assert candidates[0].title == "AI芯片公司发布新进展"
    assert meta["provider"] == "gdelt"
    assert meta["provider_attempts"] == ["newsapi", "gdelt"]
    assert any("timed out" in err for err in meta["provider_errors"])
    assert gdelt_calls


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
