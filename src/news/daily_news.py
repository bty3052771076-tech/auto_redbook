from __future__ import annotations

import json
import os
import random
import re
import math
import time
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .history import collect_used_news_url_keys, filter_used_news_items, news_history_dedupe_enabled
from src.sources.health import (
    SourceAttempt,
    SourceHealthSnapshot,
    is_source_in_cooldown,
    load_source_health_snapshot,
    save_source_health_snapshot,
)

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
DEFAULT_SOURCE_DOMAIN_MAX_RATIO = 0.3
DEFAULT_PROVIDER_CANDIDATE_MAX_RATIO = 0.35
DEFAULT_COLLECTION_DOMAIN_MAX_RATIO = 0.2
# Automatic collection intentionally visits multiple sources. Keep each source
# bounded so a slow fallback cannot make the whole candidate-pool stage look
# stalled in the CLI or GUI.
DEFAULT_EXHAUSTIVE_PROVIDER_QUERY_LIMIT = 2
DEFAULT_EXHAUSTIVE_PROVIDER_TIMEOUT_S = 14.0
DEFAULT_EXHAUSTIVE_RSS_TIMEOUT_S = 8.0
DEFAULT_EXHAUSTIVE_OFFICIAL_RSS_DOMAIN_LIMIT = 2
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
    re.compile(r"^\s*[A-Z]{1,8}\|[^|]{2,80}\|price:\s*\d", re.IGNORECASE),
    re.compile(
        r"^\s*(?:(?:it|\u79d1\u6280|\u8d22\u7ecf|\u65b0\u95fb|\u5e02\u573a)\s*)?"
        r"(?:\u65e9\u62a5|\u665a\u62a5|\u65e5\u62a5|\u6668\u62a5|\u5348\u62a5|\u5feb\u8baf|\u8981\u95fb)"
        r"(?:\s*\d{2,8})?\s*[:\uff1a].*[;\uff1b]",
        re.IGNORECASE,
    ),
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
NEWSDATA_BASE_URL = "https://newsdata.io/api/1/latest"
ALPHAVANTAGE_BASE_URL = "https://www.alphavantage.co/query"
THENEWSAPI_BASE_URL = "https://api.thenewsapi.com/v1/news/top"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
HOTNEWS_BASE_URL = "https://orz.ai/api/v1/dailynews"
GOOGLE_NEWS_RSS_BASE_URL = "https://news.google.com/rss/search"
BBC_RSS_FEEDS = {
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "sport": "https://feeds.bbci.co.uk/sport/rss.xml",
}

# Public Chinese mainland newsrooms. These are used as Google News RSS
# domain filters, so the workflow only reads publicly exposed headlines and
# links and does not bypass access controls.
CN_OFFICIAL_NEWS_DOMAINS = (
    "xinhuanet.com",
    "people.com.cn",
    "cctv.com",
    "gov.cn",
    "chinanews.com.cn",
)


def _positive_env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return default


def _positive_env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if raw:
        try:
            return max(0.5, float(raw))
        except ValueError:
            pass
    return default


def _provider_request_timeout_s(
    provider: str,
    *,
    requested_timeout_s: float,
    exhaustive_sources: bool,
) -> float:
    if not exhaustive_sources:
        return requested_timeout_s
    is_rss_like = provider in {"google_rss", "google_rss_cn", "bbc_rss", "hotnews"}
    env_name = "NEWS_EXHAUSTIVE_RSS_TIMEOUT_S" if is_rss_like else "NEWS_EXHAUSTIVE_PROVIDER_TIMEOUT_S"
    default = DEFAULT_EXHAUSTIVE_RSS_TIMEOUT_S if is_rss_like else DEFAULT_EXHAUSTIVE_PROVIDER_TIMEOUT_S
    return min(requested_timeout_s, _positive_env_float(env_name, default))


