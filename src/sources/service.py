"""Unified, bounded news source service.

This module is intentionally independent from the content generator.  It can
reuse the existing API collector through a callback, while adding reviewed
RSS sources and an optional World Monitor digest supplement.  The callback
keeps legacy provider behavior stable during migration and prevents a second
copy of every API adapter from emerging here.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from xml.etree import ElementTree

from src.network.tls import https_context

from .models import SourceArticle, SourceSpec, SourceRequest, SourceSnapshot
from .registry import SourceRegistry

try:
    from src.integrations.worldmonitor.client import WorldMonitorClient
    from src.integrations.worldmonitor.runtime import WorldMonitorRuntime
    from src.integrations.worldmonitor.adapter import batch_to_source_records
except ImportError:  # pragma: no cover - optional until World Monitor integration is installed
    WorldMonitorClient = None  # type: ignore[assignment]
    WorldMonitorRuntime = None  # type: ignore[assignment]
    batch_to_source_records = None  # type: ignore[assignment]


LegacyFetcher = Callable[..., tuple[list[Any], dict[str, Any]]]
ProgressCallback = Callable[[str, str, dict[str, Any]], None]

_TAG_RE = re.compile(r"\{[^}]+\}")
_MAX_FEED_BYTES = 4 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    """Reject unreviewed feed redirects instead of following them blindly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover - urllib calls this
        raise ValueError(f"feed redirect rejected: HTTP {code}")


