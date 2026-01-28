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

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
DEFAULT_MODEL = "qwen-image-plus"
DEFAULT_SIZE = "1104*1472"  # 3:4 (适合小红书竖图)
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_DOWNLOAD_TIMEOUT_S = 60.0
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_POLL_TIMEOUT_S = 240.0
DEFAULT_TASK_QUERY_TIMEOUT_S = 30.0

_EXT_RE = re.compile(r"\.(png|jpg|jpeg|webp)(?:$|[?#])", re.IGNORECASE)


@dataclass(frozen=True)
class AliyunImageResult:
    path: Path
    meta: dict[str, Any]


@dataclass(frozen=True)
class AliyunImageConfig:
    api_key: str
    base_url: str
    region: str


class AliyunImageAPIError(RuntimeError):
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
        super().__init__("Aliyun image API error: " + (": ".join(parts) if parts else "unknown"))


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
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


def load_aliyun_image_config(*, key_file: Path | str = Path("docs/aliyun_image_api-key.md")) -> AliyunImageConfig:
    """
    Load DashScope (阿里云百炼) image config.

    Priority:
      1) env: ALIYUN_IMAGE_API_KEY / ALIYUN_IMAGE_BASE_URL / ALIYUN_IMAGE_REGION
      2) env: DASHSCOPE_API_KEY (compat)
      3) file: docs/aliyun_image_api-key.md (local-only, should be gitignored)
    """
    env_key = (os.getenv("ALIYUN_IMAGE_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    env_base = (os.getenv("ALIYUN_IMAGE_BASE_URL") or "").strip()
    env_region = (os.getenv("ALIYUN_IMAGE_REGION") or "").strip()

    file_cfg = _parse_kv_file(Path(key_file))
    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    base_url = (env_base or file_cfg.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    region = (env_region or file_cfg.get("region") or "cn-beijing").strip()

    if not api_key:
        raise RuntimeError(
            "Aliyun/DashScope api_key missing: set ALIYUN_IMAGE_API_KEY (or DASHSCOPE_API_KEY) "
            "or create docs/aliyun_image_api-key.md"
        )
    if not base_url:
        base_url = DEFAULT_BASE_URL
    return AliyunImageConfig(api_key=api_key, base_url=base_url, region=region)


def _raise_api_error(*, url: str, status: Optional[int], raw: bytes, fallback_exc: Exception) -> None:
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        body = None
    if isinstance(body, dict):
        raise AliyunImageAPIError(
            url=url,
            status=status,
            code=str(body.get("code") or "") or None,
            message=str(body.get("message") or "") or None,
            response=body,
        ) from fallback_exc
    raise AliyunImageAPIError(url=url, status=status, code=None, message=str(fallback_exc)) from fallback_exc


def _http_post_json(*, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        _raise_api_error(url=url, status=getattr(exc, "code", None), raw=raw, fallback_exc=exc)
        raise  # unreachable
    except Exception as exc:
        raise RuntimeError(f"Aliyun image request failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Aliyun image response parse failed: {exc}") from exc


def _http_get_json(*, url: str, headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        _raise_api_error(url=url, status=getattr(exc, "code", None), raw=raw, fallback_exc=exc)
        raise  # unreachable
    except Exception as exc:
        raise RuntimeError(f"Aliyun image request failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Aliyun image response parse failed: {exc}") from exc


def _download_bytes(*, url: str, timeout_s: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (redbook_workflow)"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()
    except Exception as exc:
        raise RuntimeError(f"Aliyun image download failed: {exc}") from exc


def _guess_ext(url: str) -> str:
    m = _EXT_RE.search(url or "")
    if not m:
        return ".png"
    ext = m.group(1).lower()
    if ext == "jpeg":
        ext = "jpg"
    return f".{ext}"


def _extract_sync_image_url(resp: dict[str, Any]) -> str:
    output = resp.get("output")
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            message = (choices[0] or {}).get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict):
                        image_url = first.get("image") or first.get("url")
                        if isinstance(image_url, str) and image_url.strip():
                            return image_url.strip()
    raise RuntimeError("Aliyun image response missing image url")


def _extract_task_id(resp: dict[str, Any]) -> str:
    output = resp.get("output")
    if isinstance(output, dict):
        task_id = output.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            return task_id.strip()
    raise RuntimeError("Aliyun async response missing task_id")


def _extract_task_status(resp: dict[str, Any]) -> str:
    output = resp.get("output")
    if isinstance(output, dict):
        status = output.get("task_status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    return ""


def _extract_task_image_url(resp: dict[str, Any]) -> str:
    output = resp.get("output")
    if isinstance(output, dict):
        results = output.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                url = first.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
    # Some tasks may return multimodal output on success.
    return _extract_sync_image_url(resp)


def _is_wan26_model(model_name: str) -> bool:
    return (model_name or "").strip().lower().startswith("wan2.6")


def _is_text2image_async_model(model_name: str) -> bool:
    """
    Old protocol is required for wan2.5 and earlier models (and some legacy wanx).
    """
    m = (model_name or "").strip().lower()
    if m.startswith("wan2.") and not m.startswith("wan2.6"):
        return True
    if m.startswith("wanx") or m.startswith("wanx-"):
        return True
    return False


def _supports_negative_prompt(model_name: str) -> bool:
    """
    Not all Aliyun/Bailian image models accept negative_prompt.

    - z-image docs don't list negative_prompt, so we avoid sending it.
    - qwen-image / wan2.6 docs support it.
    """
    m = (model_name or "").strip().lower()
    if m.startswith("z-image"):
        return False
    return True


def _call_multimodal_generation_sync(
    *,
    cfg: AliyunImageConfig,
    model_name: str,
    prompt: str,
    size_value: str,
    timeout_s: float,
    prompt_extend: bool,
    watermark: bool,
    negative_prompt: str,
) -> dict[str, Any]:
    url = f"{cfg.base_url}/api/v1/services/aigc/multimodal-generation/generation"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
    }

    parameters: dict[str, Any] = {
        "size": size_value,
        "prompt_extend": bool(prompt_extend),
        "watermark": bool(watermark),
    }
    # Wan2.6 默认 n=4；这里强制 n=1，避免多出 3 张图的时间与费用。
    if _is_wan26_model(model_name):
        parameters["n"] = 1
    if negative_prompt and _supports_negative_prompt(model_name):
        parameters["negative_prompt"] = negative_prompt

    payload: dict[str, Any] = {
        "model": model_name,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": parameters,
    }
    return _http_post_json(url=url, payload=payload, headers=headers, timeout_s=timeout_s)


def _call_wan26_generation_async(
    *,
    cfg: AliyunImageConfig,
    model_name: str,
    prompt: str,
    size_value: str,
    timeout_s: float,
    prompt_extend: bool,
    watermark: bool,
    negative_prompt: str,
) -> dict[str, Any]:
    """
    Wan2.6+ async endpoint:
      POST {base_url}/api/v1/services/aigc/image-generation/generation
      Header: X-DashScope-Async: enable
    """
    url = f"{cfg.base_url}/api/v1/services/aigc/image-generation/generation"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
        "X-DashScope-Async": "enable",
    }

    parameters: dict[str, Any] = {
        "size": size_value,
        "n": 1,
        "prompt_extend": bool(prompt_extend),
        "watermark": bool(watermark),
    }
    if negative_prompt and _supports_negative_prompt(model_name):
        parameters["negative_prompt"] = negative_prompt

    payload: dict[str, Any] = {
        "model": model_name,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ]
        },
        "parameters": parameters,
    }
    return _http_post_json(url=url, payload=payload, headers=headers, timeout_s=timeout_s)


def _call_text2image_synthesis_async(
    *,
    cfg: AliyunImageConfig,
    model_name: str,
    prompt: str,
    size_value: str,
    timeout_s: float,
    prompt_extend: bool,
    watermark: bool,
    negative_prompt: str,
) -> dict[str, Any]:
    """
    Old protocol (wan2.5 and earlier, some legacy models):
      POST {base_url}/api/v1/services/aigc/text2image/image-synthesis
      Header: X-DashScope-Async: enable
    """
    url = f"{cfg.base_url}/api/v1/services/aigc/text2image/image-synthesis"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
        "X-DashScope-Async": "enable",
    }

    input_obj: dict[str, Any] = {"prompt": prompt}
    if negative_prompt and _supports_negative_prompt(model_name):
        input_obj["negative_prompt"] = negative_prompt

    payload: dict[str, Any] = {
        "model": model_name,
        "input": input_obj,
        "parameters": {
            "size": size_value,
            "n": 1,
            "prompt_extend": bool(prompt_extend),
            "watermark": bool(watermark),
        },
    }
    return _http_post_json(url=url, payload=payload, headers=headers, timeout_s=timeout_s)


def _poll_task_result(
    *,
    cfg: AliyunImageConfig,
    task_id: str,
    poll_timeout_s: float,
    poll_interval_s: float,
    query_timeout_s: float,
) -> dict[str, Any]:
    url = f"{cfg.base_url}/api/v1/tasks/{task_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
    }

    deadline = time.time() + max(1.0, poll_timeout_s)
    last_status = ""
    while True:
        if time.time() > deadline:
            raise TimeoutError(
                f"Aliyun image task poll timed out after {poll_timeout_s}s "
                f"(task_id={task_id}, last_status={last_status})"
            )
        resp = _http_get_json(url=url, headers=headers, timeout_s=query_timeout_s)
        last_status = _extract_task_status(resp)
        if last_status in ("SUCCEEDED", "FAILED", "CANCELED"):
            return resp
        time.sleep(max(0.2, poll_interval_s))


