from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
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
    tier: str = ""
    region: str = "global"
    topics: tuple[str, ...] = ()
    priority: int = 0

    def __post_init__(self) -> None:
        if self.tier:
            return
        if self.kind == "aggregator":
            tier = "aggregator"
        elif self.kind in {"social", "search"}:
            tier = "social_backfill" if self.kind == "social" else "search_backfill"
        elif self.kind == "github" or self.parser in {"rss", "github_releases"}:
            tier = "official_stream"
        else:
            tier = "official_page"
        object.__setattr__(self, "tier", tier)


def default_ai_digest_sources() -> list[AIDigestSource]:
    sources = [
        AIDigestSource("openai", "official", "https://openai.com/news/rss.xml", "OpenAI", "rss"),
        AIDigestSource(
            "github-status",
            "official",
            "https://www.githubstatus.com/history.rss",
            "GitHub Status",
            "rss",
            tier="official_stream",
            region="global",
            topics=("incident", "outage", "platform", "service"),
            priority=5,
        ),
        AIDigestSource("anthropic", "official", "https://www.anthropic.com/news", "Anthropic", "html"),
        AIDigestSource("deepmind", "official", "https://deepmind.google/blog/rss.xml", "Google DeepMind", "rss"),
        AIDigestSource("metaai", "official", "https://ai.meta.com/blog", "Meta AI", "html"),
        AIDigestSource("microsoft", "official", "https://blogs.microsoft.com/", "Microsoft AI", "html"),
        AIDigestSource("nvidia", "official", "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "NVIDIA", "rss"),
        AIDigestSource("mistral", "official", "https://mistral.ai/rss.xml", "Mistral AI", "rss"),
        AIDigestSource("xai", "official", "https://x.ai/news", "xAI", "html"),
        AIDigestSource("cohere", "official", "https://cohere.com/newsroom", "Cohere", "html"),
        AIDigestSource("google-gemini", "official", "https://blog.google/products-and-platforms/products/gemini/", "Google Gemini", "html"),
        AIDigestSource("amazon-nova", "official", "https://aws.amazon.com/nova/models/", "Amazon Nova", "html"),
        AIDigestSource("ai21", "official", "https://www.ai21.com/blog/", "AI21 Labs", "html"),
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
        AIDigestSource(
            "deepseek",
            "official",
            "https://api-docs.deepseek.com/updates",
            "DeepSeek",
            "html",
            tier="official_stream",
            region="domestic",
            topics=("model", "api"),
            priority=10,
        ),
        AIDigestSource("minimax", "official", "https://platform.minimax.io/docs/release-notes/models", "MiniMax", "html"),
        AIDigestSource("doubao", "official", "https://www.volcengine.com/docs/82379/1159178", "火山方舟/豆包", "html"),
        AIDigestSource("tencent-hunyuan", "official", "https://hy.tencent.com/", "腾讯混元", "html"),
        AIDigestSource(
            "tencent-ai-announcements",
            "official",
            "https://cloud.tencent.com/announce/",
            "Tencent Cloud AI",
            "html",
            tier="official_stream",
            region="domestic",
            topics=("model", "api", "platform"),
            priority=10,
        ),
        AIDigestSource("stepfun", "official", "https://platform.stepfun.com/docs/zh/guides/models/overview", "阶跃星辰 StepFun", "html"),
        AIDigestSource(
            "bytedance-seed",
            "official",
            "https://seed.bytedance.com/blog",
            "ByteDance Seed",
            "html",
            tier="official_stream",
            region="domestic",
            topics=("model", "multimodal"),
            priority=10,
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
            "https://sensetime.com/en/research/",
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
        AIDigestSource("aihot-daily", "aggregator", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily"),
        AIDigestSource("huggingface", "aggregator", "https://huggingface.co/blog/feed.xml", "Hugging Face", "rss"),
        AIDigestSource(
            "github-ai",
            "aggregator",
            "https://api.github.com/repos/huggingface/transformers/releases",
            "Hugging Face",
            "github_releases",
        ),
        AIDigestSource("x-openai", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/OpenAI", "OpenAI", "x_profile"),
        AIDigestSource("x-openai-devs", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/OpenAIDevs", "OpenAI Developers", "x_profile"),
        AIDigestSource("x-anthropic", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/AnthropicAI", "Anthropic", "x_profile"),
        AIDigestSource("x-claude-devs", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/ClaudeDevs", "Claude Developers", "x_profile"),
        AIDigestSource("x-sam-altman", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/sama", "Sam Altman", "x_profile"),
        AIDigestSource("x-tibo-maker", "social", "https://syndication.twitter.com/srv/timeline-profile/screen-name/tibo_maker", "Tibo", "x_profile"),
        AIDigestSource("x", "social", "https://x.com/search?q=AI%20model%20release&f=live", "X", "social_html", enabled=False),
        AIDigestSource("hackernews", "social", "https://hn.algolia.com/?q=AI%20model", "Hacker News", "social_html", enabled=False),
    ]
    domestic_source_names = {
        "aliyun",
        "qwen-blog",
        "qwen-github",
        "zhipu-glm",
        "zcode",
        "deepseek",
        "minimax",
        "doubao",
        "tencent-hunyuan",
        "tencent-ai-announcements",
        "stepfun",
        "bytedance-seed",
        "baidu-qianfan",
        "moonshot-kimi",
        "iflytek-spark",
        "huawei-pangu",
        "sensetime-sensenova",
        "01ai-yi",
        "01ai-yi-github",
        "baichuan-github",
        "internlm-github",
        "minicpm-github",
        "minicpm-v-github",
        "skywork",
        "kling",
    }
    return [
        replace(source, region="domestic") if source.name in domestic_source_names else source
        for source in sources
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
        social = [source for source in sources if source.kind == "social" and source.enabled]
    else:
        social = [by_name[name] for name in social_names if name in by_name]

    if primary_names and not aggregator_names:
        fallback = []
    elif aggregator_names:
        fallback = [by_name[name] for name in aggregator_names if name in by_name]
    else:
        fallback = [source for source in sources if source.kind == "aggregator" and source.enabled]
    return [*primary, *fallback, *social]
