from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import ALIYUN_FREE_LLM_MODELS, DEFAULT_ALIYUN_LLM_MODEL


BAILIAN_FREE_QUOTA_URL = "https://bailian.console.aliyun.com/cn-beijing/?tab=costing-balance"
BAILIAN_USAGE_URL = "https://bailian.console.aliyun.com/cn-beijing/?tab=costing"
DEFAULT_ALIYUN_IMAGE_QUOTA_MODELS = [
    "wan2.7-image",
    "wan2.7-image-pro",
    "qwen-image-2.0-pro-2026-06-22",
    "qwen-image-2.0-pro-2026-04-22",
]


@dataclass(frozen=True)
class AliyunQuotaRecord:
    model: str
    kind: str = "unknown"
    total: int | float | None = None
    used: int | float | None = None
    remaining: int | float | None = None
    unit: str = ""
    expires_at: str = ""
    status: str = "unknown"
    raw_text: str = ""
    source_url: str = BAILIAN_FREE_QUOTA_URL

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
    if (
        name in {item.lower() for item in DEFAULT_ALIYUN_IMAGE_QUOTA_MODELS}
        or name.startswith(("qwen-image", "z-image", "wanx"))
        or name.startswith("wan2.7-image")
    ):
        return "image"
    if name.startswith(("qwen", "deepseek", "glm", "kimi")):
        return "llm"
    if any(
        marker in name
        for marker in (
            "sambert",
            "paraformer",
            "cosyvoice",
            "music",
            "asr",
            "audio",
            "video",
            "t2v",
            "i2v",
            "r2v",
            "wordart",
            "happyhorse",
        )
    ):
        return "unknown"
    return "llm"


def aliyun_quota_model_candidates(
    *,
    llm_models: Optional[Iterable[str]] = None,
    image_models: Optional[Iterable[str]] = None,
    env: Optional[dict[str, str]] = None,
) -> list[str]:
    env = env if env is not None else os.environ
    if llm_models is None:
        env_llm_models = _split_values(env.get("ALIYUN_LLM_MODELS", ""))
        if env_llm_models:
            llm = env_llm_models
        else:
            single = (env.get("ALIYUN_LLM_MODEL") or DEFAULT_ALIYUN_LLM_MODEL).strip()
            llm = [single] if single else list(ALIYUN_FREE_LLM_MODELS)
    else:
        llm = list(llm_models)

    if image_models is None:
        env_image_models = _split_values(env.get("ALIYUN_IMAGE_MODELS", ""))
        if env_image_models:
            images = env_image_models
        else:
            single = (env.get("ALIYUN_IMAGE_MODEL") or "").strip()
            images = [single] if single else list(DEFAULT_ALIYUN_IMAGE_QUOTA_MODELS)
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


def _as_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _parse_number(value)
    return None


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

    total = _number_after_labels(raw_text, ["总额度", "总量", "免费额度", "额度总量", "总计"], model=model)
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
    if remaining is not None:
        if remaining > 0:
            return "available"
        if remaining == 0 and (total is None or total > 0):
            return "exhausted"
    if re.search(r"已用完|用尽|耗尽", text):
        return "exhausted"
    return "unknown"


