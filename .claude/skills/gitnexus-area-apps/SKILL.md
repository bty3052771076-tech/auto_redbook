---
name: gitnexus-area-apps
description: "Skill for the Apps area of auto_redbook. 475 symbols across 37 files."
---

# Apps

475 symbols | 37 files | Cohesion: 69%

## When to Use

- Working with code in `apps/`
- Understanding how daily_global_map, delete_drafts, progress work
- Modifying apps-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `apps/gui.py` | _clean_env, build_subprocess_env, _auto_env, _collect_env_overrides, _material_env (+193) |
| `apps/cli.py` | _emit_progress_event, _format_progress_event, _headless_option_value, _next_attempt, _refresh_metrics_for_preflight (+78) |
| `apps/web_service.py` | read_json, valid_conversation_id, valid_id, __init__, _agent_conversation_path (+47) |
| `tests/test_gui.py` | test_build_subprocess_env_forces_unbuffered_utf8_output, test_debounced_callback_keeps_only_the_latest_scheduled_refresh, test_gui_hidden_autorun_propagates_child_exit_code, test_resolve_delete_mode_flags_keeps_preview_safe, test_open_toutiao_creator_launches_shared_profile (+46) |
| `src/publish/delivery_state.py` | _from_record, _key, terminal_action_block_reason, _find, _transaction (+5) |
| `apps/web_gui.py` | dispatch, do_GET, do_OPTIONS, do_POST, do_PUT (+4) |
| `tests/test_cli_headless.py` | test_format_progress_event_labels_current_step, test_headless_option_value_for_explicit_flag, test_headless_option_value_preserves_env_fallback_when_flag_is_absent, test_format_stage_error_labels_news_failure, test_format_stage_error_labels_upload_failure (+2) |
| `src/publish/playwright_steps.py` | run_collect_published_metrics_sync, run_delete_drafts_sync, run_publish_drafts_sync, run_save_draft_sync, run_update_draft_sync (+1) |
| `tests/test_auto_guardrails.py` | test_default_upload_assets_use_frozen_post_manifest, test_explicit_upload_glob_overrides_frozen_post_manifest, test_cli_text_repair_restores_corrupted_daily_news_title, test_empty_assets_glob_is_an_auto_image_sentinel, test_run_record_captures_selected_volcengine_models (+1) |
| `tests/test_delivery_state.py` | test_pending_review_action_blocks_browser_write, test_platform_restriction_is_terminal_and_cannot_be_resubmitted, test_prepare_action_is_idempotent_and_unknown_requires_reconcile, test_record_observation_confirms_publication_without_allowing_resubmit, test_saved_draft_observation_is_a_confirmed_draft_stage (+1) |

## Entry Points

Start here when exploring this area:

- **`daily_global_map`** (Function) — `apps/cli.py:4127`
- **`delete_drafts`** (Function) — `apps/cli.py:5023`
- **`progress`** (Function) — `apps/cli.py:3365`
- **`upload`** (Function) — `apps/cli.py:3649`
- **`upload_batch`** (Function) — `apps/cli.py:3790`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `daily_global_map` | Function | `apps/cli.py` | 4127 |
| `delete_drafts` | Function | `apps/cli.py` | 5023 |
| `progress` | Function | `apps/cli.py` | 3365 |
| `upload` | Function | `apps/cli.py` | 3649 |
| `upload_batch` | Function | `apps/cli.py` | 3790 |
| `global_map` | Function | `apps/cli.py` | 4152 |
| `manage_drafts` | Function | `apps/cli.py` | 4710 |
| `publish_drafts` | Function | `apps/cli.py` | 4873 |
| `run` | Function | `apps/cli.py` | 2322 |
| `update_draft` | Function | `apps/cli.py` | 2473 |
| `update_metrics` | Function | `apps/cli.py` | 4587 |
| `main` | Function | `scripts/_delete_old_drafts.py` | 33 |
| `xhs_upload_slot` | Function | `src/publish/concurrency.py` | 16 |
| `terminal_action_block_reason` | Function | `src/publish/delivery_state.py` | 60 |
| `run_collect_published_metrics_sync` | Function | `src/publish/playwright_steps.py` | 4723 |
| `run_delete_drafts_sync` | Function | `src/publish/playwright_steps.py` | 4541 |
| `run_publish_drafts_sync` | Function | `src/publish/playwright_steps.py` | 3655 |
| `run_save_draft_sync` | Function | `src/publish/playwright_steps.py` | 4098 |
| `run_update_draft_sync` | Function | `src/publish/playwright_steps.py` | 4315 |
| `test_default_upload_assets_use_frozen_post_manifest` | Function | `tests/test_auto_guardrails.py` | 19 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Create_daily_wool_posts → _normalize_token` | cross_community | 9 |
| `Post_quality_callback → _news_metadata` | cross_community | 7 |
| `Daily_global_map → _is_current` | cross_community | 7 |
| `Daily_global_map → _normalise_key` | cross_community | 7 |
| `Daily_global_map → Verified_location` | cross_community | 7 |
| `Daily_global_map → _normalise_text` | cross_community | 7 |
| `Generate → Canonical_volcengine_model` | cross_community | 7 |
| `Drain → _quota_selectable_kind` | cross_community | 7 |
| `Drain → _quota_dashboard_default_sort_key` | cross_community | 7 |
| `Execute_agent_plan → _strip_quotes` | cross_community | 7 |

## How to Explore

1. `context({name: "daily_global_map"})` — see callers and callees
2. `query({search_query: "apps"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
