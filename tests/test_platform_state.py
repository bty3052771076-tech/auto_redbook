from pathlib import Path

import pytest

from src.publish.platform_state import PlatformStateStore, PlatformStateError


def test_platform_risk_state_persists_and_blocks_until_explicit_clear(tmp_path: Path):
    state_file = tmp_path / "platform-state.json"
    first = PlatformStateStore(state_file)
    paused = first.pause(
        profile_key="profile-a",
        code="XHS_RISK_BLOCKED",
        detail="平台风险提示",
        evidence_ref="evidence/1.json",
    )
    assert paused["version"] == 1

    second = PlatformStateStore(state_file)
    with pytest.raises(PlatformStateError, match="XHS_RISK_BLOCKED"):
        second.assert_operable("profile-a")

    cleared = second.clear("profile-a", expected_version=1)
    assert cleared["status"] == "ready"
    second.assert_operable("profile-a")


def test_platform_state_rejects_stale_clear(tmp_path: Path):
    store = PlatformStateStore(tmp_path / "state.json")
    store.pause(profile_key="profile-a", code="XHS_CHALLENGE_REQUIRED", detail="challenge")
    with pytest.raises(PlatformStateError, match="version"):
        store.clear("profile-a", expected_version=0)
