from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from apps import cli
from apps.cli import (
    _apply_visual_spare_selection,
    _daily_news_visual_spare_count,
    _replenish_visual_news_until_target,
    _review_with_bounded_image_repair,
)
from src.config import LLMConfig
from src.images.auto_image import _build_aliyun_image_prompt
from src.storage.models import AssetInfo, Post
from src.workflow.create_post import _daily_news_image_repair_hint
from src.workflow.create_post import _daily_news_story_identity
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


def test_load_vision_review_config_accepts_minimax_subscription_multimodal_model(monkeypatch):
    monkeypatch.delenv("VLM_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("MINIMAX_LLM_MODEL", raising=False)
    monkeypatch.setenv("VLM_REVIEW_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "test-token-plan-key")
    monkeypatch.setenv("MINIMAX_BILLING_MODE", "subscription_only")
    monkeypatch.setenv("MINIMAX_ALLOW_PAID_CREDITS", "0")
    monkeypatch.setenv("MINIMAX_ALLOW_PAYGO", "0")

    config = load_vision_review_config()

    assert config.provider == "minimax"
    assert config.model == "MiniMax-M3"
    assert config.base_url == "https://api.minimax.cn/v1"


def test_news_image_prompt_adds_specific_scene_and_hard_negatives():
    prompt = _build_aliyun_image_prompt(
        title="UK to give support to Saudi jets",
        body="英国将提供防御性空中支援。",
        topics=["每日新闻"],
        prompt_hint="UK to give support to Saudi jets in attempt to counter Houthi fighters",
    )

    assert "一到两架无标识飞机平稳巡航" in prompt
    assert "不要出现任何文字" in prompt
    assert "爆炸" in prompt
    assert "皇家空军" not in prompt


def test_visual_repair_hint_does_not_echo_logo_or_text_prescription():
    hint = _daily_news_image_repair_hint(
        "建议加入皇家空军圆形标志；画面缺少防御性巡航动作；请去除机身乱码文字。"
    )

    assert "皇家空军圆形标志" not in hint
    assert "乱码文字" not in hint
    assert "防御性巡航动作" in hint
    assert "不得采纳视觉模型提出的具体标志" in hint


def test_daily_news_story_identity_dedupes_url_and_title_variants():
    first = _daily_news_story_identity(
        {"url": "https://example.com/story?id=7&utm_source=rss", "title": "同一事件出现新进展"}
    )
    second = _daily_news_story_identity(
        {"url": "https://example.com/story?id=7", "title": "同一事件出现新进展"}
    )

    assert first & second


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


def test_visual_spares_replace_failed_news_before_upload(tmp_path, monkeypatch):
    def reviewed_post(post_id: str, *, ok: bool) -> Post:
        post_dir = tmp_path / post_id
        post_dir.mkdir()
        post = _post_with_image(post_dir)
        post.id = post_id
        post.platform["quality_gate"] = {
            "deterministic_ok": True,
            "vision": {
                "ok": ok,
                "score": 90 if ok else 20,
                "issues": [] if ok else ["图片与正文不一致"],
            },
        }
        return post

    saved: list[Post] = []
    monkeypatch.setattr(cli, "save_post", lambda post: saved.append(post))
    posts = [
        reviewed_post("ready-1", ok=True),
        reviewed_post("failed-1", ok=False),
        reviewed_post("ready-2", ok=True),
    ]

    applied, selected_count, failed_count, unused_count = _apply_visual_spare_selection(
        posts,
        requested_count=2,
    )

    assert applied is True
    assert [post.id for post in posts] == ["ready-1", "ready-2"]
    assert selected_count == 2
    assert failed_count == 1
    assert unused_count == 0
    assert saved[0].id == "failed-1"
    assert saved[0].platform["batch_selection"]["status"] == "visual_quality_failed"


def test_visual_selection_accepts_exactly_one_reviewed_news(tmp_path):
    post = _post_with_image(tmp_path)
    post.platform["quality_gate"] = {
        "deterministic_ok": True,
        "vision": {"ok": True, "score": 72, "issues": []},
    }
    posts = [post]

    applied, selected_count, failed_count, unused_count = _apply_visual_spare_selection(
        posts,
        requested_count=1,
    )

    assert applied is True
    assert posts == [post]
    assert (selected_count, failed_count, unused_count) == (1, 0, 0)


def test_daily_news_visual_spare_budget_covers_ten_item_batch():
    assert _daily_news_visual_spare_count(1) == 0
    assert _daily_news_visual_spare_count(10) == 4
    assert _daily_news_visual_spare_count(20) == 5


def test_visual_news_replenishment_fills_gap_after_initial_review(tmp_path):
    def reviewed_post(post_id: str, *, ok: bool) -> Post:
        post_dir = tmp_path / post_id
        post_dir.mkdir()
        post = _post_with_image(post_dir)
        post.id = post_id
        post.title = f"芯片企业发布新方案-{post_id}"
        post.platform["quality_gate"] = {
            "deterministic_ok": True,
            "vision": {"ok": ok, "score": 90 if ok else 20, "issues": [] if ok else ["乱码"]},
        }
        return post

    posts = [reviewed_post("ready-1", ok=True), reviewed_post("failed-1", ok=False)]
    generated: list[int] = []

    def generate_more(batch_size: int, _round: int) -> list[Post]:
        generated.append(batch_size)
        return [reviewed_post("ready-2", ok=True)]

    complete, rounds, selected_count, failed_count, unused_count, errors = _replenish_visual_news_until_target(
        posts,
        requested_count=2,
        generate_batch=generate_more,
        review_batch=lambda _new_posts: [],
        max_rounds=2,
        max_candidates=6,
    )

    assert complete is True
    assert rounds == 1
    assert selected_count == 2
    assert failed_count == 1
    assert unused_count == 0
    assert errors == []
    assert generated == [3]
    assert [post.id for post in posts] == ["ready-1", "failed-1", "ready-2"]


def test_low_scoring_best_of_two_does_not_count_as_visual_ready(tmp_path):
    first_dir = tmp_path / "first"
    first_dir.mkdir()
    poor = _post_with_image(first_dir)
    poor.platform["quality_gate"] = {
        "deterministic_ok": True,
        "vision": {
            "ok": False,
            "score": 15,
            "issues": ["画面主体与新闻无关"],
            "selection_mode": "best_of_two",
            "best_effort_eligible": True,
        },
    }
    replacement_dir = tmp_path / "replacement"
    replacement_dir.mkdir()
    replacement = _post_with_image(replacement_dir)
    replacement.id = "replacement"
    replacement.title = "另一条有合格图片的新闻"
    replacement.platform["quality_gate"] = {
        "deterministic_ok": True,
        "vision": {"ok": True, "score": 90, "issues": []},
    }
    posts = [poor]
    calls = []

    complete, rounds, selected_count, failed_count, _, errors = _replenish_visual_news_until_target(
        posts,
        requested_count=1,
        generate_batch=lambda size, round_no: calls.append((size, round_no)) or [replacement],
        review_batch=lambda _new_posts: [],
        max_rounds=1,
        max_candidates=4,
    )

    assert complete is True
    assert rounds == 1
    assert selected_count == 1
    assert failed_count == 1
    assert calls == [(3, 1)]
    assert errors == []


def test_visual_news_replenishment_respects_candidate_cap(tmp_path):
    post_dir = tmp_path / "failed"
    post_dir.mkdir()
    post = _post_with_image(post_dir)
    post.platform["quality_gate"] = {
        "deterministic_ok": True,
        "vision": {"ok": False, "score": 0, "issues": ["视觉失败"]},
    }
    posts = [post]
    calls = 0

    def generate_more(batch_size: int, _round: int) -> list[Post]:
        nonlocal calls
        calls += 1
        assert batch_size == 1
        extra_dir = tmp_path / f"extra-{calls}"
        extra_dir.mkdir()
        extra = _post_with_image(extra_dir)
        extra.id = f"extra-{calls}"
        extra.title = f"补偿候选-{calls}"
        extra.platform["quality_gate"] = {
            "deterministic_ok": True,
            "vision": {"ok": False, "score": 0, "issues": ["视觉失败"]},
        }
        return [extra]

    complete, rounds, selected_count, _failed_count, _unused_count, errors = _replenish_visual_news_until_target(
        posts,
        requested_count=2,
        generate_batch=generate_more,
        review_batch=lambda _new_posts: [],
        max_rounds=3,
        max_candidates=2,
    )

    assert complete is False
    assert rounds == 1
    assert selected_count == 0
    assert calls == 1
    assert any("候选上限" in error for error in errors)


def test_visual_news_replenishment_stops_on_provider_limit(tmp_path):
    post_dir = tmp_path / "failed"
    post_dir.mkdir()
    post = _post_with_image(post_dir)
    post.platform["quality_gate"] = {
        "deterministic_ok": True,
        "vision": {"ok": False, "score": 0, "issues": ["视觉失败"]},
    }
    posts = [post]
    calls = 0

    def generate_more(_batch_size: int, _round: int) -> list[Post]:
        nonlocal calls
        calls += 1
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra = _post_with_image(extra_dir)
        extra.id = "extra"
        extra.title = "供应商限流后的新候选"
        extra.platform["quality_gate"] = {
            "deterministic_ok": True,
            "vision": {"ok": False, "score": 0, "issues": ["视觉失败"]},
        }
        return [extra]

    complete, rounds, selected_count, _failed_count, _unused_count, errors = _replenish_visual_news_until_target(
        posts,
        requested_count=2,
        generate_batch=generate_more,
        review_batch=lambda _new_posts: ["HTTP 429: Token Plan 用量上限"],
        max_rounds=3,
        max_candidates=10,
    )

    assert complete is False
    assert rounds == 1
    assert selected_count == 0
    assert calls == 1
    assert any("HTTP 429" in error for error in errors)


def test_ai_digest_quality_gate_accepts_complete_local_render_without_vlm(tmp_path, monkeypatch):
    assets = []
    for index in range(4):
        path = tmp_path / ("ai_digest_00_cover.png" if index == 0 else f"ai_digest_{index:02d}.png")
        Image.effect_noise((320, 420), 45 + index).convert("RGB").save(path)
        assets.append(AssetInfo(path=str(path), kind="image"))
    post = Post(
        title="每日AI|模型与工具等8条更新",
        body="每日AI讯息\n发布日期：2026-08-09\n来源链接：\nhttps://example.com/ai",
        assets=assets,
        platform={
            "ai_digest": {
                "mode": "daily_ai_digest",
                "actual_items": 8,
                "items": [{"title": f"AI update {index}"} for index in range(8)],
            }
        },
    )
    saved: list[Post] = []
    monkeypatch.setattr(cli, "list_posts", lambda: [])
    monkeypatch.setattr(cli, "save_post", lambda item: saved.append(item))
    monkeypatch.setattr(cli, "configured_vision_review_model", lambda: "")
    monkeypatch.setattr(
        cli,
        "review_post_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("VLM must not be called")),
    )

    errors = cli._run_auto_quality_gate(
        [post],
        expected_count=1,
        evaluation_viewpoint="无视角评价",
        require_vision=True,
    )

    assert errors == []
    assert saved
    assert post.platform["quality_gate"]["vision"]["ok"] is True
    assert post.platform["quality_gate"]["vision"]["provider"] == "local_renderer"
    assert post.platform["quality_gate"]["vision"]["model"] == "ai_digest_template"


def test_quality_gate_does_not_treat_missing_vlm_as_pass_for_normal_news(monkeypatch):
    post = Post(
        title="明确的新闻标题",
        body="发布日期：2026-09-20\n来源链接：https://example.com/news",
        assets=[],
        platform={"news": {"source_url": "https://example.com/news", "picked": {"seendate": "2026-09-20"}}},
    )
    monkeypatch.setattr(cli, "configured_vision_review_model", lambda: "")
    monkeypatch.setattr(cli, "list_posts", lambda: [])

    errors = cli._run_auto_quality_gate(
        [post], expected_count=1, evaluation_viewpoint="无视角评价", require_vision=True
    )

    assert errors
    assert "视觉" in errors[0]


def test_quality_gate_does_not_treat_disabled_vlm_as_pass_when_required(monkeypatch):
    post = Post(title="新闻标题", body="新闻正文", assets=[])
    monkeypatch.setenv("AUTO_VLM_REVIEW", "0")

    errors = cli._run_auto_quality_gate(
        [post], expected_count=1, evaluation_viewpoint="无视角评价", require_vision=True
    )

    assert errors
    assert "关闭" in errors[0]


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


def test_bounded_image_repair_stops_after_one_redraw_without_stock_fallback():
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

    assert result.score == 24
    assert repair_count == 1
    assert repair_errors == []
    assert ai_repairs == ["Show a generic laptop RAM upgrade scene with no text."]
    assert pexels_fallbacks == []
    assert [item.score for item in history] == [24, 18]


def test_bounded_image_repair_keeps_higher_score_when_redraw_is_worse():
    post = Post(
        title="News",
        body="Body",
        platform={"news": {"source_url": "https://example.com/news"}, "marker": "first"},
    )
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    results = iter(
        [
            VisionReviewResult(False, 64, ("first",), "redraw", "volcengine", config.model),
            VisionReviewResult(False, 41, ("worse",), "", "volcengine", config.model),
        ]
    )

    def redraw(current_post, _prompt):
        current_post.platform["marker"] = "second"
        return True

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="neutral",
        max_repairs=3,
        review_fn=lambda *_args, **_kwargs: next(results),
        regenerate_fn=redraw,
    )

    assert result.score == 64
    assert repair_count == 1
    assert repair_errors == []
    assert [item.score for item in history] == [64, 41]
    assert post.platform["marker"] == "first"
    assert post.platform["vision_selection"] == {
        "strategy": "best_of_two",
        "candidate_count": 2,
        "selected_index": 1,
        "selected_score": 64,
        "alternate_score": 41,
        "below_threshold": True,
    }


def test_bounded_image_repair_reuses_completed_best_of_two_after_resume():
    post = Post(
        title="News",
        body="Body",
        platform={
            "news": {"source_url": "https://example.com/news"},
            "vision_selection": {
                "strategy": "best_of_two",
                "candidate_count": 2,
                "selected_index": 1,
                "selected_score": 64,
                "alternate_score": 41,
                "below_threshold": True,
            },
            "quality_gate": {
                "vision": {
                    "ok": False,
                    "score": 3,
                    "issues": ["text is garbled"],
                    "retry_prompt": "",
                    "provider": "volcengine",
                    "model": "doubao-seed-1-6-vision",
                    "repair_count": 0,
                    "selection_mode": "best_of_two",
                    "best_effort_eligible": True,
                    "repair_errors": [],
                    "history": [{"ok": False, "score": 3, "issues": ["text is garbled"]}],
                }
            },
        },
    )
    config = LLMConfig(
        provider="volcengine",
        model="doubao-seed-1-6-vision",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    review_calls: list[str] = []
    repair_calls: list[str] = []

    result, repair_count, repair_errors, history = _review_with_bounded_image_repair(
        post,
        config=config,
        viewpoint="neutral",
        max_repairs=1,
        review_fn=lambda *_args, **_kwargs: review_calls.append("review"),
        regenerate_fn=lambda _post, prompt: repair_calls.append(prompt) or True,
    )

    assert result.score == 64
    assert repair_count == 1
    assert repair_errors == []
    assert review_calls == []
    assert repair_calls == []
    assert [item.score for item in history] == [64, 41]


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
