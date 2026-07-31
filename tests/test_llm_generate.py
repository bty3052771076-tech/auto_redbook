import json

from src.config import LLMConfig
import src.llm.generate as generate_mod
from src.llm.generate import _coerce_text, _parse_json_text, _should_try_next_llm, generate_json
from src.text_integrity import repair_utf8_as_gbk_mojibake


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


def test_generate_draft_uses_60000_max_tokens(monkeypatch):
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

    assert captured["kwargs"]["max_tokens"] == 60000
    assert captured["kwargs"]["timeout"] == 240


def test_generate_json_keeps_literal_json_schema_in_prompt(monkeypatch):
    captured = {}

    class FakeModel:
        def invoke(self, messages):
            captured["messages"] = messages
            return type("FakeResponse", (), {"content": '{"ranked_ids":[2,1]}'})()

    monkeypatch.setattr(generate_mod, "init_chat_model", lambda *_args, **_kwargs: FakeModel())

    result = generate_json(
        LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.invalid/v1"),
        system_prompt='Return exactly {"ranked_ids":[1]}.',
        user_prompt='{"candidates":[1,2]}',
    )

    assert result == {"ranked_ids": [2, 1]}
    assert any('"ranked_ids"' in str(message.content) for message in captured["messages"])


def test_repair_utf8_as_gbk_mojibake_handles_one_and_two_passes():
    original = "\u6bcf\u65e5\u65b0\u95fb"
    once = original.encode("utf-8").decode("gb18030")
    twice = once.encode("utf-8").decode("gb18030")

    assert repair_utf8_as_gbk_mojibake(once) == original
    assert repair_utf8_as_gbk_mojibake(twice) == original
    assert repair_utf8_as_gbk_mojibake(original) == original


def test_provider_account_overdue_error_allows_the_next_configured_candidate():
    assert _should_try_next_llm(RuntimeError("403 AccountOverdue: account is overdue"))


def test_generate_draft_repairs_model_mojibake_and_retries_rate_limit(monkeypatch):
    calls = {"invoke": 0, "sleep": []}
    original = "\u8d22\u7ecf\u4ea7\u4e1a\u5e02\u573a\u53d8\u5316\u901f\u89c8"
    corrupted = original.encode("utf-8").decode("gb18030")

    class FakeModel:
        def invoke(self, _messages):
            calls["invoke"] += 1
            if calls["invoke"] == 1:
                raise RuntimeError("429 RATE_LIMIT_EXCEEDED")
            return type(
                "FakeResponse",
                (),
                {"content": json.dumps({"title": corrupted, "body": corrupted, "topics": [corrupted]})},
            )()

    monkeypatch.setattr(generate_mod, "init_chat_model", lambda *_args, **_kwargs: FakeModel())
    monkeypatch.setattr(generate_mod.time, "sleep", lambda seconds: calls["sleep"].append(seconds))

    out = generate_mod.generate_draft(
        LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.invalid/v1"),
        title_hint="\u6d4b\u8bd5",
        prompt_hint="\u6d4b\u8bd5",
        asset_paths=[],
    )

    assert calls["invoke"] == 2
    assert calls["sleep"] == [65]
    assert out["title"] == original
    assert out["body"] == original
    assert out["topics"] == [original]


def test_generate_draft_allows_configured_multiple_rate_limit_retries(monkeypatch):
    calls = {"invoke": 0, "sleep": []}
    monkeypatch.setenv("LLM_RATE_LIMIT_MAX_RETRIES", "3")

    class FakeModel:
        def invoke(self, _messages):
            calls["invoke"] += 1
            if calls["invoke"] <= 3:
                raise RuntimeError("429 RATE_LIMIT_EXCEEDED")
            return type(
                "FakeResponse",
                (),
                {"content": '{"title":"测试标题","body":"测试正文","topics":[]}'},
            )()

    monkeypatch.setattr(generate_mod, "init_chat_model", lambda *_args, **_kwargs: FakeModel())
    monkeypatch.setattr(generate_mod.time, "sleep", lambda seconds: calls["sleep"].append(seconds))

    out = generate_mod.generate_draft(
        LLMConfig(model="fake-model", api_key="fake-key", base_url="https://example.invalid/v1"),
        title_hint="测试",
        prompt_hint="测试",
        asset_paths=[],
    )

    assert calls["invoke"] == 4
    assert calls["sleep"] == [65, 65, 65]
    assert out["title"] == "测试标题"
