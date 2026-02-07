from __future__ import annotations

from pathlib import Path

from src.config import load_llm_configs


def test_aliyun_llm_models_list_builds_multiple_configs(monkeypatch):
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "m1,m2 m1")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs[:3]] == ["aliyun", "aliyun", "fallback"]
    assert [c.model for c in cfgs[:2]] == ["m1", "m2"]


def test_aliyun_llm_models_list_overrides_single_model(monkeypatch):
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODEL", "single")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "list1,list2")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["aliyun", "aliyun"]
    assert [c.model for c in cfgs] == ["list1", "list2"]


def test_aliyun_llm_single_model_fallback(monkeypatch):
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODEL", "single")
    monkeypatch.delenv("ALIYUN_LLM_MODELS", raising=False)

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert len(cfgs) == 1
    assert cfgs[0].provider == "aliyun"
    assert cfgs[0].model == "single"

