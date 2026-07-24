import os
import sys
from pathlib import Path

import pytest

# ensure project root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_local_news_credentials(monkeypatch):
    """Keep tests deterministic and prevent use of a developer's local API keys."""
    prefixes = (
        "NEWS_",
        "GNEWS_",
        "JUHE_",
        "NEWSDATA_",
        "ALPHAVANTAGE_",
        "ALPHA_VANTAGE_",
        "THENEWSAPI_",
        "THENEWS_API_",
        "FINNHUB_",
        "GOOGLE_NEWS_",
        "HOTNEWS_",
    )
    for name in tuple(os.environ):
        if name.startswith(prefixes):
            monkeypatch.delenv(name, raising=False)
    # Do not fall back to the ignored local docs/news_sources_api-key.md file.
    monkeypatch.setenv("NEWS_SOURCES_CONFIG_FILE", "__pytest_missing_news_sources_config__.env")

    # Legacy provider loaders use fixed local docs paths.  Preserve explicitly
    # supplied temporary key files, but never read a developer's ignored keys.
    from src.news import daily_news

    original_parse = daily_news._parse_kv_file
    secret_filenames = {
        "news_api-key.md",
        "gnews_api-key.md",
        "juhe_api-key.md",
        "news_sources_api-key.md",
    }

    def _parse_test_key_file(path):
        candidate = Path(path)
        if candidate.name in secret_filenames and candidate.parent == Path("docs"):
            return {}
        return original_parse(candidate)

    monkeypatch.setattr(daily_news, "_parse_kv_file", _parse_test_key_file)
