"""Bounded, independent queues for model work.

The two providers have different rate limits and failure modes, so LLM and
image work must never share a worker pool.  The public cap is intentionally
two workers per queue; callers may lower it for a provider with a stricter
account limit, but cannot raise it here.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


def _cap_workers(value: int) -> int:
    return max(1, min(2, int(value)))


class ModelWorkQueues:
    """Own one bounded executor for LLM work and one for image work."""

    def __init__(self, *, llm_workers: int = 2, image_workers: int = 2) -> None:
        self.llm_workers = _cap_workers(llm_workers)
        self.image_workers = _cap_workers(image_workers)
        self.llm = ThreadPoolExecutor(max_workers=self.llm_workers, thread_name_prefix="redbook-llm")
        self.image = ThreadPoolExecutor(max_workers=self.image_workers, thread_name_prefix="redbook-image")

    def submit_llm(self, fn: Callable[..., T], *args, **kwargs) -> Future[T]:
        return self.llm.submit(fn, *args, **kwargs)

    def submit_image(self, fn: Callable[..., T], *args, **kwargs) -> Future[T]:
        return self.image.submit(fn, *args, **kwargs)

    def close(self) -> None:
        self.llm.shutdown(wait=True, cancel_futures=False)
        self.image.shutdown(wait=True, cancel_futures=False)

    def __enter__(self) -> "ModelWorkQueues":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
