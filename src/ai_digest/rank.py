from __future__ import annotations

from collections import OrderedDict

from .models import AIUpdateItem


def _merge_items(primary: AIUpdateItem, other: AIUpdateItem) -> AIUpdateItem:
    data = primary.model_dump()
    evidence = list(data.get("evidence_urls") or [])
    for url in [other.url, *(other.evidence_urls or [])]:
        if url and url not in evidence and url != primary.url:
            evidence.append(url)
    data["evidence_urls"] = evidence
    tags = list(data.get("tags") or [])
    for tag in other.tags or []:
        if tag and tag not in tags:
            tags.append(tag)
    data["tags"] = tags
    if primary.source_type in {"official", "github"} and other.source_type in {"social", "search"}:
        data["verification_status"] = "social_confirmed"
        data["confidence_score"] = max(primary.confidence_score, 0.9)
    elif (
        primary.source_type in {"official", "github"}
        and other.verification_status == "social_confirmed"
    ):
        data["verification_status"] = "social_confirmed"
        data["confidence_score"] = max(primary.confidence_score, other.confidence_score, 0.9)
    return AIUpdateItem.model_validate(data)


def _prefer_item(a: AIUpdateItem, b: AIUpdateItem) -> AIUpdateItem:
    priority = {"official": 4, "github": 3, "search": 2, "social": 1}
    if priority.get(b.source_type, 0) > priority.get(a.source_type, 0):
        return b
    if (
        priority.get(b.source_type, 0) == priority.get(a.source_type, 0)
        and len(b.title or "") < len(a.title or "")
    ):
        return b
    if b.confidence_score > a.confidence_score:
        return b
    return a


def _dedupe_updates(items: list[AIUpdateItem]) -> list[AIUpdateItem]:
    by_key: OrderedDict[str, AIUpdateItem] = OrderedDict()
    title_keys: dict[str, str] = {}
    for item in items:
        key = item.dedupe_key
        title_key = item.title_key
        existing_key = title_keys.get(title_key)
        if existing_key and existing_key in by_key:
            merged = by_key[existing_key]
            if key in by_key and key != existing_key:
                winner = _prefer_item(merged, by_key[key])
                loser = by_key[key] if winner is merged else merged
                merged = _merge_items(winner, loser)
                del by_key[key]
            winner = _prefer_item(merged, item)
            loser = item if winner is merged else merged
            by_key[existing_key] = _merge_items(winner, loser)
            if title_key:
                title_keys[title_key] = existing_key
            continue
        if key in by_key:
            winner = _prefer_item(by_key[key], item)
            loser = item if winner is by_key[key] else by_key[key]
            by_key[key] = _merge_items(winner, loser)
            continue
        by_key[key] = item
        if title_key:
            title_keys[title_key] = key
    return list(by_key.values())


def rank_ai_updates(
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    min_official_count: int = 6,
    allow_social_backfill: bool = True,
) -> list[AIUpdateItem]:
    target = max(1, int(target_count or 10))
    deduped = _dedupe_updates(items)
    official_like = [item for item in deduped if item.source_type in {"official", "github"}]
    social_like = [item for item in deduped if item.source_type in {"social", "search"}]

    def sort_key(item: AIUpdateItem):
        source_priority = {"official": 4, "github": 3, "search": 2, "social": 1}
        return (
            source_priority.get(item.source_type, 0),
            item.confidence_score,
            item.timestamp_sort_key,
        )

    official_like = sorted(official_like, key=sort_key, reverse=True)
    social_like = sorted(social_like, key=sort_key, reverse=True)

    if len(official_like) >= min_official_count:
        return official_like[:target]

    if not allow_social_backfill:
        return official_like[:target]

    return [*official_like, *social_like][:target]
