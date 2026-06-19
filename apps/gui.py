from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import (
    ALIYUN_FREE_LLM_MODELS,
    DEFAULT_ALIYUN_LLM_BASE_URL,
    DEFAULT_ALIYUN_LLM_MODEL,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
)
from src.storage.files import latest_execution


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
DEFAULT_LOGIN_HOLD = 600
DEFAULT_WAIT_TIMEOUT = 600

LLM_PROVIDER_OPTIONS = ["aliyun", "ppinfra", "auto"]
IMAGE_PROVIDER_OPTIONS = ["pexels", "aliyun"]

ALIYUN_LLM_MODEL_OPTIONS = list(ALIYUN_FREE_LLM_MODELS)
PPINFRA_LLM_MODEL_OPTIONS = [DEFAULT_LLM_MODEL]
AUTO_LLM_MODEL_OPTION = "阿里云免费模型列表（顺序回退）"

DEFAULT_LLM_PROVIDER = "aliyun"
DEFAULT_IMAGE_PROVIDER = "pexels"

ALIYUN_IMAGE_MODEL_OPTIONS = ["wan2.7-image", "wan2.7-image-pro"]
DEFAULT_ALIYUN_IMAGE_MODELS = ALIYUN_IMAGE_MODEL_OPTIONS[0]
DEFAULT_ALIYUN_IMAGE_SIZE = "1104*1472"
DEFAULT_ALIYUN_IMAGE_NEGATIVE_PROMPT = (
    "no text, no words, no letters, no watermark, no logo, no caption, no subtitle, no signature, no UI"
)

DEFAULT_NEWS_CHINA_RATIO = "0.6"
DEFAULT_NEWS_CHINA_BONUS = "0.15"
DEFAULT_DRAFT_URL = "https://creator.xiaohongshu.com/publish/publish?target=image"
POST_ID_RE = re.compile(r"[0-9a-fA-F]{32}")


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


