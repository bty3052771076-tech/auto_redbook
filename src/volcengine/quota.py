from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import VOLCENGINE_AVAILABLE_LLM_MODELS


VOLCENGINE_ARK_USAGE_URL = "https://console.volcengine.com/ark/region:cn-beijing/usage"
VOLCENGINE_ARK_USAGE_TRACKING_URL = "https://console.volcengine.com/ark/region:cn-beijing/usageTracking"
VOLCENGINE_ARK_FREE_QUOTA_DOC_URL = "https://www.volcengine.com/docs/82379/1399514"
VOLCENGINE_ARK_MODEL_LIST_DOC_URL = "https://www.volcengine.com/docs/82379/1330310"
DEFAULT_VOLCENGINE_IMAGE_QUOTA_MODELS = [
    "doubao-seedream-5-0-lite-260128",
    "doubao-seedream-5-0-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
]


@dataclass(frozen=True)
class VolcengineQuotaRecord:
    model: str
    kind: str = "unknown"
    total: int | float | None = None
    used: int | float | None = None
    remaining: int | float | None = None
    unit: str = ""
    expires_at: str = ""
    status: str = "unknown"
    raw_text: str = ""
    source_url: str = VOLCENGINE_ARK_USAGE_URL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_values(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\s;，；]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = (part or "").strip()
        if not item or item in seen:
            continue
        out.append(item)
        seen.add(item)
    return out


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        out.append(item)
        seen.add(item)
    return out


def _classify_model(model: str) -> str:
    name = (model or "").strip().lower()
    if not name:
        return "unknown"
    normalized = _normalize_volcengine_model_key(name)
    for candidate in DEFAULT_VOLCENGINE_IMAGE_QUOTA_MODELS:
        if normalized in _volcengine_model_aliases(candidate):
            return "image"
    for candidate in VOLCENGINE_AVAILABLE_LLM_MODELS:
        if normalized in _volcengine_model_aliases(candidate):
            return "llm"
    if "seedream" in name or "image" in name:
        return "image"
    if any(marker in name for marker in ("seedance", "seed3d", "seededit", "hyper3d", "hitem3d", "wan2")):
        return "unknown"
    return "llm"


def volcengine_quota_model_candidates(
    *,
    llm_models: Optional[Iterable[str]] = None,
    image_models: Optional[Iterable[str]] = None,
    env: Optional[dict[str, str]] = None,
) -> list[str]:
    env = env if env is not None else os.environ
    if llm_models is None:
        env_llm_models = _split_values(env.get("VOLCENGINE_LLM_MODELS", ""))
        if env_llm_models:
            llm = env_llm_models
        else:
            single = (env.get("VOLCENGINE_LLM_MODEL") or "").strip()
            llm = [single] if single else list(VOLCENGINE_AVAILABLE_LLM_MODELS)
    else:
        llm = list(llm_models)

    if image_models is None:
        env_image_models = _split_values(env.get("VOLCENGINE_IMAGE_MODELS", ""))
        if env_image_models:
            images = env_image_models
        else:
            single = (env.get("VOLCENGINE_IMAGE_MODEL") or "").strip()
            images = [single] if single else list(DEFAULT_VOLCENGINE_IMAGE_QUOTA_MODELS)
    else:
        images = list(image_models)

    return _dedupe([*llm, *images])


def _normalize_date(text: str) -> str:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text or "")
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _parse_number(value: str) -> int | float | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    multiplier = 1
    suffix_match = re.search(r"\s*(万|亿|k|K|m|M)$", text)
    if suffix_match:
        suffix = suffix_match.group(1)
        multiplier = {"万": 10_000, "亿": 100_000_000, "k": 1_000, "K": 1_000, "m": 1_000_000, "M": 1_000_000}[suffix]
        text = text[: suffix_match.start()].strip()
    try:
        number = float(text)
    except ValueError:
        return None
    number *= multiplier
    return int(number) if number.is_integer() else number


NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:万|亿|k|K|m|M)?(?![A-Za-z0-9_.-])"
)


def _numbers_without_dates(text: str, *, model: str = "") -> list[int | float]:
    without_dates = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", " ", text or "")
    if model:
        without_dates = re.sub(re.escape(model), " ", without_dates, flags=re.IGNORECASE)
    numbers: list[int | float] = []
    for match in NUMBER_RE.finditer(without_dates):
        parsed = _parse_number(match.group(0))
        if parsed is not None:
            numbers.append(parsed)
    return numbers


