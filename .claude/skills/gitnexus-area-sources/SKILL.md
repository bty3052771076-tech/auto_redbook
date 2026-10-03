---
name: gitnexus-area-sources
description: "Skill for the Sources area of auto_redbook. 44 symbols across 11 files."
---

# Sources

44 symbols | 11 files | Cohesion: 79%

## When to Use

- Working with code in `src/`
- Understanding how report, test_registry_selects_by_source_pack, is_source_in_cooldown work
- Modifying sources-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/sources/service.py` | report, _article_key, _save_snapshot, _selected_specs, search (+9) |
| `src/sources/health.py` | _parse_datetime, _utc_now, is_source_in_cooldown, replacement_probe_due, load_source_health_snapshot (+2) |
| `tests/test_source_health.py` | test_source_health_marks_timeout_in_cooldown_until_expiry, test_source_health_replacement_becomes_half_open_after_probe_interval, test_stale_or_missing_date_source_is_cooled_down_briefly, test_successful_official_stream_is_not_cooled_down, test_source_health_snapshot_round_trips_without_workspace_global_state |
| `src/sources/models.py` | to_dict, to_dict, _strings, from_mapping |
| `src/sources/request_budget.py` | _lock_for, get, get_or_set, set |
| `tests/test_news_source_registry.py` | test_registry_selects_by_source_pack, test_registry_loads_reviewed_public_sources, test_registry_rejects_duplicate_ids_and_missing_endpoint |
| `src/sources/registry.py` | select, get, load |
| `tests/test_news_source_service.py` | test_parse_rss_and_atom_preserve_publisher_and_date |
| `tests/test_ai_digest_collect.py` | test_collect_ai_digest_skips_recent_timeout_and_persists_attempt_trace |
| `tests/test_daily_news.py` | test_daily_news_records_provider_health_trace_and_persists_snapshot |

## Entry Points

Start here when exploring this area:

- **`report`** (Function) — `src/sources/service.py:288`
- **`test_registry_selects_by_source_pack`** (Function) — `tests/test_news_source_registry.py:33`
- **`is_source_in_cooldown`** (Function) — `src/sources/health.py:124`
- **`replacement_probe_due`** (Function) — `src/sources/health.py:180`
- **`test_source_health_marks_timeout_in_cooldown_until_expiry`** (Function) — `tests/test_source_health.py:16`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `report` | Function | `src/sources/service.py` | 288 |
| `test_registry_selects_by_source_pack` | Function | `tests/test_news_source_registry.py` | 33 |
| `is_source_in_cooldown` | Function | `src/sources/health.py` | 124 |
| `replacement_probe_due` | Function | `src/sources/health.py` | 180 |
| `test_source_health_marks_timeout_in_cooldown_until_expiry` | Function | `tests/test_source_health.py` | 16 |
| `test_source_health_replacement_becomes_half_open_after_probe_interval` | Function | `tests/test_source_health.py` | 142 |
| `test_stale_or_missing_date_source_is_cooled_down_briefly` | Function | `tests/test_source_health.py` | 62 |
| `test_successful_official_stream_is_not_cooled_down` | Function | `tests/test_source_health.py` | 40 |
| `test_registry_loads_reviewed_public_sources` | Function | `tests/test_news_source_registry.py` | 10 |
| `test_registry_rejects_duplicate_ids_and_missing_endpoint` | Function | `tests/test_news_source_registry.py` | 20 |
| `test_parse_rss_and_atom_preserve_publisher_and_date` | Function | `tests/test_news_source_service.py` | 26 |
| `load_source_health_snapshot` | Function | `src/sources/health.py` | 212 |
| `test_collect_ai_digest_skips_recent_timeout_and_persists_attempt_trace` | Function | `tests/test_ai_digest_collect.py` | 235 |
| `test_daily_news_records_provider_health_trace_and_persists_snapshot` | Function | `tests/test_daily_news.py` | 350 |
| `test_source_health_snapshot_round_trips_without_workspace_global_state` | Function | `tests/test_source_health.py` | 85 |
| `parse_feed_bytes` | Function | `src/sources/service.py` | 102 |
| `test_ttl_cache_singleflight_and_expiry` | Function | `tests/test_speed_first_mode.py` | 75 |
| `legacy_task` | Function | `src/sources/service.py` | 292 |
| `get` | Function | `src/sources/service.py` | 154 |
| `to_dict` | Method | `src/sources/models.py` | 106 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Check_sources → _strings` | cross_community | 6 |
| `Check_sources → To_dict` | cross_community | 6 |
| `Fetch_one → _strings` | cross_community | 6 |
| `Fetch_one → To_dict` | cross_community | 6 |
| `Fetch_and_pick_daily_news → _strings` | cross_community | 6 |
| `Fetch_and_pick_daily_news → To_dict` | cross_community | 6 |
| `Check_sources → From_dict` | cross_community | 5 |
| `Check_sources → Select` | cross_community | 5 |
| `Fetch_one → From_dict` | cross_community | 5 |
| `Fetch_one → Select` | cross_community | 5 |

## How to Explore

1. `context({name: "report"})` — see callers and callees
2. `query({search_query: "sources"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
