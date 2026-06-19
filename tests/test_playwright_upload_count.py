from src.publish.playwright_steps import UPLOAD_COUNT_PATTERN


def test_upload_count_pattern_matches_xhs_counter_text():
    match = UPLOAD_COUNT_PATTERN.search("图片编辑 1/18")

    assert match is not None
    assert match.group(1) == "1"
