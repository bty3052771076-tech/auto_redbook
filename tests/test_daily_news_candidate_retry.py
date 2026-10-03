from src.workflow.create_post import (
    _DailyNewsCandidateResult,
    _daily_news_llm_unavailable_reason,
    _daily_news_provider_capacity_exhausted,
    _schedule_daily_news_candidate_retry,
)


def test_transient_image_failure_is_requeued_within_retry_limit(monkeypatch):
    monkeypatch.setenv("DAILY_NEWS_CANDIDATE_RETRY_LIMIT", "1")
    result = _DailyNewsCandidateResult(
        candidate_index=4,
        status="failed",
        reason="image_generation_failed",
        error="connection reset by peer",
    )
    pending = []
    attempts = {}

    assert _schedule_daily_news_candidate_retry(result, attempts, pending) is True
    assert pending == [4]
    assert attempts == {4: 1}
    assert _schedule_daily_news_candidate_retry(result, attempts, pending) is False
    assert pending == [4]


def test_permanent_model_failure_is_not_requeued(monkeypatch):
    monkeypatch.setenv("DAILY_NEWS_CANDIDATE_RETRY_LIMIT", "3")
    result = _DailyNewsCandidateResult(
        candidate_index=2,
        status="failed",
        reason="llm_request_failed",
        error="401 invalid api_key",
    )
    pending = []
    attempts = {}

    assert _schedule_daily_news_candidate_retry(result, attempts, pending) is False
    assert pending == []
    assert attempts == {}


def test_provider_token_plan_exhaustion_is_fatal_for_candidate_batch():
    error = "429 rate_limit_error: 已达到 Token Plan 用量上限，请升级 Token Plan 套餐或购买积分补充用量"

    assert _daily_news_provider_capacity_exhausted(error) is True
    assert "Token Plan" in _daily_news_llm_unavailable_reason(error)
    assert _daily_news_provider_capacity_exhausted("connection reset by peer") is False
