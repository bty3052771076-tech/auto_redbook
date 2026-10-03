from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable, Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector import Vector
from pgvector.psycopg import register_vector

from .models import KnowledgeDocument


_SCHEMA_VERSION = 3
_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_CHUNK_VERSION = "char-token-320-overlap-48-v1"
_POOL_LOCK = threading.Lock()
_POOLS: dict[str, ConnectionPool] = {}


def _configure_connection(conn: Connection) -> None:
    register_vector(conn)


class KnowledgeStore:
    """PostgreSQL/pgvector knowledge store. Production never falls back to files or memory."""

    def __init__(self, *, credentials_path: Path | None = None):
        self.credentials_path = Path(credentials_path or os.getenv(
            "KNOWLEDGE_DB_CREDENTIALS", "data/knowledge/postgresql-local/connection.json"
        ))
        self._memory = False
        self._memory_documents: dict[tuple[str, str], dict[str, Any]] = {}
        self._pool_by_role: dict[str, ConnectionPool] = {}

    @classmethod
    def from_env(cls, *, credentials_path: Path | None = None) -> "KnowledgeStore":
        return cls(credentials_path=credentials_path)

    def _credentials(self, role: str = "app") -> dict[str, Any]:
        raw = json.loads(self.credentials_path.read_text(encoding="utf-8"))
        return {
            "host": raw.get("host", "127.0.0.1"),
            "port": int(raw.get("port", 5432)),
            "dbname": raw.get("database", "redbook_knowledge"),
            "user": raw[f"{role}_user"],
            "password": raw[f"{role}_password"],
        }

    def _pool(self, role: str = "app") -> ConnectionPool:
        if role in self._pool_by_role:
            return self._pool_by_role[role]
        from psycopg.conninfo import make_conninfo

        cfg = self._credentials(role)
        conninfo = make_conninfo(**cfg, connect_timeout=5, options="-c search_path=knowledge,public")
        pool_key = hashlib.sha256((str(self.credentials_path.resolve()) + role + conninfo).encode()).hexdigest()
        with _POOL_LOCK:
            pool = _POOLS.get(pool_key)
            if pool is None:
                pool = ConnectionPool(
                    conninfo,
                    min_size=1,
                    max_size=max(2, min(12, int(os.getenv("KNOWLEDGE_DB_POOL_MAX", "8")))),
                    timeout=max(1.0, float(os.getenv("KNOWLEDGE_DB_POOL_TIMEOUT", "5"))),
                    kwargs={"row_factory": dict_row},
                    configure=_configure_connection,
                    open=True,
                )
                _POOLS[pool_key] = pool
        self._pool_by_role[role] = pool
        return pool

    @contextmanager
    def connection(self, role: str = "app") -> Iterator[Connection]:
        with self._pool(role).connection() as conn:
            yield conn

    def ensure_schema(self) -> None:
        """Apply additive, serialized migrations; existing documents are never rebuilt."""
        with self.connection("migration") as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('redbook-knowledge-schema'))")
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            conn.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
            conn.execute("CREATE SCHEMA IF NOT EXISTS agent")
            conn.execute("CREATE TABLE IF NOT EXISTS knowledge.schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge.documents (
                  id bigserial PRIMARY KEY, record_id text NOT NULL, record_type text NOT NULL,
                  account_namespace text NOT NULL DEFAULT 'local', title text NOT NULL DEFAULT '',
                  body text NOT NULL DEFAULT '', source_url text NOT NULL DEFAULT '',
                  source_published_at text NOT NULL DEFAULT '', observed_at text NOT NULL DEFAULT '',
                  status text NOT NULL DEFAULT '', visibility text NOT NULL DEFAULT 'unknown',
                  allowed_purposes text NOT NULL DEFAULT '', metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                  content_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
                  updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (account_namespace, record_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge.document_versions (
                  id bigserial PRIMARY KEY, document_id bigint NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
                  content_hash text NOT NULL, snapshot jsonb NOT NULL,
                  captured_at timestamptz NOT NULL DEFAULT now(), UNIQUE(document_id, content_hash)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge.ingestion_runs (
                  run_id text PRIMARY KEY, domain text NOT NULL, input_count integer NOT NULL DEFAULT 0,
                  inserted_count integer NOT NULL DEFAULT 0, updated_count integer NOT NULL DEFAULT 0,
                  quarantined_count integer NOT NULL DEFAULT 0, status text NOT NULL,
                  details jsonb NOT NULL DEFAULT '{}'::jsonb, started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge.feedback (
                  id bigserial PRIMARY KEY, record_id text NOT NULL, feedback_type text NOT NULL,
                  note text NOT NULL DEFAULT '', evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
                  created_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge.chunks (
                  chunk_id text PRIMARY KEY, document_id bigint NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
                  document_version text NOT NULL, chunk_index integer NOT NULL, content text NOT NULL,
                  char_start integer NOT NULL, char_end integer NOT NULL, token_count integer NOT NULL,
                  embedding vector(384), model_id text NOT NULL, chunk_version text NOT NULL,
                  batch_id text NOT NULL, index_status text NOT NULL DEFAULT 'pending',
                  created_at timestamptz NOT NULL DEFAULT now(),
                  UNIQUE(document_id, document_version, chunk_index, model_id, chunk_version)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS documents_content_trgm_idx ON knowledge.documents USING gin ((lower(title || ' ' || body)) gin_trgm_ops)")
            conn.execute("CREATE INDEX IF NOT EXISTS documents_purpose_idx ON knowledge.documents (account_namespace, record_type, visibility, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_content_trgm_idx ON knowledge.chunks USING gin (lower(content) gin_trgm_ops)")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_document_idx ON knowledge.chunks (document_id, document_version, index_status)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent.conversations (
                  conversation_id text PRIMARY KEY, account_namespace text NOT NULL DEFAULT 'local',
                  status text NOT NULL DEFAULT 'active', active_snapshot_version integer NOT NULL DEFAULT 0,
                  last_message_seq bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            conn.execute("ALTER TABLE agent.conversations ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE agent.conversations ADD COLUMN IF NOT EXISTS payload jsonb NOT NULL DEFAULT '{}'::jsonb")
            conn.execute("ALTER TABLE agent.conversations ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE agent.conversations ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now()")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent.messages (
                  conversation_id text NOT NULL REFERENCES agent.conversations(conversation_id) ON DELETE CASCADE,
                  seq bigint NOT NULL, message_id text NOT NULL UNIQUE, role text NOT NULL,
                  content jsonb NOT NULL, tool_call_id text, created_at timestamptz NOT NULL DEFAULT now(),
                  PRIMARY KEY(conversation_id, seq)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent.compaction_snapshots (
                  conversation_id text NOT NULL REFERENCES agent.conversations(conversation_id) ON DELETE CASCADE,
                  version integer NOT NULL, through_seq bigint NOT NULL, summary text NOT NULL,
                  constraints jsonb NOT NULL, evidence_refs jsonb NOT NULL, task_state jsonb NOT NULL,
                  input_tokens integer NOT NULL, output_tokens integer NOT NULL,
                  status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
                  PRIMARY KEY(conversation_id, version)
                )
            """)
            conn.execute("INSERT INTO knowledge.schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING", (_SCHEMA_VERSION,))
            conn.execute("GRANT USAGE ON SCHEMA knowledge, agent TO redbook_app")
            conn.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA knowledge, agent TO redbook_app")
            conn.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA knowledge, agent TO redbook_app")
            conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO redbook_app")
            conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO redbook_app")
            conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT USAGE, SELECT ON SEQUENCES TO redbook_app")
            conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT USAGE, SELECT ON SEQUENCES TO redbook_app")

    def status(self) -> dict[str, Any]:
        try:
            with self.connection() as conn:
                row = conn.execute("""
                    SELECT count(*) AS documents,
                           count(*) FILTER (WHERE c.chunk_count > 0) AS indexed_documents,
                           coalesce(max(d.updated_at)::text, '') AS updated_at
                    FROM knowledge.documents d
                    LEFT JOIN LATERAL (
                      SELECT count(*) AS chunk_count FROM knowledge.chunks c
                      WHERE c.document_id=d.id AND c.index_status='ready' AND c.model_id=%s AND c.chunk_version=%s
                    ) c ON true
                """, (_MODEL_ID, _CHUNK_VERSION)).fetchone()
                return {
                    "status": "ready",
                    "documents": int(row["documents"]),
                    "indexed_documents": int(row["indexed_documents"]),
                    "index_ready": int(row["documents"]) == int(row["indexed_documents"]),
                    "updated_at": row["updated_at"],
                    "embedding_model": _MODEL_ID,
                    "embedding_dimensions": 384,
                }
        except Exception as exc:
            return {"status": "degraded", "documents": 0, "indexed_documents": 0, "index_ready": False, "error": _safe_error(exc)}

    def upsert_documents(self, documents: Iterable[KnowledgeDocument]) -> dict[str, int]:
        items = list(documents)
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        if self._memory:
            for item in items:
                key = (item.account_namespace, item.record_id)
                previous = self._memory_documents.get(key)
                kind = "inserted" if previous is None else ("unchanged" if previous["content_hash"] == item.content_hash else "updated")
                counts[kind] += 1
                self._memory_documents[key] = item.to_record()
            return counts
        if not items:
            return counts
        with self.connection() as conn, conn.transaction():
            for item in items:
                row = item.to_record()
                previous = conn.execute(
                    "SELECT id, record_type, account_namespace, title, body, source_url, source_published_at, observed_at, status, visibility, allowed_purposes, metadata, content_hash FROM knowledge.documents WHERE account_namespace=%s AND record_id=%s FOR UPDATE",
                    (item.account_namespace, item.record_id),
                ).fetchone()
                if previous and previous["content_hash"] == item.content_hash:
                    counts["unchanged"] += 1
                    continue
                if previous:
                    conn.execute(
                        "INSERT INTO knowledge.document_versions(document_id,content_hash,snapshot) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (previous["id"], previous["content_hash"], json.dumps(dict(previous), ensure_ascii=False, default=str)),
                    )
                    doc_id = previous["id"]
                    conn.execute("""
                        UPDATE knowledge.documents SET record_type=%s,title=%s,body=%s,source_url=%s,
                        source_published_at=%s,observed_at=%s,status=%s,visibility=%s,allowed_purposes=%s,
                        metadata=%s,content_hash=%s,updated_at=now() WHERE id=%s
                    """, (row["record_type"], row["title"], row["body"], row["source_url"], row["source_published_at"], row["observed_at"], row["status"], row["visibility"], ",".join(row["allowed_purposes"]), json.dumps(row["metadata"], ensure_ascii=False), row["content_hash"], doc_id))
                    conn.execute("DELETE FROM knowledge.chunks WHERE document_id=%s", (doc_id,))
                    counts["updated"] += 1
                else:
                    conn.execute("""
                        INSERT INTO knowledge.documents(record_id,record_type,account_namespace,title,body,source_url,
                        source_published_at,observed_at,status,visibility,allowed_purposes,metadata,content_hash)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (row["record_id"], row["record_type"], row["account_namespace"], row["title"], row["body"], row["source_url"], row["source_published_at"], row["observed_at"], row["status"], row["visibility"], ",".join(row["allowed_purposes"]), json.dumps(row["metadata"], ensure_ascii=False), row["content_hash"]))
                    counts["inserted"] += 1
        return counts

    def upsert_document(self, document: KnowledgeDocument) -> dict[str, Any]:
        result = self.upsert_documents([document])
        status = next((name for name, count in result.items() if count), "unchanged")
        return {"status": status, "record_id": document.record_id}

    def get(self, record_id: str, *, account_namespace: str = "local") -> dict[str, Any]:
        if self._memory:
            return dict(self._memory_documents[(account_namespace, record_id)])
        with self.connection() as conn:
            row = conn.execute("""
                SELECT record_id,record_type,account_namespace,title,body,source_url,source_published_at,
                       observed_at,status,visibility,allowed_purposes,metadata,content_hash
                FROM knowledge.documents WHERE account_namespace=%s AND record_id=%s
            """, (account_namespace, record_id)).fetchone()
        if not row:
            raise KeyError(record_id)
        item = dict(row)
        item["allowed_purposes"] = [p for p in (item.get("allowed_purposes") or "").split(",") if p]
        return item

    def pending_documents(self, *, limit: int = 128) -> list[dict[str, Any]]:
        if self._memory:
            raise RuntimeError("RAG indexing is disabled in test-only in-memory mode")
        with self.connection() as conn:
            rows = conn.execute("""
                SELECT d.record_id,d.record_type,d.account_namespace,d.title,d.body,d.source_url,
                       d.source_published_at,d.observed_at,d.status,d.visibility,d.allowed_purposes,
                       d.metadata,d.content_hash
                FROM knowledge.documents d
                WHERE NOT EXISTS (
                    SELECT 1 FROM knowledge.chunks c WHERE c.document_id=d.id
                    AND c.document_version=d.content_hash AND c.model_id=%s
                    AND c.chunk_version=%s AND c.index_status='ready'
                )
                ORDER BY d.id LIMIT %s
            """, (_MODEL_ID, _CHUNK_VERSION, max(1, min(1000, int(limit))))).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["allowed_purposes"] = [p for p in (item.get("allowed_purposes") or "").split(",") if p]
            result.append(item)
        return result

    def index_progress(self) -> dict[str, int]:
        if self._memory:
            return {"documents": len(self._memory_documents), "indexed_documents": 0, "pending_documents": len(self._memory_documents)}
        with self.connection() as conn:
            row = conn.execute("""
                SELECT count(*) AS documents,
                       count(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM knowledge.chunks c WHERE c.document_id=d.id
                           AND c.document_version=d.content_hash AND c.model_id=%s
                           AND c.chunk_version=%s AND c.index_status='ready'
                       )) AS indexed_documents
                FROM knowledge.documents d
            """, (_MODEL_ID, _CHUNK_VERSION)).fetchone()
        total, indexed = int(row["documents"]), int(row["indexed_documents"])
        return {"documents": total, "indexed_documents": indexed, "pending_documents": total - indexed}

    def upsert_chunks(self, record_id: str, chunks: list[dict[str, Any]], *, account_namespace: str = "local") -> int:
        if self._memory:
            raise RuntimeError("RAG vectors are disabled in test-only in-memory mode")
        with self.connection() as conn, conn.transaction():
            row = conn.execute("SELECT id,content_hash FROM knowledge.documents WHERE account_namespace=%s AND record_id=%s", (account_namespace, record_id)).fetchone()
            if not row:
                raise KeyError(record_id)
            for chunk in chunks:
                conn.execute("""
                    INSERT INTO knowledge.chunks(chunk_id,document_id,document_version,chunk_index,content,char_start,char_end,
                        token_count,embedding,model_id,chunk_version,batch_id,index_status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready')
                    ON CONFLICT(chunk_id) DO UPDATE SET content=EXCLUDED.content,char_start=EXCLUDED.char_start,
                        char_end=EXCLUDED.char_end,token_count=EXCLUDED.token_count,embedding=EXCLUDED.embedding,
                        index_status='ready',batch_id=EXCLUDED.batch_id
                """, (chunk["chunk_id"], row["id"], row["content_hash"], chunk["chunk_index"], chunk["content"], chunk["char_start"], chunk["char_end"], chunk["token_count"], Vector(chunk["embedding"]), _MODEL_ID, _CHUNK_VERSION, chunk["batch_id"]))
        return len(chunks)

    def search(self, query: str, *, purpose: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        capped = max(1, min(100, int(limit)))
        if self._memory:
            terms = [term.casefold() for term in query.split() if term]
            hits = []
            for item in self._memory_documents.values():
                if purpose and purpose not in item["allowed_purposes"]:
                    continue
                text = f"{item['title']} {item['body']}".casefold()
                if all(term in text for term in terms):
                    hits.append(item)
            return hits[:capped]
        from .embeddings import get_embedding_model

        embedder = get_embedding_model()
        query_vector = Vector(embedder.embed_query(query))
        purpose_filter = purpose or ""
        with self.connection() as conn:
            ready = conn.execute("SELECT count(*) AS n FROM knowledge.chunks WHERE index_status='ready' AND model_id=%s AND chunk_version=%s", (_MODEL_ID, _CHUNK_VERSION)).fetchone()["n"]
            if not ready:
                raise RuntimeError("KNOWLEDGE_INDEX_NOT_READY: no ready vector chunks for the configured embedding model")
            rows = conn.execute("""
                WITH semantic AS (
                    SELECT c.chunk_id, row_number() OVER (ORDER BY c.embedding <=> %s) AS rank
                    FROM knowledge.chunks c JOIN knowledge.documents d ON d.id=c.document_id
                    WHERE c.index_status='ready' AND c.model_id=%s AND c.chunk_version=%s
                      AND d.account_namespace=%s AND (%s='' OR (','||d.allowed_purposes||',') LIKE ('%%,'||%s||',%%'))
                    ORDER BY c.embedding <=> %s LIMIT 40
                ), lexical AS (
                    SELECT c.chunk_id, row_number() OVER (ORDER BY similarity(lower(d.title||' '||c.content),lower(%s)) DESC) AS rank
                    FROM knowledge.chunks c JOIN knowledge.documents d ON d.id=c.document_id
                    WHERE c.index_status='ready' AND c.model_id=%s AND c.chunk_version=%s
                      AND d.account_namespace=%s AND (%s='' OR (','||d.allowed_purposes||',') LIKE ('%%,'||%s||',%%'))
                      AND (lower(d.title||' '||c.content) %% lower(%s) OR lower(d.title||' '||c.content) LIKE ('%%'||lower(%s)||'%%'))
                    ORDER BY similarity(lower(d.title||' '||c.content),lower(%s)) DESC LIMIT 40
                ), fused AS (
                    SELECT chunk_id, sum(1.0/(60+rank)) AS score FROM (
                        SELECT chunk_id,rank FROM semantic UNION ALL SELECT chunk_id,rank FROM lexical
                    ) candidates GROUP BY chunk_id
                )
                SELECT d.record_id,d.record_type,d.account_namespace,d.title,d.body,d.source_url,d.source_published_at,
                       d.observed_at,d.status,d.visibility,d.allowed_purposes,d.metadata,d.content_hash,
                       c.chunk_id,c.content AS matched_chunk,c.char_start,c.char_end,f.score
                FROM fused f JOIN knowledge.chunks c USING(chunk_id) JOIN knowledge.documents d ON d.id=c.document_id
                ORDER BY f.score DESC LIMIT %s
            """, (query_vector,_MODEL_ID,_CHUNK_VERSION,"local",purpose_filter,purpose_filter,query_vector,query,_MODEL_ID,_CHUNK_VERSION,"local",purpose_filter,purpose_filter,query,query,query,capped)).fetchall()
        result = []
        seen = set()
        for row in rows:
            key = row["record_id"]
            if key in seen:
                continue
            seen.add(key)
            item = dict(row)
            item["allowed_purposes"] = [p for p in (item.get("allowed_purposes") or "").split(",") if p]
            result.append(item)
        return result[:capped]


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"(?i)(password|api[_-]?key|token)=([^\s]+)", r"\1=[redacted]", message)
    return message[:500]
