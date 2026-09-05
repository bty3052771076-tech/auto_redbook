"""Bounded, independent queues for model work.

LLM and image work use separate pools.  MiniMax Token Plan permits a larger
LLM agent fan-out, while other providers retain the conservative two-request
cap.  Image generation remains capped at two and publishing is handled by
the caller's serial upload loop.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


def _normalize_provider(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _cap_workers(value: int, *, maximum: int) -> int:
    return max(1, min(maximum, int(value)))


def infer_llm_provider(configs: object) -> str | None:
    """Return a provider only when every configured LLM is that provider."""
    try:
        providers = {
            _normalize_provider(getattr(config, "provider", ""))
            for config in configs  # type: ignore[union-attr]
            if _normalize_provider(getattr(config, "provider", ""))
        }
    except TypeError:
        return None
    return next(iter(providers)) if len(providers) == 1 else None


class ModelWorkQueues:
    """Own one bounded executor for LLM work and one for image work."""

    def __init__(
        self,
        *,
        llm_workers: int = 2,
        image_workers: int = 2,
        llm_provider: str | None = None,
    ) -> None:
        self.llm_provider = _normalize_provider(llm_provider)
        llm_maximum = 5 if self.llm_provider == "minimax" else 2
        self.llm_workers = _cap_workers(llm_workers, maximum=llm_maximum)
        self.image_workers = _cap_workers(image_workers, maximum=2)
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
