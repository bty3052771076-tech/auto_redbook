from __future__ import annotations

from src.ai_digest.generate import (
    build_ai_digest_prompt,
    build_fallback_brief,
    parse_ai_digest_brief_json,
    render_ai_digest_body,
)
from src.ai_digest.models import AIUpdateItem


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


def test_render_ai_digest_body_is_short_and_does_not_include_urls():
    body = render_ai_digest_body(build_fallback_brief(_updates(2), date="2026-06-30"))

    assert "每日AI讯息" in body
    assert "发布时间：2026-06-30" in body
    assert "https://" not in body
