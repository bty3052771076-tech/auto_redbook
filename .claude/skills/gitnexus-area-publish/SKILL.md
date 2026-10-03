---
name: gitnexus-area-publish
description: "Skill for the Publish area of auto_redbook. 331 symbols across 22 files."
---

# Publish

331 symbols | 22 files | Cohesion: 77%

## When to Use

- Working with code in `src/`
- Understanding how inspection_completeness, run_inspect_platform_drafts_sync, save_event work
- Modifying publish-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/publish/playwright_steps.py` | _assert_xhs_operable, _capture_publication_failure_evidence, _classify_write_failure, _click_publish_button, _collect_draft_items (+123) |
| `src/publish/toutiao_steps.py` | ToutiaoDraftVerification, _emit_progress, _ensure_toutiao_device_verified, _open_toutiao_publish_page, _resolve_toutiao_sms_wait_seconds (+44) |
| `tests/test_toutiao_publish.py` | test_toutiao_cdp_sms_challenge_gets_a_default_manual_wait, test_toutiao_device_check_does_not_block_on_stale_phone_permission_flag, test_toutiao_draft_verification_reports_each_failed_field, test_toutiao_runner_does_not_close_a_user_managed_cdp_browser, test_toutiao_runner_reports_official_sms_requirement_in_headless_mode (+19) |
| `src/publish/draft_management.py` | inspection_completeness, build_action_plan, rank_reviews, review_snapshot, load_checkpoint (+18) |
| `tests/test_published_metrics.py` | test_parse_published_total_text, test_published_metrics_default_routes_exclude_legacy_and_editor_pages, test_published_metrics_default_scroll_budget_supports_large_creator_accounts, test_published_metrics_defaults_prefer_current_note_manager_route, test_published_metrics_operation_timeout_caps_each_dom_operation (+11) |
| `tests/test_playwright_draft_button.py` | test_draft_item_matches_post_uses_specific_local_title, test_draft_title_match_requires_specific_title_not_generic_prefix, test_open_draft_editor_for_titles_falls_back_to_current_title, test_read_editor_draft_snapshot_returns_actual_title_and_body, test_open_draft_list_and_check_saved_reopens_publish_page_when_inline_box_missing (+10) |
| `tests/test_draft_management.py` | test_inspection_completeness_distinguishes_limited_detail_scan, _snapshot, test_action_plan_rejects_action_outside_authorization, test_rank_and_action_plan_respect_limit_and_authorization, test_review_blocks_ambiguous_platform_identity_from_publish (+6) |
| `tests/test_playwright_profile_config.py` | test_context_default_timeout_follows_wait_timeout, test_custom_profile_keeps_system_chrome_channel_by_default, test_format_progress_message_includes_detail, test_resolve_headless_accepts_env_flag, test_resolve_headless_argument_overrides_env (+6) |
| `src/publish/mcp_steps.py` | _extract_pages, _get_tool, _js_escape, _parse_uid, _pick_page_idx (+3) |
| `tests/test_draft_delivery.py` | test_failure_before_click_remains_a_definite_automation_error, test_publication_failure_evidence_is_written_under_post_evidence, test_write_failure_after_click_is_classified_as_uncertain, test_content_revision_fingerprint_ignores_post_id_and_timestamps, test_current_draft_receipt_is_false_for_missing_or_changed_revision (+2) |

## Entry Points

Start here when exploring this area:

- **`inspection_completeness`** (Function) — `src/publish/draft_management.py:23`
- **`run_inspect_platform_drafts_sync`** (Function) — `src/publish/playwright_steps.py:2930`
- **`save_event`** (Function) — `src/storage/events.py:12`
- **`test_failure_before_click_remains_a_definite_automation_error`** (Function) — `tests/test_draft_delivery.py:84`
- **`test_publication_failure_evidence_is_written_under_post_evidence`** (Function) — `tests/test_draft_delivery.py:94`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `ToutiaoDraftVerification` | Class | `src/publish/toutiao_steps.py` | 72 |
| `PlatformRiskError` | Class | `src/publish/platform_guard.py` | 11 |
| `PlatformStateError` | Class | `src/publish/platform_state.py` | 21 |
| `inspection_completeness` | Function | `src/publish/draft_management.py` | 23 |
| `run_inspect_platform_drafts_sync` | Function | `src/publish/playwright_steps.py` | 2930 |
| `save_event` | Function | `src/storage/events.py` | 12 |
| `test_failure_before_click_remains_a_definite_automation_error` | Function | `tests/test_draft_delivery.py` | 84 |
| `test_publication_failure_evidence_is_written_under_post_evidence` | Function | `tests/test_draft_delivery.py` | 94 |
| `test_write_failure_after_click_is_classified_as_uncertain` | Function | `tests/test_draft_delivery.py` | 73 |
| `test_inspection_completeness_distinguishes_limited_detail_scan` | Function | `tests/test_draft_management.py` | 162 |
| `test_draft_item_matches_post_uses_specific_local_title` | Function | `tests/test_playwright_draft_button.py` | 361 |
| `test_draft_title_match_requires_specific_title_not_generic_prefix` | Function | `tests/test_playwright_draft_button.py` | 355 |
| `test_open_draft_editor_for_titles_falls_back_to_current_title` | Function | `tests/test_playwright_draft_button.py` | 369 |
| `test_read_editor_draft_snapshot_returns_actual_title_and_body` | Function | `tests/test_playwright_draft_button.py` | 392 |
| `test_context_default_timeout_follows_wait_timeout` | Function | `tests/test_playwright_profile_config.py` | 59 |
| `test_custom_profile_keeps_system_chrome_channel_by_default` | Function | `tests/test_playwright_profile_config.py` | 21 |
| `test_format_progress_message_includes_detail` | Function | `tests/test_playwright_profile_config.py` | 52 |
| `test_resolve_headless_accepts_env_flag` | Function | `tests/test_playwright_profile_config.py` | 40 |
| `test_resolve_headless_argument_overrides_env` | Function | `tests/test_playwright_profile_config.py` | 46 |
| `test_resolve_headless_defaults_to_visible_browser` | Function | `tests/test_playwright_profile_config.py` | 34 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Publish_drafts → _format_progress_message` | cross_community | 6 |
| `Publish_drafts → _env_flag` | cross_community | 6 |
| `Publish_drafts → _repo_root` | cross_community | 6 |
| `Run → _format_progress_message` | cross_community | 6 |
| `Publish_drafts → _resolve_cdp_url` | cross_community | 5 |
| `Update_metrics → _context_default_timeout_ms` | cross_community | 5 |
| `Main → _parse_time` | cross_community | 5 |
| `Run_save_draft_sync → _repo_root` | cross_community | 5 |
| `Delete_drafts → _env_flag` | cross_community | 5 |
| `Delete_drafts → _repo_root` | cross_community | 5 |

## How to Explore

1. `context({name: "inspection_completeness"})` — see callers and callees
2. `query({search_query: "publish"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
