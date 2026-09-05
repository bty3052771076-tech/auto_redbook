from __future__ import annotations

from datetime import date, datetime
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable

from src.config import load_llm_configs
from src.llm.generate import generate_json
from src.storage.files import copy_assets_into_post, post_dir, save_post, save_revision
from src.storage.models import AssetInfo, Post, PostStatus, Revision, RevisionSource, now_iso
from src.text_integrity import repair_utf8_as_gbk_mojibake

from .collect import collect_daily_wool_offers
from .models import WoolOffer
from .render import ensure_wool_assets


WoolProgress = Callable[[str, str], None]


def _asset_info(path: Path) -> AssetInfo:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return AssetInfo(
        path=str(path),
        kind="image",
        size_bytes=path.stat().st_size,
        sha256=digest,
        validated=True,
    )


def _source_evidence_label(source_type: str) -> str:
    return {
        "official": "官方页面",
        "github": "官方代码仓库",
        "social": "官方社交账号",
        "aggregator": "可信聚合源（二手线索，以官方活动页面或客户端显示为准）",
        "search": "搜索线索（需以官方页面或客户端显示为准）",
    }.get(source_type, "待确认来源")


def _claim_details(offer: WoolOffer) -> str:
    text = " ".join(part.strip() for part in (offer.claim_steps, offer.benefit) if part and part.strip())
    lower = text.lower()
    compact = re.sub(r"\s+", "", lower)
    if "zcode" in compact and ("3亿" in compact or "300m" in compact) and "glm-5.3" in compact:
        return "登录 ZCode 客户端，按活动页面规则领取；具体资格和截止时间以客户端显示为准。"
    pieces = [part.strip() for part in re.split(r"(?<=[。！？.!?；;])\s+|\n+", text) if part.strip()]
    useful = [
        part
        for part in pieces
        if re.search(r"(?i)(领取|免费|赠送|额度|token|credit|quota|截止|有效期|expires|valid|weekend|登录)", part)
    ]
    unique: list[str] = []
    for part in useful:
        clean = re.sub(r"\s+", " ", part).strip(" -:：")
        if clean and clean not in unique:
            unique.append(clean)
    return " ".join(unique[:3])[:220] or "以活动页面或客户端显示的领取规则为准。"


def _deterministic_copy(offers: list[WoolOffer], *, max_age_days: int) -> tuple[str, str]:
    if not offers:
        return (
            "每日羊毛|今日暂无可核验福利",
            f"截至今日，暂未发现生成日前{max_age_days}日内可核验的AI厂商免费额度、领取、试用或重置活动。\n"
            "本期不编造福利，后续如官方发布新的活动将按来源和发布时间重新核验。",
        )
    lines = ["今日发现以下可核验的AI福利："]
    for index, offer in enumerate(offers, 1):
        lines.extend(
            [
                f"{index}. {offer.provider}：{offer.title}",
                f"发布时间：{offer.published_at}",
                f"核验级别：{_source_evidence_label(offer.source_type)}",
                f"领取说明：{_claim_details(offer)}",
                f"来源：{offer.url}",
            ]
        )
    return "每日羊毛|今日有AI福利", "\n".join(lines)


def _llm_copy(offers: list[WoolOffer], fallback: tuple[str, str]) -> tuple[str, str, str]:
    # A benefit post is a fact ledger. Keep critical amounts, dates and claim
    # conditions deterministic unless the operator explicitly opts in.
    if (os.getenv("WOOL_LLM_COPY") or "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return fallback[0], fallback[1], "deterministic_fact_first"
    try:
        configs = load_llm_configs()
        if not configs or any((getattr(cfg, "provider", "") or "").lower() == "ppinfra" for cfg in configs):
            return fallback[0], fallback[1], "deterministic_free_first"
        payload = [offer.model_dump() for offer in offers]
        data = generate_json(
            configs,
            system_prompt=(
                "你是中文事实编辑。只根据输入的已核验事实写作，不得新增福利、日期、金额或领取条件。"
                "输出 JSON，字段仅包含 title 和 body；使用简体中文。"
            ),
            user_prompt=(
                "请把以下 AI 福利整理成一条小红书草稿。标题必须以‘每日羊毛|’开头，正文逐条保留提供的来源 URL、"
                "发布时间和领取说明；没有证据的内容不要写。\n事实：" + str(payload)
            ),
            max_tokens=3000,
        )
        title = repair_utf8_as_gbk_mojibake(str(data.get("title") or "")).strip()
        body = repair_utf8_as_gbk_mojibake(str(data.get("body") or "")).strip()
        if not title.startswith("每日羊毛|") or not body or not all(offer.url in body for offer in offers):
            return fallback[0], fallback[1], "deterministic_validation_fallback"
        return title, body, "llm"
    except Exception as exc:
        print(f"[daily-wool] llm_copy_failed error={exc}")
        return fallback[0], fallback[1], "deterministic_llm_error_fallback"


def create_daily_wool_posts(
    *,
    asset_paths: list[Path] | None = None,
    copy_assets: bool = True,
    count: int = 1,
    lookback_days: object = None,
    now: datetime | date | None = None,
    progress: WoolProgress | None = None,
    performance_mode: str | None = None,
) -> list[Post]:
    """Create one Daily Wool draft; the publisher is intentionally one post."""
    del asset_paths
    del count
    try:
        max_age_days = max(1, int(lookback_days)) if lookback_days not in (None, "") else 3
    except (TypeError, ValueError):
        max_age_days = 3
    if progress:
        progress("collect", f"in_progress window={max_age_days}d")
    offers, collect_meta = collect_daily_wool_offers(
        now=now,
        max_age_days=max_age_days,
        progress=progress,
        performance_mode=performance_mode,
    )
    if progress:
        progress("collect", f"success offers={len(offers)}")
    fallback_title, fallback_body = _deterministic_copy(offers, max_age_days=max_age_days)
    title, body, generation_mode = _llm_copy(offers, (fallback_title, fallback_body))
    image_sources = ensure_wool_assets()
    selected = image_sources["with_wool" if offers else "without_wool"]
    post = Post(
        type="image",
        status=PostStatus.draft,
        title=title,
        body=body,
        topics=["每日羊毛", "AI福利"],
        platform={
            "daily_wool": {
                "mode": "daily_wool",
                "has_wool": bool(offers),
                "offer_count": len(offers),
                "max_age_days": max_age_days,
                "generation_mode": generation_mode,
                "offers": [offer.model_dump() for offer in offers],
                "collection": collect_meta,
                "asset_variant": "with_wool" if offers else "without_wool",
                "generated_at": now_iso(),
            }
        },
    )
    if copy_assets:
        copied = copy_assets_into_post(post.id, [selected])
        resolved = copied or [selected]
    else:
        resolved = [selected]
    post.assets = [_asset_info(path) for path in resolved]
    revision = Revision(
        post_id=post.id,
        source=RevisionSource.llm,
        content={"title": post.title, "body": post.body, "topics": post.topics, "daily_wool": post.platform["daily_wool"]},
    )
    save_post(post)
    save_revision(revision)
    if progress:
        progress("draft", f"success post_id={post.id} has_wool={bool(offers)}")
    return [post]
