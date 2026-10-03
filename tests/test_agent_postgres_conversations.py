from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.agent.conversation_store import ConversationConflict, PostgresConversationStore
from src.knowledge.store import KnowledgeStore


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires the configured E: PostgreSQL instance",
)


def test_postgres_conversation_roundtrip_append_and_compare_and_swap():
    store = PostgresConversationStore(KnowledgeStore.from_env())
    store.knowledge_store.ensure_schema()
    conversation_id = uuid4().hex
    message_id = uuid4().hex
    try:
        created = store.save({
            "id": conversation_id,
            "title": "PostgreSQL 会话持久化测试",
            "created_at": 1_790_000_000.0,
            "updated_at": 1_790_000_001.0,
            "status": "planned",
            "messages": [{"id": message_id, "role": "user", "content": "生成中文内容", "created_at": 1_790_000_001.0}],
            "plans": [{"id": "plan-1", "version": 1}],
            "runs": [],
        })
        assert created["_revision"] == 1
        assert created["messages"][0]["content"] == "生成中文内容"
        assert store.list()[0]["id"] == conversation_id

        first = store.get(conversation_id)
        stale = store.get(conversation_id)
        first["status"] = "running"
        first["messages"].append({"id": uuid4().hex, "role": "assistant", "content": "已开始", "created_at": 1_790_000_002.0})
        updated = store.save(first)
        assert updated["_revision"] == 2
        assert len(updated["messages"]) == 2
        stale["status"] = "failed"
        with pytest.raises(ConversationConflict, match="another process"):
            store.save(stale)

        loaded = store.get(conversation_id)
        assert loaded["status"] == "running"
        assert [message["id"] for message in loaded["messages"]][0] == message_id
        with store.knowledge_store.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM agent.messages WHERE conversation_id=%s",
                (conversation_id,),
            ).fetchone()
            assert row["n"] == 2
    finally:
        with store.knowledge_store.connection("migration") as conn, conn.transaction():
            conn.execute("DELETE FROM agent.conversations WHERE conversation_id=%s", (conversation_id,))


def test_legacy_conversation_import_is_idempotent():
    store = PostgresConversationStore(KnowledgeStore.from_env())
    conversation_id = uuid4().hex
    legacy = {
        "id": conversation_id,
        "title": "旧 JSON 会话",
        "created_at": 1_790_000_000.0,
        "updated_at": 1_790_000_001.0,
        "status": "idle",
        "messages": [{"id": uuid4().hex, "role": "user", "content": "保留原文", "created_at": 1_790_000_001.0}],
        "plans": [],
        "runs": [],
    }
    try:
        first = store.import_legacy(legacy)
        second = store.import_legacy(legacy)
        assert first["messages"] == second["messages"]
        assert len(second["messages"]) == 1
    finally:
        with store.knowledge_store.connection("migration") as conn, conn.transaction():
            conn.execute("DELETE FROM agent.conversations WHERE conversation_id=%s", (conversation_id,))


def test_postgres_compaction_snapshot_is_versioned_and_keeps_original_messages():
    store = PostgresConversationStore(KnowledgeStore.from_env())
    conversation_id = uuid4().hex
    try:
        current = store.save({
            "id": conversation_id, "title": "压缩快照测试", "created_at": 1_790_000_000.0,
            "updated_at": 1_790_000_001.0, "status": "idle", "messages": [
                {"id": uuid4().hex, "role": "user", "content": "保留原始约束", "created_at": 1_790_000_001.0},
            ], "plans": [], "runs": [],
        })
        snapshot = store.save_snapshot(conversation_id, expected_revision=current["_revision"], snapshot={
            "through_seq": 1, "summary": "用户要求保留原始约束。", "constraints": ["保留原文"],
            "evidence_refs": ["evidence-1"], "task_state": {"status": "running"},
            "input_tokens": 400, "output_tokens": 40,
        })
        assert snapshot["version"] == 1
        assert store.active_snapshot(conversation_id)["summary"] == "用户要求保留原始约束。"
        assert len(store.context_messages(conversation_id)) == 1
        with store.knowledge_store.connection() as conn:
            active = conn.execute("SELECT active_snapshot_version FROM agent.conversations WHERE conversation_id=%s", (conversation_id,)).fetchone()
            assert active["active_snapshot_version"] == 1
    finally:
        with store.knowledge_store.connection("migration") as conn, conn.transaction():
            conn.execute("DELETE FROM agent.conversations WHERE conversation_id=%s", (conversation_id,))
