from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.ai_digest import collect as collect_mod
from src.ai_digest.collect import collect_ai_digest_updates, fetch_ai_digest_source
from src.ai_digest import fetchers
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.fetchers import (
    parse_aihot_daily_html,
    parse_github_releases_json,
    parse_official_html,
    parse_rss_feed,
    parse_social_search_html,
    parse_x_profile_html,
)
from src.ai_digest.sources import AIDigestSource, default_ai_digest_sources, resolve_ai_digest_sources
from src.ai_digest.rank import ai_update_region


def test_curl_transport_enforces_connect_and_total_time_limits(monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    class Completed:
        returncode = 0
        stdout = b"<rss><channel /></rss>\n200"
        stderr = b""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(collect_mod.subprocess, "run", fake_run)

    text = collect_mod._curl_get_text("https://example.com/feed", timeout_s=7.0, executable="curl.exe")

    assert text == "<rss><channel /></rss>"
    assert "--connect-timeout" in calls[0][0]
    assert "--max-time" in calls[0][0]
    assert calls[0][1]["timeout"] > 7.0


def test_curl_transport_surfaces_http_status(monkeypatch):
    class Completed:
        returncode = 0
        stdout = b"not found\n404"
        stderr = b""

    monkeypatch.setattr(collect_mod.subprocess, "run", lambda *_args, **_kwargs: Completed())

    with pytest.raises(collect_mod.HTTPError) as exc_info:
        collect_mod._curl_get_text("https://example.com/missing", timeout_s=5.0, executable="curl.exe")

    assert exc_info.value.code == 404


def test_source_region_is_preserved_on_fetched_items(monkeypatch):
    source = AIDigestSource(
        "fixture-domestic",
        "official",
        "https://example.com/releases.xml",
        "Fixture Vendor",
        "rss",
        region="domestic",
    )
    monkeypatch.setattr(
        collect_mod,
        "_http_get_text",
        lambda *_args, **_kwargs: """
        <rss><channel><item>
          <title>Model service update</title>
          <link>https://example.com/releases/1</link>
          <pubDate>Fri, 31 Jul 2026 08:00:00 GMT</pubDate>
        </item></channel></rss>
        """,
    )

    items = fetch_ai_digest_source(source)

    assert items[0].tags[-1] == "region:domestic"
    assert ai_update_region(items[0]) == "domestic"


def test_default_sources_include_expandable_official_and_social_groups():
    sources = default_ai_digest_sources()

    names = {source.name for source in sources}
    assert {"openai", "anthropic", "deepmind", "huggingface", "github-ai"}.issubset(names)
    assert {
        "zhipu-glm",
        "zcode",
        "deepseek",
        "minimax",
        "doubao",
        "baidu-qianfan",
        "bytedance-seed",
    }.issubset(names)
    assert "aihot-daily" in names
    assert next(source for source in sources if source.name == "aihot-daily").kind == "aggregator"
    assert any(source.kind == "official" for source in sources)
    assert any(source.kind == "social" for source in sources)
    assert all(source.enabled for source in sources if source.kind == "official")
    assert {
        "x-openai",
        "x-openai-devs",
        "x-anthropic",
        "x-claude-devs",
        "x-sam-altman",
        "x-tibo-maker",
    }.issubset(names)
    assert all(
        source.kind == "social" and source.parser == "x_profile" and source.enabled
        for source in sources
        if source.name.startswith("x-")
    )


def test_default_sources_use_current_official_pages_when_legacy_rss_endpoints_are_retired():
    by_name = {source.name: source for source in default_ai_digest_sources()}

    assert by_name["anthropic"].url == "https://www.anthropic.com/news"
    assert by_name["anthropic"].parser == "html"
    assert by_name["metaai"].url == "https://ai.meta.com/blog"
    assert by_name["metaai"].parser == "html"
    assert by_name["microsoft"].url == "https://blogs.microsoft.com/"
    assert by_name["microsoft"].parser == "html"


def test_default_sources_expand_model_labs_and_keep_huggingface_as_final_aggregator():
    sources = default_ai_digest_sources()
    by_name = {source.name: source for source in sources}

    assert {
        "qwen-blog",
        "qwen-github",
        "tencent-hunyuan",
        "stepfun",
        "mistral",
        "xai",
        "cohere",
    }.issubset(by_name)
    assert by_name["qwen-blog"].kind == "official"
    assert by_name["qwen-github"].kind == "github"
    assert by_name["qwen-github"].parser == "github_releases"
    assert by_name["tencent-hunyuan"].kind == "official"
    assert by_name["stepfun"].kind == "official"
    assert by_name["mistral"].kind == "official"
    assert by_name["mistral"].parser == "rss"
    assert by_name["xai"].kind == "official"
    assert by_name["cohere"].kind == "official"
    assert by_name["huggingface"].kind == "aggregator"
    assert by_name["github-ai"].kind == "aggregator"


def test_default_sources_include_all_extended_domestic_and_global_model_feeds():
    sources = default_ai_digest_sources()
    by_name = {source.name: source for source in sources}

    expected = {
        "iflytek-spark": ("official", "html", "xinghuo.xfyun.cn"),
        "huawei-pangu": ("official", "html", "huaweicloud.com"),
        "sensetime-sensenova": ("official", "html", "sensetime.com"),
        "01ai-yi": ("official", "html", "01.ai"),
        "01ai-yi-github": ("github", "github_releases", "api.github.com/repos/01-ai/yi/releases"),
        "baichuan-github": ("github", "github_releases", "api.github.com/repos/baichuan-inc/Baichuan2/releases"),
        "internlm-github": ("github", "github_releases", "api.github.com/repos/InternLM/InternLM/releases"),
        "minicpm-github": ("github", "github_releases", "api.github.com/repos/OpenBMB/MiniCPM/releases"),
        "minicpm-v-github": ("github", "github_releases", "api.github.com/repos/OpenBMB/MiniCPM-V/releases"),
        "skywork": ("official", "html", "kunlun.com"),
        "kling": ("official", "html", "kuaishou.com"),
        "google-gemini": ("official", "html", "ai.google.dev"),
        "amazon-nova": ("official", "html", "aws.amazon.com/nova/models"),
        "ai21": ("official", "html", "docs.ai21.com/changelog"),
        "perplexity-sonar": ("official", "html", "docs.perplexity.ai/docs/sonar/models"),
        "stability-ai": ("official", "html", "stability.ai/news"),
        "black-forest-labs": ("official", "html", "bfl.ai/blog"),
        "runway": ("official", "html", "runwayml.com"),
        "luma-ai": ("official", "html", "lumalabs.ai/news"),
        "ideogram": ("official", "html", "ideogram.ai"),
        "recraft": ("official", "html", "recraft.ai/blog"),
    }

    assert expected.keys() <= by_name.keys()
    for name, (kind, parser, url_part) in expected.items():
        source = by_name[name]
        assert source.kind == kind
        assert source.parser == parser
        assert url_part in source.url
        assert source.enabled is True


def test_resolve_ai_digest_sources_places_aggregators_before_social_sources_by_default(monkeypatch):
    monkeypatch.delenv("AI_DIGEST_PRIMARY_SOURCES", raising=False)
    monkeypatch.delenv("AI_DIGEST_SOCIAL_SOURCES", raising=False)
    monkeypatch.delenv("AI_DIGEST_AGGREGATOR_SOURCES", raising=False)

    names = [source.name for source in resolve_ai_digest_sources()]

    assert "aihot-daily" in names
    assert names.index("huggingface") > names.index("aihot-daily")
    assert names.index("github-ai") > names.index("huggingface")
    assert names.index("github-ai") < names.index("x-openai")
    assert names[-1] == "x-tibo-maker"


def test_resolve_ai_digest_sources_places_aggregators_before_social_sources(monkeypatch):
    sources = resolve_ai_digest_sources(
        {
            "AI_DIGEST_SOCIAL_SOURCES": "x",
            "AI_DIGEST_AGGREGATOR_SOURCES": "aihot-daily,huggingface",
        }
    )
    names = [source.name for source in sources]

    assert names.index("aihot-daily") < names.index("x")
    assert names.index("huggingface") < names.index("x")


def test_domestic_ai_sources_use_official_release_pages():
    sources = {source.name: source for source in default_ai_digest_sources()}

    expected_domains = {
        "zhipu-glm": "bigmodel.cn",
        "zcode": "zcode.z.ai",
        "deepseek": "deepseek.com",
        "minimax": "platform.minimax.io",
        "doubao": "volcengine.com",
        "bytedance-seed": "seed.bytedance.com",
        "baidu-qianfan": "cloud.baidu.com",
    }

    for name, domain in expected_domains.items():
        source = sources[name]
        assert source.kind == "official"
        assert source.parser == "html"
        assert source.enabled is True
        assert domain in source.url


def test_resolve_ai_digest_sources_filters_by_env_names(monkeypatch):
    monkeypatch.setenv("AI_DIGEST_PRIMARY_SOURCES", "openai,huggingface")
    monkeypatch.setenv("AI_DIGEST_SOCIAL_SOURCES", "x")

    sources = resolve_ai_digest_sources()

    assert [source.name for source in sources] == ["openai", "huggingface", "x"]


def test_resolve_ai_digest_sources_includes_enabled_search_backfill_by_default(monkeypatch):
    monkeypatch.delenv("AI_DIGEST_PRIMARY_SOURCES", raising=False)
    monkeypatch.delenv("AI_DIGEST_SOCIAL_SOURCES", raising=False)

    names = [source.name for source in resolve_ai_digest_sources()]

    assert "aihot-daily" in names


def test_parse_aihot_daily_html_maps_traceable_digest_items():
    html = """
    <html><body>
      <p>美团 LongCat-2.0 正式发布：国产算力集群训练的万亿参数大模型</p>
      <p>公众号·官方 公众号：龙猫LongCat（美团）</p>
      <p>美团发布新一代万亿参数大模型LongCat-2.0并开源，原生支持1M超长上下文，在国产算力集群上完成训练与推理。</p>
      <p>7 日 GitHub 开源 Spec Kit 工具包 8 日 Harness-1 搜索智能体</p>
      <p>Hacker News 热门（buzzing.cc 中文翻译）</p>
      <p>这是归档导航区域，不应被当作一条正式 AI 资讯进入候选池。</p>
      <p>Claude Code v2.1.198 发布</p>
      <p>官方 Claude Code：GitHub Releases（RSS）</p>
      <p>Claude Code 更新浏览器、后台智能体和开发者工具能力，修复多项工作流问题并增强团队协作，适合开发者关注自动化编码流程变化。</p>
    </body></html>
    """

    items = parse_aihot_daily_html(
        html,
        source_name="AI HOT",
        vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-07-02",
        published_date="2026-07-02",
    )

    assert len(items) == 2
    assert items[0].vendor == "美团 LongCat"
    assert items[0].source_type == "aggregator"
    assert items[0].verification_status == "aggregator_only"
    assert items[0].published_at == "2026-07-02T08:00:00+08:00"
    assert items[0].url == "https://aihot.virxact.com/daily/2026-07-02?item=1"
    assert items[0].evidence_urls == []
    assert items[1].vendor == "Anthropic"
    assert all("7 日 GitHub" not in item.title for item in items)


def test_parse_aihot_daily_html_promotes_embedded_official_url_to_primary_link():
    html = """
    <html><body>
      <p>Claude 发现加密算法弱点，Anthropic 发布新研究</p>
      <p>X：Anthropic (@AnthropicAI)</p>
      <p>Anthropic 介绍 Claude 的密码学研究进展。了解更多：https://www.anthropic.com/research/cryptographic-weaknesses</p>
    </body></html>
    """

    items = parse_aihot_daily_html(
        html,
        source_name="AI HOT",
        vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-07-29",
        published_date="2026-07-29",
    )

    assert items[0].source_type == "aggregator"
    assert items[0].url == "https://www.anthropic.com/research/cryptographic-weaknesses"
    assert items[0].source_name == "Anthropic 原始页面（AI HOT 汇总）"
    assert items[0].evidence_urls == ["https://aihot.virxact.com/daily/2026-07-29?item=1"]


def test_parse_aihot_next_payload_keeps_each_title_summary_and_source_together():
    payload = """
    ["$","div",{"className":"m-daily-entry-title","children":"xAI 发布 Grok CLI 并支持 /tutorial 命令"}]
    ["$","p",{"className":"m-daily-entry-sum","children":"下载 Grok Build 并输入 /tutorial，可快速了解命令行工具。"}]
    ["$","div",{"className":"m-daily-entry-src","children":"X：Elon Musk (@elonmusk, xAI)"}]
    ["$","div",{"className":"m-daily-entry-title","children":"Suno 推出多项新功能，含 MIDI 导出"}]
    ["$","p",{"className":"m-daily-entry-sum","children":"网页端和移动端新增高级音轨分离、MIDI 导出、歌词合写与自动保存。"}]
    ["$","div",{"className":"m-daily-entry-src","children":"X：Suno (@suno)"}]
    {"isoDate":"2026-07-20","headline":"Qwen3.8 开源发布，2.4T 参数模型上线"}
    """
    html = f"<script>self.__next_f.push({json.dumps([1, payload], ensure_ascii=False)})</script>"

    items = parse_aihot_daily_html(
        html,
        source_name="AI HOT",
        vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-07-27",
        published_date="2026-07-27",
    )

    assert [item.title for item in items] == [
        "xAI 发布 Grok CLI 并支持 /tutorial 命令",
        "Suno 推出多项新功能，含 MIDI 导出",
    ]
    assert items[0].raw_excerpt.startswith("下载 Grok Build")
    assert items[0].source_name == "X：Elon Musk (@elonmusk, xAI)"
    assert items[1].raw_excerpt.startswith("网页端和移动端新增")
    assert items[1].source_name == "X：Suno (@suno)"
    assert all("Qwen3.8" not in item.title for item in items)


def test_parse_aihot_next_payload_keeps_detail_page_url_for_source_resolution():
    payload = """
    ["$","a",null,{"className":"m-daily-entry-title","href":"/items/minimax-h3","children":"MiniMax H3 发布"}]
    ["$","p",{"className":"m-daily-entry-sum","children":"MiniMax 发布多模态视频生成模型，支持文本、图像、视频和音频输入。"}]
    ["$","div",{"className":"m-daily-entry-src","children":"MiniMax：Blog（网页）"}]
    """
    html = f"<script>self.__next_f.push({json.dumps([1, payload], ensure_ascii=False)})</script>"

    items = parse_aihot_daily_html(
        html,
        source_name="AI HOT",
        vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-08-01",
        published_date="2026-08-01",
    )

    assert items[0].url == "https://aihot.virxact.com/items/minimax-h3"
    assert items[0].evidence_urls == []


def test_parse_aihot_daily_html_merges_rendered_detail_href_with_structured_entry():
    payload = """
    ["$","div",{"className":"m-daily-entry-title","children":"MiniMax H3 发布"}]
    ["$","p",{"className":"m-daily-entry-sum","children":"MiniMax 发布多模态视频生成模型，支持文本、图像、视频和音频输入。"}]
    ["$","div",{"className":"m-daily-entry-src","children":"MiniMax：Blog（网页）"}]
    """
    html = (
        '<a class="m-daily-entry-title" href="/items/minimax-h3">MiniMax H3 发布</a>'
        f"<script>self.__next_f.push({json.dumps([1, payload], ensure_ascii=False)})</script>"
    )

    items = parse_aihot_daily_html(
        html,
        source_name="AI HOT",
        vendor="AI HOT",
        base_url="https://aihot.virxact.com/daily/2026-08-01",
        published_date="2026-08-01",
    )

    assert items[0].url == "https://aihot.virxact.com/items/minimax-h3"


def test_parse_rss_feed_maps_items_to_ai_updates():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <title>OpenAI News</title>
      <item>
        <title>OpenAI 发布新模型</title>
        <link>https://openai.com/news/model</link>
        <pubDate>Tue, 30 Jun 2026 08:30:00 GMT</pubDate>
        <description>OpenAI announced a new model for developers.</description>
      </item>
    </channel></rss>
    """

    items = parse_rss_feed(xml, source_name="OpenAI", vendor="OpenAI")

    assert len(items) == 1
    assert items[0].title == "OpenAI 发布新模型"
    assert items[0].source_type == "official"
    assert items[0].url == "https://openai.com/news/model"
    assert items[0].vendor == "OpenAI"
    assert items[0].published_at.startswith("2026-06-30T08:30:00")


def test_fetch_aggregator_rss_preserves_aggregator_source_tier(monkeypatch):
    xml = """<?xml version="1.0"?>
    <rss><channel><item>
      <title>Hugging Face 模型工具更新</title>
      <link>https://huggingface.co/blog/model-update</link>
      <pubDate>Wed, 29 Jul 2026 08:30:00 GMT</pubDate>
      <description>Hugging Face 汇总模型与推理工具更新。</description>
    </item></channel></rss>
    """
    source = next(source for source in default_ai_digest_sources() if source.name == "huggingface")
    monkeypatch.setattr(collect_mod, "_http_get_text", lambda *_args, **_kwargs: xml)

    items = collect_mod.fetch_ai_digest_source(source)

    assert items[0].source_type == "aggregator"
    assert items[0].verification_status == "aggregator_only"


def test_resolve_aihot_detail_source_promotes_matching_vendor_official_url(monkeypatch):
    candidate = AIUpdateItem(
        title="MiniMax H3 发布",
        summary="MiniMax 发布全能多模态生成模型。",
        source_name="MiniMax：Blog（网页）",
        source_type="aggregator",
        url="https://aihot.virxact.com/items/minimax-h3",
        published_at="2026-08-01T08:00:00+08:00",
        vendor="MiniMax",
        verification_status="aggregator_only",
    )
    monkeypatch.setattr(
        collect_mod,
        "_http_get_text",
        lambda *_args, **_kwargs: (
            '<a href="https://www.minimax.io/blog/minimax-h3" '
            'class="dt-readtop" data-track="click_external">阅读原文</a>'
        ),
    )

    resolved = collect_mod.resolve_aihot_detail_source(candidate)

    assert resolved.source_type == "official"
    assert resolved.verification_status == "aggregator_confirmed"
    assert resolved.source_name == "MiniMax 官网"
    assert resolved.url == "https://www.minimax.io/blog/minimax-h3"
    assert resolved.evidence_urls == ["https://aihot.virxact.com/items/minimax-h3"]


def test_resolve_aihot_detail_source_promotes_vendor_blog_subdomain(monkeypatch):
    candidate = AIUpdateItem(
        title="Gemini Agent 评测服务正式可用",
        summary="Google Developers 发布 Agent 与模型评测服务更新。",
        source_name="Google：Blog（网页）",
        source_type="aggregator",
        url="https://aihot.virxact.com/items/gemini-agent-evals",
        published_at="2026-08-01T08:00:00+08:00",
        vendor="Google",
        verification_status="aggregator_only",
    )
    monkeypatch.setattr(
        collect_mod,
        "_http_get_text",
        lambda *_args, **_kwargs: (
            '<a href="https://developers.googleblog.com/agent-evaluations" '
            'class="dt-readtop" data-track="click_external">阅读原文</a>'
        ),
    )

    resolved = collect_mod.resolve_aihot_detail_source(candidate)

    assert resolved.source_type == "official"
    assert resolved.verification_status == "aggregator_confirmed"
    assert resolved.source_name == "Google 官网"


def test_collect_ai_digest_updates_uses_resolved_aihot_official_source(monkeypatch):
    candidate = AIUpdateItem(
        title="MiniMax H3 发布",
        summary="MiniMax 发布全能多模态生成模型。",
        source_name="MiniMax：Blog（网页）",
        source_type="aggregator",
        url="https://aihot.virxact.com/items/minimax-h3",
        published_at="2026-08-01T08:00:00+08:00",
        vendor="MiniMax",
        verification_status="aggregator_only",
    )
    source = AIDigestSource("aihot-daily", "aggregator", "https://aihot.virxact.com/daily", "AI HOT", "aihot_daily")
    monkeypatch.setenv("AI_DIGEST_SEARCH_BACKFILL", "0")
    monkeypatch.setattr(
        collect_mod,
        "_http_get_text",
        lambda *_args, **_kwargs: (
            '<a href="https://www.minimax.io/blog/minimax-h3" '
            'class="dt-readtop" data-track="click_external">阅读原文</a>'
        ),
    )

    ranked, meta = collect_ai_digest_updates(
        sources=[source],
        fetch_source=lambda _source: [candidate],
        target_count=1,
        min_official_count=1,
        max_age_days=3,
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
        persist_source_health=False,
    )

    assert ranked[0].source_type == "official"
    assert ranked[0].url == "https://www.minimax.io/blog/minimax-h3"
    assert meta["detail_source_resolution"] == {"considered": 1, "resolved": 1, "official": 1, "social": 0}


def test_parse_github_releases_json_maps_release_entries():
    payload = """
    [
      {
        "name": "Transformers v5.0",
        "html_url": "https://github.com/huggingface/transformers/releases/tag/v5",
        "published_at": "2026-06-30T01:02:03Z",
        "body": "Major release with new model support."
      }
    ]
    """

    items = parse_github_releases_json(payload, source_name="Hugging Face GitHub", vendor="Hugging Face")

    assert len(items) == 1
    assert items[0].source_type == "github"
    assert items[0].title == "Transformers v5.0"
    assert items[0].product == "GitHub Release"


def test_parse_social_search_html_maps_public_links_as_social_candidates():
    html = """
    <html><body>
      <a href="https://x.com/OpenAI/status/123">OpenAI：今天发布了开发者工具更新</a>
      <a href="https://example.com/other">ignored</a>
    </body></html>
    """

    items = parse_social_search_html(html, source_name="X Search", vendor="OpenAI")

    assert len(items) == 1
    assert items[0].source_type == "social"
    assert items[0].verification_status == "social_only"
    assert items[0].url == "https://x.com/OpenAI/status/123"


def test_parse_x_profile_html_maps_public_tweets_with_real_publish_times():
    payload = {
        "props": {
            "pageProps": {
                "timeline": {
                    "entries": [
                        {
                            "type": "tweet",
                            "content": {
                                "tweet": {
                                    "created_at": "Wed Jul 29 00:35:31 +0000 2026",
                                    "full_text": "We released the open-source Codex Security CLI for repository scanning.",
                                    "permalink": "/OpenAI/status/2082263717916586117",
                                    "user": {"name": "OpenAI", "screen_name": "OpenAI"},
                                }
                            },
                        }
                    ]
                }
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    items = parse_x_profile_html(html, source_name="OpenAI X", vendor="OpenAI")

    assert len(items) == 1
    assert items[0].source_type == "social"
    assert items[0].verification_status == "social_only"
    assert items[0].published_at == "2026-07-29T00:35:31Z"
    assert items[0].url == "https://x.com/OpenAI/status/2082263717916586117"
    assert items[0].source_name == "X：OpenAI (@OpenAI)"


def test_parse_official_html_extracts_release_lines_as_official_candidates():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html>
      <head><title>模型更新记录 - 百度千帆</title></head>
      <body>
        <h1>模型更新记录</h1>
        <p>9月26日 百度 ERNIE X1.1 推理服务 API V2 版本上新，事实性和工具调用能力提升。</p>
        <a href="/doc/qianfan/s/api">API调用文档</a>
        <script>ignore me</script>
      </body>
    </html>
    """

    items = parse_official_html(
        html,
        source_name="百度千帆",
        vendor="百度千帆",
        base_url="https://cloud.baidu.com/doc/qianfan/s/Kmh4stnjp",
    )

    assert items
    assert items[0].source_type == "official"
    assert items[0].source_name == "百度千帆"
    assert "ERNIE X1.1" in " ".join(item.title for item in items)


def test_parse_official_html_ignores_navigation_when_an_official_article_body_exists():
    html = """
    <html><body>
      <nav><p>2026年7月28日 Qwen Code 产品升级公告</p></nav>
      <div class="post__body">
        <h2>2026年7月9日</h2>
        <p>Kimi-K2.5 推理服务 API V2 版本下线，推荐替换模型请查看升级机制。</p>
      </div>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="百度千帆",
        vendor="百度千帆",
        base_url="https://cloud.baidu.com/doc/qianfan/s/Kmh4stnjp",
    )

    assert [item.title for item in items] == [
        "Kimi-K2.5 推理服务 API V2 版本下线，推荐替换模型请查看升级机制。"
    ]
    assert items[0].published_at == "2026-07-09"


def test_parse_official_html_extracts_publish_date_from_release_line():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <p>2026年7月2日 GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="智谱 GLM",
        vendor="智谱 GLM",
        base_url="https://docs.bigmodel.cn/cn/update/new-releases",
    )

    assert items
    assert items[0].published_at == "2026-07-02"


def test_parse_official_html_extracts_english_publish_date_from_nearby_line():
    html = """
    <html><body>
      <p>Jul 10, 2026</p>
      <p>Anthropic announces a Claude model update for developers and agent workflows.</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="Anthropic",
        vendor="Anthropic",
        base_url="https://www.anthropic.com/news",
    )

    assert items
    assert items[0].published_at == "2026-07-10"


