from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import urllib.request
from typing import Any, Callable

import certifi

from .fetchers import (
    parse_aihot_daily_html,
    parse_github_releases_json,
    parse_official_html,
    parse_rss_feed,
    parse_social_search_html,
    parse_x_profile_html,
)
from .models import AIUpdateItem
from .rank import ai_digest_quota_counts, dedupe_ai_updates, filter_recent_ai_updates, rank_ai_updates
from .sources import AIDigestSource, resolve_ai_digest_sources
from src.sources.health import (
    SourceAttempt,
    SourceHealthSnapshot,
    is_source_in_cooldown,
    load_source_health_snapshot,
    save_source_health_snapshot,
)


FetchSource = Callable[[AIDigestSource], list[AIUpdateItem]]
ProgressCallback = Callable[[str, str], None]
DEFAULT_SEARCH_BACKFILL_QUERIES = (
    "国内 AI 模型 发布 GLM Qwen 豆包 DeepSeek Kimi MiniMax",
    "AI model release OpenAI Anthropic Claude Gemini GPT Llama Mistral",
    "AI API developer tools model release open source",
)
BEIJING_TZ = timezone(timedelta(hours=8))
_AIHOT_HOST = "aihot.virxact.com"
_VENDOR_OFFICIAL_HOSTS = {
    "openai": ("openai.com",),
    "anthropic": ("anthropic.com",),
    "google deepmind": ("deepmind.google", "google.com", "google.dev", "googleblog.com"),
    "google": ("google.com", "google.dev", "googleblog.com"),
    "deepseek": ("deepseek.com",),
    "minimax": ("minimax.io",),
    "qwen": ("qwen.ai", "aliyun.com"),
    "阿里/qwen": ("qwen.ai", "aliyun.com"),
    "月之暗面 kimi": ("moonshot.cn",),
    "火山方舟/豆包": ("volcengine.com", "bytedance.com"),
    "智谱 glm": ("bigmodel.cn", "z.ai"),
    "xai": ("x.ai",),
    "meta ai": ("meta.com",),
    "mistral ai": ("mistral.ai",),
    "nvidia": ("nvidia.com",),
    "thinking machines lab": ("thinkingmachines.ai",),
    "runway": ("runwayml.com",),
    "langchain": ("langchain.com",),
    "sierra": ("sierra.ai",),
    "cloudflare blog": ("cloudflare.com",),
    "github blog": ("github.blog", "github.com"),
    "apple machine learning research（rss）": ("apple.com",),
    "cursor blog": ("cursor.com",),
}


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        value = float(default)
    return max(min_value, min(max_value, value))


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except ValueError:
        value = int(default)
    return max(min_value, min(max_value, value))


def _health_checked_at(now: datetime | date | None) -> datetime:
    if isinstance(now, datetime):
        value = now
    elif isinstance(now, date):
        value = datetime.combine(now, datetime.min.time())
    else:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _health_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_error_status(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, HTTPError):
        return "http_error"
    if isinstance(exc, URLError) or "connection" in text or "network" in text:
        return "transport_error"
    return "error"


def _source_item_counts(items: list[AIUpdateItem]) -> tuple[int, int, int]:
    item_count = len(items)
    dated_count = sum(1 for item in items if str(item.published_at or "").strip())
    url_count = sum(1 for item in items if str(item.url or "").strip())
    return item_count, dated_count, url_count


def _source_result_status(
    items: list[AIUpdateItem],
    *,
    max_age_days: int | None,
    now: datetime | date | None,
) -> str:
    item_count, dated_count, _url_count = _source_item_counts(items)
    if not item_count:
        return "empty"
    if not dated_count:
        return "missing_date"
    if max_age_days is not None and not filter_recent_ai_updates(
        items,
        max_age_days=max_age_days,
        now=now,
        require_url=False,
    ):
        return "stale"
    return "success"


