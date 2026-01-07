from src.news.daily_news import NewsItem, pick_best_news, pick_news_items
from src.workflow.create_post import _ensure_daily_news_sections


def test_pick_best_news_empty_hint_returns_first():
    items = [
        NewsItem(title="A", url="https://example.com/a", seendate="20250101T000000Z"),
        NewsItem(title="B", url="https://example.com/b", seendate="20250102T000000Z"),
    ]
    picked = pick_best_news(items, "")
    assert picked.title == "A"


def test_pick_best_news_prefers_title_match():
    items = [
        NewsItem(title="苹果发布新款Mac", url="https://example.com/1"),
        NewsItem(title="新能源车销量创新高", url="https://example.com/2"),
        NewsItem(title="足球赛事回顾", url="https://example.com/3"),
    ]
    picked = pick_best_news(items, "新能源车")
    assert "新能源" in picked.title


def test_pick_best_news_tiebreaker_by_seendate():
    items = [
        NewsItem(title="AI 芯片公司融资", url="https://example.com/1", seendate="20250101T000000Z"),
        NewsItem(title="AI 芯片公司融资", url="https://example.com/2", seendate="20250102T000000Z"),
    ]
    picked = pick_best_news(items, "AI 芯片")
    assert picked.url == "https://example.com/2"


def test_pick_best_news_tiebreaker_by_iso_seendate():
    items = [
        NewsItem(title="AI 芯片公司融资", url="https://example.com/1", seendate="2025-01-01T00:00:00Z"),
        NewsItem(title="AI 芯片公司融资", url="https://example.com/2", seendate="2025-01-02T00:00:00Z"),
    ]
    picked = pick_best_news(items, "AI 芯片")
    assert picked.url == "https://example.com/2"


def test_pick_news_items_empty_hint_returns_first_n_distinct():
    items = [
        NewsItem(title="A", url="https://example.com/a"),
        NewsItem(title="B", url="https://example.com/b"),
        NewsItem(title="A-dup", url="https://example.com/a"),
        NewsItem(title="C", url="https://example.com/c"),
    ]
    picked = pick_news_items(items, "", count=3)
    assert [p.url for p in picked] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_pick_news_items_with_hint_returns_single_best():
    items = [
        NewsItem(title="新能源车销量创新高", url="https://example.com/1"),
        NewsItem(title="苹果发布新款Mac", url="https://example.com/2"),
    ]
    picked = pick_news_items(items, "新能源", count=3)
    assert len(picked) == 1
    assert "新能源" in picked[0].title


def test_ensure_daily_news_sections_adds_headings():
    body = "这是只有一段的正文。"
    out = _ensure_daily_news_sections(body, "美国时政")
    assert "新闻内容：" in out
    assert "我的点评：" in out


def test_ensure_daily_news_sections_preserves_two_paragraphs():
    body = "第一段内容。\n\n第二段点评。"
    out = _ensure_daily_news_sections(body, "")
    assert out.splitlines()[0] == "新闻内容："
    assert "第一段内容。" in out
    assert "我的点评：" in out
