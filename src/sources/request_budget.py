"""Small, dependency-free request budget and single-flight cache."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from typing import Callable, Generic, Iterator, TypeVar


T = TypeVar("T")


class RequestBudget:
    """Cap concurrent external requests without coupling provider queues."""

    def __init__(self, max_in_flight: int = 4) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        self.max_in_flight = int(max_in_flight)
        self._semaphore = threading.BoundedSemaphore(self.max_in_flight)

    @contextmanager
    def slot(self, timeout: float | None = None) -> Iterator[None]:
        acquired = self._semaphore.acquire(timeout=timeout) if timeout is not None else self._semaphore.acquire()
        if not acquired:
            raise TimeoutError("request budget slot unavailable before deadline")
        try:
            yield
        finally:
            self._semaphore.release()


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLRequestCache(Generic[T]):
    """TTL cache with per-key single-flight loading."""

    def __init__(self, default_ttl_s: float = 30.0) -> None:
        if default_ttl_s <= 0:
            raise ValueError("default_ttl_s must be > 0")
        self.default_ttl_s = float(default_ttl_s)
        self._entries: dict[str, _CacheEntry[T]] = {}
        self._key_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(str(key), threading.Lock())

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._entries.get(str(key))
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                self._entries.pop(str(key), None)
                return None
            return entry.value

    def set(self, key: str, value: T, *, ttl_s: float | None = None) -> None:
        ttl = self.default_ttl_s if ttl_s is None else float(ttl_s)
        if ttl <= 0:
            raise ValueError("ttl_s must be > 0")
        with self._lock:
            self._entries[str(key)] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl)

    def get_or_set(
        self,
        key: str,
        loader: Callable[[], T],
        *,
        ttl_s: float | None = None,
    ) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        with self._lock_for(key):
            cached = self.get(key)
            if cached is not None:
                return cached
            value = loader()
            self.set(key, value, ttl_s=ttl_s)
            return value
