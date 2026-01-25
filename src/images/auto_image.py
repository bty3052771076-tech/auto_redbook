from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PEXELS_BASE_URL = "https://api.pexels.com"
DEFAULT_PROVIDER = "pexels"
DEFAULT_QUERY = "lifestyle"
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_MAX_CANDIDATES = 30
DEFAULT_ORIENTATION = "portrait"
DEFAULT_IMAGE_COUNT = 3
DEFAULT_MIN_SCORE = 0.12
MAX_IMAGE_COUNT = 18

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_HASHTAG_RE = re.compile(r"#\S+")
_EN_TOKEN_RE = re.compile(r"[a-zA-Z]+")
_EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "court",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "left",
    "news",
    "now",
    "of",
    "on",
    "or",
    "out",
    "over",
    "s",
    "says",
    "saying",
    "that",
    "the",
    "this",
    "to",
    "under",
    "was",
    "were",
    "with",
    "what",
    "why",
}
_ENTITY_MAP = {
    "中国": "China",
    "美国": "USA",
    "俄罗斯": "Russia",
    "乌克兰": "Ukraine",
    "以色列": "Israel",
    "加沙": "Gaza",
    "伊朗": "Iran",
    "伊拉克": "Iraq",
    "叙利亚": "Syria",
    "土耳其": "Turkey",
    "欧盟": "EU",
    "联合国": "United Nations",
    "越南": "Vietnam",
    "巴基斯坦": "Pakistan",
    "利比亚": "Libya",
    "委内瑞拉": "Venezuela",
    "菲律宾": "Philippines",
    "日本": "Japan",
    "韩国": "South Korea",
    "朝鲜": "North Korea",
    "印度": "India",
}


@dataclass(frozen=True)
class ImageItem:
    provider: str
    id: str
    page_url: str
    download_url: str
    photographer: Optional[str] = None
    photographer_url: Optional[str] = None
    license: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    alt: Optional[str] = None


def is_auto_image_enabled() -> bool:
    v = (os.getenv("AUTO_IMAGE") or "").strip().lower()
    if not v:
        return True
    return v not in ("0", "false", "no", "off")


def _parse_kv_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        data[k] = v
    return data


def _load_pexels_config(
    *,
    key_file: Path | str = Path("docs/pexels_api-key.md"),
) -> tuple[str, str]:
    env_key = os.getenv("PEXELS_API_KEY")
    env_base = os.getenv("PEXELS_BASE_URL")
    file_cfg = _parse_kv_file(Path(key_file))

    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    base_url = (env_base or file_cfg.get("base_url") or PEXELS_BASE_URL).strip()

    if not api_key:
        raise RuntimeError("Pexels api_key missing: set PEXELS_API_KEY env or docs/pexels_api-key.md")
    if not base_url:
        base_url = PEXELS_BASE_URL
    return api_key, base_url.rstrip("/")


def _tokens(text: str) -> set[str]:
    text = (text or "").strip().lower()
    if not text:
        return set()
    out: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        part = m.group(0)
        if not part:
            continue
        out.add(part)
        if _CJK_RE.match(part):
            # Add bigrams for better Chinese fuzzy matching.
            if len(part) <= 4:
                out.update(part)
            for i in range(len(part) - 1):
                out.add(part[i : i + 2])
    return out


def _strip_hashtags(text: str) -> str:
    if not text:
        return ""
    return _HASHTAG_RE.sub("", text).strip()


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _english_tokens(text: str) -> list[str]:
    return [t.lower() for t in _EN_TOKEN_RE.findall(text or "")]


def _compress_english_query(text: str, *, max_words: int = 6) -> str:
    tokens = _english_tokens(text)
    if not tokens:
        return ""
    filtered = [t for t in tokens if t not in _EN_STOPWORDS and len(t) > 2]
    if not filtered:
        filtered = [t for t in tokens if len(t) > 2] or tokens
    seen: set[str] = set()
    out: list[str] = []
    for t in filtered:
        if t in seen:
            continue
        out.append(t)
        seen.add(t)
        if len(out) >= max_words:
            break
    return " ".join(out).strip()


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if not t or t in seen:
            continue
        out.append(t)
        seen.add(t)
    return out


def _resolve_image_count(count: Optional[int]) -> int:
    env = (os.getenv("AUTO_IMAGE_COUNT") or "").strip()
    if count is None and env:
        try:
            count = int(env)
        except ValueError:
            count = None
    if count is None:
        count = DEFAULT_IMAGE_COUNT
    return max(1, min(int(count), MAX_IMAGE_COUNT))


def _item_tokens(item: ImageItem) -> set[str]:
    tokens = _tokens(item.alt or "")
    if tokens:
        return tokens
    return _tokens(item.page_url or "")


