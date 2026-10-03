"""Bounded, manual Danbooru acquisition; never promotes downloaded candidates."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
import re
from math import ceil
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from src.images.opencodex_images import _file_lock, _write_json
from .reference_library import image_digest, MAX_IMAGE_BYTES, WoolReferenceLibrary

STYLES = {"office": "office_lady", "dress": "dress", "casual": "sweater", "summer": "outdoors"}
EXCLUDED_TAGS = {
    "loli", "shota", "child", "young", "underage", "teenage", "baby", "toddler", "school_uniform",
    "schoolgirl", "serafuku", "chibi", "nude", "nipples", "nipple", "pussy", "penis", "sex",
    "sex_toy", "dildo", "masturbation", "spread_legs", "guro", "gore", "scat", "feces", "bondage",
    "see-through", "micro_bikini", "bottomless", "topless", "1boy", "2girls", "3girls",
}
KNOWN_AGE_AMBIGUOUS = {"kagami_tsurugi"}


def eligible_post(post: dict) -> bool:
    tags = set(str(post.get("tag_string_general") or "").split())
    characters = set(str(post.get("tag_string_character") or "").split())
    return (post.get("rating") in {"g", "s"} and "mature_female" in tags
            and not tags & EXCLUDED_TAGS and not characters & KNOWN_AGE_AMBIGUOUS)


def fetch_candidates(root: Path, *, count: int = 10, style: str = "mixed",
                     client: httpx.Client | None = None, pause=None) -> dict:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 30 or style not in {*STYLES, "mixed"}:
        raise ValueError("获取数量必须为 1–30，风格必须为预设类型")
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(25), follow_redirects=False,
                          headers={"User-Agent": "RedbookReferenceLibrary/1.0 (anonymous local reference review)",
                                   "Accept": "application/json"}) as session:
            return fetch_candidates(root, count=count, style=style, client=session, pause=pause)
    pause = pause or (lambda: time.sleep(1.1))
    root = root.resolve()
    with _file_lock(root / "danbooru-fetch.lock", wait=False):
        batch = root / "候选原图" / (datetime.now().strftime("Danbooru-%Y%m%d-%H%M%S-") + uuid4().hex[:6])
        batch = WoolReferenceLibrary(root)._safe(batch, "候选原图")
        batch.mkdir(parents=True, exist_ok=False)
        result = {"batch": batch.name, "downloaded": 0, "errors": [], "images": [], "queries": []}
        existing = {row["sha256"] for row in WoolReferenceLibrary(root).snapshot()["rows"]}
        artist_counts: dict[str, int] = {}
        styles = list(STYLES) if style == "mixed" else [style]
        seen = set()
        per_style = ceil(count / len(styles))
        attempts = 0
        for selected_style in styles:
            style_count = 0
            query = f"rating:g,s mature_female {STYLES[selected_style]}"
            result["queries"].append(query)
            try:
                response = client.get("https://danbooru.donmai.us/posts.json", params={"tags": query, "limit": 60})
                response.raise_for_status()
                posts = response.json()
                if not isinstance(posts, list) or not all(isinstance(post, dict) for post in posts):
                    raise ValueError("API 未返回图片列表")
            except (httpx.HTTPError, ValueError) as exc:
                code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                result["errors"].append(f"检索 {selected_style} 失败：{code}；请检查网络或稍后再试")
                if code in {403, 429}:
                    break
                pause()
                continue
            posts.sort(key=lambda item: not bool(set(str(item.get("tag_string_general", "")).split()) & {"curvy", "large_breasts", "medium_breasts"}))
            for post in posts:
                post_id = post.get("id")
                if post_id in seen or not eligible_post(post):
                    continue
                seen.add(post_id)
                artist = str(post.get("tag_string_artist") or "unknown")
                if artist_counts.get(artist, 0) >= 2:
                    continue
                if attempts >= max(8, count * 3):
                    result["errors"].append("下载失败或重复较多，已停止本次采集；可调整风格后手动再试")
                    _write_json(batch / "manifest.json", result)
                    return result
                attempts += 1
                pause()
                try:
                    url = urlsplit(str(post.get("file_url") or ""))
                    if (url.scheme != "https" or url.hostname not in {"cdn.donmai.us", "danbooru.donmai.us"}
                            or url.port not in {None, 443} or url.username or url.password):
                        raise ValueError("下载地址不是允许的官方 HTTPS CDN")
                    suffix = Path(url.path).suffix.lower()
                    expected = str(post.get("md5") or "")
                    if suffix not in {".jpg", ".jpeg", ".png", ".webp"} or not re.fullmatch(r"[a-f0-9]{32}", expected):
                        raise ValueError("图片格式或散列无效")
                    with client.stream("GET", url.geturl()) as download:
                        download.raise_for_status()
                        content = bytearray()
                        for chunk in download.iter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_IMAGE_BYTES:
                                raise ValueError("图片超过 10 MiB")
                    if md5(content).hexdigest() != expected:
                        raise ValueError("MD5 校验失败")
                    path = batch / f"danbooru_{int(post_id)}{suffix}"
                    path.write_bytes(content)
                    try:
                        digest, width, height = image_digest(path)
                    except Exception:
                        path.unlink(missing_ok=True)
                        raise
                    if digest in existing:
                        path.unlink()
                        continue
                    existing.add(digest)
                    row = {"filename": path.name, "post_id": int(post_id), "post_url": f"https://danbooru.donmai.us/posts/{int(post_id)}",
                           "source": str(post.get("source") or ""), "artist": artist,
                           "characters": str(post.get("tag_string_character") or ""),
                           "rating": post["rating"], "tags": post.get("tag_string_general", ""),
                           "reference_style": selected_style, "md5": expected, "sha256": digest,
                           "width": width, "height": height, "license_status": "unverified",
                           "approval_status": "pending_manual_review", "adult_evidence": "mature_female tag; human review required",
                           "retrieved_at": datetime.now(timezone.utc).isoformat()}
                    result["images"].append(row)
                    result["downloaded"] += 1
                    style_count += 1
                    artist_counts[artist] = artist_counts.get(artist, 0) + 1
                    _write_json(batch / "manifest.json", result)
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                    result["errors"].append(f"图片 {post_id} 未获取：{code}")
                    if code in {403, 429}:
                        _write_json(batch / "manifest.json", result)
                        return result
                if result["downloaded"] >= count or style_count >= per_style:
                    break
            if result["downloaded"] >= count:
                break
            pause()
        _write_json(batch / "manifest.json", result)
        return result
