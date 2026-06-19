from src.publish.playwright_steps import (
    _bottom_draft_click_point,
    _draft_title_matches_expected,
    _pick_draft_click_candidate,
    _title_match_terms,
)


def test_bottom_draft_click_point_targets_left_bottom_action():
    assert _bottom_draft_click_point({"width": 1280, "height": 720}) == (550, 675)


def test_pick_draft_click_candidate_prefers_bottom_temporary_leave():
    candidates = [
        {"text": "保存草稿", "x": 900, "y": 120, "bottom": 150},
        {"text": "暂存离开", "x": 548, "y": 675, "bottom": 696},
    ]

    picked = _pick_draft_click_candidate(candidates)

    assert picked is not None
    assert picked["text"] == "暂存离开"
    assert picked["x"] == 548


def test_pick_draft_click_candidate_ignores_publish_text():
    candidates = [
        {"text": "发布", "x": 690, "y": 675, "bottom": 696},
        {"text": "保存草稿", "x": 550, "y": 675, "bottom": 696},
    ]

    picked = _pick_draft_click_candidate(candidates)

    assert picked is not None
    assert picked["text"] == "保存草稿"


def test_title_match_terms_ignore_generic_daily_news_prefix():
    terms = _title_match_terms("每日新闻｜Inside the figh")

    assert "每日新闻" not in terms
    assert "Inside" in terms
    assert "figh" in terms


def test_draft_title_match_requires_specific_title_not_generic_prefix():
    assert _draft_title_matches_expected("每日新闻｜The Korean Tele", "每日新闻｜Inside the figh") is False
    assert _draft_title_matches_expected("暂无笔记标题", "每日新闻｜Inside the figh") is False
    assert _draft_title_matches_expected("每日新闻｜Inside the figh", "每日新闻｜Inside the figh") is True