def _strip_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _localize_dt(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _find_text(node: ElementTree.Element, *names: str) -> str:
    wanted = set(names)
    for child in list(node):
        if _TAG_RE.sub("", child.tag).lower() in wanted:
            return "".join(child.itertext()).strip()
    return ""


def _find_link(node: ElementTree.Element, base_url: str) -> str:
    for child in list(node):
        if _TAG_RE.sub("", child.tag).lower() != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        relation = str(child.attrib.get("rel") or "alternate").lower()
        text = (href or "" if relation in {"alternate", ""} else "")
        if not text:
            text = "".join(child.itertext()).strip()
        if text:
            return urljoin(base_url, text)
    return ""


def parse_feed_bytes(body: bytes, *, source: SourceSpec) -> list[SourceArticle]:
    if len(body) > _MAX_FEED_BYTES:
        raise ValueError("feed exceeds maximum size")
    root = ElementTree.fromstring(body)
    root_name = _TAG_RE.sub("", root.tag).lower()
    nodes = []
    if root_name == "rss":
        channel = next((item for item in list(root) if _TAG_RE.sub("", item.tag).lower() == "channel"), root)
        nodes = [item for item in list(channel) if _TAG_RE.sub("", item.tag).lower() == "item"]
    elif root_name == "feed":
        nodes = [item for item in list(root) if _TAG_RE.sub("", item.tag).lower() == "entry"]
    else:
        raise ValueError("unsupported feed root")
    results: list[SourceArticle] = []
    for node in nodes:
        title = _strip_html(_find_text(node, "title"))
        url = _find_link(node, source.source_url)
        if not title or not url or urlsplit(url).scheme not in {"http", "https"}:
            continue
        published = _localize_dt(
            _find_text(node, "pubdate", "published", "updated", "date", "dc:date")
        )
        description = _strip_html(_find_text(node, "description", "summary", "content", "encoded"))
        article_id = sha256(f"{source.publisher_id}\n{url}".encode("utf-8")).hexdigest()[:24]
        results.append(SourceArticle(
            article_id=article_id,
            title=title,
            url=url,
            publisher_id=source.publisher_id,
            publisher_family=source.publisher_family,
            discovery_source_id=source.source_id,
            discovery_kind=source.discovery_kind,
            network_group=source.network_group,
            description=description,
            published_at=published,
            language=source.languages[0] if source.languages else "",
            evidence_status="lead",
            discovery_paths=(source.source_id,),
        ))
    return results


def _article_key(item: Any) -> tuple[str, str]:
    url = str(getattr(item, "url", "") or (item.get("url") if isinstance(item, Mapping) else "") or "").strip()
    title = str(getattr(item, "title", "") or (item.get("title") if isinstance(item, Mapping) else "") or "").strip().lower()
    return url, re.sub(r"\s+", " ", title)


def _legacy_to_article(item: Any, *, source_id: str = "legacy_api") -> SourceArticle | None:
    if isinstance(item, Mapping):
        get = item.get
    else:
        get = lambda key, default=None: getattr(item, key, default)
    title = str(get("title") or "").strip()
    url = str(get("url") or "").strip()
    if not title or not url:
        return None
    source = str(get("source") or get("provider") or source_id).strip()
    provider = str(get("provider") or source_id).strip()
    published = str(get("seendate") or get("published_at") or "").strip()
    return SourceArticle(
        article_id=sha256(f"{provider}\n{url}".encode("utf-8")).hexdigest()[:24],
        title=title,
        url=url,
        publisher_id=source.lower().replace(" ", "_"),
        publisher_family=source.lower().replace(" ", "_"),
        discovery_source_id=provider,
        discovery_kind="api" if provider not in {"google_rss", "bbc_rss"} else "rss",
        network_group=provider,
        description=str(get("description") or "").strip(),
        content=str(get("content") or "").strip(),
        published_at=published,
        language=str(get("language") or "").strip(),
        category="",
        evidence_status="lead",
        discovery_paths=(provider,),
        raw={"provider": provider, "source": source},
    )


@dataclass
class UnifiedNewsSourceService:
    registry: SourceRegistry
    snapshot_dir: Path = Path("data") / "runs" / "news_sources"
    max_workers: int = 4
    worldmonitor_timeout_s: float = 6.0
    _request_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_environment(cls) -> "UnifiedNewsSourceService":
        return cls(
            registry=SourceRegistry.load(),
            snapshot_dir=Path(os.getenv("NEWS_SOURCE_SNAPSHOT_DIR") or "data/runs/news_sources"),
            max_workers=max(1, min(8, int(os.getenv("NEWS_SOURCE_CONCURRENCY") or "4"))),
            worldmonitor_timeout_s=max(1.0, float(os.getenv("WORLDMONITOR_TIMEOUT_S") or "6")),
        )

    def _fetch_rss(self, spec: SourceSpec, timeout_s: float) -> tuple[list[SourceArticle], dict[str, Any]]:
        parsed = urlsplit(spec.source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("registry RSS URL must be HTTPS")
        request = Request(spec.source_url, headers={"Accept": "application/rss+xml, application/atom+xml, application/xml", "User-Agent": "redbook-workflow-source/1.0"})
        opener = build_opener(_NoRedirect, HTTPSHandler(context=https_context()))
        with opener.open(request, timeout=max(0.5, timeout_s)) as response:
            body = response.read(_MAX_FEED_BYTES + 1)
        if len(body) > _MAX_FEED_BYTES:
            raise ValueError("feed exceeds maximum size")
        items = parse_feed_bytes(body, source=spec)
        return items, {"source_id": spec.source_id, "status": "success", "item_count": len(items)}

    def _fetch_worldmonitor(self, spec: SourceSpec, timeout_s: float) -> tuple[list[SourceArticle], dict[str, Any]]:
        if WorldMonitorClient is None or WorldMonitorRuntime is None or batch_to_source_records is None:
            return [], {"source_id": spec.source_id, "status": "unavailable", "error": "worldmonitor adapter unavailable"}
        base_url = (os.getenv("WORLDMONITOR_BASE_URL") or "http://127.0.0.1:3000").rstrip("/")
        root = (os.getenv("WORLDMONITOR_DIR") or "").strip()
        auto_start = str(os.getenv("WORLDMONITOR_AUTO_START", "0")).lower() in {"1", "true", "yes", "on"}
        client = WorldMonitorClient(base_url, timeout=timeout_s)
        runtime = WorldMonitorRuntime(client, root=Path(root) if root else None, auto_start=auto_start)
        try:
            probe = runtime.ensure_ready()
            if not probe.ready:
                return [], {"source_id": spec.source_id, "status": "unavailable", "error": str(probe.message)}
            batch = client.fetch_digest(variant="full", lang="zh", reuse_cycle=False)
            records = batch_to_source_records(batch)
            items = []
            for record in records:
                url = str(record.get("url") or "").strip()
                title = str(record.get("title") or "").strip()
                if not title or not url:
                    continue
                items.append(SourceArticle(
                    article_id=sha256(f"worldmonitor\n{url}".encode("utf-8")).hexdigest()[:24],
                    title=title,
                    url=url,
                    publisher_id=str(record.get("source") or "unknown").strip().lower().replace(" ", "_"),
                    publisher_family=str(record.get("source") or "unknown").strip().lower().replace(" ", "_"),
                    discovery_source_id=spec.source_id,
                    discovery_kind="service_digest",
                    network_group="worldmonitor_local",
                    description=str(record.get("description") or "").strip(),
                    published_at=str(record.get("published_at") or "").strip(),
                    category=str(record.get("category") or "").strip(),
                    stale=bool(record.get("served_stale")),
                    evidence_status="lead",
                    discovery_paths=(spec.source_id,),
                    raw={"coverage_state": record.get("coverage_state"), "served_stale": record.get("served_stale")},
                ))
            return items, {
                "source_id": spec.source_id,
                "status": "success",
                "item_count": len(items),
                "coverage_state": batch.coverage.state,
                "served_stale": batch.coverage.served_stale,
            }
        finally:
            runtime.release()

    def _selected_specs(self, request: SourceRequest) -> tuple[SourceSpec, ...]:
        values = list(self.registry.select(request.source_packs))
        if not str(os.getenv("WORLDMONITOR_DIR") or "").strip() and not str(os.getenv("WORLDMONITOR_BASE_URL") or "").strip():
            values = [item for item in values if item.adapter != "worldmonitor_digest"]
        if str(os.getenv("UNIFIED_WORLDMONITOR", "1")).lower() in {"0", "false", "no", "off"}:
            values = [item for item in values if item.adapter != "worldmonitor_digest"]
        return tuple(values)

    def _save_snapshot(self, snapshot: SourceSnapshot) -> Path:
        target = self.snapshot_dir / snapshot.request.run_id / f"{snapshot.snapshot_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return target

    def search(
        self,
        request: SourceRequest,
        *,
        legacy_fetcher: LegacyFetcher | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SourceSnapshot:
        started = time.perf_counter()
        deadline = started + request.timeout_s
        specs = self._selected_specs(request)
        articles: list[SourceArticle] = []
        attempts: list[dict[str, Any]] = []

        def report(stage: str, status: str, detail: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(stage, status, detail)

        def legacy_task() -> tuple[list[SourceArticle], dict[str, Any]]:
            if legacy_fetcher is None:
                return [], {"status": "not_configured"}
            remaining = max(0.5, deadline - time.monotonic())
            raw, meta = legacy_fetcher(
                request.prompt,
                max_records=request.max_records,
                search_days=request.search_days,
                timeout_s=min(remaining, request.timeout_s),
                exhaustive_sources=True,
                additional_queries=request.additional_queries,
                progress_callback=None,
            )
            values = [item for raw_item in raw if (item := _legacy_to_article(raw_item)) is not None]
            return values, {"status": "success", "item_count": len(values), "legacy_meta": meta}

        tasks: dict[Any, tuple[str, str]] = {}
        worker_count = max(1, min(self.max_workers, len(specs) + (1 if legacy_fetcher else 0)))
        executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="news-source")
        try:
            if legacy_fetcher is not None:
                future = executor.submit(legacy_task)
                tasks[future] = ("legacy_api", "api")
            for spec in specs:
                if spec.adapter == "rss":
                    future = executor.submit(self._fetch_rss, spec, min(request.timeout_s, max(0.5, deadline - time.monotonic())))
                elif spec.adapter == "worldmonitor_digest":
                    future = executor.submit(self._fetch_worldmonitor, spec, min(self.worldmonitor_timeout_s, max(0.5, deadline - time.monotonic())))
                else:
                    continue
                tasks[future] = (spec.source_id, spec.adapter)
            pending = set(tasks)
            while pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        for future in pending:
                            source_id, adapter = tasks[future]
                            future.cancel()
                            attempts.append({"source_id": source_id, "status": "deadline_exceeded", "adapter": adapter})
                        break
                    done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        source_id, adapter = tasks[future]
                        try:
                            values, attempt = future.result()
                            articles.extend(values)
                            attempts.append({"adapter": adapter, **attempt})
                            report("统一信源采集", "success", {"source_id": source_id, "count": len(values)})
                        except Exception as exc:
                            attempts.append({"source_id": source_id, "adapter": adapter, "status": "failed", "error": str(exc)})
                            report("统一信源采集", "warning", {"source_id": source_id, "error": str(exc)})
            for future in pending:
                future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        unique: dict[tuple[str, str], SourceArticle] = {}
        for item in articles:
            key = _article_key(item)
            if key == ("", ""):
                continue
            old = unique.get(key)
            if old is None:
                unique[key] = item
            else:
                paths = tuple(dict.fromkeys((*old.discovery_paths, *item.discovery_paths)))
                # Prefer direct/primary evidence and non-stale records when two
                # collectors expose the same article.
                preferred = item if (old.stale and not item.stale) or (
                    old.discovery_kind == "search_rss" and item.discovery_kind == "native_rss"
                ) else old
                unique[key] = SourceArticle(**{
                    **preferred.to_dict(),
                    "discovery_paths": paths,
                })
        values = tuple(unique.values())
        target = max(request.target_count, request.max_records)
        selected = values[:target]
        warnings: list[str] = []
        if any(attempt.get("status") in {"failed", "unavailable", "deadline_exceeded"} for attempt in attempts):
            warnings.append("部分信源不可用或超过本轮预算，已保留其他信源结果")
        if any(item.stale for item in selected):
            warnings.append("World Monitor 陈旧批次仅作为线索，必须经过正文与日期核验")
        status = "ready" if len(selected) >= request.target_count else ("partial" if selected else "unavailable")
        gaps = () if len(selected) >= request.target_count else (f"usable_events<{request.target_count}",)
        coverage = {
            "registry_version": self.registry.version,
            "planned_sources": len(specs) + (1 if legacy_fetcher else 0),
            "attempts": len(attempts),
            "successful_sources": sum(1 for item in attempts if item.get("status") == "success"),
            "unique_publishers": len({item.publisher_family for item in selected if item.publisher_family}),
            "network_groups": sorted({item.network_group for item in selected if item.network_group}),
            "raw_articles": len(articles),
            "unique_articles": len(values),
            "selected_articles": len(selected),
            "source_attempts": attempts,
        }
        snapshot = SourceSnapshot(
            snapshot_id=sha256(f"{request.run_id}:{request.request_id}:{time.time_ns()}".encode()).hexdigest()[:24],
            request=request,
            status=status,
            items=selected,
            decisions=(),
            coverage=coverage,
            gaps=gaps,
            warnings=tuple(warnings),
            timings={"wall_seconds": round(time.perf_counter() - started, 3)},
        )
        path = self._save_snapshot(snapshot)
        coverage["snapshot_path"] = str(path)
        return snapshot


def source_snapshot_items(snapshot: SourceSnapshot) -> list[dict[str, Any]]:
    """Return normalized dictionaries for legacy consumers and diagnostics."""
    return [item.to_dict() for item in snapshot.items]
