from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import unquote, urlsplit

from .models import AIUpdateItem


BEIJING_TZ = timezone(timedelta(hours=8))
_GENERIC_PRODUCT_KEYS = {"", "ai", "api", "chatgpt", "model", "models", "tool", "tools"}
_TOPIC_STOPWORDS = {
    "ai",
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "inside",
    "introducing",
    "introduction",
    "case",
    "cases",
    "study",
    "studies",
    "blog",
    "index",
    "news",
    "update",
    "updates",
    "release",
    "releases",
    "launch",
    "launches",
    "new",
    "how",
    "why",
    "what",
    "openai",
    "hugging",
    "face",
    "google",
    "deepmind",
    "anthropic",
    "microsoft",
}
_GENERIC_TOPIC_EXTRAS = {
    "benchmark",
    "bench",
    "eval",
    "model",
    "models",
    "tool",
    "tools",
    "update",
    "updates",
}
_MODEL_TOPIC_RE = re.compile(
    r"\b(?:gpt|glm|qwen|claude|codex|gemini|gemma|doubao|seedream|deepseek|llama|kimi|minimax|ernie|"
    r"genebench|scarfbench|discoformer|benchmark|bench|eval)\b",
    flags=re.IGNORECASE,
)
_MODEL_RELEASE_MARKERS = (
    "模型",
    "版本",
    "发布",
    "上线",
    "升级",
    "release",
    "released",
    "launch",
    "launches",
    "introducing",
    "model",
    "version",
    "gpt",
    "glm",
    "qwen",
    "claude",
    "gemini",
    "gemma",
    "doubao",
    "seedream",
    "deepseek",
    "llama",
)
_BENCHMARK_MARKERS = ("benchmark", "bench", "eval", "评测", "基准", "测试集")
_TECHNICAL_MARKERS = (
    "api",
    "sdk",
    "agent",
    "agents",
    "code",
    "coding",
    "developer",
    "tool",
    "tools",
    "framework",
    "open source",
    "github",
    "infrastructure",
    "debug",
    "core dump",
    "voice",
    "multimodal",
    "reasoning",
    "inference",
    "智能体",
    "开发者",
    "工具",
    "开源",
    "框架",
    "基础设施",
    "调试",
    "语音",
    "多模态",
    "推理",
    "代码",
)
_DISCUSSION_MARKERS = (
    "why",
    "opinion",
    "analysis",
    "trend",
    "trends",
    "inevitable",
    "adoption",
    "case study",
    "case studies",
    "customer",
    "business",
    "为什么",
    "观点",
    "探讨",
    "趋势",
    "必然",
    "采用",
    "普及",
    "案例",
    "行业观察",
)
_CATEGORY_PRIORITY = {
    "model_release": 5,
    "benchmark": 4,
    "technical_tool": 4,
    "research": 3,
    "business_case": 2,
    "discussion": 1,
    "other": 0,
}


def _parse_published_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        match = re.search(r"(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})", text)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        try:
            dt = datetime(year, month, day)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_datetime(value: datetime | date | None) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        dt = datetime.now(timezone.utc).astimezone()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _beijing_date(value: datetime) -> date:
    return value.astimezone(BEIJING_TZ).date()


def _text_blob(item: AIUpdateItem) -> str:
    return " ".join(
        part.strip()
        for part in (
            item.title,
            item.summary,
            item.product,
            item.vendor,
            item.source_name,
            item.raw_excerpt,
            _url_topic_text(item.url),
        )
        if part and part.strip()
    )


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value or "", flags=re.IGNORECASE).lower()


def _url_topic_text(url: str) -> str:
    try:
        parts = [unquote(part) for part in urlsplit(url or "").path.split("/") if part.strip()]
    except ValueError:
        return ""
    return " ".join(parts[-3:])


def _topic_tokens(value: str) -> list[str]:
    raw = re.sub(r"[_\-/]+", " ", value or "")
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", raw):
        norm = _normalize_token(token)
        if not norm or norm in _TOPIC_STOPWORDS or norm.isdigit():
            continue
        tokens.append(norm)
    return tokens


def _product_topic_key(item: AIUpdateItem) -> str:
    product = _normalize_token(item.product)
    if product and product not in _GENERIC_PRODUCT_KEYS and (
        any(ch.isdigit() for ch in product) or _MODEL_TOPIC_RE.search(item.product)
    ):
        return f"product:{product}"
    return ""


def _semantic_topic_key(item: AIUpdateItem) -> str:
    product_key = _product_topic_key(item)
    if product_key:
        return product_key
    tokens = _topic_tokens(f"{item.title} {item.summary} {item.raw_excerpt} {_url_topic_text(item.url)}")
    if not tokens:
        return ""
    topic_tokens = [
        token
        for token in tokens
        if _MODEL_TOPIC_RE.search(token) or any(ch.isdigit() for ch in token) or token.endswith(("bench", "former"))
    ]
    if not topic_tokens:
        return ""
    anchor = topic_tokens[0]
    extras = [
        token
        for token in topic_tokens[1:]
        if token != anchor and token not in _GENERIC_TOPIC_EXTRAS
    ][:2]
    return "topic:" + "-".join([anchor, *extras])


