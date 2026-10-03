---
name: gitnexus-area-images
description: "Skill for the Images area of auto_redbook. 112 symbols across 12 files."
---

# Images

112 symbols | 12 files | Cohesion: 85%

## When to Use

- Working with code in `src/`
- Understanding how generate_aliyun_image, load_aliyun_image_config, test_model_list_fallback_on_quota work
- Modifying images-related functionality

## Key Files

| File | Symbols |
|------|---------|
| `src/images/aliyun_images.py` | _download_bytes, _extract_sync_image_url, _extract_task_id, _extract_task_image_url, _extract_task_status (+21) |
| `src/images/auto_image.py` | _guess_ext, _load_pexels_config, _parse_kv_file, _resolve_image_count, fetch_and_download_related_image (+20) |
| `src/images/volcengine_images.py` | _download_bytes, _extract_image_data, _guess_ext, _http_post_json, _parse_kv_file (+7) |
| `tests/test_aliyun_image_models.py` | test_model_list_fallback_on_quota, test_model_list_skips_non_t2i, test_qwen_image_20_pro_20260622_model_is_passed_to_multimodal_sync, test_qwen_image_20_pro_model_is_passed_to_multimodal_sync, test_qwen_image_does_not_send_negative_prompt_by_default (+5) |
| `tests/test_auto_image.py` | test_fetch_related_images_supports_volcengine_provider, test_pick_best_image_prefers_alt_match, test_pick_best_image_tiebreaker_by_area, test_pick_top_images_prefers_diverse_results, test_pick_top_images_respects_exclude_ids (+5) |
| `src/images/siliconflow_images.py` | _download_image, _image_price_cny, _parse_kv_file, _post_json, _resolve_model_candidates (+4) |
| `src/images/minimax_images.py` | _download, _extract_image, _model_candidates, _request_json, _split_models (+2) |
| `tests/test_volcengine_image_models.py` | test_volcengine_image_generation_posts_seedream_payload, test_volcengine_image_model_list_fallback_on_quota, test_volcengine_image_model_list_fallback_on_transient_generation_failure, fake_post_json |
| `tests/test_aliyun_image_retry.py` | test_aliyun_image_does_not_retry_on_auth_error, test_aliyun_image_gives_up_after_max_attempts, test_aliyun_image_retries_then_succeeds |
| `tests/test_siliconflow_image_models.py` | test_siliconflow_image_config_requires_key, test_siliconflow_image_model_candidates_prefer_env, test_siliconflow_image_price_table_marks_kolors_free |

## Entry Points

Start here when exploring this area:

- **`generate_aliyun_image`** (Function) — `src/images/aliyun_images.py:501`
- **`load_aliyun_image_config`** (Function) — `src/images/aliyun_images.py:158`
- **`test_model_list_fallback_on_quota`** (Function) — `tests/test_aliyun_image_models.py:69`
- **`test_model_list_skips_non_t2i`** (Function) — `tests/test_aliyun_image_models.py:38`
- **`test_qwen_image_20_pro_20260622_model_is_passed_to_multimodal_sync`** (Function) — `tests/test_aliyun_image_models.py:211`

## Key Symbols

| Symbol | Type | File | Line |
|--------|------|------|------|
| `AliyunImageAPIError` | Class | `src/images/aliyun_images.py` | 42 |
| `VolcengineImageAPIError` | Class | `src/images/volcengine_images.py` | 42 |
| `generate_aliyun_image` | Function | `src/images/aliyun_images.py` | 501 |
| `load_aliyun_image_config` | Function | `src/images/aliyun_images.py` | 158 |
| `test_model_list_fallback_on_quota` | Function | `tests/test_aliyun_image_models.py` | 69 |
| `test_model_list_skips_non_t2i` | Function | `tests/test_aliyun_image_models.py` | 38 |
| `test_qwen_image_20_pro_20260622_model_is_passed_to_multimodal_sync` | Function | `tests/test_aliyun_image_models.py` | 211 |
| `test_qwen_image_20_pro_model_is_passed_to_multimodal_sync` | Function | `tests/test_aliyun_image_models.py` | 176 |
| `test_qwen_image_does_not_send_negative_prompt_by_default` | Function | `tests/test_aliyun_image_models.py` | 7 |
| `test_wan25_auto_uses_async_text2image_and_polls` | Function | `tests/test_aliyun_image_models.py` | 280 |
| `test_wan26_forces_n_to_1` | Function | `tests/test_aliyun_image_models.py` | 105 |
| `test_wan27_image_uses_multimodal_sync` | Function | `tests/test_aliyun_image_models.py` | 140 |
| `test_z_image_does_not_send_negative_prompt` | Function | `tests/test_aliyun_image_models.py` | 249 |
| `generate_volcengine_image` | Function | `src/images/volcengine_images.py` | 249 |
| `load_volcengine_image_config` | Function | `src/images/volcengine_images.py` | 89 |
| `test_volcengine_image_generation_posts_seedream_payload` | Function | `tests/test_volcengine_image_models.py` | 13 |
| `test_volcengine_image_model_list_fallback_on_quota` | Function | `tests/test_volcengine_image_models.py` | 61 |
| `test_volcengine_image_model_list_fallback_on_transient_generation_failure` | Function | `tests/test_volcengine_image_models.py` | 96 |
| `fetch_and_download_related_image` | Function | `src/images/auto_image.py` | 1137 |
| `fetch_and_download_related_images` | Function | `src/images/auto_image.py` | 735 |

## Execution Flows

| Flow | Type | Steps |
|------|------|-------|
| `Fetch_and_download_related_image → _compact_spaces` | cross_community | 6 |
| `Fetch_and_download_related_image → _is_text_to_image_model` | cross_community | 5 |
| `Fetch_and_download_related_image → _split_models` | cross_community | 5 |
| `Fetch_and_download_related_image → _parse_kv_file` | cross_community | 5 |
| `Fetch_and_download_related_image → _english_tokens` | cross_community | 5 |
| `Fetch_and_download_related_image → _strip_hashtags` | cross_community | 5 |
| `Fetch_and_download_related_image → _strip_urls` | cross_community | 5 |
| `Minimax_quota → _parse_kv_file` | cross_community | 4 |
| `Regenerate → _split_models` | cross_community | 4 |
| `Regenerate → _parse_kv_file` | cross_community | 4 |

## How to Explore

1. `context({name: "generate_aliyun_image"})` — see callers and callees
2. `query({search_query: "images"})` — find related execution flows
3. Read key files listed above for implementation details
4. `explain({target: "<file or symbol>"})` — persisted taint findings (source→sink data flows), when indexed with `--pdg`
