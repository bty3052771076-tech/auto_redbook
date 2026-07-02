from __future__ import annotations

import base64
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

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedream-5-0-lite-260128"
DEFAULT_MODELS = [
    "doubao-seedream-5-0-lite-260128",
    "doubao-seedream-5-0-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
]
DEFAULT_SIZE = "1440x2560"  # Seedream 5.0 requires at least 3,686,400 pixels.
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_DOWNLOAD_TIMEOUT_S = 60.0

_EXT_RE = re.compile(r"\.(png|jpg|jpeg|webp)(?:$|[?#])", re.IGNORECASE)


@dataclass(frozen=True)
class VolcengineImageResult:
    path: Path
    meta: dict[str, Any]


@dataclass(frozen=True)
class VolcengineImageConfig:
    api_key: str
    base_url: str
    region: str = "cn-beijing"


class VolcengineImageAPIError(RuntimeError):
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
        super().__init__("Volcengine image API error: " + (": ".join(parts) if parts else "unknown"))


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


def load_volcengine_image_config(
    *,
    key_file: Path | str = Path("docs/volcengine_api-key.md"),
) -> VolcengineImageConfig:
    env_key = (
        os.getenv("VOLCENGINE_IMAGE_API_KEY")
        or os.getenv("VOLCENGINE_API_KEY")
        or os.getenv("ARK_API_KEY")
        or ""
    ).strip()
    env_base = (os.getenv("VOLCENGINE_IMAGE_BASE_URL") or os.getenv("ARK_BASE_URL") or "").strip()
    env_region = (os.getenv("VOLCENGINE_IMAGE_REGION") or os.getenv("ARK_REGION") or "").strip()

    file_cfg = _parse_kv_file(Path(key_file))
    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    base_url = (env_base or file_cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    region = (env_region or file_cfg.get("region") or "cn-beijing").strip()

    if not api_key:
        raise RuntimeError(
            "Volcengine/Ark api_key missing: set VOLCENGINE_IMAGE_API_KEY, "
            "VOLCENGINE_API_KEY, ARK_API_KEY, or create docs/volcengine_api-key.md"
        )
    return VolcengineImageConfig(api_key=api_key, base_url=base_url, region=region)


def _resolve_model_candidates(model: Optional[str]) -> list[str]:
    env_models = _split_models(os.getenv("VOLCENGINE_IMAGE_MODELS") or os.getenv("ARK_IMAGE_MODELS") or "")
    if env_models:
        return env_models
    single = (
        model
        or os.getenv("VOLCENGINE_IMAGE_MODEL")
        or os.getenv("ARK_IMAGE_MODEL")
        or DEFAULT_MODEL
    ).strip()
    return [single] if single else []


def _raise_api_error(*, url: str, status: Optional[int], raw: bytes, fallback_exc: Exception) -> None:
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        body = None
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise VolcengineImageAPIError(
            url=url,
            status=status,
            code=str(err.get("code") or body.get("code") or "") or None,
            message=str(err.get("message") or body.get("message") or "") or None,
            response=body,
        ) from fallback_exc
    raise VolcengineImageAPIError(url=url, status=status, code=None, message=str(fallback_exc)) from fallback_exc


def _http_post_json(*, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        _raise_api_error(url=url, status=getattr(exc, "code", None), raw=raw, fallback_exc=exc)
        raise
    except Exception as exc:
        raise RuntimeError(f"Volcengine image request failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Volcengine image response parse failed: {exc}") from exc


def _download_bytes(*, url: str, timeout_s: float, api_key: str | None = None) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (redbook_workflow)"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except Exception as exc:
        if api_key:
            req_no_auth = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req_no_auth, timeout=timeout_s) as resp:
                    return resp.read()
            except Exception:
                pass
        raise RuntimeError(f"Volcengine image download failed: {exc}") from exc


def _should_try_next_model(exc: Exception) -> bool:
    if isinstance(exc, VolcengineImageAPIError):
        code = (exc.code or "").lower()
        msg = (exc.message or str(exc) or "").lower()
    else:
        code = ""
        msg = str(exc or "").lower()
    keywords = (
        "quota",
        "out of quota",
        "insufficient",
        "balance",
        "limit",
        "throttl",
        "rate",
        "exceeded",
        "model not found",
        "unsupported",
        "not support",
        "invalid model",
        "no available",
        "余额",
        "配额",
        "限流",
        "不足",
        "超限",
    )
    return any(k in code or k in msg for k in keywords)


def _guess_ext(url: str) -> str:
    m = _EXT_RE.search(url or "")
    if not m:
        return ".png"
    ext = m.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    return f".{ext}"


def _extract_image_data(resp: dict[str, Any]) -> tuple[str | None, bytes | None, str]:
    data = resp.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("Volcengine image response missing data")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError("Volcengine image response data item is not an object")
    url = first.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip(), None, str(first.get("size") or "")
    b64 = first.get("b64_json")
    if isinstance(b64, str) and b64.strip():
        return None, base64.b64decode(b64), str(first.get("size") or "")
    raise RuntimeError("Volcengine image response missing image url/b64_json")


def generate_volcengine_image(
    *,
    post_id: str,
    prompt: str,
    dest_dir: Path,
    timeout_s: Optional[float] = None,
    download_timeout_s: Optional[float] = None,
    model: Optional[str] = None,
    size: Optional[str] = None,
    watermark: Optional[bool] = None,
) -> VolcengineImageResult:
    """
    Generate ONE image via Volcengine Ark Seedream and download it locally.

    Ark image generation uses an OpenAI-compatible endpoint:
    POST {base_url}/images/generations
    """
    cfg = load_volcengine_image_config()
    model_candidates = _resolve_model_candidates(model)
    size_value = (size or os.getenv("VOLCENGINE_IMAGE_SIZE") or DEFAULT_SIZE).strip()
    timeout_s = float(os.getenv("VOLCENGINE_IMAGE_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    download_timeout_s = float(
        os.getenv("VOLCENGINE_IMAGE_DOWNLOAD_TIMEOUT_S")
        or (download_timeout_s or DEFAULT_DOWNLOAD_TIMEOUT_S)
    )
    if watermark is None:
        raw = (os.getenv("VOLCENGINE_IMAGE_WATERMARK") or "").strip().lower()
        watermark = raw in ("1", "true", "yes", "on") if raw else False

    last_exc: Optional[Exception] = None
    for idx, model_name in enumerate(model_candidates or []):
        url = f"{cfg.base_url}/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        }
        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "size": size_value,
            "response_format": "url",
            "watermark": bool(watermark),
            "sequential_image_generation": "disabled",
        }

        print(f"[volcengine-image] model={model_name} size={size_value}")
        try:
            create_resp = _http_post_json(url=url, payload=payload, headers=headers, timeout_s=timeout_s)
            image_url, image_bytes, returned_size = _extract_image_data(create_resp)
            if image_bytes is None:
                if not image_url:
                    raise RuntimeError("Volcengine image URL is empty")
                image_bytes = _download_bytes(
                    url=image_url,
                    timeout_s=download_timeout_s,
                    api_key=cfg.api_key,
                )

            dest_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            ext = _guess_ext(image_url or "") if image_url else ".png"
            out_path = dest_dir / f"ai_volcengine_{ts}{ext}"
            out_path.write_bytes(image_bytes)

            meta: dict[str, Any] = {
                "mode": "volcengine_image",
                "provider": "volcengine",
                "post_id": post_id,
                "region": cfg.region,
                "model": model_name,
                "size": size_value,
                "returned_size": returned_size,
                "prompt": prompt,
                "watermark": bool(watermark),
                "src_url": image_url,
                "downloaded_path": str(out_path),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "usage": create_resp.get("usage"),
            }
            return VolcengineImageResult(path=out_path, meta=meta)
        except Exception as exc:
            last_exc = exc
            if idx + 1 < len(model_candidates) and _should_try_next_model(exc):
                time.sleep(0.2)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("No usable Volcengine image models resolved.")
