from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.ai_digest.models import AIUpdateItem
from src.storage.models import AssetInfo, Post
from src.workflow.content_evidence import (
    ai_digest_items_in_beijing_window,
    text_integrity_issues,
)
from src.workflow.quality_gate import validate_post_batch


def _image(path: Path) -> Path:
    Image.new("RGB", (160, 160), (30, 120, 90)).save(path)
    return path


def test_text_integrity_rejects_question_mark_corruption_and_replacement_character():
    issues = text_integrity_issues("每日新闻????", "正文包含�和???")

    assert "replacement_character" in issues
    assert "question_mark_corruption" in issues


def test_post_quality_gate_rejects_corrupted_text_even_when_image_is_valid(tmp_path: Path):
    image = _image(tmp_path / "cover.png")
    post = Post(
        title="每日新闻????",
        body="正文???",
        assets=[AssetInfo(path=str(image), kind="image")],
    )

    report = validate_post_batch([post], expected_count=1)

    assert not report.ok
    assert {issue.code for issue in report.issues} >= {
        "question_mark_corruption",
    }


def test_ai_digest_publish_window_keeps_only_beijing_today_and_yesterday():
    items = [
        AIUpdateItem(
            title="今日模型发布",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商A",
            url="https://example.com/today",
            published_at="2026-09-13T00:30:00+08:00",
        ),
        AIUpdateItem(
            title="昨日模型发布",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商B",
            url="https://example.com/yesterday",
            published_at="2026-09-12T23:30:00+08:00",
        ),
        AIUpdateItem(
            title="前日模型发布",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商C",
            url="https://example.com/old",
            published_at="2026-09-11T23:30:00+08:00",
        ),
    ]

    selected, meta = ai_digest_items_in_beijing_window(
        items,
        publication_date="2026-09-13",
    )

    assert [item.title for item in selected] == ["今日模型发布", "昨日模型发布"]
    assert meta["dropped_out_of_window"] == 1


def test_ai_digest_publish_window_rejects_future_and_unknown_dates():
    items = [
        AIUpdateItem(
            title="未来模型发布",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商A",
            url="https://example.com/future",
            published_at="2026-09-14T00:01:00+08:00",
        ),
        AIUpdateItem(
            title="无日期模型发布",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商B",
            url="https://example.com/unknown",
            published_at="",
        ),
    ]

    selected, meta = ai_digest_items_in_beijing_window(
        items,
        publication_date="2026-09-13",
    )

    assert selected == []
    assert meta["dropped_future"] == 1
    assert meta["dropped_unknown_date"] == 1


def test_ai_digest_publish_window_dedupes_same_url_with_different_headlines():
    items = [
        AIUpdateItem(
            title="厂商发布模型版本",
            summary="厂商发布模型版本并开放接口。",
            source_name="厂商A",
            url="https://example.com/model?utm_source=feed",
            published_at="2026-09-13T08:00:00+08:00",
        ),
        AIUpdateItem(
            title="模型版本正式开放",
            summary="厂商发布模型版本并开放接口。",
            source_name="资讯站",
            url="https://example.com/model",
            published_at="2026-09-13T09:00:00+08:00",
        ),
    ]

    selected, meta = ai_digest_items_in_beijing_window(
        items,
        publication_date="2026-09-13",
    )

    assert len(selected) == 1
    assert meta["duplicate_removed"] == 1


def test_ai_digest_publish_window_dedupes_same_model_release_across_urls():
    items = [
        AIUpdateItem(
            title="GLM-5.3正式发布",
            summary="智谱发布GLM-5.3模型。",
            source_name="智谱官网",
            source_type="official",
            url="https://www.zhipuai.cn/news/glm-5-3",
            published_at="2026-09-13T08:00:00+08:00",
            vendor="智谱",
            product="GLM-5.3",
        ),
        AIUpdateItem(
            title="GLM 5.3上线并开放服务",
            summary="资讯站转述智谱发布GLM 5.3模型。",
            source_name="AI资讯站",
            source_type="aggregator",
            url="https://news.example.com/glm-53-launch",
            published_at="2026-09-13T09:00:00+08:00",
            vendor="智谱",
            product="GLM 5.3",
        ),
    ]

    selected, meta = ai_digest_items_in_beijing_window(
        items,
        publication_date="2026-09-13",
    )

    assert len(selected) == 1
    assert meta["duplicate_removed"] == 1


def test_ai_required_image_policy_rejects_stock_fallback(tmp_path: Path):
    image = _image(tmp_path / "pexels.png")
    post = Post(
        title="新闻标题",
        body="新闻正文",
        assets=[AssetInfo(path=str(image), kind="image")],
        platform={
            "news": {"image_policy": "ai_required"},
            "images": [{"provider": "pexels", "downloaded_path": str(image)}],
        },
    )

    report = validate_post_batch([post], expected_count=1)

    assert not report.ok
    assert any(issue.code == "ai_image_required" for issue in report.issues)
