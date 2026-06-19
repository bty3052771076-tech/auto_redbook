from __future__ import annotations

from pathlib import Path

from apps.gui import (
    ALIYUN_IMAGE_MODEL_OPTIONS,
    ALIYUN_LLM_MODEL_OPTIONS,
    DEFAULT_DRAFT_URL,
    DEFAULT_IMAGE_PROVIDER,
    LLM_PROVIDER_OPTIONS,
    build_cli_args,
    build_provider_env_overrides,
    extract_post_id_from_choice,
    format_post_choice,
    format_post_detail,
    list_recent_posts,
    load_env_file,
    save_env_file,
)


def test_gui_default_image_provider_prefers_available_search_provider():
    assert DEFAULT_IMAGE_PROVIDER == "pexels"


def test_gui_exposes_llm_and_image_provider_model_options():
    assert LLM_PROVIDER_OPTIONS == ["aliyun", "ppinfra", "auto"]
    assert "qwen3.7-plus" in ALIYUN_LLM_MODEL_OPTIONS
    assert "deepseek-v4-flash" in ALIYUN_LLM_MODEL_OPTIONS
    assert ALIYUN_IMAGE_MODEL_OPTIONS == ["wan2.7-image", "wan2.7-image-pro"]


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
    assert any("2026-06-19 12:34:56" in label for label in labels)
    assert second_item.uploaded is True
    assert second_item.uploaded_at == "2026-06-19T12:34:56.000000Z"
    assert second_item.latest_execution_result == "saved_draft"
    assert second_item.asset_count == 1


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
    assert "2026-06-19 12:34:56" in detail
    assert "saved_draft" in detail
    assert "素材数量：1" in detail
    assert "要点摘要" in detail


def test_xhs_creator_quick_launch_target_uses_image_publish_url():
    assert DEFAULT_DRAFT_URL == "https://creator.xiaohongshu.com/publish/publish?target=image"


def test_quick_launch_scripts_are_workspace_local():
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "start_gui.ps1").exists()
    assert (root / "scripts" / "open_xhs_creator.ps1").exists()
    assert (root / "Start-GUI.cmd").exists()
    assert (root / "Open-XHS-Creator.cmd").exists()


def test_build_cli_args_auto():
    args = build_cli_args(
        "auto",
        params={
            "title": "每日新闻",
            "prompt": "美国时政",
            "assets_glob": "assets/pics/*",
            "count": 2,
            "no_copy": True,
            "dry_run": True,
            "login_hold": 10,
            "wait_timeout": 20,
            "force": True,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "auto"]
    assert "--title" in args and "每日新闻" in args
    assert "--prompt" in args and "美国时政" in args
    assert "--count" in args and "2" in args
    assert "--no-copy" in args
    assert "--dry-run" in args
    assert "--force" in args


def test_build_cli_args_create():
    args = build_cli_args(
        "create",
        params={
            "title": "标题",
            "prompt": "",
            "assets_glob": "assets/pics/*",
            "count": 1,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "create"]
    assert "--title" in args and "标题" in args
    assert "--prompt" not in args  # empty prompt should be omitted


def test_build_cli_args_delete_drafts():
    args = build_cli_args(
        "delete-drafts",
        params={
            "draft_type": "image",
            "draft_location": "publish",
            "limit": 5,
            "dry_run": True,
            "yes": True,
            "login_hold": 0,
            "wait_timeout": 300,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "delete-drafts"]
    assert "--draft-type" in args and "image" in args
    assert "--limit" in args and "5" in args
    assert "--dry-run" in args
    assert "--yes" in args


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
            "login_hold": 10,
            "wait_timeout": 20,
            "force": True,
        },
    )
    assert args[1:4] == ["-m", "apps.cli", "run"]
    assert "0123456789abcdef0123456789abcdef" in args
    assert "--assets-glob" not in args  # empty glob should be omitted
    assert "--dry-run" in args
    assert "--login-hold" in args and "10" in args
    assert "--wait-timeout" in args and "20" in args
    assert "--force" in args
