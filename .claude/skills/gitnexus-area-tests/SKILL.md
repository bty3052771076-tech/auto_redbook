---
name: gitnexus-area-tests
description: "Skill for the Tests area of auto_redbook. 1054 symbols across 94 files."
---

# Tests

1054 symbols | 94 files | Cohesion: 70%

## When to Use

- Working with code in `tests/`
- Understanding how fetch_daily_news_candidates, cache_key, source_snapshot_items work
- Modifying tests-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `tests/test_daily_news.py` | test_auto_plan_includes_configured_additional_news_providers, item, test_daily_news_health_marks_undated_provider_result_as_missing_date, test_fetch_daily_news_candidates_auto_aggregates_fallback_sources_until_raw_target, item (+221) |
| `src/workflow/create_post.py` | _append_news_source_line, _finalize_daily_news_body, _news_source_line, _daily_news_conflict_signal, _prioritize_all_daily_news_conflicts (+68) |
| `tests/test_ai_digest_workflow.py` | _updates, test_ai_digest_prompt_search_queries_include_claude_fable_release, test_create_daily_ai_digest_allows_traceable_backfill_when_official_target_is_unmet, test_create_daily_ai_digest_fails_when_history_blocks_quota, test_create_daily_ai_digest_fallback_selects_quotas_from_full_pool (+59) |
| `tests/test_ai_digest_generate.py` | test_ensure_chinese_item_converts_common_traditional_source_title, test_ensure_chinese_item_does_not_keep_a_social_url_fragment_as_title, test_ensure_chinese_item_gives_hy4_search_result_a_complete_release_title, test_ensure_chinese_item_is_idempotent_for_repaired_mixed_language_titles, test_ensure_chinese_item_repairs_title_cut_inside_summary_lead (+51) |
| `tests/test_ai_digest.py` | _item, test_ai_update_item_normalizes_url_key_and_source_type, test_ai_update_quality_rejects_disclosure_related_content_title, test_ai_update_quality_rejects_disclosure_title_without_concrete_object, test_filter_recent_ai_updates_uses_explicit_model_event_date_from_excerpt (+50) |
| `tests/test_gui.py` | test_build_cli_args_aliyun_quota, test_build_cli_args_approve, test_build_cli_args_auto, test_build_cli_args_auto_aliyun_image_source_ignores_local_assets, test_build_cli_args_auto_daily_ai_digest_keeps_special_title (+31) |
| `tests/test_ai_digest_collect.py` | test_collect_ai_digest_can_force_social_backfill_for_short_lived_benefits, test_collect_ai_digest_does_not_fetch_official_pages_when_streams_fill_the_pool, test_collect_ai_digest_fetches_official_streams_before_pages, test_collect_ai_digest_fetches_same_stage_sources_concurrently_when_requested, test_collect_ai_digest_fills_requested_candidate_pool_before_stopping_sources (+31) |
| `src/news/daily_news.py` | _google_news_rss_base_url, _google_rss_fetch_articles, _hotnews_base_url, _news_health_timestamp, _news_provider_health_tier (+19) |
| `tests/test_web_gui.py` | creation, snapshot, test_agent_plan_passes_independent_role_models, test_auto_does_not_refresh_quotas_or_allow_paid, test_empty_latest_snapshot_does_not_revive_old (+16) |
| `tests/test_vision_review.py` | _post_with_image, test_review_post_image_rejects_inconsistent_result, test_review_post_image_sends_title_body_viewpoint_and_image, test_visual_news_replenishment_fills_gap_after_initial_review, generate_more (+15) |

## Entry Points

Start here when exploring this area:

- **`fetch_daily_news_candidates`** (Function) — `src/news/daily_news.py:3778`
- **`cache_key`** (Function) — `src/news/daily_news.py:4127`
- **`source_snapshot_items`** (Function) — `src/sources/service.py:407`
- **`test_auto_plan_includes_configured_additional_news_providers`** (Function) — `tests/test_daily_news.py:5083`
- **`item`** (Function) — `tests/test_daily_news.py:5097`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `AdditionalNewsSourcesConfig` | Class | `src/news/daily_news.py` | 461 |
| `CloseLocator` | Class | `tests/test_toutiao_publish.py` | 173 |
| `ConfirmLocator` | Class | `tests/test_toutiao_publish.py` | 189 |
| `DrawerLocator` | Class | `tests/test_toutiao_publish.py` | 159 |
| `InputLocator` | Class | `tests/test_toutiao_publish.py` | 185 |
| `ToolLocator` | Class | `tests/test_toutiao_publish.py` | 177 |
| `fetch_daily_news_candidates` | Function | `src/news/daily_news.py` | 3778 |
| `cache_key` | Function | `src/news/daily_news.py` | 4127 |
| `source_snapshot_items` | Function | `src/sources/service.py` | 407 |
| `test_auto_plan_includes_configured_additional_news_providers` | Function | `tests/test_daily_news.py` | 5083 |
| `item` | Function | `tests/test_daily_news.py` | 5097 |
| `test_daily_news_health_marks_undated_provider_result_as_missing_date` | Function | `tests/test_daily_news.py` | 392 |
| `test_fetch_daily_news_candidates_auto_aggregates_fallback_sources_until_raw_target` | Function | `tests/test_daily_news.py` | 4411 |
| `item` | Function | `tests/test_daily_news.py` | 4428 |
| `test_fetch_daily_news_candidates_auto_does_not_fallback_to_gdelt` | Function | `tests/test_daily_news.py` | 4532 |
| `test_fetch_daily_news_candidates_auto_tries_configured_gnews_when_newsapi_times_out` | Function | `tests/test_daily_news.py` | 4141 |
| `test_fetch_daily_news_candidates_auto_uses_gnews_when_newsapi_missing` | Function | `tests/test_daily_news.py` | 4916 |
| `test_fetch_daily_news_candidates_auto_uses_google_rss_before_hotnews_when_keyed_provider_fails` | Function | `tests/test_daily_news.py` | 4177 |
| `test_fetch_daily_news_candidates_auto_uses_hotnews_after_keyed_provider_failure` | Function | `tests/test_daily_news.py` | 4370 |
| `test_fetch_daily_news_candidates_auto_uses_hotnews_when_no_keyed_provider` | Function | `tests/test_daily_news.py` | 4323 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Ensure_quota → _normalize_token` | cross_community | 10 |
| `Create_daily_wool_posts → _normalize_token` | cross_community | 9 |
| `Ai_digest_item_is_current → _normalize_token` | cross_community | 9 |
| `Ensure_quota → _url_topic_text` | cross_community | 8 |
| `Ai_digest_item_is_current → _url_topic_text` | cross_community | 8 |
| `Evaluate_ai_digest_impact_with_llm → _normalize_token` | cross_community | 8 |
| `Post_quality_callback → _news_metadata` | cross_community | 7 |
| `Daily_global_map → _is_current` | cross_community | 7 |
| `Daily_global_map → _normalise_key` | cross_community | 7 |
| `Daily_global_map → Verified_location` | cross_community | 7 |

## How to Explore

1. `context({name: "fetch_daily_news_candidates"})` — see callers and callees
2. `query({search_query: "tests"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
