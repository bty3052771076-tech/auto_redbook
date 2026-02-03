from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


def _detect_project_root() -> Path:
    """
    Detect repository root for both source-run and PyInstaller-frozen exe.

    - Source run: apps/gui.py -> repo root is parent of apps/
    - Frozen exe: prefer the exe directory; if it's under dist/, use parent
    """
    candidates: list[Path] = []

    # PyInstaller: sys.executable is the exe path.
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent])

    # Normal source run.
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

DEFAULT_ALIYUN_LLM_MODEL = "deepseek-v3.2"
DEFAULT_ALIYUN_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

DEFAULT_IMAGE_PROVIDER = "aliyun"
DEFAULT_ALIYUN_IMAGE_MODELS = "qwen-image-plus-2026-01-09"
DEFAULT_ALIYUN_IMAGE_SIZE = "1104*1472"
# Keep this in env so it can be changed easily; default aims to reduce "image with text" issues.
DEFAULT_ALIYUN_IMAGE_NEGATIVE_PROMPT = (
    "no text, no words, no letters, no watermark, no logo, no caption, no subtitle, no signature, no UI"
)

DEFAULT_NEWS_CHINA_RATIO = "0.6"
DEFAULT_NEWS_CHINA_BONUS = "0.15"

DEFAULT_DRAFT_URL = "https://creator.xiaohongshu.com/publish/publish"


def list_recent_post_ids(*, project_root: Path = PROJECT_ROOT, limit: int = 50) -> list[str]:
    """
    List recent post ids from local storage (data/posts/<post_id>/).
    Used by the GUI to make "run/approve" easier.
    """
    posts_dir = project_root / "data" / "posts"
    if not posts_dir.exists():
        return []

    def _looks_like_post_id(name: str) -> bool:
        if len(name) != 32:
            return False
        return all(ch in "0123456789abcdef" for ch in name.lower())

    items: list[tuple[float, str]] = []
    for p in posts_dir.iterdir():
        if not p.is_dir():
            continue
        if not _looks_like_post_id(p.name):
            continue
        try:
            items.append((p.stat().st_mtime, p.name))
        except Exception:
            continue
    items.sort(key=lambda t: t[0], reverse=True)
    return [name for _, name in items[: max(0, int(limit or 0) or 50)]]


def _python_for_cli() -> str:
    """
    Use the workspace venv python if present so the GUI works when packaged as an exe.

    When running as a frozen exe, sys.executable points to the exe itself (not python),
    so we must avoid using it for `python -m apps.cli ...`.
    """
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)

    # Source run in venv: sys.executable should already be python.exe.
    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        return str(exe)

    # Last resort: rely on PATH.
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
        if not key:
            continue
        out[key] = _strip_quotes(v.strip())
    return out


