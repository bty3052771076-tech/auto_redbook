from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.ai_digest.models import AIDigestBrief
from src.ai_digest.generate import build_fallback_brief
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.render import CARD_SIZE, _paginate_items, render_ai_digest_cards


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
    source_diverse = [
        item.model_copy(update={"source_name": f"Vendor{i}", "vendor": f"Vendor{i}"})
        for i, item in enumerate(
            [_item(i, "这是一条简短的 AI 动态摘要，说明模型、产品或工具更新。") for i in range(10)]
        )
    ]
    brief = build_fallback_brief(
        source_diverse,
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


def test_render_ai_digest_long_text_stays_inside_card_bounds(monkeypatch, tmp_path: Path):
    from PIL import ImageDraw

    drawn: list[tuple[tuple[int, int], str, object]] = []
    real_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        font = kwargs.get("font")
        drawn.append((xy, str(text), font))
        return real_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    items = [
        AIUpdateItem(
            title=f"Gemini API Managed Agents 默认升级并新增开发者环境钩子与预算控制功能{i}",
            summary=(
                "这是一条较长的模型与开发工具更新摘要，用于验证中文、EnglishModelName、"
                "数字参数和长来源名称都不会越过卡片边界或遮挡后续内容。"
            ),
            source_name="Hacker News 热门（buzzing.cc 中文翻译）",
            source_type="search",
            url=f"https://example.com/long-{i}",
            published_at="2026-07-29T08:00:00+08:00",
            vendor="Hacker News 热门（buzzing.cc 中文翻译）",
            raw_excerpt="AI model release with long metadata.",
            verification_status="social_confirmed",
            tags=["AI"],
        )
        for i in range(8)
    ]
    brief = AIDigestBrief(
        title="每日AI讯息",
        subtitle=(
            "2026年7月29日：Claude发现加密弱点、OpenAI转录模型API、"
            "Kimi K3开源、豆包搜索服务上线"
        ),
        date="2026-07-29",
        items=items,
        source_summary=(
            "本期资讯来源涵盖 Anthropic 官方社交账号、MarkTechPost、Hacker News 热门、"
            "OpenAI Developers、Google Blog RSS、火山引擎公众号及月之暗面公众号，"
            "均经公开来源交叉核验确认。"
        ),
    )

    render_ai_digest_cards(brief, tmp_path / "digest")

    assert drawn
    for (x, y), text, font in drawn:
        if font is None:
            continue
        left, top, right, bottom = font.getbbox(text)
        assert x + (right - left) <= CARD_SIZE[0] - 50
        assert y + (bottom - top) <= CARD_SIZE[1] - 100
