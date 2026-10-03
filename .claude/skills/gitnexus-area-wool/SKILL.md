---
name: gitnexus-area-wool
description: "Skill for the Wool area of auto_redbook. 23 symbols across 6 files."
---

# Wool

23 symbols | 6 files | Cohesion: 68%

## When to Use

- Working with code in `src/`
- Understanding how contains_recoverable_utf8_as_gbk_mojibake, repair_utf8_as_gbk_mojibake, test_repair_utf8_as_gbk_mojibake_handles_one_and_two_passes work
- Modifying wool-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/wool/collect.py` | _event_key, _normalized_benefit_amounts, _normalized_benefit_dates, _provider, _published_datetime (+6) |
| `src/wool/workflow.py` | _llm_copy, _claim_details, _deterministic_copy, _source_evidence_label |
| `src/text_integrity.py` | _looks_like_utf8_as_gbk, contains_recoverable_utf8_as_gbk_mojibake, repair_utf8_as_gbk_mojibake |
| `src/wool/sources.py` | _split_names, default_wool_sources, resolve_wool_sources |
| `tests/test_llm_generate.py` | test_repair_utf8_as_gbk_mojibake_handles_one_and_two_passes |
| `tests/test_daily_wool.py` | test_deterministic_wool_copy_does_not_repeat_raw_aggregator_excerpt |

## Entry Points

Start here when exploring this area:

- **`contains_recoverable_utf8_as_gbk_mojibake`** (Function) — `src/text_integrity.py:51`
- **`repair_utf8_as_gbk_mojibake`** (Function) — `src/text_integrity.py:31`
- **`test_repair_utf8_as_gbk_mojibake_handles_one_and_two_passes`** (Function) — `tests/test_llm_generate.py:238`
- **`collect_daily_wool_offers`** (Function) — `src/wool/collect.py:359`
- **`default_wool_sources`** (Function) — `src/wool/sources.py:44`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `contains_recoverable_utf8_as_gbk_mojibake` | Function | `src/text_integrity.py` | 51 |
| `repair_utf8_as_gbk_mojibake` | Function | `src/text_integrity.py` | 31 |
| `test_repair_utf8_as_gbk_mojibake_handles_one_and_two_passes` | Function | `tests/test_llm_generate.py` | 238 |
| `collect_daily_wool_offers` | Function | `src/wool/collect.py` | 359 |
| `default_wool_sources` | Function | `src/wool/sources.py` | 44 |
| `resolve_wool_sources` | Function | `src/wool/sources.py` | 64 |
| `test_deterministic_wool_copy_does_not_repeat_raw_aggregator_excerpt` | Function | `tests/test_daily_wool.py` | 253 |
| `_event_key` | Function | `src/wool/collect.py` | 266 |
| `_normalized_benefit_amounts` | Function | `src/wool/collect.py` | 122 |
| `_normalized_benefit_dates` | Function | `src/wool/collect.py` | 171 |
| `_provider` | Function | `src/wool/collect.py` | 242 |
| `_published_datetime` | Function | `src/wool/collect.py` | 250 |
| `_text` | Function | `src/wool/collect.py` | 222 |
| `_looks_like_utf8_as_gbk` | Function | `src/text_integrity.py` | 27 |
| `_llm_copy` | Function | `src/wool/workflow.py` | 85 |
| `_contains_marker` | Function | `src/wool/collect.py` | 230 |
| `_first_marker` | Function | `src/wool/collect.py` | 238 |
| `_has_concrete_benefit_evidence` | Function | `src/wool/collect.py` | 195 |
| `_has_concrete_reset_benefit` | Function | `src/wool/collect.py` | 107 |
| `_split_names` | Function | `src/wool/sources.py` | 40 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Create_daily_wool_posts → _normalize_token` | cross_community | 9 |
| `Create_daily_wool_posts → _parse_published_datetime` | cross_community | 6 |
| `Approve → _looks_like_utf8_as_gbk` | cross_community | 5 |
| `Create_daily_wool_posts → _split_env_names` | cross_community | 5 |
| `Create_daily_wool_posts → Default_ai_digest_sources` | cross_community | 5 |
| `Create_daily_wool_posts → _as_datetime` | cross_community | 5 |
| `Create_daily_wool_posts → _beijing_date` | cross_community | 5 |
| `Create_daily_wool_posts → _trace_url` | cross_community | 5 |
| `Create_daily_wool_posts → _split_names` | cross_community | 5 |
| `Validate → _looks_like_utf8_as_gbk` | cross_community | 5 |

## How to Explore

1. `context({name: "contains_recoverable_utf8_as_gbk_mojibake"})` — see callers and callees
2. `query({search_query: "wool"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
