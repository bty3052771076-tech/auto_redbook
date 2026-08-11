from __future__ import annotations

from pathlib import Path

from src.config import (
    DEFAULT_SILICONFLOW_LLM_BASE_URL,
    DEFAULT_SILICONFLOW_LLM_MODEL,
    SILICONFLOW_FREE_LLM_MODELS,
    load_llm_configs,
)


def test_siliconflow_llm_model_catalog_has_known_free_models():
    assert DEFAULT_SILICONFLOW_LLM_BASE_URL == "https://api.siliconflow.cn/v1"
    assert DEFAULT_SILICONFLOW_LLM_MODEL == "deepseek-ai/DeepSeek-V3"
    assert "deepseek-ai/DeepSeek-V3" in SILICONFLOW_FREE_LLM_MODELS
    assert "Qwen/Qwen3-32B" in SILICONFLOW_FREE_LLM_MODELS
    assert "THUDM/GLM-4-9B-0414" in SILICONFLOW_FREE_LLM_MODELS


def test_siliconflow_llm_provider_builds_multiple_configs(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "dummy-sf")
    monkeypatch.setenv("SILICONFLOW_LLM_MODELS", "deepseek-ai/DeepSeek-V3,Qwen/Qwen3-32B")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "dummy-volc")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["siliconflow", "siliconflow"]
    assert [c.model for c in cfgs] == [
        "deepseek-ai/DeepSeek-V3",
        "Qwen/Qwen3-32B",
    ]
    assert all(c.base_url == DEFAULT_SILICONFLOW_LLM_BASE_URL for c in cfgs)


def test_auto_provider_includes_siliconflow_when_key_present(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "dummy-sf")
    monkeypatch.setenv("SILICONFLOW_LLM_MODELS", "sf-free")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "aliyun-free")
    monkeypatch.delenv("VOLCENGINE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VOLCENGINE_LLM_MODELS", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [(c.provider, c.model) for c in cfgs] == [
        ("aliyun", "aliyun-free"),
        ("siliconflow", "sf-free"),
    ]
