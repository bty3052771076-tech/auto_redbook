from datetime import datetime, timedelta, timezone

import pytest

from apps.cli import _agent_ai_digest_review_issues
from src.ai_digest.models import AIUpdateItem
from src.storage.models import Post
from src.workflow import create_post


def updates():
    day = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return [
        AIUpdateItem(title="OpenAI发布GPT-6模型并开放API", source_name="OpenAI", vendor="OpenAI",
                     source_type="official", url="https://openai.com/index/gpt-6/", published_at=day,
                     summary="OpenAI发布GPT-6模型并开放API，新增工具调用与图像输入能力。"),
        AIUpdateItem(title="OpenAI为Realtime接口新增语音工具调用", source_name="OpenAI", vendor="OpenAI",
                     source_type="official", url="https://openai.com/index/realtime/", published_at=day,
                     summary="OpenAI为Realtime接口新增语音输入输出和服务端工具调用。"),
    ]


def select(items, **kwargs):
    return create_post._select_adaptive_ai_digest_items(
        items, impact_scores={item.dedupe_key: {"high_impact": True} for item in items},
        historical_keys=set(), min_official_count=1, min_domestic_model_count=0,
        min_foreign_ai_count=0, **kwargs)


def test_single_source_adaptive_pool_selects_one_instead_of_failing_agent_review():
    selected, meta = select(updates())
    assert len(selected) == 2
    assert meta["target_items"] == 2
    assert meta["source_diversity"]["limited_to_single_item"] is False


def test_multiple_sources_are_not_reduced_to_a_single_item():
    items = updates()
    items[1] = items[1].model_copy(update={"source_name": "Google", "vendor": "Google",
                                         "url": "https://blog.google/ai/realtime/"})
    selected, _ = select(items)
    assert len(selected) == 2


def test_explicit_multi_item_minimum_does_not_get_silently_relaxed():
    selected, _ = select(updates(), min_items=2)
    assert len(selected) == 2
    with pytest.raises(RuntimeError, match="material insufficient"):
        select(updates(), min_items=3)


def test_generation_and_agent_review_agree_for_a_single_source_pool(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key, value in {"AI_DIGEST_MIN_ITEMS": "1", "AI_DIGEST_MIN_OFFICIAL_ITEMS": "1",
                       "AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS": "0", "AI_DIGEST_MIN_FOREIGN_AI_ITEMS": "0",
                       "AI_DIGEST_IMPACT_SUPERVISOR": "0", "AI_DIGEST_HIGH_IMPACT_SCORE": "0"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(create_post, "collect_ai_digest_updates", lambda **kw: (updates(), {}))
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [])
    seen = []

    def generate(configs, items, *, target_count, **kwargs):
        seen.append((len(items), target_count))
        return create_post.build_fallback_brief(items, target_count=target_count)

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", generate)
    posts = create_post.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
    assert seen == [(2, 2)]
    assert len(posts[0].platform["ai_digest"]["items"]) == 2
    assert _agent_ai_digest_review_issues(posts[0], min_official=1) == []


def test_source_concentration_is_rejected_by_final_gate_not_only_agent_adapter():
    assert create_post._ai_digest_source_cap_error(updates()) == ""


@pytest.mark.parametrize("same_vendor", [True, False])
def test_agent_review_counts_origins_not_display_labels(same_vendor):
    items = updates()
    if same_vendor:
        items[0].source_name = "API公告"
        items[1].source_name = "更新日志"
    else:
        for item in items:
            item.source_name = "统一公告渠道"
        items[1] = items[1].model_copy(update={
            "vendor": "Google", "url": "https://blog.google/ai/gemini/",
            "title": "Google发布Gemini模型并开放图像输入",
            "summary": "Google为Gemini模型新增图像输入和工具调用接口，并提供API接入文档。",
        })
    post = Post(title="AI", body="content", platform={"ai_digest": {
        "items": [item.model_dump() for item in items],
        "source_meta": {"selected_official_count": 2},
    }})
    issues = _agent_ai_digest_review_issues(post, min_official=1)
    assert issues == []
