from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli
from src.storage.models import AssetInfo, Execution, Post
from src.workflow.create_post import PartialDailyNewsError


def test_auto_uploads_partial_daily_news_posts_before_reporting_failures(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="科技新闻新进展",
        body="原文标题：测试新闻\n\n内容：这是一条用于测试的新闻正文。\n\n日期：2026-06-27\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )

    def fake_create_daily_news_posts(**_kwargs):
        raise PartialDailyNewsError(
            "quota exhausted after partial generation",
            posts=[post],
            requested_count=3,
            failed_count=2,
        )

    uploaded: list[str] = []

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        uploaded.append(post_arg.id)
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--count",
            "3",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert uploaded == [post.id]
    assert "partial daily news" in result.output
    assert "uploaded=1" in result.output
    assert "failed=2" in result.output