def _trace_url(item: AIUpdateItem) -> str:
    if item.normalized_url:
        return item.normalized_url
    for url in item.evidence_urls or []:
        text = (url or "").strip()
        if text:
            return text
    return ""


def _source_priority(item: AIUpdateItem) -> int:
    return {"official": 4, "github": 3, "search": 2, "social": 1}.get(item.source_type, 0)


def ai_update_attention_score(item: AIUpdateItem) -> float:
    score = float(item.confidence_score or 0.0)
    score += min(0.15, len(item.evidence_urls or []) * 0.03)
    if item.verification_status == "social_confirmed":
        score += 0.08
    score += _source_priority(item) * 0.005
    return round(score, 6)


def ai_update_category(item: AIUpdateItem) -> str:
    blob = _text_blob(item).lower()
    headline_blob = f"{item.title} {_url_topic_text(item.url)} {item.product}".lower()
    has_discussion_marker = any(marker in headline_blob for marker in _DISCUSSION_MARKERS)
    has_named_model_or_benchmark = bool(_MODEL_TOPIC_RE.search(headline_blob)) or any(
        marker in headline_blob for marker in _BENCHMARK_MARKERS
    )
    if has_discussion_marker and not has_named_model_or_benchmark:
        if any(marker in headline_blob for marker in ("case study", "case studies", "案例", "adoption", "采用", "普及")):
            return "business_case"
        return "discussion"
    if any(marker in blob for marker in _MODEL_RELEASE_MARKERS):
        return "model_release"
    if any(marker in blob for marker in _BENCHMARK_MARKERS):
        return "benchmark"
    if any(marker in blob for marker in _TECHNICAL_MARKERS):
        return "technical_tool"
    if any(marker in blob for marker in _DISCUSSION_MARKERS):
        if any(marker in blob for marker in ("case study", "case studies", "案例", "adoption", "采用", "普及")):
            return "business_case"
        return "discussion"
    return "other"


def ai_update_category_priority(item: AIUpdateItem) -> int:
    return _CATEGORY_PRIORITY.get(ai_update_category(item), 0)


def filter_recent_ai_updates(
    items: list[AIUpdateItem],
    *,
    max_age_days: int | None = None,
    now: datetime | date | None = None,
    require_url: bool = True,
) -> list[AIUpdateItem]:
    as_of_date = _beijing_date(_as_datetime(now))
    oldest_date = as_of_date - timedelta(days=max(0, int(max_age_days or 1) - 1))
    out: list[AIUpdateItem] = []
    for item in items:
        if require_url and not _trace_url(item):
            continue
        if max_age_days is not None:
            published = _parse_published_datetime(item.published_at)
            if published is None:
                continue
            published_date = _beijing_date(published)
            if published_date < oldest_date or published_date > as_of_date:
                continue
        out.append(item)
    return out


def _merge_items(primary: AIUpdateItem, other: AIUpdateItem) -> AIUpdateItem:
    data = primary.model_dump()
    evidence = list(data.get("evidence_urls") or [])
    for url in [other.url, *(other.evidence_urls or [])]:
        if url and url not in evidence and url != primary.url:
            evidence.append(url)
    data["evidence_urls"] = evidence
    tags = list(data.get("tags") or [])
    for tag in other.tags or []:
        if tag and tag not in tags:
            tags.append(tag)
    data["tags"] = tags
    if primary.source_type in {"official", "github"} and other.source_type in {"social", "search"}:
        data["verification_status"] = "social_confirmed"
        data["confidence_score"] = max(primary.confidence_score, 0.9)
    elif (
        primary.source_type in {"official", "github"}
        and other.verification_status == "social_confirmed"
    ):
        data["verification_status"] = "social_confirmed"
        data["confidence_score"] = max(primary.confidence_score, other.confidence_score, 0.9)
    return AIUpdateItem.model_validate(data)


def _prefer_item(a: AIUpdateItem, b: AIUpdateItem) -> AIUpdateItem:
    priority = {"official": 4, "github": 3, "search": 2, "social": 1}
    if ai_update_category_priority(b) > ai_update_category_priority(a):
        return b
    if ai_update_category_priority(b) < ai_update_category_priority(a):
        return a
    if priority.get(b.source_type, 0) > priority.get(a.source_type, 0):
        return b
    if b.confidence_score > a.confidence_score:
        return b
    if (
        priority.get(b.source_type, 0) == priority.get(a.source_type, 0)
        and len(b.title or "") < len(a.title or "")
    ):
        return b
    return a


