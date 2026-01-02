from __future__ import annotations

import json
import os
import re
from pathlib import Path
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_PROVIDER = "gdelt"
DEFAULT_TZ = "Asia/Shanghai"
DEFAULT_QUERY = "china"
DEFAULT_MAX_RECORDS = 50
DEFAULT_TIMEOUT_S = 20.0

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_BASE_URL = "https://newsapi.org"

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    domain: Optional[str] = None
    seendate: Optional[str] = None
    language: Optional[str] = None
    socialimage: Optional[str] = None
    sourcecountry: Optional[str] = None


def _resolve_tz(tz_name: str):
    tz_name = (tz_name or "").strip()
    if not tz_name:
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # Windows often lacks the IANA tz database unless tzdata is installed.
        if tz_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        return datetime.now().astimezone().tzinfo or timezone.utc


def _today_range_utc(tz_name: str) -> tuple[str, str]:
    tz = _resolve_tz(tz_name)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)
    fmt = "%Y%m%d%H%M%S"
    return start_utc.strftime(fmt), end_utc.strftime(fmt)


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
            # Add bigrams to improve fuzzy matching for Chinese.
            if len(part) <= 4:
                out.update(part)
            for i in range(len(part) - 1):
                out.add(part[i : i + 2])
    return out


def _parse_seendate_utc(seendate: Optional[str]) -> Optional[datetime]:
    if not seendate:
        return None
    seendate = seendate.strip()
    try:
        # Example: 20251230T011500Z
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(seendate, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    try:
        # Best-effort ISO 8601 support (e.g. 2025-12-30T07:00:00+00:00)
        iso = seendate.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _relevance_score(item: NewsItem, prompt_hint: str) -> float:
    hint = (prompt_hint or "").strip()
    if not hint:
        return 0.0
    hint_lc = hint.lower()
    item_text = f"{item.title} {item.domain or ''}".lower()
    hint_tokens = _tokens(hint_lc)
    if not hint_tokens:
        return 0.0
    title_tokens = _tokens(item.title)
    all_tokens = _tokens(item_text)

    title_hit = len(hint_tokens & title_tokens)
    all_hit = len(hint_tokens & all_tokens)

    # Normalize by hint size and heavily weight title matches.
    denom = max(1, len(hint_tokens))
    score = (2.0 * title_hit + 1.0 * all_hit) / denom

    if hint_lc in item_text:
        score += 1.0
    return score


def _best_relevance(items: list[NewsItem], hint: str) -> float:
    hint = (hint or "").strip()
    if not hint or not items:
        return 0.0
    return max(_relevance_score(i, hint) for i in items)


def _maybe_translate_hint_to_en(hint: str) -> str:
    """
    Best-effort mapping for common Chinese hints to English keywords for NewsAPI.
    This is intentionally lightweight (no external translation dependency).
    """
    hint = (hint or "").strip()
    if not hint:
        return ""
    # If it already contains enough ASCII, keep it as-is.
    if re.search(r"[a-zA-Z]", hint):
        return hint
    tokens: list[str] = []
    if "美国" in hint or "美國" in hint:
        tokens.append("US")
    if "时政" in hint or "時政" in hint or "政治" in hint:
        tokens.append("politics")
    if "大选" in hint or "大選" in hint or "选举" in hint or "選舉" in hint:
        tokens.append("election")
    if "国会" in hint or "國會" in hint:
        tokens.append("congress")
    if "外交" in hint:
        tokens.append("diplomacy")
    if "经济" in hint or "經濟" in hint or "财经" in hint or "財經" in hint:
        tokens.append("economy")
    if "科技" in hint or "AI" in hint.upper() or "人工智能" in hint:
        tokens.append("technology")
    if "战争" in hint or "戰爭" in hint:
        tokens.append("war")
    if "国际" in hint or "國際" in hint:
        tokens.append("international")

    return " ".join(tokens).strip()


def pick_best_news(items: list[NewsItem], prompt_hint: str) -> NewsItem:
    if not items:
        raise ValueError("no news candidates")
    if not (prompt_hint or "").strip():
        return items[0]

    best = items[0]
    best_key = (-1.0, datetime.min.replace(tzinfo=timezone.utc))
    for item in items:
        score = _relevance_score(item, prompt_hint)
        seen = _parse_seendate_utc(item.seendate) or datetime.min.replace(tzinfo=timezone.utc)
        key = (score, seen)
        if key > best_key:
            best = item
            best_key = key
    return best


def pick_news_items(
    items: list[NewsItem],
    prompt_hint: str,
    *,
    count: int = 1,
) -> list[NewsItem]:
    """
    Pick one (best match) or multiple (first N) news items.

    - If `prompt_hint` is provided: return a single best match.
    - If `prompt_hint` is empty: return up to `count` distinct items.
    """
    if count <= 0:
        return []
    if not items:
        raise ValueError("no news candidates")

    hint = (prompt_hint or "").strip()
    if hint:
        return [pick_best_news(items, hint)]

    picked: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        key = item.url or item.title
        if key in seen:
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) >= count:
            break
    return picked


