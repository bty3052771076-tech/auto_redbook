from __future__ import annotations

import os
import json
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.config import (
    ALIYUN_FREE_LLM_MODELS,
    DEFAULT_ALIYUN_LLM_BASE_URL,
    DEFAULT_ALIYUN_LLM_MODEL,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
)
from src.storage.files import latest_execution
from src.workflow.create_post import DEFAULT_EVALUATION_VIEWPOINT


def _detect_project_root() -> Path:
    """
    Detect repository root for both source-run and PyInstaller-frozen exe.

    - Source run: apps/gui.py -> repo root is parent of apps/
    - Frozen exe: prefer the exe directory; if it is under dist/, use parent
    """
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])

    try:
        candidates.append(Path(__file__).resolve().parents[1])
    except Exception:
        pass

    for root in candidates:
        if (root / "apps" / "cli.py").exists():
            return root
    return candidates[0] if candidates else Path.cwd()


PROJECT_ROOT = _detect_project_root()
ENV_GUI_PATH = PROJECT_ROOT / ".env.gui"

# --- GUI defaults (safe; no secrets) ---
DEFAULT_TITLE = "每日新闻"
DEFAULT_ASSETS_GLOB = "assets/pics/*"
AUTO_IMAGE_ASSETS_GLOB = "assets/empty/*"
DEFAULT_LOGIN_HOLD = 600
DEFAULT_WAIT_TIMEOUT = 600
DEFAULT_COMMAND_HEARTBEAT_S = 20.0
COMMAND_OUTPUT_POLL_S = 0.2

LLM_PROVIDER_OPTIONS = ["aliyun", "ppinfra", "auto"]
IMAGE_SOURCE_LOCAL = "local"
IMAGE_PROVIDER_OPTIONS = ["aliyun", "pexels"]
IMAGE_SOURCE_OPTIONS = [IMAGE_SOURCE_LOCAL] + IMAGE_PROVIDER_OPTIONS

ALIYUN_LLM_MODEL_OPTIONS = list(ALIYUN_FREE_LLM_MODELS)
PPINFRA_LLM_MODEL_OPTIONS = [DEFAULT_LLM_MODEL]
AUTO_LLM_MODEL_OPTION = "阿里云免费模型列表（顺序回退）"

DEFAULT_LLM_PROVIDER = "aliyun"
DEFAULT_IMAGE_PROVIDER = "aliyun"
DEFAULT_IMAGE_SOURCE = DEFAULT_IMAGE_PROVIDER

ALIYUN_IMAGE_MODEL_OPTIONS = [
    "wan2.7-image",
    "wan2.7-image-pro",
    "qwen-image-2.0-pro-2026-04-22",
]
DEFAULT_ALIYUN_IMAGE_MODELS = ALIYUN_IMAGE_MODEL_OPTIONS[0]
DEFAULT_ALIYUN_IMAGE_SIZE = "1104*1472"
DEFAULT_ALIYUN_IMAGE_NEGATIVE_PROMPT = (
    "no text, no words, no letters, no watermark, no logo, no caption, no subtitle, no signature, no UI"
)

DEFAULT_NEWS_CHINA_RATIO = "0.6"
DEFAULT_NEWS_CHINA_BONUS = "0.15"
DEFAULT_DRAFT_URL = "https://creator.xiaohongshu.com/publish/publish?target=image"
DEFAULT_LOGIN_URL = "https://creator.xiaohongshu.com"
DEFAULT_XHS_CHROME_PROFILE = "Default"
DELETE_MODE_PREVIEW = "安全预览（不删除）"
DELETE_MODE_DELETE = "正式删除（会删除小红书草稿）"
DELETE_MODE_OPTIONS = [DELETE_MODE_PREVIEW, DELETE_MODE_DELETE]
DELETE_CONFIRM_ASK = "执行前确认（推荐）"
DELETE_CONFIRM_AUTO = "自动确认（不再弹出确认）"
DELETE_CONFIRM_OPTIONS = [DELETE_CONFIRM_ASK, DELETE_CONFIRM_AUTO]
XHS_CHROME_PROFILE_RELATIVE = Path("data") / "browser" / "chrome-profile"
POST_ID_RE = re.compile(r"[0-9a-fA-F]{32}")
DISPLAY_STATUS_SYMBOL_RE = re.compile(r"[✅❌✔✘✖✓☑☒]")
BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class RecentPostSummary:
    post_id: str
    title: str
    status: str = ""
    uploaded: bool = False
    uploaded_at: str = ""
    updated_at: str = ""
    created_at: str = ""
    body_preview: str = ""
    asset_count: int = 0
    latest_execution_result: str = ""
    latest_execution_started_at: str = ""
    latest_execution_ended_at: str = ""
    latest_execution_evidence: tuple[str, ...] = ()


def _looks_like_post_id(name: str) -> bool:
    return len(name) == 32 and all(ch in "0123456789abcdef" for ch in name.lower())


def _shorten_choice_text(value: str, *, limit: int = 42) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _clean_display_title(value: str) -> str:
    text = DISPLAY_STATUS_SYMBOL_RE.sub("", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"[\?？�]+", text):
        text = ""
    return text or "(无标题)"


def _format_display_time(value: str) -> str:
    return _format_beijing_time(value)


