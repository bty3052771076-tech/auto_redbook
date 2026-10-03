"""Project-owned MCP server exposing narrow, read-only workflow tools."""
from __future__ import annotations

import asyncio
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from src.news.daily_news import fetch_daily_news_candidates
from src.knowledge.store import KnowledgeStore

mcp = FastMCP("redbook-workflow-local")


@mcp.tool()
async def runtime_status() -> dict:
    """Return PostgreSQL/RAG readiness without exposing credentials."""
    def read_status() -> dict:
        return KnowledgeStore.from_env().status()

    return await asyncio.to_thread(read_status)


@mcp.tool()
async def knowledge_search(query: str, purpose: str = "duplicate_reference", limit: int = 8) -> dict:
    """Search ready PostgreSQL/pgvector knowledge for an approved purpose."""
    if purpose not in {"duplicate_reference", "evidence", "style_reference", "operations"}:
        raise ValueError("purpose is not allowed")
    if not str(query or "").strip() or len(query) > 2000:
        raise ValueError("query must contain 1..2000 characters")
    def search() -> dict:
        store = KnowledgeStore.from_env()
        status = store.status()
        if status.get("status") != "ready" or not status.get("index_ready"):
            raise RuntimeError("KNOWLEDGE_INDEX_NOT_READY")
        results = store.search(query, purpose=purpose, limit=max(1, min(20, int(limit))))
        return {"status": "ok" if results else "ok_empty", "results": results}

    return await asyncio.to_thread(search)


@mcp.tool()
async def news_search(query: str, days: int = 2, limit: int = 20) -> dict:
    """Collect current daily-news candidates through the existing approved source pipeline."""
    query = str(query or "").strip()
    days = max(1, min(7, int(days)))
    limit = max(1, min(50, int(limit)))
    if not query or len(query) > 2000:
        raise ValueError("query must contain 1..2000 characters")
    def search() -> dict:
        candidates, meta = fetch_daily_news_candidates(
            query,
            max_records=limit,
            search_days=days,
            timeout_s=35,
            exhaustive_sources=True,
            _unified_sources=True,
        )
        return {
            "status": "ok" if candidates else "ok_empty",
            "trace_id": uuid4().hex,
            "items": [
                {"title": item.title, "url": item.url, "source": item.source,
                 "description": item.description, "published_at": item.seendate,
                 "discovery_provider": item.provider}
                for item in candidates[:limit]
            ],
            "source_meta": meta,
        }

    return await asyncio.to_thread(search)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
