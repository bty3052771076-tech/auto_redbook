from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str
    base_url: Optional[str] = None
    provider: str = "custom"


DEFAULT_LLM_BASE_URL = "https://api.ppinfra.com/openai"
DEFAULT_LLM_MODEL = "deepseek/deepseek-v3-0324"
DEFAULT_ALIYUN_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_ALIYUN_LLM_MODEL = "deepseek-v3.2"


def _parse_llm_key_file(path: Path) -> dict[str, str]:
    """
    Parse docs/llm_api-key file with lines like:
    base_url="https://..."
    model="deepseek/deepseek-v3-0324"
    api_key="sk-..."
    """
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        data[k] = v
    return data


def _split_models(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,\s]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        m = (p or "").strip()
        if not m or m in seen:
            continue
        out.append(m)
        seen.add(m)
    return out


def _load_fallback_llm_config(*, llm_file: Path | str) -> Optional[LLMConfig]:
    env_model = os.getenv("LLM_MODEL")
    env_key = os.getenv("LLM_API_KEY")
    env_base_llm = os.getenv("LLM_BASE_URL")
    env_base_openai = os.getenv("OPENAI_BASE_URL")
    if (
        env_base_llm
        and env_base_openai
        and env_base_llm.strip() != env_base_openai.strip()
    ):
        raise RuntimeError(
            "Conflicting base URLs: LLM_BASE_URL != OPENAI_BASE_URL. "
            "Set only one of them, or set them to the same value."
        )
    env_base = env_base_llm or env_base_openai

    file_cfg = _parse_llm_key_file(Path(llm_file))

    model = env_model or file_cfg.get("model") or DEFAULT_LLM_MODEL
    api_key = env_key or file_cfg.get("api_key")
    base_url = env_base or file_cfg.get("base_url") or DEFAULT_LLM_BASE_URL

    if not api_key:
        return None

    return LLMConfig(
        model=model.strip(),
        api_key=api_key.strip(),
        base_url=base_url.strip().rstrip("/"),
        provider="fallback",
    )


def _load_aliyun_llm_configs() -> list[LLMConfig]:
    env_key = (
        os.getenv("ALIYUN_LLM_API_KEY")
        or os.getenv("ALIYUN_IMAGE_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
    )
    env_base = os.getenv("ALIYUN_LLM_BASE_URL")
    env_model = os.getenv("ALIYUN_LLM_MODEL")
    env_models = os.getenv("ALIYUN_LLM_MODELS")

    file_cfg = _parse_llm_key_file(Path("docs/aliyun_image_api-key.md"))

    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    if not api_key:
        return []

    file_base = (file_cfg.get("base_url") or "").strip()
    if "compatible-mode" not in file_base:
        file_base = ""
    base_url = (env_base or file_base or DEFAULT_ALIYUN_LLM_BASE_URL).strip().rstrip("/")
    models = _split_models(env_models or "")
    if not models:
        single = (env_model or DEFAULT_ALIYUN_LLM_MODEL).strip()
        models = [single] if single else []

    return [
        LLMConfig(
            model=m,
            api_key=api_key,
            base_url=base_url,
            provider="aliyun",
        )
        for m in models
        if (m or "").strip()
    ]


def load_llm_configs(
    *,
    llm_file: Path | str = Path("docs/llm_api-key.md"),
) -> list[LLMConfig]:
    configs: list[LLMConfig] = []
    configs.extend(_load_aliyun_llm_configs())

    fallback_cfg = _load_fallback_llm_config(llm_file=llm_file)
    if fallback_cfg:
        # Avoid duplicates if the user reuses the same base_url/model/key.
        if not any(
            c.base_url == fallback_cfg.base_url
            and c.model == fallback_cfg.model
            and c.api_key == fallback_cfg.api_key
            for c in configs
        ):
            configs.append(fallback_cfg)

    if not configs:
        raise RuntimeError(
            "LLM api_key missing: set ALIYUN_LLM_API_KEY (or ALIYUN_IMAGE_API_KEY/DASHSCOPE_API_KEY) "
            "or set LLM_API_KEY / docs/llm_api-key.md (see docs/llm_api-key.example.md)"
        )

    return configs


def load_llm_config(
    *,
    llm_file: Path | str = Path("docs/llm_api-key.md"),
) -> LLMConfig:
    return load_llm_configs(llm_file=llm_file)[0]
