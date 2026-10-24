from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from apps.cli import _agent_ai_digest_policy_defaults
from src.ai_digest import generate as digest_generate
from src.ai_digest.models import AIUpdateItem
from src.config import LLMConfig
from src.news.daily_news import NewsItem
from src.storage.models import Post
from src.workflow import create_post
from src.workflow.news_discovery import news_key
from src.workflow.performance import PerformancePolicy


def candidate(title: str, slug: str) -> NewsItem:
    return NewsItem(
        title=title, url=f"https://news.example/{slug}", source="Example",
        domain="news.example", seendate=datetime.now(timezone.utc).isoformat(),
        description=f"{title}，公开材料说明了相关机构的具体行动及落实安排。",
    )


def configs():
    return [LLMConfig(model="editorial-test", api_key="test-only", base_url="https://invalid.example")]


@pytest.mark.parametrize("ranked_ids,rejected_ids,wanted", [
    ([2, 1], [3], ["second", "first"]),
    ([1], [2, 3], ["first"]),
    ([], [1, 2, 3], []),
    ([1, 2], [2, 3], ["first"]),
    ([1], [2], ["first", "third"]),
])
def test_explicit_rejections_never_reenter_ordinary_news_pool(
    monkeypatch, ranked_ids, rejected_ids, wanted,
):
    monkeypatch.setenv("NEWS_LLM_SUPERVISOR_ENABLED", "1")
    items = [candidate("甲机构开展新的公共服务", "first"),
             candidate("乙企业调整会员退款办法", "second"),
             candidate("丙机构重复报道同一份政策", "third")]
    monkeypatch.setattr(create_post, "generate_json", lambda *a, **kw: {
        "ranked_ids": ranked_ids, "rejected_ids": rejected_ids, "reason": "排除重复和无实质内容项",
    })

    selected, meta = create_post._supervise_daily_news_candidates(
        items, cfgs=configs(), prompt_hint="社会民生", target_count=3,
        required_china_count=0, progress_callback=None,
    )

    assert [item.url.rsplit("/", 1)[-1] for item in selected] == wanted
    assert meta["status"] == "success"
    assert meta["rejected_candidate_count"] == len(rejected_ids)


