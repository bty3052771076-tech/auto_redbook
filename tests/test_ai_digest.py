from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ai_digest.models import AIUpdateItem
from src.ai_digest import rank as rank_mod
from src.ai_digest.rank import ai_digest_quota_counts, rank_ai_updates


def _item(
    title: str,
    *,
    url: str | None = None,
    source_type: str = "official",
    source_name: str = "OpenAI",
    published_at: str = "2026-06-30T08:00:00Z",
    summary: str | None = None,
    raw_excerpt: str | None = None,
    product: str = "AI",
    evidence_urls: list[str] | None = None,
    confidence_score: float = 0.0,
) -> AIUpdateItem:
    return AIUpdateItem(
        title=title,
        summary=summary if summary is not None else f"{title} summary",
        source_name=source_name,
        source_type=source_type,
        url=f"https://example.com/{title}" if url is None else url,
        published_at=published_at,
        vendor=source_name,
        product=product,
        raw_excerpt=raw_excerpt if raw_excerpt is not None else f"{title} raw excerpt",
        confidence_score=confidence_score,
        evidence_urls=evidence_urls or [],
        tags=["AI"],
    )


def test_ai_update_item_normalizes_url_key_and_source_type():
    item = _item(
        "OpenAI 发布新功能",
        url="https://openai.com/news/example/?utm_source=x#section",
    )

    assert item.source_type == "official"
    assert item.dedupe_key == "url:https://openai.com/news/example/"
    assert item.verification_status == "official_only"


def test_rank_ai_updates_dedupes_by_url_and_title_prefers_official():
    official = _item("Claude Code 更新", url="https://anthropic.com/news/code", source_name="Anthropic")
    social_duplicate = _item(
        "Claude Code 更新",
        url="https://x.com/AnthropicAI/status/1",
        source_type="social",
        source_name="X",
    )
    same_url = _item("Claude Code 更新细节", url="https://anthropic.com/news/code")

    ranked = rank_ai_updates([social_duplicate, same_url, official], target_count=10)

    assert len(ranked) == 1
    assert ranked[0].source_type == "official"
    assert ranked[0].source_name == "Anthropic"
    assert ranked[0].verification_status == "social_confirmed"
    assert "https://x.com/AnthropicAI/status/1" in ranked[0].evidence_urls


def test_rank_ai_updates_backfills_with_social_when_official_sources_are_too_few():
    official = [_item(f"官方动态{i}", source_name="OpenAI") for i in range(3)]
    social = [
        _item(f"社交动态{i}", source_type="social", source_name="X", url=f"https://x.com/a/{i}")
        for i in range(12)
    ]

    ranked = rank_ai_updates(
        official + social,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
    )

    assert len(ranked) == 10
    assert sum(1 for item in ranked if item.source_type == "official") == 3
    assert sum(1 for item in ranked if item.source_type == "social") == 7


def test_rank_ai_updates_excludes_social_only_when_official_sources_are_enough():
    official = [_item(f"官方动态{i}", source_name="OpenAI") for i in range(10)]
    social = [
        _item(f"社交动态{i}", source_type="social", source_name="X", url=f"https://x.com/a/{i}")
        for i in range(4)
    ]

    ranked = rank_ai_updates(
        official + social,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
    )

    assert len(ranked) == 10
    assert all(item.source_type == "official" for item in ranked)


