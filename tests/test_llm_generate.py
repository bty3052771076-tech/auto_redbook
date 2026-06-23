import json

from src.config import LLMConfig
import src.llm.generate as generate_mod
from src.llm.generate import _coerce_text, _parse_json_text


def test_parse_json_text_recovers_from_malformed_body_quotes():
    text = """
{
  "title": "每日新闻｜测试事件",
  "body": "这是一段正文，包含"关键说法"并继续展开分析。
第二段继续补充。",
  "topics": ["每日新闻", "国际观察"],
  "image_event": "会议现场交谈"
}
"""
    data = _parse_json_text(text)
    assert isinstance(data, dict)
    assert data.get("title") == "每日新闻｜测试事件"
    assert "关键说法" in (data.get("body") or "")
    assert "每日新闻" in (data.get("topics") or [])
    assert data.get("image_event") == "会议现场交谈"


def test_parse_json_text_accepts_list_content_payload():
    payload = [
        {
            "type": "text",
            "text": '{"title":"标题A","body":"正文A","topics":["话题A","话题B"]}',
        }
    ]
    data = _parse_json_text(payload)
    assert isinstance(data, dict)
    assert data.get("title") == "标题A"
    assert data.get("body") == "正文A"
    assert data.get("topics") == ["话题A", "话题B"]


def test_coerce_text_preserves_daily_news_body_object_as_json():
    body_obj = {
        "原文标题": "AI芯片新品发布",
        "内容": "这是一段正文。",
        "评价": "",
        "日期": "2026-06-19",
        "来源": "Example News",
    }

    out = _coerce_text(body_obj)

    assert json.loads(out) == body_obj


def test_generate_draft_uses_25565_max_tokens(monkeypatch):
    captured = {}

    class FakeModel:
        def invoke(self, _messages):
            return type(
                "FakeResponse",
                (),
                {
                    "content": json.dumps(
                        {
                            "title": "测试标题",
                            "body": "这是一段用于测试的正文。",
                            "topics": ["测试"],
                        },
                        ensure_ascii=False,
                    )
                },
            )()

    def fake_init_chat_model(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeModel()

    monkeypatch.setattr(generate_mod, "init_chat_model", fake_init_chat_model)

    generate_mod.generate_draft(
        LLMConfig(
            model="fake-model",
            api_key="fake-key",
            base_url="https://example.invalid/v1",
        ),
        title_hint="测试标题",
        prompt_hint="测试提示",
        asset_paths=[],
    )

    assert captured["kwargs"]["max_tokens"] == 25565