def _is_similar_tokens(a: set[str], b: set[str], *, threshold: float = 0.6) -> bool:
    if not a or not b:
        return False
    min_len = min(len(a), len(b))
    if min_len < 3:
        return False
    overlap = len(a & b) / min_len
    return overlap >= threshold


def build_image_query(
    title: str,
    body: str,
    topics: list[str],
    prompt_hint: str,
    *,
    max_len: int = 80,
) -> str:
    """
    Build a short query for image search.

    Priority:
      1) Title
      2) Topics
      3) Short prompt/body snippet as fallback
    """
    parts: list[str] = []

    title_norm = _compact_spaces(title)
    if "｜" in title_norm:
        # For "每日新闻｜xxx" style titles, prefer the actual topic part.
        title_norm = _compact_spaces(title_norm.split("｜", 1)[1])
    if "|" in title_norm:
        title_norm = _compact_spaces(title_norm.split("|", 1)[1]) or title_norm
    if re.search(r"[a-zA-Z]", title_norm):
        word_count = len(_english_tokens(title_norm))
        if len(title_norm) > 60 or word_count > 8:
            title_norm = _compress_english_query(title_norm, max_words=6) or title_norm
    if title_norm:
        parts.append(title_norm)

    topics_norm: list[str] = []
    for t in topics or []:
        t = _compact_spaces(t).lstrip("#")
        if t in ("每日新闻", "每日假新闻"):
            continue
        if "新闻" in t or "news" in t.lower():
            continue
        if not t or t in topics_norm:
            continue
        topics_norm.append(t)
        if len(topics_norm) >= 3:
            break
    if topics_norm:
        parts.append(" ".join(topics_norm))

    hint = _compact_spaces(prompt_hint)
    if hint and len(hint) <= 32:
        parts.append(hint)
    elif not parts:
        snippet = _compact_spaces(_strip_hashtags(body))
        if snippet:
            parts.append(snippet[:32])

    query = _compact_spaces(" ".join(p for p in parts if p))
    if not query:
        query = (os.getenv("IMAGE_QUERY_DEFAULT") or DEFAULT_QUERY).strip() or DEFAULT_QUERY
    return query if len(query) <= max_len else query[:max_len]


def _pexels_query_hint(query: str) -> str:
    """
    Pexels search tends to work better with English keywords. Do a tiny mapping for common
    Chinese hints to improve relevance without external translation.
    """
    q = (query or "").strip()
    if not q:
        return ""
    def _add_token(bucket: list[str], value: str) -> None:
        if not value:
            return
        if value not in bucket:
            bucket.append(value)

    tokens: list[str] = []
    english_hint = _compress_english_query(q, max_words=6)
    if english_hint:
        tokens.extend(english_hint.split())
    for cn, en in _ENTITY_MAP.items():
        if cn in q:
            _add_token(tokens, en)
    if "美国" in q or "美國" in q:
        _add_token(tokens, "USA")
    if "时政" in q or "時政" in q or "政治" in q:
        _add_token(tokens, "politics")
    if "大选" in q or "大選" in q or "选举" in q or "選舉" in q:
        _add_token(tokens, "election")
    if "国会" in q or "國會" in q:
        _add_token(tokens, "congress")
    if "外交" in q:
        _add_token(tokens, "diplomacy")
    if "经济" in q or "經濟" in q or "财经" in q or "財經" in q:
        _add_token(tokens, "economy")
    if "科技" in q or "AI" in q.upper() or "人工智能" in q:
        _add_token(tokens, "technology")
    if "国际" in q or "國際" in q:
        _add_token(tokens, "international")
    has_news = "新闻" in q
    if "军事" in q or "軍事" in q:
        _add_token(tokens, "military")
    if "能源" in q or "石油" in q or "油价" in q or "油價" in q:
        _add_token(tokens, "oil")
    if "工业" in q or "工業" in q:
        _add_token(tokens, "industry")
    if "制造" in q or "製造" in q:
        _add_token(tokens, "manufacturing")
    if "金融" in q:
        _add_token(tokens, "finance")

    if not tokens and has_news:
        tokens.append("news")

    if not tokens:
        return q

    tokens = _dedupe_tokens(tokens)
    return " ".join(tokens[:8]).strip()


def _relevance_score(
    item: ImageItem, query: str, *, query_tokens: Optional[set[str]] = None
) -> float:
    q_tokens = query_tokens or _tokens(query)
    if not q_tokens:
        return 0.0
    item_text = f"{item.alt or ''} {item.page_url or ''}".lower()
    i_tokens = _tokens(item_text)
    hit = len(q_tokens & i_tokens)
    denom = max(1, len(q_tokens))
    score = hit / denom
    if not (item.alt or "").strip():
        score *= 0.8

    # Prefer higher-resolution assets (soft weight).
    w = int(item.width or 0)
    h = int(item.height or 0)
    area = w * h
    if area > 0:
        score += min(1.0, area / (2000 * 2000)) * 0.15
    return score


