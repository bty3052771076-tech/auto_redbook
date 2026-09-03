from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlsplit, urlunsplit

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
    # Do not include ``.`` in the separator: in ``GLM-5.3是`` the greedy
    # separator would otherwise consume the decimal point and parse only 5.
    r"[\s_-]*(?:v)?(?P<version>\d+(?:\.\d+)?)(?=$|[^A-Za-z0-9_])",
    flags=re.IGNORECASE,
)
_MODEL_VARIANT_RE = re.compile(
    r"\b(?:deepseek|glm|qwen|gpt|claude|gemini|gemma|doubao|seedream|kimi|minimax|ernie|llama|mistral)"
    r"[\s._-]*(?:v)?\d+(?:\.\d+)?[\s._-]+(?P<suffix>[a-z0-9]+)\b",
    flags=re.IGNORECASE,
)
_GENERIC_MODEL_VERSION_RE = re.compile(
    r"\b(?P<family>[A-Za-z]{2,})[-_ ]*(?:v)?(?P<version>\d+(?:\.\d+)?)(?:[-_ ]+(?P<suffix>[A-Za-z][A-Za-z0-9]*))?\b",
    flags=re.IGNORECASE,
)
_NON_MODEL_VERSION_FAMILIES = {
    "status",
    "issue",
    "issues",
    "post",
    "posts",
    "comment",
    "comments",
    "commit",
    "commits",
    "page",
    "pages",
    "item",
    "items",
    "update",
    "updates",
}
_MODEL_FAMILY_MERGED_SUFFIXES = {"pro", "max", "flash", "lite", "preview", "exp", "speciale"}
_MODEL_HISTORY_VARIANT_WORDS = {
    "air",
    "code",
    "coder",
    "flash",
    "instruct",
    "lite",
    "max",
    "mini",
    "preview",
    "pro",
    "reasoning",
    "speciale",
    "thinking",
    "turbo",
    "vision",
    "exp",
}
_EXPLICIT_EVENT_MARKERS = (
    ("model-hardware-standard", ("model hardware standard", "mhs")),
    ("openai-jalapeno", ("jalapeno", "jalapeño")),
)
AI_DIGEST_MAX_ITEMS_PER_SOURCE = 2
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
_MODEL_RELEASE_ACTION_MARKERS = (
    "release",
    "released",
    "launch",
    "launched",
    "introducing",
    "available",
    "general availability",
    "open weight",
    "open-weight",
    "open weights",
    "open-weights",
    "发布",
    "上线",
    "推出",
    "开放权重",
    "正式发布",
    "preview",
    "预览",
    "预览版",
    "公开预览",
    "内测",
)
_MODEL_LIFECYCLE_MARKERS = (
    "下线",
    "下架",
    "停用",
    "弃用",
    "迁移",
    "升级通知",
    "维护通知",
    "deprecat",
    "sunset",
    "retire",
    "retirement",
    "end of life",
    "migration notice",
    "upgrade notice",
    "service notice",
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


_EXPLICIT_EVENT_DATE_RE = re.compile(
    r"(?:"
    r"(?P<year>20\d{2})\s*(?:年|[-./])\s*"
    r"(?P<month>1[0-2]|0?[1-9])\s*(?:月|[-./])\s*"
    r"(?P<day>3[01]|[12]\d|0?[1-9])\s*日?"
    r"|"
    r"(?P<month_only>1[0-2]|0?[1-9])\s*月\s*"
    r"(?P<day_only>3[01]|[12]\d|0?[1-9])\s*日"
    r")"
)
_EVENT_DATE_ACTION_RE = re.compile(
    r"(?i)(?:上线|发布|发布于|推出|开放|开源|公测|可用|released?|launched?|available)"
)


def _explicit_model_event_datetime(item: AIUpdateItem) -> datetime | None:
    """Find an explicit model event date stated near a release action."""

    excerpt = re.sub(r"\s+", " ", item.raw_excerpt or "").strip()
    if not excerpt or not _contains_any_marker(
        _text_blob(item),
        ("模型", "model", "glm", "qwen", "gpt", "deepseek", "llm", "ai"),
    ):
        return None
    published = _parse_published_datetime(item.published_at)
    fallback_year = published.year if published is not None else datetime.now(BEIJING_TZ).year
    for match in _EXPLICIT_EVENT_DATE_RE.finditer(excerpt):
        context = excerpt[max(0, match.start() - 24) : min(len(excerpt), match.end() + 32)]
        if not _EVENT_DATE_ACTION_RE.search(context):
            continue
        try:
            event_date = datetime(
                int(match.group("year") or fallback_year),
                int(match.group("month") or match.group("month_only")),
                int(match.group("day") or match.group("day_only")),
                tzinfo=BEIJING_TZ,
            ).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        # A page can mention a future planned release or an expiry date. Only
        # let an explicit earlier event date override the page timestamp.
        if published is None or event_date <= published:
            return event_date
    return None


def ai_update_effective_published_datetime(item: AIUpdateItem) -> datetime | None:
    """Return the event date when the source states one, otherwise page date."""

    published = _parse_published_datetime(item.published_at)
    event_date = _explicit_model_event_datetime(item)
    return event_date or published


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


def _explicit_event_key(value: str) -> str:
    for event_key, markers in _EXPLICIT_EVENT_MARKERS:
        if _contains_any_marker(value, markers):
            return event_key
    return ""


def _stable_cross_source_event_key(item: AIUpdateItem) -> str:
    """Identify high-risk events whose wording and URLs vary by source."""
    blob = _text_blob(item)
    if (
        _contains_any_marker(blob, ("claude fable", "claude-fable"))
        and _contains_any_marker(blob, ("5.1", "5-1"))
        and _contains_any_marker(blob, ("anthropic", "claude"))
    ):
        # Anthropic's Fable announcement has appeared under multiple official
        # URLs, including a combined Fable/Mythos announcement page.
        return "anthropic-claude-fable-5-1-release"
    if _contains_any_marker(blob, ("牛来", "oxalpha")) and _contains_any_marker(
        blob,
        ("模型", "model", "glm", "智谱", "zhipu", "z.ai"),
    ):
        return "zhipu-niulai-model"
    if (
        _contains_marker(blob, "hy4")
        and _contains_any_marker(blob, ("腾讯", "混元", "tencent", "hunyuan"))
        and _contains_any_marker(
            blob,
            ("发布", "开源", "release", "released", "launch", "launched", "disclos"),
        )
    ):
        return "tencent-hunyuan-hy4-release"
    if (
        _contains_marker(blob, "openai")
        and _contains_marker(blob, "cursor")
        and _contains_any_marker(
            blob,
            (
                "停止",
                "终止",
                "断供",
                "wind down",
                "terminate",
                "termination",
                "shutoff",
                "end its commercial partnership",
            ),
        )
    ):
        return "openai-cursor-model-access"
    if (
        _contains_marker(blob, "hacker-opus")
        and _contains_any_marker(blob, ("anthropic",))
        and _contains_any_marker(
            blob,
            (
                "hugging face",
                "third-party infrastructure",
                "attack",
                "越界",
                "攻击",
            ),
        )
    ):
        # Anthropic's Hacker-Opus simulation can produce several social posts
        # describing the same test with different URLs and wording.
        return "anthropic-hacker-opus-simulation"
    return ""


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
    semantic_blob = " ".join(
        part
        for part in (item.title, item.summary, item.raw_excerpt, _url_topic_text(item.url))
        if part and part.strip()
    )
    # Some social feeds publish several URLs for one named standard or event.
    # Keep a stable event key so URL-level provenance does not defeat dedupe.
    explicit_event = _explicit_event_key(semantic_blob)
    if explicit_event:
        return f"event:{explicit_event}"
    stable_event = _stable_cross_source_event_key(item)
    if stable_event:
        return f"event:{stable_event}"
    normalized_excerpt = re.sub(r"https?://\S+", " ", item.raw_excerpt or "")
    normalized_excerpt = re.sub(r"\s+", " ", normalized_excerpt).strip().lower()
    if len(normalized_excerpt) >= 80:
        excerpt_hash = hashlib.sha256(normalized_excerpt.encode("utf-8")).hexdigest()[:24]
        return f"event:excerpt:{excerpt_hash}"
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


def _model_history_topic_key(item: AIUpdateItem) -> str:
    """Preserve named model variants for cross-digest history checks."""
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
        suffix_words: list[str] = []
        suffix_text = text[match.end() : match.end() + 64]
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", suffix_text):
            normalized = word.lower()
            if normalized not in _MODEL_HISTORY_VARIANT_WORDS:
                break
            suffix_words.append(normalized)
            if len(suffix_words) >= 4:
                break
        suffix_part = "-".join(suffix_words)
        return f"model:{family}-{version}{('-' + suffix_part) if suffix_part else ''}"
    return ""


def _history_event_key(item: AIUpdateItem) -> str:
    # ``raw_excerpt`` survives LLM rewriting and is the most stable event
    # descriptor when comparing a saved digest with a newly fetched source.
    blob = (item.raw_excerpt or item.title or item.summary or _text_blob(item)).lower()
    explicit_event = _explicit_event_key(blob)
    if explicit_event:
        return explicit_event
    if _contains_any_marker(blob, ("harness",)):
        return "harness"
    if _contains_any_marker(blob, ("billing", "pricing", "price", "计费", "收费", "价格")):
        return "billing"
    if _contains_any_marker(blob, ("api", "公测", "调用", "接口")):
        return "api"
    if _contains_any_marker(
        blob,
        ("release", "released", "launch", "launched", "introducing", "发布", "上线", "推出"),
    ):
        return "release"
    if _contains_any_marker(blob, ("update", "updated", "更新", "升级", "集成", "integrat")):
        return "update"
    return ai_update_category(item)


def ai_update_history_key(item: AIUpdateItem) -> str:
    """Return a stable event key for cross-digest history deduplication.

    A whole official release-notes page is not one event: several model
    updates may share its URL. Combine the trace URL with the model/topic key
    so the same release is blocked without suppressing a different update on
    that page.
    """
    stable_event = _stable_cross_source_event_key(item)
    if stable_event:
        return f"event:{stable_event}"
    topic = _model_history_topic_key(item) or _semantic_topic_key(item) or f"title:{item.title_key}"
    # A named model version identifies the release event across official
    # vendor pages, cloud catalogs, and mirrored documentation URLs.
    if topic.startswith(("model:", "event:")):
        return f"{topic}|event:{_history_event_key(item)}"
    normalized_excerpt = re.sub(r"https?://\S+", " ", item.raw_excerpt or "")
    normalized_excerpt = re.sub(r"\s+", " ", normalized_excerpt).strip().lower()
    if len(normalized_excerpt) >= 80:
        excerpt_hash = hashlib.sha256(normalized_excerpt.encode("utf-8")).hexdigest()[:24]
        return f"event:excerpt:{excerpt_hash}"
    raw_url = item.normalized_url or ""
    if raw_url:
        parsed = urlsplit(raw_url)
        path = unquote(parsed.path or "/").rstrip("/") or "/"
        base = urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.query,
                "",
            )
        )
        path_parts = [part for part in path.split("/") if part]
        generic_pages = {
            "announce",
            "blog",
            "changelog",
            "news",
            "research",
            "updates",
        }
        if len(path_parts) >= 2 and path_parts[-1].lower() not in generic_pages:
            # A specific article URL is a stronger event identity than a
            # rewritten headline. Listing pages retain the semantic topic
            # suffix because one page can contain several updates.
            return f"{base}|event:url"
        # Listing/announcement pages often expose the same update again with
        # a different LLM-written title. The source excerpt is the stable
        # event identity in that case; keep the URL as a namespace so two
        # unrelated pages with similar wording do not collide.
        raw_excerpt = re.sub(r"\s+", " ", (item.raw_excerpt or "").strip().lower())
        if raw_excerpt:
            excerpt_hash = hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest()[:24]
            return f"{base}|event:text:{excerpt_hash}"
    else:
        base = f"title:{item.title_key}"
    return f"{base}|{topic}"


