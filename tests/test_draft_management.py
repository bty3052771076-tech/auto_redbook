from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.publish.draft_management import (
    DraftAuthorization,
    DraftImage,
    DraftManagementStore,
    DraftReviewPolicy,
    PlatformDraftSnapshot,
    build_action_plan,
    build_platform_snapshot,
    inspection_completeness,
    idempotency_key,
    rank_reviews,
    review_snapshot,
)


def _snapshot(**overrides) -> PlatformDraftSnapshot:
    values = {
        "snapshot_id": "snap-1",
        "platform_draft_id": "platform-1",
        "title": "每日AI|模型正式发布",
        "body": "厂商今天发布新模型，公布了能力、开放范围和发布时间。",
        "saved_at": "2026-09-18T09:00:00+08:00",
        "images": (DraftImage(source="cover.png", sha256="abc"),),
        "read_status": "complete",
        "scan_complete": True,
    }
    values.update(overrides)
    return PlatformDraftSnapshot(**values)


def test_review_rejects_incomplete_markup_and_missing_image():
    review = review_snapshot(
        _snapshot(
            body='<p id="x">披露AI产品变化</p>',
            images=(),
            read_status="partial",
        ),
        policy=DraftReviewPolicy(require_images=True),
    )

    assert review.decision == "needs_review"
    assert "incomplete_snapshot" in review.issues
    assert "body_contains_markup" in review.issues
    assert "body_is_vague" in review.issues
    assert "missing_images" in review.issues


def test_review_rejects_stale_saved_draft_when_policy_has_age_limit():
    now = datetime(2026, 9, 18, 12, tzinfo=timezone(timedelta(hours=8)))
    review = review_snapshot(
        _snapshot(saved_at="2026-09-10T09:00:00+08:00"),
        now=now,
        policy=DraftReviewPolicy(max_age_days=2),
    )

    assert review.decision == "excluded"
    assert "stale_saved_draft" in review.issues


def test_rank_and_action_plan_respect_limit_and_authorization():
    reviews = [
        review_snapshot(_snapshot(snapshot_id="one", title="热点一"), policy=DraftReviewPolicy()),
        review_snapshot(_snapshot(snapshot_id="two", title="热点二"), policy=DraftReviewPolicy()),
    ]
    ranked = rank_reviews(reviews, limit=1)
    auth = DraftAuthorization(
        account_id="xhs-account",
        allowed_actions=("publish",),
        max_items=1,
        expires_at="2099-09-18T23:59:59+08:00",
    )

    plan = build_action_plan(ranked, action="publish", authorization=auth)

    assert [item.snapshot_id for item in plan.items] == ["one"]
    assert plan.action == "publish"
    assert plan.authorization_valid is True


def test_action_plan_rejects_action_outside_authorization():
    review = review_snapshot(_snapshot(), policy=DraftReviewPolicy())
    auth = DraftAuthorization(
        account_id="xhs-account",
        allowed_actions=("review",),
        max_items=1,
        expires_at="2026-09-18T23:59:59+08:00",
    )

    plan = build_action_plan([review], action="publish", authorization=auth)

    assert plan.authorization_valid is False
    assert plan.errors == ("action_not_authorized",)
    assert plan.items == ()


def test_fingerprint_and_idempotency_change_when_content_changes():
    original = _snapshot()
    changed = _snapshot(body="同一事件出现了新的官方进展。")

    assert original.content_fingerprint != changed.content_fingerprint
    assert idempotency_key(original, "publish") != idempotency_key(changed, "publish")


def test_store_persists_snapshots_reviews_and_checkpoint(tmp_path: Path):
    store = DraftManagementStore(tmp_path / "draft_management" / "run-1")
    snapshot = _snapshot()
    review = review_snapshot(snapshot, policy=DraftReviewPolicy())

    store.save_snapshot(snapshot)
    store.save_review(review)
    store.save_checkpoint({"status": "reviewed", "snapshot_ids": [snapshot.snapshot_id]})

    assert store.load_snapshot(snapshot.snapshot_id).content_fingerprint == snapshot.content_fingerprint
    assert store.load_reviews()[0].snapshot_id == snapshot.snapshot_id
    assert store.load_checkpoint()["status"] == "reviewed"


def test_build_platform_snapshot_keeps_raw_time_and_marks_partial_reads():
    snapshot = build_platform_snapshot(
        item={"index": "4", "title": "列表标题", "saved_at": "刚刚", "draft_type": "image"},
        editor={"actual_title": "编辑标题", "actual_body": "编辑正文"},
        image_sources=["https://cdn.example/cover.png"],
        snapshot_id="snap-4",
    )

    assert snapshot.snapshot_id == "snap-4"
    assert snapshot.title == "编辑标题"
    assert snapshot.body == "编辑正文"
    assert snapshot.saved_at_raw == "刚刚"
    assert snapshot.images[0].source.endswith("cover.png")
    assert snapshot.read_status == "partial"
    assert "saved_time_unknown" in snapshot.errors


def test_build_platform_snapshot_parses_relative_creator_center_time():
    snapshot = build_platform_snapshot(
        item={"index": "1", "title": "列表标题", "saved_at": "今天 09:30", "draft_type": "image"},
        editor={"actual_title": "编辑标题", "actual_body": "编辑正文"},
        image_sources=["cover.png"],
        snapshot_id="snap-relative",
        captured_at="2026-09-18T12:00:00+08:00",
    )

    assert snapshot.read_status == "complete"
    assert snapshot.saved_at == "2026-09-18T09:30:00+08:00"
    assert snapshot.captured_at == "2026-09-18T12:00:00+08:00"


def test_review_blocks_ambiguous_platform_identity_from_publish():
    snapshot = _snapshot(identity_confidence="ambiguous")

    review = review_snapshot(snapshot, policy=DraftReviewPolicy())

    assert review.decision == "needs_review"
    assert "identity_ambiguous" in review.issues


def test_inspection_completeness_distinguishes_limited_detail_scan():
    assert inspection_completeness(total=65, inspected=5, requested_limit=5, errors=[]) == {
        "enumeration_complete": True,
        "inspection_complete": False,
        "complete": False,
        "stop_reason": "detail_limit",
    }
    assert inspection_completeness(total=2, inspected=2, requested_limit=5, errors=[]) == {
        "enumeration_complete": True,
        "inspection_complete": True,
        "complete": True,
        "stop_reason": "end_of_list",
    }