def test_rank_ai_updates_preserves_recent_official_vendor_diversity():
    openai = [
        _item(
            f"OpenAI当日动态{i}",
            source_name="OpenAI",
            url=f"https://openai.com/{i}",
            published_at=f"2026-06-30T{12 - (i % 12):02d}:00:00Z",
        )
        for i in range(12)
    ]
    other_vendors = [
        _item(
            "智谱GLM当日模型更新",
            source_name="智谱 GLM",
            url="https://docs.bigmodel.cn/update/glm",
            published_at="2026-06-30T09:00:00Z",
        ),
        _item(
            "MiniMax当日模型更新",
            source_name="MiniMax",
            url="https://platform.minimax.io/docs/release-notes/models",
            published_at="2026-06-30T08:00:00Z",
        ),
        _item(
            "通义千问当日模型更新",
            source_name="阿里云百炼",
            url="https://help.aliyun.com/model-studio/release-notes",
            published_at="2026-06-30T07:00:00Z",
        ),
    ]

    ranked = rank_ai_updates(
        openai + other_vendors,
        target_count=10,
        min_official_count=6,
        allow_social_backfill=True,
    )

    vendors = [item.vendor for item in ranked]
    assert {"智谱 GLM", "MiniMax", "阿里云百炼"}.issubset(set(vendors))
    assert vendors.count("OpenAI") < 10


def test_rank_ai_updates_prefers_newer_official_items_before_confidence_boosts():
    newer = _item(
        "今日模型更新",
        source_name="OpenAI",
        url="https://openai.com/today",
        published_at="2026-06-30T08:00:00Z",
    )
    older_with_social_evidence = _item(
        "昨日模型更新",
        source_name="OpenAI",
        url="https://openai.com/yesterday",
        published_at="2026-06-29T15:00:00Z",
        evidence_urls=["https://x.com/OpenAI/status/1"],
    )

    ranked = rank_ai_updates(
        [older_with_social_evidence, newer],
        target_count=2,
        min_official_count=1,
        allow_social_backfill=True,
    )

    assert [item.title for item in ranked] == ["今日模型更新", "昨日模型更新"]


def test_rank_ai_updates_keeps_only_recent_linked_items_and_caps_twenty():
    now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
    today_high = _item(
        "今日高关注模型更新",
        source_name="OpenAI",
        published_at="2026-07-02T08:00:00Z",
        confidence_score=0.95,
    )
    today_low = _item(
        "今日低关注工具更新",
        source_name="OpenAI",
        published_at="2026-07-02T09:00:00Z",
        confidence_score=0.5,
    )
    yesterday_high = _item(
        "昨日高关注模型更新",
        source_name="Anthropic",
        published_at="2026-07-01T10:00:00Z",
        confidence_score=0.99,
    )
    stale = _item(
        "一月旧模型更新",
        source_name="OpenAI",
        published_at="2026.1.5",
        confidence_score=0.99,
    )
    missing_link = _item(
        "今日无链接更新",
        source_name="OpenAI",
        url="",
        published_at="2026-07-02T10:00:00Z",
        confidence_score=1.0,
    )
    fillers = [
        _item(
            f"三天内补充动态{i}",
            source_name=f"Vendor{i % 5}",
            published_at="2026-06-30T12:00:00Z",
            confidence_score=0.6,
        )
        for i in range(25)
    ]

    ranked = rank_ai_updates(
        [yesterday_high, stale, missing_link, today_low, *fillers, today_high],
        target_count=20,
        min_official_count=1,
        allow_social_backfill=True,
        max_age_days=3,
        now=now,
    )

    assert len(ranked) == 20
    assert [item.title for item in ranked[:3]] == [
        "今日高关注模型更新",
        "今日低关注工具更新",
        "昨日高关注模型更新",
    ]
    assert "一月旧模型更新" not in [item.title for item in ranked]
    assert "今日无链接更新" not in [item.title for item in ranked]