def _gdelt_fetch_articles(
    *,
    query: str,
    startdatetime: str,
    enddatetime: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "startdatetime": startdatetime,
        "enddatetime": enddatetime,
        "sort": "HybridRel",
    }
    url = f"{GDELT_DOC_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    articles = data.get("articles", [])
    items: list[NewsItem] = []
    for a in articles:
        if not isinstance(a, dict):
            continue
        title = (a.get("title") or "").strip()
        url_item = (a.get("url") or "").strip()
        if not title or not url_item:
            continue
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                domain=(a.get("domain") or "").strip() or None,
                seendate=(a.get("seendate") or "").strip() or None,
                language=(a.get("language") or "").strip() or None,
                socialimage=(a.get("socialimage") or "").strip() or None,
                sourcecountry=(a.get("sourcecountry") or "").strip() or None,
            )
        )
    return items


def _parse_kv_file(path: Path) -> dict[str, str]:
    """
    Parse a simple key file with lines like:
      base_url="https://..."
      api_key="..."
    """
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


def _load_newsapi_config(
    *,
    key_file: Path | str = Path("docs/news_api-key.md"),
) -> tuple[str, str]:
    env_key = os.getenv("NEWS_API_KEY") or os.getenv("NEWSAPI_API_KEY")
    env_base = os.getenv("NEWS_BASE_URL") or os.getenv("NEWSAPI_BASE_URL")
    file_cfg = _parse_kv_file(Path(key_file))

    api_key = env_key or file_cfg.get("api_key")
    base_url = env_base or file_cfg.get("base_url") or NEWSAPI_BASE_URL
    if not api_key:
        raise RuntimeError("NewsAPI api_key missing: set NEWS_API_KEY env or docs/news_api-key.md")
    return api_key, base_url


def _newsapi_fetch_articles(
    *,
    api_key: str,
    base_url: str,
    query: str,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
    sort_by: str = "publishedAt",
    page_size: int,
    timeout_s: float,
) -> list[NewsItem]:
    page_size = max(1, min(int(page_size), 100))
    params = {
        "q": query,
        "sortBy": sort_by,
        "pageSize": str(page_size),
        "apiKey": api_key,
    }
    if from_iso:
        params["from"] = from_iso
    if to_iso:
        params["to"] = to_iso
    url = f"{base_url.rstrip('/')}/v2/everything?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data}")
    articles = data.get("articles", [])
    items: list[NewsItem] = []
    for a in articles:
        if not isinstance(a, dict):
            continue
        title = (a.get("title") or "").strip()
        url_item = (a.get("url") or "").strip()
        if not title or not url_item:
            continue
        domain = urllib.parse.urlparse(url_item).netloc or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                domain=domain,
                seendate=(a.get("publishedAt") or "").strip() or None,
                socialimage=(a.get("urlToImage") or "").strip() or None,
            )
        )
    return items


