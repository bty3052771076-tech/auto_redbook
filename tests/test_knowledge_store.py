from __future__ import annotations

from pathlib import Path

from src.knowledge.models import KnowledgeDocument
from src.knowledge.store import KnowledgeStore


def test_postgres_store_is_idempotent_and_searchable(tmp_path: Path):
    store = KnowledgeStore.from_env(credentials_path=tmp_path / "missing.json")
    store._memory = True
    document = KnowledgeDocument(
        record_id="post-1",
        record_type="post",
        account_namespace="local",
        title="OpenAI 发布新模型",
        body="官方公告介绍了模型能力和开放时间。",
        source_url="https://example.test/openai",
        source_published_at="2026-09-20T08:00:00+08:00",
        allowed_purposes=("duplicate_reference", "style_example"),
    )

    first = store.upsert_document(document)
    second = store.upsert_document(document)

    assert first["status"] == "inserted"
    assert second["status"] == "unchanged"
    assert store.search("OpenAI 新模型", purpose="duplicate_reference")[0]["record_id"] == "post-1"


def test_store_rejects_secret_fields():
    store = KnowledgeStore.from_env()
    store._memory = True
    document = KnowledgeDocument(record_id="safe", record_type="post", title="safe", body="safe")
    result = store.upsert_document(document)
    assert "password" not in str(result).lower()