def test_rank_ai_updates_dedupes_same_model_topic_from_distinct_urls():
    intro = _item(
        "OpenAI Introducing GeneBench-Pro Introducing GeneBench-更新",
        url="https://openai.com/index/introducing-genebench-pro",
        summary="OpenAI introduces GeneBench-Pro, a genomics benchmark for AI systems.",
        raw_excerpt="Introducing GeneBench-Pro, a new benchmark testing AI performance in genomics.",
        product="",
        confidence_score=0.92,
    )
    case_study = _item(
        "OpenAI Inside Genebench-Pro更新",
        url="https://openai.com/index/genebench-pro/case-studies",
        summary="Inside GeneBench-Pro case studies for biology and genomics.",
        raw_excerpt="Case studies explaining the GeneBench-Pro benchmark.",
        product="",
        confidence_score=0.88,
    )
    other = _item(
        "OpenAI core dump infrastructure bug",
        url="https://openai.com/index/core-dump-epidemiology-data-infrastructure-bug",
        summary="OpenAI engineers describe infrastructure debugging with core dump analysis.",
        raw_excerpt="OpenAI engineers debug rare infrastructure crashes.",
        confidence_score=0.86,
    )

    ranked = rank_ai_updates(
        [case_study, other, intro],
        target_count=10,
        min_official_count=1,
        now=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        max_age_days=3,
    )

    titles = [item.title for item in ranked]
    assert sum("genebench" in title.lower() for title in titles) == 1
    genebench = next(item for item in ranked if "genebench" in item.title.lower())
    assert "https://openai.com/index/genebench-pro/case-studies" in genebench.evidence_urls
    assert "OpenAI core dump infrastructure bug" in titles


def test_rank_ai_updates_dedupes_same_model_family_variants_from_one_release():
    preview = _item(
        "DeepSeek-V4 预览版发布",
        source_name="DeepSeek",
        url="https://api-docs.deepseek.com/zh-cn/news/news260424",
        published_at="2026-04-24",
        product="DeepSeek-V4",
        raw_excerpt="DeepSeek-V4 预览版发布 2026/04/24",
    )
    pro = _item(
        "DeepSeek-V4-Pro：性能比肩顶级闭源模型",
        source_name="DeepSeek",
        url="https://api-docs.deepseek.com/zh-cn/news/news260424#deepseek-v4-pro",
        published_at="2026-04-24",
        product="DeepSeek-V4-Pro",
        raw_excerpt="DeepSeek-V4-Pro Agent 能力大幅提高。",
    )
    flash = _item(
        "DeepSeek-V4-Flash：更快捷高效的经济之选",
        source_name="DeepSeek",
        url="https://api-docs.deepseek.com/zh-cn/news/news260424#deepseek-v4-flash",
        published_at="2026-04-24",
        product="DeepSeek-V4-Flash",
        raw_excerpt="DeepSeek-V4-Flash 展现接近的推理能力。",
    )

    ranked = rank_ai_updates(
        [flash, pro, preview],
        target_count=10,
        min_official_count=1,
        now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc),
        max_age_days=3,
    )

    titles = [item.title for item in ranked]
    assert sum("DeepSeek-V4" in title for title in titles) == 1


def test_rank_ai_updates_uses_beijing_three_calendar_days():
    now = datetime(2026, 7, 2, 16, 28, tzinfo=timezone(timedelta(hours=8)))
    beijing_day_before_yesterday = _item(
        "北京时间前天凌晨的新动态",
        published_at="2026-06-29T18:00:00Z",
    )
    beijing_three_days_ago = _item(
        "北京时间大前天的旧动态",
        published_at="2026-06-29T08:29:00Z",
    )

    ranked = rank_ai_updates(
        [beijing_three_days_ago, beijing_day_before_yesterday],
        target_count=10,
        min_official_count=1,
        max_age_days=3,
        now=now,
    )

    assert [item.title for item in ranked] == ["北京时间前天凌晨的新动态"]
    assert rank_mod.ai_update_beijing_day_key(ranked[0]) == "2026-06-30"


