import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner
from typer.main import get_command

import apps.cli as cli
from src.storage.models import AssetInfo, Execution, Post
from src.workflow.create_post import PartialDailyNewsError


def test_auto_help_uses_keywords_and_keeps_prompt_alias():
    result = CliRunner().invoke(cli.app, ["auto", "--help"])

    assert result.exit_code == 0, result.output
    assert "--keywords" in result.output
    auto_command = get_command(cli.app).commands["auto"]
    prompt_option = next(param for param in auto_command.params if param.name == "prompt")
    assert "--prompt" in prompt_option.opts
    assert "--allow-partial" in result.output
    assert "新闻检索关键词" in result.output


def test_daily_news_progress_reason_uses_plain_chinese_for_known_quality_codes():
    assert cli._humanize_daily_news_progress_reason("bad_body_language") == "正文未达到简体中文表达要求"
    assert cli._humanize_daily_news_progress_reason("source_context_insufficient") == "原文信息不足，无法可靠生成"
    assert cli._humanize_daily_news_progress_reason("provider-specific-detail") == "provider-specific-detail"


def test_daily_news_progress_omits_blank_candidate_total(monkeypatch):
    emitted: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        cli,
        "_emit_progress_event",
        lambda command, stage, status, message: emitted.append((command, stage, status, message)),
    )

    cli._daily_news_generation_progress(
        "原文核验",
        "skipped",
        {
            "candidate_index": 4,
            "completed": 3,
            "target": 10,
            "reason": "duplicate_story_after_enrichment",
        },
    )

    assert emitted[-1][-1] == "原文核验：候选 4，已完成 3/10 条，原因：与已选新闻重复"


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
            "--no-preflight",
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


def test_auto_daily_ai_digest_initializes_daily_news_quality_reuse_flag(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "digest.png"
    asset.write_bytes(b"fake digest image")
    post = Post(
        title="每日AI|测试简报",
        body="每日AI讯息\n\n发布时间：2026-08-06\n来源链接：https://example.com/ai",
        assets=[AssetInfo(path=str(asset), kind="image")],
        platform={"ai_digest": {"mode": "daily_ai_digest"}},
    )
    quality_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "_prepare_auto_pipeline",
        lambda **_kwargs: SimpleNamespace(model_plan=None, warnings=()),
    )
    monkeypatch.setattr(cli, "create_daily_ai_digest_posts", lambda **_kwargs: [post])

    def fake_quality_gate(_posts, **kwargs):
        quality_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(cli, "_run_auto_quality_gate", fake_quality_gate)
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
            "每日AI讯息",
            "--assets-glob",
            "assets/empty/*",
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert quality_kwargs["reuse_vision_results"] is False


def test_auto_records_xhs_draft_metadata_after_successful_upload(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="草稿元数据测试",
        body="这是用于验证自动上传草稿元数据的测试正文。",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    saved_posts: list[Post] = []

    monkeypatch.setattr(cli, "create_daily_news_posts", lambda **_kwargs: [post])
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: Execution(
            post_id=post_arg.id,
            result="saved_draft",
            id="execution-test-id",
        ),
    )
    monkeypatch.setattr(cli, "save_post", lambda value: saved_posts.append(deepcopy(value)))

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日新闻",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    final_post = saved_posts[-1]
    assert final_post.platform["xhs_draft"]["title"] == post.title
    assert final_post.platform["xhs_draft"]["execution_id"] == "execution-test-id"
    assert final_post.platform["xhs_draft"]["saved_at"]


