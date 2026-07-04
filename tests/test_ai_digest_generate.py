from __future__ import annotations

from src.ai_digest.generate import (
    build_ai_digest_prompt,
    build_fallback_brief,
    generate_ai_digest_brief_with_llm,
    parse_ai_digest_brief_json,
    render_ai_digest_body,
)
from src.ai_digest.models import AIUpdateItem
from src.config import LLMConfig


def _updates(n: int = 3) -> list[AIUpdateItem]:
    return [
        AIUpdateItem(
            title=f"AI动态{i}",
            summary=f"第{i}条动态摘要，涉及模型、产品或开发者工具更新。",
            source_name="OpenAI",
            source_type="official",
            url=f"https://example.com/{i}",
            published_at="2026-06-30T08:00:00Z",
            vendor="OpenAI",
            product="ChatGPT",
            raw_excerpt=f"raw {i}",
            evidence_urls=[f"https://x.com/OpenAI/status/{i}"] if i == 1 else [],
            tags=["AI"],
        )
        for i in range(n)
    ]


def test_build_ai_digest_prompt_requires_structured_json_and_source_trace():
    prompt = build_ai_digest_prompt(_updates(2), target_count=10)

    assert "每日AI讯息" in prompt
    assert "10" in prompt
    assert "JSON" in prompt
    assert "evidence_urls" in prompt
    assert "AI动态0" in prompt


def test_build_ai_digest_prompt_requires_chinese_translation_for_foreign_updates():
    item = AIUpdateItem(
        title="OpenAI launches new developer tools",
        summary="Developers can build agent workflows with new API features.",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/news/tools",
        published_at="2026-06-30T08:00:00Z",
        vendor="OpenAI",
        product="API",
        raw_excerpt="OpenAI launches new developer tools for agent workflows.",
        tags=["AI"],
    )

    prompt = build_ai_digest_prompt([item], target_count=1)

    assert "翻译" in prompt
    assert "自然中文" in prompt
    assert "全部输出中文" in prompt


def test_build_ai_digest_prompt_mentions_daily_digest_quota_rules():
    prompt = build_ai_digest_prompt(
        _updates(8),
        target_count=8,
        min_domestic_model_count=3,
        min_foreign_ai_count=3,
    )

    assert "硬性配额" in prompt
    assert "不少于 8 条" in prompt
    assert "至少 3 条中国/国内模型" in prompt
    assert "至少 3 条国外 AI" in prompt


def test_generate_ai_digest_brief_with_llm_returns_chinese_items(monkeypatch):
    item = AIUpdateItem(
        title="OpenAI launches new developer tools",
        summary="Developers can build agent workflows with new API features.",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/news/tools",
        published_at="2026-06-30T08:00:00Z",
        vendor="OpenAI",
        product="API",
        raw_excerpt="OpenAI launches new developer tools for agent workflows.",
        tags=["AI"],
    )
    captured: dict[str, str] = {}

    class FakeModel:
        def invoke(self, messages):
            captured["messages"] = "\n".join(str(message.content) for message in messages)
            return type(
                "Resp",
                (),
                {
                    "content": """
                    {
                      "title": "每日AI讯息",
                      "subtitle": "AI平台与工具更新",
                      "date": "2026-06-30",
                      "items": [
                        {
                          "title": "OpenAI发布开发者工具更新",
                          "summary": "OpenAI更新开发者工具，重点面向智能体工作流和API调用体验，方便开发者更快搭建自动化应用。",
                          "source_name": "OpenAI",
                          "source_type": "official",
                          "url": "https://openai.com/news/tools",
                          "published_at": "2026-06-30T08:00:00Z",
                          "vendor": "OpenAI",
                          "product": "API",
                          "raw_excerpt": "OpenAI launches new developer tools for agent workflows.",
                          "evidence_urls": [],
                          "tags": ["AI工具"]
                        }
                      ],
                      "source_summary": "主要来源：OpenAI。"
                    }
                    """
                },
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    brief = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [item],
        target_count=1,
        date="2026-06-30",
    )

    assert "翻译" in captured["messages"]
    assert brief.items[0].title == "OpenAI发布开发者工具更新"
    assert "开发者工具" in brief.items[0].summary


def test_generate_ai_digest_brief_rewrites_generic_llm_items_from_source_trace(monkeypatch):
    item = AIUpdateItem(
        title="OpenAI launches GPT-5.2 Codex CLI with browser automation",
        summary="The release adds browser automation, stricter terminal permissions, and improved agent workflows.",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/news/gpt-5-2-codex-cli",
        published_at="2026-07-02T06:30:00Z",
        vendor="OpenAI",
        product="Codex CLI",
        raw_excerpt="OpenAI launches GPT-5.2 Codex CLI with browser automation and stricter terminal permissions.",
        tags=["AI"],
    )

    class FakeModel:
        def invoke(self, _messages):
            return type(
                "Resp",
                (),
                {
                    "content": """
                    {
                      "title": "每日AI讯息",
                      "subtitle": "AI平台与工具更新",
                      "date": "2026-07-02",
                      "items": [
                        {
                          "title": "OpenAI发布AI动态",
                          "summary": "OpenAI公开了与AI有关的动态，具体链接已保存在本地元数据中。",
                          "source_name": "OpenAI",
                          "source_type": "official",
                          "url": "",
                          "published_at": "",
                          "vendor": "OpenAI",
                          "product": "Codex CLI",
                          "raw_excerpt": "",
                          "evidence_urls": [],
                          "tags": ["AI动态"]
                        }
                      ],
                      "source_summary": "主要来源：OpenAI。"
                    }
                    """
                },
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    brief = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [item],
        target_count=1,
        date="2026-07-02",
    )

    out = brief.items[0]
    assert out.url == "https://openai.com/news/gpt-5-2-codex-cli"
    assert out.published_at == "2026-07-02T06:30:00Z"
    assert "发布AI动态" not in out.title
    assert "具体链接已保存在本地元数据" not in out.summary
    assert "GPT-5.2" in out.title
    assert "Codex CLI" in out.title
    assert "浏览器自动化" in out.summary
    assert "终端权限" in out.summary


