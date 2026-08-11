from __future__ import annotations

from src.siliconflow.quota import (
    _classify_model,
    _is_free_image_model,
    _parse_visible_model_lines,
    format_siliconflow_quota_records,
    siliconflow_quota_model_candidates,
)


def test_classify_model_detects_llm_and_image_kinds():
    assert _classify_model("deepseek-ai/DeepSeek-V3") == "llm"
    assert _classify_model("Qwen/Qwen3-32B") == "llm"
    assert _classify_model("THUDM/GLM-4-9B-0414") == "llm"
    assert _classify_model("Qwen/Qwen-Image") == "image"
    assert _classify_model("Kwai-Kolors/Kolors") == "image"
    assert _classify_model("stabilityai/stable-diffusion-xl-base-1.0") == "image"
    assert _classify_model("BAAI/bge-m3") == "unsupported"
    assert _classify_model("BAAI/bge-reranker-v2-m3") == "unsupported"
    assert _classify_model("Qwen/Qwen3-Embedding-8B") == "unsupported"


def test_free_image_model_marker_only_marks_free_models():
    assert _is_free_image_model("Kwai-Kolors/Kolors") is True
    assert _is_free_image_model("Qwen/Qwen-Image") is False
    assert _is_free_image_model("Tongyi-MAI/Z-Image-Turbo") is False


def test_siliconflow_quota_model_candidates_merge_defaults_and_env(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_LLM_MODELS", "custom-llm,deepseek-ai/DeepSeek-V3")
    monkeypatch.setenv("SILICONFLOW_IMAGE_MODELS", "custom-image,Qwen/Qwen-Image")

    candidates = siliconflow_quota_model_candidates()

    assert candidates[:4] == [
        "custom-llm",
        "deepseek-ai/DeepSeek-V3",
        "custom-image",
        "Qwen/Qwen-Image",
    ]


def test_parse_visible_model_lines_extracts_free_and_usage_rows():
    text = """
    Qwen/Qwen-Image 免费额度 100 张 剩余 100
    Kwai-Kolors/Kolors 已用 20 剩余 80 总数 100
    deepseek-ai/DeepSeek-V3 免费 1,000,000 tokens
    """

    records = _parse_visible_model_lines(
        text,
        ["Qwen/Qwen-Image", "Kwai-Kolors/Kolors", "deepseek-ai/DeepSeek-V3"],
    )

    by_model = {record.model: record for record in records}
    assert by_model["Qwen/Qwen-Image"].kind == "image"
    assert by_model["Qwen/Qwen-Image"].status == "available"
    assert by_model["Kwai-Kolors/Kolors"].kind == "image"
    assert by_model["Kwai-Kolors/Kolors"].remaining == 80
    assert by_model["Kwai-Kolors/Kolors"].total == 100
    assert by_model["deepseek-ai/DeepSeek-V3"].kind == "llm"
    assert by_model["deepseek-ai/DeepSeek-V3"].remaining == 1000000


def test_format_siliconflow_quota_records_renders_rows():
    from src.siliconflow.quota import SiliconflowQuotaRecord

    records = [
        SiliconflowQuotaRecord(
            model="deepseek-ai/DeepSeek-V3",
            kind="llm",
            status="available",
            remaining=500000,
            used=0,
            total=500000,
            unit="token",
        )
    ]

    rendered = format_siliconflow_quota_records(records)

    assert "deepseek-ai/DeepSeek-V3" in rendered
    assert "llm" in rendered
    assert "500000" in rendered
