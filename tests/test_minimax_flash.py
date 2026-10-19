import json
from pathlib import Path

import pytest

from apps import gui
from src.config import load_llm_configs
from src.model_platforms.integration import frozen_legacy_config


FLASH = "MiniMax-M3.1-Flash"


@pytest.fixture
def subscription(tmp_path, monkeypatch, workbench_factory):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gui, "build_subprocess_env", lambda overrides: dict(overrides))
    config = (
        "MINIMAX_TOKEN_PLAN_API_KEY=unit-token-plan-key\n"
        "MINIMAX_LLM_MODEL=MiniMax-M3\n"
        "MINIMAX_BASE_URL=https://api.minimax.cn/v1\n"
        "MINIMAX_BILLING_MODE=subscription_only\n"
        "MINIMAX_ALLOW_PAID_CREDITS=0\n"
        "MINIMAX_ALLOW_PAYGO=0\n"
    )
    (tmp_path / ".env.gui").write_text(config, encoding="utf-8")
    return workbench_factory(tmp_path)


def test_flash_can_be_selected_alongside_m3_without_quota_sync(subscription):
    rows = subscription.models()["rows"]
    for model in ("MiniMax-M3", FLASH):
        matches = [row for row in rows if row["id"] == "minimax:" + model]
        assert len(matches) == 1
        assert matches[0]["selectable"] is True
        assert matches[0]["cost_class"] == "subscription_included"
        assert matches[0]["remaining"] is None


def test_flash_selection_uses_same_key_and_survives_reopen(subscription, workbench_factory):
    roles = {"agent": "minimax:" + FLASH, "writer": "minimax:" + FLASH, "image": ""}
    subscription.save_model_bindings(roles)
    reopened = workbench_factory(subscription.root)
    assert reopened.providers()["bindings"] == roles
    frozen = reopened.freeze_model_roles(reopened.environment(), {"kind": "agent"})
    for role in ("agent", "writer"):
        config = frozen_legacy_config(role, env=frozen)
        assert config.model == FLASH
        assert config.api_key == "unit-token-plan-key"
        assert config.base_url == "https://api.minimax.cn/v1"
        assert config.provider == "minimax"
        assert config.cost_class == "subscription_included"
    assert json.loads(frozen["RUN_LEGACY_MODEL_ROLES"])["agent"] == "minimax:" + FLASH


def test_configuring_flash_does_not_duplicate_catalog_rows(subscription):
    path = subscription.root / ".env.gui"
    path.write_text(path.read_text(encoding="utf-8").replace("MODEL=MiniMax-M3", "MODEL=" + FLASH), encoding="utf-8")
    rows = subscription.models()["rows"]
    assert len([row for row in rows if row["id"] == "minimax:" + FLASH]) == 1


@pytest.mark.parametrize("change", ["missing_key", "paygo", "paid_credits"])
def test_flash_keeps_subscription_billing_guards(subscription, change):
    path = subscription.root / ".env.gui"
    text = path.read_text(encoding="utf-8")
    old, new = {
        "missing_key": ("MINIMAX_TOKEN_PLAN_API_KEY=unit-token-plan-key", "MINIMAX_TOKEN_PLAN_API_KEY="),
        "paygo": ("MINIMAX_ALLOW_PAYGO=0", "MINIMAX_ALLOW_PAYGO=1"),
        "paid_credits": ("MINIMAX_ALLOW_PAID_CREDITS=0", "MINIMAX_ALLOW_PAID_CREDITS=1"),
    }[change]
    path.write_text(text.replace(old, new), encoding="utf-8")
    row = next(row for row in subscription.models()["rows"] if row["id"] == "minimax:" + FLASH)
    assert row["selectable"] is False
    assert row["disabled_reason"]


def test_desktop_choice_exposes_flash_without_changing_default(subscription, monkeypatch):
    assert FLASH in gui.MINIMAX_LLM_MODEL_OPTIONS
    for key, value in subscription.environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    monkeypatch.delenv("MINIMAX_LLM_MODELS", raising=False)
    configs = load_llm_configs(llm_file=Path("missing-llm-file"))
    assert configs[0].model == "MiniMax-M3"
    monkeypatch.setenv("MINIMAX_LLM_MODEL", FLASH)
    configs = load_llm_configs(llm_file=Path("missing-llm-file"))
    assert configs[0].model == FLASH
    assert configs[0].api_key == "unit-token-plan-key"
