"""Central configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # --- ClickHouse ---
    ch_host: str
    ch_port: int
    ch_user: str
    ch_password: str
    ch_secure: bool
    ch_database: str
    table: str

    # --- Gemini ---
    gcp_project: str
    gcp_location: str
    gemini_model: str
    gemini_api_key: str

    # --- Data access engine ---
    engine: str
    mcp_command: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            ch_host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            ch_port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
            ch_user=os.getenv("CLICKHOUSE_USER", "default"),
            ch_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            ch_secure=os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true",
            ch_database=os.getenv("CLICKHOUSE_DATABASE", "default"),
            table=os.getenv("TABLE_NAME", "playback_events"),
            gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            gcp_location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            engine=os.getenv("ENGINE", "direct"),
            mcp_command=os.getenv("MCP_COMMAND", "mcp-clickhouse"),
        )

    def mcp_env(self) -> dict:
        """Environment variables the ClickHouse MCP server expects."""
        return {
            "CLICKHOUSE_HOST": self.ch_host,
            "CLICKHOUSE_PORT": str(self.ch_port),
            "CLICKHOUSE_USER": self.ch_user,
            "CLICKHOUSE_PASSWORD": self.ch_password,
            "CLICKHOUSE_SECURE": "true" if self.ch_secure else "false",
            "CLICKHOUSE_DATABASE": self.ch_database,
        }
