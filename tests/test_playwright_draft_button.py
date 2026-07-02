from src.publish.playwright_steps import (
    _bottom_draft_click_point,
    _click_draft,
    _draft_item_matches_post,
    _draft_title_matches_expected,
    _open_draft_list_and_check_saved,
    _pick_draft_click_candidate,
    _read_editor_draft_snapshot,
    _title_match_terms,
)
from src.storage.models import Post


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


def test_click_draft_prefers_visible_text_candidate_before_coordinate_fallback():
    class FakeMouse:
        def __init__(self):
            self.clicks: list[tuple[int, int]] = []

        def click(self, x, y):
            self.clicks.append((x, y))

    class FakePage:
        viewport_size = {"width": 1600, "height": 900}

        def __init__(self):
            self.mouse = FakeMouse()

        def evaluate(self, script, *_args):
            if "return out.slice" in script:
                return [
                    {"text": "暂存离开", "x": 548, "y": 675, "bottom": 696},
                ]
            return []

    page = FakePage()

    clicked, detail = _click_draft(page)

    assert clicked is True
    assert detail == "current:ranked-text:暂存离开:x=548,y=675"
    assert page.mouse.clicks == [(548, 675)]


def test_open_draft_list_and_check_saved_reopens_publish_page_when_inline_box_missing(monkeypatch):
    calls: list[dict] = []
    page = object()
    post = Post(id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", title="每日AI讯息")

    monkeypatch.setattr("src.publish.playwright_steps._open_draft_box", lambda _page: False)
    monkeypatch.setattr("src.publish.playwright_steps._open_image_draft_tab", lambda _page: False)
    monkeypatch.setattr(
        "src.publish.playwright_steps._open_platform_draft_list",
        lambda _page, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "src.publish.playwright_steps._draft_item_exists",
        lambda _page, title: title == "每日AI讯息",
    )

    opened, exists = _open_draft_list_and_check_saved(
        page,
        post,
        wait_timeout_ms=123000,
        headless=True,
    )

    assert opened is True
    assert exists is True
    assert calls and calls[0]["draft_type"] == "image"
    assert calls[0]["wait_timeout_ms"] == 123000
    assert calls[0]["headless"] is True


def test_open_draft_list_and_check_saved_waits_for_platform_list_refresh(monkeypatch):
    calls: list[dict] = []
    checks = iter([False, False, True])
    sleeps: list[float] = []
    page = object()
    post = Post(id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", title="八部门发文推进工业互联网高质量发展")

    monkeypatch.setattr("src.publish.playwright_steps._open_draft_box", lambda _page: False)
    monkeypatch.setattr("src.publish.playwright_steps._open_image_draft_tab", lambda _page: False)
    monkeypatch.setattr(
        "src.publish.playwright_steps._open_platform_draft_list",
        lambda _page, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "src.publish.playwright_steps._draft_item_exists",
        lambda _page, _title: next(checks),
    )
    monkeypatch.setattr("src.publish.playwright_steps.time.sleep", lambda seconds: sleeps.append(seconds))

    opened, exists = _open_draft_list_and_check_saved(
        page,
        post,
        wait_timeout_ms=3000,
        headless=False,
    )

    assert opened is True
    assert exists is True
    assert calls
    assert sleeps == [1, 1]


def test_title_match_terms_ignore_generic_daily_news_prefix():
    terms = _title_match_terms("每日新闻｜Inside the figh")

    assert "每日新闻" not in terms
    assert "Inside" in terms
    assert "figh" in terms


def test_draft_title_match_requires_specific_title_not_generic_prefix():
    assert _draft_title_matches_expected("每日新闻｜The Korean Tele", "每日新闻｜Inside the figh") is False
    assert _draft_title_matches_expected("暂无笔记标题", "每日新闻｜Inside the figh") is False
    assert _draft_title_matches_expected("每日新闻｜Inside the figh", "每日新闻｜Inside the figh") is True


def test_draft_item_matches_post_uses_specific_local_title():
    post = Post(id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", title="AI chip factory expands")

    assert _draft_item_matches_post({"title": "AI chip factory expands"}, post) is True
    assert _draft_item_matches_post({"title": "Different daily news"}, post) is False
    assert _draft_item_matches_post({"title": ""}, post) is False


def test_read_editor_draft_snapshot_returns_actual_title_and_body():
    class FakePage:
        def evaluate(self, _script):
            return {
                "actual_title": "Edited title before publish",
                "actual_body": "Edited body before publish",
            }

    assert _read_editor_draft_snapshot(FakePage()) == {
        "actual_title": "Edited title before publish",
        "actual_body": "Edited body before publish",
    }
