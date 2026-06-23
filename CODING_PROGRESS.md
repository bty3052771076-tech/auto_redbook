# CODING_PROGRESS

### 2026-06-23 02:35
**Task:** Fix daily-news `原文标题` being replaced by generic fallback summaries.
**Git:** `main (dirty)`; this entry covers workflow title fallback hardening, prompt wording, regression tests, and docs.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added generic-original-title detection, separated `原文标题` fallback from short-title fallback, and passed the normalized post title into final body rendering so non-Chinese source titles no longer become `科技/国际议题出现进展`. Updated the prompt to forbid generic fallback phrases in `原文标题`. | Old XHS/platform drafts still need deletion/regeneration if they already contain bad `原文标题`. |
| `tests/test_daily_news.py` | DONE | Added regressions for `科技议题出现进展` and `平台封锁VPN用户` being replaced by the relevant normalized Chinese post title. | None. |
| `README.md` / `docs/每日新闻原文标题泛化修复-2026-06-23.md` | DONE | Documented the root cause, fix rules, old-draft caveat, and verification. | None. |

**Verification**
- Red: the two new regression tests failed with `原文标题` still equal to `科技议题出现进展` / `国际议题出现进展`.
- Green: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py::test_create_daily_news_posts_replaces_generic_original_title_with_post_title tests\test_daily_news.py::test_create_daily_news_posts_prefers_post_title_over_mismatched_original_summary -q` -> 2 passed.
- `.\.venv\Scripts\python.exe -m py_compile src\workflow\create_post.py tests\test_daily_news.py` -> passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 129 passed.
- `git diff --check` -> no whitespace errors; only existing LF/CRLF conversion warnings.

### 2026-06-23 02:05
**Task:** Raise the unified LLM output token limit to `25565`.
**Git:** `main (dirty)`; this entry covers the LLM call parameter, regression test, and docs.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/llm/generate.py` | DONE | Added `DEFAULT_LLM_MAX_TOKENS = 25565` and passed it to `init_chat_model(..., max_tokens=...)`. | If a provider rejects this limit, lower per-provider handling may be needed later. |
| `tests/test_llm_generate.py` | DONE | Added a regression proving `generate_draft()` passes `max_tokens=25565` to the LLM client. | None. |
| `README.md` / `docs/*` | DONE | Documented the new default and the provider/model limit caveat in `docs/LLM输出token上限调整-2026-06-23.md`. | None. |

**Verification**
- Red: `.\.venv\Scripts\python.exe -m pytest tests\test_llm_generate.py::test_generate_draft_uses_25565_max_tokens -q` failed with `assert 1200 == 25565`.
- Green: `.\.venv\Scripts\python.exe -m pytest tests\test_llm_generate.py::test_generate_draft_uses_25565_max_tokens -q` -> 1 passed.
- `.\.venv\Scripts\python.exe -m py_compile src\llm\generate.py` -> passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_llm_generate.py -q` -> 4 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_llm_generate.py -q` -> 131 passed.
- `git diff --check` -> no whitespace errors; only existing LF/CRLF conversion warnings.

### 2026-06-23 01:45
**Task:** Diagnose and fix incomplete sentence tails in daily-news `评价` content.
**Git:** `main (dirty)`; this entry covers workflow postprocessing, regression tests, and docs.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added `评价`-specific cleanup so leaked `发布时间` / `日期` / `来源` markers and obviously incomplete trailing clauses are removed before the final five-section body is rendered. | Old already-uploaded XHS drafts need deletion/regeneration if they contain half sentences. |
| `tests/test_daily_news.py` | DONE | Added a regression covering the OLED certification draft where `评价` ended with an incomplete clause before `发布时间`. | None. |
| `README.md` / `docs/每日新闻评价半句截断修复-2026-06-23.md` | DONE | Documented why this is not only a `max_tokens` issue, the root cause, cleanup behavior, and verification. | None. |

**Verification**
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py::test_finalize_daily_news_body_removes_incomplete_comment_tail_before_publish_time -q` -> 1 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 127 passed.

### 2026-06-23 01:20
**Task:** Diagnose and fix daily-news image/text mismatch caused by cross-candidate field leakage.
**Git:** `main (dirty)`; this entry covers workflow hardening, regression tests, and docs.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added high-signal context matching for `原文标题` and `image_event`; cross-candidate values are replaced with picked-news/final-title derived values before image generation. Added OLED/display/certification English title mapping. | Old already-uploaded XHS drafts need deletion/regeneration if they have mismatched images. |
| `tests/test_daily_news.py` | DONE | Added a regression reproducing the LG OLED body paired with `锂提取技术获进展` original title/image event. | None. |
| `README.md` / `docs/每日新闻图文不符修复-2026-06-23.md` | DONE | Documented the root cause, exact local evidence, fix, and verification. | None. |

**Verification**
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py::test_create_daily_news_posts_replaces_cross_candidate_title_and_image_event -q` -> 1 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 126 passed.

### 2026-06-23 00:45
**Task:** Fix GUI perceived freezes during long auto-generation tasks and rebuild the quick launcher.
**Git:** `main (dirty)`; this entry covers GUI runner responsiveness, docs, tests, and launcher rebuild.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Added unbuffered subprocess output, a heartbeat for silent long-running CLI subprocesses, explicit run/stop/idle status display, and clearer stop feedback. | If a specific external API hangs beyond its own timeout, inspect the CLI command shown in the GUI log. |
| `tests/test_gui.py` | DONE | Added regressions proving silent subprocesses emit heartbeat logs, status transitions are reported, and GUI subprocess env forces UTF-8 unbuffered output. | None. |
| `AutoRedbookGUI-Launcher.exe` | DONE | Rebuilt the lightweight launcher from `scripts/AutoRedbookGuiLauncher.cs`; it still only starts `.venv\Scripts\pythonw.exe -m apps.gui` and installs nothing. | Reopen GUI from the regenerated exe. |
| `README.md` / `docs/*` | DONE | Documented the GUI heartbeat/status behavior, troubleshooting guidance, and verification in `docs/GUI运行流畅度与心跳修复-2026-06-23.md`. | None. |

**Verification**
- `.\.venv\Scripts\python.exe -m py_compile apps\gui.py` -> passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_gui.py -q` -> 37 passed.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_gui_exe.ps1` -> rebuilt `AutoRedbookGUI-Launcher.exe`.
- Controlled launcher smoke test -> started new `pythonw.exe -m apps.gui` processes and stopped only the test-started processes.

### 2026-06-23 00:00
**Task:** Add a configurable daily-news `评价视角` parameter with neutral default.
**Git:** `main (dirty)`; this entry covers CLI, GUI, prompt, docs, and non-network verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added `DEFAULT_EVALUATION_VIEWPOINT`, normalized viewpoint handling, injected the viewpoint into `_daily_news_prompt(...)`, removed the hardcoded China-stance prompt line, and persisted `platform.news.evaluation_viewpoint`. | Monitor live drafts for whether specific custom viewpoints produce overly opinionated wording. |
| `apps/cli.py` | DONE | Added `--evaluation-viewpoint` to `create` and `auto`, defaulting to `无视角评价`, and passed it into the daily-news workflow. | None. |
| `apps/gui.py` | DONE | Added `评价视角` controls to `自动发帖` and `仅生成`, passed them to CLI args, and supported `AUTO_REDBOOK_GUI_EVALUATION_VIEWPOINT` for GUI autorun. | Reopen GUI to see the new field. |
| `tests/test_daily_news.py` / `tests/test_gui.py` | DONE | Added regression coverage for default/custom viewpoint prompt text and GUI CLI argument construction. | None. |
| `README.md` / `docs/*` | DONE | Documented usage, GUI behavior, workflow metadata, and verification in `docs/每日新闻评价视角参数-2026-06-23.md`. | None. |

