from __future__ import annotations

from collections import Counter, OrderedDict
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
_MODEL_FAMILY_VERSION_RE = re.compile(
    r"\b(?P<family>deepseek|glm|qwen|gpt|claude|gemini|gemma|doubao|seedream|kimi|minimax|ernie|llama|mistral)"
    r"[\s._-]*(?:v)?(?P<version>\d+(?:\.\d+)?)\b",
    flags=re.IGNORECASE,
)
_MODEL_VARIANT_RE = re.compile(
    r"\b(?:deepseek|glm|qwen|gpt|claude|gemini|gemma|doubao|seedream|kimi|minimax|ernie|llama|mistral)"
    r"[\s._-]*(?:v)?\d+(?:\.\d+)?[\s._-]+(?P<suffix>[a-z0-9]+)\b",
    flags=re.IGNORECASE,
)
_MODEL_FAMILY_MERGED_SUFFIXES = {"pro", "max", "flash", "lite", "preview", "exp", "speciale"}
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
_FINANCIAL_MODEL_MARKERS = (
    "discounted cash flow",
    "dcf model",
    "valuation model",
    "intrinsic value",
    "price target",
    "earnings forecast",
    "估值模型",
    "现金流折现",
    "内在价值",
    "目标价",
    "盈利预测",
)
_FINANCIAL_NEWS_MARKERS = (
    "stock",
    "stocks",
    "shares",
    "share price",
    "banking",
    "bank valuation",
    "earnings",
    "investor",
    "investment risk",
    "price target",
    "portfolio",
    "sec filing",
    "sec-filings",
    "current report",
    "6-k",
    "股票",
    "股价",
    "银行",
    "财报",
    "投资者",
    "估值",
    "目标价",
    "投资组合",
)
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
_DOMESTIC_AI_MARKERS = (
    "阿里",
    "阿里云",
    "aliyun",
    "alibaba",
    "dashscope",
    "通义",
    "千问",
    "qwen",
    "火山",
    "火山方舟",
    "volcengine",
    "字节",
    "bytedance",
    "美团",
    "longcat",
    "豆包",
    "doubao",
    "seedream",
    "seed",
    "智谱",
    "zhipu",
    "bigmodel",
    "glm",
    "deepseek",
    "月之暗面",
    "moonshot",
    "kimi",
    "minimax",
    "abab",
    "腾讯",
    "tencent",
    "混元",
    "hunyuan",
    "百度",
    "baidu",
    "文心",
    "ernie",
    "商汤",
    "sensechat",
    "昆仑",
    "天工",
    "skywork",
    "阶跃",
    "stepfun",
    "百川",
    "baichuan",
    "零一万物",
    "01.ai",
)
_FOREIGN_AI_MARKERS = (
    "openai",
    "chatgpt",
    "gpt",
    "anthropic",
    "claude",
    "google",
    "deepmind",
    "gemini",
    "gemma",
    "microsoft",
    "github",
    "copilot",
    "meta",
    "llama",
    "x.ai",
    "xai",
    "grok",
    "mistral",
    "perplexity",
    "hugging face",
    "huggingface",
    "nvidia",
    "stability ai",
    "stable diffusion",
    "cohere",
    "ai21",
)
_MODEL_NEWS_MARKERS = (
    *_MODEL_RELEASE_MARKERS,
    "reasoning",
    "inference",
    "multimodal",
    "推理",
    "多模态",
    "上下文",
    "context",
)
_NON_MODEL_INFRASTRUCTURE_MARKERS = (
    "database",
    "mysql",
    "tdsql",
    "数据库",
    "创建账号",
    "账号接口",
    "认证升级",
    "certification",
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
_EXPLICIT_AI_TOPIC_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:ai|llm|vlm|model|models)(?:[^a-z0-9]|$)|"
    r"artificial intelligence|generative ai|agentic ai|machine learning|"
    r"人工智能|生成式\s*AI|大模型|模型|智能体",
    flags=re.IGNORECASE,
)
_AI_CHANGE_MARKERS = (
    "更新",
    "发布",
    "推出",
    "上线",
    "升级",
    "新增",
    "开放",
    "开源",
    "停用",
    "下线",
    "支持",
    "修复",
    "集成",
    "接入",
    "评测",
    "进展",
    "动态",
    "release",
    "released",
    "launch",
    "launched",
    "introducing",
    "introduces",
    "update",
    "updated",
    "adds",
    "added",
    "available",
    "open source",
    "open-source",
    "open weight",
    "open-weight",
    "deprecat",
    "discontinu",
    "integrat",
    "collaborat",
    "improv",
    "new ",
    "debug",
    "bug",
    "core dump",
    "why",
    "opinion",
    "analysis",
    "trend",
    "inevitable",
    "case study",
    "探讨",
    "讨论",
    "观点",
    "趋势",
    "案例",
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


def _topic_blob(item: AIUpdateItem) -> str:
    return " ".join(
        part.strip()
        for part in (
            item.title,
            item.summary,
            item.product,
            item.raw_excerpt,
            _url_topic_text(item.url),
        )
        if part and part.strip()
    )


def _source_blob(item: AIUpdateItem) -> str:
    try:
        host = urlsplit(item.url or "").netloc
    except ValueError:
        host = ""
    return " ".join(
        part.strip()
        for part in (item.vendor, item.source_name, host)
        if part and part.strip()
    )


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value or "", flags=re.IGNORECASE).lower()


