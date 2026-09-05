"""Bounded, deduplicated search planning for AI digest discovery."""

from __future__ import annotations

from dataclasses import dataclass

from src.workflow.performance import PerformancePolicy


@dataclass(frozen=True)
class SearchPlan:
    queries: tuple[str, ...]
    max_concurrency: int


def build_search_plan(
    queries: list[str] | tuple[str, ...] | None,
    *,
    performance_mode: str | None = None,
) -> SearchPlan:
    policy = (
        PerformancePolicy.from_value(performance_mode)
        if performance_mode is not None
        else PerformancePolicy.from_environment()
    )
    unique: list[str] = []
    seen: set[str] = set()
    for value in queries or ():
        query = " ".join(str(value or "").split()).strip()
        key = query.casefold()
        if not query or key in seen:
            continue
        unique.append(query)
        seen.add(key)
    if policy.is_speed_first:
        unique = unique[: policy.ai_initial_search_queries]
    return SearchPlan(
        queries=tuple(unique),
        max_concurrency=policy.ai_backfill_concurrency if policy.is_speed_first else 1,
    )
