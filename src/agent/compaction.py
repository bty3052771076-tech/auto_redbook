from __future__ import annotations

import json
import math
import os
import re
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from src.agent.conversation_store import PostgresConversationStore


_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’._-][A-Za-z0-9]+)*|[^\s]")


def estimate_tokens(value: Any) -> int:
    """Conservative local estimate used only for budget decisions, not billing."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    pieces = _TOKEN.findall(text)
    return sum(1 if re.fullmatch(r"[\u3400-\u9fff]|[^A-Za-z0-9\s]", piece) else max(1, math.ceil(len(piece) / 4)) for piece in pieces)


def compact_conversation(
    store: PostgresConversationStore,
    conversation_id: str,
    *,
    summarize: Callable[[dict[str, Any]], dict[str, Any]],
    soft_limit_tokens: int = 12000,
    keep_recent_messages: int = 16,
    allowed_evidence_refs: set[str] | None = None,
    task_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an immutable, versioned summary while preserving all raw messages."""
    conversation = store.get(conversation_id)
    messages = store.context_messages(conversation_id)
    active = store.active_snapshot(conversation_id)
    current_context = {"snapshot": active, "messages": messages}
    input_tokens = estimate_tokens(current_context)
    if input_tokens <= max(256, int(soft_limit_tokens)):
        return {"status": "not_needed", "input_tokens": input_tokens, "saved": False}
    compactable = messages[:-max(1, int(keep_recent_messages))]
    if not compactable:
        return {"status": "not_needed", "input_tokens": input_tokens, "saved": False}

    previous_through = int((active or {}).get("through_seq") or 0)
    increment = [message for message in compactable if int(message["seq"]) > previous_through]
    if not increment:
        return {"status": "not_needed", "input_tokens": input_tokens, "saved": False}
    through_seq = int(compactable[-1]["seq"])
    source = {
        "prior_summary": str((active or {}).get("summary") or ""),
        "prior_constraints": (active or {}).get("constraints") or [],
        "new_messages": increment,
        "instruction": "只保留用户明确约束、已完成/未完成事项、决策和待办；不补事实、不推断授权、不输出思维链。",
    }

    last_error = "summary response invalid"
    for attempt in range(2):
        try:
            response = summarize(source)
            if not isinstance(response, dict):
                raise ValueError("summary response must be an object")
            summary = str(response.get("summary") or "").strip()
            if not summary or len(summary) > 8000:
                raise ValueError("summary is empty or exceeds the size limit")
            previous_constraints = list((active or {}).get("constraints") or [])
            generated_constraints = response.get("constraints") or []
            if not isinstance(generated_constraints, list) or any(not isinstance(item, str) for item in generated_constraints):
                raise ValueError("constraints must be a list of strings")
            constraints = list(dict.fromkeys([*previous_constraints, *[item.strip()[:500] for item in generated_constraints if item.strip()]]))[:100]
            allowlist = allowed_evidence_refs or set()
            requested_refs = response.get("evidence_refs") or []
            if not isinstance(requested_refs, list) or any(not isinstance(item, str) for item in requested_refs):
                raise ValueError("evidence_refs must be a list of strings")
            evidence_refs = sorted(set((active or {}).get("evidence_refs") or []) | (set(requested_refs) & allowlist))
            output_tokens = estimate_tokens({"summary": summary, "constraints": constraints, "evidence_refs": evidence_refs})
            if output_tokens >= estimate_tokens(increment):
                return {"status": "no_savings", "input_tokens": input_tokens, "output_tokens": output_tokens, "saved": False}
            snapshot = store.save_snapshot(
                conversation_id,
                expected_revision=int(conversation.get("_revision", 0)),
                snapshot={
                    "through_seq": through_seq,
                    "summary": summary,
                    "constraints": constraints,
                    "evidence_refs": evidence_refs,
                    "task_state": task_state or {},
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )
            return {
                "status": "compacted",
                "saved": True,
                "snapshot_version": int(snapshot["version"]),
                "through_seq": through_seq,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "messages_preserved": len(messages),
            }
        except Exception as exc:
            last_error = str(exc)
            if "conversation changed" in last_error:
                return {"status": "conflict", "saved": False, "error": last_error}
    return {"status": "blocked", "saved": False, "error": last_error, "attempts": 2}


def compacted_context(store: PostgresConversationStore, conversation_id: str, *, recent_messages: int = 16) -> dict[str, Any]:
    """Return the active compressed prefix plus the untouched recent message suffix."""
    snapshot = store.active_snapshot(conversation_id)
    messages = store.context_messages(conversation_id)
    through_seq = int((snapshot or {}).get("through_seq") or 0)
    recent = [message for message in messages if int(message["seq"]) > through_seq]
    if not snapshot:
        recent = messages[-max(1, int(recent_messages)):]
    return {"snapshot": snapshot, "recent_messages": recent, "raw_message_count": len(messages)}


@contextmanager
def _minimax_environment() -> Iterator[None]:
    keys = ("LLM_PROVIDER", "ALLOW_PAID_LLM_FALLBACK", "MINIMAX_USE_SUBSCRIPTION", "MINIMAX_BILLING_MODE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.update({
            "LLM_PROVIDER": "minimax",
            "ALLOW_PAID_LLM_FALLBACK": "0",
            "MINIMAX_USE_SUBSCRIPTION": "1",
            "MINIMAX_BILLING_MODE": "subscription_only",
        })
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def minimax_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Use only the configured MiniMax subscription; never fall back to another provider."""
    with _minimax_environment():
        from src.config import load_llm_config
        from src.llm.generate import generate_json

        config = load_llm_config()
        configs = config if isinstance(config, list) else [config]
        if len(configs) != 1 or str(configs[0].provider).lower() != "minimax":
            raise RuntimeError("COMPACTION_PROVIDER_BLOCKED: expected exactly one MiniMax LLM configuration")
        return generate_json(
            configs[0],
            system_prompt=(
                "你负责压缩长期对话上下文，只输出 JSON {summary:string,constraints:string[],evidence_refs:string[]}。"
                "只总结显式用户要求、当前任务进度和待办；不推断外部事实、权限或已完成状态。"
                "证据引用只能逐字复制输入中已有引用，禁止补造；不输出思维链。"
            ),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            max_tokens=1400,
        )
