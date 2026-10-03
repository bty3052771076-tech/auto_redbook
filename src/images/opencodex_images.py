"""Fail-closed local ChatGPT image relay with durable, bounded requests."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from PIL import Image, ImageStat

MODEL = "gpt-image-2"
VERIFIED_CODE_HASHES = {"d263dd024eb8e6bd6eea93ab02fc81f6ff2e890722df0e844833044c4b764586"}
MAX_RESPONSE = 100 * 1024 * 1024


class OpenCodexImageError(RuntimeError):
    def __init__(self, code: str, *, fallback_safe: bool = False):
        super().__init__(code)
        self.code = code
        self.fallback_safe = fallback_safe


@dataclass(frozen=True)
class SubscriptionImageResult:
    path: Path
    meta: dict[str, Any]


def validate_subscription_config(config: dict) -> None:
    if not isinstance(config, dict) or not isinstance(config.get("providers"), dict):
        raise OpenCodexImageError("OPENCODEX_CONFIG_CONTRACT_INVALID", fallback_safe=True)
    if config.get("images"):
        raise OpenCodexImageError("OPENCODEX_CUSTOM_IMAGE_ROUTE_FORBIDDEN", fallback_safe=True)
    providers = config["providers"]
    if set(providers) - {"openai", "command-code"}:
        raise OpenCodexImageError("OPENCODEX_UNVERIFIED_PROVIDER_FORBIDDEN", fallback_safe=True)
    p = providers.get("openai")
    if not isinstance(p, dict) or (
        p.get("adapter") != "openai-responses"
        or p.get("authMode") != "forward"
        or p.get("baseUrl", "").rstrip("/") != "https://chatgpt.com/backend-api/codex"
        or p.get("codexAccountMode", "pool") not in {"pool", "direct"}
        or p.get("disabled")
    ):
        raise OpenCodexImageError("OPENCODEX_SUBSCRIPTION_ROUTE_REQUIRED", fallback_safe=True)
    if any(p.get(k) for k in ("apiKey", "hasApiKey", "hasKey", "apiKeyPool", "keyPool", "headers")):
        raise OpenCodexImageError("OPENCODEX_API_CREDENTIAL_ROUTE_FORBIDDEN", fallback_safe=True)


def package_code_hash(package: Path) -> str:
    files = sorted(
        (p for name in ("src", "bin") for p in (package / name).rglob("*")
         if p.is_file() and p.suffix in {".ts", ".js", ".mjs", ".cjs"}),
        key=lambda p: p.relative_to(package).as_posix(),
    )
    if not files:
        raise OpenCodexImageError("OPENCODEX_INSTALLED_SOURCE_MISSING", fallback_safe=True)
    digest = sha256()
    for file in files:
        digest.update(file.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256(file.read_bytes()).digest())
    return digest.hexdigest()


def connection_settings() -> tuple[str, Path, Path]:
    base = (os.getenv("OPENCODEX_IMAGE_BASE_URL") or "http://127.0.0.1:10100").rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise OpenCodexImageError("OPENCODEX_LOOPBACK_URL_REQUIRED")
    home = Path(os.getenv("OPENCODEX_IMAGE_HOME") or Path.home() / ".opencodex")
    package = Path(os.getenv("OPENCODEX_IMAGE_PACKAGE_DIR") or
                   Path.home() / "AppData/Roaming/npm/node_modules/@bitkyc08/opencodex")
    return base, home, package


def preflight(client: httpx.Client) -> dict:
    base, home, package = connection_settings()
    try:
        raw = (home / "config.json").read_bytes()
        disk = json.loads(raw)
        validate_subscription_config(disk)
        code_hash = package_code_hash(package)
        if code_hash not in VERIFIED_CODE_HASHES:
            raise OpenCodexImageError("OPENCODEX_UPDATE_REQUIRES_COMPATIBILITY_REVIEW", fallback_safe=True)
        installed = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        health_response = client.get(base + "/healthz", timeout=5)
        health_response.raise_for_status()
        health = health_response.json()
        if health.get("version") != installed or health.get("status") != "ok":
            raise OpenCodexImageError("OPENCODEX_RESTART_OR_VERSION_REVIEW_REQUIRED", fallback_safe=True)
        admin = (home / "admin-api-token").read_text(encoding="utf-8").strip()
        response = client.get(base + "/api/config",
                              headers={"X-OpenCodex-API-Key": admin}, timeout=5)
        response.raise_for_status()
        live = response.json()
        validate_subscription_config(live)
        if int(disk.get("port", 10100)) != urlsplit(base).port or int(live.get("port", 0)) != urlsplit(base).port:
            raise OpenCodexImageError("OPENCODEX_CONFIG_PORT_MISMATCH", fallback_safe=True)
        if sha256(raw).hexdigest() != sha256((home / "config.json").read_bytes()).hexdigest():
            raise OpenCodexImageError("OPENCODEX_CONFIG_CHANGED", fallback_safe=True)
        return {"version": installed, "code_hash": code_hash, "config_hash": sha256(raw).hexdigest(),
                "billing": "chatgpt_subscription", "main_account_allowed": True}
    except OpenCodexImageError:
        raise
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        raise OpenCodexImageError("OPENCODEX_PREFLIGHT_UNAVAILABLE", fallback_safe=True) from None


def image_connection_status(env: dict | None = None) -> dict:
    # Catalog checks do not submit generation requests or consume image quota.
    values = env if env is not None else os.environ
    enabled = str(values.get("OPENCODEX_IMAGE_ENABLED", "0")).lower() in {"1", "true", "yes"}
    return {"enabled": enabled, "model": MODEL, "billing": "chatgpt_subscription",
            "remaining": None, "requires_preflight": True}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_request_state(record: Path, shared_record: Path, value: dict) -> None:
    # Write shared state first so a crash cannot hide submission from a new post.
    _write_json(shared_record, value)
    _write_json(record, value)


@contextmanager
def _file_lock(path: Path, *, wait: bool = True) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        started = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not wait or time.monotonic() - started > 620:
                    raise OpenCodexImageError("OPENCODEX_LOCAL_LOCK_BUSY")
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _image_slot() -> Iterator[None]:
    root = Path(os.getenv("OPENCODEX_IMAGE_LOCK_DIR") or
                Path(os.getenv("REDBOOK_RUNTIME_ROOT") or ".") / "data/runs/opencodex-image-locks")
    count = max(1, min(2, int(os.getenv("OPENCODEX_IMAGE_CONCURRENCY", "2"))))
    started = time.monotonic()
    while True:
        for i in range(count):
            lock = _file_lock(root / f"slot-{i}.lock", wait=False)
            try:
                lock.__enter__()
            except OpenCodexImageError:
                continue
            try:
                yield
            finally:
                lock.__exit__(None, None, None)
            return
        if time.monotonic() - started > 620:
            raise OpenCodexImageError("OPENCODEX_IMAGE_QUEUE_TIMEOUT")
        time.sleep(0.05)


def validate_image(content: bytes, input_hashes: list[str]) -> tuple[int, int]:
    if sha256(content).hexdigest() in input_hashes:
        raise OpenCodexImageError("OPENCODEX_RETURNED_REFERENCE_UNCHANGED")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            if min(image.size) < 64 or max(image.size) > 8192:
                raise ValueError("invalid dimensions")
            sample = image.convert("RGB")
            sample.thumbnail((128, 128))
            if max(ImageStat.Stat(sample).stddev) < 2:
                raise ValueError("blank image")
            return image.size
    except OpenCodexImageError:
        raise
    except Exception:
        raise OpenCodexImageError("OPENCODEX_INVALID_IMAGE_RESULT") from None


def generate_subscription_image(*, post_id: str, prompt: str, dest_dir: Path,
                                reference_paths: list[Path] | None = None,
                                allow_minimax_fallback: bool = True) -> SubscriptionImageResult:
    if not prompt.strip() or len(prompt) > 16000:
        raise OpenCodexImageError("OPENCODEX_INVALID_PROMPT")
    references = reference_paths or []
    if references and len(references) != 2:
        raise OpenCodexImageError("OPENCODEX_TWO_REFERENCES_REQUIRED")
    encoded, hashes = [], []
    for path in references:
        content = path.read_bytes()
        if len(content) > 10 * 1024 * 1024:
            raise OpenCodexImageError("OPENCODEX_REFERENCE_TOO_LARGE")
        with Image.open(BytesIO(content)) as image:
            mime = Image.MIME.get(image.format)
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            raise OpenCodexImageError("OPENCODEX_REFERENCE_FORMAT_INVALID")
        hashes.append(sha256(content).hexdigest())
        encoded.append({"image_url": f"data:{mime};base64," + base64.b64encode(content).decode("ascii")})
    body: dict = {"model": MODEL, "prompt": prompt.strip(), "n": 1,
                  "quality": "medium", "size": "1024x1536", "background": "opaque"}
    endpoint = "edits" if encoded else "generations"
    if encoded:
        body["images"] = encoded
    key = sha256(json.dumps({"model": MODEL, "prompt": prompt.strip(), "inputs": hashes,
                            "quality": "medium", "size": body["size"]}, sort_keys=True).encode()).hexdigest()
    dest_dir.mkdir(parents=True, exist_ok=True)
    record = dest_dir / f"opencodex-{key}.json"
    state_dir = Path(os.getenv("OPENCODEX_IMAGE_STATE_DIR") or
                     Path(os.getenv("REDBOOK_RUNTIME_ROOT") or ".") / "data/runs/opencodex-image-state")
    shared_record = state_dir / f"{key}.json"
    with _file_lock(state_dir / f"{key}.lock"), _file_lock(dest_dir / f"opencodex-{key}.lock"):
        if record.exists():
            saved = json.loads(record.read_text(encoding="utf-8"))
            if saved.get("status") == "complete":
                file = dest_dir / saved["file"]
                if file.is_file() and sha256(file.read_bytes()).hexdigest() == saved["sha256"]:
                    validate_image(file.read_bytes(), hashes)
                    return SubscriptionImageResult(file, {**saved, "cache_hit": True,
                                                         "cached_from_post_id": saved.get("post_id"),
                                                         "post_id": post_id})
                raise OpenCodexImageError("OPENCODEX_CACHE_ARTIFACT_INVALID")
            # A process death after submission must not cause a second charged POST.
            if saved.get("status") in {"submitted", "uncertain"}:
                raise OpenCodexImageError("OPENCODEX_PREVIOUS_REQUEST_UNCERTAIN")
            if saved.get("status") == "rejected":
                raise OpenCodexImageError(saved.get("error", "OPENCODEX_PREVIOUS_REQUEST_REJECTED"))
        if shared_record.exists():
            shared = json.loads(shared_record.read_text(encoding="utf-8"))
            if shared.get("status") in {"submitted", "uncertain"}:
                raise OpenCodexImageError("OPENCODEX_PREVIOUS_REQUEST_UNCERTAIN")
        started = time.monotonic()
        meta: dict = {"provider": "opencodex", "mode": "ai_generated", "model": MODEL,
                      "endpoint": endpoint, "request_key": key, "input_hashes": hashes,
                      "post_id": post_id, "status": "not_submitted", "cache_hit": False,
                      "started_at": datetime.now(timezone.utc).isoformat()}
        try:
            with _image_slot():
                with httpx.Client(trust_env=False, follow_redirects=False, timeout=310) as client:
                    proof = preflight(client)
                    meta.update(proof)
                    base, home, _package = connection_settings()
                    if sha256((home / "config.json").read_bytes()).hexdigest() != proof["config_hash"]:
                        raise OpenCodexImageError("OPENCODEX_CONFIG_CHANGED", fallback_safe=True)
                    meta["status"] = "submitted"
                    meta["queue_elapsed_s"] = round(time.monotonic() - started, 3)
                    meta["upstream_started_at"] = datetime.now(timezone.utc).isoformat()
                    _write_request_state(record, shared_record, meta)
                    upstream_start = time.monotonic()
                    try:
                        with client.stream("POST", base + "/v1/images/" + endpoint, json=body) as response:
                            if not 200 <= response.status_code < 300:
                                safe = response.status_code in {401, 404, 429}
                                raise OpenCodexImageError(f"OPENCODEX_HTTP_{response.status_code}",
                                                         fallback_safe=safe)
                            chunks, length = [], 0
                            for chunk in response.iter_bytes():
                                length += len(chunk)
                                if length > MAX_RESPONSE:
                                    raise OpenCodexImageError("OPENCODEX_RESPONSE_TOO_LARGE")
                                chunks.append(chunk)
                            data = json.loads(b"".join(chunks))
                            results = data.get("data")
                            if not isinstance(results, list) or len(results) != 1:
                                raise OpenCodexImageError("OPENCODEX_IMAGE_CONTRACT_CHANGED")
                            content = base64.b64decode(results[0]["b64_json"], validate=True)
                    except httpx.ConnectError:
                        raise OpenCodexImageError("OPENCODEX_NOT_CONNECTED", fallback_safe=True) from None
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        raise OpenCodexImageError("OPENCODEX_RESULT_UNCERTAIN") from None
                    meta["upstream_elapsed_s"] = round(time.monotonic() - upstream_start, 3)
                    meta["upstream_finished_at"] = datetime.now(timezone.utc).isoformat()
                    meta["config_unchanged"] = sha256((home / "config.json").read_bytes()).hexdigest() == proof["config_hash"]
                    if not meta["config_unchanged"]:
                        raise OpenCodexImageError("OPENCODEX_CONFIG_CHANGED_AFTER_SUBMISSION")
            width, height = validate_image(content, hashes)
            meta.update(width=width, height=height)
        except OpenCodexImageError as exc:
            meta.update(error=exc.code, status="not_submitted" if exc.fallback_safe else
                        ("uncertain" if meta["status"] == "submitted" else "rejected"))
            _write_request_state(record, shared_record, meta)
            enabled = (os.getenv("OPENCODEX_IMAGE_FALLBACK") or "none").lower() == "minimax"
            if not (exc.fallback_safe and enabled and allow_minimax_fallback and not references):
                raise
            from src.images.minimax_images import generate_minimax_image
            # Use only the existing Token Plan loader; never load a paygo key.
            meta.update(status="submitted", provider="minimax", fallback_reason=exc.code)
            _write_request_state(record, shared_record, meta)
            result = generate_minimax_image(post_id=post_id, prompt=prompt, dest_dir=dest_dir)
            content = result.path.read_bytes()
            width, height = validate_image(content, [])
            meta.update(result.meta, provider="minimax", fallback_from="opencodex",
                        fallback_reason=exc.code, billing="minimax_subscription", width=width, height=height)
        file = dest_dir / f"opencodex-{key}.png"
        temporary = file.with_suffix(".png.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, file)
        meta.update(status="complete", file=file.name, sha256=sha256(content).hexdigest(),
                    elapsed_s=round(time.monotonic() - started, 3))
        _write_request_state(record, shared_record, meta)
        return SubscriptionImageResult(file, meta)
