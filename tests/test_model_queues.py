from __future__ import annotations

import threading
import time

from src.workflow.model_queues import ModelWorkQueues


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
