from datetime import datetime, timedelta, timezone

import pytest

from apps.cli import _agent_ai_digest_review_issues
from src.ai_digest.generate import build_ai_digest_prompt, build_fallback_brief, cap_ai_digest_items_by_source
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import rank_ai_updates
from src.storage.models import Post
from src.workflow import create_post


def updates():
    published = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    names = ("GPT-6", "Realtime", "Codex", "Sora", "Whisper", "ChatGPT")
    return [
        AIUpdateItem(
            title=f"OpenAI发布{name}并开放API调用",
            summary=f"OpenAI发布{name}，开放图像输入和工具调用接口，开发者可通过API接入。",
            source_name="OpenAI", vendor="OpenAI", product=name,
            source_type="official", url=f"https://openai.com/index/test-release-{index}/",
            published_at=published,
        )
        for index, name in enumerate(names)
    ]


def test_default_ranking_and_rewrite_keep_more_than_two_same_vendor_events():
    items = updates()
    ranked = rank_ai_updates(items, target_count=6)
    assert len(ranked) == 6
    assert {item.product for item in ranked} == {"GPT-6", "Realtime", "Codex", "Sora", "Whisper", "ChatGPT"}
    assert len(cap_ai_digest_items_by_source(ranked, target_count=6)) == 6
    assert len(build_fallback_brief(ranked, target_count=6).items) == 6


def test_adaptive_selection_keeps_single_origin_and_explicit_item_minimum():
    items = updates()
    selected, meta = create_post._select_adaptive_ai_digest_items(
        items, impact_scores={item.dedupe_key: {"high_impact": True} for item in items},
        historical_keys=set(), min_items=4, max_items=6,
        min_official_count=0, min_domestic_model_count=0, min_foreign_ai_count=0,
    )
    assert len(selected) == 6
    assert meta["source_diversity"]["selected_sources"] == 1
    assert meta["source_diversity"]["limited_to_single_item"] is False


def test_final_date_and_agent_gates_do_not_reject_same_vendor_events():
    final, meta = create_post._enforce_ai_digest_publish_policy(build_fallback_brief(updates(), target_count=6))
    assert len(final.items) == 6
    assert meta["source_cap_removed"] == 0
    post = Post(title="每日AI讯息", body="测试", platform={"ai_digest": {
        "items": [item.model_dump() for item in final.items],
        "source_meta": {"selected_official_count": 0},
    }})
    assert _agent_ai_digest_review_issues(post, min_official=6) == []


def test_source_change_keeps_expired_item_rejection():
    old = updates()[0].model_copy(update={
        "published_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
    })
    with pytest.raises(RuntimeError, match="strict Beijing two-day window"):
        create_post._enforce_ai_digest_publish_policy(build_fallback_brief([old], target_count=1))


def test_prompt_preserves_events_without_source_or_country_hard_quotas():
    prompt = build_ai_digest_prompt(updates(), target_count=6,
                                   min_domestic_model_count=4, min_foreign_ai_count=2)
    assert "信源硬约束" not in prompt
    assert "硬性配额" not in prompt
    assert "不得删除、增加、合并或调整顺序" in prompt


def test_workflow_ignores_stale_source_quota_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("AI_DIGEST_MIN_OFFICIAL_ITEMS", "AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS",
                 "AI_DIGEST_MIN_FOREIGN_AI_ITEMS"):
        monkeypatch.setenv(name, "20")
    monkeypatch.setenv("AI_DIGEST_IMPACT_SUPERVISOR", "0")
    monkeypatch.setenv("AI_DIGEST_HIGH_IMPACT_SCORE", "0")
    monkeypatch.setattr(create_post, "collect_ai_digest_updates", lambda **kw: (updates(), {}))
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [])
    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm",
                        lambda configs, items, target_count, **kw:
                        build_fallback_brief(items, target_count=target_count))
    digest = create_post.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0].platform["ai_digest"]
    assert len(digest["items"]) == 6
    assert digest["effective_min_official_items"] == 0
    assert digest["effective_min_domestic_model_items"] == 0
    assert digest["effective_min_foreign_ai_items"] == 0