def test_parse_official_html_applies_nearby_publish_date_heading_to_release_line():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <h2>2026年7月2日</h2>
      <p>GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="智谱 GLM",
        vendor="智谱 GLM",
        base_url="https://docs.bigmodel.cn/cn/update/new-releases",
    )

    assert items
    assert items[0].published_at == "2026-07-02"


def test_parse_official_html_uses_page_date_label_for_release_title():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <h1>Seed2.1 Officially Released: Advancing AI Productivity</h1>
      <p>Date</p>
      <p>2026-06-23</p>
      <p>Doubao and Volcano Engine users can now start to access Doubao Seed 2.1.</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="ByteDance Seed",
        vendor="ByteDance Seed",
        base_url="https://seed.bytedance.com/en/blog/seed2-1-officially-released-advancing-ai-productivity",
    )

    assert items
    assert items[0].published_at == "2026-06-23"


def test_parse_official_html_uses_published_at_millis_for_release_title():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <h1>ZCode 3.0 深度适配 GLM-5.2，多 Agent 协作更进一步</h1>
      <script>{"published_at":1783091813682}</script>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="智谱 ZCode",
        vendor="智谱 ZCode",
        base_url="https://zcode.z.ai/cn",
    )

    assert items
    assert items[0].published_at == "2026-07-03"


