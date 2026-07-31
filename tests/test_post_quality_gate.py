from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.storage.models import AssetInfo, Post, PostStatus
from src.workflow.quality_gate import inspect_image, validate_post_batch


def _image(path: Path, *, color=(40, 100, 180)) -> Path:
    image = Image.new("RGB", (320, 420), color)
    for x in range(40, 280):
        image.putpixel((x, 210), (220, 80, 60))
    image.save(path)
    return path


def _news_post(
    image_path: Path,
    *,
    title: str,
    body_date: str = "2026-07-28",
    source_date: str = "2026-07-28T08:00:00+08:00",
    source_url: str = "https://example.com/news/1",
) -> Post:
    return Post(
        title=title,
        body=(
            "内容：这是经过来源核验的新闻正文，包含事件主体、变化和实际影响。"
            "\n\n评价：应继续关注正式文件和后续执行。"
            f"\n\n日期：{body_date}\n\n来源：示例媒体"
        ),
        assets=[AssetInfo(path=str(image_path), kind="image")],
        platform={
            "news": {
                "source_url": source_url,
                "picked": {
                    "title": title,
                    "url": source_url,
                    "seendate": source_date,
                    "source": "示例媒体",
                },
            }
        },
    )


def test_quality_gate_rejects_source_date_mismatch(tmp_path):
    post = _news_post(
        _image(tmp_path / "news.png"),
        title="Meta出租算力引发市场波动",
        body_date="2026-07-28",
        source_date="2026-07-25T08:00:00+08:00",
    )

    report = validate_post_batch([post], expected_count=1)

    assert not report.ok
    assert any(issue.code == "source_date_mismatch" for issue in report.issues)


def test_quality_gate_accepts_alphavantage_compact_source_date(tmp_path):
    post = _news_post(
        _image(tmp_path / "news.png"),
        title="国际企业发布最新业务数据",
        body_date="2026-07-28",
        source_date="20260728T155945Z",
    )

    report = validate_post_batch([post], expected_count=1)

    assert report.ok


def test_quality_gate_rejects_duplicate_event_across_different_urls(tmp_path):
    image_path = _image(tmp_path / "news.png")
    first = _news_post(
        image_path,
        title="Meta出租AI算力引发股价波动",
        source_url="https://example.com/a",
    )
    second = _news_post(
        image_path,
        title="Meta开放AI算力出租后股价出现波动",
        source_url="https://other.example.com/b",
    )

    report = validate_post_batch([first, second], expected_count=2)

    assert not report.ok
    assert any(issue.code == "duplicate_event" and issue.post_id == second.id for issue in report.issues)


def test_quality_gate_rejects_non_simplified_generated_fields(tmp_path):
    post = _news_post(
        _image(tmp_path / "news.png"),
        title="臺灣企業發佈人工智慧模型",
    )

    report = validate_post_batch([post], expected_count=1)

    assert not report.ok
    assert any(issue.code == "non_simplified_chinese" for issue in report.issues)


def test_batch_gate_requires_exact_requested_count_before_upload(tmp_path):
    post = _news_post(
        _image(tmp_path / "news.png"),
        title="国内制造业发布新技术方案",
    )

    report = validate_post_batch([post], expected_count=3)

    assert not report.ok
    assert report.issues[0].code == "batch_count_mismatch"


def test_batch_gate_rejects_uploaded_historical_source_duplicate(tmp_path):
    image_path = _image(tmp_path / "news.png")
    current = _news_post(
        image_path,
        title="国内芯片企业发布新方案",
        source_url="https://example.com/news/42?utm_source=feed",
    )
    historical = _news_post(
        image_path,
        title="旧稿标题",
        source_url="https://example.com/news/42",
    )
    historical.status = PostStatus.saved_draft
    historical.uploaded = True

    report = validate_post_batch(
        [current],
        expected_count=1,
        historical_posts=[historical],
    )

    assert not report.ok
    assert any(issue.code == "historical_duplicate" for issue in report.issues)


def test_batch_gate_allows_daily_ai_digests_with_different_source_items():
    current = Post(
        title="每日AI讯息",
        platform={
            "ai_digest": {
                "items": [
                    {"url": f"https://current.example.com/update-{index}"}
                    for index in range(8)
                ]
            }
        },
    )
    historical = Post(
        title="每日AI讯息",
        status=PostStatus.published,
        uploaded=True,
        platform={
            "ai_digest": {
                "items": [
                    {"url": f"https://history.example.com/update-{index}"}
                    for index in range(8)
                ]
            }
        },
    )

    report = validate_post_batch(
        [current],
        expected_count=1,
        historical_posts=[historical],
    )

    assert report.ok


def test_batch_gate_rejects_daily_ai_digest_with_mostly_same_source_items():
    shared = [f"https://example.com/update-{index}" for index in range(7)]
    current = Post(
        title="每日AI讯息",
        platform={
            "ai_digest": {
                "items": [
                    *({"url": url} for url in shared),
                    {"url": "https://example.com/current-only"},
                ]
            }
        },
    )
    historical = Post(
        title="每日AI讯息",
        status=PostStatus.published,
        uploaded=True,
        platform={
            "ai_digest": {
                "items": [
                    *({"url": url} for url in shared),
                    {"url": "https://example.com/history-only"},
                ]
            }
        },
    )

    report = validate_post_batch(
        [current],
        expected_count=1,
        historical_posts=[historical],
    )

    assert not report.ok
    assert any(issue.code == "historical_duplicate" for issue in report.issues)


def test_image_inspection_rejects_blank_or_broken_images(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (320, 420), "white").save(blank)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")

    blank_result = inspect_image(blank)
    broken_result = inspect_image(broken)

    assert not blank_result.ok
    assert blank_result.code == "blank_image"
    assert not broken_result.ok
    assert broken_result.code == "broken_image"
