from __future__ import annotations

import pytest

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
    assert "恰好 8 条" in prompt
    assert "至少 3 条中国/国内模型" in prompt
    assert "至少 3 条国外 AI" in prompt


def test_build_ai_digest_prompt_requires_exact_compact_rewrite():
    prompt = build_ai_digest_prompt(_updates(8), target_count=8)

    assert "恰好 8 条" in prompt
    assert "不得删除、增加、合并或调整顺序" in prompt
    assert "items 每项只输出" in prompt


def test_generate_ai_digest_brief_retries_malformed_json(monkeypatch):
    item = _updates(1)[0]

    class FakeModel:
        calls = 0

        def invoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return type("Resp", (), {"content": '{"title":"每日AI讯息","items":['})()
            return type(
                "Resp",
                (),
                {
                    "content": """
                    {
                      "title": "每日AI讯息",
                      "subtitle": "模型与工具更新",
                      "date": "2026-06-30",
                      "items": [
                        {
                          "title": "OpenAI更新ChatGPT开发能力",
                          "summary": "OpenAI更新ChatGPT相关模型与开发工具，说明能力变化及其对开发者工作流的实际影响。",
                          "url": "https://example.com/0",
                          "tags": ["AI工具"]
                        }
                      ],
                      "source_summary": "主要来源：OpenAI。"
                    }
                    """
                },
            )()

    model = FakeModel()
    monkeypatch.setattr(
        "src.ai_digest.generate.init_chat_model",
        lambda *_args, **_kwargs: model,
    )

    brief = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [item],
        target_count=1,
        date="2026-06-30",
    )

    assert model.calls == 2
    assert len(brief.items) == 1
    assert brief.items[0].url == item.url
    assert brief.items[0].published_at == item.published_at


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


