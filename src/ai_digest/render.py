from __future__ import annotations

import math
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import AIDigestBrief, AIUpdateItem


CARD_SIZE = (1104, 1472)
MAX_XHS_IMAGES = 18


def _font(size: int, *, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap_text(text: str, width: int) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        lines.extend(textwrap.wrap(paragraph, width=width, replace_whitespace=False, drop_whitespace=True))
    return lines


def _item_weight(item: AIUpdateItem) -> int:
    return 120 + len(item.title or "") * 2 + len(item.summary or "") + len(item.vendor or "")


def _paginate_items(items: list[AIUpdateItem], *, page_budget: int = 390) -> list[list[AIUpdateItem]]:
    pages: list[list[AIUpdateItem]] = []
    current: list[AIUpdateItem] = []
    current_weight = 0
    for item in items:
        weight = _item_weight(item)
        if current and current_weight + weight > page_budget:
            pages.append(current)
            current = []
            current_weight = 0
        current.append(item)
        current_weight += weight
    if current:
        pages.append(current)
    return pages[: max(1, MAX_XHS_IMAGES - 1)]


def _new_card() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", CARD_SIZE, "#f8f2e7")
    draw = ImageDraw.Draw(img)
    # Warm editorial background.
    draw.rectangle([0, 0, CARD_SIZE[0], 148], fill="#151b1f")
    draw.rectangle([0, CARD_SIZE[1] - 96, CARD_SIZE[0], CARD_SIZE[1]], fill="#e6d6bd")
    draw.rounded_rectangle([56, 188, CARD_SIZE[0] - 56, CARD_SIZE[1] - 132], radius=34, fill="#fffaf1")
    return img, draw


def _draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, *, width: int, fill: str, line_gap: int = 10) -> int:
    x, y = xy
    line_height = max(24, int(font.size * 1.35)) if hasattr(font, "size") else 28
    for line in _wrap_text(text, width):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_gap
    return y


def _render_cover(brief: AIDigestBrief, path: Path) -> None:
    img, draw = _new_card()
    title_font = _font(68, bold=True)
    subtitle_font = _font(34)
    body_font = _font(30)
    small_font = _font(24)

    draw.text((70, 42), "Auto Redbook AI Brief", font=small_font, fill="#f4dfbf")
    draw.text((96, 300), brief.title or "每日AI讯息", font=title_font, fill="#1f292e")
    draw.text((100, 402), brief.date or "", font=subtitle_font, fill="#b75f35")
    subtitle = brief.subtitle or "AI平台、模型、工具和开源动态简报"
    _draw_wrapped(draw, (100, 492), subtitle, subtitle_font, width=25, fill="#39454b", line_gap=12)

    count_text = f"本期整理 {len(brief.items)} 条动态"
    draw.rounded_rectangle([100, 710, 520, 792], radius=24, fill="#1f292e")
    draw.text((132, 730), count_text, font=body_font, fill="#fff7e8")

    source = brief.source_summary or "官方源为主，社交源用于补充与验证。"
    _draw_wrapped(draw, (100, 880), source, body_font, width=30, fill="#4e5a60", line_gap=12)
    draw.text((82, CARD_SIZE[1] - 64), "来源链接已保存至本地 metadata", font=small_font, fill="#51483d")
    img.save(path, format="PNG")


def _render_items_page(brief: AIDigestBrief, page_items: list[AIUpdateItem], path: Path, *, page_no: int, total_pages: int) -> None:
    img, draw = _new_card()
    header_font = _font(34, bold=True)
    title_font = _font(34, bold=True)
    body_font = _font(27)
    meta_font = _font(22)

    draw.text((70, 42), f"{brief.title or '每日AI讯息'}  {page_no}/{total_pages}", font=header_font, fill="#f4dfbf")
    y = 226
    for idx, item in enumerate(page_items, 1):
        draw.rounded_rectangle([86, y - 18, CARD_SIZE[0] - 86, y + 252], radius=24, fill="#f2eadc")
        vendor = item.vendor or item.source_name or "AI"
        draw.text((116, y), f"{vendor}", font=meta_font, fill="#b75f35")
        y += 38
        y = _draw_wrapped(draw, (116, y), item.title, title_font, width=24, fill="#1f292e", line_gap=6)
        y += 4
        y = _draw_wrapped(draw, (116, y), item.summary, body_font, width=31, fill="#334047", line_gap=6)
        status = "官方源"
        if item.verification_status == "social_confirmed":
            status = "官方源 + 社交验证"
        elif item.source_type == "social":
            status = "社交补充"
        draw.text((116, y + 6), f"{status} / {item.source_name}", font=meta_font, fill="#756e62")
        y += 292
    draw.text((82, CARD_SIZE[1] - 64), "长链接不写入图片，完整来源保存在本地", font=meta_font, fill="#51483d")
    img.save(path, format="PNG")


def render_ai_digest_cards(
    brief: AIDigestBrief,
    dest_dir: Path,
    *,
    size: tuple[int, int] = CARD_SIZE,
) -> list[Path]:
    if size != CARD_SIZE:
        # Keep the public argument for future expansion; current layout is tuned
        # for the Xiaohongshu vertical-card default.
        raise ValueError(f"unsupported size: {size}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    pages = _paginate_items(list(brief.items or []))
    total_pages = 1 + len(pages)
    total_pages = min(total_pages, MAX_XHS_IMAGES)

    paths: list[Path] = []
    cover = dest_dir / "ai_digest_00_cover.png"
    _render_cover(brief, cover)
    paths.append(cover)
    for index, page_items in enumerate(pages, 1):
        if len(paths) >= MAX_XHS_IMAGES:
            break
        path = dest_dir / f"ai_digest_{index:02d}.png"
        _render_items_page(brief, page_items, path, page_no=index, total_pages=max(1, total_pages - 1))
        paths.append(path)
    return paths