def _emit_progress(progress: ProgressCallback | None, stage: str, detail: str) -> None:
    if progress is not None:
        progress(stage, detail)


def _curl_executable() -> str:
    if os.name != "nt":
        return ""
    return shutil.which("curl.exe") or ""


def _curl_get_text(url: str, *, timeout_s: float, executable: str) -> str:
    total_timeout = max(1.0, float(timeout_s))
    connect_timeout = min(5.0, total_timeout)
    args = [
        executable,
        "--location",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-redirs",
        "5",
        "--connect-timeout",
        f"{connect_timeout:.1f}",
        "--max-time",
        f"{total_timeout:.1f}",
        "--max-filesize",
        "1500000",
        "--user-agent",
        "Mozilla/5.0 (AutoRedbook AI Digest)",
        "--write-out",
        "\n%{http_code}",
        url,
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            timeout=total_timeout + 2.0,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"curl timed out after {total_timeout:.1f}s for {url}") from exc

    raw = bytes(result.stdout or b"")
    body, separator, status_text = raw.rpartition(b"\n")
    status = 0
    if separator:
        try:
            status = int(status_text.strip() or b"0")
        except ValueError:
            body = raw
    else:
        body = raw
    error_text = bytes(result.stderr or b"").decode("utf-8", errors="replace").strip()
    if status >= 400:
        raise HTTPError(url, status, error_text or f"HTTP {status}", hdrs=None, fp=None)
    if result.returncode != 0:
        raise URLError(error_text or f"curl exited with code {result.returncode} for {url}")
    if status and not 200 <= status < 400:
        raise HTTPError(url, status, f"HTTP {status}", hdrs=None, fp=None)
    return body[:1_500_000].decode("utf-8", errors="replace")


def _http_get_text(url: str, *, timeout_s: float = 12.0) -> str:
    curl_executable = _curl_executable()
    if curl_executable:
        return _curl_get_text(url, timeout_s=timeout_s, executable=curl_executable)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (AutoRedbook AI Digest)"},
        method="GET",
    )
    context = None
    try:
        import ssl

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = None
    with urllib.request.urlopen(req, timeout=timeout_s, context=context) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read(1_500_000).decode(charset, errors="replace")


def _is_aihot_detail_url(url: str) -> bool:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return (host == _AIHOT_HOST or host.endswith(f".{_AIHOT_HOST}")) and parts.path.startswith("/items/")


def _aihot_detail_external_url(html_text: str) -> str:
    html_match = re.search(
        r'(?is)<a(?=[^>]*\bdata-track\s*=\s*["\']click_external["\'])[^>]*\bhref\s*=\s*["\'](?P<url>https?://[^"\']+)',
        html_text or "",
    )
    if html_match:
        return html_match.group("url").strip()
    payload_match = re.search(
        r'(?is)"href":"(?P<url>https?://(?:\\.|[^"\\])+?)".{0,900}?"data-track":"click_external"',
        html_text or "",
    )
    if payload_match:
        try:
            return str(json.loads(f'"{payload_match.group("url")}"')).strip()
        except (TypeError, ValueError, json.JSONDecodeError):
            return payload_match.group("url").strip()
    return ""