**Verification**
- `.\.venv\Scripts\python.exe -m py_compile apps\cli.py apps\gui.py src\workflow\create_post.py` -> passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py::test_daily_news_prompt_requires_chinese_translation_no_url_and_target_lengths tests\test_daily_news.py::test_daily_news_prompt_makes_comment_optional_and_forbids_generic_comment tests\test_daily_news.py::test_daily_news_prompt_defaults_to_no_viewpoint_and_accepts_custom_viewpoint tests\test_gui.py::test_build_cli_args_auto tests\test_gui.py::test_build_cli_args_auto_aliyun_image_source_ignores_local_assets tests\test_gui.py::test_build_cli_args_create -q` -> 6 passed.
- `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_gui.py -q` -> 159 passed.

### 2026-06-22 14:45
**Task:** Add Aliyun visual model `qwen-image-2.0-pro-2026-04-22` for later manual testing.
**Git:** `main (dirty)`; this entry covers model-list, docs, and non-network verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Added `qwen-image-2.0-pro-2026-04-22` to the Aliyun image model dropdown. Default remains `wan2.7-image`. | Manually test against Aliyun when ready. |
| `tests/test_gui.py` / `tests/test_aliyun_image_models.py` | DONE | Updated GUI model-list expectation and added a unit test proving the new model name is passed to the Aliyun multimodal generation payload. | None. |
| `README.md` / `docs/*` | DONE | Documented the new GUI image model option and added a commented manual-test env line. | None. |

**Verification**
- `python -m py_compile apps/gui.py src/images/aliyun_images.py` -> passed.
- `pytest tests/test_gui.py tests/test_aliyun_image_models.py -q` -> 41 passed.
- No live Aliyun API call was made; this change prepares the model for the user's manual test.

### 2026-06-22 14:25
**Task:** Fix GUI startup/runtime reliability after PowerShell security prompt and unstable long-task behavior.
**Git:** `main (dirty)`; this entry covers GUI event-thread hardening, startup-script safety, docs, and verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Added `UiEventQueue` so worker threads no longer write Tk widgets directly; `CommandRunner` now marks jobs running before spawning the worker to block duplicate clicks. | Close already-open old GUI windows and reopen to use the new code. |
| `scripts/start_gui.ps1` / `scripts/open_xhs_creator.ps1` / `scripts/build_gui_exe.ps1` | DONE | Set `Invoke-WebRequest:UseBasicParsing` by default for Windows PowerShell 5.1 script processes to avoid the IE parsing security prompt. | If the prompt still appears, check external PowerShell profiles/scripts or old processes. |
| `tests/test_gui.py` | DONE | Added regression coverage for UI event queue ordering and duplicate-run rejection while a process is starting. | None. |
| `docs/GUI启动与运行稳定性修复-2026-06-22.md` / `README.md` | DONE | Documented the screenshot symptom, root cause investigation, fix, restart advice, and verification commands. | None. |

**Verification**
- `python -m py_compile apps/gui.py` -> passed.
- `pytest tests/test_gui.py -q` -> 33 passed.
- PowerShell parser checks for GUI/startup scripts -> parse-ok.
- Controlled GUI startup smoke -> process stayed alive for 5s, stderr/stdout empty.
- Sensitive token/key scan across repository files -> 0 findings.
- `git diff --check` -> no whitespace errors; only existing LF/CRLF conversion warnings.

### 2026-06-22 13:35
**Task:** Live-test two daily-news XHS drafts, fix English-content leakage, and regenerate two qualified AI-image drafts.
**Git:** `main (dirty)`; this entry covers the live test, quality-gate fix, docs, and verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added English phrase leakage detection for daily-news `内容`, blocked insufficient-material fallback markers, treated `AI议题出现进展` as a generic title, and changed English fallback generation to produce Chinese facts for known topics or skip unknown candidates. | Investigate `delete-drafts --limit 2` returning `type=image total=0` if draft cleanup is required. |
| `tests/test_daily_news.py` | DONE | Added regressions for English phrase leakage and generic AI-progress titles while preserving valid English-source Chinese fallback cases. | None. |
| `docs/每日新闻英文泄漏闸门与两条草稿实测-2026-06-22.md` / `README.md` | DONE | Documented the issue, fix, command, final two XHS draft IDs, AI image provider, and verification evidence. | None. |

**Live Result**
- First online run saved two drafts but content review found one body with an English phrase; this was treated as a failed quality test.
- Attempted cleanup with `delete-drafts --limit 2 --yes`, but the command returned `type=image total=0`, so no deletion was executed.
- Final qualified uploaded image drafts:
  - `7decc80b27a7449fb21c2b2f8bb1f91a` -> `在香江细读潮汕“情书”`, `aliyun/wan2.7-image-pro`, `verified_title=True cover_ready=True`.
  - `c01de0e3735540af9eb639471d4b8717` -> `美伊谈判在即瑞士现场直击`, `aliyun/wan2.7-image-pro`, `verified_title=True cover_ready=True`.
- Local review confirmed both final bodies contain no URL and no 4-word English phrase.

**Verification**
- `pytest tests/test_daily_news.py -q` -> 124 passed.
- `pytest -q` -> 236 passed.
- `git diff --check` -> no whitespace errors; only existing LF/CRLF conversion warnings.
- Secret scan on changed relevant files -> 0 key/token assignment findings.

### 2026-06-22 12:30
**Task:** Fix GUI daily-news `count>1` jobs generating/uploading fewer drafts than requested.
**Git:** `main (dirty)`; this entry covers the candidate-pool/count-safety fix and docs/tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Increased daily-news candidate attempts for multi-count jobs and made partial generation fail with `created only x/y` instead of returning fewer posts to upload. | Run a live GUI auto job if a new XHS upload verification is required. |
| `apps/gui.py` | DONE | Added `ensure_daily_news_candidate_pool_env(...)`; GUI `auto`/`create` now injects `NEWS_MAX_RECORDS=max(60,count*20)` for multi-count daily-news jobs and forces UTF-8 subprocess output. | None. |
| `tests/test_daily_news.py` / `tests/test_gui.py` | DONE | Added regressions for quality-gate skips beyond the first 15 candidates, partial-count failure, GUI env expansion, and UTF-8 env propagation. | None. |
| `docs/GUI每日新闻数量不足修复-2026-06-22.md` / `README.md` / `docs/工作流新闻任务书.md` | DONE | Documented root cause, user-visible behavior, verification, and the GUI `NEWS_MAX_RECORDS` behavior. | None. |

**Verification**
- `pytest tests/test_gui.py tests/test_daily_news.py -q` -> 153 passed.
- `pytest -q` -> 234 passed.
- `git diff --check` -> no whitespace errors; only existing LF/CRLF conversion warnings.
- Secret scan on changed relevant files -> 0 key/token assignment findings.

### 2026-06-22 11:35
**Task:** Finish the interrupted 3-draft live test, harden daily-news quality gates, delete bad XHS drafts, and upload 3 corrected AI-image drafts.
**Git:** `main (dirty)`; this entry covers the final live delete/regenerate verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added HTML-artifact stripping, site-sidebar noise gates, final `comment_mismatch` detection, tighter AI/copyright comment gating, and factual fallbacks for 大湾区科创 / 韩国科技资金 / 夏播粮食 samples. Added specific title compression for 大湾区、科幻论坛、韩国科技 to avoid 17-18 char truncation. | None. |
| `tests/test_daily_news.py` | DONE | Added regressions for broken HTML image tags, 21jingji sidebar noise, mismatched 美股 comments, 大湾区 title compression, and 韩国科技 title/comment cleanup. | None. |
| `docs/每日新闻三条草稿最终实测-2026-06-22.md` | DONE | Added the final live-test report, online provider failure states, verification commands, and final XHS draft IDs/titles/times. | None. |

**Live Result**
- Deleted the previously uploaded bad image drafts from XHS creator-center using `delete-drafts --draft-type image --yes`.
- Confirmed the draft box was empty before the final upload: `type=image total=0`, `type=video total=0`, `type=article total=0`.
- Final uploaded image drafts:
  - `83a5dbc8aa2d490b8a65160b44b7780a` -> `大湾区前沿技术落地`, saved at `2026-06-22 11:22:20`.
  - `2fdaeadf7f7847c19c2caa8a076e1a76` -> `大湾区科创中心建设提速`, saved at `2026-06-22 11:24:18`.
  - `211bacff2cc24208954a39b6c6ef39cc` -> `全球资金布局韩国科技`, saved at `2026-06-22 11:26:16`.
- Final dry-run confirmation: `type=image total=3`; upload logs for all three posts showed `result: saved_draft` and `verified_title=True cover_ready=True`.
- Online provider status during live testing: Juhe returned daily quota exceeded, GNews returned HTTP 429, NewsAPI timed out from the current network. Final upload used a local cached GNews candidate file via `NEWS_PROVIDER=file` and did not persist any API keys.

**Verification**
- `pytest tests/test_daily_news.py -q` -> 120 passed.
- `pytest -q` -> 229 passed.

### 2026-06-21 19:45
**Task:** Delete old XHS creator-center drafts, tighten daily-news quality, and regenerate 3 daily-news drafts.
**Git:** `main (dirty)`; this entry covers the quality fix before the final live delete/regenerate run.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Rewrote truncated 17-18 char LLM titles from source facts, filtered Juhe/site datelines and footer fragments, removed broken quote fragments, made AI/copyright comment detection whitespace-robust, required final daily-news bodies to include `原文标题/内容/日期/来源`, and added factual comment fallbacks for consumer-product checks, consumption subsidies, concert network保障, and WeChat AI assistant/product-boundary news. | Run final live delete/regenerate verification. |
| `tests/test_daily_news.py` | DONE | Added regressions for the real bad samples: truncated titles, missing content section, The Paper footer/责任编辑/ICP noise, irrelevant AI/copyright comment, WeChat AI wrong-template comment, and broken `苏新消费·品` content. | None. |
| `docs/每日新闻正文渲染修复-2026-06-21.md` | DONE | Documented the latest title/content/comment quality gates and verification commands. | Update with final live post IDs after regeneration if needed. |

**Verification**
- `pytest tests/test_daily_news.py -q` -> 103 passed.
- `pytest -q` -> 212 passed.

### 2026-06-21 18:55
**Task:** Live-test Juhe by generating two daily-news drafts and fix issues found during inspection.
**Git:** `main (dirty)`; this entry covers daily-news quality cleanup and live local draft generation.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Tightened irrelevant AI/copyright comment detection, added industry-tech / securities-regulation factual comment fallbacks, removed audio-column/byline noise, and made daily-news body finalization idempotent by running a second normalize pass. | None. |
| `tests/test_daily_news.py` | DONE | Added regressions for industrial AI news, finance/trade news, securities penalties, audio-column noise, reporter byline cleanup, and repeated broken-tail cleanup. | None. |

**Live Result**
- Generated local Juhe daily-news draft: `9a4af4e4510a4ee6b314fb5c03f728ae`, title `第二十四届海创会落幕`, provider `juhe`, source `厦门日报`, body has no URL and no AI/copyright mismatch.
- Generated local Juhe daily-news draft: `a8d51a33f697474d9bce4a4de7e04bcc`, title `新海达码头流动机械装上360度全景`, provider `juhe`, source `厦门日报`, body has no URL and no AI/copyright mismatch.

**Verification**
- `pytest tests/test_daily_news.py -q` -> 97 passed.
- `pytest -q` -> 206 passed.
- Secret scan: no Juhe/appkey 32-hex secret-like matches in tracked code/docs/tests.

### 2026-06-21 18:10
**Task:** Add Juhe news headline and finance-news providers without persisting user API keys.
**Git:** `main (dirty)`; this entry covers provider implementation, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | Added `NEWS_PROVIDER=juhe`, Juhe key loading, headline list/detail mapping, finance-news mapping, auto-provider detection, category routing, and key-safe Juhe error messages. | Run a live request only after the user sets keys in local env/session; real keys were not written to tracked files. |
| `tests/test_daily_news.py` | DONE | Added Juhe regressions for headline detail content, finance query routing, auto-mode discovery, and APP-key leak prevention. | None. |
| `README.md` / `docs/使用说明-自动新闻生成与草稿发布.md` / `docs/工作流新闻任务书.md` | DONE | Documented Juhe env vars, auto-provider order, usage examples, and secret-handling workflow. | None. |
| `docs/juhe_api-key.example.md` / `docs/聚合数据新闻源接入-2026-06-21.md` | DONE | Added placeholder-only local key template and dedicated Juhe integration note. | None. |

**Notes**
- Juhe is treated as a category API, not a full-text keyword API, so the generic keyword relevance filter is not applied before accepting category results.
- Secret safety: the user-provided APP-keys were not copied into code, docs, tests, commands, or tracked config files.
- Verification: `pytest tests/test_daily_news.py -q` -> 91 passed; `pytest -q` -> 200 passed; `git diff --check` -> no whitespace errors, only existing CRLF warnings.

### 2026-06-21 17:15
**Task:** Remove GDELT news source and harden daily-news quality gates after live XHS draft inspection.
**Git:** `main (dirty)`; this entry covers news-provider routing, daily-news title/body/comment cleanup, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | Removed GDELT production fetch path and `gdelt` from supported providers. `NEWS_PROVIDER=auto` now tries only configured NewsAPI/GNews or `file`, and errors clearly when no provider is configured. | None. |
| `src/workflow/create_post.py` | DONE | Added title/body language quality gates, common Traditional-to-Simplified normalization, site-noise cleanup, generic fallback rejection, NASA/World-Cup comment correction, and final single-post daily-news quality checks. | None. |
| `apps/cli.py` | DONE | Removed stale `gdelt` stage keyword while keeping NewsAPI/GNews/file errors mapped to `stage=获取新闻`. | None. |
| `tests/test_daily_news.py` | DONE | Added regressions for no GDELT fallback, unsupported `NEWS_PROVIDER=gdelt`, foreign excerpt title rejection, site-noise cleanup, and wrong sports-template comment replacement. Updated old GDELT tests to GNews behavior. | None. |
| `README.md` | DONE | Replaced GDELT usage docs with NewsAPI/GNews/file guidance and added the new repair document to the docs index. | None. |
| `docs/每日新闻质量闸门与GDELT移除-2026-06-21.md` | DONE | Added repair notes, usage guidance, and verification result. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` / `docs/工作流新闻任务书.md` | DONE | Updated news-source troubleshooting and provider contract to remove GDELT. | None. |

**Notes**
- Root cause: GDELT fallback could provide only titles/low-quality snippets, allowing foreign/title-fragment drafts and generic filler to reach XHS.
- Verification: `pytest tests/test_daily_news.py -q` -> 87 passed.

### 2026-06-21 15:50
**Task:** Diagnose GUI/CLI `delete-drafts` showing `type=image total=0` even when XHS image drafts exist.
**Git:** `main (dirty)`; this entry covers CLI delete-draft preview error reporting, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/cli.py` | DONE | `delete-drafts` now prints preview `errors` and exits with code 1 before deletion when the dry-run enumeration fails, instead of silently reporting `未找到草稿`. | None. |
| `tests/test_cli_delete_drafts.py` | DONE | Added regression coverage for `total=0 + errors`, ensuring the CLI prints the real error and does not claim the draft box is empty. | None. |
| `docs/GUI删除草稿total0诊断-2026-06-21.md` | DONE | Documented the root cause, safe dry-run command, `--limit 0` semantics, and verification result. | None. |
| `README.md` | DONE | Added the new diagnostic doc to the docs index. | None. |

**Notes**
- Investigation: latest saved XHS draft evidence HTML contains 21 `.draft-item` entries, and a fresh headless dry-run against the workspace profile returned `type=image total=20`, so the user's `total=0` was not proof that drafts were absent.
- Verification: `pytest tests/test_cli_delete_drafts.py tests/test_cli_headless.py -q` -> 10 passed; safe dry-run command returned 20 image drafts and printed the first 5.
- Safety: no deletion command was executed; only dry-run preview was used.

### 2026-06-21 11:32
**Task:** Tighten daily-news draft title/content quality after XHS screenshot review.
**Git:** `main (dirty)`; this entry focuses on daily-news prompt/content normalization, tests, and docs while earlier uncommitted GUI/upload/news-source changes remain in the working tree.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Daily-news titles now prefer a summarized 12-18 character Chinese title, ideal around 15 characters, instead of blindly preserving/truncating/copying original titles. Original-source lookup now runs by default when a URL exists and keeps up to `NEWS_SOURCE_LOOKUP_MAX_CHARS` characters for grounded LLM summarization. Content cleanup removes browser-upgrade notices, site navigation noise, media IDs, protocol-relative image URLs, generic methodology filler, duplicate fact sentences, photo-credit tails, Xinhua dateline fragments, recommendation-read noise, and copied title fragments before final body rendering. `内容` is capped at 150 Chinese characters. Fact/评价 consistency checks now replace unsupported hallucinated content and irrelevant commentary templates. | None. |
| `tests/test_daily_news.py` | DONE | Added/updated regression coverage for semantic title compression, no-copy short title rewriting, balanced Chinese quotes, column-prefix stripping, browser/navigation-noise removal, original-source enrichment, 150-char content limit, generic filler removal, Xinhua caption/dateline cleanup, unsupported-content fallback, irrelevant-comment replacement, repeated named-subject dedupe, and contextual topic fallback. | None. |
| `README.md` | DONE | Updated daily-news usage rules: five-section body, 12-18 char title, 150-char content, source lookup, and `NEWS_SOURCE_LOOKUP_MAX_CHARS`. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Expanded user-facing daily-news rules for title length, five-section rendering, source lookup, and no-URL/no-noise output. | None. |
| `docs/每日新闻正文JSON结构稳定化-2026-06-20.md` | DONE | Updated the stable body contract so `内容` is 150 characters or fewer. | None. |
| `docs/每日新闻正文渲染修复-2026-06-21.md` | DONE | Added the latest rendering/quality constraints, including generic-filler removal and original-source lookup depth. | None. |

**Notes**
- Skills used: `$using-superpowers` for workflow discipline, plus systematic debugging, TDD, prompt optimization, screenshot verification, and verification-before-completion.
- Tests/Lint: targeted daily-news tests were red before implementation; after fixes, `pytest tests/test_daily_news.py -q` -> 82 passed. Full-suite and diff checks are tracked in the final turn summary.
- Live XHS verification: after multiple screenshot-driven fixes, generated and uploaded `eac90d3a7b554ad28ff8bad5aca2ca61` with Aliyun `wan2.7-image-pro`; XHS draft-box screenshot shows title `中国共商全球人权治理`, saved at Beijing time `2026-06-21 13:18:14`, with title verified and cover ready.
- Risks/Assumptions: NewsAPI/GDELT/GNews were rate-limited during this final run, so the accepted live verification used a local Xinhua candidate file while still fetching the original article page for grounded summarization.
- Next steps: None for this specific repair; optional cleanup is to delete older iterative test drafts from the XHS draft box if you no longer need them.

### 2026-06-20 10:51
**Task:** Unify GUI image source selection into local assets, Aliyun, and Pexels.
**Git:** `main (dirty)`; this entry focuses on `apps/gui.py`, `tests/test_gui.py`, `README.md`, and the new image-source doc, while earlier uncommitted headless/upload-layout files remain in the working tree.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Added `local` / `aliyun` / `pexels` image source semantics, route non-local sources through `assets/empty/*`, disable local assets input when automatic providers are selected, disable auto image for local source, and bind mouse wheel for the scrollable auto tab. | None. |
| `tests/test_gui.py` | DONE | Added coverage for three image sources, local source disabling auto-image, non-local source forcing `assets/empty/*`, and Aliyun auto command behavior. | None. |
| `README.md` | DONE | Documented GUI image source choices and clarified that Aliyun/Pexels ignore local assets to trigger automatic image generation/search. | None. |
| `docs/GUI图片来源统一-2026-06-20.md` | DONE | Added dedicated explanation of the old confusion, new mapping, CLI/env behavior, and verification. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding/docs work. |

**Notes**
- Tests/Lint: `py_compile apps/gui.py` passed; `pytest tests/test_gui.py -q` -> 24 passed; full `pytest -q` -> 121 passed in 41.57s.
- Screenshot verification: GUI launched successfully and temporary screenshots were deleted; automated wheel scrolling was unreliable in the capture harness, so final verification relies on unit tests plus successful Tk window construction.
- Risks/Assumptions: `local` intentionally injects `AUTO_IMAGE=0`; if the local glob is empty, the user should choose `aliyun` or `pexels` instead of expecting fallback.
- Next steps: Consider applying the same unified image-source selector to the `仅生成` tab if you want create-only runs to expose Aliyun/Pexels explicitly too.

### 2026-06-20 10:37
**Task:** Redesign the GUI auto-post run-options area to prevent clipped controls and verify with screenshots.
**Git:** `main (dirty)`; this entry focuses on `apps/gui.py` and the new GUI layout doc, while earlier uncommitted headless-upload files remain in the working tree.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Replaced the cramped one-line run-options layout with a panel layout, moved run options above the main form, added a scrollable auto-post tab, and moved title shortcut/buttons plus image hint text to separate rows to prevent right-edge clipping. | None. |
| `docs/GUI运行选项布局修复-2026-06-20.md` | DONE | Added root cause, layout changes, validation commands, and screenshot-verification note. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding/docs work. |

**Notes**
- Tests/Lint: `py_compile apps/gui.py` passed; `pytest tests/test_gui.py -q` -> 21 passed; full `pytest -q` -> 118 passed in 47.09s.
- Screenshot verification: captured GUI window via Windows window handle; confirmed `dry-run`, `无界面上传`, `force`, `登录等待（秒）`, and `页面等待（秒）` are fully visible without right-edge clipping. Temporary screenshots were deleted after inspection.
- Risks/Assumptions: Verification was visual/manual because Tkinter widget geometry is best validated against an actual rendered window; no upload or XHS automation was executed.
- Next steps: If this layout feels good in daily use, keep the same panel pattern for future GUI option groups.

### 2026-06-20 10:22
**Task:** Add optional headless XHS draft upload and live terminal progress reporting.
**Git:** `main (dirty)`; modified upload automation, CLI/GUI entry points, tests, README, and added a docs note.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added `XHS_HEADLESS` / `headless` resolution, protected progress callbacks, incremental upload-ready progress, and headless launch support for save-draft and delete-drafts flows. | Live XHS behavior still depends on the already logged-in workspace profile and platform headless tolerance. |
| `apps/cli.py` | DONE | Added `--headless` to `run`, `auto`, `retry`, and `delete-drafts`; wired live `[xhs-upload]` progress to terminal output with `post_id`. | None. |
| `apps/save_draft.py` | DONE | Added `--headless` and real-time progress output for the legacy save-draft entry point. | None. |
| `apps/gui.py` | DONE | Added GUI headless options for auto upload, draft processing upload, and draft deletion; command builder now emits `--headless`. | None. |
| `tests/test_cli_headless.py` | DONE | Added regression coverage ensuring CLI default `False` does not override `XHS_HEADLESS=1`, while explicit `--headless` still passes through. | None. |
| `tests/test_playwright_profile_config.py` | DONE | Added regression coverage for headless env/argument precedence and incremental upload progress messages. | None. |
| `tests/test_gui.py` | DONE | Added regression coverage that GUI command construction includes `--headless` for auto/run/delete paths. | None. |
| `README.md` | DONE | Documented quick headless usage, GUI headless checkbox behavior, profile requirement, and terminal progress format at a high level. | None. |
| `docs/无界面上传与终端进度-2026-06-20.md` | DONE | Added focused usage documentation with CLI examples, GUI steps, progress output examples, and limitations. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding/docs work. |

**Notes**
- Tests/Lint: `pytest tests/test_cli_headless.py tests/test_playwright_profile_config.py tests/test_gui.py -q` -> 31 passed; `py_compile src/publish/playwright_steps.py apps/cli.py apps/save_draft.py apps/gui.py` passed; full `pytest -q` -> 118 passed in 39.71s; CLI help checks for `run`, `auto`, `delete-drafts`, and `apps.save_draft run` showed `--headless`.
- Risks/Assumptions: Headless upload requires an already logged-in `data/browser/chrome-profile`; first login, QR/captcha, and account risk checks still require visible Chrome. If XHS blocks headless automation, visible mode remains the default fallback.
- Next steps: Use `--headless --login-hold 0` only after confirming the workspace profile is logged in; if a headless upload fails, open `Open-XHS-Creator.cmd` or GUI `登录/检查Profile` and retry without `--headless`.

### 2026-06-20 10:11
**Task:** Add README quick-use section and back up the previous version before upload.
**Git:** `main (dirty)`; `README.md` modified after pushing backup branch/tag `pre-readme-quickuse-20260620-101059`.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added `快速使用` with required 小红书账号、阿里云账号（LLM/VLM/图像能力）和 Python 环境； included workspace-local setup, Aliyun env vars, GUI launch, and one CLI news command. Also updated quick-start comments from Pexels-default to Aliyun-default. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding/docs work. |

**Notes**
- Backup: pushed branch `backup/pre-readme-quickuse-20260620-101059` and tag `pre-readme-quickuse-20260620-101059`, both pointing to pre-change commit `a912802`.
- Tests/Lint: README inspected with `Get-Content`; `git diff --check` passed. No Python tests were run because this is documentation-only.
- Risks/Assumptions: The README uses placeholder key values only; real API keys remain excluded by `.gitignore`.
- Next steps: Commit and push the README quick-use update to `main`.

### 2026-06-20 10:06
**Task:** Tighten daily-news title/prompt/source-grounding rules and improve GUI defaults, profile login, and Beijing-time draft display.
**Git:** `main (dirty)`; modified news workflow, GUI, tests, README/docs; added one repair note.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added Japanese-kana detection, 20-char Chinese title normalization without `每日新闻｜`, original-news excerpt lookup for incomplete snippets, stronger source-grounded prompt rules, and per-post source lookup metadata. | None. |
| `apps/gui.py` | DONE | Changed GUI default image provider to `aliyun`, added profile login launch URL/button, removed mixed time from draft choices, and added Beijing-time formatting/detail helpers. | None. |
| `tests/test_daily_news.py` | DONE | Added regression tests for Japanese-title cleanup, Japanese trade-title fallback, source lookup enrichment, and no-speculation prompt requirements. | None. |
| `tests/test_gui.py` | DONE | Updated default image provider tests and added coverage for Aliyun fallback, login launch args, and Beijing-time draft detail. | None. |
| `README.md` | DONE | Documented Aliyun as default image provider, source lookup env vars, stricter daily-news title rules, and GUI Beijing-time/profile login behavior. | None. |
| `docs/模型与GUI供应商配置.md` | DONE | Updated GUI default provider documentation and draft-processing time display description. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Documented profile login button, Beijing-time draft time panel, title cleanup, no-Japanese rule, and source lookup behavior. | None. |
| `docs/GUI小红书Profile修复-2026-06-20.md` | DONE | Added the new `登录/检查Profile` button note. | None. |
| `docs/新闻标题提示词与GUI默认项修复-2026-06-20.md` | DONE | Added focused repair documentation for title/prompt/source lookup and GUI defaults. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding work. |

**Notes**
- Tests/Lint: TDD red check first failed on missing helpers/constants; after implementation, `py_compile src/workflow/create_post.py apps/gui.py` passed, `pytest tests/test_daily_news.py tests/test_gui.py -q` -> 55 passed, and full `pytest -q` -> 109 passed in 33.57s.
- Risks/Assumptions: Original-news lookup uses a simple HTML text extractor with an 8s default timeout; if source pages block bots/paywall, the prompt falls back to conservative no-speculation language.
- Next steps: Use GUI default Aliyun image provider for the next real draft run; if login state fails, click `登录/检查Profile` before running upload.

### 2026-06-20 09:35
**Task:** Fix GUI "打开小红书创作平台" to open the workspace Chrome profile instead of the system default profile.
**Git:** `main (dirty)`; modified GUI/profile launch code, tests, quick-launch script, README, usage docs; added one repair note.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Replaced `webbrowser.open()`-only behavior with Chrome launch args that use `data/browser/chrome-profile`; added `XHS_CHROME_PATH`, `XHS_CHROME_USER_DATA_DIR`, and `XHS_CHROME_PROFILE` support. | None. |
| `scripts/open_xhs_creator.ps1` | DONE | Aligned the standalone quick-launch script with the GUI profile rules and added Chrome path/profile overrides. | None. |
| `tests/test_gui.py` | DONE | Added regression tests for workspace profile launch args, profile overrides, and actual GUI launch invocation. | None. |
| `README.md` | DONE | Documented that the GUI button and `Open-XHS-Creator.cmd` use the workspace profile. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Added the same GUI profile note and optional override variables. | None. |
| `docs/GUI小红书Profile修复-2026-06-20.md` | DONE | Added a focused repair note with root cause, fix behavior, config variables, and verification commands. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry after invoking the file-progress-followup workflow. | Keep updating after future coding work. |

**Notes**
- Tests/Lint: first TDD red check failed with missing `build_xhs_creator_launch_args`; after the fix, `pytest tests/test_gui.py -q` -> 18 passed, `py_compile apps/gui.py` passed, PowerShell script parser passed, and full `pytest -q` -> 102 passed in 13.77s.
- Verification: non-invasive runtime check reports `C:\Program Files\Google\Chrome\Application\chrome.exe --user-data-dir=E:\AI\codex\redbook_workflow\data\browser\chrome-profile --profile-directory=Default https://creator.xiaohongshu.com/publish/publish?target=image`.
- Risks/Assumptions: I did not force-open Chrome during final verification to avoid interrupting your current browser session; the generated launch args point to the correct existing workspace profile.
- Next steps: Open GUI and click “打开小红书创作平台”; it should now show the same logged-in account and drafts as the automation profile.

> 记录按时间倒序（最新在前）

### 2026-06-19 19:22
**Task:** Fix daily-news prompt leakage, strict XHS draft-title persistence, resilient news sources, and verify 5 AI-image news drafts end-to-end.
**Git:** `main (dirty)`; working tree already had earlier GUI/model/API changes from this session.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Removed prompt echo from daily-news fallback bodies/topics; stopped unsafe "news fetch failed -> generic one-post generation" fallback. | None. |
| `src/news/daily_news.py` | DONE | Added NewsAPI -> GDELT auto fallback metadata, `NEWS_PROVIDER=file`, JSON candidate loading, and safer entity dedupe that ignores source boilerplate like `AP`/`Reuters`. | Keep candidate-file schema documented if more source fields are added. |
| `src/publish/playwright_steps.py` | DONE | Made title/body filling use trusted keyboard input, added fill-settle verification, and kept strict post-save draft-box title verification. | Re-check selectors if XHS publish UI changes. |
| `apps/cli.py` | DONE | `create`/`auto` now exit with an error when zero posts are created instead of silently succeeding. | None. |
| `tests/test_daily_news.py` | DONE | Added coverage for prompt-safe fallback, provider fallback, file provider, failed-news-source behavior, and over-dedupe regressions. | None. |
| `tests/test_playwright_draft_button.py` | DONE | Added coverage for specific draft-title matching and generic-title rejection. | None. |
| `README.md` | DONE | Documented `NEWS_PROVIDER=file` / `NEWS_CANDIDATES_FILE` and the verified 5-news command pattern. | None. |
| `docs/新闻自动化修复与实测报告-2026-06-19.md` | DONE | Added a dedicated repair/test report with the 5 real XHS draft IDs, titles, AI image provider, and evidence notes. | None. |
| `data/news/manual_candidates_20260619.json` | DONE | Added the verified AP News candidate file used for the live 5-draft test while NewsAPI/GDELT were unavailable. | Replace with a fresh verified file for future date-specific runs. |
| `CODING_PROGRESS.md` | DONE | Logged this entry after invoking `$file-progress-followup`. | Continue logging after future coding work. |

**Notes**
- Tests/Lint: `py_compile` for changed Python files passed; `pytest tests/test_daily_news.py tests/test_playwright_draft_button.py -q` -> 31 passed; `pytest -q` -> 92 passed in 12.76s.
- Live XHS result: five posts saved as titled image drafts with Aliyun `wan2.7-image`; latest execution for each ended `saved_draft` with `verified_title=True cover_ready=True`.
- Risks/Assumptions: NewsAPI returned connection refused and GDELT returned 429 during this run, so the real-news input used a verified file provider; two failed attempts left `暂无笔记标题` test drafts in XHS and were not deleted without user confirmation.
- Next steps: If desired, run a limited `delete-drafts --dry-run` then delete only the known untitled test drafts after explicit confirmation.

### 2026-02-03
**Task:** GUI 默认值与“仅上传（approve/run）”工作流增强
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/图形界面工作流增强任务书.md` | DONE | 新增任务书：明确默认值策略、Key 不上传保障、approve/run 工作流。 | None. |
| `apps/gui.py` | DONE | 配置页补默认值；新增 `run（仅上传）` 页签（支持选择 post_id、approve、run）。 | 手动跑一次 GUI 做冒烟测试。 |
| `tests/test_gui.py` | DONE | 补充 `approve/run` 的 CLI 参数构造单测。 | None. |
| `.gitignore` | DONE | 显式忽略 `.env.gui`（并保留 `.env.*` 兜底）。 | None. |
| `README.md` | DONE | 补充 GUI 工作流说明与任务书索引。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-03
**Task:** 打包 GUI 为 AutoRedbookGUI.exe（快速启动）
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | 支持打包后运行：CLI 调用优先使用 `.venv\\Scripts\\python.exe`，避免 frozen exe 下 `sys.executable` 失效。 | None. |
| `scripts/build_gui_exe.ps1` | DONE | 新增 PyInstaller 打包脚本（生成并拷贝 `AutoRedbookGUI.exe` 到仓库根目录）。 | 运行脚本生成 exe 并手动打开验证。 |
| `.gitignore` | DONE | 忽略 PyInstaller 产物（build/dist/*.spec）与本地 exe（AutoRedbookGUI*.exe）。 | None. |
| `docs/图形界面任务书.md` | DONE | 补充 exe 打包说明与进度记录。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-03
**Task:** 图形界面（GUI）用于选择模型/参数并一键执行
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/图形界面任务书.md` | DONE | 新增 GUI 任务书（目标/方案/验收/测试/拆解）。 | None. |
| `apps/gui.py` | DONE | 新增 Tkinter GUI：auto/create/delete-drafts + `.env.gui` 保存/加载 + 日志输出。 | 手动跑一次 `python -m apps.gui` 验证窗口与执行。 |
| `tests/test_gui.py` | DONE | 新增 GUI 辅助函数单测（env 读写/命令构造）。 | None. |
| `README.md` | DONE | 增加 GUI 启动方式与任务书索引。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-02
**Task:** 每日新闻加入发布时间、候选去重与严格内容约束
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | 增加发布时间兜底写入、提示词严格约束。 | None. |
| `src/news/daily_news.py` | DONE | 候选新闻统一去重，减少重复。 | None. |
| `tests/test_image_event_hint.py` | DONE | 新增发布时间兜底单测。 | None. |
| `tests/test_daily_news.py` | DONE | 新增候选去重单测。 | None. |
| `docs/新闻时效性去重与内容规范任务书.md` | DONE | 新增任务书。 | None. |
| `README.md` | DONE | 补充发布时间与文档索引。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-02
**Task:** 生图提示词加“无文字”约束
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | 生图提示词追加“不要出现文字/水印/标志/海报排版/UI”。 | None. |
| `tests/test_auto_image.py` | DONE | 新增断言确保提示词包含“无文字”约束。 | None. |
| `docs/生图事件摘要任务书.md` | DONE | 追加进度记录。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-03
**Task:** 每日新闻偏向中国新闻（中国:海外≈6:4）
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | 增加中国新闻判定 + 比例挑选（默认 0.6）与轻度加分。 | None. |
| `tests/test_daily_news.py` | DONE | 新增 6:4 比例挑选单测。 | None. |
| `docs/中国海外新闻比例任务书.md` | DONE | 新增任务书与进度记录。 | None. |
| `README.md` | DONE | 增加 `NEWS_CHINA_RATIO/NEWS_CHINA_BONUS` 说明与任务书索引。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-02-01
**Task:** 每日新闻正文首行加入“要点摘要”并加兜底
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | 新增要点摘要提示词与兜底逻辑（首行摘要 + 三段结构）。 | None. |
| `tests/test_daily_news.py` | DONE | 更新单元测试断言摘要与结构。 | None. |
| `docs/新闻要点摘要任务书.md` | DONE | 新增任务书与进度记录。 | None. |
| `README.md` | DONE | 补充每日新闻首行摘要说明与改进清单。 | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-28
**Task:** 测试：使用 Z-Image 生成每日新闻（count=10）。
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `data/posts/*/post.json` | DONE | 运行 `auto --title "每日新闻" --count 10`（Z-Image）后生成多条 post；其中 17 条有 Z-Image 配图，5 条保存为草稿，12 条停留在 `draft`，5 条失败。 | 如需“正好 10 条已保存草稿”，建议单独对 `draft` 状态的 post 执行 `apps.cli run <post_id>` 或延长 `--wait-timeout`/`--login-hold` 重新跑。 |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- 命令分两次执行，均在本地超时中断；Z-Image 配图仍已落盘（`data/posts/<id>/assets/ai_aliyun_*.png`）。

### 2026-01-28
**Task:** Document Aliyun Bailian text-to-image model support (Qwen-Image/Z-Image/Wanxiang) and URL-download behavior.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Documented supported model families, call mode, and URL download note. | None. |
| `docs/AI生图任务书.md` | DONE | Added model list, call mode, URL download note, and progress entry. | None. |
| `docs/aliyun_image_api-key.example.md` | DONE | Added model examples note. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- Verified Bailian docs for Qwen-Image/Z-Image/Wan2.x endpoints and URL outputs.

### 2026-01-28
**Task:** Remove web-based ChatGPT Images generation and switch to Aliyun DashScope API image generation.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Removed `chatgpt_images` provider and added `aliyun` provider with retry/abandon logic. | Run `auto --count 3` a few times to confirm no stalls. |
| `src/images/aliyun_images.py` | DONE | Added DashScope (百炼) text-to-image API call + download-to-assets implementation. | If model/size changes, update env vars in README. |
| `README.md` | DONE | Removed ChatGPT Images workflow docs; documented Aliyun provider and one-line commands. | Keep examples in sync with preferred timeouts. |
| `docs/AI生图任务书.md` | DONE | Rewrote task doc for Aliyun API; removed webpage automation approach. | None. |
| `docs/图片生成失败重试任务书.md` | DONE | Updated retry spec to target Aliyun API generation. | None. |
| `apps/inspect_chatgpt_images.py` | DONE | Deleted (no longer used). | — |
| `apps/e2e_test_chatgpt_images.py` | DONE | Deleted (no longer used). | — |
| `tests/test_chatgpt_images.py` | DONE | Deleted (no longer used). | — |
| `tests/test_chatgpt_image_retry.py` | DONE | Deleted (no longer used). | — |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- The old ChatGPT Images implementation was removed because it was unstable (Cloudflare/网页 UI 变更/自动化登录问题).
- The new Aliyun provider uses `docs/aliyun_image_api-key.md` (gitignored) or `ALIYUN_IMAGE_API_KEY` env var.

### 2026-01-27 13:44
**Task:** Re-run `auto --count 3` three times with ChatGPT images.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `data/posts/498905ce5476495cb4d99fc4678ff72a/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/23499b32f9a24494a08f84b0ccc9df41/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/02492089aceb46cb84b4e983aee1300a/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/779f220f4d664ca69d3d1b54d20834df/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/92dda163aba14b938db489f8f903ec09/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/94ce8d3339ae42fa96a893d94cf6dca8/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/23d74a0f4b764d8a949851020ecadd02/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/f6c31bae7f614d53a3ab0bb1bfcc50cb/post.json` | DONE | Draft saved with image. | None. |
| `data/posts/8276c364308d425ab649f9d99dc9be4e/post.json` | DONE | Draft saved with image. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this batch. | Continue logging. |

**Notes**
- Each run used `auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*"` with ChatGPT images and CDP.
- All 9 drafts saved (`saved_draft`).

