from pathlib import Path

from typer.testing import CliRunner

import apps.cli as cli
from src.storage.models import AssetInfo, Execution, Post


def _digest_post(asset: Path) -> Post:
    return Post(
        title="每日AI讯息",
        body="今日AI简报：10条官方动态已汇总，适合快速浏览。",
        topics=["每日AI讯息", "AI动态"],
        assets=[AssetInfo(path=str(asset), kind="image")],
        platform={"ai_digest": {"mode": "daily_ai_digest", "target_items": 10}},
    )


def test_create_command_is_not_public(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "digest.png"
    asset.write_bytes(b"fake image")
    calls: list[dict] = []

    def fake_create_daily_ai_digest_posts(**kwargs):
        calls.append(kwargs)
        return [_digest_post(asset)]

    def fail_regular_create(**_kwargs):
        raise AssertionError("每日AI讯息 should not use the generic create flow")

    monkeypatch.setattr(cli, "create_daily_ai_digest_posts", fake_create_daily_ai_digest_posts, raising=False)
    monkeypatch.setattr(cli, "create_post_with_draft", fail_regular_create)

    result = CliRunner().invoke(
        cli.app,
        [
            "create",
            "--title",
            "每日AI讯息",
            "--count",
            "5",
            "--assets-glob",
            str(asset),
        ],
    )

    assert result.exit_code != 0
    assert not calls


def test_auto_daily_ai_digest_title_uploads_one_digest_post(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "digest.png"
    asset.write_bytes(b"fake image")
    post = _digest_post(asset)
    calls: list[dict] = []
    uploaded: list[str] = []

    def fake_create_daily_ai_digest_posts(**kwargs):
        calls.append(kwargs)
        return [post]

    def fail_regular_create(**_kwargs):
        raise AssertionError("每日AI讯息 should not use the generic create flow")

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        uploaded.append(post_arg.id)
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_ai_digest_posts", fake_create_daily_ai_digest_posts, raising=False)
    monkeypatch.setattr(cli, "create_post_with_draft", fail_regular_create)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日AI讯息",
            "--count",
            "5",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["count"] == 1
    assert uploaded == [post.id]
    assert "uploaded=1" in result.output
    assert "requested=1" in result.output
    assert "自动选择 8-20 条" in result.output
    assert "AI_DIGEST_MAX_ITEMS" in result.output


def test_auto_daily_ai_digest_missing_assets_explains_local_card_rendering(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "digest.png"
    asset.write_bytes(b"fake image")
    post = _digest_post(asset)

    def fake_create_daily_ai_digest_posts(**_kwargs):
        return [post]

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_ai_digest_posts", fake_create_daily_ai_digest_posts, raising=False)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日AI讯息",
            "--assets-glob",
            str(tmp_path / "missing" / "*"),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert "未找到素材文件" not in result.output
    assert "自动查找配图" not in result.output
    assert "本地简报图" in result.output


def test_auto_daily_wool_title_dispatches_to_daily_wool_workflow(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "wool.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="每日羊毛|今日暂无可核验福利",
        body="截至今日，暂未发现可核验的AI福利。",
        topics=["每日羊毛", "AI福利"],
        assets=[AssetInfo(path=str(asset), kind="image")],
        platform={"daily_wool": {"mode": "daily_wool", "has_wool": False}},
    )
    calls: list[dict] = []
    uploaded: list[str] = []

    def fake_create_daily_wool_posts(**kwargs):
        calls.append(kwargs)
        return [post]

    def fake_run_save_draft_sync(post_arg, **_kwargs):
        uploaded.append(post_arg.id)
        return Execution(post_id=post_arg.id, result="saved_draft")

    monkeypatch.setattr(cli, "create_daily_wool_posts", fake_create_daily_wool_posts)
    monkeypatch.setattr(cli, "run_save_draft_sync", fake_run_save_draft_sync)

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日羊毛",
            "--count",
            "4",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["count"] == 1
    assert uploaded == [post.id]
    assert "每日羊毛会生成 1 条" in result.output
