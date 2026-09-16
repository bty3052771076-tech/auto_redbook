from src.ai_digest.sources import default_ai_digest_sources, resolve_ai_digest_sources


def test_default_sources_include_rsshub_media_and_paper_routes():
    """RSSHub-backed routes add reliable CN media + paper sources."""
    by_name = {source.name: source for source in default_ai_digest_sources()}

    assert "rsshub-jiqizhixin" in by_name
    assert "rsshub-qbitai" in by_name
    assert "rsshub-hf-daily-papers" in by_name
    assert "rsshub-github-trending" in by_name
    assert "arxiv-cs-ai" in by_name

    for name in ("rsshub-jiqizhixin", "rsshub-qbitai", "rsshub-hf-daily-papers", "rsshub-github-trending"):
        source = by_name[name]
        assert source.kind == "aggregator"
        assert source.parser == "rss"
        assert source.url.startswith("rsshub://")

    arxiv = by_name["arxiv-cs-ai"]
    assert arxiv.parser == "rss"
    assert arxiv.url.startswith("https://export.arxiv.org/rss/")


def test_resolve_ai_digest_sources_expands_rsshub_scheme(monkeypatch):
    """rsshub:// URLs are rewritten to the configured base at resolve time."""
    monkeypatch.setenv("AI_DIGEST_RSSHUB_BASE_URL", "https://rsshub.example.com")
    resolved = resolve_ai_digest_sources()
    by_name = {source.name: source for source in resolved}

    assert by_name["rsshub-jiqizhixin"].url == "https://rsshub.example.com/zhihu/zhuanlan/jiqizhixin"
    assert by_name["rsshub-hf-daily-papers"].url == "https://rsshub.example.com/huggingface/daily-papers"


def test_resolve_ai_digest_sources_keeps_rsshub_sources_when_base_missing(monkeypatch):
    """Without a base URL the rsshub sources stay in the list but stay disabled."""
    monkeypatch.delenv("AI_DIGEST_RSSHUB_BASE_URL", raising=False)
    monkeypatch.delenv("AI_DIGEST_AGGREGATOR_SOURCES", raising=False)
    monkeypatch.setenv("AI_DIGEST_AGGREGATOR_SOURCES", "rsshub-jiqizhixin,rsshub-qbitai,rsshub-hf-daily-papers,rsshub-github-trending,aihot-daily")
    resolved = resolve_ai_digest_sources()
    rsshub = [source for source in resolved if source.url.startswith("rsshub://")]

    assert rsshub
    assert all(source.enabled is False for source in rsshub)
