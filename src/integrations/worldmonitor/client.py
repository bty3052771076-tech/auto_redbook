from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .models import WorldMonitorBatch, WorldMonitorCoverage, WorldMonitorItem, _parse_datetime
from src.network.tls import https_context


class WorldMonitorError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


Fetcher = Callable[[str, float], Any]


class WorldMonitorClient:
    """Small, bounded client for the World Monitor digest endpoint."""

    def __init__(self, base_url: str, *, timeout: float = 12.0, fetcher: Fetcher | None = None):
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = max(0.5, float(timeout))
        self.fetcher = fetcher or self._fetch_url
        self._lock = threading.Lock()
        # A digest cache must include the request identity.  Reusing a full
        # English batch for a tech/Chinese request silently contaminates
        # downstream source and date decisions.
        self._in_cycle: dict[tuple[str, str], WorldMonitorBatch] = {}

    def fetch_digest(self, *, variant: str = "full", lang: str = "zh", reuse_cycle: bool = True) -> WorldMonitorBatch:
        with self._lock:
            cache_key = (str(variant or "full"), str(lang or "zh"))
            if reuse_cycle and cache_key in self._in_cycle:
                return self._in_cycle[cache_key]
            query = urllib.parse.urlencode({"variant": variant, "lang": lang, "public": "1"})
            url = f"{self.base_url}/api/news/v1/list-feed-digest?{query}"
            try:
                status, headers, body = _normalise_response(self.fetcher(url, self.timeout))
            except WorldMonitorError:
                raise
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                raise WorldMonitorError("WM_NOT_READY", str(exc)) from exc
            if status < 200 or status >= 300:
                raise WorldMonitorError("WM_NOT_READY", f"HTTP {status}")
            content_type = str(headers.get("content-type", "")).lower()
            if content_type and "json" not in content_type:
                raise WorldMonitorError("WM_INVALID_RESPONSE", f"expected JSON, got {content_type}")
            try:
                payload = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
            except (TypeError, ValueError, UnicodeDecodeError) as exc:
                raise WorldMonitorError("WM_INVALID_RESPONSE", "response is not valid JSON") from exc
            batch = parse_digest_payload(payload)
            if reuse_cycle:
                self._in_cycle[cache_key] = batch
            return batch

    @staticmethod
    def _fetch_url(url: str, timeout: float):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "redbook-workflow/1.0"})
        with urllib.request.urlopen(request, timeout=timeout, context=https_context()) as response:
            return response.status, dict(response.headers.items()), response.read()


def parse_digest_payload(payload: Any) -> WorldMonitorBatch:
    if not isinstance(payload, Mapping):
        raise WorldMonitorError("WM_INVALID_RESPONSE", "top-level response must be an object")
    raw_categories = payload.get("categories") or {}
    raw_items: list[Mapping[str, Any]] = []
    if isinstance(payload.get("items"), list):
        raw_items.extend(item for item in payload["items"] if isinstance(item, Mapping))
    if isinstance(raw_categories, Mapping):
        for category, value in raw_categories.items():
            category_items = value.get("items") if isinstance(value, Mapping) else value
            if isinstance(category_items, list):
                for item in category_items:
                    if isinstance(item, Mapping):
                        merged = dict(item)
                        merged.setdefault("category", category)
                        raw_items.append(merged)
    items = []
    seen: set[tuple[str, str]] = set()
    for value in raw_items:
        item = WorldMonitorItem.from_payload(value)
        if not item.title or not item.url or not item.source:
            continue
        key = (item.url, item.title)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    if not isinstance(payload.get("coverage"), Mapping):
        raise WorldMonitorError("WM_INVALID_RESPONSE", "coverage block is missing")
    categories = {str(key): len(value.get("items", [])) if isinstance(value, Mapping) else 0 for key, value in raw_categories.items()}
    generated_at = _parse_datetime(payload.get("generatedAt", payload.get("generated_at")))
    return WorldMonitorBatch(
        items=items,
        categories=categories,
        coverage=WorldMonitorCoverage.from_payload(payload.get("coverage")),
        generated_at=generated_at,
        raw=dict(payload),
    )


def _normalise_response(value: Any) -> tuple[int, Mapping[str, Any], Any]:
    if isinstance(value, tuple) and len(value) == 3:
        return int(value[0]), value[1] or {}, value[2]
    status = int(getattr(value, "status", getattr(value, "status_code", 200)))
    headers = getattr(value, "headers", {}) or {}
    body = value.read() if hasattr(value, "read") else value
    return status, headers, body
