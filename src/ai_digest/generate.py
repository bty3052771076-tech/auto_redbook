from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import unquote, urlsplit

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from src.config import LLMConfig
from src.llm.generate import _temperature_kwargs
from src.text_integrity import simplify_common_chinese

from .models import AIDigestBrief, AIUpdateItem
from .rank import (
    AI_DIGEST_MAX_ITEMS_PER_SOURCE,
    ai_update_impact_score,
    ai_update_is_high_impact,
    ai_update_history_key,
    ai_update_source_key,
)


# Keep this aligned with the workflow-wide LLM ceiling.  In particular, some
# Ark reasoning models can consume a substantial output budget before emitting
# their final answer, so a small ceiling may surface as an empty response.
AI_DIGEST_LLM_MAX_TOKENS = 60000
AI_DIGEST_LLM_TIMEOUT_SECONDS = 240
AI_DIGEST_BODY_LIMIT = 1000
_BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_GENERIC_AI_DIGEST_MARKERS = (
    "发布AI动态",
    "公开了与AI有关的动态",
    "公开了与相关AI产品有关的AI动态",
    "具体链接已保存在本地元数据",
    "当前摘要仅基于原始标题和摘录整理",
    "披露AI产品变化",
    "当前可核实信息以原始标题",
)
_LOW_INFORMATION_TITLE_MARKERS = (
    "发布新进展",
    "AI产品发布新进展",
    "披露AI产品变化",
    "AI产品披露AI产品变化",
)
_GENERIC_CHANGE_TITLE_RE = re.compile(
    r"(?:披露|公开|宣布|发布|推出|上线)[^。！？\n]{0,80}(?:AI产品变化|产品变化|AI动态|新进展)$",
    flags=re.IGNORECASE,
)


def cap_ai_digest_items_by_source(
    items: Iterable[AIUpdateItem],
    *,
    target_count: int | None = None,
) -> list[AIUpdateItem]:
    """Keep the first ranked items while enforcing the hard source cap."""

    output: list[AIUpdateItem] = []
    counts: Counter[str] = Counter()
    limit = None if target_count is None else max(0, int(target_count))
    for item in items:
        if limit is not None and len(output) >= limit:
            break
        source_key = ai_update_source_key(item)
        if counts[source_key] >= AI_DIGEST_MAX_ITEMS_PER_SOURCE:
            continue
        output.append(item)
        counts[source_key] += 1
    return output
_AI_CLAIM_NAMES = (
    "openai",
    "anthropic",
    "claude",
    "gpt",
    "xai",
    "grok",
    "suno",
    "qwen",
    "deepseek",
    "glm",
    "zhipu",
    "doubao",
    "seedream",
    "kimi",
    "moonshot",
    "gemini",
    "gemma",
    "google",
    "deepmind",
    "meta",
    "llama",
    "mistral",
    "minimax",
    "nvidia",
    "hugging face",
    "cohere",
    "perplexity",
    "ernie",
    "baidu",
)
_AI_MODEL_VERSION_RE = re.compile(
    r"(?<![a-z0-9])(?:hy|gpt|claude|qwen|deepseek|glm|doubao|seedream|kimi|gemini|gemma|"
    r"llama|mistral|minimax|ernie)[-_. ]?(?:v)?\d+(?:\.\d+)*(?:[-_. ]?[a-z0-9]+)?(?:\s+api)?(?![a-z0-9])",
    flags=re.IGNORECASE,
)
_AI_CLAIM_NUMBER_RE = re.compile(r"(?<![a-z0-9])\d+(?:\.\d+)?(?:[tkmb]|%|％)?(?![a-z0-9])", re.IGNORECASE)
_EN_DETAIL_TERMS: tuple[tuple[str, str], ...] = (
    ("browser automation", "浏览器自动化"),
    ("stricter terminal permissions", "更严格的终端权限"),
    ("terminal permissions", "终端权限"),
    ("background agents", "后台智能体"),
    ("pull request tracking", "拉取请求跟踪"),
    ("pull requests", "拉取请求"),
    ("developer tools", "开发者工具"),
    ("agent workflows", "智能体工作流"),
    ("api features", "API功能"),
    ("multimodal", "多模态能力"),
    ("reasoning", "推理能力"),
    ("code generation", "代码生成"),
    ("open source", "开源"),
    ("voice", "语音能力"),
    ("vision", "视觉能力"),
    ("web", "网页端"),
    ("benchmark", "评测基准"),
    ("bench", "评测基准"),
    ("genomics", "基因组学"),
    ("biology", "生物科研"),
    ("adoption", "用户采用情况"),
    ("infrastructure", "基础设施"),
    ("core dump", "故障调试"),
    ("debug", "故障调试"),
    ("specialization", "专业化模型"),
)


def _today_date() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _looks_generic_ai_digest_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return any(marker.replace(" ", "") in compact for marker in _GENERIC_AI_DIGEST_MARKERS) or bool(
        _GENERIC_CHANGE_TITLE_RE.search(compact)
    )


def _is_low_information_ai_digest_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(re.search(r"(?i)AI\s*AI", text or "")) or _looks_generic_ai_digest_text(text) or any(
        marker.replace(" ", "") in compact for marker in _LOW_INFORMATION_TITLE_MARKERS
    )


def _has_chinese_title_context(text: str) -> bool:
    # A short Chinese action phrase is enough to establish that the remaining
    # English tokens are likely product or company names, not untranslated prose.
    return len(_CJK_RE.findall(text or "")) >= 2


def _source_text(item: AIUpdateItem) -> str:
    return " ".join(
        part.strip()
        for part in (item.title, item.summary, item.raw_excerpt)
        if part and part.strip()
    )


