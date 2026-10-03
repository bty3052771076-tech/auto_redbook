from __future__ import annotations

from pathlib import Path

from src.agent.editorial_agent import AgentJob, EditorialAgentConfig, EditorialAgentTools, run_editorial_agent
from src.knowledge.ingest import _purposes
from src.knowledge.service import knowledge_context, prepare_local_knowledge_snapshot


class _UnavailableStore:
    def status(self):
        return {"status": "degraded", "error": "connection refused"}

    def ensure_schema(self):
        raise RuntimeError("connection refused")


def test_knowledge_context_blocks_without_database():
    result = knowledge_context(job_kind="daily_news", query="today", store_factory=_UnavailableStore)

    assert result["knowledge_status"] == "blocked"
    assert result["error_code"] == "KNOWLEDGE_DB_UNAVAILABLE"
    assert "回退" not in result.get("knowledge_warning", "")


def test_snapshot_reports_blocked_instead_of_degraded_fallback(tmp_path: Path):
    result = prepare_local_knowledge_snapshot(data_root=tmp_path, store=_UnavailableStore())

    assert result["knowledge_status"] == "blocked"
    assert result["error_code"] == "KNOWLEDGE_DB_UNAVAILABLE"


def test_generated_post_is_never_promoted_to_factual_evidence():
    class _Post:
        id = "generated-1"
        title = "Generated title"
        body = "Generated summary"
        status = "saved_as_draft"
        platform = {"publish": {"visibility": "public"}}

    assert "evidence" not in _purposes(_Post())


def test_agent_stops_before_generation_when_knowledge_is_blocked(tmp_path: Path):
    generated = []
    uploaded = []
    tools = EditorialAgentTools(
        sync_context=lambda _job: {
            "knowledge_status": "blocked",
            "error_code": "KNOWLEDGE_DB_UNAVAILABLE",
            "knowledge_warning": "PostgreSQL unavailable",
        },
        generate=lambda *_args: generated.append(True) or [],
        review=lambda *_args: [],
        upload=lambda *_args: uploaded.append(True) or (True, "unexpected"),
        upload_enabled=True,
    )

    result = run_editorial_agent(
        [AgentJob(kind="daily_news", title="daily news")],
        tools=tools,
        config=EditorialAgentConfig(checkpoint_dir=tmp_path / "checkpoint"),
    )

    assert result.status == "blocked"
    assert not generated
    assert not uploaded