def test_rank_ai_updates_enforces_daily_digest_domestic_model_and_foreign_quotas():
    now = datetime(2026, 7, 3, 11, 30, tzinfo=timezone(timedelta(hours=8)))
    domestic_models = [
        _item(
            "GLM-5.2 模型版本发布",
            source_name="智谱 GLM",
            url="https://docs.bigmodel.cn/cn/update/glm-5-2",
            published_at="2026-07-03T01:00:00Z",
            product="GLM-5.2",
            confidence_score=0.72,
        ),
        _item(
            "Qwen3-Coder API 升级",
            source_name="阿里云百炼",
            url="https://help.aliyun.com/model-studio/qwen3-coder",
            published_at="2026-07-02T10:00:00Z",
            product="Qwen3-Coder",
            confidence_score=0.68,
        ),
        _item(
            "豆包 Doubao-Seed 模型更新",
            source_name="火山方舟",
            url="https://www.volcengine.com/docs/ark/doubao-seed",
            published_at="2026-07-01T09:00:00Z",
            product="Doubao-Seed",
            confidence_score=0.66,
        ),
    ]
    foreign_updates = [
        _item(
            "OpenAI GPT-5.2 API 更新",
            source_name="OpenAI",
            url="https://openai.com/index/gpt-5-2-api",
            published_at="2026-07-03T03:00:00Z",
            product="GPT-5.2",
            confidence_score=0.94,
        ),
        _item(
            "Anthropic Claude Code 工具更新",
            source_name="Anthropic",
            url="https://www.anthropic.com/news/claude-code",
            published_at="2026-07-02T05:00:00Z",
            product="Claude Code",
            confidence_score=0.91,
        ),
        _item(
            "Google Gemini 推理能力升级",
            source_name="Google DeepMind",
            url="https://deepmind.google/discover/blog/gemini-reasoning",
            published_at="2026-07-01T06:00:00Z",
            product="Gemini",
            confidence_score=0.9,
        ),
    ]
    high_attention_supplements = [
        _item(
            f"AI 行业观点讨论{i}",
            source_name="Hugging Face",
            url=f"https://huggingface.co/blog/ai-trend-{i}",
            published_at="2026-07-03T02:00:00Z",
            summary="观点探讨，分析 AI 专业化趋势。",
            raw_excerpt="Opinion: why AI specialization is inevitable.",
            confidence_score=0.99 - i * 0.01,
        )
        for i in range(5)
    ]
    stale = _item(
        "DeepSeek 上月模型动态",
        source_name="DeepSeek",
        url="https://api-docs.deepseek.com/news/old",
        published_at="2026-06-15T08:00:00Z",
        product="DeepSeek",
        confidence_score=0.99,
    )

    ranked = rank_ai_updates(
        [*high_attention_supplements, *foreign_updates, stale, *domestic_models],
        target_count=8,
        min_official_count=1,
        allow_social_backfill=True,
        max_age_days=3,
        now=now,
        min_domestic_model_count=3,
        min_foreign_ai_count=3,
    )

    counts = ai_digest_quota_counts(ranked)
    titles = [item.title for item in ranked]
    assert len(ranked) == 8
    assert counts["domestic_model"] >= 3
    assert counts["foreign_ai"] >= 3
    assert "DeepSeek 上月模型动态" not in titles


def test_ai_update_region_recognizes_new_domestic_model_families():
    longcat = _item(
        "美团 LongCat-2.0 正式发布：国产算力集群训练的万亿参数大模型",
        source_name="AI HOT",
        url="https://aihot.virxact.com/daily/2026-07-02?item=1",
        published_at="2026-07-02T08:00:00+08:00",
        product="LongCat-2.0",
        summary="美团发布新一代万亿参数大模型LongCat-2.0并开源，原生支持1M超长上下文。",
    )
    skywork = _item(
        "昆仑万维天工3.2发布Skywork Tags，AI智能体加入工作群聊",
        source_name="AI HOT",
        url="https://aihot.virxact.com/daily/2026-07-03?item=11",
        published_at="2026-07-03T08:00:00+08:00",
        product="Skywork Tags",
        summary="昆仑万维发布天工3.2相关更新，加入AI智能体协作能力。",
    )

    assert rank_mod.ai_update_region(longcat) == "domestic"
    assert rank_mod.ai_update_is_model_news(longcat)
    assert rank_mod.ai_update_region(skywork) == "domestic"


