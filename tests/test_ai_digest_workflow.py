from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.storage.models import PostStatus
from src.workflow import create_post


def _fresh_published_at() -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(hours=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _updates(n: int = 10) -> list[AIUpdateItem]:
    profiles = [
        ("智谱 GLM", "GLM-5.2", "https://docs.bigmodel.cn/cn/update/glm-5-2"),
        ("阿里云百炼", "Qwen3-Coder", "https://help.aliyun.com/model-studio/qwen3-coder"),
        ("火山方舟", "Doubao-Seed", "https://www.volcengine.com/docs/ark/doubao-seed"),
        ("OpenAI", "GPT-5.2", "https://openai.com/index/gpt-5-2-api"),
        ("Anthropic", "Claude Code", "https://www.anthropic.com/news/claude-code"),
        ("Google DeepMind", "Gemini", "https://deepmind.google/discover/blog/gemini-reasoning"),
        ("Hugging Face", "Transformers", "https://huggingface.co/blog/transformers-update"),
    ]
    updates: list[AIUpdateItem] = []
    for i in range(n):
        vendor, product_base, base_url = profiles[i % len(profiles)]
        product = f"{product_base}-{i}"
        updates.append(
            AIUpdateItem(
                title=f"{product} 模型动态{i}",
                summary=f"{vendor} 发布 {product} 模型、API 或开发者工具更新，说明能力变化和使用价值。",
                source_name=vendor,
                source_type="official",
                url=f"{base_url}?item={i}",
                published_at=_fresh_published_at(),
                vendor=vendor,
                product=product,
                raw_excerpt=f"{vendor} {product} model release raw {i}",
                tags=["AI"],
            )
        )
    return updates


def test_create_daily_ai_digest_posts_creates_post_with_rendered_cards(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (_updates(10), {"sources": ["fixture"], "social_backfill_used": False}),
    )
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: (_ for _ in ()).throw(RuntimeError("no test llm")))

    posts = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)

    assert len(posts) == 1
    post = posts[0]
    assert post.title.startswith("每日AI|")
    assert len(post.title) <= 20
    assert post.status == PostStatus.draft
    assert post.assets
    assert all(Path(asset.path).exists() for asset in post.assets)
    assert post.platform["ai_digest"]["mode"] == "daily_ai_digest"
    assert len(post.platform["ai_digest"]["items"]) == 8
    assert post.platform["ai_digest"]["source_meta"]["sources"] == ["fixture"]


def test_ai_digest_post_title_uses_featured_item_and_compacts_common_wording():
    brief = AIDigestBrief(
        title="每日AI讯息",
        subtitle="AI平台、模型、工具和开源动态简报",
        date="2026-07-29",
        items=[
            AIUpdateItem(
                title="Claude 发现加密算法弱点，Anthropic 发布新研究",
                summary="Anthropic 介绍 Claude 在密码学安全分析中的新进展。",
                source_name="Anthropic",
                source_type="official",
                url="https://www.anthropic.com/research/example",
                published_at="2026-07-29T08:00:00+08:00",
                vendor="Anthropic",
            )
        ],
    )

    assert create_post._ai_digest_post_title(brief) == "每日AI|Claude发现加密弱点"


def test_ai_digest_post_title_uses_newest_featured_item_instead_of_first_source_tier():
    brief = AIDigestBrief(
        title="每日AI讯息",
        date="2026-07-29",
        items=[
            AIUpdateItem(
                title="百度千帆 Agent 模型服务升级及切换公告",
                source_name="百度千帆",
                source_type="official",
                url="https://cloud.baidu.com/doc/qianfan/update",
                published_at="2026-07-28T08:00:00+08:00",
                vendor="百度千帆",
            ),
            AIUpdateItem(
                title="Anthropic 研究：Claude 发现加密算法弱点",
                source_name="Anthropic 原始页面（AI HOT 汇总）",
                source_type="aggregator",
                url="https://www.anthropic.com/research/example",
                published_at="2026-07-29T08:00:00+08:00",
                vendor="Anthropic",
            ),
        ],
    )

    assert create_post._ai_digest_post_title(brief) == "每日AI|Claude发现加密弱点"


