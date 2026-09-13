from __future__ import annotations

from pathlib import Path

from src.publish.draft_delivery import (
    content_revision_fingerprint,
    has_current_draft_receipt,
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