def test_parse_ai_digest_brief_json_accepts_llm_output():
    raw = """
    {
      "title": "每日AI讯息",
      "subtitle": "模型与工具更新",
      "date": "2026-06-30",
      "items": [
        {
          "title": "OpenAI 发布工具更新",
          "summary": "OpenAI 更新开发者工具，面向企业和开发者改进调用体验。",
          "source_name": "OpenAI",
          "source_type": "official",
          "url": "https://openai.com/news/tool",
          "published_at": "2026-06-30T08:00:00Z",
          "vendor": "OpenAI",
          "product": "API",
          "raw_excerpt": "raw",
          "evidence_urls": ["https://x.com/OpenAI/status/1"],
          "tags": ["AI工具"]
        }
      ],
      "source_summary": "官方源为主，X 作为验证。"
    }
    """

    brief = parse_ai_digest_brief_json(raw)

    assert brief.title == "每日AI讯息"
    assert brief.items[0].verification_status == "social_confirmed"
    assert "官方源" in brief.source_summary


def test_build_fallback_brief_keeps_about_ten_items_and_source_summary():
    brief = build_fallback_brief(_updates(12), target_count=10, date="2026-06-30")

    assert brief.title == "每日AI讯息"
    assert brief.date == "2026-06-30"
    assert len(brief.items) == 10
    assert "OpenAI" in brief.source_summary


def test_build_fallback_brief_uses_specific_source_content_for_english_updates():
    item = AIUpdateItem(
        title="Anthropic launches Claude Code for web with background agents",
        summary="Claude Code on the web lets developers run background agents from a browser and track pull requests.",
        source_name="Anthropic",
        source_type="official",
        url="https://www.anthropic.com/news/claude-code-web",
        published_at="2026-07-02T05:20:00Z",
        vendor="Anthropic",
        product="Claude Code",
        raw_excerpt="Anthropic launches Claude Code for web with background agents and pull request tracking.",
        tags=["AI"],
    )

    brief = build_fallback_brief([item], target_count=1, date="2026-07-02")
    out = brief.items[0]

    assert "发布AI动态" not in out.title
    assert "具体链接已保存在本地元数据" not in out.summary
    assert "Claude Code" in out.title
    assert "网页" in out.summary
    assert "后台智能体" in out.summary


def test_build_fallback_brief_fills_missing_publish_time_from_brief_date():
    item = AIUpdateItem(
        title="GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。",
        summary="GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。",
        source_name="智谱 GLM",
        source_type="official",
        url="https://docs.bigmodel.cn/cn/update/new-releases",
        published_at="",
        vendor="智谱 GLM",
        product="GLM-5.2",
        raw_excerpt="GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。",
        tags=["AI"],
    )

    brief = build_fallback_brief([item], target_count=1, date="2026-07-02")

    assert brief.items[0].published_at == "2026-07-02"


def test_build_fallback_brief_uses_url_slug_when_source_title_is_vendor_only():
    item = AIUpdateItem(
        title="Hugging Face",
        summary="",
        source_name="Hugging Face",
        source_type="official",
        url="https://huggingface.co/blog/cerebras-gemma4-voice-ai",
        published_at="2026-07-01T00:00:00Z",
        vendor="Hugging Face",
        product="",
        raw_excerpt="",
        tags=["AI"],
    )

    brief = build_fallback_brief([item], target_count=1, date="2026-07-02")
    out = brief.items[0]

    assert out.title != "Hugging Face更新"
    assert "Cerebras" in out.title
    assert "Gemma4" in out.title
    assert "语音" in out.summary


def test_render_ai_digest_body_includes_source_links_for_each_item():
    body = render_ai_digest_body(build_fallback_brief(_updates(2), date="2026-06-30"))

    assert "每日AI讯息" in body
    assert "发布时间：2026-06-30" in body
    assert "来源链接：" in body
    assert "1. OpenAI https://example.com/0" in body
    assert "2. OpenAI https://example.com/1" in body


def test_render_ai_digest_body_keeps_eight_links_under_platform_limit_with_long_sources():
    items = [
        AIUpdateItem(
            title=f"AI HOT 动态{i}",
            summary="这是一条来自聚合源的 AI 模型或工具更新摘要。",
            source_name="阿里巴巴发布 Page Agent，一个开源的 JavaScript 客户端库，嵌入网页后可通过自然语言操作 DOM 元素。",
            source_type="search",
            url=f"https://aihot.virxact.com/daily/2026-07-03?item={i}",
            published_at="2026-07-03T08:00:00+08:00",
            vendor="阿里/Qwen" if i < 3 else "OpenAI",
            product="",
            raw_excerpt="raw",
            tags=["AI"],
        )
        for i in range(8)
    ]
    brief = build_fallback_brief(items, target_count=8, date="2026-07-03")

    body = render_ai_digest_body(brief, selection_meta={"fetched_count": 200, "fresh_count": 58, "deduped_count": 47})

    assert len(body) <= 1000
    assert body.count("https://aihot.virxact.com/daily/2026-07-03?item=") == 8
