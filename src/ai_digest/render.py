from __future__ import annotations

import textwrap
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import AIDigestBrief, AIUpdateItem
from .rank import featured_ai_update


CARD_SIZE = (1104, 1472)
MAX_XHS_IMAGES = 18
_NO_LINE_START_PUNCTUATION = "，。！？；：、）》】』’”％%"
_NUMBER_UNIT_CHARS = "条个家项次种人万亿天年元"


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


def _wrap_text(text: str, width: int, *, max_lines: int | None = None) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        lines.extend(textwrap.wrap(paragraph, width=width, replace_whitespace=False, drop_whitespace=True))
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("，,。；; ") + "…"
    return lines


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text or "", font=font)
    return max(0, right - left)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, *, max_width_px: int) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if _text_width(draw, value, font) <= max_width_px:
        return value
    suffix = "…"
    while value and _text_width(draw, f"{value}{suffix}", font) > max_width_px:
        value = value[:-1].rstrip()
    return f"{value}{suffix}" if value else suffix


def _wrap_text_pixels(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    *,
    max_width_px: int,
    max_lines: int | None = None,
) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        tokens = re.findall(r"[A-Za-z0-9@._+:/()\-]+|\s+|.", paragraph.strip())
        line = ""
        for token in tokens:
            candidate = f"{line}{token}"
            if line and _text_width(draw, candidate, font) > max_width_px:
                if token in _NO_LINE_START_PUNCTUATION and len(line) > 1:
                    # Keep Chinese closing punctuation attached to the text it
                    # closes instead of starting a visually broken new line.
                    trailing_size = 2 if line[-1:] in _NUMBER_UNIT_CHARS and line[-2:-1].isdigit() else 1
                    trailing = line[-trailing_size:]
                    lines.append(line[:-trailing_size].rstrip())
                    line = f"{trailing}{token}"
                elif token in _NUMBER_UNIT_CHARS and line[-1:].isdigit() and len(line) > 1:
                    # Keep common number-unit pairs such as “2条” together.
                    trailing = line[-1:]
                    lines.append(line[:-1].rstrip())
                    line = f"{trailing}{token}"
                else:
                    lines.append(line.rstrip())
                    line = token.lstrip()
            else:
                line = candidate
            while line and _text_width(draw, line, font) > max_width_px:
                split_at = len(line) - 1
                while split_at > 1 and _text_width(draw, line[:split_at], font) > max_width_px:
                    split_at -= 1
                lines.append(line[:split_at].rstrip())
                line = line[split_at:].lstrip()
        if line:
            lines.append(line.rstrip())
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit_text(
            draw,
            f"{lines[-1].rstrip('，,。；; ')}…",
            font,
            max_width_px=max_width_px,
        )
    return lines


def _fits_within_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    *,
    max_width_px: int,
    max_lines: int,
) -> bool:
    return len(
        _wrap_text_pixels(
            draw,
            text,
            font,
            max_width_px=max_width_px,
            max_lines=None,
        )
    ) <= max_lines


def _complete_text_for_layout(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    *,
    max_width_px: int,
    max_lines: int,
) -> str:
    """Prefer complete sentences/clauses before applying the layout cap."""

    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean or _fits_within_lines(
        draw,
        clean,
        font,
        max_width_px=max_width_px,
        max_lines=max_lines,
    ):
        return clean

    sentences = [part.strip() for part in re.split(r"(?<=[。！？；;])", clean) if part.strip()]
    for sentence in sentences:
        if _fits_within_lines(
            draw,
            sentence,
            font,
            max_width_px=max_width_px,
            max_lines=max_lines,
        ):
            return sentence

    first_sentence = re.split(r"[。！？；;]", clean, maxsplit=1)[0].strip()
    clauses = [part.strip() for part in re.split(r"[，,]", first_sentence) if part.strip()]
    candidate = ""
    for clause in clauses:
        next_candidate = f"{candidate}，{clause}" if candidate else clause
        if _fits_within_lines(
            draw,
            next_candidate,
            font,
            max_width_px=max_width_px,
            max_lines=max_lines,
        ):
            candidate = next_candidate
            continue
        break
    if candidate:
        return candidate

    # Last resort for a single unbroken token: keep the visible prefix without
    # adding an ellipsis that looks like a half-written sentence.
    lines = _wrap_text_pixels(
        draw,
        clean,
        font,
        max_width_px=max_width_px,
        max_lines=None,
    )
    return "".join(lines[:max_lines]).rstrip("，,；;：:")


