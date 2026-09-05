from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from src.ai_digest.fetchers import parse_benefit_html, parse_codex_reset_html
from src.ai_digest.models import AIUpdateItem
from src.storage.files import list_posts
from src.wool.collect import extract_wool_offers
from src.wool.render import ensure_wool_assets
from src.wool.workflow import _deterministic_copy, create_daily_wool_posts
from src.wool.models import WoolOffer


def _update(
    title: str,
    *,
    published_at: str,
    url: str = "https://example.com/wool",
    source_name: str = "ZCode 官方",
    summary: str = "官方活动说明",
) -> AIUpdateItem:
    return AIUpdateItem(
        title=title,
        summary=summary,
        source_name=source_name,
        source_type="official",
        url=url,
        published_at=published_at,
        vendor=source_name,
        product="GLM-5.3",
        raw_excerpt=summary,
        tags=["AI", "region:domestic"],
    )


def test_extract_wool_offers_accepts_concrete_free_quota_notice():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "ZCode 领取 3B GLM5.3 额度",
            published_at="2026-08-28T09:00:00+08:00",
            summary="登录 ZCode 可领取 3B GLM5.3 免费额度，活动规则见官方页面。",
        )
    ]

    offers = extract_wool_offers(items, now=now, max_age_days=3)

    assert len(offers) == 1
    assert "免费" in offers[0].benefit or "领取" in offers[0].benefit
    assert offers[0].url == items[0].url


def test_parse_codex_reset_tracker_keeps_today_reset_and_x_evidence():
    html = (
        '<script>\\"resetAt\\":\\"2026-09-04T03:34:46.386Z\\",'
        '\\"note\\":\\"A BANKED Reset was distributed to paid ChatGPT users who still do not have access to GPT-6 Astra.\\",'
        '\\"source\\":\\"https://x.com/thsottiaux/status/2095651088502591861\\"</script>'
    )

    items = parse_codex_reset_html(
        html,
        source_name="Codex Reset Observatory",
        vendor="Codex Reset Observatory",
        base_url="https://codex.gussuriworks.com/en",
    )

    assert len(items) == 1
    assert items[0].published_at.startswith("2026-09-04T03:34")
    assert items[0].evidence_urls == [
        "https://x.com/thsottiaux/status/2095651088502591861",
        "https://codex.gussuriworks.com/en",
    ]


def test_extract_wool_offers_accepts_current_codex_reset_signal():
    now = datetime(2026, 9, 4, 12, tzinfo=timezone(timedelta(hours=8)))
    item = AIUpdateItem(
        title="OpenAI Codex向符合条件的付费用户发放银行重置",
        summary=(
            "公开重置追踪页记录：OpenAI Codex向部分付费ChatGPT用户发放银行重置；"
            "重置可由符合条件的用户自行使用，最终以账户页面为准。"
        ),
        source_name="Codex Reset Observatory",
        source_type="aggregator",
        url="https://codex.gussuriworks.com/en",
        published_at="2026-09-04T03:34:46.386Z",
        vendor="Codex Reset Observatory",
        product="Codex banked reset",
        raw_excerpt="公开重置追踪页记录，最终以账户页面为准。",
    )

    offers = extract_wool_offers([item], now=now, max_age_days=3)

    assert len(offers) == 1
    assert offers[0].provider == "OpenAI"
    assert offers[0].published_at.startswith("2026-09-04T11:34")


def test_extract_wool_offers_accepts_zcode_weekend_token_wording():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "ZCode新版本免费提前领取Weekend Plan",
            published_at="2026-08-28T09:00:00+08:00",
            source_name="ChooseAI",
            summary=(
                "ZCode Weekend Build活动赠送3亿GLM-5.3-Flash Tokens，登录客户端后领取，"
                "本周五20:00至8月31日09:00有效。"
            ),
        )
    ]

    offers = extract_wool_offers(items, now=now, max_age_days=3)

    assert len(offers) == 1
    assert "3亿" in offers[0].benefit
    assert "evidence:" in " ".join(offers[0].tags)


def test_extract_wool_offers_rejects_vague_free_or_release_copy():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "ZCode披露AI产品变化",
            published_at="2026-08-28T09:00:00+08:00",
            summary="ZCode发布新版本并带来更好的体验。",
        ),
        _update(
            "某模型提供免费使用",
            published_at="2026-08-28T09:00:00+08:00",
            summary="平台介绍了模型能力和产品升级。",
        ),
    ]

    assert extract_wool_offers(items, now=now, max_age_days=3) == []


def test_extract_wool_offers_deduplicates_3b_and_300m_mirrors():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "ZCode周末送3亿GLM-5.3-Flash Token",
            published_at="2026-08-28T09:00:00+08:00",
            source_name="ChooseAI",
            summary="登录客户端领取300M tokens，8月31日09:00截止。",
            url="https://example.com/chooseai",
        ).model_copy(update={"source_type": "aggregator"}),
        _update(
            "ZCode Weekend Build: 300M GLM-5.3-Flash tokens",
            published_at="2026-08-28T10:00:00+08:00",
            source_name="社区线索",
            summary="登录 ZCode 后领取 300M tokens，valid until Aug 31。",
            url="https://example.com/community",
        ).model_copy(update={"source_type": "search"}),
    ]

    offers = extract_wool_offers(items, now=now, max_age_days=3)

    assert len(offers) == 1
    assert offers[0].source_type == "aggregator"


