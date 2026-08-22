from __future__ import annotations

import hashlib
import json
import urllib.parse
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .daily_news import NewsItem, parse_manual_news_materials, resolve_manual_material_times


MAX_GUI_MATERIAL_TEXT_BYTES = 1024 * 1024
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class MaterialTextSnapshot:
    path: Path
    item_count: int
    raw_char_count: int
    raw_sha256: str


def _normalize_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise RuntimeError("没有可用文字，请粘贴材料正文。")
    if "\x00" in normalized:
        raise RuntimeError("文字材料包含 NUL 控制字符，请重新粘贴纯文本。")
    if len(normalized.encode("utf-8")) > MAX_GUI_MATERIAL_TEXT_BYTES:
        raise RuntimeError(
            f"文字材料超过 {MAX_GUI_MATERIAL_TEXT_BYTES // 1024} KiB，"
            "请改用材料文件，程序不会静默截断正文。"
        )
    return normalized


def _domain_for_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    return parsed.netloc.strip().lower() or "manual.local"


def _validate_items(items: list[NewsItem]) -> None:
    missing: list[str] = []
    for index, item in enumerate(items, start=1):
        if not str(item.title or "").strip():
            missing.append(f"第{index}条缺少标题")
        if not str(item.content or item.description or "").strip():
            missing.append(f"第{index}条缺少正文")
    if missing:
        raise RuntimeError("；".join(missing) + "。")


def prepare_material_text_snapshot(
    text: str,
    *,
    mode: str,
    requested_count: int,
    default_material_time: str,
    title_override: str = "",
    source_override: str = "",
    url_override: str = "",
    output_dir: str | Path = Path("data/manual_materials/gui_text"),
) -> MaterialTextSnapshot:
    normalized = _normalize_text(text)
    mode_norm = str(mode or "").strip().lower()
    if mode_norm not in {"single", "multiple"}:
        raise RuntimeError("材料类型无效，请选择单条材料或多条材料。")
    requested = max(1, int(requested_count or 1))
    items = parse_manual_news_materials(normalized)

    if mode_norm == "single":
        if len(items) != 1:
            raise RuntimeError(
                f"单条模式必须恰好 1 条，当前解析出 {len(items)} 条；"
                "请删除分隔线，或切换到多条材料。"
            )
        item = items[0]
        title = str(title_override or "").strip()
        source = str(source_override or "").strip()
        url = str(url_override or "").strip()
        if title and not str(item.content or "").strip() and "\n" not in normalized.strip():
            body = normalized.strip()
            item = replace(item, content=body, description=body[:180])
        if title:
            item = replace(item, title=title)
        if source:
            item = replace(item, source=source)
        if url:
            item = replace(item, url=url, domain=_domain_for_url(url))
        items = [item]
    else:
        if any(str(value or "").strip() for value in (title_override, source_override, url_override)):
            raise RuntimeError("多条模式不能填写单条材料的标题、来源或链接覆盖项。")
        if len(items) < requested:
            raise RuntimeError(
                f"多条模式需要至少 {requested} 条材料，当前只有 {len(items)} 条。"
            )

    _validate_items(items)
    resolved_items, _resolved_times = resolve_manual_material_times(
        items,
        default_material_time=str(default_material_time or "").strip(),
    )

    raw_bytes = normalized.encode("utf-8")
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    payload = {
        "schema_version": 1,
        "input_origin": "gui_text",
        "created_at": datetime.now(BEIJING_TZ).isoformat(),
        "raw_char_count": len(normalized),
        "raw_sha256": raw_sha256,
        "items": [asdict(item) for item in resolved_items],
    }

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(BEIJING_TZ).strftime("%Y%m%d_%H%M%S")
    final_path = target_dir / f"{stamp}_{uuid.uuid4().hex}.json"
    temp_path = final_path.with_suffix(".tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(final_path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    return MaterialTextSnapshot(
        path=final_path,
        item_count=len(resolved_items),
        raw_char_count=len(normalized),
        raw_sha256=raw_sha256,
    )
