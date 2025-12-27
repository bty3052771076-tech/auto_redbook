from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate

from src.config import LLMConfig


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


def _parse_json_text(text: str) -> Dict[str, Any] | None:
    json_text = _extract_json_block(text)
    if json_text:
        try:
            data = json.loads(json_text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None
    return None


def generate_draft(
    cfg: LLMConfig,
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
    model = init_chat_model(
        cfg.model,
        model_provider="openai",  # use OpenAI-compatible API
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        temperature=0.4,
        max_tokens=800,
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a Xiaohongshu image-post assistant. Write in Chinese. "
                    "Generate a short title and body. Title <= 20 chars. Body <= 1000 chars. "
                    "Body may include hashtags (e.g. #topic) but do not spam. "
                    "Return strict JSON only: no Markdown, no code fences, no extra text. "
                    "JSON keys: title, body, topics (array of strings). "
                    "The body must be plain text, not JSON or a list."
                ),
            ),
            (
                "user",
                (
                    "Prompt: {prompt_hint}\n"
                    "Initial title: {title_hint}\n"
                    "Assets (for reference only, do not output paths): {assets}\n"
                    "Return a JSON object with title/body/topics."
                ),
            ),
        ]
    )

    messages = prompt.format_messages(
        prompt_hint=prompt_hint,
        title_hint=_truncate(title_hint, max_title),
        assets=", ".join(asset_paths) if asset_paths else "none",
    )

    try:
        resp = model.invoke(messages)
        text = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        text = json.dumps(
            {
                "title": _truncate(title_hint or "Title", max_title),
                "body": _truncate(f"{prompt_hint}\n(offline fallback)", max_body),
                "topics": [],
                "_fallback_error": str(exc),
            },
            ensure_ascii=False,
        )

    data = _parse_json_text(text)
    if data is None:
        data = {"title": title_hint, "body": text, "topics": []}

    raw_title = _coerce_text(data.get("title", title_hint)).strip()
    raw_body = _coerce_text(data.get("body", "")).strip()
    if raw_body.startswith("{") or raw_body.startswith("["):
        parsed_body = _parse_json_text(raw_body)
        if parsed_body and isinstance(parsed_body, dict):
            raw_body = _coerce_text(parsed_body.get("body") or parsed_body.get("text") or raw_body)

    if not raw_title:
        raw_title = title_hint
    if not raw_body:
        raw_body = prompt_hint

    data["title"] = _truncate(raw_title, max_title)
    data["body"] = _truncate(raw_body, max_body)
    data["topics"] = _normalize_topics(data.get("topics"))
    return data
