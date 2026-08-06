from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from apps import cli
from apps.cli import _review_with_bounded_image_repair
from src.config import LLMConfig
from src.storage.models import AssetInfo, Post
from src.workflow.vision_review import (
    VisionReviewResult,
    load_vision_review_config,
    parse_vision_review,
    review_post_image,
)


def _post_with_image(tmp_path: Path) -> Post:
    path = tmp_path / "scene.png"
    image = Image.new("RGB", (320, 420), (20, 80, 140))
    image.save(path)
    return Post(
        title="芯片企业发布新方案",
        body="内容：企业发布新一代芯片制造方案。\n\n评价：需要关注量产进展。",
        assets=[AssetInfo(path=str(path), kind="image")],
        platform={
            "news": {"image_event": "芯片企业在发布会展示新一代产品"},
            "image": {
                "prompt": "生成发布会现场，画面中不要出现任何文字、标志或水印。"
            },
        },
    )


def test_load_vision_review_config_accepts_provider_specific_model_alias(monkeypatch):
    monkeypatch.delenv("VLM_REVIEW_MODEL", raising=False)
    monkeypatch.setenv("VLM_REVIEW_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_VLM_MODEL", "doubao-seed-1-6-251015")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")

    config = load_vision_review_config()

    assert config.provider == "volcengine"
    assert config.model == "doubao-seed-1-6-251015"


def test_ai_digest_quality_gate_never_replaces_rendered_cards(tmp_path, monkeypatch):
    post = _post_with_image(tmp_path)
    Image.effect_noise((320, 420), 90).convert("RGB").save(post.assets[0].path)
    post.platform.pop("news", None)
    post.platform["ai_digest"] = {"mode": "daily_ai_digest"}
    repairs: list[str] = []
    review_calls: list[str] = []
    monkeypatch.setenv("VLM_REVIEW_PROVIDER", "volcengine")
    monkeypatch.setenv("VLM_REVIEW_MODEL", "doubao-seed-1-6-251015")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "test-key")
    monkeypatch.setenv("AUTO_VLM_REPAIR_ATTEMPTS", "1")
    monkeypatch.setattr(cli, "list_posts", lambda: [])
    monkeypatch.setattr(cli, "save_post", lambda _post: None)
    def fake_review(*_args, **_kwargs):
        review_calls.append("review")
        return VisionReviewResult(
            ok=False,
            score=40,
            issues=("简报卡片需要人工检查",),
            retry_prompt="不要改写简报卡片",
            provider="volcengine",
            model="doubao-seed-1-6-251015",
        )

    monkeypatch.setattr(cli, "review_post_image", fake_review)
    monkeypatch.setattr(
        cli,
        "regenerate_daily_news_post_image",
        lambda *_args, **_kwargs: repairs.append("called") or True,
    )

    errors = cli._run_auto_quality_gate(
        [post],
        expected_count=1,
        evaluation_viewpoint="无视角评价",
        require_vision=True,
    )

    assert errors
    assert review_calls == ["review"]
    assert repairs == []


def test_parse_vision_review_requires_strict_fields():
    result = parse_vision_review(
        json.dumps(
            {
                "ok": False,
                "score": 42,
                "issues": ["图片主体是汽车，与芯片发布无关"],
                "retry_prompt": "芯片发布会现场，展示晶圆和处理器",
            },
            ensure_ascii=False,
        )
    )

    assert result == VisionReviewResult(
        ok=False,
        score=42,
        issues=("图片主体是汽车，与芯片发布无关",),
        retry_prompt="芯片发布会现场，展示晶圆和处理器",
        provider="",
        model="",
    )


def test_parse_vision_review_accepts_conservative_ocr_vlm_shape():
    result = parse_vision_review(
        {
            "ok": True,
            "issues": [{"text": "N", "rotate_rect": [1, 2, 3, 4]}],
            "retry_prompt": "",
        }
    )

    assert result.ok is True
    assert result.score == 70
    assert result.issues == ("N",)


def test_review_post_image_sends_title_body_viewpoint_and_image(tmp_path):
    post = _post_with_image(tmp_path)
    captured = {}

    def fake_invoke(config, *, prompt, image_path):
        captured["config"] = config
        captured["prompt"] = prompt
        captured["image_path"] = image_path
        return {
            "ok": True,
            "score": 91,
            "issues": [],
            "retry_prompt": "",
        }

    config = LLMConfig(
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        provider="volcengine",
    )
    result = review_post_image(
        post,
        config=config,
        viewpoint="关注量产和产业影响",
        invoke=fake_invoke,
    )

    assert result.ok
    assert captured["config"] == config
    assert "芯片企业发布新方案" in captured["prompt"]
    assert "企业发布新一代芯片制造方案" in captured["prompt"]
    assert "关注量产和产业影响" in captured["prompt"]
    assert "生成发布会现场" in captured["prompt"]
    assert "不得因缺少品牌文字或 Logo 判定不通过" in captured["prompt"]
    assert captured["image_path"].name == "scene.png"
    assert result.provider == "volcengine"
    assert result.model == "doubao-seed-1-6-vision"


