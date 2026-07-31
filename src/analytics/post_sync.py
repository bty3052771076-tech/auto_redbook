from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

from src.storage.files import DATA_ROOT, list_posts, save_post
from src.storage.models import Post, PostStatus, now_iso


def normalize_metric_title(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def normalize_metric_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except Exception:
        return text.rstrip("/")
    clean = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    return clean or text.rstrip("/")


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        data = value.model_dump()
        return data if isinstance(data, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _raw_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metric_url(metric: dict[str, Any]) -> str:
    return str(metric.get("url") or metric.get("note_url") or metric.get("xhs_url") or "").strip()


def _post_url_candidates(post: Post) -> set[str]:
    out: set[str] = set()
    platform = post.platform if isinstance(post.platform, dict) else {}
    publish = platform.get("publish") if isinstance(platform.get("publish"), dict) else {}
    for key in (
        "url",
        "note_url",
        "xhs_url",
        "published_url",
        "share_url",
        "web_url",
    ):
        value = str(publish.get(key) or "").strip()
        if value:
            out.add(normalize_metric_url(value))
    return {value for value in out if value}


def _post_title_candidates(post: Post) -> list[tuple[str, str]]:
    candidates = [("title", post.title)]
    platform = post.platform if isinstance(post.platform, dict) else {}
    publish = platform.get("publish") if isinstance(platform.get("publish"), dict) else {}
    for reason, key in (
        ("actual_title", "actual_title"),
        ("draft_list_title", "draft_list_title"),
    ):
        candidates.append((reason, str(publish.get(key) or "")))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for reason, title in candidates:
        norm = normalize_metric_title(title)
        if not norm or norm in seen:
            continue
        out.append((reason, norm))
        seen.add(norm)
    return out


def _published_post_match_indexes(
    posts: Iterable[Post],
) -> tuple[dict[str, Post], dict[str, list[tuple[Post, str]]]]:
    """Build stable URL and title indexes without changing match precedence."""
    url_index: dict[str, Post] = {}
    title_index: dict[str, list[tuple[Post, str]]] = {}
    for post in posts:
        for url in _post_url_candidates(post):
            url_index.setdefault(url, post)
        for reason, title in _post_title_candidates(post):
            title_index.setdefault(title, []).append((post, reason))
    return url_index, title_index


def _find_post_in_published_indexes(
    metric: Any,
    *,
    url_index: dict[str, Post],
    title_index: dict[str, list[tuple[Post, str]]],
) -> tuple[Optional[Post], str]:
    data = _as_dict(metric)
    metric_url = normalize_metric_url(_metric_url(data))
    if metric_url:
        post = url_index.get(metric_url)
        if post is not None:
            return post, "url"

    metric_title = normalize_metric_title(str(data.get("title") or ""))
    if metric_title:
        for post, reason in title_index.get(metric_title, []):
            if post.uploaded or post.status == PostStatus.published:
                return post, reason
    return None, ""


def find_post_for_published_metric(
    metric: Any,
    *,
    base=DATA_ROOT,
) -> tuple[Optional[Post], str]:
    posts = list(list_posts(base=base))
    url_index, title_index = _published_post_match_indexes(posts)
    return _find_post_in_published_indexes(
        metric,
        url_index=url_index,
        title_index=title_index,
    )


def _metric_snapshot(metric: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_dict(metric.get("raw"))
    keys = ("likes", "comments", "favorites", "published_at", "captured_at")
    snap = {key: metric.get(key) for key in keys if metric.get(key) not in ("", None)}
    for key in ("views", "shares"):
        value = raw.get(key)
        if value not in ("", None):
            snap[key] = value
    if raw.get("stats") not in ("", None):
        snap["stats"] = raw.get("stats")
    return snap


def sync_published_metrics_to_posts(
    metrics: Iterable[Any],
    *,
    base=DATA_ROOT,
) -> dict[str, Any]:
    matched = 0
    unmatched: list[str] = []
    updated_post_ids: list[str] = []
    now = now_iso()
    url_index, title_index = _published_post_match_indexes(list_posts(base=base))

    for metric in metrics:
        data = _as_dict(metric)
        post, reason = _find_post_in_published_indexes(
            data,
            url_index=url_index,
            title_index=title_index,
        )
        if post is None:
            title = str(data.get("title") or "").strip()
            url = _metric_url(data)
            unmatched.append(url or title)
            continue

        publish = post.platform.setdefault("publish", {})
        if not isinstance(publish, dict):
            publish = {}
            post.platform["publish"] = publish
        actual_title = str(data.get("title") or "").strip()
        actual_body = str(data.get("body") or data.get("content") or "").strip()
        metric_url = _metric_url(data)
        published_at = str(data.get("published_at") or "").strip()

        post.status = PostStatus.published
        post.uploaded = True
        post.updated_at = now
        publish.update(
            {
                "result": "published",
                "source": "published_metrics_sync",
                "synced_at": now,
                "match_reason": reason,
                "metrics": _metric_snapshot(data),
            }
        )
        if actual_title:
            publish["actual_title"] = actual_title
        if actual_body:
            publish["actual_body"] = actual_body
        if metric_url:
            publish["url"] = metric_url
        if published_at:
            publish["published_at"] = published_at

        save_post(post, base=base)
        matched += 1
        updated_post_ids.append(post.id)

    return {
        "matched": matched,
        "unmatched": [item for item in unmatched if item],
        "updated_post_ids": updated_post_ids,
    }
