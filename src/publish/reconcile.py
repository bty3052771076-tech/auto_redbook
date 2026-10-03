"""Classify read-only platform observations without performing a write."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicationObservation:
    status: str
    next_action: str
    reasons: tuple[str, ...] = ()
    platform_id: str = ""
    title: str = ""
    body: str = ""
    image_count: int = 0
    observed_visibility: str = "unknown"


def classify_publication_observation(
    observation: dict[str, Any], *, requested_visibility: str
) -> PublicationObservation:
    requested = str(requested_visibility or "unknown").strip().lower()
    observed = str(observation.get("observed_visibility") or "unknown").strip().lower()
    stage = str(observation.get("stage") or "").strip().lower()
    error_text = str(observation.get("error") or "").strip().lower()
    reasons: list[str] = []
    if not observation.get("platform_id"):
        reasons.append("platform_id_not_confirmed")
    if observed == "unknown":
        reasons.append("visibility_not_confirmed")
    restriction_markers = (
        "平台限制",
        "platform_restricted",
        "risk_blocked",
        "疑似使用第三方工具",
        "利用ai托管",
    )
    if stage in {"platform_restricted", "risk_blocked"} or any(
        marker in error_text for marker in restriction_markers
    ):
        return PublicationObservation(
            "platform_restricted",
            "platform_review",
            tuple(dict.fromkeys(reasons + ["platform_restricted"])),
            str(observation.get("platform_id") or ""),
            str(observation.get("title") or ""),
            str(observation.get("body") or ""),
            int(observation.get("image_count") or 0),
            observed,
        )
    if stage in {"pending_review", "reviewing", "审核中"}:
        return PublicationObservation("pending_review", "wait_or_reconcile", tuple(reasons), str(observation.get("platform_id") or ""), str(observation.get("title") or ""), str(observation.get("body") or ""), int(observation.get("image_count") or 0), observed)
    if stage in {"rejected", "failed"}:
        return PublicationObservation("failed_definite", "manual_review", tuple(reasons + ["platform_rejected"]), str(observation.get("platform_id") or ""), str(observation.get("title") or ""), str(observation.get("body") or ""), int(observation.get("image_count") or 0), observed)
    if observed != requested:
        return PublicationObservation("uncertain", "manual_review", tuple(dict.fromkeys(reasons + ["visibility_not_confirmed"])), str(observation.get("platform_id") or ""), str(observation.get("title") or ""), str(observation.get("body") or ""), int(observation.get("image_count") or 0), observed)
    if str(observation.get("evidence_level") or "").lower() != "detail":
        reasons.append("detail_evidence_required")
    if not str(observation.get("body") or "").strip():
        reasons.append("body_not_read_back")
    if reasons:
        return PublicationObservation("uncertain", "manual_review", tuple(dict.fromkeys(reasons)), str(observation.get("platform_id") or ""), str(observation.get("title") or ""), str(observation.get("body") or ""), int(observation.get("image_count") or 0), observed)
    return PublicationObservation("published", "none", (), str(observation.get("platform_id") or ""), str(observation.get("title") or ""), str(observation.get("body") or ""), int(observation.get("image_count") or 0), observed)
