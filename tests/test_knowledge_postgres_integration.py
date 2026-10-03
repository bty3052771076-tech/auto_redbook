from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.knowledge.models import KnowledgeDocument
from src.knowledge.store import KnowledgeStore


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires the configured E: PostgreSQL instance",
)


def test_real_postgres_parameterized_roundtrip_and_vector_storage():
    store = KnowledgeStore.from_env()
    store.ensure_schema()
    namespace = f"integration-{uuid4().hex}"
    record_id = "quote-'-中文"
    document = KnowledgeDocument(
        record_id=record_id,
        record_type="source",
        account_namespace=namespace,
        title="Qwen 发布新模型",
        body="Open weights were published today.",
        source_url="https://example.test/?q='quoted'",
        allowed_purposes=("duplicate_reference", "evidence"),
    )
    try:
        assert store.upsert_document(document)["status"] == "inserted"
        loaded = store.get(record_id, account_namespace=namespace)
        assert loaded["title"] == document.title
        assert loaded["source_url"] == document.source_url
        assert set(loaded["allowed_purposes"]) == set(document.allowed_purposes)
        assert store.upsert_document(document)["status"] == "unchanged"

        changed = KnowledgeDocument(
            record_id=record_id,
            record_type="source",
            account_namespace=namespace,
            title=document.title,
            body=document.body + " A specific new version is available.",
            source_url=document.source_url,
            allowed_purposes=document.allowed_purposes,
        )
        assert store.upsert_document(changed)["status"] == "updated"
        with store.connection() as conn:
            row = conn.execute("SELECT count(*) AS n FROM knowledge.document_versions v JOIN knowledge.documents d ON d.id=v.document_id WHERE d.account_namespace=%s AND d.record_id=%s", (namespace, record_id)).fetchone()
            assert row["n"] == 1

        store.upsert_chunks(record_id, [{
            "chunk_id": uuid4().hex,
            "chunk_index": 0,
            "content": changed.title + " " + changed.body,
            "char_start": 0,
            "char_end": len(changed.title + " " + changed.body),
            "token_count": 9,
            "embedding": [0.01] * 384,
            "batch_id": uuid4().hex,
        }], account_namespace=namespace)
        with store.connection() as conn:
            row = conn.execute("SELECT vector_dims(embedding) AS dimensions FROM knowledge.chunks c JOIN knowledge.documents d ON d.id=c.document_id WHERE d.account_namespace=%s AND d.record_id=%s", (namespace, record_id)).fetchone()
            assert row["dimensions"] == 384
    finally:
        with store.connection("migration") as conn, conn.transaction():
            conn.execute("DELETE FROM knowledge.documents WHERE account_namespace=%s", (namespace,))
