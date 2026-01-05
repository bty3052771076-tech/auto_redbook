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