def _trace_url(item: AIUpdateItem) -> str:
    if item.normalized_url:
        return item.normalized_url
    for url in item.evidence_urls or []:
        text = (url or "").strip()
        if text:
            return text
    return ""


_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(?:ai)?动态\d*$|"
    r"^(?:.+?)(?:发布ai动态|披露ai产品变化|公开了与ai有关的动态)$",
    flags=re.IGNORECASE,
)
_GENERIC_TITLE_SUFFIXES = (
    "发布新进展",
    "披露AI产品变化",
    "AI产品披露AI产品变化",
)
_GENERIC_CHANGE_TITLE_RE = re.compile(
    r"(?:披露|公开|宣布)[^。！？\n]{0,80}(?:AI产品变化|产品变化)$",
    flags=re.IGNORECASE,
)


def ai_update_quality_issues(item: AIUpdateItem) -> tuple[str, ...]:
    """Return deterministic quality issues before an item reaches the LLM.

    A source can be recent and technically related to AI while still carrying
    only a label or navigation text. Such records are not useful editorial
    material and tend to become ``动态3``/``披露产品变化`` after rewriting.
    """

    issues: list[str] = []
    if not _trace_url(item):
        issues.append("missing_url")

    title = re.sub(r"\s+", "", item.title or "")
    title_lower = title.lower()
    if not title:
        issues.append("missing_title")
    if title and _PLACEHOLDER_TITLE_RE.fullmatch(title):
        issues.append("placeholder_title")
    if title and _GENERIC_CHANGE_TITLE_RE.search(title):
        issues.append("generic_title")

    summary = re.sub(r"\s+", " ", item.summary or "").strip()
    excerpt = re.sub(r"\s+", " ", item.raw_excerpt or "").strip()
    title_key = _normalize_token(title)
    content_keys = {
        _normalize_token(value)
        for value in (summary, excerpt)
        if value
    }
    has_named_model = bool(
        _MODEL_FAMILY_VERSION_RE.search(
            " ".join((item.title, item.product, _url_topic_text(item.url)))
        )
    )
    is_compact_official_release = item.source_type in {"official", "github"} and has_named_model
    if not summary and not excerpt:
        issues.append("contentless")
    elif title_key and content_keys and content_keys <= {title_key} and not is_compact_official_release:
        issues.append("contentless")
    elif any(title_lower.endswith(suffix.lower()) for suffix in _GENERIC_TITLE_SUFFIXES):
        # Keep a generic feed headline only when its excerpt has enough facts
        # for the generator to derive a concrete subject.
        if len(excerpt or summary) < 48 or not has_named_model:
            issues.append("contentless")

    return tuple(dict.fromkeys(issues))


