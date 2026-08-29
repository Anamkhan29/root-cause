"""Direct ClickHouse access via the official clickhouse-connect driver.

This is the default, robust data path. It returns predictable list[dict] rows.
Used as an async context manager so it shares the pipeline's interface with the
MCP engine.
"""
from __future__ import annotations

import asyncio

import clickhouse_connect

from .config import Config


class DirectEngine:
    name = "direct (clickhouse-connect)"

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._client = None

    async def __aenter__(self) -> "DirectEngine":
        self._client = clickhouse_connect.get_client(
            host=self._cfg.ch_host,
            port=self._cfg.ch_port,
            username=self._cfg.ch_user,
            password=self._cfg.ch_password,
            secure=self._cfg.ch_secure,
            database=self._cfg.ch_database,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    async def query(self, sql: str) -> list[dict]:
        res = await asyncio.to_thread(self._client.query, sql)
        cols = res.column_names
        return [dict(zip(cols, row)) for row in res.result_rows]
