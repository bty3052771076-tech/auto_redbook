from pathlib import Path
from tempfile import TemporaryDirectory

import json

from src.storage.files import (
    copy_assets_into_post,
    ensure_dirs,
    load_post,
    save_execution,
    save_post,
    save_revision,
)
from src.storage.models import Execution, Post, PostStatus, Revision


def test_save_and_load_post_roundtrip():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        ensure_dirs(base)
        post = Post(title="t", body="b")
        save_post(post, base=base)
        loaded = load_post(post.id, base=base)
        assert loaded.title == "t"
        assert loaded.body == "b"
        assert loaded.uploaded is False
        assert loaded.uploaded_at is None


def test_load_legacy_saved_draft_marks_uploaded():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        ensure_dirs(base)
        post_id = "legacy001"
        path = base / "posts" / post_id / "post.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "id": post_id,
                    "type": "image",
                    "status": PostStatus.saved_draft.value,
                    "title": "t",
                    "body": "b",
                    "updated_at": "2026-02-01T00:00:00.000000Z",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        loaded = load_post(post_id, base=base)
        assert loaded.uploaded is True
        assert loaded.uploaded_at == "2026-02-01T00:00:00.000000Z"


def test_copy_assets_and_execution():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        ensure_dirs(base)
        post = Post(title="t", body="b")
        save_post(post, base=base)

        # fake asset
        src = base / "tmp.txt"
        src.write_text("hello", encoding="utf-8")
        copied = copy_assets_into_post(post.id, [src], base=base)
        assert copied and copied[0].exists()

        rev = Revision(post_id=post.id, content={"title": "t"})
        save_revision(rev, base=base)

        exec_rec = Execution(post_id=post.id, result="success")
        save_execution(exec_rec, base=base)
        exec_path = base / "posts" / post.id / "executions" / f"{exec_rec.id}.json"
        assert exec_path.exists()
