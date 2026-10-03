from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .ingest import ingest_posts
from .embeddings import index_pending_documents
from .store import KnowledgeStore


def prepare_local_knowledge_snapshot(
    *,
    data_root: Path = Path("data"),
    store: KnowledgeStore | None = None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, Any]:
    current = store or KnowledgeStore.from_env()
    try:
        readiness = current.status()
        if readiness.get("status") != "ready":
            raise RuntimeError(readiness.get("error") or "KNOWLEDGE_DB_UNAVAILABLE: schema is not ready")
        report = ingest_posts(current, data_root=data_root)
        report.update(index_pending_documents(current, progress_callback=progress_callback))
        report["index_progress"] = current.index_progress()
        if report["index_progress"]["pending_documents"]:
            raise RuntimeError("KNOWLEDGE_INDEX_NOT_READY: vector indexing is incomplete")
        report["knowledge_status"] = "ready"
        report["snapshot_id"] = uuid4().hex
        return report
    except Exception as exc:
        message = str(exc)
        error_code = "EMBEDDING_MODEL_UNAVAILABLE" if "EMBEDDING_MODEL" in message else (
            "KNOWLEDGE_INDEX_NOT_READY" if "KNOWLEDGE_INDEX_NOT_READY" in message else "KNOWLEDGE_DB_UNAVAILABLE"
        )
        return {
            "knowledge_status": "blocked",
            "error_code": error_code,
            "snapshot_id": "",
            "input_count": 0,
            "documents": 0,
            "warning": f"PostgreSQL 知识库不可用，已阻止生成。请启动本地数据库并检查连接/迁移状态。详情：{exc}",
        }


def knowledge_context(
    *,
    job_kind: str,
    query: str = "",
    store_factory: Callable[[], KnowledgeStore] | None = None,
) -> dict[str, Any]:
    try:
        store = store_factory() if store_factory else KnowledgeStore.from_env()
        status = store.status()
        if status.get("status") != "ready":
            raise RuntimeError(status.get("error") or "knowledge database unavailable")
        if not status.get("index_ready"):
            raise RuntimeError("KNOWLEDGE_INDEX_NOT_READY: vector index watermark is incomplete")
        hits = store.search(query, purpose="duplicate_reference", limit=8) if query else []
        return {
            "knowledge_status": status.get("status"),
            "knowledge_documents": status.get("documents", 0),
            "knowledge_hits": hits,
            "job_kind": job_kind,
        }
    except Exception as exc:
        return {
            "knowledge_status": "blocked",
            "error_code": "KNOWLEDGE_INDEX_NOT_READY" if "KNOWLEDGE_INDEX_NOT_READY" in str(exc) else (
                "EMBEDDING_MODEL_UNAVAILABLE" if "EMBEDDING_MODEL" in str(exc) else "KNOWLEDGE_DB_UNAVAILABLE"
            ),
            "knowledge_documents": 0,
            "knowledge_hits": [],
            "knowledge_warning": f"PostgreSQL 知识库不可用，已阻止生成。请启动本地数据库并检查连接/迁移状态。详情：{exc}",
            "job_kind": job_kind,
        }
