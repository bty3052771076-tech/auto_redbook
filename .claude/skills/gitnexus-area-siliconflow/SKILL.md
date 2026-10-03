---
name: gitnexus-area-siliconflow
description: "Skill for the Siliconflow area of auto_redbook. 24 symbols across 2 files."
---

# Siliconflow

24 symbols | 2 files | Cohesion: 77%

## When to Use

- Working with code in `src/`
- Understanding how run_collect_siliconflow_quota_sync, test_parse_visible_model_lines_extracts_free_and_usage_rows, test_classify_model_detects_llm_and_image_kinds work
- Modifying siliconflow-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/siliconflow/quota.py` | _emit, _env_flag, _extract_console_text, _load_api_key, _looks_like_login_page (+15) |
| `tests/test_siliconflow_quota.py` | test_parse_visible_model_lines_extracts_free_and_usage_rows, test_classify_model_detects_llm_and_image_kinds, test_free_image_model_marker_only_marks_free_models, test_siliconflow_quota_model_candidates_merge_defaults_and_env |

## Entry Points

Start here when exploring this area:

- **`run_collect_siliconflow_quota_sync`** (Function) — `src/siliconflow/quota.py:438`
- **`test_parse_visible_model_lines_extracts_free_and_usage_rows`** (Function) — `tests/test_siliconflow_quota.py:43`
- **`test_classify_model_detects_llm_and_image_kinds`** (Function) — `tests/test_siliconflow_quota.py:11`
- **`test_free_image_model_marker_only_marks_free_models`** (Function) — `tests/test_siliconflow_quota.py:23`
- **`siliconflow_quota_model_candidates`** (Function) — `src/siliconflow/quota.py:141`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `run_collect_siliconflow_quota_sync` | Function | `src/siliconflow/quota.py` | 438 |
| `test_parse_visible_model_lines_extracts_free_and_usage_rows` | Function | `tests/test_siliconflow_quota.py` | 43 |
| `test_classify_model_detects_llm_and_image_kinds` | Function | `tests/test_siliconflow_quota.py` | 11 |
| `test_free_image_model_marker_only_marks_free_models` | Function | `tests/test_siliconflow_quota.py` | 23 |
| `siliconflow_quota_model_candidates` | Function | `src/siliconflow/quota.py` | 141 |
| `test_siliconflow_quota_model_candidates_merge_defaults_and_env` | Function | `tests/test_siliconflow_quota.py` | 29 |
| `_emit` | Function | `src/siliconflow/quota.py` | 230 |
| `_env_flag` | Function | `src/siliconflow/quota.py` | 242 |
| `_extract_console_text` | Function | `src/siliconflow/quota.py` | 304 |
| `_load_api_key` | Function | `src/siliconflow/quota.py` | 171 |
| `_looks_like_login_page` | Function | `src/siliconflow/quota.py` | 278 |
| `_parse_int` | Function | `src/siliconflow/quota.py` | 365 |
| `_parse_visible_model_lines` | Function | `src/siliconflow/quota.py` | 311 |
| `_read_body_text` | Function | `src/siliconflow/quota.py` | 269 |
| `_repo_root` | Function | `src/siliconflow/quota.py` | 52 |
| `_resolve_profile_config` | Function | `src/siliconflow/quota.py` | 254 |
| `_api_get_json` | Function | `src/siliconflow/quota.py` | 195 |
| `_api_model_records` | Function | `src/siliconflow/quota.py` | 375 |
| `_api_user_info` | Function | `src/siliconflow/quota.py` | 407 |
| `_classify_model` | Function | `src/siliconflow/quota.py` | 84 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Siliconflow_quota → _repo_root` | cross_community | 4 |
| `Siliconflow_quota → _dedupe` | cross_community | 4 |
| `Siliconflow_quota → _split_values` | cross_community | 4 |
| `Siliconflow_quota → _env_flag` | cross_community | 3 |

## How to Explore

1. `context({name: "run_collect_siliconflow_quota_sync"})` — see callers and callees
2. `query({search_query: "siliconflow"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
