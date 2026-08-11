from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Kwai-Kolors/Kolors"
DEFAULT_MODELS = [
    "Kwai-Kolors/Kolors",
    "Kwai-Kolors/Kolors-Flash",
    "Qwen/Qwen-Image",
    "Qwen/Qwen-Image-Edit",
    "stabilityai/stable-diffusion-3-5-large",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "black-forest-labs/FLUX.1-schnell",
    "black-forest-labs/FLUX.1-dev",
]
DEFAULT_SIZE = "1140x1472"  # 3:4 (适合小红书竖图)
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_DOWNLOAD_TIMEOUT_S = 60.0

_EXT_RE = re.compile(r"\.(png|jpg|jpeg|webp)(?:$|[?#])", re.IGNORECASE)


@dataclass(frozen=True)
class SiliconflowImageResult:
    path: Path
    meta: dict[str, Any]


@dataclass(frozen=True)
class SiliconflowImageConfig:
    api_key: str
    base_url: str


class SiliconflowImageAPIError(RuntimeError):
    def __init__(
        self,
        *,
        url: str,
        status: Optional[int],
        code: Optional[str],
        message: Optional[str],
        response: Optional[dict[str, Any]] = None,
    ):
        self.url = url
        self.status = status
        self.code = code
        self.message = message
        self.response = response
        parts = []
        if status is not None:
            parts.append(str(status))
        if code:
            parts.append(str(code))
        if message:
            parts.append(str(message))
        super().__init__("SiliconFlow image API error: " + (": ".join(parts) if parts else "unknown"))


def _split_models(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"[,\s]+", raw) if p and p.strip()]


