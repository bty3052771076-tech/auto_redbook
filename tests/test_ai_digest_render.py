from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.ai_digest.generate import build_fallback_brief
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.render import render_ai_digest_cards


def _item(idx: int, summary: str) -> AIUpdateItem:
    return AIUpdateItem(
        title=f"AI工具更新{idx}",
        summary=summary,
        source_name="OpenAI",
        source_type="official",
        url=f"https://example.com/{idx}",
        published_at="2026-06-30T08:00:00Z",
        vendor="OpenAI",
        product="ChatGPT",
        raw_excerpt=summary,
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


def test_render_ai_digest_cards_uses_more_pages_for_longer_updates(tmp_path: Path):
    short = build_fallback_brief(
        [_item(i, "短动态。") for i in range(6)],
        target_count=6,
        date="2026-06-30",
    )
    long = build_fallback_brief(
        [
            _item(
                i,
                "这是一条较长的 AI 动态摘要，包含模型能力、产品影响、开发者使用方式、生态变化和后续关注点。"
                "为了测试自适应分页，这里需要明显增加文本长度，让单页无法容纳过多条目。",
            )
            for i in range(10)
        ],
        target_count=10,
        date="2026-06-30",
    )

    short_paths = render_ai_digest_cards(short, tmp_path / "short")
    long_paths = render_ai_digest_cards(long, tmp_path / "long")

    assert len(long_paths) > len(short_paths)
    assert len(long_paths) <= 18
