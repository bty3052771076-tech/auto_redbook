---
name: gitnexus-area-llm
description: "Skill for the Llm area of auto_redbook. 43 symbols across 5 files."
---

# Llm

43 symbols | 5 files | Cohesion: 66%

## When to Use

- Working with code in `src/`
- Understanding how controller_plan, load_llm_config, generate_json work
- Modifying llm-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/llm/generate.py` | _ensure_cfg_list, _is_provider_capacity_exhausted, _is_rate_limited, _rate_limit_max_retries, _rate_limit_retry_seconds (+22) |
| `tests/test_llm_generate.py` | test_generate_json_keeps_literal_json_schema_in_prompt, test_kimi_k3_omits_unsupported_temperature_for_draft_and_json, test_provider_account_overdue_error_allows_the_next_configured_candidate, test_token_plan_capacity_error_skips_rate_limit_backoff, test_generate_draft_allows_configured_multiple_rate_limit_retries (+8) |
| `apps/cli.py` | controller_plan |
| `src/config.py` | load_llm_config |
| `tests/test_daily_wow.py` | test_parser_survives_model_narration_and_raw_newlines |

## Entry Points

Start here when exploring this area:

- **`controller_plan`** (Function) — `apps/cli.py:3595`
- **`load_llm_config`** (Function) — `src/config.py:502`
- **`generate_json`** (Function) — `src/llm/generate.py:706`
- **`test_generate_json_keeps_literal_json_schema_in_prompt`** (Function) — `tests/test_llm_generate.py:183`
- **`test_kimi_k3_omits_unsupported_temperature_for_draft_and_json`** (Function) — `tests/test_llm_generate.py:203`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `controller_plan` | Function | `apps/cli.py` | 3595 |
| `load_llm_config` | Function | `src/config.py` | 502 |
| `generate_json` | Function | `src/llm/generate.py` | 706 |
| `test_generate_json_keeps_literal_json_schema_in_prompt` | Function | `tests/test_llm_generate.py` | 183 |
| `test_kimi_k3_omits_unsupported_temperature_for_draft_and_json` | Function | `tests/test_llm_generate.py` | 203 |
| `test_provider_account_overdue_error_allows_the_next_configured_candidate` | Function | `tests/test_llm_generate.py` | 248 |
| `test_token_plan_capacity_error_skips_rate_limit_backoff` | Function | `tests/test_llm_generate.py` | 252 |
| `generate_draft` | Function | `src/llm/generate.py` | 512 |
| `test_generate_draft_allows_configured_multiple_rate_limit_retries` | Function | `tests/test_llm_generate.py` | 292 |
| `test_generate_draft_caps_effective_tokens_for_long_prompt` | Function | `tests/test_llm_generate.py` | 120 |
| `test_generate_draft_does_not_publish_prompt_when_model_returns_empty_body` | Function | `tests/test_llm_generate.py` | 102 |
| `test_generate_draft_repairs_model_mojibake_and_retries_rate_limit` | Function | `tests/test_llm_generate.py` | 259 |
| `test_generate_draft_retries_one_transient_request_error` | Function | `tests/test_llm_generate.py` | 152 |
| `test_generate_draft_uses_safe_effective_max_tokens` | Function | `tests/test_llm_generate.py` | 60 |
| `test_parser_survives_model_narration_and_raw_newlines` | Function | `tests/test_daily_wow.py` | 422 |
| `test_parse_json_text_accepts_list_content_payload` | Function | `tests/test_llm_generate.py` | 32 |
| `test_parse_json_text_recovers_from_malformed_body_quotes` | Function | `tests/test_llm_generate.py` | 14 |
| `test_coerce_text_preserves_daily_news_body_object_as_json` | Function | `tests/test_llm_generate.py` | 46 |
| `_ensure_cfg_list` | Function | `src/llm/generate.py` | 481 |
| `_is_provider_capacity_exhausted` | Function | `src/llm/generate.py` | 405 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Controller_plan → Canonical_volcengine_model` | cross_community | 6 |
| `Controller_plan → _strip_code_fence` | cross_community | 5 |
| `Generate_json → _strip_code_fence` | cross_community | 5 |
| `Controller_plan → _parse_llm_key_file` | cross_community | 5 |
| `Controller_plan → _split_models` | cross_community | 5 |
| `Controller_plan → _iter_balanced_json_objects` | cross_community | 4 |
| `Generate_json → _escape_raw_controls_in_strings` | cross_community | 4 |
| `Generate_json → _extract_jsonish_field` | cross_community | 4 |
| `Generate_json → _looks_like_jsonish_payload` | cross_community | 4 |
| `Controller_plan → _env_enabled` | cross_community | 4 |

## How to Explore

1. `context({name: "controller_plan"})` — see callers and callees
2. `query({search_query: "llm"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
