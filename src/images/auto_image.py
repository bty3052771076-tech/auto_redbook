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

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_HASHTAG_RE = re.compile(r"#\S+")


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
    if title_norm:
        parts.append(title_norm)

    topics_norm: list[str] = []
    for t in topics or []:
        t = _compact_spaces(t).lstrip("#")
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
    if re.search(r"[a-zA-Z]", q):
        return q
    tokens: list[str] = []
    if "美国" in q or "美國" in q:
        tokens.append("USA")
    if "时政" in q or "時政" in q or "政治" in q:
        tokens.append("politics")
    if "大选" in q or "大選" in q or "选举" in q or "選舉" in q:
        tokens.append("election")
    if "国会" in q or "國會" in q:
        tokens.append("congress")
    if "外交" in q:
        tokens.append("diplomacy")
    if "经济" in q or "經濟" in q or "财经" in q or "財經" in q:
        tokens.append("economy")
    if "科技" in q or "AI" in q.upper() or "人工智能" in q:
        tokens.append("technology")
    if "国际" in q or "國際" in q:
        tokens.append("international")
    if "新闻" in q:
        tokens.append("news")
    if "金融" in q:
        tokens.append("finance")

    return " ".join(tokens).strip()


def _relevance_score(item: ImageItem, query: str) -> float:
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    item_text = f"{item.alt or ''} {item.photographer or ''} {item.page_url or ''}".lower()
    i_tokens = _tokens(item_text)
    hit = len(q_tokens & i_tokens)
    denom = max(1, len(q_tokens))
    score = hit / denom

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
    provider_env = (provider or os.getenv("IMAGE_PROVIDER") or "").strip().lower()
    provider_name = provider_env or DEFAULT_PROVIDER

    timeout_s = float(os.getenv("IMAGE_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    max_candidates = int(os.getenv("IMAGE_MAX_CANDIDATES") or (max_candidates or DEFAULT_MAX_CANDIDATES))
    orientation = (os.getenv("IMAGE_ORIENTATION") or DEFAULT_ORIENTATION).strip().lower()
    default_query = (os.getenv("IMAGE_QUERY_DEFAULT") or DEFAULT_QUERY).strip() or DEFAULT_QUERY

    query_original = build_image_query(title, body, topics, prompt_hint)
    query_used = query_original
    if provider_name == "pexels":
        hint = _pexels_query_hint(query_original)
        if hint:
            query_used = hint
    queries = [q for q in (query_used, default_query) if q]

    chosen_query = query_used
    candidates: list[ImageItem] = []
    last_err: Optional[str] = None

    for q in queries:
        chosen_query = q
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
                    f"unsupported IMAGE_PROVIDER={provider_name!r}; supported: pexels"
                )
            if candidates:
                break
        except Exception as exc:
            last_err = str(exc)
            candidates = []

    if not candidates:
        raise RuntimeError(
            f"no image returned (provider={provider_name}, query={chosen_query}, err={last_err})"
        )

    picked = pick_best_image(candidates, chosen_query)

    ext = _guess_ext(picked.download_url)
    filename = f"auto_image_{provider_name}_{picked.id}{ext}"
    dest_path = dest_dir / filename
    if not dest_path.exists():
        _download_image(url=picked.download_url, dest_path=dest_path, timeout_s=timeout_s)

    meta: dict[str, Any] = {
        "mode": "auto_image",
        "provider": provider_name,
        "query": chosen_query,
        "query_original": query_original,
        "query_used": query_used,
        "picked": asdict(picked),
        "downloaded_path": str(dest_path),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    return dest_path, meta
