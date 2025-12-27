from __future__ import annotations

from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection


def chrome_client() -> MultiServerMCPClient:
    """
    Build a MultiServerMCPClient for chrome-devtools (stdio, npx).
    使用固定 user-data-dir 持久化登录态。
    """
    user_data_dir = Path.home() / ".cache" / "chrome-devtools-mcp" / "chrome-profile-persist"
    conn: StdioConnection = {
        "transport": "stdio",
        "command": "cmd",
        "args": [
            "/c",
            "npx",
            "-y",
            "chrome-devtools-mcp@latest",
            f"--user-data-dir={user_data_dir}",
        ],
        "env": {"SystemRoot": "C:\\Windows", "PROGRAMFILES": "C:\\Program Files"},
    }
    return MultiServerMCPClient({"chrome": conn}, tool_name_prefix=True)