def _contains_marker(value: str, marker: str) -> bool:
    text = (value or "").lower()
    needle = (marker or "").lower().strip()
    if not needle:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in needle) or any(ch in needle for ch in ".-/ "):
        return needle in text
    if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text):
        return True
    if needle in {"meta", "xai", "ai21"}:
        return False
    compact = _normalize_token(text)
    compact_needle = _normalize_token(needle)
    return bool(compact_needle and compact_needle in compact)


def _contains_any_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(_contains_marker(value, marker) for marker in markers)


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


def _model_family_topic_key(item: AIUpdateItem) -> str:
    parts = (
        item.product,
        item.title,
        item.summary,
        item.raw_excerpt,
        _url_topic_text(item.url),
    )
    for text in parts:
        if not text or not text.strip():
            continue
        match = _MODEL_FAMILY_VERSION_RE.search(text)
        if not match:
            continue
        family = _normalize_token(match.group("family"))
        version = _normalize_token(match.group("version"))
        if not family or not version:
            continue
        suffix_match = _MODEL_VARIANT_RE.search(text)
        suffix = _normalize_token(suffix_match.group("suffix")) if suffix_match else ""
        suffix_part = f"-{suffix}" if suffix and suffix not in _MODEL_FAMILY_MERGED_SUFFIXES else ""
        return f"model:{family}-{version}{suffix_part}"
    return ""


def _semantic_topic_key(item: AIUpdateItem) -> str:
    model_family_key = _model_family_topic_key(item)
    if model_family_key:
        return model_family_key
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
    return {"official": 4, "github": 4, "aggregator": 2, "search": 2, "social": 1}.get(item.source_type, 0)


def ai_update_attention_score(item: AIUpdateItem) -> float:
    score = float(item.confidence_score or 0.0)
    score += min(0.15, len(item.evidence_urls or []) * 0.03)
    if item.verification_status in {"aggregator_confirmed", "social_confirmed"}:
        score += 0.08
    score += _source_priority(item) * 0.005
    return round(score, 6)


def ai_update_category(item: AIUpdateItem) -> str:
    blob = _text_blob(item).lower()
    headline_blob = f"{item.title} {_url_topic_text(item.url)} {item.product}".lower()
    financial_model_context = any(marker in blob for marker in _FINANCIAL_MODEL_MARKERS)
    explicit_ai_context = bool(_MODEL_TOPIC_RE.search(blob)) or bool(
        re.search(r"(?:^|[^a-z])ai(?:[^a-z]|$)|artificial intelligence|人工智能|大模型|智能体", blob)
    )
    if financial_model_context and not explicit_ai_context:
        return "other"
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


def ai_update_impact_score(item: AIUpdateItem) -> float:
    """Score publish impact without inventing signals absent from the source item."""
    category = ai_update_category(item)
    category_score = {
        "model_release": 78.0,
        "benchmark": 74.0,
        "technical_tool": 72.0,
        "research": 68.0,
        "business_case": 52.0,
        "discussion": 35.0,
        "other": 40.0,
    }.get(category, 40.0)
    reliability_bonus = min(10.0, max(0.0, ai_update_attention_score(item) * 10.0))
    source_bonus = {"official": 2.5, "github": 2.5, "aggregator": 1.0, "search": 0.5}.get(
        item.source_type,
        0.0,
    )
    evidence_bonus = min(3.0, len(item.evidence_urls or []) * 1.0)
    concrete_bonus = 0.0
    product = (item.product or "").strip()
    if product and product.lower() != "ai":
        concrete_bonus += 3.0
    if _MODEL_TOPIC_RE.search(_text_blob(item)):
        concrete_bonus += 2.0
    return round(min(100.0, category_score + reliability_bonus + source_bonus + evidence_bonus + concrete_bonus), 3)


