from __future__ import annotations

from pathlib import Path

from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.storage.models import PostStatus
from src.workflow import create_post


def _updates(n: int = 10) -> list[AIUpdateItem]:
    return [
        AIUpdateItem(
            title=f"AI动态{i}",
            summary=f"第{i}条 AI 动态摘要，说明产品、模型或开源工具的重要变化。",
            source_name="OpenAI",
            source_type="official",
            url=f"https://example.com/{i}",
            published_at="2026-06-30T08:00:00Z",
            vendor="OpenAI",
            product="ChatGPT",
            raw_excerpt=f"raw {i}",
            tags=["AI"],
        )
        for i in range(n)
    ]


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
    assert post.title == "每日AI讯息"
    assert post.status == PostStatus.draft
    assert post.assets
    assert all(Path(asset.path).exists() for asset in post.assets)
    assert post.platform["ai_digest"]["mode"] == "daily_ai_digest"
    assert len(post.platform["ai_digest"]["items"]) == 10
    assert post.platform["ai_digest"]["source_meta"]["sources"] == ["fixture"]


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
        published_at="2026-06-30T08:00:00Z",
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
        published_at="2026-06-30T08:00:00Z",
        vendor="OpenAI",
        product="API",
        raw_excerpt="OpenAI launches new developer tools for agent workflows.",
        tags=["AI工具"],
    )
    calls: list[list[AIUpdateItem]] = []
    collect_kwargs: list[dict] = []
    llm_kwargs: list[dict] = []

    def fake_collect_ai_digest_updates(**kwargs):
        collect_kwargs.append(kwargs)
        return [english_item], {"sources": ["fixture"], "social_backfill_used": False}

    monkeypatch.setattr(create_post, "collect_ai_digest_updates", fake_collect_ai_digest_updates)
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [object()])

    def fake_generate_ai_digest_brief_with_llm(_cfgs, items, **kwargs):
        calls.append(items)
        llm_kwargs.append(kwargs)
        return AIDigestBrief(
            title="每日AI讯息",
            subtitle="AI平台与工具更新",
            date=kwargs.get("date") or "2026-06-30",
            items=[chinese_item],
            source_summary="主要来源：OpenAI。",
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate_ai_digest_brief_with_llm)

    posts = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)

    assert calls == [[english_item]]
    assert collect_kwargs[0]["target_count"] == 60
    assert collect_kwargs[0]["max_age_days"] == 3
    assert llm_kwargs[0]["target_count"] == 1
    assert posts[0].platform["ai_digest"]["generation_mode"] == "llm"
    assert posts[0].platform["ai_digest"]["candidate_pool_target"] == 60
    assert posts[0].platform["ai_digest"]["actual_items"] == 1
    assert posts[0].platform["ai_digest"]["items"][0]["title"] == "OpenAI发布开发者工具更新"
    assert "开发者工具" in posts[0].platform["ai_digest"]["items"][0]["summary"]
    assert "https://openai.com/news/tools" in posts[0].body


def test_create_daily_ai_digest_posts_collects_expanded_pool_and_records_counts(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_DIGEST_TARGET_ITEMS", "4")
    monkeypatch.setenv("AI_DIGEST_CANDIDATE_POOL_FACTOR", "3")
    monkeypatch.setenv("AI_DIGEST_MAX_AGE_DAYS", "3")
    pool = _updates(12)
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
            items=items[:4],
            source_summary="主要来源：fixture。",
        )

    monkeypatch.setattr(create_post, "generate_ai_digest_brief_with_llm", fake_generate_ai_digest_brief_with_llm)

    post = create_post.create_daily_ai_digest_posts(asset_paths=[], copy_assets=True)[0]
    meta = post.platform["ai_digest"]

    assert collect_kwargs[0]["target_count"] == 12
    assert meta["target_items"] == 4
    assert meta["candidate_pool_target"] == 12
    assert meta["selection_pool_items"] == 12
    assert meta["actual_items"] == 4
    assert llm_kwargs[0]["target_count"] == 4
    assert "候选池：抓取30条，近3日20条，去重后12条，发布4条" in post.body


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
