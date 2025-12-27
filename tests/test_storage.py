from pathlib import Path
from tempfile import TemporaryDirectory

from src.storage.files import (
    copy_assets_into_post,
    ensure_dirs,
    load_post,
    save_execution,
    save_post,
    save_revision,
)
from src.storage.models import Execution, Post, Revision


def test_save_and_load_post_roundtrip():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        ensure_dirs(base)
        post = Post(title="t", body="b")
        save_post(post, base=base)
        loaded = load_post(post.id, base=base)
        assert loaded.title == "t"
        assert loaded.body == "b"


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
