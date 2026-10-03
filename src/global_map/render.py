from __future__ import annotations

from pathlib import Path

from .basemap import draw_basemap, load_basemap, validate_map_artifact
from .models import MapSnapshot


def _font(path: Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int, *, max_lines: int = 2) -> list[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return ["暂无标题"]
    lines: list[str] = []
    current = ""
    for char in value:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(lines) == max_lines and current and "".join(lines) != value:
        tail = lines[-1].rstrip()
        while tail and draw.textbbox((0, 0), tail + "…", font=font)[2] > max_width:
            tail = tail[:-1]
        lines[-1] = (tail or "…") + "…"
    return lines[:max_lines]


def render_global_map(
    snapshot: MapSnapshot,
    output_path: Path,
    *,
    width: int = 1080,
    height: int = 1440,
    basemap_path: str | Path | None = None,
) -> Path:
    """Render a real local world map with deterministic event overlays.

    A missing or invalid basemap is a hard error. The old coordinate-only
    rendering was visually non-empty but was not a map and must not be used for
    a platform draft.
    """

    from PIL import Image, ImageDraw

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    asset = load_basemap(basemap_path)
    image = Image.new("RGB", (width, height), "#0b1324")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = _font(font_path, 34)
    small = _font(font_path, 22)
    tiny = _font(font_path, 18)
    # The map is fixed at 1080x1440 for mobile publishing.  Keep all event
    # rows visible when eight long headlines are selected instead of failing
    # after collecting valid evidence.  This is a layout mode only; it does
    # not drop events or alter their ranking.
    compact_index = len(snapshot.events) >= 7
    event_font = _font(font_path, 17 if compact_index else 22)
    event_detail_font = _font(font_path, 14 if compact_index else 18)
    event_line_height = 22 if compact_index else 29
    event_detail_height = 20 if compact_index else 30
    event_gap = 4 if compact_index else 12
    draw.text((48, 38), f"今日全球事件关注图 · {snapshot.target_date}", fill="#f7fbff", font=font)
    draw.text((48, 88), "关注度来自已采集并核验的公开信源，不代表全球风险真值", fill="#9db1c9", font=small)
    map_box = (48, 145, width - 48, 760)
    draw.rounded_rectangle(map_box, radius=18, fill="#111f35", outline="#2d4b70", width=2)
    left, top, right, bottom = map_box
    draw_basemap(draw, asset, map_box)
    for index in range(1, 6):
        x = left + (right - left) * index / 6
        draw.line((x, top, x, bottom), fill="#243d5c", width=1)
    for index in range(1, 5):
        y = top + (bottom - top) * index / 5
        draw.line((left, y, right, y), fill="#243d5c", width=1)

    located_index = 0
    for event in snapshot.events:
        if event.latitude is None or event.longitude is None:
            continue
        located_index += 1
        x = left + (float(event.longitude) + 180) / 360 * (right - left)
        y = top + (90 - float(event.latitude)) / 180 * (bottom - top)
        radius = 10 + int(20 * min(max(event.score, 0.0), 1.0))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill="#ff6b5f", outline="#ffd1a8", width=2)
        label = str(located_index)
        bbox = draw.textbbox((0, 0), label, font=tiny)
        draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2 - 1), label, fill="#192337", font=tiny)

    draw.text((left + 16, bottom - 34), "本地世界底图 · 编号对应下方事件 · 点位精度以正文为准", fill="#b7cfdf", font=tiny)
    y = 815
    draw.text((48, y), f"入选事件 {len(snapshot.events)} · 已定位 {snapshot.located_event_count} · 覆盖国家 {snapshot.country_count}", fill="#f7fbff", font=small)
    y += 48
    if snapshot.warning:
        draw.text((48, y), snapshot.warning, fill="#ffd28a", font=tiny)
        y += 38

    rendered = 0
    for index, event in enumerate(snapshot.events, 1):
        title_lines = _wrap(draw, f"{index}. {event.title}", event_font, width - 96, max_lines=2)
        detail = f"{event.location_name or event.country or '位置未核验'} · {event.publisher_count}个独立信源 · 关注度 {event.score:.2f}"
        needed = len(title_lines) * event_line_height + event_detail_height + event_gap
        if y + needed > height - 30:
            raise RuntimeError("MAP_RENDER_FAILED: 事件索引无法完整排版，请减少重点事件上限")
        for line in title_lines:
            draw.text((48, y), line, fill="#f7fbff", font=event_font)
            y += event_line_height
        draw.text((70, y), detail, fill="#9db1c9", font=event_detail_font)
        y += event_detail_height + event_gap
        rendered += 1
    if rendered != len(snapshot.events):
        raise RuntimeError("MAP_RENDER_FAILED: 事件索引存在未渲染条目")

    image.save(output_path, format="PNG", optimize=True)
    validate_map_artifact(output_path, map_box=(int(left), int(top), int(right), int(bottom)))
    return output_path
