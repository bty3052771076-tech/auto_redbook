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
