---
name: gitnexus-area-global-map
description: "Skill for the Global_map area of auto_redbook. 31 symbols across 10 files."
---

# Global_map

31 symbols | 10 files | Cohesion: 76%

## When to Use

- Working with code in `src/`
- Understanding how build_global_map_preview, create_global_map_post_from_service, preview_global_map_from_service work
- Modifying global_map-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/global_map/basemap.py` | _project, _rings, draw_basemap, load_basemap, resolve_basemap_path (+2) |
| `src/global_map/workflow.py` | _bounded_body, _compact_text, create_global_map_post, render_snapshot, save_snapshot |
| `src/global_map/service.py` | _service_client_and_runtime, build_global_map_preview, create_global_map_post_from_service, preview_global_map_from_service |
| `tests/test_global_map_request.py` | test_global_map_preview_reports_coverage_without_creating_post, test_global_map_request_accepts_only_supported_delivery_and_map_modes, test_global_map_request_freezes_scope_and_rejects_multiple_posts |
| `src/global_map/models.py` | from_mapping, to_dict, to_dict |
| `src/global_map/render.py` | _font, _wrap, render_global_map |
| `src/global_map/geography.py` | _normalise_text, resolve_explicit_country_location |
| `tests/test_global_map_country_resolution.py` | test_ambiguous_multi_country_text_is_not_mapped_to_an_arbitrary_country, test_explicit_country_name_resolves_to_country_level_label_only |
| `apps/web_service.py` | global_map_preview |
| `src/global_map/editorial.py` | build_global_map_editorial |

## Entry Points

Start here when exploring this area:

- **`build_global_map_preview`** (Function) — `src/global_map/service.py:26`
- **`create_global_map_post_from_service`** (Function) — `src/global_map/service.py:67`
- **`preview_global_map_from_service`** (Function) — `src/global_map/service.py:62`
- **`test_global_map_preview_reports_coverage_without_creating_post`** (Function) — `tests/test_global_map_request.py:37`
- **`test_global_map_request_accepts_only_supported_delivery_and_map_modes`** (Function) — `tests/test_global_map_request.py:30`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `build_global_map_preview` | Function | `src/global_map/service.py` | 26 |
| `create_global_map_post_from_service` | Function | `src/global_map/service.py` | 67 |
| `preview_global_map_from_service` | Function | `src/global_map/service.py` | 62 |
| `test_global_map_preview_reports_coverage_without_creating_post` | Function | `tests/test_global_map_request.py` | 37 |
| `test_global_map_request_accepts_only_supported_delivery_and_map_modes` | Function | `tests/test_global_map_request.py` | 30 |
| `test_global_map_request_freezes_scope_and_rejects_multiple_posts` | Function | `tests/test_global_map_request.py` | 10 |
| `draw_basemap` | Function | `src/global_map/basemap.py` | 104 |
| `load_basemap` | Function | `src/global_map/basemap.py` | 56 |
| `resolve_basemap_path` | Function | `src/global_map/basemap.py` | 36 |
| `validate_map_artifact` | Function | `src/global_map/basemap.py` | 146 |
| `render_global_map` | Function | `src/global_map/render.py` | 39 |
| `build_global_map_editorial` | Function | `src/global_map/editorial.py` | 5 |
| `create_global_map_post` | Function | `src/global_map/workflow.py` | 85 |
| `render_snapshot` | Function | `src/global_map/workflow.py` | 81 |
| `save_snapshot` | Function | `src/global_map/workflow.py` | 75 |
| `resolve_explicit_country_location` | Function | `src/global_map/geography.py` | 55 |
| `test_ambiguous_multi_country_text_is_not_mapped_to_an_arbitrary_country` | Function | `tests/test_global_map_country_resolution.py` | 49 |
| `test_explicit_country_name_resolves_to_country_level_label_only` | Function | `tests/test_global_map_country_resolution.py` | 9 |
| `global_map_preview` | Method | `apps/web_service.py` | 881 |
| `from_mapping` | Method | `src/global_map/models.py` | 44 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Daily_global_map → _is_current` | cross_community | 7 |
| `Daily_global_map → _normalise_key` | cross_community | 7 |
| `Daily_global_map → Verified_location` | cross_community | 7 |
| `Daily_global_map → _normalise_text` | cross_community | 7 |
| `Global_map → _is_current` | cross_community | 7 |
| `Global_map → _normalise_key` | cross_community | 7 |
| `Global_map → Verified_location` | cross_community | 7 |
| `Global_map → _normalise_text` | cross_community | 7 |
| `Daily_global_map → _authority` | cross_community | 6 |
| `Global_map_preview → Score_event` | cross_community | 6 |

## How to Explore

1. `context({name: "build_global_map_preview"})` — see callers and callees
2. `query({search_query: "global_map"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