def test_auto_platform_both_saves_each_generated_post_to_xhs_and_toutiao(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="多平台草稿测试",
        body="内容：这是用于验证多平台草稿保存的正文。\n\n评价：需要继续观察。\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    calls: list[str] = []

    monkeypatch.setattr(cli, "create_daily_news_posts", lambda **_kwargs: [post])
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: calls.append("xhs")
        or Execution(post_id=post_arg.id, result="saved_draft", id="xhs-exec"),
    )
    monkeypatch.setattr(
        cli,
        "run_save_toutiao_draft_sync",
        lambda post_arg, **_kwargs: calls.append("toutiao")
        or Execution(post_id=post_arg.id, result="saved_draft", id="toutiao-exec"),
        raising=False,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--platform",
            "both",
            "--title",
            "每日新闻",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["xhs", "toutiao"]
    assert post.platform["xhs_draft"]["execution_id"] == "xhs-exec"
    assert post.platform["toutiao_draft"]["execution_id"] == "toutiao-exec"



def test_auto_refuses_partial_daily_news_batch_before_upload_by_default(monkeypatch, tmp_path):
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
            "--no-preflight",
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

    assert result.exit_code == 1
    assert uploaded == []
    assert "batch incomplete" in result.output
    assert "uploaded=0" in result.output
    assert "requested=3" in result.output


def test_auto_can_explicitly_upload_partial_daily_news_batch(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="Partial draft",
        body="Content: verified test news.\n\nComment: test.\n\nDate: 2026-07-28\n\nSource: Test",
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
    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: uploaded.append(post_arg.id) or Execution(post_id=post_arg.id, result="saved_draft"),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日新闻",
            "--count",
            "3",
            "--allow-partial",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert uploaded == [post.id]
    assert "partial daily news" in result.output


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
            "--no-preflight",
            "--title",
            "每日新闻",
            "--count",
            "2",
            "--allow-partial",
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
            "--no-preflight",
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
            "--no-preflight",
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
            "--no-preflight",
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


def test_auto_returns_failure_when_generated_draft_was_not_saved(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    post = Post(
        title="测试新闻",
        body="内容：测试正文。\n\n评价：测试评价。\n\n日期：2026-07-29\n\n来源：测试源",
        assets=[AssetInfo(path=str(asset), kind="image")],
    )
    monkeypatch.setattr(
        cli,
        "create_daily_news_posts",
        lambda **_kwargs: [post],
    )
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: Execution(
            post_id=post_arg.id,
            result="failed",
            error={"message": "xiaohongshu login required"},
        ),
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "auto",
            "--no-preflight",
            "--title",
            "每日新闻",
            "--assets-glob",
            str(asset),
            "--login-hold",
            "0",
            "--wait-timeout",
            "30",
        ],
    )

    assert result.exit_code == 1
    assert "uploaded=0" in result.output
    assert "[auto] stage=完成 | failed" in result.output


def test_auto_continues_candidate_pool_after_visual_quality_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    asset = tmp_path / "asset.png"
    asset.write_bytes(b"fake image")
    body = "内容：经过来源核验的测试新闻。\n\n评价：测试评价。\n\n日期：2026-07-29\n\n来源：测试源"
    posts = [
        Post(title=f"测试新闻{i}", body=body, assets=[AssetInfo(path=str(asset), kind="image")])
        for i in range(1, 4)
    ]
    observed: dict[str, object] = {}
    uploaded: list[str] = []

    monkeypatch.setattr(
        cli,
        "_prepare_auto_pipeline",
        lambda **_kwargs: SimpleNamespace(model_plan=None),
    )

    def fake_create_daily_news_posts(**kwargs):
        observed.update(kwargs)
        quality_callback = kwargs["post_quality_callback"]
        accepted = []
        for post in posts:
            if not quality_callback(post):
                accepted.append(post)
            if len(accepted) >= kwargs["count"]:
                break
        return accepted

    quality_calls: list[tuple[list[str], bool]] = []

    def fake_quality_gate(candidates, **kwargs):
        quality_calls.append(
            ([post.id for post in candidates], bool(kwargs.get("reuse_vision_results")))
        )
        for post in candidates:
            is_bad = post is posts[0]
            post.platform["quality_gate"] = {
                "deterministic_ok": True,
                "issues": [],
                "vision": {
                    "ok": not is_bad,
                    "score": 100 if not is_bad else 0,
                    "issues": [] if not is_bad else ["图片与文字不一致"],
                },
            }
        if len(candidates) == 1 and candidates[0] is posts[0]:
            return ["第 1 条图片与文字不一致（得分 0）"]
        return []

    monkeypatch.setattr(cli, "create_daily_news_posts", fake_create_daily_news_posts)
    monkeypatch.setattr(cli, "_run_auto_quality_gate", fake_quality_gate)
    monkeypatch.setattr(
        cli,
        "run_save_draft_sync",
        lambda post_arg, **_kwargs: uploaded.append(post_arg.id)
        or Execution(post_id=post_arg.id, result="saved_draft"),
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
    assert observed["count"] == 2
    assert callable(observed["post_quality_callback"])
    assert uploaded == [posts[1].id, posts[2].id]
    assert quality_calls[:3] == [
        ([posts[0].id], False),
        ([posts[1].id], False),
        ([posts[2].id], False),
    ]
    assert quality_calls[-1] == ([posts[1].id, posts[2].id], True)
    assert "视觉递补" in result.output
