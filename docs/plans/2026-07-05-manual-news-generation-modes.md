# Manual News Generation Modes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split user-provided daily-news material into a single-news file mode that always creates one post and a multi-news material pool mode that keeps prompt/count/lookback filtering.

**Architecture:** Keep the existing `--news-materials-file` behavior as the multi-news pool path. Add a separate single-news material file path that parses exactly one article, bypasses prompt/count/lookback candidate filtering, and feeds the existing daily-news drafting pipeline with one selected `NewsItem`.

**Tech Stack:** Python, Typer CLI, Tkinter GUI, pytest, existing `src.news.daily_news` and `src.workflow.create_post` modules.

---

### Task 1: Add Behavior Tests

**Files:**
- Modify: `tests/test_daily_news.py`
- Modify: `tests/test_cli_partial_auto.py`
- Modify: `tests/test_gui.py`

**Step 1: Write failing tests**

Add tests proving:
- A single-news material file is parsed into exactly one `NewsItem`.
- The single-news workflow bypasses prompt relevance and date-window filtering.
- CLI `auto` forwards `--single-news-material-file`.
- GUI exposes separate single-news and multi-news material file inputs.
- GUI single-news mode omits prompt/lookback and forces `--count 1`.

**Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py::test_fetch_single_daily_news_candidate_ignores_prompt_and_lookback tests\test_cli_partial_auto.py::test_auto_daily_news_passes_single_news_material_file tests\test_gui.py::test_build_cli_args_auto_single_news_material_forces_one_without_prompt_or_lookback -q
```

Expected: fail because the single-news material API and CLI/GUI arguments do not exist yet.

### Task 2: Implement Single-News Material API

**Files:**
- Modify: `src/news/daily_news.py`
- Modify: `src/workflow/create_post.py`

**Step 1: Add parser entry**

Add `load_single_news_material_file(path)` that reads `.md/.txt/.json/.jsonl` with the existing manual parser and returns exactly one `NewsItem`.

**Step 2: Add workflow entry**

Add `single_news_material_file` to `_fetch_daily_news_candidates_for_upload(...)`, `create_post_with_draft(...)`, and `create_daily_news_posts(...)`.

Rules:
- If `single_news_material_file` is set, return one candidate and metadata provider `manual_single`.
- Ignore prompt relevance filtering.
- Ignore lookback filtering.
- Force `create_daily_news_posts(...)` target count to one.
- Reject empty or multi-item single-news material files with actionable errors.

### Task 3: Implement CLI and GUI Split

**Files:**
- Modify: `apps/cli.py`
- Modify: `apps/gui.py`

**Step 1: CLI**

Add `--single-news-material-file` to `create` and `auto`.

Rules:
- If provided, pass `single_news_material_file` to workflow.
- Treat it as mutually exclusive with `--news-materials-file`.
- For `auto --title 每日新闻`, force count to one.

**Step 2: GUI**

Split the existing GUI material input into:
- `单条新闻材料文件`
- `多条新闻材料文件`

Rules:
- Single-news file produces CLI args with `--single-news-material-file` and `--count 1`.
- Multi-news file produces CLI args with `--news-materials-file` and keeps prompt/count/lookback.
- Do not allow both fields in the built command.

### Task 4: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Create: `docs/每日新闻人工材料双模式-2026-07-05.md`

**Step 1: Document modes**

Explain:
- Single-news file mode: one raw article, one generated post, no prompt/count/lookback needed.
- Multi-news material pool mode: long file, multiple candidates, prompt/count/lookback still apply.

**Step 2: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_daily_news.py tests\test_cli_partial_auto.py tests\test_gui.py -q
.\.venv\Scripts\python.exe -m compileall -q src\news src\workflow apps
```

Expected: all selected tests pass and compile succeeds.
