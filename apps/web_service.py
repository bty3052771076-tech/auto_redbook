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
from urllib.parse import parse_qs, urlsplit

from apps import gui
from src.agent.conversation_store import PostgresConversationStore
from src.config import DEFAULT_MINIMAX_IMAGE_MODEL, DEFAULT_MINIMAX_LLM_MODEL
from src.storage.files import _write_json_atomic, latest_execution, load_post, save_post
from src.storage.models import now_iso
from src.global_map.models import GlobalMapRequest
from src.global_map.service import preview_global_map_from_service

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"aliyun": "阿里云", "volcengine": "火山引擎", "siliconflow": "硅基流动", "minimax": "MiniMax", "opencodex": "OpenCodex / ChatGPT订阅"}
ROLE_NAMES = {"agent": "智能体主控", "writer": "写稿模型", "image": "生图模型"}
CUSTOM_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,50}$")
CUSTOM_MODEL_ID = re.compile(r"^[^\s]{1,200}$")
CUSTOM_PROTOCOLS = {"openai_chat", "openai_image"}
CUSTOM_BILLING = {"free", "subscription", "payg", "unknown"}
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
AGENT_JOB_TITLES = {
    "daily_news": ("每日新闻", "近期国内外热点新闻，优先事实完整且影响力较高的事件"),
    "daily_ai_digest": ("每日AI讯息", "模型发布、AI厂商产品更新和具体可核验的AI动态"),
    "daily_wool": ("每日羊毛", "今日仍有效的AI福利、免费额度、活动和重置信息"),
    "daily_wow": ("每日我去", "真实、具体、近期且反差强烈的猎奇事件；不要恶心或虚构"),
    "daily_global_map": ("今日全球事件关注图", "基于当日公开信源、已核验位置和可追溯证据生成事件关注图"),
}


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


def valid_conversation_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", str(value or "")):
        raise ValueError("会话编号无效")
    return str(value)


def parse_time(value: str) -> float | None:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc).timestamp() if d.tzinfo is None else d.timestamp()
    except (ValueError, TypeError):
        return None


