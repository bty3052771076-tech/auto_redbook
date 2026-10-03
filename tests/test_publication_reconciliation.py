from __future__ import annotations

from src.publish.reconcile import classify_publication_observation


def test_missing_visibility_is_unknown_not_failed():
    result = classify_publication_observation({
        "platform_id": "note-1",
        "title": "同名新闻",
        "body": "完整正文",
        "image_count": 2,
    }, requested_visibility="public")

    assert result.status == "uncertain"
    assert result.next_action == "manual_review"
    assert "visibility_not_confirmed" in result.reasons


def test_detail_evidence_can_confirm_publication():
    result = classify_publication_observation({
        "platform_id": "note-2",
        "title": "明确标题",
        "body": "完整正文",
        "image_count": 3,
        "observed_visibility": "public",
        "stage": "published",
        "evidence_level": "detail",
    }, requested_visibility="public")

    assert result.status == "published"
    assert result.next_action == "none"
    assert result.image_count == 3


def test_pending_review_is_not_publication_success():
    result = classify_publication_observation({
        "platform_id": "note-3",
        "observed_visibility": "public",
        "stage": "pending_review",
        "evidence_level": "detail",
    }, requested_visibility="public")

    assert result.status == "pending_review"
    assert result.next_action == "wait_or_reconcile"


def test_platform_moderation_restriction_is_not_a_retryable_failure():
    result = classify_publication_observation({
        "platform_id": "note-restricted",
        "stage": "platform_restricted",
        "error": "笔记存在利用AI托管进行发文/互动的内容",
        "observed_visibility": "private",
        "evidence_level": "detail",
    }, requested_visibility="public")

    assert result.status == "platform_restricted"
    assert result.next_action == "platform_review"
    assert "platform_restricted" in result.reasons
