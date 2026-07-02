from src.publish.playwright_steps import (
    _published_metrics_collection_status,
    _parse_metric_number,
    _parse_published_metric_text,
    _parse_published_total_text,
    _published_metrics_collect_cap,
    _published_url_candidates,
)


def test_parse_metric_number_supports_chinese_and_short_units():
    assert _parse_metric_number("1.2万") == 12000
    assert _parse_metric_number("3k") == 3000
    assert _parse_metric_number("1,234") == 1234


def test_parse_published_metric_text_extracts_title_and_counts():
    parsed = _parse_published_metric_text(
        "中国科技新闻标题\n点赞 12\n评论：3\n收藏 4\n2026-06-27"
    )

    assert parsed["title"] == "中国科技新闻标题"
    assert parsed["likes"] == 12
    assert parsed["comments"] == 3
    assert parsed["favorites"] == 4


def test_parse_published_metric_text_extracts_note_manager_stats_row():
    parsed = _parse_published_metric_text(
        "七孩父亲在妻产四胞胎后离奇去世\n2026-06-27 08:19\n33\n1\n2\n3\n4"
    )

    assert parsed["title"] == "七孩父亲在妻产四胞胎后离奇去世"
    assert parsed["published_at"] == "2026-06-27"
    assert parsed["likes"] == 1
    assert parsed["comments"] == 2
    assert parsed["favorites"] == 3


def test_published_metrics_defaults_prefer_current_note_manager_route():
    assert _published_url_candidates()[0] == "https://creator.xiaohongshu.com/new/note-manager"


def test_published_metrics_collect_cap_is_configurable(monkeypatch):
    assert _published_metrics_collect_cap() >= 1000

    monkeypatch.setenv("XHS_METRICS_MAX_ITEMS", "25")

    assert _published_metrics_collect_cap() == 25


def test_parse_published_total_text():
    assert _parse_published_total_text("全部 297\n已发布\n审核中") == 297
    assert _parse_published_total_text("没有总数") == 0


def test_published_metrics_collection_status_requires_target_total_when_unlimited():
    status = _published_metrics_collection_status(collected=317, target_total=322, limit=0)

    assert status["complete"] is False
    assert status["missing_count"] == 5
    assert "fetched=317 target=322 missing=5" in status["message"]


def test_published_metrics_collection_status_treats_limit_as_requested_scope():
    status = _published_metrics_collection_status(collected=50, target_total=322, limit=50)

    assert status["complete"] is True
    assert status["required_total"] == 50
