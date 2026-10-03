---
name: gitnexus-area-volcengine
description: "Skill for the Volcengine area of auto_redbook. 63 symbols across 3 files."
---

# Volcengine

63 symbols | 3 files | Cohesion: 71%

## When to Use

- Working with code in `src/`
- Understanding how run_collect_volcengine_quota_sync, test_capture_charge_item_request_headers_accepts_any_ark_console_api_request, test_fetch_all_charge_item_payloads_pages_without_model_filter work
- Modifying volcengine-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/volcengine/quota.py` | _capture_charge_item_request_headers, _capture_json_response, _click_usage_tracking, _emit, _env_flag (+42) |
| `tests/test_volcengine_quota.py` | test_capture_charge_item_request_headers_accepts_any_ark_console_api_request, test_fetch_all_charge_item_payloads_pages_without_model_filter, test_fetch_target_charge_item_payloads_uses_default_headers_without_capture, test_parse_volcengine_console_api_quota_distinguishes_available_without_free_usage, test_parse_volcengine_console_api_quota_extracts_free_usage (+10) |
| `apps/cli.py` | volcengine_quota |

## Entry Points

Start here when exploring this area:

- **`run_collect_volcengine_quota_sync`** (Function) — `src/volcengine/quota.py:933`
- **`test_capture_charge_item_request_headers_accepts_any_ark_console_api_request`** (Function) — `tests/test_volcengine_quota.py:203`
- **`test_fetch_all_charge_item_payloads_pages_without_model_filter`** (Function) — `tests/test_volcengine_quota.py:178`
- **`parse_volcengine_console_api_quota`** (Function) — `src/volcengine/quota.py:508`
- **`test_fetch_target_charge_item_payloads_uses_default_headers_without_capture`** (Function) — `tests/test_volcengine_quota.py:160`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `run_collect_volcengine_quota_sync` | Function | `src/volcengine/quota.py` | 933 |
| `test_capture_charge_item_request_headers_accepts_any_ark_console_api_request` | Function | `tests/test_volcengine_quota.py` | 203 |
| `test_fetch_all_charge_item_payloads_pages_without_model_filter` | Function | `tests/test_volcengine_quota.py` | 178 |
| `parse_volcengine_console_api_quota` | Function | `src/volcengine/quota.py` | 508 |
| `test_fetch_target_charge_item_payloads_uses_default_headers_without_capture` | Function | `tests/test_volcengine_quota.py` | 160 |
| `test_parse_volcengine_console_api_quota_distinguishes_available_without_free_usage` | Function | `tests/test_volcengine_quota.py` | 246 |
| `test_parse_volcengine_console_api_quota_extracts_free_usage` | Function | `tests/test_volcengine_quota.py` | 219 |
| `test_parse_volcengine_console_api_quota_extracts_resource_pack_free_inference` | Function | `tests/test_volcengine_quota.py` | 278 |
| `parse_volcengine_quota_text` | Function | `src/volcengine/quota.py` | 310 |
| `test_parse_volcengine_quota_text_extracts_llm_and_image_values` | Function | `tests/test_volcengine_quota.py` | 36 |
| `test_parse_volcengine_quota_text_handles_reordered_columns_units_and_status` | Function | `tests/test_volcengine_quota.py` | 74 |
| `parse_all_volcengine_console_api_quota` | Function | `src/volcengine/quota.py` | 569 |
| `test_charge_item_model_names_discovers_models_outside_static_candidates` | Function | `tests/test_volcengine_quota.py` | 17 |
| `test_parse_all_volcengine_console_api_quota_keeps_resource_pack_free_models` | Function | `tests/test_volcengine_quota.py` | 315 |
| `volcengine_quota` | Function | `apps/cli.py` | 4268 |
| `format_volcengine_quota_records` | Function | `src/volcengine/quota.py` | 606 |
| `test_format_volcengine_quota_records_marks_unknown_remaining_values` | Function | `tests/test_volcengine_quota.py` | 118 |
| `test_make_volcengine_not_visible_records_marks_visible_only_status` | Function | `tests/test_volcengine_quota.py` | 132 |
| `test_complete_volcengine_visible_only_records_fills_missing_targets` | Function | `tests/test_volcengine_quota.py` | 147 |
| `volcengine_quota_model_candidates` | Function | `src/volcengine/quota.py` | 92 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Volcengine_quota → _repo_root` | cross_community | 4 |
| `Volcengine_quota → _dedupe` | cross_community | 4 |
| `Volcengine_quota → _split_values` | cross_community | 4 |
| `Volcengine_quota → _cell` | intra_community | 3 |
| `Volcengine_quota → _env_flag` | cross_community | 3 |
| `Volcengine_quota → _jsonable_quota_result` | cross_community | 3 |
| `Volcengine_quota → _format_progress_event` | cross_community | 3 |

## How to Explore

1. `context({name: "run_collect_volcengine_quota_sync"})` — see callers and callees
2. `query({search_query: "volcengine"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
