from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import DEFAULT_MINIMAX_LLM_BASE_URL, MINIMAX_IMAGE_MODELS, MINIMAX_LLM_MODELS


MINIMAX_MODELS_URL = f"{DEFAULT_MINIMAX_LLM_BASE_URL}/models"
MINIMAX_TOKEN_PLAN_REMAINS_URL = "https://www.minimaxi.com/v1/token_plan/remains"
MINIMAX_USAGE_URL = "https://platform.minimaxi.com/console/usage"
MINIMAX_BILLING_MODE = "subscription_only"
MINIMAX_POOL_ID = "token_plan_shared"


@dataclass(frozen=True)
class MiniMaxQuotaRecord:
    model: str
    kind: str = "llm"
    total: int | float | None = None
    used: int | float | None = None
    remaining: int | float | None = None
    unit: str = ""
    expires_at: str = ""
    status: str = "unknown"
    cost_class: str = "subscription_included"
    quota_pool: str = MINIMAX_POOL_ID
    raw_text: str = ""
    source_url: str = MINIMAX_TOKEN_PLAN_REMAINS_URL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split_models(value: str) -> list[str]:
    parts = re.split(r"[,\s;，；]+", (value or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = part.strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def minimax_model_candidates(
    *,
    models: Optional[Iterable[str]] = None,
    env: Optional[dict[str, str]] = None,
) -> list[str]:
    if models is not None:
        return _split_models(" ".join(str(item) for item in models))
    values = env if env is not None else os.environ
    configured = _split_models(values.get("MINIMAX_LLM_MODELS", ""))
    if configured:
        return configured
    single = (values.get("MINIMAX_LLM_MODEL") or "").strip()
    return [single] if single else list(MINIMAX_LLM_MODELS)


def _parse_kv_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return result
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        result[key.strip().lower()] = value.strip().strip("\"'")
    return result


def load_minimax_subscription_key(
    *, key_file: Path | str = Path("docs/minimax_api-key.md"),
) -> str:
    value = (os.getenv("MINIMAX_TOKEN_PLAN_API_KEY") or "").strip()
    if value:
        return value
    return (_parse_kv_file(Path(key_file)).get("api_key") or "").strip()


def _api_get_json(*, url: str, api_key: str, timeout_s: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "redbook-workflow/minimax-quota",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"MiniMax API HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"MiniMax API network error: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MiniMax API non-JSON response (status={status})") from exc
    if not isinstance(data, dict):
        raise RuntimeError("MiniMax API response is not an object")
    return data


def _iter_model_ids(payload: Any) -> Iterable[str]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, (list, dict)):
            yield from _iter_model_ids(data)
        for key in ("models", "items", "results"):
            if key in payload:
                yield from _iter_model_ids(payload[key])
        if isinstance(payload.get("id"), str):
            yield payload["id"]
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_model_ids(item)
        return
    if isinstance(payload, str) and payload.strip():
        yield payload.strip()


def _classify_model(model: str) -> str:
    value = (model or "").strip().lower()
    if not value:
        return "unknown"
    if any(marker in value for marker in ("image", "vision", "video", "speech", "tts", "audio")):
        return "image" if "image" in value else "unsupported"
    if any(marker in value for marker in ("embedding", "rerank", "moderation")):
        return "unsupported"
    return "llm"


def parse_minimax_model_ids(payload: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in _iter_model_ids(payload):
        model = str(raw).strip()
        if not model or model in seen:
            continue
        if _classify_model(model) != "llm":
            continue
        result.append(model)
        seen.add(model)
    return result


def _walk_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    parsed = float(match.group(0))
    return int(parsed) if parsed.is_integer() else parsed


def _find_number(obj: dict[str, Any], keys: tuple[str, ...]) -> int | float | None:
    lowered = {str(key).lower(): value for key, value in obj.items()}
    for key in keys:
        if key in lowered:
            parsed = _number(lowered[key])
            if parsed is not None:
                return parsed
    return None


def _percent(value: Any) -> float | None:
    parsed = _number(value)
    if parsed is None:
        return None
    return max(0.0, min(100.0, float(parsed)))


def _epoch_millis_iso(value: Any) -> str:
    parsed = _number(value)
    if parsed is None or parsed <= 0:
        return ""
    try:
        return datetime.fromtimestamp(float(parsed) / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _parse_model_remain_pool(obj: dict[str, Any]) -> dict[str, Any]:
    """Normalize MiniMax's actual 5-hour/weekly pool response.

    The endpoint exposes either request counts or percentages depending on
    the pool.  We use the smaller remaining value across the two windows and
    never convert a percentage into tokens or images.
    """
    interval_total = _number(obj.get("current_interval_total_count"))
    interval_used = _number(obj.get("current_interval_usage_count"))
    weekly_total = _number(obj.get("current_weekly_total_count"))
    weekly_used = _number(obj.get("current_weekly_usage_count"))
    count_remaining: list[float] = []
    count_totals: list[float] = []
    for total, used in ((interval_total, interval_used), (weekly_total, weekly_used)):
        if total is None or total <= 0:
            continue
        count_totals.append(float(total))
        count_remaining.append(max(0.0, float(total) - float(used or 0)))

    interval_percent = _percent(obj.get("current_interval_remaining_percent"))
    weekly_percent = _percent(obj.get("current_weekly_remaining_percent"))
    percentages = [value for value in (interval_percent, weekly_percent) if value is not None]
    if count_remaining:
        remaining: int | float = min(count_remaining)
        total: int | float | None = min(count_totals) if count_totals else None
        used: int | float | None = max(0.0, float(total) - float(remaining)) if total else None
        unit = "requests"
    elif percentages:
        remaining = min(percentages)
        total = 100
        used = max(0.0, 100.0 - float(remaining))
        unit = "percent"
    else:
        remaining = None
        total = None
        used = None
        unit = ""

    reset_candidates = [
        value
        for value in (
            _epoch_millis_iso(obj.get("end_time")),
            _epoch_millis_iso(obj.get("weekly_end_time")),
        )
        if value
    ]
    reset_at = min(reset_candidates) if reset_candidates else ""
    status = "available" if remaining is not None and remaining > 0 else "unknown"
    if remaining == 0:
        status = "exhausted"
    return {
        "model_name": str(obj.get("model_name") or "").strip(),
        "total": total,
        "used": used,
        "remaining": remaining,
        "unit": unit,
        "expires_at": reset_at,
        "reset_at": reset_at,
        "status": status,
        "interval_remaining_percent": interval_percent,
        "weekly_remaining_percent": weekly_percent,
        "raw": obj,
    }


def parse_minimax_shared_quota(
    payload: dict[str, Any],
    *,
    source_url: str = MINIMAX_TOKEN_PLAN_REMAINS_URL,
) -> dict[str, Any]:
    """Normalize only fields explicitly recognizable as usage numbers.

    The public FAQ does not define a stable JSON schema. Unknown fields stay
    unknown and are never converted into a guessed token count.
    """
    model_remains = payload.get("model_remains")
    if isinstance(model_remains, list):
        pools: dict[str, dict[str, Any]] = {}
        for item in model_remains:
            if not isinstance(item, dict):
                continue
            parsed = _parse_model_remain_pool(item)
            pool_name = parsed["model_name"] or f"pool_{len(pools) + 1}"
            pools[pool_name] = parsed
        if pools:
            primary = pools.get("general") or next(iter(pools.values()))
            return {
                **primary,
                "pools": pools,
                "source_url": source_url,
                "raw": payload,
            }

    for obj in _walk_objects(payload):
        remaining = _find_number(obj, ("remaining", "remain", "left", "available", "quota_remaining"))
        used = _find_number(obj, ("used", "consumed", "usage", "used_amount"))
        total = _find_number(obj, ("total", "limit", "quota", "quota_total", "capacity"))
        if any(value is not None for value in (remaining, used, total)):
            status = "available" if remaining is not None and remaining > 0 else "unknown"
            if remaining == 0:
                status = "exhausted"
            return {
                "total": total,
                "used": used,
                "remaining": remaining,
                "unit": str(obj.get("unit") or obj.get("quota_unit") or "").strip(),
                "expires_at": str(obj.get("expires_at") or obj.get("expire_at") or "").strip(),
                "status": status,
                "source_url": source_url,
                "raw": obj,
            }
    return {
        "total": None,
        "used": None,
        "remaining": None,
        "unit": "",
        "expires_at": "",
        "status": "unknown",
        "source_url": source_url,
        "raw": payload,
    }


def _emit(callback: Optional[Callable[[str], None]], stage: str, status: str, detail: str = "") -> None:
    if callback is None:
        return
    message = f"[minimax-quota] {stage}: {status}"
    if detail:
        message += f" | {detail}"
    try:
        callback(message)
    except Exception:
        pass


def format_minimax_quota_records(records: Iterable[MiniMaxQuotaRecord | dict[str, Any]]) -> str:
    lines = ["model | kind | billing | status | remaining | used | total | unit"]
    lines.append("--- | --- | --- | --- | ---: | ---: | ---: | ---")
    for item in records:
        data = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        lines.append(
            " | ".join(
                [
                    str(data.get("model") or ""),
                    str(data.get("kind") or "unknown"),
                    str(data.get("cost_class") or "subscription_included"),
                    str(data.get("status") or "unknown"),
                    str(data.get("remaining") if data.get("remaining") is not None else "unknown"),
                    str(data.get("used") if data.get("used") is not None else "unknown"),
                    str(data.get("total") if data.get("total") is not None else "unknown"),
                    str(data.get("unit") or ""),
                ]
            )
        )
    return "\n".join(lines)


def run_collect_minimax_quota_sync(
    *,
    models: Optional[Iterable[str]] = None,
    all_models: bool = True,
    timeout_s: float = 30.0,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Collect model catalog and shared Token Plan usage without inference."""
    api_key = load_minimax_subscription_key()
    if not api_key:
        message = (
            "MiniMax Token Plan API key missing: set MINIMAX_TOKEN_PLAN_API_KEY "
            "or create local docs/minimax_api-key.md"
        )
        _emit(progress_callback, "load_key", "failed", message)
        return {"provider": "minimax", "records": [], "errors": [message], "source_mode": "api"}

    errors: list[str] = []
    _emit(progress_callback, "list_models", "in_progress", MINIMAX_MODELS_URL)
    catalog_ids: list[str] = []
    try:
        catalog_ids = parse_minimax_model_ids(
            _api_get_json(url=MINIMAX_MODELS_URL, api_key=api_key, timeout_s=timeout_s)
        )
        _emit(progress_callback, "list_models", "success", f"models={len(catalog_ids)}")
    except Exception as exc:
        errors.append(f"model catalog failed: {exc}")
        _emit(progress_callback, "list_models", "warning", str(exc))

    requested = _split_models(" ".join(str(item) for item in models)) if models is not None else []
    target_models = requested or (catalog_ids if all_models and catalog_ids else minimax_model_candidates())
    target_models = list(dict.fromkeys(target_models))
    if not requested:
        target_models.extend(model for model in MINIMAX_IMAGE_MODELS if model not in target_models)

    _emit(progress_callback, "read_usage", "in_progress", MINIMAX_TOKEN_PLAN_REMAINS_URL)
    try:
        usage_payload = _api_get_json(
            url=MINIMAX_TOKEN_PLAN_REMAINS_URL,
            api_key=api_key,
            timeout_s=timeout_s,
        )
        usage = parse_minimax_shared_quota(usage_payload)
        _emit(progress_callback, "read_usage", "success", f"status={usage['status']}")
    except Exception as exc:
        usage_payload = {}
        usage = parse_minimax_shared_quota({})
        errors.append(f"usage endpoint failed: {exc}")
        _emit(progress_callback, "read_usage", "failed", str(exc))

    raw_text = json.dumps(usage.get("raw") or usage_payload, ensure_ascii=False)[:2000]
    pools = usage.get("pools") if isinstance(usage.get("pools"), dict) else {}
    records = []
    for model in target_models:
        pool_name = "video" if "video" in model.lower() else "general"
        model_usage = pools.get(pool_name) or usage
        records.append(
            MiniMaxQuotaRecord(
                model=model,
                kind="image" if model in MINIMAX_IMAGE_MODELS else "llm",
                total=model_usage.get("total"),
                used=model_usage.get("used"),
                remaining=model_usage.get("remaining"),
                unit=model_usage.get("unit") or "",
                expires_at=model_usage.get("expires_at") or "",
                status=model_usage.get("status") or "unknown",
                raw_text=raw_text,
            )
        )
    return {
        "provider": "minimax",
        "records": [record.to_dict() for record in records],
        "model_ids": catalog_ids,
        "usage": usage,
        "usage_url": MINIMAX_USAGE_URL,
        "source_mode": "api",
        "billing_mode": MINIMAX_BILLING_MODE,
        "quota_pool": MINIMAX_POOL_ID,
        "errors": errors,
    }
