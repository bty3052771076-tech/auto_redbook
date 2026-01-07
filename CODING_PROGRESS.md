# CODING_PROGRESS

### 2026-01-04 10:40
**Task:** Add DeepSeek V3 config example doc; diagnose LLM auth failure for draft generation.
**Git:** `main` (untracked: `AGENT.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_example/deepseek-v3-0324.md` | DONE | Added project config notes + Python OpenAI-SDK example for DeepSeek. | Ensure `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` are valid, then rerun `apps.cli create/auto`. |
| `AGENT.md` | NEEDS_REVIEW | Repo-local agent instructions file exists but is untracked. | Decide whether to commit it or add it to `.gitignore` if it should remain local-only. |
| `CODING_PROGRESS.md` | DONE | Created progress log and recorded this entry. | Keep appending new entries after coding work. |

**Notes**
- Tests/Lint: Not run (docs-only change); LLM smoke test via `apps.cli create` returned `401 authentication_error` (invalid API key for configured base URL).
- Next steps: Update to a valid DeepSeek API key (do not paste in chat), rerun `.\.venv\Scripts\python -m apps.cli create ...` to confirm LLM succeeds, then run `auto` to save draft.

### 2026-01-04 10:50
**Task:** Validate DeepSeek config; confirm why `apps.cli create` still falls back.
**Git:** `main` (untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_example/deepseek-v3-0324.md` | DONE | Added runnable project config + SDK snippet. | Commit it if you want the doc in repo history. |
| `AGENT.md` | NEEDS_REVIEW | Still untracked. | Decide commit vs ignore. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after coding work. |

**Notes**
- LLM smoke test: `apps.cli create` returned `401 authentication_error (invalid api key)` again (see `data/posts/6be3cdfd4de140a78284a9f4699dfa7a/revisions/4c128cc60b9346f69b357b3df454f801.json`).
- Next steps: Replace `LLM_API_KEY` with a valid DeepSeek key (or switch `LLM_BASE_URL` to the provider that issued your key), then rerun `create` until正文不再是“生成失败”。

### 2026-01-04 11:36
**Task:** Fix false-negative draft save verification; rerun Playwright save flow.
**Git:** `backup_2026-1-2-1` (modified: `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Made `_click_first` tolerant to transient DOM detach; improved `confirm_leave` clicking; `verify_draft_saved` now also checks draft box items as fallback and waits longer for count updates. | If XHS UI changes again, adjust selectors in `confirm_leave` / draft box detection. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |
| `AGENT.md` | NEEDS_REVIEW | Still untracked. | Decide commit vs ignore. |
| `docs/llm_example/deepseek-v3-0324.md` | NEEDS_REVIEW | Still untracked. | Decide commit vs remove. |

**Notes**
- Tests: `pytest -q` → 18 passed.
- Real run: `apps.cli retry 4d44ccb883bd4a70b26a62719bafa323 --login-hold 0 --wait-timeout 600 --force` → `saved_draft` (evidence under `data/posts/4d44ccb883bd4a70b26a62719bafa323/evidence/771bd408d4224fcd93cd24010f1411eb/`).
- LLM is still returning 401 invalid key in this environment, so generated正文可能为回退内容，需更换有效 `LLM_API_KEY` 才能生成正常文案。

### 2026-01-04 11:45
**Task:** Set local LLM API key config (do not commit); re-check connectivity.
**Git:** `backup_2026-1-2-1` (modified: `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.md` | DONE | Updated local LLM config file (ignored by git via `.gitignore` rule `docs/*api-key.md`). | Replace with a valid key for the configured `base_url` to stop 401 errors. |

**Notes**
- LLM smoke test still fails: `401 authentication_error (invalid api key)` when calling `https://api.deepseek.com/v1`.
- Do not commit/push `docs/llm_api-key.md`; it is ignored and not tracked.

### 2026-01-04 11:52
**Task:** Align LLM example base URL with DeepSeek doc.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.example.md` | DONE | Updated example to use `base_url="https://api.deepseek.com/v1"` + `model="deepseek-chat"`. | If you use a different provider, replace base_url/model accordingly. |

**Notes**
- Even with correct base_url, current LLM calls still return 401 (key invalid for that provider). Confirm the key is issued by DeepSeek and active; otherwise change `LLM_BASE_URL` to match the key issuer.

### 2026-01-04 12:14
**Task:** Unify LLM base URL to a single value and re-test.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/config.py`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/config.py` | DONE | Defaulted `base_url` to `https://api.deepseek.com/v1`; default model to `deepseek-chat`; added guard when `LLM_BASE_URL` and `OPENAI_BASE_URL` conflict. | If you use a different LLM provider, set `LLM_BASE_URL`/`OPENAI_BASE_URL` and `LLM_MODEL` accordingly. |
| `docs/llm_api-key.example.md` | DONE | Updated example to DeepSeek `base_url` + `model` so all docs match. | None. |
| `docs/llm_example/deepseek-v3-0324.md` | NEEDS_REVIEW | Holds the reference URL used for docs. | Commit it if you want it tracked (it contains no secrets). |

**Notes**
- Tests/Lint: `pytest -q` → 18 passed.
- LLM smoke test: still fails with `401 authentication_error (invalid api key)` on the unified URL; this indicates the key does not match the configured provider.

### 2026-01-04 12:38
**Task:** Update local LLM API key and re-test authentication.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/config.py`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.md` | DONE | Updated local `api_key` (git-ignored). | Ensure the key is valid for the configured provider; rerun `apps.cli create` until正文正常生成。 |

**Notes**
- Test result: `apps.cli create` still returns `401 authentication_error (invalid api key)` on DeepSeek URL, and OpenAI URL also reports `invalid_api_key` for this key.
- Next steps: Confirm which platform issued this key; then set the matching `LLM_BASE_URL` + `LLM_MODEL` for that platform.

### 2026-01-04 12:58
**Task:** Point LLM calls to ppinfra OpenAI-compatible base URL; pick an available model; re-test draft generation.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/config.py`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/config.py` | DONE | Defaulted LLM `base_url` to `https://api.ppinfra.com/openai`; updated default model to `deepseek/deepseek-v3-0324` (ppinfra `/models` contains this). | If you prefer another ppinfra model, set `LLM_MODEL` explicitly. |
| `docs/llm_api-key.example.md` | DONE | Updated example `base_url`/`model` to match ppinfra defaults. | None. |
| `docs/llm_example/deepseek-v3-0324.md` | DONE | Updated example `LLM_BASE_URL`/`LLM_MODEL` to match ppinfra defaults. | Commit this doc if you want it tracked (contains no secrets). |
| `docs/llm_api-key.md` | DONE | Updated local (git-ignored) `base_url`/`model` to ppinfra + `deepseek/deepseek-v3-0324`. | Keep it untracked/ignored; do not paste keys in chat. |

**Notes**
- LLM smoke test: `apps.cli create` now succeeds and generates a normal title/body (no “生成失败”).
- End-to-end: `apps.cli run 785b978f5e5643e99257802f8a147606 --login-hold 0 --wait-timeout 600` → `saved_draft` (evidence under `data/posts/785b978f5e5643e99257802f8a147606/evidence/ca390eb65565442585a76c903c0b18b7/`).
- Tests: `pytest -q` → 18 passed.

### 2026-01-05 10:20
**Task:** Draft taskbook for expanding body length requirements (wait for review before coding).
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Added requirements/constraints/plan for: body >=300; daily news news>=200 + review>=100; no fabrication; prompt + token_max changes (optional fallback). | Await your review/approval; then implement changes in `src/llm/generate.py` and `src/workflow/create_post.py` (and possibly `src/news/daily_news.py`). |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

### 2026-01-05 10:32
**Task:** Implement plan A: enforce body >= 300 and raise max_tokens; keep news non-fabrication guidance.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/llm/generate.py` | DONE | Updated system prompt to require body >= 300 chars and forbid news fabrication; raised `max_tokens` to 1200. | Proceed with plan B and NewsAPI field expansion after your approval. |
| `docs/正文内容扩充任务书.md` | DONE | Updated task progress table to reflect plan A completion. | Keep updating as plan B/C/D progress. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (prompt/token change only).

### 2026-01-05 10:45
**Task:** Implement plan B: daily news prompt enforces structure and length.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Updated `_daily_news_prompt()` to require “新闻内容>=200字 + 点评>=100字 + 总正文>=300字” and forbid fabrication; added explicit allowed fields. | Next: expand NewsAPI fields and pass description/content to LLM. |
| `docs/正文内容扩充任务书.md` | DONE | Marked plan B as completed in progress table. | Continue tracking plan B/C/D items. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (prompt-only change).

### 2026-01-05 11:05
**Task:** Expand NewsAPI fields and pass to daily news prompt.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | Added `source/description/content` to `NewsItem`; populated these fields in NewsAPI fetch. | Consider enriching GDELT if needed (optional). |
| `src/workflow/create_post.py` | DONE | Added `_clip_text` and included source/description/content in `_daily_news_prompt()` allowed fields. | Add length validation/second-pass expansion if required. |
| `docs/正文内容扩充任务书.md` | DONE | Marked NewsAPI field expansion as completed. | Keep tracking remaining TODO items. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Continue updating after further work. |

**Notes**
- Tests: Not run (news fields/prompt update only).

### 2026-01-05 11:12
**Task:** Run tests after daily news prompt/news field updates.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Marked test status as in-progress (unit tests done, smoke pending). | Run a local smoke test for "每日新闻" when ready. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: `pytest -q` → 18 passed.

### 2026-01-05 11:25
**Task:** Daily news smoke test for length/structure.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Updated test status: length OK, structure missing headings. | Tighten prompt to require explicit headings or add post-check/second pass. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Smoke test: `apps.cli create --title "每日新闻" --prompt "美国时政"` produced body_len=306, but no explicit “新闻内容/我的点评” sections.

### 2026-01-05 11:45
**Task:** Run full auto flow for "每日新闻" and verify draft content rules.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Marked smoke test as blocked due to unmet length/structure rules. | Implement post-check + rewrite to enforce section headings and min lengths. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 posts and saved drafts.
- Results: body_len = 288, 288, 309; none contained explicit “新闻内容/我的点评” sections.
- Conclusion: rules not met; needs stronger prompt and/or validation fallback.

### 2026-01-05 12:05
**Task:** Strengthen daily news prompt with fixed section headings.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Enforced fixed headings “新闻内容/我的点评” and clarified format/length constraints. | Re-run full auto smoke test to verify headings + length. |
| `docs/正文内容扩充任务书.md` | DONE | Added progress row for prompt strengthening; set test status to in-progress. | Update after smoke test results. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (prompt-only change).

### 2026-01-05 12:18
**Task:** Re-run full auto flow after prompt strengthening and verify section lengths.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Updated test status: headings present and body>=300, but news section <200 in all 3 drafts. | Add stronger constraint or post-check/second-pass rewrite for news section length. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 drafts and saved successfully.
- Section lengths (news/review): 163/142, 161/145, 143/145; total body lengths 317, 318, 300.

### 2026-01-05 12:40
**Task:** Re-run auto flow; accept completeness over strict 200-char news section; report results.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Relaxed news section length requirement when content is complete; updated test status summary. | Await your manual review of saved drafts for completeness. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 posts.
- Results: 1 failed (`a0333d...` body not filled); 2 saved (`6d8df1...`, `9e3ff0...`).
- Saved drafts include headings; news section lengths 152 and 196 chars (shorter than 200 but may be complete).

### 2026-01-05 13:05
**Task:** Re-run auto flow per request; validate length/structure.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Updated test status: latest auto run produced 3 drafts under 300 chars; 2 missing section headings. | Decide whether to relax global 300-char rule or add post-check/second pass. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 drafts and saved successfully.
- Results: body_len 277/261/258; section headings missing on 2 of 3; one draft had headings but still <300.

### 2026-01-05 13:25
**Task:** Relax global body minimum to >=200 and re-test.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/llm/generate.py` | DONE | Changed global minimum body length in system prompt from 300 to 200. | Re-run full auto smoke test to validate new threshold. |
| `docs/正文内容扩充任务书.md` | DONE | Updated requirements to global >=200 and set test status to in-progress. | Update after smoke test results. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run yet (awaiting new auto run).

### 2026-01-05 13:45
**Task:** Re-run auto flow after relaxing global body length to >=200.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Adjusted daily news prompt total length requirement to >=200 to match global rule. | Consider enforcing headings via post-check/second pass. |
| `docs/正文内容扩充任务书.md` | DONE | Updated test status with latest auto run results. | Await your review of whether missing headings are acceptable. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 drafts and saved successfully.
- Results: body_len 270/432/284 (all >=200). Headings missing in 2 drafts; 1 draft contains only “我的点评” label.

### 2026-01-05 14:05
**Task:** Investigate daily news image mismatch; update taskbook with findings.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Added verification that image query uses post.title/topics; when title/topic is “每日新闻” it leads to generic news images. | If needed, change query builder to prefer picked news title or filter out “每日新闻”. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Evidence: `post.platform.image.query_original` includes “每日新闻” when title/topics contain it; example `data/posts/a0333d5285354ca8b946a9ff82704130/post.json`.

### 2026-01-05 14:25
**Task:** Filter topic "每日新闻" from auto image query.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Skipped topic "每日新闻" when building image query, reducing generic news image bias. | Re-run auto flow to validate image relevance. |
| `docs/增加图片api后的错误修正任务书.md` | DONE | Updated taskbook checklist and progress note. | Keep tracking image relevance results. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No tests run (small query change).

### 2026-01-07 14:40
**Task:** Fix delete-drafts confirmation for d-popconfirm and verify deletion.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added `d-popconfirm/d-popover` selectors for delete confirm, improved confirm click targeting, and removed premature “暂无” empty-state break to avoid false zero counts. | If UI changes again, re-capture evidence and update confirm selectors. |
| `docs/删除草稿功能任务书.md` | DONE | Logged confirm dialog structure and successful deletion test. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Manual run: `apps.cli delete-drafts --draft-type image --limit 5 --yes --login-hold 120` deleted 5/50 drafts.
- Tests/Lint: Not run (Playwright UI change).

### 2026-01-07 15:10
**Task:** Delete all drafts across all tabs.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/删除草稿功能任务书.md` | DONE | Logged full delete-drafts run results (image 45/45, video/long 0). | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Manual run: `apps.cli delete-drafts --all --yes --login-hold 120` deleted 45/45 image drafts; video/long both 0.

### 2026-01-07 15:25
**Task:** Add delete-drafts description and examples to README.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added delete-drafts capability to feature list, added example commands, and clarified profile scope. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

### 2026-01-06 17:25
**Task:** Improve delete-drafts reliability (confirm wait + list change detection).
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added confirm-dialog wait loop and switched delete loop to fast list-change detection with fallback item-exists check. | Re-run `delete-drafts` to validate deletion speed and stability. |
| `docs/删除草稿功能任务书.md` | DONE | Logged the new reliability improvements and pending re-test. | Update with real test outcome. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-07 13:20
**Task:** Fix delete-drafts confirm handling after timeout.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added popconfirm/popup selectors and avoided clicking list-level delete; now fails fast if confirm not found. | Re-run delete test to verify confirmation click and list change. |
| `docs/删除草稿功能任务书.md` | DONE | Logged delete timeout and confirm-selector fix. | Update with test outcome. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-07 13:35
**Task:** Handle native confirm dialog in delete-drafts flow.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added a one-shot Playwright dialog accept handler before clicking delete. | Re-run delete test to confirm items are removed. |
| `docs/删除草稿功能任务书.md` | DONE | Logged confirm-accept update. | Update with actual deletion outcome. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-07 13:50
**Task:** Improve delete detection using draft box count.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added `before_total` tracking and header count change detection when waiting for deletion. | Re-run delete test to verify count-based detection. |
| `docs/删除草稿功能任务书.md` | DONE | Logged the count-based detection change. | Update with test result. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-07 14:05
**Task:** Add delete failure evidence capture for debugging.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added screenshot/HTML capture on delete errors and timeouts under `data/events/delete_<id>/`. | Re-run delete and inspect evidence to adjust selectors. |
| `docs/删除草稿功能任务书.md` | DONE | Documented evidence capture path. | Update after inspection. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-06 17:50
**Task:** Add draft-location parameter to target alternate draft pages.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/cli.py` | DONE | Added `--draft-location` and `--draft-url` options with validation; passed through to deletion flow. | Re-run delete test against the correct draft URL if needed. |
| `src/publish/playwright_steps.py` | DONE | Added location-aware navigation and relaxed waits for non-publish pages. | Verify custom URL path and selectors if the page layout differs. |
| `docs/删除草稿功能任务书.md` | DONE | Documented new parameters and test note. | Update with real deletion result. |
| `README.md` | DONE | Added example showing custom draft URL usage. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: Not run (Playwright UI change).

### 2026-01-06 14:36
**Task:** Improve news image relevance by reducing generic “news” queries.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Skip “新闻/每日假新闻” topics and only add “news” keyword when no other hints exist. | Consider live daily-news run to confirm image relevance. |
| `src/workflow/create_post.py` | DONE | Daily news multi-flow now uses picked title/description for image query. | Consider live daily-news run to confirm image relevance. |
| `tests/test_auto_image.py` | DONE | Added coverage for skipping news topics and refined query hint behavior. | None. |
| `docs/增加图片api后的错误修正任务书.md` | DONE | Logged the latest fix for query de-genericization. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `pytest tests/test_auto_image.py` (10 passed).
- Risks/Assumptions: Image relevance still depends on Pexels coverage; if results remain generic, consider custom keyword mapping per news domain.
- Next steps: Run `apps.cli auto --title "每日新闻"` to validate real-world image picks.

### 2026-01-06 14:45
**Task:** Add entity-aware keyword mapping for news image queries.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Added country/region/entity mappings and industry keywords to strengthen specific image queries. | Consider expanding entity map as needed. |
| `tests/test_auto_image.py` | DONE | Added coverage for entity keyword mapping. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `pytest tests/test_auto_image.py` (11 passed).
- Risks/Assumptions: Pexels still may return generic results for low-signal topics; mapping can be expanded with more entities.
- Next steps: Re-run `apps.cli auto --title "每日新闻"` and inspect `platform.image.query_used` vs. picked image.

### 2026-01-06 14:57
**Task:** Re-run daily news auto and tighten English query heuristics.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Added English stopword compression for long titles; expanded entity/industry keyword mapping. | Monitor real-world relevance and extend mappings if needed. |
| `tests/test_auto_image.py` | DONE | Added long-English compression coverage. | None. |
| `docs/增加图片api后的错误修正任务书.md` | DONE | Logged latest auto run outcomes and remaining mismatch. | Run another auto to verify the new compression behavior. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `pytest tests/test_auto_image.py` (12 passed).
- Run: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 posts and saved drafts; command timed out after 300s but all 3 posts show `saved_as_draft`.
- Image relevance: two picks aligned with topic (Vietnam town, humanoid robot), one still off-topic (stadium image for Venezuela/US politics).

### 2026-01-06 15:13
**Task:** Re-run daily news auto to validate image relevance.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Logged latest auto run and remaining mismatches (oil hands, cemetery). | Further compress/clean English queries; consider stronger keyword extraction. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Run: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 posts; command timed out but drafts saved.
- Image relevance: 1/3 aligned (hacker), 2/3 still off-topic due to noisy English titles.

### 2026-01-06 15:18
**Task:** Enforce daily news two-section body output.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Strengthened prompt and added post-processing to ensure “新闻内容/我的点评” two-section body. | None. |
| `tests/test_daily_news.py` | DONE | Added tests for section enforcement helper. | None. |
| `docs/正文内容扩充任务书.md` | DONE | Updated testing status with latest auto validation. | Continue sampling if needed. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `pytest tests/test_daily_news.py` (8 passed).
- Run: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 posts; all show both “新闻内容/我的点评” sections.

### 2026-01-06 15:57
**Task:** Add delete-drafts CLI and Playwright flow.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/storage/events.py` | DONE | Added event logging helper for delete-drafts runs. | None. |
| `src/publish/playwright_steps.py` | DONE | Implemented delete-drafts flow and helpers. | Validate selectors in live UI if needed. |
| `apps/cli.py` | DONE | Added `delete-drafts` command with preview/confirm. | Add optional tests if desired. |
| `README.md` | DONE | Documented delete-drafts usage. | None. |
| `docs/删除草稿功能任务书.md` | DONE | Updated progress for implemented items. | Add tests if required. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: Not run (Playwright UI feature).
- Risks/Assumptions: UI selectors may change; delete confirmation dialog varies.
- Next steps: Run `apps.cli delete-drafts --dry-run` then `--yes` to validate in UI.

### 2026-01-06 16:08
**Task:** Fix delete-drafts CLI runtime error and run dry-run.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Fixed indentation error in draft-tab helper. | Consider adding selector resilience tests. |
| `docs/删除草稿功能任务书.md` | DONE | Logged dry-run result and cleaned heading. | Re-run dry-run after confirming login/profile. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `apps.cli delete-drafts --dry-run` ran (total=0).
- Risks/Assumptions: Dry-run likely returned 0 due to login/profile mismatch; verify with `--login-hold`.
- Next steps: Re-run `delete-drafts --dry-run --login-hold 60` and confirm drafts list before deletion.

### 2026-01-06 15:47
**Task:** Draft delete-drafts feature task doc.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/删除草稿功能任务书.md` | DONE | Added requirements, safety checks, and acceptance criteria for deleting drafts. | Await user review before coding. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: Not run (documentation only).
- Risks/Assumptions: None.
- Next steps: Implement after user approval.

### 2026-01-06 10:25
**Task:** Add fake news tests, update README example, and prepare release.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added fake-news prompt branch and disclaimer fallback. | None. |
| `tests/test_fake_news.py` | DONE | Added fake-news unit tests (topics, disclaimer, metadata). | None. |
| `README.md` | DONE | Added “每日假新闻” feature notes and example command. | None. |
| `docs/假新闻任务书.md` | DONE | Marked tests complete and logged recent runs. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | None. |

**Notes**
- Tests/Lint: `pytest tests/test_fake_news.py` (2 passed).
- Risks/Assumptions: None.
- Next steps: Push to `main` and create/push `backup_2026-1-6-2`.

### 2026-01-05 20:35
**Task:** Re-run daily news auto and inspect image outputs.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Logged the latest auto run and that `image_url` is empty. | Investigate why Pexels results are not persisted in `image_url`. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` timed out in shell but reported 3 posts created: `f821fab5...`, `7fdceaf2...`, `36e0f249...`.
- `image_query_original` no longer includes “每日新闻”, but `image_url` is empty in all 3 post.json files.
- Two `apps.cli auto` Python processes still running due to timeout (PIDs 17232, 20848).

### 2026-01-05 20:42
**Task:** Re-run daily news auto with longer timeout.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Logged another auto run; image_url still empty. | Investigate why Pexels image URL is not persisted. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` (300s timeout) created 3 posts: `6ed60c5a...`, `f554b93d...`, `f66e70c7...`.
- Draft save flow succeeded for `6ed60c5a...` per CLI log; no Python processes left after run.
- `image_query_original` no longer includes “每日新闻”, but `image_url` is empty in all 3 post.json files.

### 2026-01-06 09:30
**Task:** Draft fake news workflow task doc.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/假新闻任务书.md` | DONE | Added requirements, flow, acceptance criteria, and task list for “每日假新闻”. | Await user confirmation before coding. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No code changes requested yet; documentation only.

### 2026-01-06 10:05
**Task:** Implement fake news workflow for title "每日假新闻".
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added fake-news prompt, offline fallback, and branch handling with `platform.fake_news`. | Add tests for trigger/prompt/topics if needed. |
| `docs/假新闻任务书.md` | DONE | Marked completed items and updated progress heading. | Consider README updates after review. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No tests run.

### 2026-01-06 10:20
**Task:** Test fake news flow and enforce disclaimer.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Ensure body includes “本文纯属虚构，仅供娱乐。” if missing. | Re-run auto/create to confirm disclaimer appears. |
| `docs/假新闻任务书.md` | DONE | Logged test run and added disclaimer fallback item. | Add README example later. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Ran: `apps.cli auto --title "每日假新闻" --prompt "吕布和董卓是一对苦命鸳鸯" --assets-glob "assets/pics/*"`.
- Result: saved_draft, but body lacked disclaimer; added fallback enforcement.

### 2026-01-06 10:40
**Task:** Re-run fake news auto after disclaimer enforcement.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/假新闻任务书.md` | DONE | Logged regression test with disclaimer present. | Add README example later. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Ran: `apps.cli auto --title "每日假新闻" --prompt "吕布和董卓是一对苦命鸳鸯" --assets-glob "assets/pics/*"`.
- Result: saved_draft; body tail includes “本文纯属虚构，仅供娱乐。”.

### 2026-01-06 11:10
**Task:** Add unit tests for fake news workflow.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `tests/test_fake_news.py` | DONE | Added tests for fake-news prompt branch, metadata, and disclaimer enforcement. | None. |
| `docs/假新闻任务书.md` | DONE | Marked unit test task as complete. | Update README example when ready. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: `pytest tests/test_fake_news.py` (2 passed).

### 2026-01-06 11:35
**Task:** Update README with fake news examples and re-run unit tests.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added “每日假新闻” feature notes and example command. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: `pytest tests/test_fake_news.py` (2 passed).

### 2026-01-05 14:45
**Task:** Re-run daily news auto after filtering topic "每日新闻"; inspect image queries.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Noted auto re-run and that query_original no longer contains "每日新闻". | Evaluate image relevance and consider switching to picked news title for query. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Command: `apps.cli auto --title "每日新闻" --assets-glob "assets/empty/*"` created 3 drafts.
- Image queries: `query_original` no longer includes “每日新闻”; sample IDs `5c8796...`, `5abe1...`, `5e7a5...`.

### 2026-01-05 15:10
**Task:** Prefer picked news title for auto image queries.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | When auto-image is used, query title now prefers `post.platform.news.picked.title` (or current picked in multi flow). | Re-run auto to validate image relevance. |
| `docs/增加图片api后的错误修正任务书.md` | DONE | Marked "query aligns to picked news title" as completed. | Keep tracking image relevance outcomes. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No tests run (small query change).

### 2026-01-06 17:11
**Task:** Investigate delete-drafts tab mismatch report; update taskbook.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/删除草稿功能任务书.md` | DONE | Documented that `draft_type=image` opens 图文 and only `--all` cycles to 视频/长文; long-tab view is not the root failure. | If deletion still stalls, improve post-delete list refresh wait/confirm dialog detection. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No runtime test executed in this step.

### 2026-01-05 15:45
**Task:** Use picked news title/description as image search hint.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Auto-image now passes picked news title/description as `prompt_hint` to reduce generic results. | Re-run auto to confirm image relevance improves. |
| `docs/增加图片api后的错误修正任务书.md` | DONE | Marked prompt_hint alignment with picked news as completed. | Keep tracking image relevance after tests. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No tests run (small query change).
