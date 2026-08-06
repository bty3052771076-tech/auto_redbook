from src.publish.playwright_steps import (
    _bottom_draft_click_point,
    _click_draft,
    _draft_item_matches_post,
    _draft_title_matches_expected,
    _open_draft_editor_for_titles,
    _open_image_draft_tab,
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


def test_click_draft_tries_frame_button_before_coordinate_fallback():
    class FakeMouse:
        def __init__(self):
            self.clicks: list[tuple[int, int]] = []

        def click(self, x, y):
            self.clicks.append((x, y))

    class EmptyLocator:
        def count(self):
            return 0

    class ClickableLocator:
        def __init__(self):
            self.clicked = False

        def count(self):
            return 1

        def nth(self, _idx):
            return self

        def is_visible(self):
            return True

        def click(self, **_kwargs):
            self.clicked = True

    class FakeFrame:
        def __init__(self):
            self.button = ClickableLocator()

        def get_by_role(self, role, name=None):
            if role == "button" and name == "暂存离开":
                return self.button
            return EmptyLocator()

        def get_by_text(self, *_args, **_kwargs):
            return EmptyLocator()

        def locator(self, *_args, **_kwargs):
            return EmptyLocator()

        def evaluate(self, *_args):
            return ""

    class FakePage:
        viewport_size = {"width": 1600, "height": 900}
        main_frame = object()

        def __init__(self):
            self.mouse = FakeMouse()
            self.frame = FakeFrame()
            self.frames = [self.main_frame, self.frame]

        def evaluate(self, script, *_args):
            if "return out.slice" in script:
                return []
            return []

        def get_by_role(self, *_args, **_kwargs):
            return EmptyLocator()

        def get_by_text(self, *_args, **_kwargs):
            return EmptyLocator()

        def locator(self, *_args, **_kwargs):
            return EmptyLocator()

    page = FakePage()

    clicked, detail = _click_draft(page)

    assert clicked is True
    assert detail == "frame1:role-button:暂存离开"
    assert page.frame.button.clicked is True
    assert page.mouse.clicks == []


def test_click_draft_uses_element_from_point_before_mouse_coordinate():
    class FakeMouse:
        def __init__(self):
            self.clicks: list[tuple[int, int]] = []

        def click(self, x, y):
            self.clicks.append((x, y))

    class EmptyLocator:
        def count(self):
            return 0

    class FakePage:
        viewport_size = {"width": 1280, "height": 720}

        def __init__(self):
            self.mouse = FakeMouse()
            self.js_clicked = False

        def evaluate(self, script, *_args):
            if "return out.slice" in script:
                return []
            if "xhs-publish-btn" in script:
                return ""
            if "elementFromPoint" in script:
                self.js_clicked = True
                return "button:暂存离开"
            return []

        def get_by_role(self, *_args, **_kwargs):
            return EmptyLocator()

        def get_by_text(self, *_args, **_kwargs):
            return EmptyLocator()

        def locator(self, *_args, **_kwargs):
            return EmptyLocator()

    page = FakePage()

    clicked, detail = _click_draft(page)

    assert clicked is True
    assert detail == "coordinate-js:x=550,y=675:button:暂存离开"
    assert page.js_clicked is True
    assert page.mouse.clicks == []


def test_click_draft_prefers_xhs_publish_save_component():
    class FakeMouse:
        def __init__(self):
            self.clicks: list[tuple[int, int]] = []

        def click(self, x, y):
            self.clicks.append((x, y))

    class EmptyLocator:
        def count(self):
            return 0

    class FakePage:
        viewport_size = {"width": 1280, "height": 720}

        def __init__(self):
            self.mouse = FakeMouse()

        def evaluate(self, script, *_args):
            if "return out.slice" in script:
                return []
            if "xhs-publish-btn" in script:
                return "xhs-publish-btn:暂存离开"
            if "elementFromPoint" in script:
                return ""
            return []

        def get_by_role(self, *_args, **_kwargs):
            return EmptyLocator()

        def get_by_text(self, *_args, **_kwargs):
            return EmptyLocator()

        def locator(self, *_args, **_kwargs):
            return EmptyLocator()

    page = FakePage()

    clicked, detail = _click_draft(page)

    assert clicked is True
    assert detail == "xhs-publish-btn:暂存离开"
    assert page.mouse.clicks == []


def test_open_image_draft_tab_scopes_selection_to_open_draft_drawer():
    class EmptyLocator:
        def count(self):
            return 0

    class DrawerLocator:
        def count(self):
            return 1

        def nth(self, _index):
            return self

        def is_visible(self):
            return True

    class FakePage:
        def __init__(self):
            self.scripts: list[str] = []

        def locator(self, selector):
            if selector == ".draft-drawer":
                return DrawerLocator()
            return EmptyLocator()

        def get_by_text(self, *_args, **_kwargs):
            raise AssertionError("main-page tab lookup must not run when a draft drawer is open")

        def evaluate(self, script, *_args):
            self.scripts.append(script)
            if ".draft-tabs .tab-item" in script:
                return {"drawer": True, "clicked": True}
            return False

    page = FakePage()

    assert _open_image_draft_tab(page) is True
    assert any(".draft-tabs .tab-item" in script for script in page.scripts)


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


def test_open_draft_editor_for_titles_falls_back_to_current_title(monkeypatch):
    post = Post(id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", title="\u6bcf\u65e5AI|\u65b0\u6807\u9898")
    seen: list[str] = []

    def fake_open(_page, candidate):
        seen.append(candidate.title)
        if candidate.title == "\u6bcf\u65e5AI|\u65e7\u6807\u9898":
            raise RuntimeError("draft not found")
        return {"title": candidate.title}

    monkeypatch.setattr("src.publish.playwright_steps._open_draft_editor_for_post", fake_open)

    item, matched_title = _open_draft_editor_for_titles(
        object(),
        post,
        titles=["\u6bcf\u65e5AI|\u65e7\u6807\u9898", post.title],
    )

    assert seen == ["\u6bcf\u65e5AI|\u65e7\u6807\u9898", post.title]
    assert item == {"title": post.title}
    assert matched_title == post.title


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