def pick_best_image(items: list[ImageItem], query: str) -> ImageItem:
    if not items:
        raise ValueError("no image candidates")
    best = items[0]
    best_key = (-1.0, 0)
    for item in items:
        score = _relevance_score(item, query)
        area = int(item.width or 0) * int(item.height or 0)
        key = (score, area)
        if key > best_key:
            best = item
            best_key = key
    return best


def pick_top_images(
    items: list[ImageItem],
    query: str,
    count: int,
    *,
    exclude_ids: Optional[set[str]] = None,
    min_score: Optional[float] = None,
) -> list[ImageItem]:
    if not items:
        raise ValueError("no image candidates")
    count = max(1, int(count))
    exclude_ids = set(exclude_ids or [])
    q_tokens = _tokens(query)

    ranked: list[tuple[float, int, ImageItem]] = []
    for item in items:
        score = _relevance_score(item, query, query_tokens=q_tokens)
        area = int(item.width or 0) * int(item.height or 0)
        ranked.append((score, area, item))
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)

    if min_score is None:
        try:
            min_score = float(os.getenv("IMAGE_MIN_SCORE") or DEFAULT_MIN_SCORE)
        except ValueError:
            min_score = DEFAULT_MIN_SCORE
    if len(ranked) >= count:
        filtered = [r for r in ranked if r[0] >= min_score]
        if len(filtered) >= count:
            ranked = filtered

    selected: list[ImageItem] = []
    selected_tokens: list[set[str]] = []
    for _score, _area, item in ranked:
        if item.id in exclude_ids:
            continue
        item_tokens = _item_tokens(item)
        if any(_is_similar_tokens(item_tokens, t) for t in selected_tokens):
            continue
        selected.append(item)
        selected_tokens.append(item_tokens)
        if len(selected) >= count:
            break

    if len(selected) < count:
        for _score, _area, item in ranked:
            if item.id in exclude_ids or item in selected:
                continue
            selected.append(item)
            if len(selected) >= count:
                break

    return selected


def _guess_ext(url: str) -> str:
    try:
        path = urllib.parse.urlparse(url).path
        ext = Path(path).suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return ext if ext != ".jpeg" else ".jpg"
    except Exception:
        pass
    return ".jpg"


def _pexels_search_photos(
    *,
    api_key: str,
    base_url: str,
    query: str,
    per_page: int,
    orientation: str,
    timeout_s: float,
) -> list[ImageItem]:
    per_page = max(1, min(int(per_page), 80))
    params: dict[str, str] = {
        "query": query,
        "per_page": str(per_page),
        "page": "1",
    }
    if orientation:
        params["orientation"] = orientation

    url = f"{base_url.rstrip('/')}/v1/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "User-Agent": "Mozilla/5.0 (redbook_workflow)",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except Exception as exc:
        raise RuntimeError(f"Pexels request failed: {exc}") from exc

    data = json.loads(raw.decode("utf-8", errors="replace"))
    photos = data.get("photos", [])
    items: list[ImageItem] = []
    for p in photos:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        page_url = (p.get("url") or "").strip()
        photographer = (p.get("photographer") or "").strip() or None
        photographer_url = (p.get("photographer_url") or "").strip() or None
        alt = (p.get("alt") or "").strip() or None
        width = p.get("width")
        height = p.get("height")
        try:
            width_i = int(width) if width is not None else None
        except Exception:
            width_i = None
        try:
            height_i = int(height) if height is not None else None
        except Exception:
            height_i = None

        src = p.get("src")
        if not isinstance(src, dict):
            continue
        download_url = (
            (src.get("portrait") or "")
            or (src.get("large2x") or "")
            or (src.get("large") or "")
            or (src.get("original") or "")
        ).strip()

        if not pid or not page_url or not download_url:
            continue

        items.append(
            ImageItem(
                provider="pexels",
                id=str(pid),
                page_url=page_url,
                download_url=download_url,
                photographer=photographer,
                photographer_url=photographer_url,
                license="Pexels License",
                width=width_i,
                height=height_i,
                alt=alt,
            )
        )
    return items