def _source_priority(item: AIUpdateItem) -> int:
    return {"official": 4, "github": 4, "aggregator": 2, "search": 2, "social": 1}.get(item.source_type, 0)


def ai_update_attention_score(item: AIUpdateItem) -> float:
    score = float(item.confidence_score or 0.0)
    score += min(0.15, len(item.evidence_urls or []) * 0.03)
    if item.verification_status in {"aggregator_confirmed", "social_confirmed"}:
        score += 0.08
    score += _source_priority(item) * 0.005
    return round(score, 6)


def _has_explicit_model_release(item: AIUpdateItem) -> bool:
    """Return whether the headline identifies a model version being released."""
    headline_fields = f"{item.title} {item.product}".strip().lower()
    url_topic = _url_topic_text(item.url).lower()
    headline_blob = f"{headline_fields} {url_topic}".strip()
    release_evidence_blob = f"{headline_blob} {item.summary} {item.raw_excerpt}".lower()
    has_named_model_version = bool(_MODEL_FAMILY_VERSION_RE.search(headline_fields))
    if not has_named_model_version:
        generic_match = _GENERIC_MODEL_VERSION_RE.search(headline_fields)
        if generic_match and generic_match.group("family").lower() not in _NON_MODEL_VERSION_FAMILIES:
            has_named_model_version = True
    # Search backfills may carry the model only in a slug (for example,
    # ``tencent-hunyuan-hy4-preview-open-source``). A social URL's numeric
    # ``status/209...`` identifier must never count as a model version.
    if not has_named_model_version and not re.search(r"\b(?:status|issues?|comments?|commits?)/?\b", url_topic):
        generic_match = _GENERIC_MODEL_VERSION_RE.search(url_topic)
        if generic_match and generic_match.group("family").lower() not in _NON_MODEL_VERSION_FAMILIES:
            has_named_model_version = True
    return has_named_model_version and _contains_any_marker(
        release_evidence_blob,
        _MODEL_RELEASE_ACTION_MARKERS,
    )


