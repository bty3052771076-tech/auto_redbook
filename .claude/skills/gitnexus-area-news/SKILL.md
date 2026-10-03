---
name: gitnexus-area-news
description: "Skill for the News area of auto_redbook. 168 symbols across 9 files."
---

# News

168 symbols | 9 files | Cohesion: 62%

## When to Use

- Working with code in `src/`
- Understanding how test_additional_news_provider_response_mapping, test_exhaustive_collection_uses_bounded_provider_timeouts, test_required_queries_survive_limit_and_record_target work
- Modifying news-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/news/daily_news.py` | _alphavantage_fetch_articles, _alphavantage_topics_for_query, _compact_api_datetime, _external_domain, _external_text (+102) |
| `tests/test_daily_news.py` | test_additional_news_provider_response_mapping, test_exhaustive_collection_uses_bounded_provider_timeouts, test_load_manual_news_materials_file_reads_json_aliases, test_load_manual_news_materials_file_reads_jsonl, test_load_single_news_material_file_requires_exactly_one_item (+21) |
| `src/news/daily_wow.py` | _item_text, daily_wow_candidate_pool, daily_wow_contrast_signal, daily_wow_score, daily_wow_eligible (+5) |
| `tests/test_daily_wow.py` | test_candidate_pool_keeps_date_valid_items_for_model_and_drops_only_fiction, test_conflict_and_disaster_stories_are_hard_rejected, test_odd_beat_source_outranks_generic_headline, test_eligible_requires_a_contrast_signal_or_user_keyword, test_offline_strict_fallback_requires_a_contrast_signal (+3) |
| `src/workflow/news_discovery.py` | news_domain, source_domain_cap, _pool, _valid_time, __init__ (+2) |
| `tests/test_news_quota_repair.py` | test_required_queries_survive_limit_and_record_target, test_conflict_actions_are_recognized, test_non_conflict_headlines_are_excluded, test_bbc_mixed_prompt_preserves_world_and_interleaves |
| `src/news/history.py` | _news_urls_from_post_data, collect_used_news_url_keys, filter_used_news_items, normalize_news_url_key |
| `tests/test_news_discovery.py` | test_daily_news_category_mix_is_soft_only_when_agent_policy_is_enabled |
| `src/workflow/create_post.py` | _daily_wow_image_prompt_for_post |

## Entry Points

Start here when exploring this area:

- **`test_additional_news_provider_response_mapping`** (Function) — `tests/test_daily_news.py:4964`
- **`test_exhaustive_collection_uses_bounded_provider_timeouts`** (Function) — `tests/test_daily_news.py:4807`
- **`test_required_queries_survive_limit_and_record_target`** (Function) — `tests/test_news_quota_repair.py:30`
- **`load_manual_news_materials_file`** (Function) — `src/news/daily_news.py:3323`
- **`load_single_news_material_file`** (Function) — `src/news/daily_news.py:3346`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `test_additional_news_provider_response_mapping` | Function | `tests/test_daily_news.py` | 4964 |
| `test_exhaustive_collection_uses_bounded_provider_timeouts` | Function | `tests/test_daily_news.py` | 4807 |
| `test_required_queries_survive_limit_and_record_target` | Function | `tests/test_news_quota_repair.py` | 30 |
| `load_manual_news_materials_file` | Function | `src/news/daily_news.py` | 3323 |
| `load_single_news_material_file` | Function | `src/news/daily_news.py` | 3346 |
| `parse_manual_news_materials` | Function | `src/news/daily_news.py` | 3294 |
| `test_load_manual_news_materials_file_reads_json_aliases` | Function | `tests/test_daily_news.py` | 5189 |
| `test_load_manual_news_materials_file_reads_jsonl` | Function | `tests/test_daily_news.py` | 5217 |
| `test_load_single_news_material_file_requires_exactly_one_item` | Function | `tests/test_daily_news.py` | 5234 |
| `test_parse_manual_news_materials_reads_markdown_blocks` | Function | `tests/test_daily_news.py` | 5159 |
| `news_domain` | Function | `src/workflow/news_discovery.py` | 85 |
| `source_domain_cap` | Function | `src/workflow/news_discovery.py` | 89 |
| `test_balanced_candidate_pool_keeps_later_provider_and_domain_diversity` | Function | `tests/test_daily_news.py` | 5056 |
| `test_daily_news_rejects_chinese_multi_story_roundup_before_generation` | Function | `tests/test_daily_news.py` | 1008 |
| `test_daily_news_rejects_stock_quote_page_before_generation` | Function | `tests/test_daily_news.py` | 1021 |
| `filter_recent_news_items` | Function | `src/news/daily_news.py` | 1191 |
| `resolve_manual_material_times` | Function | `src/news/daily_news.py` | 1136 |
| `test_juhe_candidate_pool_skips_per_article_detail_requests` | Function | `tests/test_daily_news.py` | 4770 |
| `test_daily_news_query_variants_expand_space_separated_prompt_keywords` | Function | `tests/test_daily_news.py` | 76 |
| `test_daily_news_required_queries_are_sent_before_keyword_variants` | Function | `tests/test_daily_news.py` | 86 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `_run_parallel_daily_news_candidates → _resolve_tz` | cross_community | 6 |
| `_run_parallel_daily_news_candidates → _item_text` | cross_community | 6 |
| `_run_parallel_daily_news_candidates → Daily_wow_is_political_statement` | cross_community | 6 |
| `Take → Contains_marker` | cross_community | 6 |
| `_run_parallel_daily_news_candidates → Normalize_news_url_key` | cross_community | 5 |
| `_run_parallel_daily_news_candidates → _parse_seendate_utc` | cross_community | 5 |
| `_fetch_news_provider → _numeric_value` | intra_community | 4 |
| `Fetch_and_pick_daily_news → _domain_for_item` | cross_community | 4 |
| `Fetch_and_pick_daily_news → _title_similar` | cross_community | 4 |
| `Fetch_and_pick_daily_news → _tokens` | cross_community | 4 |

## How to Explore

1. `context({name: "test_additional_news_provider_response_mapping"})` — see callers and callees
2. `query({search_query: "news"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
