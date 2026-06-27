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