### 2026-01-27 12:35
**Task:** Retry ChatGPT image generation when send trigger fails.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/auto_image.py` | DONE | Treat “未能触发生成（发送按钮/快捷键均失败）” as retryable so it won’t abort the batch early. | Re-run `auto --count 3` 3–4 times. |
| `tests/test_chatgpt_image_retry.py` | DONE | Added retry test for send-trigger failure. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-27 12:27
**Task:** Fix CDP ChatGPT Images navigation abort during `auto`.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Added CDP fallback when `page.goto` fails (reuse existing images tab or open a new tab) to avoid `net::ERR_ABORTED`. | Re-run `auto --count 3` multiple times to confirm stability. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-27 12:22
**Task:** Don’t mark saved drafts as failed when optional draft-box screenshots/timeouts happen.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | After `verify_draft_saved` succeeds, all draft-box navigation (open tab / cover wait / screenshot / html / verify) is now best-effort and won’t flip the execution to `failed`. | Re-run `apps.cli retry <post_id>` once to confirm result becomes `saved_draft`. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-27 11:53
**Task:** Run `auto` with ChatGPT images for 3 daily-news drafts.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `data/posts/9f8fd2943cf64364963d603ed66ba7c0/post.json` | DONE | Draft saved with uploaded image via ChatGPT images. | None. |
| `data/posts/a8295d26470c4632a96947924563e10d/post.json` | DONE | Draft saved with uploaded image via ChatGPT images. | None. |
| `data/posts/78834a70b4fb45ca9fc136846346d572/post.json` | DONE | Draft saved with uploaded image via ChatGPT images. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this run. | Continue logging. |

**Notes**
- Command: `.\.venv\Scripts\python -m apps.cli auto --title "每日新闻" --count 3 --assets-glob "empty/pics/*" --login-hold 0 --wait-timeout 600`
- Result: 3/3 drafts saved (`saved_draft`). Evidence saved under each post’s `evidence/` folder.

### 2026-01-27 13:19
**Task:** Fix ChatGPT Images prompt sending (multiline paste + reliable send button click) and verify `auto --count 3`.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Contenteditable input now uses `keyboard.insert_text()` (paste-style) to avoid early-send on newline; send button click scans multiple matches to avoid picking a hidden/disabled first match. | If ChatGPT UI changes again, re-check selectors in `_find_prompt_box` / `_click_send_if_present`. |
| `tests/test_chatgpt_image_retry.py` | DONE | Still passes after the ChatGPT input/send changes. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry with real run IDs. | Continue logging. |

**Notes**
- E2E ChatGPT Images: `apps.e2e_test_chatgpt_images` saved `data/posts/91c54288046f450dae1a9cfca04de7dc/assets/ai_chatgpt_20260127_041752.webp` via `method=request_download`.
- Real run: `apps.cli auto --title \"每日新闻\" --count 3` → saved drafts for post_ids:
  - `831f7804fb9348eebee3eb2ce54f144b`
  - `73e528d838bc4a4c88d46c76183b6f0b`
  - `c4c1e13760984aa78f0eab8019d1b7a4`
