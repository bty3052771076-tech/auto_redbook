"""Request defaults shared by MiniMax-compatible text entry points."""

import os

MINIMAX_FLASH_MODELS = frozenset({"minimax-m3.1-flash", "minimax-m3.1-flash-preview"})
MINIMAX_FLASH_OUTPUT_TOKENS = 131072


def minimax_output_tokens(model: str, fallback: int) -> int:
    """Reserve reasoning plus final output; copy length is controlled by the prompt."""
    if (model or "").strip().lower().rsplit("/", 1)[-1] in MINIMAX_FLASH_MODELS:
        return MINIMAX_FLASH_OUTPUT_TOKENS
    return fallback


def minimax_reasoning_options(model: str, *, effort: str | None = None) -> dict[str, str]:
    if (model or "").strip().lower().rsplit("/", 1)[-1] not in MINIMAX_FLASH_MODELS:
        return {}
    value = (effort if effort is not None else os.getenv("MINIMAX_REASONING_EFFORT", "medium")).strip().lower() or "medium"
    if value not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("MiniMax Flash reasoning_effort must be low, medium, high, xhigh or max; thinking cannot be disabled")
    return {"reasoning_effort": value}
