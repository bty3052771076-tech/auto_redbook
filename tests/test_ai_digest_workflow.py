from __future__ import annotations

from pathlib import Path

from src.ai_digest.models import AIUpdateItem
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