def ai_update_is_high_impact(item: AIUpdateItem, *, threshold: float = 75.0) -> bool:
    category = ai_update_category(item)
    if category not in {"model_release", "benchmark", "technical_tool", "research"}:
        return False
    bounded_threshold = min(100.0, max(0.0, float(threshold)))
    return ai_update_impact_score(item) >= bounded_threshold


def ai_update_is_relevant(item: AIUpdateItem) -> bool:
    """Reject query matches that mention AI only incidentally in article text."""
    content_parts = [
        re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", part.lower())
        for part in (item.title, item.summary, item.raw_excerpt)
        if part and part.strip()
    ]
    content_blob = f"{item.title} {item.summary} {item.raw_excerpt}".lower()
    if (
        content_parts
        and len(set(content_parts)) == 1
        and not _contains_any_marker(content_blob, _AI_CHANGE_MARKERS)
    ):
        return False
    if item.source_type != "search":
        return True
    if not (item.summary.strip() or item.raw_excerpt.strip()):
        return False

    headline_blob = " ".join(
        part.strip()
        for part in (item.title, item.product, _url_topic_text(item.url))
        if part and part.strip()
    ).lower()
    content_blob = f"{headline_blob} {item.summary} {item.raw_excerpt}".lower()
    financial_blob = f"{content_blob} {item.source_name} {item.url}".lower()
    if _contains_any_marker(financial_blob, _FINANCIAL_NEWS_MARKERS):
        return False
    headline_has_ai = bool(_MODEL_TOPIC_RE.search(headline_blob) or _EXPLICIT_AI_TOPIC_RE.search(headline_blob))
    has_concrete_change = _contains_any_marker(content_blob, _AI_CHANGE_MARKERS)
    return headline_has_ai and has_concrete_change


def ai_update_region(item: AIUpdateItem) -> str:
    tags = {str(tag or "").strip().lower() for tag in item.tags}
    if "region:domestic" in tags:
        return "domestic"
    if "region:foreign" in tags:
        return "foreign"
    topic = _topic_blob(item).lower()
    source = _source_blob(item).lower()
    topic_is_domestic = _contains_any_marker(topic, _DOMESTIC_AI_MARKERS)
    topic_is_foreign = _contains_any_marker(topic, _FOREIGN_AI_MARKERS)
    if topic_is_domestic and not topic_is_foreign:
        return "domestic"
    if topic_is_foreign and not topic_is_domestic:
        return "foreign"

    source_is_domestic = _contains_any_marker(source, _DOMESTIC_AI_MARKERS)
    source_is_foreign = _contains_any_marker(source, _FOREIGN_AI_MARKERS)
    if source_is_domestic and not source_is_foreign:
        return "domestic"
    if source_is_foreign and not source_is_domestic:
        return "foreign"
    if topic_is_domestic:
        return "domestic"
    if topic_is_foreign:
        return "foreign"
    return "unknown"


def ai_update_is_model_news(item: AIUpdateItem) -> bool:
    blob = _text_blob(item).lower()
    headline_blob = " ".join(
        part.strip()
        for part in (item.title, item.product, _url_topic_text(item.url))
        if part and part.strip()
    ).lower()
    if (
        _contains_any_marker(headline_blob, _NON_MODEL_INFRASTRUCTURE_MARKERS)
        and not _contains_any_marker(headline_blob, ("model", "模型", "大模型"))
    ):
        return False
    if ai_update_category(item) in {"model_release", "benchmark"}:
        return True
    if any(marker in blob for marker in _FINANCIAL_MODEL_MARKERS) and not (
        _MODEL_TOPIC_RE.search(blob)
        or re.search(r"(?:^|[^a-z])ai(?:[^a-z]|$)|artificial intelligence|人工智能|大模型|智能体", blob)
    ):
        return False
    return _contains_any_marker(_topic_blob(item).lower(), _MODEL_NEWS_MARKERS)


def ai_update_is_domestic_model_news(item: AIUpdateItem) -> bool:
    return ai_update_region(item) == "domestic" and ai_update_is_model_news(item)


def ai_update_is_foreign_ai_news(item: AIUpdateItem) -> bool:
    return ai_update_region(item) == "foreign"


def ai_digest_quota_counts(items: list[AIUpdateItem]) -> dict[str, int]:
    return {
        "domestic_model": sum(1 for item in items if ai_update_is_domestic_model_news(item)),
        "foreign_ai": sum(1 for item in items if ai_update_is_foreign_ai_news(item)),
    }


