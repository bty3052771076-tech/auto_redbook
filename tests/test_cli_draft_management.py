from __future__ import annotations

from typer.testing import CliRunner

import apps.cli as cli
from src.publish.draft_management import DraftImage, PlatformDraftSnapshot


def _snapshot(title: str = "平台草稿一") -> dict:
    return PlatformDraftSnapshot(
        snapshot_id="snap-1",
        platform_draft_id="platform-1",
        title=title,
        body="这是一个具体事件的正文，包含主体、进展和可核验事实。",
        saved_at="2026-09-18T09:00:00+08:00",
        images=(DraftImage(source="cover.png", sha256="abc"),),
    ).to_dict()


def test_manage_drafts_review_saves_auditable_results(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_inspect_platform_drafts_sync",
        lambda **_kwargs: {"snapshots": [_snapshot()], "total": 1, "inspected": 1, "complete": True, "errors": []},
    )

    result = CliRunner().invoke(cli.app, ["manage-drafts", "--mode", "review", "--headless", "--run-id", "review-1"])

    assert result.exit_code == 0, result.output
    assert "accepted=1" in result.output
    assert (tmp_path / "data" / "runs" / "draft_management" / "review-1" / "checkpoint.json").exists()
    assert "reviews.jsonl" in " ".join(
        str(path) for path in (tmp_path / "data" / "runs" / "draft_management" / "review-1").rglob("*")
    )


def test_manage_drafts_publish_requires_explicit_confirmation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_inspect_platform_drafts_sync",
        lambda **_kwargs: {"snapshots": [_snapshot()], "total": 1, "inspected": 1, "complete": True, "errors": []},
    )

    result = CliRunner().invoke(cli.app, ["manage-drafts", "--mode", "publish", "--headless"])

    assert result.exit_code == 1
    assert "--yes" in result.output


def test_manage_drafts_publish_uses_only_accepted_platform_snapshots(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_inspect_platform_drafts_sync",
        lambda **_kwargs: {"snapshots": [_snapshot()], "total": 1, "inspected": 1, "complete": True, "errors": []},
    )
    calls = []

    def fake_publish(**kwargs):
        calls.append(kwargs)
        return {"published": 1, "total": 1, "published_post_ids": [kwargs["posts"][0].id], "items": [], "errors": []}

    monkeypatch.setattr(cli, "run_publish_drafts_sync", fake_publish)

    result = CliRunner().invoke(
        cli.app,
        ["manage-drafts", "--mode", "publish", "--yes", "--headless", "--run-id", "publish-1"],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert len(calls[0]["posts"]) == 1
    assert "published=1" in result.output


def test_manage_drafts_excludes_duplicate_platform_snapshots_in_same_scan(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    duplicate = _snapshot()
    duplicate["snapshot_id"] = "snap-2"
    monkeypatch.setattr(
        cli,
        "run_inspect_platform_drafts_sync",
        lambda **_kwargs: {
            "snapshots": [_snapshot(), duplicate],
            "total": 2,
            "inspected": 2,
            "complete": True,
            "errors": [],
        },
    )

    result = CliRunner().invoke(
        cli.app,
        ["manage-drafts", "--mode", "review", "--headless", "--run-id", "duplicate-1"],
    )

    assert result.exit_code == 0, result.output
    assert "accepted=1" in result.output
    assert "excluded=1" in result.output
    assert "duplicate_batch" in result.output
