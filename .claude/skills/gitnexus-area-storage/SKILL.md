---
name: gitnexus-area-storage
description: "Skill for the Storage area of auto_redbook. 28 symbols across 5 files."
---

# Storage

28 symbols | 5 files | Cohesion: 66%

## When to Use

- Working with code in `src/`
- Understanding how save_draft_via_chrome, copy_assets_into_post, evidence_dir work
- Modifying storage-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/storage/files.py` | copy_assets_into_post, evidence_dir, execution_path, post_dir, revision_path (+14) |
| `tests/test_storage.py` | test_copy_assets_and_execution, test_save_published_metrics_snapshot_latest_csv_uses_current_snapshot_only, test_save_published_metrics_snapshot_updates_latest_csv_without_duplicates, test_save_published_metrics_snapshot_writes_jsonl_and_csv, test_append_run_record_writes_table_and_jsonl |
| `src/publish/image_draft.py` | save_draft_via_chrome, _step |
| `src/publish/toutiao_steps.py` | _capture_toutiao_evidence |
| `tests/test_web_gui.py` | test_saved_draft_is_not_readback_verified |

## Entry Points

Start here when exploring this area:

- **`save_draft_via_chrome`** (Function) — `src/publish/image_draft.py:10`
- **`copy_assets_into_post`** (Function) — `src/storage/files.py:141`
- **`evidence_dir`** (Function) — `src/storage/files.py:78`
- **`execution_path`** (Function) — `src/storage/files.py:74`
- **`post_dir`** (Function) — `src/storage/files.py:66`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `save_draft_via_chrome` | Function | `src/publish/image_draft.py` | 10 |
| `copy_assets_into_post` | Function | `src/storage/files.py` | 141 |
| `evidence_dir` | Function | `src/storage/files.py` | 78 |
| `execution_path` | Function | `src/storage/files.py` | 74 |
| `post_dir` | Function | `src/storage/files.py` | 66 |
| `revision_path` | Function | `src/storage/files.py` | 70 |
| `save_execution` | Function | `src/storage/files.py` | 116 |
| `save_revision` | Function | `src/storage/files.py` | 110 |
| `test_copy_assets_and_execution` | Function | `tests/test_storage.py` | 60 |
| `test_saved_draft_is_not_readback_verified` | Function | `tests/test_web_gui.py` | 454 |
| `list_published_metrics` | Function | `src/storage/files.py` | 224 |
| `published_metrics_paths` | Function | `src/storage/files.py` | 190 |
| `save_published_metrics_snapshot` | Function | `src/storage/files.py` | 205 |
| `test_save_published_metrics_snapshot_latest_csv_uses_current_snapshot_only` | Function | `tests/test_storage.py` | 133 |
| `test_save_published_metrics_snapshot_updates_latest_csv_without_duplicates` | Function | `tests/test_storage.py` | 107 |
| `test_save_published_metrics_snapshot_writes_jsonl_and_csv` | Function | `tests/test_storage.py` | 82 |
| `append_run_record` | Function | `src/storage/files.py` | 264 |
| `list_run_records` | Function | `src/storage/files.py` | 274 |
| `run_records_paths` | Function | `src/storage/files.py` | 198 |
| `test_append_run_record_writes_table_and_jsonl` | Function | `tests/test_storage.py` | 160 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `List_live_publishable_drafts → Post_dir` | cross_community | 6 |
| `List_recent_post_ids → Post_dir` | cross_community | 6 |
| `Agent_events → Post_dir` | cross_community | 6 |
| `Posts → Post_dir` | cross_community | 6 |
| `Analyze_metrics → Published_metrics_paths` | cross_community | 5 |
| `Sync_context → Published_metrics_paths` | cross_community | 5 |
| `Edit_post → Post_dir` | cross_community | 5 |
| `Publish_drafts → Post_dir` | cross_community | 4 |
| `Retry → Post_dir` | cross_community | 4 |
| `Update_draft → Post_dir` | cross_community | 4 |

## How to Explore

1. `context({name: "save_draft_via_chrome"})` — see callers and callees
2. `query({search_query: "storage"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
