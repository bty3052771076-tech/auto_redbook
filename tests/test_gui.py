from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from apps.gui import (
    ALIYUN_IMAGE_MODEL_OPTIONS,
    ALIYUN_LLM_MODEL_OPTIONS,
    AUTO_IMAGE_ASSETS_GLOB,
    CommandRunner,
    DEFAULT_LOGIN_URL,
    DEFAULT_DRAFT_URL,
    DELETE_CONFIRM_AUTO,
    DELETE_CONFIRM_ASK,
    DELETE_MODE_DELETE,
    DELETE_MODE_PREVIEW,
    DEFAULT_IMAGE_PROVIDER,
    IMAGE_SOURCE_OPTIONS,
    LLM_PROVIDER_OPTIONS,
    PublishedMetricTableRow,
    QuotaDashboardRow,
    RecentPostSummary,
    UiEventQueue,
    build_xhs_login_launch_args,
    build_xhs_creator_launch_args,
    build_cli_args,
    build_quota_dashboard_rows,
    build_provider_env_overrides,
    build_subprocess_env,
    combine_prompt_entries,
    DEFAULT_PROMPT_ENTRY_COUNT,
    ensure_daily_news_candidate_pool_env,
    env_flag_enabled,
    env_int_value,
    extract_post_id_from_choice,
    filter_quota_dashboard_rows,
    format_post_choice,
    format_post_detail,
    format_post_time_detail,
    format_shared_draft_preview,
    find_local_post_for_metric_row,
    list_published_metric_table_rows,
    list_publishable_drafts,
    list_recent_posts,
    load_env_file,
    load_latest_quota_snapshots,
    merge_model_option_values,
    open_xhs_creator,
    parse_command_progress_line,
    progress_status_from_event,
    quota_dashboard_layout,
    quota_dashboard_row_kind_label,
    quota_dashboard_row_title,
    sort_quota_dashboard_rows,
    quota_dashboard_selection_target,
    resolve_assets_glob_for_image_source,
    resolve_delete_mode_flags,
    save_env_file,
    split_prompt_entries_from_text,
    sort_published_metric_table_rows,
    VOLCENGINE_IMAGE_MODEL_OPTIONS,
    VOLCENGINE_LLM_MODEL_OPTIONS,
)


def test_gui_default_image_provider_prefers_ai_generation():
    assert DEFAULT_IMAGE_PROVIDER == "aliyun"


def test_gui_exposes_llm_and_image_provider_model_options():
    assert LLM_PROVIDER_OPTIONS == ["aliyun", "volcengine", "ppinfra", "auto"]
    assert IMAGE_SOURCE_OPTIONS == ["local", "aliyun", "volcengine", "pexels"]
    assert "qwen3.7-plus" in ALIYUN_LLM_MODEL_OPTIONS
    assert "deepseek-v4-flash" in ALIYUN_LLM_MODEL_OPTIONS
    assert "doubao-seed-2-1-turbo-260628" in VOLCENGINE_LLM_MODEL_OPTIONS
    assert "glm-5.2" in VOLCENGINE_LLM_MODEL_OPTIONS
    assert "deepseek-v4-pro" in VOLCENGINE_LLM_MODEL_OPTIONS
    assert "deepseek-v4-flash" in VOLCENGINE_LLM_MODEL_OPTIONS
    assert ALIYUN_IMAGE_MODEL_OPTIONS == [
        "wan2.7-image",
        "wan2.7-image-pro",
        "qwen-image-2.0-pro-2026-06-22",
        "qwen-image-2.0-pro-2026-04-22",
    ]
    assert VOLCENGINE_IMAGE_MODEL_OPTIONS == [
        "doubao-seedream-5-0-lite-260128",
        "doubao-seedream-5-0-260128",
        "doubao-seedream-4-5-251128",
        "doubao-seedream-4-0-250828",
    ]


def test_ui_event_queue_drains_callbacks_in_order():
    events: list[str] = []
    ui_events = UiEventQueue()

    ui_events.put(events.append, "first")
    ui_events.put(events.append, "second")

    assert ui_events.drain() == 2
    assert events == ["first", "second"]
    assert ui_events.drain() == 0


