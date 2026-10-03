from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.conninfo import make_conninfo
from langgraph.checkpoint.postgres import PostgresSaver

from src.knowledge.store import KnowledgeStore


def _conninfo(store: KnowledgeStore, role: str) -> str:
    return make_conninfo(**store._credentials(role), connect_timeout=5, options="-c statement_timeout=30000 -c lock_timeout=5000")


@contextmanager
def postgres_checkpointer(store: KnowledgeStore | None = None) -> Iterator[PostgresSaver]:
    current = store or KnowledgeStore.from_env()
    conn = psycopg.connect(_conninfo(current, "app"), autocommit=True, prepare_threshold=0)
    try:
        yield PostgresSaver(conn)
    finally:
        conn.close()


def setup_postgres_checkpointer(store: KnowledgeStore | None = None) -> dict[str, str]:
    """Initialize official LangGraph checkpoint tables using migration credentials."""
    current = store or KnowledgeStore.from_env()
    conn = psycopg.connect(_conninfo(current, "migration"), autocommit=True, prepare_threshold=0)
    try:
        saver = PostgresSaver(conn)
        saver.setup()
        conn.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations TO redbook_app"
        )
        return {"status": "ready", "backend": "langgraph-postgres-saver"}
    finally:
        conn.close()
