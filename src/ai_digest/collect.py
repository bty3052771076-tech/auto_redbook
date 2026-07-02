from __future__ import annotations

from datetime import date, datetime
import urllib.request
from typing import Callable

import certifi

from .fetchers import parse_github_releases_json, parse_official_html, parse_rss_feed, parse_social_search_html
from .models import AIUpdateItem
from .rank import dedupe_ai_updates, filter_recent_ai_updates, rank_ai_updates
from .sources import AIDigestSource, resolve_ai_digest_sources


FetchSource = Callable[[AIDigestSource], list[AIUpdateItem]]


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


def fetch_ai_digest_source(source: AIDigestSource, *, timeout_s: float = 12.0) -> list[AIUpdateItem]:
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


def collect_ai_digest_updates(
    *,
    sources: list[AIDigestSource] | None = None,
    fetch_source: FetchSource | None = None,
    target_count: int = 10,
    min_official_count: int = 6,
    allow_social_backfill: bool = True,
    max_age_days: int | None = None,
    now: datetime | date | None = None,
) -> tuple[list[AIUpdateItem], dict]:
    resolved = sources if sources is not None else resolve_ai_digest_sources()
    fetcher = fetch_source or fetch_ai_digest_source
    official_sources = [source for source in resolved if source.kind in {"official", "github"}]
    social_sources = [source for source in resolved if source.kind in {"social", "search"}]
    fetched: list[AIUpdateItem] = []
    errors: list[str] = []

    for source in official_sources:
        try:
            fetched.extend(fetcher(source))
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")

    official_ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=False,
        max_age_days=max_age_days,
        now=now,
    )
    official_count = len(official_ranked)
    social_backfill_used = False

    if allow_social_backfill and official_count < min_official_count:
        social_backfill_used = True
        for source in social_sources:
            try:
                fetched.extend(fetcher(source))
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")

    ranked = rank_ai_updates(
        fetched,
        target_count=target_count,
        min_official_count=min_official_count,
        allow_social_backfill=allow_social_backfill,
        max_age_days=max_age_days,
        now=now,
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
        "max_age_days": max_age_days,
        "fetched_count": len(fetched),
        "fresh_count": len(fresh_items),
        "deduped_count": len(deduped_items),
        "duplicate_removed_count": max(0, len(fresh_items) - len(deduped_items)),
        "ranked_count": len(ranked),
        "official_count": official_count,
        "social_backfill_used": social_backfill_used,
        "sources": [source.name for source in resolved],
        "errors": errors,
    }
    return ranked, meta