def _parse_kv_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_siliconflow_image_config(
    *,
    key_file: Path | str = Path("docs/siliconflow_api-key.md"),
) -> SiliconflowImageConfig:
    env_key = (
        os.getenv("SILICONFLOW_IMAGE_API_KEY")
        or os.getenv("SILICONFLOW_API_KEY")
        or os.getenv("SF_API_KEY")
        or ""
    ).strip()
    env_base = (
        os.getenv("SILICONFLOW_IMAGE_BASE_URL")
        or os.getenv("SILICONFLOW_LLM_BASE_URL")
        or os.getenv("SF_BASE_URL")
        or ""
    ).strip()

    file_cfg = _parse_kv_file(Path(key_file))
    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    base_url = (env_base or file_cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")

    if not api_key:
        raise RuntimeError(
            "SiliconFlow api_key missing: set SILICONFLOW_API_KEY (or SILICONFLOW_IMAGE_API_KEY), "
            "or create docs/siliconflow_api-key.md"
        )
    return SiliconflowImageConfig(api_key=api_key, base_url=base_url)


def _user_balance(api_key: str, base_url: str, timeout_s: float = 20.0) -> float | None:
    """Read account balance from user/info without calling billable models."""
    url = f"{base_url.rstrip('/')}/user/info"
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
        data = json.loads(raw)
    except Exception:
        return None
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None
    balance = str(payload.get("balance") or "").strip()
    try:
        return float(balance) if balance else 0.0
    except ValueError:
        return None


def _image_price_cny(model: str) -> float | None:
    """Known per-image price in CNY; None means unknown, 0.0 means free."""
    name = (model or "").strip().lower()
    if "kolors" in name:
        return 0.0
    if "z-image-turbo" in name:
        return 0.10
    if "ernie-image-turbo" in name:
        return 0.11
    if "qwen-image" in name:
        return 0.30
    if "z-image" in name:
        return 0.30
    return None


def _resolve_model_candidates(model: Optional[str]) -> list[str]:
    env_models = _split_models(
        os.getenv("SILICONFLOW_IMAGE_MODELS") or os.getenv("SF_IMAGE_MODELS") or ""
    )
    if env_models:
        return env_models
    single = (model or os.getenv("SILICONFLOW_IMAGE_MODEL") or os.getenv("SF_IMAGE_MODEL") or "").strip()
    if single:
        return [single]
    return list(DEFAULT_MODELS)


def _post_json(
    *,
    cfg: SiliconflowImageConfig,
    path: str,
    payload: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    url = f"{cfg.base_url.rstrip('/')}/{path.lstrip('/')}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
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
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        raise SiliconflowImageAPIError(
            url=url,
            status=status,
            code=str(data.get("code") or "") if isinstance(data, dict) else "",
            message=str(data.get("message") or raw[:300] or "") if isinstance(data, dict) else raw[:300],
            response=data if isinstance(data, dict) else None,
        ) from exc
    except urllib.error.URLError as exc:
        raise SiliconflowImageAPIError(
            url=url,
            status=None,
            code="",
            message=str(exc.reason),
        ) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SiliconflowImageAPIError(
            url=url,
            status=status,
            code="",
            message=f"non-JSON response: {raw[:200]}",
        ) from exc


def _download_image(*, url: str, dest_dir: Path, timeout_s: float) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    ext_match = _EXT_RE.search(url)
    ext = f".{ext_match.group(1)}" if ext_match else ".png"
    dest = dest_dir / f"siliconflow_{stamp}{ext}"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
    return dest


def generate_siliconflow_image(
    *,
    post_id: str,
    prompt: str,
    dest_dir: Path,
    timeout_s: Optional[float] = None,
    download_timeout_s: Optional[float] = None,
    model: Optional[str] = None,
    size: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
) -> SiliconflowImageResult:
    """Generate ONE image via SiliconFlow images/generations and download it."""
    cfg = load_siliconflow_image_config()
    model_candidates = _resolve_model_candidates(model)
    if os.getenv("SILICONFLOW_FREE_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
        paid = [candidate for candidate in model_candidates if _image_price_cny(candidate) not in (None, 0.0)]
        if paid:
            raise SiliconflowImageAPIError(
                url=f"{cfg.base_url}/images/generations",
                status=None,
                code="",
                message=(
                    "SILICONFLOW_FREE_ONLY=1 and the selected model is not free: "
                    f"{paid[0]}. Use Kwai-Kolors/Kolors (free) or set SILICONFLOW_FREE_ONLY=0 explicitly."
                ),
            )
    size_value = (size or os.getenv("SILICONFLOW_IMAGE_SIZE") or DEFAULT_SIZE).strip()
    timeout_s = float(os.getenv("SILICONFLOW_IMAGE_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    download_timeout_s = float(
        os.getenv("SILICONFLOW_IMAGE_DOWNLOAD_TIMEOUT_S") or (download_timeout_s or DEFAULT_DOWNLOAD_TIMEOUT_S)
    )
    env_negative = os.getenv("SILICONFLOW_IMAGE_NEGATIVE_PROMPT")
    negative_prompt = "" if env_negative is None else (env_negative or "").strip() if negative_prompt is None else negative_prompt
    if num_inference_steps is None:
        env_steps = os.getenv("SILICONFLOW_IMAGE_NUM_INFERENCE_STEPS")
        num_inference_steps = int(env_steps) if env_steps and env_steps.strip().isdigit() else None
    if guidance_scale is None:
        env_scale = os.getenv("SILICONFLOW_IMAGE_GUIDANCE_SCALE")
        guidance_scale = float(env_scale) if env_scale else None

    last_exc: Optional[Exception] = None
    for model_name in model_candidates:
        price = _image_price_cny(model_name)
        balance = _user_balance(cfg.api_key, cfg.base_url)
        if price is not None and price > 0 and balance is not None and balance <= 0:
            raise SiliconflowImageAPIError(
                url=f"{cfg.base_url}/images/generations",
                status=None,
                code="",
                message=(
                    f"refusing paid image generation: {model_name} costs {price:.2f} CNY/image "
                    "and account balance is 0. Only free models (Kwai-Kolors/Kolors) are allowed "
                    "when balance is zero."
                ),
            )
        print(f"[siliconflow-image] model={model_name} size={size_value}")
        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "image_size": size_value,
            "batch_size": 1,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if num_inference_steps is not None:
            payload["num_inference_steps"] = num_inference_steps
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        try:
            data = _post_json(
                cfg=cfg,
                path="images/generations",
                payload=payload,
                timeout_s=timeout_s,
            )
            images = (data or {}).get("images") or []
            if not images:
                raise SiliconflowImageAPIError(
                    url=f"{cfg.base_url}/images/generations",
                    status=200,
                    code="",
                    message="response contains no images",
                    response=data,
                )
            image_url = str(images[0].get("url") or "").strip()
            if not image_url:
                raise SiliconflowImageAPIError(
                    url=f"{cfg.base_url}/images/generations",
                    status=200,
                    code="",
                    message="first image entry has no url",
                    response=data,
                )
            path = _download_image(url=image_url, dest_dir=dest_dir, timeout_s=download_timeout_s)
            meta = {
                "provider": "siliconflow",
                "model": model_name,
                "size": size_value,
                "url": image_url,
                "seed": data.get("seed"),
                "timings": data.get("timings"),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            return SiliconflowImageResult(path=path, meta=meta)
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise SiliconflowImageAPIError(
        url=f"{cfg.base_url}/images/generations",
        status=None,
        code="",
        message="no model candidates",
    )