def _matches_vendor_official_host(item: AIUpdateItem, url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    vendor = (item.vendor or "").strip().lower()
    expected_hosts = _VENDOR_OFFICIAL_HOSTS.get(vendor, ())
    return any(host == expected or host.endswith(f".{expected}") for expected in expected_hosts)


def resolve_aihot_detail_source(item: AIUpdateItem, *, timeout_s: float = 8.0) -> AIUpdateItem:
    """Attach the original source linked by an AI HOT detail page when it is verifiable."""
    if item.source_type != "aggregator" or not _is_aihot_detail_url(item.url):
        return item
    try:
        external_url = _aihot_detail_external_url(_http_get_text(item.url, timeout_s=timeout_s))
    except Exception:
        return item
    if not external_url:
        return item

    data = item.model_dump()
    evidence = [item.url, *(item.evidence_urls or [])]
    data["url"] = external_url
    data["evidence_urls"] = list(dict.fromkeys(url for url in evidence if url and url != external_url))
    if _matches_vendor_official_host(item, external_url):
        data["source_type"] = "official"
        data["verification_status"] = "aggregator_confirmed"
        # The public-facing source is the verified official page.  Keep the
        # AI HOT detail URL only in evidence_urls for local traceability.
        data["source_name"] = f"{item.vendor} 官网"
        data["confidence_score"] = max(float(item.confidence_score or 0.0), 0.9)
    elif (urlsplit(external_url).hostname or "").lower() in {"x.com", "twitter.com", "www.twitter.com"}:
        data["source_type"] = "social"
        data["verification_status"] = "social_only"
        data["source_name"] = f"{item.vendor} 社交动态（AI HOT 索引）"
    else:
        data["verification_status"] = "aggregator_confirmed"
    return AIUpdateItem.model_validate(data)


def fetch_ai_digest_source(
    source: AIDigestSource,
    *,
    timeout_s: float = 12.0,
    max_age_days: int | None = None,
) -> list[AIUpdateItem]:
    if source.parser == "aihot_daily":
        return fetch_aihot_daily_source(source, days=max_age_days)
    text = _http_get_text(source.url, timeout_s=timeout_s)
    if source.parser == "rss":
        items = parse_rss_feed(text, source_name=source.vendor, vendor=source.vendor)
    elif source.parser == "github_releases":
        items = parse_github_releases_json(text, source_name=source.vendor, vendor=source.vendor)
    elif source.parser == "social_html":
        items = parse_social_search_html(text, source_name=source.vendor, vendor=source.vendor, base_url=source.url)
    elif source.parser == "x_profile":
        items = parse_x_profile_html(text, source_name=source.vendor, vendor=source.vendor)
    elif source.parser == "html":
        items = parse_official_html(text, source_name=source.vendor, vendor=source.vendor, base_url=source.url)
    else:
        items = []
    if source.region in {"domestic", "foreign"}:
        items = [
            AIUpdateItem.model_validate(
                {
                    **item.model_dump(),
                    "tags": [*item.tags, f"region:{source.region}"],
                }
            )
            for item in items
        ]
    if source.kind != "aggregator":
        return items
    return [
        AIUpdateItem.model_validate(
            {
                **item.model_dump(),
                "source_type": "aggregator",
                "verification_status": "aggregator_only",
            }
        )
        for item in items
    ]


def _aihot_daily_dates(days: int = 3) -> list[date]:
    today = datetime.now(timezone.utc).astimezone(BEIJING_TZ).date()
    return [today - timedelta(days=offset) for offset in range(max(1, int(days or 3)))]


def fetch_aihot_daily_source(source: AIDigestSource, *, days: int | None = None) -> list[AIUpdateItem]:
    days_raw = (os.getenv("AI_DIGEST_AIHOT_DAYS") or "").strip()
    try:
        days = int(days_raw) if days_raw else int(days or 3)
    except ValueError:
        days = int(days or 3)
    timeout_s = _env_float("AI_DIGEST_AIHOT_TIMEOUT_S", 8.0, min_value=3.0, max_value=30.0)
    items: list[AIUpdateItem] = []
    for day in _aihot_daily_dates(days=days):
        url = f"{source.url.rstrip('/')}/{day.isoformat()}"
        try:
            html = _http_get_text(url, timeout_s=timeout_s)
        except Exception:
            continue
        items.extend(
            parse_aihot_daily_html(
                html,
                source_name=source.vendor,
                vendor=source.vendor,
                base_url=url,
                published_date=day.isoformat(),
            )
        )
    return items


def _search_backfill_enabled() -> bool:
    return (os.getenv("AI_DIGEST_SEARCH_BACKFILL") or "1").strip().lower() not in {"0", "false", "no", "off"}


def _search_backfill_queries() -> list[str]:
    raw = (os.getenv("AI_DIGEST_SEARCH_BACKFILL_QUERIES") or "").strip()
    if not raw:
        return list(DEFAULT_SEARCH_BACKFILL_QUERIES)
    queries = [part.strip() for part in raw.split("|") if part.strip()]
    return queries or list(DEFAULT_SEARCH_BACKFILL_QUERIES)


def _search_backfill_max_records() -> int:
    raw = (os.getenv("AI_DIGEST_SEARCH_BACKFILL_MAX_RECORDS") or "").strip()
    try:
        value = int(raw) if raw else 12
    except ValueError:
        value = 12
    return max(5, min(80, value))


def _search_backfill_timeout_s() -> float:
    return _env_float("AI_DIGEST_SEARCH_BACKFILL_TIMEOUT_S", 12.0, min_value=3.0, max_value=30.0)


def _normalize_news_seen_at(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return text


def _news_item_to_ai_update(item, *, query: str) -> AIUpdateItem:
    source_name = (getattr(item, "source", "") or getattr(item, "domain", "") or "新闻搜索").strip()
    body = " ".join(
        part.strip()
        for part in (
            getattr(item, "description", "") or "",
            getattr(item, "content", "") or "",
        )
        if part and part.strip()
    )
    body = re.sub(
        r"\bONLY\s+AVAILABLE\s+IN\s+PAID\s+PLANS\b",
        " ",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"\s+", " ", body).strip(" -|")
    return AIUpdateItem(
        title=str(getattr(item, "title", "") or "").strip(),
        summary=body[:220],
        source_name=source_name,
        source_type="search",
        url=str(getattr(item, "url", "") or "").strip(),
        published_at=_normalize_news_seen_at(getattr(item, "seendate", "") or ""),
        vendor=source_name,
        product="",
        raw_excerpt=body,
        confidence_score=float(getattr(item, "attention", None) or 0.58),
        tags=["AI", "搜索补充", query[:40]],
    )


def fetch_ai_digest_search_backfill(
    *,
    max_age_days: int | None,
    now: datetime | date | None,
    queries: list[str] | None = None,
    max_records: int | None = None,
    timeout_s: float | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[AIUpdateItem], dict]:
    from src.news.daily_news import fetch_daily_news_candidates, filter_recent_news_items

    query_list = queries or _search_backfill_queries()
    record_limit = max_records or _search_backfill_max_records()
    request_timeout_s = timeout_s if timeout_s is not None else _search_backfill_timeout_s()
    fetched = []
    errors: list[str] = []
    per_query: list[dict] = []
    for query in query_list:
        try:
            _emit_progress(
                progress,
                "search_backfill_query",
                f"in_progress query={query[:60]} max_records={record_limit} window={max_age_days or 3}d",
            )
            candidates, meta = fetch_daily_news_candidates(
                query,
                max_records=record_limit,
                search_days=max_age_days or 3,
                timeout_s=request_timeout_s,
                expand_query_variants=False,
            )
            recent, date_meta = filter_recent_news_items(
                list(candidates),
                tz_name=str((meta or {}).get("tz") or os.getenv("NEWS_TZ") or "Asia/Shanghai"),
                max_age_days=max_age_days or 3,
                now=now if isinstance(now, datetime) else None,
            )
            converted = [
                _news_item_to_ai_update(item, query=query)
                for item in recent
                if str(getattr(item, "title", "") or "").strip() and str(getattr(item, "url", "") or "").strip()
            ]
            fetched.extend(converted)
            per_query.append(
                {
                    "query": query,
                    "raw_count": len(candidates),
                    "recent_count": len(recent),
                    "converted_count": len(converted),
                    "date_window": date_meta,
                }
            )
            _emit_progress(
                progress,
                "search_backfill_query",
                f"success query={query[:60]} raw={len(candidates)} recent={len(recent)} converted={len(converted)}",
            )
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            _emit_progress(progress, "search_backfill_query", f"failed query={query[:60]} error={exc}")
    return fetched, {"queries": per_query, "errors": errors}


def _needs_search_backfill(
    ranked: list[AIUpdateItem],
    *,
    target_count: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
    require_target_count: bool = False,
) -> bool:
    required_min = (
        max(1, target_count)
        if require_target_count
        else max(1, min(target_count, max(8, min_domestic_model_count + min_foreign_ai_count)))
    )
    counts = ai_digest_quota_counts(ranked)
    return (
        len(ranked) < required_min
        or counts["domestic_model"] < min_domestic_model_count
        or counts["foreign_ai"] < min_foreign_ai_count
    )


def collect_ai_digest_updates(
    *,
    sources: list[AIDigestSource] | None = None,
    fetch_source: FetchSource | None = None,
    target_count: int = 10,
    min_official_count: int = 6,
    allow_social_backfill: bool = True,
    max_age_days: int | None = None,
    now: datetime | date | None = None,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
    include_pool_items: bool = False,
    force_search_backfill: bool = False,
    force_aggregator_backfill: bool = False,
    progress: ProgressCallback | None = None,
    source_health_path: str | Path | None = None,
    source_cooldown_seconds: int | None = None,
    persist_source_health: bool | None = None,
    source_concurrency: int | None = None,
    batch_timeout_s: float | None = None,
) -> tuple[list[AIUpdateItem], dict]:
    resolved = sources if sources is not None else resolve_ai_digest_sources()
    source_timeout_s = _env_float("AI_DIGEST_SOURCE_TIMEOUT_S", 8.0, min_value=3.0, max_value=30.0)
    cooldown_seconds = (
        _env_int("AI_DIGEST_SOURCE_COOLDOWN_S", 300, min_value=0, max_value=3600)
        if source_cooldown_seconds is None
        else max(0, int(source_cooldown_seconds))
    )
    if source_concurrency is None:
        source_concurrency = 1 if fetch_source is not None else _env_int(
            "AI_DIGEST_SOURCE_CONCURRENCY",
            4,
            min_value=1,
            max_value=12,
        )
    else:
        source_concurrency = max(1, min(int(source_concurrency), 12))
    if batch_timeout_s is None:
        batch_timeout_s = _env_float("AI_DIGEST_BATCH_TIMEOUT_S", 45.0, min_value=5.0, max_value=120.0)
    else:
        batch_timeout_s = max(0.1, float(batch_timeout_s))
    health_path = Path(source_health_path) if source_health_path else None
    should_persist_health = bool(health_path) if persist_source_health is None else bool(persist_source_health)
    previous_health = load_source_health_snapshot(health_path) if health_path else None
    persisted_attempts = {
        attempt.source_name: attempt
        for attempt in (previous_health.attempts if previous_health is not None else [])
        if attempt.source_name
    }
    health_now = _health_checked_at(now)
    health_attempts: list[SourceAttempt] = []
    cooldown_skipped: list[str] = []

    def _fetch_with_window(source: AIDigestSource) -> list[AIUpdateItem]:
        if fetch_source is not None:
            return fetch_source(source)
        return fetch_ai_digest_source(source, max_age_days=max_age_days, timeout_s=source_timeout_s)

    fetcher = _fetch_with_window
    official_candidates = [source for source in resolved if source.kind in {"official", "github"}]
    official_stream_sources = [source for source in official_candidates if source.tier == "official_stream"]
    official_page_sources = [
        source for source in official_candidates if source.tier != "official_stream"
    ]
    social_sources = [source for source in resolved if source.kind in {"social", "search"}]
    aggregator_sources = [source for source in resolved if source.kind == "aggregator"]
    fetched: list[AIUpdateItem] = []
    errors: list[str] = []

    def _record_source_result(
        source: AIDigestSource,
        checked_at: str,
        elapsed: float,
        source_items: list[AIUpdateItem],
        error: Exception | None,
    ) -> None:
        if error is not None:
            attempt = SourceAttempt(
                collection="ai_digest",
                source_name=source.name,
                source_url=source.url,
                tier=source.tier,
                status=_source_error_status(error),
                checked_at=checked_at,
                elapsed_seconds=elapsed,
                error=str(error),
                http_status=getattr(error, "code", None),
            )
            health_attempts.append(attempt)
            persisted_attempts[source.name] = attempt
            errors.append(f"{source.name}: {error}")
            _emit_progress(progress, "fetch_source", f"failed name={source.name} error={error}")
            return
        item_count, dated_count, url_count = _source_item_counts(source_items)
        attempt = SourceAttempt(
            collection="ai_digest",
            source_name=source.name,
            source_url=source.url,
            tier=source.tier,
            status=_source_result_status(source_items, max_age_days=max_age_days, now=now),
            checked_at=checked_at,
            elapsed_seconds=elapsed,
            item_count=item_count,
            dated_count=dated_count,
            url_count=url_count,
        )
        health_attempts.append(attempt)
        persisted_attempts[source.name] = attempt
        fetched.extend(source_items)
        _emit_progress(
            progress,
            "fetch_source",
            f"success name={source.name} items={item_count} dated={dated_count} urls={url_count}",
        )

    def _fetch_one(source: AIDigestSource) -> tuple[str, float, list[AIUpdateItem], Exception | None]:
        started = time.perf_counter()
        try:
            source_items = fetcher(source)
            return _health_timestamp(health_now), time.perf_counter() - started, source_items, None
        except Exception as exc:
            return _health_timestamp(health_now), time.perf_counter() - started, [], exc

    def _fetch_stage(stage_sources: list[AIDigestSource]) -> None:
        eligible: list[AIDigestSource] = []
        for source in stage_sources:
            previous_attempt = persisted_attempts.get(source.name)
            if is_source_in_cooldown(
                previous_attempt,
                now=health_now,
                cooldown_seconds=cooldown_seconds,
            ):
                cooldown_skipped.append(source.name)
                health_attempts.append(
                    SourceAttempt(
                        collection="ai_digest",
                        source_name=source.name,
                        source_url=source.url,
                        tier=source.tier,
                        status="cooldown",
                        checked_at=previous_attempt.checked_at if previous_attempt is not None else _health_timestamp(health_now),
                        elapsed_seconds=0.0,
                        item_count=previous_attempt.item_count if previous_attempt is not None else 0,
                        dated_count=previous_attempt.dated_count if previous_attempt is not None else 0,
                        url_count=previous_attempt.url_count if previous_attempt is not None else 0,
                        error=previous_attempt.error if previous_attempt is not None else "",
                        http_status=previous_attempt.http_status if previous_attempt is not None else None,
                    )
                )
                _emit_progress(progress, "fetch_source", f"skipped_cooldown name={source.name} tier={source.tier}")
                continue
            eligible.append(source)
            _emit_progress(progress, "fetch_source", f"in_progress name={source.name} kind={source.kind}")
        if not eligible:
            return
        if source_concurrency <= 1 or len(eligible) == 1:
            for source in eligible:
                checked_at, elapsed, source_items, error = _fetch_one(source)
                _record_source_result(source, checked_at, elapsed, source_items, error)
            return

        executor = ThreadPoolExecutor(max_workers=min(source_concurrency, len(eligible)))
        futures = {executor.submit(_fetch_one, source): source for source in eligible}
        results: dict[AIDigestSource, tuple[str, float, list[AIUpdateItem], Exception | None]] = {}
        try:
            done, pending = wait(futures, timeout=batch_timeout_s)
            for future in done:
                source = futures[future]
                try:
                    results[source] = future.result()
                except Exception as exc:
                    results[source] = (_health_timestamp(health_now), batch_timeout_s, [], exc)
            for future in pending:
                future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        for source in eligible:
            result = results.get(source)
            if result is None:
                timeout_error = TimeoutError(f"source batch deadline exceeded after {batch_timeout_s:.1f}s")
                _record_source_result(
                    source,
                    _health_timestamp(health_now),
                    batch_timeout_s,
                    [],
                    timeout_error,
                )
                continue
            checked_at, elapsed, source_items, error = result
            _record_source_result(source, checked_at, elapsed, source_items, error)

    _fetch_stage(official_stream_sources)
    stream_ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=False,
        max_age_days=max_age_days,
        now=now,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_items_per_source=None,
    )
    official_page_backfill_used = bool(official_page_sources) and _needs_search_backfill(
        stream_ranked,
        target_count=target_count,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        require_target_count=include_pool_items,
    )
    if official_page_backfill_used:
        _fetch_stage(official_page_sources)
    official_ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=False,
        max_age_days=max_age_days,
        now=now,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_items_per_source=None,
    )
    official_count = len(official_ranked)
    social_backfill_used = False
    search_backfill_used = False
    aggregator_backfill_used = False
    search_backfill_meta: dict = {}
    detail_source_resolution = {"considered": 0, "resolved": 0, "official": 0, "social": 0}

    ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=allow_social_backfill,
        max_age_days=max_age_days,
        now=now,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
        max_items_per_source=None,
    )
    if allow_social_backfill and aggregator_sources and (
        force_aggregator_backfill
        or _needs_search_backfill(
            ranked,
            target_count=target_count,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            require_target_count=include_pool_items,
        )
    ):
        aggregator_backfill_used = True
        _fetch_stage(aggregator_sources)
        detail_candidates = rank_ai_updates(
            [item for item in fetched if _is_aihot_detail_url(item.url)],
            target_count=max(24, target_count * 3),
            min_official_count=1,
            allow_social_backfill=True,
            max_age_days=max_age_days,
            now=now,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_items_per_source=None,
        )
        detail_limit = _env_int("AI_DIGEST_AGGREGATOR_DETAIL_LIMIT", 24, min_value=1, max_value=80)
        detail_candidates = detail_candidates[:detail_limit]
        detail_source_resolution["considered"] = len(detail_candidates)
        if detail_candidates:
            detail_timeout_s = _env_float("AI_DIGEST_AGGREGATOR_DETAIL_TIMEOUT_S", 8.0, min_value=3.0, max_value=30.0)
            detail_concurrency = _env_int("AI_DIGEST_AGGREGATOR_DETAIL_CONCURRENCY", 6, min_value=1, max_value=12)
            with ThreadPoolExecutor(max_workers=min(detail_concurrency, len(detail_candidates))) as executor:
                resolved_detail_items = list(
                    executor.map(
                        lambda item: resolve_aihot_detail_source(item, timeout_s=detail_timeout_s),
                        detail_candidates,
                    )
                )
            resolved_by_original_url = {
                original.url: resolved_item
                for original, resolved_item in zip(detail_candidates, resolved_detail_items)
            }
            fetched = [
                resolved_by_original_url.get(item.url, item)
                for item in fetched
            ]
            changed = [
                resolved_item
                for original, resolved_item in zip(detail_candidates, resolved_detail_items)
                if resolved_item.url != original.url
            ]
            detail_source_resolution["resolved"] = len(changed)
            detail_source_resolution["official"] = sum(item.source_type == "official" for item in changed)
            detail_source_resolution["social"] = sum(item.source_type == "social" for item in changed)
        ranked = rank_ai_updates(
            fetched,
            target_count=target_count,
            min_official_count=min_official_count,
            allow_social_backfill=allow_social_backfill,
            max_age_days=max_age_days,
            now=now,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_items_per_source=None,
        )
    if (
        allow_social_backfill
        and _search_backfill_enabled()
        and (
            force_search_backfill
            or _needs_search_backfill(
                ranked,
                target_count=target_count,
                min_domestic_model_count=min_domestic_model_count,
                min_foreign_ai_count=min_foreign_ai_count,
                require_target_count=include_pool_items,
            )
        )
    ):
        search_backfill_used = True
        _emit_progress(progress, "search_backfill", f"in_progress window={max_age_days or 3}d")
        extra, search_backfill_meta = fetch_ai_digest_search_backfill(
            max_age_days=max_age_days,
            now=now,
            progress=progress,
        )
        fetched.extend(extra)
        errors.extend(search_backfill_meta.get("errors") or [])
        _emit_progress(progress, "search_backfill", f"success items={len(extra)} errors={len(search_backfill_meta.get('errors') or [])}")
        ranked = rank_ai_updates(
            fetched,
            target_count=target_count,
            min_official_count=min_official_count,
            allow_social_backfill=allow_social_backfill,
            max_age_days=max_age_days,
            now=now,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_items_per_source=None,
        )
    if (
        allow_social_backfill
        and social_sources
        and _needs_search_backfill(
            ranked,
            target_count=target_count,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            require_target_count=include_pool_items,
        )
    ):
        social_backfill_used = True
        _fetch_stage(social_sources)
        ranked = rank_ai_updates(
            fetched,
            target_count=target_count,
            min_official_count=min_official_count,
            allow_social_backfill=allow_social_backfill,
            max_age_days=max_age_days,
            now=now,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
            max_items_per_source=None,
        )
    fresh_items = filter_recent_ai_updates(
        fetched,
        max_age_days=max_age_days,
        now=now,
        require_url=True,
    )
    deduped_items = dedupe_ai_updates(fresh_items)
    health_snapshot_path = ""
    if health_path is not None and should_persist_health:
        snapshot = SourceHealthSnapshot(
            collection="ai_digest",
            generated_at=_health_timestamp(health_now),
            attempts=sorted(persisted_attempts.values(), key=lambda item: item.source_name),
        )
        health_snapshot_path = str(save_source_health_snapshot(snapshot, health_path))
    meta = {
        "target_count": target_count,
        "min_official_count": min_official_count,
        "min_domestic_model_count": min_domestic_model_count,
        "min_foreign_ai_count": min_foreign_ai_count,
        "max_age_days": max_age_days,
        "fetched_count": len(fetched),
        "fresh_count": len(fresh_items),
        "deduped_count": len(deduped_items),
        "duplicate_removed_count": max(0, len(fresh_items) - len(deduped_items)),
        "ranked_count": len(ranked),
        "official_count": official_count,
        "official_page_backfill_used": official_page_backfill_used,
        "social_backfill_used": social_backfill_used,
        "search_backfill_used": search_backfill_used,
        "aggregator_backfill_used": aggregator_backfill_used,
        "aggregator_backfill_forced": bool(force_aggregator_backfill),
        "detail_source_resolution": detail_source_resolution,
        "search_backfill": search_backfill_meta,
        "quota_counts": ai_digest_quota_counts(ranked),
        "sources": [source.name for source in resolved],
        "errors": errors,
        "source_health": {
            "enabled": health_path is not None,
            "snapshot_path": health_snapshot_path or (str(health_path) if health_path is not None else ""),
            "cooldown_seconds": cooldown_seconds,
            "cooldown_skipped": cooldown_skipped,
            "attempts": [attempt.to_dict() for attempt in health_attempts],
        },
    }
    if include_pool_items:
        meta["_fetched_items"] = list(fetched)
        meta["_fresh_items"] = list(fresh_items)
        meta["_deduped_items"] = list(deduped_items)
    return ranked, meta
