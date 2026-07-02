from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from src.config import LLMConfig


DEFAULT_LLM_MAX_TOKENS = 60000


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _extract_json_block(text: str) -> str | None:
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return brace_match.group(0)
    return None


def _looks_like_jsonish_payload(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return (
        t.startswith("{")
        or t.startswith("[")
        or "```json" in t
        or '"title"' in t
        or '"body"' in t
        or '"topics"' in t
        or '"image_event"' in t
    )


def _strip_code_fence(text: str) -> str:
    if "```" not in text:
        return text
    text = re.sub(r"```(?:json)?", "", text)
    return text.replace("```", "").strip()


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _strip_code_fence(value)
    if isinstance(value, list):
        parts = [_coerce_text(v) for v in value if _coerce_text(v)]
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        daily_news_keys = ("原文标题", "内容", "评价", "日期", "来源")
        if any(key in value for key in daily_news_keys):
            ordered = {key: value.get(key, "") for key in daily_news_keys}
            return json.dumps(ordered, ensure_ascii=False, indent=2)
        for key in ("text", "body", "content", "summary"):
            if key in value:
                return _coerce_text(value[key])
        for v in value.values():
            text = _coerce_text(v)
            if text:
                return text
    return _strip_code_fence(str(value))


def _normalize_topics(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        topics: List[str] = []
        for item in value:
            if isinstance(item, str):
                topics.append(item)
            elif isinstance(item, dict):
                for key in ("name", "topic", "tag"):
                    if key in item and isinstance(item[key], str):
                        topics.append(item[key])
                        break
                else:
                    topics.append(_coerce_text(item))
            else:
                topics.append(_coerce_text(item))
        return [t for t in topics if t]
    return []


def _sanitize_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        return body

    markers = (
        "Prompt:",
        "Prompt：",
        "Initial title:",
        "Initial title：",
        "Assets",
        "要求",
        "写作要求",
        "新闻标题",
        "用户偏好",
        "用户关注点",
        "offline fallback",
        "news_fetch_failed",
        "http://",
        "https://",
    )
    if not any(m in body for m in markers):
        return body

    lines = [ln.strip() for ln in body.splitlines()]
    kept: list[str] = []
    for ln in lines:
        if not ln:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if ln.startswith(("Prompt:", "Prompt：", "Initial title:", "Initial title：")):
            continue
        if ln.startswith(("Assets", "Assets:")):
            continue
        if ln.startswith(("写作要求", "写作要求：", "要求", "要求：")):
            continue
        if re.match(r"^[-*]\s*(标题|来源|时间|链接)[:：]", ln):
            continue
        if "news_fetch_failed" in ln or "offline fallback" in ln:
            continue
        if re.search(r"https?://", ln):
            continue
        kept.append(ln)

    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _decode_jsonish_string(raw: str) -> str:
    text = (raw or "").strip().rstrip(",").strip()
    text = re.sub(r"\n\s*[}\]]\s*$", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1]
    text = (
        text.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\'", "'")
    )
    return _strip_code_fence(text).strip()


def _extract_jsonish_field(text: str, key: str, next_keys: List[str]) -> str | None:
    m = re.search(rf'(?is)"{re.escape(key)}"\s*:\s*', text)
    if not m:
        return None
    start = m.end()
    end = len(text)
    for nk in next_keys:
        m2 = re.search(
            rf'(?im)^\s*,?\s*"{re.escape(nk)}"\s*:\s*',
            text[start:],
        )
        if m2:
            end = min(end, start + m2.start())
    value = text[start:end].strip().rstrip(",").strip()
    return value or None


def _parse_jsonish_topics(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        return []
    for candidate in (text, text.replace("'", '"')):
        try:
            obj = json.loads(candidate)
            topics = _normalize_topics(obj)
            if topics:
                return topics
        except Exception:
            pass
    # Fallback for malformed arrays: pick quoted strings first.
    quoted = re.findall(r'"([^"\n]{1,40})"', text)
    if quoted:
        return [t.strip() for t in quoted if t.strip()]
    return [seg.strip() for seg in re.split(r"[,，、/|]", text) if seg.strip()]


def _recover_jsonish_object(text: str) -> Dict[str, Any] | None:
    src = _strip_code_fence((text or "")).strip()
    if not _looks_like_jsonish_payload(src):
        return None

    out: Dict[str, Any] = {}
    title_raw = _extract_jsonish_field(src, "title", ["body", "topics", "image_event"])
    body_raw = _extract_jsonish_field(src, "body", ["topics", "image_event"])
    topics_raw = _extract_jsonish_field(src, "topics", ["image_event"])
    event_raw = _extract_jsonish_field(src, "image_event", [])

    if title_raw:
        title = _decode_jsonish_string(title_raw)
        if title:
            out["title"] = title
    if body_raw:
        body = _decode_jsonish_string(body_raw)
        if body:
            out["body"] = body
    if topics_raw:
        topics = _parse_jsonish_topics(topics_raw)
        if topics:
            out["topics"] = topics
    if event_raw:
        image_event = _decode_jsonish_string(event_raw)
        if image_event:
            out["image_event"] = image_event

    if out:
        return out
    return None


def _parse_json_text(text: Any) -> Dict[str, Any] | None:
    if not isinstance(text, str):
        text = _coerce_text(text)
    text = (text or "").strip()
    if not text:
        return None
    json_text = _extract_json_block(text)
    if json_text:
        try:
            data = json.loads(json_text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            recovered = _recover_jsonish_object(json_text)
            if recovered:
                return recovered
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        recovered = _recover_jsonish_object(text)
        if recovered:
            return recovered
        return None
    return None


def _should_try_next_llm(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    keywords = (
        "quota",
        "out of quota",
        "insufficient",
        "balance",
        "limit",
        "throttl",
        "rate",
        "exceeded",
        "forbidden",
        "permission",
        "no permission",
        "access denied",
        "model not found",
        "unsupported",
        "not support",
        "invalid model",
        "no available",
        "429",
        "余额",
        "配额",
        "限流",
        "不足",
        "超限",
    )
    return any(k in msg for k in keywords)


def _ensure_cfg_list(cfg: LLMConfig | list[LLMConfig]) -> list[LLMConfig]:
    if isinstance(cfg, list):
        return cfg
    return [cfg]


def generate_draft(
    cfg: LLMConfig | list[LLMConfig],
    *,
    title_hint: str,
    prompt_hint: str,
    asset_paths: List[str],
    max_title: int = 20,
    max_body: int = 1000,
) -> Dict[str, Any]:
    """
    Generate a structured draft (title/body/topics) using the configured LLM.
    Fallback to offline template if the API call fails.
    """
    cfg_list = _ensure_cfg_list(cfg)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a Xiaohongshu image-post assistant. Write in Chinese. "
                    "Generate a short title and body. Title <= 20 chars. Body <= 1000 chars. "
                    "Body must be at least 200 Chinese characters (count punctuation). "
                    "If the body is shorter, expand it with more explanation or commentary. "
                    "If the initial title is long, rewrite it into <= 20 chars (do NOT just truncate with '...'). "
                    "Body may include hashtags (e.g. #topic) but do not spam. "
                    "Only output the final publishable article body. Do NOT include any prompt text, requirements, metadata, or links. "
                    "If the prompt includes news details (e.g. title/source/time/url or mentions 每日新闻), "
                    "do NOT fabricate facts; only use the provided news information. "
                    "When information is limited, stay conservative and avoid adding specifics. "
                    "Return strict JSON only: no Markdown, no code fences, no extra text. "
                    "JSON keys: title, body, topics (array of strings). "
                    "Optional JSON key: image_event (a short event-only description for image generation). "
                    "The body is normally plain text; if the user prompt explicitly requires body to be a JSON object text, follow that stricter body format."
                ),
            ),
            (
                "user",
                (
                    "Prompt: {prompt_hint}\n"
                    "Initial title: {title_hint}\n"
                    "Assets (for reference only, do not output paths): {assets}\n"
                    "Return a JSON object with title/body/topics (and optionally image_event)."
                ),
            ),
        ]
    )

    messages = prompt.format_messages(
        prompt_hint=prompt_hint,
        title_hint=(title_hint or "").strip(),
        assets=", ".join(asset_paths) if asset_paths else "none",
    )

    last_exc: Exception | None = None
    for idx, llm_cfg in enumerate(cfg_list):
        try:
            model = init_chat_model(
                llm_cfg.model,
                model_provider="openai",  # use OpenAI-compatible API
                base_url=llm_cfg.base_url,
                api_key=llm_cfg.api_key,
                temperature=0.4,
                max_tokens=DEFAULT_LLM_MAX_TOKENS,
            )
            print(
                f"[llm] provider={llm_cfg.provider} model={llm_cfg.model} base_url={llm_cfg.base_url}"
            )
            resp = model.invoke(messages)
            text = resp.content if hasattr(resp, "content") else str(resp)
            break
        except Exception as exc:
            last_exc = exc
            if idx + 1 < len(cfg_list) and _should_try_next_llm(exc):
                continue
            text = json.dumps(
                {
                    "title": _truncate((title_hint or "标题").strip(), max_title),
                    "body": "（生成失败，请稍后重试）",
                    "topics": [],
                    "image_event": "",
                    "_fallback_error": str(exc),
                },
                ensure_ascii=False,
            )
            break

    data = _parse_json_text(text)
    if data is None:
        data = {"title": title_hint, "body": text, "topics": [], "image_event": ""}

    raw_title = _coerce_text(data.get("title", title_hint)).strip()
    raw_body = _coerce_text(data.get("body", "")).strip()
    if _looks_like_jsonish_payload(raw_body):
        parsed_body = _parse_json_text(raw_body)
        if parsed_body and isinstance(parsed_body, dict):
            nested_body = _coerce_text(parsed_body.get("body") or parsed_body.get("text")).strip()
            if nested_body:
                raw_body = nested_body
            nested_title = _coerce_text(parsed_body.get("title")).strip()
            if nested_title and (not raw_title or raw_title == title_hint):
                raw_title = nested_title
            nested_topics = _normalize_topics(parsed_body.get("topics"))
            if nested_topics and not _normalize_topics(data.get("topics")):
                data["topics"] = nested_topics
            nested_event = _coerce_text(parsed_body.get("image_event")).strip()
            if nested_event and not _coerce_text(data.get("image_event")).strip():
                data["image_event"] = nested_event

    raw_body = _sanitize_body(raw_body)

    if not raw_title:
        raw_title = title_hint
    if not raw_body:
        raw_body = prompt_hint

    data["title"] = _truncate(raw_title, max_title)
    data["body"] = _truncate(raw_body, max_body)
    data["topics"] = _normalize_topics(data.get("topics"))
    data.setdefault("image_event", "")
    return data
