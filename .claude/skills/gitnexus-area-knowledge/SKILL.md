---
name: gitnexus-area-knowledge
description: "Skill for the Knowledge area of auto_redbook. 20 symbols across 6 files."
---

# Knowledge

20 symbols | 6 files | Cohesion: 77%

## When to Use

- Working with code in `src/`
- Understanding how document_from_post, ingest_posts, test_ingest_posts_preserves_private_and_failed_purpose work
- Modifying knowledge-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/knowledge/store.py` | _json_literal, _sql_literal, _credentials, _psql_path, _run_sql (+7) |
| `src/knowledge/ingest.py` | _purposes, document_from_post, ingest_posts |
| `tests/test_knowledge_store.py` | test_postgres_store_is_idempotent_and_searchable, test_store_rejects_secret_fields |
| `tests/test_knowledge_ingest.py` | test_ingest_posts_preserves_private_and_failed_purpose |
| `src/knowledge/service.py` | prepare_local_knowledge_snapshot |
| `src/knowledge/models.py` | to_record |

## Entry Points

Start here when exploring this area:

- **`document_from_post`** (Function) — `src/knowledge/ingest.py:27`
- **`ingest_posts`** (Function) — `src/knowledge/ingest.py:51`
- **`test_ingest_posts_preserves_private_and_failed_purpose`** (Function) — `tests/test_knowledge_ingest.py:10`
- **`prepare_local_knowledge_snapshot`** (Function) — `src/knowledge/service.py:10`
- **`test_postgres_store_is_idempotent_and_searchable`** (Function) — `tests/test_knowledge_store.py:8`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `document_from_post` | Function | `src/knowledge/ingest.py` | 27 |
| `ingest_posts` | Function | `src/knowledge/ingest.py` | 51 |
| `test_ingest_posts_preserves_private_and_failed_purpose` | Function | `tests/test_knowledge_ingest.py` | 10 |
| `prepare_local_knowledge_snapshot` | Function | `src/knowledge/service.py` | 10 |
| `test_postgres_store_is_idempotent_and_searchable` | Function | `tests/test_knowledge_store.py` | 8 |
| `test_store_rejects_secret_fields` | Function | `tests/test_knowledge_store.py` | 30 |
| `ensure_schema` | Method | `src/knowledge/store.py` | 133 |
| `get` | Method | `src/knowledge/store.py` | 200 |
| `status` | Method | `src/knowledge/store.py` | 138 |
| `upsert_documents` | Method | `src/knowledge/store.py` | 151 |
| `to_record` | Method | `src/knowledge/models.py` | 36 |
| `from_env` | Method | `src/knowledge/store.py` | 97 |
| `search` | Method | `src/knowledge/store.py` | 214 |
| `upsert_document` | Method | `src/knowledge/store.py` | 190 |
| `_purposes` | Function | `src/knowledge/ingest.py` | 14 |
| `_json_literal` | Function | `src/knowledge/store.py` | 81 |
| `_sql_literal` | Function | `src/knowledge/store.py` | 73 |
| `_credentials` | Method | `src/knowledge/store.py` | 100 |
| `_psql_path` | Method | `src/knowledge/store.py` | 110 |
| `_run_sql` | Method | `src/knowledge/store.py` | 116 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Prepare_local_knowledge_snapshot → _credentials` | cross_community | 6 |
| `Prepare_local_knowledge_snapshot → _psql_path` | cross_community | 6 |
| `Prepare_local_knowledge_snapshot → _purposes` | cross_community | 4 |
| `Prepare_local_knowledge_snapshot → _read_json` | cross_community | 4 |
| `Sync_context → From_env` | cross_community | 3 |
| `Search → _credentials` | cross_community | 3 |
| `Search → _psql_path` | cross_community | 3 |

## How to Explore

1. `context({name: "document_from_post"})` — see callers and callees
2. `query({search_query: "knowledge"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
