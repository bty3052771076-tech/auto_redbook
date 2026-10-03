---
name: gitnexus-area-ai-digest
description: "Skill for the Ai_digest area of auto_redbook. 219 symbols across 19 files."
---

# Ai_digest

219 symbols | 19 files | Cohesion: 66%

## When to Use

- Working with code in `src/`
- Understanding how parse_aihot_daily_html, test_parse_aihot_daily_html_maps_traceable_digest_items, test_parse_aihot_daily_html_merges_rendered_detail_href_with_structured_entry work
- Modifying ai_digest-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/ai_digest/rank.py` | _model_family_topic_key, _model_history_topic_key, _normalize_token, _product_topic_key, _semantic_topic_key (+47) |
| `src/ai_digest/generate.py` | _clean_subject, _detail_terms_from_item, _english_fact_fallback_summary, _english_fact_fallback_title, _english_fact_vendor (+46) |
| `src/ai_digest/fetchers.py` | _aihot_external_url, _aihot_rendered_detail_hrefs, _aihot_structured_entries, _aihot_vendor, _decode_embedded_json_string (+23) |
| `src/ai_digest/collect.py` | _aihot_detail_external_url, _is_aihot_detail_url, _matches_vendor_official_host, load_ai_digest_research_items, resolve_aihot_detail_source (+23) |
| `src/ai_digest/render.py` | _cover_title_parts, _featured_item, _font, _format_published_at, _new_card (+9) |
| `tests/test_ai_digest_sources.py` | test_parse_aihot_daily_html_maps_traceable_digest_items, test_parse_aihot_daily_html_merges_rendered_detail_href_with_structured_entry, test_parse_aihot_daily_html_promotes_embedded_official_url_to_primary_link, test_parse_aihot_next_payload_keeps_detail_page_url_for_source_resolution, test_parse_aihot_next_payload_keeps_each_title_summary_and_source_together (+7) |
| `tests/test_ai_digest_generate.py` | test_restore_traceable_items_dedupes_same_event_across_social_urls, test_restore_traceable_items_keeps_valid_model_title_when_fallback_is_empty, test_validate_ai_digest_concrete_content_rejects_vague_change_summary, test_evaluate_ai_digest_impact_with_llm_blends_valid_scores, test_evaluate_ai_digest_impact_with_llm_falls_back_to_deterministic_scores (+2) |
| `src/ai_digest/models.py` | strip_html_artifacts, _strip_text, _normalize_title_key, title_key, _normalize_url (+1) |
| `src/workflow/create_post.py` | _compact_ai_digest_subject, _is_meaningful, _norm_label, _trim_dangling_ai_digest_tail, prepare |
| `tests/test_ai_digest.py` | test_non_model_database_api_notice_is_not_relevant_for_digest_ranking, test_source_key_normalizes_display_suffixes_and_falls_back_to_url_host, test_ai_update_category_does_not_treat_financial_valuation_model_as_ai_release, test_ai_update_is_model_news_rejects_database_infrastructure_update |

## Entry Points

Start here when exploring this area:

- **`parse_aihot_daily_html`** (Function) — `src/ai_digest/fetchers.py:1008`
- **`test_parse_aihot_daily_html_maps_traceable_digest_items`** (Function) — `tests/test_ai_digest_sources.py:330`
- **`test_parse_aihot_daily_html_merges_rendered_detail_href_with_structured_entry`** (Function) — `tests/test_ai_digest_sources.py:438`
- **`test_parse_aihot_daily_html_promotes_embedded_official_url_to_primary_link`** (Function) — `tests/test_ai_digest_sources.py:364`
- **`test_parse_aihot_next_payload_keeps_detail_page_url_for_source_resolution`** (Function) — `tests/test_ai_digest_sources.py:418`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `parse_aihot_daily_html` | Function | `src/ai_digest/fetchers.py` | 1008 |
| `test_parse_aihot_daily_html_maps_traceable_digest_items` | Function | `tests/test_ai_digest_sources.py` | 330 |
| `test_parse_aihot_daily_html_merges_rendered_detail_href_with_structured_entry` | Function | `tests/test_ai_digest_sources.py` | 438 |
| `test_parse_aihot_daily_html_promotes_embedded_official_url_to_primary_link` | Function | `tests/test_ai_digest_sources.py` | 364 |
| `test_parse_aihot_next_payload_keeps_detail_page_url_for_source_resolution` | Function | `tests/test_ai_digest_sources.py` | 418 |
| `test_parse_aihot_next_payload_keeps_each_title_summary_and_source_together` | Function | `tests/test_ai_digest_sources.py` | 387 |
| `cap_ai_digest_items_by_source` | Function | `src/ai_digest/generate.py` | 150 |
| `test_restore_traceable_items_dedupes_same_event_across_social_urls` | Function | `tests/test_ai_digest_generate.py` | 1904 |
| `test_restore_traceable_items_keeps_valid_model_title_when_fallback_is_empty` | Function | `tests/test_ai_digest_generate.py` | 1954 |
| `ai_update_is_non_model_infrastructure_notice` | Function | `src/ai_digest/rank.py` | 1022 |
| `ai_update_is_relevant` | Function | `src/ai_digest/rank.py` | 1114 |
| `test_non_model_database_api_notice_is_not_relevant_for_digest_ranking` | Function | `tests/test_ai_digest.py` | 121 |
| `source_key` | Function | `src/ai_digest/rank.py` | 1551 |
| `can_add` | Function | `src/ai_digest/rank.py` | 1612 |
| `ensure_quota` | Function | `src/ai_digest/rank.py` | 1618 |
| `ai_update_source_key` | Function | `src/ai_digest/rank.py` | 1407 |
| `test_source_key_normalizes_display_suffixes_and_falls_back_to_url_host` | Function | `tests/test_ai_digest.py` | 353 |
| `load_ai_digest_research_items` | Function | `src/ai_digest/collect.py` | 335 |
| `resolve_aihot_detail_source` | Function | `src/ai_digest/collect.py` | 351 |
| `test_research_material_requires_real_official_host` | Function | `tests/test_ai_digest_release_first.py` | 89 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Ensure_quota → _normalize_token` | cross_community | 10 |
| `Create_daily_wool_posts → _normalize_token` | cross_community | 9 |
| `Ai_digest_item_is_current → _normalize_token` | cross_community | 9 |
| `Ensure_quota → _url_topic_text` | cross_community | 8 |
| `Ai_digest_item_is_current → _url_topic_text` | cross_community | 8 |
| `Evaluate_ai_digest_impact_with_llm → _normalize_token` | cross_community | 8 |
| `_rank_sort_key → _normalize_token` | cross_community | 7 |
| `Ensure_quota → _source_blob` | cross_community | 6 |
| `Create_daily_wool_posts → _parse_published_datetime` | cross_community | 6 |
| `Fetch_one → _strings` | cross_community | 6 |

## How to Explore

1. `context({name: "parse_aihot_daily_html"})` — see callers and callees
2. `query({search_query: "ai_digest"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
