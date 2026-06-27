from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

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
    RecentPostSummary,
    UiEventQueue,
    build_xhs_login_launch_args,
    build_xhs_creator_launch_args,
    build_cli_args,
    build_provider_env_overrides,
    build_subprocess_env,
    ensure_daily_news_candidate_pool_env,
    env_flag_enabled,
    env_int_value,
    extract_post_id_from_choice,
    format_post_choice,
    format_post_detail,
    format_post_time_detail,
    list_published_metric_table_rows,
    list_recent_posts,
    load_env_file,
    open_xhs_creator,
    resolve_assets_glob_for_image_source,
    resolve_delete_mode_flags,
    save_env_file,
    sort_published_metric_table_rows,
)


def test_gui_default_image_provider_prefers_ai_generation():
    assert DEFAULT_IMAGE_PROVIDER == "aliyun"


def test_gui_exposes_llm_and_image_provider_model_options():
    assert LLM_PROVIDER_OPTIONS == ["aliyun", "ppinfra", "auto"]
    assert IMAGE_SOURCE_OPTIONS == ["local", "aliyun", "pexels"]
    assert "qwen3.7-plus" in ALIYUN_LLM_MODEL_OPTIONS
    assert "deepseek-v4-flash" in ALIYUN_LLM_MODEL_OPTIONS
    assert ALIYUN_IMAGE_MODEL_OPTIONS == [
        "wan2.7-image",
        "wan2.7-image-pro",
        "qwen-image-2.0-pro-2026-04-22",
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
    while not any("仍在运行" in line for line in lines) and time.time() < deadline:
        time.sleep(0.01)

    release.set()
    deadline = time.time() + 2
    while (runner.is_running() or not exits) and time.time() < deadline:
        time.sleep(0.01)

    assert any("仍在运行" in line for line in lines)
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

    assert int(env["NEWS_MAX_RECORDS"]) >= 60
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


def test_ensure_daily_news_candidate_pool_env_keeps_larger_user_value():
    env = ensure_daily_news_candidate_pool_env(
        {"NEWS_MAX_RECORDS": "120"},
        title="\u6bcf\u65e5\u65b0\u95fb",
        count=3,
    )

    assert env["NEWS_MAX_RECORDS"] == "120"


def test_ensure_daily_news_candidate_pool_env_does_not_expand_other_titles():
    env = ensure_daily_news_candidate_pool_env(
        {},
        title="\u79d1\u6280\u9009\u9898",
        count=3,
    )

    assert "NEWS_MAX_RECORDS" not in env
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


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


def test_build_cli_args_create():
    args = build_cli_args(
        "create",
        params={
            "title": "标题",
            "prompt": "",
            "evaluation_viewpoint": "无视角评价",
            "assets_glob": "assets/pics/*",
            "count": 1,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "create"]
    assert "--title" in args and "标题" in args
    assert "--prompt" not in args  # empty prompt should be omitted
    assert "--evaluation-viewpoint" in args and "无视角评价" in args


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


def test_build_cli_args_update_metrics():
    args = build_cli_args(
        "update-metrics",
        params={
            "limit": 25,
            "headless": True,
            "login_hold": 0,
            "wait_timeout": 300,
        },
    )

    assert args[1:4] == ["-m", "apps.cli", "update-metrics"]
    assert "--limit" in args and "25" in args
    assert "--headless" in args
    assert "--login-hold" in args and "0" in args
    assert "--wait-timeout" in args and "300" in args


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
