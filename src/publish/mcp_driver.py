from __future__ import annotations

import os
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_mcp_user_data_dir() -> Path:
    raw = (os.getenv("XHS_MCP_USER_DATA_DIR") or "").strip()
    if raw:
        return Path(raw)
    return _repo_root() / "data" / "browser" / "chrome-devtools-mcp-profile"


def chrome_client() -> MultiServerMCPClient:
    """
    Build a MultiServerMCPClient for chrome-devtools (stdio, npx).
    使用固定 user-data-dir 持久化登录态。
    """
    user_data_dir = _resolve_mcp_user_data_dir()
    npm_cache_dir = _repo_root() / ".npm-cache"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
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
        "env": {
            "SystemRoot": "C:\\Windows",
            "PROGRAMFILES": "C:\\Program Files",
            "npm_config_cache": str(npm_cache_dir),
            "NPM_CONFIG_CACHE": str(npm_cache_dir),
        },
    }
    return MultiServerMCPClient({"chrome": conn}, tool_name_prefix=True)
