from src.publish.playwright_steps import UPLOAD_COUNT_PATTERN, _draft_count_poll_iterations


def test_upload_count_pattern_matches_xhs_counter_text():
    match = UPLOAD_COUNT_PATTERN.search("图片编辑 1/18")

    assert match is not None
    assert match.group(1) == "1"


def test_draft_count_poll_is_skipped_when_platform_hides_baseline(monkeypatch):
    monkeypatch.delenv("XHS_DRAFT_COUNT_POLL_S", raising=False)

    assert _draft_count_poll_iterations(None) == 0
    assert _draft_count_poll_iterations(12) == 10


def test_draft_count_poll_budget_is_bounded(monkeypatch):
    monkeypatch.setenv("XHS_DRAFT_COUNT_POLL_S", "999")
    assert _draft_count_poll_iterations(12) == 30

    monkeypatch.setenv("XHS_DRAFT_COUNT_POLL_S", "-4")
    assert _draft_count_poll_iterations(12) == 0
