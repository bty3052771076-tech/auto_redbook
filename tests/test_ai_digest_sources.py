from __future__ import annotations

from src.ai_digest import fetchers
from src.ai_digest.fetchers import parse_github_releases_json, parse_rss_feed, parse_social_search_html
from src.ai_digest.sources import default_ai_digest_sources, resolve_ai_digest_sources


def test_default_sources_include_expandable_official_and_social_groups():
    sources = default_ai_digest_sources()

    names = {source.name for source in sources}
    assert {"openai", "anthropic", "deepmind", "huggingface", "github-ai"}.issubset(names)
    assert {"zhipu-glm", "minimax", "doubao", "baidu-qianfan"}.issubset(names)
    assert any(source.kind == "official" for source in sources)
    assert any(source.kind == "social" for source in sources)
    assert all(source.enabled for source in sources if source.kind == "official")


def test_domestic_ai_sources_use_official_release_pages():
    sources = {source.name: source for source in default_ai_digest_sources()}

    expected_domains = {
        "zhipu-glm": "bigmodel.cn",
        "minimax": "platform.minimax.io",
        "doubao": "volcengine.com",
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
