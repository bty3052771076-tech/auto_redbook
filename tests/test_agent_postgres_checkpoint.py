from __future__ import annotations

import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from src.agent.postgres_checkpoint import postgres_checkpointer, setup_postgres_checkpointer
from src.agent.editorial_agent import AgentJob, EditorialAgentConfig, EditorialAgentTools, run_editorial_agent
from src.knowledge.store import KnowledgeStore


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
    reason="requires the configured E: PostgreSQL instance",
)


class State(TypedDict):
    value: str


def test_official_langgraph_checkpointer_persists_state_between_connections():
    store = KnowledgeStore.from_env()
    setup_postgres_checkpointer(store)
    thread_id = "test-" + uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    builder = StateGraph(State)
    builder.add_node("write", lambda _state: {"value": "PostgreSQL 持久状态"})
    builder.add_edge(START, "write")
    builder.add_edge("write", END)
    try:
        with postgres_checkpointer(store) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"value": "initial"}, config)
            assert result["value"] == "PostgreSQL 持久状态"
        with postgres_checkpointer(store) as saver:
            snapshot = saver.get(config)
            assert snapshot is not None
            assert snapshot["channel_values"]["value"] == "PostgreSQL 持久状态"
            saver.delete_thread(thread_id)
    finally:
        with store.connection("migration") as conn, conn.transaction():
            conn.execute("DELETE FROM checkpoints WHERE thread_id=%s", (thread_id,))
            conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id=%s", (thread_id,))
            conn.execute("DELETE FROM checkpoint_writes WHERE thread_id=%s", (thread_id,))


def test_editorial_agent_resume_uses_postgres_state_not_json_replay(tmp_path):
    store = KnowledgeStore.from_env()
    setup_postgres_checkpointer(store)
    run_id = "resume-" + uuid4().hex
    calls = {"sync": 0, "generate": 0, "review": 0}

    def sync_context(_job):
        calls["sync"] += 1
        return {"synced": True}

    def generate(_job, _context):
        calls["generate"] += 1
        return [{"id": "pg-resume-post", "title": "integration", "content": "complete"}]

    def review(_job, _posts, _context):
        calls["review"] += 1
        return []

    tools = EditorialAgentTools(
        sync_context=sync_context,
        generate=generate,
        review=review,
        upload=lambda *_args: (True, "unused"),
        upload_enabled=False,
    )
    base_config = EditorialAgentConfig(
        checkpoint_dir=tmp_path,
        checkpoint_backend="postgres",
        max_elapsed_s=60,
    )
    try:
        first = run_editorial_agent(
            [AgentJob("daily_news", "每日新闻")],
            tools=tools,
            config=base_config,
            run_id=run_id,
        )
        before_resume = dict(calls)
        second = run_editorial_agent(
            [],
            tools=tools,
            config=EditorialAgentConfig(
                checkpoint_dir=tmp_path,
                checkpoint_backend="postgres",
                resume_from=first.checkpoint_path,
                max_elapsed_s=60,
            ),
        )
        assert first.status == second.status == "completed"
        assert first.run_id == second.run_id == run_id
        assert calls == before_resume
    finally:
        with postgres_checkpointer(store) as saver:
            saver.delete_thread(run_id)


def test_editorial_agent_resume_budget_exhausted_postgres_run(tmp_path):
    store = KnowledgeStore.from_env()
    setup_postgres_checkpointer(store)
    run_id = "budget-resume-" + uuid4().hex
    calls = {"generate": 0, "upload": 0}

    def generate(_job, _context):
        calls["generate"] += 1
        return [{"id": "budget-post", "title": "test"}]

    def upload(_job, _post, _context):
        calls["upload"] += 1
        return True, "saved"

    tools = EditorialAgentTools(
        sync_context=lambda _job: {}, generate=generate,
        review=lambda *_args: [], upload=upload,
    )
    try:
        first = run_editorial_agent(
            [AgentJob("daily_news", "每日新闻")], tools=tools,
            config=EditorialAgentConfig(
                checkpoint_dir=tmp_path,
                checkpoint_backend="postgres",
                max_steps=2,
            ),
            run_id=run_id,
        )
        assert first.status == "blocked"

        second = run_editorial_agent(
            [], tools=tools,
            config=EditorialAgentConfig(
                checkpoint_dir=tmp_path,
                checkpoint_backend="postgres",
                resume_from=first.checkpoint_path,
                max_elapsed_s=60,
            ),
        )

        assert second.status == "completed"
        assert calls == {"generate": 1, "upload": 1}
    finally:
        with postgres_checkpointer(store) as saver:
            saver.delete_thread(run_id)
