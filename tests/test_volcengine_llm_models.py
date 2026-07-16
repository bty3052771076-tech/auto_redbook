from __future__ import annotations

from pathlib import Path

from src.config import (
    DEFAULT_VOLCENGINE_LLM_BASE_URL,
    DEFAULT_VOLCENGINE_LLM_MODEL,
    VOLCENGINE_AVAILABLE_LLM_MODELS,
    load_llm_configs,
)


def test_volcengine_llm_model_catalog_matches_current_ark_list():
    assert DEFAULT_VOLCENGINE_LLM_BASE_URL == "https://ark.cn-beijing.volces.com/api/v3"
    assert DEFAULT_VOLCENGINE_LLM_MODEL == "doubao-seed-2-1-turbo-260628"
    assert "doubao-seed-2-1-pro-260628" in VOLCENGINE_AVAILABLE_LLM_MODELS
    assert "deepseek-v4-flash-260425" in VOLCENGINE_AVAILABLE_LLM_MODELS
    assert "deepseek-v4-flash" in VOLCENGINE_AVAILABLE_LLM_MODELS
    assert "deepseek-v4-pro" in VOLCENGINE_AVAILABLE_LLM_MODELS
    assert "glm-5.2" in VOLCENGINE_AVAILABLE_LLM_MODELS
    assert "glm-4-7-251222" in VOLCENGINE_AVAILABLE_LLM_MODELS


def test_volcengine_llm_provider_builds_multiple_configs(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "dummy-volc")
    monkeypatch.setenv("VOLCENGINE_LLM_MODELS", "doubao-seed-2-1-turbo-260628,deepseek-v4-flash-260425")
    monkeypatch.setenv("ALIYUN_LLM_API_KEY", "dummy-aliyun")
    monkeypatch.setenv("LLM_API_KEY", "dummy-fallback")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert [c.provider for c in cfgs] == ["volcengine", "volcengine"]
    assert [c.model for c in cfgs] == [
        "doubao-seed-2-1-turbo-260628",
        "deepseek-v4-flash-260425",
    ]
    assert all(c.base_url == DEFAULT_VOLCENGINE_LLM_BASE_URL for c in cfgs)


def test_volcengine_deepseek_v4_pro_alias_uses_live_endpoint_id(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_API_KEY", "dummy-volc")
    monkeypatch.setenv("VOLCENGINE_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.delenv("VOLCENGINE_LLM_MODELS", raising=False)

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert len(cfgs) == 1
    assert cfgs[0].model == "deepseek-v4-pro-260425"


def test_ark_llm_provider_alias_uses_ark_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ark")
    monkeypatch.delenv("VOLCENGINE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.setenv("ARK_API_KEY", "dummy-ark")
    monkeypatch.setenv("VOLCENGINE_LLM_MODEL", "glm-4-7-251222")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert len(cfgs) == 1
    assert cfgs[0].provider == "volcengine"
    assert cfgs[0].api_key == "dummy-ark"
    assert cfgs[0].model == "glm-4-7-251222"


def test_volcengine_llm_reads_local_key_file(monkeypatch, tmp_path: Path):
    key_file = tmp_path / "volcengine_api-key.md"
    key_file.write_text(
        'api_key="dummy-file-key"\n'
        'base_url="https://ark.example/api/v3"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "volcengine")
    monkeypatch.setenv("VOLCENGINE_LLM_MODEL", "doubao-seed-2-1-turbo-260628")
    monkeypatch.delenv("VOLCENGINE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("ARK_BASE_URL", raising=False)

    docs = tmp_path / "docs"
    docs.mkdir()
    key_file.replace(docs / "volcengine_api-key.md")

    cfgs = load_llm_configs(llm_file=Path("does_not_exist"))

    assert len(cfgs) == 1
    assert cfgs[0].api_key == "dummy-file-key"
    assert cfgs[0].base_url == "https://ark.example/api/v3"
