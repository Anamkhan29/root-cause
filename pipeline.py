"""The deterministic diagnostic pipeline — the agent's brain.

Control flow is fixed (the seven stages always run in the same order). Gemini
fills two narrow slots (parse and narrate); ClickHouse answers the queries. The
engine (direct or MCP) is interchangeable.
"""
from __future__ import annotations

import asyncio

from .config import Config
from .gemini import GeminiClient
from .queries import DIMENSIONS, confirm_sql, decompose_sql, drill_sql, timeseries_sql
from .scoring import add_scores, concentration, total_excess

# Which dimensions imply which mitigation verb.
_MITIGATION = {
    "app_version": "roll back app version {value}",
    "cdn_pop": "drain / reroute traffic away from CDN PoP {value}",
    "os": "hold rollout on {value} and investigate the client build",
    "isp": "open a peering / routing ticket with {value}",
}


def make_engine(cfg: Config):
    if cfg.engine == "mcp":
        from .clickhouse_mcp import MCPEngine
        return MCPEngine(cfg)
    from .clickhouse_client import DirectEngine
    return DirectEngine(cfg)


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _clean(rows: list[dict]) -> list[dict]:
    """Normalise engine rows to {value:str, n:int, rate:float}."""
    out = []
    for r in rows:
        out.append({
            "value": str(r.get("value")),
            "n": int(_num(r.get("n"))),
            "rate": _num(r.get("rate")),
        })
    return out


class DiagnosticPipeline:
    def __init__(self, cfg: Config, engine, gemini: GeminiClient):
        self.cfg = cfg
        self.engine = engine
        self.gemini = gemini
        self.table = cfg.table

    async def run(self, incident_text: str, t0: str, t1: str) -> dict:
        # --- Stage 1: Scope (Gemini) ---
        spec = await asyncio.to_thread(self.gemini.parse_incident, incident_text)

        # --- Stage 2: Confirm ---
        conf_rows = await self.engine.query(confirm_sql(self.table, t0, t1))
        conf = conf_rows[0] if conf_rows else {}
        baseline = _num(conf.get("baseline_rate"))
        incident = _num(conf.get("incident_rate"))
        incident_sessions = int(_num(conf.get("incident_sessions")))

        # --- Stage 3: Decompose across candidate dimensions ---
        dim_results: dict[str, dict] = {}
        for dim in DIMENSIONS:
            rows = _clean(await self.engine.query(decompose_sql(self.table, dim, t0, t1)))
            add_scores(rows, baseline)
            conc, top = concentration(rows)
            dim_results[dim] = {
                "rows": rows,
                "concentration": conc,
                "top": top,
                "total_excess": total_excess(rows),
            }

        # --- Stage 4: Rank -> pick the dimension carrying the most excess ---
        ranked = sorted(dim_results.items(), key=lambda kv: kv[1]["total_excess"], reverse=True)
        top_dim, top_info = ranked[0]
        top_value = top_info["top"]["value"] if top_info["top"] else "unknown"

        # --- Stage 5: Drill -> find the strongest interacting factor within the culprit value ---
        best = None
        for other in [d for d in DIMENSIONS if d != top_dim]:
            rows = _clean(await self.engine.query(drill_sql(self.table, top_dim, top_value, other, t0, t1)))
            add_scores(rows, baseline)
            conc, top = concentration(rows)
            if top and (best is None or top["excess"] > best["excess"]):
                best = {"dim": other, "concentration": conc, **top}
        if best is None:
            best = {"dim": top_dim, "value": top_value, "rate": incident, "n": incident_sessions, "concentration": 1.0}
        secondary_dim, secondary_value = best["dim"], best["value"]

        # --- Smoking-gun chart series ---
        ts = await self.engine.query(
            timeseries_sql(self.table, top_dim, top_value, secondary_dim, secondary_value, t1)
        )
        chart = {
            "labels": [str(r.get("hour")) for r in ts],
            "overall": [_num(r.get("overall_rate")) for r in ts],
            "culprit": [_num(r.get("culprit_rate")) for r in ts],
        }

        # --- Suggested mitigation (heuristic hint passed to Gemini) ---
        suggested = self._suggest(top_dim, top_value, secondary_dim, secondary_value)

        findings = {
            "metric": spec.get("metric", "rebuffer_rate"),
            "window": f"{t0} to {t1}",
            "baseline_rate": round(baseline, 4),
            "incident_rate": round(incident, 4),
            "rate_multiple": round(incident / baseline, 1) if baseline else None,
            "incident_sessions": incident_sessions,
            "primary_factor": f"{top_dim} = {top_value}",
            "primary_concentration": round(top_info["concentration"], 3),
            "secondary_factor": f"{secondary_dim} = {secondary_value}",
            "culprit_segment_rate": round(_num(best.get("rate")), 4),
            "culprit_segment_sessions": int(_num(best.get("n"))),
            "suggested_action": suggested,
        }

        # --- Stage 6/7: Synthesize (Gemini) ---
        report = await asyncio.to_thread(self.gemini.write_report, incident_text, findings)

        return {
            "report": report,
            "findings": findings,
            "chart": chart,
            "spec": spec,
            "engine": getattr(self.engine, "name", self.cfg.engine),
        }

    @staticmethod
    def _suggest(top_dim, top_value, secondary_dim, secondary_value) -> str:
        for dim, value in ((top_dim, top_value), (secondary_dim, secondary_value)):
            if dim in _MITIGATION:
                return _MITIGATION[dim].format(value=value)
        return f"investigate the {top_dim}={top_value} / {secondary_dim}={secondary_value} segment"