def test_create_daily_ai_digest_passes_workspace_source_health_path_to_collector(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    collect_kwargs: list[dict] = []

    def fake_collect(**kwargs):
        collect_kwargs.append(kwargs)
        return _updates(10), {"sources": ["fixture"], "social_backfill_used": False}

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: (_ for _ in ()).throw(RuntimeError("no test llm")))

    create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)

    assert collect_kwargs
    assert Path(collect_kwargs[0]["source_health_path"]) == Path("data") / "source_health" / "ai_digest.json"
    assert collect_kwargs[0]["persist_source_health"] is True


def test_create_daily_ai_digest_posts_uses_llm_brief_for_chinese_items(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_DIGEST_TARGET_ITEMS", raising=False)
    monkeypatch.delenv("AI_DIGEST_MAX_AGE_DAYS", raising=False)
    english_item = AIUpdateItem(
        title="OpenAI launches new developer tools",
        summary="Developers can build agent workflows with new API features.",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/news/tools",
        published_at=_fresh_published_at(),
        vendor="OpenAI",
        product="API",
        raw_excerpt="OpenAI launches new developer tools for agent workflows.",
        tags=["AI"],
    )
    chinese_item = AIUpdateItem(
        title="OpenAI发布开发者工具更新",
        summary="OpenAI更新开发者工具，重点面向智能体工作流和API调用体验，方便开发者更快搭建自动化应用。",
        source_name="OpenAI",
        source_type="official",
        url="https://openai.com/news/tools",
        published_at=_fresh_published_at(),
        vendor="OpenAI",
        product="API",
        raw_excerpt="OpenAI launches new developer tools for agent workflows.",
        tags=["AI工具"],
    )
    pool = [english_item, *_updates(7)]
    calls: list[list[AIUpdateItem]] = []
    collect_kwargs: list[dict] = []
    llm_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        return pool, {"sources": ["fixture"], "social_backfill_used": False}

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [object()])

    def fake_generate_ai_digest_brief_with_llm(_cfgs, items, **kwargs):
        calls.append(items)
        llm_kwargs.append(kwargs)
        return AIDigestBrief(
            title="每日AI讯息",
            subtitle="AI平台与工具更新",
            date=kwargs.get("date") or "2026-06-30",
            items=[chinese_item, *items[1:8]],
            source_summary="主要来源：OpenAI。",
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate_ai_digest_brief_with_llm)

    posts = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)

    assert len(calls) == 1
    assert {item.url for item in calls[0]} == {item.url for item in pool}
    assert collect_kwargs[0]["target_count"] == 24
    assert collect_kwargs[0]["max_age_days"] == 14
    assert collect_kwargs[0]["include_pool_items"] is True
    assert collect_kwargs[0]["force_search_backfill"] is True
    assert collect_kwargs[0]["min_domestic_model_count"] == 3
    assert collect_kwargs[0]["min_foreign_ai_count"] == 3
    assert llm_kwargs[0]["target_count"] == 8
    assert llm_kwargs[0]["min_domestic_model_count"] == 3
    assert llm_kwargs[0]["min_foreign_ai_count"] == 3
    assert posts[0].platform["ai_digest"]["generation_mode"] == "llm"
    assert posts[0].platform["ai_digest"]["candidate_pool_target"] == 24
    assert posts[0].platform["ai_digest"]["actual_items"] == 8
    titles = [item["title"] for item in posts[0].platform["ai_digest"]["items"]]
    assert "OpenAI发布开发者工具更新" in titles
    summaries = [item["summary"] for item in posts[0].platform["ai_digest"]["items"]]
    assert any("开发者工具" in summary for summary in summaries)
    assert "https://openai.com/news/tools" in posts[0].body


