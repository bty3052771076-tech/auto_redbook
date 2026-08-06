from pathlib import Path

import pytest

from apps import cli
from src.storage.models import AssetInfo, Post
from src.workflow import create_post


def test_empty_assets_glob_is_an_auto_image_sentinel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    empty_dir = tmp_path / "assets" / "empty"
    empty_dir.mkdir(parents=True)
    (empty_dir / "stale.png").write_bytes(b"stale")

    assert cli._initial_asset_paths("assets/empty/*") == []
    assert cli._is_auto_image_sentinel_glob("assets\\empty\\*")


def test_default_upload_assets_use_frozen_post_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assets_dir = tmp_path / "data" / "posts" / "post-1" / "assets"
    assets_dir.mkdir(parents=True)
    final_image = assets_dir / "final.jpg"
    stale_attempt = assets_dir / "stale-attempt.jpg"
    final_image.write_bytes(b"final")
    stale_attempt.write_bytes(b"stale")
    post = Post(
        id="post-1",
        assets=[AssetInfo(path=str(final_image), validated=True)],
    )

    assert cli._resolve_asset_paths(post, "") == [str(final_image)]


def test_explicit_upload_glob_overrides_frozen_post_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()
    explicit_image = explicit_dir / "manual.jpg"
    explicit_image.write_bytes(b"manual")
    frozen_image = tmp_path / "final.jpg"
    frozen_image.write_bytes(b"final")
    post = Post(assets=[AssetInfo(path=str(frozen_image), validated=True)])

    resolved = cli._resolve_asset_paths(post, "explicit/*")

    assert [Path(path).resolve() for path in resolved] == [explicit_image.resolve()]


def test_cli_text_repair_restores_corrupted_daily_news_title(capsys):
    original = "\u6bcf\u65e5\u65b0\u95fb"
    corrupted = original.encode("utf-8").decode("gb18030")

    assert cli._repair_cli_text(corrupted, field="title") == original
    assert "repaired UTF-8/GBK mojibake" in capsys.readouterr().out


def test_upload_fingerprint_treats_whitespace_and_punctuation_variants_as_duplicate():
    first = Post(title="\u6bcf\u65e5\u65b0\u95fb", body="\u8d22\u7ecf\u4ea7\u4e1a\u901f\u89c8\uff0c\u5e02\u573a\u53d8\u5316\u3002")
    second = Post(title="\u6bcf\u65e5\u65b0\u95fb!", body="\u8d22\u7ecf\u4ea7\u4e1a\u901f\u89c8 \u5e02\u573a\u53d8\u5316")

    assert cli._post_upload_fingerprint(first) == cli._post_upload_fingerprint(second)


def test_generic_llm_fallback_is_not_saved_as_a_draft(monkeypatch):
    monkeypatch.setattr(create_post, "load_llm_configs", lambda: [])
    monkeypatch.setattr(
        create_post,
        "generate_draft",
        lambda *_args, **_kwargs: {
            "title": "\u6d4b\u8bd5",
            "body": "\uff08\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\uff09",
            "topics": [],
            "_fallback_error": "429 RATE_LIMIT_EXCEEDED",
        },
    )

    with pytest.raises(RuntimeError, match="fallback placeholder will not be saved or uploaded"):
        create_post.create_post_with_draft(
            title_hint="\u666e\u901a\u65b0\u95fb",
            prompt_hint="\u6d4b\u8bd5",
            asset_paths=[],
            auto_image=False,
        )


def test_llm_model_not_found_error_is_actionable():
    error = (
        "404 InvalidEndpointOrModel.NotFound: "
        "The model or endpoint glm-5.2 does not exist or you do not have access to it"
    )

    reason = create_post._daily_news_llm_unavailable_reason(error)

    assert "模型标识" in reason
    assert "权限" in reason


def test_daily_news_image_repair_hint_allows_text_free_software_visuals():
    hint = create_post._daily_news_image_repair_hint("Show a software performance optimization event")

    assert "text-free abstract performance interface is allowed" in hint


def test_daily_news_image_repair_hint_forbids_text_bearing_artifacts():
    hint = create_post._daily_news_image_repair_hint(
        "请修正图片中的品牌名称为 X Money"
    )

    assert "VLM 反馈" in hint
    assert "品牌名" in hint
    assert "Logo" in hint
    assert "屏幕" in hint
    assert "字母" in hint
    assert "数字" in hint
    assert "只用人物、环境、实体物体和动作" in hint


def test_run_record_captures_selected_volcengine_models(monkeypatch):
    captured = {}
    monkeypatch.setenv("LLM_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_LLM_MODEL", "glm-5.2")
    monkeypatch.setenv("IMAGE_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_IMAGE_MODEL", "doubao-seedream-4-5-251128")
    monkeypatch.setenv("VLM_REVIEW_PROVIDER", "volcengine")
    monkeypatch.setenv("VLM_REVIEW_MODEL", "doubao-seed-1-6-251015")

    def fake_append_run_record(record):
        captured["record"] = record
        return {"csv": "unused"}

    monkeypatch.setattr(cli, "append_run_record", fake_append_run_record)

    cli._record_generation_run(
        command="auto",
        title="每日新闻",
        prompt="测试",
        requested_count=1,
        generated_count=1,
        uploaded_count=1,
        failed_count=0,
        started_at="2026-07-29T00:00:00Z",
        post_ids=["post-1"],
        errors=[],
    )

    record = captured["record"]
    assert record.llm_provider == "volcengine"
    assert record.llm_models == "glm-5.2"
    assert record.image_provider == "volcengine"
    assert record.image_models == "doubao-seedream-4-5-251128"
    assert record.extra["vlm_provider"] == "volcengine"
    assert record.extra["vlm_model"] == "doubao-seed-1-6-251015"
