"""Load and draw a versioned, local world basemap.

The map workflow must never silently turn a missing basemap into a coordinate
grid.  This module deliberately uses the GeoJSON already shipped with the
local World Monitor checkout (or an explicitly configured path) and a simple
equirectangular projection that matches the event coordinate contract.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class BasemapAsset:
    path: Path
    sha256: str
    feature_count: int
    projection: str = "equirectangular"
    bounds: tuple[float, float, float, float] = (-180.0, -90.0, 180.0, 90.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "feature_count": self.feature_count,
            "projection": self.projection,
            "bounds": list(self.bounds),
        }


def resolve_basemap_path(explicit: str | Path | None = None) -> Path:
    configured = explicit or os.getenv("GLOBAL_MAP_BASEMAP_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates: list[Path] = []
    worldmonitor_dir = str(os.getenv("WORLDMONITOR_DIR") or "").strip()
    if worldmonitor_dir:
        candidates.append(Path(worldmonitor_dir) / "public" / "data" / "countries.geojson")

    # This is a local development convenience only. Server deployments should
    # set GLOBAL_MAP_BASEMAP_PATH or WORLDMONITOR_DIR explicitly.
    candidates.append(Path.cwd().parent / "worldmonitor" / "public" / "data" / "countries.geojson")
    candidates.append(Path(__file__).resolve().parents[2] / "worldmonitor" / "public" / "data" / "countries.geojson")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0] if candidates else Path("countries.geojson")


def load_basemap(path: str | Path | None = None) -> BasemapAsset:
    asset_path = resolve_basemap_path(path)
    if not asset_path.is_file():
        raise RuntimeError(
            "MAP_ASSET_MISSING: 未找到真实世界底图；请配置 GLOBAL_MAP_BASEMAP_PATH "
            "或 WORLDMONITOR_DIR/public/data/countries.geojson"
        )
    try:
        raw = json.loads(asset_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"MAP_ASSET_INVALID: 无法读取世界底图 {asset_path}") from exc
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection":
        raise RuntimeError("MAP_ASSET_INVALID: 底图必须是 GeoJSON FeatureCollection")
    features = raw.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("MAP_ASSET_INVALID: GeoJSON 没有可绘制的国家/地区几何数据")
    valid = sum(1 for item in features if isinstance(item, dict) and isinstance(item.get("geometry"), dict))
    if valid <= 0:
        raise RuntimeError("MAP_ASSET_INVALID: GeoJSON 没有有效 geometry")
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    return BasemapAsset(path=asset_path, sha256=digest, feature_count=valid)


def _project(lon: float, lat: float, box: tuple[float, float, float, float]) -> tuple[float, float]:
    left, top, right, bottom = box
    lon = max(-180.0, min(180.0, float(lon)))
    lat = max(-90.0, min(90.0, float(lat)))
    return (
        left + (lon + 180.0) / 360.0 * (right - left),
        top + (90.0 - lat) / 180.0 * (bottom - top),
    )


def _rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Polygon" and isinstance(coords, list):
        for ring in coords:
            if isinstance(ring, list):
                yield ring
    elif kind == "MultiPolygon" and isinstance(coords, list):
        for polygon in coords:
            if isinstance(polygon, list):
                for ring in polygon:
                    if isinstance(ring, list):
                        yield ring


def draw_basemap(draw, asset: BasemapAsset, map_box: tuple[float, float, float, float]) -> int:
    """Draw land masses and coastlines; return the number of rendered rings."""

    try:
        raw = json.loads(asset.path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"MAP_ASSET_INVALID: 无法绘制世界底图 {asset.path}") from exc

    left, top, right, bottom = map_box
    water = "#111f35"
    land = "#294b63"
    coast = "#6f9ab3"
    rendered = 0
    for feature in raw.get("features", []):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict):
            continue
        feature_rings = list(_rings(geometry))
        if not feature_rings:
            continue
        for ring_index, ring in enumerate(feature_rings):
            points: list[tuple[float, float]] = []
            for pair in ring:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                try:
                    points.append(_project(float(pair[0]), float(pair[1]), map_box))
                except (TypeError, ValueError):
                    continue
            if len(points) < 3:
                continue
            # Holes are redrawn as water; the source geometry remains the
            # authority for shape and no country label is invented here.
            fill = land if ring_index == 0 else water
            draw.polygon(points, fill=fill)
            draw.line(points + [points[0]], fill=coast, width=1, joint="curve")
            rendered += 1
    if rendered == 0:
        raise RuntimeError("MAP_ASSET_INVALID: 底图没有可绘制的多边形")
    return rendered


def validate_map_artifact(path: str | Path, *, map_box: tuple[int, int, int, int]) -> dict[str, Any]:
    from PIL import Image

    artifact = Path(path)
    try:
        image = Image.open(artifact).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"MAP_RENDER_FAILED: 无法重新读取地图图片 {artifact}") from exc
    left, top, right, bottom = map_box
    crop = image.crop((left, top, right, bottom))
    # Land is deliberately a stable color family; counting it makes a grid or
    # a blank navy rectangle fail even when the PNG itself is non-empty.
    land_pixels = sum(1 for pixel in crop.getdata() if pixel[0] in range(35, 50) and pixel[1] in range(60, 85) and pixel[2] in range(75, 110))
    if land_pixels < 100:
        raise RuntimeError("MAP_RENDER_FAILED: 地图区域没有检测到真实陆地轮廓")
    return {"width": image.width, "height": image.height, "land_pixels": land_pixels}
