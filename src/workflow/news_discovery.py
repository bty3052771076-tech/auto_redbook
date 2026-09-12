"""Adaptive ordinary-news discovery; AI digests and manual materials opt out."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.news.daily_news import (
    NewsFetchSession, _canonical_domain, _cjk_story_event_signature, _dedupe_by_story,
    _domain_for_item, _is_china_item, _parse_seendate_utc, _resolve_tz,
    _required_china_count_for_daily_news, _same_cjk_story_event,
    _source_domain_max_ratio, daily_news_international_conflict_quota,
    filter_prompt_relevant_news_items, filter_recent_news_items,
    is_international_conflict_news, rank_news_candidate_pool,
)
from src.news.history import normalize_news_url_key


AUTO_NEWS_WINDOWS = (1, 2, 3, 5)
NEWS_LOOKBACK_MAX = 5


def resolve_news_windows(value: object = None, *, env_names: tuple[str, ...] = ()):
    source = "argument"
    if value is None or str(value).strip() == "":
        source = "default"
        for name in env_names:
            configured = os.getenv(name, "").strip()
            if configured:
                value, source = configured, name
                break
    raw = str(value or "").strip().lower() if value != 0 else "0"
    if raw in {"", "auto"}:
        windows = list(AUTO_NEWS_WINDOWS)
        mode = "auto"
    else:
        if not re.fullmatch(r"[1-5]", raw):
            raise ValueError(
                f"每日新闻回溯设置 {source}={value!r} 无效；请选择 auto（自动1/2/3/5天）或整数1至5。"
                "旧的7/14天配置请改为auto；固定天数不足时不会自动扩展。"
            )
        windows, mode = [int(raw)], "fixed"
    return windows, {"mode": mode, "source": source, "windows": windows,
                     "max_allowed_days": NEWS_LOOKBACK_MAX, "rule_version": "adaptive_1_2_3_5_v1"}


def news_key(item: Any) -> str:
    return normalize_news_url_key(item.url) or str(item.title)


def news_domain(item: Any) -> str:
    return _canonical_domain(_domain_for_item(item)) or "unknown"


def feasible_news_batch(items: list[Any], count: int, *, china: int, conflict: int,
                        total: int | None = None, accepted: list[Any] | None = None) -> list[Any]:
    """Solve count, both editorial quotas and domain capacity together.

    DP state caps quota counters; domain-local options avoid an exponential
    tuple of per-domain counters. Order is a preference, not a quota bypass.
    """
    if count <= 0:
        return []
    accepted = accepted or []
    total = total or count
    groups: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    for index, item in enumerate(items):
        groups[news_domain(item)].append((index, item))
    used = Counter(news_domain(item) for item in accepted)
    cap = max(1, math.ceil(total * _source_domain_max_ratio()))
    # Preserve the existing single-source exception, but never invent domains.
    if len(set(groups) | set(used)) <= 1:
        cap = total
    states = {(0, 0, 0): ()}

    def keep(table, state, indices):
        existing = table.get(state)
        indices = tuple(sorted(indices))
        if existing is None or indices < existing:
            table[state] = indices

    for domain, group in groups.items():
        capacity = max(0, cap - used[domain])
        options = {(0, 0, 0): ()}
        for index, item in group:
            for (n, c, f), indices in list(options.items()):
                if n >= min(count, capacity):
                    continue
                state = (n + 1, min(china, c + int(_is_china_item(item))),
                         min(conflict, f + int(is_international_conflict_news(item))))
                keep(options, state, (*indices, index))
        combined = {}
        for (n, c, f), indices in states.items():
            for (dn, dc, df), extra in options.items():
                if n + dn <= count:
                    keep(combined, (n + dn, min(china, c + dc), min(conflict, f + df)), (*indices, *extra))
        states = combined
    chosen = states.get((count, china, conflict), ())
    return [items[index] for index in chosen]


class DailyNewsDiscovery:
    """Retain source/context work while expanding or replacing rejected stories."""

    def __init__(self, *, prompt: str, count: int, windows: list[int], window_meta: dict,
                 raw_target: int, preferred_target: int, budget_seconds: float,
                 fetch: Callable, prepare: Callable, incomplete: Callable,
                 progress: Callable | None = None, history_signatures: list | None = None):
        self.prompt, self.count = prompt, count
        self.windows, self.window_meta = windows, window_meta
        self.raw_target, self.preferred_target = raw_target, preferred_target
        self.reserve_target = min(5, max(1, math.ceil(count * 0.3)))
        self.china = _required_china_count_for_daily_news(count)
        self.conflict = daily_news_international_conflict_quota(count)
        if max(self.china, self.conflict) > count:
            raise ValueError("新闻数量与国内/国际争议配额矛盾，请调整数量。")
        self.fetch, self.prepare, self.incomplete, self.progress = fetch, prepare, incomplete, progress
        self.session = NewsFetchSession(datetime.now(timezone.utc), budget_seconds)
        self.raw: dict[str, Any] = {}
        self.prepared: dict[str, tuple] = {}
        self.checked: set[str] = set()
        self.offered: set[str] = set()
        self.signatures = list(history_signatures or [])
        self.reviewed_stories: list[Any] = []
        self.rejected: Counter = Counter()
        self.review_log: list[dict[str, Any]] = []
        self.review_seconds = 0.0
        self.review_batches = 0
        self.material_titles: set[str] = set()
        self.attempts: list[dict] = []
        self.source_rounds: list[dict] = []
        self.index = -1
        self.meta: dict[str, Any] = {}
        self.stop_reason = "collecting"
        self.record_path = Path("data/runs/news_discovery") / f"{uuid4().hex}.json"

    def emit(self, stage, status="in_progress", **detail):
        if self.progress:
            self.progress(stage, status, detail)

    def save_record(self, *, status: str | None = None, post_ids: list[str] | None = None):
        """Persist diagnosis, not credentials or a claim of upload success."""
        self.meta["discovery_record"] = str(self.record_path)
        payload = {"selection_pool": self.meta.get("selection_pool", {}),
                   "status": status or self.stop_reason, "local_post_ids": post_ids or [],
                   "raw_candidates": [asdict(item) for item in self.raw.values()],
                   "reviewed_keys": sorted(self.checked), "offered_keys": sorted(self.offered),
                   "material_candidates": [asdict(item) for item in self.reviewed_stories],
                   "material_review_log": self.review_log}
        try:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.record_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.record_path)
        except OSError as exc:
            self.emit("候选记录", "warning", reason=f"无法写入候选记录，请检查目录写权限或磁盘空间：{type(exc).__name__}")

    def _pool(self):
        days = self.windows[self.index]
        recent, dates = filter_recent_news_items(
            list(self.raw.values()), tz_name="Asia/Shanghai", max_age_days=days, now=self.session.now)
        recent = [item for item in recent if self._valid_time(item)]
        relevant, relevance = filter_prompt_relevant_news_items(recent, self.prompt)
        keys = {news_key(item) for item in relevant}
        if self.conflict:
            relevant += [item for item in recent if is_international_conflict_news(item) and news_key(item) not in keys]
        keys = {news_key(item) for item in relevant}
        if self.china:
            relevant += [item for item in recent if _is_china_item(item) and news_key(item) not in keys]
        ordered = rank_news_candidate_pool(relevant, self.prompt)
        # Calendar day first; preserve existing attention/relevance order within a day.
        ordered.sort(key=lambda item: _parse_seendate_utc(item.seendate).astimezone(_resolve_tz("Asia/Shanghai")).date(), reverse=True)
        return ordered, dates, relevance, len(recent)

    def _valid_time(self, item):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.seendate or "")):
            return str(item.seendate) <= self.session.now.astimezone(_resolve_tz("Asia/Shanghai")).date().isoformat()
        stamp = _parse_seendate_utc(item.seendate)
        return stamp is not None and stamp <= self.session.now

    def _next_window(self):
        if self.index + 1 >= len(self.windows):
            return False
        self.index += 1
        days = self.windows[self.index]
        self.emit("扩展检索", window_days=days, remaining_seconds=round(self.session.remaining_seconds, 1),
                  reason="initial_window" if self.index == 0 else "candidate_or_reserve_shortfall")
        queries = []
        if self.china:
            queries.append("中国 国内 政策 产业 民生")
        if self.conflict:
            queries += ["国际冲突 停火 制裁 争端 争议事件", "international conflict ceasefire sanctions military dispute"]
        try:
            items, meta = self.fetch(
                self.prompt, tz_name="Asia/Shanghai", max_records=self.raw_target, search_days=days,
                source_health_path="data/source_health/daily_news.json", persist_source_health=True,
                exhaustive_sources=True, progress_callback=self.progress,
                additional_queries=queries, session=self.session)
        except TypeError as exc:
            # Keep local test doubles and third-party integrations with the
            # historical one-argument callable contract usable.
            if "unexpected keyword" not in str(exc) and "positional" not in str(exc):
                raise
            items, meta = self.fetch(self.prompt)
        self.source_rounds.append({key: value for key, value in meta.items() if key != "candidates"})
        self.meta.update(meta)
        for item in items:
            key = news_key(item)
            # Never refresh an old event's date from a later syndicated copy.
            if key not in self.raw:
                self.raw[key] = item
        return True

    def _available(self, ordered):
        available = []
        seen = set(self.offered)
        for item in ordered:
            prepared = self.prepared.get(news_key(item))
            if prepared is None or news_key(prepared[0]) in seen:
                continue
            available.append(prepared[0])
            seen.add(news_key(prepared[0]))
        return available

    def _review(self, items):
        if not items:
            return
        started = time.perf_counter()
        self.review_batches += 1
        self.checked.update(news_key(item) for item in items)
        def title_key(item):
            return re.sub(r"\W+", "", str(item.title).casefold())

        pending = []
        for item in items:
            if title_key(item) and title_key(item) in self.material_titles:
                self.rejected["duplicate_title_before_lookup"] += 1
                self.review_log.append({"url": item.url, "title": item.title,
                                        "reason": "duplicate_title_before_lookup"})
            else:
                pending.append(item)
        if not pending:
            return
        self.emit("材料审核", batch=self.review_batches, count=len(pending),
                  checked=len(self.checked), reason="原文补全与单事件核验")
        results = self.prepare(pending, progress_callback=self.progress)
        self.review_seconds += time.perf_counter() - started
        for index, original in enumerate(pending, 1):
            audit = {"batch": self.review_batches, "url": original.url, "title": original.title,
                     "raw_conflict": is_international_conflict_news(original), "reason": "accepted"}
            self.review_log.append(audit)
            prepared = results.get(index)
            if prepared is None:
                self.rejected["context_lookup_failed"] += 1
                audit["reason"] = "context_lookup_failed"
                continue
            enriched, lookup, focus, dedupe = prepared
            audit["lookup"] = lookup
            audit["material_conflict"] = is_international_conflict_news(enriched)
            if self.incomplete(enriched):
                self.rejected["context_insufficient"] += 1
                audit["reason"] = "context_insufficient"
                continue
            recent, _ = filter_recent_news_items([enriched], tz_name="Asia/Shanghai",
                max_age_days=self.windows[self.index], now=self.session.now)
            if not recent or not self._valid_time(enriched):
                self.rejected["enriched_date_out_of_window"] += 1
                audit["reason"] = "enriched_date_out_of_window"
                continue
            signature = _cjk_story_event_signature(dedupe)
            if any(_same_cjk_story_event(signature, seen) for seen in self.signatures):
                self.rejected["duplicate_event"] += 1
                audit["reason"] = "duplicate_event_signature"
                continue
            if len(_dedupe_by_story([*self.reviewed_stories, dedupe], max_count=len(self.reviewed_stories) + 1)) <= len(self.reviewed_stories):
                self.rejected["duplicate_event"] += 1
                audit["reason"] = "duplicate_event_similarity"
                continue
            self.signatures.append(signature)
            self.reviewed_stories.append(dedupe)
            self.material_titles.add(title_key(original))
            self.material_titles.add(title_key(enriched))
            self.prepared[news_key(original)] = prepared
            self.prepared[news_key(enriched)] = prepared

    def take(self, *, accepted: list[Any] | None = None, carry: list[Any] | None = None,
             initial: bool = False):
        accepted = accepted or []
        carry = carry or []
        needed = self.count - len(accepted)
        china = max(0, self.china - sum(_is_china_item(item) for item in accepted))
        conflict = max(0, self.conflict - sum(is_international_conflict_news(item) for item in accepted))
        if needed <= 0:
            return []
        if self.index < 0:
            self._next_window()
        while True:
            ordered, dates, relevance, recent_count = self._pool()
            unchecked = [item for item in ordered if news_key(item) not in self.checked]
            while True:
                available = self._available(ordered)
                carry_keys = {news_key(item) for item in carry}
                available = [*carry, *[item for item in available if news_key(item) not in carry_keys]]
                main = feasible_news_batch(available, needed, china=china, conflict=conflict,
                                           total=self.count, accepted=accepted)
                reserve = max(0, len(available) - needed) if main else 0
                if main and reserve >= self.reserve_target:
                    break
                if not unchecked:
                    break
                china_gap = max(0, china - sum(_is_china_item(item) for item in available))
                conflict_gap = max(0, conflict - sum(is_international_conflict_news(item) for item in available))
                # A missing required lane cannot be filled by reviewing more ordinary stories.
                if (conflict_gap > sum(is_international_conflict_news(item) for item in unchecked)
                        or china_gap > sum(_is_china_item(item) for item in unchecked)):
                    self.emit("配额预筛", "warning", window_days=self.windows[self.index],
                              deferred=len(unchecked), china_missing=china_gap, conflict_missing=conflict_gap,
                              reason="原始候选类别不足，延后普通材料审核，检查下一日期窗口")
                    break
                prioritized = sorted(unchecked, key=lambda item: (
                    not (conflict_gap and is_international_conflict_news(item)),
                    not (china_gap and _is_china_item(item)),
                ))
                size = min(8, max(1, needed + self.reserve_target - len(available)))
                if china_gap or conflict_gap:
                    size = min(8, max(2, china_gap + conflict_gap))
                shortlist = prioritized[:size]
                shortlist_keys = {news_key(item) for item in shortlist}
                unchecked = [item for item in unchecked if news_key(item) not in shortlist_keys]
                self._review(shortlist)
            attempt = {"max_age_days": self.windows[self.index], "raw_candidate_count": len(self.raw),
                       "recent_candidate_count": recent_count, "prompt_relevant_candidate_count": len(ordered),
                       "material_candidate_count": len(available), "main_candidate_count": len(main),
                       "reserve_count": reserve, "date_window": dates,
                       "raw_conflict_count": sum(is_international_conflict_news(item) for item in ordered),
                       "material_conflict_count": sum(is_international_conflict_news(item) for item in available),
                       "deferred_context_count": len(unchecked),
                       "context_review_seconds": round(self.review_seconds, 3),
                       "china_missing": max(0, china - sum(_is_china_item(item) for item in available)),
                       "conflict_missing": max(0, conflict - sum(is_international_conflict_news(item) for item in available))}
            self.attempts.append(attempt)
            self.emit("候选筛选", window_days=self.windows[self.index], recent=recent_count,
                      relevant=len(ordered), qualified=len(available), min_qualified=needed,
                      preferred_target=self.preferred_target, main=len(main), reserve=reserve,
                      china_missing=attempt["china_missing"], conflict_missing=attempt["conflict_missing"])
            if main and reserve >= self.reserve_target:
                self.stop_reason = "ready_with_reserve"
                break
            if not self._next_window():
                self.stop_reason = ("ready_without_full_reserve" if main else
                                    "budget_incomplete" if self.session.budget_incomplete else
                                    "quota_unmet" if len(available) >= needed else "exhausted_insufficient")
                break
        self.meta["selection_pool"] = {
            "rule_version": "adaptive_1_2_3_5_v1", "requested_count": self.count,
            "target_fetch_count": self.preferred_target, "raw_fetch_count": self.raw_target,
            "raw_candidate_count": len(self.raw), "actual_candidate_count": len(available),
            "prompt_relevant_candidate_count": len(ordered), "recent_candidate_count": recent_count,
            "dropped_out_of_window_count": max(0, len(self.raw) - recent_count),
            "material_candidate_count": len(available), "reserve_target": self.reserve_target,
            "context_review_seconds": round(self.review_seconds, 3),
            "context_review_batches": self.review_batches,
            "context_checked_count": len(self.checked),
            "reserve_count": reserve, "stop_reason": self.stop_reason, "date_window": dates,
            "prompt_relevance": relevance, "rejections": dict(self.rejected),
            "lookback": {**self.window_meta, "selected_max_age_days": self.windows[self.index], "attempts": list(self.attempts)},
            "source_rounds": list(self.source_rounds), "frozen_at": self.session.now.isoformat(),
            "remaining_discovery_seconds": self.session.remaining_seconds,
            "remaining_windows": self.windows[self.index + 1:],
            "source_domain_count": len({news_domain(item) for item in available}),
        }
        if not main:
            self.save_record()
            message = (f"每日新闻材料不足：需要补齐{needed}条，材料合格{len(available)}条；"
                       f"国内缺{attempt['china_missing']}条、国际争议缺{attempt['conflict_missing']}条。"
                       f"已检查窗口{[row['max_age_days'] for row in self.attempts]}，状态={self.stop_reason}。"
                       "请补充近期信源、检查新闻API配额或调整提示词；数量够但无法组成主候选时请检查同源集中度。")
            message += (f"原始国际争议候选{attempt['raw_conflict_count']}条，审核合格"
                        f"{attempt['material_conflict_count']}条；延后审核{len(unchecked)}条普通/其他候选。")
            if self.session.budget_incomplete:
                message += "采集预算内未完成所有历史请求，不能据此断言这些日期没有新闻。"
            self.emit("候选不足", "failed", reason=message)
            if initial:
                raise RuntimeError(message)
            return []
        chosen_keys = {news_key(item) for item in main}
        output = main + [item for item in available if news_key(item) not in chosen_keys]
        self.offered.update(news_key(item) for item in output)
        self.save_record()
        if len({news_domain(item) for item in available}) < 2:
            self.emit("信源覆盖", "warning", reason="仅一个可用来源；沿用单源例外，覆盖不足已记录")
        self.emit("候选就绪", "success", main=len(main), target=needed,
                  reserve=len(output) - len(main), reserve_target=self.reserve_target,
                  window_days=self.windows[self.index], reason=self.stop_reason)
        return output
