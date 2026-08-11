from __future__ import annotations

from pathlib import Path

from src.images.siliconflow_images import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_MODELS,
    DEFAULT_SIZE,
    _image_price_cny,
    _resolve_model_candidates,
)


def test_siliconflow_image_defaults_match_known_generation_endpoint():
    assert DEFAULT_BASE_URL == "https://api.siliconflow.cn/v1"
    assert DEFAULT_MODEL == "Kwai-Kolors/Kolors"
    assert DEFAULT_SIZE == "1140x1472"
    assert "Kwai-Kolors/Kolors" in DEFAULT_MODELS
    assert DEFAULT_MODELS[0] == "Kwai-Kolors/Kolors"


def test_siliconflow_image_model_candidates_prefer_env(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_IMAGE_MODEL", "custom-image")
    assert _resolve_model_candidates(None) == ["custom-image"]

    monkeypatch.setenv("SILICONFLOW_IMAGE_MODEL", "")
    monkeypatch.setenv("SILICONFLOW_IMAGE_MODELS", "a,b c")
    assert _resolve_model_candidates(None) == ["a", "b", "c"]


def test_siliconflow_image_config_requires_key(tmp_path: Path, monkeypatch):
    from src.images.siliconflow_images import load_siliconflow_image_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("SF_API_KEY", raising=False)

    key_file = tmp_path / "docs" / "siliconflow_api-key.md"
    key_file.parent.mkdir(parents=True)
    key_file.write_text('api_key="dummy-sf-key"\nbase_url="https://api.siliconflow.cn/v1"\n', encoding="utf-8")

    cfg = load_siliconflow_image_config(key_file=key_file)
    assert cfg.api_key == "dummy-sf-key"
    assert cfg.base_url == "https://api.siliconflow.cn/v1"

    key_file.write_text("# no key\n", encoding="utf-8")
    try:
        load_siliconflow_image_config(key_file=key_file)
        raise AssertionError("expected RuntimeError for missing key")
    except RuntimeError as exc:
        assert "api_key missing" in str(exc)


def test_siliconflow_image_price_table_marks_kolors_free():
    assert _image_price_cny("Kwai-Kolors/Kolors") == 0.0
    assert _image_price_cny("Qwen/Qwen-Image") == 0.30
    assert _image_price_cny("Tongyi-MAI/Z-Image-Turbo") == 0.10
    assert _image_price_cny("baidu/ERNIE-Image-Turbo") == 0.11
    assert _image_price_cny("unknown/model") is None
