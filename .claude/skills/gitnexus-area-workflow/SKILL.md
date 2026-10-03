---
name: gitnexus-area-workflow
description: "Skill for the Workflow area of auto_redbook. 305 symbols across 29 files."
---

# Workflow

305 symbols | 29 files | Cohesion: 66%

## When to Use

- Working with code in `src/`
- Understanding how key, render, test_clean_original_news_text_removes_browser_and_navigation_noise work
- Modifying workflow-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/workflow/create_post.py` | _cjk_count, _clean_daily_news_comment_value, _clean_daily_news_json_value, _clean_daily_news_text_value, _clean_daily_news_title_candidate (+143) |
| `src/workflow/pipeline.py` | _choose_image, _choose_llm, _choose_vision, _explicit_rank, _llm_selection_reason (+17) |
| `tests/test_daily_news.py` | test_clean_original_news_text_removes_browser_and_navigation_noise, test_daily_news_rejects_bay_area_comment_for_sports_plan, test_daily_news_rejects_weather_comment_for_non_weather_story, test_render_daily_news_body_fields_omits_original_title_from_publishable_body, test_repair_daily_news_mismatched_comment_uses_source_grounded_comment (+16) |
| `src/workflow/quality_gate.py` | _ai_digest_item_keys, _ai_digest_metadata, _daily_wool_event_keys, _daily_wool_metadata, _looks_like_recurring_source_title (+12) |
| `tests/test_daily_wow.py` | test_column_keeps_the_full_platform_title_budget, test_image_event_strips_model_narration_and_json_leak, test_placeholder_contrast_values_are_treated_as_absent, _wow_item, test_create_daily_wow_posts_skips_quota_and_uses_wow_prompt (+4) |
| `src/workflow/news_discovery.py` | news_key, _available, _column_fetch_kwargs, _next_window, emit (+4) |
| `src/workflow/model_queues.py` | submit_image, submit_llm, _cap_workers, _normalize_provider, infer_llm_provider (+3) |
| `src/workflow/content_evidence.py` | _item_key, _normalize_url, _parse_date, _published_beijing_date, ai_digest_item_is_current (+2) |
| `tests/test_ai_digest_workflow.py` | test_final_ai_digest_policy_drops_stale_items_before_publication, test_adaptive_selection_fails_when_only_historical_domestic_items_remain, test_adaptive_selection_never_reuses_historical_quota_candidates, test_ai_digest_prompt_matches_minimax_h3_max_fal_event_across_english_source_text, test_ai_digest_prompt_matches_openai_cursor_event_across_english_source_text (+2) |
| `tests/test_pipeline_preflight.py` | test_automatic_model_plan_skips_unverified_vision_display_alias, test_model_plan_never_adds_ppinfra_without_paid_opt_in, test_quota_unknown_blocks_automatic_model_selection, test_latest_snapshot_skips_newer_empty_sync_result, test_snapshot_freshness_uses_file_timestamp_when_payload_has_no_time (+1) |

## Entry Points

Start here when exploring this area:

- **`key`** (Function) — `src/workflow/create_post.py:2697`
- **`render`** (Function) — `src/workflow/create_post.py:3249`
- **`test_clean_original_news_text_removes_browser_and_navigation_noise`** (Function) — `tests/test_daily_news.py:2072`
- **`test_daily_news_rejects_bay_area_comment_for_sports_plan`** (Function) — `tests/test_daily_news.py:1290`
- **`test_daily_news_rejects_weather_comment_for_non_weather_story`** (Function) — `tests/test_daily_news.py:1273`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `key` | Function | `src/workflow/create_post.py` | 2697 |
| `render` | Function | `src/workflow/create_post.py` | 3249 |
| `test_clean_original_news_text_removes_browser_and_navigation_noise` | Function | `tests/test_daily_news.py` | 2072 |
| `test_daily_news_rejects_bay_area_comment_for_sports_plan` | Function | `tests/test_daily_news.py` | 1290 |
| `test_daily_news_rejects_weather_comment_for_non_weather_story` | Function | `tests/test_daily_news.py` | 1273 |
| `test_render_daily_news_body_fields_omits_original_title_from_publishable_body` | Function | `tests/test_daily_news.py` | 923 |
| `test_repair_daily_news_mismatched_comment_uses_source_grounded_comment` | Function | `tests/test_daily_news.py` | 6389 |
| `test_simplify_daily_news_draft_converts_common_taiwanese_source_characters` | Function | `tests/test_daily_news.py` | 1257 |
| `daily_wow_clean_image_event` | Function | `src/news/daily_wow.py` | 419 |
| `daily_wow_display_title` | Function | `src/news/daily_wow.py` | 377 |
| `daily_wow_title_max_len` | Function | `src/news/daily_wow.py` | 368 |
| `test_daily_news_body_has_prompt_leak_allows_publishable_body` | Function | `tests/test_daily_news.py` | 785 |
| `test_daily_news_body_has_prompt_leak_detects_echoed_prompt` | Function | `tests/test_daily_news.py` | 773 |
| `test_daily_news_candidate_result_keeps_prefetch_conflict_signal` | Function | `tests/test_daily_news.py` | 150 |
| `test_daily_news_generic_multi_item_title_is_rejected_after_llm_generation` | Function | `tests/test_daily_news.py` | 1002 |
| `test_column_keeps_the_full_platform_title_budget` | Function | `tests/test_daily_wow.py` | 356 |
| `test_image_event_strips_model_narration_and_json_leak` | Function | `tests/test_daily_wow.py` | 346 |
| `test_placeholder_contrast_values_are_treated_as_absent` | Function | `tests/test_daily_wow.py` | 483 |
| `test_ensure_news_publish_date_inserts_when_missing` | Function | `tests/test_image_event_hint.py` | 54 |
| `daily_wow_queries` | Function | `src/news/daily_wow.py` | 207 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Ai_digest_item_is_current → _normalize_token` | cross_community | 9 |
| `Ai_digest_item_is_current → _url_topic_text` | cross_community | 8 |
| `Post_quality_callback → _news_metadata` | cross_community | 7 |
| `Regenerate_daily_news_post_image → _english_keyword_hit` | cross_community | 7 |
| `Review → _news_metadata` | cross_community | 7 |
| `Review_more → _news_metadata` | cross_community | 7 |
| `Post_quality_callback → _normalized_url` | cross_community | 6 |
| `Post_quality_callback → _daily_wool_metadata` | cross_community | 6 |
| `Post_quality_callback → _parse_date` | cross_community | 6 |
| `_run_parallel_daily_news_candidates → _resolve_tz` | cross_community | 6 |

## How to Explore

1. `context({name: "key"})` — see callers and callees
2. `query({search_query: "workflow"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
