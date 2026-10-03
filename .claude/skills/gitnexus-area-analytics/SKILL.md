---
name: gitnexus-area-analytics
description: "Skill for the Analytics area of auto_redbook. 28 symbols across 6 files."
---

# Analytics

28 symbols | 6 files | Cohesion: 73%

## When to Use

- Working with code in `src/`
- Understanding how find_post_for_published_metric, normalize_metric_title, normalize_metric_url work
- Modifying analytics-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/analytics/published_metrics.py` | _build_category_summaries, _category_score, _date_range, _days_old, _signal_level (+10) |
| `src/analytics/post_sync.py` | _as_dict, _find_post_in_published_indexes, _metric_url, _post_title_candidates, _post_url_candidates (+4) |
| `apps/gui.py` | _find_local_post |
| `apps/cli.py` | sync_context |
| `src/knowledge/service.py` | knowledge_context |
| `tests/test_agent_knowledge.py` | test_knowledge_context_degrades_without_database |

## Entry Points

Start here when exploring this area:

- **`find_post_for_published_metric`** (Function) — `src/analytics/post_sync.py:126`
- **`normalize_metric_title`** (Function) — `src/analytics/post_sync.py:11`
- **`normalize_metric_url`** (Function) — `src/analytics/post_sync.py:15`
- **`sync_context`** (Function) — `apps/cli.py:3368`
- **`analyze_published_metrics`** (Function) — `src/analytics/published_metrics.py:470`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `find_post_for_published_metric` | Function | `src/analytics/post_sync.py` | 126 |
| `normalize_metric_title` | Function | `src/analytics/post_sync.py` | 11 |
| `normalize_metric_url` | Function | `src/analytics/post_sync.py` | 15 |
| `sync_context` | Function | `apps/cli.py` | 3368 |
| `analyze_published_metrics` | Function | `src/analytics/published_metrics.py` | 470 |
| `knowledge_context` | Function | `src/knowledge/service.py` | 28 |
| `test_knowledge_context_degrades_without_database` | Function | `tests/test_agent_knowledge.py` | 5 |
| `load_analyzed_metrics` | Function | `src/analytics/published_metrics.py` | 307 |
| `_find_local_post` | Function | `apps/gui.py` | 5503 |
| `_as_dict` | Function | `src/analytics/post_sync.py` | 27 |
| `_find_post_in_published_indexes` | Function | `src/analytics/post_sync.py` | 105 |
| `_metric_url` | Function | `src/analytics/post_sync.py` | 49 |
| `_post_title_candidates` | Function | `src/analytics/post_sync.py` | 71 |
| `_post_url_candidates` | Function | `src/analytics/post_sync.py` | 53 |
| `_published_post_match_indexes` | Function | `src/analytics/post_sync.py` | 91 |
| `_build_category_summaries` | Function | `src/analytics/published_metrics.py` | 355 |
| `_category_score` | Function | `src/analytics/published_metrics.py` | 348 |
| `_date_range` | Function | `src/analytics/published_metrics.py` | 335 |
| `_days_old` | Function | `src/analytics/published_metrics.py` | 340 |
| `_signal_level` | Function | `src/analytics/published_metrics.py` | 461 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Analyze_metrics → _ratio_cap` | cross_community | 5 |
| `Analyze_metrics → Published_metrics_paths` | cross_community | 5 |
| `Sync_context → _ratio_cap` | cross_community | 5 |
| `Sync_context → Published_metrics_paths` | cross_community | 5 |
| `Analyze_metrics → _category_score` | cross_community | 4 |
| `Analyze_metrics → _recommendation_reason` | cross_community | 4 |
| `Analyze_metrics → _category_for_title` | cross_community | 4 |
| `Analyze_metrics → _raw_dict` | cross_community | 4 |
| `Analyze_metrics → _to_int` | cross_community | 4 |
| `Sync_published_metrics_to_posts → Normalize_metric_title` | cross_community | 4 |

## How to Explore

1. `context({name: "find_post_for_published_metric"})` — see callers and callees
2. `query({search_query: "analytics"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