def test_command_runner_rejects_duplicate_while_process_is_starting(monkeypatch):
    lines: list[str] = []
    exits: list[int] = []
    release = threading.Event()

    class FakeStdout:
        def __iter__(self):
            return iter(())

    class FakeProcess:
        stdout = FakeStdout()

        def poll(self):
            return None

        def wait(self):
            release.wait(timeout=2)
            return 0

        def terminate(self):
            release.set()

    def fake_popen(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr("apps.gui.subprocess.Popen", fake_popen)

    runner = CommandRunner(on_line=lines.append, on_exit=exits.append)
    runner.run([sys.executable, "--version"], {})
    runner.run([sys.executable, "--version"], {})

    assert runner.is_running() is True
    assert any("已有任务正在运行" in line for line in lines)

    release.set()
    deadline = time.time() + 3
    while (runner.is_running() or not exits) and time.time() < deadline:
        time.sleep(0.01)

    assert runner.is_running() is False
    assert exits == [0]


def test_command_runner_emits_heartbeat_when_process_is_silent(monkeypatch):
    lines: list[str] = []
    exits: list[int] = []
    release = threading.Event()

    class BlockingStdout:
        def __iter__(self):
            release.wait(timeout=2)
            return iter(())

    class FakeProcess:
        stdout = BlockingStdout()

        def poll(self):
            return 0 if release.is_set() else None

        def wait(self):
            release.wait(timeout=2)
            return 0

        def terminate(self):
            release.set()

    monkeypatch.setattr("apps.gui.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess())

    runner = CommandRunner(on_line=lines.append, on_exit=exits.append, heartbeat_seconds=0.05)
    runner.run([sys.executable, "--version"], {})

    deadline = time.time() + 1
    while not any("当前步骤" in line for line in lines) and time.time() < deadline:
        time.sleep(0.01)

    release.set()
    deadline = time.time() + 2
    while (runner.is_running() or not exits) and time.time() < deadline:
        time.sleep(0.01)

    assert any("当前步骤" in line and "CLI 子进程" in line for line in lines)
    assert exits == [0]


def test_command_runner_reports_status_transitions(monkeypatch):
    statuses: list[str] = []
    release = threading.Event()

    class FakeStdout:
        def __iter__(self):
            release.wait(timeout=2)
            return iter(())

    class FakeProcess:
        stdout = FakeStdout()

        def poll(self):
            return 0 if release.is_set() else None

        def wait(self):
            release.wait(timeout=2)
            return 0

        def terminate(self):
            release.set()

    monkeypatch.setattr("apps.gui.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess())

    runner = CommandRunner(
        on_line=lambda _line: None,
        on_exit=lambda _code: None,
        on_status=statuses.append,
        heartbeat_seconds=0.05,
    )
    runner.run([sys.executable, "--version"], {})

    deadline = time.time() + 1
    while not any("运行中" in status for status in statuses) and time.time() < deadline:
        time.sleep(0.01)
    runner.stop()
    deadline = time.time() + 2
    while runner.is_running() and time.time() < deadline:
        time.sleep(0.01)

    assert any("运行中" in status for status in statuses)
    assert any("正在停止" in status for status in statuses)
    assert statuses[-1] == "空闲"


def test_env_autorun_helpers_parse_flags_and_ints():
    assert env_flag_enabled("1") is True
    assert env_flag_enabled("YES") is True
    assert env_flag_enabled("off") is False
    assert env_flag_enabled(None) is False

    assert env_int_value("5", 1, min_value=1) == 5
    assert env_int_value("bad", 3, min_value=1) == 3
    assert env_int_value("-2", 3, min_value=1) == 1


def test_prompt_entry_helpers_split_combine_and_dedupe():
    assert DEFAULT_PROMPT_ENTRY_COUNT >= 3
    assert split_prompt_entries_from_text("世界杯|体育；足球\n世界杯") == ["世界杯", "体育", "足球"]

    prompt = combine_prompt_entries(["世界杯", "体育 足球", "", "世界杯", "财经政策；市场变化"])

    assert prompt == "世界杯\n体育 足球\n财经政策\n市场变化"


def test_build_subprocess_env_forces_unbuffered_utf8_output():
    env = build_subprocess_env({})

    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_build_provider_env_overrides_for_aliyun_single_model():
    env = build_provider_env_overrides(
        {},
        llm_provider="aliyun",
        llm_model="qwen3.7-plus",
        image_provider="aliyun",
        image_model="wan2.7-image",
    )

    assert env["LLM_PROVIDER"] == "aliyun"
    assert env["ALIYUN_LLM_MODEL"] == "qwen3.7-plus"
    assert env["ALIYUN_LLM_MODELS"] == "qwen3.7-plus"
    assert env["IMAGE_PROVIDER"] == "aliyun"
    assert env["ALIYUN_IMAGE_MODEL"] == "wan2.7-image"
    assert env["ALIYUN_IMAGE_MODELS"] == "wan2.7-image"


def test_build_provider_env_overrides_for_ppinfra_model():
    env = build_provider_env_overrides(
        {},
        llm_provider="ppinfra",
        llm_model="deepseek/deepseek-v3-0324",
        image_provider="pexels",
        image_model="wan2.7-image-pro",
    )

    assert env["LLM_PROVIDER"] == "ppinfra"
    assert env["LLM_MODEL"] == "deepseek/deepseek-v3-0324"
    assert "ALIYUN_LLM_MODEL" not in env
    assert env["IMAGE_PROVIDER"] == "pexels"
    assert "ALIYUN_IMAGE_MODEL" not in env


def test_build_provider_env_overrides_for_volcengine_models():
    env = build_provider_env_overrides(
        {},
        llm_provider="volcengine",
        llm_model="doubao-seed-2-1-turbo-260628",
        image_provider="volcengine",
        image_model="doubao-seedream-5-0-lite-260128",
    )

    assert env["LLM_PROVIDER"] == "volcengine"
    assert env["VOLCENGINE_LLM_MODEL"] == "doubao-seed-2-1-turbo-260628"
    assert env["VOLCENGINE_LLM_MODELS"] == "doubao-seed-2-1-turbo-260628"
    assert "ALIYUN_LLM_MODEL" not in env
    assert env["IMAGE_PROVIDER"] == "volcengine"
    assert env["VOLCENGINE_IMAGE_MODEL"] == "doubao-seedream-5-0-lite-260128"
    assert env["VOLCENGINE_IMAGE_MODELS"] == "doubao-seedream-5-0-lite-260128"
    assert "ALIYUN_IMAGE_MODEL" not in env


def test_build_provider_env_overrides_invalid_image_provider_falls_back_to_aliyun():
    env = build_provider_env_overrides(
        {},
        llm_provider="aliyun",
        llm_model="qwen3.7-plus",
        image_provider="unknown-provider",
        image_model="wan2.7-image",
    )

    assert env["IMAGE_PROVIDER"] == "aliyun"
    assert env["ALIYUN_IMAGE_MODEL"] == "wan2.7-image"


def test_build_provider_env_overrides_local_image_source_disables_auto_image():
    env = build_provider_env_overrides(
        {"IMAGE_PROVIDER": "aliyun"},
        llm_provider="aliyun",
        llm_model="qwen3.7-plus",
        image_provider="local",
        image_model="wan2.7-image",
    )

    assert env["AUTO_IMAGE"] == "0"
    assert "IMAGE_PROVIDER" not in env
    assert "ALIYUN_IMAGE_MODEL" not in env


def test_ensure_daily_news_candidate_pool_env_expands_multi_count_jobs():
    env = ensure_daily_news_candidate_pool_env(
        {},
        title="\u6bcf\u65e5\u65b0\u95fb",
        count=3,
    )

    assert env["NEWS_MAX_RECORDS"] == "60"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_ensure_daily_news_candidate_pool_env_uses_exact_twenty_times_pool_even_with_larger_user_value():
    env = ensure_daily_news_candidate_pool_env(
        {"NEWS_MAX_RECORDS": "120"},
        title="\u6bcf\u65e5\u65b0\u95fb",
        count=3,
    )

    assert env["NEWS_MAX_RECORDS"] == "60"


def test_ensure_daily_news_candidate_pool_env_does_not_expand_other_titles():
    env = ensure_daily_news_candidate_pool_env(
        {},
        title="\u79d1\u6280\u9009\u9898",
        count=3,
    )

    assert "NEWS_MAX_RECORDS" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_parse_command_progress_line_reads_generic_stage_events():
    event = parse_command_progress_line("[auto] stage=生成草稿 | in_progress | count=3")

    assert event == {
        "command": "auto",
        "stage": "生成草稿",
        "status": "in_progress",
        "detail": "count=3",
    }


def test_parse_command_progress_line_reads_xhs_upload_events():
    event = parse_command_progress_line(
        "[xhs-upload] collect_metrics: in_progress | items=330 target=335 scroll=220/240"
    )

    assert event == {
        "command": "xhs-upload",
        "stage": "collect_metrics",
        "status": "in_progress",
        "detail": "items=330 target=335 scroll=220/240",
    }
    assert progress_status_from_event(event) == "运行中：xhs-upload / collect_metrics / in_progress / items=330 target=335 scroll=220/240"


def test_resolve_assets_glob_for_image_source():
    assert resolve_assets_glob_for_image_source("local", "assets/pics/*") == "assets/pics/*"
    assert resolve_assets_glob_for_image_source("aliyun", "assets/pics/*") == AUTO_IMAGE_ASSETS_GLOB
    assert resolve_assets_glob_for_image_source("pexels", "assets/pics/*") == AUTO_IMAGE_ASSETS_GLOB


def test_env_file_roundtrip(tmp_path: Path):
    p = tmp_path / ".env.gui"
    save_env_file(p, {"FOO": "bar", "HAS_SPACE": "a b", "EMPTY": ""})
    data = load_env_file(p)
    assert data["FOO"] == "bar"
    assert data["HAS_SPACE"] == "a b"
    assert "EMPTY" not in data


def test_list_recent_posts_includes_titles_and_status(tmp_path: Path):
    posts = tmp_path / "data" / "posts"
    posts.mkdir(parents=True)
    first = posts / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    second = posts / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    first.mkdir()
    second.mkdir()
    (first / "post.json").write_text(
        '{"title":"第一条新闻","status":"draft","uploaded":false,"updated_at":"2026-06-19T10:00:00.000000Z","body":"本地草稿正文"}',
        encoding="utf-8",
    )
    (second / "post.json").write_text(
        '{"title":"第二条新闻","status":"saved_as_draft","uploaded":true,"uploaded_at":"2026-06-19T12:34:56.000000Z","updated_at":"2026-06-19T12:35:00.000000Z","body":"已经上传的正文","assets":[{"path":"a.png","kind":"image"}]}',
        encoding="utf-8",
    )
    exec_dir = second / "executions"
    exec_dir.mkdir()
    (exec_dir / "run.json").write_text(
        """
        {
          "id": "exec1",
          "post_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "attempt": 1,
          "started_at": "2026-06-19T12:30:00.000000Z",
          "ended_at": "2026-06-19T12:34:56.000000Z",
          "result": "saved_draft",
          "steps": [],
          "evidence": ["data/posts/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/evidence/exec1/final.png"]
        }
        """,
        encoding="utf-8",
    )

    items = list_recent_posts(project_root=tmp_path, limit=10)
    labels = [format_post_choice(item) for item in items]
    second_item = next(item for item in items if item.post_id == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    assert {item.post_id for item in items} == {
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    }
    assert any("第一条新闻" in label and "未上传" in label for label in labels)
    assert any("第二条新闻" in label and "已上传至小红书草稿" in label for label in labels)
    assert all("2026-06-19 12:34:56" not in label for label in labels)
    assert second_item.uploaded is True
    assert second_item.uploaded_at == "2026-06-19T12:34:56.000000Z"
    assert second_item.latest_execution_result == "saved_draft"
    assert second_item.asset_count == 1


def test_list_publishable_drafts_filters_uploaded_posts_by_beijing_date(tmp_path: Path):
    posts = tmp_path / "data" / "posts"
    posts.mkdir(parents=True)
    matching = posts / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    not_uploaded = posts / "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    other_day = posts / "cccccccccccccccccccccccccccccccc"
    matching.mkdir()
    not_uploaded.mkdir()
    other_day.mkdir()
    (matching / "post.json").write_text(
        '{"title":"可发布草稿","status":"saved_as_draft","uploaded":true,'
        '"uploaded_at":"2026-06-28T16:30:00.000000Z","body":"正文"}',
        encoding="utf-8",
    )
    (not_uploaded / "post.json").write_text(
        '{"title":"未上传草稿","status":"draft","uploaded":false,'
        '"updated_at":"2026-06-28T16:30:00.000000Z","body":"正文"}',
        encoding="utf-8",
    )
    (other_day / "post.json").write_text(
        '{"title":"其他日期草稿","status":"saved_as_draft","uploaded":true,'
        '"uploaded_at":"2026-06-27T15:30:00.000000Z","body":"正文"}',
        encoding="utf-8",
    )

    items = list_publishable_drafts(project_root=tmp_path, date="2026-06-29")

    assert [item.post_id for item in items] == ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
    assert items[0].title == "可发布草稿"


def test_list_publishable_drafts_scans_beyond_recent_non_publishable_posts(tmp_path: Path):
    posts = tmp_path / "data" / "posts"
    posts.mkdir(parents=True)
    old_publishable = posts / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    old_publishable.mkdir()
    (old_publishable / "post.json").write_text(
        json.dumps(
            {
                "title": "历史可发布草稿",
                "status": "saved_as_draft",
                "uploaded": True,
                "uploaded_at": "2026-06-20T08:00:00.000000Z",
                "body": "正文",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.utime(old_publishable, (1000, 1000))

    for idx in range(220):
        post_id = f"{idx + 1:032x}"
        post_dir = posts / post_id
        post_dir.mkdir()
        (post_dir / "post.json").write_text(
            json.dumps(
                {
                    "title": f"最近失败草稿 {idx}",
                    "status": "failed",
                    "uploaded": False,
                    "updated_at": "2026-06-30T08:00:00.000000Z",
                    "body": "正文",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.utime(post_dir, (2000 + idx, 2000 + idx))

    items = list_publishable_drafts(project_root=tmp_path, date="", limit=0)

    assert [item.post_id for item in items] == ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]


def test_format_post_choice_strips_symbolic_status_marks_from_title():
    post = RecentPostSummary(
        post_id="0123456789abcdef0123456789abcdef",
        title="❌测试标题",
        status="saved_as_draft",
        uploaded=True,
    )

    choice = format_post_choice(post)

    assert "❌" not in choice
    assert "测试标题" in choice
    assert "已上传至小红书草稿" in choice


def test_format_post_choice_replaces_garbled_question_mark_title():
    post = RecentPostSummary(
        post_id="0123456789abcdef0123456789abcdef",
        title="????",
        status="saved_as_draft",
        uploaded=True,
    )

    choice = format_post_choice(post)

    assert "????" not in choice
    assert "(无标题)" in choice


def test_format_post_time_detail_shows_beijing_time():
    from apps.gui import RecentPostSummary

    summary = RecentPostSummary(
        post_id="0123456789abcdef0123456789abcdef",
        title="AI芯片新品发布",
        status="saved_as_draft",
        uploaded=True,
        uploaded_at="2026-06-19T12:34:56.000000Z",
        updated_at="2026-06-19T12:35:00.000000Z",
        latest_execution_started_at="2026-06-19T12:30:00.000000Z",
        latest_execution_ended_at="2026-06-19T12:34:56.000000Z",
    )

    detail = format_post_time_detail(summary)

    assert "北京时间" in detail
    assert "上传时间：2026-06-19 20:34:56 北京时间" in detail
    assert "本地更新时间：2026-06-19 20:35:00 北京时间" in detail
    assert "执行开始：2026-06-19 20:30:00 北京时间" in detail
    assert "执行结束：2026-06-19 20:34:56 北京时间" in detail


def test_extract_post_id_from_choice_accepts_label_or_raw_id():
    pid = "0123456789abcdef0123456789abcdef"
    assert extract_post_id_from_choice(pid) == pid
    assert extract_post_id_from_choice(f"标题 [approved] | {pid}") == pid


def test_format_post_detail_shows_upload_state_time_and_body_preview():
    item = list_recent_posts(project_root=Path("non-existent-root"), limit=1)
    assert item == []
    from apps.gui import RecentPostSummary

    summary = RecentPostSummary(
        post_id="0123456789abcdef0123456789abcdef",
        title="AI芯片新品发布",
        status="saved_as_draft",
        uploaded=True,
        uploaded_at="2026-06-19T12:34:56.000000Z",
        updated_at="2026-06-19T12:35:00.000000Z",
        body_preview="要点摘要：AI芯片企业发布新品，强调推理算力与能效提升。",
        latest_execution_result="saved_draft",
        latest_execution_ended_at="2026-06-19T12:34:56.000000Z",
        asset_count=1,
    )

    detail = format_post_detail(summary)

    assert "AI芯片新品发布" in detail
    assert "已上传至小红书草稿" in detail
    assert "2026-06-19 20:34:56 北京时间" in detail
    assert "saved_draft" in detail
    assert "素材数量：1" in detail
    assert "要点摘要" in detail


def test_format_shared_draft_preview_reads_full_post_json(tmp_path: Path):
    post_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    post_dir = tmp_path / "data" / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        """
        {
          "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "type": "image",
          "status": "published",
          "uploaded": true,
          "uploaded_at": "2026-06-28T16:30:00.000000Z",
          "title": "Local draft title",
          "body": "Full local body line one\\n\\nFull local body line two",
          "topics": ["daily", "news"],
          "assets": [{"path": "data/posts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/assets/a.png", "kind": "image"}],
          "platform": {
            "news": {
              "api_source": "hotnews",
              "source_api": {
                "provider": "hotnews",
                "item_source": "hotnews:jinritoutiao",
                "item_domain": "example.com",
                "item_url": "https://example.com/news"
              }
            },
            "publish": {
              "result": "published",
              "published_at": "2026-06-29T01:02:03.000000Z",
              "actual_title": "Actual platform title",
              "actual_body": "Actual platform body from editor"
            }
          },
          "created_at": "2026-06-28T16:00:00.000000Z",
          "updated_at": "2026-06-29T01:02:03.000000Z"
        }
        """,
        encoding="utf-8",
    )

    preview = format_shared_draft_preview(post_id=post_id, project_root=tmp_path)

    assert "Actual platform title" in preview
    assert "Actual platform body from editor" in preview
    assert "hotnews" in preview
    assert "hotnews:jinritoutiao" in preview
    assert "https://example.com/news" in preview
    assert "data/posts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/assets/a.png" in preview
    assert "2026-06-29 09:02:03" in preview


def test_find_local_post_for_metric_row_prefers_url_then_title(tmp_path: Path):
    post_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    post_dir = tmp_path / "data" / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        """
        {
          "id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "type": "image",
          "status": "saved_as_draft",
          "uploaded": true,
          "title": "Original local title",
          "body": "Local body",
          "topics": [],
          "assets": [],
          "platform": {
            "publish": {
              "url": "https://www.xiaohongshu.com/explore/abc123"
            }
          },
          "created_at": "2026-06-29T00:00:00.000000Z",
          "updated_at": "2026-06-29T00:00:00.000000Z"
        }
        """,
        encoding="utf-8",
    )
    metric = PublishedMetricTableRow(
        title="Changed title on platform",
        url="https://www.xiaohongshu.com/explore/abc123",
        published_at="2026-06-29",
        likes=3,
    )

    match = find_local_post_for_metric_row(metric, project_root=tmp_path)

    assert match is not None
    assert match.post_id == post_id


def test_list_published_metric_table_rows_reads_latest_csv_and_raw_counts(tmp_path: Path):
    analytics = tmp_path / "data" / "analytics"
    analytics.mkdir(parents=True)
    (analytics / "published_metrics_latest.csv").write_text(
        "\n".join(
            [
                "id,captured_at,title,url,published_at,likes,comments,favorites,raw",
                'm1,2026-06-27T01:00:00Z,high engagement news,,2026-06-27,12,3,5,"{""views"":88,""shares"":2}"',
            ]
        ),
        encoding="utf-8-sig",
    )

    rows = list_published_metric_table_rows(project_root=tmp_path)

    assert len(rows) == 1
    assert rows[0].title == "high engagement news"
    assert rows[0].likes == 12
    assert rows[0].comments == 3
    assert rows[0].favorites == 5
    assert rows[0].views == 88
    assert rows[0].shares == 2


def test_sort_published_metric_table_rows_sorts_numeric_columns():
    rows = [
        PublishedMetricTableRow(title="low likes", likes=1, comments=7, favorites=2),
        PublishedMetricTableRow(title="high likes", likes=9, comments=1, favorites=5),
    ]

    by_likes = sort_published_metric_table_rows(rows, "likes", descending=True)
    by_comments = sort_published_metric_table_rows(rows, "comments", descending=False)

    assert [row.title for row in by_likes] == ["high likes", "low likes"]
    assert [row.title for row in by_comments] == ["high likes", "low likes"]


def test_xhs_creator_quick_launch_target_uses_image_publish_url():
    assert DEFAULT_DRAFT_URL == "https://creator.xiaohongshu.com/publish/publish?target=image"
    assert DEFAULT_LOGIN_URL == "https://creator.xiaohongshu.com"


def test_xhs_creator_launch_args_use_workspace_chrome_profile(tmp_path: Path):
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("", encoding="utf-8")

    args = build_xhs_creator_launch_args(project_root=tmp_path, chrome_path=chrome, env={})

    assert args[0] == str(chrome)
    assert f"--user-data-dir={tmp_path / 'data' / 'browser' / 'chrome-profile'}" in args
    assert "--profile-directory=Default" in args
    assert args[-1] == DEFAULT_DRAFT_URL


def test_xhs_creator_launch_args_allow_profile_override(tmp_path: Path):
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")
    custom_profile = tmp_path / "custom-xhs-profile"

    args = build_xhs_creator_launch_args(
        project_root=tmp_path,
        chrome_path=chrome,
        env={
            "XHS_CHROME_USER_DATA_DIR": str(custom_profile),
            "XHS_CHROME_PROFILE": "Profile 1",
        },
    )

    assert f"--user-data-dir={custom_profile}" in args
    assert "--profile-directory=Profile 1" in args


def test_xhs_login_launch_args_use_workspace_profile(tmp_path: Path):
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")

    args = build_xhs_login_launch_args(project_root=tmp_path, chrome_path=chrome, env={})

    assert f"--user-data-dir={tmp_path / 'data' / 'browser' / 'chrome-profile'}" in args
    assert "--profile-directory=Default" in args
    assert args[-1] == DEFAULT_LOGIN_URL


def test_open_xhs_creator_launches_chrome_with_workspace_profile(monkeypatch, tmp_path: Path):
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")
    launched: list[tuple[list[str], Path | None]] = []

    def fake_popen(args, cwd=None):
        launched.append((list(args), Path(cwd) if cwd else None))

        class FakeProcess:
            pid = 123

        return FakeProcess()

    monkeypatch.setattr("apps.gui.find_chrome_executable", lambda env=None: chrome)
    monkeypatch.setattr("apps.gui.subprocess.Popen", fake_popen)

    assert open_xhs_creator(project_root=tmp_path, env={}) is True

    profile_dir = tmp_path / "data" / "browser" / "chrome-profile"
    assert profile_dir.exists()
    assert launched == [
        (
            [
                str(chrome),
                f"--user-data-dir={profile_dir}",
                "--profile-directory=Default",
                DEFAULT_DRAFT_URL,
            ],
            tmp_path,
        )
    ]


def test_quick_launch_scripts_are_workspace_local():
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "start_gui.ps1").exists()
    assert (root / "scripts" / "open_xhs_creator.ps1").exists()
    assert (root / "Start-GUI.cmd").exists()
    assert (root / "Open-XHS-Creator.cmd").exists()


def test_gui_launcher_uses_pythonw_without_python_console_fallback():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "AutoRedbookGuiLauncher.cs").read_text(encoding="utf-8")

    assert 'Path.Combine(scriptsDir, "pythonw.exe")' in source
    assert 'Path.Combine(scriptsDir, "python.exe")' not in source
    assert "WindowStyle = ProcessWindowStyle.Hidden" in source


def test_start_gui_script_prefers_hidden_pythonw():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "start_gui.ps1").read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in source
    assert "Start-Process" in source
    assert "-WindowStyle Hidden" in source


def test_metrics_tab_has_local_table_and_sortable_headings():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "metrics_tree = ttk.Treeview" in source
    assert "刷新本地表格" in source
    assert "分析发布方向" in source
    assert "render_published_metrics_analysis" in source
    assert "_sort_metric_table" in source
    assert "list_published_metric_table_rows" in source


def test_gui_has_publish_drafts_preview_and_confirmation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "发布草稿" in source
    assert "publish_tree = ttk.Treeview" in source
    assert "list_publishable_drafts" in source
    assert "messagebox.askyesno" in source
    assert "publish-drafts" in source


def test_gui_has_daily_ai_digest_quick_title_button():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "每日AI讯息" in source
    assert 'title_var.set("每日AI讯息")' in source


def test_auto_tab_uses_multiple_prompt_entry_boxes():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "prompt_entry_vars" in source
    assert "DEFAULT_PROMPT_ENTRY_COUNT" in source
    assert "combine_prompt_entries(var.get() for var in prompt_entry_vars)" in source
    assert "split_prompt_entries_from_text(prompt_value" in source
    assert "tk.Text(auto_grid" not in source


def test_build_cli_args_auto_daily_ai_digest_keeps_special_title():
    args = build_cli_args(
        "auto",
        params={
            "title": "每日AI讯息",
            "prompt": "",
            "assets_glob": "assets/empty/*",
            "image_source": "aliyun",
            "count": 5,
        },
    )

    assert "--title" in args and "每日AI讯息" in args
    assert "--count" in args and "5" in args
    idx = args.index("--assets-glob")
    assert args[idx + 1] == AUTO_IMAGE_ASSETS_GLOB


def test_build_cli_args_auto():
    args = build_cli_args(
        "auto",
        params={
            "title": "每日新闻",
            "prompt": "美国时政",
            "evaluation_viewpoint": "产业政策视角",
            "assets_glob": "assets/pics/*",
            "count": 2,
            "no_copy": True,
            "dry_run": True,
            "headless": True,
            "login_hold": 10,
            "wait_timeout": 20,
            "force": True,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "auto"]
    assert "--title" in args and "每日新闻" in args
    assert "--prompt" in args and "美国时政" in args
    assert "--evaluation-viewpoint" in args and "产业政策视角" in args
    assert "--count" in args and "2" in args
    assert "--no-copy" in args
    assert "--dry-run" in args
    assert "--headless" in args
    assert "--force" in args


def test_build_cli_args_auto_aliyun_image_source_ignores_local_assets():
    args = build_cli_args(
        "auto",
        params={
            "title": "每日新闻",
            "prompt": "科技新闻",
            "assets_glob": "assets/pics/*",
            "image_source": "aliyun",
            "count": 1,
        },
    )

    idx = args.index("--assets-glob")
    assert args[idx + 1] == AUTO_IMAGE_ASSETS_GLOB


def test_build_cli_args_rejects_create_only():
    with pytest.raises(ValueError, match="unsupported subcommand"):
        build_cli_args(
            "create",
            params={
                "title": "标题",
                "prompt": "",
                "evaluation_viewpoint": "无视角评价",
                "assets_glob": "assets/pics/*",
                "count": 1,
            },
        )


def test_build_cli_args_delete_drafts():
    args = build_cli_args(
        "delete-drafts",
        params={
            "draft_type": "image",
            "draft_location": "publish",
            "limit": 5,
            "dry_run": True,
            "headless": True,
            "yes": True,
            "login_hold": 0,
            "wait_timeout": 300,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "delete-drafts"]
    assert "--draft-type" in args and "image" in args
    assert "--limit" in args and "5" in args
    assert "--dry-run" in args
    assert "--headless" in args
    assert "--yes" in args


def test_build_cli_args_publish_drafts_by_date_and_post_ids():
    args = build_cli_args(
        "publish-drafts",
        params={
            "date": "2026-06-29",
            "post_ids": [
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ],
            "limit": 2,
            "dry_run": True,
            "headless": True,
            "yes": True,
            "login_hold": 0,
            "wait_timeout": 600,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "publish-drafts"]
    assert "--date" in args and "2026-06-29" in args
    assert args.count("--post-id") == 2
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in args
    assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in args
    assert "--limit" in args and "2" in args
    assert "--dry-run" in args
    assert "--headless" in args
    assert "--yes" in args


def test_build_cli_args_publish_drafts_blank_filter_uses_all():
    args = build_cli_args(
        "publish-drafts",
        params={
            "date": "",
            "post_ids": [],
            "limit": 0,
            "dry_run": True,
            "headless": False,
            "yes": False,
            "login_hold": 0,
            "wait_timeout": 600,
        },
    )

    assert "--all" in args
    assert "--date" not in args
    assert "--post-id" not in args


def test_publish_tab_defaults_to_show_all_local_uploaded_drafts():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert 'publish_date_var = tk.StringVar(value="")' in source


def test_build_cli_args_update_metrics():
    args = build_cli_args(
        "update-metrics",
        params={
            "limit": 25,
            "headless": True,
            "allow_partial": False,
            "login_hold": 0,
            "wait_timeout": 300,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "update-metrics"]
    assert "--limit" in args and "25" in args
    assert "--headless" in args
    assert "--login-hold" in args and "0" in args
    assert "--wait-timeout" not in args
    assert "--allow-partial" not in args


def test_build_cli_args_update_metrics_allow_partial():
    args = build_cli_args(
        "update-metrics",
        params={
            "limit": 0,
            "headless": False,
            "allow_partial": True,
            "login_hold": 0,
            "wait_timeout": 600,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "update-metrics"]
    assert "--allow-partial" in args
    assert "--wait-timeout" not in args


def test_gui_exposes_full_metrics_sync_option():
    source = (Path(__file__).resolve().parents[1] / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "必须全量同步" in source
    assert "allow_partial" in source
    assert "全量同步会持续滚动采集" in source
    assert "metrics_wait_timeout_var" not in source


def test_build_cli_args_aliyun_quota():
    args = build_cli_args(
        "aliyun-quota",
        params={
            "models": ["qwen3.7-plus", "wan2.7-image"],
            "headless": True,
            "login_hold": 0,
            "wait_timeout": 120,
            "save_raw": True,
            "visible_only": True,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "aliyun-quota"]
    assert args.count("--model") == 2
    assert "qwen3.7-plus" in args
    assert "wan2.7-image" in args
    assert "--headless" in args
    assert "--save-raw" in args
    assert "--visible-only" in args
    assert "--login-hold" in args and "0" in args
    assert "--wait-timeout" in args and "120" in args


def test_build_cli_args_volcengine_quota():
    args = build_cli_args(
        "volcengine-quota",
        params={
            "models": ["doubao-seed-2-1-turbo-260628", "doubao-seedream-5-0-lite-260128"],
            "headless": True,
            "login_hold": 0,
            "wait_timeout": 120,
            "save_raw": True,
            "visible_only": True,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "volcengine-quota"]
    assert args.count("--model") == 2
    assert "doubao-seed-2-1-turbo-260628" in args
    assert "doubao-seedream-5-0-lite-260128" in args
    assert "--headless" in args
    assert "--save-raw" in args
    assert "--visible-only" in args
    assert "--login-hold" in args and "0" in args
    assert "--wait-timeout" in args and "120" in args


def test_build_cli_args_sync_quotas():
    args = build_cli_args(
        "sync-quotas",
        params={
            "all_free": False,
            "aliyun_models": ["glm-5.2", "qwen-image-2.0-pro-2026-06-22"],
            "volcengine_models": "glm-5.2,deepseek-v4-pro,doubao-seedream-5-0-lite-260128",
            "headless": True,
            "login_hold": 0,
            "wait_timeout": 120,
            "visible_only": True,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "sync-quotas"]
    assert "--target-only" in args
    assert args.count("--aliyun-model") == 2
    assert args.count("--volcengine-model") == 3
    assert "--headless" in args
    assert "--visible-only" in args
    assert "--login-hold" in args and "0" in args
    assert "--wait-timeout" in args and "120" in args


def test_build_cli_args_sync_quotas_defaults_to_all_free_without_target_filters():
    args = build_cli_args(
        "sync-quotas",
        params={
            "all_free": True,
            "aliyun_models": ["glm-5.2"],
            "volcengine_models": ["deepseek-v4-pro"],
            "headless": True,
            "login_hold": 0,
            "wait_timeout": 120,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "sync-quotas"]
    assert "--target-only" not in args
    assert "--aliyun-model" not in args
    assert "--volcengine-model" not in args


def test_build_quota_dashboard_rows_calculates_bar_percentages():
    rows = build_quota_dashboard_rows(
        {
            "aliyun": {
                "provider": "aliyun",
                "source_mode": "visible_page_only",
                "records": [
                    {
                        "model": "glm-5.2",
                        "kind": "llm",
                        "status": "available",
                        "remaining": 800,
                        "used": 200,
                        "total": 1000,
                        "unit": "Token",
                    },
                    {
                        "model": "qwen-image-2.0-pro-2026-06-22",
                        "kind": "image",
                        "status": "not_visible_on_page",
                    },
                ],
            }
        }
    )

    assert all(isinstance(row, QuotaDashboardRow) for row in rows)
    by_model = {row.model: row for row in rows}
    assert by_model["glm-5.2"].percent == 0.8
    assert by_model["glm-5.2"].display_value == "800/1000 Token"
    assert by_model["qwen-image-2.0-pro-2026-06-22"].percent is None
    assert by_model["qwen-image-2.0-pro-2026-06-22"].display_value == "网页未展示"


def test_build_quota_dashboard_rows_formats_large_numbers_without_scientific_notation():
    rows = build_quota_dashboard_rows(
        {
            "aliyun": {
                "provider": "aliyun",
                "records": [
                    {
                        "model": "glm-5.2",
                        "kind": "llm",
                        "status": "available",
                        "remaining": 205875.0,
                        "total": 1000000.0,
                        "unit": "token",
                    }
                ],
            }
        }
    )

    assert rows[0].display_value == "205875/1000000 token"


def test_filter_quota_dashboard_rows_matches_model_provider_kind_and_status():
    rows = [
        QuotaDashboardRow(
            provider="aliyun",
            model="glm-5.2",
            kind="llm",
            status="available",
            display_value="205875 / 1000000 token",
        ),
        QuotaDashboardRow(
            provider="volcengine",
            model="doubao-seedream-5-0-lite-260128",
            kind="image",
            status="available",
            display_value="37 / 50 张",
        ),
        QuotaDashboardRow(
            provider="aliyun",
            model="qwen-audio",
            kind="unknown",
            status="not_visible_on_page",
            display_value="网页未展示",
        ),
    ]

    assert [row.model for row in filter_quota_dashboard_rows(rows, "seedream image")] == [
        "doubao-seedream-5-0-lite-260128"
    ]
    assert [row.model for row in filter_quota_dashboard_rows(rows, "aliyun token")] == ["glm-5.2"]
    assert [row.model for row in filter_quota_dashboard_rows(rows, "not_visible")] == ["qwen-audio"]
    assert filter_quota_dashboard_rows(rows, "   ") == rows


def test_sort_quota_dashboard_rows_orders_numeric_values_with_unknown_last():
    rows = [
        QuotaDashboardRow(provider="aliyun", model="unknown", remaining=None, percent=None),
        QuotaDashboardRow(provider="aliyun", model="low", remaining=10, percent=0.1),
        QuotaDashboardRow(provider="volcengine", model="high", remaining=900, percent=0.9),
    ]

    assert [row.model for row in sort_quota_dashboard_rows(rows, "remaining", descending=True)] == [
        "high",
        "low",
        "unknown",
    ]
    assert [row.model for row in sort_quota_dashboard_rows(rows, "percent", descending=False)] == [
        "low",
        "high",
        "unknown",
    ]


def test_quota_dashboard_layout_keeps_long_names_and_values_on_one_line():
    rows = build_quota_dashboard_rows(
        {
            "volcengine": {
                "provider": "volcengine",
                "records": [
                    {
                        "model": "doubao-seed-1-6-lite",
                        "kind": "llm",
                        "status": "available",
                        "remaining": 500000,
                        "total": 500000,
                        "unit": "token",
                    }
                ],
            }
        }
    )
    row = rows[0]
    layout = quota_dashboard_layout(640)
    title = quota_dashboard_row_title(row, layout["model_width"])

    assert "\n" not in title
    assert title.startswith("doubao-seed-1-6-lite")
    assert " / " not in row.display_value
    assert row.display_value == "500000/500000 token"
    assert layout["value_width"] >= 145


def test_load_latest_quota_snapshots_skips_empty_failure_snapshot(tmp_path: Path):
    quota_dir = tmp_path / "quota"
    quota_dir.mkdir()
    old_valid = quota_dir / "aliyun_quota_20260704_001000.json"
    old_valid.write_text(
        json.dumps({"provider": "aliyun", "records": [{"model": "glm-5.2", "remaining": 10}]}),
        encoding="utf-8",
    )
    latest_empty = quota_dir / "aliyun_quota_20260704_002000.json"
    latest_empty.write_text(
        json.dumps({"provider": "aliyun", "records": [], "errors": ["login required"]}),
        encoding="utf-8",
    )
    os.utime(old_valid, (1000, 1000))
    os.utime(latest_empty, (2000, 2000))

    snapshots = load_latest_quota_snapshots(quota_dir=quota_dir, providers=("aliyun",))

    assert snapshots["aliyun"]["_snapshot_name"] == old_valid.name


def test_quota_dashboard_selection_target_distinguishes_llm_and_image_rows():
    llm_row = QuotaDashboardRow(
        provider="volcengine",
        model="glm-5.2",
        kind="llm",
        status="available",
        remaining=500000,
    )
    image_row = QuotaDashboardRow(
        provider="aliyun",
        model="qwen-image-2.0-pro-2026-06-22",
        kind="image",
        status="available",
        remaining=100,
    )
    local_row = QuotaDashboardRow(provider="unknown", model="glm-5.2", kind="llm")
    exhausted_row = QuotaDashboardRow(
        provider="aliyun",
        model="qwen3.7-plus",
        kind="llm",
        status="exhausted",
        remaining=0,
    )

    assert quota_dashboard_selection_target(llm_row) == ("llm", "volcengine", "glm-5.2")
    assert quota_dashboard_selection_target(image_row) == (
        "image",
        "aliyun",
        "qwen-image-2.0-pro-2026-06-22",
    )
    assert quota_dashboard_selection_target(local_row) is None
    assert quota_dashboard_selection_target(exhausted_row) is None


def test_quota_dashboard_selection_target_infers_image_models_with_unknown_kind():
    seedream_row = QuotaDashboardRow(
        provider="volcengine",
        model="doubao-seedream-5-0",
        kind="unknown",
        status="available",
        remaining=37,
    )
    qwen_image_row = QuotaDashboardRow(
        provider="aliyun",
        model="qwen-image-2.0-pro-2026-06-22",
        kind="unknown",
        status="available",
        remaining=98,
    )
    video_row = QuotaDashboardRow(
        provider="aliyun",
        model="wan2.7-t2v-2026-06-12",
        kind="unknown",
        status="available",
        remaining=50,
    )

    assert quota_dashboard_selection_target(seedream_row) == ("image", "volcengine", "doubao-seedream-5-0")
    assert quota_dashboard_selection_target(qwen_image_row) == (
        "image",
        "aliyun",
        "qwen-image-2.0-pro-2026-06-22",
    )
    assert quota_dashboard_selection_target(video_row) is None


def test_quota_dashboard_row_kind_label_explains_inferred_and_display_only_rows():
    seedream_row = QuotaDashboardRow(
        provider="volcengine",
        model="doubao-seedream-5-0",
        kind="unknown",
        status="available",
        remaining=37,
    )
    video_row = QuotaDashboardRow(
        provider="aliyun",
        model="wan2.7-t2v-2026-06-12",
        kind="unknown",
        status="available",
        remaining=50,
    )
    unavailable_row = QuotaDashboardRow(
        provider="volcengine",
        model="doubao-seed-evolving",
        kind="llm",
        status="unavailable",
        remaining=500000,
    )

    assert quota_dashboard_row_kind_label(seedream_row) == "image · 推断"
    assert quota_dashboard_row_kind_label(video_row) == "仅展示"
    assert quota_dashboard_row_kind_label(unavailable_row) == "llm · 不可用"


def test_merge_model_option_values_appends_clicked_quota_model_without_duplicates():
    values = merge_model_option_values(("glm-5.1", "glm-5.2"), "deepseek-v4-pro")

    assert values == ("glm-5.1", "glm-5.2", "deepseek-v4-pro")
    assert merge_model_option_values(values, "glm-5.2") == values


def test_auto_tab_has_quota_dashboard_instead_of_default_preview():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "quota_dashboard_panel" in source
    assert "quota_rows_canvas" in source
    assert "quota_model_button" in source
    assert "quota_row_hit" in source
    assert "quota_search_var" in source
    assert "quota_sort_var" in source
    assert "quota_dashboard_layout" in source
    assert "quota_dashboard_row_title" in source
    assert "width=96" not in source
    assert "prepare_quota_dashboard_rows" in source
    assert "模型额度" in source
    assert "同步免费额度" in source
    assert "sync-quotas" in source
    assert "_show_right_bottom_panel(\"quota\")" in source
    assert 'ttk.Label(preview_header, text="草稿预览"' not in source


def test_quota_sync_defaults_to_visible_login_browser():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "quota_sync_headless_var = tk.BooleanVar(value=False)" in source
    assert '"login_hold": DEFAULT_LOGIN_HOLD if not quota_sync_headless_var.get() else 0' in source


def test_gui_has_aliyun_quota_panel():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "aliyun-quota" in source
    assert "Aliyun Bailian quota" in source
    assert "Save raw snapshot" in source
    assert "Visible page only" in source


def test_gui_has_volcengine_quota_panel():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert "volcengine-quota" in source
    assert "Volcengine Ark quota" in source
    assert "Save raw snapshot" in source
    assert "Visible page only" in source


def test_gui_no_longer_exposes_create_only_tab():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps" / "gui.py").read_text(encoding="utf-8")

    assert 'nb.add(tab_create, text="仅生成")' not in source
    assert "运行 create：只生成本地草稿" not in source


def test_delete_mode_labels_are_explicit_and_non_symbolic():
    text = DELETE_MODE_PREVIEW + DELETE_MODE_DELETE + DELETE_CONFIRM_ASK + DELETE_CONFIRM_AUTO

    assert "不删除" in DELETE_MODE_PREVIEW
    assert "会删除" in DELETE_MODE_DELETE
    assert "执行前确认" in DELETE_CONFIRM_ASK
    assert "自动确认" in DELETE_CONFIRM_AUTO
    assert "❌" not in text
    assert "dry-run" not in text
    assert "--yes" not in text


def test_resolve_delete_mode_flags_keeps_preview_safe():
    assert resolve_delete_mode_flags(DELETE_MODE_PREVIEW, DELETE_CONFIRM_ASK) == (True, False)
    assert resolve_delete_mode_flags(DELETE_MODE_PREVIEW, DELETE_CONFIRM_AUTO) == (True, False)
    assert resolve_delete_mode_flags(DELETE_MODE_DELETE, DELETE_CONFIRM_ASK) == (False, False)
    assert resolve_delete_mode_flags(DELETE_MODE_DELETE, DELETE_CONFIRM_AUTO) == (False, True)


def test_build_cli_args_approve():
    args = build_cli_args(
        "approve",
        params={"post_id": "0123456789abcdef0123456789abcdef", "force": True},
    )
    assert args[1:4] == ["-m", "apps.cli", "approve"]
    assert "0123456789abcdef0123456789abcdef" in args
    assert "--force" in args


def test_build_cli_args_run():
    args = build_cli_args(
        "run",
        params={
            "post_id": "0123456789abcdef0123456789abcdef",
            "assets_glob": "",
            "dry_run": True,
            "headless": True,
            "login_hold": 10,
            "wait_timeout": 20,
            "force": True,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "run"]
    assert "0123456789abcdef0123456789abcdef" in args
    assert "--assets-glob" not in args  # empty glob should be omitted
    assert "--dry-run" in args
    assert "--headless" in args
    assert "--login-hold" in args and "10" in args
    assert "--wait-timeout" in args and "20" in args
    assert "--force" in args
