from __future__ import annotations

import numpy as np

from src.knowledge.embeddings import MODEL_DIMENSIONS, chunk_document, index_pending_documents, prepare_chunks
from src.knowledge.models import KnowledgeDocument


class _FakeEmbedder:
    def embed_documents(self, texts):
        return [np.full(MODEL_DIMENSIONS, index / 10, dtype=np.float32).tolist() for index, _ in enumerate(texts)]


def test_chunk_document_preserves_chinese_text_and_overlap():
    body = "模型发布。" * 200
    chunks = chunk_document("测试标题", body, max_tokens=32, overlap=8)

    assert len(chunks) > 1
    assert all(chunk["token_count"] <= 32 for chunk in chunks)
    assert chunks[0]["char_start"] == 0
    assert chunks[0]["content"].startswith("测试标题")
    assert chunks[1]["char_start"] < chunks[0]["char_end"]
    assert "模型发布。" in "".join(chunk["content"] for chunk in chunks)


def test_prepare_chunks_records_content_version_model_input_and_real_vector():
    doc = KnowledgeDocument(
        record_id="post-1",
        record_type="post",
        title="Qwen 发布",
        body="开源模型今天正式发布。",
    ).to_record()
    groups = prepare_chunks([doc], embedder=_FakeEmbedder())

    assert len(groups) == 1
    document, chunks = groups[0]
    assert document["record_id"] == "post-1"
    assert len(chunks[0]["chunk_id"]) == 64
    assert len(chunks[0]["embedding"]) == MODEL_DIMENSIONS
    assert all(value == value for value in chunks[0]["embedding"])


def test_index_pending_documents_reports_bounded_batch_progress():
    class Store:
        def __init__(self):
            self.pending = [
                KnowledgeDocument(record_id=f"post-{index}", record_type="post", title="标题", body="正文").to_record()
                for index in range(3)
            ]
            self.indexed_chunks = 0

        def pending_documents(self, *, limit):
            return list(self.pending[:limit])

        def upsert_chunks(self, record_id, chunks, *, account_namespace):
            self.pending = [item for item in self.pending if item["record_id"] != record_id]
            self.indexed_chunks += len(chunks)
            return len(chunks)

        def index_progress(self):
            return {
                "documents": 3,
                "indexed_documents": 3 - len(self.pending),
                "pending_documents": len(self.pending),
            }

    events = []
    report = index_pending_documents(
        Store(),
        batch_size=2,
        embedder=_FakeEmbedder(),
        progress_callback=events.append,
    )

    assert report["indexed_documents"] == 3
    assert report["indexed_chunks"] == 3
    assert [event["pending_documents"] for event in events] == [1, 0]