def test_generate_ai_digest_brief_restores_search_provenance_and_rejects_cross_item_claims(monkeypatch):
    item = AIUpdateItem(
        title="Suno 推出多项新功能，含 MIDI 导出",
        summary="网页端和移动端新增高级音轨分离、MIDI 导出、歌词合写与自动保存。",
        source_name="X：Suno (@suno)",
        source_type="search",
        url="https://aihot.virxact.com/daily/2026-07-27?item=2",
        published_at="2026-07-27T08:00:00+08:00",
        vendor="Suno",
        product="",
        raw_excerpt="Suno 推出 MIDI 导出、音轨分离和歌词合写功能。",
        confidence_score=0.72,
        verification_status="social_confirmed",
        evidence_urls=["https://aihot.virxact.com/daily/2026-07-27"],
        tags=["AI", "AI HOT"],
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
                      "subtitle": "模型与工具更新",
                      "date": "2026-07-27",
                      "items": [
                        {
                          "title": "xAI发布Grok CLI，Suno同步推出MIDI导出",
                          "summary": "xAI发布Grok CLI并加入tutorial命令，Suno同时上线MIDI导出和音轨分离功能。",
                          "url": "https://aihot.virxact.com/daily/2026-07-27?item=2",
                          "tags": ["AI工具"]
                        }
                      ],
                      "source_summary": "主要来源：AI HOT。"
                    }
                    """
                },
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    out = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [item],
        target_count=1,
        date="2026-07-27",
    ).items[0]

    assert out.source_type == "search"
    assert out.verification_status == "social_confirmed"
    assert out.confidence_score == 0.72
    assert "xAI" not in out.title
    assert "Grok" not in out.title
    assert "xAI" not in out.summary
    assert "Grok" not in out.summary
    assert "Suno" in out.title


def test_generate_ai_digest_brief_restores_each_llm_item_to_a_distinct_source(monkeypatch):
    sources = [
        AIUpdateItem(
            title="OpenAI 发布科研智能体报告",
            summary="OpenAI 展示 AI 编程智能体如何帮助科学计算。",
            source_name="OpenAI",
            source_type="official",
            url="https://openai.com/index/scientific-computing-agentic-ai",
            published_at="2026-07-28T17:00:00Z",
            vendor="OpenAI",
            raw_excerpt="AI coding agents modernize scientific computing.",
            tags=["AI"],
        ),
        AIUpdateItem(
            title="DeepSeek 将停用旧 API 模型名",
            summary="deepseek-chat 与 deepseek-reasoner 将在三个月后停用。",
            source_name="DeepSeek",
            source_type="official",
            url="https://api-docs.deepseek.com/updates",
            published_at="2026-07-24",
            vendor="DeepSeek",
            raw_excerpt="The legacy API model names will be discontinued.",
            tags=["AI"],
        ),
    ]

    class FakeModel:
        def invoke(self, _messages):
            return type(
                "Resp",
                (),
                {
                    "content": """
                    {
                      "title": "每日AI讯息",
                      "subtitle": "模型与工具更新",
                      "date": "2026-07-29",
                      "items": [
                        {
                          "title": "OpenAI发布科研智能体报告",
                          "summary": "OpenAI展示AI编程智能体如何帮助科学计算。",
                          "url": "https://openai.com/index/scientific-computing-agentic-ai",
                          "tags": ["AI工具"]
                        },
                        {
                          "title": "OpenAI科研智能体报告更新",
                          "summary": "OpenAI继续介绍AI编程智能体与科学计算。",
                          "url": "https://openai.com/index/scientific-computing-agentic-ai",
                          "tags": ["AI工具"]
                        }
                      ],
                      "source_summary": "主要来源：OpenAI、DeepSeek。"
                    }
                    """
                },
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    brief = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        sources,
        target_count=2,
        date="2026-07-29",
    )

    assert {item.url for item in brief.items} == {source.url for source in sources}


@pytest.mark.parametrize(
    "unsupported_claim",
    ["仅限付费计划使用", "附带使用限制，企业需关注许可条款"],
)
def test_generate_ai_digest_brief_rejects_unsupported_access_claim(monkeypatch, unsupported_claim):
    source = AIUpdateItem(
        title="What is Kimi K3? New open-weight model explained",
        summary="Moonshot AI released Kimi K3 for coding and agent workflows.",
        source_name="Tom's Guide",
        source_type="search",
        url="https://example.com/kimi-k3",
        published_at="2026-07-28T08:45:00Z",
        vendor="Tom's Guide",
        raw_excerpt="Kimi K3 is available as an open-weight model.",
        tags=["AI"],
    )

    class FakeModel:
        def invoke(self, _messages):
            content = """
                {
                  "title": "每日AI讯息",
                  "items": [
                    {
                      "title": "Kimi K3开放权重模型发布",
                      "summary": "Kimi K3面向编程和智能体任务，但目前仅限付费计划使用。",
                      "source_name": "Tom's Guide",
                      "source_type": "search",
                      "url": "https://example.com/kimi-k3",
                      "published_at": "2026-07-28T08:45:00Z",
                      "vendor": "Tom's Guide",
                      "raw_excerpt": "",
                      "tags": ["AI模型"]
                    }
                  ]
                }
                """.replace("仅限付费计划使用", unsupported_claim)
            return type(
                "Resp",
                (),
                {"content": content},
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    out = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [source],
        target_count=1,
        date="2026-07-29",
    ).items[0]

    assert unsupported_claim not in out.summary
    assert "open-weight" in out.summary or "开放权重" in out.summary


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


def test_generate_ai_digest_brief_restores_source_publish_time_when_llm_changes_it(monkeypatch):
    item = AIUpdateItem(
        title="DeepSeek-V4 预览版发布",
        summary="DeepSeek-V4 预览版本正式上线并同步开源。",
        source_name="DeepSeek",
        source_type="official",
        url="https://api-docs.deepseek.com/zh-cn/news/news260424",
        published_at="2026-04-24",
        vendor="DeepSeek",
        product="DeepSeek-V4",
        raw_excerpt="DeepSeek-V4 预览版发布 2026/04/24",
        tags=["国内模型"],
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
                      "subtitle": "模型更新",
                      "date": "2026-07-08",
                      "items": [
                        {
                          "title": "DeepSeek-V4预览版发布",
                          "summary": "DeepSeek-V4上线并开源，强化Agent与推理能力。",
                          "source_name": "DeepSeek",
                          "source_type": "official",
                          "url": "https://api-docs.deepseek.com/zh-cn/news/news260424",
                          "published_at": "2026-07-08",
                          "vendor": "DeepSeek",
                          "product": "DeepSeek-V4",
                          "raw_excerpt": "DeepSeek-V4 预览版发布",
                          "evidence_urls": [],
                          "tags": ["国内模型"]
                        }
                      ],
                      "source_summary": "主要来源：DeepSeek。"
                    }
                    """,
                },
            )()

    monkeypatch.setattr("src.ai_digest.generate.init_chat_model", lambda *_args, **_kwargs: FakeModel())

    brief = generate_ai_digest_brief_with_llm(
        [LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.com", provider="test")],
        [item],
        target_count=1,
        date="2026-07-08",
    )

    assert brief.items[0].published_at == "2026-04-24"


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


def test_build_fallback_brief_preserves_chinese_action_after_long_english_subject():
    item = AIUpdateItem(
        title="Scientific computing in the age of agentic AI",
        summary="A field report shows how scientists use AI coding agents in genomics.",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/index/scientific-computing-agentic-ai",
        published_at="2026-07-28T17:00:00Z",
        vendor="OpenAI",
        product="",
        raw_excerpt="AI coding agents modernize scientific computing and genomics.",
        tags=["AI"],
    )

    out = build_fallback_brief([item], target_count=1, date="2026-07-29").items[0]

    assert len(out.title) <= 28
    assert "发布新进展" in out.title
    assert any("\u4e00" <= char <= "\u9fff" for char in out.title)


def test_build_fallback_brief_translates_ntt_data_enterprise_adoption_case():
    item = AIUpdateItem(
        title="NTT DATA Group uses ChatGPT Enterprise and Codex",
        summary=(
            "NTT DATA Group uses ChatGPT Enterprise and Codex to help 9,000 employees "
            "automate work and cut incident analysis to 30 minutes."
        ),
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/index/ntt-data",
        published_at="2026-07-22T00:00:00Z",
        vendor="OpenAI",
        raw_excerpt=(
            "NTT DATA Group uses ChatGPT Enterprise and Codex to help 9,000 employees "
            "automate work, cut incident analysis to 30 minutes, and scale secure AI adoption."
        ),
        tags=["AI"],
    )

    out = build_fallback_brief([item], target_count=1, date="2026-07-29").items[0]

    assert out.title == "NTT DATA借助ChatGPT与Codex提效"
    assert "9000名员工" in out.summary
    assert "30分钟" in out.summary
    assert " uses " not in out.title
    assert " uses " not in out.summary


def test_build_fallback_brief_does_not_fabricate_missing_publish_time_from_brief_date():
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

    assert brief.items[0].published_at == ""


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


def test_build_fallback_brief_describes_deepseek_api_deprecation_instead_of_the_update():
    item = AIUpdateItem(
        title="The two legacy API model names will be discontinued",
        summary="",
        source_name="DeepSeek",
        source_type="official",
        url="https://api-docs.deepseek.com/updates",
        published_at="2026-07-24",
        vendor="DeepSeek",
        product="",
        raw_excerpt=(
            "The two legacy API model names, deepseek-chat and deepseek-reasoner, "
            "will be discontinued in three months. They currently point to the "
            "non-thinking and thinking modes of deepseek-v4-flash."
        ),
        tags=["AI"],
    )

    out = build_fallback_brief([item], target_count=1, date="2026-07-29").items[0]

    assert "The更新" not in out.title
    assert "DeepSeek" in out.title
    assert "停用" in out.title
    assert "deepseek-chat" in out.summary
    assert "deepseek-reasoner" in out.summary


def test_render_ai_digest_body_includes_source_links_for_each_item():
    body = render_ai_digest_body(build_fallback_brief(_updates(2), date="2026-06-30"))

    assert "每日AI讯息" in body
    assert "发布时间：2026-06-30" in body
    assert "来源链接：" in body
    assert "信源层级：官网2条，资讯整合站0条，社交媒体0条" in body
    assert "1. OpenAI https://example.com/0" in body
    assert "2. OpenAI https://example.com/1" in body


def test_render_ai_digest_body_keeps_primary_url_before_shorter_evidence_url():
    official_url = "https://www.anthropic.com/research/discovering-cryptographic-weaknesses-with-claude"
    aggregator_url = "https://aihot.virxact.com/daily/2026-07-29?item=1"
    item = AIUpdateItem(
        title="Claude 发现加密算法弱点",
        summary="Anthropic 介绍 Claude 在密码学研究中的新进展。",
        source_name="AI HOT",
        source_type="search",
        url=official_url,
        published_at="2026-07-29T08:00:00+08:00",
        vendor="Anthropic",
        product="Claude",
        raw_excerpt="Claude cryptographic research.",
        evidence_urls=[aggregator_url],
        tags=["AI"],
    )

    body = render_ai_digest_body(build_fallback_brief([item], target_count=1, date="2026-07-29"))

    assert official_url in body
    assert aggregator_url not in body


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
