from copy import deepcopy

from src.agent.compaction import compact_conversation, compacted_context, estimate_tokens


class FakeStore:
    def __init__(self, messages, revision=1, active=None):
        self.messages = deepcopy(messages)
        self.revision = revision
        self.snapshot = active

    def get(self, _conversation_id):
        return {"_revision": self.revision}

    def context_messages(self, _conversation_id):
        return deepcopy(self.messages)

    def active_snapshot(self, _conversation_id):
        return deepcopy(self.snapshot)

    def save_snapshot(self, _conversation_id, *, expected_revision, snapshot):
        if expected_revision != self.revision:
            raise RuntimeError("conversation changed while compacting")
        self.revision += 1
        self.snapshot = {**deepcopy(snapshot), "version": 1}
        return deepcopy(self.snapshot)


def long_messages(count=24):
    return [
        {"seq": index, "id": str(index), "role": "user" if index % 2 else "assistant",
         "content": f"消息{index}：保留用户约束和任务进度。" * 8}
        for index in range(1, count + 1)
    ]


def test_compaction_triggers_only_over_threshold_and_preserves_raw_history():
    store = FakeStore(long_messages())
    calls = []
    result = compact_conversation(
        store, "conversation", summarize=lambda value: calls.append(value) or {"summary": "用户要求保留来源。", "constraints": ["不发布未经确认内容"]},
        soft_limit_tokens=20, keep_recent_messages=6,
    )
    assert result["status"] == "compacted"
    assert result["messages_preserved"] == 24
    assert len(store.messages) == 24
    assert len(calls) == 1
    context = compacted_context(store, "conversation", recent_messages=6)
    assert context["snapshot"]["summary"] == "用户要求保留来源。"
    assert len(context["recent_messages"]) == 6


def test_compaction_does_not_call_summarizer_under_threshold():
    store = FakeStore(long_messages(2))
    result = compact_conversation(store, "conversation", summarize=lambda _: (_ for _ in ()).throw(AssertionError()), soft_limit_tokens=10000)
    assert result["status"] == "not_needed"
    assert store.snapshot is None


def test_compaction_filters_unapproved_evidence_and_keeps_prior_constraints():
    prior = {"through_seq": 2, "summary": "旧摘要", "constraints": ["必须使用中文"], "evidence_refs": ["doc-1"]}
    store = FakeStore(long_messages(), active=prior)
    result = compact_conversation(
        store, "conversation", summarize=lambda _: {
            "summary": "新摘要", "constraints": ["必须使用中文", "不得公开发布"],
            "evidence_refs": ["doc-1", "made-up"],
        }, soft_limit_tokens=20, keep_recent_messages=6, allowed_evidence_refs={"doc-1", "doc-2"},
    )
    assert result["status"] == "compacted"
    assert store.snapshot["constraints"] == ["必须使用中文", "不得公开发布"]
    assert store.snapshot["evidence_refs"] == ["doc-1"]


def test_compaction_retries_invalid_summary_at_most_once():
    store = FakeStore(long_messages())
    calls = []

    def summarize(_):
        calls.append(1)
        return {} if len(calls) == 1 else {"summary": "有效摘要", "constraints": []}

    result = compact_conversation(store, "conversation", summarize=summarize, soft_limit_tokens=20, keep_recent_messages=6)
    assert len(calls) == 2
    assert result["status"] == "compacted"


def test_token_estimator_handles_cjk_and_json():
    assert estimate_tokens("中文 A token") >= 3
