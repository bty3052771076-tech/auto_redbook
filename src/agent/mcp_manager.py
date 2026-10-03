from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class LocalMCPServer:
    server_id: str
    command: str
    args: tuple[str, ...]
    cwd: Path
    allowed_tools: frozenset[str]
    timeout_seconds: float = 60.0
    startup_timeout_seconds: float = 20.0


class MCPManager:
    """On-demand stdio MCP client. Only the reviewed project server is enabled by default."""

    SOURCE_ENV_ALLOWLIST = frozenset({
        "NEWS_PROVIDER", "NEWS_TIMEOUT_S", "NEWS_MAX_RECORDS", "NEWS_FETCH_WINDOW_DAYS",
        "UNIFIED_NEWS_SOURCES", "UNIFIED_WORLDMONITOR", "WORLDMONITOR_BASE_URL",
        "WORLDMONITOR_DIR", "WORLDMONITOR_AUTO_START", "WORLDMONITOR_TIMEOUT_S",
        "NEWS_API_KEY", "GNEWS_API_KEY", "NEWSDATA_API_KEY", "THENEWSAPI_TOKEN",
        "ALPHAVANTAGE_API_KEY", "FINNHUB_API_KEY", "JUHE_NEWS_APPKEY",
        "JUHE_FINANCE_NEWS_APPKEY", "TIANAPI_API_KEY", "TIANAPI_KEY",
        "NEWSAPI_API_KEY", "NEWSAPI_KEY",
    })
    PROCESS_ENV_ALLOWLIST = frozenset({
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA",
    })
    _TOOL_REQUIRED = {
        "runtime_status": set(),
        "knowledge_search": {"query"},
        "news_search": {"query"},
    }

    def __init__(self, workspace_root: Path):
        self.root = workspace_root.resolve()
        self.python = (self.root / ".venv" / "Scripts" / "python.exe").resolve()
        if self.root.drive.upper() != "E:" or not self.python.is_file():
            raise RuntimeError("MCP_RUNTIME_MUST_USE_WORKSPACE_E_VENV")
        self.server = LocalMCPServer(
            server_id="redbook-local",
            command=str(self.python),
            args=("-m", "src.agent.mcp_server"),
            cwd=self.root,
            allowed_tools=frozenset(self._TOOL_REQUIRED),
        )

    def _parameters(self) -> StdioServerParameters:
        env = {
            key: value for key in self.SOURCE_ENV_ALLOWLIST | self.PROCESS_ENV_ALLOWLIST
            if (value := os.environ.get(key)) is not None
        }
        env_file = self.root / ".env.gui"
        if env_file.is_file():
            from apps.gui import load_env_file
            configured = load_env_file(env_file)
            env.update({key: configured[key] for key in self.SOURCE_ENV_ALLOWLIST if configured.get(key)})
        env["PYTHONIOENCODING"] = "utf-8"
        env["TEMP"] = str(self.root / "data" / "tmp" / "mcp")
        env["TMP"] = env["TEMP"]
        Path(env["TEMP"]).mkdir(parents=True, exist_ok=True)
        return StdioServerParameters(
            command=self.server.command,
            args=list(self.server.args),
            cwd=str(self.server.cwd),
            env=env,
            encoding="utf-8",
            encoding_error_handler="replace",
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        async with stdio_client(self._parameters()) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=self.server.startup_timeout_seconds)
                tools = await asyncio.wait_for(session.list_tools(), timeout=self.server.startup_timeout_seconds)
                self._validate_tools(tools.tools)
                yield session

    def _validate_tools(self, tools: list[Any]) -> None:
        names = {str(tool.name) for tool in tools}
        if names != set(self.server.allowed_tools):
            raise RuntimeError("MCP_TOOL_CATALOG_MISMATCH: local MCP tools changed; review before use")
        for tool in tools:
            schema = getattr(tool, "inputSchema", {}) or {}
            properties = set((schema.get("properties") or {}).keys())
            required = set(schema.get("required") or [])
            if not self._TOOL_REQUIRED[tool.name].issubset(properties | required):
                raise RuntimeError(f"MCP_TOOL_SCHEMA_INVALID: {tool.name}")

    @staticmethod
    def _contains_timeout(exc: BaseException, seen: set[int] | None = None) -> bool:
        seen = seen or set()
        if id(exc) in seen:
            return False
        seen.add(id(exc))
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return True
        if "timed out while waiting for response" in str(exc).casefold():
            return True
        children = getattr(exc, "exceptions", ())
        linked = [*children]
        if exc.__cause__ is not None:
            linked.append(exc.__cause__)
        if exc.__context__ is not None:
            linked.append(exc.__context__)
        return any(MCPManager._contains_timeout(child, seen) for child in linked)

    async def alist_tools(self) -> list[dict[str, Any]]:
        async with self._session() as session:
            result = await asyncio.wait_for(session.list_tools(), timeout=self.server.startup_timeout_seconds)
            return [
                {"name": tool.name, "description": tool.description or "", "input_schema": tool.inputSchema,
                 "server_id": self.server.server_id}
                for tool in result.tools
            ]

    async def acall_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.server.allowed_tools:
            raise PermissionError("MCP_TOOL_NOT_ALLOWED")
        try:
            async with self._session() as session:
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments, read_timeout_seconds=timedelta(seconds=self.server.timeout_seconds)),
                    timeout=self.server.timeout_seconds + 2,
                )
                if result.isError:
                    raise RuntimeError(f"MCP_TOOL_ERROR: {name}")
                structured = getattr(result, "structuredContent", None)
                if structured is not None:
                    return {"status": "ok", "server_id": self.server.server_id, "tool": name, "result": structured}
                text_parts = [str(item.text) for item in result.content if getattr(item, "text", None)]
                if len(text_parts) == 1:
                    try:
                        decoded = json.loads(text_parts[0])
                    except (json.JSONDecodeError, TypeError):
                        pass
                    else:
                        if isinstance(decoded, dict):
                            return {"status": "ok", "server_id": self.server.server_id, "tool": name, "result": decoded}
                return {"status": "ok", "server_id": self.server.server_id, "tool": name, "content": text_parts}
        except Exception as exc:
            if self._contains_timeout(exc):
                raise TimeoutError(f"MCP_TOOL_TIMEOUT: {name} exceeded {self.server.timeout_seconds:g}s") from None
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        return asyncio.run(self.alist_tools())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("MCP arguments must be a JSON object")
        return asyncio.run(self.acall_tool(name, arguments))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Reviewed local MCP utilities")
    parser.add_argument("action", choices=("list", "call"))
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--args", default="{}", help="JSON object; never interpreted as shell")
    args = parser.parse_args(argv)
    manager = MCPManager(Path(__file__).resolve().parents[2])
    if args.action == "list":
        payload = {"status": "ready", "tools": manager.list_tools()}
    else:
        if not args.tool:
            parser.error("call requires a tool name")
        payload = manager.call_tool(args.tool, json.loads(args.args))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