def parse_aliyun_quota_text(
    text: str,
    model_names: Iterable[str],
    *,
    source_url: str = BAILIAN_FREE_QUOTA_URL,
) -> list[AliyunQuotaRecord]:
    models = _dedupe(model_names)
    windows = _candidate_windows(text, models)
    records: list[AliyunQuotaRecord] = []
    for model in models:
        raw_text = windows.get(model, "")
        if not raw_text:
            continue
        total, used, remaining = _parse_quota_values(raw_text, model=model)
        records.append(
            AliyunQuotaRecord(
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


def _make_aliyun_not_visible_records(
    model_names: Iterable[str],
    *,
    source_url: str = BAILIAN_FREE_QUOTA_URL,
) -> list[AliyunQuotaRecord]:
    return [
        AliyunQuotaRecord(
            model=model,
            kind=_classify_model(model),
            status="not_visible_on_page",
            raw_text="target model free quota is not visible on the Aliyun Bailian page in visible-only mode",
            source_url=source_url,
        )
        for model in _dedupe(model_names)
    ]


def _complete_aliyun_visible_only_records(
    records: Iterable[AliyunQuotaRecord],
    model_names: Iterable[str],
    *,
    source_url: str = BAILIAN_FREE_QUOTA_URL,
) -> list[AliyunQuotaRecord]:
    by_model = {record.model: record for record in records}
    missing = [model for model in _dedupe(model_names) if model not in by_model]
    for record in _make_aliyun_not_visible_records(missing, source_url=source_url):
        by_model[record.model] = record
    return [by_model[model] for model in _dedupe(model_names) if model in by_model]


def _extract_aliyun_free_tier_quota_items(payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            quotas = value.get("freeTierQuotas")
            if isinstance(quotas, list):
                items.extend(item for item in quotas if isinstance(item, dict))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for payload in payloads:
        walk(payload)
    return items


def _date_from_epoch_ms(value: object) -> str:
    number = _as_number(value)
    if number is None or number <= 0:
        return ""
    try:
        return datetime.fromtimestamp(float(number) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _aliyun_api_status(
    item: dict[str, Any] | None,
    *,
    total: int | float | None,
    remaining: int | float | None,
) -> str:
    if not item:
        return "not_found"
    status = str(item.get("quotaStatus") or "").strip().upper()
    if status in {"EXPIRED", "OVERDUE"}:
        return "expired"
    if status in {"UNKNOWN", ""} and remaining is None:
        return "quota_not_returned"
    if total == 0:
        return "no_free_quota"
    if remaining is not None:
        if remaining > 0:
            return "available"
        if remaining == 0 and (total is None or total > 0):
            return "exhausted"
    if status == "VALID":
        return "available"
    return "unknown"


def parse_aliyun_console_api_quota(
    payloads: Iterable[dict[str, Any]],
    model_names: Iterable[str],
    *,
    source_url: str = BAILIAN_FREE_QUOTA_URL,
) -> list[AliyunQuotaRecord]:
    models = _dedupe(model_names)
    items = _extract_aliyun_free_tier_quota_items(payloads)
    by_model: dict[str, dict[str, Any]] = {}
    for item in items:
        model = str(item.get("model") or "").strip()
        if not model:
            continue
        current = by_model.get(model.lower())
        if current is None:
            by_model[model.lower()] = item
            continue
        current_has_quota = _as_number(current.get("quotaTotal")) is not None
        item_has_quota = _as_number(item.get("quotaTotal")) is not None
        if item_has_quota and not current_has_quota:
            by_model[model.lower()] = item

    records: list[AliyunQuotaRecord] = []
    for model in models:
        item = by_model.get(model.lower())
        total = _as_number(item.get("quotaInitTotal")) if item else None
        remaining = _as_number(item.get("quotaTotal")) if item else None
        used = None
        if total is not None and remaining is not None:
            used = total - remaining
        raw_text = json.dumps(item or {"model": model, "error": "free tier quota item not found"}, ensure_ascii=False)
        records.append(
            AliyunQuotaRecord(
                model=model,
                kind=_classify_model(model),
                total=total,
                used=used,
                remaining=remaining,
                unit="token" if _classify_model(model) == "llm" else "次",
                expires_at=_date_from_epoch_ms(item.get("quotaValidityPeriod")) if item else "",
                status=_aliyun_api_status(item, total=total, remaining=remaining),
                raw_text=raw_text,
                source_url=source_url,
            )
        )
    return records


def parse_all_aliyun_console_api_quota(
    payloads: Iterable[dict[str, Any]],
    *,
    source_url: str = BAILIAN_FREE_QUOTA_URL,
) -> list[AliyunQuotaRecord]:
    items = _extract_aliyun_free_tier_quota_items(payloads)
    by_model: dict[str, dict[str, Any]] = {}
    for item in items:
        model = str(item.get("model") or "").strip()
        if not model:
            continue
        total = _as_number(item.get("quotaInitTotal"))
        remaining = _as_number(item.get("quotaTotal"))
        if (total is None or total <= 0) and (remaining is None or remaining <= 0):
            continue
        current = by_model.get(model.lower())
        if current is None:
            by_model[model.lower()] = item
            continue
        current_total = _as_number(current.get("quotaInitTotal")) or 0
        item_total = total or 0
        if item_total > current_total:
            by_model[model.lower()] = item

    return parse_aliyun_console_api_quota(
        [dict(data=dict(DataV2=dict(data=dict(data=dict(freeTierQuotas=list(by_model.values()))))))],
        [str(item.get("model") or "").strip() for item in by_model.values()],
        source_url=source_url,
    )


def _iter_nested_values(value: object) -> Iterable[object]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield item
            yield from _iter_nested_values(item)
    elif isinstance(value, list):
        for item in value:
            yield item
            yield from _iter_nested_values(item)


def _aliyun_login_transition_seen(api_payloads: Iterable[dict[str, Any]]) -> bool:
    saw_not_logged_in = False
    saw_logged_in = False
    for payload in api_payloads:
        if not isinstance(payload, dict):
            continue
        values = [str(value) for value in _iter_nested_values(payload) if value is not None]
        haystack = "\n".join(values)
        if "BailianGateway.Login.NotLogined" in haystack or "NOT_LOGINED" in haystack:
            saw_not_logged_in = True
        if "ALIYUN_LOGINED" in haystack:
            saw_logged_in = True
    return saw_not_logged_in and saw_logged_in


def _should_retry_aliyun_quota_after_login_transition(
    raw_text: str,
    api_payloads: Iterable[dict[str, Any]],
    records: Iterable[AliyunQuotaRecord],
    *,
    visible_only: bool = False,
) -> bool:
    if visible_only:
        return False
    if list(records):
        return False
    if not _aliyun_login_transition_seen(api_payloads):
        return False
    return "暂无符合条件的资源" in (raw_text or "") or "免费额度" in (raw_text or "")


def detect_aliyun_console_errors(
    raw_text: str,
    api_payloads: Iterable[dict[str, Any]] = (),
) -> list[str]:
    errors: list[str] = []
    text = raw_text or ""
    if re.search(r"登录以使用|未登录状态|立即登录", text):
        errors.append("aliyun_console_login_required")
    if "暂无符合条件的资源" in text:
        errors.append("aliyun_no_free_quota_rows_visible")

    saw_internal_not_logged_in = False
    saw_internal_logged_in = False
    for payload in api_payloads:
        if not isinstance(payload, dict):
            continue
        values = [str(value) for value in _iter_nested_values(payload) if value is not None]
        haystack = "\n".join(values)
        if "BailianGateway.Login.NotLogined" in haystack or "NOT_LOGINED" in haystack:
            saw_internal_not_logged_in = True
        if "ALIYUN_LOGINED" in haystack:
            saw_internal_logged_in = True
        if "InvalidCSRFToken" in haystack:
            errors.append("aliyun_invalid_csrf_token")
    if saw_internal_not_logged_in and not saw_internal_logged_in:
        errors.append("bailian_internal_not_logged_in")

    out: list[str] = []
    seen: set[str] = set()
    for error in errors:
        if error in seen:
            continue
        out.append(error)
        seen.add(error)
    return out


def _cell(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def format_aliyun_quota_records(records: Iterable[AliyunQuotaRecord | dict[str, Any]]) -> str:
    normalized: list[AliyunQuotaRecord] = []
    for item in records:
        if isinstance(item, AliyunQuotaRecord):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(AliyunQuotaRecord(**{k: item.get(k) for k in AliyunQuotaRecord.__dataclass_fields__}))

    if not normalized:
        return (
            "No matching quota rows were parsed. Please open the official Bailian console "
            "and confirm the free-quota table is visible."
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
            "not_found means the target model was not present in the visible Bailian free-quota tables; "
            "not_visible_on_page means visible-only mode could not find a visible free-quota row for that model; "
            "open the official Bailian console and expand the quota table if needed."
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
    user_data_dir = (os.getenv("ALIYUN_CONSOLE_USER_DATA_DIR") or "").strip()
    profile_dir = Path(user_data_dir) if user_data_dir else _repo_root() / "data" / "browser" / "aliyun-console-profile"
    channel = (os.getenv("ALIYUN_BROWSER_CHANNEL") or "chrome").strip() or None
    args: list[str] = []
    profile_name = (os.getenv("ALIYUN_CHROME_PROFILE") or "").strip()
    if profile_name:
        args.append(f"--profile-directory={profile_name}")
    return profile_dir, channel, args


def _emit(progress_callback: Optional[Callable[[str], None]], name: str, status: str, detail: str = "") -> None:
    if not progress_callback:
        return
    message = f"[aliyun-quota] {name}: {status}"
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
    login_hints = ("login", "signin", "登录", "扫码", "验证码", "账号密码", "阿里云账号")
    quota_hints = ("免费额度", "额度", "模型名称", "剩余额度")
    return any(hint in haystack for hint in login_hints) and not any(hint in body_text for hint in quota_hints)


def _extract_console_text(page) -> str:
    body_text = _read_body_text(page)
    try:
        row_texts = page.evaluate(
            """
            () => {
              const selectors = [
                'tr',
                '[role="row"]',
                '.ant-table-row',
                '.next-table-row',
                '.semi-table-row',
                '.arco-table-tr',
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


def _click_text(page, text: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (needle) => {
                  const nodes = Array.from(document.querySelectorAll('button,a,div,span'));
                  const node = nodes.find(n => (n.innerText || n.textContent || '').trim() === needle)
                    || nodes.find(n => (n.innerText || n.textContent || '').includes(needle));
                  if (!node) return false;
                  node.click();
                  return true;
                }
                """,
                text,
            )
        )
    except Exception:
        return False


def _collect_free_quota_text_across_tabs(page) -> str:
    parts = [_extract_console_text(page)]
    for tab in ("大语言模型", "视觉模型", "全模态模型", "语音模型", "向量模型", "全部模型"):
        if not _click_text(page, tab):
            continue
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass
        parts.append(_extract_console_text(page))
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for line in (part or "").splitlines():
            item = line.strip()
            if not item or item in seen:
                continue
            out.append(item)
            seen.add(item)
    return "\n".join(out)


def _capture_json_response(resp, captured: list[dict[str, Any]]) -> None:
    url = str(getattr(resp, "url", "") or "")
    lowered = url.lower()
    if not any(
        marker in lowered
        for marker in (
            "bailian-cs.console.aliyun.com",
            "costing",
            "quota",
            "balance",
            "workspace",
            "logininfo",
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


def run_collect_aliyun_quota_sync(
    *,
    models: Optional[list[str]] = None,
    all_free: bool = False,
    login_hold: int = 0,
    wait_timeout_ms: int = 120000,
    headless: Optional[bool] = None,
    visible_only: bool = False,
    quota_url: str = BAILIAN_FREE_QUOTA_URL,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """
    Read Aliyun Bailian free quota from the official console page.

    Alibaba's public docs expose free quota primarily in the Bailian console,
    not as a DashScope API-key balance endpoint. This browser reader avoids
    making model calls that would consume quota.
    """
    result: dict[str, Any] = {
        "source_url": quota_url,
        "source_mode": (
            "visible_page_only"
            if visible_only
            else "visible_page_with_console_api_capture_all_free"
            if all_free
            else "visible_page_with_console_api_capture"
        ),
        "usage_url": BAILIAN_USAGE_URL,
        "all_free": bool(all_free),
        "records": [],
        "raw_text": "",
        "console_api_payloads": [],
        "errors": [],
    }
    model_names = [] if all_free else _dedupe(models or aliyun_quota_model_candidates())
    headless_value = _env_flag("ALIYUN_CONSOLE_HEADLESS", False) if headless is None else bool(headless)
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
                if not visible_only:
                    page.on("response", lambda resp: _capture_json_response(resp, console_api_payloads))
                _emit(progress_callback, "open_quota_page", "in_progress", quota_url)
                page.goto(quota_url, wait_until="domcontentloaded")

                deadline = time.time() + max(1, wait_timeout_ms / 1000)
                login_deadline = time.time() + max(0, login_hold)
                body_text = ""
                while time.time() < deadline:
                    body_text = _read_body_text(page)
                    visible_login_required = bool(re.search(r"登录以使用|未登录状态|立即登录", body_text or ""))
                    if _looks_like_login_page(page, body_text) or visible_login_required:
                        if headless_value:
                            raise RuntimeError(
                                "Aliyun console login required but browser is headless; "
                                "run aliyun-quota once without --headless and log in to the workspace profile"
                            )
                        if login_hold <= 0 or time.time() >= login_deadline:
                            raise RuntimeError(
                                "Aliyun console login required; rerun with --login-hold 600 and finish login in the visible browser"
                            )
                        time.sleep(1)
                        continue
                    if model_names and any(model.lower() in body_text.lower() for model in model_names):
                        break
                    if any(hint in body_text for hint in ("模型名称", "剩余额度", "暂无符合条件的资源")):
                        break
                    time.sleep(1)

                _emit(progress_callback, "read_console_text", "in_progress", "")
                raw_text = _collect_free_quota_text_across_tabs(page)
                result["raw_text"] = raw_text
                result["console_api_payloads"] = console_api_payloads
                text_records = parse_aliyun_quota_text(raw_text, model_names, source_url=quota_url) if model_names else []
                if visible_only and all_free:
                    records = []
                    result["errors"].append(
                        "all-free Aliyun quota sync requires console API capture; disable --visible-only"
                    )
                elif visible_only:
                    records = _complete_aliyun_visible_only_records(text_records, model_names, source_url=quota_url)
                elif all_free:
                    records = parse_all_aliyun_console_api_quota(console_api_payloads, source_url=quota_url)
                else:
                    api_records = parse_aliyun_console_api_quota(
                        console_api_payloads,
                        model_names,
                        source_url=quota_url,
                    )
                    records_by_model = {record.model: record for record in api_records}
                    for record in text_records:
                        current = records_by_model.get(record.model)
                        if current is None or (current.remaining is None and record.remaining is not None):
                            records_by_model[record.model] = record
                    records = [records_by_model[model] for model in model_names if model in records_by_model]
                if _should_retry_aliyun_quota_after_login_transition(
                    raw_text,
                    console_api_payloads,
                    records,
                    visible_only=visible_only,
                ):
                    _emit(progress_callback, "reload_after_login", "in_progress", quota_url)
                    page.goto(quota_url, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(wait_timeout_ms, 30000))
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    raw_text = _collect_free_quota_text_across_tabs(page)
                    result["raw_text"] = raw_text
                    result["console_api_payloads"] = console_api_payloads
                    text_records = (
                        parse_aliyun_quota_text(raw_text, model_names, source_url=quota_url)
                        if model_names
                        else []
                    )
                    if all_free:
                        records = parse_all_aliyun_console_api_quota(console_api_payloads, source_url=quota_url)
                    else:
                        api_records = parse_aliyun_console_api_quota(
                            console_api_payloads,
                            model_names,
                            source_url=quota_url,
                        )
                        records_by_model = {record.model: record for record in api_records}
                        for record in text_records:
                            current = records_by_model.get(record.model)
                            if current is None or (current.remaining is None and record.remaining is not None):
                                records_by_model[record.model] = record
                        records = [records_by_model[model] for model in model_names if model in records_by_model]
                if not records and "模型Code" in raw_text:
                    records = [
                        AliyunQuotaRecord(
                            model=model,
                            kind=_classify_model(model),
                            status="not_found",
                            raw_text="target model not found in the visible Bailian free-quota tables",
                            source_url=quota_url,
                        )
                        for model in model_names
                    ]
                result["records"] = [record.to_dict() for record in records]
                for error in detect_aliyun_console_errors(raw_text, console_api_payloads):
                    if error == "aliyun_no_free_quota_rows_visible" and records:
                        continue
                    if error not in result["errors"]:
                        result["errors"].append(error)
                if not records:
                    result["errors"].append(
                        "no quota rows parsed; make sure the Bailian free-quota table is visible"
                    )
                unresolved = [] if all_free else [
                    record.model
                    for record in records
                    if record.status in {"not_found", "unknown", "not_visible_on_page", "quota_not_returned"}
                    or record.remaining is None
                ]
                if unresolved:
                    if visible_only:
                        result["errors"].append(
                            "free quota not visible on the Aliyun page for requested models: "
                            + ", ".join(unresolved)
                        )
                    else:
                        result["errors"].append(
                            "free quota not returned for requested Aliyun models: " + ", ".join(unresolved)
                        )
                _emit(progress_callback, "read_console_text", "success", f"records={len(records)}")
                return result
            finally:
                context.close()
    except Exception as exc:
        result["errors"].append(str(exc))
        _emit(progress_callback, "collect_quota", "failed", str(exc))
        return result
