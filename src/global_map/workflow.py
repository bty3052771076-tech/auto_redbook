from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.integrations.worldmonitor.models import WorldMonitorBatch
from src.storage.models import AssetInfo, Post, PostStatus

from .editorial import build_global_map_editorial
from .basemap import load_basemap
from .evidence import build_verified_events
from .geography import resolve_explicit_country_location
from .models import EventCandidate, MapSnapshot
from .render import render_global_map
from .select import select_events


def build_global_map_snapshot(
    batch: WorldMonitorBatch,
    *,
    target_date: str,
    cutoff: datetime,
    max_events: int = 8,
    map_mode: str = "coordinate-grid",
) -> MapSnapshot:
    candidates = []
    for item in batch.items:
        country = str(item.raw.get("country") or "").strip()
        location_name = item.location_name
        latitude = item.latitude
        longitude = item.longitude
        location_precision = ""
        location_method = ""
        if latitude is None or longitude is None:
            resolved = resolve_explicit_country_location(
                "\n".join((item.title, item.snippet, country, location_name))
            )
            if resolved is not None:
                country = country or resolved.country
                location_name = location_name or f"{resolved.country}（国家级）"
                latitude = resolved.latitude
                longitude = resolved.longitude
                location_precision = resolved.precision
                location_method = resolved.method
        candidates.append(EventCandidate(
            event_key=item.raw.get("storyId") or item.raw.get("story_id") or item.item_id or item.title,
            title=item.title,
            summary=item.snippet,
            source=item.source,
            url=item.url,
            published_at=item.published_at,
            country=country,
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            location_precision=location_precision,
            location_method=location_method,
            authority=_authority(item),
            publisher_family=str(item.raw.get("originPublisher") or item.source),
        ))
    events = build_verified_events(candidates, target_date=target_date, cutoff=cutoff)
    return select_events(
        events,
        max_events=max_events,
        target_date=target_date,
        cutoff=cutoff,
        raw_item_count=len(batch.items),
        source_state=batch.coverage.state,
        map_mode=map_mode,
    )


def save_snapshot(snapshot: MapSnapshot, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_snapshot(snapshot: MapSnapshot, path: Path, *, basemap_path: str | Path | None = None) -> Path:
    return render_global_map(snapshot, path, basemap_path=basemap_path)


def create_global_map_post(
    batch: WorldMonitorBatch,
    *,
    target_date: str,
    cutoff: datetime,
    output_dir: Path,
    max_events: int = 8,
    map_mode: str = "coordinate-grid",
    basemap_path: str | Path | None = None,
) -> Post | None:
    snapshot = build_global_map_snapshot(
        batch,
        target_date=target_date,
        cutoff=cutoff,
        max_events=max_events,
        map_mode=map_mode,
    )
    output_dir = Path(output_dir)
    basemap = load_basemap(basemap_path)
    map_path = render_snapshot(snapshot, output_dir / f"global-map-{target_date}.png", basemap_path=basemap_path)
    save_snapshot(snapshot, output_dir / f"global-map-{target_date}.json")
    if not snapshot.upload_allowed:
        return None

    editorial = build_global_map_editorial(snapshot)
    located_events = [
        event for event in snapshot.events
        if event.latitude is not None and event.longitude is not None
    ]
    body_lines = [
        str(editorial["summary"]),
        f"时间范围：北京时间 {target_date} 00:00 至 {cutoff.astimezone(timezone(timedelta(hours=8))).isoformat(timespec='minutes')}。",
        "以下是本轮信源中已核验、可定位的代表性事件；地图不代表全球全部事件或风险真值。",
    ]
    for index, event in enumerate(located_events, 1):
        title = _compact_text(event.title, 96)
        summary = _compact_text(event.summary, 120) or "具体进展见地图编号和本地证据记录。"
        body_lines.append(
            f"{index}. {title}：{summary}"
            f"（地点：{event.location_name or event.country or '未披露'}；"
            f"独立信源：{event.publisher_count}）"
        )
    body_lines.append("本帖正文不附外部链接，完整证据和来源记录已保存在本地任务目录。")
    body = _bounded_body("\n".join(body_lines), 980)
    map_sha256 = hashlib.sha256(map_path.read_bytes()).hexdigest()
    return Post(
        title=str(editorial["title"]),
        body=body,
        status=PostStatus.draft,
        assets=[AssetInfo(path=str(map_path), kind="image", size_bytes=map_path.stat().st_size, sha256=map_sha256, validated=True)],
        platform={
            "global_map": snapshot.to_dict(),
            "editorial": editorial,
            "basemap": basemap.to_dict(),
            "render_report": {"map_sha256": map_sha256, "basemap_sha256": basemap.sha256, "feature_count": basemap.feature_count},
        },
    )


def _authority(item) -> float:
    if item.credibility_score is not None:
        return max(0.0, min(1.0, item.credibility_score))
    return 0.8 if item.raw.get("originPublisherTrusted") else 0.5


def _compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _bounded_body(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    suffix = "\n完整证据和来源记录已保存在本地任务目录。"
    return text[: max(1, limit - len(suffix))].rstrip() + suffix