- Tests: `pytest -q` → `41 passed`.

### 2026-01-27 11:27
**Task:** Retry ChatGPT image generation on timeout (max 3) and skip the news item after repeated failures.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/图片生成失败重试任务书.md` | DONE | Added spec for timeout-retry + give-up behavior and how we persist attempts/errors. | None. |
| `src/images/auto_image.py` | DONE | Added `CHATGPT_IMAGE_MAX_ATTEMPTS` retry loop for `chatgpt_images`; after max attempts, raise `ImageGenerationAbandoned` with attempts/errors. | Consider also surfacing these env vars in README if you want end-user knobs. |
| `src/workflow/create_post.py` | DONE | In daily-news batch mode, pick extra candidates and skip posts when image generation is abandoned; persist failed post with `platform.image_generate` metadata. | Observe a few real runs (`--count 3`) and confirm count can still be satisfied in practice. |
| `tests/test_chatgpt_image_retry.py` | DONE | Added unit tests covering retry success, give-up after max attempts, and no-retry for non-timeout errors. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- Env knobs: `CHATGPT_IMAGE_MAX_ATTEMPTS` (default 3), `CHATGPT_IMAGE_RETRY_SLEEP_S` (default 2s).

### 2026-01-26 14:08
**Task:** Avoid ChatGPT image placeholder selection that causes detached screenshot errors.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Skip placeholder/unstable images during fallback picking (treat evaluate errors as skip) and collect more baseline `img` srcs to reduce false positives. | Re-run `auto` with `--count 3` a few times to confirm images consistently save. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- Prior run failed with `Locator.screenshot: Element is not attached to the DOM` after selecting a `data:image/gif` placeholder; the picker now ignores those and requires stable loaded dimensions.

### 2026-01-25 16:57
**Task:** Fix delete-drafts SyntaxError and run a real delete.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Fixed indentation around the delete list-change fallback so the delete loop runs. | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry and the delete run result. | Continue logging. |

**Notes**
- Run: `.\.venv\Scripts\python -m apps.cli delete-drafts --limit 5 --yes`
- Result: deleted 5/92 image drafts; event `data/events/f283ccc98e724605a13febf4ad372335.json`.

### 2026-01-25 18:44
**Task:** Cap ChatGPT image timeouts to 3 minutes in the one-line commands.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Updated the one-line “GPT 生图 → 保存草稿” commands to set `CHATGPT_CHALLENGE_TIMEOUT_S=180` and `CHATGPT_MANUAL_TIMEOUT_S=180` (so ChatGPT-related waits don’t exceed ~3 minutes). | None. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

**Notes**
- README 一行指令已整理为单行（避免重复行）。

### 2026-01-26 11:47
**Task:** Reduce missing draft images and cap ChatGPT challenge waits.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added upload-in-progress detection and a short settle wait before saving drafts to avoid saving while uploads are still processing. | Re-run `auto` with `XHS_UPLOAD_SETTLE_S=5` (default) to confirm missing-image drafts no longer occur. |
| `src/images/chatgpt_images.py` | DONE | Defaulted `CHATGPT_CHALLENGE_TIMEOUT_S`/`CHATGPT_MANUAL_TIMEOUT_S` to 180s to prevent long stalls when ChatGPT is blocked. | If you still see long gaps, consider lowering `CHATGPT_IMAGE_TIMEOUT_S` or checking LLM latency. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-25 16:50
**Task:** Fix draft deletion flow (confirm click + list change detection).
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Confirm dialog click now targets visible confirm buttons first; deletion list change detection uses title+time key to avoid false timeouts on duplicate titles. | Run `apps.cli delete-drafts --dry-run` or a limited delete to validate. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-25 16:21
**Task:** Add GPT image commands for “每日假新闻”.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added full and one-line commands to generate GPT images for “每日假新闻” and save drafts. | Run the new commands if you want a fresh verification. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-25 12:46
**Task:** Provide single-line GPT image → XHS draft command in README.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added a one-line PowerShell command that launches Chrome with CDP, waits for manual verification, then runs `auto` with ChatGPT Images. | Use it to run the full flow end-to-end. |
| `CODING_PROGRESS.md` | DONE | Logged this entry. | Continue logging. |

### 2026-01-25 12:11
**Task:** Shorten ChatGPT image timeout and stabilize prompt input on images page.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Prefer `#prompt-textarea`/ProseMirror for ChatGPT Images input; add robust contenteditable fill path and guard when prompt isn't written. | Re-run `apps.e2e_test_auto_full` (count=3) to confirm prompt send works reliably. |
| `apps/e2e_test_auto_full.py` | DONE | Default `--image-timeout` reduced to 180s and prompt omitted unless non-empty. | Use shorter timeouts when re-testing. |
| `README.md` | DONE | Updated ChatGPT Images timeout example to 180s. | Keep examples aligned with preferred timeouts. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Continue logging. |

**Notes**
- E2E run was interrupted by user before completion.

