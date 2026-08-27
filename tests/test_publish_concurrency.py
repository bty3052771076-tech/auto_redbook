from __future__ import annotations

import threading
import time

from src.publish import playwright_steps
from src.publish.concurrency import xhs_upload_slot


def test_xhs_upload_slot_serializes_creator_center_sessions():
    active = 0
    peak = 0
    lock = threading.Lock()

    def task() -> None:
        nonlocal active, peak
        with xhs_upload_slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1

    threads = [threading.Thread(target=task) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


def test_run_save_draft_sync_keeps_platform_runner_serial(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_runner(*_args, **_kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return "saved"

    monkeypatch.setattr(playwright_steps, "_run_save_draft_sync_unlocked", fake_runner)
    threads = [
        threading.Thread(target=playwright_steps.run_save_draft_sync, args=(object(),))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1