def _format_display_time(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.replace("T", " ").rstrip("Z")
    if "." in text:
        text = text.split(".", 1)[0]
    return text


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
    time_value = post.uploaded_at if post.uploaded else (post.updated_at or post.latest_execution_ended_at)
    time_label = _format_display_time(time_value)
    time_part = f" · {time_label}" if time_label else ""
    return f"{_shorten_choice_text(post.title)}{status} · {format_upload_state(post)}{time_part} | {post.post_id}"


def format_post_detail(post: RecentPostSummary) -> str:
    lines = [
        f"标题：{post.title}",
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


def extract_post_id_from_choice(value: str) -> str:
    text = (value or "").strip()
    if _looks_like_post_id(text):
        return text.lower()
    matches = POST_ID_RE.findall(text)
    return matches[-1].lower() if matches else text


def list_recent_post_ids(*, project_root: Path = PROJECT_ROOT, limit: int = 50) -> list[str]:
    return [post.post_id for post in list_recent_posts(project_root=project_root, limit=limit)]


def open_xhs_creator() -> bool:
    return bool(webbrowser.open(DEFAULT_DRAFT_URL))


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
        assets_glob = str(params.get("assets_glob") or "assets/pics/*").strip()
        count = int(params.get("count") or 1)
        no_copy = bool(params.get("no_copy") or False)

        args.extend(["--title", title])
        if prompt:
            args.extend(["--prompt", prompt])
        if assets_glob:
            args.extend(["--assets-glob", assets_glob])
        args.extend(["--count", str(count)])
        if no_copy:
            args.append("--no-copy")

        if subcommand == "auto":
            dry_run = bool(params.get("dry_run") or False)
            login_hold = int(params.get("login_hold") or 0)
            wait_timeout = int(params.get("wait_timeout") or 300)
            force = bool(params.get("force") or False)
            if dry_run:
                args.append("--dry-run")
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
        login_hold = int(params.get("login_hold") or 0)
        wait_timeout = int(params.get("wait_timeout") or 300)
        force = bool(params.get("force") or False)

        args.append(post_id)
        if assets_glob:
            args.extend(["--assets-glob", assets_glob])
        if dry_run:
            args.append("--dry-run")
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

    img_provider = (image_provider or DEFAULT_IMAGE_PROVIDER).strip().lower()
    if img_provider not in IMAGE_PROVIDER_OPTIONS:
        img_provider = DEFAULT_IMAGE_PROVIDER
    env["IMAGE_PROVIDER"] = img_provider

    if img_provider == "aliyun":
        selected_image = (image_model or DEFAULT_ALIYUN_IMAGE_MODELS).strip()
        env["ALIYUN_IMAGE_MODEL"] = selected_image
        env["ALIYUN_IMAGE_MODELS"] = selected_image
    else:
        env.pop("ALIYUN_IMAGE_MODEL", None)
        env.pop("ALIYUN_IMAGE_MODELS", None)

    return env


def build_subprocess_env(env_overrides: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_clean_env(env_overrides or {}))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


@dataclass
class _RunState:
    proc: Optional[subprocess.Popen] = None
    thread: Optional[threading.Thread] = None


class CommandRunner:
    def __init__(self, *, on_line: Callable[[str], None], on_exit: Callable[[int], None]):
        self._on_line = on_line
        self._on_exit = on_exit
        self._state = _RunState()

    def is_running(self) -> bool:
        return bool(self._state.proc and self._state.proc.poll() is None)

    def stop(self) -> None:
        proc = self._state.proc
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception:
            pass

    def run(self, args: list[str], env: dict[str, str]) -> None:
        if self.is_running():
            self._on_line("[gui] 已有任务正在运行，请先停止当前任务。\n")
            return

        def _target() -> None:
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
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._on_line(line)
                code = int(proc.wait())
            except Exception as exc:
                self._on_line(f"[gui] 运行失败：{exc}\n")
                code = 1
            finally:
                self._state.proc = None
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
    style.configure("Title.TLabel", font=title_font, background=palette["paper"], foreground=palette["ink"])
    style.configure("Section.TLabel", font=section_font, background=palette["paper"], foreground=palette["ink"])
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

    def log_line(s: str) -> None:
        log.insert("end", s)
        log.see("end")

    def log_exit(code: int) -> None:
        log_line(f"\n[exit] code={code}\n")

    runner = CommandRunner(on_line=log_line, on_exit=log_exit)

    log_actions = ttk.Frame(right)
    log_actions.pack(fill="x", pady=(8, 0))
    ttk.Button(log_actions, text="停止当前任务", command=runner.stop).pack(side="left")
    ttk.Button(log_actions, text="清空日志", command=lambda: log.delete("1.0", "end")).pack(
        side="left", padx=(8, 0)
    )

    nb = ttk.Notebook(left)
    nb.pack(fill="both", expand=True)

    cfg_vars: dict[str, tk.StringVar] = {}

    def _add_labeled_entry(parent, row: int, label: str, var, *, width: int = 44, secret: bool = False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=var, width=width, show="*" if secret else "")
        entry.grid(row=row, column=1, sticky="we", pady=5, padx=(10, 0))
        return entry

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
        runner.run(args, build_subprocess_env(env_overrides))

    # --- Auto tab ---
    tab_auto = ttk.Frame(nb)
    nb.add(tab_auto, text="自动发帖")

    auto_top = ttk.Frame(tab_auto)
    auto_top.pack(fill="x", padx=4, pady=(8, 10))
    ttk.Label(auto_top, text="一键生成并保存草稿", style="Section.TLabel").pack(anchor="w")
    ttk.Label(
        auto_top,
        text="推荐先 dry-run 验证登录与页面状态，再关闭 dry-run 保存草稿。",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    auto_grid = ttk.Frame(tab_auto)
    auto_grid.pack(fill="x", padx=4, pady=(0, 8))
    auto_grid.columnconfigure(1, weight=1)
    auto_grid.columnconfigure(3, weight=1)

    title_var = tk.StringVar(value=DEFAULT_TITLE)
    assets_var = tk.StringVar(value=DEFAULT_ASSETS_GLOB)
    count_var = tk.IntVar(value=1)
    no_copy_var = tk.BooleanVar(value=False)
    dry_run_var = tk.BooleanVar(value=False)
    force_var = tk.BooleanVar(value=False)
    login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)

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
    quick_titles.grid(row=0, column=2, columnspan=2, sticky="e", padx=(10, 0))
    ttk.Button(quick_titles, text="每日新闻", command=lambda: title_var.set("每日新闻")).pack(side="left")
    ttk.Button(quick_titles, text="每日假新闻", command=lambda: title_var.set("每日假新闻")).pack(
        side="left", padx=(8, 0)
    )

    ttk.Label(auto_grid, text="提示词").grid(row=1, column=0, sticky="nw", pady=5)
    prompt_text = tk.Text(auto_grid, height=4, relief="solid", bd=1, wrap="word", font=base_font)
    prompt_text.grid(row=1, column=1, columnspan=3, sticky="we", pady=5, padx=(10, 0))
    _init_prompt_placeholder(prompt_text)

    _add_labeled_entry(auto_grid, 2, "素材 glob", assets_var)
    ttk.Label(auto_grid, text="没有本地图片时会按配图来源自动补图", style="Muted.TLabel").grid(
        row=2, column=2, columnspan=2, sticky="e", padx=(10, 0)
    )

    ttk.Label(auto_grid, text="数量").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Spinbox(auto_grid, from_=1, to=50, textvariable=count_var, width=8).grid(
        row=3, column=1, sticky="w", pady=5, padx=(10, 0)
    )
    ttk.Checkbutton(auto_grid, text="不复制素材 (--no-copy)", variable=no_copy_var).grid(
        row=3, column=2, sticky="w", padx=(10, 0)
    )
    ttk.Checkbutton(auto_grid, text="force 跳过校验错误继续", variable=force_var).grid(
        row=3, column=3, sticky="e"
    )

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
    image_provider_var = tk.StringVar(value=_env_default("IMAGE_PROVIDER", DEFAULT_IMAGE_PROVIDER))
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

    ttk.Label(model_grid, text="配图来源").grid(row=2, column=0, sticky="w", pady=5)
    image_provider_box = ttk.Combobox(
        model_grid,
        textvariable=image_provider_var,
        values=IMAGE_PROVIDER_OPTIONS,
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
        if image_provider_var.get().strip().lower() == "aliyun":
            image_model_box.configure(state="normal")
        else:
            image_model_box.configure(state="disabled")

    llm_provider_var.trace_add("write", _sync_llm_model_values)
    image_provider_var.trace_add("write", _sync_image_model_state)
    _sync_llm_model_values()
    _sync_image_model_state()

    timing = ttk.Frame(tab_auto)
    timing.pack(fill="x", padx=4, pady=(8, 8))
    ttk.Checkbutton(timing, text="dry-run 只验证不上传/保存", variable=dry_run_var).pack(side="left")
    ttk.Label(timing, text="login-hold").pack(side="left", padx=(18, 6))
    ttk.Spinbox(timing, from_=0, to=3600, textvariable=login_hold_var, width=8).pack(side="left")
    ttk.Label(timing, text="wait-timeout").pack(side="left", padx=(18, 6))
    ttk.Spinbox(timing, from_=30, to=3600, textvariable=wait_timeout_var, width=8).pack(side="left")

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
            "assets_glob": assets_var.get(),
            "count": count_var.get(),
            "no_copy": no_copy_var.get(),
            "dry_run": dry_run_var.get(),
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
    create_prompt = tk.Text(create_grid, height=4, relief="solid", bd=1, wrap="word", font=base_font)

    _add_labeled_entry(create_grid, 0, "标题", create_title_var)
    ttk.Label(create_grid, text="提示词").grid(row=1, column=0, sticky="nw", pady=5)
    create_prompt.grid(row=1, column=1, sticky="we", pady=5, padx=(10, 0))
    _init_prompt_placeholder(create_prompt)
    _add_labeled_entry(create_grid, 2, "素材 glob", create_assets_var)
    ttk.Label(create_grid, text="数量").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Spinbox(create_grid, from_=1, to=50, textvariable=create_count_var, width=8).grid(
        row=3, column=1, sticky="w", pady=5, padx=(10, 0)
    )
    ttk.Checkbutton(create_grid, text="不复制素材 (--no-copy)", variable=create_no_copy_var).grid(
        row=4, column=1, sticky="w", pady=5, padx=(10, 0)
    )

    def _run_create() -> None:
        params = {
            "title": create_title_var.get(),
            "prompt": _read_prompt(create_prompt),
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
    run_force_var = tk.BooleanVar(value=False)
    run_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    run_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)
    post_lookup: dict[str, RecentPostSummary] = {}

    ttk.Label(run_grid, text="帖子").grid(row=0, column=0, sticky="w", pady=5)
    post_id_box = ttk.Combobox(run_grid, textvariable=post_id_var, values=[], width=68)
    post_id_box.grid(row=0, column=1, sticky="we", pady=5, padx=(10, 0))

    detail_frame = ttk.Frame(tab_run)
    detail_frame.pack(fill="both", expand=True, padx=4, pady=(0, 10))
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
            _set_post_detail("暂无本地草稿。")

    def _on_post_id_change(*_args) -> None:
        pid = extract_post_id_from_choice(post_id_var.get())
        if not pid:
            _set_post_detail("请选择一个本地草稿。")
            return
        cur_assets = assets_glob_var.get().strip()
        if not cur_assets or cur_assets.startswith("data/posts/"):
            assets_glob_var.set(_suggest_run_assets_glob(pid))
        summary = post_lookup.get(pid)
        if summary:
            _set_post_detail(format_post_detail(summary))
        else:
            _set_post_detail(f"未找到本地草稿：{pid}")

    post_id_var.trace_add("write", _on_post_id_change)
    ttk.Button(run_grid, text="刷新", command=_refresh_post_ids).grid(
        row=0, column=2, sticky="e", padx=(8, 0), pady=5
    )
    _add_labeled_entry(run_grid, 1, "素材 glob", assets_glob_var)
    ttk.Label(run_grid, text="留空则使用 post 内素材", style="Muted.TLabel").grid(
        row=1, column=2, sticky="e", padx=(8, 0)
    )

    run_opts = ttk.Frame(tab_run)
    run_opts.pack(fill="x", padx=4, pady=(0, 8))
    ttk.Checkbutton(run_opts, text="dry-run 只验证", variable=run_dry_var).pack(side="left")
    ttk.Checkbutton(run_opts, text="force 跳过校验", variable=run_force_var).pack(side="left", padx=(12, 0))
    ttk.Label(run_opts, text="login-hold").pack(side="left", padx=(18, 6))
    ttk.Spinbox(run_opts, from_=0, to=3600, textvariable=run_login_hold_var, width=8).pack(side="left")
    ttk.Label(run_opts, text="wait-timeout").pack(side="left", padx=(18, 6))
    ttk.Spinbox(run_opts, from_=30, to=3600, textvariable=run_wait_timeout_var, width=8).pack(side="left")

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
    del_dry_var = tk.BooleanVar(value=True)
    del_yes_var = tk.BooleanVar(value=False)
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
    ttk.Label(del_grid, text="limit (0=不限)").grid(row=2, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=0, to=500, textvariable=del_limit_var, width=8).grid(
        row=2, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Checkbutton(del_grid, text="dry-run 只预览", variable=del_dry_var).grid(
        row=2, column=2, sticky="e", padx=(10, 0)
    )
    ttk.Checkbutton(del_grid, text="--yes 跳过确认", variable=del_yes_var).grid(
        row=3, column=2, sticky="e", padx=(10, 0)
    )
    ttk.Label(del_grid, text="login-hold").grid(row=3, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=0, to=3600, textvariable=del_login_hold_var, width=8).grid(
        row=3, column=1, sticky="w", padx=(10, 0), pady=5
    )
    ttk.Label(del_grid, text="wait-timeout").grid(row=4, column=0, sticky="w", pady=5)
    ttk.Spinbox(del_grid, from_=30, to=3600, textvariable=del_wait_timeout_var, width=8).grid(
        row=4, column=1, sticky="w", padx=(10, 0), pady=5
    )

    def _run_delete() -> None:
        _run_command(
            "delete-drafts",
            {
                "draft_type": draft_type_var.get(),
                "draft_location": draft_loc_var.get(),
                "draft_url": draft_url_var.get(),
                "all_types": all_types_var.get(),
                "limit": del_limit_var.get(),
                "dry_run": del_dry_var.get(),
                "yes": del_yes_var.get(),
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
