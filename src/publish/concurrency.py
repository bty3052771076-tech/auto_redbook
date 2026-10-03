"""Process-level guards for browser automation against platform races."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator


_XHS_UPLOAD_LOCK = Lock()


@contextmanager
def xhs_upload_slot(*, timeout_s: float | None = None) -> Iterator[None]:
    """Allow one creator-center draft save across threads and processes.

    The in-process lock protects threads. A one-byte advisory file lock covers
    a CLI process and the Web GUI process sharing the same workspace/profile.
    """
    timeout = float(timeout_s if timeout_s is not None else os.getenv("XHS_UPLOAD_LOCK_TIMEOUT_S", "900"))
    lock_path = Path(os.getenv("XHS_UPLOAD_LOCK_PATH", "data/runs/xhs-upload.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _XHS_UPLOAD_LOCK:
        with lock_path.open("a+b") as stream:
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            acquired = False
            deadline = time.monotonic() + max(0.1, timeout)
            try:
                if os.name == "nt":
                    import msvcrt

                    while time.monotonic() < deadline:
                        try:
                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                            acquired = True
                            break
                        except OSError:
                            time.sleep(0.1)
                else:
                    import fcntl

                    while time.monotonic() < deadline:
                        try:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired = True
                            break
                        except BlockingIOError:
                            time.sleep(0.1)
                if not acquired:
                    raise TimeoutError(f"小红书上传锁等待超时（{timeout:.0f}s）")
                yield
            finally:
                if acquired:
                    if os.name == "nt":
                        import msvcrt

                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
