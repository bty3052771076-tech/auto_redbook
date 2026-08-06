from __future__ import annotations

import json
import math
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


FREE_PROVIDERS = ("aliyun", "volcengine")
DEFAULT_QUOTA_MAX_AGE = timedelta(hours=2)

_PROVIDER_ORDER = {"volcengine": 0, "aliyun": 1}
_TEXT_MODEL_PREFERENCE = (
    "glm-5.2",
    "deepseek-v4-flash",
    "doubao-seed-2-1-pro-260628",
    "doubao-seed-2-1-turbo-260628",
    "qwen3.7-max",
    "qwen3.7-plus",
)
_UNSUPPORTED_LLM_MARKERS = (
    "embedding",
    "rerank",
    "moderation",
    "speech",
    "tts",
)
_VISION_MODEL_MARKERS = (
    "vision",
    "-vl",
    "vl-",
    "omni",
    "ui-tars",
)
_VISION_MODEL_PREFERENCE = (
    "doubao-seed-1-6-251015",
    "doubao-seed-1-6-vision",
    "doubao-1-5-vision-pro-32k",
    "doubao-1-5-vision-lite",
    "qwen3.5-ocr",
)
_VISION_MODEL_EXACT = {
    "doubao-seed-1-6-251015",
    "qwen3.5-ocr",
}
# Ark may expose this legacy display label in the quota table even though the
# OpenAI-compatible endpoint currently returns 404 for it.
_UNCALLABLE_VISION_DISPLAY_ALIASES = {
    "doubao-seed-1-6-vision",
    "doubao-1-5-vision-lite",
    "doubao-1-5-vision-pro-32k",
}


class FreeQuotaUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuotaSnapshot:
    provider: str
    path: Path
    captured_at: datetime
    age: timedelta
    fresh: bool
    payload: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class QuotaModelRecord:
    provider: str
    model: str
    kind: str
    status: str
    remaining: float
    total: float | None
    unit: str
    expires_at: datetime | None
    snapshot_path: Path
    captured_at: datetime

    @property
    def remaining_ratio(self) -> float:
        if self.total is None or self.total <= 0:
            return 0.0
        return max(0.0, self.remaining / self.total)


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    kind: str
    remaining: float
    total: float | None
    unit: str
    snapshot_path: Path
    captured_at: datetime

    @classmethod
    def from_record(cls, record: QuotaModelRecord) -> "ModelChoice":
        return cls(
            provider=record.provider,
            model=record.model,
            kind=record.kind,
            remaining=record.remaining,
            total=record.total,
            unit=record.unit,
            snapshot_path=record.snapshot_path,
            captured_at=record.captured_at,
        )


@dataclass(frozen=True)
class FreeModelPlan:
    llm: ModelChoice
    image: ModelChoice | None
    vision: ModelChoice | None
    rejected: tuple[str, ...] = ()

    def environment(self) -> dict[str, str]:
        values = {
            "LLM_PROVIDER": self.llm.provider,
            "ALLOW_PAID_LLM_FALLBACK": "0",
        }
        if self.llm.provider == "aliyun":
            values["ALIYUN_LLM_MODEL"] = self.llm.model
            values["ALIYUN_LLM_MODELS"] = self.llm.model
        elif self.llm.provider == "volcengine":
            values["VOLCENGINE_LLM_MODEL"] = self.llm.model
            values["VOLCENGINE_LLM_MODELS"] = self.llm.model
        if self.image is not None:
            values["IMAGE_PROVIDER"] = self.image.provider
            if self.image.provider == "aliyun":
                values["ALIYUN_IMAGE_MODEL"] = self.image.model
                values["ALIYUN_IMAGE_MODELS"] = self.image.model
            elif self.image.provider == "volcengine":
                values["VOLCENGINE_IMAGE_MODEL"] = self.image.model
                values["VOLCENGINE_IMAGE_MODELS"] = self.image.model
        if self.vision is not None:
            values["VLM_REVIEW_PROVIDER"] = self.vision.provider
            values["VLM_REVIEW_MODEL"] = self.vision.model
        return values


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "none", "null", "-"}:
        return None
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return _as_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _parse_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"unknown", "none", "null", "-", "n/a"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return number if math.isfinite(number) else None


