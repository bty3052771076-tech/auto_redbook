from __future__ import annotations

from src.knowledge.service import knowledge_context


def test_knowledge_context_blocks_without_database(tmp_path):
    result = knowledge_context(job_kind="daily_news", store_factory=lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    assert result["knowledge_status"] == "blocked"
    assert result["error_code"] == "KNOWLEDGE_DB_UNAVAILABLE"
    assert result["knowledge_warning"]
    assert result["job_kind"] == "daily_news"
