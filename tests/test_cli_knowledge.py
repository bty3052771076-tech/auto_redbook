from __future__ import annotations

from typer.testing import CliRunner

from apps import cli


def test_knowledge_index_requires_ready_postgres_before_running_indexer(monkeypatch):
    class Store:
        def status(self):
            return {"status": "degraded", "documents": 0, "error": "connection refused"}

    monkeypatch.setattr(cli.KnowledgeStore, "from_env", lambda: Store())
    monkeypatch.setattr(
        cli,
        "prepare_local_knowledge_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not index without PostgreSQL")),
    )

    result = CliRunner().invoke(cli.app, ["knowledge-index"])

    assert result.exit_code == 2
    assert "connection refused" in result.output


def test_knowledge_index_reports_completed_indexing(monkeypatch):
    class Store:
        def status(self):
            return {"status": "ready", "documents": 3, "indexed_documents": 3, "index_ready": True}

    monkeypatch.setattr(cli.KnowledgeStore, "from_env", lambda: Store())
    monkeypatch.setattr(
        cli,
        "prepare_local_knowledge_snapshot",
        lambda **kwargs: {
            "knowledge_status": "ready",
            "snapshot_id": "snapshot-1",
            "input_count": 3,
            "documents": 3,
            "indexed_documents": 3,
            "indexed_chunks": 3,
            "index_progress": {"documents": 3, "indexed_documents": 3, "pending_documents": 0},
        },
    )
    result = CliRunner().invoke(cli.app, ["knowledge-index"])

    assert result.exit_code == 0
    assert '"knowledge_status": "ready"' in result.output
    assert '"pending_documents": 0' in result.output