def _snapshot_captured_at(path: Path, payload: Mapping[str, Any]) -> datetime:
    for key in ("captured_at", "collected_at", "created_at", "timestamp"):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def load_latest_quota_snapshot(
    provider: str,
    *,
    quota_dir: Path | str = Path("data") / "quota",
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_QUOTA_MAX_AGE,
) -> QuotaSnapshot | None:
    root = Path(quota_dir)
    provider_name = (provider or "").strip().lower()
    current = _as_utc(now or datetime.now(timezone.utc))
    candidates = sorted(
        root.glob(f"{provider_name}_quota_*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("records"), list)
            or not payload.get("records")
        ):
            continue
        captured_at = _snapshot_captured_at(path, payload)
        age = max(timedelta(0), current - captured_at)
        return QuotaSnapshot(
            provider=provider_name,
            path=path,
            captured_at=captured_at,
            age=age,
            fresh=age <= max_age,
            payload=payload,
        )
    return None


def _normalized_kind(model: str, raw_kind: object) -> str:
    kind = str(raw_kind or "").strip().lower()
    model_lower = model.lower()
    if kind == "llm":
        if any(marker in model_lower for marker in _UNSUPPORTED_LLM_MARKERS):
            return "unsupported"
        return "llm"
    if kind == "image":
        return "image"
    return "unsupported"


def _record_rejection_reason(
    *,
    provider: str,
    model: str,
    reason: str,
) -> str:
    return f"{provider}/{model}: {reason}"


def load_quota_records(
    *,
    quota_dir: Path | str = Path("data") / "quota",
    providers: Iterable[str] = FREE_PROVIDERS,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_QUOTA_MAX_AGE,
    provider_keys: Mapping[str, bool] | None = None,
    allow_stale: bool = False,
) -> tuple[list[QuotaModelRecord], list[str]]:
    current = _as_utc(now or datetime.now(timezone.utc))
    accepted: list[QuotaModelRecord] = []
    rejected: list[str] = []
    key_states = {str(key).lower(): bool(value) for key, value in (provider_keys or {}).items()}

    for raw_provider in providers:
        provider = str(raw_provider or "").strip().lower()
        if provider not in FREE_PROVIDERS:
            rejected.append(f"{provider or 'unknown'}: unsupported free provider")
            continue
        if provider_keys is not None and not key_states.get(provider, False):
            rejected.append(f"{provider}: API key is not configured")
            continue
        snapshot = load_latest_quota_snapshot(
            provider,
            quota_dir=quota_dir,
            now=current,
            max_age=max_age,
        )
        if snapshot is None:
            rejected.append(f"{provider}: no valid quota snapshot")
            continue
        if not snapshot.fresh and not allow_stale:
            rejected.append(
                f"{provider}: quota snapshot is stale "
                f"({snapshot.age.total_seconds() / 3600:.1f}h > {max_age.total_seconds() / 3600:.1f}h)"
            )
            continue
        for raw in snapshot.payload.get("records") or []:
            if not isinstance(raw, Mapping):
                continue
            model = str(raw.get("model") or "").strip()
            if not model:
                continue
            status = str(raw.get("status") or "unknown").strip().lower()
            if status != "available":
                rejected.append(
                    _record_rejection_reason(
                        provider=provider,
                        model=model,
                        reason=f"status={status or 'unknown'}",
                    )
                )
                continue
            remaining = _parse_number(raw.get("remaining"))
            if remaining is None or remaining <= 0:
                rejected.append(
                    _record_rejection_reason(
                        provider=provider,
                        model=model,
                        reason="remaining quota is unknown or zero",
                    )
                )
                continue
            expires_at = _parse_datetime(raw.get("expires_at"))
            if expires_at is not None and expires_at < current:
                rejected.append(
                    _record_rejection_reason(
                        provider=provider,
                        model=model,
                        reason=f"expired at {expires_at.isoformat()}",
                    )
                )
                continue
            kind = _normalized_kind(model, raw.get("kind"))
            if kind == "unsupported":
                rejected.append(
                    _record_rejection_reason(
                        provider=provider,
                        model=model,
                        reason=f"unsupported task kind={str(raw.get('kind') or 'unknown').lower()}",
                    )
                )
                continue
            accepted.append(
                QuotaModelRecord(
                    provider=provider,
                    model=model,
                    kind=kind,
                    status=status,
                    remaining=remaining,
                    total=_parse_number(raw.get("total")),
                    unit=str(raw.get("unit") or "").strip(),
                    expires_at=expires_at,
                    snapshot_path=snapshot.path,
                    captured_at=snapshot.captured_at,
                )
            )
    return accepted, rejected


def model_supports_vision(model: str) -> bool:
    value = (model or "").strip().lower()
    if any(marker in value for marker in _UNSUPPORTED_LLM_MARKERS):
        return False
    return value in _VISION_MODEL_EXACT or any(marker in value for marker in _VISION_MODEL_MARKERS)


def _explicit_rank(model: str, explicit_model: str) -> int:
    explicit = (explicit_model or "").strip().lower()
    return 0 if explicit and model.lower() == explicit else 1


def _preference_rank(model: str) -> int:
    value = model.lower()
    for index, preferred in enumerate(_TEXT_MODEL_PREFERENCE):
        if value == preferred or value.startswith(f"{preferred}-"):
            return index
    return len(_TEXT_MODEL_PREFERENCE)


def _vision_preference_rank(model: str) -> int:
    value = model.lower()
    for index, preferred in enumerate(_VISION_MODEL_PREFERENCE):
        if value == preferred or value.startswith(f"{preferred}-"):
            return index
    return len(_VISION_MODEL_PREFERENCE)


def _choose_llm(
    records: Iterable[QuotaModelRecord],
    *,
    explicit_model: str = "",
) -> QuotaModelRecord | None:
    candidates = [record for record in records if record.kind == "llm" and not model_supports_vision(record.model)]
    if explicit_model:
        exact = [record for record in records if record.kind == "llm" and record.model.lower() == explicit_model.lower()]
        if exact:
            candidates = exact
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda record: (
            _explicit_rank(record.model, explicit_model),
            _preference_rank(record.model),
            -record.remaining_ratio,
            -record.remaining,
            _PROVIDER_ORDER.get(record.provider, 99),
            record.model.lower(),
        ),
    )


