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
DEFAULT_VOLCENGINE_LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ALIYUN_FREE_LLM_MODELS = [
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
DEFAULT_ALIYUN_LLM_MODEL = ALIYUN_FREE_LLM_MODELS[0]
VOLCENGINE_AVAILABLE_LLM_MODELS = [
    "doubao-seed-2-1-turbo-260628",
    "doubao-seed-2-1-pro-260628",
    "doubao-seed-2-0-pro-260215",
    "doubao-seed-2-0-lite-260428",
    "doubao-seed-2-0-mini-260428",
    "doubao-seed-1-8-251228",
    "doubao-seed-1-6-251015",
    "doubao-seed-1-6-250615",
    "doubao-seed-1-6-flash-250828",
    "doubao-seed-1-6-flash-250615",
    "doubao-seed-code-preview-251028",
    "doubao-seed-2-0-code-preview-260215",
    "doubao-seed-character-260628",
    "doubao-seed-character-251128",
    "doubao-seed-translation-250915",
    "glm-5.2",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-260425",
    "deepseek-v4-pro-260425",
    "deepseek-v3-2-251201",
    "glm-4-7-251222",
    "glm-4-5-air-20250728",
    "qwen3-32b-20250429",
    "qwen3-14b-20250429",
    "qwen3-8b-20250429",
    "qwen3-0-6b-20250429",
]
DEFAULT_VOLCENGINE_LLM_MODEL = VOLCENGINE_AVAILABLE_LLM_MODELS[0]

# Ark exposes the user-facing DeepSeek V4 Pro name in the console catalog, but
# the OpenAI-compatible endpoint currently requires the dated deployment ID.
VOLCENGINE_LLM_ENDPOINT_ALIASES = {
    "glm-5.2": "glm-5-2-260617",
    "deepseek-v4-pro": "deepseek-v4-pro-260425",
    "deepseek-v4-flash": "deepseek-v4-flash-260425",
}


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


def _canonical_volcengine_model(value: str) -> str:
    model = (value or "").strip()
    return VOLCENGINE_LLM_ENDPOINT_ALIASES.get(model, model)


def _env_enabled(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


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
        provider="ppinfra",
    )


def _load_aliyun_llm_configs(*, default_to_all_free_models: bool = False) -> list[LLMConfig]:
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
        if env_model:
            models = [(env_model or "").strip()]
        elif default_to_all_free_models:
            models = list(ALIYUN_FREE_LLM_MODELS)
        else:
            single = DEFAULT_ALIYUN_LLM_MODEL.strip()
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


def _load_volcengine_llm_configs(*, include_default_model: bool = True) -> list[LLMConfig]:
    env_key = (
        os.getenv("VOLCENGINE_LLM_API_KEY")
        or os.getenv("VOLCENGINE_API_KEY")
        or os.getenv("ARK_API_KEY")
    )
    env_base = os.getenv("VOLCENGINE_LLM_BASE_URL") or os.getenv("ARK_BASE_URL")
    env_model = os.getenv("VOLCENGINE_LLM_MODEL") or os.getenv("ARK_LLM_MODEL")
    env_models = os.getenv("VOLCENGINE_LLM_MODELS") or os.getenv("ARK_LLM_MODELS")

    file_cfg = _parse_llm_key_file(Path("docs/volcengine_api-key.md"))

    api_key = (env_key or file_cfg.get("api_key") or "").strip()
    if not api_key:
        return []

    base_url = (env_base or file_cfg.get("base_url") or DEFAULT_VOLCENGINE_LLM_BASE_URL).strip().rstrip("/")
    models = _split_models(env_models or "")
    if not models:
        single = (env_model or (DEFAULT_VOLCENGINE_LLM_MODEL if include_default_model else "")).strip()
        models = [single] if single else []

    return [
        LLMConfig(
            model=_canonical_volcengine_model(m),
            api_key=api_key,
            base_url=base_url,
            provider="volcengine",
        )
        for m in models
        if (m or "").strip()
    ]


def _normalize_llm_provider(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "auto"
    aliases = {
        "dashscope": "aliyun",
        "bailian": "aliyun",
        "ali": "aliyun",
        "pp": "ppinfra",
        "fallback": "ppinfra",
        "openai": "ppinfra",
        "ark": "volcengine",
        "doubao": "volcengine",
        "volcano": "volcengine",
        "volc": "volcengine",
        "default": "auto",
    }
    raw = aliases.get(raw, raw)
    if raw not in {"auto", "aliyun", "volcengine", "ppinfra"}:
        raise RuntimeError(
            f"Unsupported LLM_PROVIDER={value!r}; supported: auto, aliyun, volcengine, ppinfra"
        )
    return raw


def load_llm_configs(
    *,
    llm_file: Path | str = Path("docs/llm_api-key.md"),
) -> list[LLMConfig]:
    configs: list[LLMConfig] = []
    provider = _normalize_llm_provider(os.getenv("LLM_PROVIDER") or "auto")
    allow_paid_fallback = provider == "auto" and _env_enabled("ALLOW_PAID_LLM_FALLBACK")

    if provider in ("auto", "aliyun"):
        configs.extend(
            _load_aliyun_llm_configs(default_to_all_free_models=provider == "auto")
        )

    if provider in ("auto", "volcengine"):
        configs.extend(_load_volcengine_llm_configs(include_default_model=provider != "auto"))

    if provider == "ppinfra" or allow_paid_fallback:
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
        if provider == "auto":
            raise RuntimeError(
                "No Aliyun or Volcengine LLM configuration is available in free-first auto mode. "
                "Configure ALIYUN_LLM_API_KEY or VOLCENGINE_API_KEY, explicitly set LLM_PROVIDER=ppinfra, "
                "or set ALLOW_PAID_LLM_FALLBACK=1 to opt in to PPInfra after both platforms fail."
            )
        raise RuntimeError(
            "LLM api_key missing: set ALIYUN_LLM_API_KEY (or ALIYUN_IMAGE_API_KEY/DASHSCOPE_API_KEY) "
            "or VOLCENGINE_API_KEY/ARK_API_KEY, or set LLM_API_KEY / docs/llm_api-key.md "
            "(see README.md for configuration examples)"
        )

    return configs


def load_llm_config(
    *,
    llm_file: Path | str = Path("docs/llm_api-key.md"),
) -> LLMConfig:
    return load_llm_configs(llm_file=llm_file)[0]
