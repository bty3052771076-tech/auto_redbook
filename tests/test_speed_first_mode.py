from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from src.workflow.performance import PerformancePolicy, RunContext, iter_first_completed
from src.sources.request_budget import RequestBudget, TTLRequestCache
from src.ai_digest import collect as collect_mod
from src.ai_digest.search_plan import build_search_plan
from src.news.daily_news import NewsItem
from apps.gui import build_cli_args


def test_speed_policy_is_explicit_and_keeps_model_lanes_independent():
    balanced = PerformancePolicy.from_value("balanced")
    speed = PerformancePolicy.from_value("speed")

    assert balanced.mode == "balanced"
    assert speed.mode == "speed"
    assert speed.news_candidate_deadline_s < balanced.news_candidate_deadline_s
    assert speed.llm_workers == balanced.llm_workers == 2
    assert speed.image_workers == balanced.image_workers == 2
    assert speed.llm_workers_for_provider("minimax") == 5
    assert speed.llm_workers_for_provider("aliyun") == 2


def test_performance_policy_rejects_unknown_mode():
    with pytest.raises(ValueError, match="performance mode"):
        PerformancePolicy.from_value("turbo")


def test_run_context_keeps_secret_free_run_metadata(tmp_path):
    context = RunContext.create(
        "speed",
        run_id="run-test",
        telemetry_dir=tmp_path,
        model_config={"llm": "minimax", "image": "minimax"},
    )

    assert context.run_id == "run-test"
    assert context.policy.mode == "speed"
    context.record("stage", "success", provider="minimax", api_key="should-not-persist")
    text = (tmp_path / "run-test" / "events.jsonl").read_text(encoding="utf-8")
    assert "should-not-persist" not in text
    assert "api_key" not in text


def test_request_budget_caps_in_flight_requests():
    budget = RequestBudget(max_in_flight=2)
    active = 0
    peak = 0
    lock = threading.Lock()

    def work():
        nonlocal active, peak
        with budget.slot(timeout=1):
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 2


def test_ttl_cache_singleflight_and_expiry():
    cache = TTLRequestCache(default_ttl_s=0.03)
    calls = 0
    lock = threading.Lock()

    def loader():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.02)
        return {"ok": True}

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get_or_set("k", loader)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [{"ok": True}] * 4
    assert calls == 1
    time.sleep(0.04)
    assert cache.get_or_set("k", loader) == {"ok": True}
    assert calls == 2


def test_speed_scheduler_refills_a_lane_when_one_item_finishes():
    started: list[str] = []
    lock = threading.Lock()

    def work(item: tuple[str, float]) -> str:
        name, delay = item
        with lock:
            started.append(name)
        time.sleep(delay)
        return name

    items = [("slow", 0.12), ("fast", 0.02), ("refill", 0.02)]
    completed = list(iter_first_completed(items, work, max_workers=2))

    assert [result for _, result, error in completed if error is None] == ["fast", "refill", "slow"]
    assert started.index("refill") < 3


def test_speed_ai_backfill_queries_run_in_parallel(monkeypatch):
    calls: list[str] = []

    def fake_fetch(query: str, **_kwargs):
        calls.append(query)
        time.sleep(0.05)
        return [
            NewsItem(
                title=f"{query} model release",
                url=f"https://example.com/{len(calls)}",
                source="fixture",
                domain="example.com",
                seendate="2026-07-29T08:00:00Z",
                description="Concrete model release details",
            )
        ], {"tz": "Asia/Shanghai"}

    monkeypatch.setattr("src.news.daily_news.fetch_daily_news_candidates", fake_fetch)
    started_at = time.monotonic()
    items, meta = collect_mod.fetch_ai_digest_search_backfill(
        max_age_days=3,
        now=datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
        queries=["q1", "q2", "q3"],
        max_records=2,
        performance_mode="speed",
    )

    assert time.monotonic() - started_at < 0.14
    assert len(calls) == 3
    assert len(items) == 3
    assert len(meta["queries"]) == 3


def test_gui_builds_explicit_speed_mode_argument():
    args = build_cli_args(
        "auto",
        params={"title": "每日新闻", "count": 1, "performance_mode": "speed"},
    )
    assert args[args.index("--performance-mode") + 1] == "speed"


def test_speed_search_plan_deduplicates_and_limits_first_round():
    plan = build_search_plan([" official model release ", "official model release", "q3"], performance_mode="speed")
    assert plan.queries == ("official model release", "q3")
    assert plan.max_concurrency == 3
