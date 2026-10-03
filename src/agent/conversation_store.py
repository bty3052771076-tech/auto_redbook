from __future__ import annotations

from copy import deepcopy
from typing import Any

from psycopg.types.json import Jsonb

from src.knowledge.store import KnowledgeStore


class ConversationConflict(RuntimeError):
    """Raised when another process changed a conversation since it was read."""


class PostgresConversationStore:
    """PostgreSQL-backed conversation state with append-only normalized messages."""

    def __init__(self, knowledge_store: KnowledgeStore | None = None):
        self.knowledge_store = knowledge_store or KnowledgeStore.from_env()

    def get(self, conversation_id: str) -> dict[str, Any]:
        with self.knowledge_store.connection() as conn:
            row = conn.execute(
                "SELECT payload,revision,last_message_seq FROM agent.conversations WHERE conversation_id=%s",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            messages = conn.execute(
                "SELECT content FROM agent.messages WHERE conversation_id=%s ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        conversation = deepcopy(row["payload"] or {})
        conversation["id"] = conversation_id
        conversation["messages"] = [deepcopy(item["content"]) for item in messages]
        conversation["_revision"] = int(row["revision"])
        conversation["_last_message_seq"] = int(row["last_message_seq"])
        conversation.setdefault("plans", [])
        conversation.setdefault("runs", [])
        return conversation

    def context_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.knowledge_store.connection() as conn:
            rows = conn.execute(
                "SELECT seq,content FROM agent.messages WHERE conversation_id=%s ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        return [{"seq": int(row["seq"]), **dict(row["content"])} for row in rows]

    def active_snapshot(self, conversation_id: str) -> dict[str, Any] | None:
        with self.knowledge_store.connection() as conn:
            row = conn.execute(
                """SELECT s.version,s.through_seq,s.summary,s.constraints,s.evidence_refs,s.task_state,
                          s.input_tokens,s.output_tokens,s.status,s.created_at
                   FROM agent.conversations c
                   JOIN agent.compaction_snapshots s
                     ON s.conversation_id=c.conversation_id AND s.version=c.active_snapshot_version
                   WHERE c.conversation_id=%s""",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def save_snapshot(self, conversation_id: str, *, expected_revision: int, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self.knowledge_store.connection() as conn, conn.transaction():
            row = conn.execute(
                """SELECT active_snapshot_version,revision FROM agent.conversations
                   WHERE conversation_id=%s AND account_namespace='local' FOR UPDATE""",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            if int(row["revision"]) != int(expected_revision):
                raise ConversationConflict("conversation changed while compacting; reload before retrying")
            version = int(row["active_snapshot_version"]) + 1
            conn.execute(
                """INSERT INTO agent.compaction_snapshots
                   (conversation_id,version,through_seq,summary,constraints,evidence_refs,task_state,
                    input_tokens,output_tokens,status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')""",
                (conversation_id, version, int(snapshot["through_seq"]), str(snapshot["summary"]),
                 Jsonb(snapshot.get("constraints") or []), Jsonb(snapshot.get("evidence_refs") or []),
                 Jsonb(snapshot.get("task_state") or {}), int(snapshot["input_tokens"]),
                 int(snapshot["output_tokens"])),
            )
            conn.execute(
                """UPDATE agent.compaction_snapshots SET status='superseded'
                   WHERE conversation_id=%s AND version<>%s AND status='active'""",
                (conversation_id, version),
            )
            conn.execute(
                """UPDATE agent.conversations
                   SET active_snapshot_version=%s,revision=revision+1,updated_at=now()
                   WHERE conversation_id=%s AND revision=%s""",
                (version, conversation_id, expected_revision),
            )
        return self.active_snapshot(conversation_id) or {}

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.knowledge_store.connection() as conn:
            rows = conn.execute(
                """SELECT c.conversation_id,c.title,c.status,c.payload,c.updated_at,c.revision,
                          c.last_message_seq,
                          (SELECT count(*) FROM agent.messages m WHERE m.conversation_id=c.conversation_id) AS message_count
                   FROM agent.conversations c
                   WHERE c.account_namespace='local'
                   ORDER BY c.updated_at DESC LIMIT %s""",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        result = []
        for row in rows:
            payload = row["payload"] or {}
            plans = payload.get("plans") or []
            result.append({
                "id": row["conversation_id"],
                "title": row["title"] or "新对话",
                "created_at": payload.get("created_at"),
                "updated_at": row["updated_at"].timestamp(),
                "status": row["status"],
                "message_count": int(row["message_count"]),
                "latest_plan_id": plans[-1].get("id", "") if plans else "",
                "_revision": int(row["revision"]),
            })
        return result

    def save(self, conversation: dict[str, Any]) -> dict[str, Any]:
        value = deepcopy(conversation)
        conversation_id = str(value["id"])
        expected_revision = int(value.pop("_revision", 0))
        last_message_seq = int(value.pop("_last_message_seq", 0))
        messages = list(value.pop("messages", []) or [])
        title = str(value.get("title") or "新对话")[:120]
        status = str(value.get("status") or "idle")[:40]
        created_at = float(value.get("created_at") or 0)
        updated_at = float(value.get("updated_at") or 0)

        with self.knowledge_store.connection() as conn, conn.transaction():
            if expected_revision == 0:
                row = conn.execute(
                    """INSERT INTO agent.conversations
                       (conversation_id,account_namespace,title,status,payload,revision,created_at,updated_at,last_message_seq)
                       VALUES (%s,'local',%s,%s,%s,1,to_timestamp(%s),to_timestamp(%s),0)
                       ON CONFLICT(conversation_id) DO NOTHING RETURNING revision,last_message_seq""",
                    (conversation_id, title, status, Jsonb(value), created_at or updated_at, updated_at or created_at),
                ).fetchone()
                if row is None:
                    raise ConversationConflict("conversation already exists; reload before saving")
                revision = int(row["revision"])
                last_message_seq = int(row["last_message_seq"])
            else:
                row = conn.execute(
                    """UPDATE agent.conversations
                       SET title=%s,status=%s,payload=%s,revision=revision+1,
                           updated_at=to_timestamp(%s)
                       WHERE conversation_id=%s AND account_namespace='local' AND revision=%s
                       RETURNING revision,last_message_seq""",
                    (title, status, Jsonb(value), updated_at or created_at, conversation_id, expected_revision),
                ).fetchone()
                if row is None:
                    raise ConversationConflict("conversation changed in another process; reload before saving")
                revision = int(row["revision"])
                last_message_seq = int(row["last_message_seq"])

            known_ids = {
                row["message_id"] for row in conn.execute(
                    "SELECT message_id FROM agent.messages WHERE conversation_id=%s", (conversation_id,)
                ).fetchall()
            }
            for message in messages:
                message_id = str(message.get("id") or "")
                if not message_id or message_id in known_ids:
                    continue
                last_message_seq += 1
                role = str(message.get("role") or "assistant")
                if role not in {"system", "user", "assistant", "tool"}:
                    role = "assistant"
                conn.execute(
                    """INSERT INTO agent.messages(conversation_id,seq,message_id,role,content,tool_call_id,created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,to_timestamp(%s))""",
                    (conversation_id, last_message_seq, message_id, role, Jsonb(message),
                     message.get("tool_call_id"), float(message.get("created_at") or updated_at or created_at)),
                )
                known_ids.add(message_id)
            conn.execute(
                "UPDATE agent.conversations SET last_message_seq=%s WHERE conversation_id=%s",
                (last_message_seq, conversation_id),
            )

        saved = self.get(conversation_id)
        return saved

    def import_legacy(self, conversation: dict[str, Any]) -> dict[str, Any]:
        """Import an old JSON conversation once; the source file remains untouched."""
        candidate = deepcopy(conversation)
        candidate["_revision"] = 0
        try:
            return self.save(candidate)
        except ConversationConflict:
            return self.get(str(candidate["id"]))
