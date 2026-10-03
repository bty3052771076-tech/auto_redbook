from __future__ import annotations

import os
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.integrations.worldmonitor.client import WorldMonitorClient
from src.integrations.worldmonitor.runtime import WorldMonitorRuntime

from .workflow import create_global_map_post
from .models import GlobalMapRequest
from .workflow import build_global_map_snapshot


def _service_client_and_runtime():
    base_url = (os.getenv("WORLDMONITOR_BASE_URL") or "http://127.0.0.1:3000").rstrip("/")
    client = WorldMonitorClient(base_url, timeout=float(os.getenv("WORLDMONITOR_TIMEOUT_S", "12")))
    root = (os.getenv("WORLDMONITOR_DIR") or "").strip()
    auto_start = str(os.getenv("WORLDMONITOR_AUTO_START", "0")).lower() in {"1", "true", "yes", "on"}
    parsed = urlsplit(base_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 3000)
    runtime = WorldMonitorRuntime(client, root=Path(root) if root else None, auto_start=auto_start, port=port)
    return client, runtime


def build_global_map_preview(*, client, runtime, request: GlobalMapRequest) -> dict[str, object]:
    try:
        probe = runtime.ensure_ready()
        if not probe.ready:
            raise RuntimeError(f"{probe.error_code or 'WM_NOT_READY'}: {probe.message}")
        # The readiness probe performs a request to the same client.  Refresh
        # here so a stale probe response can never become the map snapshot.
        batch = client.fetch_digest(reuse_cycle=False)
        snapshot = build_global_map_snapshot(
            batch,
            target_date=request.target_date,
            cutoff=request.cutoff_at,
            max_events=request.max_events,
            map_mode=request.map_mode,
        )
        return {
            "frozen_scope": request.to_dict(),
            "source_state": batch.coverage.state,
            "served_stale": batch.coverage.served_stale,
            "coverage": {
                "raw_items": snapshot.raw_item_count,
                "independent_events": snapshot.independent_event_count,
                "eligible_events": len(snapshot.events),
                "located_events": snapshot.located_event_count,
                "countries": snapshot.country_count,
                "publishers": snapshot.publisher_count,
            },
            "quality_state": snapshot.coverage_status,
            "upload_allowed": snapshot.upload_allowed,
            "warning": snapshot.warning,
            "events": snapshot.to_dict()["events"],
        }
    finally:
        runtime.release()


def preview_global_map_from_service(*, request: GlobalMapRequest) -> dict[str, object]:
    client, runtime = _service_client_and_runtime()
    return build_global_map_preview(client=client, runtime=runtime, request=request)


def create_global_map_post_from_service(
    *,
    output_dir: Path | None = None,
    target_date: str | None = None,
    request: GlobalMapRequest | None = None,
) :
    enabled = str(os.getenv("GLOBAL_MAP_ENABLED", "0")).lower() in {"1", "true", "yes", "on"}
    if not enabled:
        raise RuntimeError("GLOBAL_MAP_DISABLED: set GLOBAL_MAP_ENABLED=1 before using the map workflow")
    client, runtime = _service_client_and_runtime()
    try:
        probe = runtime.ensure_ready()
        if not probe.ready:
            raise RuntimeError(f"{probe.error_code}: {probe.message}")
        # Do not reuse the readiness probe's cached response for publication.
        batch = client.fetch_digest(reuse_cycle=False)
        if request is None:
            cutoff = datetime.now(timezone.utc)
            beijing = cutoff.astimezone(timezone(timedelta(hours=8)))
            request = GlobalMapRequest.from_mapping({
                "target_date": target_date or beijing.date().isoformat(),
                "cutoff_at": cutoff,
            })
        return create_global_map_post(
            batch,
            target_date=request.target_date,
            cutoff=request.cutoff_at,
            max_events=request.max_events,
            map_mode=request.map_mode,
            output_dir=output_dir or Path("data") / "global_map",
        )
    finally:
        runtime.release()
