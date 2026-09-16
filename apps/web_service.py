"""Local workbench adapter. No browser or provider calls on import/read routes."""
from __future__ import annotations

import csv
import hashlib
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps import gui
from src.storage.files import _write_json_atomic, latest_execution, load_post, save_post
from src.storage.models import now_iso

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"aliyun": "阿里云", "volcengine": "火山引擎", "siliconflow": "硅基流动", "minimax": "MiniMax"}
ACTIVE = {"queued", "running", "waiting_user", "stopping"}
SAFE_SETTINGS = {"performance_mode", "platform"}
SECRET_FIELDS = {
    "DASHSCOPE_API_KEY", "VOLCENGINE_API_KEY", "SILICONFLOW_API_KEY", "MINIMAX_TOKEN_PLAN_API_KEY",
    "LLM_API_KEY", "NEWS_API_KEY", "GNEWS_API_KEY", "NEWSDATA_API_KEY", "THENEWSAPI_TOKEN",
    "ALPHAVANTAGE_API_KEY", "FINNHUB_API_KEY", "JUHE_NEWS_APPKEY", "JUHE_FINANCE_NEWS_APPKEY", "PEXELS_API_KEY",
}
CONFIG_FIELDS = {"ALIYUN_LLM_BASE_URL", "VOLCENGINE_LLM_BASE_URL", "SILICONFLOW_LLM_BASE_URL",
                 "MINIMAX_BASE_URL", "LLM_BASE_URL", "ALIYUN_IMAGE_SIZE", "VOLCENGINE_IMAGE_SIZE",
                 "SILICONFLOW_IMAGE_SIZE", "ALIYUN_IMAGE_NEGATIVE_PROMPT", "NEWS_CHINA_RATIO", "NEWS_CHINA_BONUS"}


def bounded_int(value: Any, minimum: int, maximum: int) -> int:
    number = int(value)
    if isinstance(value, bool) or str(number) != str(value) or not minimum <= number <= maximum:
        raise ValueError(f"请输入 {minimum} 至 {maximum} 的整数")
    return number


def deletion_scope(request: dict) -> dict:
    draft_type = request.get("draft_type", "image")
    if draft_type not in {"image", "video", "article", "all"}:
        raise ValueError("草稿类型无效")
    title = str(request.get("title_contains", "")).strip()
    if len(title) > 200 or any(ord(c) < 32 for c in title):
        raise ValueError("标题筛选条件无效")
    return {"draft_type": draft_type, "title_contains": title,
            "limit": bounded_int(request.get("limit", 10), 0, 10000)}


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def valid_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("草稿或任务编号无效")
    return value


def parse_time(value: str) -> float | None:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc).timestamp() if d.tzinfo is None else d.timestamp()
    except (ValueError, TypeError):
        return None