class Workbench:
    def wool_library(self):
        from src.wool.reference_library import WoolReferenceLibrary, wool_asset_root
        return WoolReferenceLibrary(wool_asset_root(self.root, gui.load_env_file(self.root / ".env.gui")))

    def wool_library_action(self, action: str, request: dict):
        library = self.wool_library()
        if action == "review":
            return library.review(
                str(request.get("id") or ""), decision=str(request.get("decision") or ""),
                adult_confirmed=request.get("adult_confirmed") is True,
                rights_confirmed=request.get("rights_confirmed") is True,
                non_explicit_confirmed=request.get("non_explicit_confirmed") is True,
                note=str(request.get("note") or ""),
            )
        if action == "select":
            return library.set_selection(str(request.get("id") or ""))
        if action == "fetch":
            from src.wool.danbooru import fetch_candidates
            return fetch_candidates(library.root, count=bounded_int(request.get("count", 10), 1, 30),
                                    style=str(request.get("style") or "mixed"))
        raise ValueError("图库操作无效")

    def __init__(self, root: Path = ROOT, *, conversation_store=None):
        self.root = root.resolve()
        self.directory = self.root / "data/web_gui"
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "conversations").mkdir(parents=True, exist_ok=True)
        self.conversation_store = conversation_store or PostgresConversationStore()
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

    def _agent_conversation_path(self, conversation_id: str) -> Path:
        return self.directory / "conversations" / f"{valid_conversation_id(conversation_id)}.json"

    def _read_agent_conversation(self, conversation_id: str) -> dict:
        try:
            value = self.conversation_store.get(conversation_id)
        except KeyError:
            path = self._agent_conversation_path(conversation_id)
            legacy = read_json(path, None)
            if not isinstance(legacy, dict) or legacy.get("id") != conversation_id:
                raise ValueError("会话不存在")
            value = self.conversation_store.import_legacy(legacy)
        value.setdefault("messages", [])
        value.setdefault("plans", [])
        value.setdefault("runs", [])
        return value

    def _write_agent_conversation(self, conversation: dict) -> dict:
        conversation["updated_at"] = time.time()
        saved = self.conversation_store.save(conversation)
        saved.pop("_revision", None)
        saved.pop("_last_message_seq", None)
        return self.redact(saved)

    def list_agent_conversations(self) -> list[dict]:
        for path in (self.directory / "conversations").glob("*.json"):
            value = read_json(path, {})
            if isinstance(value, dict) and re.fullmatch(r"[a-f0-9]{32}", str(value.get("id") or "")):
                self.conversation_store.import_legacy(value)
        rows = self.conversation_store.list(limit=100)
        for row in rows:
            row.pop("_revision", None)
        return [self.redact(row) for row in rows]

    def create_agent_conversation(self, title: str = "新对话") -> dict:
        conversation_id = uuid.uuid4().hex
        now = time.time()
        conversation = {
            "id": conversation_id,
            "title": str(title or "新对话").strip()[:120] or "新对话",
            "created_at": now,
            "updated_at": now,
            "status": "idle",
            "messages": [],
            "plans": [],
            "runs": [],
        }
        return self._write_agent_conversation(conversation)

    @staticmethod
    def _agent_count(text: str) -> int:
        patterns = (
            r"(?<!\d)(\d{1,3})\s*(?:条|篇)?\s*(?:(?:今日|今天)(?:的)?\s*)?每日新闻",
            r"每日新闻\s*(?:生成|做|写)?\s*(\d{1,3})\s*(?:条|篇)?",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                count = int(match.group(1))
                if not 1 <= count <= 20:
                    raise ValueError("每日新闻数量必须是1至20")
                return count
        return 1

    @staticmethod
    def _agent_job_enabled(text: str, phrases: tuple[str, ...]) -> bool:
        for phrase in phrases:
            for match in re.finditer(re.escape(phrase), text):
                clause_prefix = re.split(r"[，,。！？；;\n]", text[:match.start()])[-1]
                if re.search(
                    r"(?:不要|不需要|无需|不用|不必|不生成|不做|不写|禁止|别|取消|跳过|去掉)"
                    r".{0,12}$",
                    clause_prefix,
                ):
                    continue
                return True
        return False

    def _parse_agent_message(self, text: str) -> dict:
        cleaned = str(text or "").strip()
        if not cleaned:
            raise ValueError("请输入要交给智能体的任务")
        if len(cleaned) > 10000:
            raise ValueError("对话内容不能超过10000个字符")
        generation_requested = self._agent_job_enabled(
            cleaned,
            ("每日新闻", "每日AI讯息", "每日AI资讯", "每日羊毛", "AI羊毛", "AI鸡蛋", "每日AI鸡蛋", "AI福利", "每日AI福利", "每日我去",
             "今日全球事件关注图", "全球事件热力图", "全球新闻热力图"),
        )
        draft_scope = bool(re.search(r"(?:创作者中心|草稿箱|平台草稿|已有草稿)", cleaned))
        explicit_publish = bool(re.search(r"(?:发布|公开)", cleaned)) and not bool(
            re.search(r"(?:不要|不需要|无需|禁止|先审查)[^，,。！？\n]{0,10}(?:发布|公开)", cleaned)
        )
        draft_action = bool(re.search(r"(?:检查|查看|筛选|管理|审查)", cleaned)) or explicit_publish
        if draft_scope and draft_action and not generation_requested:
            mode = "publish" if explicit_publish else "review"
            count_match = re.search(r"(?:最多|不超过|限|选择)\s*(\d{1,3})\s*(?:条|篇)?", cleaned)
            max_items = int(count_match.group(1)) if count_match else 0
            if max_items > 100:
                raise ValueError("平台草稿数量上限为100")
            title_match = re.search(r"标题(?:包含|含)\s*[“\"]?([^”\"，。\n]+)", cleaned)
            title_contains = title_match.group(1).strip() if title_match else ""
            bindings = self.providers()["bindings"]
            action_text = "公开发布" if mode == "publish" else "只读审查"
            return {
                "executable": True,
                "plan_kind": "draft_management",
                "jobs": [],
                "management": {
                    "mode": mode,
                    "draft_type": "image",
                    "max_items": max_items,
                    "title_contains": title_contains,
                    "max_age_days": 0,
                },
                "platform": "xhs",
                "delivery": "manage_drafts",
                "model_roles": bindings,
                "performance_mode": self.settings()["performance_mode"],
                "budget_minutes": 30.0,
                "assistant_summary": f"已识别：读取小红书创作者中心现有图文草稿，执行{action_text}"
                + (f"，最多{max_items}条" if max_items else "，不限制数量")
                + "；不会生成新稿。",
            }
        jobs: list[dict] = []
        if self._agent_job_enabled(cleaned, ("每日新闻",)):
            jobs.append({
                "kind": "daily_news",
                "title": "每日新闻",
                "count": self._agent_count(cleaned),
                "prompt": "国际冲突 争议事件 全球热点 财经产业 科技产业 芯片 AI 社会民生 体育文化 中国国内",
                "evaluation_viewpoint": "无视角评价",
                "lookback_days": "auto",
            })
        if self._agent_job_enabled(cleaned, ("每日AI讯息", "每日AI资讯")):
            jobs.append({
                "kind": "daily_ai_digest",
                "title": "每日AI讯息",
                "count": 1,
                "prompt": "模型发布 AI厂商产品更新 具体且可核验的AI动态",
                "evaluation_viewpoint": "无视角评价",
                "lookback_days": "auto",
            })
        if self._agent_job_enabled(cleaned, ("每日羊毛", "AI羊毛", "AI鸡蛋", "每日AI鸡蛋", "AI福利", "每日AI福利")):
            jobs.append({
                "kind": "daily_wool",
                "title": "每日羊毛",
                "count": 1,
                "prompt": "今日仍有效的AI福利、免费额度、活动和重置信息",
                "evaluation_viewpoint": "无视角评价",
                "lookback_days": "auto",
            })
        if self._agent_job_enabled(cleaned, ("每日我去",)):
            jobs.append({
                "kind": "daily_wow",
                "title": "每日我去",
                "count": 1,
                "prompt": "真实、具体、近期且反差强烈的猎奇事件；不要恶心或虚构",
                "evaluation_viewpoint": "无视角评价",
                "lookback_days": "auto",
            })
        if self._agent_job_enabled(cleaned, ("今日全球事件关注图", "全球事件热力图", "全球新闻热力图")):
            jobs.append({
                "kind": "daily_global_map",
                "title": "今日全球事件关注图",
                "count": 1,
                "prompt": "仅收录当日有具体进展、来源可追溯且位置可核验的全球事件；不足时保存本地报告，不虚构全球覆盖",
                "evaluation_viewpoint": "无视角评价",
                "lookback_days": "auto",
            })
        if "今日头条" in cleaned and "小红书" in cleaned:
            platform = "both"
        elif "今日头条" in cleaned or "头条" in cleaned:
            platform = "toutiao"
        else:
            platform = "xhs"
        wants_platform_draft = bool(re.search(
            r"(?:保存|上传|存)(?:到|至|进)?[^，,。！？\n]{0,18}(?:草稿箱|创作者中心|小红书草稿|平台草稿)",
            cleaned,
        ))
        generate_only = not wants_platform_draft and bool(
            re.search(r"(?:只|仅)(?:生成|做|写)|(?:不要|不需要|禁止)(?:上传|保存)", cleaned)
        )
        delivery = "generate_only" if generate_only else "save_draft"
        bindings = self.providers()["bindings"]
        return {
            "executable": bool(jobs),
            "jobs": jobs,
            "platform": platform,
            "delivery": delivery,
            "model_roles": bindings,
            "performance_mode": self.settings()["performance_mode"],
            "budget_minutes": 30.0,
            "assistant_summary": (
                "已识别："
                + "、".join(f"{job['title']} {job['count']}条" for job in jobs)
                + f"；目标平台：{'小红书+今日头条' if platform == 'both' else '小红书' if platform == 'xhs' else '今日头条'}；"
                + ("只生成本地稿，不上传平台。" if delivery == "generate_only" else "完成后保存到草稿箱。")
            ) if jobs else "请明确要生成的栏目，例如“生成1篇每日AI讯息”或“生成3条每日新闻并保存到小红书草稿”。",
        }

    def append_agent_message(self, conversation_id: str, text: str) -> dict:
        conversation = self._read_agent_conversation(valid_conversation_id(conversation_id))
        plan_data = self._parse_agent_message(text)
        now = time.time()
        message_id = uuid.uuid4().hex
        conversation["messages"].append({"id": message_id, "role": "user", "content": str(text).strip(), "created_at": now})
        plan_id = uuid.uuid4().hex
        plan = {"id": plan_id, "version": len(conversation["plans"]) + 1, "created_at": now, "status": "ready" if plan_data["executable"] else "needs_input", **plan_data}
        conversation["plans"].append(plan)
        conversation["messages"].append({
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": plan_data["assistant_summary"],
            "created_at": now,
            "plan_id": plan_id,
        })
        if len(conversation["messages"]) == 2:
            conversation["title"] = str(text).strip().replace("\n", " ")[:60]
        conversation["status"] = "planned" if plan_data["executable"] else "needs_input"
        self._write_agent_conversation(conversation)
        return {"message": self.redact(conversation["messages"][-2]), "assistant": self.redact(conversation["messages"][-1]), "plan": self.redact(plan)}

    def get_agent_conversation(self, conversation_id: str) -> dict:
        conversation = self._read_agent_conversation(valid_conversation_id(conversation_id))
        conversation.pop("_revision", None)
        conversation.pop("_last_message_seq", None)
        return self.redact(conversation)

    def agent_context_status(self, conversation_id: str) -> dict:
        conversation_id = valid_conversation_id(conversation_id)
        self._read_agent_conversation(conversation_id)
        if not hasattr(self.conversation_store, "context_messages"):
            return {"status": "unavailable", "reason": "PostgreSQL conversation store is required"}
        from src.agent.compaction import compacted_context, estimate_tokens
        context = compacted_context(self.conversation_store, conversation_id)
        return {
            "status": "ready",
            "conversation_id": conversation_id,
            "snapshot_version": int((context.get("snapshot") or {}).get("version") or 0),
            "through_seq": int((context.get("snapshot") or {}).get("through_seq") or 0),
            "raw_message_count": context["raw_message_count"],
            "active_context_tokens_estimate": estimate_tokens(context),
            "context": self.redact(context),
        }

    def _agent_memory_for_execution(self, conversation_id: str) -> dict:
        status = self.agent_context_status(conversation_id)
        snapshot = ((status.get("context") or {}).get("snapshot") or {})
        if not snapshot:
            return {}
        summary = str(self.redact(snapshot.get("summary") or "")).strip()[:6000]
        constraints = snapshot.get("constraints") or []
        if not isinstance(constraints, list):
            constraints = []
        return {
            "snapshot_version": int(snapshot.get("version") or 0),
            "through_seq": int(snapshot.get("through_seq") or 0),
            "summary": summary,
            "constraints": [str(self.redact(item)).strip()[:500] for item in constraints[:30] if str(item).strip()],
        }

    def compact_agent_conversation(self, conversation_id: str) -> dict:
        conversation_id = valid_conversation_id(conversation_id)
        self._read_agent_conversation(conversation_id)
        if not hasattr(self.conversation_store, "save_snapshot"):
            raise RuntimeError("CONVERSATION_COMPACTION_REQUIRES_POSTGRES")
        from src.agent.compaction import compact_conversation, minimax_summary
        result = compact_conversation(
            self.conversation_store,
            conversation_id,
            summarize=minimax_summary,
            task_state={"conversation_status": self.conversation_store.get(conversation_id).get("status", "idle")},
        )
        return self.redact(result)

    def agent_capabilities(self) -> dict:
        from src.agent.mcp_manager import MCPManager
        from src.agent.skills import SkillCatalog

        skill_catalog = SkillCatalog(self.root)
        try:
            skills = skill_catalog.list()
            skills_error = ""
        except Exception as exc:
            skills, skills_error = [], str(exc)
        try:
            mcp_tools = MCPManager(self.root).list_tools()
            mcp_status = "ready"
            mcp_error = ""
        except Exception as exc:
            mcp_tools, mcp_status, mcp_error = [], "blocked", str(exc)
        database = self.conversation_store.knowledge_store.status() if hasattr(self.conversation_store, "knowledge_store") else {"status": "test_adapter"}
        return self.redact({
            "database": database,
            "mcp": {"status": mcp_status, "tools": mcp_tools, "error": mcp_error},
            "skills": {"status": "ready" if not skills_error else "blocked", "items": skills, "error": skills_error},
            "compaction": {"available": hasattr(self.conversation_store, "save_snapshot"), "default_provider": "minimax_subscription_only"},
        })

    def execute_agent_plan(
        self,
        conversation_id: str,
        plan_id: str,
        version: Any,
        key: str,
        *,
        skill_mode: str = "off",
        skill_names: list[str] | None = None,
    ) -> dict:
        conversation = self._read_agent_conversation(valid_conversation_id(conversation_id))
        plan = next((item for item in conversation.get("plans", []) if item.get("id") == plan_id), None)
        if not plan:
            raise ValueError("智能体计划不存在")
        try:
            requested_version = int(version)
        except (TypeError, ValueError):
            raise ValueError("智能体计划版本无效")
        if requested_version != int(plan.get("version", 0)):
            raise ValueError("智能体计划已更新，请重新执行当前版本")
        if plan.get("plan_kind") == "draft_management":
            existing_run_id = str(plan.get("job_id") or plan.get("resume_job_id") or "").strip()
            if existing_run_id:
                existing = self.jobs.get(existing_run_id) or read_json(self.directory / "jobs" / f"{existing_run_id}.json", {})
                if existing:
                    return self.redact(existing)
            management = dict(plan.get("management") or {})
            management_mode = str(management.get("mode") or "review").strip().lower()
            request = {
                "kind": "manage-drafts",
                "title": "智能体：管理小红书平台草稿",
                "mode": management_mode,
                "draft_type": str(management.get("draft_type") or "image"),
                "max_items": int(management.get("max_items") or 0),
                "max_age_days": int(management.get("max_age_days") or 0),
                "title_contains": str(management.get("title_contains") or ""),
                "yes": management_mode == "publish",
            }
            job = self.submit(request, key)
            for item in conversation["plans"]:
                if item.get("id") == plan_id:
                    item["status"] = "running"
                    item["job_id"] = job.get("id", "")
            if job.get("id") and job["id"] not in conversation["runs"]:
                conversation["runs"].append(job["id"])
            conversation["status"] = "running"
            self._write_agent_conversation(conversation)
            return self.redact(job)
        if not plan.get("executable") or not plan.get("jobs"):
            raise ValueError("当前对话没有可执行的智能体任务")
        skill_mode = str(skill_mode or "off").strip().lower()
        if skill_mode not in {"off", "auto", "manual"}:
            raise ValueError("skill_mode must be off, auto, or manual")
        requested_skill_names = [str(name).strip() for name in (skill_names or []) if str(name).strip()]
        if len(requested_skill_names) > 3:
            raise ValueError("最多手动选择 3 个 Skill")
        if skill_mode == "manual" and not requested_skill_names:
            raise ValueError("manual 模式至少选择一个 Skill")
        from src.agent.skills import SkillCatalog

        skill_query = " ".join(f"{job.get('kind', '')} {job.get('title', '')} {job.get('prompt', '')}" for job in plan["jobs"])
        selected_skills = SkillCatalog(self.root).select(
            skill_query,
            mode=skill_mode,
            manual_names=tuple(requested_skill_names),
        )
        existing_run_id = str(plan.get("job_id") or plan.get("resume_job_id") or "").strip()
        if existing_run_id:
            existing = self.jobs.get(existing_run_id) or read_json(self.directory / "jobs" / f"{existing_run_id}.json", {})
            if existing:
                # The plan itself is the idempotency boundary. A page refresh
                # or a second click must not create another platform task.
                return self.redact(existing)
        plans_dir = self.directory / "conversations" / conversation_id / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{plan_id}.json"
        _write_json_atomic(plan_path, {
            "jobs": plan["jobs"],
            "delivery": plan["delivery"],
            "conversation_context": self._agent_memory_for_execution(conversation_id),
            "skill_mode": skill_mode,
            "skill_names": [str(item.get("name") or "") for item in selected_skills],
            "selected_skills": [
                {
                    "name": str(item.get("name") or "")[:80],
                    "version_hash": str(item.get("version_hash") or "")[:64],
                    "body": str(self.redact(item.get("body") or ""))[:12000],
                }
                for item in selected_skills[:3]
            ],
        })
        bindings = plan.get("model_roles") or self.providers()["bindings"]
        news_job = next((item for item in plan["jobs"] if item["kind"] == "daily_news"), None)
        request = {
            "kind": "agent",
            "title": "智能体：" + str(conversation.get("title") or "对话任务")[:70],
            "count": int(news_job["count"]) if news_job else 1,
            "prompts": [news_job["prompt"]] if news_job else ["模型发布 AI厂商产品更新 具体且可核验的AI动态"],
            "evaluation_viewpoint": "无视角评价",
            "lookback_days": "auto",
            "assets_glob": "assets/empty/*",
            "platform": plan["platform"],
            "performance_mode": plan["performance_mode"],
            "budget_minutes": plan["budget_minutes"],
            "agent_jobs_file": str(plan_path),
            "agent_id": bindings.get("agent", ""),
            "llm_id": bindings.get("writer", ""),
            "image_id": bindings.get("image", ""),
            "delivery": plan["delivery"],
        }
        job = self.submit(request, key)
        for item in conversation["plans"]:
            if item.get("id") == plan_id:
                item["status"] = "running"
                item["job_id"] = job.get("id", "")
        if job.get("id") and job["id"] not in conversation["runs"]:
            conversation["runs"].append(job["id"])
        conversation["status"] = "running"
        self._write_agent_conversation(conversation)
        return self.redact(job)

    def resume_agent_run(self, conversation_id: str, run_id: str, key: str) -> dict:
        """Resume only the unfinished portion of a persisted agent run."""
        conversation = self._read_agent_conversation(valid_conversation_id(conversation_id))
        run_id = valid_id(run_id)
        if run_id not in conversation.get("runs", []):
            raise ValueError("该智能体运行不属于当前会话")
        previous = self.jobs.get(run_id) or read_json(self.directory / "jobs" / f"{run_id}.json", {})
        if not previous or previous.get("kind") != "agent":
            raise ValueError("智能体运行记录不存在")
        if previous.get("status") in ACTIVE:
            raise ValueError("智能体任务仍在运行中，不能重复恢复")
        checkpoint = (self.root / "data" / "runs" / "agent" / run_id / "checkpoint.json").resolve()
        agent_root = (self.root / "data" / "runs" / "agent").resolve()
        if not checkpoint.is_relative_to(agent_root) or not checkpoint.is_file():
            raise ValueError("找不到该运行的智能体检查点")
        snapshot = read_json(checkpoint, {})
        if snapshot.get("status") == "completed":
            raise ValueError("该智能体运行已经完成，无需恢复")
        plan = next((item for item in conversation.get("plans", []) if item.get("job_id") == run_id), None)
        if not plan or not plan.get("jobs"):
            raise ValueError("找不到该运行对应的任务计划")
        bindings = plan.get("model_roles") or self.providers()["bindings"]
        news_job = next((item for item in plan["jobs"] if item["kind"] == "daily_news"), None)
        request = {
            "kind": "agent",
            "title": "智能体：" + str(conversation.get("title") or "对话任务")[:70],
            "count": int(news_job["count"]) if news_job else 1,
            "prompts": [news_job["prompt"]] if news_job else ["模型发布 AI厂商产品更新 具体且可核验的AI动态"],
            "evaluation_viewpoint": "无视角评价",
            "lookback_days": "auto",
            "assets_glob": "assets/empty/*",
            "platform": plan["platform"],
            "performance_mode": plan["performance_mode"],
            "budget_minutes": plan["budget_minutes"],
            "agent_jobs_file": str(self.directory / "conversations" / conversation_id / "plans" / f"{plan['id']}.json"),
            "agent_id": bindings.get("agent", ""),
            "llm_id": bindings.get("writer", ""),
            "image_id": bindings.get("image", ""),
            "delivery": plan["delivery"],
            "resume_from": str(checkpoint),
            "run_id": run_id,
        }
        job = self.submit(request, key)
        for item in conversation["plans"]:
            if item.get("id") == plan["id"]:
                item["status"] = "running"
                item["resume_job_id"] = job.get("id", "")
        if job.get("id") and job["id"] not in conversation["runs"]:
            conversation["runs"].append(job["id"])
        conversation["status"] = "running"
        self._write_agent_conversation(conversation)
        return self.redact(job)

    def agent_events(self, conversation_id: str, after: Any = 0) -> dict:
        conversation = self._read_agent_conversation(valid_conversation_id(conversation_id))
        try:
            cursor = max(0, int(after))
        except (TypeError, ValueError):
            cursor = 0
        all_events = []
        for index, message in enumerate(conversation.get("messages", []), start=1):
            all_events.append({"id": index, "kind": "message", "message": self.redact(message)})
        jobs = []
        for job_id in conversation.get("runs", []):
            if job_id in self.jobs:
                detail = self.job_detail(job_id)
                jobs.append(detail)
                for event in detail.get("events", []):
                    all_events.append({
                        "id": len(all_events) + 1,
                        "kind": "job",
                        "job_id": job_id,
                        "message": self.redact(event),
                    })
        events = [event for event in all_events if int(event["id"]) > cursor]
        return {"conversation_id": conversation["id"], "events": events, "jobs": jobs, "next": len(all_events)}

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

    def _provider_state(self) -> dict:
        payload = read_json(self.directory / "providers.json", {})
        if not isinstance(payload, dict):
            payload = {}
        connections = payload.get("connections", [])
        if not isinstance(connections, list):
            connections = []
        bindings = payload.get("bindings", {})
        if not isinstance(bindings, dict):
            bindings = {}
        return {
            "connections": [row for row in connections if isinstance(row, dict)],
            "bindings": {role: str(bindings.get(role) or "") for role in ROLE_NAMES},
        }

    def _custom_secrets(self) -> dict[str, str]:
        payload = read_json(self.directory / "provider_secrets.json", {})
        return {str(k): str(v) for k, v in payload.items()} if isinstance(payload, dict) else {}

    def _builtin_provider_rows(self) -> list[dict]:
        env = gui.load_env_file(self.root / ".env.gui")
        rows = []
        for provider, label in PROVIDERS.items():
            prefix = provider.upper()
            configured = any(value for key, value in env.items() if key.startswith(prefix) and ("KEY" in key or "TOKEN" in key))
            if provider == "opencodex":
                configured = env.get("OPENCODEX_IMAGE_ENABLED") == "1"
            rows.append({
                "id": provider,
                "name": label,
                "label": label,
                "builtin": True,
                "protocol": "内置适配器",
                "billing": "subscription" if provider in {"minimax", "opencodex"} else "unknown",
                "configured": bool(configured),
                "verification_status": "configured" if configured else "not_configured",
                "models": [],
            })
        return rows

    def providers(self) -> dict:
        state = self._provider_state()
        custom = []
        secrets = self._custom_secrets()
        for row in state["connections"]:
            provider_id = str(row.get("id") or "")
            if provider_id in PROVIDERS or not CUSTOM_PROVIDER_ID.fullmatch(provider_id):
                continue
            models = [m for m in row.get("models", []) if isinstance(m, dict)]
            custom.append({
                "id": provider_id,
                "name": str(row.get("name") or provider_id),
                "label": str(row.get("name") or provider_id),
                "builtin": False,
                "protocol": str(row.get("protocol") or ""),
                "base_url": str(row.get("base_url") or ""),
                "billing": str(row.get("billing") or "unknown"),
                "configured": bool(secrets.get(provider_id)),
                "verification_status": str(row.get("verification_status") or "unverified"),
                "models": [{"id": str(m.get("id") or ""), "name": str(m.get("name") or m.get("id") or ""), "kind": str(m.get("kind") or "llm")} for m in models],
            })
        return {"connections": self._builtin_provider_rows() + custom, "bindings": state["bindings"], "roles": ROLE_NAMES}

    def save_provider(self, data: dict) -> dict:
        provider_id = str(data.get("id") or "").strip().lower()
        if not CUSTOM_PROVIDER_ID.fullmatch(provider_id) or provider_id in PROVIDERS:
            raise ValueError("自定义供应商 ID 必须是未占用的小写字母、数字、下划线或短横线")
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 80:
            raise ValueError("供应商名称不能为空或超过80个字符")
        protocol = str(data.get("protocol") or "").strip()
        if protocol not in CUSTOM_PROTOCOLS:
            raise ValueError("接口协议暂只支持 OpenAI 兼容聊天或生图")
        base_url = str(data.get("base_url") or "").strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API 地址必须是 http 或 https URL，不能携带查询参数")
        billing = str(data.get("billing") or "unknown").strip()
        if billing not in CUSTOM_BILLING:
            raise ValueError("计费类型无效")
        raw_models = data.get("models", [])
        if not isinstance(raw_models, list) or len(raw_models) > 100:
            raise ValueError("模型数量必须为0至100个")
        models = []
        for item in raw_models:
            if not isinstance(item, dict):
                raise ValueError("模型格式无效")
            model_id = str(item.get("id") or "").strip()
            kind = str(item.get("kind") or "llm").strip()
            if not CUSTOM_MODEL_ID.fullmatch(model_id) or kind not in {"llm", "image"}:
                raise ValueError("模型 ID 或能力类型无效")
            models.append({"id": model_id, "name": str(item.get("name") or model_id).strip()[:120], "kind": kind})
        state = self._provider_state()
        custom = [row for row in state["connections"] if str(row.get("id") or "") != provider_id]
        custom.append({"id": provider_id, "name": name, "protocol": protocol, "base_url": base_url, "billing": billing,
                       "verification_status": "unverified", "models": models})
        _write_json_atomic(self.directory / "providers.json", {"connections": custom, "bindings": state["bindings"]})
        secrets = self._custom_secrets()
        api_key = str(data.get("api_key") or "").strip()
        if api_key:
            secrets[provider_id] = api_key
        _write_json_atomic(self.directory / "provider_secrets.json", secrets)
        return {"connection": next(row for row in self.providers()["connections"] if row["id"] == provider_id), "bindings": self.providers()["bindings"]}

    def save_model_bindings(self, data: dict) -> dict:
        if set(data) - set(ROLE_NAMES):
            raise ValueError("模型角色无效")
        state = self._provider_state()
        bindings = {role: str(data.get(role) or "").strip() for role in ROLE_NAMES}
        catalog = {row["id"]: row for row in self.models()["rows"]}
        for role, model_id in bindings.items():
            if len(model_id) > 260 or (model_id and ":" not in model_id):
                raise ValueError(f"{ROLE_NAMES[role]}的模型标识无效")
            if not model_id:
                continue
            model = catalog.get(model_id)
            expected_kind = "image" if role == "image" else "llm"
            if not model or not model.get("selectable") or model.get("kind") != expected_kind:
                raise ValueError(f"{ROLE_NAMES[role]}只能绑定当前目录中可执行的{('生图' if role == 'image' else '语言')}模型")
        _write_json_atomic(self.directory / "providers.json", {"connections": state["connections"], "bindings": bindings})
        return {"bindings": bindings}

    def models(self) -> dict:
        rows, snapshots = [], []
        labels = dict(PROVIDERS)
        env = gui.load_env_file(self.root / ".env.gui")
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
                entry.update(id=f"{provider}:{row.model}", provider_name=PROVIDERS[provider], kind=kind[0] if kind else row.kind, cost_class=cost,
                             expires_at=expiry, snapshot_at=timestamp, disabled_reason=reason, selectable=not reason)
                rows.append(entry)
        # MiniMax Token Plan is a subscription connection. It may be usable
        # without a quota snapshot, so expose its explicitly configured models
        # instead of forcing an unnecessary second sync. The unknown quantity
        # is shown as metadata, never converted into a fake remaining balance.
        existing_ids = {str(row.get("id") or "") for row in rows}
        minimax_key = str(env.get("MINIMAX_TOKEN_PLAN_API_KEY") or "").strip()
        minimax_models = []
        for key, default, kind in (
            ("MINIMAX_LLM_MODEL", DEFAULT_MINIMAX_LLM_MODEL, "llm"),
            ("MINIMAX_IMAGE_MODEL", DEFAULT_MINIMAX_IMAGE_MODEL, "image"),
        ):
            configured = str(env.get(key) or "").strip() or default
            values = [item.strip() for item in re.split(r"[,;\s]+", configured) if item.strip()]
            for model in values:
                minimax_models.append((model, kind))
        subscription_ok = str(env.get("MINIMAX_BILLING_MODE") or "subscription_only").strip().lower() in {"subscription", "subscription_only"}
        paid_disabled = str(env.get("MINIMAX_ALLOW_PAID_CREDITS") or "0").strip().lower() not in {"1", "true", "yes", "on"} and str(env.get("MINIMAX_ALLOW_PAYGO") or "0").strip().lower() not in {"1", "true", "yes", "on"}
        minimax_configured = bool(minimax_key or env.get("MINIMAX_LLM_MODEL") or env.get("MINIMAX_IMAGE_MODEL") or env.get("MINIMAX_USE_SUBSCRIPTION"))
        configured_minimax_ids = {f"minimax:{model}" for model, _ in minimax_models}
        if minimax_key and subscription_ok and paid_disabled:
            for entry in rows:
                if entry.get("id") not in configured_minimax_ids:
                    continue
                entry.update(
                    remaining=None,
                    total=None,
                    used=None,
                    unit="订阅额度未同步",
                    cost_class="subscription_included",
                    quota_pool="MiniMax Token Plan",
                    status="subscription_configured",
                    selectable=True,
                    disabled_reason="",
                    snapshot_at=0,
                    expires_at="",
                )
        for model, kind in minimax_models if minimax_configured else []:
            model_id = f"minimax:{model}"
            if model_id in existing_ids:
                continue
            reason = "" if minimax_key and subscription_ok and paid_disabled else (
                "未配置 MiniMax Token Plan 密钥" if not minimax_key else "MiniMax 订阅策略未确认"
            )
            rows.append({"id": model_id, "provider": "minimax", "provider_name": PROVIDERS["minimax"],
                         "model": model, "kind": kind, "remaining": None, "total": None, "used": None,
                         "unit": "订阅额度未同步", "cost_class": "subscription_included", "quota_pool": "MiniMax Token Plan",
                         "status": "subscription_configured", "selectable": not reason, "disabled_reason": reason,
                         "snapshot_at": 0, "expires_at": ""})
        state = self._provider_state()
        secrets = self._custom_secrets()
        for provider in state["connections"]:
            provider_id = str(provider.get("id") or "")
            if provider_id in PROVIDERS or not CUSTOM_PROVIDER_ID.fullmatch(provider_id):
                continue
            label = str(provider.get("name") or provider_id)
            labels[provider_id] = label
            billing = str(provider.get("billing") or "unknown")
            configured = bool(secrets.get(provider_id))
            for model in provider.get("models", []):
                if not isinstance(model, dict):
                    continue
                model_id, kind = str(model.get("id") or ""), str(model.get("kind") or "llm")
                if not CUSTOM_MODEL_ID.fullmatch(model_id) or kind not in {"llm", "image"}:
                    continue
                reason = ""
                if billing not in {"free", "subscription"}:
                    reason = "费用未知或不允许按量付费"
                elif not configured:
                    reason = "未配置密钥"
                else:
                    reason = "自定义供应商适配器尚未启用"
                rows.append({"id": f"{provider_id}:{model_id}", "provider": provider_id, "provider_name": label,
                             "model": model_id, "kind": kind, "remaining": None, "total": None, "used": None,
                             "unit": "", "cost_class": billing, "quota_pool": "", "status": "custom",
                             "selectable": not reason, "disabled_reason": reason, "snapshot_at": 0, "expires_at": ""})
        from src.images.opencodex_images import image_connection_status
        connection = image_connection_status(env)
        if connection["enabled"]:
            rows.append({"id": "opencodex:gpt-image-2", "provider": "opencodex",
                         "provider_name": PROVIDERS["opencodex"], "model": "gpt-image-2", "kind": "image",
                         "remaining": None, "total": None, "used": None, "unit": "订阅额度未查询",
                         "cost_class": "subscription_included", "quota_pool": "ChatGPT subscription",
                         "status": "preflight_required", "selectable": True, "disabled_reason": "",
                         "snapshot_at": 0, "expires_at": ""})
        return {"rows": rows, "snapshots": snapshots, "provider_labels": labels}

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
        return {"capabilities": {"titles": ["每日新闻", "每日我去", "每日AI讯息", "每日羊毛", "每日假新闻", "每日全球事件关注图"], "news_windows": [1, 2, 3, 5],
                 "max_count": 20, "source_cap": 2, "platforms": ["xhs", "toutiao", "both"], "readback_platform": "xhs"},
                "settings": self.settings(), "models": self.models(), "providers": self.providers(), "jobs": self.list_jobs(),
                "accounts": [{"provider": p, "label": label, "configured": any(v for k, v in env.items() if k.startswith(p.upper()) and ("KEY" in k or "TOKEN" in k))} for p, label in PROVIDERS.items()],
                "profile": "data/browser/" + gui.build_xhs_creator_profile_dir(project_root=self.root, env=env).name,
                "login_status": "未验证"}

    def assert_idle(self) -> None:
        if self.process is not None or any(j["status"] in ACTIVE for j in self.jobs.values()):
            raise ValueError("已有任务运行中，请在任务中心等待完成或停止；浏览器任务不能并发")

    def global_map_preview(self, request: dict) -> dict:
        """Read-only coverage preview; it never creates a platform draft."""
        payload = dict(request or {})
        if str(os.getenv("GLOBAL_MAP_ENABLED", "0")).lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("GLOBAL_MAP_DISABLED: 请先启用全球事件关注图功能")
        return preview_global_map_from_service(request=GlobalMapRequest.from_mapping(payload))

    def plan(self, request: dict, job_id: str) -> tuple[list[str], dict]:
        kind = request.get("kind")
        env = self.environment()
        args = [sys.executable, "-u", "-m", "apps.cli"]
        if kind == "agent":
            count = int(request.get("count", 10))
            if not 1 <= count <= 20:
                raise ValueError("数量必须为1至20")
            mode = str(request.get("performance_mode", "speed"))
            platform = str(request.get("platform", "xhs"))
            if mode not in {"balanced", "speed"} or platform not in {"xhs", "toutiao", "both"}:
                raise ValueError("模式或目标平台无效")
            prompt = gui.combine_prompt_entries(request.get("prompts", []))
            if not prompt:
                prompt = "国际冲突 争议事件 全球热点 财经产业 科技产业 芯片 AI 社会民生 体育文化 中国国内"
            lookback = str(request.get("lookback_days", "auto") or "auto")
            try:
                budget_minutes = max(0.1, min(120.0, float(request.get("budget_minutes", 30))))
            except (TypeError, ValueError):
                raise ValueError("智能体预算必须是0.1至120分钟")
            resume_from = str(request.get("resume_from", "") or "").strip()
            if resume_from:
                resume_path = (Path(resume_from) if Path(resume_from).is_absolute() else self.root / resume_from).resolve()
                agent_root = (self.root / "data" / "runs" / "agent").resolve()
                if not resume_path.is_relative_to(agent_root):
                    raise ValueError("智能体检查点必须位于 data/runs/agent 内")
            run_id = str(request.get("run_id", "") or "").strip()
            if run_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
                raise ValueError("智能体运行编号无效")
            agent_jobs_file = str(request.get("agent_jobs_file", "") or "").strip()
            if agent_jobs_file:
                jobs_path = Path(agent_jobs_file)
                if not jobs_path.is_absolute():
                    jobs_path = self.root / jobs_path
                jobs_path = jobs_path.resolve()
                conversations_root = (self.directory / "conversations").resolve()
                if not jobs_path.is_relative_to(conversations_root) or jobs_path.suffix.lower() != ".json" or not jobs_path.is_file():
                    raise ValueError("智能体任务计划必须位于 data/web_gui/conversations 内")
            assets_glob = str(request.get("assets_glob", "assets/empty/*") or "assets/empty/*").strip()
            if Path(assets_glob).is_absolute() or ".." in Path(assets_glob).parts:
                raise ValueError("素材路径必须是工作区内的相对路径")
            # Resolve the three roles from the same catalog used by the pickers.
            # An omitted role keeps the documented MiniMax subscription default;
            # an explicitly selected role must be a currently selectable model.
            catalog = {row["id"]: row for row in self.models()["rows"]}

            def resolve_role(role: str, requested: str, fallback_provider: str, fallback_model: str) -> dict:
                if not requested:
                    return {"provider": fallback_provider, "model": fallback_model}
                selected = catalog.get(requested)
                expected_kind = "image" if role == "image" else "llm"
                if not selected or not selected.get("selectable") or selected.get("kind") != expected_kind:
                    expected = "生图" if role == "image" else "语言"
                    raise ValueError(f"{ROLE_NAMES[role]}模型不可用：请重新选择有有效额度的{expected}模型")
                return selected

            agent_role = resolve_role(
                "agent", str(request.get("agent_id") or "").strip(), "minimax",
                env.get("MINIMAX_LLM_MODEL") or "",
            )
            writer_role = resolve_role(
                "writer", str(request.get("llm_id") or "").strip(), "minimax",
                env.get("MINIMAX_LLM_MODEL") or "",
            )
            image_requested = str(request.get("image_id") or "").strip()
            if image_requested:
                image_role = catalog.get(image_requested)
                if not image_role or not image_role.get("selectable") or image_role.get("kind") != "image":
                    raise ValueError("生图模型不可用：请重新选择有有效额度的生图模型")
            else:
                image_provider = "opencodex" if env.get("IMAGE_PROVIDER") == "opencodex" else "minimax"
                image_role = {"provider": image_provider, "model": "gpt-image-2" if image_provider == "opencodex" else env.get("MINIMAX_IMAGE_MODEL") or ""}

            # The agent owns provider selection, but the selected role values are
            # passed explicitly so the controller cannot silently reuse the writer.
            env = gui.build_provider_env_overrides(
                env,
                llm_provider=writer_role["provider"],
                llm_model=writer_role["model"],
                image_provider=image_role["provider"],
                image_model=image_role["model"],
            )
            env.update(
                AGENT_LLM_PROVIDER=agent_role["provider"],
                AGENT_LLM_MODEL=agent_role["model"],
                LLM_PROVIDER=writer_role["provider"],
                IMAGE_PROVIDER=image_role["provider"],
                MINIMAX_USE_SUBSCRIPTION="1",
                MINIMAX_BILLING_MODE="subscription_only",
                MINIMAX_ALLOW_PAID_CREDITS="0",
                MINIMAX_ALLOW_PAYGO="0",
                ALLOW_PAID_LLM_FALLBACK="0",
                DAILY_NEWS_SELECTION_POLICY="soft",
                WORKFLOW_PERFORMANCE_MODE=mode,
            )
            args += [
                "agent",
                "--prompt", prompt,
                "--count", str(count),
                "--evaluation-viewpoint", str(request.get("evaluation_viewpoint") or "无视角评价"),
                "--lookback-days", lookback,
                "--assets-glob", assets_glob or "assets/empty/*",
                "--platform", platform,
                "--performance-mode", mode,
                "--headless", "--login-hold", "0", "--wait-timeout", "600",
                "--budget-minutes", str(budget_minutes),
                "--no-refresh-quotas",
            ]
            if resume_from:
                args += ["--resume-from", str(resume_path)]
            if run_id:
                args += ["--run-id", run_id]
            if agent_jobs_file:
                args += ["--job-plan-file", str(jobs_path)]
            if bool(request.get("include_wow")):
                args.append("--wow")
        elif kind in {"auto", "material"}:
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
                if model_kind == "image" and (asset_pattern or title == "每日AI讯息" or (title == "每日羊毛" and not request.get("image_id"))):
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
        elif kind == "manage-drafts":
            management_mode = str(request.get("mode", "review") or "review").strip().lower()
            if management_mode not in {"review", "publish"}:
                raise ValueError("平台草稿管理模式仅支持 review 或 publish")
            if management_mode == "publish" and not bool(request.get("yes")):
                raise ValueError("发布平台草稿必须显式确认 yes")
            visibility = str(request.get("visibility") or "private").strip().lower()
            if visibility != "private":
                raise ValueError("为避免误公开，平台草稿发布当前只允许 visibility=private")
            draft_type = str(request.get("draft_type", "image") or "image").strip().lower()
            if draft_type not in {"image", "video", "article"}:
                raise ValueError("平台草稿类型无效")
            max_items = bounded_int(request.get("max_items", 0), 0, 1000)
            max_age_days = bounded_int(request.get("max_age_days", 0), 0, 365)
            args += [
                "manage-drafts", "--mode", management_mode,
                "--draft-type", draft_type,
                "--max-items", str(max_items),
                "--max-age-days", str(max_age_days),
                "--run-id", str(request.get("run_id") or job_id),
                "--visibility", visibility,
                "--headless", "--login-hold", "0", "--wait-timeout", "600",
            ]
            title_contains = str(request.get("title_contains") or "").strip()
            if title_contains:
                args += ["--title-contains", title_contains]
            if management_mode == "publish":
                args.append("--yes")
        elif kind in {"global-map", "daily-global-map"}:
            scope_payload = dict(request)
            if kind == "global-map" and "delivery" not in scope_payload:
                scope_payload["delivery"] = "xhs"
            request_scope = GlobalMapRequest.from_mapping(scope_payload)
            args = [
                sys.executable, "-u", "-m", "apps.cli", "daily-global-map",
                "--date", request_scope.target_date,
                "--cutoff", request_scope.cutoff_at.isoformat(),
                "--map-mode", request_scope.map_mode,
                "--max-events", str(request_scope.max_events),
                "--delivery", request_scope.delivery,
                "--headless", "--login-hold", "0", "--wait-timeout", "600",
            ]
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
            if request.get("confirmation") != "确认仅自己可见":
                raise ValueError("私密发布前必须输入确认仅自己可见")
            args += ["publish-drafts", "--visibility", "private", "--yes", "--headless", "--login-hold", "0"]
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
            if kind == "publish-drafts" and request.get("confirmation") != "确认仅自己可见":
                raise ValueError("私密发布前必须输入确认仅自己可见")
            if kind == "publish-drafts":
                args += [kind, "--post-id", post_id, "--visibility", "private", "--yes", "--headless", "--login-hold", "0"]
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
            planned_request = dict(request)
            if request.get("kind") == "agent":
                # Tie the CLI checkpoint to the Web job so a later resume does
                # not need to guess which random agent run belongs to it.
                planned_request.setdefault("run_id", job_id)
            args, env = self.plan(planned_request, job_id)
            job = {"id": job_id, "key": key, "digest": digest, "kind": request["kind"], "title": request.get("title") or request["kind"],
                   "status": "queued", "created_at": time.time(), "started_at": None, "ended_at": None,
                   "message": "等待启动", "stage": "准备", "events": [], "post_ids": [], "exit_code": None}
            if request.get("kind") == "agent":
                job["agent_run_id"] = job_id
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