def ai_digest_official_count(items: list[AIUpdateItem]) -> int:
    """Count only direct official or official-project release URLs."""
    count = 0
    for item in items:
        if item.source_type not in {"official", "github"}:
            continue
        host = (urlsplit(item.url or "").hostname or "").lower()
        if host == "aihot.virxact.com" or host.endswith(".aihot.virxact.com"):
            continue
        if host:
            count += 1
    return count


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
    if primary.source_type in {"official", "github"} and other.source_type in {"aggregator", "search"}:
        data["verification_status"] = "aggregator_confirmed"
        data["confidence_score"] = max(primary.confidence_score, 0.9)
    elif primary.source_type in {"official", "github"} and other.source_type == "social":
        data["verification_status"] = "social_confirmed"
        data["confidence_score"] = max(primary.confidence_score, 0.9)
    elif (
        primary.source_type in {"official", "github"}
        and other.verification_status in {"aggregator_confirmed", "social_confirmed"}
    ):
        data["verification_status"] = other.verification_status
        data["confidence_score"] = max(primary.confidence_score, other.confidence_score, 0.9)
    return AIUpdateItem.model_validate(data)


def _prefer_item(a: AIUpdateItem, b: AIUpdateItem) -> AIUpdateItem:
    priority = {"official": 4, "github": 4, "aggregator": 2, "search": 2, "social": 1}
    if priority.get(b.source_type, 0) > priority.get(a.source_type, 0):
        return b
    if priority.get(b.source_type, 0) < priority.get(a.source_type, 0):
        return a
    if ai_update_category_priority(b) > ai_update_category_priority(a):
        return b
    if ai_update_category_priority(b) < ai_update_category_priority(a):
        return a
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
    shared_official_urls = Counter(
        item.normalized_url
        for item in items
        if item.source_type in {"official", "github"} and item.normalized_url
    )
    for item in items:
        key = item.dedupe_key
        if (
            item.source_type in {"official", "github"}
            and item.normalized_url
            and shared_official_urls[item.normalized_url] > 1
            and item.title_key
        ):
            # A release-notes page can contain several independently dated
            # entries. Preserve distinct titles from that same official page;
            # semantic-topic deduplication below still merges the same update.
            key = f"{key}|title:{item.title_key}"
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


def featured_ai_update(items: list[AIUpdateItem]) -> AIUpdateItem | None:
    if not items:
        return None
    return max(items, key=_rank_sort_key)


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


def _selection_key(item: AIUpdateItem) -> str:
    trace_url = _trace_url(item)
    if item.source_type in {"official", "github"} and trace_url and item.title_key:
        return f"{trace_url}|title:{item.title_key}"
    return trace_url or item.dedupe_key or item.title_key or f"{item.title}|{item.published_at}"


def _meets_ai_digest_quotas(
    items: list[AIUpdateItem],
    *,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
) -> bool:
    counts = ai_digest_quota_counts(items)
    return (
        counts["domestic_model"] >= max(0, min_domestic_model_count)
        and counts["foreign_ai"] >= max(0, min_foreign_ai_count)
    )


def _can_drop_for_quota(
    item: AIUpdateItem,
    selected: list[AIUpdateItem],
    *,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
) -> bool:
    counts = ai_digest_quota_counts(selected)
    if ai_update_is_domestic_model_news(item) and counts["domestic_model"] <= min_domestic_model_count:
        return False
    if ai_update_is_foreign_ai_news(item) and counts["foreign_ai"] <= min_foreign_ai_count:
        return False
    return True


def _rebalance_vendor_concentration(
    ranked: list[AIUpdateItem],
    selected: list[AIUpdateItem],
    *,
    max_per_vendor: int,
    min_domestic_model_count: int,
    min_foreign_ai_count: int,
) -> list[AIUpdateItem]:
    if len(selected) < 2 or max_per_vendor < 1:
        return selected

    def source_key(item: AIUpdateItem) -> str:
        value = (item.vendor or item.source_name or "").strip().lower()
        return value or _selection_key(item)

    balanced = list(selected)
    selected_keys = {_selection_key(item) for item in balanced}
    counts = Counter(source_key(item) for item in balanced)
    for candidate in ranked:
        candidate_key = _selection_key(candidate)
        candidate_source = source_key(candidate)
        if candidate_key in selected_keys or counts[candidate_source] >= max_per_vendor:
            continue
        overloaded = {key for key, count in counts.items() if count > max_per_vendor}
        if not overloaded:
            break
        replace_index = next(
            (
                index
                for index in range(len(balanced) - 1, -1, -1)
                if source_key(balanced[index]) in overloaded
                and _meets_ai_digest_quotas(
                    [*balanced[:index], candidate, *balanced[index + 1 :]],
                    min_domestic_model_count=min_domestic_model_count,
                    min_foreign_ai_count=min_foreign_ai_count,
                )
            ),
            None,
        )
        if replace_index is None:
            continue
        removed = balanced[replace_index]
        removed_source = source_key(removed)
        selected_keys.discard(_selection_key(removed))
        counts[removed_source] -= 1
        balanced[replace_index] = candidate
        selected_keys.add(candidate_key)
        counts[candidate_source] += 1
    return balanced


