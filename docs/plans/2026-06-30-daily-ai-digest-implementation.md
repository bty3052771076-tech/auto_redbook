# Daily AI Digest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `每日AI讯息`, a workflow that gathers about 10 AI updates from official sources, uses social sources as verification/backfill, renders adaptive brief-card images, and saves a Xiaohongshu draft.

**Architecture:** Add a new `src/ai_digest` package. Keep collection, ranking, summarization, image rendering, and post creation separate, then add a small branch in `src/workflow/create_post.py` and `apps/cli.py`/`apps/gui.py` for the new special title.

**Tech Stack:** Python stdlib RSS/XML/HTML parsing, Pydantic/dataclasses, existing LLM config, Pillow for local PNG rendering, existing Post storage and Playwright upload.

---

### Task 1: Data Model And Ranking

**Files:**
- Create: `src/ai_digest/__init__.py`
- Create: `src/ai_digest/models.py`
- Create: `src/ai_digest/rank.py`
- Test: `tests/test_ai_digest.py`

**Steps:**
1. Write failing tests for `AIUpdateItem`, URL/title dedupe, official-first ranking, social verification, and target item count near 10.
2. Run `pytest tests/test_ai_digest.py -q` and verify failure because package does not exist.
3. Implement models and ranking helpers.
4. Run the same tests and make them pass.

### Task 2: Source Configuration And Fixture Fetchers

**Files:**
- Create: `src/ai_digest/sources.py`
- Create: `src/ai_digest/fetchers.py`
- Test: `tests/test_ai_digest_sources.py`

**Steps:**
1. Write failing tests for official source registry, RSS fixture parsing, GitHub release fixture parsing, and social search fixture parsing.
2. Run targeted tests and verify failure.
3. Implement source registry and fixture-friendly fetchers.
4. Run targeted tests and make them pass.

### Task 3: Digest Generation

**Files:**
- Create: `src/ai_digest/generate.py`
- Test: `tests/test_ai_digest_generate.py`

**Steps:**
1. Write failing tests for prompt construction, LLM JSON parsing, and local fallback brief.
2. Run targeted tests and verify failure.
3. Implement generation helpers.
4. Run targeted tests and make them pass.

### Task 4: Adaptive Image Rendering

**Files:**
- Create: `src/ai_digest/render.py`
- Modify: `requirements.txt`
- Test: `tests/test_ai_digest_render.py`

**Steps:**
1. Add failing tests that render short and long digest items to PNG and assert longer content creates more images.
2. Run targeted tests and verify failure.
3. Add `Pillow>=10.0.0` to requirements and install it into `.venv` with workspace-local `PIP_CACHE_DIR`.
4. Implement renderer with `1104x1472` default cards and adaptive pagination.
5. Run targeted tests and make them pass.

### Task 5: Workflow Integration

**Files:**
- Modify: `src/workflow/create_post.py`
- Modify: `apps/cli.py`
- Test: `tests/test_ai_digest_workflow.py`
- Test: existing CLI partial tests if affected

**Steps:**
1. Write failing tests that `create_post_with_draft(title_hint="每日AI讯息")` creates a Post with digest metadata and PNG assets.
2. Write failing CLI test that `auto --title 每日AI讯息` calls the new workflow.
3. Run targeted tests and verify failure.
4. Implement `create_daily_ai_digest_post(s)` and route the special title.
5. Run targeted tests and make them pass.

### Task 6: GUI And Documentation

**Files:**
- Modify: `apps/gui.py`
- Modify: `README.md`
- Create: `docs/每日AI讯息功能说明-2026-06-30.md`
- Test: `tests/test_gui.py`

**Steps:**
1. Write failing GUI tests for the quick title button and source configuration text.
2. Run targeted tests and verify failure.
3. Implement GUI quick title and docs.
4. Run targeted tests and make them pass.

### Task 7: Regression And Smoke Verification

**Commands:**
- `.\.venv\Scripts\python.exe -m py_compile src\ai_digest\*.py src\workflow\create_post.py apps\cli.py apps\gui.py`
- `.\.venv\Scripts\python.exe -m pytest tests\test_ai_digest.py tests\test_ai_digest_sources.py tests\test_ai_digest_generate.py tests\test_ai_digest_render.py tests\test_ai_digest_workflow.py tests\test_gui.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`

**Expected:** All tests pass; CLI can generate a local `每日AI讯息` post with adaptive PNG assets using mocked fetchers/LLM in tests.
