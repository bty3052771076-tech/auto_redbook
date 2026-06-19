from pathlib import Path

from src.publish.playwright_steps import _resolve_profile_config


def test_custom_profile_keeps_system_chrome_channel_by_default(monkeypatch, tmp_path: Path):
    custom_profile = tmp_path / "chrome-profile"
    monkeypatch.setenv("XHS_CHROME_USER_DATA_DIR", str(custom_profile))
    monkeypatch.delenv("XHS_BROWSER_CHANNEL", raising=False)
    monkeypatch.delenv("XHS_CHROME_PROFILE", raising=False)

    profile_dir, channel, args = _resolve_profile_config()

    assert profile_dir == custom_profile
    assert channel == "chrome"
    assert args == []