def _clean_subject(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip(" -:：,，.。")
    text = re.split(
        r"\b(?:with|adds?|adding|for developers|lets?|from|and track|that|which|featuring)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" -:：,，.。")
    return text[:48].strip()


def _norm_subject(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value or "", flags=re.IGNORECASE).lower()


def _slug_words_from_url(url: str) -> list[str]:
    try:
        parts = [unquote(part) for part in urlsplit(url or "").path.split("/") if part.strip()]
    except ValueError:
        return []
    if not parts:
        return []
    candidates = parts[-2:] if parts[-1].lower() in {"case-studies", "index", "blog", "post"} and len(parts) >= 2 else parts[-1:]
    raw = " ".join(candidates)
    raw = re.sub(r"[_\-]+", " ", raw)
    words = []
    stop = {"blog", "blogs", "index", "news", "post", "posts", "article", "articles", "zh", "cn", "en"}
    for word in re.findall(r"[A-Za-z0-9]+", raw):
        lower = word.lower()
        if lower in stop or lower.isdigit():
            continue
        words.append(word)
    return words


def _format_slug_word(word: str) -> str:
    special = {
        "ai": "AI",
        "api": "API",
        "gpt": "GPT",
        "glm": "GLM",
        "llm": "LLM",
        "os": "OS",
        "chatgpt": "ChatGPT",
        "genebench": "GeneBench",
        "discoformer": "DiScoFormer",
    }
    lower = word.lower()
    if lower in special:
        return special[lower]
    if any(ch.isdigit() for ch in word):
        return word[:1].upper() + word[1:]
    return word[:1].upper() + word[1:].lower()


def _slug_subject_from_url(item: AIUpdateItem) -> str:
    words = _slug_words_from_url(item.url)
    if not words:
        return ""
    subject = " ".join(_format_slug_word(word) for word in words)
    return _clean_subject(subject)


def _subject_is_only_source(subject: str, item: AIUpdateItem) -> bool:
    norm = _norm_subject(subject)
    if not norm:
        return True
    source_norms = {
        _norm_subject(item.vendor),
        _norm_subject(item.source_name),
        _norm_subject(item.product),
    }
    source_norms.discard("")
    return norm in source_norms or norm in {"ai", "update", "updates"}


def is_ai_digest_source_label_title(value: str, item: AIUpdateItem) -> bool:
    """Reject a source label or placeholder masquerading as an event title."""

    compact = _norm_subject(value)
    if not compact:
        return True
    if re.fullmatch(r"(?:ai)?动态\d*", compact, flags=re.IGNORECASE):
        return True
    labels = {
        _norm_subject(item.source_name),
        _norm_subject(item.vendor),
        _norm_subject(item.product),
    }
    labels.discard("")
    if compact in labels:
        return True
    for suffix in ("发布新进展", "披露AI产品变化", "AI产品披露AI产品变化"):
        if compact.endswith(suffix):
            base = compact[: -len(suffix)]
            if base in labels:
                return True
    return False


def _english_subject(item: AIUpdateItem) -> str:
    product = _clean_subject(item.product)
    if product and not _subject_is_only_source(product, item):
        return product
    patterns = (
        (
            r"\b(?:GPT|GLM|Qwen|Claude|Codex|Gemini|Kimi|Doubao|Seedream|ERNIE|Llama|Mistral|DeepSeek|MiniMax)[A-Za-z0-9.\- ]{0,64}",
            re.IGNORECASE,
        ),
        (r"\b[A-Z][A-Za-z0-9.\-]+(?:\s+[A-Z][A-Za-z0-9.\-]+){0,4}\b", 0),
    )
    for raw in (item.raw_excerpt or "", _source_text(item)):
        for pattern, flags in patterns:
            match = re.search(pattern, raw, flags=flags)
            if not match:
                continue
            subject = _clean_subject(match.group(0))
            if (
                len(subject) >= 3
                and subject.lower() not in {"the", "this", "openai", "anthropic", "microsoft"}
                and not re.fullmatch(r"[A-Za-z0-9_-]{28,}", subject)
                and not _subject_is_only_source(subject, item)
            ):
                return subject
    slug_subject = _slug_subject_from_url(item)
    if slug_subject:
        return slug_subject
    return _clean_subject(item.product or item.vendor or item.source_name or "AI")


def _detail_terms_from_item(item: AIUpdateItem) -> list[str]:
    raw = f"{_source_text(item)} {_slug_subject_from_url(item)}"
    lower = raw.lower()
    details: list[str] = []
    for needle, label in _EN_DETAIL_TERMS:
        if needle in lower and label not in details:
            details.append(label)
    for marker in ("多模态", "推理", "代码", "智能体", "浏览器", "网页", "开源", "语音", "视觉", "API"):
        if marker in raw and marker not in details:
            details.append(marker)
    return details[:4]


_AI_PROPER_ENGLISH_WORDS = {
    "ai",
    "api",
    "active",
    "chatgpt",
    "claude",
    "codex",
    "deepseek",
    "doubao",
    "embedding",
    "face",
    "flash",
    "gemini",
    "glm",
    "gpt",
    "hardware",
    "hugging",
    "incident",
    "kimi",
    "llm",
    "luma",
    "minimax",
    "model",
    "moe",
    "next",
    "ngram",
    "omni",
    "openai",
    "open",
    "report",
    "research",
    "qwen",
    "runway",
    "standard",
    "seedream",
    "token",
    "transcribe",
    "video",
    "weight",
}
_GENERIC_FALLBACK_PRODUCTS = {"", "ai", "api", "model", "models", "tool", "tools", "update", "updates"}


def _has_untranslated_english_phrase(text: str) -> bool:
    value = text or ""
    if re.search(r"\b(?:AI|API|LLM)\s+[a-z](?=[\u4e00-\u9fff]|$)", value):
        return True
    words = [word.lower() for word in re.findall(r"[A-Za-z]{4,}", value)]
    untranslated = [word for word in words if word not in _AI_PROPER_ENGLISH_WORDS]
    return len(untranslated) >= 2 or any(len(word) >= 8 for word in untranslated)


def _has_truncated_english_tail(text: str) -> bool:
    """Detect a one-letter English fragment glued to a Chinese clause."""
    return bool(re.search(r"(?<![A-Za-z0-9])[a-z](?=[\u4e00-\u9fff])", text or ""))


def _social_concrete_fallback_title(item: AIUpdateItem) -> str:
    """Turn known social-post facts into a publishable, non-generic title."""

    raw = (item.raw_excerpt or "").lower()
    if "scale this research model" in raw and "researcher" in raw and "access" in raw:
        return "Anthropic扩大研究模型访问"
    if "studies are ongoing" in raw and "claude" in raw and "metr" in raw:
        return "Anthropic推进Claude影响研究"
    if "safety scores" in raw and (
        "alignment failures" in raw or "without degrading capabilities" in raw
    ):
        return "Claude安全评测结果更新"
    if "model hardware standard" in raw and ("lab" in raw or "manufacturing" in raw):
        return "Anthropic发布模型硬件标准"
    if (
        "hacker-opus" in raw
        and "reward" in raw
        and ("misaligned" in raw or "grader" in raw)
    ):
        return "Anthropic披露Hacker-Opus奖励寻优风险"
    if "coding agents" in raw and "productivity" in raw:
        return "编程智能体生产力研究进行中"
    if (
        "claude models" in raw
        and "unauthorized access" in raw
        and "real systems" in raw
        and "without safeguards" in raw
    ):
        return "Anthropic披露Claude网络安全评估事件"
    return ""


def _social_concrete_fallback_summary(item: AIUpdateItem) -> str:
    """Translate only facts with stable evidence in a social excerpt.

    A source post without a recognized fact is intentionally left for the
    caller to reject or replace; inventing ``披露AI产品变化`` is worse than
    publishing fewer items.
    """

    raw = (item.raw_excerpt or "").lower()
    if "scale this research model" in raw and "researcher" in raw and "access" in raw:
        return "Anthropic宣布扩大该研究模型的研究访问范围，并邀请研究人员申请工具访问资格。"
    if "studies are ongoing" in raw and "claude" in raw and "metr" in raw:
        return "Anthropic表示两项研究仍在进行：一项关注Claude行为与用户使用AI的感受，另一项评估编程智能体对实际生产力的影响。"
    if "safety scores" in raw and (
        "alignment failures" in raw or "without degrading capabilities" in raw
    ):
        return "Anthropic介绍一项Claude对齐研究：在10个安全对齐失败案例中，Claude提升了安全评分，同时没有降低能力表现。"
    if "model hardware standard" in raw and ("lab" in raw or "manufacturing" in raw):
        return "Anthropic发布模型硬件标准，内容覆盖AI模型训练和部署所需的实验室及制造设备。"
    if (
        "hacker-opus" in raw
        and "reward" in raw
        and ("misaligned" in raw or "grader" in raw)
    ):
        return (
            "Anthropic称，Hacker-Opus会在追逐奖励时采取多种失向行为；"
            "在没有明确评分者的评估中，该模型仍保持对齐。"
        )
    if "coding agents" in raw and "productivity" in raw:
        return "相关研究正在评估编程智能体对实际生产力的影响，当前仍处于研究阶段。"
    if (
        "claude models" in raw
        and "unauthorized access" in raw
        and "real systems" in raw
        and "without safeguards" in raw
    ):
        return (
            "Anthropic表示，7月披露的三起事件中，未配备防护的Claude模型在网络安全评估中"
            "取得了对真实系统的未授权访问；新文章介绍了后续加固措施。"
        )
    return ""


def _github_status_fallback_title(item: AIUpdateItem) -> str:
    raw = _source_text(item).lower()
    if (
        "copilot" in raw
        and "higher rate of errors" in raw
        and "resolved" in raw
        and ("model provider" in raw or "model providers" in raw)
    ):
        return "GitHub Copilot模型错误率升高后恢复"
    return ""


def _github_status_fallback_summary(item: AIUpdateItem) -> str:
    raw = _source_text(item).lower()
    if (
        "copilot" in raw
        and "higher rate of errors" in raw
        and "resolved" in raw
        and ("model provider" in raw or "model providers" in raw)
    ):
        return (
            "GitHub Status称，8月31日Copilot的AI模型提供商出现错误率升高，影响部分OpenAI模型；"
            "状态页显示问题已缓解并恢复，后续将发布详细根因分析。"
        )
    return ""


def _fallback_chinese_subject(item: AIUpdateItem) -> str:
    raw = _source_text(item)
    lower = raw.lower()
    model_match = _AI_MODEL_VERSION_RE.search(raw)
    if model_match:
        subject = _clean_subject(model_match.group(0))
        # The version matcher can include the first character of an English
        # sentence tail (for example, "API i" from "API is now...").
        subject = re.sub(r"\s+[A-Za-z]$", "", subject).strip()
        product = _clean_subject(item.product)
        if product:
            missing_words = [
                word
                for word in product.split()
                if word.lower() not in subject.lower().split()
            ]
            if missing_words:
                subject = _clean_subject(f"{subject} {' '.join(missing_words)}")
        return subject
    product = _clean_subject(item.product)
    if product and product.lower() not in _GENERIC_FALLBACK_PRODUCTS:
        return product
    if "mathemat" in lower:
        return "数学AI研究"
    # Social posts often contain a long English sentence but no Chinese
    # headline. Prefer a complete, known product name over the first English
    # clause, which may end in the middle of a word or URL token.
    for name in (
        "DeepSeek",
        "ChatGPT",
        "Claude",
        "Gemini",
        "Qwen",
        "GLM",
        "GPT",
        "Kimi",
        "Llama",
        "OpenAI",
    ):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", raw, flags=re.IGNORECASE):
            if any(
                marker in lower
                for marker in ("发布", "上线", "推出", "新进展", "release", "released", "launch", "launched")
            ):
                return f"{name}发布新进展"
            return name
    english_subject = _english_subject(item)
    if english_subject:
        subject_lower = english_subject.lower()
        if re.match(
            r"^(?:gpt|glm|qwen|claude|codex|gemini|gemma|deepseek|doubao|seedream|"
            r"kimi|minimax|ernie|llama|mistral|cerebras|suno|voice)\b",
            subject_lower,
        ):
            return english_subject
        proper_tokens = english_subject.split()
        raw_excerpt = (item.raw_excerpt or "").strip()
        is_named_release = bool(
            len(proper_tokens) == 1
            and re.match(
                rf"^{re.escape(english_subject)}\s+(?:introduces|launches|releases|unveils)\b",
                raw_excerpt,
                flags=re.IGNORECASE,
            )
        )
        has_product_shape = bool(
            any(char.isdigit() for char in english_subject)
            or re.search(r"[a-z][A-Z]", english_subject)
            or any(token.isupper() and len(token) >= 2 for token in proper_tokens)
        )
        if len(proper_tokens) <= 2 and (is_named_release or has_product_shape) and re.fullmatch(
            r"[A-Z][A-Za-z0-9.\-]*(?:\s+[A-Z0-9][A-Za-z0-9.\-]*)?",
            english_subject,
        ):
            return english_subject
    source = _clean_subject(item.vendor or item.source_name or "AI")
    if not source or source.lower() in {"ai", "ai hot", "x"}:
        for name in ("Suno", "Cerebras", "OpenAI", "Anthropic", "Google", "DeepSeek"):
            if re.search(rf"\b{re.escape(name)}\b", raw, flags=re.IGNORECASE):
                source = name
                break
    source = source or "AI"
    if "mathemat" in lower:
        topic = "数学AI研究"
    elif "robot" in lower:
        topic = "机器人AI"
    elif "video" in lower or "cinematic" in lower:
        topic = "视频生成"
    elif "workforce" in lower or "enterprise" in lower:
        topic = "企业AI应用"
    elif "scientific computing" in lower or "genomics" in lower:
        topic = "科研智能体"
    elif "agent" in lower:
        topic = "智能体"
    elif "model" in lower or "release" in lower or "launch" in lower:
        topic = "AI模型"
    elif "api" in lower:
        topic = "AI接口"
    else:
        topic = "AI产品"
    return f"{source}{topic}"[:22]


def _title_with_action(subject: str, action: str, *, limit: int = 28) -> str:
    clean_action = re.sub(r"\s+", " ", action or "").strip()
    clean_subject = re.sub(r"\s+", " ", subject or "").strip()
    subject_limit = max(1, limit - len(clean_action))
    clean_subject = clean_subject[:subject_limit].rstrip("，,。；;：: -")
    return f"{clean_subject}{clean_action}"[:limit]


def _specific_chinese_excerpt_title(item: AIUpdateItem, *, subject: str) -> str:
    excerpt = re.sub(r"\s+", " ", item.raw_excerpt or "").strip()
    if not excerpt or not _has_cjk(excerpt):
        return ""
    lower = excerpt.lower()
    concise_subject = re.sub(r"AI产品$", "", subject or "").strip() or subject
    multimodal_release = re.search(
        r"(?P<vendor>[\u4e00-\u9fff]{2,10})发布开源(?:多模态)?模型\s*"
        r"(?P<model>[A-Za-z][A-Za-z0-9.\-]*(?:\s+[A-Z0-9][A-Za-z0-9.\-]*){0,2})",
        excerpt,
    )
    if multimodal_release:
        return _title_with_action(
            f"{multimodal_release.group('vendor')}{multimodal_release.group('model').strip()}",
            "开源模型发布",
        )
    open_new_release = re.search(
        r"开源新版\s*(?P<model>[A-Za-z][A-Za-z0-9.\-]*(?:\s+[A-Z0-9][A-Za-z0-9.\-]*){0,2})",
        excerpt,
    )
    if open_new_release:
        return _title_with_action(open_new_release.group("model").strip(), "正式开源")
    paper_release = re.search(
        r"(?P<vendor>[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff ]{0,16})\s*发布《(?P<paper>[^》]{2,40})》论文",
        excerpt,
    )
    if paper_release:
        vendor = re.sub(r"\s+", " ", paper_release.group("vendor")).strip()
        paper = paper_release.group("paper").strip()
        if paper.lower() == "the agent access model":
            paper = "智能体访问模型"
        return _title_with_action(f"{vendor}{paper}", "论文发布")
    if "评测服务" in excerpt and ("全面可用" in excerpt or "（ga）" in lower or "(ga)" in lower):
        if "gemini" in lower:
            concise_subject = "Gemini智能体"
        return _title_with_action(concise_subject, "评测服务正式上线")
    if "siggraph" in lower and "数字人" in excerpt:
        return _title_with_action(concise_subject, "数字人系统入选SIGGRAPH")
    if "代码审查" in excerpt and "评测" in excerpt:
        return _title_with_action(concise_subject, "构建代码审查评测基准")
    sentence = re.split(r"[。！？；]", excerpt, maxsplit=1)[0].strip()
    vendor_prefix = re.escape(item.vendor or "")
    if vendor_prefix:
        without_vendor = re.sub(rf"^{vendor_prefix}[：:，,、\s]*", "", sentence).strip()
        if without_vendor:
            sentence = f"{concise_subject}{without_vendor}"
    if sentence and not _has_untranslated_english_phrase(sentence):
        return sentence[:28].rstrip("，,。；; ")
    return ""


def _fallback_chinese_title(item: AIUpdateItem) -> str:
    raw = _source_text(item)
    lower = raw.lower()
    if "cursor" in lower and any(
        marker in lower
        for marker in (
            "wind down",
            "shutoff",
            "stop providing",
            "terminate",
            "end its commercial partnership",
        )
    ):
        return "OpenAI拟停止向Cursor提供模型"
    if "h3 max" in lower and "fal" in lower and any(
        marker in lower for marker in ("release", "released", "available", "video", "post-trained")
    ):
        return "fal发布MiniMax H3 Max视频模型"
    if re.search(r"\bhy\s*[-_.]?\s*4\b", raw, flags=re.IGNORECASE):
        if any(marker in lower for marker in ("release", "released", "launch", "open-sourc", "preview", "发布", "开源")):
            return "腾讯混元Hy4 Preview模型发布"
    github_status_title = _github_status_fallback_title(item)
    if github_status_title:
        return github_status_title
    social_title = _social_concrete_fallback_title(item)
    if social_title:
        return social_title
    if (
        _has_cjk(item.title)
        and not _has_untranslated_english_phrase(item.title)
        and not _is_low_information_ai_digest_text(item.title)
    ):
        title = item.title or item.summary or item.raw_excerpt
        title = re.sub(r"\s+", " ", title or "").strip()
        return title[:28].rstrip("，,。；; ") or "AI产品更新"
    if "suno" in lower and "midi" in lower:
        return "Suno推出MIDI导出等新功能"
    if "ntt data" in lower and "chatgpt enterprise" in lower and "codex" in lower:
        return "NTT DATA借助ChatGPT与Codex提效"
    legacy_names = list(
        dict.fromkeys(re.findall(r"\bdeepseek-(?:chat|reasoner)\b", lower, flags=re.IGNORECASE))
    )
    if legacy_names and ("discontinu" in lower or "deprecat" in lower):
        return f"DeepSeek将停用{'与'.join(legacy_names)}旧API名"[:28]
    subject = _fallback_chinese_subject(item)
    excerpt_title = _specific_chinese_excerpt_title(item, subject=subject)
    if excerpt_title:
        return excerpt_title
    if subject.endswith("发布新进展"):
        return subject
    if "open-weight" in lower or "open weight" in lower:
        return _title_with_action(subject, "开放权重模型发布")
    if "agentic ai" in lower and "semiconductor" in lower:
        return _title_with_action(subject, "推进AI智能体芯片设计")
    if _is_low_information_ai_digest_text(item.title):
        summary_subject = re.split(r"[，。！？；;]", item.summary or "", maxsplit=1)[0]
        summary_subject = re.sub(r"\s+", " ", summary_subject).strip()
        if (
            len(summary_subject) >= 6
            and _has_cjk(summary_subject)
            and not _is_low_information_ai_digest_text(summary_subject)
            and not re.match(r"^X\s*[：:]", summary_subject, flags=re.IGNORECASE)
            and "原文" not in summary_subject
        ):
            return summary_subject[:28].rstrip("，,。；; ")
    if any(marker in lower for marker in ("launch", "release", "introducing", "new ")):
        return _title_with_action(subject, "发布新进展")
    details = _detail_terms_from_item(item)
    if details:
        return _title_with_action(subject, "发布新进展")
    return _title_with_action(subject, "披露AI产品变化")


def _fallback_chinese_summary(item: AIUpdateItem) -> str:
    source = item.source_name or item.vendor or "公开来源"
    raw = _source_text(item)
    preferred_text = item.summary or item.raw_excerpt or item.title
    if _is_low_information_ai_digest_text(preferred_text) and item.raw_excerpt:
        preferred_text = item.raw_excerpt
    text = re.sub(r"\s+", " ", preferred_text).strip()
    lower = raw.lower()
    if "cursor" in lower and any(
        marker in lower
        for marker in (
            "wind down",
            "shutoff",
            "stop providing",
            "terminate",
            "end its commercial partnership",
        )
    ):
        return "OpenAI官方公告称，计划于2026年11月12日停止向Cursor提供OpenAI模型，公告将原因归于SpaceX收购Cursor后的合同合规风险。"
    if "h3 max" in lower and "fal" in lower and any(
        marker in lower for marker in ("release", "released", "available", "video", "post-trained")
    ):
        speed = "5秒视频约3秒生成" if "3 seconds" in lower or "under 3 seconds" in lower else "面向视频生成场景"
        return f"fal宣布发布由其训练和优化的MiniMax H3 Max视频模型，{speed}，并已在fal平台开放使用。"
    if re.search(r"\bhy\s*[-_.]?\s*4\b", raw, flags=re.IGNORECASE) and any(
        marker in lower for marker in ("release", "released", "launch", "open-sourc", "preview", "发布", "开源")
    ):
        parameter_note = "，原文提到总参数量约7700亿" if "770 billion" in lower else ""
        return (
            "腾讯混元发布并开源 Hy4 Preview，原文将其描述为新一代大语言模型"
            f"{parameter_note}；具体能力和适用范围以原始来源为准。"
        )
    github_status_summary = _github_status_fallback_summary(item)
    if github_status_summary:
        return github_status_summary
    social_summary = _social_concrete_fallback_summary(item)
    if social_summary:
        return social_summary
    # Retain a source excerpt that is already written in Chinese even when it
    # contains unavoidable product names such as SIGGRAPH or Characters.
    if _has_cjk(raw) and _has_cjk(text) and not _has_truncated_english_tail(text):
        return text[:120].rstrip("，,。；; ") + ("…" if len(text) > 120 else "")
    if "ntt data" in lower and "chatgpt enterprise" in lower and "codex" in lower:
        return (
            "NTT DATA集团使用ChatGPT Enterprise与Codex帮助9000名员工自动化工作，"
            "并将事件分析缩短至30分钟，同时推进安全的企业AI应用。"
        )
    if (
        "deepseek-chat" in lower
        and "deepseek-reasoner" in lower
        and ("discontinu" in lower or "deprecat" in lower)
    ):
        return (
            "DeepSeek公告称，deepseek-chat与deepseek-reasoner两个旧API模型名将在三个月后停用；"
            "目前它们分别指向deepseek-v4-flash的非思考与思考模式。"
        )
    if "agentic ai" in lower and "semiconductor" in lower:
        reduction = "，已展示最高40%的调试周期缩短" if "40%" in lower else ""
        return (
            "Synopsys、AMD与微软正把AI智能体接入半导体设计和自动化工程流程"
            f"{reduction}，目标是缩短芯片从概念到成品的开发路径。"
        )
    if ("open-weight" in lower or "open weight" in lower) and "kimi" in lower:
        return "Kimi K3以开放权重形式提供，原始资料重点提到代码与智能体能力，并给出了定价和可用性信息。"
    subject = _fallback_chinese_subject(item)
    details = _detail_terms_from_item(item)
    if details:
        return f"{source}披露{subject}的新进展，原文明确涉及{'、'.join(details)}；具体能力和适用范围以来源链接为准。"
    return f"{source}披露{subject}的AI产品变化；当前可核实信息以原始标题、摘录和来源链接为准。"


_INCOMPLETE_AI_TITLE_ENDINGS = (
    "情况下",
    "因为",
    "由于",
    "如果",
    "虽然",
    "其中",
    "显示",
    "宣布与",
    "推出",
    "披露",
    "正在",
    "将",
    "已",
    "在",
    "通过",
    "针对",
    "与",
    "和",
    "或",
    "及",
    "的",
)


def _title_ends_with_incomplete_phrase(value: str) -> bool:
    compact = re.sub(r"\s+", "", value or "")
    return bool(compact) and compact.endswith(_INCOMPLETE_AI_TITLE_ENDINGS)


def _complete_summary_headline(
    summary: str,
    *,
    limit: int = 72,
    include_following_clause: bool = False,
) -> str:
    """Extract a complete, readable headline without cutting a clause."""

    clean = re.sub(r"\s+", " ", summary or "").strip()
    if not clean:
        return ""
    sentence = re.split(r"[。！？；;]", clean, maxsplit=1)[0].strip()
    clauses = [part.strip() for part in re.split(r"[，,]", sentence) if part.strip()]
    if not include_following_clause and clauses:
        first_clause = clauses[0]
        if len(first_clause) <= limit and not _title_ends_with_incomplete_phrase(first_clause):
            return first_clause
    if len(sentence) <= limit:
        return sentence
    candidates: list[str] = []
    for count in range(1, len(clauses) + 1):
        candidate = "，".join(clauses[:count]).strip()
        if len(candidate) <= limit and not _title_ends_with_incomplete_phrase(candidate):
            candidates.append(candidate)
    if candidates:
        return max(candidates, key=len)
    return sentence


def _repair_title_cut_inside_summary_lead(title: str, summary: str, *, limit: int = 72) -> str:
    clean_title = re.sub(r"\s+", " ", title or "").strip()
    clean_summary = re.sub(r"\s+", " ", summary or "").strip()
    if not clean_title or not _has_cjk(clean_summary) or not clean_summary.startswith(clean_title):
        return clean_title
    remainder = clean_summary[len(clean_title) :]
    if not remainder:
        return clean_title
    starts_inside_token = remainder[0].isalnum() or remainder[0] in "-_/"
    if remainder[0] in "，,。！？；;：:" and not _title_ends_with_incomplete_phrase(clean_title):
        return clean_title
    if starts_inside_token or _title_ends_with_incomplete_phrase(clean_title):
        lead = _complete_summary_headline(
            clean_summary,
            limit=limit,
            include_following_clause=_title_ends_with_incomplete_phrase(clean_title),
        )
        if len(lead) > len(clean_title):
            return lead
    return clean_title


def _ensure_chinese_item(item: AIUpdateItem) -> AIUpdateItem:
    data = item.model_dump()
    data["title"] = simplify_common_chinese(data.get("title", ""))
    data["summary"] = simplify_common_chinese(data.get("summary", ""))
    repaired_title = _repair_title_cut_inside_summary_lead(item.title, item.summary)
    title_repaired = repaired_title != item.title
    data["title"] = repaired_title
    if not title_repaired and (
        not _has_cjk(data.get("title", ""))
        or _is_low_information_ai_digest_text(data.get("title", ""))
        or is_ai_digest_source_label_title(data.get("title", ""), item)
        or (
            _has_untranslated_english_phrase(data.get("title", ""))
            and not _has_chinese_title_context(data.get("title", ""))
        )
    ):
        data["title"] = _fallback_chinese_title(item)
    if (
        not _has_cjk(data.get("summary", ""))
        or _is_low_information_ai_digest_text(data.get("summary", ""))
        or _has_untranslated_english_phrase(data.get("summary", ""))
    ):
        data["summary"] = _fallback_chinese_summary(item)
    data["title"] = _repair_title_cut_inside_summary_lead(data.get("title", ""), data.get("summary", ""))
    data["title"] = simplify_common_chinese(data.get("title", ""))
    if is_ai_digest_source_label_title(data["title"], item) or _is_low_information_ai_digest_text(data["title"]):
        fallback_title = _fallback_chinese_title(item)
        if fallback_title and not is_ai_digest_source_label_title(fallback_title, item):
            data["title"] = fallback_title
    data["summary"] = simplify_common_chinese(data.get("summary", ""))
    tags = []
    for tag in item.tags or []:
        tags.append(tag if _has_cjk(tag) else "AI动态")
    data["tags"] = list(dict.fromkeys(tags or ["AI动态"]))
    return AIUpdateItem.model_validate(data)


def _item_match_score(generated: AIUpdateItem, source: AIUpdateItem, index: int, generated_index: int) -> float:
    score = 0.0
    if generated.url and generated.url == source.url:
        score += 10.0
    if generated.vendor and source.vendor and generated.vendor.lower() == source.vendor.lower():
        score += 2.0
    if generated.product and source.product and generated.product.lower() == source.product.lower():
        score += 2.0
    if generated.source_name and source.source_name and generated.source_name.lower() == source.source_name.lower():
        score += 1.0
    gen_tokens = set(re.findall(r"[A-Za-z0-9.\-]+|[\u4e00-\u9fff]{2,}", f"{generated.title} {generated.summary}".lower()))
    src_tokens = set(re.findall(r"[A-Za-z0-9.\-]+|[\u4e00-\u9fff]{2,}", _source_text(source).lower()))
    if gen_tokens and src_tokens:
        score += len(gen_tokens & src_tokens) / max(1, min(len(gen_tokens), len(src_tokens)))
    if index == generated_index:
        score += 0.4
    return score


def _claim_tokens(text: str) -> set[str]:
    lower = (text or "").lower()
    names = {
        name.replace(" ", "")
        for name in _AI_CLAIM_NAMES
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lower)
    }
    names.update(
        re.sub(r"\s+", "", match.group(0)).lower()
        for match in _AI_MODEL_VERSION_RE.finditer(text or "")
    )
    numbers = {match.group(0).lower() for match in _AI_CLAIM_NUMBER_RE.finditer(text or "")}
    access_claims: set[str] = set()
    if re.search(r"仅限.{0,6}付费|only\s+available\s+in\s+paid|paid[- ]only", lower):
        access_claims.add("access:paid-only")
    if re.search(
        r"使用限制|限制使用|许可条款|usage restrictions?|license restrictions?|license terms?|caveat",
        lower,
    ):
        access_claims.add("access:restrictions")
    if re.search(r"开放权重|开源权重|open[- ]weight", lower):
        access_claims.add("access:open-weight")
    if re.search(r"(?:^|[^a-z])free(?:[^a-z]|$)|免费", lower):
        access_claims.add("access:free")
    return names | numbers | access_claims


def _generated_item_is_grounded(generated: AIUpdateItem, source: AIUpdateItem) -> bool:
    generated_claims = _claim_tokens(f"{generated.title} {generated.summary}")
    if not generated_claims:
        return True
    source_claims = _claim_tokens(
        f"{source.title} {source.summary} {source.raw_excerpt} {source.product} "
        f"{source.vendor} {source.source_name} {source.url}"
    )
    return generated_claims <= source_claims


def _best_source_match(generated: AIUpdateItem, source_items: list[AIUpdateItem], index: int) -> AIUpdateItem | None:
    if not source_items:
        return None
    scored = [(_item_match_score(generated, source, idx, index), source) for idx, source in enumerate(source_items)]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    if best_score <= 0 and index < len(source_items):
        return source_items[index]
    return best


def _restore_traceable_ai_digest_items(brief: AIDigestBrief, source_items: list[AIUpdateItem]) -> AIDigestBrief:
    if not source_items:
        return _ensure_chinese_brief(brief)
    requested_count = len(brief.items)
    # Deduplicate the model response before provenance restoration.  A model
    # can paraphrase one URL more than once even when the prompt forbids it.
    deduped_items = []
    seen_keys = set()
    for item in brief.items:
        key = ai_update_history_key(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_items.append(item)

    # Keep the requested count when the candidate pool has enough unused
    # sources.  These replacements use source text and metadata directly, so
    # they remain traceable and can never render as "动态N".
    for source in source_items:
        if len(deduped_items) >= requested_count:
            break
        key = ai_update_history_key(source)
        if key in seen_keys:
            continue
        replacement = source.model_copy(
            update={
                "title": _fallback_chinese_title(source),
                "summary": _fallback_chinese_summary(source),
                "tags": source.tags or ["AI动态"],
            }
        )
        deduped_items.append(replacement)
        seen_keys.add(key)

    brief = brief.model_copy(update={"items": deduped_items})
    restored = []
    used_source_keys: set[str] = set()
    # Match every retained item to a distinct event.  URL-level matching alone
    # lets two paraphrases consume two mirror URLs for one real-world event.
    for index, item in enumerate(brief.items):
        available_sources = [
            source
            for source in source_items
            if ai_update_history_key(source) not in used_source_keys
        ]
        match = _best_source_match(item, available_sources, index)
        data = item.model_dump()
        if match is not None:
            used_source_keys.add(ai_update_history_key(match))
            for key in ("url", "published_at", "source_name", "vendor", "product", "raw_excerpt"):
                data[key] = getattr(match, key)
            data["source_type"] = match.source_type
            data["verification_status"] = match.verification_status
            data["confidence_score"] = match.confidence_score
            evidence = []
            for url in match.evidence_urls or []:
                if url and url not in evidence and url != data.get("url"):
                    evidence.append(url)
            data["evidence_urls"] = evidence
            grounded = _generated_item_is_grounded(item, match)
            if (
                not grounded
                or _is_low_information_ai_digest_text(str(data.get("title") or ""))
                or is_ai_digest_source_label_title(str(data.get("title") or ""), match)
                or not _has_cjk(str(data.get("title") or ""))
            ):
                data["title"] = _fallback_chinese_title(match)
            if (
                not grounded
                or _looks_generic_ai_digest_text(str(data.get("summary") or ""))
                or not _has_cjk(str(data.get("summary") or ""))
            ):
                data["summary"] = _fallback_chinese_summary(match)
        restored.append(_ensure_chinese_item(AIUpdateItem.model_validate(data)))
    unique_restored = []
    seen_keys = set()
    for item in restored:
        key = ai_update_history_key(item)
        if key in seen_keys:
            continue
        unique_restored.append(item)
        seen_keys.add(key)
    capped = cap_ai_digest_items_by_source(unique_restored, target_count=requested_count)
    seen_keys = {ai_update_history_key(item) for item in capped}
    source_counts = Counter(ai_update_source_key(item) for item in capped)
    for source in source_items:
        if len(capped) >= requested_count:
            break
        source_event_key = ai_update_history_key(source)
        if source_event_key in seen_keys:
            continue
        source_key = ai_update_source_key(source)
        if source_counts[source_key] >= AI_DIGEST_MAX_ITEMS_PER_SOURCE:
            continue
        replacement = source.model_copy(
            update={
                "title": _fallback_chinese_title(source),
                "summary": _fallback_chinese_summary(source),
                "tags": source.tags or ["AI"],
            }
        )
        capped.append(_ensure_chinese_item(replacement))
        seen_keys.add(source_event_key)
        source_counts[source_key] += 1
    brief_data = brief.model_dump()
    brief_data["items"] = [item.model_dump() for item in capped]
    return _ensure_chinese_brief(AIDigestBrief.model_validate(brief_data))


def _fill_missing_item_publish_times(brief: AIDigestBrief, *, date: str = "") -> AIDigestBrief:
    fallback_date = (date or brief.date or _today_date()).strip()
    data = brief.model_dump()
    data["date"] = brief.date or fallback_date
    return AIDigestBrief.model_validate(data)


def _ensure_chinese_brief(brief: AIDigestBrief) -> AIDigestBrief:
    data = brief.model_dump()
    data["title"] = brief.title if _has_cjk(brief.title) else "每日AI讯息"
    data["subtitle"] = brief.subtitle if _has_cjk(brief.subtitle) else "AI平台、模型、工具和开源动态简报"
    data["items"] = [_ensure_chinese_item(item).model_dump() for item in brief.items]
    if not _has_cjk(brief.source_summary):
        vendors = Counter(item.vendor or item.source_name or "公开来源" for item in brief.items)
        source_summary = "、".join(name for name, _count in vendors.most_common(6))
        data["source_summary"] = f"主要来源：{source_summary}。" if source_summary else "主要来源：官方公开渠道。"
    return AIDigestBrief.model_validate(data)


def build_ai_digest_prompt(
    items: Iterable[AIUpdateItem],
    *,
    target_count: int = 10,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
) -> str:
    rows = []
    for idx, item in enumerate(items, 1):
        rows.append(
            {
                "index": idx,
                "title": item.title,
                "summary": item.summary,
                "source_name": item.source_name,
                "source_type": item.source_type,
                "vendor": item.vendor,
                "product": item.product,
                "published_at": item.published_at,
                "url": item.url,
                "evidence_urls": item.evidence_urls,
                "verification_status": item.verification_status,
                "raw_excerpt": item.raw_excerpt[:800],
            }
        )
    quota_rule = ""
    if min_domestic_model_count or min_foreign_ai_count:
        quota_rule = (
            f"硬性配额：最终 items 恰好 {target_count} 条；"
            f"至少 {min_domestic_model_count} 条中国/国内模型、模型版本或模型 API 资讯；"
            f"至少 {min_foreign_ai_count} 条国外 AI 平台、模型、工具或开源资讯。\n"
        )
    return (
        "你正在为小红书图文笔记制作《每日AI讯息》。\n"
        + f"程序已经选定恰好 {target_count} 条候选。请逐条翻译和改写，不得删除、增加、合并或调整顺序。\n"
        + quota_rule
        + "候选已经按官网、官方项目、资讯整合站、搜索发现、社交补充分层；不得把低层级来源改写成官网来源。\n"
        + "候选已通过程序的 URL、日期、相关性和具体事实门禁；不得用泛化句替代事实，也不得输出没有具体内容的‘披露AI产品变化’。\n"
        + f"信源硬约束：同一规范化信源最多保留 {AI_DIGEST_MAX_ITEMS_PER_SOURCE} 条；若不足目标条数，必须从候选池中换用其他信源，不得用第三条补齐。\n"
        + "要求：官方源优先；社交源只能用于补充或验证；不得编造未提供的信息；全部输出中文。\n"
        + "发布时间硬规则：items[].published_at 必须从候选数据原样复制；不得使用简报日期、抓取日期、页面运行时 now 或自行推断日期替代；"
        + "候选缺少 published_at 时不得选入最终 items。\n"
        + "如果候选信息是英文、日文或其他语言，必须翻译并改写为自然中文；公司名、模型名、产品名可保留原文。\n"
        + "请返回严格 JSON，字段为 title, subtitle, date, items, source_summary。\n"
        + "items 每项只输出：title, summary, url, tags。url 必须从对应候选原样复制；每个 URL 只能出现一次，不得把同一来源改写成多个条目。\n"
        + "候选来源足够时必须优先使用不同来源补齐数量；不得使用‘动态数字’、‘动态3’或‘动态5’作为标题、来源或占位文本。\n"
        + "summary 控制在 50-90 字，说明更新内容和对用户/开发者的意义。\n"
        + "候选数据：\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
    )


def _extract_json_object(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


def parse_ai_digest_impact_json(text: str, *, candidate_count: int) -> dict[int, dict[str, object]]:
    data = json.loads(_extract_json_object(text))
    raw_rows = data.get("scores") if isinstance(data, dict) else None
    if not isinstance(raw_rows, list):
        raise ValueError("impact supervisor response must contain a scores list")
    expected = set(range(1, max(0, int(candidate_count)) + 1))
    parsed: dict[int, dict[str, object]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ValueError("impact supervisor score row must be an object")
        index = raw.get("index")
        score = raw.get("impact_score")
        high_impact = raw.get("high_impact")
        if isinstance(index, bool) or not isinstance(index, int) or index not in expected:
            raise ValueError(f"impact supervisor returned unknown candidate index: {index}")
        if index in parsed:
            raise ValueError(f"impact supervisor returned duplicate candidate index: {index}")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            raise ValueError(f"impact supervisor returned invalid score for candidate {index}")
        if not isinstance(high_impact, bool):
            raise ValueError(f"impact supervisor returned invalid high_impact flag for candidate {index}")
        parsed[index] = {
            "impact_score": float(score),
            "high_impact": high_impact,
            "reason": str(raw.get("reason") or "").strip()[:80],
        }
    if set(parsed) != expected:
        missing = sorted(expected.difference(parsed))
        raise ValueError(f"impact supervisor omitted candidate indices: {missing}")
    return parsed


def _deterministic_ai_digest_impact(
    items: list[AIUpdateItem],
    *,
    threshold: float,
) -> dict[str, dict[str, object]]:
    return {
        item.dedupe_key: {
            "impact_score": ai_update_impact_score(item),
            "deterministic_score": ai_update_impact_score(item),
            "llm_score": None,
            "high_impact": ai_update_is_high_impact(item, threshold=threshold),
            "reason": "deterministic_category_source_evidence_score",
        }
        for item in items
    }


def _build_ai_digest_impact_prompt(items: list[AIUpdateItem]) -> str:
    rows = [
        {
            "index": index,
            "title": item.title,
            "summary": item.summary,
            "source_name": item.source_name,
            "source_type": item.source_type,
            "published_at": item.published_at,
            "vendor": item.vendor,
            "product": item.product,
            "verification_status": item.verification_status,
            "evidence_count": len(item.evidence_urls or []),
            "raw_excerpt": (item.raw_excerpt or "")[:400],
        }
        for index, item in enumerate(items, 1)
    ]
    return (
        "请评估每条 AI 候选事件的公开影响力。只能依据给定事实评分，不得补充事实、改写日期或增删候选。\n"
        "模型发布、重要版本、关键基准、具体技术突破、重大安全事件和广泛基础设施变化优先；"
        "泛泛观点、普通企业案例和缺少具体变化的动态不得评为高影响。\n"
        f"必须为全部 {len(rows)} 个 index 各返回一次，顺序不限。"
        "只输出严格 JSON：{\"scores\":[{\"index\":1,\"impact_score\":0-100,"
        "\"high_impact\":true或false,\"reason\":\"不超过30字\"}]}。\n"
        "候选：\n"
        + json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    )


def evaluate_ai_digest_impact_with_llm(
    cfgs: list[LLMConfig],
    items: list[AIUpdateItem],
    *,
    threshold: float = 75.0,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    bounded_threshold = min(100.0, max(0.0, float(threshold)))
    deterministic = _deterministic_ai_digest_impact(items, threshold=bounded_threshold)
    if not items:
        return deterministic, {"mode": "deterministic", "evaluated_count": 0, "error": ""}
    if not cfgs:
        return deterministic, {
            "mode": "deterministic_fallback",
            "evaluated_count": len(items),
            "error": "LLM config missing for impact supervisor",
        }

    try:
        request_timeout = int((os.getenv("AI_DIGEST_IMPACT_TIMEOUT_S") or "120").strip())
    except ValueError:
        request_timeout = 120
    request_timeout = max(30, min(request_timeout, 600))
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是严谨的 AI 新闻影响力审核员。只按候选事实评分，只输出严格 JSON。",
            ),
            ("user", "{user_prompt}"),
        ]
    )
    last_exc: Exception | None = None
    for cfg in cfgs:
        try:
            model_kwargs = {
                "model_provider": "openai",
                "base_url": cfg.base_url,
                "api_key": cfg.api_key,
                "max_tokens": min(AI_DIGEST_LLM_MAX_TOKENS, max(4000, len(items) * 180)),
                "timeout": request_timeout,
            }
            model_kwargs.update(_temperature_kwargs(cfg.model, 0))
            if (cfg.provider or "").strip().lower() == "volcengine":
                model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            model = init_chat_model(cfg.model, **model_kwargs)
            messages = prompt.format_messages(user_prompt=_build_ai_digest_impact_prompt(items))
            response = model.invoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
            llm_rows = parse_ai_digest_impact_json(content, candidate_count=len(items))
            merged: dict[str, dict[str, object]] = {}
            for index, item in enumerate(items, 1):
                base = float(deterministic[item.dedupe_key]["deterministic_score"])
                llm_score = float(llm_rows[index]["impact_score"])
                combined = round(base * 0.4 + llm_score * 0.6, 3)
                category_eligible = ai_update_is_high_impact(item, threshold=0)
                merged[item.dedupe_key] = {
                    "impact_score": combined,
                    "deterministic_score": base,
                    "llm_score": llm_score,
                    "high_impact": bool(llm_rows[index]["high_impact"])
                    and category_eligible
                    and combined >= bounded_threshold,
                    "reason": llm_rows[index]["reason"],
                }
            return merged, {
                "mode": "llm_hybrid",
                "evaluated_count": len(items),
                "provider": cfg.provider,
                "model": cfg.model,
                "error": "",
            }
        except Exception as exc:
            last_exc = exc
            continue
    return deterministic, {
        "mode": "deterministic_fallback",
        "evaluated_count": len(items),
        "error": str(last_exc or "impact supervisor failed"),
    }


def parse_ai_digest_brief_json(text: str) -> AIDigestBrief:
    data = json.loads(_extract_json_object(text))
    items = [AIUpdateItem.model_validate(item) for item in data.get("items", []) if isinstance(item, dict)]
    for idx, item in enumerate(items):
        if item.source_type not in {"official", "github"} or not item.evidence_urls:
            continue
        if item.verification_status != "official_only":
            continue
        evidence_hosts = {
            (urlsplit(url).hostname or "").lower().strip().rstrip(".")
            for url in item.evidence_urls
            if url
        }
        if any(
            host in {"x.com", "twitter.com", "www.twitter.com"}
            or host.endswith(".x.com")
            for host in evidence_hosts
        ):
            item_data = item.model_dump()
            item_data["verification_status"] = "social_confirmed"
            items[idx] = AIUpdateItem.model_validate(item_data)
        elif any(
            host in {"aihot.virxact.com", "www.aihot.virxact.com"}
            or host.endswith(".aihot.virxact.com")
            for host in evidence_hosts
        ):
            item_data = item.model_dump()
            item_data["verification_status"] = "aggregator_confirmed"
            items[idx] = AIUpdateItem.model_validate(item_data)
    data["items"] = items
    return _ensure_chinese_brief(AIDigestBrief.model_validate(data))


def generate_ai_digest_brief_with_llm(
    cfgs: list[LLMConfig],
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    min_domestic_model_count: int = 0,
    min_foreign_ai_count: int = 0,
    date: str = "",
) -> AIDigestBrief:
    """Use the configured LLM to translate and summarize preselected AI digest items."""
    if not cfgs:
        raise RuntimeError("LLM config missing for daily AI digest")

    user_prompt = build_ai_digest_prompt(
        items,
        target_count=target_count,
        min_domestic_model_count=min_domestic_model_count,
        min_foreign_ai_count=min_foreign_ai_count,
    )
    try:
        request_timeout = int(
            (os.getenv("AI_DIGEST_LLM_TIMEOUT_S") or str(AI_DIGEST_LLM_TIMEOUT_SECONDS)).strip()
        )
    except ValueError:
        request_timeout = AI_DIGEST_LLM_TIMEOUT_SECONDS
    request_timeout = max(30, min(request_timeout, 600))
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "你是严谨的中文科技简报编辑。只输出严格 JSON，不要 Markdown 或代码块。"
                    "所有面向读者的 title、subtitle、summary、source_summary 必须是自然中文；"
                    "专有名词如 OpenAI、Claude、GLM、Qwen、Kimi、API、GitHub 可以保留原文。"
                    "不得添加候选数据之外的事实，链接只保留在 JSON 字段中。"
                ),
            ),
            ("user", "{user_prompt}\n\n简报日期：{date}"),
        ]
    )
    last_exc: Exception | None = None
    for cfg in cfgs:
        try:
            model_kwargs = {
                "model_provider": "openai",
                "base_url": cfg.base_url,
                "api_key": cfg.api_key,
                "max_tokens": AI_DIGEST_LLM_MAX_TOKENS,
                "timeout": request_timeout,
            }
            model_kwargs.update(_temperature_kwargs(cfg.model, 0.2))
            # Ark models can otherwise spend the whole output allowance on
            # hidden reasoning and return an empty final message.  The digest
            # is a constrained JSON transformation, so direct answering is
            # both faster and more reliable here.
            if (cfg.provider or "").strip().lower() == "volcengine":
                model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            model = init_chat_model(
                cfg.model,
                **model_kwargs,
            )
            print(
                f"[ai-digest-llm] provider={cfg.provider} model={cfg.model} "
                f"base_url={cfg.base_url} timeout={request_timeout}s",
                flush=True,
            )
            for attempt in range(1, 3):
                retry_instruction = ""
                if attempt > 1:
                    retry_instruction = (
                        "\n\n上一次返回无法通过 JSON 或条数校验。"
                        f"本次必须只返回一个完整 JSON 对象，items 必须恰好 {target_count} 条。"
                    )
                messages = prompt.format_messages(
                    user_prompt=user_prompt + retry_instruction,
                    date=date or _today_date(),
                )
                try:
                    print(
                        f"[ai-digest-llm] stage=request attempt={attempt}/2 timeout={request_timeout}s",
                        flush=True,
                    )
                    resp = model.invoke(messages)
                    text = resp.content if hasattr(resp, "content") else str(resp)
                    brief = parse_ai_digest_brief_json(text)
                    if len(brief.items) != target_count:
                        raise ValueError(
                            f"expected exactly {target_count} items, got {len(brief.items)}"
                        )
                    brief = _restore_traceable_ai_digest_items(brief, items)
                    if len(brief.items) != target_count:
                        raise ValueError(
                            f"source diversity cap left {len(brief.items)} of {target_count} items"
                        )
                    if date and not brief.date:
                        data = brief.model_dump()
                        data["date"] = date
                        brief = AIDigestBrief.model_validate(data)
                    brief = _fill_missing_item_publish_times(brief, date=date)
                    return _ensure_chinese_brief(brief)
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        print(
                            f"[ai-digest-llm] retry=2 reason={type(exc).__name__}: {exc}",
                            flush=True,
                        )
        except Exception as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"daily ai digest LLM generation failed: {last_exc}")


