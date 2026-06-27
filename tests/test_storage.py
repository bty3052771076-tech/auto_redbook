from pathlib import Path
from tempfile import TemporaryDirectory

import json

from src.storage.files import (
    append_run_record,
    copy_assets_into_post,
    ensure_dirs,
    load_post,
    list_published_metrics,
    list_run_records,
    save_published_metrics_snapshot,
    save_execution,
    save_post,
    save_revision,
)
from src.storage.models import Execution, Post, PostStatus, PublishedMetric, Revision, RunRecord


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


def test_save_published_metrics_snapshot_writes_jsonl_and_csv():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        metric = PublishedMetric(
            title="测试已发布笔记",
            url="https://www.xiaohongshu.com/explore/abc",
            likes=12,
            comments=3,
            favorites=4,
            raw={"source": "unit"},
        )

        result = save_published_metrics_snapshot([metric], base=base)

        assert result["count"] == 1
        assert (base / "analytics" / "published_metrics.jsonl").exists()
        csv_text = (base / "analytics" / "published_metrics.csv").read_text(encoding="utf-8-sig")
        assert "测试已发布笔记" in csv_text
        assert "likes" in csv_text
        loaded = list_published_metrics(base=base)
        assert len(loaded) == 1
        assert loaded[0].likes == 12
        assert loaded[0].favorites == 4


def test_save_published_metrics_snapshot_updates_latest_csv_without_duplicates():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        first = PublishedMetric(
            title="同一笔记",
            published_at="2026-06-27",
            likes=1,
            comments=0,
            favorites=0,
        )
        second = PublishedMetric(
            title="同一笔记",
            published_at="2026-06-27",
            likes=5,
            comments=2,
            favorites=1,
        )

        save_published_metrics_snapshot([first], base=base)
        result = save_published_metrics_snapshot([second], base=base)

        latest_text = result["latest_csv"].read_text(encoding="utf-8-sig")
        assert latest_text.count("同一笔记") == 1
        assert ",5,2,1," in latest_text


def test_append_run_record_writes_table_and_jsonl():
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        record = RunRecord(
            command="auto",
            title="每日新闻",
            requested_count=3,
            generated_count=2,
            uploaded_count=1,
            failed_count=2,
            llm_provider="aliyun",
            llm_models="qwen3.7-plus",
            image_provider="aliyun",
            image_models="wan2.7-image",
            news_provider="gnews",
            post_ids=["p1", "p2"],
            errors=["quota exhausted"],
        )

        paths = append_run_record(record, base=base)

        assert paths["jsonl"].exists()
        assert paths["csv"].exists()
        csv_text = paths["csv"].read_text(encoding="utf-8-sig")
        assert "qwen3.7-plus" in csv_text
        assert "wan2.7-image" in csv_text
        loaded = list_run_records(base=base)
        assert len(loaded) == 1
        assert loaded[0].generated_count == 2
        assert loaded[0].post_ids == ["p1", "p2"]