def _choose_image(
    records: Iterable[QuotaModelRecord],
    *,
    explicit_model: str = "",
) -> QuotaModelRecord | None:
    candidates = [record for record in records if record.kind == "image"]
    if explicit_model:
        exact = [record for record in candidates if record.model.lower() == explicit_model.lower()]
        if exact:
            candidates = exact
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda record: (
            _explicit_rank(record.model, explicit_model),
            -record.remaining,
            -record.remaining_ratio,
            _PROVIDER_ORDER.get(record.provider, 99),
            record.model.lower(),
        ),
    )


def _choose_vision(records: Iterable[QuotaModelRecord]) -> QuotaModelRecord | None:
    candidates = [
        record
        for record in records
        if (
            record.kind == "llm"
            and model_supports_vision(record.model)
            and record.model.strip().lower() not in _UNCALLABLE_VISION_DISPLAY_ALIASES
        )
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda record: (
            _vision_preference_rank(record.model),
            -record.remaining_ratio,
            -record.remaining,
            _PROVIDER_ORDER.get(record.provider, 99),
            record.model.lower(),
        ),
    )


def build_free_model_plan(
    records: Iterable[QuotaModelRecord],
    *,
    explicit_llm_model: str = "",
    explicit_image_model: str = "",
    require_image: bool = True,
    rejected: Iterable[str] = (),
    allow_paid_fallback: bool = False,
) -> FreeModelPlan:
    items = list(records)
    rejected_items = tuple(str(reason) for reason in rejected)
    if explicit_llm_model and not any(
        record.kind == "llm" and record.model.lower() == explicit_llm_model.lower()
        for record in items
    ):
        raise FreeQuotaUnavailableError(
            f"指定的 LLM 模型 {explicit_llm_model} 没有可信的正数免费额度，"
            "不会静默切换到其他模型或 PPInfra。"
        )
    llm = _choose_llm(items, explicit_model=explicit_llm_model)
    if llm is None:
        paid_hint = (
            "已允许付费兜底，但调用方仍需显式提供付费模型。"
            if allow_paid_fallback
            else "不会自动调用 PPInfra；如确需付费模型，必须显式指定并确认。"
        )
        raise FreeQuotaUnavailableError(
            f"没有可信的免费 LLM 额度，已在模型调用前停止。{paid_hint}"
        )
    if require_image and explicit_image_model and not any(
        record.kind == "image" and record.model.lower() == explicit_image_model.lower()
        for record in items
    ):
        raise FreeQuotaUnavailableError(
            f"指定的生图模型 {explicit_image_model} 没有可信的正数免费额度，"
            "不会静默切换到付费生图服务。"
        )
    image = _choose_image(items, explicit_model=explicit_image_model)
    if require_image and image is None:
        raise FreeQuotaUnavailableError(
            "没有可信的免费生图额度，已在生图前停止。"
            "不会自动调用付费生图服务；如确需付费模型，必须显式指定并确认。"
        )
    vision = _choose_vision(items)
    return FreeModelPlan(
        llm=ModelChoice.from_record(llm),
        image=ModelChoice.from_record(image) if image is not None else None,
        vision=ModelChoice.from_record(vision) if vision is not None else None,
        rejected=rejected_items,
    )


@contextmanager
def temporary_environment(values: Mapping[str, object]) -> Iterator[None]:
    previous: dict[str, str | None] = {}
    try:
        for raw_key, raw_value in values.items():
            key = str(raw_key)
            previous[key] = os.environ.get(key)
            if raw_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(raw_value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