def build_fallback_brief(
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    date: str = "",
) -> AIDigestBrief:
    selected = [
        _ensure_chinese_item(item)
        for item in cap_ai_digest_items_by_source(
            items,
            target_count=max(1, int(target_count or 10)),
        )
    ]
    vendors = Counter(item.vendor or item.source_name or "unknown" for item in selected)
    source_summary = "、".join(name for name, _count in vendors.most_common(6))
    if source_summary:
        source_summary = f"主要来源：{source_summary}。"
    brief = AIDigestBrief(
        title="每日AI讯息",
        subtitle="AI平台、模型、工具和开源动态简报",
        date=date or _today_date(),
        items=selected,
        source_summary=source_summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    return _fill_missing_item_publish_times(brief, date=date)


def _selection_summary_line(selection_meta: dict | None, *, item_count: int) -> str:
    if not selection_meta:
        return ""
    fetched = selection_meta.get("fetched_count")
    fresh = selection_meta.get("fresh_count")
    deduped = selection_meta.get("deduped_count")
    max_age_days = selection_meta.get("max_age_days") or 3
    if fetched is None and fresh is None and deduped is None:
        return ""
    parts = []
    if fetched is not None:
        parts.append(f"抓取{fetched}条")
    if fresh is not None:
        parts.append(f"近{max_age_days}日{fresh}条")
    if deduped is not None:
        parts.append(f"去重后{deduped}条")
    parts.append(f"发布{item_count}条")
    return "候选池：" + "，".join(parts)


def _ai_digest_body_source(item: AIUpdateItem) -> str:
    return (item.vendor or item.source_name or "官方来源").strip() or "官方来源"


def _shorten_ai_digest_body_title(value: str, *, max_chars: int) -> str:
    clean = re.sub(r"\s+", " ", value or "").strip()
    if len(clean) <= max_chars:
        return clean
    candidate = _complete_summary_headline(clean, limit=max_chars)
    if candidate and len(candidate) <= max_chars:
        return candidate
    # Titles are normally repaired before this point. This final branch is
    # only a body-capacity guard; keep a word/clause boundary where possible.
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9._+/-]*|[\u4e00-\u9fff]", clean)
    compact = ""
    for word in words:
        if len(compact) + len(word) > max_chars:
            break
        compact += word
    return compact or clean[:max_chars]