def test_parse_benefit_html_keeps_activity_facts_and_page_date():
    html = """
    <html><head><meta property="article:published_time" content="2026-08-28T09:00:00+08:00"></head>
    <body><h1>ZCode 周末送 3 亿 Token</h1>
    <main><p>活动主体：ZCode 发放 GLM-5.3-Flash 3亿 Tokens。</p>
    <p>登录客户端后领取，8月31日09:00截止。</p><p>相关文章：其他内容</p></main></body></html>
    """

    items = parse_benefit_html(html, source_name="ChooseAI", vendor="ChooseAI", base_url="https://example.com/wool")

    assert len(items) == 1
    assert "3 亿 Token" in items[0].title
    assert "8月31日09:00截止" in items[0].raw_excerpt


def test_extract_wool_offers_rejects_generic_model_upgrade_notice():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "腾讯云 DeepSeek-V4-Flash 下线及升级通知",
            published_at="2026-08-28T09:00:00+08:00",
            source_name="Tencent Cloud AI",
            summary="现有模型将下线并升级，请迁移至新版本。",
        )
    ]

    assert extract_wool_offers(items, now=now, max_age_days=3) == []


def test_extract_wool_offers_filters_old_items_and_deduplicates_same_event():
    now = datetime(2026, 8, 29, 12, tzinfo=timezone(timedelta(hours=8)))
    items = [
        _update(
            "Codex 用户额度重置",
            published_at="2026-08-29T08:00:00+08:00",
            url="https://example.com/wool-a",
            summary="Codex 用户可获得免费额度重置，登录后领取。",
        ),
        _update(
            "Codex 用户额度重置通知",
            published_at="2026-08-28T08:00:00+08:00",
            url="https://example.com/wool-b",
            source_name="Sam Altman",
            summary="Codex 用户可获得免费额度重置，登录后领取。",
        ),
        _update(
            "旧的免费额度活动",
            published_at="2026-08-24T08:00:00+08:00",
            url="https://example.com/old",
            summary="免费额度活动仍可领取。",
        ),
    ]

    offers = extract_wool_offers(items, now=now, max_age_days=3)

    assert len(offers) == 1
    assert offers[0].provider in {"Codex", "Sam Altman"}


def test_ensure_wool_assets_renders_distinct_png_variants(tmp_path: Path):
    assets = ensure_wool_assets(tmp_path)

    assert set(assets) == {"with_wool", "without_wool"}
    assert assets["with_wool"].name == "有羊毛的羊.png"
    assert assets["without_wool"].name == "无羊毛的羊.png"
    assert all(path.exists() and path.suffix == ".png" for path in assets.values())
    with Image.open(assets["with_wool"]) as image:
        assert image.size == (1080, 1440)
    with Image.open(assets["without_wool"]) as image:
        assert image.size == (1080, 1440)
    assert assets["with_wool"].read_bytes() != assets["without_wool"].read_bytes()


def test_create_daily_wool_posts_creates_no_wool_draft_without_fabricating_offer(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.wool.workflow.collect_daily_wool_offers", lambda **_kwargs: ([], {"offers": 0}))
    monkeypatch.setattr("src.wool.workflow.load_llm_configs", lambda: [])

    posts = create_daily_wool_posts(now=datetime(2026, 8, 29, 12, tzinfo=timezone.utc))

    assert len(posts) == 1
    post = posts[0]
    assert post.platform["daily_wool"]["has_wool"] is False
    assert "暂无可核验福利" in post.title
    assert Path(post.assets[0].path).name == "无羊毛的羊.png"
    assert len(list(list_posts())) == 1


def test_deterministic_wool_copy_does_not_repeat_raw_aggregator_excerpt():
    offer = WoolOffer(
        title="ZCode 周末活动再送 3 亿 GLM-5.3-Flash Token，8月31日上午截止",
        provider="ZCode",
        benefit=(
            "ZCode：ZCode 周末活动再送 3 亿 GLM-5.3-Flash Token，8月31日上午截止。"
            "智谱AI旗下编程工具开展 Weekend Build 活动。"
        ),
        claim_steps="ZCode 周末活动再送 3 亿 GLM-5.3-Flash Token，8月31日上午截止。",
        source_name="ChooseAI",
        source_type="aggregator",
        url="https://www.chooseai.net/news/6285/",
        published_at="2026-08-28T00:00:00+08:00",
    )

    title, body = _deterministic_copy([offer], max_age_days=3)

    assert title == "每日羊毛|今日有AI福利"
    assert body.count("ZCode 周末活动再送 3 亿 GLM-5.3-Flash Token") == 1
    assert "领取说明：登录 ZCode 客户端" in body
    assert body.count(offer.url) == 1