def generate_aliyun_image(
    *,
    post_id: str,
    prompt: str,
    dest_dir: Path,
    timeout_s: Optional[float] = None,
    download_timeout_s: Optional[float] = None,
    model: Optional[str] = None,
    size: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    prompt_extend: Optional[bool] = None,
    watermark: Optional[bool] = None,
) -> AliyunImageResult:
    """
    Generate ONE image via 阿里云百炼（DashScope）并下载落盘。

    Notes:
    - 文生图 API 返回的是图片 URL（通常 24h 有效），必须下载才能本地保存用于上传小红书。
    - Wan2.6+ 支持同步（multimodal-generation）与异步（image-generation/task）两种模式；
      Wan2.5 及更早版本需走 text2image 异步协议。
    """
    cfg = load_aliyun_image_config()

    model_name = (model or os.getenv("ALIYUN_IMAGE_MODEL") or DEFAULT_MODEL).strip()
    size_value = (size or os.getenv("ALIYUN_IMAGE_SIZE") or DEFAULT_SIZE).strip()
    timeout_s = float(os.getenv("ALIYUN_IMAGE_TIMEOUT_S") or (timeout_s or DEFAULT_TIMEOUT_S))
    download_timeout_s = float(
        os.getenv("ALIYUN_IMAGE_DOWNLOAD_TIMEOUT_S") or (download_timeout_s or DEFAULT_DOWNLOAD_TIMEOUT_S)
    )

    if prompt_extend is None:
        raw = (os.getenv("ALIYUN_IMAGE_PROMPT_EXTEND") or "").strip().lower()
        prompt_extend = raw in ("1", "true", "yes", "on") if raw else False
    if watermark is None:
        raw = (os.getenv("ALIYUN_IMAGE_WATERMARK") or "").strip().lower()
        watermark = raw in ("1", "true", "yes", "on") if raw else False

    if negative_prompt is None:
        negative_prompt = (os.getenv("ALIYUN_IMAGE_NEGATIVE_PROMPT") or "").strip()

    call_mode = (os.getenv("ALIYUN_IMAGE_CALL_MODE") or "auto").strip().lower()
    poll_interval_s = float(os.getenv("ALIYUN_IMAGE_POLL_INTERVAL_S") or DEFAULT_POLL_INTERVAL_S)
    poll_timeout_s = float(os.getenv("ALIYUN_IMAGE_POLL_TIMEOUT_S") or max(timeout_s, DEFAULT_POLL_TIMEOUT_S))
    query_timeout_s = float(
        os.getenv("ALIYUN_IMAGE_TASK_QUERY_TIMEOUT_S") or min(DEFAULT_TASK_QUERY_TIMEOUT_S, timeout_s)
    )

    def _sync_not_supported(err: Exception) -> bool:
        msg = str(err or "").lower()
        return "does not support synchronous calls" in msg or "do not support synchronous calls" in msg

    method = "multimodal_generation_sync"
    task_id: Optional[str] = None
    create_resp: dict[str, Any]
    task_resp: Optional[dict[str, Any]] = None

    if call_mode == "auto":
        if _is_text2image_async_model(model_name):
            call_mode = "async"
        else:
            call_mode = "sync"

    if call_mode in ("async", "task", "text2image"):
        if _is_wan26_model(model_name):
            method = "wan26_generation_async"
            create_resp = _call_wan26_generation_async(
                cfg=cfg,
                model_name=model_name,
                prompt=prompt,
                size_value=size_value,
                timeout_s=timeout_s,
                prompt_extend=bool(prompt_extend),
                watermark=bool(watermark),
                negative_prompt=negative_prompt or "",
            )
        else:
            method = "text2image_synthesis_async"
            create_resp = _call_text2image_synthesis_async(
                cfg=cfg,
                model_name=model_name,
                prompt=prompt,
                size_value=size_value,
                timeout_s=timeout_s,
                prompt_extend=bool(prompt_extend),
                watermark=bool(watermark),
                negative_prompt=negative_prompt or "",
            )
        task_id = _extract_task_id(create_resp)
        task_resp = _poll_task_result(
            cfg=cfg,
            task_id=task_id,
            poll_timeout_s=poll_timeout_s,
            poll_interval_s=poll_interval_s,
            query_timeout_s=query_timeout_s,
        )
        image_url = _extract_task_image_url(task_resp)
    else:
        try:
            create_resp = _call_multimodal_generation_sync(
                cfg=cfg,
                model_name=model_name,
                prompt=prompt,
                size_value=size_value,
                timeout_s=timeout_s,
                prompt_extend=bool(prompt_extend),
                watermark=bool(watermark),
                negative_prompt=negative_prompt or "",
            )
        except AliyunImageAPIError as exc:
            # 某些账号/模型可能不支持同步：自动降级为异步（旧协议 or wan2.6 新协议）
            if _sync_not_supported(exc):
                if _is_wan26_model(model_name):
                    method = "wan26_generation_async_fallback"
                    create_resp = _call_wan26_generation_async(
                        cfg=cfg,
                        model_name=model_name,
                        prompt=prompt,
                        size_value=size_value,
                        timeout_s=timeout_s,
                        prompt_extend=bool(prompt_extend),
                        watermark=bool(watermark),
                        negative_prompt=negative_prompt or "",
                    )
                else:
                    method = "text2image_synthesis_async_fallback"
                    create_resp = _call_text2image_synthesis_async(
                        cfg=cfg,
                        model_name=model_name,
                        prompt=prompt,
                        size_value=size_value,
                        timeout_s=timeout_s,
                        prompt_extend=bool(prompt_extend),
                        watermark=bool(watermark),
                        negative_prompt=negative_prompt or "",
                    )
                task_id = _extract_task_id(create_resp)
                task_resp = _poll_task_result(
                    cfg=cfg,
                    task_id=task_id,
                    poll_timeout_s=poll_timeout_s,
                    poll_interval_s=poll_interval_s,
                    query_timeout_s=query_timeout_s,
                )
                image_url = _extract_task_image_url(task_resp)
            else:
                raise
        else:
            image_url = _extract_sync_image_url(create_resp)

    data = _download_bytes(url=image_url, timeout_s=download_timeout_s)

    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = _guess_ext(image_url)
    out_path = dest_dir / f"ai_aliyun_{ts}{ext}"
    out_path.write_bytes(data)

    meta: dict[str, Any] = {
        "mode": "aliyun_image",
        "provider": "aliyun",
        "post_id": post_id,
        "region": cfg.region,
        "model": model_name,
        "size": size_value,
        "prompt": prompt,
        "prompt_extend": bool(prompt_extend),
        "watermark": bool(watermark),
        "negative_prompt": negative_prompt,
        "call_mode": call_mode,
        "method": method,
        "task_id": task_id,
        "src_url": image_url,
        "downloaded_path": str(out_path),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "request_id": (create_resp or {}).get("request_id"),
        "usage": (create_resp or {}).get("usage"),
    }
    if task_resp is not None:
        meta["task"] = {"status": _extract_task_status(task_resp)}

    return AliyunImageResult(path=out_path, meta=meta)

