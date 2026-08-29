"""Root Cause — command-line entrypoint.

Examples:
  python main.py "Rebuffering spiked last night in the Southeast"
  python main.py "Playback errors up in the West" --engine mcp --incident-date 2026-08-29
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv()

from src.config import Config
from src.gemini import GeminiClient
from src.pipeline import DiagnosticPipeline, make_engine
from src.window import default_incident_window


async def run(incident: str, engine_override: str | None, incident_date: str | None) -> None:
    cfg = Config.from_env()
    if engine_override:
        cfg.engine = engine_override
    t0, t1 = default_incident_window(incident_date)

    gemini = GeminiClient(cfg)
    engine = make_engine(cfg)
    async with engine as e:
        pipeline = DiagnosticPipeline(cfg, e, gemini)
        result = await pipeline.run(incident, t0, t1)

    print(f"\n[engine: {result['engine']}  window: {t0} .. {t1}]\n")
    print(result["report"])
    f = result["findings"]
    print("\n--- structured findings ---")
    print(f"baseline rate:      {f['baseline_rate']:.2%}")
    print(f"incident rate:      {f['incident_rate']:.2%}  ({f['rate_multiple']}x baseline)")
    print(f"sessions in window: {f['incident_sessions']:,}")
    print(f"primary factor:     {f['primary_factor']}  (concentration {f['primary_concentration']})")
    print(f"secondary factor:   {f['secondary_factor']}")
    print(f"culprit segment:    {f['culprit_segment_rate']:.2%} over {f['culprit_segment_sessions']:,} sessions")
    print(f"suggested action:   {f['suggested_action']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Root Cause — agentic streaming diagnostics")
    ap.add_argument("incident", help="the incident, in plain English")
    ap.add_argument("--engine", choices=["direct", "mcp"], default=None,
                    help="data path: direct clickhouse-connect (default) or the ClickHouse MCP server")
    ap.add_argument("--incident-date", default=None,
                    help="YYYY-MM-DD of the incident evening (default: yesterday)")
    args = ap.parse_args()
    asyncio.run(run(args.incident, args.engine, args.incident_date))


if __name__ == "__main__":
    main()