def _download_image(
    *,
    url: str,
    dest_path: Path,
    timeout_s: float,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read()
    except Exception as exc:
        raise RuntimeError(f"image download failed: {exc}") from exc
    dest_path.write_bytes(data)


def fetch_and_download_related_images(
    *,
    title: str,
    body: str,
    topics: list[str],
    prompt_hint: str,
    dest_dir: Path,
    provider: Optional[str] = None,
    count: Optional[int] = None,
    exclude_ids: Optional[set[str]] = None,
    max_candidates: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """
    Search related images and download them into `dest_dir`.

    Returns:
      - downloaded file paths
      - meta dict list for persistence/audit (provider/query/picked/attribution)
    """
    provider_env = (provider or os.getenv("IMAGE_PROVIDER") or "").strip().lower()
    provider_name = provider_env or DEFAULT_PROVIDER

    timeout_s = float(os.getenv("IMAGE_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    max_candidates = int(os.getenv("IMAGE_MAX_CANDIDATES") or (max_candidates or DEFAULT_MAX_CANDIDATES))
    orientation = (os.getenv("IMAGE_ORIENTATION") or DEFAULT_ORIENTATION).strip().lower()
    default_query = (os.getenv("IMAGE_QUERY_DEFAULT") or DEFAULT_QUERY).strip() or DEFAULT_QUERY
    requested_count = count
    count = _resolve_image_count(count)

    query_original = build_image_query(title, body, topics, prompt_hint)

    if provider_name in ("chatgpt_images", "chatgpt"):
        from src.images.chatgpt_images import build_chatgpt_image_prompt, generate_chatgpt_image

        # ChatGPT Images is interactive and much slower than search-based providers.
        # Default to 1 image unless the caller or env explicitly requests otherwise.
        if requested_count is None and not (os.getenv("AUTO_IMAGE_COUNT") or "").strip():
            count = 1

        chatgpt_timeout_s = float(os.getenv("CHATGPT_IMAGE_TIMEOUT_S") or 180.0)
        prompt = build_chatgpt_image_prompt(
            title=title, body=body, topics=topics, prompt_hint=prompt_hint
        )

        # Best-effort derive post_id from dest_dir; we use it only for evidence folder naming.
        post_id = dest_dir.parent.name if dest_dir.name == "assets" else dest_dir.name

        paths: list[Path] = []
        metas: list[dict[str, Any]] = []
        for _ in range(count):
            res = generate_chatgpt_image(
                post_id=post_id,
                prompt=prompt,
                dest_dir=dest_dir,
                timeout_s=chatgpt_timeout_s,
            )
            meta = {
                **res.meta,
                "query_original": query_original,
            }
            paths.append(res.path)
            metas.append(meta)
        return paths, metas

    query_used = query_original
    if provider_name == "pexels":
        hint = _pexels_query_hint(query_original)
        if hint:
            query_used = hint

    queries = _dedupe_tokens([q for q in (query_used, query_original, default_query) if q])
    last_err: Optional[str] = None
    used_ids = set(exclude_ids or [])
    paths: list[Path] = []
    metas: list[dict[str, Any]] = []

    for q in queries:
        try:
            if provider_name == "pexels":
                api_key, base_url = _load_pexels_config()
                candidates = _pexels_search_photos(
                    api_key=api_key,
                    base_url=base_url,
                    query=q,
                    per_page=max_candidates,
                    orientation=orientation,
                    timeout_s=timeout_s,
                )
            else:
                raise RuntimeError(
                    f"unsupported IMAGE_PROVIDER={provider_name!r}; supported: pexels, chatgpt_images"
                )
        except Exception as exc:
            last_err = str(exc)
            continue

        if not candidates:
            continue

        picks = pick_top_images(
            candidates, q, count - len(paths), exclude_ids=used_ids
        )
        if not picks:
            continue

        for picked in picks:
            if len(paths) >= count:
                break
            if picked.id in used_ids:
                continue
            ext = _guess_ext(picked.download_url)
            filename = f"auto_image_{provider_name}_{picked.id}{ext}"
            dest_path = dest_dir / filename
            try:
                if not dest_path.exists():
                    _download_image(
                        url=picked.download_url, dest_path=dest_path, timeout_s=timeout_s
                    )
            except Exception as exc:
                last_err = str(exc)
                continue

            meta: dict[str, Any] = {
                "mode": "auto_image",
                "provider": provider_name,
                "query": q,
                "query_original": query_original,
                "query_used": q,
                "picked": asdict(picked),
                "downloaded_path": str(dest_path),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            paths.append(dest_path)
            metas.append(meta)
            used_ids.add(picked.id)

        if len(paths) >= count:
            break

    if not paths:
        raise RuntimeError(
            f"no image returned (provider={provider_name}, query={query_used}, err={last_err})"
        )
    return paths, metas


def fetch_and_download_related_image(
    *,
    title: str,
    body: str,
    topics: list[str],
    prompt_hint: str,
    dest_dir: Path,
    provider: Optional[str] = None,
    max_candidates: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Search a related image and download it into `dest_dir`.

    Returns:
      - downloaded file path
      - meta dict for persistence/audit (provider/query/picked/attribution)
    """
    paths, metas = fetch_and_download_related_images(
        title=title,
        body=body,
        topics=topics,
        prompt_hint=prompt_hint,
        dest_dir=dest_dir,
        provider=provider,
        count=1,
        max_candidates=max_candidates,
        timeout_s=timeout_s,
    )
    return paths[0], metas[0]
