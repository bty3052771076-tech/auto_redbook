"""Process-level guards for browser automation against platform races."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator


_XHS_UPLOAD_LOCK = Lock()


@contextmanager
def xhs_upload_slot() -> Iterator[None]:
    """Allow exactly one creator-center draft save in this process."""
    with _XHS_UPLOAD_LOCK:
        yield