def save_env_file(path: Path, values: dict[str, str]) -> None:
    lines: list[str] = []
    lines.append("# Local-only GUI config; DO NOT commit this file.")
    for k in sorted(values.keys()):
        v = (values.get(k) or "").strip()
        if not v:
            continue
        # Quote when needed.
        if any(ch.isspace() for ch in v) or "#" in v:
            v = '"' + v.replace('"', '\\"') + '"'
        lines.append(f"{k}={v}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_cli_args(subcommand: str, *, params: dict[str, object]) -> list[str]:
    """
    Build `python -m apps.cli <subcommand> ...` args from typed parameters.
    This is intentionally tiny: GUI focuses on common flags.
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
        force = bool(params.get("force") or False)
        args.append(post_id)
        if force:
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


def build_subprocess_env(env_overrides: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update({k: v for k, v in (env_overrides or {}).items() if (v or "").strip()})
    # Keep CLI output stable/UTF-8 when possible.
    env.setdefault("PYTHONIOENCODING", "utf-8")
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
            self._on_line("[gui] 已有任务在运行，请先停止。\n")
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
    root.title("Auto Redbook GUI")
    root.geometry("980x720")

    # Load persisted config (local-only).
    persisted = load_env_file(ENV_GUI_PATH)

    def _env_default(key: str, default: str = "") -> str:
        return (persisted.get(key) or os.getenv(key) or default).strip()

    PROMPT_PLACEHOLDER = "（可选）例如：中国要闻 / 科技 / 社会热点"

    def _init_prompt_placeholder(widget) -> None:
        widget.insert("1.0", PROMPT_PLACEHOLDER)
        widget.configure(fg="#888888")

        def _on_focus_in(_evt=None) -> None:
            cur = widget.get("1.0", "end-1c")
            if cur.strip() == PROMPT_PLACEHOLDER:
                widget.delete("1.0", "end")
                widget.configure(fg="#000000")

        def _on_focus_out(_evt=None) -> None:
            cur = widget.get("1.0", "end-1c")
            if not cur.strip():
                widget.insert("1.0", PROMPT_PLACEHOLDER)
                widget.configure(fg="#888888")

        widget.bind("<FocusIn>", _on_focus_in)
        widget.bind("<FocusOut>", _on_focus_out)

    def _read_prompt(widget) -> str:
        cur = widget.get("1.0", "end-1c")
        if cur.strip() == PROMPT_PLACEHOLDER:
            return ""
        return cur.strip()

    # --- shared widgets ---
    log = ScrolledText(root, height=16)
    log.pack(fill="both", expand=False, padx=10, pady=(10, 6))

    def log_line(s: str) -> None:
        log.insert("end", s)
        log.see("end")

    def log_exit(code: int) -> None:
        log_line(f"\n[exit] code={code}\n")

    runner = CommandRunner(on_line=log_line, on_exit=log_exit)

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=(0, 10))

    def _clear_log() -> None:
        log.delete("1.0", "end")

    stop_btn = ttk.Button(btn_frame, text="停止当前任务", command=runner.stop)
    stop_btn.pack(side="left")

    clear_btn = ttk.Button(btn_frame, text="清空日志", command=_clear_log)
    clear_btn.pack(side="left", padx=(8, 0))

    # --- tabs ---
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # --- Config tab ---
    tab_cfg = ttk.Frame(nb)
    nb.add(tab_cfg, text="配置")

    cfg_vars: dict[str, tk.StringVar] = {}

    def add_cfg_row(
        parent,
        row: int,
        label: str,
        key: str,
        *,
        secret: bool = False,
        default: str = "",
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = tk.StringVar(value=_env_default(key, default))
        cfg_vars[key] = var
        entry = ttk.Entry(parent, textvariable=var, width=70, show="*" if secret else "")
        entry.grid(row=row, column=1, sticky="we", pady=4)

    cfg_grid = ttk.Frame(tab_cfg)
    cfg_grid.pack(fill="both", expand=True)
    cfg_grid.columnconfigure(1, weight=1)

    row = 0
    ttk.Label(
        cfg_grid,
        text="这些配置会作为环境变量注入子进程（等价于命令行设置）。可保存到 .env.gui（已被 .gitignore 忽略）。",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 8))
    row += 1

    # Keys (optional)
    add_cfg_row(cfg_grid, row, "DashScope Key (DASHSCOPE_API_KEY)", "DASHSCOPE_API_KEY", secret=True)
    row += 1
    add_cfg_row(cfg_grid, row, "NewsAPI Key (NEWS_API_KEY)", "NEWS_API_KEY", secret=True)
    row += 1
    add_cfg_row(cfg_grid, row, "Pexels Key (PEXELS_API_KEY)", "PEXELS_API_KEY", secret=True)
    row += 1

    # LLM
    add_cfg_row(
        cfg_grid,
        row,
        "Aliyun LLM 模型 (ALIYUN_LLM_MODEL)",
        "ALIYUN_LLM_MODEL",
        default=DEFAULT_ALIYUN_LLM_MODEL,
    )
    row += 1
    add_cfg_row(
        cfg_grid,
        row,
        "Aliyun LLM Base URL (ALIYUN_LLM_BASE_URL)",
        "ALIYUN_LLM_BASE_URL",
        default=DEFAULT_ALIYUN_LLM_BASE_URL,
    )
    row += 1

    # Image
    add_cfg_row(
        cfg_grid,
        row,
        "图片提供商 (IMAGE_PROVIDER=aliyun/pexels)",
        "IMAGE_PROVIDER",
        default=DEFAULT_IMAGE_PROVIDER,
    )
    row += 1
    add_cfg_row(
        cfg_grid,
        row,
        "阿里云生图模型列表 (ALIYUN_IMAGE_MODELS)",
        "ALIYUN_IMAGE_MODELS",
        default=DEFAULT_ALIYUN_IMAGE_MODELS,
    )
    row += 1
    add_cfg_row(
        cfg_grid,
        row,
        "阿里云生图尺寸 (ALIYUN_IMAGE_SIZE)",
        "ALIYUN_IMAGE_SIZE",
        default=DEFAULT_ALIYUN_IMAGE_SIZE,
    )
    row += 1
    add_cfg_row(
        cfg_grid,
        row,
        "阿里云负面提示词 (ALIYUN_IMAGE_NEGATIVE_PROMPT)",
        "ALIYUN_IMAGE_NEGATIVE_PROMPT",
        default=DEFAULT_ALIYUN_IMAGE_NEGATIVE_PROMPT,
    )
    row += 1

    # News preference
    add_cfg_row(
        cfg_grid,
        row,
        "中国新闻比例 (NEWS_CHINA_RATIO, 默认0.6)",
        "NEWS_CHINA_RATIO",
        default=DEFAULT_NEWS_CHINA_RATIO,
    )
    row += 1
    add_cfg_row(
        cfg_grid,
        row,
        "中国新闻加分 (NEWS_CHINA_BONUS, 默认0.15)",
        "NEWS_CHINA_BONUS",
        default=DEFAULT_NEWS_CHINA_BONUS,
    )
    row += 1

    def _collect_env_overrides() -> dict[str, str]:
        out: dict[str, str] = {}
        for k, var in cfg_vars.items():
            v = (var.get() or "").strip()
            if v:
                out[k] = v
        return out

    def _save_env_gui() -> None:
        vals = _collect_env_overrides()
        save_env_file(ENV_GUI_PATH, vals)
        log_line(f"[gui] 已保存：{ENV_GUI_PATH}\n")

    def _reload_env_gui() -> None:
        vals = load_env_file(ENV_GUI_PATH)
        for k, var in cfg_vars.items():
            if k in vals:
                var.set(vals[k])
        log_line(f"[gui] 已加载：{ENV_GUI_PATH}\n")

    cfg_btns = ttk.Frame(tab_cfg)
    cfg_btns.pack(fill="x", pady=(8, 0))
    ttk.Button(cfg_btns, text="保存 .env.gui", command=_save_env_gui).pack(side="left")
    ttk.Button(cfg_btns, text="加载 .env.gui", command=_reload_env_gui).pack(side="left", padx=(8, 0))

    # --- Auto tab ---
    tab_auto = ttk.Frame(nb)
    nb.add(tab_auto, text="auto（生成+保存草稿）")

    def _common_form(parent) -> dict[str, object]:
        form: dict[str, object] = {}
        grid = ttk.Frame(parent)
        grid.pack(fill="x", padx=6, pady=6)
        grid.columnconfigure(1, weight=1)

        title_var = tk.StringVar(value=DEFAULT_TITLE)
        prompt_text = tk.Text(grid, height=4)
        assets_var = tk.StringVar(value=DEFAULT_ASSETS_GLOB)
        count_var = tk.IntVar(value=1)
        no_copy_var = tk.BooleanVar(value=False)

        _init_prompt_placeholder(prompt_text)

        ttk.Label(grid, text="标题").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(grid, textvariable=title_var).grid(row=0, column=1, sticky="we", pady=4)

        quick = ttk.Frame(grid)
        quick.grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Button(quick, text="每日新闻", command=lambda: title_var.set("每日新闻")).pack(side="left")
        ttk.Button(quick, text="每日假新闻", command=lambda: title_var.set("每日假新闻")).pack(
            side="left", padx=(6, 0)
        )

        ttk.Label(grid, text="提示词").grid(row=1, column=0, sticky="nw", pady=4)
        prompt_text.grid(row=1, column=1, columnspan=2, sticky="we", pady=4)

        ttk.Label(grid, text="素材 glob").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(grid, textvariable=assets_var).grid(row=2, column=1, sticky="we", pady=4)
        ttk.Label(grid, text="例如：assets/pics/*").grid(row=2, column=2, sticky="e", padx=(8, 0))

        ttk.Label(grid, text="数量").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=1, to=50, textvariable=count_var, width=6).grid(
            row=3, column=1, sticky="w", pady=4
        )
        ttk.Checkbutton(grid, text="不复制素材（--no-copy）", variable=no_copy_var).grid(
            row=3, column=2, sticky="e", pady=4
        )

        form["title_var"] = title_var
        form["prompt_text"] = prompt_text
        form["assets_var"] = assets_var
        form["count_var"] = count_var
        form["no_copy_var"] = no_copy_var
        return form

    auto_form = _common_form(tab_auto)

    auto_opts = ttk.Frame(tab_auto)
    auto_opts.pack(fill="x", padx=12, pady=(0, 8))
    dry_run_var = tk.BooleanVar(value=False)
    force_var = tk.BooleanVar(value=False)
    login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)

    ttk.Checkbutton(auto_opts, text="dry-run（仅打开/取证，不上传/保存）", variable=dry_run_var).pack(
        side="left"
    )
    ttk.Checkbutton(auto_opts, text="force（忽略校验错误继续）", variable=force_var).pack(
        side="left", padx=(12, 0)
    )
    ttk.Label(auto_opts, text="login-hold").pack(side="left", padx=(12, 0))
    ttk.Spinbox(auto_opts, from_=0, to=3600, textvariable=login_hold_var, width=6).pack(
        side="left"
    )
    ttk.Label(auto_opts, text="wait-timeout").pack(side="left", padx=(12, 0))
    ttk.Spinbox(auto_opts, from_=30, to=3600, textvariable=wait_timeout_var, width=6).pack(
        side="left"
    )

    def _run_auto() -> None:
        prompt = _read_prompt(auto_form["prompt_text"])
        params = {
            "title": auto_form["title_var"].get(),
            "prompt": prompt,
            "assets_glob": auto_form["assets_var"].get(),
            "count": auto_form["count_var"].get(),
            "no_copy": auto_form["no_copy_var"].get(),
            "dry_run": dry_run_var.get(),
            "login_hold": login_hold_var.get(),
            "wait_timeout": wait_timeout_var.get(),
            "force": force_var.get(),
        }
        args = build_cli_args("auto", params=params)
        env = build_subprocess_env(_collect_env_overrides())
        runner.run(args, env)

    ttk.Button(tab_auto, text="运行 auto", command=_run_auto).pack(anchor="w", padx=12, pady=(0, 10))

    # --- Create tab ---
    tab_create = ttk.Frame(nb)
    nb.add(tab_create, text="create（仅生成）")

    create_form = _common_form(tab_create)

    def _run_create() -> None:
        prompt = _read_prompt(create_form["prompt_text"])
        params = {
            "title": create_form["title_var"].get(),
            "prompt": prompt,
            "assets_glob": create_form["assets_var"].get(),
            "count": create_form["count_var"].get(),
            "no_copy": create_form["no_copy_var"].get(),
        }
        args = build_cli_args("create", params=params)
        env = build_subprocess_env(_collect_env_overrides())
        runner.run(args, env)

    ttk.Button(tab_create, text="运行 create", command=_run_create).pack(anchor="w", padx=12, pady=(0, 10))

    # --- Run tab ---
    tab_run = ttk.Frame(nb)
    nb.add(tab_run, text="run（仅上传）")

    run_grid = ttk.Frame(tab_run)
    run_grid.pack(fill="x", padx=12, pady=12)
    run_grid.columnconfigure(1, weight=1)

    post_id_var = tk.StringVar(value="")
    assets_glob_var = tk.StringVar(value="")

    ttk.Label(run_grid, text="post_id").grid(row=0, column=0, sticky="w", pady=4)
    post_id_box = ttk.Combobox(run_grid, textvariable=post_id_var, values=[], width=46)
    post_id_box.grid(row=0, column=1, sticky="we", pady=4)

    def _suggest_run_assets_glob(pid: str) -> str:
        pid_norm = (pid or "").strip()
        if not pid_norm:
            return ""
        return f"data/posts/{pid_norm}/assets/*"

    def _refresh_post_ids() -> None:
        ids = list_recent_post_ids(project_root=PROJECT_ROOT, limit=80)
        post_id_box["values"] = ids
        if ids and not (post_id_var.get() or "").strip():
            post_id_var.set(ids[0])

    def _on_post_id_change(*_args) -> None:
        pid = (post_id_var.get() or "").strip()
        if not pid:
            return
        cur_assets = (assets_glob_var.get() or "").strip()
        if not cur_assets or cur_assets.startswith("data/posts/"):
            assets_glob_var.set(_suggest_run_assets_glob(pid))

    post_id_var.trace_add("write", _on_post_id_change)

    ttk.Button(run_grid, text="刷新", command=_refresh_post_ids).grid(
        row=0, column=2, sticky="e", padx=(8, 0), pady=4
    )

    ttk.Label(run_grid, text="assets glob").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(run_grid, textvariable=assets_glob_var).grid(row=1, column=1, sticky="we", pady=4)
    ttk.Label(run_grid, text="留空则自动使用 post 内的素材").grid(
        row=1, column=2, sticky="e", padx=(8, 0), pady=4
    )

    run_opts = ttk.Frame(tab_run)
    run_opts.pack(fill="x", padx=12, pady=(0, 8))
    run_dry_var = tk.BooleanVar(value=False)
    run_force_var = tk.BooleanVar(value=False)
    run_login_hold_var = tk.IntVar(value=DEFAULT_LOGIN_HOLD)
    run_wait_timeout_var = tk.IntVar(value=DEFAULT_WAIT_TIMEOUT)

    ttk.Checkbutton(run_opts, text="dry-run（仅打开/取证）", variable=run_dry_var).pack(side="left")
    ttk.Checkbutton(run_opts, text="force（跳过校验/未审核也上传）", variable=run_force_var).pack(
        side="left", padx=(12, 0)
    )
    ttk.Label(run_opts, text="login-hold").pack(side="left", padx=(12, 0))
    ttk.Spinbox(run_opts, from_=0, to=3600, textvariable=run_login_hold_var, width=6).pack(side="left")
    ttk.Label(run_opts, text="wait-timeout").pack(side="left", padx=(12, 0))
    ttk.Spinbox(run_opts, from_=30, to=3600, textvariable=run_wait_timeout_var, width=6).pack(side="left")

    run_btns = ttk.Frame(tab_run)
    run_btns.pack(fill="x", padx=12, pady=(0, 10))

    def _run_approve() -> None:
        params = {"post_id": post_id_var.get(), "force": run_force_var.get()}
        args = build_cli_args("approve", params=params)
        env = build_subprocess_env(_collect_env_overrides())
        runner.run(args, env)

    def _run_run() -> None:
        params = {
            "post_id": post_id_var.get(),
            "assets_glob": assets_glob_var.get(),
            "dry_run": run_dry_var.get(),
            "login_hold": run_login_hold_var.get(),
            "wait_timeout": run_wait_timeout_var.get(),
            "force": run_force_var.get(),
        }
        args = build_cli_args("run", params=params)
        env = build_subprocess_env(_collect_env_overrides())
        runner.run(args, env)

    ttk.Button(run_btns, text="运行 approve（审核）", command=_run_approve).pack(side="left")
    ttk.Button(run_btns, text="运行 run（仅上传）", command=_run_run).pack(side="left", padx=(8, 0))

    _refresh_post_ids()

    # --- Delete drafts tab ---
    tab_delete = ttk.Frame(nb)
    nb.add(tab_delete, text="delete-drafts（删除草稿）")

    del_grid = ttk.Frame(tab_delete)
    del_grid.pack(fill="x", padx=12, pady=12)
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

    ttk.Label(del_grid, text="草稿类型").grid(row=0, column=0, sticky="w", pady=4)
    ttk.Combobox(del_grid, textvariable=draft_type_var, values=["image", "video", "article"], width=10).grid(
        row=0, column=1, sticky="w", pady=4
    )
    ttk.Checkbutton(del_grid, text="--all（所有类型）", variable=all_types_var).grid(
        row=0, column=2, sticky="e", pady=4
    )

    ttk.Label(del_grid, text="草稿位置").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Combobox(del_grid, textvariable=draft_loc_var, values=["publish", "url"], width=10).grid(
        row=1, column=1, sticky="w", pady=4
    )
    ttk.Entry(del_grid, textvariable=draft_url_var).grid(row=1, column=2, sticky="we", pady=4)

    ttk.Label(del_grid, text="limit（0=不限）").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Spinbox(del_grid, from_=0, to=500, textvariable=del_limit_var, width=8).grid(
        row=2, column=1, sticky="w", pady=4
    )
    ttk.Checkbutton(del_grid, text="dry-run（只预览）", variable=del_dry_var).grid(
        row=2, column=2, sticky="e", pady=4
    )

    ttk.Checkbutton(del_grid, text="--yes（跳过确认）", variable=del_yes_var).grid(
        row=3, column=2, sticky="e", pady=4
    )
    ttk.Label(del_grid, text="login-hold").grid(row=3, column=0, sticky="w", pady=4)
    ttk.Spinbox(del_grid, from_=0, to=3600, textvariable=del_login_hold_var, width=8).grid(
        row=3, column=1, sticky="w", pady=4
    )
    ttk.Label(del_grid, text="wait-timeout").grid(row=4, column=0, sticky="w", pady=4)
    ttk.Spinbox(del_grid, from_=30, to=3600, textvariable=del_wait_timeout_var, width=8).grid(
        row=4, column=1, sticky="w", pady=4
    )

    ttk.Label(del_grid, text="（draft-url 仅在 draft-location=url 时生效）").grid(
        row=4, column=2, sticky="e", pady=4
    )

    def _run_delete() -> None:
        params = {
            "draft_type": draft_type_var.get(),
            "draft_location": draft_loc_var.get(),
            "draft_url": draft_url_var.get(),
            "all_types": all_types_var.get(),
            "limit": del_limit_var.get(),
            "dry_run": del_dry_var.get(),
            "yes": del_yes_var.get(),
            "login_hold": del_login_hold_var.get(),
            "wait_timeout": del_wait_timeout_var.get(),
        }
        args = build_cli_args("delete-drafts", params=params)
        env = build_subprocess_env(_collect_env_overrides())
        runner.run(args, env)

    ttk.Button(tab_delete, text="运行 delete-drafts", command=_run_delete).pack(
        anchor="w", padx=12, pady=(0, 10)
    )

    root.mainloop()


if __name__ == "__main__":
    main()
