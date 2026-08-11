from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.config import SILICONFLOW_FREE_LLM_MODELS, SILICONFLOW_IMAGE_MODELS


SILICONFLOW_MODELS_URL = "https://api.siliconflow.cn/v1/models"
SILICONFLOW_USER_INFO_URL = "https://api.siliconflow.cn/v1/user/info"
SILICONFLOW_CONSOLE_MODELS_URL = "https://cloud.siliconflow.cn/me/models?types=to-image"
SILICONFLOW_API_DOC_URL = "https://docs.siliconflow.cn/cn/api-reference/models/get-model-list"
DEFAULT_SILICONFLOW_IMAGE_QUOTA_MODELS = list(SILICONFLOW_IMAGE_MODELS)

# Authoritative pricing from the official console biz-info API (2026-08-10):
# stdUnitPrice in 1e-12 CNY; 0 means the model is free.
_SILICONFLOW_PRICING_URL_PREFIX = "https://cloud.siliconflow.cn/biz-server/api/v1/playground/"
_SILICONFLOW_KNOWN_IMAGE_PRICES = {
    "tongyi-mai/z-image-turbo.online.image-cnt": 0.10,
    "tongyi-mai/z-image.online.image-cnt": 0.30,
    "baidu/ernie-image-turbo.online.image-cnt": 0.11,
    "qwen/qwen-image-edit-2509.online.image-cnt": 0.30,
    "qwen/qwen-image-edit.online.image-cnt": 0.30,
    "qwen/qwen-image.online.image-cnt": 0.30,
    "free-image-model.online.image-cnt": 0.0,
}


@dataclass(frozen=True)
class SiliconflowQuotaRecord:
    model: str
    kind: str = "unknown"
    total: int | float | None = None
    used: int | float | None = None
    remaining: int | float | None = None
    unit: str = ""
    expires_at: str = ""
    status: str = "unknown"
    raw_text: str = ""
    source_url: str = SILICONFLOW_MODELS_URL

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
        name in {item.lower() for item in SILICONFLOW_IMAGE_MODELS}
        or any(marker in name for marker in ("image", "kolors", "flux", "stable-diffusion", "sdxl", "sd-", "wanx", "t2i"))
    ):
        return "image"
    if any(
        marker in name
        for marker in (
            "embedding",
            "reranker",
            "rerank",
            "bge-",
            "moderation",
            "speech",
            "tts",
            "captioner",
            "ocr",
        )
    ):
        return "unsupported"
    if name.startswith(("pro/", "pro-")):
        return "llm"
    if any(marker in name for marker in ("deepseek", "qwen", "glm", "kimi", "moonshot", "yi-", "minimax", "doubao")):
        return "llm"
    return "llm"


def _free_image_model_ids() -> set[str]:
    """Return user-facing model names whose official price is exactly 0 (free to use)."""
    free: set[str] = set()
    # Console pricing object codes map to these user-facing model names.
    free.add("kwai-kolors/kolors")
    for object_code, price in _SILICONFLOW_KNOWN_IMAGE_PRICES.items():
        if price is None or price <= 0:
            normalized = object_code.split(".online.", 1)[0].lower().replace("-", "/")
            if normalized:
                free.add(normalized)
    return free