def _select_with_ai_digest_quotas(
    ranked: list[AIUpdateItem],
    *,
    target_count: int,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
) -> list[AIUpdateItem]:
    target = max(1, int(target_count or 1))
    selected = list(ranked[:target])
    selected_keys = {_selection_key(item) for item in selected}

    def ensure_quota(predicate, minimum: int) -> None:
        nonlocal selected_keys
        minimum = max(0, int(minimum or 0))
        while sum(1 for item in selected if predicate(item)) < minimum:
            candidate = next(
                (
                    item
                    for item in ranked
                    if predicate(item) and _selection_key(item) not in selected_keys
                ),
                None,
            )
            if candidate is None:
                break
            replace_index = next(
                (
                    idx
                    for idx in range(len(selected) - 1, -1, -1)
                    if not predicate(selected[idx])
                    and _can_drop_for_quota(
                        selected[idx],
                        selected,
                        min_domestic_model_count=min_domestic_model_count,
                        min_foreign_ai_count=min_foreign_ai_count,
                    )
                ),
                None,
            )
            if replace_index is None:
                break
            selected_keys.discard(_selection_key(selected[replace_index]))
            selected[replace_index] = candidate
            selected_keys.add(_selection_key(candidate))

    ensure_quota(ai_update_is_domestic_model_news, min_domestic_model_count)
    ensure_quota(ai_update_is_foreign_ai_news, min_foreign_ai_count)
    selected = _rebalance_vendor_concentration(
        ranked,
        selected,
        max_per_vendor=2,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )

    selected_keys = {_selection_key(item) for item in selected}
    return [item for item in ranked if _selection_key(item) in selected_keys][:target]


def rank_ai_updates(
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    min_official_count: int = 6,
    allow_social_backfill: bool = True,
    max_age_days: int | None = None,
    now: datetime | date | None = None,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
) -> list[AIUpdateItem]:
    target = max(1, int(target_count or 10))
    relevant = [
        item
        for item in filter_recent_ai_updates(
            items,
            max_age_days=max_age_days,
            now=now,
            require_url=True,
        )
        if ai_update_is_relevant(item)
    ]
    deduped = _dedupe_updates(
        relevant
    )
    official_like = [item for item in deduped if item.source_type in {"official", "github"}]
    aggregator_like = [item for item in deduped if item.source_type in {"aggregator", "search"}]
    social_like = [item for item in deduped if item.source_type == "social"]

    official_like = sorted(official_like, key=_rank_sort_key, reverse=True)
    aggregator_like = sorted(aggregator_like, key=_rank_sort_key, reverse=True)
    social_like = sorted(social_like, key=_rank_sort_key, reverse=True)

    if len(official_like) >= min_official_count:
        official_ranked = _interleave_by_vendor_for_same_day(official_like, target_count=len(official_like))
        selected = _select_with_ai_digest_quotas(
            official_ranked,
            target_count=target,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )
        if _meets_ai_digest_quotas(
            selected,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        ):
            return selected
        if not allow_social_backfill:
            return selected

    if not allow_social_backfill:
        official_ranked = _interleave_by_vendor_for_same_day(official_like, target_count=len(official_like))
        return _select_with_ai_digest_quotas(
            official_ranked,
            target_count=target,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )

    official_ranked = _interleave_by_vendor_for_same_day(official_like, target_count=len(official_like))
    aggregator_ranked = _interleave_by_vendor_for_same_day(aggregator_like, target_count=len(aggregator_like))
    social_ranked = _interleave_by_vendor_for_same_day(social_like, target_count=len(social_like))
    combined_ranked = [*official_ranked, *aggregator_ranked, *social_ranked]
    return _select_with_ai_digest_quotas(
        combined_ranked,
        target_count=target,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