def _news_health_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _news_source_error_status(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"
    if isinstance(exc, urllib.error.URLError) or "connection" in text or "network" in text:
        return "transport_error"
    return "error"


def _news_provider_health_url(provider: str) -> str:
    if provider == "newsapi":
        return NEWSAPI_BASE_URL
    if provider == "gnews":
        return GNEWS_BASE_URL
    if provider == "juhe":
        return JUHE_NEWS_BASE_URL
    if provider == "newsdata":
        return NEWSDATA_BASE_URL
    if provider == "alphavantage":
        return ALPHAVANTAGE_BASE_URL
    if provider == "thenewsapi":
        return THENEWSAPI_BASE_URL
    if provider == "finnhub":
        return FINNHUB_BASE_URL
    if provider == "google_rss":
        return _google_news_rss_base_url()
    if provider == "google_rss_cn":
        return _google_news_rss_base_url()
    if provider == "bbc_rss":
        return "https://feeds.bbci.co.uk/"
    if provider == "hotnews":
        return _hotnews_base_url()
    return ""


def _news_provider_health_tier(provider: str) -> str:
    if provider in {
        "newsapi",
        "gnews",
        "juhe",
        "newsdata",
        "alphavantage",
        "thenewsapi",
        "finnhub",
    }:
        return "keyed_api"
    if provider in {"google_rss", "google_rss_cn", "bbc_rss"}:
        return "dated_rss"
    if provider == "hotnews":
        return "heat_backfill"
    return "manual"


def _news_provider_result_status(*, item_count: int, dated_count: int) -> str:
    if item_count <= 0:
        return "empty"
    if dated_count <= 0:
        return "missing_date"
    return "success"
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
_CJK_STORY_EVENT_TOKENS = frozenset(
    "\u5904\u7f5a \u7f5a\u6b3e \u5784\u65ad \u6536\u8d2d \u878d\u8d44 \u53d1\u5e03 \u8d77\u8bc9 \u8c03\u67e5 \u88c1\u5458 \u7834\u4ea7 \u4e0a\u5e02 \u7b7e\u7ea6 \u6da8\u4ef7 \u964d\u4ef7 \u53ec\u56de \u505c\u706b \u5236\u88c1 \u5173\u7a0e \u9884\u8b66 \u53f0\u98ce \u5730\u9707 \u706b\u707e \u4e8b\u6545".split()
)
_CJK_STORY_EVENT_FAMILIES = {
    "\u4e0a\u5e02": ("\u4e0a\u5e02", "\u767b\u9646", "\u6302\u724c", "\u9996\u65e5"),
}
_CJK_STORY_GENERIC_TOKENS = frozenset(
    "\u65b0\u95fb \u539f\u6587 \u6458\u5f55 \u4e0b\u8f7d \u5ba2\u6237\u7aef \u4e2d\u56fd \u56fd\u5bb6 \u7ecf\u6d4e \u5e02\u573a \u5e73\u53f0 \u884c\u4e1a \u4f01\u4e1a \u516c\u53f8 \u96c6\u56e2 \u7528\u6237 \u76d1\u7ba1 \u6267\u6cd5 \u53d1\u5c55 \u670d\u52a1 \u7ecf\u8425 \u7ade\u4e89 \u884c\u4e3a \u4fe1\u606f \u76f8\u5173 \u5f71\u54cd \u5065\u5eb7 \u89c4\u8303 \u7ef4\u62a4 \u63a8\u52a8 \u4f9d\u6cd5 \u6280\u672f \u6570\u636e \u6d41\u91cf \u5408\u4f5c \u4ef7\u683c".split()
)
_CJK_STORY_ENTITY_SUFFIXES = (
    "\u96c6\u56e2",
    "\u516c\u53f8",
    "\u6cd5\u9662",
    "\u603b\u5c40",
    "\u59d4\u5458\u4f1a",
    "\u94f6\u884c",
    "\u57fa\u91d1",
    "\u5927\u5b66",
    "\u533b\u9662",
    "\u79d1\u6280",
)
_CJK_STORY_GENERIC_ENTITIES = frozenset(
    "\u4eba\u6c11\u6cd5\u9662 \u5e02\u573a\u76d1\u7ba1\u603b\u5c40 \u76d1\u7ba1\u603b\u5c40".split()
)
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
    provider: Optional[str] = None


@dataclass(frozen=True)
class JuheConfig:
    news_key: Optional[str]
    finance_key: Optional[str]
    news_base_url: str
    finance_base_url: str


@dataclass(frozen=True)
class AdditionalNewsSourcesConfig:
    newsdata_api_key: Optional[str]
    alphavantage_api_key: Optional[str]
    thenewsapi_token: Optional[str]
    finnhub_api_key: Optional[str]


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


def _recent_range_utc(tz_name: str, *, days: int = 1) -> tuple[str, str]:
    tz = _resolve_tz(tz_name)
    now_local = datetime.now(tz)
    age_days = max(1, int(days or 1))
    start_day = now_local.date() - timedelta(days=age_days - 1)
    start_local = datetime.combine(start_day, datetime.min.time(), tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)
    fmt = "%Y%m%d%H%M%S"
    return start_utc.strftime(fmt), end_utc.strftime(fmt)


def _today_range_utc(tz_name: str) -> tuple[str, str]:
    return _recent_range_utc(tz_name, days=1)


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


def _cjk_story_event_signature(item: NewsItem) -> tuple[set[str], set[str]]:
    """Return shared-event and specific-subject signals from Chinese news context."""
    text = " ".join(
        part
        for part in (
            item.title,
            item.description,
        )
        if part
    )
    tokens = _tokens(text)
    events = tokens & _CJK_STORY_EVENT_TOKENS
    for canonical_event, markers in _CJK_STORY_EVENT_FAMILIES.items():
        if any(marker in text for marker in markers):
            events.add(canonical_event)
    subjects = {
        token
        for token in tokens
        if 3 <= len(token) <= 12
        and _CJK_RE.fullmatch(token)
        and token not in _CJK_STORY_EVENT_TOKENS
        and token not in _CJK_STORY_GENERIC_TOKENS
    }
    for part in _TOKEN_RE.findall(text):
        if not _CJK_RE.fullmatch(part):
            continue
        for suffix in _CJK_STORY_ENTITY_SUFFIXES:
            start = 0
            while True:
                pos = part.find(suffix, start)
                if pos < 0:
                    break
                if pos >= 2:
                    for prefix_len in (2, 3, 4):
                        if pos < prefix_len:
                            continue
                        entity = part[pos - prefix_len : pos + len(suffix)]
                        if entity not in _CJK_STORY_GENERIC_ENTITIES:
                            subjects.add(entity)
                start = pos + len(suffix)
    return events, subjects


def _same_cjk_story_event(
    left: tuple[set[str], set[str]], right: tuple[set[str], set[str]]
) -> bool:
    left_events, left_subjects = left
    right_events, right_subjects = right
    return bool(left_events & right_events) and bool(left_subjects & right_subjects)


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
    # Several established mainland sources use .com (or a Taiwan domain)
    # and do not expose sourcecountry in their RSS metadata.
    domestic_domains = {
        *CN_OFFICIAL_NEWS_DOMAINS,
        "36kr.com",
        "ithome.com",
    }
    if domain in domestic_domains or any(domain.endswith("." + suffix) for suffix in domestic_domains):
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


def _limit_single_domain(
    items: list[NewsItem],
    *,
    count: int,
    cap_count: Optional[int] = None,
) -> list[NewsItem]:
    if count <= 1 or not items:
        return items[:count] if count > 0 else []
    domains = [_canonical_domain(_domain_for_item(item)) for item in items]
    available_domains = {domain for domain in domains if domain}
    if len(available_domains) <= 1:
        return items[:count]
    cap_base = count if cap_count is None else max(1, int(cap_count))
    cap = max(1, int(math.ceil(cap_base * _source_domain_max_ratio())))
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


def _required_china_count_for_daily_news(count: int) -> int:
    if count > 5:
        return 2
    if count > 2:
        return 1
    return 0


def _balance_china_foreign(items: list[NewsItem], *, count: int) -> list[NewsItem]:
    """
    Keep a rough China:foreign ratio (default 6:4) while preserving relevance order.
    Multi-draft batches also enforce a minimum China-news quota:
    count > 2 => 1 item, count > 5 => 2 items.
    If one side is insufficient, fill from the other side.
    """
    if count <= 0 or not items:
        return []
    if count == 1:
        return items[:1]

    ratio = _china_ratio()
    desired_china = max(
        _required_china_count_for_daily_news(count),
        int(round(count * ratio)),
    )
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
    by overlapping ASCII "entity-ish" tokens (names/abbreviations/numbers), plus Chinese
    stories that share both a concrete subject and an event signal in their context.

    This is used when selecting multiple items to publish. We keep fetch-time candidate
    dedupe conservative to preserve cross-domain evidence for scoring.
    """
    picked: list[NewsItem] = []
    picked_title_tokens: list[set[str]] = []
    picked_entity_tokens: list[set[str]] = []
    picked_cjk_signatures: list[tuple[set[str], set[str]]] = []
    for item in items:
        title_tokens = _tokens(item.title)
        entity_tokens = _entity_tokens(f"{item.title} {item.description or ''}")
        cjk_signature = _cjk_story_event_signature(item)
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
        if any(_same_cjk_story_event(cjk_signature, signature) for signature in picked_cjk_signatures):
            continue
        picked.append(item)
        picked_title_tokens.append(title_tokens)
        picked_entity_tokens.append(entity_tokens)
        picked_cjk_signatures.append(cjk_signature)
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


def _balanced_candidate_pool(items: list[NewsItem], *, max_records: int) -> list[NewsItem]:
    """
    Keep an exhaustive automatic fetch fair before ranking.

    A large early provider used to fill the raw cap before later providers were
    merged. Round-robin by provider and conservative domain caps preserve room
    for independent sources while still filling from a strong source when the
    rest of the plan is sparse.
    """
    unique = _dedupe_candidates(items)
    limit = max(1, int(max_records))
    if len(unique) <= limit:
        return unique

    provider_cap = max(1, int(math.ceil(limit * DEFAULT_PROVIDER_CANDIDATE_MAX_RATIO)))
    domain_cap = max(1, int(math.ceil(limit * DEFAULT_COLLECTION_DOMAIN_MAX_RATIO)))
    buckets: dict[str, list[NewsItem]] = {}
    for item in unique:
        provider = (item.provider or "unknown").strip().lower() or "unknown"
        buckets.setdefault(provider, []).append(item)

    selected: list[NewsItem] = []
    overflow: list[NewsItem] = []
    provider_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    positions = {provider: 0 for provider in buckets}

    # First pass: each provider receives turns; keep any one publisher from
    # occupying the raw pool by itself.
    while len(selected) < limit:
        progressed = False
        for provider, bucket in buckets.items():
            pos = positions[provider]
            if pos >= len(bucket):
                continue
            item = bucket[pos]
            positions[provider] = pos + 1
            progressed = True
            domain = _canonical_domain(_domain_for_item(item)) or f"unknown:{provider}"
            if provider_counts.get(provider, 0) >= provider_cap or domain_counts.get(domain, 0) >= domain_cap:
                overflow.append(item)
                continue
            selected.append(item)
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if len(selected) >= limit:
                break
        if not progressed:
            break

    # If several providers are thin, relax the provider cap but still protect
    # the domain cap. This lets a later provider with many independent
    # publishers fill the pool before an early single-domain source does.
    if len(selected) < limit:
        selected_urls = {item.url or item.title for item in selected}
        for item in unique:
            key = item.url or item.title
            if key in selected_urls:
                continue
            provider = (item.provider or "unknown").strip().lower() or "unknown"
            domain = _canonical_domain(_domain_for_item(item)) or f"unknown:{provider}"
            if domain_counts.get(domain, 0) >= domain_cap:
                continue
            selected.append(item)
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            selected_urls.add(key)
            if len(selected) >= limit:
                break

    # Availability wins over artificial scarcity if the configured sources do
    # not provide enough distinct records.
    if len(selected) < limit:
        selected_urls = {item.url or item.title for item in selected}
        for item in unique:
            key = item.url or item.title
            if key in selected_urls:
                continue
            selected.append(item)
            selected_urls.add(key)
            if len(selected) >= limit:
                break
    return selected[:limit]


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


def _normalize_manual_material_time(value: str, *, tz_name: str = DEFAULT_TZ) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    tz = _resolve_tz(tz_name)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=tz).isoformat()
        except ValueError:
            continue
    parsed = _parse_seendate_utc(raw)
    if parsed is None:
        return ""
    return parsed.astimezone(tz).isoformat()


def resolve_manual_material_times(
    items: list[NewsItem],
    *,
    default_material_time: str = "",
    tz_name: str | None = None,
) -> tuple[list[NewsItem], list[str]]:
    """Resolve user-supplied material times without applying a recency window."""
    resolved_default = _normalize_manual_material_time(
        default_material_time,
        tz_name=tz_name or os.getenv("NEWS_TZ") or DEFAULT_TZ,
    )
    if str(default_material_time or "").strip() and not resolved_default:
        raise RuntimeError(
            f"材料时间无法解析：默认材料时间为 {str(default_material_time).strip()!r}，"
            "支持 YYYY-MM-DD 或 YYYY-MM-DD HH:MM。"
        )
    resolved_items: list[NewsItem] = []
    resolved_times: list[str] = []
    for index, item in enumerate(items, start=1):
        raw_time = str(item.seendate or "").strip() or str(default_material_time or "").strip()
        if not raw_time:
            raise RuntimeError(f"材料时间缺失：第{index}条材料没有时间，请填写记录时间或默认材料时间。")
        normalized = _normalize_manual_material_time(
            raw_time,
            tz_name=tz_name or os.getenv("NEWS_TZ") or DEFAULT_TZ,
        )
        if not normalized:
            raise RuntimeError(
                f"材料时间无法解析：第{index}条材料的时间为 {raw_time!r}，"
                "支持 YYYY-MM-DD 或 YYYY-MM-DD HH:MM。"
            )
        resolved_items.append(replace(item, seendate=normalized))
        resolved_times.append(normalized)
    return resolved_items, resolved_times


def _recent_news_day_window(
    *,
    tz_name: Optional[str] = None,
    max_age_days: int = 3,
    now: Optional[datetime] = None,
):
    tz = _resolve_tz(tz_name or DEFAULT_TZ)
    if now is None:
        now_local = datetime.now(tz)
    elif now.tzinfo is None:
        now_local = now.replace(tzinfo=tz)
    else:
        now_local = now.astimezone(tz)
    age_days = max(1, int(max_age_days or 3))
    end_day = now_local.date()
    start_day = end_day - timedelta(days=age_days - 1)
    return start_day, end_day, tz


def filter_recent_news_items(
    items: list[NewsItem],
    *,
    tz_name: Optional[str] = None,
    max_age_days: int = 3,
    now: Optional[datetime] = None,
) -> tuple[list[NewsItem], dict[str, Any]]:
    """
    Keep only items published within the Beijing-calendar freshness window.

    The caller controls the number of Beijing calendar days. Items with missing
    or unparseable dates are excluded because they cannot prove freshness.
    """
    start_day, end_day, tz = _recent_news_day_window(
        tz_name=tz_name,
        max_age_days=max_age_days,
        now=now,
    )
    kept: list[NewsItem] = []
    missing_or_unparseable = 0
    outside_window = 0
    for item in items:
        published = _parse_seendate_utc(item.seendate)
        if published is None:
            missing_or_unparseable += 1
            continue
        local_day = published.astimezone(tz).date()
        if start_day <= local_day <= end_day:
            kept.append(item)
        else:
            outside_window += 1

    meta = {
        "tz": tz_name or DEFAULT_TZ,
        "max_age_days": max(1, int(max_age_days or 3)),
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
        "input_count": len(items),
        "kept_count": len(kept),
        "missing_or_unparseable_date_count": missing_or_unparseable,
        "outside_window_count": outside_window,
    }
    return kept, meta


def _relevance_score(item: NewsItem, prompt_hint: str) -> float:
    hint = (prompt_hint or "").strip()
    if not hint:
        return 0.0
    hint_lc = hint.lower()
    hint_tokens = _tokens(hint_lc)
    if not hint_tokens:
        return 0.0

    title_text = item.title or ""
    description_text = item.description or ""
    content_text = item.content or ""
    source_text = f"{item.source or ''} {item.domain or ''}"
    visible_text = f"{title_text} {description_text} {source_text}".lower()

    title_tokens = _tokens(title_text)
    description_tokens = _tokens(description_text)
    content_tokens = _tokens(content_text[:1200])
    source_tokens = _tokens(source_text)
    title_hit = len(hint_tokens & title_tokens)
    description_hit = len(hint_tokens & description_tokens)
    content_hit = len(hint_tokens & content_tokens)
    source_hit = len(hint_tokens & source_tokens)

    # Normalize by hint size and heavily weight title/summary matches.
    denom = max(1, len(hint_tokens))
    score = (
        3.0 * title_hit
        + 1.5 * description_hit
        + 0.4 * content_hit
        + 0.5 * source_hit
    ) / denom

    if hint_lc in visible_text:
        score += 1.0
    elif hint_lc in (content_text or "").lower():
        score += 0.4

    combined_text = f"{title_text} {description_text} {content_text}"
    combined_lc = combined_text.lower()
    if "政策" in hint and re.search(
        r"(政策|新规|规定|法规|条例|监管|措施|施行|调整|policy|policies|regulation|regulatory|rule|law|legislation|measure)",
        combined_lc,
    ):
        score += 0.6
    if "公司" in hint and re.search(
        r"(公司|企业|平台|上市|融资|并购|管理层|company|companies|corporate|business|platform)",
        combined_lc,
    ):
        score += 0.4
    if "市场" in hint and re.search(
        r"(市场|價格|价格|股价|行業|行业|需求|供给|銷售|销售|消费|market|markets|price|prices|stock|demand|supply|sales|consumer)",
        combined_lc,
    ):
        score += 0.4
    if re.search(r"(科技|技术|人工智能|AI|ai)", hint) and re.search(
        r"(科技|技术|人工智能|芯片|算力|模型|软件|半导体|ai|tech|technology|chip|accelerator|inference|software|semiconductor|model)",
        combined_lc,
    ):
        score += 0.8
    if re.search(r"(产业|行业|公司|企业)", hint) and re.search(
        r"(产业|產業|行业|行業|公司|企业|企業|平台|服务|服務|company|industry|business|market|sector)",
        combined_lc,
    ):
        score += 0.6
    if "财经" in hint and re.search(
        r"(财经|经济|市场|金融|股价|价格|投资|融资|economy|finance|market|stock|price|investment|funding)",
        combined_lc,
    ):
        score += 0.6
    if re.search(r"(世界杯|世界盃)", hint) and re.search(
        r"(世界杯|世界盃|world cup|fifa)",
        combined_lc,
    ):
        score += 0.9
    if "足球" in hint and re.search(
        r"(足球|football|soccer|fifa|world cup)",
        combined_lc,
    ):
        score += 0.6
    if "社会" in hint and re.search(
        r"(社会|民生|医疗|教育|交通|劳动|权益|健康|society|public|health|access|fda|review|regulation)",
        combined_lc,
    ):
        score += 0.6
    if "国际" in hint and re.search(
        r"(国际|全球|海外|国家|外交|global|world|international|countries|foreign|us|europe|japan)",
        combined_lc,
    ):
        score += 0.6
    if "体育" in hint and re.search(
        r"(体育|赛事|足球|篮球|世界杯|sports?|world cup|football|basketball|league|match)",
        combined_lc,
    ):
        score += 0.6
    return score


def filter_prompt_relevant_news_items(
    items: list[NewsItem],
    prompt_hint: str,
) -> tuple[list[NewsItem], dict[str, Any]]:
    """Keep only candidates with direct prompt relevance when a prompt is present."""
    hint = (prompt_hint or "").strip()
    if not hint:
        return list(items), {
            "enabled": False,
            "input_count": len(items),
            "kept_count": len(items),
            "dropped_count": 0,
            "min_score": 0.0,
        }

    scored: list[tuple[float, int, NewsItem]] = []
    for idx, item in enumerate(items):
        score = _relevance_score(item, hint)
        if score > 0:
            scored.append((score, -idx, item))
    kept = [item for _, _, item in scored]
    return kept, {
        "enabled": True,
        "input_count": len(items),
        "kept_count": len(kept),
        "dropped_count": len(items) - len(kept),
        "min_score": 0.0,
    }


def rank_news_candidate_pool(
    items: list[NewsItem],
    prompt_hint: str,
) -> list[NewsItem]:
    """Rank a broad candidate pool without applying final publish quotas."""
    if not items:
        return []
    hint = (prompt_hint or "").strip()
    counts = _cross_domain_counts(items)
    scored: list[tuple[float, datetime, int, int, NewsItem]] = []
    seen: set[str] = set()
    china_bonus = _china_bonus()
    for idx, item in enumerate(items):
        key = item.url or item.title
        if key in seen:
            continue
        seen.add(key)
        score = _relevance_score(item, hint) if hint else 0.0
        score += max(0, counts[idx] - 1) * CROSS_DOMAIN_BONUS
        score += _attention_score(item) * 0.2
        if _is_china_item(item):
            score += china_bonus
        seen_at = _parse_seendate_utc(item.seendate) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        scored.append((score, seen_at, counts[idx], -idx, item))
    scored.sort(reverse=True)
    return [item for _, _, _, _, item in scored]


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
    if "中国" in hint or "中國" in hint:
        tokens.append("China")
    if "经济" in hint or "經濟" in hint or "财经" in hint or "財經" in hint:
        tokens.append("economy")
    if "市场" in hint or "市場" in hint:
        tokens.append("market")
    if "政策" in hint:
        tokens.append("policy")
    if "公司" in hint or "企业" in hint or "企業" in hint or "平台" in hint:
        tokens.append("business")
    if "产业" in hint or "產業" in hint or "行业" in hint or "行業" in hint:
        tokens.append("industry")
    if "社会" in hint or "民生" in hint:
        tokens.append("society")
    if "气候" in hint or "氣候" in hint or "环境" in hint or "環境" in hint or "碳达峰" in hint or "碳達峰" in hint:
        tokens.append("climate")
    if "科技" in hint or "AI" in hint.upper() or "人工智能" in hint:
        tokens.append("technology")
    if "世界杯" in hint or "世界盃" in hint:
        tokens.append("world cup")
    if "体育" in hint or "體育" in hint:
        tokens.append("sports")
    if "足球" in hint:
        tokens.append("football")
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
        deduped = _limit_single_domain(
            deduped,
            count=len(deduped),
            cap_count=count,
        )
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
    deduped = _limit_single_domain(
        deduped,
        count=len(deduped),
        cap_count=count,
    )
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


def _load_additional_news_sources_config(
    *,
    key_file: Path | str = Path("docs/news_sources_api-key.md"),
) -> AdditionalNewsSourcesConfig:
    configured_path = (os.getenv("NEWS_SOURCES_CONFIG_FILE") or "").strip()
    file_cfg = _parse_kv_file(Path(configured_path) if configured_path else Path(key_file))

    def first_value(*names: str) -> Optional[str]:
        for name in names:
            value = os.getenv(name) or file_cfg.get(name.lower())
            if value and value.strip():
                return value.strip()
        return None

    return AdditionalNewsSourcesConfig(
        newsdata_api_key=first_value("NEWSDATA_API_KEY", "NEWSDATA_KEY"),
        alphavantage_api_key=first_value(
            "ALPHAVANTAGE_API_KEY",
            "ALPHA_VANTAGE_API_KEY",
        ),
        thenewsapi_token=first_value(
            "THENEWSAPI_TOKEN",
            "THE_NEWS_API_TOKEN",
            "THENEWS_API_TOKEN",
        ),
        finnhub_api_key=first_value("FINNHUB_API_KEY", "FINNHUB_TOKEN"),
    )


def _load_additional_news_source_key(provider: str) -> str:
    config = _load_additional_news_sources_config()
    values = {
        "newsdata": config.newsdata_api_key,
        "alphavantage": config.alphavantage_api_key,
        "thenewsapi": config.thenewsapi_token,
        "finnhub": config.finnhub_api_key,
    }
    value = values.get(provider)
    if value:
        return value
    env_name = {
        "newsdata": "NEWSDATA_API_KEY",
        "alphavantage": "ALPHAVANTAGE_API_KEY",
        "thenewsapi": "THENEWSAPI_TOKEN",
        "finnhub": "FINNHUB_API_KEY",
    }.get(provider, "API_KEY")
    raise RuntimeError(
        f"{provider} api_key missing: set {env_name} or docs/news_sources_api-key.md"
    )


def _split_news_queries(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,，;；、\n|]+", text)
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


def _split_prompt_keyword_queries(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    parts = re.split(r"[,，;；、\n|/\s]+", text)
    queries: list[str] = []
    seen: set[str] = set()
    for part in parts:
        q = part.strip()
        if len(q) < 2:
            continue
        key = q.lower()
        if key in seen:
            continue
        queries.append(q)
        seen.add(key)
    return queries


def _build_prompt_news_queries(prompt_hint: str) -> list[str]:
    hint_query = (prompt_hint or "").strip()
    if not hint_query:
        return _default_news_queries()
    hint_en = _maybe_translate_hint_to_en(hint_query)
    default_queries = _split_news_queries(os.getenv("NEWS_QUERY_DEFAULT")) or [DEFAULT_QUERY]
    out: list[str] = []
    seen: set[str] = set()
    for q in [hint_query, *_split_prompt_keyword_queries(hint_query), hint_en, *default_queries]:
        item = re.sub(r"\s+", " ", (q or "")).strip()
        key = item.lower()
        if not item or key in seen:
            continue
        out.append(item)
        seen.add(key)
    return out


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
    for key in (
        "score",
        "hot",
        "heat",
        "hot_score",
        "rank_score",
        "views",
        "view_count",
        "read_count",
        "热度",
        "关注度",
        "阅读",
        "浏览",
        "观看",
    ):
        if key in record:
            value = _numeric_value(record.get(key))
            if value is not None:
                return value
    return None


def _external_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_external_text(item) for item in value if _external_text(item))
    if isinstance(value, dict):
        for key in ("name", "title", "label", "value"):
            text = _external_text(value.get(key))
            if text:
                return text
        return ""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _external_domain(url: str, fallback: str = "") -> Optional[str]:
    for value in (url, fallback):
        text = (value or "").strip()
        if not text:
            continue
        parsed = urllib.parse.urlparse(text)
        domain = parsed.netloc.strip()
        if not domain and "://" not in text:
            domain = urllib.parse.urlparse(f"https://{text}").netloc.strip()
        if domain:
            return domain
    return None


def _provider_request_json(
    provider: str,
    endpoint: str,
    params: dict[str, str],
    *,
    timeout_s: float,
) -> Any:
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{provider} HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{provider} transport error") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"{provider} timeout") from exc
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{provider} returned invalid JSON") from exc


def _compact_api_datetime(value: Any) -> str:
    text = _external_text(value)
    if not text:
        return ""
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, ValueError):
            return text
    if re.fullmatch(r"\d{8}T\d{6}", text):
        return f"{text}Z"
    return text


def _newsdata_fetch_articles(
    *,
    api_key: str,
    query: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    params = {
        "apikey": api_key,
        "q": query,
        "language": (os.getenv("NEWSDATA_LANGUAGES") or "zh,en").strip(),
        # The current free endpoint accepts at most 10 records per request.
        # A paid account can opt in to a higher limit explicitly.
        "size": str(_newsdata_max_results(max_records)),
    }
    data = _provider_request_json("NewsData", NEWSDATA_BASE_URL, params, timeout_s=timeout_s)
    if not isinstance(data, dict) or str(data.get("status") or "").lower() not in {"success", "ok"}:
        raise RuntimeError("NewsData API returned an unsuccessful response")
    articles = data.get("results") or []
    items: list[NewsItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _external_text(article.get("title"))
        url_item = _external_text(article.get("link"))
        if not title or not url_item:
            continue
        source_url = _external_text(article.get("source_url"))
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=_external_text(article.get("source_name") or article.get("source_id")) or None,
                description=_external_text(article.get("description")) or None,
                content=_external_text(article.get("content")) or None,
                domain=_external_domain(source_url, url_item),
                seendate=_compact_api_datetime(article.get("pubDate") or article.get("pubDateTZ")) or None,
                language=_external_text(article.get("language")) or None,
                socialimage=_external_text(article.get("image_url")) or None,
                sourcecountry=_external_text(article.get("country")) or None,
            )
        )
    return items[:max_records]


def _newsdata_max_results(max_records: int) -> int:
    raw = (os.getenv("NEWSDATA_MAX") or "").strip()
    try:
        configured = int(raw) if raw else 10
    except ValueError:
        configured = 10
    return max(1, min(50, int(max_records), configured))


def _alphavantage_topics_for_query(query: str) -> str:
    text = (query or "").lower()
    topics: list[str] = []
    topic_checks = (
        ("technology", ("technology", "ai", "chip", "tech", "科技", "人工智能", "芯片")),
        ("finance", ("finance", "market", "stock", "财经", "金融", "市场", "股")),
        ("economy_macro", ("economy", "macro", "经济", "宏观")),
        ("economy_fiscal", ("policy", "fiscal", "税", "财政", "政策")),
        ("mergers_and_acquisitions", ("merger", "acquisition", "并购", "收购")),
        ("ipo", ("ipo", "上市")),
        ("energy_transportation", ("energy", "transport", "能源", "汽车", "交通")),
        ("manufacturing", ("manufacturing", "制造", "工业", "产业")),
    )
    for topic, keywords in topic_checks:
        if any(keyword in text for keyword in keywords):
            topics.append(topic)
    return ",".join(dict.fromkeys(topics))


def _alphavantage_fetch_articles(
    *,
    api_key: str,
    query: str,
    from_iso: Optional[str],
    to_iso: Optional[str],
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    params = {
        "function": "NEWS_SENTIMENT",
        "apikey": api_key,
        "sort": "LATEST",
        "limit": str(max(1, min(50, int(max_records)))),
    }
    topics = _alphavantage_topics_for_query(query)
    if topics:
        params["topics"] = topics
    for source, target in ((from_iso, "time_from"), (to_iso, "time_to")):
        parsed = _parse_seendate_utc(source)
        if parsed is not None:
            params[target] = parsed.strftime("%Y%m%dT%H%M")
    data = _provider_request_json("Alpha Vantage", ALPHAVANTAGE_BASE_URL, params, timeout_s=timeout_s)
    if not isinstance(data, dict):
        raise RuntimeError("Alpha Vantage returned an invalid response")
    if any(data.get(key) for key in ("Error Message", "Information", "Note")):
        raise RuntimeError("Alpha Vantage API returned an error response")
    articles = data.get("feed") or []
    items: list[NewsItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _external_text(article.get("title"))
        url_item = _external_text(article.get("url"))
        if not title or not url_item:
            continue
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=_external_text(article.get("source")) or None,
                description=_external_text(article.get("summary")) or None,
                domain=_external_domain(_external_text(article.get("source_domain")), url_item),
                seendate=_compact_api_datetime(article.get("time_published")) or None,
                socialimage=_external_text(article.get("banner_image")) or None,
                attention=_numeric_value(article.get("relevance_score")),
            )
        )
    return items[:max_records]


def _thenewsapi_fetch_articles(
    *,
    api_token: str,
    query: str,
    max_records: int,
    timeout_s: float,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> list[NewsItem]:
    params = {
        "api_token": api_token,
        "search": query,
        "limit": str(max(1, min(50, int(max_records)))),
    }
    categories = _thenewsapi_categories_for_query(query)
    if categories:
        params["categories"] = categories
    for source, target in ((from_iso, "published_after"), (to_iso, "published_before")):
        parsed = _parse_seendate_utc(source)
        if parsed is not None:
            params[target] = parsed.strftime("%Y-%m-%dT%H:%M:%S")
    data = _provider_request_json("TheNewsAPI", THENEWSAPI_BASE_URL, params, timeout_s=timeout_s)
    if not isinstance(data, dict):
        raise RuntimeError("TheNewsAPI returned an invalid response")
    if data.get("error") or data.get("errors"):
        raise RuntimeError("TheNewsAPI returned an error response")
    articles = data.get("data") or []
    items: list[NewsItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = _external_text(article.get("title"))
        url_item = _external_text(article.get("url"))
        if not title or not url_item:
            continue
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=_external_text(article.get("source")) or None,
                description=_external_text(article.get("description") or article.get("snippet")) or None,
                domain=_external_domain(url_item),
                seendate=_compact_api_datetime(article.get("published_at")) or None,
                language=_external_text(article.get("language")) or None,
                socialimage=_external_text(article.get("image_url")) or None,
                attention=_numeric_value(article.get("relevance_score")),
            )
        )
    return items[:max_records]


def _thenewsapi_categories_for_query(query: str) -> str:
    text = (query or "").lower()
    categories: list[str] = []
    category_checks = (
        ("tech", ("technology", "ai", "chip", "tech", "科技", "人工智能", "芯片")),
        ("business", ("finance", "market", "stock", "财经", "金融", "市场", "公司", "产业")),
        ("politics", ("policy", "politics", "government", "政策", "政治", "监管", "外交")),
        ("science", ("science", "research", "科学", "研究")),
        ("sports", ("sport", "football", "soccer", "体育", "足球")),
        ("entertainment", ("culture", "entertainment", "文化", "娱乐")),
        ("health", ("health", "medical", "健康", "医疗")),
    )
    for category, keywords in category_checks:
        if any(keyword in text for keyword in keywords):
            categories.append(category)
    return ",".join(dict.fromkeys(categories))


def _finnhub_category_for_query(query: str) -> str:
    text = (query or "").lower()
    if any(token in text for token in ("crypto", "加密", "比特币", "bitcoin")):
        return "crypto"
    if any(token in text for token in ("forex", "汇率", "外汇", "currency")):
        return "forex"
    if any(token in text for token in ("merger", "acquisition", "并购", "收购")):
        return "merger"
    return "general"


def _finnhub_fetch_articles(
    *,
    api_key: str,
    query: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    params = {
        "category": _finnhub_category_for_query(query),
        "token": api_key,
    }
    data = _provider_request_json("Finnhub", f"{FINNHUB_BASE_URL}/news", params, timeout_s=timeout_s)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError("Finnhub returned an error response")
    if not isinstance(data, list):
        raise RuntimeError("Finnhub returned an invalid response")
    items: list[NewsItem] = []
    for article in data:
        if not isinstance(article, dict):
            continue
        title = _external_text(article.get("headline"))
        url_item = _external_text(article.get("url"))
        if not title or not url_item:
            continue
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=_external_text(article.get("source")) or None,
                description=_external_text(article.get("summary")) or None,
                domain=_external_domain(url_item),
                seendate=_compact_api_datetime(article.get("datetime")) or None,
                socialimage=_external_text(article.get("image")) or None,
            )
        )
    return items[:max_records]


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
    fetch_detail: Optional[bool] = None,
) -> list[NewsItem]:
    news_type = _juhe_toutiao_type_for_query(query)
    data = _juhe_request_json(
        url=f"{base_url.rstrip('/')}/index",
        params={"key": api_key, "type": news_type},
        timeout_s=timeout_s,
    )
    _juhe_ensure_success(data, context="toutiao")
    records = _juhe_records_from_data(data)[: max(1, max_records)]
    detail_enabled = _juhe_fetch_detail_enabled() if fetch_detail is None else bool(fetch_detail)
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
    fetch_detail: Optional[bool] = None,
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
            fetch_detail=fetch_detail,
        )
    if finance_key:
        return _juhe_finance_fetch_articles(
            api_key=finance_key,
            base_url=finance_base_url,
            max_records=max_records,
            timeout_s=timeout_s,
        )
    raise RuntimeError("Juhe appkey missing")


def _rss_local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].lower()


def _rss_clean_text(value: Optional[str]) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _rss_child(item: ElementTree.Element, name: str) -> Optional[ElementTree.Element]:
    for child in item:
        if _rss_local_name(child.tag) == name:
            return child
    return None


def _rss_child_text(item: ElementTree.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in item:
        if _rss_local_name(child.tag) in wanted:
            text = _rss_clean_text(child.text)
            if text:
                return text
    return ""


def _rss_item_url(item: ElementTree.Element) -> str:
    for child in item:
        if _rss_local_name(child.tag) != "link":
            continue
        href = _rss_clean_text(child.attrib.get("href"))
        if href:
            return href
        text = _rss_clean_text(child.text)
        if text:
            return text
    return _rss_child_text(item, "guid", "id")


def _rss_pubdate_to_iso(value: Optional[str]) -> Optional[str]:
    raw = _rss_clean_text(value)
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _rss_items_from_xml(
    payload: bytes,
    *,
    source_name: str,
    fallback_language: str,
) -> list[NewsItem]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise RuntimeError("RSS response is not valid XML") from exc

    items: list[NewsItem] = []
    for element in root.iter():
        if _rss_local_name(element.tag) not in {"item", "entry"}:
            continue
        title = _rss_child_text(element, "title")
        url_item = _rss_item_url(element)
        if not title or not url_item:
            continue
        description = _rss_child_text(element, "description", "summary", "encoded", "content") or None
        date_text = _rss_child_text(element, "pubdate", "published", "updated", "date")
        source_element = _rss_child(element, "source")
        publisher = _rss_clean_text(source_element.text if source_element is not None else "") or source_name
        publisher_url = _rss_clean_text(source_element.attrib.get("url") if source_element is not None else "")
        domain = urllib.parse.urlparse(publisher_url or url_item).netloc.strip().lower() or None
        items.append(
            NewsItem(
                title=title,
                url=url_item,
                source=publisher,
                description=description,
                content=description,
                domain=domain,
                seendate=_rss_pubdate_to_iso(date_text),
                language=fallback_language,
            )
        )
    return items


def _rss_fetch_articles(
    *,
    feed_url: str,
    source_name: str,
    fallback_language: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    # Google News RSS can rate-limit consecutive keyword queries (observed as
    # intermittent ``[Errno 2] No such file or directory`` / connection resets).
    # Add a small delay before the first attempt plus one retry so a single
    # rate-limited query does not silently starve the candidate pool.
    delay_before = float(os.getenv("NEWS_RSS_REQUEST_DELAY_S") or "0.6")
    time.sleep(max(0.0, delay_before))
    attempts = 2
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(float(os.getenv("NEWS_RSS_RETRY_DELAY_S") or "3.0"))
        request = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "Mozilla/5.0 (redbook_workflow RSS)"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = response.read()
            return _rss_items_from_xml(
                payload,
                source_name=source_name,
                fallback_language=fallback_language,
            )[: max(1, int(max_records))]
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(f"{source_name} RSS HTTP error {exc.code}")
        except urllib.error.URLError as exc:
            reason = _juhe_text(getattr(exc, "reason", "") or "network error")
            last_error = RuntimeError(f"{source_name} RSS request failed: {reason}")
        except TimeoutError as exc:
            last_error = RuntimeError(f"{source_name} RSS request timed out")
    raise last_error if last_error is not None else RuntimeError(f"{source_name} RSS request failed")


def _google_news_rss_base_url() -> str:
    return (os.getenv("GOOGLE_NEWS_RSS_BASE_URL") or GOOGLE_NEWS_RSS_BASE_URL).strip().rstrip("?")


def _google_rss_fetch_articles(
    *,
    query: str,
    max_records: int,
    timeout_s: float,
    language: str | None = None,
    country: str | None = None,
) -> list[NewsItem]:
    language = (language or os.getenv("GOOGLE_NEWS_RSS_HL") or "en-US").strip()
    country = (country or os.getenv("GOOGLE_NEWS_RSS_GL") or "US").strip()
    ceid = (os.getenv("GOOGLE_NEWS_RSS_CEID") or f"{country}:{language.split('-', 1)[0]}").strip()
    params = urllib.parse.urlencode({"q": query, "hl": language, "gl": country, "ceid": ceid})
    feed_url = f"{_google_news_rss_base_url()}?{params}"
    return _rss_fetch_articles(
        feed_url=feed_url,
        source_name="Google News RSS (CN)" if country == "CN" else "Google News RSS",
        fallback_language=language.split("-", 1)[0] or "en",
        max_records=max_records,
        timeout_s=timeout_s,
    )


def _bbc_rss_feed_keys(prompt_hint: str) -> tuple[str, ...]:
    hint = (prompt_hint or "").lower()
    if re.search(r"(世界杯|世界盃|体育|體育|足球|篮球|籃球|sport|football|soccer|basketball|league|match)", hint):
        return ("sport",)
    if re.search(r"(财经|財經|经济|經濟|金融|市场|市場|公司|企业|企業|产业|產業|business|economy|finance|market|stock)", hint):
        return ("business",)
    if re.search(r"(科技|技术|技術|人工智能|ai|芯片|晶片|technology|tech|software|semiconductor)", hint):
        return ("technology",)
    return ("world",)


def _bbc_rss_fetch_articles(
    *,
    prompt_hint: str,
    max_records: int,
    timeout_s: float,
) -> list[NewsItem]:
    labels = {
        "world": "BBC World",
        "business": "BBC Business",
        "technology": "BBC Technology",
        "sport": "BBC Sport",
    }
    items: list[NewsItem] = []
    errors: list[str] = []
    for key in _bbc_rss_feed_keys(prompt_hint):
        try:
            items.extend(
                _rss_fetch_articles(
                    feed_url=BBC_RSS_FEEDS[key],
                    source_name=labels[key],
                    fallback_language="en",
                    max_records=max_records,
                    timeout_s=timeout_s,
                )
            )
        except RuntimeError as exc:
            errors.append(str(exc))
    if not items and errors:
        raise RuntimeError("; ".join(errors))
    return _dedupe_candidates(items)[: max(1, int(max_records))]


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


_MANUAL_NEWS_TITLE_KEYS = ("title", "headline", "新闻", "标题", "新闻标题")
_MANUAL_NEWS_SOURCE_KEYS = ("source", "source_name", "author_name", "media", "来源", "媒体", "出处")
_MANUAL_NEWS_URL_KEYS = ("url", "link", "href", "链接", "原文链接", "网址")
_MANUAL_NEWS_TIME_KEYS = (
    "seendate",
    "published_at",
    "publishedAt",
    "publish_time",
    "date",
    "time",
    "时间",
    "发布时间",
    "发布日期",
    "日期",
)
_MANUAL_NEWS_DESC_KEYS = ("description", "summary", "desc", "abstract", "摘要", "简介", "导语")
_MANUAL_NEWS_CONTENT_KEYS = ("content", "body", "text", "正文", "内容", "新闻内容", "材料", "原文")
_MANUAL_NEWS_IMAGE_KEYS = ("socialimage", "image", "cover", "thumbnail", "配图", "图片")
_MANUAL_NEWS_COUNTRY_KEYS = ("sourcecountry", "country", "国家", "地区")
_MANUAL_NEWS_LANGUAGE_KEYS = ("language", "lang", "语言")


def _manual_first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in record:
            value = _juhe_text(record.get(key))
            if value:
                return value
    return ""


def _manual_news_url(title: str, url: str) -> str:
    if url:
        return url
    slug = urllib.parse.quote(re.sub(r"\s+", "-", title.strip())[:80] or "manual-news")
    return f"manual://news/{slug}"


def _manual_record_to_news_item(record: dict[str, Any]) -> NewsItem | None:
    title = _manual_first_text(record, _MANUAL_NEWS_TITLE_KEYS)
    content = _manual_first_text(record, _MANUAL_NEWS_CONTENT_KEYS)
    desc = _manual_first_text(record, _MANUAL_NEWS_DESC_KEYS)
    if not title:
        title = (desc or content).splitlines()[0].strip() if (desc or content) else ""
    if not title:
        return None
    url_item = _manual_news_url(title, _manual_first_text(record, _MANUAL_NEWS_URL_KEYS))
    domain = _manual_first_text(record, ("domain", "域名"))
    if not domain:
        try:
            parsed_domain = urllib.parse.urlparse(url_item).netloc.strip().lower()
            domain = parsed_domain if parsed_domain and not url_item.startswith("manual://") else "manual.local"
        except Exception:
            domain = "manual.local"
    return NewsItem(
        title=title,
        url=url_item,
        source=_manual_first_text(record, _MANUAL_NEWS_SOURCE_KEYS) or None,
        description=desc or (content[:180] if content else None),
        content=content or desc or None,
        domain=domain or None,
        seendate=_manual_first_text(record, _MANUAL_NEWS_TIME_KEYS) or None,
        language=_manual_first_text(record, _MANUAL_NEWS_LANGUAGE_KEYS) or None,
        socialimage=_manual_first_text(record, _MANUAL_NEWS_IMAGE_KEYS) or None,
        sourcecountry=_manual_first_text(record, _MANUAL_NEWS_COUNTRY_KEYS) or None,
        attention=_record_attention(record),
    )


def _manual_json_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        records = data.get("items") or data.get("candidates") or data.get("news") or data.get("新闻") or []
    else:
        records = data
    if not isinstance(records, list):
        raise RuntimeError("manual news materials JSON must contain a list or an object with items/candidates/news")
    return [rec for rec in records if isinstance(rec, dict)]


def _manual_text_blocks(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*(?:-{3,}|={3,}|\*{3,})\s*\n", normalized)
    if len(blocks) == 1:
        blocks = re.split(r"\n\s*(?=#{1,3}\s+|\d+[.、]\s*(?:新闻|标题|title)\s*[:：])", normalized, flags=re.IGNORECASE)
    return [block.strip() for block in blocks if block.strip()]


def _manual_text_record(block: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    current_key = ""
    plain_lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            if current_key:
                record[current_key] = f"{record.get(current_key, '')}\n"
            continue
        heading = re.match(r"^#{1,6}\s*(?P<title>.+)$", line)
        if heading and not record.get("标题"):
            record["标题"] = heading.group("title").strip()
            current_key = "内容"
            continue
        match = re.match(r"^(?P<key>[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s_/.-]{0,18})\s*[:：]\s*(?P<value>.*)$", line)
        if match:
            key = re.sub(r"\s+", "", match.group("key")).strip()
            value = match.group("value").strip()
            record[key] = value
            current_key = key
            continue
        if current_key in _MANUAL_NEWS_CONTENT_KEYS or current_key in {"正文", "内容", "新闻内容", "材料", "原文"}:
            prev = str(record.get(current_key) or "").rstrip()
            record[current_key] = f"{prev}\n{line}".strip() if prev else line
        else:
            plain_lines.append(line)
    if plain_lines:
        if not record.get("标题"):
            record["标题"] = plain_lines[0]
            plain_lines = plain_lines[1:]
        if plain_lines and not any(key in record for key in _MANUAL_NEWS_CONTENT_KEYS):
            record["内容"] = "\n".join(plain_lines).strip()
    return record


def parse_manual_news_materials(text: str, *, max_records: int | None = None) -> list[NewsItem]:
    """
    Parse user-provided news materials from JSON-like text or readable Markdown/plain text.

    Text records can be separated by `---` and use labels such as 标题/时间/来源/链接/内容.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    records: list[dict[str, Any]]
    if raw[0] in "[{":
        try:
            records = _manual_json_records(json.loads(raw))
        except json.JSONDecodeError:
            records = [_manual_text_record(block) for block in _manual_text_blocks(raw)]
    else:
        records = [_manual_text_record(block) for block in _manual_text_blocks(raw)]
    limit = max_records if max_records is not None else len(records)
    items: list[NewsItem] = []
    for record in records:
        item = _manual_record_to_news_item(record)
        if item is None:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def load_manual_news_materials_file(path: str | Path, *, max_records: int) -> list[NewsItem]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8-sig")
    if file_path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            data = json.loads(raw)
            if isinstance(data, dict):
                records.append(data)
            if len(records) >= max_records:
                break
        items: list[NewsItem] = []
        for record in records:
            item = _manual_record_to_news_item(record)
            if item is not None:
                items.append(item)
        return items
    return parse_manual_news_materials(text, max_records=max_records)


def load_single_news_material_file(path: str | Path) -> NewsItem:
    items = load_manual_news_materials_file(path, max_records=2)
    if len(items) != 1:
        raise RuntimeError(
            f"single news material file must contain exactly one news item; got {len(items)}"
        )
    return items[0]


def read_manual_material_source_info(path: str | Path) -> dict[str, Any]:
    """Read safe provenance fields from a GUI text snapshot, never its body."""
    info: dict[str, Any] = {"input_origin": "file"}
    file_path = Path(path)
    if file_path.suffix.lower() != ".json":
        return info
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return info
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return info
    origin = str(payload.get("input_origin") or "").strip()
    if origin != "gui_text":
        return info
    info["input_origin"] = origin
    info["schema_version"] = 1
    raw_char_count = payload.get("raw_char_count")
    if isinstance(raw_char_count, int) and raw_char_count >= 0:
        info["raw_char_count"] = raw_char_count
    raw_sha256 = str(payload.get("raw_sha256") or "").strip()
    if raw_sha256 and len(raw_sha256) <= 128:
        info["raw_sha256"] = raw_sha256
    return info


def fetch_daily_news_candidates(
    prompt_hint: str,
    *,
    tz_name: Optional[str] = None,
    max_records: Optional[int] = None,
    search_days: Optional[int] = None,
    timeout_s: Optional[float] = None,
    expand_query_variants: bool = True,
    materials_file: str | Path | None = None,
    source_health_path: str | Path | None = None,
    source_cooldown_seconds: int | None = None,
    persist_source_health: bool | None = None,
    exhaustive_sources: bool = False,
    progress_callback: Callable[[str, str, dict[str, Any]], None] | None = None,
    minimum_qualified_records: int | None = None,
    qualified_count_callback: Callable[[list[NewsItem]], int] | None = None,
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
    if max_records is None:
        max_records = int(os.getenv("NEWS_MAX_RECORDS") or DEFAULT_MAX_RECORDS)
    else:
        max_records = int(max_records)
    if search_days is None:
        search_days = int(os.getenv("NEWS_FETCH_WINDOW_DAYS") or "1")
    else:
        search_days = int(search_days)
    search_days = max(1, search_days)
    timeout_s = float(os.getenv("NEWS_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    health_path = Path(source_health_path) if source_health_path else None
    if source_cooldown_seconds is None:
        try:
            cooldown_seconds = int((os.getenv("NEWS_SOURCE_COOLDOWN_S") or "300").strip())
        except ValueError:
            cooldown_seconds = 300
    else:
        cooldown_seconds = int(source_cooldown_seconds)
    cooldown_seconds = max(0, min(cooldown_seconds, 3600))
    should_persist_health = bool(health_path) if persist_source_health is None else bool(persist_source_health)
    previous_health = load_source_health_snapshot(health_path) if health_path else None
    persisted_health_attempts = {
        attempt.source_name: attempt
        for attempt in (previous_health.attempts if previous_health is not None else [])
        if attempt.source_name
    }
    health_attempts: list[SourceAttempt] = []
    cooldown_skipped: list[str] = []

    def _persist_health_snapshot() -> str:
        if health_path is None or not should_persist_health:
            return str(health_path) if health_path is not None else ""
        snapshot = SourceHealthSnapshot(
            collection="daily_news",
            generated_at=_news_health_timestamp(),
            attempts=sorted(persisted_health_attempts.values(), key=lambda item: item.source_name),
        )
        return str(save_source_health_snapshot(snapshot, health_path))

    startdatetime, enddatetime = _recent_range_utc(tz_name, days=search_days)
    start_dt = datetime.strptime(startdatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(enddatetime, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    from_iso = start_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    to_iso = end_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    manual_materials_file = str(materials_file or os.getenv("NEWS_MATERIALS_FILE") or "").strip()
    auto_provider_selection = not provider_env and not manual_materials_file
    provider_plan: list[str]
    if manual_materials_file:
        provider_plan = ["manual"]
    elif provider_env:
        provider_plan = [provider_env]
    else:
        file_path = (os.getenv("NEWS_CANDIDATES_FILE") or "").strip()
        if file_path:
            provider_plan = ["file"]
        else:
            # Auto: gather every configured keyed provider before RSS backfills.
            # Final ranking sees a source-balanced pool, rather than whichever
            # aggregator happened to respond first.
            provider_plan = []
            try:
                _load_juhe_config()
                provider_plan.append("juhe")
            except Exception:
                pass
            additional_sources = _load_additional_news_sources_config()
            if additional_sources.newsdata_api_key:
                provider_plan.append("newsdata")
            if additional_sources.thenewsapi_token:
                provider_plan.append("thenewsapi")
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
                _load_additional_news_source_key("alphavantage")
                provider_plan.append("alphavantage")
            except Exception:
                pass
            try:
                _load_additional_news_source_key("finnhub")
                provider_plan.append("finnhub")
            except Exception:
                pass
            # CN regional Google News RSS is the primary no-key source for
            # Chinese prompts. Keep the international RSS and BBC as breadth
            # backfills, then use hot lists only as a heat supplement.
            provider_plan.extend(["google_rss_cn", "google_rss", "bbc_rss"])
            provider_plan.append("hotnews")
    provider_plan = list(dict.fromkeys(provider_plan))

    supported_providers = (
        "newsapi",
        "gnews",
        "juhe",
        "newsdata",
        "alphavantage",
        "thenewsapi",
        "finnhub",
        "google_rss",
        "google_rss_cn",
        "bbc_rss",
        "hotnews",
        "file",
        "manual",
    )
    unsupported = [p for p in provider_plan if p not in supported_providers]
    if unsupported:
        raise RuntimeError(
            f"unsupported NEWS_PROVIDER={unsupported[0]!r}; supported: {', '.join(supported_providers)}"
        )
    if not provider_plan:
        raise RuntimeError(
            "no news provider configured; set NEWS_PROVIDER=file with NEWS_CANDIDATES_FILE, "
            "configure NEWS_API_KEY / GNEWS_API_KEY / JUHE_NEWS_APPKEY / NEWSDATA_API_KEY, or use NEWS_PROVIDER=hotnews"
        )

    hint_query = (prompt_hint or "").strip()
    if hint_query:
        queries = _build_prompt_news_queries(hint_query) if expand_query_variants else [hint_query]
        default_queries = _split_news_queries(os.getenv("NEWS_QUERY_DEFAULT")) or [DEFAULT_QUERY]
    else:
        queries = _default_news_queries()
        default_queries = []
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
    # In automatic mode, keep collecting across providers even after the
    # first provider returns results. A large raw pool is intentional: later
    # ranking applies freshness, relevance, history, country and domain rules.
    collected_candidates: list[NewsItem] = []
    first_success_provider: str | None = None
    successful_providers: list[str] = []
    collection_stop_reason = "provider_plan_exhausted"
    qualified_count_at_stop: int | None = None
    minimum_qualified = max(0, int(minimum_qualified_records or 0))
    min_diverse_sources = _positive_env_int("NEWS_MIN_DIVERSE_PROVIDERS", 3)
    provider_total = len(provider_plan)
    for provider_index, provider in enumerate(provider_plan, start=1):
        if progress_callback is not None:
            progress_callback(
                "信源采集",
                "in_progress",
                {
                    "provider": provider,
                    "source_index": provider_index,
                    "source_total": provider_total,
                },
            )
        if provider not in provider_attempts:
            provider_attempts.append(provider)
        previous_attempt = persisted_health_attempts.get(provider)
        if auto_provider_selection and is_source_in_cooldown(
            previous_attempt,
            cooldown_seconds=cooldown_seconds,
        ):
            cooldown_skipped.append(provider)
            health_attempts.append(
                SourceAttempt(
                    collection="daily_news",
                    source_name=provider,
                    source_url=_news_provider_health_url(provider),
                    tier=_news_provider_health_tier(provider),
                    status="cooldown",
                    checked_at=previous_attempt.checked_at if previous_attempt is not None else _news_health_timestamp(),
                    elapsed_seconds=0.0,
                    item_count=previous_attempt.item_count if previous_attempt is not None else 0,
                    dated_count=previous_attempt.dated_count if previous_attempt is not None else 0,
                    url_count=previous_attempt.url_count if previous_attempt is not None else 0,
                    error=previous_attempt.error if previous_attempt is not None else "",
                    http_status=previous_attempt.http_status if previous_attempt is not None else None,
                )
            )
            if progress_callback is not None:
                progress_callback(
                    "信源采集",
                    "skipped",
                    {
                        "provider": provider,
                        "source_index": provider_index,
                        "source_total": provider_total,
                        "reason": "recent_failure_cooldown",
                    },
                )
            continue
        provider_started = time.perf_counter()
        provider_checked_at = _news_health_timestamp()
        provider_error: Exception | None = None
        provider_item_count = 0
        provider_dated_count = 0
        provider_url_count = 0
        provider_candidates: list[NewsItem] = []
        provider_queries = (
            queries[:1]
            if provider in ("file", "manual", "hotnews", "bbc_rss", "alphavantage", "finnhub")
            else queries
        )
        if exhaustive_sources:
            provider_queries = provider_queries[: _positive_env_int(
                "NEWS_EXHAUSTIVE_PROVIDER_QUERY_LIMIT",
                DEFAULT_EXHAUSTIVE_PROVIDER_QUERY_LIMIT,
            )]
        if provider == "google_rss_cn" and exhaustive_sources:
            # Keep the generic CN search, then explicitly ask for official
            # mainland newsrooms so a broad aggregator cannot crowd them out.
            # Two domains per pass are enough for a diverse pool; the domain
            # cap later preserves room for all other sources.
            official_queries = [
                f"{q} site:{domain}"
                for q in provider_queries[:1]
                for domain in CN_OFFICIAL_NEWS_DOMAINS[: _positive_env_int(
                    "NEWS_EXHAUSTIVE_OFFICIAL_RSS_DOMAIN_LIMIT",
                    DEFAULT_EXHAUSTIVE_OFFICIAL_RSS_DOMAIN_LIMIT,
                )]
            ]
            provider_queries = [*provider_queries, *official_queries]
        provider_timeout_s = _provider_request_timeout_s(
            provider,
            requested_timeout_s=timeout_s,
            exhaustive_sources=exhaustive_sources,
        )
        for q in provider_queries:
            if hint_query and q in default_queries and provider_candidates:
                break
            chosen_provider = provider
            chosen_query = q
            try:
                if provider == "newsapi":
                    api_key, base_url = _load_newsapi_config()
                    chosen_source_api = {"provider": "newsapi", "base_url": base_url}
                    sort_by = "relevancy" if hint_query and q not in default_queries else "publishedAt"
                    raw = _newsapi_fetch_articles(
                        api_key=api_key,
                        base_url=base_url,
                        query=q,
                        from_iso=from_iso,
                        to_iso=to_iso,
                        sort_by=sort_by,
                        page_size=max_records,
                        timeout_s=provider_timeout_s,
                    )
                    if not raw and not exhaustive_sources:
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
                            timeout_s=provider_timeout_s,
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
                        timeout_s=provider_timeout_s,
                    )
                    if not raw and not exhaustive_sources:
                        raw = _gnews_fetch_articles(
                            api_key=api_key,
                            base_url=base_url,
                            query=q,
                            from_iso=None,
                            to_iso=None,
                            max_records=max_records,
                            timeout_s=provider_timeout_s,
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
                        timeout_s=provider_timeout_s,
                        # Automatic multi-source collection only needs list
                        # summaries at this stage. An explicitly selected Juhe
                        # source, however, benefits from a bounded number of
                        # article details before daily-news quality screening.
                        fetch_detail=not exhaustive_sources or not auto_provider_selection,
                    )
                    in_today = []
                    for item in raw:
                        seen = _parse_seendate_utc(item.seendate)
                        if seen and start_dt <= seen <= end_dt:
                            in_today.append(item)
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                elif provider == "newsdata":
                    api_key = _load_additional_news_source_key("newsdata")
                    chosen_source_api = {"provider": "newsdata", "base_url": NEWSDATA_BASE_URL}
                    raw = _newsdata_fetch_articles(
                        api_key=api_key,
                        query=q,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                    )
                    in_today = [
                        item for item in raw
                        if (seen := _parse_seendate_utc(item.seendate)) and start_dt <= seen <= end_dt
                    ]
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                    if hint_query and q not in default_queries and _best_relevance(candidates, q) <= 0.0:
                        candidates = []
                elif provider == "alphavantage":
                    api_key = _load_additional_news_source_key("alphavantage")
                    chosen_source_api = {"provider": "alphavantage", "base_url": ALPHAVANTAGE_BASE_URL}
                    raw = _alphavantage_fetch_articles(
                        api_key=api_key,
                        query=q,
                        from_iso=from_iso,
                        to_iso=to_iso,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                    )
                    in_today = [
                        item for item in raw
                        if (seen := _parse_seendate_utc(item.seendate)) and start_dt <= seen <= end_dt
                    ]
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                elif provider == "thenewsapi":
                    api_token = _load_additional_news_source_key("thenewsapi")
                    chosen_source_api = {"provider": "thenewsapi", "base_url": THENEWSAPI_BASE_URL}
                    raw = _thenewsapi_fetch_articles(
                        api_token=api_token,
                        query=q,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                        from_iso=from_iso,
                        to_iso=to_iso,
                    )
                    in_today = [
                        item for item in raw
                        if (seen := _parse_seendate_utc(item.seendate)) and start_dt <= seen <= end_dt
                    ]
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                    if hint_query and q not in default_queries and _best_relevance(candidates, q) <= 0.0:
                        candidates = []
                elif provider == "finnhub":
                    api_key = _load_additional_news_source_key("finnhub")
                    chosen_source_api = {"provider": "finnhub", "base_url": FINNHUB_BASE_URL}
                    raw = _finnhub_fetch_articles(
                        api_key=api_key,
                        query=q,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                    )
                    in_today = [
                        item for item in raw
                        if (seen := _parse_seendate_utc(item.seendate)) and start_dt <= seen <= end_dt
                    ]
                    candidates = in_today or raw
                    used_time_range = bool(in_today)
                elif provider in {"google_rss", "google_rss_cn"}:
                    is_cn_rss = provider == "google_rss_cn"
                    chosen_source_api = {
                        "provider": provider,
                        "base_url": _google_news_rss_base_url(),
                        "hl": "zh-CN" if is_cn_rss else (os.getenv("GOOGLE_NEWS_RSS_HL") or "en-US").strip(),
                        "gl": "CN" if is_cn_rss else (os.getenv("GOOGLE_NEWS_RSS_GL") or "US").strip(),
                    }
                    candidates = _google_rss_fetch_articles(
                        query=q,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                        language="zh-CN" if is_cn_rss else None,
                        country="CN" if is_cn_rss else None,
                    )
                    used_time_range = False
                elif provider == "bbc_rss":
                    chosen_source_api = {
                        "provider": "bbc_rss",
                        "feeds": [BBC_RSS_FEEDS[key] for key in _bbc_rss_feed_keys(q)],
                    }
                    candidates = _bbc_rss_fetch_articles(
                        prompt_hint=q,
                        max_records=max_records,
                        timeout_s=provider_timeout_s,
                    )
                    used_time_range = False
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
                        timeout_s=provider_timeout_s,
                    )
                    used_time_range = False
                elif provider == "manual":
                    if not manual_materials_file:
                        raise RuntimeError("NEWS_MATERIALS_FILE or --news-materials-file is required when NEWS_PROVIDER=manual")
                    chosen_source_api = {"provider": "manual", "file_path": manual_materials_file}
                    candidates = load_manual_news_materials_file(
                        manual_materials_file,
                        max_records=max_records,
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
                candidates = [replace(item, provider=provider) for item in candidates]
                provider_item_count += len(candidates)
                provider_dated_count += sum(1 for item in candidates if str(item.seendate or "").strip())
                provider_url_count += sum(1 for item in candidates if str(item.url or "").strip())
                if candidates:
                    candidates = _dedupe_candidates(candidates)
                    candidates, skipped_used = filter_used_news_items(candidates, used_news_url_keys)
                    if skipped_used:
                        history_skipped.extend(skipped_used)
                        if not candidates:
                            last_err = "all candidates filtered by history URL dedupe"
                    if not candidates:
                        continue
                    aggregate_query = aggregate_empty_prompt or (bool(hint_query) and q not in default_queries)
                    if aggregate_query:
                        provider_candidates.extend(candidates)
                        queries_used.append(q)
                        provider_candidates = _dedupe_candidates(provider_candidates)
                        if len(provider_candidates) >= max_records and not (
                            exhaustive_sources and provider == "google_rss_cn"
                        ):
                            break
                        candidates = []
                        continue
                    break
            except Exception as exc:
                last_err = f"{provider}/{q}: {exc}"
                provider_errors.append(last_err)
                provider_error = exc
                candidates = []
                # A provider-level exception (timeout, authentication, network)
                # is not query-specific. Move to the next provider instead of
                # spending the full timeout budget on every query variant.
                break
        elapsed_seconds = time.perf_counter() - provider_started
        if provider_error is not None:
            health_attempt = SourceAttempt(
                collection="daily_news",
                source_name=provider,
                source_url=_news_provider_health_url(provider),
                tier=_news_provider_health_tier(provider),
                status=_news_source_error_status(provider_error),
                checked_at=provider_checked_at,
                elapsed_seconds=elapsed_seconds,
                item_count=provider_item_count,
                dated_count=provider_dated_count,
                url_count=provider_url_count,
                error=str(provider_error),
                http_status=getattr(provider_error, "code", None),
            )
        else:
            health_attempt = SourceAttempt(
                collection="daily_news",
                source_name=provider,
                source_url=_news_provider_health_url(provider),
                tier=_news_provider_health_tier(provider),
                status=_news_provider_result_status(
                    item_count=provider_item_count,
                    dated_count=provider_dated_count,
                ),
                checked_at=provider_checked_at,
                elapsed_seconds=elapsed_seconds,
                item_count=provider_item_count,
                dated_count=provider_dated_count,
                url_count=provider_url_count,
            )
        health_attempts.append(health_attempt)
        persisted_health_attempts[provider] = health_attempt
        if progress_callback is not None:
            progress_callback(
                "信源采集",
                "failed" if provider_error is not None else "success",
                {
                    "provider": provider,
                    "source_index": provider_index,
                    "source_total": provider_total,
                    "items": provider_item_count,
                    "dated": provider_dated_count,
                    "elapsed_seconds": round(elapsed_seconds, 1),
                    "error": str(provider_error)[:180] if provider_error is not None else "",
                },
            )
        if (aggregate_empty_prompt or hint_query) and provider_candidates:
            candidates = _dedupe_candidates(provider_candidates)[:max_records]
            chosen_query = ",".join(queries_used) if queries_used else chosen_query
        provider_pool = provider_candidates or candidates
        if provider_pool:
            if first_success_provider is None:
                first_success_provider = provider
            if provider not in successful_providers:
                successful_providers.append(provider)
            collected_candidates = _balanced_candidate_pool(
                [*collected_candidates, *provider_pool],
                max_records=max_records,
            )
        if collected_candidates:
            candidates = collected_candidates
            raw_target_met = len(collected_candidates) >= max_records
            enough_diversity = len(successful_providers) >= min(min_diverse_sources, provider_total)
            qualified_target_met = True
            if qualified_count_callback is not None and minimum_qualified > 0:
                qualified_count_at_stop = max(0, int(qualified_count_callback(collected_candidates)))
                qualified_target_met = qualified_count_at_stop >= minimum_qualified
            if (
                raw_target_met
                and (not (auto_provider_selection and exhaustive_sources) or enough_diversity)
                and qualified_target_met
            ):
                collection_stop_reason = (
                    "raw_and_qualified_pool_targets_reached"
                    if qualified_count_callback is not None and minimum_qualified > 0
                    else "raw_pool_target_reached"
                )
                if progress_callback is not None and auto_provider_selection and exhaustive_sources:
                    progress_callback(
                        "信源采集",
                        "success",
                        {
                            "provider": provider,
                            "source_index": provider_index,
                            "source_total": provider_total,
                            "items": len(collected_candidates),
                            "dated": sum(1 for item in collected_candidates if str(item.seendate or "").strip()),
                            "qualified": qualified_count_at_stop,
                            "min_qualified": minimum_qualified or None,
                            "reason": collection_stop_reason,
                        },
                    )
                break
            if (
                raw_target_met
                and enough_diversity
                and not qualified_target_met
                and progress_callback is not None
                and auto_provider_selection
                and exhaustive_sources
            ):
                progress_callback(
                    "信源采集",
                    "in_progress",
                    {
                        "provider": provider,
                        "source_index": provider_index,
                        "source_total": provider_total,
                        "items": len(collected_candidates),
                        "qualified": qualified_count_at_stop,
                        "min_qualified": minimum_qualified,
                        "reason": "qualified_pool_below_target",
                    },
                )
            # Automatic fallback is deliberately exhaustive up to the raw
            # pool target. Explicit NEWS_PROVIDER remains single-provider.
            if auto_provider_selection and exhaustive_sources:
                continue
            break

    if not candidates:
        _persist_health_snapshot()
        raise RuntimeError(
            f"no news returned (providers={','.join(provider_attempts)}, query={chosen_query}, err={last_err})"
        )
    if first_success_provider:
        chosen_provider = first_success_provider
    chosen_source_api = {
        **chosen_source_api,
        "provider": chosen_provider,
        "query": chosen_query,
        "provider_plan": provider_plan,
        "provider_attempts": provider_attempts,
    }

    health_snapshot_path = _persist_health_snapshot()
    meta: dict[str, Any] = {
        "provider": chosen_provider,
        "api_source": chosen_provider,
        "source_api": chosen_source_api,
        "provider_plan": provider_plan,
        "provider_attempts": provider_attempts,
        "provider_errors": provider_errors[-10:],
        "collection_stop_reason": collection_stop_reason,
        "qualified_count_at_stop": qualified_count_at_stop,
        "minimum_qualified_records": minimum_qualified or None,
        "successful_providers": successful_providers,
        "tz": tz_name,
        "query": chosen_query,
        "query_variants": queries,
        "query_expansion_enabled": bool(expand_query_variants),
        "queries_used": queries_used or ([chosen_query] if candidates else []),
        "startdatetime": startdatetime,
        "enddatetime": enddatetime,
        "search_days": search_days,
        "used_today_range": used_time_range,
        "history_dedupe": {
            "enabled": history_dedupe_is_enabled,
            "used_count": len(used_news_url_keys),
            "skipped_count": len(history_skipped),
            "skipped": history_skipped[:10],
        },
        "source_health": {
            "enabled": health_path is not None,
            "snapshot_path": health_snapshot_path,
            "cooldown_seconds": cooldown_seconds,
            "cooldown_skipped": cooldown_skipped,
            "attempts": [attempt.to_dict() for attempt in health_attempts],
        },
        "candidates": [asdict(c) for c in candidates[:10]],
    }
    if chosen_provider == "manual":
        meta["manual_materials"] = {
            "file_path": manual_materials_file,
            "count": len(candidates),
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
