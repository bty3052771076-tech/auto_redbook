from src.publish.playwright_steps import _parse_metric_number, _parse_published_metric_text


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
