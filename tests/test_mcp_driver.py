from pathlib import Path

from src.publish.mcp_driver import _resolve_mcp_user_data_dir


def test_mcp_user_data_dir_defaults_to_workspace(monkeypatch):
    monkeypatch.delenv("XHS_MCP_USER_DATA_DIR", raising=False)

    user_data_dir = _resolve_mcp_user_data_dir()

    assert user_data_dir == Path.cwd() / "data" / "browser" / "chrome-devtools-mcp-profile"
