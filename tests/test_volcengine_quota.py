from __future__ import annotations

from src.volcengine.quota import (
    format_volcengine_quota_records,
    parse_volcengine_quota_text,
    volcengine_quota_model_candidates,
)


def test_parse_volcengine_quota_text_extracts_llm_and_image_values():
    text = """
    模型名称 免费推理额度 已使用 剩余 到期时间
    doubao-seed-2-1-turbo-260628 token 500000 12000 488000 2026-08-01
    doubao-seedream-5-0-lite-260128 张 100 3 97 2026-08-01
    """

    records = parse_volcengine_quota_text(
        text,
        ["doubao-seed-2-1-turbo-260628", "doubao-seedream-5-0-lite-260128"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["doubao-seed-2-1-turbo-260628"].kind == "llm"
    assert by_model["doubao-seed-2-1-turbo-260628"].total == 500000
    assert by_model["doubao-seed-2-1-turbo-260628"].used == 12000
    assert by_model["doubao-seed-2-1-turbo-260628"].remaining == 488000
    assert by_model["doubao-seed-2-1-turbo-260628"].unit.lower() == "token"
    assert by_model["doubao-seed-2-1-turbo-260628"].expires_at == "2026-08-01"
    assert by_model["doubao-seedream-5-0-lite-260128"].kind == "image"
    assert by_model["doubao-seedream-5-0-lite-260128"].remaining == 97
    assert by_model["doubao-seedream-5-0-lite-260128"].unit == "张"


def test_volcengine_quota_model_candidates_merge_defaults_and_env(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_LLM_MODELS", "custom-llm,doubao-seed-2-1-turbo-260628")
    monkeypatch.setenv("VOLCENGINE_IMAGE_MODELS", "custom-image,doubao-seedream-5-0-lite-260128")

    candidates = volcengine_quota_model_candidates()

    assert candidates[:4] == [
        "custom-llm",
        "doubao-seed-2-1-turbo-260628",
        "custom-image",
        "doubao-seedream-5-0-lite-260128",
    ]


def test_format_volcengine_quota_records_marks_unknown_remaining_values():
    records = parse_volcengine_quota_text(
        "doubao-seed-2-1-turbo-260628 控制台页面未展开",
        ["doubao-seed-2-1-turbo-260628"],
    )

    output = format_volcengine_quota_records(records)

    assert "doubao-seed-2-1-turbo-260628" in output
    assert "unknown" in output
    assert "official Volcengine Ark console" in output