def _is_free_image_model(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    if name in _free_image_model_ids():
        return True
    # free-image-model is the console's object code for zero-price generation;
    # the plaza card may show the user-facing model name instead.
    if name.startswith("free-image-model"):
        return True
    return False


def siliconflow_quota_model_candidates(
    *,
    llm_models: Optional[Iterable[str]] = None,
    image_models: Optional[Iterable[str]] = None,
    env: Optional[dict[str, str]] = None,
) -> list[str]:
    env = env if env is not None else os.environ
    if llm_models is None:
        env_llm_models = _split_values(env.get("SILICONFLOW_LLM_MODELS", ""))
        if env_llm_models:
            llm = env_llm_models
        else:
            single = (env.get("SILICONFLOW_LLM_MODEL") or "").strip()
            llm = [single] if single else list(SILICONFLOW_FREE_LLM_MODELS)
    else:
        llm = list(llm_models)

    if image_models is None:
        env_image_models = _split_values(env.get("SILICONFLOW_IMAGE_MODELS", ""))
        if env_image_models:
            images = env_image_models
        else:
            single = (env.get("SILICONFLOW_IMAGE_MODEL") or "").strip()
            images = [single] if single else list(DEFAULT_SILICONFLOW_IMAGE_QUOTA_MODELS)
    else:
        images = list(image_models)

    return _dedupe([*llm, *images])


def _load_api_key(*, key_file: Path | str = Path("docs/siliconflow_api-key.md")) -> str:
    env_key = (
        os.getenv("SILICONFLOW_LLM_API_KEY")
        or os.getenv("SILICONFLOW_API_KEY")
        or os.getenv("SF_API_KEY")
        or ""
    ).strip()
    if env_key:
        return env_key
    path = Path(key_file)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() in {"api_key", "apikey", "key"}:
            return value.strip().strip('"').strip("'")
    return ""


def _api_get_json(*, url: str, api_key: str, timeout_s: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        status = exc.code
        raise RuntimeError(f"SiliconFlow API HTTP {status}: {raw[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SiliconFlow API network error: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"SiliconFlow API non-JSON response (status={status}): {raw[:200]}") from exc
    if isinstance(data, dict) and data.get("code") not in (None, "0", 0, 200, "200", 20000, "20000"):
        code = data.get("code")
        message = data.get("message")
        if str(code) not in ("", "0") and message:
            raise RuntimeError(f"SiliconFlow API error {code}: {message}")
    return data


def _emit(progress_callback: Optional[Callable[[str], None]], name: str, status: str, detail: str = "") -> None:
    if not progress_callback:
        return
    message = f"[siliconflow-quota] {name}: {status}"
    if detail:
        message += f" | {detail}"
    try:
        progress_callback(message)
    except Exception:
        pass


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
    user_data_dir = (os.getenv("SILICONFLOW_CONSOLE_USER_DATA_DIR") or "").strip()
    profile_dir = (
        Path(user_data_dir)
        if user_data_dir
        else _repo_root() / "data" / "browser" / "siliconflow-console-profile"
    )
    channel = (os.getenv("SILICONFLOW_BROWSER_CHANNEL") or "chrome").strip() or None
    args: list[str] = []
    profile_name = (os.getenv("SILICONFLOW_CHROME_PROFILE") or "").strip()
    if profile_name:
        args.append(f"--profile-directory={profile_name}")
    return profile_dir, channel, args


def _read_body_text(page, *, timeout_ms: int = 2000, max_chars: int = 50000) -> str:
    try:
        page.wait_for_timeout(min(500, max(10, timeout_ms // 4)))
        text = page.evaluate("document.body ? document.body.innerText : ''")
        return str(text or "")[:max_chars]
    except Exception:
        return ""


def _looks_like_login_page(page, body_text: str) -> bool:
    url = ""
    try:
        url = str(page.url or "")
    except Exception:
        pass
    haystack = "\n".join([url, body_text or ""]).lower()
    login_hints = ("login", "signin", "登录", "扫码", "验证码", "账号密码")
    strong_login = (
        "欢迎登录",
        "注册 / 登录",
        "注册/登录",
        "获取验证码",
        "微信登录",
        "邮箱登录",
        "密码登录",
        "短信登录",
    )
    quota_hints = ("额度", "余额", "免费")
    if any(hint in body_text for hint in strong_login):
        return True
    if any(hint in body_text for hint in quota_hints):
        return False
    return any(hint in haystack for hint in login_hints)


def _extract_console_text(page) -> str:
    try:
        return str(page.evaluate("document.body ? document.body.innerText : ''") or "").strip()
    except Exception:
        return ""


def _parse_visible_model_lines(text: str, model_names: list[str]) -> list[SiliconflowQuotaRecord]:
    records: list[SiliconflowQuotaRecord] = []
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    targets = [model.lower() for model in model_names]
    seen: set[str] = set()
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        matched = [model for model in model_names if model.lower() in line_lower]
        if not matched:
            continue
        model = matched[0]
        if model in seen:
            continue
        seen.add(model)
        window = "\n".join(lines[idx : min(len(lines), idx + 12)])
        window_no_model = re.sub(re.escape(model), " ", window, flags=re.IGNORECASE)
        numbers = re.findall(r"\d{1,3}(?:,\d{3})+|\d+", window_no_model)
        status = "not_visible_on_page"
        remaining = used = total = None
        if any(marker in line for marker in ("免费", "free", "Free")):
            status = "available"
            if numbers:
                total = _parse_int(numbers[0])
                remaining = total
        elif any(marker in line for marker in ("已用", "剩余", "余额")):
            status = "available"
            parsed = [_parse_int(n) for n in numbers]
            parsed = [n for n in parsed if n is not None]
            if parsed:
                if len(parsed) >= 3:
                    used, remaining, total = parsed[:3]
                elif len(parsed) == 2:
                    used, total = parsed[:2]
                    remaining = max(0, total - used) if total is not None else None
                else:
                    total = parsed[0]
                    remaining = total
        records.append(
            SiliconflowQuotaRecord(
                model=model,
                kind=_classify_model(model),
                total=total,
                used=used,
                remaining=remaining,
                unit="token",
                expires_at="",
                status=status,
                raw_text=window,
                source_url=SILICONFLOW_CONSOLE_MODELS_URL,
            )
        )
    return records


def _parse_int(value: str) -> int | float | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _api_model_records(*, api_key: str, timeout_s: float) -> list[SiliconflowQuotaRecord]:
    records: list[SiliconflowQuotaRecord] = []
    for model_type in ("text", "image"):
        url = f"{SILICONFLOW_MODELS_URL}?type={model_type}"
        try:
            data = _api_get_json(url=url, api_key=api_key, timeout_s=timeout_s)
        except Exception:
            continue
        items = data.get("data") or []
        for item in items:
            model = str(item.get("id") or "").strip()
            if not model:
                continue
            kind = "image" if model_type == "image" else _classify_model(model)
            free = model_type == "image" and _is_free_image_model(model)
            records.append(
                SiliconflowQuotaRecord(
                    model=model,
                    kind=kind,
                    total=None,
                    used=None,
                    remaining=None if not free else 1_000_000,
                    unit="" if not free else "张(免费)",
                    expires_at="",
                    status="available" if free else "quota_not_returned",
                    raw_text=json.dumps(item, ensure_ascii=False)[:500],
                    source_url=url,
                )
            )
    return records


def _api_user_info(*, api_key: str, timeout_s: float = 30.0) -> dict[str, Any]:
    try:
        data = _api_get_json(url=SILICONFLOW_USER_INFO_URL, api_key=api_key, timeout_s=timeout_s)
    except Exception:
        return {}
    payload = data.get("data") if isinstance(data, dict) else None
    return payload if isinstance(payload, dict) else {}


def format_siliconflow_quota_records(records: Iterable[SiliconflowQuotaRecord | dict[str, Any]]) -> str:
    rows: list[SiliconflowQuotaRecord] = []
    for record in records:
        if isinstance(record, dict):
            rows.append(SiliconflowQuotaRecord(**{k: v for k, v in record.items() if k in SiliconflowQuotaRecord.__dataclass_fields__}))
        else:
            rows.append(record)
    if not rows:
        return "No matching SiliconFlow quota rows were parsed."
    header = f"{'model':<45} {'kind':<8} {'status':<20} {'remaining':>10} {'used':>10} {'total':>10} {'unit':<8} {'expires_at':<12}"
    lines = [header, "-" * len(header)]
    for record in sorted(rows, key=lambda item: (item.model or "").lower()):
        lines.append(
            f"{record.model:<45} {record.kind:<8} {record.status:<20} "
            f"{str(record.remaining if record.remaining is not None else 'unknown'):>10} "
            f"{str(record.used if record.used is not None else 'unknown'):>10} "
            f"{str(record.total if record.total is not None else 'unknown'):>10} "
            f"{record.unit:<8} {record.expires_at:<12}"
        )
    return "\n".join(lines)


def run_collect_siliconflow_quota_sync(
    *,
    models: Optional[list[str]] = None,
    all_free: bool = False,
    login_hold: int = 0,
    wait_timeout_ms: int = 120_000,
    headless: Optional[bool] = None,
    visible_only: bool = False,
    quota_url: str = SILICONFLOW_CONSOLE_MODELS_URL,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """
    Read SiliconFlow model info and free-quota hints.

    Model availability comes from the official model-list API (needs API key).
    Remaining/free quota is exposed in the cloud console page (login required);
    the browser reader reuses the workspace-local profile so credentials stay local.
    """
    result: dict[str, Any] = {
        "source_url": quota_url,
        "source_mode": (
            "visible_page_only"
            if visible_only
            else "api_model_list_with_visible_page_all_free"
            if all_free
            else "api_model_list_with_visible_page"
        ),
        "model_list_api_url": SILICONFLOW_MODELS_URL,
        "user_info_api_url": SILICONFLOW_USER_INFO_URL,
        "api_doc_url": SILICONFLOW_API_DOC_URL,
        "all_free": bool(all_free),
        "records": [],
        "raw_text": "",
        "console_api_payloads": [],
        "errors": [],
    }
    model_names = [] if all_free else _dedupe(models or siliconflow_quota_model_candidates())
    headless_value = _env_flag("SILICONFLOW_CONSOLE_HEADLESS", False) if headless is None else bool(headless)
    profile_dir, channel, args = _resolve_profile_config()
    profile_dir.mkdir(parents=True, exist_ok=True)
    api_key = _load_api_key()

    records: list[SiliconflowQuotaRecord] = []
    user_info: dict[str, Any] = {}
    if api_key:
        try:
            _emit(progress_callback, "list_models_api", "in_progress", "type=text,image")
            api_records = _api_model_records(api_key=api_key, timeout_s=30.0)
            if all_free:
                records = api_records
            else:
                by_model = {record.model.lower(): record for record in api_records}
                records = [by_model[model.lower()] for model in model_names if model.lower() in by_model]
            result["console_api_payloads"] = [record.raw_text for record in records]
            _emit(progress_callback, "list_models_api", "success", f"records={len(records)}")
        except Exception as exc:
            result["errors"].append(f"model-list API failed: {exc}")
            _emit(progress_callback, "list_models_api", "warning", str(exc))
        user_info = _api_user_info(api_key=api_key)
        if user_info:
            balance = user_info.get("balance")
            if balance is not None and str(balance).strip() not in ("", "0", "0.0"):
                records.insert(
                    0,
                    SiliconflowQuotaRecord(
                        model="__account_balance__",
                        kind="unknown",
                        total=_parse_int(str(balance)),
                        used=None,
                        remaining=_parse_int(str(balance)),
                        unit="CNY",
                        expires_at="",
                        status="available",
                        raw_text=json.dumps(user_info, ensure_ascii=False)[:500],
                        source_url=SILICONFLOW_USER_INFO_URL,
                    ),
                )
    else:
        result["errors"].append(
            "SiliconFlow API key not configured; model list will be read from the visible console page only"
        )
    result["user_info"] = user_info

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment issue
        result["errors"].append(f"Playwright is not available: {exc}")
        result["records"] = [record.to_dict() for record in records]
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
                _emit(progress_callback, "open_models_page", "in_progress", quota_url)
                page.goto(quota_url, wait_until="domcontentloaded")

                deadline = time.time() + max(1, wait_timeout_ms / 1000)
                login_deadline = time.time() + max(0, login_hold)
                body_text = ""
                while time.time() < deadline:
                    body_text = _read_body_text(page)
                    if _looks_like_login_page(page, body_text):
                        if headless_value:
                            raise RuntimeError(
                                "SiliconFlow console login required but browser is headless; "
                                "run siliconflow-quota once without --headless and log in to the workspace profile"
                            )
                        if login_hold <= 0 or time.time() >= login_deadline:
                            raise RuntimeError(
                                "SiliconFlow console login required; rerun with --login-hold 600 and finish login in the visible browser"
                            )
                        time.sleep(1)
                        continue
                    if "模型" in body_text or "模型广场" in body_text:
                        break
                    time.sleep(1)

                _emit(progress_callback, "read_console_text", "in_progress", "")
                raw_text = _extract_console_text(page)
                result["raw_text"] = raw_text
                visible_records = _parse_visible_model_lines(raw_text, model_names or siliconflow_quota_model_candidates())
                if records:
                    by_model = {record.model.lower(): record for record in records}
                    for visible in visible_records:
                        if visible.model.lower() not in by_model:
                            records.append(visible)
                else:
                    records = visible_records
                _emit(progress_callback, "read_console_text", "success", f"records={len(records)}")
            finally:
                try:
                    context.close()
                except Exception:
                    pass
    except Exception as exc:
        result["errors"].append(str(exc))
        _emit(progress_callback, "collect_quota", "failed", str(exc))

    result["records"] = [record.to_dict() for record in records]
    return result
