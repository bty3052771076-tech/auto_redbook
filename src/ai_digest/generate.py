from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

from .models import AIDigestBrief, AIUpdateItem


def _today_date() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def build_ai_digest_prompt(items: Iterable[AIUpdateItem], *, target_count: int = 10) -> str:
    rows = []
    for idx, item in enumerate(items, 1):
        rows.append(
            {
                "index": idx,
                "title": item.title,
                "summary": item.summary,
                "source_name": item.source_name,
                "source_type": item.source_type,
                "vendor": item.vendor,
                "product": item.product,
                "published_at": item.published_at,
                "url": item.url,
                "evidence_urls": item.evidence_urls,
                "verification_status": item.verification_status,
                "raw_excerpt": item.raw_excerpt[:800],
            }
        )
    return (
        "你正在为小红书图文笔记制作《每日AI讯息》。\n"
        f"目标：从候选中挑选约 {target_count} 条 AI 平台、模型、工具、开源项目动态。\n"
        "要求：官方源优先；社交源只能用于补充或验证；不得编造未提供的信息；全部输出中文。\n"
        "请返回严格 JSON，字段为 title, subtitle, date, items, source_summary。\n"
        "items 每项字段：title, summary, source_name, source_type, url, published_at, vendor, product, raw_excerpt, evidence_urls, tags。\n"
        "summary 控制在 50-90 字，说明更新内容和对用户/开发者的意义。\n"
        "候选数据：\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
    )


def _extract_json_object(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


def parse_ai_digest_brief_json(text: str) -> AIDigestBrief:
    data = json.loads(_extract_json_object(text))
    items = [AIUpdateItem.model_validate(item) for item in data.get("items", []) if isinstance(item, dict)]
    for idx, item in enumerate(items):
        if item.source_type in {"official", "github"} and item.evidence_urls and item.verification_status == "official_only":
            item_data = item.model_dump()
            item_data["verification_status"] = "social_confirmed"
            items[idx] = AIUpdateItem.model_validate(item_data)
    data["items"] = items
    return AIDigestBrief.model_validate(data)


def build_fallback_brief(
    items: list[AIUpdateItem],
    *,
    target_count: int = 10,
    date: str = "",
) -> AIDigestBrief:
    selected = items[: max(1, int(target_count or 10))]
    vendors = Counter(item.vendor or item.source_name or "unknown" for item in selected)
    source_summary = "、".join(name for name, _count in vendors.most_common(6))
    if source_summary:
        source_summary = f"主要来源：{source_summary}。"
    return AIDigestBrief(
        title="每日AI讯息",
        subtitle="AI平台、模型、工具和开源动态简报",
        date=date or _today_date(),
        items=selected,
        source_summary=source_summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def render_ai_digest_body(brief: AIDigestBrief) -> str:
    sources = []
    for item in brief.items:
        name = item.source_name or item.vendor
        if name and name not in sources:
            sources.append(name)
    source_text = " / ".join(sources[:8]) or "官方公开渠道"
    lines = [
        "每日AI讯息",
        "",
        f"整理了 {len(brief.items)} 条 AI 平台、模型、工具和开源动态，适合快速了解今天的 AI 变化。",
        "",
        f"发布时间：{brief.date}",
        f"来源：{source_text}",
    ]
    return "\n".join(lines)
