from __future__ import annotations

import csv
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
from typing import Any, Callable, Mapping, Optional

from src.analytics.post_sync import find_post_for_published_metric
from src.analytics.published_metrics import analyze_published_metrics, render_published_metrics_analysis
from src.config import (
    ALIYUN_FREE_LLM_MODELS,
    DEFAULT_ALIYUN_LLM_BASE_URL,
    DEFAULT_ALIYUN_LLM_MODEL,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
)
from src.storage.files import latest_execution, published_metrics_paths
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


@dataclass(frozen=True)
class PublishedMetricTableRow:
    title: str = ""
    published_at: str = ""
    likes: int = 0
    comments: int = 0
    favorites: int = 0
    views: int = 0
    shares: int = 0
    captured_at: str = ""
    url: str = ""
    id: str = ""


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


def _post_publishable_date(post: RecentPostSummary) -> str:
    raw = post.uploaded_at or post.updated_at or post.created_at
    dt = _parse_stored_time(raw)
    if not dt:
        return ""
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d")


def list_publishable_drafts(
    *,
    project_root: Path = PROJECT_ROOT,
    date: str = "",
    limit: int = 200,
) -> list[RecentPostSummary]:
    """
    Local preview of creator-center drafts that were already uploaded by this tool.

    The date filter uses Beijing time because the GUI shows upload times in UTC+8.
    """
    date_norm = (date or "").strip()
    items: list[RecentPostSummary] = []
    for post in list_recent_posts(project_root=project_root, limit=max(limit, 200)):
        status = (post.status or "").strip()
        if not post.uploaded:
            continue
        if status in {"published", "failed", "canceled"}:
            continue
        if date_norm and _post_publishable_date(post) != date_norm:
            continue
        items.append(post)
        if limit and len(items) >= limit:
            break
    return items


def _metric_int(value: object) -> int:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return 0


def _metric_raw_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _published_metric_table_csv_path(*, project_root: Path = PROJECT_ROOT) -> Path:
    paths = published_metrics_paths(project_root / "data")
    if paths["latest_csv"].exists():
        return paths["latest_csv"]
    return paths["csv"]


