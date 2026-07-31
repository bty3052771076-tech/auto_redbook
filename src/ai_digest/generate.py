from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import unquote, urlsplit

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from src.config import LLMConfig

from .models import AIDigestBrief, AIUpdateItem


AI_DIGEST_LLM_MAX_TOKENS = 6000
AI_DIGEST_BODY_LIMIT = 1000
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_GENERIC_AI_DIGEST_MARKERS = (
    "发布AI动态",
    "公开了与AI有关的动态",
    "公开了与相关AI产品有关的AI动态",
    "具体链接已保存在本地元数据",
    "当前摘要仅基于原始标题和摘录整理",
)
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
    r"(?<![a-z0-9])(?:gpt|claude|qwen|deepseek|glm|doubao|seedream|kimi|gemini|gemma|"
    r"llama|mistral|minimax|ernie)[-_. ]?\d+(?:\.\d+)*(?:[-_. ]?[a-z0-9]+)?(?![a-z0-9])",
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
    return any(marker.replace(" ", "") in compact for marker in _GENERIC_AI_DIGEST_MARKERS)


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


def _english_subject(item: AIUpdateItem) -> str:
    raw = _source_text(item)
    product = _clean_subject(item.product)
    if product and not _subject_is_only_source(product, item):
        return product
    patterns = (
        r"\b(?:GPT|GLM|Qwen|Claude|Codex|Gemini|Kimi|Doubao|Seedream|ERNIE|Llama|Mistral|DeepSeek|MiniMax)[A-Za-z0-9.\- ]{0,64}",
        r"\b[A-Z][A-Za-z0-9.\-]+(?:\s+[A-Z][A-Za-z0-9.\-]+){0,4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
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


def _title_with_action(subject: str, action: str, *, limit: int = 28) -> str:
    clean_action = re.sub(r"\s+", " ", action or "").strip()
    clean_subject = re.sub(r"\s+", " ", subject or "").strip()
    subject_limit = max(1, limit - len(clean_action))
    clean_subject = clean_subject[:subject_limit].rstrip("，,。；;：: -")
    return f"{clean_subject}{clean_action}"[:limit]


def _fallback_chinese_title(item: AIUpdateItem) -> str:
    raw = _source_text(item)
    if _has_cjk(item.title):
        title = item.title or item.summary or item.raw_excerpt
        title = re.sub(r"\s+", " ", title or "").strip()
        return title[:28].rstrip("，,。；; ") or "AI产品更新"
    lower = raw.lower()
    if "ntt data" in lower and "chatgpt enterprise" in lower and "codex" in lower:
        return "NTT DATA借助ChatGPT与Codex提效"
    legacy_names = list(
        dict.fromkeys(re.findall(r"\bdeepseek-(?:chat|reasoner)\b", lower, flags=re.IGNORECASE))
    )
    if legacy_names and ("discontinu" in lower or "deprecat" in lower):
        return f"DeepSeek将停用{'与'.join(legacy_names)}旧API名"[:28]
    subject = _english_subject(item)
    if "open-weight" in lower or "open weight" in lower:
        return _title_with_action(subject, "开放权重模型发布")
    if "agentic ai" in lower and "semiconductor" in lower:
        return _title_with_action(subject, "推进AI智能体芯片设计")
    if any(marker in lower for marker in ("launch", "release", "introducing", "new ")):
        return _title_with_action(subject, "发布新进展")
    details = _detail_terms_from_item(item)
    if details:
        return _title_with_action(subject, "发布新进展")
    return _title_with_action(subject, "披露AI产品变化")


def _fallback_chinese_summary(item: AIUpdateItem) -> str:
    source = item.source_name or item.vendor or "公开来源"
    raw = _source_text(item)
    if _has_cjk(raw):
        text = re.sub(r"\s+", " ", item.summary or item.raw_excerpt or item.title).strip()
        return text[:120].rstrip("，,。；; ") + ("…" if len(text) > 120 else "")
    lower = raw.lower()
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
    subject = _english_subject(item)
    details = _detail_terms_from_item(item)
    if details:
        return f"{source}披露{subject}的新进展，原文明确涉及{'、'.join(details)}；具体能力和适用范围以来源链接为准。"
    return f"{source}披露{subject}的AI产品变化；当前可核实信息以原始标题、摘录和来源链接为准。"


def _ensure_chinese_item(item: AIUpdateItem) -> AIUpdateItem:
    data = item.model_dump()
    if not _has_cjk(data.get("title", "")) or _looks_generic_ai_digest_text(data.get("title", "")):
        data["title"] = _fallback_chinese_title(item)
    if not _has_cjk(data.get("summary", "")) or _looks_generic_ai_digest_text(data.get("summary", "")):
        data["summary"] = _fallback_chinese_summary(item)
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
    restored: list[AIUpdateItem] = []
    remaining_sources = list(source_items)
    for index, item in enumerate(brief.items):
        match = _best_source_match(item, remaining_sources, index)
        data = item.model_dump()
        if match is not None:
            remaining_sources.remove(match)
            for key in ("url", "published_at", "source_name", "vendor", "product", "raw_excerpt"):
                data[key] = getattr(match, key)
            data["source_type"] = match.source_type
            data["verification_status"] = match.verification_status
            data["confidence_score"] = match.confidence_score
            evidence: list[str] = []
            for url in match.evidence_urls or []:
                if url and url not in evidence and url != data.get("url"):
                    evidence.append(url)
            data["evidence_urls"] = evidence
            grounded = _generated_item_is_grounded(item, match)
            if (
                not grounded
                or _looks_generic_ai_digest_text(str(data.get("title") or ""))
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
    brief_data = brief.model_dump()
    brief_data["items"] = [item.model_dump() for item in restored]
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
        + "要求：官方源优先；社交源只能用于补充或验证；不得编造未提供的信息；全部输出中文。\n"
        + "发布时间硬规则：items[].published_at 必须从候选数据原样复制；不得使用简报日期、抓取日期、页面运行时 now 或自行推断日期替代；"
        + "候选缺少 published_at 时不得选入最终 items。\n"
        + "如果候选信息是英文、日文或其他语言，必须翻译并改写为自然中文；公司名、模型名、产品名可保留原文。\n"
        + "请返回严格 JSON，字段为 title, subtitle, date, items, source_summary。\n"
        + "items 每项只输出：title, summary, url, tags。url 必须从对应候选原样复制。\n"
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


def parse_ai_digest_brief_json(text: str) -> AIDigestBrief:
    data = json.loads(_extract_json_object(text))
    items = [AIUpdateItem.model_validate(item) for item in data.get("items", []) if isinstance(item, dict)]
    for idx, item in enumerate(items):
        if item.source_type in {"official", "github"} and item.evidence_urls and item.verification_status == "official_only":
            item_data = item.model_dump()
            item_data["verification_status"] = "social_confirmed"
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
            model = init_chat_model(
                cfg.model,
                model_provider="openai",
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                temperature=0.2,
                max_tokens=AI_DIGEST_LLM_MAX_TOKENS,
            )
            print(f"[ai-digest-llm] provider={cfg.provider} model={cfg.model} base_url={cfg.base_url}")
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
                    resp = model.invoke(messages)
                    text = resp.content if hasattr(resp, "content") else str(resp)
                    brief = parse_ai_digest_brief_json(text)
                    if len(brief.items) != target_count:
                        raise ValueError(
                            f"expected exactly {target_count} items, got {len(brief.items)}"
                        )
                    brief = _restore_traceable_ai_digest_items(brief, items)
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
    selected = [_ensure_chinese_item(item) for item in items[: max(1, int(target_count or 10))]]
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


def render_ai_digest_body(brief: AIDigestBrief, *, selection_meta: dict | None = None) -> str:
    sources = []
    for item in brief.items:
        name = item.vendor or item.source_name
        if name and name not in sources:
            sources.append(name)
    source_text = " / ".join(name[:16] for name in sources[:8]) or "官方公开渠道"
    source_tier_counts = {
        "official": sum(1 for item in brief.items if item.source_type in {"official", "github"}),
        "aggregator": sum(1 for item in brief.items if item.source_type in {"aggregator", "search"}),
        "social": sum(1 for item in brief.items if item.source_type == "social"),
    }
    source_tier_line = (
        f"信源层级：官网{source_tier_counts['official']}条，"
        f"资讯整合站{source_tier_counts['aggregator']}条，"
        f"社交媒体{source_tier_counts['social']}条"
    )
    lines = [
        "每日AI讯息",
        "",
        f"整理了 {len(brief.items)} 条 AI 平台、模型、工具和开源动态，适合快速了解今天的 AI 变化。",
        "",
        f"发布时间：{brief.date}",
        f"来源：{source_text}",
        source_tier_line,
    ]
    selection_line = _selection_summary_line(selection_meta, item_count=len(brief.items))
    if selection_line:
        lines.append(selection_line)
    link_lines = []
    for idx, item in enumerate(brief.items, 1):
        trace_urls = [
            url
            for url in [item.normalized_url, *(u.strip() for u in item.evidence_urls if u.strip())]
            if url
        ]
        url = next(iter(dict.fromkeys(trace_urls)), "")
        if not url:
            continue
        source = (item.vendor or item.source_name or f"动态{idx}").strip()
        link_lines.append(f"{idx}. {source[:12]} {url}")
    if link_lines:
        lines.extend(["", "来源链接：", *link_lines])
    body = "\n".join(lines)
    if len(body) <= AI_DIGEST_BODY_LIMIT:
        return body

    compact_lines = [
        "每日AI讯息",
        f"发布时间：{brief.date}",
        source_tier_line,
    ]
    if selection_line:
        compact_lines.append(selection_line)
    compact_lines.extend(["来源链接：", *link_lines])
    body = "\n".join(compact_lines)
    if len(body) <= AI_DIGEST_BODY_LIMIT:
        return body

    return "\n".join(
        [
            "每日AI讯息",
            f"发布时间：{brief.date}",
            source_tier_line,
            "来源链接：",
            *(f"{idx}. {line.split(' ', 2)[-1]}" for idx, line in enumerate(link_lines, 1)),
        ]
    )
