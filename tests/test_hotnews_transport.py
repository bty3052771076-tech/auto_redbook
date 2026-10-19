import urllib.request

import httpx
import pytest

from src.news.daily_news import _hotnews_request_json


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"status":200,"data":[{"title":"AI update"}]}', None),
    (503, '{}', "HotNews HTTP error 503"),
    (200, 'not-json', "not valid JSON"),
])
def test_hotnews_avoids_blocking_windows_proxy_bypass(monkeypatch, status, body, expected):
    original = httpx.Client
    settings = []

    def blocked(*args, **kwargs):
        raise AssertionError("Windows urllib proxy-bypass DNS must not run")

    def handler(request):
        assert request.url.params["platform"] == "ithome"
        return httpx.Response(status, text=body)

    def client(**kwargs):
        settings.append(kwargs)
        return original(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(httpx, "Client", client)
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            _hotnews_request_json(base_url="https://news.example/api", platform="ithome", timeout_s=3)
    else:
        result = _hotnews_request_json(base_url="https://news.example/api", platform="ithome", timeout_s=3)
        assert result["data"] == [{"title": "AI update"}]
    assert settings[0]["trust_env"] is True
    assert settings[0]["verify"] is True
    assert settings[0]["timeout"] == 3


@pytest.mark.parametrize("status,oversized", [(200, False), (302, False), (200, True)])
def test_unified_rss_avoids_proxy_dns_and_keeps_feed_guards(monkeypatch, status, oversized):
    from src.sources import service as module
    from src.sources.models import SourceSpec
    from src.sources.registry import SourceRegistry

    spec = SourceSpec.from_mapping({
        "source_id": "official-rss", "adapter": "rss", "publisher_id": "publisher",
        "publisher_family": "publisher", "source_url": "https://publisher.test/rss",
    })
    rss = b'<rss><channel><item><title>Model update</title><link>https://publisher.test/a</link><pubDate>Mon, 19 Oct 2026 02:00:00 GMT</pubDate></item></channel></rss>'
    original = httpx.Client
    settings = []

    def blocked(*args, **kwargs):
        raise AssertionError("Windows urllib proxy-bypass DNS must not run")

    def handler(request):
        assert str(request.url) == "https://publisher.test/rss"
        return httpx.Response(status, content=b"x" * 1025 if oversized else rss,
                              headers={"Location": "http://127.0.0.1/private"} if status == 302 else {})

    def client(**kwargs):
        settings.append(kwargs)
        return original(**{**kwargs, "transport": httpx.MockTransport(handler)})

    monkeypatch.setattr(module, "build_opener", blocked)
    monkeypatch.setattr(module, "_MAX_FEED_BYTES", 1024)
    monkeypatch.setattr(httpx, "Client", client)
    service = module.UnifiedNewsSourceService(SourceRegistry([spec]))
    if status == 302:
        with pytest.raises(httpx.HTTPStatusError):
            service._fetch_rss(spec, 3)
    elif oversized:
        with pytest.raises(ValueError, match="feed exceeds maximum size"):
            service._fetch_rss(spec, 3)
    else:
        items, _ = service._fetch_rss(spec, 3)
        assert items[0].title == "Model update"
        assert items[0].publisher_id == "publisher"
        assert items[0].published_at == "2026-10-19T02:00:00+00:00"
    assert settings[0]["trust_env"] is True
    assert settings[0]["follow_redirects"] is False
    assert settings[0]["verify"].check_hostname is True
