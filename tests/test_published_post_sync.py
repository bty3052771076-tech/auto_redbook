from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli
from src.analytics.post_sync import sync_published_metrics_to_posts


def test_sync_published_metrics_to_posts_marks_uploaded_draft_published(tmp_path: Path):
    post_id = "cccccccccccccccccccccccccccccccc"
    post_dir = tmp_path / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "saved_as_draft",
                "uploaded": True,
                "uploaded_at": "2026-06-29T00:00:00.000000Z",
                "title": "Local title before publish",
                "body": "Local draft body",
                "topics": [],
                "assets": [],
                "platform": {
                    "publish": {
                        "url": "https://www.xiaohongshu.com/explore/sync123"
                    }
                },
                "created_at": "2026-06-29T00:00:00.000000Z",
                "updated_at": "2026-06-29T00:00:00.000000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = sync_published_metrics_to_posts(
        [
            {
                "title": "Actual platform title after edit",
                "url": "https://www.xiaohongshu.com/explore/sync123",
                "published_at": "2026-06-29",
                "likes": 7,
                "comments": 2,
                "favorites": 3,
                "raw": {"views": 99, "shares": 1},
            }
        ],
        base=tmp_path,
    )

    assert result["matched"] == 1
    stored = json.loads((post_dir / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "published"
    assert stored["platform"]["publish"]["actual_title"] == "Actual platform title after edit"
    assert stored["platform"]["publish"]["url"] == "https://www.xiaohongshu.com/explore/sync123"
    assert stored["platform"]["publish"]["metrics"]["likes"] == 7
    assert stored["platform"]["publish"]["metrics"]["views"] == 99


def test_sync_published_metrics_to_posts_can_match_exact_title_without_url(tmp_path: Path):
    post_id = "dddddddddddddddddddddddddddddddd"
    post_dir = tmp_path / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "saved_as_draft",
                "uploaded": True,
                "title": "Exact title match",
                "body": "Local draft body",
                "topics": [],
                "assets": [],
                "platform": {},
                "created_at": "2026-06-29T00:00:00.000000Z",
                "updated_at": "2026-06-29T00:00:00.000000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = sync_published_metrics_to_posts(
        [{"title": "Exact title match", "published_at": "2026-06-29"}],
        base=tmp_path,
    )

    assert result["matched"] == 1
    stored = json.loads((post_dir / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "published"
    assert stored["platform"]["publish"]["match_reason"] == "title"


def test_sync_published_metrics_to_posts_matches_actual_platform_title(tmp_path: Path):
    post_id = "ffffffffffffffffffffffffffffffff"
    post_dir = tmp_path / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "published",
                "uploaded": True,
                "title": "Old local title",
                "body": "Local draft body",
                "topics": [],
                "assets": [],
                "platform": {
                    "publish": {
                        "actual_title": "Edited title on platform"
                    }
                },
                "created_at": "2026-06-29T00:00:00.000000Z",
                "updated_at": "2026-06-29T00:00:00.000000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = sync_published_metrics_to_posts(
        [{"title": "Edited title on platform", "published_at": "2026-06-29"}],
        base=tmp_path,
    )

    assert result["matched"] == 1
    stored = json.loads((post_dir / "post.json").read_text(encoding="utf-8"))
    assert stored["platform"]["publish"]["match_reason"] == "actual_title"


def test_update_metrics_cli_syncs_matching_local_posts(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    post_id = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    post_dir = tmp_path / "data" / "posts" / post_id
    post_dir.mkdir(parents=True)
    (post_dir / "post.json").write_text(
        json.dumps(
            {
                "id": post_id,
                "type": "image",
                "status": "saved_as_draft",
                "uploaded": True,
                "title": "Published from platform",
                "body": "Local body",
                "topics": [],
                "assets": [],
                "platform": {},
                "created_at": "2026-06-29T00:00:00.000000Z",
                "updated_at": "2026-06-29T00:00:00.000000Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "run_collect_published_metrics_sync",
        lambda **_kwargs: {
            "items": [
                {
                    "title": "Published from platform",
                    "published_at": "2026-06-29",
                    "likes": 1,
                    "comments": 0,
                    "favorites": 2,
                    "raw": {},
                }
            ],
            "errors": [],
        },
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["update-metrics", "--login-hold", "0"])

    assert result.exit_code == 0
    assert "posts-synced: matched=1" in result.output
    stored = json.loads((post_dir / "post.json").read_text(encoding="utf-8"))
    assert stored["status"] == "published"


def test_update_metrics_requires_complete_collection_before_saving(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_collect_published_metrics_sync",
        lambda **_kwargs: {
            "items": [
                {
                    "title": "Only one visible post",
                    "published_at": "2026-07-02",
                    "likes": 1,
                    "comments": 0,
                    "favorites": 0,
                    "raw": {},
                }
            ],
            "target_total": 2,
            "complete": False,
            "missing_count": 1,
            "errors": [],
        },
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["update-metrics", "--login-hold", "0"])

    assert result.exit_code == 1
    assert "incomplete published metrics" in result.output
    assert "fetched=1 target=2 missing=1" in result.output
    assert not (tmp_path / "data" / "analytics" / "published_metrics_latest.csv").exists()


def test_update_metrics_refuses_empty_collection_before_saving(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_collect_published_metrics_sync",
        lambda **_kwargs: {
            "items": [],
            "target_total": 2,
            "required_total": 2,
            "complete": False,
            "missing_count": 2,
            "errors": ["no published metrics found"],
        },
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["update-metrics", "--login-hold", "0"])

    assert result.exit_code == 1
    assert "no published metrics collected" in result.output
    assert not (tmp_path / "data" / "analytics" / "published_metrics_latest.csv").exists()


def test_update_metrics_allow_partial_saves_incomplete_collection(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "run_collect_published_metrics_sync",
        lambda **_kwargs: {
            "items": [
                {
                    "title": "Only one visible post",
                    "published_at": "2026-07-02",
                    "likes": 1,
                    "comments": 0,
                    "favorites": 0,
                    "raw": {},
                }
            ],
            "target_total": 2,
            "complete": False,
            "missing_count": 1,
            "errors": [],
        },
        raising=False,
    )

    result = CliRunner().invoke(cli.app, ["update-metrics", "--login-hold", "0", "--allow-partial"])

    assert result.exit_code == 0
    assert "warning: saving partial published metrics" in result.output
    assert (tmp_path / "data" / "analytics" / "published_metrics_latest.csv").exists()
