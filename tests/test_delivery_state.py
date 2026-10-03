from __future__ import annotations

from src.publish.delivery_state import (
    DeliveryStateError,
    DeliveryStateStore,
    terminal_action_block_reason,
)


def test_prepare_action_is_idempotent_and_unknown_requires_reconcile():
    store = DeliveryStateStore.in_memory()
    request = {
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "post-1",
        "content_version": "v1",
        "action": "publish",
        "visibility": "public",
    }

    first = store.prepare_action(request)
    second = store.prepare_action(request)

    assert first.action_id == second.action_id
    assert first.status == "prepared"
    assert second.status == "prepared"
    store.mark_submitting(first.action_id, expected_version=first.version)
    resumed = store.get_resume_decision(first.action_id)
    assert resumed.status == "uncertain"
    assert resumed.next_action == "reconcile"


def test_record_observation_confirms_publication_without_allowing_resubmit():
    store = DeliveryStateStore.in_memory()
    action = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "post-2",
        "content_version": "v2",
        "action": "publish",
        "visibility": "public",
    })
    store.mark_submitting(action.action_id, expected_version=action.version)

    confirmed = store.record_observation(action.action_id, {
        "platform_id": "note-2",
        "title": "明确标题",
        "body": "已读回正文",
        "stage": "published",
        "observed_visibility": "public",
        "evidence_level": "detail",
        "evidence_ref": "data/runs/platform/obs.json",
    })

    assert confirmed.status == "published"
    assert confirmed.next_action == "none"
    again = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "post-2",
        "content_version": "v2",
        "action": "publish",
        "visibility": "public",
    })
    assert again.status == "published"
    assert again.next_action == "none"


def test_platform_restriction_is_terminal_and_cannot_be_resubmitted():
    store = DeliveryStateStore.in_memory()
    action = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "restricted-post",
        "content_version": "v1",
        "action": "publish",
        "visibility": "public",
    })
    submitting = store.mark_submitting(action.action_id, expected_version=action.version)

    restricted = store.record_observation(action.action_id, {
        "platform_id": "note-restricted",
        "stage": "platform_restricted",
        "error": "疑似使用第三方工具",
        "observed_visibility": "private",
        "evidence_level": "detail",
    })

    assert restricted.status == "platform_restricted"
    assert restricted.next_action == "platform_review"
    assert store.mark_submitting(
        action.action_id,
        expected_version=restricted.version,
    ) == restricted
    assert terminal_action_block_reason(restricted, stage="publish").startswith(
        "XHS_PLATFORM_RESTRICTED:"
    )


def test_pending_review_action_blocks_browser_write():
    store = DeliveryStateStore.in_memory()
    action = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "reviewing-post",
        "content_version": "v1",
        "action": "publish",
        "visibility": "public",
    })
    submitting = store.mark_submitting(action.action_id, expected_version=action.version)
    pending = store.record_observation(submitting.action_id, {
        "platform_id": "note-reviewing",
        "stage": "pending_review",
        "observed_visibility": "public",
        "evidence_level": "detail",
    })

    assert terminal_action_block_reason(pending, stage="publish") == (
        "XHS_PENDING_REVIEW: 平台仍在审核，禁止再次提交"
    )


def test_saved_draft_observation_is_a_confirmed_draft_stage():
    store = DeliveryStateStore.in_memory()
    action = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "draft-1",
        "content_version": "v1",
        "action": "save_draft",
        "visibility": "unknown",
    })
    store.mark_submitting(action.action_id, expected_version=action.version)

    confirmed = store.record_observation(action.action_id, {
        "platform_id": "draft-1-platform",
        "stage": "saved_draft",
        "evidence_level": "detail",
    })

    assert confirmed.status == "saved_draft"
    assert confirmed.next_action == "none"


def test_version_conflict_is_fail_closed():
    store = DeliveryStateStore.in_memory()
    action = store.prepare_action({
        "account_id": "xhs-account",
        "profile_key": "profile-a",
        "post_id": "post-3",
        "content_version": "v3",
        "action": "save_draft",
        "visibility": "private",
    })

    try:
        store.mark_submitting(action.action_id, expected_version=99)
    except DeliveryStateError as exc:
        assert exc.code == "DELIVERY_STATE_VERSION_CONFLICT"
    else:
        raise AssertionError("expected optimistic-lock conflict")