def ai_update_is_lifecycle_notice(item: AIUpdateItem) -> bool:
    """Identify notices about an existing service lifecycle, not a new release.

    A genuine release may mention migration or an upgrade path, so lifecycle
    markers only win when the item does not also contain an explicit named
    model release action.
    """
    blob = _text_blob(item).lower()
    return _contains_any_marker(blob, _MODEL_LIFECYCLE_MARKERS) and not _has_explicit_model_release(item)


def ai_update_is_non_model_infrastructure_notice(item: AIUpdateItem) -> bool:
    """Reject generic cloud/database notices from the AI-news impact pool."""
    headline_blob = " ".join(
        part.strip()
        for part in (item.title, item.product, _url_topic_text(item.url))
        if part and part.strip()
    ).lower()
    return _contains_any_marker(headline_blob, _NON_MODEL_INFRASTRUCTURE_MARKERS) and not _contains_any_marker(
        headline_blob,
        ("model", "模型", "大模型", "llm", "vlm"),
    )


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
    if _has_explicit_model_release(item):
        return "model_release"
    if _contains_any_marker(
        headline_blob,
        ("model update", "model updates", "model change", "model changes", "模型更新", "模型变化", "模型升级"),
    ):
        return "technical_tool"
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
    if ai_update_is_lifecycle_notice(item) or ai_update_is_non_model_infrastructure_notice(item):
        return False
    category = ai_update_category(item)
    if category not in {"model_release", "benchmark", "technical_tool", "research"}:
        return False
    bounded_threshold = min(100.0, max(0.0, float(threshold)))
    return ai_update_impact_score(item) >= bounded_threshold


