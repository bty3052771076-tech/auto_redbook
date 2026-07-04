from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


SourceKind = Literal["official", "social", "github", "search"]


@dataclass(frozen=True)
class AIDigestSource:
    name: str
    kind: SourceKind
    url: str
    vendor: str
    parser: str = "rss"
    enabled: bool = True


def default_ai_digest_sources() -> list[AIDigestSource]:
    return [
        AIDigestSource("openai", "official", "https://openai.com/news/rss.xml", "OpenAI", "rss"),
        AIDigestSource("anthropic", "official", "https://www.anthropic.com/news/rss.xml", "Anthropic", "rss"),
        AIDigestSource("deepmind", "official", "https://deepmind.google/blog/rss.xml", "Google DeepMind", "rss"),
        AIDigestSource("metaai", "official", "https://ai.meta.com/blog/rss/", "Meta AI", "rss"),
        AIDigestSource("microsoft", "official", "https://blogs.microsoft.com/ai/feed/", "Microsoft AI", "rss"),
        AIDigestSource("nvidia", "official", "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "NVIDIA", "rss"),
        AIDigestSource("huggingface", "official", "https://huggingface.co/blog/feed.xml", "Hugging Face", "rss"),
        AIDigestSource(
            "github-ai",
            "github",
            "https://api.github.com/repos/huggingface/transformers/releases",
            "Hugging Face",
            "github_releases",
        ),
        AIDigestSource("aliyun", "official", "https://help.aliyun.com/zh/model-studio/release-notes", "阿里云百炼", "html"),
        AIDigestSource("zhipu-glm", "official", "https://docs.bigmodel.cn/cn/update/new-releases", "智谱 GLM", "html"),
        AIDigestSource("minimax", "official", "https://platform.minimax.io/docs/release-notes/models", "MiniMax", "html"),
        AIDigestSource("doubao", "official", "https://www.volcengine.com/docs/82379/1159178", "火山方舟/豆包", "html"),
        AIDigestSource("baidu-qianfan", "official", "https://cloud.baidu.com/doc/qianfan/s/Kmh4stnjp", "百度千帆/文心", "html"),
        AIDigestSource("moonshot-kimi", "official", "https://platform.moonshot.cn/blog/tags/announcement", "月之暗面 Kimi", "html"),
        AIDigestSource("aihot-daily", "search", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily"),
        AIDigestSource("x", "social", "https://x.com/search?q=AI%20model%20release&f=live", "X", "social_html", enabled=False),
        AIDigestSource("hackernews", "social", "https://hn.algolia.com/?q=AI%20model", "Hacker News", "social_html", enabled=False),
    ]


def _split_env_names(value: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;\s]+", value or ""):
        name = part.strip().lower()
        if not name or name in seen:
            continue
        out.append(name)
        seen.add(name)
    return out


def resolve_ai_digest_sources(env: dict[str, str] | None = None) -> list[AIDigestSource]:
    env = env if env is not None else os.environ
    primary_names = _split_env_names(env.get("AI_DIGEST_PRIMARY_SOURCES", ""))
    social_names = _split_env_names(env.get("AI_DIGEST_SOCIAL_SOURCES", ""))
    sources = default_ai_digest_sources()
    by_name = {source.name: source for source in sources}

    if not primary_names:
        primary = [source for source in sources if source.kind in {"official", "github"} and source.enabled]
    else:
        primary = [by_name[name] for name in primary_names if name in by_name]

    if not social_names:
        social = [source for source in sources if source.kind == "search" and source.enabled]
    else:
        social = [by_name[name] for name in social_names if name in by_name]
    return [*primary, *social]