def test_create_daily_ai_digest_passes_exact_quota_safe_selection_to_llm(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    pool = _updates(14)
    captured: list[list[AIUpdateItem]] = []

    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (pool, {"sources": ["fixture"], "social_backfill_used": False}),
    )
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [object()])

    def fake_generate(_cfgs, items, **kwargs):
        captured.append(list(items))
        return create_post.build_fallback_brief(
            list(items),
            target_count=kwargs["target_count"],
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate)

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]

    assert len(captured) == 1
    assert len(captured[0]) == 8
    assert post.platform["ai_digest"]["quota_counts"]["domestic_model"] >= 3
    assert post.platform["ai_digest"]["quota_counts"]["foreign_ai"] >= 3


def test_create_daily_ai_digest_posts_collects_expanded_pool_and_records_counts(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_DIGEST_TARGET_ITEMS", "4")
    monkeypatch.setenv("AI_DIGEST_CANDIDATE_POOL_FACTOR", "3")
    monkeypatch.setenv("AI_DIGEST_MAX_AGE_DAYS", "3")
    pool = _updates(24)
    collect_kwargs: list[dict] = []
    llm_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        return pool, {
            "sources": ["fixture"],
            "fetched_count": 30,
            "fresh_count": 20,
            "deduped_count": 12,
            "ranked_count": 12,
            "social_backfill_used": False,
        }

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [object()])

    def fake_generate_ai_digest_brief_with_llm(_cfgs, items, **kwargs):
        llm_kwargs.append(kwargs)
        return AIDigestBrief(
            title="每日AI讯息",
            subtitle="模型与工具更新",
            date="2026-07-02",
            items=items[:8],
            source_summary="主要来源：fixture。",
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate_ai_digest_brief_with_llm)

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]

    assert collect_kwargs[0]["target_count"] == 24
    assert meta["target_items"] == 8
    assert meta["candidate_pool_target"] == 24
    assert meta["selection_pool_items"] == 24
    assert meta["actual_items"] == 8
    assert meta["quota_counts"]["domestic_model"] >= 3
    assert meta["quota_counts"]["foreign_ai"] >= 3
    assert llm_kwargs[0]["target_count"] == 8
    assert "候选池：抓取30条，近3日20条，去重后12条，发布8条" in post.body


def test_create_daily_ai_digest_posts_auto_expands_to_seven_days(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_DIGEST_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("AI_DIGEST_LOOKBACK_DAYS", raising=False)
    monkeypatch.delenv("CONTENT_LOOKBACK_DAYS", raising=False)
    collect_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        pool = _updates(8)
        older = (
            (datetime.now(timezone.utc) - timedelta(days=4))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        pool = [
            item.model_copy(update={"published_at": older})
            if idx >= 5
            else item
            for idx, item in enumerate(pool)
        ]
        return pool, {
            "sources": ["fixture"],
            "fetched_count": len(pool),
            "fresh_count": len(pool),
            "deduped_count": len(pool),
            "ranked_count": len(pool),
            "social_backfill_used": False,
        }

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: (_ for _ in ()).throw(RuntimeError("no test llm")))

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]

    assert [kwargs["max_age_days"] for kwargs in collect_kwargs] == [14]
    assert meta["max_age_days"] == 7
    assert meta["actual_items"] == 8
    lookback = meta["source_meta"]["lookback"]
    assert lookback["mode"] == "auto_expand"
    assert lookback["selected_max_age_days"] == 7
    assert [attempt["max_age_days"] for attempt in lookback["attempts"]] == [3, 7]
    assert [attempt["selection_pool_items"] for attempt in lookback["attempts"]] == [5, 8]


def test_create_daily_ai_digest_posts_default_lookback_fetches_once_at_largest_window(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_DIGEST_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("AI_DIGEST_LOOKBACK_DAYS", raising=False)
    monkeypatch.delenv("CONTENT_LOOKBACK_DAYS", raising=False)
    collect_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        return _updates(8), {
            "sources": ["fixture"],
            "fetched_count": 8,
            "fresh_count": 8,
            "deduped_count": 8,
            "ranked_count": 8,
            "social_backfill_used": False,
        }

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: (_ for _ in ()).throw(RuntimeError("no test llm")))

    create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)

    assert [kwargs["max_age_days"] for kwargs in collect_kwargs] == [14]


