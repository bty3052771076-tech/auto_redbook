from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import apps.cli as cli
from src.storage.models import Execution


@pytest.fixture(autouse=True)
def fake_live_xhs_draft_scan(monkeypatch):
    """Keep CLI unit tests read-only while exercising live-intersection logic."""

    def _scan(**kwargs):
        items = []
        for index, post in enumerate(cli.list_posts()):
            if not post.uploaded and str(post.status) != "PostStatus.saved_draft":
                continue
            xhs = post.platform.get("xhs_draft") if isinstance(post.platform, dict) else {}
            xhs = xhs if isinstance(xhs, dict) else {}
            items.append(
                {
                    "index": str(index),
                    "title": str(xhs.get("title") or post.title),
                    "saved_at": str(xhs.get("saved_at") or post.uploaded_at or ""),
                    "draft_type": kwargs.get("draft_type", "image"),
                }
            )
        return {"items": items, "total": len(items), "errors": []}

    monkeypatch.setattr(cli, "run_collect_platform_drafts_sync", _scan)


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


def _write_legacy_saved_draft_post(base: Path, post_id: str, *, title: str, uploaded_at: str) -> None:
    post_dir = base / "data" / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "saved_as_draft",
                "uploaded": False,
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


def _write_published_post(base: Path, post_id: str, *, title: str, uploaded_at: str) -> None:
    _write_uploaded_post(base, post_id, title=title, uploaded_at=uploaded_at)
    path = base / "data" / "posts" / post_id / "post.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "published"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_run_can_copy_an_xhs_published_post_to_toutiao_without_force(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "abababababababababababababababab"
    _write_published_post(
        tmp_path,
        post_id,
        title="已发布内容同步到头条",
        uploaded_at="2026-08-04T01:00:00Z",
    )
    asset = tmp_path / "assets" / "example.png"
    asset.parent.mkdir()
    asset.write_bytes(b"image")
    calls: list[str] = []

    monkeypatch.setattr(
        cli,
        "run_save_toutiao_draft_sync",
        lambda post, **_kwargs: calls.append(post.id)
        or Execution(post_id=post.id, result="saved_draft", id="toutiao-run"),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("xhs uploader must not run")),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            post_id,
            "--platform",
            "toutiao",
            "--assets-glob",
            str(asset),
            "--headless",
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [post_id]
    stored = json.loads((tmp_path / "data" / "posts" / post_id / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "published"
    assert stored["platform"]["toutiao_draft"]["execution_id"] == "toutiao-run"


def test_run_dry_run_returns_nonzero_when_toutiao_preflight_fails(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "acacacacacacacacacacacacacacacac"
    _write_published_post(
        tmp_path,
        post_id,
        title="头条权益预检失败",
        uploaded_at="2026-08-04T01:00:00Z",
    )
    asset = tmp_path / "assets" / "example.png"
    asset.parent.mkdir()
    asset.write_bytes(b"image")

    monkeypatch.setattr(
        cli,
        "run_save_toutiao_draft_sync",
        lambda post, **_kwargs: Execution(
            post_id=post.id,
            result="failed",
            error={"message": "头条号尚未开通文章发布权益"},
        ),
        raising=False,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            post_id,
            "--platform",
            "toutiao",
            "--assets-glob",
            str(asset),
            "--headless",
            "--dry-run",
        ],
    )

    assert result.exit_code == 1, result.output
    assert "failed platforms: toutiao" in result.output


def test_run_preserves_existing_xhs_saved_status_when_toutiao_retry_fails(
    monkeypatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    post_id = "adadadadadadadadadadadadadadadad"
    _write_uploaded_post(
        tmp_path,
        post_id,
        title="小红书已保存但头条待验证",
        uploaded_at="2026-08-05T07:00:00Z",
    )
    post_path = tmp_path / "data" / "posts" / post_id / "post.json"
    payload = json.loads(post_path.read_text(encoding="utf-8"))
    payload["platform"]["xhs_draft"] = {
        "title": payload["title"],
        "saved_at": "2026-08-05T07:00:00Z",
        "execution_id": "xhs-ok",
    }
    post_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    asset = tmp_path / "assets" / "example.png"
    asset.parent.mkdir()
    asset.write_bytes(b"image")

    monkeypatch.setattr(
        cli,
        "run_save_toutiao_draft_sync",
        lambda post, **_kwargs: Execution(
            post_id=post.id,
            result="failed",
            error={"message": "code=7050，需要短信身份校验"},
        ),
        raising=False,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "run",
            post_id,
            "--platform",
            "toutiao",
            "--assets-glob",
            str(asset),
            "--headless",
        ],
    )

    assert result.exit_code == 1
    stored = json.loads(post_path.read_text(encoding="utf-8"))
    assert stored["status"] == "saved_as_draft"
    assert stored["platform"]["xhs_draft"]["execution_id"] == "xhs-ok"


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


def test_publish_drafts_accepts_legacy_saved_draft_without_uploaded_flag(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "dddddddddddddddddddddddddddddddd"
    _write_legacy_saved_draft_post(
        tmp_path,
        post_id,
        title="历史已上传草稿",
        uploaded_at="2026-06-29T01:00:00.000000Z",
    )
    calls: list[dict] = []

    def fake_run_publish_drafts_sync(**kwargs):
        calls.append(kwargs)
        return {
            "draft_type": "image",
            "total": 1,
            "published": 0,
            "items": [{"post_id": post_id, "title": "历史已上传草稿"}],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_run_publish_drafts_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        [
            "publish-drafts",
            "--post-id",
            post_id,
            "--dry-run",
            "--login-hold",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["posts"][0].id == post_id


def test_update_draft_updates_existing_platform_draft_without_changing_local_draft_status(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    post_id = "cccccccccccccccccccccccccccccccc"
    _write_uploaded_post(
        tmp_path,
        post_id,
        title="已保存草稿",
        uploaded_at="2026-06-29T01:00:00.000000Z",
    )
    calls: list[dict] = []

    def fake_run_update_draft_sync(post, **kwargs):
        calls.append({"post": post, **kwargs})
        return cli.Execution(post_id=post.id, result="saved_draft")

    monkeypatch.setattr(cli, "run_update_draft_sync", fake_run_update_draft_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        ["update-draft", post_id, "--headless", "--login-hold", "0", "--wait-timeout", "600"],
    )

    assert result.exit_code == 0
    assert calls
    assert calls[0]["post"].id == post_id
    assert calls[0]["draft_type"] == "image"
    assert calls[0]["headless"] is True
    stored = json.loads((tmp_path / "data" / "posts" / post_id / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "saved_as_draft"
    assert stored["uploaded"] is True
    assert stored["platform"]["draft_update"]["result"] == "saved_draft"


def test_update_draft_uses_saved_platform_title_when_local_title_changed(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    _write_uploaded_post(
        tmp_path,
        post_id,
        title="每日AI|Claude发现加密弱点",
        uploaded_at="2026-07-29T12:09:44.231880Z",
    )
    post_path = tmp_path / "data" / "posts" / post_id / "post.json"
    payload = json.loads(post_path.read_text(encoding="utf-8"))
    payload["platform"] = {"xhs_draft": {"title": "每日AI讯息"}}
    post_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    calls: list[dict] = []

    def fake_run_update_draft_sync(post, **kwargs):
        calls.append({"post": post, **kwargs})
        return cli.Execution(post_id=post.id, result="saved_draft")

    monkeypatch.setattr(cli, "run_update_draft_sync", fake_run_update_draft_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        ["update-draft", post_id, "--headless", "--login-hold", "0", "--wait-timeout", "600"],
    )

    assert result.exit_code == 0
    assert calls[0]["existing_title"] == "每日AI讯息"
    stored = json.loads(post_path.read_text(encoding="utf-8"))
    assert stored["platform"]["xhs_draft"]["title"] == "每日AI|Claude发现加密弱点"


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


def test_publish_drafts_all_with_limit_prefers_latest_uploaded_post(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    old_id = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    latest_id = "ffffffffffffffffffffffffffffffff"
    _write_uploaded_post(
        tmp_path,
        old_id,
        title="旧草稿",
        uploaded_at="2026-06-20T01:00:00.000000Z",
    )
    _write_uploaded_post(
        tmp_path,
        latest_id,
        title="新草稿",
        uploaded_at="2026-06-29T01:00:00.000000Z",
    )
    calls: list[dict] = []

    def fake_run_publish_drafts_sync(**kwargs):
        calls.append(kwargs)
        return {
            "draft_type": "image",
            "total": 1,
            "published": 0,
            "items": [{"post_id": latest_id, "title": "新草稿"}],
            "errors": [],
        }

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_run_publish_drafts_sync, raising=False)

    result = CliRunner().invoke(
        cli.app,
        [
            "publish-drafts",
            "--all",
            "--limit",
            "1",
            "--dry-run",
            "--login-hold",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert calls
    assert [post.id for post in calls[0]["posts"]] == [latest_id]


def test_publish_drafts_exits_when_explicit_local_id_is_missing_on_platform(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "11111111111111111111111111111111"
    _write_uploaded_post(tmp_path, post_id, title="Not on platform", uploaded_at="2026-08-20T01:00:00.000000Z")
    monkeypatch.setattr(cli, "run_collect_platform_drafts_sync", lambda **_kwargs: {"items": [], "total": 0, "errors": []})

    result = CliRunner().invoke(cli.app, ["publish-drafts", "--post-id", post_id, "--yes"])

    assert result.exit_code == 1
    assert "no publishable drafts remain" in result.output


def test_publish_drafts_fails_closed_when_platform_scan_errors(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "22222222222222222222222222222222"
    _write_uploaded_post(tmp_path, post_id, title="Scan error", uploaded_at="2026-08-20T01:00:00.000000Z")
    monkeypatch.setattr(
        cli,
        "run_collect_platform_drafts_sync",
        lambda **_kwargs: {"items": [], "total": 0, "errors": ["login required"]},
    )

    result = CliRunner().invoke(cli.app, ["publish-drafts", "--post-id", post_id, "--yes"])

    assert result.exit_code == 1
    assert "scan failed closed" in result.output


def test_publish_drafts_rechecks_platform_before_runner(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "33333333333333333333333333333333"
    _write_uploaded_post(tmp_path, post_id, title="Removed before publish", uploaded_at="2026-08-20T01:00:00.000000Z")
    scans = iter(
        [
            {"items": [{"index": "0", "title": "Removed before publish", "saved_at": "2026-08-20 09:00:00"}], "total": 1, "errors": []},
            {"items": [], "total": 0, "errors": []},
        ]
    )
    monkeypatch.setattr(cli, "run_collect_platform_drafts_sync", lambda **_kwargs: next(scans))
    called = False

    def fake_run_publish(**_kwargs):
        nonlocal called
        called = True
        return {"published": 0, "items": [], "errors": []}

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_run_publish)

    result = CliRunner().invoke(cli.app, ["publish-drafts", "--post-id", post_id, "--yes"])

    assert result.exit_code == 1
    assert called is False
    assert "no longer present" in result.output
