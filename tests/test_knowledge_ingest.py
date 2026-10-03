from __future__ import annotations

from pathlib import Path

from src.knowledge.ingest import ingest_posts
from src.knowledge.store import KnowledgeStore
from src.storage.models import Post
from src.storage.files import save_post


def test_ingest_posts_preserves_private_and_failed_purpose(tmp_path: Path):
    data_root = tmp_path / "data"
    private = Post(title="私密测试", body="测试正文", status="saved_as_draft", platform={"publish": {"visibility": "private"}})
    failed = Post(title="失败稿", body="失败正文", status="failed")
    save_post(private, base=data_root)
    save_post(failed, base=data_root)

    store = KnowledgeStore.from_env()
    store._memory = True
    report = ingest_posts(store, data_root=data_root)

    assert report["documents"] == 2
    private_hit = store.get("post-" + private.id)
    failed_hit = store.get("post-" + failed.id)
    assert "performance" not in private_hit["allowed_purposes"]
    assert "evidence" not in failed_hit["allowed_purposes"]
