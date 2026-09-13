from __future__ import annotations

from pathlib import Path

import pytest
import typer
from PIL import Image

import apps.cli as cli
from src.publish.draft_delivery import content_revision_fingerprint
from src.storage.models import AssetInfo, Post, PostStatus


def test_run_force_cannot_bypass_text_integrity_errors(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "cover.png"
    Image.new("RGB", (128, 128), (20, 80, 140)).save(image_path)
    post = Post(
        id="post-with-corruption",
        status=PostStatus.approved,
        title="A valid title",
        body="Body with ??? corruption",
        assets=[AssetInfo(path=str(image_path), kind="image")],
    )
    called = False

    monkeypatch.setattr(cli, "load_post", lambda _post_id: post)
    monkeypatch.setattr(cli, "_emit_progress_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_emit_validation", lambda _result: None)

    def fake_runner(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("invalid content must not reach the upload runner")

    monkeypatch.setattr(cli, "run_save_draft_sync", fake_runner)

    with pytest.raises(typer.Exit):
        cli.run(
            post_id=post.id,
            platform="xhs",
            force=True,
            dry_run=False,
            headless=True,
            login_hold=0,
            wait_timeout=1,
            assets_glob="",
        )

    assert called is False


def test_run_skips_duplicate_upload_when_current_revision_receipt_matches(
    monkeypatch, tmp_path: Path
):
    image_path = tmp_path / "cover.png"
    Image.new("RGB", (128, 128), (20, 80, 140)).save(image_path)
    post = Post(
        id="already-saved",
        status=PostStatus.saved_draft,
        title="Current title",
        body="Current body",
        assets=[AssetInfo(path=str(image_path), kind="image")],
    )
    post.platform["xhs_draft"] = {
        "title": post.title,
        "saved_at": post.updated_at,
        "revision_fingerprint": content_revision_fingerprint(post),
    }
    runner_called = False

    monkeypatch.setattr(cli, "load_post", lambda _post_id: post)
    monkeypatch.setattr(cli, "save_post", lambda _post: None)
    monkeypatch.setattr(cli, "_emit_progress_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_emit_validation", lambda _result: None)
    monkeypatch.setattr(cli, "_resolve_asset_paths", lambda *_args: [str(image_path)])

    def fake_runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("matching revision must be a no-op")

    monkeypatch.setattr(cli, "run_save_draft_sync", fake_runner)

    cli.run(
        post_id=post.id,
        platform="xhs",
        force=True,
        dry_run=False,
        headless=True,
        login_hold=0,
        wait_timeout=1,
        assets_glob="",
    )

    assert runner_called is False
