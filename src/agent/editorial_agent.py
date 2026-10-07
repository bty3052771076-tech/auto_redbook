"""Bounded, resumable editorial agent.

The graph owns orchestration and recovery. Domain work stays in injected tools,
which keeps the agent testable without network, model, or browser access.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, TypedDict
from uuid import uuid4


_SENSITIVE_KEY_RE = re.compile(r"(?i)(api[_-]?key|access[_-]?token|authorization|secret|password)")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization)([=:\s]+)[^\s&,]+"
)


def _redact_text(value: str) -> str:
    text = str(value or "")
    for name, secret in os.environ.items():
        if _SENSITIVE_KEY_RE.search(name) and secret and len(secret) >= 6:
            text = text.replace(secret, "[已隐藏]")
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1\2[已隐藏]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "[已隐藏]", text)

try:
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - dependency is declared in requirements
    raise RuntimeError("LangGraph is required for the editorial agent") from exc


AgentProgress = Callable[[str, str, str], None]

TERMINAL_PLATFORM_FAILURE_CODES = (
    "XHS_RISK_BLOCKED",
    "XHS_CHALLENGE_REQUIRED",
    "XHS_LOGIN_REQUIRED",
    "XHS_RATE_LIMITED",
    "XHS_WRITE_UNCERTAIN",
    "XHS_PENDING_REVIEW",
    "XHS_PLATFORM_RESTRICTED",
    "XHS_PLATFORM_REJECTED",
    "XHS_STATE_STORE_UNAVAILABLE",
)

TERMINAL_PROVIDER_FAILURE_MARKERS = (
    "rate_limit_error",
    "http_code': 429",
    '"http_code": 429',
    "HTTP 429",
    "Token Plan 用量上限",
    "Token Plan 速率限制",
)


@dataclass(frozen=True)
class AgentJob:
    """One independent editorial output in a single agent run."""

    kind: str
    title: str
    count: int = 1
    prompt: str = ""
    evaluation_viewpoint: str = "无视角评价"
    lookback_days: object = None

    def normalized(self) -> "AgentJob":
        kind = str(self.kind or "daily_news").strip().lower()
        if kind not in {"daily_news", "daily_ai_digest", "daily_wool", "daily_wow", "daily_global_map"}:
            raise ValueError(f"unsupported agent job kind: {kind}")
        return AgentJob(
            kind=kind,
            title=str(self.title or "").strip() or kind,
            count=max(1, int(self.count)),
            prompt=str(self.prompt or "").strip(),
            evaluation_viewpoint=str(self.evaluation_viewpoint or "无视角评价").strip(),
            lookback_days=self.lookback_days,
        )


@dataclass(frozen=True)
class EditorialAgentConfig:
    """Execution policy; quality gates are always enabled by the adapter."""

    provider: str = "minimax"
    use_subscription: bool = True
    max_attempts_per_job: int = 2
    # Three default jobs need 16 nodes on the happy path and roughly 26 when
    # each job takes one bounded recovery. Keep headroom without allowing an
    # unbounded conversation loop.
    max_steps: int = 64
    max_elapsed_s: float = 30 * 60
    checkpoint_dir: Path = Path("data") / "runs" / "agent"
    resume_from: Path | None = None
    checkpoint_backend: str = "json"
    conversation_context: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> "EditorialAgentConfig":
        provider = str(self.provider or "").strip().lower().replace("-", "_")
        checkpoint_backend = str(self.checkpoint_backend or "json").strip().lower()
        if provider not in {"minimax", "aliyun", "volcengine", "siliconflow"}:
            from src.model_platforms.integration import platform_config
            if platform_config('agent') is None:
                raise ValueError("智能体主控模型供应商必须是已接入的内置供应商或已验证的自定义模型")
        if provider == "minimax" and self.use_subscription and str(os.getenv("ALLOW_PAID_LLM_FALLBACK", "0")).lower() in {
            "1", "true", "yes", "on"
        }:
            raise ValueError("paid LLM fallback must be disabled for MiniMax subscription mode")
        if self.max_attempts_per_job < 1 or self.max_steps < 1 or self.max_elapsed_s <= 0:
            raise ValueError("agent retry and step budgets must be positive")
        if checkpoint_backend not in {"json", "postgres"}:
            raise ValueError("checkpoint backend must be json or postgres")
        if not isinstance(self.conversation_context, dict):
            raise ValueError("conversation context must be an object")
        raw_constraints = self.conversation_context.get("constraints") or []
        if not isinstance(raw_constraints, list) or any(not isinstance(item, str) for item in raw_constraints):
            raise ValueError("conversation context constraints must be strings")
        raw_skills = self.conversation_context.get("skills") or []
        if not isinstance(raw_skills, list) or any(not isinstance(item, dict) for item in raw_skills):
            raise ValueError("conversation context skills must be objects")
        conversation_context = {
            "snapshot_version": max(0, int(self.conversation_context.get("snapshot_version") or 0)),
            "through_seq": max(0, int(self.conversation_context.get("through_seq") or 0)),
            "summary": str(self.conversation_context.get("summary") or "")[:6000],
            "constraints": [item.strip()[:500] for item in raw_constraints[:30] if item.strip()],
            "skills": [
                {
                    "name": str(item.get("name") or "")[:80],
                    "version_hash": str(item.get("version_hash") or "")[:64],
                    "body": str(item.get("body") or "")[:12000],
                }
                for item in raw_skills[:3]
            ],
        }
        return EditorialAgentConfig(
            provider=provider,
            use_subscription=self.use_subscription,
            max_attempts_per_job=min(3, int(self.max_attempts_per_job)),
            max_steps=min(200, int(self.max_steps)),
            max_elapsed_s=max(1.0, float(self.max_elapsed_s)),
            checkpoint_dir=Path(self.checkpoint_dir),
            resume_from=Path(self.resume_from) if self.resume_from else None,
            checkpoint_backend=checkpoint_backend,
            conversation_context=conversation_context,
        )


@dataclass
class EditorialAgentTools:
    """Business tools supplied by the CLI/GUI adapter or by tests."""

    sync_context: Callable[[AgentJob], dict[str, Any]]
    generate: Callable[[AgentJob, dict[str, Any]], list[Any]]
    review: Callable[[AgentJob, list[Any], dict[str, Any]], list[str]]
    upload: Callable[[AgentJob, Any, dict[str, Any]], tuple[bool, str]]
    plan: Callable[[list[AgentJob], dict[str, Any]], dict[str, Any]] | None = None
    load_posts: Callable[[list[str]], list[Any]] | None = None
    upload_enabled: bool = True
    # The adapter may keep one browser context for the whole reviewed batch.
    # The returned mapping is keyed by post id and is still interpreted one
    # item at a time so checkpoints remain resumable and auditable.
    upload_batch: Callable[[AgentJob, list[Any], dict[str, Any]], dict[str, tuple[bool, str]]] | None = None


class AgentState(TypedDict, total=False):
    run_id: str
    model_runtime: dict[str, Any]
    jobs: list[dict[str, Any]]
    job_index: int
    attempts: dict[str, int]
    current_job: dict[str, Any]
    context: dict[str, Any]
    conversation_memory: dict[str, Any]
    controller_decision: dict[str, Any]
    plan_complete: bool
    posts: list[Any]
    post_ids: list[str]
    reviewed_posts: list[Any]
    reviewed_post_ids: list[str]
    uploaded_posts: list[Any]
    uploaded_post_ids: list[str]
    item_status: dict[str, str]
    errors: list[str]
    events: list[dict[str, Any]]
    status: str
    last_failure: str
    failed_jobs: list[int]
    recovery_attempts: dict[str, int]
    event_log_path: str
    next_event_id: int
    started_at: float
    root_started_at: float
    resume_count: int
    budget_exceeded: bool
    platform_paused: bool
    provider_paused: bool
    last_node: str
    steps: int


def _job_from_dict(value: dict[str, Any]) -> AgentJob:
    return AgentJob(**value).normalized()


def _post_id(post: Any) -> str:
    return str(getattr(post, "id", "") or "")


def _post_ids(posts: list[Any]) -> list[str]:
    return [post_id for post in posts if (post_id := _post_id(post))]


def _content_version(post: Any) -> str:
    """Return a stable local version so a changed post is never skipped blindly."""
    if hasattr(post, "model_dump"):
        value: Any = post.model_dump()
    elif hasattr(post, "__dict__"):
        value = vars(post)
    else:
        value = {"id": _post_id(post), "value": str(post)}
    return hashlib.sha256(
        json.dumps(_safe_value(value), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def _safe_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _safe_value(value.model_dump())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(k): _safe_value(v)
            for k, v in value.items()
            if not _SENSITIVE_KEY_RE.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(v) for v in value]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _checkpoint_payload(state: AgentState) -> dict[str, Any]:
    """Persist state needed for audit/resume without credentials or raw secrets."""
    from src.model_platforms.integration import checkpoint_models
    return {
        "run_id": state.get("run_id", ""),
        "model_runtime": checkpoint_models(saved=state['model_runtime']) if state.get('model_runtime') else {},
        "jobs": _safe_value(state.get("jobs", [])),
        "job_index": int(state.get("job_index", 0)),
        "attempts": _safe_value(state.get("attempts", {})),
        "context": _safe_value(state.get("context", {})),
        "controller_decision": _safe_value(state.get("controller_decision", {})),
        "plan_complete": bool(state.get("plan_complete", False)),
        "post_ids": list(state.get("post_ids") or _post_ids(state.get("posts", []))),
        "reviewed_post_ids": list(state.get("reviewed_post_ids") or _post_ids(state.get("reviewed_posts", []))),
        "uploaded_post_ids": list(state.get("uploaded_post_ids") or _post_ids(state.get("uploaded_posts", []))),
        "item_status": _safe_value(state.get("item_status", {})),
        "errors": list(state.get("errors", [])),
        "failed_jobs": list(state.get("failed_jobs", [])),
        "recovery_attempts": _safe_value(state.get("recovery_attempts", {})),
        "event_log_path": str(state.get("event_log_path", "")),
        "next_event_id": int(state.get("next_event_id", 0)),
        "started_at": float(state.get("started_at", 0.0)),
        "root_started_at": float(state.get("root_started_at", state.get("started_at", 0.0))),
        "resume_count": int(state.get("resume_count", 0)),
        "budget_exceeded": bool(state.get("budget_exceeded", False)),
        "platform_paused": bool(state.get("platform_paused", False)),
        "provider_paused": bool(state.get("provider_paused", False)),
        "events": _safe_value(state.get("events", []))[-80:],
        "status": state.get("status", "running"),
        "last_failure": state.get("last_failure", ""),
        "last_node": state.get("last_node", ""),
        "steps": int(state.get("steps", 0)),
        "saved_at": time.time(),
    }


def _save_checkpoint(state: AgentState, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tmp").mkdir(parents=True, exist_ok=True)
    path = directory / "checkpoint.json"
    temporary = directory / "tmp" / "checkpoint.json.tmp"
    temporary.write_text(
        json.dumps(_checkpoint_payload(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_agent_checkpoint(path: Path | str) -> dict[str, Any]:
    """Load an audit checkpoint for inspection or an adapter-managed resume."""
    checkpoint_path = Path(path)
    if checkpoint_path.is_dir():
        checkpoint_path = checkpoint_path / "checkpoint.json"
    # Keep compatibility with the first implementation, which wrote
    # data/runs/agent/<run_id>.json directly under the base directory.
    return json.loads(checkpoint_path.read_text(encoding="utf-8"))


def _emit(state: AgentState, progress: AgentProgress | None, node: str, status: str, detail: str = "") -> None:
    event_id = int(state.get("next_event_id", 0)) + 1
    safe_detail = _redact_text(detail)
    event = {"id": event_id, "node": node, "status": status, "detail": safe_detail, "at": time.time()}
    state["next_event_id"] = event_id
    state.setdefault("events", []).append(event)
    state["last_node"] = node
    log_path = str(state.get("event_log_path", "")).strip()
    if log_path:
        try:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(_safe_value(event), ensure_ascii=False) + "\n")
        except OSError:
            # The checkpoint remains authoritative if telemetry storage is
            # temporarily unavailable; never fail an editorial job only for a
            # progress-log write.
            pass
    if progress:
        progress(node, status, safe_detail)


def _build_graph(
    *,
    config: EditorialAgentConfig,
    tools: EditorialAgentTools,
    progress: AgentProgress | None,
    checkpointer: Any = None,
):
    def persist(state: AgentState, node: str) -> AgentState:
        state["steps"] = int(state.get("steps", 0)) + 1
        state["last_node"] = node
        _save_checkpoint(state, config.checkpoint_dir)
        return state

    def stop_if_budget_exceeded(state: AgentState, node: str) -> bool:
        if state.get("budget_exceeded"):
            return True
        started_at = float(state.get("started_at", time.time()))
        elapsed = max(0.0, time.time() - started_at)
        # Leave room for the current node and a terminal finish node after the
        # guard trips; otherwise LangGraph's recursion limit could mask the
        # intended partial/blocked result.
        if elapsed < config.max_elapsed_s and int(state.get("steps", 0)) < config.max_steps - 2:
            return False
        state["budget_exceeded"] = True
        state["last_failure"] = (
            f"agent budget exhausted at {node}: elapsed={elapsed:.1f}s/{config.max_elapsed_s:.1f}s "
            f"steps={state.get('steps', 0)}/{config.max_steps}"
        )
        _emit(state, progress, "budget", "warning", state["last_failure"])
        return True

    def plan(state: AgentState) -> AgentState:
        jobs = [_job_from_dict(item).__dict__ for item in state.get("jobs", [])]
        if not jobs:
            raise ValueError("editorial agent has no jobs")
        decision: dict[str, Any] = {}
        if tools.plan is not None and not state.get("controller_decision"):
            try:
                decision = _safe_value(tools.plan([_job_from_dict(item) for item in jobs], state.get("context", {}))) or {}
                if not isinstance(decision, dict):
                    raise ValueError("controller plan must be an object")
                requested_order = decision.get("job_order")
                if isinstance(requested_order, list):
                    ordered: list[dict[str, Any]] = []
                    used: set[int] = set()
                    for raw_index in requested_order:
                        try:
                            index = int(raw_index)
                        except (TypeError, ValueError):
                            continue
                        if 0 <= index < len(jobs) and index not in used:
                            ordered.append(jobs[index])
                            used.add(index)
                    jobs = ordered + [job for index, job in enumerate(jobs) if index not in used]
                state["controller_decision"] = decision
            except Exception as exc:
                state["controller_decision"] = {"status": "fallback", "error": str(exc)}
                state.setdefault("errors", []).append(_redact_text(f"controller_plan_warning: {exc}"))
        index = min(max(0, int(state.get("job_index", 0))), len(jobs))
        state.update({"jobs": jobs, "job_index": index, "status": "running", "plan_complete": True})
        summary = str(state.get("controller_decision", {}).get("summary", "")).strip()
        _emit(state, progress, "plan", "success", f"jobs={len(jobs)} index={index} provider={config.provider}" + (f" summary={summary}" if summary else ""))
        return persist(state, "plan")

    def sync_context(state: AgentState) -> AgentState:
        if int(state.get("job_index", 0)) >= len(state["jobs"]):
            return persist(state, "sync_context")
        if stop_if_budget_exceeded(state, "sync_context"):
            return persist(state, "sync_context")
        job = _job_from_dict(state["jobs"][state["job_index"]])
        state["current_job"] = job.__dict__
        context = tools.sync_context(job) or {}
        if state.get("conversation_memory"):
            context["conversation_memory"] = state["conversation_memory"]
        state["context"] = context
        if "knowledge_status" in context and context.get("knowledge_status") != "ready":
            code = str(context.get("error_code") or "KNOWLEDGE_DB_UNAVAILABLE")
            warning = str(context.get("knowledge_warning") or "PostgreSQL 知识库未就绪，已阻止生成。")
            state["status"] = "blocked"
            state["last_failure"] = f"{code}: {warning}"
            state.setdefault("errors", []).append(state["last_failure"])
            _emit(state, progress, "sync_context", "blocked", state["last_failure"])
            return persist(state, "sync_context")
        _emit(state, progress, "sync_context", "success", job.kind)
        return persist(state, "sync_context")

    def generate(state: AgentState) -> AgentState:
        if stop_if_budget_exceeded(state, "generate"):
            return persist(state, "generate")
        job = _job_from_dict(state["current_job"])
        saved_post_ids = list(state.get("post_ids") or [])
        if saved_post_ids and tools.load_posts is not None:
            try:
                restored = list(tools.load_posts(saved_post_ids) or [])
            except Exception as exc:
                restored = []
                _emit(state, progress, "generate", "warning", f"恢复稿件失败，将重新生成：{exc}")
            if len(restored) == len(saved_post_ids) and _post_ids(restored) == saved_post_ids:
                state["posts"] = restored
                state["last_failure"] = ""
                _emit(state, progress, "generate", "resumed", f"{job.kind} reused={len(restored)}")
                return persist(state, "generate")
        key = str(state["job_index"])
        attempts = dict(state.get("attempts", {}))
        attempts[key] = int(attempts.get(key, 0)) + 1
        state["attempts"] = attempts
        state["post_ids"] = []
        state["reviewed_post_ids"] = []
        try:
            posts = list(tools.generate(job, state.get("context", {})) or [])
            state["posts"] = posts
            state["post_ids"] = _post_ids(posts)
            state["last_failure"] = ""
            _emit(state, progress, "generate", "success", f"{job.kind} posts={len(posts)} attempt={attempts[key]}")
        except Exception as exc:
            state["posts"] = []
            state["last_failure"] = _redact_text(f"generation_error: {exc}")
            state.setdefault("errors", []).append(state["last_failure"])
            _emit(state, progress, "generate", "failed", state["last_failure"])
        return persist(state, "generate")

    def review(state: AgentState) -> AgentState:
        if stop_if_budget_exceeded(state, "review"):
            return persist(state, "review")
        job = _job_from_dict(state["current_job"])
        posts = list(state.get("posts", []))
        reviewed_ids = list(state.get("reviewed_post_ids") or [])
        if not posts and reviewed_ids and tools.load_posts is not None:
            try:
                restored = list(tools.load_posts(reviewed_ids) or [])
            except Exception as exc:
                restored = []
                _emit(state, progress, "review", "warning", f"恢复待审核稿件失败：{exc}")
            if len(restored) == len(reviewed_ids) and _post_ids(restored) == reviewed_ids:
                posts = restored
                state["posts"] = restored
        try:
            errors = list(tools.review(job, posts, state.get("context", {})) or [])
        except Exception as exc:
            errors = [f"review_error: {exc}"]
        state["reviewed_posts"] = posts if not errors else []
        state["reviewed_post_ids"] = _post_ids(state["reviewed_posts"])
        if errors:
            safe_errors = [_redact_text(error) for error in errors]
            state["last_failure"] = "; ".join(safe_errors[:3])
            state.setdefault("errors", []).extend(safe_errors)
            if any(
                marker in error
                for error in safe_errors
                for marker in TERMINAL_PROVIDER_FAILURE_MARKERS
            ):
                state["provider_paused"] = True
                _emit(
                    state,
                    progress,
                    "provider_pause",
                    "warning",
                    "模型供应商返回不可重试的限流/订阅上限，停止本次任务恢复循环",
                )
            _emit(state, progress, "review", "failed", state["last_failure"])
        else:
            state["last_failure"] = ""
            _emit(state, progress, "review", "success", f"posts={len(posts)}")
        return persist(state, "review")

    def upload(state: AgentState) -> AgentState:
        if stop_if_budget_exceeded(state, "upload"):
            return persist(state, "upload")
        job = _job_from_dict(state["current_job"])
        uploaded = list(state.get("uploaded_posts", []))
        uploaded_ids = list(state.get("uploaded_post_ids") or _post_ids(uploaded))
        if uploaded_ids and tools.load_posts is not None and not uploaded:
            try:
                uploaded = list(tools.load_posts(uploaded_ids) or [])
            except Exception as exc:
                _emit(state, progress, "upload", "warning", f"恢复已保存稿件失败：{exc}")
        item_status = dict(state.get("item_status") or {})
        failures: list[str] = []
        if state.get("platform_paused"):
            for post in state.get("reviewed_posts", []):
                item_key = f"{state.get('job_index', 0)}:{_post_id(post)}:{_content_version(post)}"
                item_status[item_key] = "skipped_platform_paused"
            _emit(state, progress, "upload", "skipped", f"{job.kind} platform_paused")
            state["item_status"] = item_status
            return persist(state, "upload")
        pending_posts: list[Any] = []
        for post in state.get("reviewed_posts", []):
            post_id = _post_id(post)
            item_key = f"{state.get('job_index', 0)}:{post_id}:{_content_version(post)}"
            legacy_key = f"{state.get('job_index', 0)}:{post_id}"
            if item_status.get(item_key) in {"saved", "skipped_local"} or item_status.get(legacy_key) in {"saved", "skipped_local"} or post_id in uploaded_ids:
                _emit(state, progress, "upload", "skipped", f"{job.kind} post={post_id} already_complete")
                continue
            if not tools.upload_enabled:
                item_status[item_key] = "skipped_local"
                _emit(state, progress, "upload", "skipped", f"{job.kind} post={post_id} local_only")
                continue
            pending_posts.append(post)

        if tools.upload_batch is not None and pending_posts:
            _emit(state, progress, "upload_batch", "in_progress", f"{job.kind} posts={len(pending_posts)}")
            outcomes: dict[str, tuple[bool, str]] = {}
            try:
                raw_outcomes = tools.upload_batch(job, pending_posts, state.get("context", {}))
                if not isinstance(raw_outcomes, dict):
                    raise TypeError("batch upload adapter must return a mapping keyed by post id")
                for post in pending_posts:
                    value = raw_outcomes.get(_post_id(post))
                    if isinstance(value, (tuple, list)) and len(value) >= 2:
                        outcomes[_post_id(post)] = (bool(value[0]), str(value[1] or ""))
                    else:
                        outcomes[_post_id(post)] = (
                            False,
                            "batch upload adapter returned no result for post_id=" + _post_id(post),
                        )
            except Exception as exc:
                detail = f"upload_batch_error: {exc}"
                outcomes = {_post_id(post): (False, detail) for post in pending_posts}

            for index, post in enumerate(pending_posts):
                post_id = _post_id(post)
                item_key = f"{state.get('job_index', 0)}:{post_id}:{_content_version(post)}"
                ok, detail = outcomes.get(post_id, (False, f"batch upload result missing for post_id={post_id}"))
                if ok:
                    uploaded.append(post)
                    uploaded_ids.append(post_id)
                    item_status[item_key] = "saved"
                    _emit(state, progress, "upload", "success", f"{job.kind} post={post_id} {detail}")
                    continue
                item_status[item_key] = "uncertain" if "uncertain" in str(detail).lower() else "failed"
                failures.append(f"upload_error: {detail or f'upload failed post={post_id}'}")
                _emit(state, progress, "upload", "failed", failures[-1])
                if any(code in str(detail) for code in TERMINAL_PLATFORM_FAILURE_CODES):
                    state["platform_paused"] = True
                    for remaining in pending_posts[index + 1:]:
                        remaining_id = _post_id(remaining)
                        remaining_key = f"{state.get('job_index', 0)}:{remaining_id}:{_content_version(remaining)}"
                        item_status[remaining_key] = "skipped_platform_paused"
                    break

            state["uploaded_posts"] = uploaded
            state["uploaded_post_ids"] = list(dict.fromkeys(uploaded_ids))
            state["item_status"] = item_status
            failures = [_redact_text(error) for error in failures]
            state["last_failure"] = "; ".join(failures[:3])
            if failures:
                state.setdefault("errors", []).extend(failures)
            _emit(state, progress, "upload_batch", "failed" if failures else "success", f"{job.kind} uploaded={len(uploaded)}")
            return persist(state, "upload")

        # The fallback loop is deliberately serial for adapters that have not
        # opted into the batch contract. Platform locks and idempotency remain
        # owned by the adapter.
        for post in pending_posts:
            post_id = _post_id(post)
            item_key = f"{state.get('job_index', 0)}:{post_id}:{_content_version(post)}"
            try:
                ok, detail = tools.upload(job, post, state.get("context", {}))
            except Exception as exc:
                ok, detail = False, f"upload_error: {exc}"
            if ok:
                uploaded.append(post)
                uploaded_ids.append(post_id)
                item_status[item_key] = "saved"
                _emit(state, progress, "upload", "success", f"{job.kind} post={post_id} {detail}")
            else:
                item_status[item_key] = "uncertain" if "uncertain" in str(detail).lower() else "failed"
                failures.append(f"upload_error: {detail or f'upload failed post={post_id}'}")
                _emit(state, progress, "upload", "failed", failures[-1])
                # A platform write may already have had an external side
                # effect. Stop this serial batch immediately instead of
                # submitting another post or retrying the uncertain action.
                if any(code in str(detail) for code in TERMINAL_PLATFORM_FAILURE_CODES):
                    state["platform_paused"] = True
                    break
        state["uploaded_posts"] = uploaded
        state["uploaded_post_ids"] = list(dict.fromkeys(uploaded_ids))
        state["item_status"] = item_status
        failures = [_redact_text(error) for error in failures]
        state["last_failure"] = "; ".join(failures[:3])
        if failures:
            state.setdefault("errors", []).extend(failures)
        return persist(state, "upload")

    def recover(state: AgentState) -> AgentState:
        if stop_if_budget_exceeded(state, "recover"):
            return persist(state, "recover")
        job = _job_from_dict(state["current_job"])
        key = str(state["job_index"])
        recoveries = dict(state.get("recovery_attempts", {}))
        recoveries[key] = int(recoveries.get(key, 0)) + 1
        state["recovery_attempts"] = recoveries
        # Review failures invalidate the generated batch.  Clear its IDs so
        # the next generate node cannot silently reload the same rejected
        # posts.  Upload failures keep the IDs and retry the same post batch
        # for platform idempotency.
        if not str(state.get("last_failure", "")).startswith("upload"):
            state["posts"] = []
            state["post_ids"] = []
            state["reviewed_posts"] = []
            state["reviewed_post_ids"] = []
        if recoveries[key] < config.max_attempts_per_job:
            _emit(state, progress, "recover", "retry", f"{job.kind} recovery={recoveries[key]} reason={state.get('last_failure', '')}")
        else:
            _emit(state, progress, "recover", "warning", f"{job.kind} retry budget exhausted")
        return persist(state, "recover")

    def next_job(state: AgentState) -> AgentState:
        if stop_if_budget_exceeded(state, "next_job"):
            return persist(state, "next_job")
        key = int(state.get("job_index", 0))
        recovery = int(state.get("recovery_attempts", {}).get(str(key), 0))
        if state.get("last_failure") and recovery >= config.max_attempts_per_job:
            state.setdefault("failed_jobs", []).append(key)
        state["job_index"] = int(state.get("job_index", 0)) + 1
        state["posts"] = []
        state["post_ids"] = []
        state["reviewed_posts"] = []
        state["reviewed_post_ids"] = []
        state["last_failure"] = ""
        return persist(state, "next_job")

    def finish(state: AgentState) -> AgentState:
        requested = len(state.get("jobs", []))
        completed = int(state.get("job_index", 0)) >= requested
        if state.get("budget_exceeded"):
            if state.get("last_failure") and state["last_failure"] not in state.setdefault("errors", []):
                state["errors"].append(state["last_failure"])
            state["status"] = "partial" if state.get("uploaded_posts") else "blocked"
        elif state.get("platform_paused"):
            # A platform pause after a real submission attempt is a partial
            # run even when the remaining jobs were only generated locally.
            state["status"] = "partial"
        elif state.get("provider_paused"):
            state["status"] = "partial" if state.get("uploaded_posts") else "blocked"
        elif state.get("status") == "blocked":
            state["status"] = "blocked"
        else:
            state["status"] = "completed" if completed and not state.get("failed_jobs") else (
            "partial" if state.get("uploaded_posts") else "failed"
            )
        _emit(state, progress, "finish", state["status"], f"uploaded={len(state.get('uploaded_posts', []))}")
        return persist(state, "finish")

    def after_review(state: AgentState) -> str:
        if state.get("budget_exceeded") or state.get("provider_paused"):
            return "finish"
        if state.get("reviewed_posts"):
            return "upload"
        return "recover"

    def after_generate(state: AgentState) -> str:
        return "finish" if state.get("budget_exceeded") else "review"

    def after_sync_context(state: AgentState) -> str:
        if state.get("budget_exceeded") or state.get("status") == "blocked" or int(state.get("job_index", 0)) >= len(state.get("jobs", [])):
            return "finish"
        return "generate" if state.get("plan_complete") else "plan"

    def after_upload(state: AgentState) -> str:
        if state.get("budget_exceeded"):
            return "finish"
        last_failure = str(state.get("last_failure") or "")
        # A platform write can have an external side effect even when the
        # browser connection fails. Never retry a risk pause, challenge, login
        # failure, or uncertain submit from the generic recovery branch.
        if any(code in last_failure for code in TERMINAL_PLATFORM_FAILURE_CODES):
            return "next_job"
        key = str(state.get("job_index", 0))
        recovery = int(state.get("recovery_attempts", {}).get(key, 0))
        if not state.get("last_failure"):
            return "next_job"
        if recovery < config.max_attempts_per_job:
            return "recover"
        return "next_job"

    def after_recover(state: AgentState) -> str:
        if state.get("budget_exceeded"):
            return "finish"
        last_failure = str(state.get("last_failure") or "")
        if any(
            code in last_failure
            for code in TERMINAL_PLATFORM_FAILURE_CODES
        ):
            return "finish"
        key = str(state.get("job_index", 0))
        recovery = int(state.get("recovery_attempts", {}).get(key, 0))
        if recovery >= config.max_attempts_per_job:
            return "next_job"
        # A platform write failure must reuse the reviewed post. Re-generating
        # here would create a new post and could duplicate a successfully saved
        # platform draft from the same batch.
        if str(state.get("last_failure", "")).startswith("upload"):
            return "upload"
        return "generate"

    def after_next(state: AgentState) -> str:
        if state.get("budget_exceeded"):
            return "finish"
        return "finish" if int(state.get("job_index", 0)) >= len(state.get("jobs", [])) else "sync_context"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("sync_context", sync_context)
    graph.add_node("generate", generate)
    graph.add_node("review", review)
    graph.add_node("upload", upload)
    graph.add_node("recover", recover)
    graph.add_node("next_job", next_job)
    graph.add_node("finish", finish)
    graph.add_edge(START, "sync_context")
    graph.add_edge("plan", "sync_context")
    graph.add_conditional_edges("sync_context", after_sync_context)
    graph.add_conditional_edges("generate", after_generate)
    graph.add_conditional_edges("review", after_review)
    graph.add_conditional_edges("upload", after_upload)
    graph.add_conditional_edges("recover", after_recover)
    graph.add_conditional_edges("next_job", after_next)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def run_editorial_agent(
    jobs: list[AgentJob],
    *,
    tools: EditorialAgentTools,
    config: EditorialAgentConfig | None = None,
    progress: AgentProgress | None = None,
    run_id: str | None = None,
) -> AgentRunResult:
    """Run all jobs in one bounded state graph and save an audit checkpoint."""
    cfg = (config or EditorialAgentConfig()).validate()
    normalized_jobs = [job.normalized() for job in jobs]
    resume_checkpoint: dict[str, Any] = {}
    if cfg.resume_from and Path(cfg.resume_from).is_file():
        resume_checkpoint = load_agent_checkpoint(cfg.resume_from)
    elif cfg.resume_from and Path(cfg.resume_from).is_dir():
        resume_checkpoint = load_agent_checkpoint(cfg.resume_from)
    postgres_resume = cfg.checkpoint_backend == "postgres" and cfg.resume_from is not None
    if not normalized_jobs and not (postgres_resume and resume_checkpoint.get("run_id")):
        raise ValueError("at least one editorial job is required")
    identifier = str(resume_checkpoint.get("run_id") or run_id or uuid4().hex)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
        raise ValueError("智能体运行编号无效")
    run_directory = Path(cfg.checkpoint_dir) / identifier
    cfg = replace(cfg, checkpoint_dir=run_directory)
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_directory / "tmp").mkdir(parents=True, exist_ok=True)
    from src.model_platforms.integration import checkpoint_models
    initial: AgentState = {
        "run_id": identifier,
        "model_runtime": checkpoint_models(saved=resume_checkpoint.get('model_runtime')),
        "jobs": [job.__dict__ for job in normalized_jobs],
        "job_index": 0,
        "attempts": {},
        "context": {},
        "conversation_memory": dict(cfg.conversation_context),
        "controller_decision": {},
        "plan_complete": False,
        "posts": [],
        "post_ids": [],
        "reviewed_posts": [],
        "reviewed_post_ids": [],
        "uploaded_posts": [],
        "uploaded_post_ids": [],
        "item_status": {},
        "errors": [],
        "events": [],
        "status": "running",
        "failed_jobs": [],
        "recovery_attempts": {},
        "event_log_path": str(run_directory / "events.jsonl"),
        "next_event_id": 0,
        "started_at": time.time(),
        "root_started_at": time.time(),
        "resume_count": 0,
        "budget_exceeded": False,
        "platform_paused": False,
        "provider_paused": False,
        "steps": 0,
    }
    if resume_checkpoint and not postgres_resume:
        checkpoint = resume_checkpoint
        if checkpoint.get("jobs"):
            initial.update({
                "run_id": str(checkpoint.get("run_id") or identifier),
                "jobs": checkpoint["jobs"],
                "job_index": int(checkpoint.get("job_index", 0)),
                "attempts": dict(checkpoint.get("attempts") or {}),
                "controller_decision": dict(checkpoint.get("controller_decision") or {}),
                "plan_complete": bool(checkpoint.get("plan_complete", bool(checkpoint.get("controller_decision")))),
                "post_ids": list(checkpoint.get("post_ids") or []),
                "reviewed_post_ids": list(checkpoint.get("reviewed_post_ids") or []),
                "uploaded_post_ids": list(checkpoint.get("uploaded_post_ids") or []),
                "item_status": dict(checkpoint.get("item_status") or {}),
                "errors": list(checkpoint.get("errors") or []),
                "failed_jobs": list(checkpoint.get("failed_jobs") or []),
                "recovery_attempts": dict(checkpoint.get("recovery_attempts") or {}),
                "event_log_path": str(checkpoint.get("event_log_path") or run_directory / "events.jsonl"),
                "next_event_id": int(checkpoint.get("next_event_id", 0)),
                # A resumed attempt gets a fresh budget clock. Keep the first
                # start time separately for audit without making a long pause
                # consume the new attempt's entire budget.
                "started_at": time.time(),
                "root_started_at": float(checkpoint.get("root_started_at") or checkpoint.get("started_at") or time.time()),
                "resume_count": int(checkpoint.get("resume_count", 0)) + 1,
                "budget_exceeded": False,
                "platform_paused": bool(checkpoint.get("platform_paused", False)),
                "provider_paused": bool(checkpoint.get("provider_paused", False)),
                "events": list(checkpoint.get("events") or []),
                "steps": 0,
                "last_failure": "" if checkpoint.get("budget_exceeded") else str(checkpoint.get("last_failure") or ""),
            })
    graph_config = {
        "recursion_limit": cfg.max_steps + 4,
        "configurable": {"thread_id": identifier},
    }
    try:
        if cfg.checkpoint_backend == "postgres":
            from src.agent.postgres_checkpoint import postgres_checkpointer
            with postgres_checkpointer() as checkpointer:
                graph = _build_graph(config=cfg, tools=tools, progress=progress, checkpointer=checkpointer)
                if postgres_resume:
                    persisted = graph.get_state(graph_config)
                    if not persisted or not persisted.values:
                        raise RuntimeError("POSTGRES_CHECKPOINT_NOT_FOUND: no durable state exists for this run id")
                    if persisted.next:
                        final = graph.invoke(None, graph_config)
                    elif persisted.values.get("budget_exceeded"):
                        resumed = dict(persisted.values)
                        resumed.update({
                            "started_at": time.time(),
                            "root_started_at": float(resumed.get("root_started_at") or resumed.get("started_at") or time.time()),
                            "resume_count": int(resumed.get("resume_count", 0)) + 1,
                            "budget_exceeded": False,
                            "steps": 0,
                            "status": "running",
                            "last_failure": "",
                        })
                        final = graph.invoke(resumed, graph_config)
                    else:
                        final = dict(persisted.values)
                else:
                    final = graph.invoke(initial, graph_config)
        else:
            graph = _build_graph(config=cfg, tools=tools, progress=progress)
            final = graph.invoke(initial, graph_config)
    except Exception as exc:
        initial["status"] = "failed"
        initial.setdefault("errors", []).append(_redact_text(f"agent_runtime_error: {exc}"))
        if cfg.checkpoint_backend != "postgres":
            _save_checkpoint(initial, cfg.checkpoint_dir)
        raise
    processed_jobs = min(int(final.get("job_index", 0)), len(final.get("jobs") or []))
    failed_jobs = {
        int(index) for index in (final.get("failed_jobs") or [])
        if isinstance(index, int) or str(index).isdigit()
    }
    return AgentRunResult(
        run_id=str(final.get("run_id") or identifier),
        status=str(final.get("status") or "failed"),
        requested_jobs=len(final.get("jobs") or []),
        completed_jobs=processed_jobs - sum(0 <= index < processed_jobs for index in failed_jobs),
        uploaded_posts=list(final.get("uploaded_posts") or []),
        errors=list(final.get("errors") or []),
        checkpoint_path=cfg.checkpoint_dir / "checkpoint.json",
        events=list(final.get("events") or []),
    )


@dataclass(frozen=True)
class AgentRunResult:
    run_id: str
    status: str
    requested_jobs: int
    completed_jobs: int
    uploaded_posts: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checkpoint_path: Path | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