### 2026-01-24 11:35
**Task:** Fix ChatGPT Images “no_image” false-negative after prompt.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Improve image picking: instead of scanning only the last 50 `<img>`, mark/select the largest visible new `<img>` (generated image) and fall back to a larger tail scan. | Re-run `apps.e2e_test_chatgpt_images` once CDP port is confirmed open (`/json/version` reachable). |

**Tests**
- `pytest -q` (37 passed)

### 2026-01-24 10:05
**Task:** Add runnable E2E test scripts for ChatGPT Images and full auto flow.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/e2e_test_chatgpt_images.py` | DONE | Added a CDP-based script that generates one image and verifies the saved file isn't HTML/screenshot. | Run with your already-open `--remote-debugging-port=9222` Chrome to validate the method is `request_download`/`page_fetch*`. |
| `apps/e2e_test_auto_full.py` | DONE | Added an end-to-end script that runs `apps.cli auto` and checks `post.json` for `platform.image.method` + local asset existence. | Use the same CDP Chrome (ChatGPT + XHS) for stable runs. |
| `README.md` | DONE | Documented the two new E2E scripts under the ChatGPT Images section. | — |

**Tests**
- `pytest -q` (37 passed)

### 2026-01-23 20:10
**Task:** Fix ChatGPT Images blurred/in-progress capture.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Stop relying on UI screenshots; prefer downloading original image bytes (`http/https` via authenticated request, `blob/data` via in-page fetch). Also record `src_url` in meta and ignore tiny icon images. | Run one end-to-end `auto` with CDP-enabled Chrome to confirm the saved file is a crisp image (not blurred preview). |
| `tests/test_chatgpt_images.py` | DONE | Added a small unit test for data URL parsing. | — |
| `README.md` | DONE | Updated `chatgpt_images` description and documented `CHATGPT_DOWNLOAD_TIMEOUT_S`. | — |
| `docs/实现计划书.md` | DONE | Noted the blur root-cause and the download-based fix. | — |
| `docs/AI生图任务书.md` | DONE | Updated “下载图片到本地” to prefer `currentSrc` download over screenshot. | — |

**Tests**
- `pytest -q` (37 passed)

### 2026-01-23 11:50
**Task:** Add CDP attach mode to avoid re-triggering Cloudflare; keep the whole pipeline automated.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Added `CHATGPT_CDP_URL` support to attach to an already opened Chrome tab and reuse `https://chatgpt.com/images` without relaunching. | Validate prompt send + image capture works on your account. |
| `src/publish/playwright_steps.py` | DONE | Added `XHS_CDP_URL` support so XHS automation can reuse the same Chrome instance (avoids “profile in use” failures). | Run end-to-end `auto` and confirm `saved_draft`. |
| `README.md` | DONE | Documented the recommended CDP workflow (launch Chrome with `--remote-debugging-port=9222`, set `CHATGPT_CDP_URL` + `XHS_CDP_URL`). | None. |
| `docs/AI生图任务书.md` | DONE | Added CDP workflow notes and the need to set `XHS_CDP_URL` for full automation. | None. |

**Notes**
- This does not bypass Cloudflare; it reduces how often Cloudflare is triggered by avoiding automation relaunch/navigation.

### 2026-01-23 11:10
**Task:** Handle Cloudflare blocking on ChatGPT Images by adding a manual fallback flow; update docs.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | When automation is stuck on Cloudflare challenge beyond `CHATGPT_CHALLENGE_TIMEOUT_S`, fall back to a manual mode: open ChatGPT Images in normal Chrome and wait for a downloaded image to appear under `data/posts/<post_id>/assets/`. | Run an end-to-end `auto` and confirm `ai_chatgpt_*.png` is produced and uploaded. |
| `README.md` | DONE | Documented Cloudflare limitation + manual fallback env vars. | Keep README aligned if selector changes. |
| `docs/AI生图任务书.md` | DONE | Clarified that Cloudflare cannot be bypassed and documented manual downgrade strategy. | None. |

**Notes**
- Why: In Playwright-controlled Chrome, ChatGPT may trigger Cloudflare checks and show a blank/loading page; automation cannot bypass it.
- Next: rerun `apps.cli auto` with `IMAGE_PROVIDER=chatgpt_images` and set `CHATGPT_CHALLENGE_TIMEOUT_S=30` to quickly enter manual mode when blocked.

### 2026-01-22 20:30
**Task:** Make ChatGPT Images automation resilient to Cloudflare challenge; update docs.
**Git:** `main` (dirty)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | Added Cloudflare challenge detection + wait loop (default 600s, configurable via `CHATGPT_CHALLENGE_TIMEOUT_S`); prompt box wait to reduce race conditions. | Run one real image generation while manually completing challenge when prompted; then confirm image is saved under `data/posts/<post_id>/assets/`. |
| `README.md` | DONE | Documented `CHATGPT_CHALLENGE_TIMEOUT_S` and clarified ChatGPT Images prerequisites. | None. |
| `docs/AI生图任务书.md` | DONE | Added Cloudflare challenge handling to failure strategies. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Smoke run in this environment hit Cloudflare challenge; the code now waits and prompts for manual completion instead of failing silently.

