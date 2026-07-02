from __future__ import annotations

import json
import os
import random
import re
import math
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .history import collect_used_news_url_keys, filter_used_news_items, news_history_dedupe_enabled

DEFAULT_PROVIDER = "gnews"
DEFAULT_TZ = "Asia/Shanghai"
DEFAULT_QUERY = "technology"
DEFAULT_QUERY_POOL = (
    "technology",
    "world",
    "science",
    "business",
    "health",
    "climate",
    "society",
    "international",
)
DEFAULT_MAX_RECORDS = 50
DEFAULT_TIMEOUT_S = 20.0
CROSS_DOMAIN_SIM_THRESHOLD = 0.75
CROSS_DOMAIN_BONUS = 0.4
NEWS_DEDUPE_SIM_THRESHOLD = 0.8
DEFAULT_CHINA_RATIO = 0.6
DEFAULT_CHINA_BONUS = 0.15
DEFAULT_SOURCE_DOMAIN_MAX_RATIO = 0.5
LOW_QUALITY_NEWS_DOMAINS = {
    "pypi.org",
    "test.pypi.org",
    "github.com",
    "gitlab.com",
    "npmjs.com",
    "crates.io",
    "rubygems.org",
    "packagist.org",
    "libraries.io",
}
LOW_QUALITY_NEWS_TITLE_PATTERNS = (
    re.compile(r"^\s*watch\s*:", re.IGNORECASE),
    re.compile(r"\bnews in brief\b", re.IGNORECASE),
    re.compile(r"\badded to pypi\b", re.IGNORECASE),
    re.compile(r"\bpublished to pypi\b", re.IGNORECASE),
    re.compile(r"\bpackage\b.*\b(pypi|npm|crates\.io|rubygems)\b", re.IGNORECASE),
    re.compile(r"\b(version|release|changelog|release notes)\s+v?\d", re.IGNORECASE),
    re.compile(r"\bgithub (release|repository|repo)\b", re.IGNORECASE),
)

