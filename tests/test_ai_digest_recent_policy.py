from __future__ import annotations

from src.workflow import create_post


def test_agent_ai_digest_policy_is_strict_two_beijing_days(monkeypatch):
    monkeypatch.setenv("AI_DIGEST_STRICT_RECENT", "1")

    windows, meta = create_post._ai_digest_lookback_windows(None)

    assert windows == [2]
    assert meta["mode"] == "strict_two_day"


def test_non_agent_ai_digest_policy_keeps_legacy_configurable_windows(monkeypatch):
    monkeypatch.delenv("AI_DIGEST_STRICT_RECENT", raising=False)
    monkeypatch.delenv("AI_DIGEST_LOOKBACK_DAYS", raising=False)
    monkeypatch.delenv("AI_DIGEST_MAX_AGE_DAYS", raising=False)
    monkeypatch.delenv("CONTENT_LOOKBACK_DAYS", raising=False)

    windows, meta = create_post._ai_digest_lookback_windows(None)

    assert meta["mode"] == "auto_expand"
    assert windows == list(create_post.DEFAULT_CANDIDATE_LOOKBACK_WINDOWS)