def _number_after_labels(text: str, labels: Iterable[str], *, model: str = "") -> int | float | None:
    if model:
        text = re.sub(re.escape(model), " ", text or "", flags=re.IGNORECASE)
    label_re = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"(?:{label_re})\s*[:：]?\s*({NUMBER_RE.pattern})", re.IGNORECASE)
    match = pattern.search(text or "")
    if not match:
        return None
    return _parse_number(match.group(1))


def _detect_unit(text: str) -> str:
    match = re.search(r"\b(tokens?|Token|Tokens)\b|张|幅|次|点|条", text or "", re.IGNORECASE)
    if not match:
        return ""
    return match.group(0)


def _candidate_windows(text: str, model_names: list[str]) -> dict[str, str]:
    normalized = re.sub(r"\r\n?", "\n", text or "")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    models_lower = {model.lower(): model for model in model_names}
    windows: dict[str, str] = {}
    last_header = ""
    for idx, line in enumerate(lines):
        if _looks_like_quota_header(line):
            last_header = line
        line_lower = line.lower()
        current = ""
        for model_lower, model in models_lower.items():
            if model_lower in line_lower:
                current = model
                break
        if not current or current in windows:
            continue
        end = min(len(lines), idx + 10)
        for next_idx in range(idx + 1, min(len(lines), idx + 10)):
            next_lower = lines[next_idx].lower()
            if any(other != current and other.lower() in next_lower for other in model_names):
                end = next_idx
                break
        parts = [last_header] if last_header else []
        parts.extend(lines[idx:end])
        windows[current] = "\n".join(parts)
    return windows


def _looks_like_quota_header(line: str) -> bool:
    text = line or ""
    return "模型" in text and any(label in text for label in ("剩余", "已用", "使用", "免费", "总额度", "总量"))


def _header_fields(header: str) -> list[str]:
    patterns = [
        ("remaining", r"剩余额度|剩余量|剩余|可用额度|可用"),
        ("used", r"已用额度|已用量|已使用|已用|使用量|使用"),
        ("total", r"免费推理额度(?!剩余|已用|使用)|免费额度(?!剩余|已用|使用)|额度总量|总额度|总量|总计"),
    ]
    found: list[tuple[int, str]] = []
    for name, pattern in patterns:
        match = re.search(pattern, header or "", flags=re.IGNORECASE)
        if match:
            found.append((match.start(), name))
    return [name for _pos, name in sorted(found)]


def _parse_values_by_header(raw_text: str, *, model: str) -> tuple[int | float | None, int | float | None, int | float | None]:
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    header = next((line for line in lines if _looks_like_quota_header(line)), "")
    if not header:
        return None, None, None
    data_line = next((line for line in lines if model.lower() in line.lower()), "")
    if not data_line:
        return None, None, None
    fields = _header_fields(header)
    numbers = _numbers_without_dates(data_line, model=model)
    if not fields or len(numbers) < len(fields):
        return None, None, None
    values = dict(zip(fields, numbers))
    if ("total" not in values or values.get("total") is None) and "/" in data_line:
        text_without_dates = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", " ", data_line or "")
        ratio_match = re.search(rf"({NUMBER_RE.pattern})\s*/\s*(?:共)?\s*({NUMBER_RE.pattern})", text_without_dates)
        if ratio_match:
            remaining = _parse_number(ratio_match.group(1))
            total = _parse_number(ratio_match.group(2))
            if remaining is not None:
                values.setdefault("remaining", remaining)
            if total is not None:
                values["total"] = total
    return values.get("total"), values.get("used"), values.get("remaining")


def _parse_quota_values(raw_text: str, *, model: str = "") -> tuple[int | float | None, int | float | None, int | float | None]:
    if re.search(r"无免费额度|暂无免费额度|未开通|不可用", raw_text or ""):
        return 0, None, 0

    by_header = _parse_values_by_header(raw_text, model=model)
    if any(value is not None for value in by_header):
        return by_header

    total = _number_after_labels(raw_text, ["总额度", "总量", "免费额度", "免费推理额度", "额度总量", "总计"], model=model)
    used = _number_after_labels(raw_text, ["已用额度", "已用量", "已使用", "已用", "使用量"], model=model)
    remaining = _number_after_labels(raw_text, ["剩余额度", "剩余量", "剩余", "可用额度", "可用"], model=model)

    if total is not None or used is not None or remaining is not None:
        return total, used, remaining

    text_without_dates = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", " ", raw_text or "")
    ratio_match = re.search(rf"({NUMBER_RE.pattern})\s*/\s*(?:共)?\s*({NUMBER_RE.pattern})", text_without_dates)
    if ratio_match:
        first = _parse_number(ratio_match.group(1))
        second = _parse_number(ratio_match.group(2))
        if first is not None and second is not None:
            return second, None, first

    numbers = _numbers_without_dates(raw_text, model=model)
    if len(numbers) >= 3:
        return numbers[0], numbers[1], numbers[2]
    if len(numbers) == 2:
        return numbers[1], None, numbers[0]
    if len(numbers) == 1:
        return None, None, numbers[0]
    return None, None, None


