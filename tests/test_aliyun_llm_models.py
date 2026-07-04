from __future__ import annotations

from pathlib import Path

from src.config import ALIYUN_FREE_LLM_MODELS, DEFAULT_ALIYUN_LLM_MODEL, load_llm_configs


def _isolate_volcengine_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "VOLCENGINE_LLM_API_KEY",
        "VOLCENGINE_API_KEY",
        "VOLCENGINE_IMAGE_API_KEY",
        "ARK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_aliyun_free_llm_model_catalog_matches_current_console_list():
    assert DEFAULT_ALIYUN_LLM_MODEL == "qwen3.7-plus"
    assert ALIYUN_FREE_LLM_MODELS == [
        "qwen3.7-plus",
        "deepseek-v4-flash",
        "qwen3.6-flash-2026-04-16",
        "qwen3.6-35b-a3b",
        "qwen3.7-max-2026-05-17",
        "qwen3.7-max-2026-06-08",
        "glm-5.1",
        "qwen3.6-plus-2026-04-02",
        "qwen3.7-max-preview",
        "glm-5.2",
        "qwen3.6-plus",
        "qwen3.5-plus-2026-04-20",
        "qwen3.6-max-preview",
        "qwen3.7-max",
        "kimi-k2.6",
        "qwen3.7-max-2026-05-20",
        "qwen3.7-plus-2026-05-26",
        "qwen3.6-flash",
    ]


def test_aliyun_llm_models_list_builds_multiple_configs(monkeypatch, tmp_path: Path):
    _isolate_volcengine_config(monkeypatch, tmp_path)
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "m1,m2 m1")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs[:3]] == ["aliyun", "aliyun", "fallback"]
    assert [c.model for c in cfgs[:2]] == ["m1", "m2"]


def test_aliyun_llm_models_list_overrides_single_model(monkeypatch, tmp_path: Path):
    _isolate_volcengine_config(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "aliyun")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODEL", "single")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "list1,list2")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["aliyun", "aliyun"]
    assert [c.model for c in cfgs] == ["list1", "list2"]


def test_aliyun_llm_single_model_fallback(monkeypatch, tmp_path: Path):
    _isolate_volcengine_config(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "aliyun")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODEL", "single")
    monkeypatch.delenv("ALIYUN_LLM_MODELS", raising=False)

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert len(cfgs) == 1
    assert cfgs[0].provider == "aliyun"
    assert cfgs[0].model == "single"


def test_llm_provider_ppinfra_skips_aliyun_even_when_key_exists(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ppinfra")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "qwen3.7-plus")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")
    monkeypatch.setenv("LLM_MODEL", "deepseek/deepseek-v3-0324")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["fallback"]
    assert [c.model for c in cfgs] == ["deepseek/deepseek-v3-0324"]


def test_llm_provider_aliyun_skips_ppinfra_fallback(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "aliyun")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("ALIYUN_LLM_MODELS", "qwen3.7-plus")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["aliyun"]
    assert [c.model for c in cfgs] == ["qwen3.7-plus"]