def _parse_stored_time(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
            return dt.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        try:
            dt = datetime.strptime(text.split(".", 1)[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _format_beijing_time(value: str) -> str:
    dt = _parse_stored_time(value)
    if not dt:
        return ""
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S 北京时间")


def format_upload_state(post: RecentPostSummary) -> str:
    return "已上传至小红书草稿" if post.uploaded else "未上传"


def _read_post_summary(post_dir_path: Path) -> RecentPostSummary:
    title = "(untitled)"
    status = ""
    uploaded = False
    uploaded_at = ""
    updated_at = ""
    created_at = ""
    body_preview = ""
    asset_count = 0
    post_json = post_dir_path / "post.json"
    if post_json.exists():
        try:
            data = json.loads(post_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                title = str(data.get("title") or title).strip() or title
                status = str(data.get("status") or "").strip()
                uploaded = bool(data.get("uploaded")) or status == "saved_as_draft"
                uploaded_at = str(data.get("uploaded_at") or "").strip()
                updated_at = str(data.get("updated_at") or "").strip()
                created_at = str(data.get("created_at") or "").strip()
                body_text = re.sub(r"\s+", " ", str(data.get("body") or "")).strip()
                body_preview = _shorten_choice_text(body_text, limit=220)
                assets = data.get("assets") or []
                asset_count = len(assets) if isinstance(assets, list) else 0
                if uploaded and not uploaded_at:
                    uploaded_at = updated_at or created_at
        except Exception:
            pass
    exec_result = ""
    exec_started_at = ""
    exec_ended_at = ""
    exec_evidence: tuple[str, ...] = ()
    try:
        data_root = post_dir_path.parents[1]
        latest = latest_execution(post_dir_path.name, base=data_root)
        if latest:
            exec_result = latest.result or ""
            exec_started_at = latest.started_at or ""
            exec_ended_at = latest.ended_at or ""
            exec_evidence = tuple(str(item) for item in latest.evidence or ())
    except Exception:
        pass
    return RecentPostSummary(
        post_id=post_dir_path.name,
        title=title,
        status=status,
        uploaded=uploaded,
        uploaded_at=uploaded_at,
        updated_at=updated_at,
        created_at=created_at,
        body_preview=body_preview,
        asset_count=asset_count,
        latest_execution_result=exec_result,
        latest_execution_started_at=exec_started_at,
        latest_execution_ended_at=exec_ended_at,
        latest_execution_evidence=exec_evidence,
    )


def list_recent_posts(*, project_root: Path = PROJECT_ROOT, limit: int = 50) -> list[RecentPostSummary]:
    """
    List recent posts from local storage (data/posts/<post_id>/).
    Used by the GUI to make run/approve easier.
    """
    posts_dir = project_root / "data" / "posts"
    if not posts_dir.exists():
        return []

    items: list[tuple[float, RecentPostSummary]] = []
    for p in posts_dir.iterdir():
        if not p.is_dir() or not _looks_like_post_id(p.name):
            continue
        try:
            items.append((p.stat().st_mtime, _read_post_summary(p)))
        except Exception:
            continue
    items.sort(key=lambda t: t[0], reverse=True)
    return [summary for _, summary in items[: max(0, int(limit or 0) or 50)]]


def format_post_choice(post: RecentPostSummary) -> str:
    status = f" [{post.status}]" if post.status else ""
    title = _shorten_choice_text(_clean_display_title(post.title))
    return f"{title}{status} · {format_upload_state(post)} | {post.post_id}"


def format_post_detail(post: RecentPostSummary) -> str:
    lines = [
        f"标题：{_clean_display_title(post.title)}",
        f"post_id：{post.post_id}",
        f"本地状态：{post.status or '未知'}",
        f"上传状态：{format_upload_state(post)}",
    ]
    if post.uploaded_at:
        lines.append(f"上传时间：{_format_display_time(post.uploaded_at)}")
    if post.updated_at:
        lines.append(f"本地更新时间：{_format_display_time(post.updated_at)}")
    if post.latest_execution_result:
        lines.append(f"最近执行：{post.latest_execution_result}")
    if post.latest_execution_started_at:
        lines.append(f"执行开始：{_format_display_time(post.latest_execution_started_at)}")
    if post.latest_execution_ended_at:
        lines.append(f"执行结束：{_format_display_time(post.latest_execution_ended_at)}")
    lines.append(f"素材数量：{post.asset_count}")
    if post.latest_execution_evidence:
        lines.append("证据文件：" + "；".join(post.latest_execution_evidence[:3]))
    lines.append("")
    lines.append("正文预览：")
    lines.append(post.body_preview or "（无正文预览）")
    return "\n".join(lines)


def format_post_time_detail(post: RecentPostSummary) -> str:
    rows = [("显示时区", "北京时间 UTC+8")]
    time_fields = [
        ("创建时间", post.created_at),
        ("本地更新时间", post.updated_at),
        ("上传时间", post.uploaded_at),
        ("执行开始", post.latest_execution_started_at),
        ("执行结束", post.latest_execution_ended_at),
    ]
    for label, raw in time_fields:
        formatted = _format_beijing_time(raw)
        if formatted:
            rows.append((label, formatted))
    if len(rows) == 1:
        rows.append(("时间", "暂无记录"))
    return "\n".join(f"{label}：{value}" for label, value in rows)


def extract_post_id_from_choice(value: str) -> str:
    text = (value or "").strip()
    if _looks_like_post_id(text):
        return text.lower()
    matches = POST_ID_RE.findall(text)
    return matches[-1].lower() if matches else text


def list_recent_post_ids(*, project_root: Path = PROJECT_ROOT, limit: int = 50) -> list[str]:
    return [post.post_id for post in list_recent_posts(project_root=project_root, limit=limit)]


def _env_lookup(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if env is None else env


def build_xhs_creator_profile_dir(
    *,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
) -> Path:
    value = str(_env_lookup(env).get("XHS_CHROME_USER_DATA_DIR") or "").strip()
    if value:
        return Path(value).expanduser()
    return project_root / XHS_CHROME_PROFILE_RELATIVE


def build_xhs_creator_profile_name(*, env: Mapping[str, str] | None = None) -> str:
    value = str(_env_lookup(env).get("XHS_CHROME_PROFILE") or "").strip()
    return value or DEFAULT_XHS_CHROME_PROFILE


def find_chrome_executable(*, env: Mapping[str, str] | None = None) -> Path | None:
    source = _env_lookup(env)
    explicit = str(source.get("XHS_CHROME_PATH") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path

    candidates: list[Path] = []
    program_files = str(source.get("ProgramFiles") or "").strip()
    if program_files:
        candidates.append(Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe")
    program_files_x86 = str(source.get("ProgramFiles(x86)") or "").strip()
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe")
    local_app_data = str(source.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_xhs_creator_launch_args(
    *,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
    chrome_path: str | Path | None = None,
    url: str = DEFAULT_DRAFT_URL,
) -> list[str]:
    chrome = Path(chrome_path).expanduser() if chrome_path else find_chrome_executable(env=env)
    if not chrome:
        return []

    profile_dir = build_xhs_creator_profile_dir(project_root=project_root, env=env)
    profile_name = build_xhs_creator_profile_name(env=env)
    return [
        str(chrome),
        f"--user-data-dir={profile_dir}",
        f"--profile-directory={profile_name}",
        url,
    ]


def build_xhs_login_launch_args(
    *,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
    chrome_path: str | Path | None = None,
) -> list[str]:
    return build_xhs_creator_launch_args(
        project_root=project_root,
        env=env,
        chrome_path=chrome_path,
        url=DEFAULT_LOGIN_URL,
    )


def open_xhs_creator(
    *,
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
    url: str = DEFAULT_DRAFT_URL,
) -> bool:
    profile_dir = build_xhs_creator_profile_dir(project_root=project_root, env=env)
    args = build_xhs_creator_launch_args(project_root=project_root, env=env, url=url)
    if args:
        profile_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(args, cwd=str(project_root))
        return True
    return bool(webbrowser.open(url))


def open_xhs_profile_login() -> bool:
    return open_xhs_creator(url=DEFAULT_LOGIN_URL)


def _python_for_cli() -> str:
    """
    Use the workspace venv python if present so the GUI works when packaged as an exe.

    When running as a frozen exe, sys.executable points to the exe itself, not python.
    """
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)

    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        return str(exe)

    return "python"


def _strip_quotes(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_env_file(path: Path) -> dict[str, str]:
    """
    Minimal .env parser for GUI local config.

    - Supports KEY=VALUE with optional quotes
    - Ignores blank lines and comments starting with '#'
    """
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if key:
            out[key] = _strip_quotes(v.strip())
    return out


def save_env_file(path: Path, values: dict[str, str]) -> None:
    lines = ["# Local-only GUI config; DO NOT commit this file."]
    for k in sorted(values.keys()):
        v = (values.get(k) or "").strip()
        if not v:
            continue
        if any(ch.isspace() for ch in v) or "#" in v:
            v = '"' + v.replace('"', '\\"') + '"'
        lines.append(f"{k}={v}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_image_source(value: str) -> str:
    source = (value or "").strip().lower()
    if source not in IMAGE_SOURCE_OPTIONS:
        return IMAGE_SOURCE_LOCAL
    return source


def resolve_assets_glob_for_image_source(image_source: str, assets_glob: str) -> str:
    source = normalize_image_source(image_source)
    if source == IMAGE_SOURCE_LOCAL:
        return (assets_glob or DEFAULT_ASSETS_GLOB).strip()
    return AUTO_IMAGE_ASSETS_GLOB


def resolve_delete_mode_flags(delete_mode: str, confirm_mode: str) -> tuple[bool, bool]:
    """
    Translate human-readable delete choices into CLI flags.

    Preview mode must never pass auto-confirm, even if the confirm selector is
    changed, so the command remains semantically unambiguous.
    """
    dry_run = (delete_mode or DELETE_MODE_PREVIEW).strip() != DELETE_MODE_DELETE
    if dry_run:
        return True, False
    yes = (confirm_mode or DELETE_CONFIRM_ASK).strip() == DELETE_CONFIRM_AUTO
    return False, yes


def build_cli_args(subcommand: str, *, params: dict[str, object]) -> list[str]:
    """
    Build `python -m apps.cli <subcommand> ...` args from typed parameters.
    This is intentionally small: GUI focuses on common flags.
    """
    args: list[str] = [_python_for_cli(), "-m", "apps.cli", subcommand]

    if subcommand in ("auto", "create"):
        title = str(params.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")
        prompt = str(params.get("prompt") or "").strip()
        evaluation_viewpoint = (
            str(params.get("evaluation_viewpoint") or DEFAULT_EVALUATION_VIEWPOINT).strip()
            or DEFAULT_EVALUATION_VIEWPOINT
        )
        image_source = str(params.get("image_source") or IMAGE_SOURCE_LOCAL)
        assets_glob = resolve_assets_glob_for_image_source(
            image_source,
            str(params.get("assets_glob") or DEFAULT_ASSETS_GLOB),
        )
        count = int(params.get("count") or 1)
        no_copy = bool(params.get("no_copy") or False)

        args.extend(["--title", title])
        if prompt:
            args.extend(["--prompt", prompt])
        args.extend(["--evaluation-viewpoint", evaluation_viewpoint])
        if assets_glob:
            args.extend(["--assets-glob", assets_glob])
        args.extend(["--count", str(count)])
        if no_copy:
            args.append("--no-copy")

        if subcommand == "auto":
            dry_run = bool(params.get("dry_run") or False)
            headless = bool(params.get("headless") or False)
            login_hold = int(params.get("login_hold") or 0)
            wait_timeout = int(params.get("wait_timeout") or 300)
            force = bool(params.get("force") or False)
            if dry_run:
                args.append("--dry-run")
            if headless:
                args.append("--headless")
            args.extend(["--login-hold", str(login_hold)])
            args.extend(["--wait-timeout", str(wait_timeout)])
            if force:
                args.append("--force")
        return args

    if subcommand == "approve":
        post_id = str(params.get("post_id") or "").strip()
        if not post_id:
            raise ValueError("post_id is required")
        args.append(post_id)
        if bool(params.get("force") or False):
            args.append("--force")
        return args

    if subcommand == "run":
        post_id = str(params.get("post_id") or "").strip()
        if not post_id:
            raise ValueError("post_id is required")
        assets_glob = str(params.get("assets_glob") or "").strip()
        dry_run = bool(params.get("dry_run") or False)
        headless = bool(params.get("headless") or False)
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 300)
        force = bool(params.get("force") or False)

        args.append(post_id)
        if assets_glob:
            args.extend(["--assets-glob", assets_glob])
        if dry_run:
            args.append("--dry-run")
        if headless:
            args.append("--headless")
        args.extend(["--login-hold", str(login_hold)])
        args.extend(["--wait-timeout", str(wait_timeout)])
        if force:
            args.append("--force")
        return args

    if subcommand == "delete-drafts":
        draft_type = str(params.get("draft_type") or "image").strip()
        draft_location = str(params.get("draft_location") or "publish").strip()
        draft_url = str(params.get("draft_url") or "").strip()
        all_types = bool(params.get("all_types") or False)
        limit = int(params.get("limit") or 0)
        dry_run = bool(params.get("dry_run") or False)
        headless = bool(params.get("headless") or False)
        yes = bool(params.get("yes") or False)
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 300)

        args.extend(["--draft-type", draft_type])
        args.extend(["--draft-location", draft_location])
        if draft_location == "url" and draft_url:
            args.extend(["--draft-url", draft_url])
        if all_types:
            args.append("--all")
        args.extend(["--limit", str(limit)])
        if dry_run:
            args.append("--dry-run")
        if headless:
            args.append("--headless")
        if yes:
            args.append("--yes")
        args.extend(["--login-hold", str(login_hold)])
        args.extend(["--wait-timeout", str(wait_timeout)])
        return args

    raise ValueError(f"unsupported subcommand: {subcommand}")


def _clean_env(values: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in values.items() if (v or "").strip()}


def build_provider_env_overrides(
    base: dict[str, str],
    *,
    llm_provider: str,
    llm_model: str,
    image_provider: str,
    image_model: str,
) -> dict[str, str]:
    """
    Merge GUI provider/model choices into env overrides passed to the CLI subprocess.

    The CLI already implements provider fallback. This function only expresses the
    user's GUI choices as environment variables without changing command flags.
    """
    env = _clean_env(dict(base or {}))
    provider = (llm_provider or "auto").strip().lower()
    model = (llm_model or "").strip()

    if provider not in LLM_PROVIDER_OPTIONS:
        provider = "auto"
    env["LLM_PROVIDER"] = provider

    if provider == "aliyun":
        selected = model if model and model != AUTO_LLM_MODEL_OPTION else DEFAULT_ALIYUN_LLM_MODEL
        env["ALIYUN_LLM_MODEL"] = selected
        env["ALIYUN_LLM_MODELS"] = selected
        env.setdefault("ALIYUN_LLM_BASE_URL", DEFAULT_ALIYUN_LLM_BASE_URL)
        env.pop("LLM_MODEL", None)
    elif provider == "ppinfra":
        selected = model if model and model != AUTO_LLM_MODEL_OPTION else DEFAULT_LLM_MODEL
        env["LLM_MODEL"] = selected
        env.setdefault("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
        env.pop("ALIYUN_LLM_MODEL", None)
        env.pop("ALIYUN_LLM_MODELS", None)
    else:
        if model == AUTO_LLM_MODEL_OPTION or not model:
            env["ALIYUN_LLM_MODELS"] = ",".join(ALIYUN_LLM_MODEL_OPTIONS)
        elif model in ALIYUN_LLM_MODEL_OPTIONS:
            env["ALIYUN_LLM_MODEL"] = model
            env["ALIYUN_LLM_MODELS"] = model
        elif model in PPINFRA_LLM_MODEL_OPTIONS:
            env["LLM_MODEL"] = model

    img_provider = (image_provider or DEFAULT_IMAGE_SOURCE).strip().lower()
    if img_provider == IMAGE_SOURCE_LOCAL:
        env["AUTO_IMAGE"] = "0"
        env.pop("IMAGE_PROVIDER", None)
        env.pop("ALIYUN_IMAGE_MODEL", None)
        env.pop("ALIYUN_IMAGE_MODELS", None)
        return env

    if img_provider not in IMAGE_PROVIDER_OPTIONS:
        img_provider = DEFAULT_IMAGE_PROVIDER
    env["AUTO_IMAGE"] = "1"
    env["IMAGE_PROVIDER"] = img_provider

    if img_provider == "aliyun":
        selected_image = (image_model or DEFAULT_ALIYUN_IMAGE_MODELS).strip()
        env["ALIYUN_IMAGE_MODEL"] = selected_image
        env["ALIYUN_IMAGE_MODELS"] = selected_image
    else:
        env.pop("ALIYUN_IMAGE_MODEL", None)
        env.pop("ALIYUN_IMAGE_MODELS", None)

    return env


def ensure_daily_news_candidate_pool_env(
    env_overrides: dict[str, str],
    *,
    title: str,
    count: object,
) -> dict[str, str]:
    env = _clean_env(dict(env_overrides or {}))
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    try:
        count_int = int(count or 1)
    except (TypeError, ValueError):
        count_int = 1
    if (title or "").strip() != DEFAULT_TITLE or count_int <= 1:
        return env

    desired = max(60, count_int * 20)
    raw_current = (env.get("NEWS_MAX_RECORDS") or os.getenv("NEWS_MAX_RECORDS") or "").strip()
    try:
        current = int(raw_current) if raw_current else 0
    except ValueError:
        current = 0
    env["NEWS_MAX_RECORDS"] = str(max(current, desired))
    return env


def build_subprocess_env(env_overrides: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_clean_env(env_overrides or {}))
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def env_flag_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def env_int_value(value: str | None, default: int, *, min_value: int | None = None) -> int:
    try:
        parsed = int((value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    return parsed


@dataclass
class _RunState:
    proc: Optional[subprocess.Popen] = None
    thread: Optional[threading.Thread] = None
    running: bool = False


class UiEventQueue:
    """Queue callbacks from worker threads and drain them on the Tk main thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[Callable[..., None], tuple[object, ...]]] = queue.Queue()

    def put(self, callback: Callable[..., None], *args: object) -> None:
        self._queue.put((callback, args))

    def drain(self, *, max_items: int = 200) -> int:
        count = 0
        while count < max_items:
            try:
                callback, args = self._queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
            count += 1
        return count


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _heartbeat_line(elapsed_seconds: float) -> str:
    return (
        f"[gui] 仍在运行，已耗时 {_format_elapsed(elapsed_seconds)}；"
        "当前可能在等待新闻 API、LLM、VLM 生图或小红书页面响应。\n"
    )


class CommandRunner:
    def __init__(
        self,
        *,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
        on_status: Callable[[str], None] | None = None,
        heartbeat_seconds: float = DEFAULT_COMMAND_HEARTBEAT_S,
    ):
        self._on_line = on_line
        self._on_exit = on_exit
        self._on_status = on_status or (lambda _status: None)
        self._heartbeat_seconds = float(heartbeat_seconds)
        self._state = _RunState()

    def is_running(self) -> bool:
        return self._state.running or bool(self._state.proc and self._state.proc.poll() is None)

    def stop(self) -> None:
        if not self.is_running():
            self._on_line("[gui] 当前没有正在运行的任务。\n")
            self._on_status("空闲")
            return
        self._on_status("正在停止")
        proc = self._state.proc
        if not proc or proc.poll() is not None:
            self._on_line("[gui] 任务正在启动或已经结束，无法发送停止信号。\n")
            return
        try:
            proc.terminate()
            self._on_line("[gui] 已请求停止当前任务，正在等待子进程退出...\n")
        except Exception:
            self._on_line("[gui] 停止请求失败，请查看是否已有残留子进程。\n")

    def run(self, args: list[str], env: dict[str, str]) -> None:
        if self.is_running():
            self._on_line("[gui] 已有任务正在运行，请先停止当前任务。\n")
            return
        self._state.running = True
        self._on_status("运行中：正在启动")

        def _target() -> None:
            code = 1
            started_at = time.monotonic()
            next_heartbeat = started_at + self._heartbeat_seconds
            sentinel = object()
            try:
                self._on_line(f"[cmd] {' '.join(args)}\n")
                proc = subprocess.Popen(
                    args,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self._state.proc = proc
                self._on_status(f"运行中：pid={getattr(proc, 'pid', 'unknown')}")
                output_queue: queue.Queue[object] = queue.Queue()

                def _read_stdout() -> None:
                    try:
                        assert proc.stdout is not None
                        for line in proc.stdout:
                            output_queue.put(line)
                    except Exception as exc:
                        output_queue.put(f"[gui] 读取子进程输出失败：{exc}\n")
                    finally:
                        output_queue.put(sentinel)

                reader = threading.Thread(target=_read_stdout, daemon=True)
                reader.start()
                while True:
                    try:
                        item = output_queue.get(timeout=COMMAND_OUTPUT_POLL_S)
                    except queue.Empty:
                        if self._heartbeat_seconds > 0 and time.monotonic() >= next_heartbeat:
                            now = time.monotonic()
                            self._on_line(_heartbeat_line(now - started_at))
                            next_heartbeat = now + self._heartbeat_seconds
                        continue
                    if item is sentinel:
                        break
                    self._on_line(str(item))
                    if self._heartbeat_seconds > 0:
                        next_heartbeat = time.monotonic() + self._heartbeat_seconds
                code = int(proc.wait())
                reader.join(timeout=1)
            except Exception as exc:
                self._on_line(f"[gui] 运行失败：{exc}\n")
            finally:
                self._state.proc = None
                self._state.running = False
                self._on_status("空闲")
                self._on_exit(code)

        t = threading.Thread(target=_target, daemon=True)
        self._state.thread = t
        t.start()


def main() -> None:
    # Import tkinter lazily so tests can import this module without GUI dependencies.
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("Auto Redbook - 发布控制台")
    root.geometry("1180x760")
    root.minsize(1040, 680)

    palette = {
        "paper": "#f7f3ea",
        "panel": "#fffaf0",
        "ink": "#26231f",
        "muted": "#756e62",
        "line": "#d9cfbd",
        "accent": "#b75f35",
        "accent_dark": "#884421",
        "soft": "#efe5d3",
    }

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    base_font = ("Microsoft YaHei UI", 10)
    title_font = ("Microsoft YaHei UI", 18, "bold")
    section_font = ("Microsoft YaHei UI", 11, "bold")
    style.configure(".", font=base_font, background=palette["paper"], foreground=palette["ink"])
    style.configure("TFrame", background=palette["paper"])
    style.configure("Panel.TFrame", background=palette["panel"])
    style.configure("TLabel", background=palette["paper"], foreground=palette["ink"])
    style.configure("Muted.TLabel", background=palette["paper"], foreground=palette["muted"])
    style.configure("Panel.TLabel", background=palette["panel"], foreground=palette["ink"])
    style.configure("PanelMuted.TLabel", background=palette["panel"], foreground=palette["muted"])
    style.configure("Title.TLabel", font=title_font, background=palette["paper"], foreground=palette["ink"])
    style.configure("Section.TLabel", font=section_font, background=palette["paper"], foreground=palette["ink"])
    style.configure("PanelSection.TLabel", font=section_font, background=palette["panel"], foreground=palette["ink"])
    style.configure("Panel.TCheckbutton", background=palette["panel"], foreground=palette["ink"], padding=(0, 2))
    style.map("Panel.TCheckbutton", background=[("active", palette["panel"])])
    style.configure("Accent.TButton", foreground="#ffffff", background=palette["accent"], padding=(14, 7))
    style.map("Accent.TButton", background=[("active", palette["accent_dark"])])
    style.configure("TNotebook", background=palette["paper"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 8))

    persisted = load_env_file(ENV_GUI_PATH)

    def _env_default(key: str, default: str = "") -> str:
        return (persisted.get(key) or os.getenv(key) or default).strip()

    root.configure(bg=palette["paper"])

    header = ttk.Frame(root)
    header.pack(fill="x", padx=18, pady=(14, 10))
    ttk.Label(header, text="Auto Redbook 发布控制台", style="Title.TLabel").pack(side="left")
    ttk.Button(header, text="打开小红书创作平台", command=open_xhs_creator).pack(side="right")
    ttk.Button(header, text="登录/检查Profile", command=open_xhs_profile_login).pack(side="right", padx=(0, 8))
    ttk.Label(
        header,
        text="新闻生成、AI 配图、草稿状态和删除验证放在同一个工作流里，减少反复改配置文件。",
        style="Muted.TLabel",
    ).pack(side="left", padx=(18, 0))

    body = ttk.PanedWindow(root, orient="horizontal")
    body.pack(fill="both", expand=True, padx=18, pady=(0, 14))

    left = ttk.Frame(body)
    right = ttk.Frame(body)
    body.add(left, weight=3)
    body.add(right, weight=2)

    log_header = ttk.Frame(right)
    log_header.pack(fill="x", pady=(0, 8))
    ttk.Label(log_header, text="运行日志", style="Section.TLabel").pack(side="left")
    ttk.Label(log_header, text="实时输出 CLI 子进程", style="Muted.TLabel").pack(side="left", padx=(10, 0))

    log = ScrolledText(
        right,
        height=28,
        bg="#171411",
        fg="#f6eadb",
        insertbackground="#f6eadb",
        relief="flat",
        font=("Cascadia Mono", 10),
        wrap="word",
    )
    log.pack(fill="both", expand=True)

    ui_events = UiEventQueue()

    def _append_log(s: str) -> None:
        log.insert("end", s)
        log.see("end")

    def _append_exit(code: int) -> None:
        _append_log(f"\n[exit] code={code}\n")

    def _drain_ui_events() -> None:
        ui_events.drain()
        root.after(50, _drain_ui_events)

    def log_line(s: str) -> None:
        ui_events.put(_append_log, s)

    def log_exit(code: int) -> None:
        ui_events.put(_append_exit, code)

    status_var = tk.StringVar(value="状态：空闲")

    def _set_status(status: str) -> None:
        status_var.set(f"状态：{status}")

    def log_status(status: str) -> None:
        ui_events.put(_set_status, status)

    root.after(50, _drain_ui_events)

    runner = CommandRunner(on_line=log_line, on_exit=log_exit, on_status=log_status)

    log_actions = ttk.Frame(right)
    log_actions.pack(fill="x", pady=(8, 0))
    ttk.Button(log_actions, text="停止当前任务", command=runner.stop).pack(side="left")
    ttk.Button(log_actions, text="清空日志", command=lambda: log.delete("1.0", "end")).pack(
        side="left", padx=(8, 0)
    )
    ttk.Label(log_actions, textvariable=status_var, style="Muted.TLabel").pack(side="right")

    nb = ttk.Notebook(left)
    nb.pack(fill="both", expand=True)

    def _add_scrollable_tab(text: str):
        outer = ttk.Frame(nb)
        nb.add(outer, text=text)
        canvas = tk.Canvas(outer, bg=palette["paper"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_inner_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def _on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_inner_width)
        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        inner.bind("<Enter>", _bind_mousewheel)
        inner.bind("<Leave>", _unbind_mousewheel)
        return inner

    cfg_vars: dict[str, tk.StringVar] = {}

    def _add_labeled_entry(parent, row: int, label: str, var, *, width: int = 44, secret: bool = False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=var, width=width, show="*" if secret else "")
        entry.grid(row=row, column=1, sticky="we", pady=5, padx=(10, 0))
        return entry

    def _add_execution_options(
        parent,
        *,
        dry_run_var,
        headless_var,
        login_hold_var,
        wait_timeout_var,
        force_var=None,
        dry_label: str = "dry-run 只验证",
        headless_label: str = "无界面上传",
    ) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 10))
        panel.pack(fill="x", padx=4, pady=(8, 10))
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="运行选项", style="PanelSection.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            panel,
            text="无界面模式需要已登录的工作区 Profile；首次扫码或验证码请先用可视浏览器完成。",
            style="PanelMuted.TLabel",
            wraplength=620,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ttk.Frame(panel, style="Panel.TFrame")
        body.grid(row=2, column=0, sticky="we", pady=(10, 0))
        body.columnconfigure(0, weight=1)

        mode_row = ttk.Frame(body, style="Panel.TFrame")
        mode_row.grid(row=0, column=0, sticky="nw")
        ttk.Checkbutton(
            mode_row,
            text=dry_label,
            variable=dry_run_var,
            style="Panel.TCheckbutton",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Checkbutton(
            mode_row,
            text=headless_label,
            variable=headless_var,
            style="Panel.TCheckbutton",
        ).grid(row=0, column=1, sticky="w", padx=(20, 0), pady=(0, 2))
        if force_var is not None:
            ttk.Checkbutton(
                mode_row,
                text="force 跳过校验",
                variable=force_var,
                style="Panel.TCheckbutton",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        wait_row = ttk.Frame(body, style="Panel.TFrame")
        wait_row.grid(row=0, column=1, sticky="ne", padx=(24, 0))
        ttk.Label(wait_row, text="登录等待（秒）", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Spinbox(wait_row, from_=0, to=3600, textvariable=login_hold_var, width=8).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 4)
        )
        ttk.Label(wait_row, text="页面等待（秒）", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Spinbox(wait_row, from_=30, to=3600, textvariable=wait_timeout_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(8, 0)
        )

    def _cfg_var(key: str, default: str = ""):
        var = tk.StringVar(value=_env_default(key, default))
        cfg_vars[key] = var
        return var

    def _collect_env_overrides() -> dict[str, str]:
        return _clean_env({k: var.get().strip() for k, var in cfg_vars.items()})

    def _run_command(subcommand: str, params: dict[str, object], env_overrides: dict[str, str]) -> None:
        try:
            args = build_cli_args(subcommand, params=params)
        except Exception as exc:
            log_line(f"[gui] 参数错误：{exc}\n")
            return
        if subcommand in ("auto", "create"):
            env_overrides = ensure_daily_news_candidate_pool_env(
                env_overrides,
                title=str(params.get("title") or ""),
                count=params.get("count") or 1,
            )
        runner.run(args, build_subprocess_env(env_overrides))

    # --- Auto tab ---
    tab_auto = _add_scrollable_tab("自动发帖")

    auto_top = ttk.Frame(tab_auto)
    auto_top.pack(fill="x", padx=4, pady=(8, 10))
    ttk.Label(auto_top, text="一键生成并保存草稿", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        auto_top,
        text="推荐先 dry-run 验证登录与页面状态，再关闭 dry-run 保存草稿。",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    auto_grid = ttk.Frame(tab_auto)
    auto_grid.columnconfigure(1, weight=1)
    auto_grid.columnconfigure(3, weight=1)

    title_var = tk.StringVar(value=DEFAULT_TITLE)
    assets_var = tk.StringVar(value=DEFAULT_ASSETS_GLOB)
    count_var = tk.IntVar(value=1)
    no_copy_var = tk.BooleanVar(value=False)
    dry_run_var = tk.BooleanVar(value=False)
    headless_var = tk.BooleanVar(value=False)
    force_var = tk.BooleanVar(value=False)
    login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)
    evaluation_viewpoint_var = tk.StringVar(value=DEFAULT_EVALUATION_VIEWPOINT)

    prompt_placeholder = "可选，例如：中国要闻 / 科技热点 / 上海周末活动"

    def _init_prompt_placeholder(widget) -> None:
        widget.insert("1.0", prompt_placeholder)
        widget.configure(fg=palette["muted"])

        def _on_focus_in(_evt=None) -> None:
            cur = widget.get("1.0", "end-1c")
            if cur.strip() == prompt_placeholder:
                widget.delete("1.0", "end")
                widget.configure(fg=palette["ink"])

        def _on_focus_out(_evt=None) -> None:
            cur = widget.get("1.0", "end-1c")
            if not cur.strip():
                widget.insert("1.0", prompt_placeholder)
                widget.configure(fg=palette["muted"])

        widget.bind("<FocusIn>", _on_focus_in)
        widget.bind("<FocusOut>", _on_focus_out)

    def _read_prompt(widget) -> str:
        cur = widget.get("1.0", "end-1c")
        if cur.strip() == prompt_placeholder:
            return ""
        return cur.strip()

    _add_labeled_entry(auto_grid, 0, "标题", title_var)
    quick_titles = ttk.Frame(auto_grid)
    quick_titles.grid(row=1, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(0, 5))
    ttk.Button(quick_titles, text="每日新闻", command=lambda: title_var.set("每日新闻")).pack(side="left")
    ttk.Button(quick_titles, text="每日假新闻", command=lambda: title_var.set("每日假新闻")).pack(
        side="left", padx=(8, 0)
    )

    ttk.Label(auto_grid, text="提示词").grid(row=2, column=0, sticky="nw", pady=5)
    prompt_text = tk.Text(auto_grid, height=4, relief="solid", bd=1, wrap="word", font=base_font)
    prompt_text.grid(row=2, column=1, columnspan=3, sticky="we", pady=5, padx=(10, 0))
    _init_prompt_placeholder(prompt_text)

    _add_labeled_entry(auto_grid, 3, "评价视角", evaluation_viewpoint_var)

    assets_entry = _add_labeled_entry(auto_grid, 4, "本地 assets glob", assets_var)
    assets_hint_var = tk.StringVar(value="")
    ttk.Label(auto_grid, textvariable=assets_hint_var, style="Muted.TLabel").grid(
        row=5, column=1, columnspan=3, sticky="w", padx=(10, 0), pady=(0, 4)
    )

    ttk.Label(auto_grid, text="数量").grid(row=6, column=0, sticky="w", pady=5)
    ttk.Spinbox(auto_grid, from_=1, to=50, textvariable=count_var, width=8).grid(
        row=6, column=1, sticky="w", pady=5, padx=(10, 0)
    )
    ttk.Checkbutton(auto_grid, text="不复制素材 (--no-copy)", variable=no_copy_var).grid(
        row=6, column=2, sticky="w", padx=(10, 0)
    )

    _add_execution_options(
        tab_auto,
        dry_run_var=dry_run_var,
        headless_var=headless_var,
        login_hold_var=login_hold_var,
        wait_timeout_var=wait_timeout_var,
        force_var=force_var,
        dry_label="dry-run 只验证",
        headless_label="无界面上传",
    )
    auto_grid.pack(fill="x", padx=4, pady=(0, 8))

    model_grid = ttk.Frame(tab_auto)
    model_grid.pack(fill="x", padx=4, pady=(10, 8))
    model_grid.columnconfigure(1, weight=1)
    model_grid.columnconfigure(3, weight=1)
    ttk.Label(model_grid, text="供应商与模型", style="Section.TLabel").grid(
        row=0, column=0, columnspan=4, sticky="w", pady=(0, 5)
    )

    llm_provider_var = tk.StringVar(value=_env_default("LLM_PROVIDER", DEFAULT_LLM_PROVIDER))
    initial_llm_model = (
        _env_default("ALIYUN_LLM_MODEL")
        or _env_default("LLM_MODEL")
        or DEFAULT_ALIYUN_LLM_MODEL
    )
    llm_model_var = tk.StringVar(value=initial_llm_model)
    initial_image_source = (
        _env_default("IMAGE_SOURCE")
        or _env_default("IMAGE_PROVIDER")
        or DEFAULT_IMAGE_SOURCE
    ).strip().lower()
    if initial_image_source not in IMAGE_SOURCE_OPTIONS:
        initial_image_source = DEFAULT_IMAGE_SOURCE
    image_provider_var = tk.StringVar(value=initial_image_source)
    image_model_var = tk.StringVar(
        value=_env_default("ALIYUN_IMAGE_MODEL", DEFAULT_ALIYUN_IMAGE_MODELS)
    )

    ttk.Label(model_grid, text="LLM 供应商").grid(row=1, column=0, sticky="w", pady=5)
    llm_provider_box = ttk.Combobox(
        model_grid,
        textvariable=llm_provider_var,
        values=LLM_PROVIDER_OPTIONS,
        state="readonly",
        width=14,
    )
    llm_provider_box.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)

    ttk.Label(model_grid, text="LLM 模型").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=5)
    llm_model_box = ttk.Combobox(model_grid, textvariable=llm_model_var, values=ALIYUN_LLM_MODEL_OPTIONS)
    llm_model_box.grid(row=1, column=3, sticky="we", padx=(10, 0), pady=5)

    ttk.Label(model_grid, text="图片来源").grid(row=2, column=0, sticky="w", pady=5)
    image_provider_box = ttk.Combobox(
        model_grid,
        textvariable=image_provider_var,
        values=IMAGE_SOURCE_OPTIONS,
        state="readonly",
        width=14,
    )
    image_provider_box.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=5)

    ttk.Label(model_grid, text="阿里云生图模型").grid(row=2, column=2, sticky="w", padx=(16, 0), pady=5)
    image_model_box = ttk.Combobox(
        model_grid,
        textvariable=image_model_var,
        values=ALIYUN_IMAGE_MODEL_OPTIONS,
    )
    image_model_box.grid(row=2, column=3, sticky="we", padx=(10, 0), pady=5)

    def _sync_llm_model_values(*_args) -> None:
        provider = llm_provider_var.get().strip().lower()
        if provider == "aliyun":
            values = ALIYUN_LLM_MODEL_OPTIONS
            fallback = DEFAULT_ALIYUN_LLM_MODEL
        elif provider == "ppinfra":
            values = PPINFRA_LLM_MODEL_OPTIONS
            fallback = DEFAULT_LLM_MODEL
        else:
            values = [AUTO_LLM_MODEL_OPTION] + ALIYUN_LLM_MODEL_OPTIONS + PPINFRA_LLM_MODEL_OPTIONS
            fallback = AUTO_LLM_MODEL_OPTION
        llm_model_box["values"] = values
        if llm_model_var.get() not in values:
            llm_model_var.set(fallback)

    def _sync_image_model_state(*_args) -> None:
        source = normalize_image_source(image_provider_var.get())
        if source == "aliyun":
            image_model_box.configure(state="normal")
        else:
            image_model_box.configure(state="disabled")
        if source == IMAGE_SOURCE_LOCAL:
            assets_entry.configure(state="normal")
            assets_hint_var.set("选择 local 时使用本地文件；找不到图片时不会自动调用 AI/Pexels。")
        else:
            assets_entry.configure(state="disabled")
            assets_hint_var.set(
                f"选择 {source} 时会忽略本地 assets，自动使用 {AUTO_IMAGE_ASSETS_GLOB} 触发自动配图。"
            )

    llm_provider_var.trace_add("write", _sync_llm_model_values)
    image_provider_var.trace_add("write", _sync_image_model_state)
    _sync_llm_model_values()
    _sync_image_model_state()

    def _auto_env() -> dict[str, str]:
        return build_provider_env_overrides(
            _collect_env_overrides(),
            llm_provider=llm_provider_var.get(),
            llm_model=llm_model_var.get(),
            image_provider=image_provider_var.get(),
            image_model=image_model_var.get(),
        )

    def _run_auto() -> None:
        params = {
            "title": title_var.get(),
            "prompt": _read_prompt(prompt_text),
            "evaluation_viewpoint": evaluation_viewpoint_var.get(),
            "assets_glob": assets_var.get(),
            "image_source": image_provider_var.get(),
            "count": count_var.get(),
            "no_copy": no_copy_var.get(),
            "dry_run": dry_run_var.get(),
            "headless": headless_var.get(),
            "login_hold": login_hold_var.get(),
            "wait_timeout": wait_timeout_var.get(),
            "force": force_var.get(),
        }
        _run_command("auto", params, _auto_env())

    action_bar = ttk.Frame(tab_auto)
    action_bar.pack(fill="x", padx=4, pady=(8, 0))
    ttk.Button(action_bar, text="运行 auto：生成并保存草稿", command=_run_auto, style="Accent.TButton").pack(
        side="left"
    )
    ttk.Label(
        action_bar,
        text="模型选择会作为环境变量注入本次任务，不会写入密钥文件。",
        style="Muted.TLabel",
    ).pack(side="left", padx=(14, 0))

    def _maybe_autorun_from_env() -> None:
        if (os.getenv("AUTO_REDBOOK_GUI_AUTORUN") or "").strip().lower() != "auto":
            return

        title_var.set(os.getenv("AUTO_REDBOOK_GUI_TITLE") or DEFAULT_TITLE)
        evaluation_viewpoint_var.set(
            os.getenv("AUTO_REDBOOK_GUI_EVALUATION_VIEWPOINT") or DEFAULT_EVALUATION_VIEWPOINT
        )
        assets_var.set(os.getenv("AUTO_REDBOOK_GUI_ASSETS_GLOB") or AUTO_IMAGE_ASSETS_GLOB)
        count_var.set(env_int_value(os.getenv("AUTO_REDBOOK_GUI_COUNT"), count_var.get(), min_value=1))
        dry_run_var.set(env_flag_enabled(os.getenv("AUTO_REDBOOK_GUI_DRY_RUN")))
        headless_var.set(env_flag_enabled(os.getenv("AUTO_REDBOOK_GUI_HEADLESS")))
        force_var.set(env_flag_enabled(os.getenv("AUTO_REDBOOK_GUI_FORCE")))
        login_hold_var.set(env_int_value(os.getenv("AUTO_REDBOOK_GUI_LOGIN_HOLD"), login_hold_var.get(), min_value=0))
        wait_timeout_var.set(env_int_value(os.getenv("AUTO_REDBOOK_GUI_WAIT_TIMEOUT"), wait_timeout_var.get(), min_value=30))

        image_provider_var.set(os.getenv("AUTO_REDBOOK_GUI_IMAGE_SOURCE") or DEFAULT_IMAGE_SOURCE)
        image_model_var.set(os.getenv("AUTO_REDBOOK_GUI_IMAGE_MODEL") or image_model_var.get())
        llm_provider_var.set(os.getenv("AUTO_REDBOOK_GUI_LLM_PROVIDER") or llm_provider_var.get())
        llm_model_var.set(os.getenv("AUTO_REDBOOK_GUI_LLM_MODEL") or llm_model_var.get())

        prompt_value = (os.getenv("AUTO_REDBOOK_GUI_PROMPT") or "").strip()
        if prompt_value:
            prompt_text.delete("1.0", "end")
            prompt_text.insert("1.0", prompt_value)
            prompt_text.configure(fg=palette["ink"])

        log_line("[gui] AUTO_REDBOOK_GUI_AUTORUN=auto，已从 GUI 自动触发 auto 任务。\n")
        root.after(300, _run_auto)

    root.after(500, _maybe_autorun_from_env)

    # --- Create tab ---
    tab_create = ttk.Frame(nb)
    nb.add(tab_create, text="仅生成")
    create_grid = ttk.Frame(tab_create)
    create_grid.pack(fill="x", padx=4, pady=12)
    create_grid.columnconfigure(1, weight=1)

    create_title_var = tk.StringVar(value=DEFAULT_TITLE)
    create_assets_var = tk.StringVar(value=DEFAULT_ASSETS_GLOB)
    create_count_var = tk.IntVar(value=1)
    create_no_copy_var = tk.BooleanVar(value=False)
    create_evaluation_viewpoint_var = tk.StringVar(value=DEFAULT_EVALUATION_VIEWPOINT)
    create_prompt = tk.Text(create_grid, height=4, relief="solid", bd=1, wrap="word", font=base_font)

    _add_labeled_entry(create_grid, 0, "标题", create_title_var)
    ttk.Label(create_grid, text="提示词").grid(row=1, column=0, sticky="nw", pady=5)
    create_prompt.grid(row=1, column=1, sticky="we", pady=5, padx=(10, 0))
    _init_prompt_placeholder(create_prompt)
    _add_labeled_entry(create_grid, 2, "评价视角", create_evaluation_viewpoint_var)
    _add_labeled_entry(create_grid, 3, "素材 glob", create_assets_var)
    ttk.Label(create_grid, text="数量").grid(row=4, column=0, sticky="w", pady=5)
    ttk.Spinbox(create_grid, from_=1, to=50, textvariable=create_count_var, width=8).grid(
        row=4, column=1, sticky="w", pady=5, padx=(10, 0)
    )
    ttk.Checkbutton(create_grid, text="不复制素材 (--no-copy)", variable=create_no_copy_var).grid(
        row=5, column=1, sticky="w", pady=5, padx=(10, 0)
    )

    def _run_create() -> None:
        params = {
            "title": create_title_var.get(),
            "prompt": _read_prompt(create_prompt),
            "evaluation_viewpoint": create_evaluation_viewpoint_var.get(),
            "assets_glob": create_assets_var.get(),
            "count": create_count_var.get(),
            "no_copy": create_no_copy_var.get(),
        }
        _run_command("create", params, _auto_env())

    ttk.Button(tab_create, text="运行 create：只生成本地草稿", command=_run_create, style="Accent.TButton").pack(
        anchor="w", padx=4, pady=(0, 10)
    )

    # --- Run tab ---
    tab_run = ttk.Frame(nb)
    nb.add(tab_run, text="草稿处理")
    run_grid = ttk.Frame(tab_run)
    run_grid.pack(fill="x", padx=4, pady=12)
    run_grid.columnconfigure(1, weight=1)

    post_id_var = tk.StringVar(value="")
    assets_glob_var = tk.StringVar(value="")
    run_dry_var = tk.BooleanVar(value=False)
    run_headless_var = tk.BooleanVar(value=False)
    run_force_var = tk.BooleanVar(value=False)
    run_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    run_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)
    post_lookup: dict[str, RecentPostSummary] = {}

    ttk.Label(run_grid, text="帖子").grid(row=0, column=0, sticky="w", pady=5)
    post_id_box = ttk.Combobox(run_grid, textvariable=post_id_var, values=[], width=68)
    post_id_box.grid(row=0, column=1, sticky="we", pady=5, padx=(10, 0))

    detail_frame = ttk.Frame(tab_run)
    detail_frame.pack(fill="both", expand=True, padx=4, pady=(0, 10))
    time_frame = ttk.Frame(detail_frame)
    time_frame.pack(fill="x", pady=(0, 8))
    ttk.Label(time_frame, text="时间（北京时间）", style="Section.TLabel").pack(anchor="w")
    post_time_detail = ScrolledText(
        time_frame,
        height=5,
        bg="#fffaf0",
        fg=palette["ink"],
        insertbackground=palette["ink"],
        relief="solid",
        bd=1,
        font=base_font,
        wrap="word",
    )
    post_time_detail.pack(fill="x", pady=(6, 0))
    ttk.Label(detail_frame, text="草稿详情", style="Section.TLabel").pack(anchor="w")
    post_detail = ScrolledText(
        detail_frame,
        height=10,
        bg="#fffaf0",
        fg=palette["ink"],
        insertbackground=palette["ink"],
        relief="solid",
        bd=1,
        font=base_font,
        wrap="word",
    )
    post_detail.pack(fill="both", expand=True, pady=(6, 0))

    def _set_post_detail(text: str) -> None:
        post_detail.configure(state="normal")
        post_detail.delete("1.0", "end")
        post_detail.insert("1.0", text)
        post_detail.configure(state="disabled")

    def _set_post_time_detail(text: str) -> None:
        post_time_detail.configure(state="normal")
        post_time_detail.delete("1.0", "end")
        post_time_detail.insert("1.0", text)
        post_time_detail.configure(state="disabled")

    def _suggest_run_assets_glob(pid: str) -> str:
        pid_norm = extract_post_id_from_choice(pid)
        return f"data/posts/{pid_norm}/assets/*" if pid_norm else ""

    def _refresh_post_ids() -> None:
        posts = list_recent_posts(project_root=PROJECT_ROOT, limit=80)
        post_lookup.clear()
        for post in posts:
            post_lookup[post.post_id] = post
        choices = [format_post_choice(post) for post in posts]
        post_id_box["values"] = choices
        if choices and not post_id_var.get().strip():
            post_id_var.set(choices[0])
        elif choices:
            _on_post_id_change()
        else:
            _set_post_time_detail("暂无本地草稿时间记录。")
            _set_post_detail("暂无本地草稿。")

    def _on_post_id_change(*_args) -> None:
        pid = extract_post_id_from_choice(post_id_var.get())
        if not pid:
            _set_post_time_detail("请选择一个本地草稿以查看北京时间。")
            _set_post_detail("请选择一个本地草稿。")
            return
        cur_assets = assets_glob_var.get().strip()
        if not cur_assets or cur_assets.startswith("data/posts/"):
            assets_glob_var.set(_suggest_run_assets_glob(pid))
        summary = post_lookup.get(pid)
        if summary:
            _set_post_time_detail(format_post_time_detail(summary))
            _set_post_detail(format_post_detail(summary))
        else:
            _set_post_time_detail("未找到本地草稿时间记录。")
            _set_post_detail(f"未找到本地草稿：{pid}")

    post_id_var.trace_add("write", _on_post_id_change)
    ttk.Button(run_grid, text="刷新", command=_refresh_post_ids).grid(
        row=0, column=2, sticky="e", padx=(8, 0), pady=5
    )
    _add_labeled_entry(run_grid, 1, "素材 glob", assets_glob_var)
    ttk.Label(run_grid, text="留空则使用 post 内素材", style="Muted.TLabel").grid(
        row=1, column=2, sticky="e", padx=(8, 0)
    )

    _add_execution_options(
        tab_run,
        dry_run_var=run_dry_var,
        headless_var=run_headless_var,
        login_hold_var=run_login_hold_var,
        wait_timeout_var=run_wait_timeout_var,
        force_var=run_force_var,
        dry_label="dry-run 只验证",
        headless_label="无界面上传",
    )

    run_buttons = ttk.Frame(tab_run)
    run_buttons.pack(fill="x", padx=4, pady=(0, 12))

    def _run_approve() -> None:
        _run_command(
            "approve",
            {"post_id": extract_post_id_from_choice(post_id_var.get()), "force": run_force_var.get()},
            _collect_env_overrides(),
        )

    def _run_run() -> None:
        _run_command(
            "run",
            {
                "post_id": extract_post_id_from_choice(post_id_var.get()),
                "assets_glob": assets_glob_var.get(),
                "dry_run": run_dry_var.get(),
                "headless": run_headless_var.get(),
                "login_hold": run_login_hold_var.get(),
                "wait_timeout": run_wait_timeout_var.get(),
                "force": run_force_var.get(),
            },
            _collect_env_overrides(),
        )

    ttk.Button(run_buttons, text="运行 approve：本地审核", command=_run_approve).pack(side="left")
    ttk.Button(run_buttons, text="运行 run：上传并保存草稿", command=_run_run, style="Accent.TButton").pack(
        side="left", padx=(8, 0)
    )
    _refresh_post_ids()

    # --- Delete drafts tab ---
    tab_delete = ttk.Frame(nb)
    nb.add(tab_delete, text="删除草稿")
    del_grid = ttk.Frame(tab_delete)
    del_grid.pack(fill="x", padx=4, pady=12)
    del_grid.columnconfigure(1, weight=1)

    draft_type_var = tk.StringVar(value="image")
    draft_loc_var = tk.StringVar(value="publish")
    draft_url_var = tk.StringVar(value=DEFAULT_DRAFT_URL)
    all_types_var = tk.BooleanVar(value=False)
    del_limit_var = tk.IntVar(value=0)
    del_headless_var = tk.BooleanVar(value=False)
    del_mode_var = tk.StringVar(value=DELETE_MODE_PREVIEW)
    del_confirm_var = tk.StringVar(value=DELETE_CONFIRM_ASK)
    del_hint_var = tk.StringVar(value="")
    del_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    del_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)

    ttk.Label(del_grid, text="草稿类型").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Combobox(del_grid, textvariable=draft_type_var, values=["image", "video", "article"], width=12).grid(
        row=0, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Checkbutton(del_grid, text="--all 所有类型", variable=all_types_var).grid(
        row=0, column=2, sticky="e", padx=(10, 0)
    )
    ttk.Label(del_grid, text="草稿位置").grid(row=1, column=0, sticky="w", pady=5)
    ttk.Combobox(del_grid, textvariable=draft_loc_var, values=["publish", "url"], width=12).grid(
        row=1, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Entry(del_grid, textvariable=draft_url_var).grid(row=1, column=2, sticky="we", padx=(10, 0), pady=5)
    ttk.Label(del_grid, text="删除模式").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Combobox(
        del_grid,
        textvariable=del_mode_var,
        values=DELETE_MODE_OPTIONS,
        state="readonly",
        width=28,
    ).grid(row=2, column=1, columnspan=2, sticky="we", padx=(10, 0), pady=5)

    ttk.Label(del_grid, text="limit (0=不限)").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=0, to=500, textvariable=del_limit_var, width=8).grid(
        row=3, column=1, sticky="w", padx=(10, 0), pady=5
    )

    ttk.Label(del_grid, text="确认方式").grid(row=4, column=0, sticky="w", pady=5)
    ttk.Combobox(
        del_grid,
        textvariable=del_confirm_var,
        values=DELETE_CONFIRM_OPTIONS,
        state="readonly",
        width=28,
    ).grid(row=4, column=1, columnspan=2, sticky="we", padx=(10, 0), pady=5)
    ttk.Label(del_grid, textvariable=del_hint_var, style="Muted.TLabel", wraplength=520).grid(
        row=5, column=0, columnspan=3, sticky="we", pady=(0, 8)
    )
    ttk.Checkbutton(del_grid, text="无界面运行 (--headless)", variable=del_headless_var).grid(
        row=6, column=2, sticky="e", padx=(10, 0)
    )
    ttk.Label(del_grid, text="login-hold").grid(row=6, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=0, to=3600, textvariable=del_login_hold_var, width=8).grid(
        row=6, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Label(del_grid, text="wait-timeout").grid(row=7, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=30, to=3600, textvariable=del_wait_timeout_var, width=8).grid(
        row=7, column=1, sticky="w", padx=(10, 0), pady=5
    )

    def _sync_delete_hint(*_args) -> None:
        dry_run, yes = resolve_delete_mode_flags(del_mode_var.get(), del_confirm_var.get())
        if dry_run:
            del_hint_var.set("当前为安全预览：只列出将被删除的草稿，不会删除任何平台草稿。")
        elif yes:
            del_hint_var.set("当前为正式删除 + 自动确认：点击后会直接删除匹配的小红书草稿，请先确认 limit 和 --all。")
        else:
            del_hint_var.set("当前为正式删除：命令行会再次询问确认，确认后才会删除平台草稿。")

    del_mode_var.trace_add("write", _sync_delete_hint)
    del_confirm_var.trace_add("write", _sync_delete_hint)
    _sync_delete_hint()

    def _run_delete() -> None:
        dry_run, yes = resolve_delete_mode_flags(del_mode_var.get(), del_confirm_var.get())
        _run_command(
            "delete-drafts",
            {
                "draft_type": draft_type_var.get(),
                "draft_location": draft_loc_var.get(),
                "draft_url": draft_url_var.get(),
                "all_types": all_types_var.get(),
                "limit": del_limit_var.get(),
                "dry_run": dry_run,
                "headless": del_headless_var.get(),
                "yes": yes,
                "login_hold": del_login_hold_var.get(),
                "wait_timeout": del_wait_timeout_var.get(),
            },
            _collect_env_overrides(),
        )

    ttk.Button(tab_delete, text="运行 delete-drafts", command=_run_delete, style="Accent.TButton").pack(
        anchor="w", padx=4, pady=(0, 10)
    )

    # --- Config tab ---
    tab_cfg = ttk.Frame(nb)
    nb.add(tab_cfg, text="配置")
    cfg_intro = ttk.Frame(tab_cfg)
    cfg_intro.pack(fill="x", padx=4, pady=(10, 8))
    ttk.Label(cfg_intro, text="本机环境配置", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        cfg_intro,
        text=".env.gui 只保存在当前工作区，建议只放本机密钥和默认参数，不要提交。",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    cfg_grid = ttk.Frame(tab_cfg)
    cfg_grid.pack(fill="x", padx=4, pady=(0, 8))
    cfg_grid.columnconfigure(1, weight=1)

    row = 0
    for label, key, default, secret in [
        ("DashScope Key (DASHSCOPE_API_KEY)", "DASHSCOPE_API_KEY", "", True),
        ("ppinfra Key (LLM_API_KEY)", "LLM_API_KEY", "", True),
        ("NewsAPI Key (NEWS_API_KEY)", "NEWS_API_KEY", "", True),
        ("Pexels Key (PEXELS_API_KEY)", "PEXELS_API_KEY", "", True),
        ("Aliyun LLM Base URL", "ALIYUN_LLM_BASE_URL", DEFAULT_ALIYUN_LLM_BASE_URL, False),
        ("ppinfra Base URL", "LLM_BASE_URL", DEFAULT_LLM_BASE_URL, False),
        ("Aliyun Image Size", "ALIYUN_IMAGE_SIZE", DEFAULT_ALIYUN_IMAGE_SIZE, False),
        ("Aliyun Negative Prompt", "ALIYUN_IMAGE_NEGATIVE_PROMPT", DEFAULT_ALIYUN_IMAGE_NEGATIVE_PROMPT, False),
        ("NEWS_CHINA_RATIO", "NEWS_CHINA_RATIO", DEFAULT_NEWS_CHINA_RATIO, False),
        ("NEWS_CHINA_BONUS", "NEWS_CHINA_BONUS", DEFAULT_NEWS_CHINA_BONUS, False),
    ]:
        _add_labeled_entry(cfg_grid, row, label, _cfg_var(key, default), secret=secret)
        row += 1

    cfg_buttons = ttk.Frame(tab_cfg)
    cfg_buttons.pack(fill="x", padx=4, pady=(2, 0))

    def _save_env_gui() -> None:
        vals = _collect_env_overrides()
        save_env_file(ENV_GUI_PATH, vals)
        log_line(f"[gui] 已保存：{ENV_GUI_PATH}\n")

    def _reload_env_gui() -> None:
        vals = load_env_file(ENV_GUI_PATH)
        for k, var in cfg_vars.items():
            var.set(vals.get(k, _env_default(k, var.get())))
        log_line(f"[gui] 已加载：{ENV_GUI_PATH}\n")

    ttk.Button(cfg_buttons, text="保存 .env.gui", command=_save_env_gui, style="Accent.TButton").pack(side="left")
    ttk.Button(cfg_buttons, text="重新加载 .env.gui", command=_reload_env_gui).pack(side="left", padx=(8, 0))

    root.mainloop()


if __name__ == "__main__":
    main()
