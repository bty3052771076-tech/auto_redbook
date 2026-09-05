from __future__ import annotations

import threading
import time

from src.news.daily_news import NewsItem
from src.workflow import create_post


def test_prefetch_daily_news_context_is_bounded_and_reports_progress(monkeypatch):
    monkeypatch.setenv("NEWS_SOURCE_LOOKUP_CONCURRENCY", "2")
    active = 0
    peak = 0
    lock = threading.Lock()
    events: list[tuple[str, str, dict]] = []

    def fake_enrich(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return item, {"source_lookup": {"ok": True}}

    monkeypatch.setattr(create_post, "_enrich_daily_news_item", fake_enrich)
    monkeypatch.setattr(create_post, "_focus_daily_news_item", lambda item: (item, {}))

    picks = [
        NewsItem(
            title=f"新闻 {index}",
            url=f"https://example.com/{index}",
            description="这是一条有足够上下文的新闻摘要，用于测试来源补充并行处理。",
        )
        for index in range(3)
    ]
    prepared = create_post._prefetch_daily_news_context(
        picks,
        progress_callback=lambda stage, status, detail: events.append(
            (stage, status, detail)
        ),
    )

    assert list(sorted(prepared)) == [1, 2, 3]
    assert peak == 2
    assert events[-1][1] == "success"
    assert events[-1][2]["completed"] == 3


def test_daily_news_context_accepts_title_plus_rss_summary_but_not_title_only():
    with_summary = NewsItem(
        title="国际冲突双方就停火安排继续谈判并公布最新进展",
        url="https://news.google.com/rss/articles/example",
        description="双方代表在最新会谈后分别说明当前立场，相关安排仍需进一步确认，后续将继续磋商。双方表示将通过正式渠道发布后续信息，并继续就停火执行、人员安全和地区局势展开沟通。会谈涉及停火安排、人员安全、地区局势和后续信息发布等具体事项。",
    )
    title_only = NewsItem(
        title="国际冲突双方就停火安排继续谈判并公布最新进展",
        url="https://news.google.com/rss/articles/example-2",
    )

    assert create_post._daily_news_context_is_incomplete(with_summary) is False
    assert create_post._daily_news_context_is_incomplete(title_only) is True