def test_parse_official_html_does_not_use_page_now_for_release_banner_when_no_other_date():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <a>🎉 DeepSeek-V4 预览版本发布，具备世界顶级推理性能，Agent 能力大幅提高。</a>
      <script>{"now":"$D2026-06-26T06:13:58.756Z"}</script>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="DeepSeek",
        vendor="DeepSeek",
        base_url="https://www.deepseek.com/",
    )

    assert items
    assert items[0].published_at == ""


def test_parse_official_html_keeps_deepseek_article_publish_date_not_runtime_now():
    html = """
    <html><body>
      <nav>DeepSeek-V4 预览版发布 2026/04/24</nav>
      <h1>DeepSeek-V4 预览版：迈入百万上下文普惠时代</h1>
      <p>今天，我们全新系列模型 DeepSeek-V4 的预览版本正式上线并同步开源。</p>
      <script>{"now":"$D2026-07-08T06:13:58.756Z"}</script>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="DeepSeek",
        vendor="DeepSeek",
        base_url="https://api-docs.deepseek.com/zh-cn/news/news260424",
    )

    assert items
    assert {item.published_at for item in items} == {"2026-04-24"}


def test_parse_official_html_filters_common_doc_navigation_noise():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <p>Use this file to discover all available pages before exploring further.</p>
      <p>文档指南 订阅 [Agent/Coding Plan] API参考 资源</p>
      <p>智谱AI开放文档 home page</p>
      <p>Models - MiniMax API Docs</p>
      <p>Moonshot AI Blogs</p>
      <p>Kimi K2 Thinking 模型发布并开源，全面提升 Agent 和推理能力。</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="月之暗面 Kimi",
        vendor="月之暗面 Kimi",
        base_url="https://platform.moonshot.cn/blog/tags/announcement",
    )

    titles = [item.title for item in items]
    assert titles == ["Kimi K2 Thinking 模型发布并开源，全面提升 Agent 和推理能力。"]


def test_parse_official_html_filters_model_doc_and_billing_noise():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <p>用户指南（模型）</p>
      <p>模型服务计费说明</p>
      <p>模型默认参数说明</p>
      <p>MiniMax M3 模型发布，强化长文本推理和多工具调用能力。</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="MiniMax",
        vendor="MiniMax",
        base_url="https://platform.minimax.io/docs/release-notes/models",
    )

    titles = [item.title for item in items]
    assert titles == ["MiniMax M3 模型发布，强化长文本推理和多工具调用能力。"]


def test_parse_official_html_filters_generic_update_directory_noise():
    parse_official_html = getattr(fetchers, "parse_official_html", None)
    assert parse_official_html is not None
    html = """
    <html><body>
      <p>模型上下架与更新</p>
      <p>豆包模型服务协议</p>
      <p>推理服务监控告警</p>
      <p>GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="智谱 GLM",
        vendor="智谱 GLM",
        base_url="https://docs.bigmodel.cn/cn/update/new-releases",
    )

    titles = [item.title for item in items]
    assert titles == ["GLM-5.2 模型发布，强化多模态理解、代码生成和复杂推理能力。"]