### 2026-01-22 19:10
**Task:** Add ChatGPT Images（网页生图）作为自动配图来源，提升“每日新闻”等场景配图相关性。
**Git:** `main` (dirty)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/images/chatgpt_images.py` | DONE | 新增基于 Playwright + 持久化 Chrome profile 的生图流程：打开 `chatgpt.com/images`、写入提示词、等待图片出现、截图落盘，并在 `data/posts/<post_id>/evidence/` 留证。 | 用已登录 ChatGPT 的 profile 现场验证；若 UI 变更导致找不到输入框/图片，基于 evidence 调整选择器。 |
| `src/images/auto_image.py` | DONE | 增加 `IMAGE_PROVIDER=chatgpt_images` 分支：无图时改走 ChatGPT Images 生图；支持 `CHATGPT_IMAGE_TIMEOUT_S`。 | 如需“失败自动回退到 pexels”，再补充链式 fallback。 |
| `apps/inspect_chatgpt_images.py` | DONE | 新增探测脚本：检查 ChatGPT Images 登录态/输入框是否存在，并自动落盘 HTML/截图证据。 | 选择器失效时先跑该脚本采集证据再修。 |
| `tests/test_chatgpt_images.py` | DONE | 新增提示词构造单测（前缀清理 + 安全约束）。 | None. |
| `docs/AI生图任务书.md` | DONE | 补充“复用已登录 Chrome profile（Default1）”与实现可配置项说明。 | 待补充：登录态下输入框/生成区/下载区的更精确定位（如需要）。 |
| `docs/实现计划书.md` | DONE | 记录 AI 生图功能接入与待端到端验证项。 | 跑一次端到端：`每日新闻 + empty/pics/* + IMAGE_PROVIDER=chatgpt_images`，确认图片确实写入并上传草稿。 |
| `README.md` | DONE | 增加 ChatGPT Images 配置示例与 `apps/inspect_chatgpt_images.py` 用法。 | None. |
| `CODING_PROGRESS.md` | DONE | 追加本条进度记录。 | Keep appending after future work. |

**Notes**
- Tests: `pytest -q` → 36 passed.
- MCP: `chatgpt.com/images` 在 MCP 会话里仍显示未登录（独立 profile），因此实现改为 Playwright 复用你已登录的 `chrome-profile/Default1`。

### 2026-01-07 15:25
**Task:** Add delete-drafts description and examples to README.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added delete-drafts capability to feature list, added example commands, and clarified profile scope. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

### 2026-01-07 15:10
**Task:** Delete all drafts across all tabs.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/删除草稿功能任务书.md` | DONE | Logged full delete-drafts run results (image 45/45, video/long 0). | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Manual run: `apps.cli delete-drafts --all --yes --login-hold 120` deleted 45/45 image drafts; video/long both 0.

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

### 2026-01-06 17:11
**Task:** Investigate delete-drafts tab mismatch report; update taskbook.
**Git:** `main (dirty)`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/删除草稿功能任务书.md` | DONE | Documented that `draft_type=image` opens 图文 and only `--all` cycles to 视频/长文; long-tab view is not the root failure. | If deletion still stalls, improve post-delete list refresh wait/confirm dialog detection. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No runtime test executed in this step.

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

### 2026-01-06 11:35
**Task:** Update README with fake news examples and re-run unit tests.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `README.md` | DONE | Added “每日假新闻” feature notes and example command. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: `pytest tests/test_fake_news.py` (2 passed).

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

### 2026-01-06 09:30
**Task:** Draft fake news workflow task doc.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/假新闻任务书.md` | DONE | Added requirements, flow, acceptance criteria, and task list for “每日假新闻”. | Await user confirmation before coding. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- No code changes requested yet; documentation only.

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

### 2026-01-05 14:05
**Task:** Investigate daily news image mismatch; update taskbook with findings.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/增加图片api后的错误修正任务书.md` | DONE | Added verification that image query uses post.title/topics; when title/topic is “每日新闻” it leads to generic news images. | If needed, change query builder to prefer picked news title or filter out “每日新闻”. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Evidence: `post.platform.image.query_original` includes “每日新闻” when title/topics contain it; example `data/posts/a0333d5285354ca8b946a9ff82704130/post.json`.

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

### 2026-01-05 11:25
**Task:** Daily news smoke test for length/structure.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Updated test status: length OK, structure missing headings. | Tighten prompt to require explicit headings or add post-check/second pass. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Smoke test: `apps.cli create --title "每日新闻" --prompt "美国时政"` produced body_len=306, but no explicit “新闻内容/我的点评” sections.

### 2026-01-05 11:12
**Task:** Run tests after daily news prompt/news field updates.
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Marked test status as in-progress (unit tests done, smoke pending). | Run a local smoke test for "每日新闻" when ready. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

**Notes**
- Tests: `pytest -q` → 18 passed.

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

### 2026-01-05 10:20
**Task:** Draft taskbook for expanding body length requirements (wait for review before coding).
**Git:** `main`

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/正文内容扩充任务书.md` | DONE | Added requirements/constraints/plan for: body >=300; daily news news>=200 + review>=100; no fabrication; prompt + token_max changes (optional fallback). | Await your review/approval; then implement changes in `src/llm/generate.py` and `src/workflow/create_post.py` (and possibly `src/news/daily_news.py`). |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future work. |

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

### 2026-01-04 12:38
**Task:** Update local LLM API key and re-test authentication.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/config.py`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.md` | DONE | Updated local `api_key` (git-ignored). | Ensure the key is valid for the configured provider; rerun `apps.cli create` until正文正常生成。 |

**Notes**
- Test result: `apps.cli create` still returns `401 authentication_error (invalid api key)` on DeepSeek URL, and OpenAI URL also reports `invalid_api_key` for this key.
- Next steps: Confirm which platform issued this key; then set the matching `LLM_BASE_URL` + `LLM_MODEL` for that platform.

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

### 2026-01-04 11:52
**Task:** Align LLM example base URL with DeepSeek doc.
**Git:** `backup_2026-1-2-1` (modified: `docs/llm_api-key.example.md`, `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.example.md` | DONE | Updated example to use `base_url="https://api.deepseek.com/v1"` + `model="deepseek-chat"`. | If you use a different provider, replace base_url/model accordingly. |

**Notes**
- Even with correct base_url, current LLM calls still return 401 (key invalid for that provider). Confirm the key is issued by DeepSeek and active; otherwise change `LLM_BASE_URL` to match the key issuer.

### 2026-01-04 11:45
**Task:** Set local LLM API key config (do not commit); re-check connectivity.
**Git:** `backup_2026-1-2-1` (modified: `src/publish/playwright_steps.py`; untracked: `AGENT.md`, `CODING_PROGRESS.md`, `docs/llm_example/`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/llm_api-key.md` | DONE | Updated local LLM config file (ignored by git via `.gitignore` rule `docs/*api-key.md`). | Replace with a valid key for the configured `base_url` to stop 401 errors. |

**Notes**
- LLM smoke test still fails: `401 authentication_error (invalid api key)` when calling `https://api.deepseek.com/v1`.
- Do not commit/push `docs/llm_api-key.md`; it is ignored and not tracked.

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

### 2026-06-19 14:02
**Task:** Audit and repair API availability, local cache paths, and Xiaohongshu draft publishing.
**Git:** `main` (modified: `.gitignore`, `README.md`, `apps/gui.py`, `requirements.txt`, `scripts/build_gui_exe.ps1`, `src/images/auto_image.py`, `src/publish/mcp_driver.py`, `src/publish/playwright_steps.py`, `tests/test_auto_image.py`, `tests/test_gui.py`; untracked tests: `tests/test_mcp_driver.py`, `tests/test_playwright_profile_config.py`, `tests/test_playwright_upload_count.py`)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `.gitignore` | DONE | Ignored workspace-local npm, pip, and Playwright browser caches. | None. |
| `README.md` | DONE | Documented workspace-local cache env vars and updated default image-provider wording to Pexels-first. | None. |
| `apps/gui.py` | DONE | Changed GUI default image provider from Aliyun to Pexels after live quota checks. | Switch back manually only if Aliyun paid quota is available. |
| `requirements.txt` | DONE | Added `certifi` for stable HTTPS certificate verification. | None. |
| `scripts/build_gui_exe.ps1` | DONE | Forces pip cache into `.pip-cache` under the workspace. | None. |
| `src/images/auto_image.py` | DONE | Uses `certifi` HTTPS context for Pexels search/download to fix local SSL certificate failures. | None. |
| `src/publish/mcp_driver.py` | DONE | Moves Chrome DevTools MCP profile and npm cache defaults into the workspace instead of user home / C drive. | None. |
| `src/publish/playwright_steps.py` | DONE | Keeps system Chrome as default when a custom XHS profile dir is set, fixes upload-count regex, improves draft button detection/clicking, and records stronger evidence snapshots. | Coordinate fallback may need retuning if XHS changes the publish UI layout. |
| `tests/test_auto_image.py` | DONE | Added tests proving Pexels HTTP calls pass an explicit TLS context. | None. |
| `tests/test_gui.py` | DONE | Added regression coverage for the Pexels default provider. | None. |
| `tests/test_mcp_driver.py` | DONE | Added regression coverage that MCP defaults to a workspace-local browser profile. | None. |
| `tests/test_playwright_profile_config.py` | DONE | Added regression coverage for custom XHS profile + Chrome channel resolution. | None. |
| `tests/test_playwright_upload_count.py` | DONE | Added regression coverage for XHS upload-count text matching. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this repair/audit entry. | Keep appending after future coding work. |

**Notes**
- Tests/Lint: `.\.venv\Scripts\python.exe -m pytest -q` -> 69 passed.
- Live API smoke: Aliyun LLM and Aliyun image generation both returned `403 AllocationQuota.FreeTierOnly` (free tier exhausted); ppinfra fallback LLM OK; NewsAPI OK; Pexels OK after TLS fix; GDELT timed out from this network.
- Xiaohongshu smoke: real retry for diagnostic post `75256f74d0694feebb1a59a72a76441b` reached `saved_draft`; evidence under `data/posts/75256f74d0694feebb1a59a72a76441b/evidence/092a4c4ebfc342d5bd403cdbc26a9462/`.
- Risks/Assumptions: API keys were checked by live minimal requests only, not by provider billing dashboards; a diagnostic draft with a question-mark title may remain in the XHS draft box because the one-off local test script used a PowerShell stdin encoding path.
- Next steps: If you want Aliyun generation again, add paid quota or disable free-tier-only mode in the Aliyun console; otherwise keep Pexels as the image default and ppinfra as the working LLM fallback.

### 2026-06-19 14:26
**Task:** Add Aliyun free model options, provider switching, wan2.7 image support, redesigned GUI auto-posting console, and docs.
**Git:** `main` (modified files from the previous repair entry remain uncommitted; this entry covers the new GUI/model/docs changes)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Rebuilt the Tkinter GUI as a publishing console with auto-posting controls for LLM provider, LLM model, image provider, and Aliyun image model. | Manual visual review is useful if you want spacing tweaks after opening the desktop window. |
| `src/config.py` | DONE | Added the Aliyun free LLM model catalog, changed default Aliyun LLM to `qwen3.7-plus`, and added `LLM_PROVIDER=auto/aliyun/ppinfra`. | Keep the catalog updated if the Aliyun console free list changes. |
| `src/images/aliyun_images.py` | DONE | Changed default image model to `wan2.7-image` and fixed wan2.6+ protocol detection so wan2.7 uses the new multimodal/image-generation flow. | None. |
| `src/workflow/create_post.py` | DONE | Updated image model mismatch guidance to recommend `wan2.7-image` / `wan2.7-image-pro`. | None. |
| `tests/test_aliyun_llm_models.py` | DONE | Added regression coverage for the Aliyun free model list and provider-only selection behavior. | None. |
| `tests/test_gui.py` | DONE | Added regression coverage for GUI model option catalogs and provider env override generation. | None. |
| `tests/test_aliyun_image_models.py` | DONE | Added regression coverage that `wan2.7-image` uses the multimodal sync endpoint with `n=1`. | None. |
| `docs/模型与GUI供应商配置.md` | DONE | Added a dedicated guide for GUI supplier/model selection, env mappings, and recommended combinations. | None. |
| `docs/llm_api-key.example.md` | DONE | Rewrote the fallback LLM example around ppinfra and linked Aliyun config to the GUI/model guide. | None. |
| `docs/aliyun_image_api-key.example.md` | DONE | Rewrote the DashScope image example and documented `wan2.7-image` / `wan2.7-image-pro`. | None. |
| `docs/图形界面任务书.md` | DONE | Appended the 2026-06-19 GUI publishing-console enhancement notes. | None. |
| `docs/图形界面工作流增强任务书.md` | DONE | Updated old default values to `qwen3.7-plus` and `wan2.7-image`. | None. |
| `docs/AI生图任务书.md` | DONE | Updated image defaults and added Wan 2.7 model notes. | None. |
| `docs/图片查找功能.md` | DONE | Updated Aliyun image default model documentation. | None. |
| `docs/生图事件摘要任务书.md` | DONE | Updated examples to reference Wan 2.7 image models. | None. |
| `README.md` | DONE | Updated GUI description, default model names, provider selection notes, and quick examples. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this entry. | Keep appending after future coding work. |

**Notes**
- Tests/Lint: `.\.venv\Scripts\python.exe -m py_compile apps\gui.py src\config.py src\images\aliyun_images.py src\workflow\create_post.py` -> passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 76 passed.
- Docs: Added `docs/模型与GUI供应商配置.md` and expanded related docs in `docs/` per the project documentation requirement.
- External reference: Aliyun official Wan 2.7 image API docs show `wan2.7-image` / `wan2.7-image-pro` use `multimodal-generation/generation` for sync calls and `image-generation/generation` for async calls.
- Risks/Assumptions: GUI visual layout has automated import/unit coverage but was not manually opened in this session; API quota state still depends on provider console balances and cannot be guaranteed by code alone.

### 2026-06-19 14:41
**Task:** Test GUI news automation, document results, and fix daily-news prompt leakage found during live testing.
**Git:** `main` (working tree already contained the earlier repair/model/GUI changes; this entry covers the new test report and prompt-leak regression fix)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added `_daily_news_body_has_prompt_leak()` and fallback handling for single/batch daily-news flows when an LLM echoes prompt instructions into publishable body text. | None. |
| `tests/test_daily_news.py` | DONE | Added regression tests for prompt-leak detection and daily-news safe fallback behavior. | None. |
| `docs/测试报告-2026-06-19-GUI新闻自动化.md` | DONE | Added a full test report covering key presence checks, GUI smoke tests, full pytest, live daily-news generation, and XHS dry-run evidence. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this testing/fix entry. | Keep appending after future coding work. |

**Notes**
- Tests/Lint: `.\.venv\Scripts\python.exe -m py_compile apps\gui.py src\config.py src\images\aliyun_images.py src\workflow\create_post.py` -> passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 79 passed.
- Live generation: first test post `bd6bfa4a48bb414cad83670097ca71ff` reproduced prompt leakage; after the fix, new post `0ad0d7e865e64bfd9b3159e6086c2bb0` validated `ok`, had 3 Pexels assets, and `prompt_leak=False`.
- XHS dry-run: `apps.cli run 0ad0d7e865e64bfd9b3159e6086c2bb0 --dry-run --login-hold 0 --wait-timeout 120 --force` opened the creator publish page, matched `上传图文`, matched `button.upload-button`, and skipped upload/fill/save as expected.
- Evidence: `data/posts/0ad0d7e865e64bfd9b3159e6086c2bb0/evidence/5e860106014a412c8d2eac60a6d6763c/`.
- Risks/Assumptions: This test intentionally did not save a real XHS draft; it used dry-run for the browser automation portion to avoid changing the account draft box.

### 2026-06-19 15:01
**Task:** Complete the live news generation-to-XHS-draft chain and add GUI post-title visibility.
**Git:** `main` (working tree still contains earlier repair/model/docs changes; this entry covers the final live-chain fix, GUI title list, and updated docs/tests)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Added recent-post summaries so the draft/run page lists each post as title + status + post_id, and safely extracts the id from either the label or a raw id. | Open the GUI manually only if visual spacing needs refinement. |
| `tests/test_gui.py` | DONE | Added regression coverage for recent-post title/status labels and id extraction from GUI choices. | None. |
| `src/publish/playwright_steps.py` | DONE | Fixed the live draft save path by prioritizing the bottom "暂存离开"/draft action coordinate and keeping ranked text-candidate fallbacks. | Re-check if XHS significantly changes the publish page layout. |
| `tests/test_playwright_draft_button.py` | DONE | Added regression tests for bottom draft-button targeting and candidate selection. | None. |
| `README.md` | DONE | Documented that GUI draft handling now shows title + status + post_id for recent posts. | None. |
| `docs/模型与GUI供应商配置.md` | DONE | Updated GUI provider/model guide to mention the title/status/post_id recent-post selector. | None. |
| `docs/测试报告-2026-06-19-GUI新闻自动化.md` | DONE | Expanded the report from dry-run coverage to a real generated-news, image-upload, save-draft, and draft-box verification run. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this live-chain verification entry after invoking the file-progress-followup workflow. | Keep appending after future coding work. |

**Notes**
- Tests/Lint: `.\.venv\Scripts\python.exe -m py_compile apps\gui.py src\publish\playwright_steps.py src\workflow\create_post.py src\config.py src\images\aliyun_images.py` -> passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 84 passed.
- Live chain: first non-dry-run `apps.cli auto` generated post `19147964f9214ab69fb1eb90f2a1bcc0` but draft verification failed because the old click path hit a preview text node; after the button-targeting fix, `apps.cli retry 19147964f9214ab69fb1eb90f2a1bcc0 --force --login-hold 0 --wait-timeout 180` returned `saved_draft`.
- XHS evidence: title `每日新闻｜The Korean Tele`, local status `saved_as_draft`, execution `87f704791e314a509b7634e8b484e3b8`, evidence under `data/posts/19147964f9214ab69fb1eb90f2a1bcc0/evidence/87f704791e314a509b7634e8b484e3b8/`; verified steps include `upload_images`, `fill_title_body`, `save_draft`, `verify_draft_saved`, and `verify_draft_box_item`.
- Risks/Assumptions: The project automation intentionally saves into the Xiaohongshu draft box rather than clicking public "发布"; manual final review is still recommended before public posting.

### 2026-06-20 00:22
**Task:** Fix daily-news Chinese output/source handling, add GUI draft upload-state details and quick launchers, then complete live delete + two-draft API/AI-image test.
**Git:** `main` (working tree already had many pre-existing modified/untracked files; this entry covers the files changed for this task)

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Strengthened daily-news prompt rules, added URL stripping, Chinese fallback body/title handling for English items, final source-line cleanup, and local `source_url` persistence. | Consider a future provider-side translation retry if you want less generic offline fallback text when LLM output is rejected. |
| `apps/gui.py` | DONE | Added uploaded/uploaded_at/updated/execution/body-preview fields to recent-post summaries, richer draft choices/details, XHS quick-open button, and `target=image` creator URL. | Manual visual tuning optional after opening the desktop GUI. |
| `tests/test_daily_news.py` | DONE | Added regressions for Chinese translation prompt requirements, offline English fallback, no URL in body, and URL persistence in local metadata for single/batch daily news. | None. |
| `tests/test_gui.py` | DONE | Added regressions for uploaded-state labels, detail text, creator URL, and workspace-local quick-launch scripts. | None. |
| `docs/新闻中文化与GUI草稿状态修复-2026-06-19.md` | DONE | Documented the new content rules, GUI behavior, quick launchers, tests, and live XHS results. | None. |
| `scripts/start_gui.ps1` | DONE | Added workspace-local PowerShell launcher for `python -m apps.gui`. | None. |
| `scripts/open_xhs_creator.ps1` | DONE | Added workspace-local Chrome launcher using `data/browser/chrome-profile` and the XHS image publish URL. | None. |
| `Start-GUI.cmd` | DONE | Added double-click wrapper for the GUI PowerShell launcher. | None. |
| `Open-XHS-Creator.cmd` | DONE | Added double-click wrapper for the XHS creator PowerShell launcher. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this task entry after invoking the file-progress-followup workflow. | Keep appending after future coding work. |

**Notes**
- Tests/Lint: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_daily_news.py tests/test_gui.py -q` -> 45 passed; `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` -> 99 passed; PowerShell script parse checks passed for both new `.ps1` launchers.
- Live delete test: `delete-drafts --all --dry-run` found `image total=42`; `delete-drafts --all --yes` deleted `42/42`; follow-up dry-run showed image/video/article all `0`.
- Live save test: final XHS draft box dry-run shows exactly 2 image drafts: GUI path `e2474373af9d4457847b7230d703715e` (`每日新闻｜科技动态`, NewsAPI/Business Insider, Aliyun `wan2.7-image`) and CLI path `2fc339424dc1446e8a544227f6f23fad` (`每日新闻｜经济动态`, NewsAPI/Pluralistic.net, Aliyun `wan2.7-image`).
- Risks/Assumptions: GDELT returned `HTTP Error 429` during this run, so both final API news drafts used NewsAPI. A discarded PowerShell-pipe encoding attempt and duplicate-attempt local `data/posts/*` artifacts remain locally, but the platform draft box was cleaned to the final 2 visible drafts.
- Next steps: Open `Start-GUI.cmd` for manual visual review if desired; before public posting, review the two XHS drafts in the browser because this workflow intentionally saves drafts rather than clicking public publish.

### 2026-06-20 00:34
**Task:** Add usage instructions, verify API-key safety, back up the previous version, and push to GitHub.
**Git:** `main` pushed to `origin/main`; backup branch `backup/pre-upload-20260620-002817` and tag `pre-upload-20260620-002817` pushed before the release commit.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Added end-user instructions for GUI startup, CLI news generation, AI image settings, draft deletion, manual review, key safety, and backup checks. | Keep updated when CLI flags or GUI tabs change. |
| `README.md` | DONE | Added the new usage guide and recent repair/testing docs to the docs index. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this upload/backup/key-safety entry after invoking the file-progress-followup workflow. | Keep appending after future coding work. |

**Notes**
- Verification: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` -> 99 passed before the release commit; `git diff --cached --check` passed after fixing doc trailing whitespace.
- Key safety: `git check-ignore -v` confirmed local `docs/*api-key.md`, `.env`, `.env.gui`, and `data/browser/chrome-profile` are ignored; staged content secret scan returned `staged_findings_count=0`; tracked-file secret scan returned `tracked_findings_count=0`; sensitive-path scan of staged names was empty.
- Pushes: backup branch/tag were pushed before commit `cd302c4`; `main` was pushed to `https://github.com/bty3052771076-tech/auto_redbook.git`.
- Risks/Assumptions: The remote push uses the currently configured Git credentials; no API key files were staged or uploaded.

### 2026-06-20 09:18
**Task:** Replace the ugly historical GUI exe with a lightweight launcher for the redesigned `apps.gui` interface.
**Git:** `main` pending launcher-source/docs commit at time of entry.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `scripts/AutoRedbookGuiLauncher.cs` | DONE | Added a small Windows launcher that starts `.venv\Scripts\pythonw.exe -m apps.gui` from the repo root and shows an error dialog if `.venv` is missing. | None. |
| `scripts/build_gui_exe.ps1` | DONE | Replaced the old PyInstaller build with a no-install .NET Framework compile step for `AutoRedbookGUI-Launcher.exe`. | None. |
| `README.md` | DONE | Updated GUI quick-start docs to prefer `AutoRedbookGUI-Launcher.exe` / `Start-GUI.cmd` and mark old `AutoRedbookGUI.exe` as deprecated. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Documented the new launcher, build command, and deprecation of the old full exe. | None. |
| `docs/模型与GUI供应商配置.md` | DONE | Added launcher-based GUI entry instructions. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this launcher replacement entry. | Keep appending after future coding work. |

**Notes**
- Verification: Removed old `AutoRedbookGUI.exe`; built `AutoRedbookGUI-Launcher.exe` via `scripts/build_gui_exe.ps1`; launched it and observed new `pythonw.exe -m apps.gui` processes, then stopped the test processes.
- Key/upload safety: `AutoRedbookGUI*.exe` is ignored by `.gitignore`, so the local launcher binary is not staged/uploaded; only launcher source and docs are intended for Git.

### 2026-06-20 09:24
**Task:** Clean up the workspace while preserving previous news draft records.
**Git:** `main` clean before cleanup; only this progress entry remains after documenting the cleanup.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `build/` | DONE | Removed old PyInstaller build artifacts for the deprecated GUI exe. | Regenerate only if needed via the new launcher build script. |
| `dist/` | DONE | Removed empty old distribution directory. | None. |
| `exports/` | DONE | Removed empty exports directory. | Recreated by workflow if future exports are needed. |
| `logs/` | DONE | Removed old local run logs; execution/evidence records under `data/posts` were preserved. | Use `data/posts/<id>/executions` for durable run evidence. |
| `.pytest_cache/` and `__pycache__/` | DONE | Removed Python/pytest caches outside `.venv` and outside protected draft records. | Caches will be recreated by Python/pytest as needed. |
| `tmp_*.png` / `tmp_diag_dom.png` | DONE | Removed old root-level diagnostic screenshots/DOM dump. | None. |
| `AutoRedbookGUI.spec` | DONE | Removed obsolete PyInstaller spec for the old GUI exe. | Use `scripts/build_gui_exe.ps1` for the new launcher. |
| `data/diagnostics` / `data/indexes` | DONE | Removed empty local data directories. | Workflow can recreate indexes if needed. |
| `data/posts/` | DONE | Protected and preserved all previous local draft records. | Do not delete unless explicitly requested. |
| `CODING_PROGRESS.md` | DONE | Appended this cleanup entry. | Keep appending after future workspace changes. |

**Notes**
- Cleanup safety: deletion script verified every resolved path stayed under `E:\AI\codex\redbook_workflow` and refused anything under `data/posts`.
- Preserved records: `data/posts` remained at 1120 directories after cleanup.
- Removed: 22 cache/build/temp items, about 12.668 MB.
- Verification: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` -> 99 passed.
- Kept intentionally: `data/posts` (draft records), `data/browser` (XHS login/browser profile), `data/events` (audit events), `.venv`, and `AutoRedbookGUI-Launcher.exe`.

### 2026-06-20 11:45
**Task:** Fix daily-news prompt/category title leakage, then complete one CLI and one GUI AI-image draft upload test.
**Git:** `main` with pre-existing modified/untracked files from earlier GUI/headless work; this entry covers the additional quality-gate, docs, and live-test changes.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added prompt-like title rejection, prompt-slice/category title rejection, generic-title rejection, source-field-only English fallback titles, generic-body fallback detection, and Chinese `image_event` fallback for English news. | Add more deterministic English-title mappings over time if new providers return unfamiliar headline patterns. |
| `tests/test_daily_news.py` | DONE | Added regressions for prompt-like title leakage, prompt-category title + generic-body fallback, and NATO/Europe defense news not being misclassified as technology due to user prompt text. | None. |
| `docs/新闻质量闸门与终端GUI实测-2026-06-20.md` | DONE | Documented the quality-gate fix, automated tests, CLI/GUI live upload evidence, and diagnostic samples that should not be treated as final accepted drafts. | None. |
| `README.md` | DONE | Added the new quality-gate/live-test report to the docs index. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Regression verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_gui.py tests\test_cli_headless.py -q` -> 65 passed after the quality-gate changes.
- CLI live accepted sample: `68f348cdefa248d89aa35e049e62df26`, title `防晒审批迎来进展`, `uploaded=True`, `status=saved_as_draft`, XHS draft box `verified_title=True cover_ready=True`, image provider `aliyun`, model `wan2.7-image`.
- GUI live accepted sample: `53e095f286384eae8f75b61e9f91dc89`, generated by launching `apps.gui`, filling the auto tab, invoking the GUI auto button, and waiting for the GUI subprocess; `uploaded=True`, `status=saved_as_draft`, XHS draft box `verified_title=True cover_ready=True`, image provider `aliyun`, model `wan2.7-image`.
- Diagnostic samples left in local/XHS drafts: `6058671d3d5e47e9bfc6066d799c40c4` had a prompt/category title before the fix; `d47abc2ed7bd4a769e17b9e9dee58b3f` had a generic GUI title/body before the defense-news fallback fix. Review/delete these manually before public posting if they remain in the platform draft box.
- Safety: no API key files were edited; docs avoid signed image URLs and secrets.

### 2026-06-20 12:18
**Task:** Verify GUI delete-drafts workflow, redesign unclear preview/confirmation controls, and smoke-test GUI pages.
**Git:** `main` with existing uncommitted GUI/headless/news-quality changes; this entry covers the delete UI/verification additions.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `apps/gui.py` | DONE | Replaced delete-page `dry-run` / `--yes` checkboxes with explicit delete-mode and confirmation-mode comboboxes, added dynamic risk hints, added safe flag resolution, and sanitized old symbolic/garbled titles in GUI display. | Consider adding a per-draft targeted delete if the platform DOM remains stable enough for title-specific matching. |
| `tests/test_gui.py` | DONE | Added regressions for explicit delete labels, preview-mode safety, removing symbolic status marks from displayed titles, and replacing all-question-mark garbled titles with `(无标题)`. | None. |
| `docs/GUI删除草稿验证与提示优化-2026-06-20.md` | DONE | Documented the new GUI delete controls, how to delete all drafts safely, dry-run/real-delete verification, and GUI smoke results. | None. |
| `README.md` | DONE | Added the new delete verification/UX doc to the docs index. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- GUI dry-run verification: launched `apps.gui`, selected `删除草稿`, clicked GUI `运行 delete-drafts` with `--all`, `limit=0`, safe preview; result `image total=11`, `video total=0`, `article total=0`, exit `0`.
- GUI real-delete verification: launched `apps.gui`, selected `正式删除（会删除小红书草稿）` + `自动确认（不再弹出确认）`, set `--all`, `limit=1`, clicked GUI `运行 delete-drafts`; result deleted `1/11` image drafts, `0/0` video, `0/0` article, exit `0`.
- Follow-up preview: `image total=10`, `video total=0`, `article total=0`, confirming the platform draft count decreased by one.
- Local-record safety: `data/posts/53e095f286384eae8f75b61e9f91dc89/post.json` and `data/posts/68f348cdefa248d89aa35e049e62df26/post.json` still exist after platform deletion; `local_posts_count=1130`.
- GUI smoke: window launches with 5 tabs, key `auto` / `create` / `delete-drafts` controls present, `.env.gui` config area present, new delete combobox options present, old delete labels absent, garbled `???? [saved_as_draft]` choices no longer shown.

### 2026-06-20 12:45
**Task:** Change empty-prompt daily-news behavior so it no longer defaults to `china`, and verify candidate fetching.
**Git:** `main` with existing uncommitted GUI/headless/news-quality changes; this entry covers the news-query default changes.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | Replaced the hardcoded empty-prompt default `china` with a broad default query pool (`technology/world/science/business/health/climate/society/international`), randomized query order, `NEWS_QUERY_DEFAULT` list parsing, and empty-prompt candidate aggregation across default queries when needed. | Consider exposing the default query pool in GUI config if you want non-technical editing. |
| `tests/test_daily_news.py` | DONE | Added regressions ensuring empty-prompt defaults are not single `china`, and empty-prompt fetch can aggregate candidates from multiple default queries. | None. |
| `README.md` | DONE | Updated daily-news docs to explain no-prompt random/default query pool behavior and `NEWS_QUERY_DEFAULT` override. | None. |
| `docs/工作流新闻任务书.md` | DONE | Updated workflow spec and config notes to remove the old default-`china` behavior. | None. |
| `docs/使用说明-自动新闻生成与草稿发布.md` | DONE | Added a note that no-prompt daily news now uses the default broad query pool; prompt or `NEWS_QUERY_DEFAULT` can be used to fix a topic direction. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Root cause: `DEFAULT_QUERY` was previously `china`, so empty prompt used only `china`; when NewsAPI timed out/returned no candidates and GDELT was rate-limited, `auto` produced `posts=0`.
- Live candidate verification: forced `NEWS_PROVIDER=newsapi` and called `fetch_daily_news_candidates("")`; result provider `newsapi`, `query_variants=['technology', 'climate', 'society', 'international', 'world', 'science', 'business', 'health']`, `queries_used=['technology']`, `count=8`.
- Targeted tests: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 39 passed; `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_gui.py tests\test_cli_headless.py -q` -> 71 passed.
- Full five-draft generation/upload was not rerun in this step to avoid unintended LLM/image quota usage; the verified failure point was candidate fetching.

### 2026-06-20 15:20
**Task:** Fix XHS login-hold behavior so it detects real login/editor readiness, then verify the complete daily-news generation + AI image + XHS draft chain with 2 posts.
**Git:** `main` with existing uncommitted GUI/headless/news-quality changes; this entry covers the login-state detection, daily-news quality fixes, docs, and live verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Replaced unconditional `time.sleep(login_hold)` with XHS page-state detection (`ready/login/unknown`), fast continuation when editor is ready, fast failure for headless login pages, and `login_check` progress output. Applied to save-draft and delete-drafts paths. | Consider porting the same behavior to legacy `src/publish/mcp_steps.py` if that old MCP publisher is reactivated. |
| `src/news/daily_news.py` | DONE | Added low-quality candidate filtering for package releases, repository-style updates, `Watch:` video snippets, and `News in brief`; fixed prompted fallback query bug (`default_query` undefined). | NewsAPI/GDELT can still rate-limit; use provider fallback or cached/file provider for deterministic tests. |
| `src/workflow/create_post.py` | DONE | Added English word-boundary keyword matching, stricter generic-title/body quality gates, fact-based offline bodies for seawater battery / NATO troop review / AI authors, and candidate skipping before AI image generation when content remains too generic. | Add more fact-based templates only if live candidates repeatedly need deterministic fallback. |
| `tests/test_playwright_profile_config.py` | DONE | Added login-state classification and wait behavior tests, including “ready pages must not sleep for login_hold”. | None. |
| `tests/test_daily_news.py` | DONE | Added regressions for French `importe` not matching `import`, package/video/brief candidate filtering, prompted query fallback, generic quality rejection, and fact-based fallback body. | None. |
| `README.md` / `docs/小红书登录态检测与每日新闻链路实测-2026-06-20.md` | DONE | Documented the new `login-hold` semantics, quality fixes, deletion of bad test drafts, API rate-limit handling, and final live-chain results. | None. |

**Notes**
- Login dry-run verification: ran `apps.cli run <post_id> --headless --login-hold 600 --wait-timeout 90 --dry-run --force`; `login_check` reached `state=ready`, total elapsed about 5.7s, so it did not wait 600s.
- Initial live NewsAPI run produced two low-quality drafts (`外贸数据出现变化`, `AI议题出现进展`); after identifying the quality issue, deleted those two platform drafts with `delete-drafts --limit 2 --yes`, result `deleted 2/12 drafts (image)`.
- NewsAPI and GDELT later returned 429 rate limits, so the final chain used `NEWS_PROVIDER=file` with local cache `data/news_candidates_api_cache_2026-06-20.json` derived from the just-returned API candidates.
- Final live accepted drafts:
  - `c30ccbd535fd4c19a96c0410be483b3d` / `海水电池技术突破` / `saved_draft` / `verified_title=True cover_ready=True` / image `aliyun wan2.7-image`.
  - `eef16f64e55847e58ed98e43f6a0b370` / `美军欧洲部署审查` / `saved_draft` / `verified_title=True cover_ready=True` / image `aliyun wan2.7-image`.
- Final platform dry-run top items: `美军欧洲部署审查` saved at `2026-06-20 15:11:03`, `海水电池技术突破` saved at `2026-06-20 15:09:58`, image drafts total `12`.
- Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 44 passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 141 passed.
- Safety: no API-key files were printed or edited; local draft records under `data/posts` were preserved.

### 2026-06-20 16:05
**Task:** Add GNews as a daily-news provider without persisting secrets, and add terminal stage labels for failures.
**Git:** `main` with existing uncommitted GUI/headless/news-quality changes; this entry covers only the GNews provider, CLI stage-error output, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/daily_news.py` | DONE | Added `NEWS_PROVIDER=gnews`, `GNEWS_API_KEY` / `GNEWS_TOKEN`, optional `GNEWS_LANG` / `GNEWS_COUNTRY` / `GNEWS_MAX` / `GNEWS_BASE_URL`, GNews `/search` mapping to `NewsItem`, and auto-mode fallback order including GNews. | Live GNews requests require setting the key via local env or ignored `docs/gnews_api-key.md`; the real key was not written to tracked files. |
| `apps/cli.py` | DONE | Added `error: stage=...` formatting for create/auto/run upload failures and refined stage classification for `获取新闻` / `LLM` / `VLM生图` / `上传`. | Keep adding provider-specific keywords if new integrations introduce distinct errors. |
| `tests/test_daily_news.py` | DONE | Added GNews provider mapping and auto-mode GNews fallback regressions. | None. |
| `tests/test_cli_headless.py` | DONE | Added stage-error formatting and classification regressions, including VLM image key errors not being mislabeled as LLM. | None. |
| `README.md` / `docs/gnews_api-key.example.md` / `docs/GNews新闻源接入与阶段化错误提示-2026-06-20.md` | DONE | Documented safe GNews configuration, ignored local key-file workflow, auto fallback order, and stage-error meanings. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Secret safety: the user-provided GNews key was not repeated in code, docs, test fixtures, commands, or committed files. Only placeholders such as `YOUR_GNEWS_API_KEY` were added.
- Official GNews reference checked: Search endpoint `https://gnews.io/api/v4/search`, API key parameter `apikey`, optional `lang` / `country` / `max` / `from` / `to` / `sortby`.
- Expected failure examples now include `error: stage=获取新闻 | ...`, `error: stage=LLM | ...`, `error: stage=VLM生图 | ...`, and `error: stage=上传 | ...`.

### 2026-06-20 16:35
**Task:** Re-test generation of 2 daily-news drafts, fix fallback-body quality conflict, and verify XHS draft upload.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews changes; this entry covers the fallback-body fix, docs, and two-draft live verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added context-aware daily-news offline fallback body so candidates with usable title/summary/content no longer fall into the old generic template that the quality gate rejects. Sparse candidates still remain blocked. | Consider adding provider-specific summaries only if new live sources repeatedly return English topics that cannot be summarized by the current rules. |
| `tests/test_daily_news.py` | DONE | Added regression for context-rich candidates passing `generic_body` gate while sparse candidates still fail; re-ran full daily-news tests. | None. |
| `docs/每日新闻兜底正文与两条草稿实测-2026-06-20.md` | DONE | Documented the failed first run, root cause, fix, command, and final two uploaded draft results. | None. |
| `README.md` | DONE | Added the new test report to the docs index. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Initial live run failed before post creation: `skipped_quality=7`, `posts=0`, because fallback bodies were intentionally generic and then rejected by the quality gate.
- After fix, deterministic end-to-end run used `NEWS_PROVIDER=file` with `data/news_candidates_api_cache_2026-06-20.json` to avoid live NewsAPI/GDELT rate-limit or low-quality candidate noise.
- Created and uploaded two XHS drafts with AI images:
  - `3b3ffeb323d140898a352ac8bd369262` / `海水电池技术突破` / source `Geeky Gadgets` / `uploaded=True` / `status=saved_as_draft` / image `aliyun wan2.7-image` / XHS `verified_title=True cover_ready=True`.
  - `0dd946893d024b2482e81a33ca0cfafd` / `美军欧洲部署审查` / source `Dailymail.com` / `uploaded=True` / `status=saved_as_draft` / image `aliyun wan2.7-image` / XHS `verified_title=True cover_ready=True`.
- Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 47 passed.
- Safety: no API-key files were printed or edited; user-provided GNews key remains absent from tracked files.

### 2026-06-20 17:05
**Task:** Add daily-news historical URL dedupe so repeated source links are skipped before generation.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews changes; this entry covers only the historical URL dedupe feature, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/news/history.py` | DONE | Added URL normalization, local `data/posts/*/post.json` history scanning, and filtering helpers for previously used news URLs. | Extend tracking-param list only if new providers introduce additional noisy params. |
| `src/news/daily_news.py` | DONE | Integrated history URL filtering into candidate fetching after in-batch candidate dedupe; continues to later query/provider when duplicates are skipped; records `history_dedupe` metadata. | None. |
| `tests/test_daily_news.py` | DONE | Added TDD regressions for URL normalization and skipping a duplicate historical URL while keeping the next fresh candidate. | None. |
| `README.md` / `docs/每日新闻历史URL查重-2026-06-20.md` | DONE | Documented default behavior, metadata, URL normalization rules, and `NEWS_HISTORY_DEDUPE=0` escape hatch. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Default behavior is enabled: local history URLs are read from `platform.news.source_url` and `platform.news.picked.url`.
- Normalization removes common tracking params (`utm_*`, `fbclid`, `gclid`, etc.), strips fragments, lowercases scheme/domain, and normalizes trailing slashes.
- Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 49 passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 151 passed.
- Local functional check: with `NEWS_PROVIDER=file` and the cached 2026-06-20 candidates, history dedupe skipped the two URLs already used in prior drafts and returned only the fresh AI-authors candidate; with `NEWS_HISTORY_DEDUPE=0`, all three candidates returned.
- Safety: no API-key files were printed or edited.

### 2026-06-20 17:45
**Task:** Perform engineering-wide check and generate two daily-news drafts with AI images.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews/history-dedupe changes; this entry covers the additional quality fix, docs, tests, and live draft results from this check.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Fixed title normalization for person-colon headlines, stripped site suffixes such as `_新闻频道_中华网` / `-- 国际 -- 人民网`, and cleaned original-page excerpts before using them in summaries/bodies. | Consider adding title-specific source quality scoring if live sources keep returning sports/event photo pages. |
| `tests/test_daily_news.py` | DONE | Added regressions for rejecting person-name-only titles and removing navigation/share noise from original excerpts. | None. |
| `docs/工程性全面检测与每日新闻AI配图实测-2026-06-20.md` | DONE | Documented the engineering checks, initial quality issues, fix, final generated drafts, and external service warnings. | None. |
| `README.md` | DONE | Added the new engineering test report to the docs index. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Fresh verification before live run: `.\.venv\Scripts\python.exe -m pytest -q` -> 151 passed.
- First live run uploaded two drafts but quality review found issues:
  - `15fdb4d8ae454c2b99913e295f2385dd`: body included navigation noise.
  - `b70583b47aa44a6cadd58a301845261d`: title collapsed to `谢晖`.
- Regression verification after fix: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 51 passed.
- Final accepted drafts:
  - `3bd038ad974f4eeaa698d4df5395beb9` / `2026年世界体操联合会艺术体操世界挑战` / `uploaded=True` / `status=saved_as_draft` / image `aliyun wan2.7-image` / XHS `verified_title=True cover_ready=True`.
  - `6a3e21e506c44641a3c33ebefe18587b` / `作家使用AI引争议` / `uploaded=True` / `status=saved_as_draft` / image `aliyun wan2.7-image` / XHS `verified_title=True cover_ready=True`.
- External service notes: one GDELT request returned 429 and one Aliyun image request was connection-refused; workflow skipped failed/low-quality candidates and completed with replacement drafts.
- Safety: no API-key files were printed or edited.

### 2026-06-20 18:20
**Task:** Optimize daily-news commentary so empty template comments are removed and factual comments are optional.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews/history-dedupe changes; this entry covers only commentary prompt logic, fallback body behavior, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Made `点评` optional in the LLM prompt, added generic-comment detection/removal, stopped auto-inventing comments for one-paragraph bodies, and added fact-based offline comments only when supported by news facts. | Monitor live drafts for new empty commentary phrases and add them to the marker list if needed. |
| `tests/test_daily_news.py` | DONE | Added regressions for optional comments, removing the exact generic commentary template, prompt constraints, and fact-supported weather/disaster comments. | None. |
| `README.md` / `docs/每日新闻点评与正文通顺优化-2026-06-20.md` | DONE | Documented optional commentary behavior, prompt constraints, cleanup rules, and verification command. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this progress entry. | Keep appending after future coding work. |

**Notes**
- Regression verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py` -> 54 passed.
- The known bad commentary template (`这类新闻适合先看事实，再看影响...`) is now removed instead of published.
- Sparse daily-news fallback bodies no longer add a fake `点评：` block; they remain generic enough for the quality gate to reject when facts are insufficient.
- Safety: no API-key files were printed or edited.

