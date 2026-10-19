import weakref

from src.storage import files
from src.storage.models import Post
from src.workflow.quality_gate import validate_post_batch


def test_post_iterator_is_lazy_and_legacy_list_api_stays_a_list(tmp_path, monkeypatch):
    files.save_post(Post(id="first", title="First", body="First body"), base=tmp_path)
    files.save_post(Post(id="second", title="Second", body="Second body"), base=tmp_path)
    bad = tmp_path / "posts" / "bad" / "post.json"
    bad.parent.mkdir()
    bad.write_text("not-json", encoding="utf-8")
    read = files._read_json
    opened = []

    def tracked(path):
        opened.append(path)
        return read(path)

    monkeypatch.setattr(files, "_read_json", tracked)
    stream = files.iter_posts(base=tmp_path)
    assert opened == []
    first = next(stream)
    assert len([path for path in opened if path.parent.name != "bad"]) == 1
    assert {first.id, *(post.id for post in stream)} == {"first", "second"}
    legacy = files.list_posts(base=tmp_path)
    assert isinstance(legacy, list)
    assert {post.id for post in legacy} == {"first", "second"}


def test_history_review_does_not_retain_every_full_post_payload():
    target = Post(id="target", title="Satellite reached orbit", body="The satellite reached its planned orbit.")
    refs, peak = [], []

    def history():
        for index in range(20):
            post = Post(id=f"h{index}", title=f"Local school funding {index}",
                        body=f"School funding allocation number {index}.", uploaded=True,
                        platform={"raw_evidence": "x" * 100_000})
            refs.append(weakref.ref(post))
            peak.append(sum(ref() is not None for ref in refs))
            yield post

    report = validate_post_batch([target], expected_count=1, historical_posts=history())
    assert len(peak) == 20
    assert max(peak) <= 2
    assert not any(issue.code == "historical_duplicate" for issue in report.issues)


def test_streaming_history_keeps_first_match_and_batch_issue_order():
    first = Post(id="a", title="Satellite reached orbit", body="The satellite reached its planned orbit.")
    second = Post(id="b", title="School funding approved", body="The city approved new school funding.")
    history = [second.model_copy(update={"id": "b-old", "uploaded": True}),
               first.model_copy(update={"id": "a-old", "uploaded": True}),
               first.model_copy(update={"id": "a-later", "uploaded": True})]
    report = validate_post_batch([first, second], expected_count=2, historical_posts=iter(history))
    issues = [issue for issue in report.issues if issue.code == "historical_duplicate"]
    assert [issue.post_id for issue in issues] == ["a", "b"]
    assert "a-old" in issues[0].message
    assert "b-old" in issues[1].message
