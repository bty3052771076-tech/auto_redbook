from __future__ import annotations

from pathlib import Path

from src.publish.draft_delivery import (
    content_revision_fingerprint,
    has_current_draft_receipt,
    has_current_delivery_receipt,
)
from src.publish.playwright_steps import (
    _capture_publication_failure_evidence,
    _classify_write_failure,
)
from src.storage.models import AssetInfo, Post


def test_content_revision_fingerprint_ignores_post_id_and_timestamps(tmp_path: Path):
    image = tmp_path / "cover.png"
    image.write_bytes(b"stable image bytes")
    first = Post(
        id="first",
        title="Same title",
        body="Same body",
        topics=["topic"],
        assets=[AssetInfo(path=str(image), kind="image")],
    )
    second = Post(
        id="second",
        title="Same title",
        body="Same body",
        topics=["topic"],
        assets=[AssetInfo(path=str(image), kind="image")],
    )

    assert content_revision_fingerprint(first) == content_revision_fingerprint(second)


def test_current_draft_receipt_is_false_for_missing_or_changed_revision(tmp_path: Path):
    image = tmp_path / "cover.png"
    image.write_bytes(b"image")
    post = Post(
        title="Title",
        body="Body",
        assets=[AssetInfo(path=str(image), kind="image")],
    )

    assert not has_current_draft_receipt(post, platform="xhs")
    fingerprint = content_revision_fingerprint(post)
    post.platform["xhs_draft"] = {"revision_fingerprint": fingerprint}
    assert has_current_draft_receipt(post, platform="xhs")

    post.body = "Changed body"
    assert not has_current_draft_receipt(post, platform="xhs")


def test_publish_delivery_does_not_treat_saved_draft_as_published():
    post = Post(title="Title", body="Body")
    post.platform["xhs_draft"] = {"revision_fingerprint": content_revision_fingerprint(post)}

    assert has_current_delivery_receipt(post, platform="xhs", delivery="save_draft")
    assert not has_current_delivery_receipt(post, platform="xhs", delivery="publish")


def test_publish_delivery_requires_matching_publication_revision():
    post = Post(title="Title", body="Body")
    post.platform["xhs_publication"] = {
        "revision_fingerprint": content_revision_fingerprint(post),
        "visibility": "public",
    }

    assert has_current_delivery_receipt(post, platform="xhs", delivery="publish")


def test_write_failure_after_click_is_classified_as_uncertain():
    message = _classify_write_failure(
        "draft save verification failed",
        submitted=True,
        operation="draft_save",
    )

    assert message.startswith("XHS_WRITE_UNCERTAIN:")
    assert "draft_save" in message


def test_failure_before_click_remains_a_definite_automation_error():
    message = _classify_write_failure(
        "publish button not found",
        submitted=False,
        operation="publish",
    )

    assert message == "publish button not found"


def test_publication_failure_evidence_is_written_under_post_evidence(tmp_path, monkeypatch):
    class FakePage:
        def screenshot(self, *, path, full_page):
            Path(path).write_bytes(b"png")

        def content(self):
            return "<html>platform state</html>"

    monkeypatch.setattr(
        "src.publish.playwright_steps.evidence_dir",
        lambda post_id, execution_id: tmp_path / post_id / execution_id,
    )

    evidence = _capture_publication_failure_evidence(
        FakePage(), post_id="post-1", operation="publish"
    )

    evidence_dir = Path(evidence)
    assert evidence_dir.parent.name == "post-1"
    assert (evidence_dir / "publish_failure.png").read_bytes() == b"png"
    assert (evidence_dir / "publish_failure.html").read_text(encoding="utf-8") == (
        "<html>platform state</html>"
    )