def _detect_status(
    raw_text: str,
    *,
    remaining: int | float | None,
    total: int | float | None,
) -> str:
    text = raw_text or ""
    if re.search(r"无免费额度|暂无免费额度|未开通|不可用", text):
        return "no_free_quota"
    if re.search(r"已过期|过期", text):
        return "expired"
    if re.search(r"已用完|用尽|耗尽", text):
        return "exhausted"
    if remaining is not None:
        if remaining > 0:
            return "available"
        if remaining == 0 and (total is None or total > 0):
            return "exhausted"
    return "unknown"


def parse_volcengine_quota_text(
    text: str,
    model_names: Iterable[str],
    *,
    source_url: str = VOLCENGINE_ARK_USAGE_URL,
) -> list[VolcengineQuotaRecord]:
    models = _dedupe(model_names)
    windows = _candidate_windows(text, models)
    records: list[VolcengineQuotaRecord] = []
    for model in models:
        raw_text = windows.get(model, "")
        if not raw_text:
            continue
        total, used, remaining = _parse_quota_values(raw_text, model=model)
        records.append(
            VolcengineQuotaRecord(
                model=model,
                kind=_classify_model(model),
                total=total,
                used=used,
                remaining=remaining,
                unit=_detect_unit(raw_text),
                expires_at=_normalize_date(re.sub(re.escape(model), " ", raw_text, flags=re.IGNORECASE)),
                status=_detect_status(raw_text, remaining=remaining, total=total),
                raw_text=raw_text,
                source_url=source_url,
            )
        )
    return records


def _make_volcengine_not_visible_records(
    model_names: Iterable[str],
    *,
    source_url: str = VOLCENGINE_ARK_USAGE_URL,
) -> list[VolcengineQuotaRecord]:
    return [
        VolcengineQuotaRecord(
            model=model,
            kind=_classify_model(model),
            status="not_visible_on_page",
            raw_text="target model free quota is not visible on the Volcengine Ark page in visible-only mode",
            source_url=source_url,
        )
        for model in _dedupe(model_names)
    ]


def _complete_volcengine_visible_only_records(
    records: Iterable[VolcengineQuotaRecord],
    model_names: Iterable[str],
    *,
    source_url: str = VOLCENGINE_ARK_USAGE_URL,
) -> list[VolcengineQuotaRecord]:
    by_model = {record.model: record for record in records}
    missing = [model for model in _dedupe(model_names) if model not in by_model]
    for record in _make_volcengine_not_visible_records(missing, source_url=source_url):
        by_model[record.model] = record
    return [by_model[model] for model in _dedupe(model_names) if model in by_model]


def _as_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _parse_number(value)
    return None


def _normalize_volcengine_model_key(value: str) -> str:
    return (value or "").strip().lower().replace(".", "-").replace("_", "-")


def _volcengine_model_aliases(model: str) -> set[str]:
    return set(_volcengine_model_alias_list(model))


def _volcengine_model_alias_list(model: str) -> list[str]:
    base = _normalize_volcengine_model_key(model)
    aliases: list[str] = []
    if base:
        aliases.append(base)
    if re.search(r"-\d{6}$", base):
        aliases.append(re.sub(r"-\d{6}$", "", base))
    # Ark charge-item names currently omit "lite" for Seedream 5.0 lite.
    if "-seedream-" in base and "-lite" in base:
        aliases.append(base.replace("-lite", ""))
        aliases.append(re.sub(r"-lite-\d{6}$", "", base))
    out: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if not alias or alias in seen:
            continue
        out.append(alias)
        seen.add(alias)
    return out


def _volcengine_canonical_model_name(item: dict[str, Any]) -> str:
    foundation = _normalize_volcengine_model_key(str(item.get("FoundationModelName") or ""))
    display = _normalize_volcengine_model_key(str(item.get("DisplayName") or ""))
    known_models = [*VOLCENGINE_AVAILABLE_LLM_MODELS, *DEFAULT_VOLCENGINE_IMAGE_QUOTA_MODELS]
    for candidate in known_models:
        aliases = _volcengine_model_aliases(candidate)
        if foundation in aliases or display in aliases:
            return candidate
    if foundation == "glm-5-2" or display == "glm-5-2":
        return "glm-5.2"
    if foundation == "doubao-seedream-5-0" and "lite" in display:
        return "doubao-seedream-5-0-lite-260128"
    return foundation or display