def test_create_daily_ai_digest_posts_fixed_lookback_days_does_not_expand(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_DIGEST_MAX_AGE_DAYS", raising=False)
    collect_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        return _updates(5), {
            "sources": ["fixture"],
            "fetched_count": 5,
            "fresh_count": 5,
            "deduped_count": 5,
            "ranked_count": 5,
            "social_backfill_used": False,
        }

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)

    with pytest.raises(RuntimeError, match="daily ai digest material insufficient"):
        create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True, lookback_days=3)

    assert [kwargs["max_age_days"] for kwargs in collect_kwargs] == [3]


def test_create_daily_ai_digest_posts_falls_back_when_llm_breaks_quota(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    pool = _updates(8)
    foreign_extra = [
        AIUpdateItem(
            title=f"OpenAI GPT 额外更新{i}",
            summary="OpenAI 发布 GPT API 和开发者工具更新。",
            source_name="OpenAI",
            source_type="official",
            url=f"https://openai.com/news/extra-{i}",
            published_at=_fresh_published_at(),
            vendor="OpenAI",
            product=f"GPT-extra-{i}",
            raw_excerpt="OpenAI GPT API update.",
            tags=["AI"],
        )
        for i in range(2)
    ]

    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (pool, {"sources": ["fixture"], "social_backfill_used": False}),
    )
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [object()])

    def fake_generate_ai_digest_brief_with_llm(_cfgs, _items, **kwargs):
        return AIDigestBrief(
            title="每日AI讯息",
            subtitle="模型与工具更新",
            date=kwargs.get("date") or "2026-07-02",
            items=[pool[0], pool[1], pool[3], pool[4], pool[5], pool[6], *foreign_extra],
            source_summary="主要来源：fixture。",
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate_ai_digest_brief_with_llm)

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]

    assert meta["generation_mode"] == "llm_quota_fallback"
    assert "国内模型资讯不足3条" in meta["llm_error"]
    assert meta["actual_items"] == 8
    assert meta["quota_counts"]["domestic_model"] >= 3
    assert meta["quota_counts"]["foreign_ai"] >= 3


def test_create_daily_ai_digest_fallback_selects_quotas_from_full_pool(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def published(minutes_ago: int) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")

    neutral = [
        AIUpdateItem(
            title=f"ModelX-{i} 发布模型与 API 更新",
            summary="独立实验室发布模型、API 与开发者工具更新。",
            source_name=f"Neutral Lab {i}",
            source_type="official",
            url=f"https://neutral-{i}.example.com/model-release",
            published_at=published(i + 1),
            vendor=f"Neutral Lab {i}",
            product=f"ModelX-{i}",
            raw_excerpt=f"ModelX-{i} model release and API update.",
            tags=["AI"],
        )
        for i in range(8)
    ]
    domestic = [
        AIUpdateItem(
            title=f"智谱 GLM-{i} 发布模型版本",
            summary="智谱发布 GLM 模型版本与 API 更新。",
            source_name="智谱",
            source_type="official",
            url=f"https://bigmodel.cn/news/glm-{i}",
            published_at=published(30 + i),
            vendor="智谱",
            product=f"GLM-{i}",
            raw_excerpt=f"智谱 GLM-{i} 模型发布。",
            tags=["AI模型"],
        )
        for i in range(3)
    ]
    foreign = [
        AIUpdateItem(
            title=f"OpenAI GPT-{i} 发布模型版本",
            summary="OpenAI 发布 GPT 模型版本与开发者 API 更新。",
            source_name="OpenAI",
            source_type="official",
            url=f"https://openai.com/news/gpt-{i}",
            published_at=published(40 + i),
            vendor="OpenAI",
            product=f"GPT-{i}",
            raw_excerpt=f"OpenAI GPT-{i} model release.",
            tags=["AI模型"],
        )
        for i in range(3)
    ]
    pool = [*neutral, *domestic, *foreign]

    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (pool, {"sources": ["fixture"], "social_backfill_used": False}),
    )
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: (_ for _ in ()).throw(RuntimeError("test LLM unavailable")),
    )

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]

    assert meta["actual_items"] == 8
    assert meta["quota_counts"]["domestic_model"] >= 3
    assert meta["quota_counts"]["foreign_ai"] >= 3


