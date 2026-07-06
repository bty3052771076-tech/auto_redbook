from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import urllib.request
from typing import Callable

import certifi

from .fetchers import (
    parse_aihot_daily_html,
    parse_github_releases_json,
    parse_official_html,
    parse_rss_feed,
    parse_social_search_html,
)
from .models import AIUpdateItem
from .rank import ai_digest_quota_counts, dedupe_ai_updates, filter_recent_ai_updates, rank_ai_updates
from .sources import AIDigestSource, resolve_ai_digest_sources


FetchSource = Callable[[AIDigestSource], list[AIUpdateItem]]
ProgressCallback = Callable[[str, str], None]
DEFAULT_SEARCH_BACKFILL_QUERIES = (
    "国内 AI 模型 发布 GLM Qwen 豆包 DeepSeek Kimi MiniMax",
    "AI model release OpenAI Anthropic Claude Gemini GPT Llama Mistral",
    "AI API developer tools model release open source",
)
BEIJING_TZ = timezone(timedelta(hours=8))


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else float(default)
    except ValueError:
        value = float(default)
    return max(min_value, min(max_value, value))


def _emit_progress(progress: ProgressCallback | None, stage: str, detail: str) -> None:
    if progress is not None:
        progress(stage, detail)


def _http_get_text(url: str, *, timeout_s: float = 12.0) -> str:
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
        return parse_rss_feed(text, source_name=source.vendor, vendor=source.vendor)
    if source.parser == "github_releases":
        return parse_github_releases_json(text, source_name=source.vendor, vendor=source.vendor)
    if source.parser == "social_html":
        return parse_social_search_html(text, source_name=source.vendor, vendor=source.vendor, base_url=source.url)
    if source.parser == "html":
        return parse_official_html(text, source_name=source.vendor, vendor=source.vendor, base_url=source.url)
    return []


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
) -> bool:
    required_min = max(1, min(target_count, max(8, min_domestic_model_count + min_foreign_ai_count)))
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
    progress: ProgressCallback | None = None,
) -> tuple[list[AIUpdateItem], dict]:
    resolved = sources if sources is not None else resolve_ai_digest_sources()
    source_timeout_s = _env_float("AI_DIGEST_SOURCE_TIMEOUT_S", 8.0, min_value=3.0, max_value=30.0)

    def _fetch_with_window(source: AIDigestSource) -> list[AIUpdateItem]:
        if fetch_source is not None:
            return fetch_source(source)
        return fetch_ai_digest_source(source, max_age_days=max_age_days, timeout_s=source_timeout_s)

    fetcher = _fetch_with_window
    official_sources = [source for source in resolved if source.kind in {"official", "github"}]
    social_sources = [source for source in resolved if source.kind in {"social", "search"}]
    aggregator_sources = [source for source in resolved if source.kind == "aggregator"]
    fetched: list[AIUpdateItem] = []
    errors: list[str] = []

    for source in official_sources:
        try:
            _emit_progress(progress, "fetch_source", f"in_progress name={source.name} kind={source.kind}")
            source_items = fetcher(source)
            fetched.extend(source_items)
            _emit_progress(progress, "fetch_source", f"success name={source.name} items={len(source_items)}")
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
            _emit_progress(progress, "fetch_source", f"failed name={source.name} error={exc}")

    official_ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=False,
        max_age_days=max_age_days,
        now=now,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    official_count = len(official_ranked)
    social_backfill_used = False
    search_backfill_used = False
    aggregator_backfill_used = False
    search_backfill_meta: dict = {}

    if allow_social_backfill and official_count < min_official_count:
        social_backfill_used = True
        for source in social_sources:
            try:
                _emit_progress(progress, "fetch_source", f"in_progress name={source.name} kind={source.kind}")
                source_items = fetcher(source)
                fetched.extend(source_items)
                _emit_progress(progress, "fetch_source", f"success name={source.name} items={len(source_items)}")
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                _emit_progress(progress, "fetch_source", f"failed name={source.name} error={exc}")

    ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=allow_social_backfill,
        max_age_days=max_age_days,
        now=now,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
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
        )
    if (
        allow_social_backfill
        and aggregator_sources
        and _needs_search_backfill(
            ranked,
            target_count=target_count,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
    ):
        aggregator_backfill_used = True
        for source in aggregator_sources:
            try:
                _emit_progress(progress, "fetch_source", f"in_progress name={source.name} kind={source.kind}")
                source_items = fetcher(source)
                fetched.extend(source_items)
                _emit_progress(progress, "fetch_source", f"success name={source.name} items={len(source_items)}")
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                _emit_progress(progress, "fetch_source", f"failed name={source.name} error={exc}")
        ranked = rank_ai_updates(
            fetched,
            target_count=target_count,
            min_official_count=min_official_count,
            allow_social_backfill=allow_social_backfill,
            max_age_days=max_age_days,
            now=now,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
    fresh_items = filter_recent_ai_updates(
        fetched,
        max_age_days=max_age_days,
        now=now,
        require_url=True,
    )
    deduped_items = dedupe_ai_updates(fresh_items)
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
        "social_backfill_used": social_backfill_used,
        "search_backfill_used": search_backfill_used,
        "aggregator_backfill_used": aggregator_backfill_used,
        "search_backfill": search_backfill_meta,
        "quota_counts": ai_digest_quota_counts(ranked),
        "sources": [source.name for source in resolved],
        "errors": errors,
    }
    if include_pool_items:
        meta["_fetched_items"] = list(fetched)
        meta["_fresh_items"] = list(fresh_items)
        meta["_deduped_items"] = list(deduped_items)
    return ranked, meta