### 2026-06-20 19:10
**Task:** Stabilize daily-news publish body as fixed JSON and prepare live delete/regenerate verification.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews/history-dedupe changes; this entry covers only daily-news body JSON structure, image prompt compatibility, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Added final 5-field body JSON normalization (`原文标题/内容/评价/日期/来源`), URL scrubbing, old-label compatibility, JSON-safe field-level clamping, and prompt updates requiring body-as-JSON-object-text. | Live verify with two uploaded XHS drafts after deleting old platform drafts. |
| `src/llm/generate.py` | DONE | Preserves direct dict-style `body` values as JSON strings when the model returns the 5 Chinese fields; relaxed the global “body plain text” instruction for explicit JSON-body prompts. | None. |
| `src/images/auto_image.py` | DONE | Reads `内容/评价` from JSON body for image prompt snippets so AI image generation is not polluted by JSON field names. | None. |
| `tests/test_daily_news.py` / `tests/test_llm_generate.py` / `tests/test_auto_image.py` | DONE | Added regressions for fixed JSON body, URL-only-in-metadata, valid JSON after clamping, dict body coercion, and JSON-body image snippets. | None. |
| `README.md` / `docs/使用说明-自动新闻生成与草稿发布.md` / `docs/每日新闻正文JSON结构稳定化-2026-06-20.md` | DONE | Documented the new 5-field body contract and where URLs are stored. | None. |