def test_rank_ai_updates_prioritizes_technical_model_updates_over_discussion_on_same_beijing_day():
    today_discussion = _item(
        "为什么 AI 专业化是必然趋势",
        source_name="Hugging Face",
        published_at="2026-07-02T02:00:00Z",
        summary="这是一篇观点探讨，分析 AI 专业化为何可能成为趋势。",
        raw_excerpt="Why specialization is inevitable for AI systems.",
        confidence_score=0.99,
    )
    today_model = _item(
        "GLM-5.3 模型版本发布",
        source_name="智谱 GLM",
        url="https://docs.bigmodel.cn/cn/update/glm-5-3",
        published_at="2026-07-02T01:00:00Z",
        summary="GLM-5.3 模型发布，提升多模态理解、代码生成和推理能力。",
        raw_excerpt="GLM-5.3 model release improves multimodal reasoning and coding.",
        product="GLM-5.3",
        confidence_score=0.78,
    )
    yesterday_tool = _item(
        "Claude Code 工具更新",
        source_name="Anthropic",
        published_at="2026-07-01T10:00:00Z",
        summary="Claude Code 增加开发者工具能力。",
        raw_excerpt="Claude Code developer tool update.",
        confidence_score=0.9,
    )

    ranked = rank_ai_updates(
        [today_discussion, yesterday_tool, today_model],
        target_count=10,
        min_official_count=1,
        max_age_days=3,
        now=datetime(2026, 7, 2, 16, 28, tzinfo=timezone(timedelta(hours=8))),
    )

    assert [item.title for item in ranked] == [
        "GLM-5.3 模型版本发布",
        "为什么 AI 专业化是必然趋势",
        "Claude Code 工具更新",
    ]
    assert rank_mod.ai_update_category(today_model) in {"model_release", "technical_tool"}
    assert rank_mod.ai_update_category(today_discussion) == "discussion"


def test_ai_update_category_keeps_opinion_discussion_as_supplement_even_with_generic_model_words():
    item = _item(
        "Hugging Face Why Specialization Is Inevitable更新",
        source_name="Hugging Face",
        url="https://huggingface.co/blog/Dharma-AI/why-specialization-is-inevitable",
        published_at="2026-06-30T14:39:11Z",
        summary="Hugging Face更新Why Specialization Is Inevitable，原始信息提到模型、工具或平台能力变化。",
        raw_excerpt="Why specialization is inevitable for AI systems.",
        product="",
    )

    assert rank_mod.ai_update_category(item) == "discussion"


def test_rank_ai_updates_interleaves_vendors_only_within_same_category_tier():
    discussion = _item(
        "Dharma AI 探讨：为什么模型专用化不可避免",
        source_name="Hugging Face",
        published_at="2026-06-30T14:39:11Z",
        summary="观点探讨，讨论模型专用化趋势。",
        raw_excerpt="Why specialization is inevitable.",
        confidence_score=0.99,
    )
    technical = _item(
        "OpenAI 核心转储分析修复基础设施缺陷",
        source_name="OpenAI",
        url="https://openai.com/index/core-dump-epidemiology-data-infrastructure-bug",
        published_at="2026-06-30T00:00:00Z",
        summary="OpenAI 通过 core dump 分析排查基础设施 bug。",
        raw_excerpt="Core dump infrastructure debugging.",
        confidence_score=0.7,
    )
    model = _item(
        "GeneBench-Pro 基因组学评测基准发布",
        source_name="OpenAI",
        url="https://openai.com/index/introducing-genebench-pro",
        published_at="2026-06-30T00:00:00Z",
        summary="OpenAI 推出 GeneBench-Pro 基因组学 benchmark。",
        raw_excerpt="GeneBench-Pro benchmark release.",
        confidence_score=0.8,
    )

    ranked = rank_ai_updates(
        [discussion, technical, model],
        target_count=10,
        min_official_count=1,
        max_age_days=3,
        now=datetime(2026, 7, 2, 16, 28, tzinfo=timezone(timedelta(hours=8))),
    )

    assert [item.title for item in ranked] == [
        "GeneBench-Pro 基因组学评测基准发布",
        "OpenAI 核心转储分析修复基础设施缺陷",
        "Dharma AI 探讨：为什么模型专用化不可避免",
    ]