def fetch_daily_news_candidates(
    prompt_hint: str,
    *,
    tz_name: Optional[str] = None,
    max_records: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> tuple[list[NewsItem], dict[str, Any]]:
    """
    Fetch today's news via an external API.

    Returns:
      - candidates list
      - meta dict for persistence/audit (provider/query/time range/candidates)
    """
    provider_env = (os.getenv("NEWS_PROVIDER") or "").strip().lower()
    tz_name = (tz_name or os.getenv("NEWS_TZ") or DEFAULT_TZ).strip()
    max_records = int(os.getenv("NEWS_MAX_RECORDS") or (max_records or DEFAULT_MAX_RECORDS))
    timeout_s = float(os.getenv("NEWS_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))

    startdatetime, enddatetime = _today_range_utc(tz_name)
    start_dt = datetime.strptime(startdatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(enddatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    from_iso = start_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    to_iso = end_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    provider = provider_env
    if not provider:
        # Auto: prefer NewsAPI when a key is configured, otherwise fall back to GDELT.
        try:
            _load_newsapi_config()
            provider = "newsapi"
        except Exception:
            provider = DEFAULT_PROVIDER

    if provider not in ("gdelt", "newsapi"):
        raise RuntimeError(
            f"unsupported NEWS_PROVIDER={provider!r}; supported: gdelt, newsapi"
        )

    default_query = (os.getenv("NEWS_QUERY_DEFAULT") or DEFAULT_QUERY).strip()
    hint_query = (prompt_hint or "").strip()
    hint_en = _maybe_translate_hint_to_en(hint_query) if hint_query else ""
    queries = [q for q in (hint_query, hint_en, default_query) if q]

    last_err: Optional[str] = None
    chosen_query = default_query
    candidates: list[NewsItem] = []
    used_time_range = False
    for q in queries:
        chosen_query = q
        try:
            if provider == "newsapi":
                api_key, base_url = _load_newsapi_config()
                sort_by = "relevancy" if q in (hint_query, hint_en) and q else "publishedAt"
                raw = _newsapi_fetch_articles(
                    api_key=api_key,
                    base_url=base_url,
                    query=q,
                    from_iso=from_iso,
                    to_iso=to_iso,
                    sort_by=sort_by,
                    page_size=max_records,
                    timeout_s=timeout_s,
                )
                if not raw:
                    # If today's time window yields no results (common in early hours),
                    # fall back to an unbounded search and filter locally.
                    raw = _newsapi_fetch_articles(
                        api_key=api_key,
                        base_url=base_url,
                        query=q,
                        from_iso=None,
                        to_iso=None,
                        sort_by=sort_by,
                        page_size=max_records,
                        timeout_s=timeout_s,
                    )
                in_today = []
                for item in raw:
                    seen = _parse_seendate_utc(item.seendate)
                    if seen and start_dt <= seen <= end_dt:
                        in_today.append(item)
                candidates = in_today or raw
                used_time_range = bool(in_today)
                # If user provided a hint and nothing matches it, try the next query variant.
                if hint_query and q != default_query and _best_relevance(candidates, q) <= 0.0:
                    candidates = []
            else:
                candidates = _gdelt_fetch_articles(
                    query=q,
                    startdatetime=startdatetime,
                    enddatetime=enddatetime,
                    max_records=max_records,
                    timeout_s=timeout_s,
                )
            if candidates:
                break
        except Exception as exc:
            last_err = str(exc)
            candidates = []

    if not candidates:
        raise RuntimeError(
            f"no news returned (provider={provider}, query={chosen_query}, err={last_err})"
        )

    meta: dict[str, Any] = {
        "provider": provider,
        "tz": tz_name,
        "query": chosen_query,
        "query_variants": queries,
        "startdatetime": startdatetime,
        "enddatetime": enddatetime,
        "used_today_range": used_time_range,
        "candidates": [asdict(c) for c in candidates[:10]],
    }
    return candidates, meta


def fetch_and_pick_daily_news(
    prompt_hint: str,
    *,
    tz_name: Optional[str] = None,
    max_records: Optional[int] = None,
    timeout_s: Optional[float] = None,
) -> tuple[NewsItem, dict[str, Any]]:
    """
    Fetch today's news via an external API and pick the best match for `prompt_hint`.

    Returns:
      - picked NewsItem
      - meta dict for persistence/audit (provider/query/time range/candidates)
    """
    candidates, base_meta = fetch_daily_news_candidates(
        prompt_hint,
        tz_name=tz_name,
        max_records=max_records,
        timeout_s=timeout_s,
    )
    score_hint = (base_meta.get("query") or "").strip()
    picked = pick_best_news(candidates, score_hint if score_hint else prompt_hint)
    meta = {**base_meta, "picked": asdict(picked)}
    return picked, meta
