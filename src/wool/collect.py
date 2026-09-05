from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Callable

from src.ai_digest.collect import collect_ai_digest_updates
from src.ai_digest.models import AIUpdateItem
from src.ai_digest.rank import filter_recent_ai_updates

from .models import WoolOffer
from .sources import resolve_wool_sources


BEIJING_TZ = timezone(timedelta(hours=8))
WOOL_SEARCH_QUERIES = [
    "AI 免费额度 领取 重置 试用 福利",
    "ZCode GLM 额度 领取",
    "Codex credits reset free quota",
    "AI model free credits promotion claim",
]
_BENEFIT_MARKERS = (
    "免费额度",
    "免费使用",
    "可领取",
    "领取",
    "领取额度",
    "额度重置",
    "重置额度",
    "赠送额度",
    "免费试用",
    "福利",
    "credits",
    "free quota",
    "reset",
    "bonus",
    "trial",
    "claim",
    "giveaway",
    "promotion",
    "weekend",
)
_LIFECYCLE_ONLY_MARKERS = (
    "下线",
    "下架",
    "停用",
    "弃用",
    "升级通知",
    "维护通知",
    "deprecat",
    "sunset",
    "migration notice",
    "upgrade notice",
)
_PROVIDER_MARKERS = (
    "OpenAI",
    "Codex",
    "ZCode",
    "智谱",
    "GLM",
    "DeepSeek",
    "Qwen",
    "通义",
    "豆包",
    "Doubao",
    "Kimi",
    "MiniMax",
    "Claude",
    "Gemini",
    "Anthropic",
    "火山",
    "阿里云",
)

_BENEFIT_AMOUNT_RE = re.compile(
    r"(?i)(?<![a-z0-9])\d[\d,.]*\s*(?:亿|万|k|m|b|million|billion)?\s*"
    r"(?:token(?:s)?|令牌|积分|点数|额度)(?![a-z0-9])"
)
_BENEFIT_ACTION_MARKERS = (
    "领取",
    "免费",
    "赠送",
    "重置",
    "免费试用",
    "claim",
    "free",
    "bonus",
    "reset",
    "trial",
    "giveaway",
)
_BENEFIT_DETAIL_MARKERS = (
    "额度",
    "token",
    "credit",
    "quota",
    "试用",
    "plan",
    "有效期",
    "截止",
    "expires",
    "valid",
    "weekend",
)


def _has_concrete_reset_benefit(text: str) -> bool:
    lowered = (text or "").lower()
    english_signal = (
        "banked reset" in lowered
        and "credit" in lowered
        and any(marker in lowered for marker in ("redeem", "apply", "paid chatgpt", "eligible"))
    )
    chinese_signal = (
        "银行重置" in lowered
        and "符合条件" in lowered
        and any(marker in lowered for marker in ("账户", "自行使用", "到账"))
    )
    return english_signal or chinese_signal


def _normalized_benefit_amounts(text: str) -> tuple[str, ...]:
    values: set[str] = set()
    for match in re.finditer(
        r"(?i)(?<![a-z0-9])(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>亿|万|billion|million|b|m|k)",
        text or "",
    ):
        number = float(match.group("number"))
        unit = match.group("unit").lower()
        factor = {
            "亿": 100_000_000,
            "万": 10_000,
            "billion": 1_000_000_000,
            "million": 1_000_000,
            "b": 1_000_000_000,
            "m": 1_000_000,
            "k": 1_000,
        }[unit]
        values.add(str(int(number * factor)))
    return tuple(sorted(values))


_ENGLISH_MONTH_NUMBERS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _normalized_benefit_dates(item: AIUpdateItem, text: str) -> tuple[str, ...]:
    published = _published_datetime(item.published_at)
    year = published.year if published is not None else datetime.now(BEIJING_TZ).year
    values: set[str] = set()
    for month, day in re.findall(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text or ""):
        try:
            values.add(f"{year:04d}-{int(month):02d}-{int(day):02d}")
        except ValueError:
            continue
    for month, day in re.findall(
        r"(?i)\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})\b",
        text or "",
    ):
        month_number = _ENGLISH_MONTH_NUMBERS.get(month.lower())
        if month_number is not None:
            values.add(f"{year:04d}-{month_number:02d}-{int(day):02d}")
    if values:
        return tuple(sorted(values))
    if published is not None:
        return (published.date().isoformat(),)
    return ()


def _has_concrete_benefit_evidence(text: str) -> bool:
    """Reject generic product news unless it carries a usable benefit fact."""
    lowered = (text or "").lower()
    has_action = any(_contains_marker(lowered, marker) for marker in _BENEFIT_ACTION_MARKERS)
    has_detail = any(_contains_marker(lowered, marker) for marker in _BENEFIT_DETAIL_MARKERS)
    has_amount = bool(_BENEFIT_AMOUNT_RE.search(lowered))
    has_window = any(marker in lowered for marker in ("截止", "有效期", "expires", "valid until", "本周", "周末"))
    if _has_concrete_reset_benefit(lowered):
        return True
    return has_action and has_detail and (
        has_amount
        or has_window
        or "免费额度" in lowered
        or "free quota" in lowered
    )


def _evidence_tag(source_type: str) -> str:
    return {
        "official": "evidence:official",
        "github": "evidence:official-repository",
        "social": "evidence:official-social",
        "aggregator": "evidence:trusted-aggregator",
        "search": "evidence:search-lead",
    }.get(source_type, "evidence:unclassified")


def _text(item: AIUpdateItem) -> str:
    return " ".join(
        part.strip()
        for part in (item.title, item.summary, item.product, item.raw_excerpt)
        if part and part.strip()
    )


