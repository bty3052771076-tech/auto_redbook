from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from src.ai_digest.generate import render_ai_digest_body
from src.ai_digest.models import AIDigestBrief, AIUpdateItem
from src.storage.models import AssetInfo, Post
from src.validation.rules import validate_post


def updates(count=18, *, verbose_source=False):
    published = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return [
        AIUpdateItem(
            title=f"BudgetModel{index}模型正式发布并开放开发者推理接口及工具调用功能",
            summary=f"测试厂商发布BudgetModel{index}模型，开放文本推理接口和工具调用，开发者可通过API接入应用。",
            source_name=("测试厂商官方开发者技术公告" * 100 if verbose_source else f"测试厂商{index % 4}"),
            vendor=("" if verbose_source else f"测试厂商{index % 4}"),
            source_type="official", product=f"BudgetModel{index}",
            url=f"https://example.com/model-release-{index}",
            published_at=published,
            raw_excerpt=f"测试厂商发布BudgetModel{index}模型，开放文本推理接口和工具调用，开发者可通过API接入应用。",
        )
        for index in range(count)
    ]


@pytest.mark.parametrize("count", [17, 18, 20])
def test_caption_fits_800_without_mutating_complete_items(count):
    brief = AIDigestBrief(date="2026-10-22", items=updates(count))
    before = brief.model_dump()
    body = render_ai_digest_body(brief)
    assert len(body) <= 800
    assert brief.model_dump() == before
    assert brief.items[0].title in body
    assert "http" not in body


def test_oversized_source_labels_do_not_force_caption_over_budget():
    brief = AIDigestBrief(date="2026-10-22", items=updates(2, verbose_source=True))
    before = brief.model_dump()
    body = render_ai_digest_body(brief)
    assert len(body) <= 800
    assert brief.items[0].title in body
    assert brief.model_dump() == before


def test_caption_omission_is_explicit_and_does_not_cut_a_headline():
    items = updates(20)
    brief = AIDigestBrief(date="2026-10-22", items=items)
    body = render_ai_digest_body(brief)
    displayed = [item for item in items if item.title in body]
    assert displayed
    assert "BudgetModel0" in body
    if len(displayed) < len(items):
        assert f"其余{len(items) - len(displayed)}条" in body
        assert "配图" in body
    for line in body.splitlines():
        if ". " in line and line.split(". ", 1)[0].isdigit():
            title = line.split(". ", 1)[1]
            assert any(title == item.title for item in items)


@pytest.mark.parametrize("length,blocked", [(799, False), (800, False), (801, True), (1000, True)])
def test_ai_digest_validation_enforces_800_including_whitespace(tmp_path, length, blocked):
    image = tmp_path / "image.png"
    Image.new("RGB", (2, 2)).save(image)
    body = "甲" * (length - 2) + "\n乙"
    post = Post(title="每日AI|模型发布", body=body,
                assets=[AssetInfo(path=str(image))],
                platform={"ai_digest": {"mode": "daily_ai_digest"}})
    errors = validate_post(post).errors
    assert any(error.startswith("body too long:") for error in errors) is blocked


def test_news_with_ai_in_title_keeps_its_existing_1000_limit(tmp_path):
    image = tmp_path / "image.png"
    Image.new("RGB", (2, 2)).save(image)
    post = Post(title="AI产业新消息", body="甲" * 1000,
                assets=[AssetInfo(path=str(image))], platform={"news": {}})
    assert validate_post(post).ok


@pytest.mark.parametrize("broken_renderer", [False, True])
def test_generation_does_not_save_an_oversized_caption_or_repeat_source_calls(monkeypatch, tmp_path, broken_renderer):
    from src.ai_digest.generate import build_fallback_brief
    from src.workflow import create_post as workflow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_DIGEST_IMPACT_SUPERVISOR", "0")
    monkeypatch.setenv("AI_DIGEST_HIGH_IMPACT_SCORE", "0")
    monkeypatch.delenv("AI_DIGEST_TARGET_ITEMS", raising=False)
    monkeypatch.delenv("AI_DIGEST_MAX_ITEMS", raising=False)
    items = updates(18)
    calls = {"sources": 0, "writer": 0}
    saved = []

    def collect(**kwargs):
        calls["sources"] += 1
        return items, {}

    def rewrite(configs, selected, target_count, **kwargs):
        calls["writer"] += 1
        return build_fallback_brief(selected, target_count=target_count)

    def render(brief, **kwargs):
        return "甲" * 801 if broken_renderer and calls["writer"] else render_ai_digest_body(brief, **kwargs)

    image = tmp_path / "card.png"
    Image.new("RGB", (2, 2)).save(image)
    monkeypatch.setattr(workflow, "collect_ai_digest_updates", collect)
    monkeypatch.setattr(workflow, "load_llm_configs", lambda: [])
    monkeypatch.setattr(workflow, "generate_ai_digest_brief_with_llm", rewrite)
    monkeypatch.setattr(workflow, "render_ai_digest_body", render)
    monkeypatch.setattr(workflow, "render_ai_digest_cards", lambda *args, **kwargs: [image])
    monkeypatch.setattr(workflow, "save_post", saved.append)
    monkeypatch.setattr(workflow, "save_revision", lambda revision: None)

    if broken_renderer:
        with pytest.raises(RuntimeError, match="801 > 800"):
            workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)
        assert saved == []
    else:
        post = workflow.create_daily_ai_digest_posts(asset_paths=[], lookback_days=2)[0]
        assert len(post.body) <= 800
        assert len(post.platform["ai_digest"]["items"]) == 18
        assert saved == [post]
    assert calls == {"sources": 1, "writer": 1}