def test_review_post_image_rejects_inconsistent_result(tmp_path):
    post = _post_with_image(tmp_path)
    config = LLMConfig(
        model="vision-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        provider="aliyun",
    )

    result = review_post_image(
        post,
        config=config,
        invoke=lambda *_args, **_kwargs: {
            "ok": False,
            "score": 20,
            "issues": ["图中没有新闻主体"],
            "retry_prompt": "发布会上的芯片产品",
        },
    )

    assert not result.ok
    assert result.issues == ("图中没有新闻主体",)
    assert result.retry_prompt == "发布会上的芯片产品"


def test_bounded_image_repair_rechecks_daily_news_once():
    post = Post(
        title="测试新闻",
        body="测试正文",
        platform={"news": {"source_url": "https://example.com/news"}},
    )
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    results = iter(
        [
            VisionReviewResult(
                ok=False,
                score=48,
                issues=("图片主体不符",),
                retry_prompt="突出芯片产业新闻事件",
                provider="volcengine",
                model=config.model,
            ),
            VisionReviewResult(
                ok=True,
                score=91,
                issues=(),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
        ]
    )
    repairs: list[str] = []

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="无视角评价",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: next(results),
        regenerate_fn=lambda _post, retry_prompt: repairs.append(retry_prompt) or True,
    )

    assert result.ok
    assert repair_count == 1
    assert repair_errors == []
    assert repairs == ["突出芯片产业新闻事件"]
    assert [item.score for item in history] == [48, 91]


def test_bounded_image_repair_falls_back_after_ai_retry_semantic_failure():
    post = Post(
        title="Memory optimization news",
        body="The company will optimize operating-system memory use.",
        platform={"news": {"source_url": "https://example.com/news"}},
    )
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    results = iter(
        [
            VisionReviewResult(
                ok=False,
                score=24,
                issues=("The image is unrelated to computer memory optimization.",),
                retry_prompt="Show a generic laptop RAM upgrade scene with no text.",
                provider="volcengine",
                model=config.model,
            ),
            VisionReviewResult(
                ok=False,
                score=18,
                issues=("The regenerated image is still unrelated.",),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
            VisionReviewResult(
                ok=True,
                score=94,
                issues=(),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
        ]
    )
    ai_repairs: list[str] = []
    pexels_fallbacks: list[str] = []

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="neutral evaluation",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: next(results),
        regenerate_fn=lambda _post, prompt: ai_repairs.append(prompt) or True,
        fallback_regenerate_fn=lambda _post, prompt: pexels_fallbacks.append(prompt) or True,
    )

    assert result.score == 94
    assert repair_count == 1
    assert repair_errors == []
    assert ai_repairs == ["Show a generic laptop RAM upgrade scene with no text."]
    assert pexels_fallbacks == ["Show a generic laptop RAM upgrade scene with no text."]
    assert [item.score for item in history] == [24, 18, 94]


def test_bounded_image_repair_retries_inconsistent_zero_score_even_if_ok_flag_is_true():
    post = Post(
        title="测试新闻",
        body="测试正文",
        platform={"news": {"source_url": "https://example.com/news"}},
    )
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    results = iter(
        [
            VisionReviewResult(
                ok=True,
                score=0,
                issues=("图片与新闻事件不一致",),
                retry_prompt="改为与新闻主体相关的无文字场景",
                provider="volcengine",
                model=config.model,
            ),
            VisionReviewResult(
                ok=True,
                score=90,
                issues=(),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
        ]
    )
    repairs: list[str] = []

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="无视角评价",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: next(results),
        regenerate_fn=lambda _post, retry_prompt: repairs.append(retry_prompt) or True,
    )

    assert result.score == 90
    assert repair_count == 1
    assert repair_errors == []
    assert repairs == ["改为与新闻主体相关的无文字场景"]
    assert [item.score for item in history] == [0, 90]


def test_bounded_image_repair_does_not_redraw_non_news_cards():
    post = Post(title="每日AI讯息", body="测试正文", platform={})
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    result = VisionReviewResult(
        ok=False,
        score=55,
        issues=("文字太小",),
        retry_prompt="增大文字",
        provider="volcengine",
        model=config.model,
    )
    regenerate_calls: list[str] = []

    final, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="无视角评价",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: result,
        regenerate_fn=lambda *_args, **_kwargs: regenerate_calls.append("called") or True,
    )

    assert final is result
    assert repair_count == 0
    assert repair_errors == []
    assert regenerate_calls == []
    assert len(history) == 1


def test_bounded_image_repair_rechecks_inconclusive_non_news_review_without_redrawing():
    post = Post(title="每日AI讯息", body="测试正文", platform={})
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    results = iter(
        [
            VisionReviewResult(
                ok=True,
                score=0,
                issues=(),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
            VisionReviewResult(
                ok=True,
                score=96,
                issues=(),
                retry_prompt="",
                provider="volcengine",
                model=config.model,
            ),
        ]
    )
    regenerated: list[str] = []

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="无视角评价",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: next(results),
        regenerate_fn=lambda *_args, **_kwargs: regenerated.append("called") or True,
    )

    assert result.score == 96
    assert repair_count == 0
    assert repair_errors == []
    assert regenerated == []
    assert [item.score for item in history] == [0, 96]
