"""ClickHouse access via the official ClickHouse MCP server (mcp-clickhouse).

This is the partner-MCP integration path. The same deterministic pipeline runs
against it unchanged — select it with ENGINE=mcp (or `--engine mcp`). The MCP
server is launched as a stdio subprocess and the standard `mcp` client calls its
`run_select_query` tool.

Notes:
- The server is read-only by default (SELECT only), which is exactly what the
  diagnostic needs.
- Different mcp-clickhouse versions can serialize rows slightly differently, so
  the row parser below is intentionally defensive. If your server version returns
  a shape this misses, the direct engine is the reliable fallback.
"""
from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Config


class MCPEngine:
    name = "mcp (ClickHouse MCP server)"

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "MCPEngine":
        params = StdioServerParameters(
            command=self._cfg.mcp_command,
            args=[],
            env={**os.environ, **self._cfg.mcp_env()},
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def query(self, sql: str) -> list[dict]:
        result = await self._session.call_tool("run_select_query", {"query": sql})
        return _parse_rows(result)


def _parse_rows(result) -> list[dict]:
    """Coerce an MCP CallToolResult into list[dict], across known result shapes."""
    # 1) Newer servers expose typed structured content.
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    payload = structured if structured is not None else _text_payload(result)

    data = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []  # non-JSON text (e.g. an error string) -> empty result set

    # 2) Common envelopes.
    if isinstance(data, dict):
        for key in ("result", "rows", "data"):
            if key in data:
                data = data[key]
                break

    # 3) Rows as {"columns": [...], "rows": [[...]]}.
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        cols = data["columns"]
        return [dict(zip(cols, row)) for row in data["rows"]]

    # 4) Already a list of dicts, or a list of lists we can't name.
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return data
        return [{"value": r} for r in data]

    return []


def _text_payload(result) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()