def _contains_marker(text: str, marker: str) -> bool:
    lowered = text.lower()
    needle = marker.lower()
    if any("\u4e00" <= char <= "\u9fff" for char in needle) or " " in needle:
        return needle in lowered
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered))


def _first_marker(text: str, markers: tuple[str, ...]) -> str:
    return next((marker for marker in markers if _contains_marker(text, marker)), "")


def _provider(item: AIUpdateItem) -> str:
    blob = _text(item)
    for marker in _PROVIDER_MARKERS:
        if _contains_marker(blob, marker):
            return marker
    return (item.vendor or item.source_name or "AI厂商").strip()


def _published_datetime(value: str, *, now: datetime | date | None = None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
        if not match:
            return None
        parsed = datetime(*(int(value) for value in match.groups()))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def _event_key(item: AIUpdateItem, benefit_marker: str) -> str:
    provider = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _provider(item).lower())
    text = _text(item).lower()
    amounts = _normalized_benefit_amounts(text)
    models = tuple(
        sorted(
            set(
                re.findall(
                    r"(?i)(?:glm|gpt|qwen|deepseek|codex|claude|gemini|h3)[a-z0-9._-]{0,32}",
                    text,
                )
            )
        )
    )
    date_tokens = _normalized_benefit_dates(item, text)
    if amounts:
        # Mirror articles often use different wording (3B vs 3亿). Use the
        # normalized benefit facts instead of the headline to deduplicate them.
        return f"{provider}|{','.join(models)}|{','.join(amounts)}|{','.join(date_tokens)}"
    title = re.sub(r"通知|公告|活动|消息|官方|登录|用户|可获得|领取", "", item.title.lower())
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title)
    summary = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", item.summary.lower())
    # Prefer a compact event identity over URL identity: mirrors of one offer
    # should produce one card while distinct offers from one vendor survive.
    return f"{provider}|{title}|{benefit_marker.lower()}|{summary[:80]}"


def extract_wool_offers(
    items: Iterable[AIUpdateItem],
    *,
    now: datetime | date | None = None,
    max_age_days: int = 3,
) -> list[WoolOffer]:
    """Extract only concrete and traceable AI benefit notices."""
    current = now or datetime.now(BEIJING_TZ)
    recent = filter_recent_ai_updates(
        list(items or []),
        max_age_days=max(1, int(max_age_days or 3)),
        now=current if isinstance(current, datetime) else None,
        require_url=True,
    )
    deduped: dict[str, WoolOffer] = {}
    source_priority = {"official": 4, "github": 4, "social": 3, "aggregator": 2, "search": 1}
    for item in recent:
        text = _text(item)
        benefit_marker = _first_marker(text, _BENEFIT_MARKERS)
        if not benefit_marker:
            continue
        if not _has_concrete_benefit_evidence(text):
            continue
        if _first_marker(text, _LIFECYCLE_ONLY_MARKERS) and not any(
            marker in text.lower() for marker in ("领取", "免费额度", "额度重置", "free quota", "claim", "reset")
        ):
            continue
        published = _published_datetime(item.published_at, now=current)
        if published is None or not item.url.strip():
            continue
        provider = _provider(item)
        confidence = min(
            0.99,
            float(item.confidence_score or 0.0)
            + {"official": 0.08, "github": 0.06, "social": 0.03}.get(item.source_type, 0.0),
        )
        offer = WoolOffer(
            title=item.title,
            provider=provider,
            benefit=f"{provider}：{item.summary or item.title}",
            claim_steps=item.raw_excerpt or item.summary,
            source_name=item.source_name,
            source_type=item.source_type,
            url=item.url,
            published_at=published.isoformat(),
            confidence_score=confidence,
            tags=["AI羊毛", benefit_marker, _evidence_tag(item.source_type)],
        )
        key = _event_key(item, benefit_marker)
        previous = deduped.get(key)
        if previous is None or (
            source_priority.get(offer.source_type, 0), offer.confidence_score, offer.published_at
        ) > (
            source_priority.get(previous.source_type, 0), previous.confidence_score, previous.published_at
        ):
            deduped[key] = offer
    return sorted(
        deduped.values(),
        key=lambda offer: (offer.published_at, offer.confidence_score),
        reverse=True,
    )


WoolProgress = Callable[[str, str], None]


def collect_daily_wool_offers(
    *,
    now: datetime | date | None = None,
    max_age_days: int = 3,
    sources=None,
    fetch_source=None,
    progress: WoolProgress | None = None,
    performance_mode: str | None = None,
) -> tuple[list[WoolOffer], dict[str, Any]]:
    if progress:
        progress("collect", f"in_progress window={max_age_days}d")
    updates, meta = collect_ai_digest_updates(
        sources=sources or resolve_wool_sources(),
        fetch_source=fetch_source,
        target_count=30,
        min_official_count=0,
        allow_social_backfill=True,
        max_age_days=max_age_days,
        now=now,
        include_pool_items=True,
        force_search_backfill=True,
        # Wool signals are often short-lived announcements on official social
        # accounts. A full generic candidate pool must not suppress this tier.
        force_social_backfill=True,
        search_backfill_queries=WOOL_SEARCH_QUERIES,
        performance_mode=performance_mode,
        progress=(lambda stage, detail: progress(stage, detail)) if progress else None,
    )
    offers = extract_wool_offers(updates, now=now, max_age_days=max_age_days)
    result_meta = {
        "candidate_updates": len(updates),
        "offers": len(offers),
        "max_age_days": max_age_days,
        "source_meta": meta,
    }
    if progress:
        progress("collect", f"success candidates={len(updates)} offers={len(offers)}")
    return offers, result_meta