def test_parse_official_html_filters_marketing_and_release_note_page_titles():
    html = """
    <html><body>
      <h1>Frontier AI LLMs, assistants, agents, services | Mistral AI</h1>
      <h1>模型能力总览 - StepFun 开放平台文档中心</h1>
      <a>Release Notes</a>
      <p>Products Solutions Research Developers Blog Customers Company</p>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="Mistral AI",
        vendor="Mistral AI",
        base_url="https://mistral.ai/news/",
    )

    assert items == []


def test_parse_official_html_filters_legal_footer_and_keeps_model_release():
    html = """
    <html><body>
      <p>Developer Terms of Service FLUX API Service Terms Self-Hosted Terms of Service
      Non-Commercial License Terms Responsible AI Development Policy Training Data Disclosure</p>
      <p>Select a category All Customer stories Models News Products Research</p>
      <a href="/blog/flux-3">FLUX 3 multimodal frontier model released in Early Access July 23, 2026</a>
    </body></html>
    """

    items = parse_official_html(
        html,
        source_name="Black Forest Labs",
        vendor="Black Forest Labs",
        base_url="https://bfl.ai/blog",
    )

    assert len(items) == 1
    assert "FLUX 3" in items[0].title
    assert "Terms of Service" not in items[0].title
    assert items[0].published_at == "2026-07-23"