def _dedupe_updates(items: list[AIUpdateItem]) -> list[AIUpdateItem]:
    by_key: OrderedDict[str, AIUpdateItem] = OrderedDict()
    title_keys: dict[str, str] = {}
    topic_keys: dict[str, str] = {}
    for item in items:
        key = item.dedupe_key
        title_key = item.title_key
        semantic_key = _semantic_topic_key(item)
        existing_key = title_keys.get(title_key)
        if not existing_key and semantic_key:
            existing_key = topic_keys.get(semantic_key)
        if existing_key and existing_key in by_key:
            merged = by_key[existing_key]
            if key in by_key and key != existing_key:
                winner = _prefer_item(merged, by_key[key])
                loser = by_key[key] if winner is merged else merged
                merged = _merge_items(winner, loser)
                del by_key[key]
            winner = _prefer_item(merged, item)
            loser = item if winner is merged else merged
            by_key[existing_key] = _merge_items(winner, loser)
            if title_key:
                title_keys[title_key] = existing_key
            if semantic_key:
                topic_keys[semantic_key] = existing_key
            continue
        if key in by_key:
            winner = _prefer_item(by_key[key], item)
            loser = item if winner is by_key[key] else by_key[key]
            by_key[key] = _merge_items(winner, loser)
            continue
        by_key[key] = item
        if title_key:
            title_keys[title_key] = key
        if semantic_key:
            topic_keys[semantic_key] = key
    return list(by_key.values())


def dedupe_ai_updates(items: list[AIUpdateItem]) -> list[AIUpdateItem]:
    return _dedupe_updates(items)


def _vendor_key(item: AIUpdateItem) -> str:
    return (item.vendor or item.source_name or item.source_type or "unknown").strip().lower()


def _published_day_key(item: AIUpdateItem) -> str:
    dt = _parse_published_datetime(item.published_at)
    if dt is None:
        return ""
    return _beijing_date(dt).isoformat()


def ai_update_published_day_key(item: AIUpdateItem) -> str:
    return _published_day_key(item)


def ai_update_beijing_day_key(item: AIUpdateItem) -> str:
    return _published_day_key(item)


def _timestamp_key(item: AIUpdateItem) -> str:
    dt = _parse_published_datetime(item.published_at)
    if dt is not None:
        return dt.isoformat()
    return item.timestamp_sort_key


def _rank_sort_key(item: AIUpdateItem):
    return (
        _published_day_key(item),
        ai_update_category_priority(item),
        ai_update_attention_score(item),
        _timestamp_key(item),
        _source_priority(item),
    )


def _interleave_by_vendor_for_same_day(items: list[AIUpdateItem], *, target_count: int) -> list[AIUpdateItem]:
    by_day: OrderedDict[str, list[AIUpdateItem]] = OrderedDict()
    for item in items:
        by_day.setdefault(_published_day_key(item), []).append(item)

    selected: list[AIUpdateItem] = []
    for _day, day_items in by_day.items():
        by_category: OrderedDict[int, list[AIUpdateItem]] = OrderedDict()
        for item in day_items:
            by_category.setdefault(ai_update_category_priority(item), []).append(item)
        for _priority, category_items in by_category.items():
            selected.extend(_interleave_by_vendor(category_items, target_count=target_count - len(selected)))
            if len(selected) >= target_count:
                break
        if len(selected) >= target_count:
            break
    return selected[:target_count]


def _interleave_by_vendor(items: list[AIUpdateItem], *, target_count: int) -> list[AIUpdateItem]:
    groups: OrderedDict[str, list[AIUpdateItem]] = OrderedDict()
    for item in items:
        groups.setdefault(_vendor_key(item), []).append(item)

    selected: list[AIUpdateItem] = []
    while groups and len(selected) < target_count:
        for key in list(groups.keys()):
            group = groups.get(key) or []
            if not group:
                groups.pop(key, None)
                continue
            selected.append(group.pop(0))
            if not group:
                groups.pop(key, None)
            if len(selected) >= target_count:
                break
    return selected


def rank_ai_updates(
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    min_official_count: int = 6,
    allow_social_backfill: bool = True,
    max_age_days: int | None = None,
    now: datetime | date | None = None,
) -> list[AIUpdateItem]:
    target = max(1, int(target_count or 10))
    deduped = _dedupe_updates(
        filter_recent_ai_updates(
            items,
            max_age_days=max_age_days,
            now=now,
            require_url=True,
        )
    )
    official_like = [item for item in deduped if item.source_type in {"official", "github"}]
    social_like = [item for item in deduped if item.source_type in {"social", "search"}]

    official_like = sorted(official_like, key=_rank_sort_key, reverse=True)
    social_like = sorted(social_like, key=_rank_sort_key, reverse=True)

    if len(official_like) >= min_official_count:
        return _interleave_by_vendor_for_same_day(official_like, target_count=target)

    if not allow_social_backfill:
        return _interleave_by_vendor_for_same_day(official_like, target_count=target)

    combined = sorted([*official_like, *social_like], key=_rank_sort_key, reverse=True)
    return _interleave_by_vendor_for_same_day(combined, target_count=target)