@pytest.mark.parametrize("mode", ["balanced", "speed"])
@pytest.mark.parametrize("entrypoint", ["coordinator", "workflow"])
def test_replenishment_is_reviewed_against_accepted_news_even_for_one_remaining_slot(
    monkeypatch, tmp_path, mode, entrypoint,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEWS_LLM_SUPERVISOR_ENABLED", "1")
    first = candidate("港口启用新救援设施", "accepted")
    failed = candidate("企业旧材料无法成稿", "failed")
    repeated = candidate("同一港口救援设施的重复报道", "repeated")
    fresh = candidate("法院明确消费者退款责任", "fresh")

    class Discovery:
        meta = {}
        record_path = Path("test-discovery.json")

        def __init__(self):
            self.prepared = {news_key(x): (x, {}, {}, x) for x in (first, failed, repeated, fresh)}
            self.taken = False

        def take(self, **kwargs):
            if self.taken:
                return []
            self.taken = True
            return [repeated, fresh]

        def save_record(self, **kwargs):
            pass

    review_requests = []

    def review(*args, **kwargs):
        payload = json.loads(kwargs["user_prompt"])
        review_requests.append(payload)
        if not payload["already_selected"]:
            return {"ranked_ids": [1], "rejected_ids": [2], "reason": "只保留合格新闻"}
        assert [row["title"] for row in payload["already_selected"]] == [first.title]
        return {"ranked_ids": [2], "rejected_ids": [1], "reason": "补位保留独立事件"}

    def prepare(*, candidate_index, picked, **kwargs):
        if picked.url == failed.url:
            return create_post._DailyNewsCandidateResult(
                candidate_index=candidate_index, status="skipped", reason="generic_title",
            )
        post = Post(
            title=picked.title, body=f"内容：\n{picked.description}\n\n评价：\n具体规则值得关注。",
            platform={"news": {"picked": {"url": picked.url}}},
        )
        return create_post._DailyNewsCandidateResult(
            candidate_index=candidate_index, status="success", picked=picked, post=post,
            dedupe_item=picked, draft={"title": picked.title}, asset_paths=[], copy_assets=False,
        )

    monkeypatch.setattr(create_post, "generate_json", review)
    monkeypatch.setattr(create_post, "_daily_news_context_is_incomplete", lambda item: False)
    monkeypatch.setattr(create_post, "_prepare_daily_news_candidate", prepare)
    monkeypatch.setattr(create_post, "save_post", lambda post: None)
    monkeypatch.setattr(create_post, "save_revision", lambda revision: None)

    if entrypoint == "workflow":
        def fetch(*args, discovery_holder, **kwargs):
            discovery_holder["session"] = Discovery()
            return [first, failed], {}
        monkeypatch.setattr(create_post, "_fetch_daily_news_candidates_for_upload", fetch)
        monkeypatch.setattr(create_post, "load_llm_configs", configs)
        posts = create_post.create_daily_news_posts(
            prompt_hint="社会民生", asset_paths=[], count=2, auto_image=False, performance_mode=mode,
        )
    else:
        posts = create_post._run_parallel_daily_news_candidates(
            picks=[first, failed], cfgs=configs(), asset_paths=[], copy_assets=False,
            auto_image_enabled=False, prompt_norm="社会民生", viewpoint_norm="无视角评价",
            target_count=2, single_material_mode=False, base_meta={}, progress_callback=None,
            post_quality_callback=None, required_china_count=0,
            required_international_conflict_count=0, discovery=Discovery(),
            performance_policy=PerformancePolicy.from_value(mode),
        )

    assert review_requests
    assert [post.title for post in posts] == [first.title, fresh.title]


@pytest.mark.parametrize("explicit_override", [False, True])
def test_agent_default_impact_review_filters_low_value_updates_without_source_quotas(
    monkeypatch, tmp_path, explicit_override,
):
    monkeypatch.chdir(tmp_path)
    for key in ("AI_DIGEST_IMPACT_SUPERVISOR", "AI_DIGEST_HIGH_IMPACT_SCORE"):
        monkeypatch.delenv(key, raising=False)
    if explicit_override:
        monkeypatch.setenv("AI_DIGEST_IMPACT_SUPERVISOR", "0")
        monkeypatch.setenv("AI_DIGEST_HIGH_IMPACT_SCORE", "0")
    for key, value in _agent_ai_digest_policy_defaults().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AI_DIGEST_MIN_ITEMS", "1")
    monkeypatch.setenv("AI_DIGEST_ADAPTIVE_COUNT", "1")
    now = datetime.now(timezone.utc).isoformat()
    items = [
        AIUpdateItem(
            title="OpenAI发布GPT-6模型并开放图像输入API", source_name="OpenAI", vendor="OpenAI",
            source_type="official", url="https://openai.com/index/gpt-6", published_at=now,
            summary="OpenAI发布GPT-6模型并开放图像输入和工具调用API。",
        ),
        AIUpdateItem(
            title="AWS为MCP服务新增工具上下文导出接口", source_name="Amazon AWS", vendor="Amazon AWS",
            source_type="official", url="https://aws.amazon.com/blogs/machine-learning/mcp-context-export",
            published_at=now, summary="AWS为MCP服务新增工具上下文导出接口，方便将会话记录交给业务程序。",
            confidence_score=0,
        ),
    ]

    class ImpactModel:
        def invoke(self, messages):
            return SimpleNamespace(content=json.dumps({"scores": [
                {"index": 1, "impact_score": 95, "high_impact": True, "reason": "明确模型发布"},
                {"index": 2, "impact_score": 25, "high_impact": False, "reason": "普通企业案例"},
            ]}))

    image = tmp_path / "card.png"
    Image.new("RGB", (2, 2)).save(image)
    monkeypatch.setattr(digest_generate, "init_chat_model", lambda *a, **kw: ImpactModel())
    monkeypatch.setattr(create_post, "collect_ai_digest_updates", lambda **kw: (items, {}))
    monkeypatch.setattr(create_post, "load_llm_configs", configs)
    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm",
                        lambda cfg, selected, *, target_count, **kw:
                        create_post.build_fallback_brief(selected, target_count=target_count))
    monkeypatch.setattr(create_post, "render_ai_digest_cards", lambda *a, **kw: [image])
    monkeypatch.setattr(create_post, "save_post", lambda post: None)
    monkeypatch.setattr(create_post, "save_revision", lambda revision: None)

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
    digest = post.platform["ai_digest"]
    assert digest["actual_items"] == (2 if explicit_override else 1)
    assert digest["max_items_per_source"] is None
    if explicit_override:
        assert digest["impact_review"]["error"] == ""
    else:
        assert digest["impact_review"]["mode"] == "llm_hybrid"
