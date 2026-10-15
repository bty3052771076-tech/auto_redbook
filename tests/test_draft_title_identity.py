from html import escape

import pytest

from src.publish import playwright_steps as steps
from src.storage.models import Post


EXPECTED = "工业巨头工博会谈工业级AI落地门槛"
UNRELATED = ["津巴布韦作家否认用AI撰写获奖短篇", "每日AI|OpenAI发布",
             "AI鸡蛋|Codex重置到账提醒", "每日AI|企业应用与智能体研究",
             "每日AI|改进离散扩散语言模型的监督微调"]


@pytest.mark.parametrize("actual", UNRELATED)
def test_common_ai_fragment_never_identifies_another_draft(actual):
    assert not steps._draft_title_matches_expected(actual, EXPECTED)


@pytest.mark.parametrize("actual,expected,want", [
    ("每日新闻｜OpenAI 发布 GPT-5", "openai发布GPT-5", True),
    ("每日我去|成年选手赢得越野比赛冠军", "成年选手赢得越野比赛冠军", True),
    ("特朗普：宣布提高汽车进口关税", "拜登：宣布提高汽车进口关税", False),
    ("补贴从100元提高到200元", "补贴从100元提高到300元", False),
    ("监管机构允许平台使用用户数据", "监管机构不允许平台使用用户数据", False),
    ("工业巨头工博会谈工业级AI", EXPECTED, True),
    ("工业巨头工博会谈工业级…", EXPECTED, True),
    ("工业巨头…", EXPECTED, False),
    ("每日新闻|AI", EXPECTED, False),
])
def test_title_identity_uses_complete_or_sufficiently_long_prefix(actual, expected, want):
    assert steps._draft_title_matches_expected(actual, expected) is want


def test_list_lookup_prefers_full_identity_over_earlier_prefix(monkeypatch):
    items = [{'index': '0', 'title': '工业巨头工博会谈工业级AI'},
             {'index': '1', 'title': EXPECTED}]
    monkeypatch.setattr(steps, '_collect_draft_items', lambda *a, **kw: items)
    index, item = steps._find_platform_draft_index_for_post(object(), Post(title=EXPECTED))
    assert index == 1 and item['title'] == EXPECTED


def test_duplicate_full_titles_are_not_resolved_by_picking_first(monkeypatch):
    monkeypatch.setattr(steps, '_collect_draft_items', lambda *a, **kw: [
        {'index': '0', 'title': EXPECTED}, {'index': '1', 'title': EXPECTED}])
    with pytest.raises(RuntimeError, match='ambiguous'):
        steps._find_platform_draft_index_for_post(object(), Post(title=EXPECTED))


@pytest.fixture(scope='module')
def draft_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        yield page
        browser.close()


@pytest.mark.parametrize('entries,exists,cover', [
    ([(UNRELATED[0], True)], False, False),
    ([(UNRELATED[0], True), (EXPECTED, False)], True, False),
    ([('工业巨头工博会谈工业级AI', True), (EXPECTED, False)], True, False),
    ([(EXPECTED, True), (EXPECTED, False)], False, False),
    ([(EXPECTED, True)], True, True),
])
def test_dom_existence_and_cover_share_unique_title_identity(draft_page, entries, exists, cover):
    draft_page.set_content(''.join(
        f'<div class="draft-item"><span class="draft-title-text">{escape(title)}</span>'
        + ('<div class="media-bg" style="background-image:url(https://example.invalid/cover.jpg)"></div>' if ready else '')
        + '</div>' for title, ready in entries))
    assert steps._draft_item_exists(draft_page, EXPECTED) is exists
    assert steps._draft_item_has_cover(draft_page, EXPECTED) is cover