NEWSAPI_BASE_URL = "https://newsapi.org"
GNEWS_BASE_URL = "https://gnews.io/api/v4"
JUHE_NEWS_BASE_URL = "https://v.juhe.cn/toutiao"
JUHE_FINANCE_NEWS_BASE_URL = "https://apis.juhe.cn/fapigx/caijing"
HOTNEWS_BASE_URL = "https://orz.ai/api/v1/dailynews"
HOTNEWS_DEFAULT_PLATFORMS = (
    "jinritoutiao",
    "sina_finance",
    "cls",
    "baidu",
    "weibo",
    "hackernews",
)
HOTNEWS_CHINA_PLATFORMS = {
    "baidu",
    "weibo",
    "jinritoutiao",
    "sina_finance",
    "cls",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_ENTITY_RE = re.compile(r"[a-z]{2,}|\d{1,3}", re.IGNORECASE)
_ENTITY_STOPWORDS = {
    # Common function words
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
    # News boilerplate / generic terms
    "analysis",
    "ap",
    "daily",
    "live",
    "news",
    "opinion",
    "report",
    "reports",
    "reuters",
    "update",
    "updates",
    "watch",
    # Common geopolitics / categories (too generic for dedupe)
    "china",
    "chinese",
    "hong",
    "kong",
    "japan",
    "japanese",
    "us",
    "u",
    "s",
    "usa",
    "uk",
    "eu",
    "india",
    "indian",
    "world",
    "international",
    # Generic event words
    "case",
    "court",
    "deal",
    "deals",
    "election",
    "historic",
    "landmark",
    "market",
    "markets",
    "prices",
    "sentenced",
    "sentences",
    "sentence",
    "jail",
    "jails",
    "years",
    "year",
}


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    domain: Optional[str] = None
    seendate: Optional[str] = None
    language: Optional[str] = None
    socialimage: Optional[str] = None
    sourcecountry: Optional[str] = None
    attention: Optional[float] = None


@dataclass(frozen=True)
class JuheConfig:
    news_key: Optional[str]
    finance_key: Optional[str]
    news_base_url: str
    finance_base_url: str


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


def _entity_tokens(text: str) -> set[str]:
    """
    Extract lightweight entity-ish tokens from a title/description for cross-language dedupe.

    We intentionally ignore CJK here; the main goal is to catch duplicate stories across
    different languages that still share ASCII names (e.g., "Jimmy Lai") and key numbers
    (e.g., "20").
    """
    text = (text or "").strip().lower()
    if not text:
        return set()
    out: set[str] = set()
    for m in _ENTITY_RE.finditer(text):
        tok = (m.group(0) or "").strip().lower()
        if not tok or tok in _ENTITY_STOPWORDS:
            continue
        out.add(tok)
    return out


def _entity_similar(tokens_a: set[str], tokens_b: set[str]) -> bool:
    if not tokens_a or not tokens_b:
        return False
    inter = tokens_a & tokens_b
    if len(inter) >= 3:
        return True
    if len(inter) >= 2 and any(not t.isdigit() for t in inter):
        return True
    return False


def _domain_for_item(item: NewsItem) -> str:
    if item.domain:
        return item.domain.strip().lower()
    try:
        return urllib.parse.urlparse(item.url or "").netloc.strip().lower()
    except Exception:
        return ""


def _canonical_domain(domain: str) -> str:
    text = (domain or "").strip().lower()
    return text[4:] if text.startswith("www.") else text


def _is_low_quality_daily_news_candidate(item: NewsItem) -> bool:
    domain = _canonical_domain(_domain_for_item(item))
    if domain in LOW_QUALITY_NEWS_DOMAINS:
        return True
    title = item.title or ""
    joined = " ".join(
        part
        for part in (item.title, item.description, item.content)
        if part
    )
    if any(pattern.search(title) or pattern.search(joined) for pattern in LOW_QUALITY_NEWS_TITLE_PATTERNS):
        return True
    return False


def _is_china_item(item: NewsItem) -> bool:
    # Prefer explicit metadata when available.
    country = (item.sourcecountry or "").strip().lower()
    if country in ("china", "cn", "chn", "ch"):
        return True
    domain = _domain_for_item(item)
    if domain.endswith(".cn") or domain.endswith(".gov.cn") or domain.endswith(".edu.cn"):
        return True
    return False


def _china_ratio() -> float:
    raw = (os.getenv("NEWS_CHINA_RATIO") or "").strip()
    if not raw:
        return DEFAULT_CHINA_RATIO
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_CHINA_RATIO
    # Clamp to a reasonable range.
    return max(0.0, min(1.0, value))


def _china_bonus() -> float:
    raw = (os.getenv("NEWS_CHINA_BONUS") or "").strip()
    if not raw:
        return DEFAULT_CHINA_BONUS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_CHINA_BONUS


def _source_domain_max_ratio() -> float:
    raw = (os.getenv("NEWS_SOURCE_DOMAIN_MAX_RATIO") or "").strip()
    if not raw:
        return DEFAULT_SOURCE_DOMAIN_MAX_RATIO
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SOURCE_DOMAIN_MAX_RATIO
    return max(0.2, min(1.0, value))


def _attention_score(item: NewsItem) -> float:
    explicit = getattr(item, "attention", None)
    if explicit is not None:
        try:
            return max(0.0, float(explicit))
        except (TypeError, ValueError):
            pass
    text = " ".join(part for part in (item.title, item.description, item.content) if part)
    score = 0.0
    weighted_markers: tuple[tuple[str, float], ...] = (
        ("国务院", 2.0),
        ("中央", 1.6),
        ("监管", 1.5),
        ("调查", 1.5),
        ("新规", 1.5),
        ("施行", 1.2),
        ("发布", 1.0),
        ("宣布", 1.0),
        ("处罚", 1.5),
        ("禁令", 1.5),
        ("事故", 1.5),
        ("死亡", 1.5),
        ("上市", 1.0),
        ("收购", 1.0),
        ("裁员", 1.0),
        ("暴涨", 1.0),
        ("暴跌", 1.0),
        ("突破", 1.0),
        ("record", 0.8),
        ("ban", 0.8),
        ("probe", 0.8),
        ("investigation", 0.8),
        ("policy", 0.6),
    )
    lower = text.lower()
    for marker, weight in weighted_markers:
        if marker.lower() in lower:
            score += weight
    if re.search(r"\d|[一二三四五六七八九十两]", text):
        score += 0.4
    return score


def _limit_single_domain(items: list[NewsItem], *, count: int) -> list[NewsItem]:
    if count <= 1 or not items:
        return items[:count] if count > 0 else []
    domains = [_canonical_domain(_domain_for_item(item)) for item in items]
    available_domains = {domain for domain in domains if domain}
    if len(available_domains) <= 1:
        return items[:count]
    cap = max(1, int(math.ceil(count * _source_domain_max_ratio())))
    picked: list[NewsItem] = []
    overflow: list[NewsItem] = []
    domain_counts: dict[str, int] = {}
    for item, domain in zip(items, domains):
        key = domain or f"unknown:{len(domain_counts)}"
        current = domain_counts.get(key, 0)
        if current < cap:
            picked.append(item)
            domain_counts[key] = current + 1
        else:
            overflow.append(item)
        if len(picked) >= count:
            break
    if len(picked) < count:
        for item in overflow:
            picked.append(item)
            if len(picked) >= count:
                break
    return picked


def _balance_china_foreign(items: list[NewsItem], *, count: int) -> list[NewsItem]:
    """
    Keep a rough China:foreign ratio (default 6:4) while preserving relevance order.
    If one side is insufficient, fill from the other side.
    """
    if count <= 0 or not items:
        return []
    if count == 1:
        return items[:1]

    ratio = _china_ratio()
    desired_china = int(round(count * ratio))
    desired_china = max(0, min(count, desired_china))
    desired_foreign = count - desired_china

    china_items = [it for it in items if _is_china_item(it)]
    foreign_items = [it for it in items if not _is_china_item(it)]

    picked: list[NewsItem] = []
    picked_china = 0
    picked_foreign = 0
    i = 0
    j = 0
    while len(picked) < count and (i < len(china_items) or j < len(foreign_items)):
        need_china = picked_china < desired_china
        need_foreign = picked_foreign < desired_foreign
        if need_china and i < len(china_items):
            picked.append(china_items[i])
            i += 1
            picked_china += 1
            continue
        if need_foreign and j < len(foreign_items):
            picked.append(foreign_items[j])
            j += 1
            picked_foreign += 1
            continue
        # Quota reached or missing: fill from remaining.
        if i < len(china_items):
            picked.append(china_items[i])
            i += 1
            picked_china += 1
            continue
        if j < len(foreign_items):
            picked.append(foreign_items[j])
            j += 1
            picked_foreign += 1
            continue
    return picked


def _title_similar(
    tokens_a: set[str],
    tokens_b: set[str],
    *,
    threshold: float = CROSS_DOMAIN_SIM_THRESHOLD,
) -> bool:
    if not tokens_a or not tokens_b:
        return False
    min_len = min(len(tokens_a), len(tokens_b))
    if min_len < 3:
        return False
    overlap = len(tokens_a & tokens_b) / min_len
    return overlap >= threshold


def _cross_domain_counts(items: list[NewsItem]) -> list[int]:
    tokens_list = [_tokens(item.title) for item in items]
    domains = [_domain_for_item(item) for item in items]
    counts: list[int] = []
    for i, tokens_i in enumerate(tokens_list):
        domains_i: set[str] = set()
        if domains[i]:
            domains_i.add(domains[i])
        for j, tokens_j in enumerate(tokens_list):
            if i == j:
                continue
            if not domains[j] or domains[j] == domains[i]:
                continue
            if _title_similar(tokens_i, tokens_j):
                domains_i.add(domains[j])
        counts.append(len(domains_i))
    return counts


def _dedupe_by_title(items: list[NewsItem], *, max_count: int) -> list[NewsItem]:
    picked: list[NewsItem] = []
    picked_tokens: list[set[str]] = []
    for item in items:
        tokens = _tokens(item.title)
        if any(
            _title_similar(tokens, t, threshold=NEWS_DEDUPE_SIM_THRESHOLD)
            for t in picked_tokens
        ):
            continue
        picked.append(item)
        picked_tokens.append(tokens)
        if len(picked) >= max_count:
            break
    return picked


def _dedupe_by_story(items: list[NewsItem], *, max_count: int) -> list[NewsItem]:
    """
    More aggressive than title-only dedupe: also attempts to dedupe cross-language stories
    by overlapping ASCII "entity-ish" tokens (names/abbreviations/numbers).

    This is used when selecting multiple items to publish. We keep fetch-time candidate
    dedupe conservative to preserve cross-domain evidence for scoring.
    """
    picked: list[NewsItem] = []
    picked_title_tokens: list[set[str]] = []
    picked_entity_tokens: list[set[str]] = []
    for item in items:
        title_tokens = _tokens(item.title)
        entity_tokens = _entity_tokens(f"{item.title} {item.description or ''}")
        if any(
            _title_similar(title_tokens, t, threshold=NEWS_DEDUPE_SIM_THRESHOLD)
            for t in picked_title_tokens
        ):
            continue
        # Cross-language dedupe: only apply entity matching when title tokens overlap is low.
        # This avoids over-deduping highly-related-but-distinct stories like:
        # "Apple releases new Mac" vs "Apple releases new iPad".
        max_overlap = 0.0
        for t in picked_title_tokens:
            if not title_tokens or not t:
                continue
            denom = float(min(len(title_tokens), len(t)) or 1)
            max_overlap = max(max_overlap, len(title_tokens & t) / denom)
        if (
            max_overlap < 0.6
            and entity_tokens
            and any(_entity_similar(entity_tokens, e) for e in picked_entity_tokens)
        ):
            continue
        picked.append(item)
        picked_title_tokens.append(title_tokens)
        picked_entity_tokens.append(entity_tokens)
        if len(picked) >= max_count:
            break
    return picked


def _dedupe_candidates(items: list[NewsItem]) -> list[NewsItem]:
    items = [item for item in items if not _is_low_quality_daily_news_candidate(item)]
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = item.url or item.title
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return _dedupe_by_title(unique, max_count=len(unique))


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
    counts = _cross_domain_counts(items)
    if not (prompt_hint or "").strip():
        if not any(c >= 2 for c in counts):
            # Default: bias slightly toward China news if possible.
            ratio = _china_ratio()
            if ratio <= 0.0:
                return items[0]
            for it in items:
                if _is_china_item(it):
                    return it
            return items[0]
        best = items[0]
        best_key = (_is_china_item(best), counts[0], datetime.min.replace(tzinfo=timezone.utc))
        for idx, item in enumerate(items):
            seen = _parse_seendate_utc(item.seendate) or datetime.min.replace(
                tzinfo=timezone.utc
            )
            key = (_is_china_item(item), counts[idx], seen)
            if key > best_key:
                best = item
                best_key = key
        return best

    best = items[0]
    best_key = (-1.0, datetime.min.replace(tzinfo=timezone.utc))
    china_bonus = _china_bonus()
    for idx, item in enumerate(items):
        score = _relevance_score(item, prompt_hint)
        score += max(0, counts[idx] - 1) * CROSS_DOMAIN_BONUS
        if _is_china_item(item):
            score += china_bonus
        seen = _parse_seendate_utc(item.seendate) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        key = (score, counts[idx], seen)
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

    - If `prompt_hint` is provided: return up to `count` items sorted by relevance.
    - If `prompt_hint` is empty: return up to `count` distinct items.
    """
    if count <= 0:
        return []
    if not items:
        raise ValueError("no news candidates")

    hint = (prompt_hint or "").strip()
    counts = _cross_domain_counts(items)
    if hint:
        scored: list[tuple[float, datetime, int, int, NewsItem]] = []
        seen: set[str] = set()
        china_bonus = _china_bonus()
        for idx, item in enumerate(items):
            key = item.url or item.title
            if key in seen:
                continue
            seen.add(key)
            score = _relevance_score(item, hint)
            score += max(0, counts[idx] - 1) * CROSS_DOMAIN_BONUS
            score += _attention_score(item) * 0.2
            if _is_china_item(item):
                score += china_bonus
            seen_at = _parse_seendate_utc(item.seendate) or datetime.min.replace(
                tzinfo=timezone.utc
            )
            scored.append((score, seen_at, counts[idx], -idx, item))
        scored.sort(reverse=True)
        order = [item for _, _, _, _, item in scored]
        deduped = _dedupe_by_story(order, max_count=len(order))
        deduped = _limit_single_domain(deduped, count=count)
        return _balance_china_foreign(deduped, count=count)

    seen: set[str] = set()
    if any(c >= 2 for c in counts):
        scored: list[tuple[int, float, datetime, int, NewsItem]] = []
        for idx, item in enumerate(items):
            seen_at = _parse_seendate_utc(item.seendate) or datetime.min.replace(
                tzinfo=timezone.utc
            )
            scored.append((counts[idx], _attention_score(item), seen_at, -idx, item))
        scored.sort(reverse=True)
        order = [item for _, _, _, _, item in scored]
    else:
        scored = []
        for idx, item in enumerate(items):
            seen_at = _parse_seendate_utc(item.seendate) or datetime.min.replace(
                tzinfo=timezone.utc
            )
            scored.append((_attention_score(item), seen_at, -idx, item))
        scored.sort(reverse=True)
        order = [item for _, _, _, item in scored]

    unique: list[NewsItem] = []
    for item in order:
        key = item.url or item.title
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    deduped = _dedupe_by_story(unique, max_count=len(unique))
    deduped = _limit_single_domain(deduped, count=count)
    return _balance_china_foreign(deduped, count=count)


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


def _load_gnews_config(
    *,
    key_file: Path | str = Path("docs/gnews_api-key.md"),
) -> tuple[str, str]:
    env_key = os.getenv("GNEWS_API_KEY") or os.getenv("GNEWS_TOKEN")
    env_base = os.getenv("GNEWS_BASE_URL")
    file_cfg = _parse_kv_file(Path(key_file))

    api_key = env_key or file_cfg.get("api_key") or file_cfg.get("apikey")
    base_url = env_base or file_cfg.get("base_url") or GNEWS_BASE_URL
    if not api_key:
        raise RuntimeError("GNews api_key missing: set GNEWS_API_KEY env or docs/gnews_api-key.md")
    return api_key.strip(), base_url.strip().rstrip("/")


def _load_juhe_config(
    *,
    key_file: Path | str = Path("docs/juhe_api-key.md"),
) -> JuheConfig:
    file_cfg = _parse_kv_file(Path(key_file))

    news_key = (
        os.getenv("JUHE_NEWS_APPKEY")
        or os.getenv("JUHE_NEWS_KEY")
        or os.getenv("JUHE_TOUTIAO_APPKEY")
        or os.getenv("JUHE_APPKEY")
        or file_cfg.get("news_appkey")
        or file_cfg.get("news_api_key")
        or file_cfg.get("news_key")
        or file_cfg.get("toutiao_appkey")
        or file_cfg.get("api_key")
        or file_cfg.get("appkey")
    )
    finance_key = (
        os.getenv("JUHE_FINANCE_NEWS_APPKEY")
        or os.getenv("JUHE_FINANCE_APPKEY")
        or os.getenv("JUHE_CAIJING_APPKEY")
        or file_cfg.get("finance_appkey")
        or file_cfg.get("finance_api_key")
        or file_cfg.get("finance_key")
        or file_cfg.get("caijing_appkey")
    )
    news_base_url = (
        os.getenv("JUHE_NEWS_BASE_URL")
        or os.getenv("JUHE_TOUTIAO_BASE_URL")
        or file_cfg.get("news_base_url")
        or file_cfg.get("toutiao_base_url")
        or file_cfg.get("base_url")
        or JUHE_NEWS_BASE_URL
    )
    finance_base_url = (
        os.getenv("JUHE_FINANCE_NEWS_BASE_URL")
        or os.getenv("JUHE_FINANCE_BASE_URL")
        or os.getenv("JUHE_CAIJING_BASE_URL")
        or file_cfg.get("finance_base_url")
        or file_cfg.get("caijing_base_url")
        or JUHE_FINANCE_NEWS_BASE_URL
    )
    news_key = news_key.strip() if news_key else None
    finance_key = finance_key.strip() if finance_key else None
    if not news_key and not finance_key:
        raise RuntimeError(
            "Juhe appkey missing: set JUHE_NEWS_APPKEY or JUHE_FINANCE_NEWS_APPKEY, "
            "or create local docs/juhe_api-key.md"
        )
    return JuheConfig(
        news_key=news_key,
        finance_key=finance_key,
        news_base_url=news_base_url.strip().rstrip("/"),
        finance_base_url=finance_base_url.strip().rstrip("/"),
    )


def _split_news_queries(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,，;；\n|]+", text)
    queries: list[str] = []
    seen: set[str] = set()
    for part in parts:
        q = re.sub(r"\s+", " ", part).strip()
        key = q.lower()
        if not q or key in seen:
            continue
        queries.append(q)
        seen.add(key)
    return queries


def _default_news_queries() -> list[str]:
    """
    Default broad queries for empty-prompt daily news.

    `NEWS_QUERY_DEFAULT` remains an override. It may be a single query or a
    comma/semicolon/newline separated list.
    """
    override = _split_news_queries(os.getenv("NEWS_QUERY_DEFAULT"))
    if override:
        return override
    queries = list(DEFAULT_QUERY_POOL)
    random.SystemRandom().shuffle(queries)
    return queries


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
        source = None
        source_raw = a.get("source")
        if isinstance(source_raw, dict):
            source = (source_raw.get("name") or "").strip() or None
        description = (a.get("description") or "").strip() or None
        content = (a.get("content") or "").strip() or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=source,
                description=description,
                content=content,
                domain=domain,
                seendate=(a.get("publishedAt") or "").strip() or None,
                socialimage=(a.get("urlToImage") or "").strip() or None,
                attention=_record_attention(a),
            )
        )
    return items


def _gnews_max_results(max_records: int) -> int:
    raw = (os.getenv("GNEWS_MAX") or "").strip()
    if raw:
        try:
            return max(1, min(100, int(raw)))
        except ValueError:
            pass
    # GNews free tier allows up to 10 articles per request; paid users can raise
    # this with GNEWS_MAX without changing code.
    return max(1, min(10, max_records))


def _gnews_fetch_articles(
    *,
    api_key: str,
    base_url: str,
    query: str,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[NewsItem]:
    endpoint = f"{base_url.rstrip('/')}/search"
    params: dict[str, str] = {
        "q": query,
        "apikey": api_key,
        "max": str(_gnews_max_results(max_records)),
        "sortby": "publishedAt",
        "nullable": "description,content,image",
    }
    lang = (os.getenv("GNEWS_LANG") or "").strip()
    country = (os.getenv("GNEWS_COUNTRY") or "").strip()
    if lang:
        params["lang"] = lang
    if country:
        params["country"] = country
    if from_iso:
        params["from"] = from_iso
    if to_iso:
        params["to"] = to_iso

    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if isinstance(data, dict) and data.get("errors"):
        raise RuntimeError(f"GNews error: {data.get('errors')}")

    articles = data.get("articles", []) if isinstance(data, dict) else []
    items: list[NewsItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = (article.get("title") or "").strip()
        url_item = (article.get("url") or "").strip()
        if not title or not url_item:
            continue
        source = None
        source_url = ""
        source_raw = article.get("source")
        if isinstance(source_raw, dict):
            source = (source_raw.get("name") or "").strip() or None
            source_url = (source_raw.get("url") or "").strip()
        domain = urllib.parse.urlparse(source_url or url_item).netloc or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=source,
                description=(article.get("description") or "").strip() or None,
                content=(article.get("content") or "").strip() or None,
                domain=domain,
                seendate=(article.get("publishedAt") or "").strip() or None,
                socialimage=(article.get("image") or "").strip() or None,
                attention=_record_attention(article),
            )
        )
    return items


def _juhe_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _numeric_value(value: Any) -> Optional[float]:
    text = re.sub(r"[,\s]", "", str(value or "")).strip()
    if not text:
        return None
    multiplier = 1.0
    if text.endswith(("万", "w", "W")):
        multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _record_attention(record: dict[str, Any]) -> Optional[float]:
    for key in ("score", "hot", "heat", "hot_score", "rank_score", "views", "view_count", "read_count"):
        if key in record:
            value = _numeric_value(record.get(key))
            if value is not None:
                return value
    return None


def _juhe_first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _juhe_text(record.get(key))
        if value:
            return value
    return ""


def _juhe_image(record: dict[str, Any]) -> Optional[str]:
    value = _juhe_first_text(
        record,
        (
            "thumbnail_pic_s",
            "thumbnail_pic_s02",
            "thumbnail_pic_s03",
            "picUrl",
            "picurl",
            "image",
            "img",
            "imgurl",
            "urlToImage",
        ),
    )
    return value or None


def _juhe_records_from_data(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    roots = [result, data]
    for root in roots:
        if isinstance(root, list):
            return [row for row in root if isinstance(row, dict)]
        if not isinstance(root, dict):
            continue
        for key in ("data", "list", "newslist", "items", "rows"):
            value = root.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
            if isinstance(value, dict):
                nested = _juhe_records_from_data(value)
                if nested:
                    return nested
    return []


def _juhe_ensure_success(
    data: Any,
    *,
    context: str,
    allow_detail_missing: bool = False,
) -> bool:
    if not isinstance(data, dict):
        raise RuntimeError(f"Juhe {context} error: invalid response")
    error_code = data.get("error_code")
    result_code = data.get("resultcode")
    code = error_code if error_code is not None else result_code
    ok_error = error_code in (None, 0, "0")
    ok_result = result_code in (None, 0, "0", 200, "200")
    if ok_error and ok_result:
        return True
    if allow_detail_missing and str(code) == "223502":
        return False
    reason = _juhe_text(data.get("reason") or data.get("msg") or data.get("message") or "unknown")
    raise RuntimeError(f"Juhe {context} error: code={code}, reason={reason}")


def _juhe_request_json(
    *,
    url: str,
    params: dict[str, str],
    timeout_s: float,
) -> dict[str, Any]:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Juhe HTTP error {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = _juhe_text(getattr(exc, "reason", "") or "network error")
        raise RuntimeError(f"Juhe request failed: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Juhe request timed out") from exc
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Juhe response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Juhe response is not a JSON object")
    return data


def _juhe_query_is_finance(query: str) -> bool:
    q = (query or "").strip().lower()
    finance_terms = (
        "finance",
        "business",
        "economy",
        "economic",
        "market",
        "stock",
        "securities",
        "\u8d22\u7ecf",
        "\u7ecf\u6d4e",
        "\u91d1\u878d",
        "\u80a1\u5e02",
        "\u8bc1\u5238",
        "\u516c\u53f8",
    )
    return any(term in q for term in finance_terms)


def _juhe_toutiao_type_for_query(query: str) -> str:
    override = (os.getenv("JUHE_NEWS_TYPE") or "").strip().lower()
    if override:
        return override
    q = (query or "").strip().lower()
    mappings: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("keji", ("technology", "tech", "science", "ai", "\u79d1\u6280", "\u79d1\u5b66", "\u4eba\u5de5\u667a\u80fd")),
        ("caijing", ("finance", "business", "economy", "market", "stock", "\u8d22\u7ecf", "\u7ecf\u6d4e", "\u91d1\u878d")),
        ("guoji", ("world", "international", "global", "foreign", "\u56fd\u9645", "\u6d77\u5916", "\u4e16\u754c")),
        ("guonei", ("china", "domestic", "national", "\u4e2d\u56fd", "\u56fd\u5185", "\u5168\u56fd")),
        ("shehui", ("society", "social", "health", "climate", "\u793e\u4f1a", "\u6c11\u751f", "\u5065\u5eb7", "\u6c14\u5019")),
        ("tiyu", ("sports", "sport", "\u4f53\u80b2")),
        ("yule", ("entertainment", "movie", "film", "\u5a31\u4e50", "\u7535\u5f71")),
        ("junshi", ("military", "defense", "war", "\u519b\u4e8b", "\u56fd\u9632", "\u6218\u4e89")),
        ("shishang", ("fashion", "\u65f6\u5c1a")),
    )
    for category, terms in mappings:
        if any(term in q for term in terms):
            return category
    return "top"


def _juhe_fetch_detail_enabled() -> bool:
    raw = (os.getenv("JUHE_NEWS_FETCH_DETAIL") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _juhe_detail_limit(max_records: int) -> int:
    raw = (os.getenv("JUHE_NEWS_DETAIL_LIMIT") or "").strip()
    if raw:
        try:
            return max(0, min(int(raw), max_records))
        except ValueError:
            pass
    return max(0, min(max_records, 10))


def _juhe_toutiao_detail(
    *,
    api_key: str,
    base_url: str,
    uniquekey: str,
    timeout_s: float,
) -> dict[str, Any]:
    data = _juhe_request_json(
        url=f"{base_url.rstrip('/')}/content",
        params={"key": api_key, "uniquekey": uniquekey},
        timeout_s=timeout_s,
    )
    if not _juhe_ensure_success(data, context="detail", allow_detail_missing=True):
        return {}
    result = data.get("result") if isinstance(data, dict) else {}
    merged: dict[str, Any] = {}
    if isinstance(result, dict):
        detail = result.get("detail")
        if isinstance(detail, dict):
            merged.update(detail)
        for key in ("content", "title", "date", "url", "author_name", "thumbnail_pic_s"):
            if result.get(key) is not None:
                merged[key] = result.get(key)
    return merged


def _juhe_toutiao_fetch_articles(
    *,
    api_key: str,
    base_url: str,
    query: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    news_type = _juhe_toutiao_type_for_query(query)
    data = _juhe_request_json(
        url=f"{base_url.rstrip('/')}/index",
        params={"key": api_key, "type": news_type},
        timeout_s=timeout_s,
    )
    _juhe_ensure_success(data, context="toutiao")
    records = _juhe_records_from_data(data)[: max(1, max_records)]
    detail_enabled = _juhe_fetch_detail_enabled()
    detail_limit = _juhe_detail_limit(max_records)

    items: list[NewsItem] = []
    for idx, record in enumerate(records):
        current = dict(record)
        uniquekey = _juhe_first_text(current, ("uniquekey", "unique_key", "id"))
        if detail_enabled and uniquekey and idx < detail_limit:
            try:
                detail = _juhe_toutiao_detail(
                    api_key=api_key,
                    base_url=base_url,
                    uniquekey=uniquekey,
                    timeout_s=timeout_s,
                )
                current.update({k: v for k, v in detail.items() if v not in (None, "")})
            except Exception:
                # Detail is a quality boost, not a hard requirement for the list item.
                pass
        title = _juhe_first_text(current, ("title", "news_title"))
        url_item = _juhe_first_text(current, ("url", "link", "news_url", "share_url"))
        if not title or not url_item:
            continue
        domain = urllib.parse.urlparse(url_item).netloc or None
        description = _juhe_first_text(current, ("description", "desc", "digest", "summary", "abstract")) or None
        content = _juhe_first_text(current, ("content", "body", "text")) or None
        source = _juhe_first_text(
            current,
            ("author_name", "source", "source_name", "media_name", "channel"),
        ) or None
        seendate = _juhe_first_text(
            current,
            ("date", "ctime", "time", "publish_time", "pubDate", "published_at", "publishedAt"),
        ) or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=source,
                description=description,
                content=content,
                domain=domain,
                seendate=seendate,
                language="zh",
                socialimage=_juhe_image(current),
                sourcecountry="cn",
                attention=_record_attention(current),
            )
        )
    return items


def _juhe_finance_fetch_articles(
    *,
    api_key: str,
    base_url: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    num = max(1, min(50, int(max_records)))
    data = _juhe_request_json(
        url=f"{base_url.rstrip('/')}/query",
        params={"key": api_key, "num": str(num), "page": "1"},
        timeout_s=timeout_s,
    )
    _juhe_ensure_success(data, context="finance")
    records = _juhe_records_from_data(data)[:num]

    items: list[NewsItem] = []
    for record in records:
        title = _juhe_first_text(record, ("title", "news_title"))
        url_item = _juhe_first_text(record, ("url", "link", "news_url", "share_url"))
        if not title or not url_item:
            continue
        domain = urllib.parse.urlparse(url_item).netloc or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=_juhe_first_text(record, ("source", "source_name", "author_name", "media_name")) or None,
                description=_juhe_first_text(record, ("description", "desc", "digest", "summary", "abstract")) or None,
                content=_juhe_first_text(record, ("content", "body", "text")) or None,
                domain=domain,
                seendate=_juhe_first_text(record, ("ctime", "date", "time", "publish_time", "pubDate")) or None,
                language="zh",
                socialimage=_juhe_image(record),
                sourcecountry="cn",
                attention=_record_attention(record),
            )
        )
    return items


def _juhe_fetch_articles(
    *,
    news_key: Optional[str],
    finance_key: Optional[str],
    news_base_url: str,
    finance_base_url: str,
    query: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    if _juhe_query_is_finance(query) and finance_key:
        return _juhe_finance_fetch_articles(
            api_key=finance_key,
            base_url=finance_base_url,
            max_records=max_records,
            timeout_s=timeout_s,
        )
    if news_key:
        return _juhe_toutiao_fetch_articles(
            api_key=news_key,
            base_url=news_base_url,
            query=query,
            max_records=max_records,
            timeout_s=timeout_s,
        )
    if finance_key:
        return _juhe_finance_fetch_articles(
            api_key=finance_key,
            base_url=finance_base_url,
            max_records=max_records,
            timeout_s=timeout_s,
        )
    raise RuntimeError("Juhe appkey missing")


def _hotnews_base_url() -> str:
    return (os.getenv("HOTNEWS_BASE_URL") or HOTNEWS_BASE_URL).strip().rstrip("/")


def _hotnews_platforms(value: Optional[str] = None) -> list[str]:
    raw = os.getenv("HOTNEWS_PLATFORMS") if value is None else value
    platforms = _split_news_queries(raw)
    if not platforms:
        platforms = list(HOTNEWS_DEFAULT_PLATFORMS)
    deduped: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        key = platform.strip().lower()
        if not key or key in seen:
            continue
        deduped.append(key)
        seen.add(key)
    return deduped


def _hotnews_request_json(
    *,
    base_url: str,
    platform: str,
    timeout_s: float,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}?{urllib.parse.urlencode({'platform': platform})}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HotNews HTTP error {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = _juhe_text(getattr(exc, "reason", "") or "network error")
        raise RuntimeError(f"HotNews request failed: {reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("HotNews request timed out") from exc
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("HotNews response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("HotNews response is not an object")
    status = data.get("status")
    if str(status) not in ("", "200") and status is not None:
        reason = _juhe_text(data.get("msg") or data.get("message") or "unknown")
        raise RuntimeError(f"HotNews error: status={status}, reason={reason}")
    return data


def _hotnews_records_from_data(data: dict[str, Any]) -> list[Any]:
    records = data.get("data")
    if isinstance(records, dict):
        records = records.get("items") or records.get("list") or records.get("news") or []
    if not isinstance(records, list):
        return []
    return records


def _hotnews_fetch_articles(
    *,
    base_url: str,
    platforms: list[str],
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    limit = max(1, int(max_records))
    items: list[NewsItem] = []
    seen: set[str] = set()
    platform_errors: list[str] = []
    for platform in platforms:
        try:
            data = _hotnews_request_json(
                base_url=base_url,
                platform=platform,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            platform_errors.append(f"{platform}: {exc}")
            continue
        for record in _hotnews_records_from_data(data):
            if not isinstance(record, dict):
                continue
            title = _juhe_first_text(record, ("title", "name"))
            url_item = _juhe_first_text(record, ("url", "link", "mobile_url", "share_url"))
            if not title or not url_item:
                continue
            key = url_item or f"{platform}:{title}"
            if key in seen:
                continue
            seen.add(key)
            domain = urllib.parse.urlparse(url_item).netloc.strip().lower() or None
            description = _juhe_first_text(
                record,
                ("desc", "description", "summary", "abstract", "digest", "content"),
            ) or None
            seendate = _juhe_first_text(
                record,
                ("published_at", "publishedAt", "pubDate", "date", "time", "created_at"),
            ) or None
            items.append(
                NewsItem(
                    title=title,
                    url=url_item,
                    source=f"hotnews:{platform}",
                    description=description,
                    content=description,
                    domain=domain,
                    seendate=seendate,
                    language="en" if platform == "hackernews" else "zh",
                    socialimage=_juhe_first_text(record, ("image", "cover", "pic", "picUrl")) or None,
                    sourcecountry="cn" if platform in HOTNEWS_CHINA_PLATFORMS else None,
                    attention=_record_attention(record),
                )
            )
            if len(items) >= limit:
                return items
    if not items and platform_errors:
        raise RuntimeError("; ".join(platform_errors[-3:]))
    return items


def _file_fetch_articles(*, path: str, max_records: int) -> list[NewsItem]:
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        records = data.get("items") or data.get("candidates") or data.get("news") or []
    else:
        records = data
    if not isinstance(records, list):
        raise RuntimeError("NEWS_CANDIDATES_FILE must contain a JSON list or an object with items/candidates/news")

    items: list[NewsItem] = []
    for rec in records[:max_records]:
        if not isinstance(rec, dict):
            continue
        title = (rec.get("title") or "").strip()
        url = (rec.get("url") or rec.get("link") or "").strip()
        if not title or not url:
            continue
        domain = (rec.get("domain") or "").strip()
        if not domain:
            try:
                domain = urllib.parse.urlparse(url).netloc.strip().lower()
            except Exception:
                domain = ""
        items.append(
            NewsItem(
                title=title,
                url=url,
                source=(rec.get("source") or rec.get("source_name") or "").strip() or None,
                description=(rec.get("description") or rec.get("summary") or "").strip() or None,
                content=(rec.get("content") or "").strip() or None,
                domain=domain or None,
                seendate=(rec.get("seendate") or rec.get("published_at") or rec.get("publishedAt") or "").strip() or None,
                language=(rec.get("language") or "").strip() or None,
                socialimage=(rec.get("socialimage") or rec.get("image") or "").strip() or None,
                sourcecountry=(rec.get("sourcecountry") or rec.get("country") or "").strip() or None,
                attention=_record_attention(rec),
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
    if provider_env == "auto":
        provider_env = ""
    tz_name = (tz_name or os.getenv("NEWS_TZ") or DEFAULT_TZ).strip()
    max_records = int(os.getenv("NEWS_MAX_RECORDS") or (max_records or DEFAULT_MAX_RECORDS))
    timeout_s = float(os.getenv("NEWS_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))

    startdatetime, enddatetime = _today_range_utc(tz_name)
    start_dt = datetime.strptime(startdatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(enddatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    from_iso = start_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    to_iso = end_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    provider_plan: list[str]
    if provider_env:
        provider_plan = [provider_env]
    else:
        file_path = (os.getenv("NEWS_CANDIDATES_FILE") or "").strip()
        if file_path:
            provider_plan = ["file"]
        else:
            # Auto: prefer keyed APIs when configured. Do not fall back to
            # GDELT-like snippet sources; hot_news is kept as the final hot-list fallback.
            provider_plan = []
            try:
                _load_newsapi_config()
                provider_plan.append("newsapi")
            except Exception:
                pass
            try:
                _load_gnews_config()
                provider_plan.append("gnews")
            except Exception:
                pass
            try:
                _load_juhe_config()
                provider_plan.append("juhe")
            except Exception:
                pass
            provider_plan.append("hotnews")
    provider_plan = list(dict.fromkeys(provider_plan))

    supported_providers = ("newsapi", "gnews", "juhe", "hotnews", "file")
    unsupported = [p for p in provider_plan if p not in supported_providers]
    if unsupported:
        raise RuntimeError(
            f"unsupported NEWS_PROVIDER={unsupported[0]!r}; supported: {', '.join(supported_providers)}"
        )
    if not provider_plan:
        raise RuntimeError(
            "no news provider configured; set NEWS_PROVIDER=file with NEWS_CANDIDATES_FILE, "
            "configure NEWS_API_KEY / GNEWS_API_KEY / JUHE_NEWS_APPKEY, or use NEWS_PROVIDER=hotnews"
        )

    hint_query = (prompt_hint or "").strip()
    hint_en = _maybe_translate_hint_to_en(hint_query) if hint_query else ""
    if hint_query:
        default_queries = _split_news_queries(os.getenv("NEWS_QUERY_DEFAULT")) or [DEFAULT_QUERY]
        queries = [q for q in (hint_query, hint_en, *default_queries) if q]
    else:
        queries = _default_news_queries()
    aggregate_empty_prompt = not bool(hint_query)
    history_dedupe_is_enabled = news_history_dedupe_enabled()
    used_news_url_keys = collect_used_news_url_keys() if history_dedupe_is_enabled else set()
    history_skipped: list[dict[str, str]] = []

    last_err: Optional[str] = None
    provider_errors: list[str] = []
    chosen_query = queries[0] if queries else DEFAULT_QUERY
    chosen_provider = provider_plan[0]
    chosen_source_api: dict[str, Any] = {"provider": chosen_provider}
    candidates: list[NewsItem] = []
    queries_used: list[str] = []
    used_time_range = False
    provider_attempts: list[str] = []
    for provider in provider_plan:
        if provider not in provider_attempts:
            provider_attempts.append(provider)
        provider_candidates: list[NewsItem] = []
        provider_queries = queries[:1] if provider in ("file", "hotnews") else queries
        for q in provider_queries:
            chosen_provider = provider
            chosen_query = q
            try:
                if provider == "newsapi":
                    api_key, base_url = _load_newsapi_config()
                    chosen_source_api = {"provider": "newsapi", "base_url": base_url}
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
                    if hint_query and q not in default_queries and _best_relevance(candidates, q) <= 0.0:
                        candidates = []
                elif provider == "gnews":
                    api_key, base_url = _load_gnews_config()
                    chosen_source_api = {"provider": "gnews", "base_url": base_url}
                    raw = _gnews_fetch_articles(
                        api_key=api_key,
                        base_url=base_url,
                        query=q,
                        from_iso=from_iso,
                        to_iso=to_iso,
                        max_records=max_records,
                        timeout_s=timeout_s,
                    )
                    if not raw:
                        raw = _gnews_fetch_articles(
                            api_key=api_key,
                            base_url=base_url,
                            query=q,
                            from_iso=None,
                            to_iso=None,
                            max_records=max_records,
                            timeout_s=timeout_s,
                        )
                    in_today = []
                    for item in raw:
                        seen = _parse_seendate_utc(item.seendate)
                        if seen and start_dt <= seen <= end_dt:
                            in_today.append(item)
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                    if hint_query and q not in default_queries and _best_relevance(candidates, q) <= 0.0:
                        candidates = []
                elif provider == "juhe":
                    cfg = _load_juhe_config()
                    chosen_source_api = {
                        "provider": "juhe",
                        "news_base_url": cfg.news_base_url,
                        "finance_base_url": cfg.finance_base_url,
                    }
                    raw = _juhe_fetch_articles(
                        news_key=cfg.news_key,
                        finance_key=cfg.finance_key,
                        news_base_url=cfg.news_base_url,
                        finance_base_url=cfg.finance_base_url,
                        query=q,
                        max_records=max_records,
                        timeout_s=timeout_s,
                    )
                    in_today = []
                    for item in raw:
                        seen = _parse_seendate_utc(item.seendate)
                        if seen and start_dt <= seen <= end_dt:
                            in_today.append(item)
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                elif provider == "hotnews":
                    base_url = _hotnews_base_url()
                    platforms = _hotnews_platforms()
                    chosen_source_api = {
                        "provider": "hotnews",
                        "base_url": base_url,
                        "platforms": platforms,
                    }
                    candidates = _hotnews_fetch_articles(
                        base_url=base_url,
                        platforms=platforms,
                        max_records=max_records,
                        timeout_s=timeout_s,
                    )
                    used_time_range = False
                else:
                    file_path = (os.getenv("NEWS_CANDIDATES_FILE") or "").strip()
                    if not file_path:
                        raise RuntimeError("NEWS_CANDIDATES_FILE is required when NEWS_PROVIDER=file")
                    chosen_source_api = {"provider": "file", "file_path": file_path}
                    candidates = _file_fetch_articles(
                        path=file_path,
                        max_records=max_records,
                    )
                    used_time_range = False
                if candidates:
                    candidates = _dedupe_candidates(candidates)
                    candidates, skipped_used = filter_used_news_items(candidates, used_news_url_keys)
                    if skipped_used:
                        history_skipped.extend(skipped_used)
                        if not candidates:
                            last_err = "all candidates filtered by history URL dedupe"
                    if not candidates:
                        continue
                    if aggregate_empty_prompt:
                        provider_candidates.extend(candidates)
                        queries_used.append(q)
                        provider_candidates = _dedupe_candidates(provider_candidates)
                        if len(provider_candidates) >= max_records:
                            break
                        candidates = []
                        continue
                    break
            except Exception as exc:
                last_err = f"{provider}/{q}: {exc}"
                provider_errors.append(last_err)
                candidates = []
        if aggregate_empty_prompt and provider_candidates:
            candidates = _dedupe_candidates(provider_candidates)[:max_records]
            chosen_query = ",".join(queries_used) if queries_used else chosen_query
        if candidates:
            break

    if not candidates:
        raise RuntimeError(
            f"no news returned (providers={','.join(provider_attempts)}, query={chosen_query}, err={last_err})"
        )
    chosen_source_api = {
        **chosen_source_api,
        "provider": chosen_provider,
        "query": chosen_query,
        "provider_plan": provider_plan,
        "provider_attempts": provider_attempts,
    }

    meta: dict[str, Any] = {
        "provider": chosen_provider,
        "api_source": chosen_provider,
        "source_api": chosen_source_api,
        "provider_plan": provider_plan,
        "provider_attempts": provider_attempts,
        "provider_errors": provider_errors[-10:],
        "tz": tz_name,
        "query": chosen_query,
        "query_variants": queries,
        "queries_used": queries_used or ([chosen_query] if candidates else []),
        "startdatetime": startdatetime,
        "enddatetime": enddatetime,
        "used_today_range": used_time_range,
        "history_dedupe": {
            "enabled": history_dedupe_is_enabled,
            "used_count": len(used_news_url_keys),
            "skipped_count": len(history_skipped),
            "skipped": history_skipped[:10],
        },
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
