from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli


def _write_uploaded_post(base: Path, post_id: str, *, title: str, uploaded_at: str) -> None:
    post_dir = base / "data" / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "saved_as_draft",
                "uploaded": True,
                "uploaded_at": uploaded_at,
                "title": title,
                "body": "正文预览",
                "topics": ["每日新闻"],
                "assets": [{"path": "assets/example.png", "kind": "image"}],
                "platform": {},
                "created_at": uploaded_at,
                "updated_at": uploaded_at,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_publish_drafts_requires_a_selector(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli.app, ["publish-drafts", "--yes"])

    assert result.exit_code == 1
    assert "请至少选择发布日期、post_id 或 --all" in result.output


def test_publish_drafts_publishes_selected_uploaded_post_and_updates_local_status(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    post_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write_uploaded_post(
        tmp_path,
        post_id,
        title="测试发布草稿",
        uploaded_at="2026-06-29T01:00:00.000000Z",
    )
    calls: list[dict] = []

    def fake_run_publish_drafts_sync(**kwargs):
        calls.append(kwargs)
        return {
            "draft_type": kwargs.get("draft_type", "image"),
            "total": 1,
            "published": 1,
            "items": [
                {
                    "post_id": post_id,
                    "title": "测试发布草稿",
                    "actual_title": "平台发布前实际标题",
                    "actual_body": "平台发布前实际正文",
                }
            ],
            "published_post_ids": [post_id],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_run_publish_drafts_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        [
            "publish-drafts",
            "--post-id",
            post_id,
            "--yes",
            "--login-hold",
            "0",
            "--wait-timeout",
            "600",
        ],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["posts"][0].id == post_id
    assert calls[0]["dry_run"] is False
    assert "published 1/1 drafts" in result.output
    stored = json.loads((tmp_path / "data" / "posts" / post_id / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "published"
    assert stored["uploaded"] is True
    assert stored["platform"]["publish"]["result"] == "published"
    assert stored["platform"]["publish"]["actual_title"] == "平台发布前实际标题"
    assert stored["platform"]["publish"]["actual_body"] == "平台发布前实际正文"


def test_publish_drafts_dry_run_previews_without_updating_status(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _write_uploaded_post(
        tmp_path,
        post_id,
        title="预览草稿",
        uploaded_at="2026-06-28T16:30:00.000000Z",
    )
    called = False

    def fake_run_publish_drafts_sync(**kwargs):
        nonlocal called
        called = True
        assert kwargs["dry_run"] is True
        return {
            "draft_type": "image",
            "total": 1,
            "published": 0,
            "items": [{"post_id": post_id, "title": "预览草稿", "saved_at": "今天 10:00"}],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_run_publish_drafts_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        [
            "publish-drafts",
            "--date",
            "2026-06-29",
            "--dry-run",
            "--login-hold",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert called is True
    assert "type=image total=1" in result.output
    stored = json.loads((tmp_path / "data" / "posts" / post_id / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "saved_as_draft"
