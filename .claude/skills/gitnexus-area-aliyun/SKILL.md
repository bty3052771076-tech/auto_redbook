---
name: gitnexus-area-aliyun
description: "Skill for the Aliyun area of auto_redbook. 51 symbols across 3 files."
---

# Aliyun

51 symbols | 3 files | Cohesion: 70%

## When to Use

- Working with code in `src/`
- Understanding how walk, parse_aliyun_console_api_quota, parse_all_aliyun_console_api_quota work
- Modifying aliyun-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/aliyun/quota.py` | _aliyun_api_status, _as_number, _date_from_epoch_ms, _extract_aliyun_free_tier_quota_items, walk (+34) |
| `tests/test_aliyun_quota.py` | test_parse_aliyun_console_api_quota_extracts_free_tier_quotas, test_parse_all_aliyun_console_api_quota_keeps_only_models_with_free_tier_total, test_wait_for_aliyun_quota_capture_waits_until_api_items_stop_growing, test_detect_aliyun_console_errors_marks_internal_not_logged_in, test_detect_aliyun_console_errors_uses_later_logged_in_status (+6) |
| `apps/cli.py` | aliyun_quota |

## Entry Points

Start here when exploring this area:

- **`walk`** (Function) — `src/aliyun/quota.py:398`
- **`parse_aliyun_console_api_quota`** (Function) — `src/aliyun/quota.py:449`
- **`parse_all_aliyun_console_api_quota`** (Function) — `src/aliyun/quota.py:497`
- **`test_parse_aliyun_console_api_quota_extracts_free_tier_quotas`** (Function) — `tests/test_aliyun_quota.py:204`
- **`test_parse_all_aliyun_console_api_quota_keeps_only_models_with_free_tier_total`** (Function) — `tests/test_aliyun_quota.py:242`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `walk` | Function | `src/aliyun/quota.py` | 398 |
| `parse_aliyun_console_api_quota` | Function | `src/aliyun/quota.py` | 449 |
| `parse_all_aliyun_console_api_quota` | Function | `src/aliyun/quota.py` | 497 |
| `test_parse_aliyun_console_api_quota_extracts_free_tier_quotas` | Function | `tests/test_aliyun_quota.py` | 204 |
| `test_parse_all_aliyun_console_api_quota_keeps_only_models_with_free_tier_total` | Function | `tests/test_aliyun_quota.py` | 242 |
| `run_collect_aliyun_quota_sync` | Function | `src/aliyun/quota.py` | 886 |
| `test_wait_for_aliyun_quota_capture_waits_until_api_items_stop_growing` | Function | `tests/test_aliyun_quota.py` | 18 |
| `detect_aliyun_console_errors` | Function | `src/aliyun/quota.py` | 571 |
| `test_detect_aliyun_console_errors_marks_internal_not_logged_in` | Function | `tests/test_aliyun_quota.py` | 361 |
| `test_detect_aliyun_console_errors_uses_later_logged_in_status` | Function | `tests/test_aliyun_quota.py` | 381 |
| `test_should_retry_aliyun_quota_after_login_transition_only_for_empty_retryable_page` | Function | `tests/test_aliyun_quota.py` | 392 |
| `test_complete_aliyun_visible_only_records_fills_missing_targets` | Function | `tests/test_aliyun_quota.py` | 348 |
| `test_make_aliyun_not_visible_records_marks_visible_only_status` | Function | `tests/test_aliyun_quota.py` | 333 |
| `aliyun_quota` | Function | `apps/cli.py` | 4172 |
| `format_aliyun_quota_records` | Function | `src/aliyun/quota.py` | 614 |
| `test_format_aliyun_quota_records_marks_unknown_remaining_values` | Function | `tests/test_aliyun_quota.py` | 322 |
| `aliyun_quota_model_candidates` | Function | `src/aliyun/quota.py` | 106 |
| `test_aliyun_quota_default_image_candidates_include_current_qwen_image` | Function | `tests/test_aliyun_quota.py` | 308 |
| `test_aliyun_quota_model_candidates_merge_defaults_and_env` | Function | `tests/test_aliyun_quota.py` | 294 |
| `_aliyun_api_status` | Function | `src/aliyun/quota.py` | 424 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Aliyun_quota → _repo_root` | cross_community | 4 |
| `Aliyun_quota → _dedupe` | cross_community | 4 |
| `Aliyun_quota → _split_values` | cross_community | 4 |
| `Sync_quotas → _repo_root` | cross_community | 4 |
| `Sync_quotas → _dedupe` | cross_community | 4 |
| `Sync_quotas → _split_values` | cross_community | 4 |
| `Aliyun_quota → _jsonable_quota_result` | cross_community | 3 |
| `Aliyun_quota → _cell` | intra_community | 3 |
| `Aliyun_quota → _env_flag` | cross_community | 3 |
| `Sync_quotas → _cell` | cross_community | 3 |

## How to Explore

1. `context({name: "walk"})` — see callers and callees
2. `query({search_query: "aliyun"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
