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
from copy import deepcopy

import pytest


class InMemoryConversationStore:
    """Explicit test double; production Workbench always defaults to PostgreSQL."""

    def __init__(self):
        self.rows = {}

    def get(self, conversation_id):
        if conversation_id not in self.rows:
            raise KeyError(conversation_id)
        return deepcopy(self.rows[conversation_id])

    def save(self, conversation):
        value = deepcopy(conversation)
        expected = int(value.pop("_revision", 0))
        current = self.rows.get(value["id"])
        if current and int(current.get("_revision", 0)) != expected:
            from src.agent.conversation_store import ConversationConflict
            raise ConversationConflict("conversation changed in another process; reload before saving")
        if not current and expected:
            from src.agent.conversation_store import ConversationConflict
            raise ConversationConflict("conversation does not exist")
        value["_revision"] = expected + 1
        value.setdefault("_last_message_seq", len(value.get("messages", [])))
        self.rows[value["id"]] = deepcopy(value)
        return deepcopy(value)

    def import_legacy(self, conversation):
        if conversation["id"] in self.rows:
            return self.get(conversation["id"])
        return self.save(conversation)

    def list(self, *, limit=100):
        return [
            {"id": value["id"], "title": value.get("title", "新对话"),
             "created_at": value.get("created_at"), "updated_at": value.get("updated_at"),
             "status": value.get("status", "idle"), "message_count": len(value.get("messages", [])),
             "latest_plan_id": (value.get("plans") or [{}])[-1].get("id", ""),
             "_revision": value.get("_revision", 0)}
            for value in sorted(self.rows.values(), key=lambda item: item.get("updated_at", 0), reverse=True)[:limit]
        ]


@pytest.fixture
def workbench_factory():
    from apps.web_service import Workbench

    stores = {}

    def create(root):
        key = str(root.resolve())
        store = stores.setdefault(key, InMemoryConversationStore())
        return Workbench(root, conversation_store=store)

    return create
