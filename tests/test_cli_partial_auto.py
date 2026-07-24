import os
from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli
from src.storage.models import AssetInfo, Execution, Post
from src.workflow.create_post import PartialDailyNewsError


def test_auto_help_uses_keywords_and_keeps_prompt_alias():
    result = CliRunner().invoke(cli.app, ["auto", "--help"])

    assert result.exit_code == 0, result.output
    assert "--keywords" in result.output
    assert "--prompt" in result.output
    assert "新闻检索关键词" in result.output


def test_auto_passes_keywords_to_daily_news_generation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="财经政策出现新变化",
        body="内容：这是经过来源核验的测试新闻。\n\n评价：\n\n日期：2026-07-19\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    seen: dict[str, object] = {}

    def fake_create_daily_news_posts(**kwargs):
        seen.update(kwargs)
        return [post]

    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: Execution(post_id=post_arg.id, result="saved_draft"),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--keywords",
            "财经产业 公司政策",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["prompt_hint"] == "财经产业 公司政策"


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


def test_auto_allows_a_valid_replacement_after_an_invalid_duplicate(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    body = "内容：这是一条经过来源核验的测试新闻。\n\n评价：\n\n日期：2026-07-24\n\n来源：测试源"
    invalid = Post(
        title="财经政策出现新变化",
        body=body,
        assets=[AssetInfo(path=str(tmp_path / "missing.png"), kind="image")],
    )
    valid = Post(
        title="财经政策出现新变化",
        body=body,
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    uploaded: list[str] = []

    monkeypatch.setattr(cli, "create_daily_news_posts", lambda **_kwargs: [invalid, valid])
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: uploaded.append(post_arg.id) or Execution(post_id=post_arg.id, result="saved_draft"),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--count",
            "2",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert uploaded == [valid.id]
    assert "skip invalid" in result.output
    assert "skip duplicate" not in result.output


def test_auto_daily_news_passes_news_materials_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    materials_file = tmp_path / "manual_news.md"
    materials_file.write_text("标题：测试新闻\n时间：2026-07-05\n来源：测试源\n内容：测试内容", encoding="utf-8")
    post = Post(
        title="测试新闻新进展",
        body="内容：测试内容\n\n评价：\n\n日期：2026-07-05\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    seen: dict[str, object] = {}

    def fake_create_daily_news_posts(**kwargs):
        seen.update(kwargs)
        return [post]

    def fake_run_save_draft_sync(post_arg, **_kwargs):
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
            "1",
            "--assets-glob",
            str(asset),
            "--news-materials-file",
            str(materials_file),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert seen["news_materials_file"] == str(materials_file)


def test_auto_daily_news_passes_single_news_material_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    single_file = tmp_path / "single_news.md"
    single_file.write_text(
        "title: One selected story\nsource: Example\ncontent: Full story text",
        encoding="utf-8",
    )
    post = Post(
        title="One selected story",
        body="内容：Full story text\n\n评价：\n\n日期：2026-07-05\n\n来源：Example",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    seen: dict[str, object] = {}

    def fake_create_daily_news_posts(**kwargs):
        seen.update(kwargs)
        return [post]

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--prompt",
            "this should be ignored",
            "--lookback-days",
            "3",
            "--count",
            "9",
            "--assets-glob",
            str(asset),
            "--single-news-material-file",
            str(single_file),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert seen["single_news_material_file"] == str(single_file)
    assert seen["news_materials_file"] in ("", None)
    assert seen["count"] == 1
    assert seen["prompt_hint"] == ""
    assert seen["lookback_days"] is None


def test_auto_news_material_options_do_not_leak_process_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEWS_MATERIALS_FILE", raising=False)
    monkeypatch.delenv("SINGLE_NEWS_MATERIAL_FILE", raising=False)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    materials_file = tmp_path / "manual_news.md"
    materials_file.write_text("标题：测试新闻\n时间：2026-07-05\n来源：测试源\n内容：测试内容", encoding="utf-8")
    post = Post(
        title="测试新闻新进展",
        body="内容：测试内容\n\n评价：\n\n日期：2026-07-05\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )

    def fake_create_daily_news_posts(**_kwargs):
        return [post]

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--title",
            "每日新闻",
            "--assets-glob",
            str(asset),
            "--news-materials-file",
            str(materials_file),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert "NEWS_MATERIALS_FILE" not in os.environ
    assert "SINGLE_NEWS_MATERIAL_FILE" not in os.environ
