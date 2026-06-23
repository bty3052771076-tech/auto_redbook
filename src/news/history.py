from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
import urllib.parse

TRACKING_QUERY_NAMES = {
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "spm",
}


def news_history_dedupe_enabled() -> bool:
    raw = (os.getenv("NEWS_HISTORY_DEDUPE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def normalize_news_url_key(url: str | None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if not parsed.netloc:
        return raw.rstrip("/")

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = urllib.parse.unquote(parsed.path or "")
    if path and path != "/":
        path = path.rstrip("/")
    query_pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        key_lc = key.lower()
        if key_lc.startswith("utm_") or key_lc in TRACKING_QUERY_NAMES:
            continue
        query_pairs.append((key, value))
    query = urllib.parse.urlencode(sorted(query_pairs))
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _news_urls_from_post_data(data: dict[str, Any]) -> Iterable[str]:
    platform = data.get("platform")
    if not isinstance(platform, dict):
        return []
    news = platform.get("news")
    if not isinstance(news, dict):
        return []

    urls: list[str] = []
    source_url = news.get("source_url")
    if isinstance(source_url, str):
        urls.append(source_url)
    picked = news.get("picked")
    if isinstance(picked, dict):
        picked_url = picked.get("url")
        if isinstance(picked_url, str):
            urls.append(picked_url)
    return urls


def collect_used_news_url_keys(*, data_root: Path | str = Path("data")) -> set[str]:
    posts_root = Path(data_root) / "posts"
    if not posts_root.exists():
        return set()

    keys: set[str] = set()
    for post_file in posts_root.glob("*/post.json"):
        try:
            data = json.loads(post_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for url in _news_urls_from_post_data(data):
            key = normalize_news_url_key(url)
            if key:
                keys.add(key)
    return keys


def filter_used_news_items(items: list[Any], used_url_keys: set[str]) -> tuple[list[Any], list[dict[str, str]]]:
    if not used_url_keys:
        return items, []

    kept: list[Any] = []
    skipped: list[dict[str, str]] = []
    for item in items:
        url = str(getattr(item, "url", "") or "").strip()
        key = normalize_news_url_key(url)
        if key and key in used_url_keys:
            skipped.append(
                {
                    "title": str(getattr(item, "title", "") or ""),
                    "url": url,
                    "key": key,
                }
            )
            continue
        kept.append(item)
    return kept, skipped

