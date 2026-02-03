from __future__ import annotations

from pathlib import Path

from apps.gui import build_cli_args, load_env_file, save_env_file


def test_env_file_roundtrip(tmp_path: Path):
    p = tmp_path / ".env.gui"
    save_env_file(p, {"FOO": "bar", "HAS_SPACE": "a b", "EMPTY": ""})
    data = load_env_file(p)
    assert data["FOO"] == "bar"
    assert data["HAS_SPACE"] == "a b"
    assert "EMPTY" not in data


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