def _extract_charge_items(payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        result = payload.get("Result")
        if not isinstance(result, dict):
            continue
        if isinstance(result.get("Items"), list):
            items.extend(item for item in result["Items"] if isinstance(item, dict))
        elif result.get("FoundationModelName") or result.get("DisplayName"):
            items.append(result)
    return items


def _charge_item_model_names(payloads: Iterable[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _extract_charge_items(payloads):
        model = str(item.get("FoundationModelName") or item.get("DisplayName") or "").strip()
        if not model or model in seen:
            continue
        out.append(model)
        seen.add(model)
    return out


def _status_from_charge_item(
    item: dict[str, Any] | None,
    *,
    total: int | float | None,
    remaining: int | float | None,
    has_free_usage: bool,
) -> str:
    if not item:
        return "not_found"
    state = str(item.get("State") or "").strip().lower()
    is_overdue = item.get("IsOverdue")
    if is_overdue is True:
        return "expired"
    if not has_free_usage:
        return "quota_not_returned"
    if total == 0:
        return "no_free_quota"
    if remaining is not None:
        if remaining > 0:
            return "available" if state in {"available", ""} else "unavailable"
        if remaining == 0 and (total is None or total > 0):
            return "exhausted"
    if state and state != "available":
        return "unavailable"
    return "unknown"


def _free_inference_resource_pack(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    packs = item.get("ResourcePackItems")
    if not isinstance(packs, list):
        return None
    candidates = [pack for pack in packs if isinstance(pack, dict)]
    for pack in candidates:
        if str(pack.get("Type") or "").strip().lower() == "freeinference":
            return pack
    return candidates[0] if candidates else None


def _unit_from_charge_item(item: dict[str, Any] | None, model: str) -> str:
    if _classify_model(model) == "llm":
        return "token"
    if not isinstance(item, dict):
        return "quota"
    charge_items = item.get("ChargeItems")
    if isinstance(charge_items, list):
        for charge in charge_items:
            if not isinstance(charge, dict):
                continue
            unit = str(charge.get("UnitCode") or "").strip()
            if unit and "token" not in unit.lower():
                return unit
    return "quota"


def parse_volcengine_console_api_quota(
    payloads: Iterable[dict[str, Any]],
    model_names: Iterable[str],
    *,
    source_url: str = VOLCENGINE_ARK_USAGE_TRACKING_URL,
) -> list[VolcengineQuotaRecord]:
    """
    Parse Ark console charge-item JSON captured from the official console.

    Some newly opened models are marked Available but do not include
    InferenceFreeUsage. Those rows are returned with status
    "quota_not_returned" so callers do not mistake model availability for a
    synchronized free-quota balance.
    """
    models = _dedupe(model_names)
    items = _extract_charge_items(payloads)
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        foundation = _normalize_volcengine_model_key(str(item.get("FoundationModelName") or ""))
        display = _normalize_volcengine_model_key(str(item.get("DisplayName") or ""))
        for key in (foundation, display):
            if key and key not in by_key:
                by_key[key] = item

    records: list[VolcengineQuotaRecord] = []
    for model in models:
        item = next((by_key[alias] for alias in _volcengine_model_aliases(model) if alias in by_key), None)
        free_usage = item.get("InferenceFreeUsage") if isinstance(item, dict) else None
        resource_pack = None if isinstance(free_usage, dict) else _free_inference_resource_pack(item)
        has_free_usage = isinstance(free_usage, dict) or isinstance(resource_pack, dict)
        if not isinstance(free_usage, dict) and isinstance(resource_pack, dict):
            free_usage = resource_pack
        total = _as_number(free_usage.get("Total")) if has_free_usage else None
        used = _as_number(free_usage.get("Consumed")) if has_free_usage else None
        reclaimed = _as_number(free_usage.get("Reclaimed")) if has_free_usage else None
        remaining = None
        if total is not None and used is not None:
            remaining = total - used - (reclaimed or 0)
        raw_text = json.dumps(item or {"model": model, "error": "model charge item not found"}, ensure_ascii=False)
        records.append(
            VolcengineQuotaRecord(
                model=model,
                kind=_classify_model(model),
                total=total,
                used=used,
                remaining=remaining,
                unit=_unit_from_charge_item(item, model) if has_free_usage else "",
                expires_at="",
                status=_status_from_charge_item(
                    item,
                    total=total,
                    remaining=remaining,
                    has_free_usage=has_free_usage,
                ),
                raw_text=raw_text,
                source_url=source_url,
            )
        )
    return records


def parse_all_volcengine_console_api_quota(
    payloads: Iterable[dict[str, Any]],
    *,
    source_url: str = VOLCENGINE_ARK_USAGE_TRACKING_URL,
) -> list[VolcengineQuotaRecord]:
    items = _extract_charge_items(payloads)
    model_names: list[str] = []
    seen: set[str] = set()
    selected_payloads: list[dict[str, Any]] = []
    for item in items:
        resource_pack = _free_inference_resource_pack(item)
        free_usage = item.get("InferenceFreeUsage") if isinstance(item.get("InferenceFreeUsage"), dict) else resource_pack
        if not isinstance(free_usage, dict):
            continue
        total = _as_number(free_usage.get("Total"))
        remaining = None
        used = _as_number(free_usage.get("Consumed"))
        reclaimed = _as_number(free_usage.get("Reclaimed"))
        if total is not None and used is not None:
            remaining = total - used - (reclaimed or 0)
        if (total is None or total <= 0) and (remaining is None or remaining <= 0):
            continue
        model = _volcengine_canonical_model_name(item)
        if not model or model in seen:
            continue
        seen.add(model)
        model_names.append(model)
        selected_payloads.append({"Result": item})
    return parse_volcengine_console_api_quota(selected_payloads, model_names, source_url=source_url)


def _cell(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def format_volcengine_quota_records(records: Iterable[VolcengineQuotaRecord | dict[str, Any]]) -> str:
    normalized: list[VolcengineQuotaRecord] = []
    for item in records:
        if isinstance(item, VolcengineQuotaRecord):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(
                VolcengineQuotaRecord(**{k: item.get(k) for k in VolcengineQuotaRecord.__dataclass_fields__})
            )

    if not normalized:
        return (
            "No matching quota rows were parsed. Please open the official Volcengine Ark console "
            "and confirm the usage/free-quota table is visible."
        )

    lines = [
        "model | kind | status | remaining | used | total | unit | expires_at",
        "--- | --- | --- | ---: | ---: | ---: | --- | ---",
    ]
    has_unknown = False
    for record in normalized:
        has_unknown = has_unknown or record.remaining is None
        lines.append(
            " | ".join(
                [
                    record.model,
                    record.kind,
                    record.status or "unknown",
                    _cell(record.remaining),
                    _cell(record.used),
                    _cell(record.total),
                    record.unit or "unknown",
                    record.expires_at or "unknown",
                ]
            )
        )
    if has_unknown:
        lines.append(
            "Note: unknown means the visible console text did not expose a parseable number; "
            "open the official Volcengine Ark console and expand the usage/free-quota table if needed; "
            "not_visible_on_page means visible-only mode could not find a visible free-quota row for that model; "
            "quota_not_returned means the official Ark console API returned model metadata but no "
            "InferenceFreeUsage field for that model."
        )
    return "\n".join(lines)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_profile_config() -> tuple[Path, Optional[str], list[str]]:
    user_data_dir = (os.getenv("VOLCENGINE_CONSOLE_USER_DATA_DIR") or "").strip()
    profile_dir = Path(user_data_dir) if user_data_dir else _repo_root() / "data" / "browser" / "volcengine-console-profile"
    channel = (os.getenv("VOLCENGINE_BROWSER_CHANNEL") or "chrome").strip() or None
    args: list[str] = []
    profile_name = (os.getenv("VOLCENGINE_CHROME_PROFILE") or "").strip()
    if profile_name:
        args.append(f"--profile-directory={profile_name}")
    return profile_dir, channel, args


def _emit(progress_callback: Optional[Callable[[str], None]], name: str, status: str, detail: str = "") -> None:
    if not progress_callback:
        return
    message = f"[volcengine-quota] {name}: {status}"
    if detail:
        message += f" | {detail}"
    try:
        progress_callback(message)
    except Exception:
        pass


def _read_body_text(page, *, timeout_ms: int = 2000, max_chars: int = 50000) -> str:
    try:
        return str(page.evaluate("() => document.body ? document.body.innerText : ''") or "")[:max_chars]
    except Exception:
        try:
            return str(page.locator("body").first.inner_text(timeout=timeout_ms) or "")[:max_chars]
        except Exception:
            return ""


def _looks_like_login_page(page, body_text: str) -> bool:
    url = ""
    try:
        url = str(page.url or "")
    except Exception:
        pass
    haystack = "\n".join([url, body_text or ""]).lower()
    login_hints = ("login", "signin", "登录", "扫码", "验证码", "账号密码", "火山引擎账号")
    usage_hints = ("用量统计", "免费推理额度", "剩余额度", "模型名称", "token")
    return any(hint in haystack for hint in login_hints) and not any(hint in body_text for hint in usage_hints)


def _extract_console_text(page) -> str:
    body_text = _read_body_text(page)
    try:
        row_texts = page.evaluate(
            """
            () => {
              const selectors = [
                'tr',
                '[role="row"]',
                '.arco-table-tr',
                '.ve-table-row',
                '.byte-table-row',
                '.semi-table-row',
                '[class*="table"] [class*="row"]'
              ];
              const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
              const seen = new Set();
              const out = [];
              for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (!text || seen.has(text)) continue;
                seen.add(text);
                out.push(text);
              }
              return out;
            }
            """
        )
    except Exception:
        row_texts = []
    row_text = "\n".join(str(item) for item in row_texts if str(item).strip())
    return "\n".join(part for part in [row_text, body_text] if part)


def _click_usage_tracking(page) -> None:
    try:
        page.evaluate(
            """
            (needle) => {
              const nodes = Array.from(document.querySelectorAll('a,button,div,span,li'));
              const node = nodes.find(n => (n.innerText || n.textContent || '').trim() === needle)
                || nodes.find(n => (n.innerText || n.textContent || '').includes(needle));
              if (node) node.click();
            }
            """,
            "用量统计",
        )
    except Exception:
        pass


def _capture_json_response(resp, captured: list[dict[str, Any]]) -> None:
    url = str(getattr(resp, "url", "") or "")
    if not any(
        name in url
        for name in (
            "GetModelChargeItem",
            "ListModelChargeItems",
            "GetAutoSetFreeLimit",
            "GetInferenceUsage",
        )
    ):
        return
    try:
        text = resp.text()
        data = json.loads(text)
    except Exception:
        return
    if isinstance(data, dict):
        captured.append(data)


def _capture_charge_item_request_headers(req, captured: list[dict[str, str]]) -> None:
    url = str(getattr(req, "url", "") or "")
    if (
        "GetModelChargeItem" not in url
        and "ListModelChargeItems" not in url
        and "/api/top/ark/" not in url
    ):
        return
    try:
        headers = dict(req.headers)
    except Exception:
        return
    allowed = {
        key: value
        for key, value in headers.items()
        if key.lower() in {"x-csrf-token", "x-web-id", "accept-language", "accept", "content-type"}
    }
    if allowed:
        captured.append(allowed)


def _target_charge_item_names(model_names: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for model in model_names:
        for alias in _volcengine_model_alias_list(model):
            if alias in seen:
                continue
            out.append(alias)
            seen.add(alias)
    return out


def _fetch_target_charge_item_payloads(page, model_names: list[str], captured_headers: list[dict[str, str]]) -> list[dict[str, Any]]:
    headers = dict(captured_headers[-1]) if captured_headers else {}
    headers.setdefault("content-type", "application/json")
    headers.setdefault("accept", "application/json, text/plain, */*")
    try:
        payloads = page.evaluate(
            """
            async ({models, headers}) => {
              const endpoints = [
                'https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetModelChargeItem?',
                'https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/ListModelChargeItems?'
              ];
              const out = [];
              for (const model of models) {
                for (const endpoint of endpoints) {
                  const body = endpoint.includes('GetModelChargeItem')
                    ? {FoundationModelName: model}
                    : {PageNumber: 1, PageSize: 10, Filter: {FoundationModelNames: [model]}, Fields: ['Base', 'Price']};
                  try {
                    const resp = await fetch(endpoint, {
                      method: 'POST',
                      credentials: 'include',
                      headers,
                      body: JSON.stringify(body)
                    });
                    const text = await resp.text();
                    try {
                      out.push(JSON.parse(text));
                    } catch (_err) {
                      out.push({ResponseMetadata: {Action: 'ConsoleFetch', Error: {Code: 'InvalidJSON'}}, RawText: text.slice(0, 500)});
                    }
                  } catch (err) {
                    out.push({ResponseMetadata: {Action: 'ConsoleFetch', Error: {Code: 'FetchFailed', Message: String(err)}}});
                  }
                }
              }
              return out;
            }
            """,
            {"models": _target_charge_item_names(model_names), "headers": headers},
        )
    except Exception:
        return []
    return [payload for payload in payloads if isinstance(payload, dict)]


def _fetch_all_charge_item_payloads(
    page,
    captured_headers: list[dict[str, str]],
    *,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    headers = dict(captured_headers[-1]) if captured_headers else {}
    headers.setdefault("content-type", "application/json")
    headers.setdefault("accept", "application/json, text/plain, */*")
    try:
        payloads = page.evaluate(
            """
            async ({headers, pageSize, maxPages}) => {
              const endpoint = 'https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/ListModelChargeItems?';
              const out = [];
              for (let pageNumber = 1; pageNumber <= maxPages; pageNumber += 1) {
                const body = {PageNumber: pageNumber, PageSize: pageSize, Fields: ['Base', 'Price']};
                try {
                  const resp = await fetch(endpoint, {
                    method: 'POST',
                    credentials: 'include',
                    headers,
                    body: JSON.stringify(body)
                  });
                  const text = await resp.text();
                  let parsed;
                  try {
                    parsed = JSON.parse(text);
                  } catch (_err) {
                    parsed = {ResponseMetadata: {Action: 'ConsoleFetch', Error: {Code: 'InvalidJSON'}}, RawText: text.slice(0, 500)};
                  }
                  out.push(parsed);
                  const result = parsed && parsed.Result ? parsed.Result : {};
                  const items = Array.isArray(result.Items) ? result.Items : [];
                  const total = Number(result.TotalCount || 0);
                  if (!items.length) break;
                  if (total > 0 && pageNumber * pageSize >= total) break;
                } catch (err) {
                  out.push({ResponseMetadata: {Action: 'ConsoleFetch', Error: {Code: 'FetchFailed', Message: String(err)}}});
                  break;
                }
              }
              return out;
            }
            """,
            {"headers": headers, "pageSize": max(1, int(page_size)), "maxPages": max(1, int(max_pages))},
        )
    except Exception:
        return []
    return [payload for payload in payloads if isinstance(payload, dict)]


def _has_charge_item_payload(payloads: Iterable[dict[str, Any]]) -> bool:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("ResponseMetadata")
        action = metadata.get("Action") if isinstance(metadata, dict) else ""
        if action in {"GetModelChargeItem", "ListModelChargeItems"}:
            return True
        result = payload.get("Result")
        if isinstance(result, dict):
            if result.get("FoundationModelName"):
                return True
            items = result.get("Items")
            if isinstance(items, list) and any(isinstance(item, dict) and item.get("FoundationModelName") for item in items):
                return True
    return False


def run_collect_volcengine_quota_sync(
    *,
    models: Optional[list[str]] = None,
    all_free: bool = False,
    login_hold: int = 0,
    wait_timeout_ms: int = 120000,
    headless: Optional[bool] = None,
    visible_only: bool = False,
    quota_url: str = VOLCENGINE_ARK_USAGE_URL,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """
    Read Volcengine Ark quota/usage from the official console page.

    Ark exposes model listing and inference APIs, but remaining free quota is a
    console/account concept. This reader avoids consuming model quota while
    keeping credentials inside the workspace-local browser profile.
    """
    result: dict[str, Any] = {
        "source_url": quota_url,
        "source_mode": (
            "visible_page_only"
            if visible_only
            else "visible_page_with_console_api_fallback_all_free"
            if all_free
            else "visible_page_with_console_api_fallback"
        ),
        "usage_tracking_url": VOLCENGINE_ARK_USAGE_TRACKING_URL,
        "free_quota_doc_url": VOLCENGINE_ARK_FREE_QUOTA_DOC_URL,
        "model_list_doc_url": VOLCENGINE_ARK_MODEL_LIST_DOC_URL,
        "all_free": bool(all_free),
        "records": [],
        "raw_text": "",
        "console_api_payloads": [],
        "errors": [],
    }
    model_names = [] if all_free else _dedupe(models or volcengine_quota_model_candidates())
    headless_value = _env_flag("VOLCENGINE_CONSOLE_HEADLESS", False) if headless is None else bool(headless)
    profile_dir, channel, args = _resolve_profile_config()
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment issue
        result["errors"].append(f"Playwright is not available: {exc}")
        return result

    try:
        _emit(progress_callback, "launch", "in_progress", f"{profile_dir} | headless={headless_value}")
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {"headless": headless_value}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = args
            context = p.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
            try:
                context.set_default_timeout(30000)
                page = context.pages[0] if context.pages else context.new_page()
                console_api_payloads: list[dict[str, Any]] = []
                charge_item_request_headers: list[dict[str, str]] = []
                if not visible_only:
                    page.on("response", lambda resp: _capture_json_response(resp, console_api_payloads))
                    page.on("request", lambda req: _capture_charge_item_request_headers(req, charge_item_request_headers))
                _emit(progress_callback, "open_usage_page", "in_progress", quota_url)
                page.goto(quota_url, wait_until="domcontentloaded")

                deadline = time.time() + max(1, wait_timeout_ms / 1000)
                login_deadline = time.time() + max(0, login_hold)
                body_text = ""
                clicked_usage = False
                while time.time() < deadline:
                    body_text = _read_body_text(page)
                    if not clicked_usage and "用量统计" in body_text:
                        _click_usage_tracking(page)
                        clicked_usage = True
                    if _has_charge_item_payload(console_api_payloads):
                        break
                    if model_names and any(model.lower() in body_text.lower() for model in model_names):
                        break
                    if any(hint in body_text for hint in ("免费推理额度", "剩余额度", "模型名称")):
                        break
                    if _looks_like_login_page(page, body_text):
                        if headless_value:
                            raise RuntimeError(
                                "Volcengine console login required but browser is headless; "
                                "run volcengine-quota once without --headless and log in to the workspace profile"
                            )
                        if login_hold <= 0 or time.time() >= login_deadline:
                            raise RuntimeError(
                                "Volcengine console login required; rerun with --login-hold 600 and finish login in the visible browser"
                            )
                    time.sleep(1)

                _emit(progress_callback, "read_console_text", "in_progress", "")
                raw_text = _extract_console_text(page)
                result["raw_text"] = raw_text
                targeted_payloads = []
                if not visible_only:
                    if all_free:
                        targeted_payloads = _fetch_all_charge_item_payloads(page, charge_item_request_headers)
                        discovered_models = _charge_item_model_names(targeted_payloads)
                        targeted_payloads.extend(
                            _fetch_target_charge_item_payloads(
                                page,
                                discovered_models or volcengine_quota_model_candidates(),
                                charge_item_request_headers,
                            )
                        )
                    else:
                        targeted_payloads = _fetch_target_charge_item_payloads(
                            page,
                            model_names,
                            charge_item_request_headers,
                        )
                if targeted_payloads:
                    console_api_payloads.extend(targeted_payloads)
                result["console_api_payloads"] = console_api_payloads
                text_records = parse_volcengine_quota_text(raw_text, model_names, source_url=quota_url) if model_names else []
                if visible_only and all_free:
                    records_by_model = {}
                    result["errors"].append(
                        "all-free Volcengine quota sync requires console API capture; disable --visible-only"
                    )
                elif visible_only:
                    records_by_model = {
                        record.model: record
                        for record in _complete_volcengine_visible_only_records(
                            text_records,
                            model_names,
                            source_url=quota_url,
                        )
                    }
                elif all_free:
                    api_records = parse_all_volcengine_console_api_quota(
                        console_api_payloads,
                        source_url=VOLCENGINE_ARK_USAGE_TRACKING_URL,
                    )
                    records_by_model = {record.model: record for record in api_records}
                else:
                    api_records = parse_volcengine_console_api_quota(
                        console_api_payloads,
                        model_names,
                        source_url=VOLCENGINE_ARK_USAGE_TRACKING_URL,
                    )
                    records_by_model = {record.model: record for record in api_records}
                    for record in text_records:
                        if record.remaining is not None or record.status not in {"unknown", "quota_not_returned"}:
                            records_by_model[record.model] = record
                records = (
                    list(records_by_model.values())
                    if all_free
                    else [records_by_model[model] for model in model_names if model in records_by_model]
                )
                result["records"] = [record.to_dict() for record in records]
                if not records:
                    result["errors"].append(
                        "no quota rows parsed; make sure the Ark usage/free-quota table is visible"
                    )
                unresolved = [] if all_free else [
                    record.model
                    for record in records
                    if record.status in {"quota_not_returned", "not_found", "not_visible_on_page"} or record.remaining is None
                ]
                if unresolved:
                    if visible_only:
                        result["errors"].append(
                            "free quota not visible on the Volcengine page for requested models: "
                            + ", ".join(unresolved)
                        )
                    else:
                        result["errors"].append(
                            "free quota not returned for requested Volcengine models: " + ", ".join(unresolved)
                        )
                _emit(progress_callback, "read_console_text", "success", f"records={len(records)}")
                return result
            finally:
                context.close()
    except Exception as exc:
        result["errors"].append(str(exc))
        _emit(progress_callback, "collect_quota", "failed", str(exc))
        return result
