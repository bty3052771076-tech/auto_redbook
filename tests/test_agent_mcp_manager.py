from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agent.mcp_manager import MCPManager


def test_mcp_manager_is_workspace_e_venv_only(tmp_path):
    with pytest.raises(RuntimeError, match="WORKSPACE_E_VENV"):
        MCPManager(tmp_path)


def test_mcp_environment_does_not_forward_model_or_database_secrets(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    manager = MCPManager(root)
    monkeypatch.setenv("MINIMAX_TOKEN_PLAN_API_KEY", "do-not-forward")
    monkeypatch.setenv("KNOWLEDGE_DB_PASSWORD", "do-not-forward")
    monkeypatch.setenv("FINNHUB_API_KEY", "source-key")
    parameters = manager._parameters()
    assert parameters.env["FINNHUB_API_KEY"] == "source-key"
    assert "MINIMAX_TOKEN_PLAN_API_KEY" not in parameters.env
    assert "KNOWLEDGE_DB_PASSWORD" not in parameters.env
    assert parameters.command.endswith(".venv\\Scripts\\python.exe")


def test_mcp_timeout_is_found_inside_transport_cleanup_group():
    from exceptiongroup import ExceptionGroup

    error = ExceptionGroup(
        "stdio cleanup",
        [RuntimeError("BrokenResourceError"), RuntimeError("Timed out while waiting for response to ClientRequest")],
    )
    assert MCPManager._contains_timeout(error)


@pytest.mark.skipif(os.getenv("RUN_MCP_INTEGRATION") != "1", reason="starts the local MCP stdio server")
def test_real_local_mcp_handshake_catalog_and_status_call():
    root = Path(__file__).resolve().parents[1]
    manager = MCPManager(root)
    tools = manager.list_tools()
    assert {tool["name"] for tool in tools} == {"runtime_status", "knowledge_search", "news_search"}
    result = manager.call_tool("runtime_status", {})
    assert result["status"] == "ok"
    assert result["result"]["status"] == "ready"
    with pytest.raises(PermissionError, match="NOT_ALLOWED"):
        manager.call_tool("anything", {})