def _paginate_items(items: list[AIUpdateItem], *, min_per_page: int = 2, max_per_page: int = 3) -> list[list[AIUpdateItem]]:
    """Group updates into 2-3 item pages, avoiding lonely one-item pages."""
    if not items:
        return []
    pages: list[list[AIUpdateItem]] = []
    index = 0
    total = len(items)
    while index < total:
        remaining = total - index
        if remaining <= max_per_page:
            pages.append(items[index:total])
            break
        take = max_per_page
        if remaining - take == 1 and take > min_per_page:
            take -= 1
        pages.append(items[index : index + take])
        index += take
    return pages[: max(1, MAX_XHS_IMAGES - 1)]


def _new_card() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", CARD_SIZE, "#f8f2e7")
    draw = ImageDraw.Draw(img)
    # Warm editorial background.
    draw.rectangle([0, 0, CARD_SIZE[0], 148], fill="#151b1f")
    draw.rectangle([0, CARD_SIZE[1] - 96, CARD_SIZE[0], CARD_SIZE[1]], fill="#e6d6bd")
    draw.rounded_rectangle([56, 188, CARD_SIZE[0] - 56, CARD_SIZE[1] - 132], radius=34, fill="#fffaf1")
    return img, draw


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    *,
    width: int,
    fill: str,
    line_gap: int = 10,
    max_lines: int | None = None,
    max_width_px: int | None = None,
) -> int:
    x, y = xy
    line_height = max(24, int(font.size * 1.35)) if hasattr(font, "size") else 28
    display_text = text
    if max_lines is not None and max_width_px is not None:
        display_text = _complete_text_for_layout(
            draw,
            text,
            font,
            max_width_px=max_width_px,
            max_lines=max_lines,
        )
    lines = (
        _wrap_text_pixels(
            draw,
            display_text,
            font,
            max_width_px=max_width_px,
            max_lines=max_lines,
        )
        if max_width_px is not None
        else _wrap_text(display_text, width, max_lines=max_lines)
    )
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + line_gap
    return y