**Notes**
- Targeted verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_llm_generate.py tests\test_auto_image.py` -> 77 passed.
- Multi-agent side review flagged the JSON truncation risk; `_dump_daily_news_body_json(...)` now shrinks fields and re-dumps JSON instead of slicing the raw JSON string.
- Safety: no API-key files were printed or edited.

### 2026-06-20 19:55
**Task:** Complete live deletion and regeneration test for two daily-news drafts after JSON body changes.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews/history-dedupe changes; this entry covers upload-selector fixes and live platform verification.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/publish/playwright_steps.py` | DONE | Added rich-text body editor selectors, JSON-aware body verification, placeholder-text fallback, and title-offset coordinate fallback for XHS body entry. | Consider adding targeted delete-by-title if platform DOM remains stable. |
| `tests/test_playwright_profile_config.py` | DONE | Added regressions for rich-text body selectors and JSON body verification by field terms. | None. |
| `docs/每日新闻正文JSON结构稳定化-2026-06-20.md` | DONE | Added live deletion/regeneration/upload verification results. | None. |
| `CODING_PROGRESS.md` | DONE | Appended this live verification entry. | Keep appending after future coding work. |

**Notes**
- Deleted existing XHS creator-center drafts: initial dry-run `image total=16`, real delete `deleted 16/16 drafts (image)`.
- Debug runs briefly left failed drafts because XHS saved title/image even when body filling failed; those were deleted with `delete-drafts --draft-type image --limit 1/2 --yes`.
- Final generated/uploaded drafts:
  - `7acb42d5494e4d35b45c9caab1607f6d` / `海水电池技术突破` / `saved_draft` / source `Geeky Gadgets` / image `aliyun wan2.7-image` / final XHS `verified_title=True cover_ready=True`.
  - `21c4aefc218349bd83c1fccbdc704103` / `美军欧洲部署审查` / `saved_draft` / source `Dailymail.com` / image `aliyun wan2.7-image` / final XHS `verified_title=True cover_ready=True`.
- Final platform dry-run: `type=image total=2`, showing only the two regenerated drafts.
- Verification: `.\.venv\Scripts\python.exe -m pytest -q` -> 162 passed; `git diff --check` -> no patch errors, only CRLF warnings.
- Safety: no API-key files were printed or edited.

### 2026-06-21
**Task:** Fix daily-news JSON body leaking into the publishable XHS正文.
**Git:** `main` with existing uncommitted GUI/headless/news/GNews/history-dedupe changes; this entry covers only daily-news body rendering, prompt wording, image prompt compatibility, docs, and tests.

| File | Status | What changed | Remaining / Next action |
|---|---|---|---|
| `src/workflow/create_post.py` | DONE | Split daily-news body handling into `_daily_news_body_to_fields(...)` and `_render_daily_news_body_fields(...)`; `_finalize_daily_news_body(...)` now returns readable five-field text instead of raw JSON. Updated prompt so `body` is directly publishable text, not nested JSON. | Verify on next live XHS upload that the textarea shows rendered text. |
| `src/images/auto_image.py` | DONE | Image prompt snippets now read `内容/评价` from rendered daily-news bodies, avoiding `原文标题/日期/来源` field noise. | None. |
| `tests/test_daily_news.py` / `tests/test_auto_image.py` | DONE | Added red/green regressions for JSON input being rendered into publishable text and rendered body snippets being clean for AI images. | None. |
| `README.md` / `docs/使用说明-自动新闻生成与草稿发布.md` / `docs/每日新闻正文JSON结构稳定化-2026-06-20.md` / `docs/每日新闻正文渲染修复-2026-06-21.md` | DONE | Updated docs to state that final `post.body`/XHS正文 is rendered text; JSON is only tolerated as an internal/input format. | None. |

**2026-06-21 follow-up**
- Refined `_render_daily_news_body_fields(...)` so `原文标题` / `内容` / `评价` / `日期` / `来源` are all separate sections with blank lines between every section, including `日期` and `来源`.
- Updated `_daily_news_prompt(...)` to teach the same blank-line layout to the LLM.
- Added `_html_for_contenteditable_text(...)` and rich-text fallback HTML insertion in `src/publish/playwright_steps.py`, so XHS contenteditable/ProseMirror/Quill editors preserve visible blank lines instead of receiving a single `textContent` blob.
- Expanded URL cleanup to remove protocol-relative links such as `//images.china.cn/...` from正文.
- Verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_playwright_profile_config.py tests\test_auto_image.py -q` -> 94 passed; `.\.venv\Scripts\python.exe -m pytest -q` -> 168 passed.

**Notes**
- Root cause: the previous JSON-stability change made `_finalize_daily_news_body()` return the internal JSON representation, and the upload layer correctly wrote `post.body` verbatim.
- Targeted verification: `.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py -q` -> 58 passed; `.\.venv\Scripts\python.exe -m pytest tests\test_auto_image.py -q` -> 19 passed.
- Full verification: `.\.venv\Scripts\python.exe -m pytest -q` -> 165 passed; `git diff --check` -> no patch errors, only existing CRLF normalization warnings.
- Safety: no API-key files were printed or edited.
