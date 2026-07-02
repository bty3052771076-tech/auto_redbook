from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import DEFAULT_VOLCENGINE_LLM_MODEL, VOLCENGINE_AVAILABLE_LLM_MODELS


VOLCENGINE_ARK_USAGE_URL = "https://console.volcengine.com/ark/region:cn-beijing/usage"
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
    if "seedream" in name or "image" in name or "seedance" in name:
        return "image"
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
            single = (env.get("VOLCENGINE_LLM_MODEL") or DEFAULT_VOLCENGINE_LLM_MODEL).strip()
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
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


NUMBER_RE = re.compile(r"(?<![\w.-])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.-])")


def _numbers_without_dates(text: str) -> list[int | float]:
    without_dates = re.sub(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", " ", text or "")
    numbers: list[int | float] = []
    for match in NUMBER_RE.finditer(without_dates):
        parsed = _parse_number(match.group(0))
        if parsed is not None:
            numbers.append(parsed)
    return numbers


def _number_after_labels(text: str, labels: Iterable[str]) -> int | float | None:
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
    for idx, line in enumerate(lines):
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
        windows[current] = "\n".join(lines[idx:end])
    return windows


def _parse_quota_values(raw_text: str) -> tuple[int | float | None, int | float | None, int | float | None]:
    total = _number_after_labels(raw_text, ["总额度", "总量", "免费额度", "免费推理额度", "额度总量", "总计"])
    used = _number_after_labels(raw_text, ["已用额度", "已用量", "已使用", "已用", "使用量"])
    remaining = _number_after_labels(raw_text, ["剩余额度", "剩余量", "剩余", "可用额度", "可用"])

    if total is not None or used is not None or remaining is not None:
        return total, used, remaining

    ratio_match = re.search(rf"({NUMBER_RE.pattern})\s*/\s*({NUMBER_RE.pattern})", raw_text or "")
    if ratio_match:
        first = _parse_number(ratio_match.group(1))
        second = _parse_number(ratio_match.group(2))
        if first is not None and second is not None:
            return second, None, first

    numbers = _numbers_without_dates(raw_text)
    if len(numbers) >= 3:
        return numbers[0], numbers[1], numbers[2]
    if len(numbers) == 2:
        return numbers[1], None, numbers[0]
    if len(numbers) == 1:
        return None, None, numbers[0]
    return None, None, None


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
        total, used, remaining = _parse_quota_values(raw_text)
        records.append(
            VolcengineQuotaRecord(
                model=model,
                kind=_classify_model(model),
                total=total,
                used=used,
                remaining=remaining,
                unit=_detect_unit(raw_text),
                expires_at=_normalize_date(raw_text),
                raw_text=raw_text,
                source_url=source_url,
            )
        )
    return records


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
        "model | kind | remaining | used | total | unit | expires_at",
        "--- | --- | ---: | ---: | ---: | --- | ---",
    ]
    has_unknown = False
    for record in normalized:
        has_unknown = has_unknown or record.remaining is None
        lines.append(
            " | ".join(
                [
                    record.model,
                    record.kind,
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
            "open the official Volcengine Ark console and expand the usage/free-quota table if needed."
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
        return str(page.locator("body").inner_text(timeout=timeout_ms) or "")[:max_chars]
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


def run_collect_volcengine_quota_sync(
    *,
    models: Optional[list[str]] = None,
    login_hold: int = 0,
    wait_timeout_ms: int = 120000,
    headless: Optional[bool] = None,
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
        "free_quota_doc_url": VOLCENGINE_ARK_FREE_QUOTA_DOC_URL,
        "model_list_doc_url": VOLCENGINE_ARK_MODEL_LIST_DOC_URL,
        "records": [],
        "raw_text": "",
        "errors": [],
    }
    model_names = _dedupe(models or volcengine_quota_model_candidates())
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
                _emit(progress_callback, "open_usage_page", "in_progress", quota_url)
                page.goto(quota_url, wait_until="domcontentloaded")

                deadline = time.time() + max(1, wait_timeout_ms / 1000)
                login_deadline = time.time() + max(0, login_hold)
                body_text = ""
                while time.time() < deadline:
                    body_text = _read_body_text(page)
                    if any(model.lower() in body_text.lower() for model in model_names):
                        break
                    if any(hint in body_text for hint in ("用量统计", "免费推理额度", "剩余额度", "模型名称")):
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
                records = parse_volcengine_quota_text(raw_text, model_names, source_url=quota_url)
                result["records"] = [record.to_dict() for record in records]
                if not records:
                    result["errors"].append(
                        "no quota rows parsed; make sure the Ark usage/free-quota table is visible"
                    )
                _emit(progress_callback, "read_console_text", "success", f"records={len(records)}")
                return result
            finally:
                context.close()
    except Exception as exc:
        result["errors"].append(str(exc))
        _emit(progress_callback, "collect_quota", "failed", str(exc))
        return result