class Workbench:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.directory = self.root / "data/web_gui"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.jobs: dict[str, dict] = {}
        for path in (self.directory / "jobs").glob("*.json"):
            job = read_json(path, {})
            if job.get("id"):
                if job.get("status") in ACTIVE:
                    job.update(status="interrupted", ended_at=time.time(), message="服务曾中断。先核对平台草稿，不会自动重传。")
                    _write_json_atomic(path, job)
                self.jobs[job["id"]] = job

    def environment(self) -> dict[str, str]:
        env = gui.build_subprocess_env(gui.load_env_file(self.root / ".env.gui"))
        profile = gui.build_xhs_creator_profile_dir(project_root=self.root, env=env).resolve()
        if not profile.is_relative_to((self.root / "data/browser").resolve()):
            raise ValueError("浏览器 profile 必须位于本项目 data/browser 内，已阻止默认浏览器回退")
        env.update(XHS_CHROME_USER_DATA_DIR=str(profile), XHS_CHROME_PROFILE=env.get("XHS_CHROME_PROFILE") or "Default",
                   ALLOW_PAID_LLM_FALLBACK="0", MINIMAX_BILLING_MODE="subscription_only",
                   MINIMAX_ALLOW_PAID_CREDITS="0", MINIMAX_ALLOW_PAYGO="0", PYTHONUNBUFFERED="1")
        env.pop("XHS_CDP_URL", None)
        toutiao_profile = Path(env.get("TOUTIAO_CHROME_USER_DATA_DIR") or profile).resolve()
        if not toutiao_profile.is_relative_to((self.root / "data/browser").resolve()):
            raise ValueError("今日头条 profile 必须位于本项目 data/browser 内")
        return env

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items() if not re.search(r"api.?key|secret|authorization|cookie|password|raw_text", k, re.I)}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        if not isinstance(value, str):
            return value
        secrets = gui.load_env_file(self.root / ".env.gui")
        secrets.update({k: v for k, v in os.environ.items() if re.search(r"KEY|TOKEN|SECRET|PASSWORD", k)})
        for key, secret in secrets.items():
            if re.search(r"KEY|TOKEN|SECRET|PASSWORD", key) and len(secret) >= 6:
                value = value.replace(secret, "[已隐藏]")
        value = re.sub(r"(?i)(api[_-]?key|access[_-]?token|authorization)([=:\s]+)[^\s&,]+", r"\1\2[已隐藏]", value)
        return re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "[已隐藏]", value)

    def settings(self) -> dict:
        saved = read_json(self.directory / "settings.json", {})
        return {"performance_mode": saved.get("performance_mode", "balanced"), "platform": saved.get("platform", "xhs")}

    def save_settings(self, data: dict) -> dict:
        if set(data) - SAFE_SETTINGS or data.get("performance_mode") not in {"balanced", "speed"} or data.get("platform") not in {"xhs", "toutiao", "both"}:
            raise ValueError("设置不合法，密钥只能在本地 .env.gui 中填写")
        _write_json_atomic(self.directory / "settings.json", data)
        return data

    def models(self) -> dict:
        rows, snapshots = [], []
        for provider in PROVIDERS:
            paths = sorted((self.root / "data/quota").glob(f"{provider}_quota_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not paths:
                continue
            path = paths[0]
            payload = read_json(path, {})
            timestamp = path.stat().st_mtime
            snapshots.append({"provider": provider, "at": timestamp, "name": path.name, "errors": self.redact(payload.get("errors", []))})
            # Never silently revive an older quota table after an empty/failed sync.
            snapshot = {provider: {**payload, "provider": provider, "_snapshot_name": path.name}}
            records = {r.get("model"): r for r in payload.get("records", []) if isinstance(r, dict)}
            for row in gui.build_quota_dashboard_rows(snapshot):
                entry = asdict(row)
                raw = records.get(row.model, {})
                expiry = str(raw.get("expires_at") or "")
                expired = parse_time(expiry)
                cost = str(raw.get("cost_class") or "unknown")
                kind = gui.quota_dashboard_selection_target(row)
                reason = ""
                if row.status in {"removed", "deleted", "offline", "disabled", "not_found"}:
                    reason = "平台已下架或停用"
                elif payload.get("errors"):
                    reason = "本次同步有错误，请核对额度"
                elif expired is not None and expired <= time.time():
                    reason = "额度已到期，请同步"
                elif time.time() - timestamp > 24 * 3600:
                    reason = "快照超过24小时，请同步"
                elif cost not in {"free", "subscription_included", "free_model"}:
                    reason = "未验证免费或订阅计费，禁止自动扣费"
                elif row.remaining is None and cost != "free_model":
                    reason = "未取得剩余额度"
                elif row.remaining is not None and row.remaining <= 0:
                    reason = "剩余额度不足"
                elif not kind:
                    reason = "不是可选的语言或生图模型"
                entry.update(id=f"{provider}:{row.model}", kind=kind[0] if kind else row.kind, cost_class=cost,
                             expires_at=expiry, snapshot_at=timestamp, disabled_reason=reason, selectable=not reason)
                rows.append(entry)
        return {"rows": rows, "snapshots": snapshots}

    def sources(self) -> dict:
        snapshots = gui.load_latest_source_health_snapshots(source_dir=self.root / "data/source_health")
        return self.redact({"rows": [asdict(r) for r in gui.build_source_health_dashboard_rows(snapshots)]})

    def analysis(self) -> dict:
        path = self.root / "data/analytics/published_metrics_analysis.md"
        return {"text": path.read_text(encoding="utf-8") if path.exists() else "",
                "captured_at": path.stat().st_mtime if path.exists() else None}

    def configuration(self) -> dict:
        env = gui.load_env_file(self.root / ".env.gui")
        return {"secrets": {key: bool(env.get(key)) for key in sorted(SECRET_FIELDS)},
                "values": {key: env.get(key, "") for key in sorted(CONFIG_FIELDS)}}

    def save_configuration(self, data: dict) -> dict:
        with self.lock:
            self.assert_idle()
            if set(data) - (SECRET_FIELDS | CONFIG_FIELDS):
                raise ValueError("包含不允许修改的配置")
            for value in data.values():
                if not isinstance(value, str) or len(value) > 8192 or any(c in value for c in '\r\n\x00"'):
                    raise ValueError("配置值必须是单行文本，不能包含双引号")
            if (self.root / ".git").exists():
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env.gui"], cwd=self.root,
                                         capture_output=True, creationflags=flags)
                ignored = subprocess.run(["git", "check-ignore", "-q", ".env.gui"], cwd=self.root,
                                         capture_output=True, creationflags=flags)
                if tracked.returncode == 0 or ignored.returncode != 0:
                    raise ValueError(".env.gui 必须未被 Git 跟踪且已加入忽略规则，才能保存密钥")
            env = gui.load_env_file(self.root / ".env.gui")
            env.update({key: value.strip() for key, value in data.items() if key not in SECRET_FIELDS or value.strip()})
            gui.save_env_file(self.root / ".env.gui", env)
            return self.configuration()

    def posts(self, limit: int = 200) -> list[dict]:
        return [asdict(row) for row in gui.list_recent_posts(project_root=self.root, limit=limit)]

    def local_assets(self, pattern: str) -> str:
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("请输入工作区 assets 或 data/posts 内的相对图片路径")
        paths = [Path(p).resolve() for p in glob.glob(str(self.root / pattern)) if Path(p).is_file()]
        if not paths or any(not any(p.is_relative_to((self.root / folder).resolve()) for folder in ("assets", "data/posts"))
                            or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} for p in paths):
            raise ValueError("素材必须为工作区 assets 或 data/posts 内的图片，且至少匹配一张")
        return str(self.root / pattern)

    def post(self, post_id: str) -> dict:
        p = load_post(valid_id(post_id), base=self.root / "data")
        execution = latest_execution(p.id, base=self.root / "data")
        steps = [s.model_dump() for s in execution.steps] if execution else []
        verified = any(s["name"] == "readback_saved_draft" and s["status"] == "success" for s in steps)
        if list((self.directory / "edits" / p.id).glob("*.json")):
            verified = False
        return self.redact({"id": p.id, "title": p.title, "body": p.body, "status": p.status.value,
                            "updated_at": p.updated_at, "topics": p.topics, "platform": p.platform,
                            "assets": [{"url": f"/api/posts/{p.id}/images/{i}", "name": Path(a.path).name} for i, a in enumerate(p.assets)],
                            "readback": "verified" if verified else "unverified", "steps": steps})

    def image(self, post_id: str, index: int) -> Path:
        p = load_post(valid_id(post_id), base=self.root / "data")
        if index < 0 or index >= len(p.assets):
            raise ValueError("图片不存在")
        path = Path(p.assets[index].path)
        path = (path if path.is_absolute() else self.root / path).resolve()
        if not any(path.is_relative_to((self.root / folder).resolve()) for folder in ("data/posts", "assets")) or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("图片路径不在允许目录")
        return path

    def edit_post(self, post_id: str, data: dict) -> dict:
        with self.lock:
            self.assert_idle()
            p = load_post(valid_id(post_id), base=self.root / "data")
            if p.status.value in {"published", "publishing"}:
                raise ValueError("不能修改已发布或发布中的本地记录")
            if data.get("updated_at") != p.updated_at:
                raise ValueError("草稿已被其他操作更新，请重新打开后编辑")
            title, body = str(data.get("title", "")).strip(), str(data.get("body", "")).strip()
            if not title or not body or len(title) > 200 or len(body) > 100000:
                raise ValueError("标题和正文不能为空或超过长度限制")
            backup = self.directory / "edits" / p.id / f"{uuid.uuid4().hex}.json"
            _write_json_atomic(backup, p.model_dump(mode="json"))
            p.title, p.body, p.updated_at = title, body, now_iso()
            save_post(p, base=self.root / "data")
            return self.post(p.id)

    def metrics(self) -> dict:
        path = self.root / "data/analytics/published_metrics_latest.csv"
        if not path.exists():
            return {"rows": [], "captured_at": None, "complete": None}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        result = []
        for r in rows:
            raw = read_json_value(r.get("raw", ""))
            row = {k: r.get(k, "") for k in ("id", "title", "published_at", "captured_at", "url")}
            for key in ("views", "likes", "favorites", "comments", "shares"):
                value = r.get(key) or raw.get(key)
                try:
                    row[key] = int(str(value).replace(",", ""))
                except (ValueError, TypeError):
                    row[key] = None
            result.append(row)
        return {"rows": result, "captured_at": path.stat().st_mtime, "complete": None}

    def bootstrap(self) -> dict:
        env = gui.load_env_file(self.root / ".env.gui")
        return {"capabilities": {"titles": ["每日新闻", "每日我去", "每日AI讯息", "每日羊毛", "每日假新闻"], "news_windows": [1, 2, 3, 5],
                 "max_count": 20, "source_cap": 2, "platforms": ["xhs", "toutiao", "both"], "readback_platform": "xhs"},
                "settings": self.settings(), "models": self.models(), "jobs": self.list_jobs(),
                "accounts": [{"provider": p, "label": label, "configured": any(v for k, v in env.items() if k.startswith(p.upper()) and ("KEY" in k or "TOKEN" in k))} for p, label in PROVIDERS.items()],
                "profile": "data/browser/" + gui.build_xhs_creator_profile_dir(project_root=self.root, env=env).name,
                "login_status": "未验证"}

    def assert_idle(self) -> None:
        if self.process is not None or any(j["status"] in ACTIVE for j in self.jobs.values()):
            raise ValueError("已有任务运行中，请在任务中心等待完成或停止；浏览器任务不能并发")

    def plan(self, request: dict, job_id: str) -> tuple[list[str], dict]:
        kind = request.get("kind")
        env = self.environment()
        args = [sys.executable, "-u", "-m", "apps.cli"]
        if kind in {"auto", "material"}:
            title = "每日新闻" if kind == "material" else request.get("title", "每日新闻")
            if title not in {"每日新闻", "每日我去", "每日AI讯息", "每日羊毛", "每日假新闻"}:
                raise ValueError("内容类型无效")
            count = int(request.get("count", 1))
            if not 1 <= count <= 20:
                raise ValueError("数量必须为1至20")
            mode = request.get("performance_mode", "balanced")
            platform = request.get("platform", "xhs")
            if mode not in {"balanced", "speed"} or platform not in {"xhs", "toutiao", "both"}:
                raise ValueError("模式或目标平台无效")
            catalog = {m["id"]: m for m in self.models()["rows"]}
            asset_pattern = self.local_assets(str(request.get("assets_glob", ""))) if request.get("use_local_images") else ""
            selections = []
            for model_kind in ("llm", "image"):
                if model_kind == "image" and (asset_pattern or title in {"每日AI讯息", "每日羊毛"}):
                    selections.append({"provider": "local" if asset_pattern else "minimax", "model": ""})
                    continue
                model = catalog.get(request.get(f"{model_kind}_id", ""))
                if not model or not model["selectable"] or model["kind"] != model_kind:
                    raise ValueError(f"请选择有有效免费/订阅额度的{model_kind}模型；不会自动刷新或切换付费模型")
                selections.append(model)
            env = gui.build_provider_env_overrides(env, llm_provider=selections[0]["provider"], llm_model=selections[0]["model"],
                                                  image_provider=selections[1]["provider"], image_model=selections[1]["model"])
            env = gui.ensure_daily_news_candidate_pool_env(env, title=title, count=count)
            env["ALLOW_PAID_LLM_FALLBACK"] = "0"
            env["SILICONFLOW_FREE_ONLY"] = "1"
            # Prevent a previous material run or shell override silently replacing news discovery.
            env.pop("NEWS_MATERIALS_FILE", None)
            params = {"title": title, "count": count, "keywords": gui.combine_prompt_entries(request.get("prompts", [])),
                      "performance_mode": mode, "platform": platform, "image_source": selections[1]["provider"],
                      "headless": True, "login_hold": 0, "wait_timeout": 600,
                      "lookback_days": request.get("lookback_days", "auto"), "lookback_mode": "auto" if request.get("lookback_days", "auto") == "auto" else "fixed",
                      "evaluation_viewpoint": str(request.get("evaluation_viewpoint") or "无视角评价")}
            if asset_pattern:
                params["assets_glob"] = asset_pattern
            if kind == "material":
                from src.news.manual_material_input import prepare_material_text_snapshot
                material_time = str(request.get("material_time", "")).replace("T", " ")
                if not material_time:
                    raise ValueError("请填写材料时间，不限制材料距今天的天数")
                material_mode = request.get("material_mode", "single")
                snapshot = prepare_material_text_snapshot(str(request.get("material_text", "")), mode=material_mode, requested_count=count,
                    default_material_time=material_time, title_override=str(request.get("material_title", "")),
                    source_override=str(request.get("material_source", "")),
                    url_override=str(request.get("material_url", "")),
                    output_dir=self.directory / "materials" / job_id)
                params.update(material_time=material_time, count=1 if material_mode == "single" else count)
                params["single_news_material_file" if material_mode == "single" else "news_materials_file"] = str(snapshot.path)
            args = gui.build_cli_args("auto", params=params) + ["--no-refresh-quotas"]
        elif kind == "sync-quotas":
            provider = request.get("provider", "all")
            if provider not in {*PROVIDERS, "all"}:
                raise ValueError("额度平台无效")
            args = gui.build_cli_args("sync-quotas" if provider == "all" else f"{provider}-quota", params={
                "all_free": not bool(request.get("models")), "models": request.get("models", ""),
                "headless": not request.get("visible"), "login_hold": 600 if request.get("visible") else 0,
                "wait_timeout": 120, "save_raw": True, "visible_only": bool(request.get("visible_only")),
            })
        elif kind == "update-metrics":
            args = gui.build_cli_args(kind, params={"limit": 0, "headless": True, "login_hold": 0})
        elif kind in {"scan-drafts", "login", "open-xhs", "open-toutiao"}:
            args = [sys.executable, "-u", "-m", "apps.web_worker", kind, "--root", str(self.root)]
        elif kind == "publish-batch":
            post_ids = request.get("post_ids")
            if not isinstance(post_ids, list) or not post_ids or len(post_ids) > 100:
                raise ValueError("请选择1至100条平台关联草稿")
            if request.get("confirmation") != "确认发布":
                raise ValueError("发布前必须输入确认发布")
            args += ["publish-drafts", "--yes", "--headless", "--login-hold", "0"]
            for post_id in dict.fromkeys(post_ids):
                post = load_post(valid_id(post_id), base=self.root / "data")
                if post.status.value in {"published", "publishing"}:
                    raise ValueError("选择中包含已发布的草稿，请刷新")
                args += ["--post-id", post_id]
        elif kind in {"run", "update-draft", "verify-draft", "publish-drafts"}:
            post_id = valid_id(str(request.get("post_id", "")))
            p = load_post(post_id, base=self.root / "data")
            if kind == "run" and p.uploaded:
                raise ValueError("该草稿已有上传记录，请使用更新草稿，避免重复上传")
            if kind == "publish-drafts" and request.get("confirmation") != "确认发布":
                raise ValueError("发布到公众前必须输入确认发布")
            if kind == "publish-drafts":
                args += [kind, "--post-id", post_id, "--yes", "--headless", "--login-hold", "0"]
            elif kind in {"verify-draft", "update-draft"}:
                args += ["update-draft", post_id, "--headless", "--login-hold", "0"]
                if kind == "verify-draft":
                    args.append("--dry-run")
            else:
                platform = request.get("platform", "xhs")
                if platform not in {"xhs", "toutiao", "both"}:
                    raise ValueError("目标平台无效")
                args = gui.build_cli_args("run", params={"post_id": post_id, "platform": platform, "headless": True, "login_hold": 0, "wait_timeout": 600})
        elif kind in {"validate", "approve", "retry"}:
            post_id = valid_id(str(request.get("post_id", "")))
            post = load_post(post_id, base=self.root / "data")
            if kind != "validate" and post.status.value in {"published", "publishing"}:
                raise ValueError("不能更改已发布或发布中的草稿状态")
            args += [kind, post_id]
            if kind == "retry":
                execution = latest_execution(post_id, base=self.root / "data")
                if not execution or execution.result != "failed":
                    raise ValueError("仅重试上次失败的上传；已保存草稿请使用原位更新")
                platform = request.get("platform", "xhs")
                if platform not in {"xhs", "toutiao", "both"}:
                    raise ValueError("目标平台无效")
                args += ["--platform", platform, "--headless", "--login-hold", "0"]
        elif kind == "analyze-metrics":
            args += [kind, "--top-n", str(bounded_int(request.get("top_n", 6), 1, 20)), "--save"]
        elif kind == "check-sources":
            args = gui.build_cli_args(kind, params={"collection": request.get("collection", "all"),
                "keywords": str(request.get("keywords", "科技")),
                "max_age_days": bounded_int(request.get("max_age_days", 3), 1, 14)})
        elif kind in {"delete-preview", "delete-drafts"}:
            scope = deletion_scope(request)
            if kind == "delete-drafts":
                preview = self.jobs.get(str(request.get("preview_id", "")), {})
                if (preview.get("kind") != "delete-preview" or preview.get("status") != "completed"
                    or preview.get("deletion_scope") != scope
                    or time.time() - (preview.get("ended_at") or 0) > 600):
                    raise ValueError("请先按相同条件完成删除预览（十分钟内有效）")
                if request.get("confirmation") != "确认删除":
                    raise ValueError("请输入确认删除")
            args += ["delete-drafts", "--draft-type", "image" if scope["draft_type"] == "all" else scope["draft_type"],
                     "--limit", str(scope["limit"]), "--headless", "--login-hold", "0", "--wait-timeout", "600"]
            if scope["draft_type"] == "all":
                args.append("--all")
            if scope["title_contains"]:
                args += ["--title-contains", scope["title_contains"]]
            args.append("--dry-run" if kind == "delete-preview" else "--yes")
        else:
            raise ValueError("不支持的任务类型")
        return args, env

    def submit(self, request: dict, key: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9-]{16,80}", key):
            raise ValueError("缺少有效的幂等标识")
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            for j in self.jobs.values():
                if j.get("key") == key:
                    if j.get("digest") != digest:
                        raise ValueError("同一幂等标识不能用于不同任务")
                    return self.redact(j)
            self.assert_idle()
            job_id = uuid.uuid4().hex
            args, env = self.plan(request, job_id)
            job = {"id": job_id, "key": key, "digest": digest, "kind": request["kind"], "title": request.get("title") or request["kind"],
                   "status": "queued", "created_at": time.time(), "started_at": None, "ended_at": None,
                   "message": "等待启动", "stage": "准备", "events": [], "post_ids": [], "exit_code": None}
            if request["kind"] in {"delete-preview", "delete-drafts"}:
                job["deletion_scope"] = deletion_scope(request)
            self.jobs[job_id] = job
            self.persist(job)
            threading.Thread(target=self._run, args=(job, args, env), daemon=True).start()
            return self.redact(job.copy())

    def persist(self, job: dict) -> None:
        _write_json_atomic(self.directory / "jobs" / f"{job['id']}.json", job)

    def event(self, job: dict, message: str) -> None:
        with self.lock:
            message = self.redact(message.strip())
            if not message:
                return
            job["message"] = message
            match = re.search(r"stage=([^|]+)", message)
            if match:
                job["stage"] = match.group(1).strip()
            for post_id in re.findall(r"(?:post_id=|post-id[:=]\s*|post:\s*)([a-f0-9]{32})", message):
                if post_id not in job["post_ids"]:
                    job["post_ids"].append(post_id)
            event_id = job.get("last_event_id", 0) + 1
            job["last_event_id"] = event_id
            job["events"].append({"id": event_id, "at": time.time(), "message": message})
            job["events"] = job["events"][-600:]
            if "error:" in message.lower() or "| failed |" in message or "| warning |" in message:
                job["has_warnings"] = True
            self.persist(job)
            with (self.directory / f"{job['id']}.log").open("a", encoding="utf-8") as log:
                log.write(message + "\n")

    def _run(self, job: dict, args: list[str], env: dict) -> None:
        try:
            with self.lock:
                job.update(status="running", started_at=time.time())
                self.persist(job)
                self.process = subprocess.Popen(args, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                process = self.process
            assert process.stdout is not None
            for line in process.stdout:
                self.event(job, line)
            code = process.wait()
            with self.lock:
                cancelled = job["status"] == "stopping"
                job.update(exit_code=code, ended_at=time.time(), status="cancelled" if cancelled else "failed" if code else "partial_success" if job.get("has_warnings") else "completed")
                if code and not cancelled:
                    job["message"] = f"任务退出码 {code}。请查看日志末尾错误，修正后重新提交；已保存草稿不会自动重传。"
                self.persist(job)
        except Exception as exc:
            self.event(job, f"启动或执行失败：{exc}")
            job.update(status="failed", ended_at=time.time())
            self.persist(job)
        finally:
            with self.lock:
                self.process = None

    def stop(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs[valid_id(job_id)]
            if job["status"] in ACTIVE and self.process:
                job["status"] = "stopping"
                self.persist(job)
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self.process.terminate()
            return self.redact(job)

    def list_jobs(self) -> list[dict]:
        with self.lock:
            return [self.redact({k: v for k, v in j.items() if k not in {"events", "key", "digest"}}) for j in sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)[:100]]

    def job_detail(self, job_id: str) -> dict:
        with self.lock:
            job = self.redact(json.loads(json.dumps(self.jobs[valid_id(job_id)])))
        rows = []
        for post_id in job.get("post_ids", []):
            try:
                p = self.post(post_id)
                rows.append({"id": p["id"], "title": p["title"], "text": "完成" if p["body"].strip() else "未完成",
                             "images": len(p["assets"]), "status": p["status"], "readback": p["readback"]})
            except (OSError, ValueError):
                continue
        job["post_rows"] = rows
        return job


def read_json_value(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}
