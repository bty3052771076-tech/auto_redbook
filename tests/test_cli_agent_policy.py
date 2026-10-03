import json
from datetime import datetime, timedelta, timezone

from apps.cli import (
    _agent_ai_digest_policy_defaults,
    _agent_ai_digest_review_issues,
    _agent_global_map_unavailable_reason,
    _agent_source_policy_defaults,
    _load_agent_job_plan,
    _normalize_agent_lookback,
)
from src.storage.models import Post


def test_agent_auto_lookback_uses_workflow_default():
    assert _normalize_agent_lookback("auto") is None
    assert _normalize_agent_lookback(3) == 3
    assert _normalize_agent_lookback(None) is None


def test_agent_ai_digest_defaults_are_soft_without_overriding_explicit_values(monkeypatch):
    for name in (
        "AI_DIGEST_IMPACT_SUPERVISOR",
        "AI_DIGEST_HIGH_IMPACT_SCORE",
        "AI_DIGEST_MIN_OFFICIAL_ITEMS",
        "AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS",
        "AI_DIGEST_MIN_FOREIGN_AI_ITEMS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _agent_ai_digest_policy_defaults() == {
        "AI_DIGEST_IMPACT_SUPERVISOR": "0",
        "AI_DIGEST_HIGH_IMPACT_SCORE": "0",
        "AI_DIGEST_MIN_OFFICIAL_ITEMS": "1",
        "AI_DIGEST_MIN_DOMESTIC_MODEL_ITEMS": "0",
        "AI_DIGEST_MIN_FOREIGN_AI_ITEMS": "0",
    }

    monkeypatch.setenv("AI_DIGEST_MIN_OFFICIAL_ITEMS", "6")
    assert _agent_ai_digest_policy_defaults()["AI_DIGEST_MIN_OFFICIAL_ITEMS"] == "6"


def test_agent_ai_digest_rejects_no_official_or_single_source():
    post = Post(
        title="每日AI讯息",
        body="内容",
        platform={"ai_digest": {
            "items": [
                {"source_type": "aggregator", "source_name": "arXiv cs.AI", "url": "https://arxiv.org/a"},
                {"source_type": "aggregator", "source_name": "arXiv cs.AI", "url": "https://arxiv.org/b"},
            ],
            "source_meta": {"selected_official_count": 0},
            "source_distribution": {"arXiv cs.AI": 2},
        }},
    )
    issues = _agent_ai_digest_review_issues(post, min_official=1)

    assert any("官网" in issue for issue in issues)
    assert any("信源" in issue for issue in issues)

    post.platform["ai_digest"]["items"][0].update({
        "source_type": "official", "source_name": "OpenAI", "url": "https://openai.com/news/a"
    })
    post.platform["ai_digest"]["source_meta"]["selected_official_count"] = 1
    post.platform["ai_digest"]["source_distribution"] = {"OpenAI": 1, "arXiv cs.AI": 1}
    assert _agent_ai_digest_review_issues(post, min_official=1) == []


def test_agent_map_failure_explains_fresh_blocked_snapshot(tmp_path):
    day = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat()
    path = tmp_path / f"global-map-{day}.json"
    path.write_text(json.dumps({
        "source_state": "stale",
        "coverage_status": "blocked",
        "warning": "主数据源不是新鲜有效状态，不能生成可投稿地图。",
    }, ensure_ascii=False), encoding="utf-8")

    reason = _agent_global_map_unavailable_reason(tmp_path, started_at=0)

    assert "stale" in reason
    assert "主数据源" in reason


def test_agent_job_plan_loads_only_validated_jobs(tmp_path, monkeypatch):
    plan = tmp_path / "data" / "web_gui" / "conversations" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({
        "jobs": [{
            "kind": "daily_ai_digest",
            "title": "每日AI讯息",
            "count": 1,
            "prompt": "模型发布",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    jobs = _load_agent_job_plan(plan, None, "无视角评价")
    assert len(jobs) == 1
    assert jobs[0].kind == "daily_ai_digest"
    assert jobs[0].count == 1


def test_agent_preserves_explicit_unified_source_override(monkeypatch):
    monkeypatch.setenv("UNIFIED_NEWS_SOURCES", "0")

    assert _agent_source_policy_defaults() == {"UNIFIED_NEWS_SOURCES": "0"}