def ai_update_is_relevant(item: AIUpdateItem) -> bool:
    """Reject query matches that mention AI only incidentally in article text."""
    if ai_update_is_non_model_infrastructure_notice(item):
        return False
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
        # Official release-note pages often expose a compact card whose title,
        # summary and excerpt are intentionally identical (for example,
        # "GLM-5.3"). Keep it when the card names a concrete model version;
        # generic product-only cards such as "Qwen Code" remain noise.
        headline_blob = " ".join(
            part.strip()
            for part in (item.title, item.product, _url_topic_text(item.url))
            if part and part.strip()
        )
        has_named_model_version = bool(_MODEL_FAMILY_VERSION_RE.search(headline_blob))
        if not (
            item.source_type in {"official", "github"}
            and has_named_model_version
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
            published = ai_update_effective_published_datetime(item)
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
    stable_event_keys: dict[str, str] = {}
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
        stable_event = _stable_cross_source_event_key(item)
        stable_lookup_key = f"event:{stable_event}" if stable_event else ""
        title_key = item.title_key
        semantic_key = _semantic_topic_key(item)
        # Generic categories such as ``topic:benchmark`` are not event
        # identities. Do not merge them at all; URL/title keys still remove
        # exact duplicates, while explicit model/product keys can continue to
        # merge mirrored announcements across vendors.
        generic_topic_keys = {
            "topic:benchmark",
            "topic:bench",
            "topic:eval",
            "topic:model",
            "topic:models",
            "topic:tool",
            "topic:tools",
            "topic:update",
            "topic:updates",
        }
        semantic_lookup_key = "" if semantic_key in generic_topic_keys else semantic_key
        existing_key = title_keys.get(title_key)
        if not existing_key and semantic_lookup_key:
            existing_key = topic_keys.get(semantic_lookup_key)
        if not existing_key and stable_lookup_key:
            existing_key = stable_event_keys.get(stable_lookup_key)
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
            if semantic_lookup_key:
                topic_keys[semantic_lookup_key] = existing_key
            if stable_lookup_key:
                stable_event_keys[stable_lookup_key] = existing_key
            continue
        if key in by_key:
            winner = _prefer_item(by_key[key], item)
            loser = item if winner is by_key[key] else by_key[key]
            by_key[key] = _merge_items(winner, loser)
            continue
        by_key[key] = item
        if title_key:
            title_keys[title_key] = key
        if semantic_lookup_key:
            topic_keys[semantic_lookup_key] = key
        if stable_lookup_key:
            stable_event_keys[stable_lookup_key] = key
    return list(by_key.values())


def dedupe_ai_updates(items: list[AIUpdateItem]) -> list[AIUpdateItem]:
    return _dedupe_updates(items)


def _normalize_source_label(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[|｜·•:/：]+", " ", text)
    text = re.sub(
        r"\b(?:official|official site|official blog|blog|newsroom|release notes|news|官网|官方|博客|新闻)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def ai_update_source_key(item: AIUpdateItem) -> str:
    """Return the canonical source/vendor key used by every selection stage."""

    label = _normalize_source_label(item.vendor or item.source_name)
    if label:
        return label
    host = (urlsplit(item.url or "").hostname or "").lower().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def ai_digest_source_counts(items: list[AIUpdateItem]) -> dict[str, int]:
    return dict(Counter(ai_update_source_key(item) for item in items))


def _vendor_key(item: AIUpdateItem) -> str:
    return ai_update_source_key(item)


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
        int(_has_explicit_model_release(item)),
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
        return ai_update_source_key(item)

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
    max_items_per_source: int | None = AI_DIGEST_MAX_ITEMS_PER_SOURCE,
) -> list[AIUpdateItem]:
    target = max(1, int(target_count or 1))
    source_limit = None if max_items_per_source is None else max(1, int(max_items_per_source))
    selected: list[AIUpdateItem] = []
    source_counts: Counter[str] = Counter()
    for item in ranked:
        if len(selected) >= target:
            break
        key = ai_update_source_key(item)
        if source_limit is not None and source_counts[key] >= source_limit:
            continue
        selected.append(item)
        source_counts[key] += 1
    selected_keys = {_selection_key(item) for item in selected}

    def can_add(item: AIUpdateItem) -> bool:
        return (
            _selection_key(item) not in selected_keys
            and (source_limit is None or source_counts[ai_update_source_key(item)] < source_limit)
        )

    def ensure_quota(predicate, minimum: int) -> None:
        nonlocal selected_keys
        minimum = max(0, int(minimum or 0))
        while sum(1 for item in selected if predicate(item)) < minimum:
            candidate = next(
                (
                    item
                    for item in ranked
                    if predicate(item) and can_add(item)
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
            removed = selected[replace_index]
            removed_source = ai_update_source_key(removed)
            candidate_source = ai_update_source_key(candidate)
            if source_limit is not None and source_counts[candidate_source] >= source_limit:
                break
            selected_keys.discard(_selection_key(removed))
            source_counts[removed_source] -= 1
            selected[replace_index] = candidate
            selected_keys.add(_selection_key(candidate))
            source_counts[candidate_source] += 1

    ensure_quota(ai_update_is_domestic_model_news, min_domestic_model_count)
    ensure_quota(ai_update_is_foreign_ai_news, min_foreign_ai_count)
    if source_limit is not None:
        selected = _rebalance_vendor_concentration(
            ranked,
            selected,
            max_per_vendor=source_limit,
            min_domestic_model_count=min_domestic_model_count,
            min_foreign_ai_count=min_foreign_ai_count,
        )

    selected_keys = {_selection_key(item) for item in selected}
    output: list[AIUpdateItem] = []
    output_counts: Counter[str] = Counter()
    for item in ranked:
        if _selection_key(item) not in selected_keys:
            continue
        source_key = ai_update_source_key(item)
        if source_limit is not None and output_counts[source_key] >= source_limit:
            continue
        output.append(item)
        output_counts[source_key] += 1
        if len(output) >= target:
            break
    return output


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
    max_items_per_source: int | None = AI_DIGEST_MAX_ITEMS_PER_SOURCE,
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
        if ai_update_is_relevant(item) and not ai_update_quality_issues(item)
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
            max_items_per_source=max_items_per_source,
        )
        if len(selected) >= target and _meets_ai_digest_quotas(
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
            max_items_per_source=max_items_per_source,
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
        max_items_per_source=max_items_per_source,
    )
