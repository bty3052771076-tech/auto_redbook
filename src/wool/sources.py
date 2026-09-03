from __future__ import annotations

import os
import re

from src.ai_digest.sources import AIDigestSource, default_ai_digest_sources


_DEFAULT_WOOL_SOURCE_NAMES = {
    # Official vendor announcements are the first source tier.
    "openai",
    "aliyun",
    "qwen-blog",
    "zhipu-glm",
    "zcode",
    "zai-official-blog",
    "deepseek",
    "minimax",
    "doubao",
    "tencent-ai-announcements",
    "bytedance-seed",
    "baidu-qianfan",
    "moonshot-kimi",
    "stepfun",
    # Official social accounts are useful for short-lived resets and claims.
    "x-openai",
    "x-openai-devs",
    "x-anthropic",
    "x-claude-devs",
    "x-sam-altman",
    "x-tibo-maker",
    "x-zcode",
    # Aggregators are a discovery fallback, never proof by themselves.
    "aihot-daily",
    "huggingface",
    "chooseai-zcode-weekend",
}


def _split_names(value: str) -> set[str]:
    return {part.strip().lower() for part in re.split(r"[,;\s]+", value or "") if part.strip()}


def default_wool_sources() -> list[AIDigestSource]:
    sources = default_ai_digest_sources()
    configured = _split_names(os.getenv("WOOL_SOURCES", ""))
    allowed = configured or _DEFAULT_WOOL_SOURCE_NAMES
    return [source for source in sources if source.name in allowed and source.enabled]


def resolve_wool_sources() -> list[AIDigestSource]:
    return default_wool_sources()