def test_create_daily_ai_digest_prefers_sources_not_used_by_uploaded_history(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    pool = _updates(24)
    historical_items = pool[:8]
    historical_post = create_post.Post(
        title="每日AI讯息",
        status=PostStatus.saved_draft,
        uploaded=True,
        platform={
            "ai_digest": {
                "mode": "daily_ai_digest",
                "items": [item.model_dump() for item in historical_items],
            }
        },
    )

    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (pool, {"sources": ["fixture"], "social_backfill_used": False}),
    )
    monkeypatch.setattr(create_post, "list_posts", lambda: [historical_post], raising=False)
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: (_ for _ in ()).throw(RuntimeError("test LLM unavailable")),
    )

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    selected_urls = {item["url"] for item in post.platform["ai_digest"]["items"]}
    historical_urls = {item.url for item in historical_items}
    history_meta = post.platform["ai_digest"]["source_meta"]["historical_novelty"]

    assert selected_urls.isdisjoint(historical_urls)
    assert history_meta["historical_key_count"] == 8
    assert history_meta["novel_candidate_count"] >= 8
    assert history_meta["reused_selected_count"] == 0


def test_create_daily_ai_digest_expands_lookback_when_history_reuse_would_hit_duplicate_gate(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    pool = _updates(14)
    recent_at = (
        (datetime.now(timezone.utc) - timedelta(days=4))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    older_at = (
        (datetime.now(timezone.utc) - timedelta(days=8))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    for index, item in enumerate(pool):
        item.published_at = recent_at if index < 8 else older_at

    historical_post = create_post.Post(
        title="每日AI讯息",
        status=PostStatus.saved_draft,
        uploaded=True,
        platform={
            "ai_digest": {
                "mode": "daily_ai_digest",
                "items": [item.model_dump() for item in pool[:6]],
            }
        },
    )

    monkeypatch.setattr(
        create_post,
        "collect_ai_digest_updates",
        lambda **_kwargs: (
            pool,
            {
                "sources": ["fixture"],
                "_fetched_items": pool,
                "social_backfill_used": False,
            },
        ),
    )
    monkeypatch.setattr(create_post, "list_posts", lambda: [historical_post])
    monkeypatch.setattr(
        create_post,
        "load_llm_configs",
        lambda: (_ for _ in ()).throw(RuntimeError("test LLM unavailable")),
    )

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]["source_meta"]

    assert meta["lookback"]["selected_max_age_days"] == 14
    assert (
        meta["historical_novelty"]["reused_selected_count"]
        <= meta["historical_novelty"]["max_reused_before_duplicate_gate"]
    )
    assert "历史资讯复用6条" in meta["lookback"]["attempts"][1]["error"]


def test_create_post_with_draft_routes_daily_ai_digest(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        create_post,
        "create_daily_ai_digest_posts",
        lambda **_kwargs: [
            create_post.Post(
                title="每日AI讯息",
                body="每日AI讯息\n\n发布时间：2026-06-30",
                assets=[],
                platform={"ai_digest": {"mode": "daily_ai_digest"}},
            )
        ],
    )

    post = create_post.create_post_with_draft(
        title_hint="每日AI讯息",
        prompt_hint="",
        asset_paths=[],
        auto_image=False,
    )

    assert post.title == "每日AI讯息"
    assert post.platform["ai_digest"]["mode"] == "daily_ai_digest"
