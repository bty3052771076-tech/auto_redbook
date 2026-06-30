from __future__ import annotations

from src.aliyun.quota import (
    aliyun_quota_model_candidates,
    format_aliyun_quota_records,
    parse_aliyun_quota_text,
)


def test_parse_aliyun_quota_text_extracts_llm_and_image_remaining_values():
    text = """
    模型名称 免费额度 已用额度 剩余额度 到期时间
    qwen3.7-plus Token 1000000 120000 880000 2026-07-31
    wan2.7-image 张 500 25 475 2026-07-31
    """

    records = parse_aliyun_quota_text(text, ["qwen3.7-plus", "wan2.7-image"])

    by_model = {record.model: record for record in records}
    assert by_model["qwen3.7-plus"].kind == "llm"
    assert by_model["qwen3.7-plus"].total == 1000000
    assert by_model["qwen3.7-plus"].used == 120000
    assert by_model["qwen3.7-plus"].remaining == 880000
    assert by_model["qwen3.7-plus"].unit.lower() == "token"
    assert by_model["qwen3.7-plus"].expires_at == "2026-07-31"
    assert by_model["wan2.7-image"].kind == "image"
    assert by_model["wan2.7-image"].remaining == 475
    assert by_model["wan2.7-image"].unit == "张"


def test_parse_aliyun_quota_text_preserves_raw_row_when_numbers_are_not_parseable():
    text = "qwen3.6-flash 当前页面展示异常，请稍后刷新"

    records = parse_aliyun_quota_text(text, ["qwen3.6-flash"])

    assert len(records) == 1
    assert records[0].model == "qwen3.6-flash"
    assert records[0].remaining is None
    assert "展示异常" in records[0].raw_text


def test_aliyun_quota_model_candidates_merge_defaults_and_env(monkeypatch):
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "custom-llm,qwen3.7-plus custom-llm")
    monkeypatch.setenv("ALIYUN_IMAGE_MODELS", "custom-image,wan2.7-image")

    candidates = aliyun_quota_model_candidates()

    assert candidates[:4] == [
        "custom-llm",
        "qwen3.7-plus",
        "custom-image",
        "wan2.7-image",
    ]


def test_format_aliyun_quota_records_marks_unknown_remaining_values():
    records = parse_aliyun_quota_text("qwen3.7-plus 页面未展开", ["qwen3.7-plus"])

    output = format_aliyun_quota_records(records)

    assert "qwen3.7-plus" in output
    assert "unknown" in output
    assert "open the official Bailian console" in output
