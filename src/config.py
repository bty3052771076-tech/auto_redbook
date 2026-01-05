from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str
    base_url: Optional[str] = None


DEFAULT_LLM_BASE_URL = "https://api.ppinfra.com/openai"


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


def load_llm_config(
    *,
    llm_file: Path | str = Path("docs/llm_api-key.md"),
) -> LLMConfig:
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

    model = env_model or file_cfg.get("model") or "deepseek/deepseek-v3-0324"
    api_key = env_key or file_cfg.get("api_key")
    base_url = env_base or file_cfg.get("base_url") or DEFAULT_LLM_BASE_URL

    if not api_key:
        raise RuntimeError(
            "LLM api_key missing: set LLM_API_KEY env or create docs/llm_api-key.md "
            "(see docs/llm_api-key.example.md)"
        )

    return LLMConfig(model=model, api_key=api_key, base_url=base_url)
