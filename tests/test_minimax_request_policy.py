import copy
import json
from types import SimpleNamespace

import pytest

from src.config import LLMConfig
from src.llm import generate
from src.model_platforms.runtime import encode

FLASH = "MiniMax-M3.1-Flash"
ANSWER = json.dumps({"title": "verified", "body": "verified news content", "topics": []})


@pytest.fixture(autouse=True)
def clean_parameters(monkeypatch):
    monkeypatch.delenv("MINIMAX_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)


def capture_client(monkeypatch, module, content=ANSWER):
    requests = []

    def factory(model, **kwargs):
        requests.append({"model": model, **kwargs})
        return SimpleNamespace(invoke=lambda messages: SimpleNamespace(
            content=content, response_metadata={"finish_reason": "stop"}, usage_metadata={},
        ))

    monkeypatch.setattr(module, "init_chat_model", factory)
    return requests


@pytest.mark.parametrize("model", [FLASH, "MiniMax-M3.1-Flash-Preview"])
def test_flash_news_request_leaves_room_for_reasoning_and_final_copy(monkeypatch, model):
    requests = capture_client(monkeypatch, generate)
    result = generate.generate_draft(
        LLMConfig(model, "test-key", provider="minimax"),
        title_hint="news", prompt_hint="verified facts", asset_paths=[],
    )
    assert result["body"] == "verified news content"
    assert requests[0].get("reasoning_effort") == "medium"
    assert requests[0]["max_tokens"] == 131072
    assert requests[0].get("extra_body", {}).get("thinking") != {"type": "disabled"}


def test_flash_draft_is_not_capped_by_legacy_global_limit_or_context_estimate(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    requests = capture_client(monkeypatch, generate)
    generate.generate_draft(LLMConfig(FLASH, "test-key", provider="minimax"),
                            title_hint="news", prompt_hint="facts" * 14000, asset_paths=[])
    assert requests[0]["max_tokens"] == 131072


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_flash_json_uses_selected_effort_and_model_output_cap(monkeypatch, effort):
    monkeypatch.setenv("MINIMAX_REASONING_EFFORT", effort)
    requests = capture_client(monkeypatch, generate, '{"result":"complete"}')
    result = generate.generate_json(
        LLMConfig(FLASH, "test-key", provider="minimax"),
        system_prompt="Return JSON", user_prompt="facts", max_tokens=2048,
    )
    assert result == {"result": "complete"}
    assert requests[0].get("reasoning_effort") == effort
    assert requests[0]["max_tokens"] == 131072


def test_flash_controller_json_defaults_to_medium(monkeypatch):
    requests = capture_client(monkeypatch, generate, '{"jobs":[]}')
    assert generate.generate_json(LLMConfig(FLASH, "test-key", provider="minimax"),
                                 system_prompt="Return JSON", user_prompt="plan") == {"jobs": []}
    assert requests[0].get("reasoning_effort") == "medium"
    assert requests[0]["max_tokens"] == 131072


@pytest.mark.parametrize("model", ["MiniMax-M3", "other-model"])
def test_existing_non_flash_requests_keep_their_token_and_effort_behavior(monkeypatch, model):
    monkeypatch.setenv("MINIMAX_REASONING_EFFORT", "low")
    requests = capture_client(monkeypatch, generate)
    generate.generate_draft(LLMConfig(model, "test-key", provider="minimax"),
                            title_hint="news", prompt_hint="facts", asset_paths=[])
    assert requests[0]["max_tokens"] == 5024
    assert "reasoning_effort" not in requests[0]


@pytest.mark.parametrize("adapter", ["openai_chat", "openai_responses", "anthropic_messages"])
@pytest.mark.parametrize("effort", [None, "high"])
@pytest.mark.parametrize("explicit_cap", [None, 1500])
def test_custom_model_adapters_use_flash_defaults_and_preserve_explicit_settings(adapter, effort, explicit_cap):
    params = {} if explicit_cap is None else {"max_output_tokens": explicit_cap}
    if effort:
        params["reasoning_effort"] = effort
    snapshot = {"adapter": adapter, "upstream_model_id": FLASH, "parameters": params}
    original = copy.deepcopy(snapshot)
    _, body = encode(snapshot, [{"role": "user", "content": "facts"}], 2000)
    expected = effort or "medium"
    expected_cap = explicit_cap or 131072
    if adapter == "openai_chat":
        assert body.get("reasoning_effort") == expected
        assert body["max_completion_tokens"] == expected_cap
        assert "max_tokens" not in body
    elif adapter == "openai_responses":
        assert body.get("reasoning") == {"effort": expected}
        assert body["max_output_tokens"] == expected_cap
    else:
        assert body.get("output_config") == {"effort": expected}
        assert body["max_tokens"] == expected_cap
    assert snapshot == original
    assert "thinking" not in body


@pytest.mark.parametrize("effort", ["none", "minimal", "unsupported"])
def test_flash_rejects_unsupported_effort_before_sending(effort):
    with pytest.raises(ValueError, match="reasoning_effort"):
        encode({"adapter": "openai_chat", "upstream_model_id": FLASH,
                "parameters": {"reasoning_effort": effort}},
               [{"role": "user", "content": "facts"}], 2000)


def test_other_model_adapter_does_not_inherit_minimax_effort(monkeypatch):
    monkeypatch.setenv("MINIMAX_REASONING_EFFORT", "high")
    _, body = encode({"adapter": "openai_chat", "upstream_model_id": "other-model",
                      "parameters": {}}, [{"role": "user", "content": "facts"}], 2000)
    assert "reasoning_effort" not in body


def digest_item():
    from src.ai_digest.models import AIUpdateItem
    return AIUpdateItem(
        title="OpenAI开放开发者模型接口",
        summary="OpenAI向开发者开放模型接口，允许通过API提交文本请求并读取响应，开发者可在现有应用中接入该接口。",
        source_name="OpenAI", source_type="official", url="https://example.com/model-api",
        published_at="2026-10-22T08:00:00Z", vendor="OpenAI", product="API",
    )


def test_flash_ai_digest_rewrite_uses_medium_effort_and_model_output_cap(monkeypatch):
    from src.ai_digest import generate as digest
    item = digest_item()
    content = json.dumps({"title": "每日AI讯息", "date": "2026-10-22",
                          "items": [item.model_dump()]}, ensure_ascii=False)
    requests = capture_client(monkeypatch, digest, content)
    brief = digest.generate_ai_digest_brief_with_llm(
        [LLMConfig(FLASH, "test-key", provider="minimax")], [item],
        target_count=1, date="2026-10-22",
    )
    assert brief.items[0].url == item.url
    assert requests[0].get("reasoning_effort") == "medium"
    assert requests[0]["max_tokens"] == 131072


def test_flash_ai_digest_impact_review_uses_medium_effort_and_model_output_cap(monkeypatch):
    from src.ai_digest import generate as digest
    content = json.dumps({"scores": [{"index": 1, "impact_score": 90,
                                     "high_impact": True, "reason": "模型接口开放"}]})
    requests = capture_client(monkeypatch, digest, content)
    scores, meta = digest.evaluate_ai_digest_impact_with_llm(
        [LLMConfig(FLASH, "test-key", provider="minimax")], [digest_item()])
    assert meta["mode"] == "llm_hybrid"
    assert scores
    assert requests[0].get("reasoning_effort") == "medium"
    assert requests[0]["max_tokens"] == 131072


def test_flash_vision_review_uses_medium_effort_and_model_output_cap(monkeypatch, tmp_path):
    from src.workflow import vision_review
    requests = capture_client(monkeypatch, vision_review, '{"ok":true,"score":90,"issues":[]}')
    path = tmp_path / "image.png"
    path.write_bytes(b"test-image")
    result = vision_review.invoke_vision_review(
        LLMConfig(FLASH, "test-key", provider="minimax"), prompt="review", image_path=path)
    assert "90" in result
    assert requests[0].get("reasoning_effort") == "medium"
    assert requests[0]["max_tokens"] == 131072


def test_flash_langchain_sends_completion_budget_and_medium_on_the_wire(monkeypatch):
    import httpx
    from langchain.chat_models import init_chat_model

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion",
                                       "created": 1, "model": FLASH, "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": ANSWER}}
        ]})

    def factory(model, **kwargs):
        return init_chat_model(model, **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(generate, "init_chat_model", factory)
    generate.generate_draft(LLMConfig(FLASH, "test-key", base_url="https://example.com/v1", provider="minimax"),
                            title_hint="news", prompt_hint="facts", asset_paths=[], concise_news=True)
    assert len(sent) == 1
    assert sent[0]["max_completion_tokens"] == 131072
    assert "max_tokens" not in sent[0]
    assert sent[0]["reasoning_effort"] == "medium"
    system = sent[0]["messages"][0]["content"]
    assert "150" in system and "220" in system
    assert "评价目标50–100字" in system


@pytest.mark.parametrize("model", [FLASH, "MiniMax-M3.1-Flash-Preview"])
def test_custom_flash_model_can_save_and_edit_128k_cap(tmp_path, model):
    from src.model_platforms import PlatformStore

    store = PlatformStore(tmp_path)
    connection = store.add_connection({"name": "Test", "adapter": "openai_chat",
                                       "base_url": "http://127.0.0.1:11434/v1",
                                       "network": "local", "auth_mode": "none"})
    row = store.add_model({"connection_id": connection["connection_id"], "upstream_model_id": model,
                           "parameters": {"max_output_tokens": 131072}}, store.state()["revision"])
    updated = store.edit_model(row["model_ref"], {"parameters": {
        "max_output_tokens": 131072, "reasoning_effort": "medium"}}, store.state()["revision"])
    assert updated["parameters"] == {"max_output_tokens": 131072, "reasoning_effort": "medium"}


def test_other_models_keep_custom_output_parameter_validation():
    from src.model_platforms import PlatformError, PlatformStore

    with pytest.raises(PlatformError, match="UNSUPPORTED_PARAMETER"):
        PlatformStore._parameters({"max_output_tokens": 131072})