def _format_published_at(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if "T" in text or ":" in text:
            return dt.strftime("%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return text[:16]


def _featured_item(brief: AIDigestBrief) -> AIUpdateItem | None:
    return featured_ai_update(list(brief.items or []))


def _cover_title_parts(
    brief_title: str,
    featured: AIUpdateItem | None,
) -> tuple[str, str]:
    """Return a stable cover label and a separately wrapped headline."""

    clean = re.sub(r"\s+", " ", (brief_title or "").strip())
    for separator in ("|", "｜"):
        if separator not in clean:
            continue
        label, headline = (part.strip() for part in clean.split(separator, 1))
        if label and headline:
            return label, headline

    label = "每日AI讯息"
    if clean and clean != label:
        return label, clean
    return label, (featured.title or "").strip() if featured else ""


def _render_cover(brief: AIDigestBrief, path: Path) -> None:
    img, draw = _new_card()
    title_font = _font(68, bold=True)
    headline_font = _font(48, bold=True)
    subtitle_font = _font(34)
    body_font = _font(30)
    small_font = _font(24)

    draw.text((70, 42), "AI动态简报", font=small_font, fill="#f4dfbf")
    featured = _featured_item(brief)
    cover_label, cover_headline = _cover_title_parts(brief.title, featured)
    title_y = 252
    title_bottom = _draw_wrapped(
        draw,
        (96, title_y),
        cover_label,
        title_font,
        width=20,
        fill="#1f292e",
        line_gap=8,
        max_lines=1,
        max_width_px=CARD_SIZE[0] - 192,
    )
    headline_bottom = title_bottom
    if cover_headline:
        headline_bottom = _draw_wrapped(
            draw,
            (100, title_bottom + 14),
            cover_headline,
            headline_font,
            width=24,
            fill="#39454b",
            line_gap=8,
            max_lines=2,
            max_width_px=CARD_SIZE[0] - 200,
        )
    date_y = headline_bottom + 16
    draw.text((100, date_y), brief.date or "", font=subtitle_font, fill="#b75f35")
    subtitle = brief.subtitle or "AI平台、模型、工具和开源动态简报"
    subtitle_y = date_y + 58
    subtitle_bottom = _draw_wrapped(
        draw,
        (100, subtitle_y),
        subtitle,
        subtitle_font,
        width=25,
        fill="#39454b",
        line_gap=12,
        max_lines=3,
        max_width_px=CARD_SIZE[0] - 200,
    )
    featured_top = max(690, subtitle_bottom + 28)
    featured_bottom = featured_top + 230
    draw.rounded_rectangle(
        [100, featured_top, CARD_SIZE[0] - 100, featured_bottom],
        radius=30,
        fill="#1f292e",
    )
    draw.text((132, featured_top + 30), "今日重点", font=small_font, fill="#f4dfbf")
    if featured:
        _draw_wrapped(
            draw,
            (132, featured_top + 74),
            featured.title,
            body_font,
            width=27,
            fill="#fff7e8",
            line_gap=8,
            max_lines=2,
            max_width_px=CARD_SIZE[0] - 264,
        )
        meta = " · ".join(
            part
            for part in (
                featured.source_name or featured.vendor,
                _format_published_at(featured.published_at),
            )
            if part
        )
        if meta:
            draw.text(
                (132, featured_bottom - 48),
                _fit_text(draw, meta, small_font, max_width_px=CARD_SIZE[0] - 264),
                font=small_font,
                fill="#d7c4a7",
            )

    _draw_wrapped(
        draw,
        (100, featured_bottom + 42),
        brief.source_summary or "官方源为主，社交源用于补充与验证。",
        body_font,
        width=30,
        fill="#4e5a60",
        line_gap=12,
        max_lines=4,
        max_width_px=CARD_SIZE[0] - 200,
    )
    img.save(path, format="PNG")


def _render_items_page(brief: AIDigestBrief, page_items: list[AIUpdateItem], path: Path, *, page_no: int, total_pages: int) -> None:
    img, draw = _new_card()
    header_font = _font(34, bold=True)
    title_font = _font(34, bold=True)
    body_font = _font(27)
    meta_font = _font(22)

    header_label, _ = _cover_title_parts(brief.title, _featured_item(brief))
    draw.text(
        (70, 42),
        f"{_fit_text(draw, header_label, header_font, max_width_px=CARD_SIZE[0] - 140)}  {page_no}/{total_pages}",
        font=header_font,
        fill="#f4dfbf",
    )
    top = 222
    bottom = CARD_SIZE[1] - 146
    gap = 26
    count = max(1, len(page_items))
    box_height = int((bottom - top - gap * (count - 1)) / count)
    y = top
    for idx, item in enumerate(page_items, 1):
        box_bottom = y + box_height
        draw.rounded_rectangle([86, y - 12, CARD_SIZE[0] - 86, box_bottom], radius=28, fill="#f2eadc")
        vendor = item.vendor or item.source_name or "AI"
        draw.text(
            (116, y + 20),
            _fit_text(draw, vendor, meta_font, max_width_px=CARD_SIZE[0] - 232),
            font=meta_font,
            fill="#b75f35",
        )
        text_y = y + 62
        text_y = _draw_wrapped(
            draw,
            (116, text_y),
            item.title,
            title_font,
            width=24,
            fill="#1f292e",
            line_gap=6,
            max_lines=2,
            max_width_px=CARD_SIZE[0] - 232,
        )
        text_y += 8
        status_y = box_bottom - 38
        line_height = max(24, int(body_font.size * 1.35)) + 6
        max_summary_lines = max(3, int((status_y - text_y - 8) / line_height))
        _draw_wrapped(
            draw,
            (116, text_y),
            item.summary,
            body_font,
            width=31,
            fill="#334047",
            line_gap=6,
            max_lines=max_summary_lines,
            max_width_px=CARD_SIZE[0] - 232,
        )
        status = "官方源"
        if item.verification_status == "social_confirmed":
            status = "交叉核验"
        elif item.verification_status == "aggregator_confirmed":
            status = "整合站核验"
        elif item.source_type == "aggregator":
            status = "资讯整合站"
        elif item.verification_status == "search_only":
            status = "搜索来源"
        elif item.source_type == "social":
            status = "社交补充"
        published = _format_published_at(item.published_at) or brief.date or "待核验"
        source_name = item.source_name or item.vendor or "公开来源"
        meta = f"发布时间：{published} · 来源：{source_name} · {status}"
        draw.text(
            (116, status_y),
            _fit_text(draw, meta, meta_font, max_width_px=CARD_SIZE[0] - 232),
            font=meta_font,
            fill="#756e62",
        )
        y = box_bottom + gap
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
    # Rendering is also used to rebuild cards from saved local metadata. Run
    # the same title/summary completeness checks here so an older brief cannot
    # reintroduce a truncated headline into the images.
    from .generate import _ensure_chinese_brief

    brief = _ensure_chinese_brief(brief)
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
