from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.ai_digest.models import AIDigestBrief
from src.ai_digest.generate import build_fallback_brief
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.render import _paginate_items, render_ai_digest_cards


def _item(
    idx: int,
    summary: str,
    *,
    title: str | None = None,
    published_at: str = "2026-06-30T08:00:00Z",
    confidence_score: float = 0.0,
    evidence_urls: list[str] | None = None,
) -> AIUpdateItem:
    return AIUpdateItem(
        title=title or f"AI工具更新{idx}",
        summary=summary,
        source_name="OpenAI",
        source_type="official",
        url=f"https://example.com/{idx}",
        published_at=published_at,
        vendor="OpenAI",
        product="ChatGPT",
        raw_excerpt=summary,
        confidence_score=confidence_score,
        evidence_urls=evidence_urls or [],
        tags=["AI"],
    )


def test_render_ai_digest_cards_creates_png_assets_with_expected_size(tmp_path: Path):
    brief = build_fallback_brief(
        [_item(i, "这是一个简短更新，说明模型或工具变化。") for i in range(4)],
        target_count=4,
        date="2026-06-30",
    )

    paths = render_ai_digest_cards(brief, tmp_path)

    assert paths
    assert all(path.suffix == ".png" for path in paths)
    with Image.open(paths[0]) as img:
        assert img.size == (1104, 1472)


def test_paginate_items_keeps_two_to_three_updates_per_content_page():
    pages = _paginate_items([_item(i, "短动态。") for i in range(10)])

    assert [len(page) for page in pages] == [3, 3, 2, 2]
    assert all(2 <= len(page) <= 3 for page in pages)


def test_render_ai_digest_cards_uses_two_to_three_updates_per_page(tmp_path: Path):
    brief = build_fallback_brief(
        [_item(i, "这是一条简短的 AI 动态摘要，说明模型、产品或工具更新。") for i in range(10)],
        target_count=10,
        date="2026-06-30",
    )

    paths = render_ai_digest_cards(brief, tmp_path / "digest")

    assert len(paths) == 5
    assert paths[0].name == "ai_digest_00_cover.png"


def test_render_ai_digest_cover_uses_featured_update_instead_of_generic_labels(monkeypatch, tmp_path: Path):
    drawn: list[str] = []

    from PIL import ImageDraw

    real_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return real_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    high_heat = _item(
        1,
        "OpenAI更新Codex CLI，加入浏览器自动化和更细的终端权限控制。",
        title="OpenAI发布Codex CLI浏览器自动化",
        confidence_score=0.97,
        evidence_urls=["https://x.com/OpenAI/status/1", "https://news.ycombinator.com/item?id=1"],
    )
    low_heat = _item(
        2,
        "Anthropic更新文档。",
        title="Anthropic更新开发者文档",
        confidence_score=0.82,
    )
    brief = AIDigestBrief(
        title="每日AI讯息",
        subtitle="AI平台与工具更新",
        date="2026-07-02",
        items=[low_heat, high_heat],
        source_summary="主要来源：OpenAI、Anthropic。",
    )

    render_ai_digest_cards(brief, tmp_path / "digest")

    joined = "\n".join(drawn)
    assert "Auto Redbook AI Brief" not in joined
    assert "本期整理" not in joined
    assert "今日重点" in joined
    assert "Codex CLI浏览器自动化" in joined
    assert "来源链接已保存至本地 metadata" not in joined
    assert "长链接不写入图片，完整来源保存在本地" not in joined


def test_render_ai_digest_item_pages_show_publish_time_and_source_without_footer(monkeypatch, tmp_path: Path):
    drawn: list[str] = []

    from PIL import ImageDraw

    real_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return real_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    brief = build_fallback_brief(
        [
            _item(
                i,
                "这是一条可以追溯到官方链接的 AI 动态摘要。",
                title=f"OpenAI工具更新{i}",
                published_at=f"2026-07-02T0{i}:30:00Z",
            )
            for i in range(3)
        ],
        target_count=3,
        date="2026-07-02",
    )

    render_ai_digest_cards(brief, tmp_path / "digest")

    joined = "\n".join(drawn)
    assert "发布时间：2026-07-02 00:30" in joined
    assert "来源：OpenAI" in joined
    assert "来源链接已保存至本地 metadata" not in joined
    assert "长链接不写入图片，完整来源保存在本地" not in joined
