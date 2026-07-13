# 信源可靠性与编辑工作台 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use test-driven-development and verification-before-completion while implementing this plan task by task.

**Goal:** 让每日新闻和每日 AI 讯息只基于可追溯、可计时、可解释的候选来源生成，并把本次采集证据和信源健康度呈现在 GUI 中。

**Architecture:** 以声明式信源目录驱动两条采集链路。AI 讯息采用“官方更新流 -> 官方发布页 -> GitHub Release -> 搜索补充 -> 聚合兜底”的阶段化并行采集；每日新闻保留现有 API/RSS 回退，但为每个提供商记录耗时、结果数、日期质量和失败原因。两条链路都写入工作区内的状态快照，GUI 读取快照展示，不接触平台账号和草稿。

**Tech Stack:** Python 3、标准库 `concurrent.futures` / `subprocess`、Windows 自带 `curl.exe`（可用时）、Tkinter/ttk、pytest、Pillow。不得新增 C 盘安装或依赖。

---

## 设计约束

1. 草稿候选必须同时有原始 URL 和可解析发布时间。
2. “官方”不是永久高优先级标签。HTTP 错误、超时、解析为空、日期缺失或过期均会留下健康记录，并在冷却期内降级。
3. 固定历史文章标记为 `official_page` 或 `legacy`，不得与官方更新流同级优先。
4. 每次任务有来源级总预算和单源硬时限；失败来源不能阻塞其他来源，也不能让 CLI/GUI 长时间没有阶段进度。
5. 聚合、搜索与热榜仅在官方层的数量或国内/海外配额不足时参与，不能伪装为官方发布。

## GUI 视觉方向

**对象与任务：** 小红书创作者每天在本地判断是否有足够可靠素材，并生成、检查、保存草稿。界面应像紧凑的编辑台，而不是营销首页或泛用设置表单。

**色彩令牌：** `paper #F7F8F5`、`ink #1C242C`、`teal #007E75`（可用与主操作）、`coral #C75037`（异常与冷却）、`mist #D8DFDC`（分隔与轨道）、`sun #C6922C`（进行中）。字体使用 Windows 已有的 `Microsoft YaHei UI` 与 `Segoe UI Semibold`，不安装字体、不使用渐变或装饰性圆球。

**布局：**

```text
+---------------------------------------------------------------+
| Auto Redbook | 本次任务状态 | 打开创作平台 | 登录检查        |
+---------------------------+-----------------------------------+
| 自动发帖输入区            | 编辑状态栏                        |
| 题材 / 数量 / 回溯        | [本次任务][信源健康][模型额度]   |
| 模型 / 图片 / 执行        | 证据轨迹 + 可滚动明细            |
+---------------------------+-----------------------------------+
| 草稿处理 | 发布草稿 | 已发布数据 | 信源中心 | 配置             |
+---------------------------------------------------------------+
```

**标志性元素：** “证据轨迹”是紧凑横向序列，使用来源层级、采集时间、候选数和最终入选数解释本次内容如何形成。它显示真实运行状态，不添加营销文案。

---

## Task 1: 建立信源目录与来源健康数据模型

**Files:**
- Modify: `src/ai_digest/sources.py`
- Create: `src/sources/__init__.py`
- Create: `src/sources/health.py`
- Test: `tests/test_source_health.py`

**Step 1: Write the failing tests**

```python
def test_source_health_marks_timeout_in_cooldown_until_expiry(): ...
def test_source_health_keeps_successful_official_stream_eligible(): ...
def test_source_catalog_distinguishes_stream_page_and_aggregator_tiers(): ...
def test_source_health_snapshot_round_trips_without_workspace_global_state(): ...
```

**Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_source_health.py -q
```

Expected: failures because health module and catalog metadata do not exist.

**Step 3: Implement the smallest model surface**

- Add immutable source metadata: tier, region, topics and priority, retaining defaults for current callers.
- Add `SourceAttempt` and `SourceHealthSnapshot` with stable JSON serialization.
- Store snapshots only under caller-provided `data/source_health`.
- Update known stale entries to chronology pages where an official list exists, including DeepSeek `/updates` and ByteDance Seed `/blog`; retain old fixed articles only as legacy fallback entries where useful.

**Step 4: Verify GREEN**

Run Task 1 tests and inspect JSON saved under a temporary test path.

## Task 2: 加入受限 HTTP 传输与来源级采集结果

**Files:**
- Modify: `src/ai_digest/collect.py`
- Modify: `src/ai_digest/fetchers.py`
- Test: `tests/test_ai_digest_collect.py`
- Test: `tests/test_ai_digest_sources.py`

**Step 1: Write failing tests**

```python
def test_fetch_source_uses_bounded_transport_and_surfaces_http_status(): ...
def test_collect_records_parse_empty_and_missing_date_attempts(): ...
def test_collect_returns_before_a_timed_out_source_blocks_the_batch(): ...
```

**Step 2: Run RED**

Run only the new tests and confirm failure arises from absent result/timeout behavior.

**Step 3: Implement bounded transport**

- Prefer `curl.exe` on Windows when present, with connect timeout, total timeout, redirects, response-size bound and HTTP failure reporting; retain urllib as portable fallback.
- Return structured attempt results: source name, tier, status, elapsed seconds, HTTP status/error, raw count, URL count and date count.
- Treat `parse_empty`, `missing_date` and `stale` as distinct source statuses.

**Step 4: Verify GREEN**

Run targeted source and collector tests, then existing RSS/GitHub parser tests.

## Task 3: 阶段化并发 AI 讯息采集与健康快照

**Files:**
- Modify: `src/ai_digest/collect.py`
- Modify: `src/workflow/create_post.py`
- Test: `tests/test_ai_digest_collect.py`
- Test: `tests/test_ai_digest_workflow.py`

**Step 1: Write failing tests**

```python
def test_collect_fetches_official_streams_before_official_pages(): ...
def test_collect_only_uses_aggregator_after_high_quality_pool_is_insufficient(): ...
def test_collect_exposes_attempts_and_health_snapshot_in_source_meta(): ...
def test_ai_digest_post_persists_source_trace_for_gui_readback(): ...
```

**Step 2: Run RED**

Run the named tests and confirm the old sequential strategy does not meet the contract.

**Step 3: Implement staged collection**

- Fetch eligible sources with bounded concurrency (`AI_DIGEST_SOURCE_CONCURRENCY`, default 4) and a batch deadline (`AI_DIGEST_BATCH_TIMEOUT_S`).
- Start with official streams and GitHub release feeds. Move to official pages, search and aggregators only when quantity, freshness or domestic/foreign quota checks fail.
- Persist health snapshot and attach attempts, tier counts, candidate counts and selected source evidence to `source_meta`.
- Keep the current date gate, duplicate removal and domestic/overseas quotas unchanged or stricter.

**Step 4: Verify GREEN**

Run focused collector/workflow tests plus a no-LLM, no-upload live collection smoke test with a short timeout.

## Task 4: 每日新闻的提供商证据与多样化 RSS 层

**Files:**
- Modify: `src/news/daily_news.py`
- Modify: `src/workflow/create_post.py`
- Test: `tests/test_daily_news.py`
- Test: `tests/test_source_health.py`

**Step 1: Write failing tests**

```python
def test_daily_news_records_provider_elapsed_status_and_dated_count(): ...
def test_daily_news_uses_curated_rss_before_undated_hot_list(): ...
def test_daily_news_trace_is_persisted_with_the_selected_candidate_pool(): ...
```

**Step 2: Run RED**

Run named tests and confirm current metadata lacks a full provider evidence trail.

**Step 3: Implement news source trace**

- Keep API providers first, then use dated RSS sources. Add only feeds that pass URL/date/response validation in this task, recording domestic/international grouping.
- Add provider attempt records with elapsed time, item count, dated count and failure detail to `source_meta`.
- Write news health snapshots and preserve strict Beijing date window, relevance filter and China-news quota.

**Step 4: Verify GREEN**

Run daily-news tests and read-only `世界杯` / domestic-economy candidate smoke tests. Do not create an XHS draft.

## Task 5: 建立 GUI 信源中心与编辑状态栏

**Files:**
- Modify: `apps/gui.py`
- Test: `tests/test_gui.py`
- Test: `tests/test_source_health.py`

**Step 1: Write failing tests**

```python
def test_load_latest_source_health_snapshots_handles_missing_and_invalid_files(): ...
def test_source_health_rows_filter_and_sort_by_status_freshness_and_latency(): ...
def test_source_evidence_summary_uses_attempt_metadata_without_exposing_keys(): ...
```

**Step 2: Run RED**

Run only new GUI helper tests and verify they fail because helpers are absent.

**Step 3: Implement the UI in current ttk patterns**

- Add persistent right-side selector: 本次任务、信源健康、模型额度、草稿详情。
- Add `信源中心` tab with sortable/searchable rows: name, type, tier, state, last success, dated count, duration and URL. A command button performs a read-only health check.
- Render evidence track from latest post/source metadata; show actionable Chinese empty/error states.
- Preserve existing buttons, CLI argument generation and quota selection behavior. Use canvas only for evidence track/progress bars and Treeview for dense tabular scanning.
- Apply the palette and spacing rules without nested cards, oversized headings, gradients or dependency installs.

**Step 4: Verify GREEN**

Run GUI tests, then launch GUI at normal desktop width and inspect the automatic-post view without opening creator-center automation.

## Task 6: 文档、真实验证和完成审计

**Files:**
- Create: `docs/信源可靠性与GUI编辑台优化-2026-07-10.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Test: affected modules and full suite

**Steps:**

1. Document source tiers, health statuses, snapshot paths, timeout variables, GUI meanings and fallback policy. Do not include keys, browser profiles or local run data.
2. Record actual validated replacement URLs and distinguish official, search and aggregator sources.
3. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q apps src tests
git diff --check
```

4. Run live read-only checks against curated AI and news sources, confirm source URL/date/status/duration metadata, and inspect the GUI source-state UI.
5. Preserve unrelated dirty worktree changes. Do not commit or push unless explicitly requested.