def list_published_metric_table_rows(
    *,
    project_root: Path = PROJECT_ROOT,
    limit: int = 1000,
) -> list[PublishedMetricTableRow]:
    path = _published_metric_table_csv_path(project_root=project_root)
    if not path.exists():
        return []

    rows: list[PublishedMetricTableRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for item in csv.DictReader(f):
            raw = _metric_raw_dict(item.get("raw"))
            rows.append(
                PublishedMetricTableRow(
                    id=str(item.get("id") or ""),
                    captured_at=str(item.get("captured_at") or ""),
                    title=str(item.get("title") or "").strip() or "(无标题)",
                    url=str(item.get("url") or ""),
                    published_at=str(item.get("published_at") or ""),
                    likes=_metric_int(item.get("likes")),
                    comments=_metric_int(item.get("comments")),
                    favorites=_metric_int(item.get("favorites")),
                    views=_metric_int(raw.get("views")),
                    shares=_metric_int(raw.get("shares")),
                )
            )
            if limit and len(rows) >= limit:
                break
    return rows


def sort_published_metric_table_rows(
    rows: list[PublishedMetricTableRow],
    field: str,
    *,
    descending: bool = True,
) -> list[PublishedMetricTableRow]:
    numeric_fields = {"likes", "comments", "favorites", "views", "shares"}
    if field in numeric_fields:
        key = lambda row: getattr(row, field, 0)
    else:
        key = lambda row: str(getattr(row, field, "") or "").lower()
    return sorted(rows, key=key, reverse=descending)


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


def _read_post_json_for_preview(*, project_root: Path, post_id: str) -> dict[str, Any]:
    post_file = project_root / "data" / "posts" / post_id / "post.json"
    if not post_file.exists():
        return {}
    try:
        data = json.loads(post_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _metric_row_to_dict(row: PublishedMetricTableRow | dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, PublishedMetricTableRow):
        return {
            "id": row.id,
            "title": row.title,
            "url": row.url,
            "published_at": row.published_at,
            "likes": row.likes,
            "comments": row.comments,
            "favorites": row.favorites,
            "captured_at": row.captured_at,
            "raw": {"views": row.views, "shares": row.shares},
        }
    return dict(row) if isinstance(row, dict) else {}


def find_local_post_for_metric_row(
    row: PublishedMetricTableRow | dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> RecentPostSummary | None:
    post, _reason = find_post_for_published_metric(
        _metric_row_to_dict(row),
        base=project_root / "data",
    )
    if post is None:
        return None
    post_dir_path = project_root / "data" / "posts" / post.id
    return _read_post_summary(post_dir_path) if post_dir_path.exists() else None


def _preview_line(label: str, value: object) -> str:
    text = str(value if value is not None else "").strip()
    return f"{label}: {text}" if text else ""


def _preview_metric_lines(metric: dict[str, Any]) -> list[str]:
    raw = metric.get("raw") if isinstance(metric.get("raw"), dict) else {}
    rows = [
        ("published_at", metric.get("published_at")),
        ("captured_at", _format_display_time(str(metric.get("captured_at") or "")) or metric.get("captured_at")),
        ("views", raw.get("views")),
        ("likes", metric.get("likes")),
        ("comments", metric.get("comments")),
        ("favorites", metric.get("favorites")),
        ("shares", raw.get("shares")),
        ("url", metric.get("url")),
    ]
    return [line for label, value in rows if (line := _preview_line(label, value))]


def format_shared_draft_preview(
    *,
    post_id: str = "",
    post: RecentPostSummary | None = None,
    metric_row: PublishedMetricTableRow | dict[str, Any] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> str:
    metric = _metric_row_to_dict(metric_row)
    if not post_id and post is not None:
        post_id = post.post_id
    if not post_id and metric:
        matched = find_local_post_for_metric_row(metric, project_root=project_root)
        if matched is not None:
            post = matched
            post_id = matched.post_id

    data = _read_post_json_for_preview(project_root=project_root, post_id=post_id) if post_id else {}
    if not data and post is None and not metric:
        return "请选择左侧草稿或已发布数据行查看完整预览。"
    if not data and post is None:
        lines = ["已发布数据预览", "未匹配到本地草稿，以下为平台同步到的公开数据。", ""]
        lines.extend(_preview_metric_lines(metric))
        return "\n".join(line for line in lines if line != "")

    platform = data.get("platform") if isinstance(data.get("platform"), dict) else {}
    publish = platform.get("publish") if isinstance(platform.get("publish"), dict) else {}
    news = platform.get("news") if isinstance(platform.get("news"), dict) else {}
    source_api = news.get("source_api") if isinstance(news.get("source_api"), dict) else {}
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    topics = data.get("topics") if isinstance(data.get("topics"), list) else []
    actual_title = str(publish.get("actual_title") or "").strip()
    actual_body = str(publish.get("actual_body") or "").strip()
    title = actual_title or str(data.get("title") or (post.title if post else "") or "").strip()
    body = actual_body or str(data.get("body") or (post.body_preview if post else "") or "").strip()

    lines = [
        "草稿预览",
        _preview_line("title", title),
        _preview_line("post_id", data.get("id") or post_id),
        _preview_line("local_status", data.get("status") or (post.status if post else "")),
        _preview_line("uploaded", "yes" if data.get("uploaded") or (post and post.uploaded) else "no"),
        _preview_line("uploaded_at", _format_display_time(str(data.get("uploaded_at") or ""))),
        _preview_line("updated_at", _format_display_time(str(data.get("updated_at") or ""))),
        "",
        "发布同步",
        _preview_line("result", publish.get("result")),
        _preview_line("source", publish.get("source")),
        _preview_line("match_reason", publish.get("match_reason")),
        _preview_line("published_at", _format_display_time(str(publish.get("published_at") or "")) or publish.get("published_at")),
        _preview_line("url", publish.get("url")),
    ]
    publish_metrics = publish.get("metrics") if isinstance(publish.get("metrics"), dict) else {}
    if publish_metrics:
        lines.append(_preview_line("metrics", json.dumps(publish_metrics, ensure_ascii=False, separators=(",", ":"))))
    if metric:
        lines.append("")
        lines.append("平台已发布数据")
        lines.extend(_preview_metric_lines(metric))

    lines.extend(
        [
            "",
            "新闻来源",
            _preview_line("api_source", news.get("api_source") or news.get("provider")),
            _preview_line("provider", source_api.get("provider")),
            _preview_line("item_source", source_api.get("item_source")),
            _preview_line("item_domain", source_api.get("item_domain")),
            _preview_line("item_url", source_api.get("item_url")),
            "",
            "素材",
        ]
    )
    if assets:
        for idx, asset in enumerate(assets, 1):
            if isinstance(asset, dict):
                lines.append(f"{idx}. {asset.get('kind', 'asset')}: {asset.get('path', '')}")
            else:
                lines.append(f"{idx}. {asset}")
    else:
        lines.append("无素材记录")
    lines.extend(
        [
            "",
            _preview_line("topics", ", ".join(str(t) for t in topics if str(t).strip())),
            "",
            "正文",
            body or "无正文记录",
        ]
    )
    return "\n".join(line for line in lines if line is not None)


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

    if subcommand == "publish-drafts":
        draft_type = str(params.get("draft_type") or "image").strip()
        date = str(params.get("date") or "").strip()
        post_ids_raw = params.get("post_ids") or []
        if isinstance(post_ids_raw, str):
            post_ids = [p.strip() for p in re.split(r"[,;\s]+", post_ids_raw) if p.strip()]
        else:
            post_ids = [str(p).strip() for p in post_ids_raw if str(p).strip()]
        limit = int(params.get("limit") or 0)
        all_selected = bool(params.get("all") or False)
        dry_run = bool(params.get("dry_run") or False)
        headless = bool(params.get("headless") or False)
        yes = bool(params.get("yes") or False)
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 300)

        args.extend(["--draft-type", draft_type])
        if date:
            args.extend(["--date", date])
        for post_id in post_ids:
            args.extend(["--post-id", post_id])
        if limit:
            args.extend(["--limit", str(limit)])
        if all_selected:
            args.append("--all")
        if dry_run:
            args.append("--dry-run")
        if headless:
            args.append("--headless")
        if yes:
            args.append("--yes")
        args.extend(["--login-hold", str(login_hold)])
        args.extend(["--wait-timeout", str(wait_timeout)])
        return args

    if subcommand == "update-metrics":
        limit = int(params.get("limit") or 0)
        headless = bool(params.get("headless") or False)
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 300)

        args.extend(["--limit", str(limit)])
        if headless:
            args.append("--headless")
        args.extend(["--login-hold", str(login_hold)])
        args.extend(["--wait-timeout", str(wait_timeout)])
        return args

    if subcommand == "aliyun-quota":
        raw_models = params.get("models") or []
        if isinstance(raw_models, str):
            models = [m.strip() for m in re.split(r"[,;\s]+", raw_models) if m.strip()]
        else:
            models = [str(m).strip() for m in raw_models if str(m).strip()]
        headless = bool(params.get("headless") or False)
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 120)

        for model in models:
            args.extend(["--model", model])
        if headless:
            args.append("--headless")
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
    from tkinter import messagebox, ttk
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
    style.configure(
        "Metrics.Treeview",
        background=palette["panel"],
        fieldbackground=palette["panel"],
        foreground=palette["ink"],
        rowheight=28,
        bordercolor=palette["line"],
    )
    style.configure("Metrics.Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
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

    right_stack = ttk.PanedWindow(right, orient="vertical")
    right_stack.pack(fill="both", expand=True)
    log_panel = ttk.Frame(right_stack)
    preview_panel = ttk.Frame(right_stack, style="Panel.TFrame")
    right_stack.add(log_panel, weight=3)
    right_stack.add(preview_panel, weight=2)

    log_header = ttk.Frame(log_panel)
    log_header.pack(fill="x", pady=(0, 8))
    ttk.Label(log_header, text="运行日志", style="Section.TLabel").pack(side="left")
    ttk.Label(log_header, text="实时输出 CLI 子进程", style="Muted.TLabel").pack(side="left", padx=(10, 0))

    log = ScrolledText(
        log_panel,
        height=16,
        bg="#171411",
        fg="#f6eadb",
        insertbackground="#f6eadb",
        relief="flat",
        font=("Cascadia Mono", 10),
        wrap="word",
    )
    log.pack(fill="both", expand=True)

    preview_header = ttk.Frame(preview_panel, style="Panel.TFrame")
    preview_header.pack(fill="x", padx=10, pady=(10, 6))
    ttk.Label(preview_header, text="草稿预览", style="PanelSection.TLabel").pack(side="left")
    ttk.Label(
        preview_header,
        text="选中草稿处理 / 发布草稿 / 已发布数据中的记录后在这里查看完整信息",
        style="PanelMuted.TLabel",
    ).pack(side="left", padx=(10, 0))

    shared_preview = ScrolledText(
        preview_panel,
        height=16,
        bg="#fffaf0",
        fg=palette["ink"],
        insertbackground=palette["ink"],
        relief="flat",
        font=base_font,
        wrap="word",
    )
    shared_preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _set_shared_preview(text: str) -> None:
        shared_preview.configure(state="normal")
        shared_preview.delete("1.0", "end")
        shared_preview.insert("1.0", text)
        shared_preview.configure(state="disabled")

    _set_shared_preview("请选择左侧草稿或已发布数据行查看完整预览。")

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

    post_command_success_callbacks: list[Callable[[], None]] = []

    def log_exit(code: int) -> None:
        ui_events.put(_append_exit, code)
        callbacks = list(post_command_success_callbacks)
        post_command_success_callbacks.clear()
        if code == 0:
            for callback in callbacks:
                ui_events.put(callback)

    status_var = tk.StringVar(value="状态：空闲")

    def _set_status(status: str) -> None:
        status_var.set(f"状态：{status}")

    def log_status(status: str) -> None:
        ui_events.put(_set_status, status)

    root.after(50, _drain_ui_events)

    runner = CommandRunner(on_line=log_line, on_exit=log_exit, on_status=log_status)

    log_actions = ttk.Frame(log_panel)
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
    ttk.Button(quick_titles, text="每日AI讯息", command=lambda: title_var.set("每日AI讯息")).pack(
        side="left", padx=(8, 0)
    )
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
            _set_shared_preview("暂无本地草稿。")

    def _on_post_id_change(*_args) -> None:
        pid = extract_post_id_from_choice(post_id_var.get())
        if not pid:
            _set_post_time_detail("请选择一个本地草稿以查看北京时间。")
            _set_post_detail("请选择一个本地草稿。")
            _set_shared_preview("请选择一个本地草稿。")
            return
        cur_assets = assets_glob_var.get().strip()
        if not cur_assets or cur_assets.startswith("data/posts/"):
            assets_glob_var.set(_suggest_run_assets_glob(pid))
        summary = post_lookup.get(pid)
        if summary:
            _set_post_time_detail(format_post_time_detail(summary))
            _set_post_detail(format_post_detail(summary))
            _set_shared_preview(
                format_shared_draft_preview(
                    post_id=pid,
                    post=summary,
                    project_root=PROJECT_ROOT,
                )
            )
        else:
            _set_post_time_detail("未找到本地草稿时间记录。")
            _set_post_detail(f"未找到本地草稿：{pid}")
            _set_shared_preview(f"未找到本地草稿：{pid}")

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

    # --- Publish creator-center drafts tab ---
    tab_publish = ttk.Frame(nb)
    nb.add(tab_publish, text="发布草稿")
    publish_intro = ttk.Frame(tab_publish)
    publish_intro.pack(fill="x", padx=4, pady=(10, 8))
    ttk.Label(publish_intro, text="从小红书创作者中心草稿箱发布", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        publish_intro,
        text="先在表格里预览本地已上传草稿；可按北京时间日期筛选，也可多选具体草稿。正式发布前会再次确认。",
        style="Muted.TLabel",
        wraplength=720,
    ).pack(anchor="w", pady=(2, 0))

    publish_filter = ttk.Frame(tab_publish, style="Panel.TFrame", padding=(12, 10))
    publish_filter.pack(fill="x", padx=4, pady=(0, 10))
    publish_filter.columnconfigure(3, weight=1)
    publish_date_var = tk.StringVar(value=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d"))
    publish_limit_var = tk.IntVar(value=0)
    publish_dry_var = tk.BooleanVar(value=True)
    publish_headless_var = tk.BooleanVar(value=False)
    publish_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    publish_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)
    publish_status_var = tk.StringVar(value="点击刷新读取本地已上传草稿。")

    ttk.Label(publish_filter, text="发布日期（北京时间）", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(publish_filter, textvariable=publish_date_var, width=16).grid(row=0, column=1, sticky="w", padx=(8, 18))
    ttk.Label(publish_filter, text="limit", style="Panel.TLabel").grid(row=0, column=2, sticky="e")
    ttk.Spinbox(publish_filter, from_=0, to=500, textvariable=publish_limit_var, width=8).grid(
        row=0, column=3, sticky="w", padx=(8, 0)
    )
    ttk.Label(
        publish_filter,
        text="日期留空则显示全部本地已上传且未发布的草稿；limit=0 表示不限制。",
        style="PanelMuted.TLabel",
    ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

    publish_options = ttk.Frame(tab_publish, style="Panel.TFrame", padding=(12, 10))
    publish_options.pack(fill="x", padx=4, pady=(0, 10))
    ttk.Checkbutton(
        publish_options,
        text="只预览，不发布（推荐先运行）",
        variable=publish_dry_var,
        style="Panel.TCheckbutton",
    ).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(
        publish_options,
        text="无界面发布（需要已登录 Profile）",
        variable=publish_headless_var,
        style="Panel.TCheckbutton",
    ).grid(row=0, column=1, sticky="w", padx=(18, 0))
    ttk.Label(publish_options, text="登录等待（秒）", style="Panel.TLabel").grid(row=0, column=2, sticky="e", padx=(18, 8))
    ttk.Spinbox(publish_options, from_=0, to=3600, textvariable=publish_login_hold_var, width=8).grid(
        row=0, column=3, sticky="w"
    )
    ttk.Label(publish_options, text="页面等待（秒）", style="Panel.TLabel").grid(row=1, column=2, sticky="e", padx=(18, 8), pady=(6, 0))
    ttk.Spinbox(publish_options, from_=30, to=3600, textvariable=publish_wait_timeout_var, width=8).grid(
        row=1, column=3, sticky="w", pady=(6, 0)
    )

    publish_panel = ttk.Frame(tab_publish, style="Panel.TFrame", padding=(12, 10))
    publish_panel.pack(fill="both", expand=True, padx=4, pady=(0, 10))
    publish_panel.columnconfigure(0, weight=1)
    publish_panel.rowconfigure(2, weight=1)
    ttk.Label(publish_panel, textvariable=publish_status_var, style="PanelMuted.TLabel", wraplength=720).grid(
        row=0, column=0, columnspan=2, sticky="we"
    )

    publish_columns = [
        ("title", "标题", 220, "w"),
        ("uploaded_at", "上传时间（北京时间）", 178, "w"),
        ("status", "本地状态", 90, "center"),
        ("assets", "素材", 54, "e"),
        ("post_id", "post_id", 230, "w"),
    ]
    publish_tree = ttk.Treeview(
        publish_panel,
        columns=[c[0] for c in publish_columns],
        show="headings",
        height=10,
        selectmode="extended",
    )
    publish_tree.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
    publish_tree_y = ttk.Scrollbar(publish_panel, orient="vertical", command=publish_tree.yview)
    publish_tree_y.grid(row=2, column=1, sticky="ns", pady=(8, 0))
    publish_tree.configure(yscrollcommand=publish_tree_y.set)
    for field, label, width, anchor in publish_columns:
        publish_tree.heading(field, text=label)
        publish_tree.column(field, width=width, minwidth=48, anchor=anchor, stretch=(field == "title"))

    publish_preview = ScrolledText(
        publish_panel,
        height=9,
        bg="#fffaf0",
        fg=palette["ink"],
        insertbackground=palette["ink"],
        relief="solid",
        bd=1,
        font=base_font,
        wrap="word",
    )
    publish_preview.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
    publish_rows: dict[str, RecentPostSummary] = {}

    def _set_publish_preview(text: str) -> None:
        publish_preview.configure(state="normal")
        publish_preview.delete("1.0", "end")
        publish_preview.insert("1.0", text)
        publish_preview.configure(state="disabled")

    def _publish_tree_values(post: RecentPostSummary) -> tuple[object, ...]:
        return (
            _clean_display_title(post.title),
            _format_display_time(post.uploaded_at or post.updated_at or post.created_at),
            post.status,
            post.asset_count,
            post.post_id,
        )

    def _selected_publish_post_ids() -> list[str]:
        return [str(item) for item in publish_tree.selection() if str(item) in publish_rows]

    def _refresh_publish_drafts() -> None:
        publish_tree.delete(*publish_tree.get_children())
        publish_rows.clear()
        items = list_publishable_drafts(
            project_root=PROJECT_ROOT,
            date=publish_date_var.get().strip(),
            limit=publish_limit_var.get() or 200,
        )
        for idx, post in enumerate(items):
            publish_rows[post.post_id] = post
            tag = "odd" if idx % 2 else "even"
            publish_tree.insert("", "end", iid=post.post_id, values=_publish_tree_values(post), tags=(tag,))
        publish_tree.tag_configure("even", background=palette["panel"])
        publish_tree.tag_configure("odd", background=palette["soft"])
        if items:
            publish_status_var.set(f"已加载 {len(items)} 条可发布草稿。选中一条或多条可只发布选中项；不选中则按当前日期筛选结果发布。")
        else:
            publish_status_var.set("未找到匹配的本地已上传草稿。请先用自动发帖/草稿处理上传到小红书草稿箱。")
        _on_publish_selection_change()

    def _on_publish_selection_change(_evt=None) -> None:
        selected_ids = _selected_publish_post_ids()
        if selected_ids:
            selected = [publish_rows[pid] for pid in selected_ids]
            lines = [f"已选择 {len(selected)} 条草稿："]
        else:
            selected = list(publish_rows.values())
            lines = [f"未单独选择草稿；将按当前筛选结果处理 {len(selected)} 条。"]
        for post in selected[:8]:
            lines.append("")
            lines.append(format_post_detail(post))
        if len(selected) > 8:
            lines.append(f"\n... 还有 {len(selected) - 8} 条未显示")
        _set_publish_preview("\n".join(lines) if selected else "暂无可预览草稿。")
        if selected:
            shared = format_shared_draft_preview(
                post_id=selected[0].post_id,
                post=selected[0],
                project_root=PROJECT_ROOT,
            )
            if len(selected) > 1:
                shared += f"\n\n---\n当前共选择 {len(selected)} 条草稿，右侧预览显示第一条。"
            _set_shared_preview(shared)
        else:
            _set_shared_preview("暂无可预览草稿。")

    publish_tree.bind("<<TreeviewSelect>>", _on_publish_selection_change)

    publish_buttons = ttk.Frame(tab_publish)
    publish_buttons.pack(fill="x", padx=4, pady=(0, 12))

    def _run_publish_drafts() -> None:
        selected_ids = _selected_publish_post_ids()
        target_count = len(selected_ids) if selected_ids else len(publish_rows)
        if target_count <= 0:
            log_line("[gui] 没有可发布的草稿。\n")
            return
        dry_run = publish_dry_var.get()
        if not dry_run:
            ok = messagebox.askyesno(
                "确认发布草稿",
                f"将从小红书创作者中心发布 {target_count} 条草稿。\n\n确认继续吗？",
            )
            if not ok:
                log_line("[gui] 已取消发布草稿。\n")
                return
        if not runner.is_running():
            post_command_success_callbacks.append(_refresh_publish_drafts)
            post_command_success_callbacks.append(_refresh_post_ids)
        _run_command(
            "publish-drafts",
            {
                "draft_type": "image",
                "date": publish_date_var.get().strip(),
                "post_ids": selected_ids,
                "limit": publish_limit_var.get(),
                "dry_run": dry_run,
                "headless": publish_headless_var.get(),
                "yes": not dry_run,
                "login_hold": publish_login_hold_var.get(),
                "wait_timeout": publish_wait_timeout_var.get(),
            },
            _collect_env_overrides(),
        )

    ttk.Button(publish_buttons, text="刷新可发布草稿", command=_refresh_publish_drafts).pack(side="left")
    ttk.Button(
        publish_buttons,
        text="发布/预览选中的草稿",
        command=_run_publish_drafts,
        style="Accent.TButton",
    ).pack(side="left", padx=(8, 0))
    _refresh_publish_drafts()

    # --- Published metrics tab ---
    tab_metrics = ttk.Frame(nb)
    nb.add(tab_metrics, text="已发布数据")
    metrics_intro = ttk.Frame(tab_metrics)
    metrics_intro.pack(fill="x", padx=4, pady=(10, 8))
    ttk.Label(metrics_intro, text="已发布稿件互动数据", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        metrics_intro,
        text="同步已发布笔记的点赞、评论、收藏，并保存到 data/analytics/published_metrics.csv 与 .jsonl。",
        style="Muted.TLabel",
        wraplength=720,
    ).pack(anchor="w", pady=(2, 0))

    metrics_grid = ttk.Frame(tab_metrics)
    metrics_grid.pack(fill="x", padx=4, pady=12)
    metrics_grid.columnconfigure(1, weight=1)

    metrics_limit_var = tk.IntVar(value=0)
    metrics_headless_var = tk.BooleanVar(value=False)
    metrics_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    metrics_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)

    ttk.Label(metrics_grid, text="同步数量 limit").grid(row=0, column=0, sticky="w", pady=5)
    ttk.Spinbox(metrics_grid, from_=0, to=500, textvariable=metrics_limit_var, width=8).grid(
        row=0, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Label(metrics_grid, text="0 表示按页面滚动上限尽量同步", style="Muted.TLabel").grid(
        row=0, column=2, sticky="w", padx=(10, 0), pady=5
    )

    metrics_options = ttk.Frame(tab_metrics, style="Panel.TFrame", padding=(12, 10))
    metrics_options.pack(fill="x", padx=4, pady=(8, 10))
    ttk.Label(metrics_options, text="同步选项", style="PanelSection.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        metrics_options,
        text="无界面同步需要该工作区 Profile 已登录；首次登录请先点击顶部“登录/检查Profile”。",
        style="PanelMuted.TLabel",
        wraplength=620,
    ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))
    ttk.Checkbutton(
        metrics_options,
        text="无界面同步",
        variable=metrics_headless_var,
        style="Panel.TCheckbutton",
    ).grid(row=2, column=0, sticky="w")
    ttk.Label(metrics_options, text="登录等待（秒）", style="Panel.TLabel").grid(
        row=2, column=1, sticky="e", padx=(24, 8)
    )
    ttk.Spinbox(metrics_options, from_=0, to=3600, textvariable=metrics_login_hold_var, width=8).grid(
        row=2, column=2, sticky="w"
    )
    ttk.Label(metrics_options, text="页面等待（秒）", style="Panel.TLabel").grid(
        row=3, column=1, sticky="e", padx=(24, 8), pady=(5, 0)
    )
    ttk.Spinbox(metrics_options, from_=30, to=3600, textvariable=metrics_wait_timeout_var, width=8).grid(
        row=3, column=2, sticky="w", pady=(5, 0)
    )

    metrics_table_panel = ttk.Frame(tab_metrics, style="Panel.TFrame", padding=(12, 10))
    metrics_table_panel.pack(fill="both", expand=True, padx=4, pady=(0, 10))
    metrics_table_panel.columnconfigure(0, weight=1)
    metrics_table_panel.rowconfigure(2, weight=1)

    metrics_table_header = ttk.Frame(metrics_table_panel, style="Panel.TFrame")
    metrics_table_header.grid(row=0, column=0, columnspan=2, sticky="we")
    metrics_table_header.columnconfigure(0, weight=1)
    ttk.Label(
        metrics_table_header,
        text="本地已发布数据表",
        style="PanelSection.TLabel",
    ).grid(row=0, column=0, sticky="w")

    metric_status_var = tk.StringVar(value="点击“刷新本地表格”读取 data/analytics/published_metrics_latest.csv。")
    ttk.Label(
        metrics_table_panel,
        textvariable=metric_status_var,
        style="PanelMuted.TLabel",
        wraplength=720,
    ).grid(row=1, column=0, columnspan=2, sticky="we", pady=(4, 8))

    metric_columns = [
        ("title", "标题", 230, "w"),
        ("published_at", "发布时间", 96, "center"),
        ("views", "浏览", 64, "e"),
        ("likes", "点赞", 64, "e"),
        ("comments", "评论", 64, "e"),
        ("favorites", "收藏", 64, "e"),
        ("shares", "分享", 64, "e"),
        ("captured_at", "同步时间", 172, "w"),
    ]
    metric_column_ids = [column[0] for column in metric_columns]
    metrics_tree = ttk.Treeview(
        metrics_table_panel,
        columns=metric_column_ids,
        show="headings",
        height=12,
        style="Metrics.Treeview",
    )
    metrics_tree.grid(row=2, column=0, sticky="nsew")
    metrics_tree_y = ttk.Scrollbar(metrics_table_panel, orient="vertical", command=metrics_tree.yview)
    metrics_tree_y.grid(row=2, column=1, sticky="ns")
    metrics_tree_x = ttk.Scrollbar(metrics_table_panel, orient="horizontal", command=metrics_tree.xview)
    metrics_tree_x.grid(row=3, column=0, sticky="we")
    metrics_tree.configure(yscrollcommand=metrics_tree_y.set, xscrollcommand=metrics_tree_x.set)

    metric_sort_state = {"field": "captured_at", "descending": True}
    metric_table_rows: list[PublishedMetricTableRow] = []
    metric_row_lookup: dict[str, PublishedMetricTableRow] = {}

    def _metric_table_display_path(path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)

    def _metric_table_values(row: PublishedMetricTableRow) -> tuple[object, ...]:
        captured = _format_display_time(row.captured_at) or row.captured_at
        return (
            row.title,
            row.published_at,
            row.views,
            row.likes,
            row.comments,
            row.favorites,
            row.shares,
            captured,
        )

    def _configure_metric_table_headings() -> None:
        for field, label, width, anchor in metric_columns:
            arrow = ""
            if metric_sort_state["field"] == field:
                arrow = " ↓" if metric_sort_state["descending"] else " ↑"
            metrics_tree.heading(field, text=f"{label}{arrow}", command=lambda col=field: _sort_metric_table(col))
            metrics_tree.column(field, width=width, minwidth=52, anchor=anchor, stretch=(field == "title"))

    def _render_metric_table(rows: list[PublishedMetricTableRow]) -> None:
        metrics_tree.delete(*metrics_tree.get_children())
        metric_row_lookup.clear()
        for idx, row in enumerate(rows):
            tag = "odd" if idx % 2 else "even"
            iid = f"metric-{idx}"
            metric_row_lookup[iid] = row
            metrics_tree.insert("", "end", iid=iid, values=_metric_table_values(row), tags=(tag,))
        metrics_tree.tag_configure("even", background=palette["panel"])
        metrics_tree.tag_configure("odd", background=palette["soft"])

    def _on_metric_selection_change(_evt=None) -> None:
        selected = metrics_tree.selection()
        if not selected:
            return
        row = metric_row_lookup.get(str(selected[0]))
        if row is None:
            return
        _set_shared_preview(format_shared_draft_preview(metric_row=row, project_root=PROJECT_ROOT))

    def _refresh_metric_table() -> None:
        nonlocal metric_table_rows
        metric_table_rows = list_published_metric_table_rows(project_root=PROJECT_ROOT, limit=2000)
        metric_table_rows = sort_published_metric_table_rows(
            metric_table_rows,
            str(metric_sort_state["field"]),
            descending=bool(metric_sort_state["descending"]),
        )
        _render_metric_table(metric_table_rows)
        _configure_metric_table_headings()
        path = _published_metric_table_csv_path(project_root=PROJECT_ROOT)
        if metric_table_rows:
            metric_status_var.set(
                f"已载入 {len(metric_table_rows)} 条本地已发布数据，来源：{_metric_table_display_path(path)}。点击列头可按点赞、评论、收藏等排序。"
            )
        else:
            metric_status_var.set(
                f"暂未找到本地已发布数据。请先点击上方“更新已发布数据”，或确认文件存在：{_metric_table_display_path(path)}。"
            )

    def _sort_metric_table(field: str) -> None:
        if metric_sort_state["field"] == field:
            metric_sort_state["descending"] = not bool(metric_sort_state["descending"])
        else:
            metric_sort_state["field"] = field
            metric_sort_state["descending"] = field in {"views", "likes", "comments", "favorites", "shares", "captured_at"}
        metric_table_rows[:] = sort_published_metric_table_rows(
            metric_table_rows,
            str(metric_sort_state["field"]),
            descending=bool(metric_sort_state["descending"]),
        )
        _render_metric_table(metric_table_rows)
        _configure_metric_table_headings()

    metric_analysis_frame = ttk.Frame(metrics_table_panel, style="Panel.TFrame")
    metric_analysis_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
    metric_analysis_frame.columnconfigure(0, weight=1)
    ttk.Label(metric_analysis_frame, text="发布方向分析", style="PanelSection.TLabel").grid(row=0, column=0, sticky="w")
    metric_analysis_text = ScrolledText(
        metric_analysis_frame,
        height=12,
        bg="#fffaf0",
        fg=palette["ink"],
        insertbackground=palette["ink"],
        relief="solid",
        bd=1,
        font=base_font,
        wrap="word",
    )
    metric_analysis_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

    def _set_metric_analysis(text: str) -> None:
        metric_analysis_text.configure(state="normal")
        metric_analysis_text.delete("1.0", "end")
        metric_analysis_text.insert("1.0", text)
        metric_analysis_text.configure(state="disabled")

    def _analyze_metric_table() -> None:
        report = analyze_published_metrics(base=PROJECT_ROOT / "data")
        _set_metric_analysis(render_published_metrics_analysis(report))
        metric_status_var.set("已根据本地已发布数据生成发布方向分析；如刚同步完平台数据，可再次点击分析刷新结论。")

    _configure_metric_table_headings()
    metrics_tree.bind("<<TreeviewSelect>>", _on_metric_selection_change)

    def _run_update_metrics() -> None:
        if not runner.is_running():
            post_command_success_callbacks.append(_refresh_metric_table)
            post_command_success_callbacks.append(_refresh_post_ids)
            post_command_success_callbacks.append(_refresh_publish_drafts)
        _run_command(
            "update-metrics",
            {
                "limit": metrics_limit_var.get(),
                "headless": metrics_headless_var.get(),
                "login_hold": metrics_login_hold_var.get(),
                "wait_timeout": metrics_wait_timeout_var.get(),
            },
            _collect_env_overrides(),
        )

    ttk.Button(
        metrics_table_header,
        text="更新已发布数据：点赞 / 评论 / 收藏",
        command=_run_update_metrics,
        style="Accent.TButton",
    ).grid(row=0, column=1, sticky="e", padx=(8, 0))
    ttk.Button(
        metrics_table_header,
        text="分析发布方向",
        command=_analyze_metric_table,
    ).grid(row=0, column=2, sticky="e", padx=(8, 0))
    ttk.Button(
        metrics_table_header,
        text="刷新本地表格",
        command=_refresh_metric_table,
    ).grid(row=0, column=3, sticky="e", padx=(8, 0))
    _refresh_metric_table()
    _analyze_metric_table()

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
        ("XHS Published URL", "XHS_PUBLISHED_URL", "", False),
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

    quota_panel = ttk.Frame(tab_cfg, style="Panel.TFrame", padding=(12, 10))
    quota_panel.pack(fill="x", padx=4, pady=(14, 10))
    quota_panel.columnconfigure(1, weight=1)
    ttk.Label(quota_panel, text="阿里云百炼额度查询", style="PanelSection.TLabel").grid(
        row=0, column=0, columnspan=4, sticky="w"
    )
    ttk.Label(
        quota_panel,
        text="Aliyun Bailian quota: 读取官方免费额度页；首次使用请用可视浏览器登录，之后可尝试无界面查询。",
        style="PanelMuted.TLabel",
        wraplength=720,
    ).grid(row=1, column=0, columnspan=4, sticky="we", pady=(2, 8))

    quota_models_var = tk.StringVar(value="qwen3.7-plus,wan2.7-image,wan2.7-image-pro")
    quota_headless_var = tk.BooleanVar(value=False)
    quota_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    quota_wait_timeout_var = tk.IntVar(value=120)

    ttk.Label(quota_panel, text="模型筛选", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Entry(quota_panel, textvariable=quota_models_var, width=52).grid(
        row=2, column=1, columnspan=3, sticky="we", padx=(10, 0), pady=5
    )
    ttk.Checkbutton(
        quota_panel,
        text="无界面查询",
        variable=quota_headless_var,
        style="Panel.TCheckbutton",
    ).grid(row=3, column=0, sticky="w", pady=5)
    ttk.Label(quota_panel, text="登录等待（秒）", style="Panel.TLabel").grid(
        row=3, column=1, sticky="e", padx=(10, 8), pady=5
    )
    ttk.Spinbox(quota_panel, from_=0, to=3600, textvariable=quota_login_hold_var, width=8).grid(
        row=3, column=2, sticky="w", pady=5
    )
    ttk.Label(quota_panel, text="页面等待（秒）", style="Panel.TLabel").grid(
        row=4, column=1, sticky="e", padx=(10, 8), pady=5
    )
    ttk.Spinbox(quota_panel, from_=30, to=3600, textvariable=quota_wait_timeout_var, width=8).grid(
        row=4, column=2, sticky="w", pady=5
    )

    def _run_aliyun_quota() -> None:
        _run_command(
            "aliyun-quota",
            {
                "models": quota_models_var.get(),
                "headless": quota_headless_var.get(),
                "login_hold": quota_login_hold_var.get(),
                "wait_timeout": quota_wait_timeout_var.get(),
            },
            _collect_env_overrides(),
        )

    ttk.Button(
        quota_panel,
        text="查询阿里云百炼额度",
        command=_run_aliyun_quota,
        style="Accent.TButton",
    ).grid(row=5, column=0, sticky="w", pady=(10, 0))

    root.mainloop()


if __name__ == "__main__":
    main()
