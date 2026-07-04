from apps.cli import (
    _format_progress_event,
    _format_stage_error,
    _headless_option_value,
    _headless_requested,
    _stage_from_create_exception,
)


def test_headless_option_value_preserves_env_fallback_when_flag_is_absent():
    assert _headless_option_value(False) is None


def test_headless_option_value_for_explicit_flag():
    assert _headless_option_value(True) is True


def test_headless_requested_accepts_env(monkeypatch):
    monkeypatch.setenv("XHS_HEADLESS", "1")

    assert _headless_requested(False) is True


def test_headless_requested_ignores_disabled_env(monkeypatch):
    monkeypatch.setenv("XHS_HEADLESS", "0")

    assert _headless_requested(False) is False


def test_format_stage_error_labels_news_failure():
    message = _format_stage_error("获取新闻", RuntimeError("HTTP Error 429: Too Many Requests"))

    assert message == "error: stage=获取新闻 | HTTP Error 429: Too Many Requests"


def test_format_stage_error_labels_upload_failure():
    message = _format_stage_error("上传", "draft save verification failed")

    assert message == "error: stage=上传 | draft save verification failed"


def test_stage_from_create_exception_labels_news_failure():
    stage = _stage_from_create_exception(RuntimeError("GNews api_key missing"))

    assert stage == "\u83b7\u53d6\u65b0\u95fb"


def test_stage_from_create_exception_labels_llm_failure():
    stage = _stage_from_create_exception(RuntimeError("LLM api_key missing"))

    assert stage == "LLM"


def test_stage_from_create_exception_labels_vlm_failure_before_generic_api_key():
    stage = _stage_from_create_exception(RuntimeError("Aliyun image api_key missing"))

    assert stage == "VLM\u751f\u56fe"


def test_format_progress_event_labels_current_step():
    message = _format_progress_event("auto", "生成草稿", "in_progress", "count=3")

    assert message == "[auto] stage=生成草稿 | in_progress | count=3"
