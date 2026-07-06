from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


SourceKind = Literal["official", "social", "github", "search", "aggregator"]


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
        AIDigestSource("mistral", "official", "https://mistral.ai/rss.xml", "Mistral AI", "rss"),
        AIDigestSource("xai", "official", "https://x.ai/news", "xAI", "html"),
        AIDigestSource("cohere", "official", "https://cohere.com/newsroom", "Cohere", "html"),
        AIDigestSource("google-gemini", "official", "https://ai.google.dev/gemini-api/docs/models", "Google Gemini", "html"),
        AIDigestSource("amazon-nova", "official", "https://aws.amazon.com/nova/models/", "Amazon Nova", "html"),
        AIDigestSource("ai21", "official", "https://docs.ai21.com/changelog", "AI21 Labs", "html"),
        AIDigestSource(
            "perplexity-sonar",
            "official",
            "https://docs.perplexity.ai/docs/sonar/models",
            "Perplexity Sonar",
            "html",
        ),
        AIDigestSource("stability-ai", "official", "https://stability.ai/news", "Stability AI", "html"),
        AIDigestSource("black-forest-labs", "official", "https://bfl.ai/blog", "Black Forest Labs", "html"),
        AIDigestSource("runway", "official", "https://runwayml.com/research", "Runway", "html"),
        AIDigestSource("luma-ai", "official", "https://lumalabs.ai/news", "Luma AI", "html"),
        AIDigestSource("ideogram", "official", "https://docs.ideogram.ai/about-ideogram/blog-posts", "Ideogram", "html"),
        AIDigestSource("recraft", "official", "https://www.recraft.ai/blog", "Recraft", "html"),
        AIDigestSource("aliyun", "official", "https://help.aliyun.com/zh/model-studio/release-notes", "阿里云百炼", "html"),
        AIDigestSource("qwen-blog", "official", "https://qwen.ai/blog", "Qwen/通义千问", "html"),
        AIDigestSource(
            "qwen-github",
            "github",
            "https://api.github.com/repos/QwenLM/Qwen3/releases",
            "Qwen/通义千问",
            "github_releases",
        ),
        AIDigestSource("zhipu-glm", "official", "https://docs.bigmodel.cn/cn/update/new-releases", "智谱 GLM", "html"),
        AIDigestSource("zcode", "official", "https://zcode.z.ai/cn", "智谱 ZCode", "html"),
        AIDigestSource("deepseek", "official", "https://www.deepseek.com/", "DeepSeek", "html"),
        AIDigestSource("minimax", "official", "https://platform.minimax.io/docs/release-notes/models", "MiniMax", "html"),
        AIDigestSource("doubao", "official", "https://www.volcengine.com/docs/82379/1159178", "火山方舟/豆包", "html"),
        AIDigestSource("tencent-hunyuan", "official", "https://hy.tencent.com/", "腾讯混元", "html"),
        AIDigestSource("stepfun", "official", "https://platform.stepfun.com/docs/zh/guides/models/overview", "阶跃星辰 StepFun", "html"),
        AIDigestSource(
            "bytedance-seed",
            "official",
            "https://seed.bytedance.com/en/blog/seed2-1-officially-released-advancing-ai-productivity",
            "ByteDance Seed",
            "html",
        ),
        AIDigestSource("baidu-qianfan", "official", "https://cloud.baidu.com/doc/qianfan/s/Kmh4stnjp", "百度千帆/文心", "html"),
        AIDigestSource("moonshot-kimi", "official", "https://platform.moonshot.cn/blog/tags/announcement", "月之暗面 Kimi", "html"),
        AIDigestSource("iflytek-spark", "official", "https://xinghuo.xfyun.cn/", "iFLYTEK Spark", "html"),
        AIDigestSource(
            "huawei-pangu",
            "official",
            "https://www.huaweicloud.com/intl/en-us/news/20250620192415143.html",
            "Huawei Pangu",
            "html",
        ),
        AIDigestSource(
            "sensetime-sensenova",
            "official",
            "https://www.sensetime.com/en/news-detail/51170629?categoryId=1072",
            "SenseTime SenseNova",
            "html",
        ),
        AIDigestSource("01ai-yi", "official", "https://www.01.ai/", "01.AI Yi", "html"),
        AIDigestSource(
            "01ai-yi-github",
            "github",
            "https://api.github.com/repos/01-ai/yi/releases",
            "01.AI Yi",
            "github_releases",
        ),
        AIDigestSource(
            "baichuan-github",
            "github",
            "https://api.github.com/repos/baichuan-inc/Baichuan2/releases",
            "Baichuan",
            "github_releases",
        ),
        AIDigestSource(
            "internlm-github",
            "github",
            "https://api.github.com/repos/InternLM/InternLM/releases",
            "InternLM",
            "github_releases",
        ),
        AIDigestSource(
            "minicpm-github",
            "github",
            "https://api.github.com/repos/OpenBMB/MiniCPM/releases",
            "OpenBMB MiniCPM",
            "github_releases",
        ),
        AIDigestSource(
            "minicpm-v-github",
            "github",
            "https://api.github.com/repos/OpenBMB/MiniCPM-V/releases",
            "OpenBMB MiniCPM-V",
            "github_releases",
        ),
        AIDigestSource("skywork", "official", "https://www.kunlun.com/", "Skywork", "html"),
        AIDigestSource(
            "kling",
            "official",
            "https://ir.kuaishou.com/news-releases/news-release-details/kling-ai-launches-30-model-ushering-era-where-everyone-can-be",
            "Kling AI",
            "html",
        ),
        AIDigestSource("aihot-daily", "search", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily"),
        AIDigestSource("huggingface", "aggregator", "https://huggingface.co/blog/feed.xml", "Hugging Face", "rss"),
        AIDigestSource(
            "github-ai",
            "aggregator",
            "https://api.github.com/repos/huggingface/transformers/releases",
            "Hugging Face",
            "github_releases",
        ),
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
    aggregator_names = _split_env_names(env.get("AI_DIGEST_AGGREGATOR_SOURCES", ""))
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

    if primary_names and not aggregator_names:
        fallback = []
    elif aggregator_names:
        fallback = [by_name[name] for name in aggregator_names if name in by_name]
    else:
        fallback = [source for source in sources if source.kind == "aggregator" and source.enabled]
    return [*primary, *social, *fallback]