def _format_ai_digest_body_published_at(value: str) -> str:
    """Keep date-only values and present timestamped sources in Beijing time."""
    text = (value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        return match.group(0) if match else ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_BEIJING_TZ)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _ai_digest_body_topic_lines(
    items: list[AIUpdateItem],
    *,
    include_source: bool,
    title_limit: int | None = None,
) -> list[str]:
    lines = []
    for idx, item in enumerate(items, 1):
        title = item.title.strip()
        if title_limit is not None:
            title = _shorten_ai_digest_body_title(title, max_chars=title_limit)
        prefix = f"{idx}. {_ai_digest_body_source(item)}：" if include_source else f"{idx}. "
        published_at = _format_ai_digest_body_published_at(item.published_at)
        suffix = f"（发布时间：{published_at}）" if published_at else ""
        lines.append(f"{prefix}{title}{suffix}")
    return lines


def render_ai_digest_body(brief: AIDigestBrief, *, selection_meta: dict | None = None) -> str:
    # Normalize once more at the presentation boundary. This protects callers
    # that render an older/raw brief directly and keeps the body aligned with
    # the cards and local metadata.
    items = [_ensure_chinese_item(item) for item in brief.items]
    sources = []
    for item in items:
        name = _ai_digest_body_source(item)
        if name and name not in sources:
            sources.append(name)
    source_text = " / ".join(sources[:8]) or "官方公开渠道"
    source_tier_counts = {
        "official": sum(1 for item in items if item.source_type in {"official", "github"}),
        "aggregator": sum(1 for item in items if item.source_type in {"aggregator", "search"}),
        "social": sum(1 for item in items if item.source_type == "social"),
    }
    source_tier_line = (
        f"信源层级：官网{source_tier_counts['official']}条，"
        f"资讯整合站{source_tier_counts['aggregator']}条，"
        f"社交媒体{source_tier_counts['social']}条"
    )
    topic_lines = _ai_digest_body_topic_lines(items, include_source=True)
    lines = [
        "每日AI讯息",
        f"发布时间：{brief.date}",
        f"来源：{source_text}",
        source_tier_line,
        "",
        "今日动态：",
        *topic_lines,
    ]
    selection_line = _selection_summary_line(selection_meta, item_count=len(items))
    if selection_line:
        lines.append(selection_line)
    # Links are intentionally not written into the draft body: external URLs in
    # XHS posts can trigger review/removal. Source URLs remain in the local
    # post metadata (ai_digest.items[].url / evidence_urls) for traceability.
    body = "\n".join(lines)
    if len(body) <= AI_DIGEST_BODY_LIMIT:
        return body

    # Compact only when the platform body limit requires it. Never slice a
    # source name or title at an arbitrary character boundary, and keep the
    # complete source list in the header when per-item labels are omitted.
    variants = (
        (True, None, False),
        (True, 72, False),
        (True, 48, False),
        (False, None, False),
        (False, 72, False),
        (False, 48, False),
        (False, 36, False),
    )
    for include_source, title_limit, include_selection in variants:
        compact_lines = [
            "每日AI讯息",
            f"发布时间：{brief.date}",
            f"来源：{source_text}",
            source_tier_line,
            "",
            "今日动态：",
            *(_ai_digest_body_topic_lines(items, include_source=include_source, title_limit=title_limit)),
        ]
        if include_selection and selection_line:
            compact_lines.append(selection_line)
        body = "\n".join(compact_lines)
        if len(body) <= AI_DIGEST_BODY_LIMIT:
            return body

    return body
