from __future__ import annotations

import threading
import time

from src.workflow.model_queues import ModelWorkQueues, infer_llm_provider
from src.workflow.create_post import (
    DEFAULT_DAILY_NEWS_COORDINATOR_WORKERS,
    _daily_news_coordinator_workers,
)


def _measure_peak(queue, count: int = 4) -> int:
    active = 0
    peak = 0
    lock = threading.Lock()

    def work() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1

    futures = [queue.submit(work) for _ in range(count)]
    for future in futures:
        future.result()
    return peak


def test_llm_and_image_queues_are_independent_and_capped_at_two():
    with ModelWorkQueues(llm_workers=2, image_workers=2) as queues:
        assert _measure_peak(queues.llm) == 2
        assert _measure_peak(queues.image) == 2


def test_model_queue_workers_cannot_be_configured_above_two():
    with ModelWorkQueues(llm_workers=8, image_workers=8) as queues:
        assert queues.llm_workers == 2
        assert queues.image_workers == 2


def test_minimax_llm_queue_allows_five_workers_but_image_stays_at_two():
    with ModelWorkQueues(
        llm_workers=8,
        image_workers=8,
        llm_provider="minimax",
    ) as queues:
        assert queues.llm_workers == 5
        assert queues.image_workers == 2
        assert _measure_peak(queues.llm, count=8) == 5


def test_infer_llm_provider_only_for_single_provider():
    class Config:
        def __init__(self, provider):
            self.provider = provider

    assert infer_llm_provider([Config("minimax"), Config("minimax")]) == "minimax"
    assert infer_llm_provider([Config("minimax"), Config("aliyun")]) is None


def test_daily_news_coordinator_has_workers_to_overlap_bounded_model_queues(monkeypatch):
    monkeypatch.delenv("DAILY_NEWS_COORDINATOR_WORKERS", raising=False)
    assert _daily_news_coordinator_workers() == DEFAULT_DAILY_NEWS_COORDINATOR_WORKERS == 4

    monkeypatch.setenv("DAILY_NEWS_COORDINATOR_WORKERS", "20")
    assert _daily_news_coordinator_workers() == 6

    monkeypatch.setenv("DAILY_NEWS_COORDINATOR_WORKERS", "0")
    assert _daily_news_coordinator_workers() == 2
