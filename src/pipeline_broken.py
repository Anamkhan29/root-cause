"""The deterministic diagnostic pipeline — RootCause's investigation brain.

Control flow is deterministic:

1. Parse incident intent
2. Resolve investigation scope
3. Confirm anomaly
4. Decompose across dimensions
5. Rank the strongest excess signal
6. Drill into an interacting factor
7. Build evidence and ask Gemini to narrate it

The LLM never decides the culprit. ClickHouse evidence does.
"""

from __future__ import annotations

import asyncio
import re

from .config import Config
from .gemini import GeminiClient
from .queries import (
DIMENSIONS,
confirm_sql,
decompose_sql,
drill_sql,
timeseries_sql,
)
from .scoring import add_scores, concentration, total_excess

ANOMALY_THRESHOLD = 1.5

_MITIGATION = {
"app_version": "roll back app version {value}",
"cdn_pop": "drain / reroute traffic away from CDN PoP {value}",
"os": "hold rollout on {value} and investigate the client build",
"isp": "open a peering / routing ticket with {value}",
}

KNOWN_REGIONS = [
"Northeast",
"Southeast",
"Midwest",
"Southwest",
"West",
]

KNOWN_DEVICES = [
"Smart TV",
"Mobile",
"Web",
"Tablet",
"Console",
]

def make_engine(cfg: Config):
"""Create the configured ClickHouse engine."""
if cfg.engine == "mcp":
from .clickhouse_mcp import MCPEngine
return MCPEngine(cfg)

```
from .clickhouse_client import DirectEngine
return DirectEngine(cfg)
```

def _num(value) -> float:
"""Safely convert ClickHouse/Gemini values to float."""
try:
return float(value)
except (TypeError, ValueError):
return 0.0

def _clean(rows: list[dict]) -> list[dict]:
"""Normalise engine rows."""
cleaned = []

```
for row in rows:
    cleaned.append(
        {
            "value": str(row.get("value")),
            "n": int(_num(row.get("n"))),
            "rate": _num(row.get("rate")),
        }
    )

return cleaned
```

def _match_known_value(
text: str,
values: list[str],
) -> str | None:
"""Case-insensitive match of known dimension values in incident text."""
lowered = text.lower()

```
for value in values:
    pattern = r"\b" + re.escape(value.lower()) + r"\b"

    if re.search(pattern, lowered):
        return value

return None
```

def _resolve_scope(
incident_text: str,
spec: dict,
) -> tuple[str | None, str | None]:
"""Resolve scope deterministically.

```
Gemini hints are useful, but the incident text is authoritative when
a known region/device is explicitly mentioned.
"""

region_hint = _match_known_value(
    incident_text,
    KNOWN_REGIONS,
)

device_hint = _match_known_value(
    incident_text,
    KNOWN_DEVICES,
)

# Fall back to Gemini only if deterministic matching found nothing.
if not region_hint:
    candidate = spec.get("region_hint")

    if candidate:
        region_hint = _match_known_value(
            str(candidate),
            KNOWN_REGIONS,
        )

if not device_hint:
    candidate = spec.get("device_hint")

    if candidate:
        device_hint = _match_known_value(
            str(candidate),
            KNOWN_DEVICES,
        )

return region_hint, device_hint
```

class DiagnosticPipeline:
def **init**(
self,
cfg: Config,
engine,
gemini: GeminiClient,
):
self.cfg = cfg
self.engine = engine
self.gemini = gemini
self.table = cfg.table

```
async def run(
    self,
    incident_text: str,
    t0: str,
    t1: str,
) -> dict:

    # =========================================================
    # STAGE 1 — PARSE INCIDENT
    # =========================================================

    spec = await asyncio.to_thread(
        self.gemini.parse_incident,
        incident_text,
    )

    metric = spec.get(
        "metric",
        "rebuffer_rate",
    )

    # Resolve explicit scope from the user's actual incident text.
    region_hint, device_hint = _resolve_scope(
        incident_text,
        spec,
    )

    # Keep the resolved scope visible to the API/UI.
    spec["region_hint"] = region_hint
    spec["device_hint"] = device_hint

    scope_parts = []

    if region_hint:
        scope_parts.append(
            f"region={region_hint}"
        )

    if device_hint:
        scope_parts.append(
            f"device={device_hint}"
        )

    scope = (
        ", ".join(scope_parts)
        if scope_parts
        else "global"
    )

    # =========================================================
    # STAGE 2 — CONFIRM ANOMALY
    # =========================================================

    conf_rows = await self.engine.query(
        confirm_sql(
            self.table,
            t0,
            t1,
            region_hint,
            device_hint,
        )
    )

    conf = conf_rows[0] if conf_rows else {}

    baseline = _num(
        conf.get("baseline_rate")
    )

    incident = _num(
        conf.get("incident_rate")
    )

    incident_sessions = int(
        _num(conf.get("incident_sessions"))
    )

    baseline_sessions = int(
        _num(conf.get("baseline_sessions"))
    )

    # A zero baseline does NOT mean "no anomaly".
    #
    # If there is historical data but the metric was previously zero,
    # and the incident rate is now positive, this is a newly emerged
    # anomaly.
    if baseline > 0:
        rate_multiple = incident / baseline
    else:
        rate_multiple = None

    # =========================================================
    # DATA AVAILABILITY GATE
    # =========================================================

    if (
        incident_sessions == 0
        or baseline_sessions == 0
    ):

        findings = {
            "metric": metric,
            "window": f"{t0} to {t1}",
            "scope": scope,
            "baseline_rate": round(
                baseline,
                4,
            ),
            "incident_rate": round(
                incident,
                4,
            ),
            "rate_multiple": (
                round(rate_multiple, 1)
                if rate_multiple is not None
                else None
            ),
            "incident_sessions": incident_sessions,
            "baseline_sessions": baseline_sessions,
            "status": "insufficient_data",
            "reason": (
                "Not enough sessions were available "
                "for a reliable comparison."
            ),
            "region_hint": region_hint,
            "device_hint": device_hint,
        }

        report = (
            "### Investigation Inconclusive\n\n"
            f"**Scope:** `{scope}`\n\n"
            "There was insufficient historical or incident-window "
            "data to confirm a statistically meaningful anomaly."
        )

        return {
            "report": report,
            "findings": findings,
            "chart": {
                "labels": [],
                "overall": [],
                "culprit": [],
            },
            "spec": spec,
            "engine": getattr(
                self.engine,
                "name",
                self.cfg.engine,
            ),
        }

    # =========================================================
    # ANOMALY GATE
    # =========================================================

    anomaly_confirmed = False

    # Normal case: compare against historical baseline.
    if rate_multiple is not None:
        anomaly_confirmed = (
            rate_multiple >= ANOMALY_THRESHOLD
        )

    # New anomaly case: historical baseline was zero but
    # the incident window is clearly non-zero.
    else:
        anomaly_confirmed = incident > 0

    if not anomaly_confirmed:

        findings = {
            "metric": metric,
            "window": f"{t0} to {t1}",
            "scope": scope,
            "baseline_rate": round(
                baseline,
                4,
            ),
            "incident_rate": round(
                incident,
                4,
            ),
            "rate_multiple": (
                round(rate_multiple, 1)
                if rate_multiple is not None
                else None
            ),
            "incident_sessions": incident_sessions,
            "baseline_sessions": baseline_sessions,
            "status": "no_anomaly",
            "reason": (
                "Incident rate did not exceed "
                "the anomaly threshold."
            ),
            "region_hint": region_hint,
            "device_hint": device_hint,
        }

        change_text = (
            f"{rate_multiple:.1f}x baseline"
            if rate_multiple is not None
            else "no measurable increase"
        )

        report = (
            "### No Active Anomaly Confirmed\n\n"
            f"**Investigation scope:** `{scope}`\n\n"
            f"**Baseline:** {baseline:.2%}\n\n"
            f"**Incident window:** {incident:.2%}\n\n"
            f"**Change:** {change_text}\n\n"
            "The observed incident-window metric does not exceed "
            f"the configured anomaly threshold of "
            f"{ANOMALY_THRESHOLD:.1f}x baseline.\n\n"
            "RootCause will not assign a culprit without sufficient "
            "evidence."
        )

        return {
            "report": report,
            "findings": findings,
            "chart": {
                "labels": [],
                "overall": [],
                "culprit": [],
            },
            "spec": spec,
            "engine": getattr(
                self.engine,
                "name",
                self.cfg.engine,
            ),
        }

    # =========================================================
    # STAGE 3 — DECOMPOSE ACROSS DIMENSIONS
    # =========================================================

    dim_results: dict[str, dict] = {}

    for dim in DIMENSIONS:

        rows = _clean(
            await self.engine.query(
                decompose_sql(
                    self.table,
                    dim,
                    t0,
                    t1,
                    region_hint,
                    device_hint,
                )
            )
        )

        add_scores(
            rows,
            baseline,
        )

        conc, top = concentration(
            rows
        )

        dim_results[dim] = {
            "rows": rows,
            "concentration": conc,
            "top": top,
            "total_excess": total_excess(
                rows
            ),
        }

    # =========================================================
    # STAGE 4 — RANK ROOT CAUSE DIMENSION
    # =========================================================

    # Do not select a dimension already explicitly supplied as
    # investigation scope. For example:
    #
    # "spike in West"
    #
    # region=West is the scope, not automatically the explanation.
    excluded_dims = set()

    if region_hint:
        excluded_dims.add("region")

    if device_hint:
        excluded_dims.add("device")

    candidate_dims = [
        (dim, info)
        for dim, info in dim_results.items()
        if dim not in excluded_dims
        and info["top"] is not None
    ]

    # If all dimensions were excluded, fall back to all.
    if not candidate_dims:
        candidate_dims = [
            (dim, info)
            for dim, info in dim_results.items()
            if info["top"] is not None
        ]

    def dimension_score(item):
        """
        Rank dimensions by explanatory power.

        A strong root-cause dimension should have:
        - a high-impact anomalous segment
        - strong concentration of excess signal
        """

        _, info = item

        impact = float(
            info.get("total_excess") or 0
        )

        concentration_score = float(
            info.get("concentration") or 0
        )

        top = info.get("top") or {}

        top_excess = float(
            top.get("excess") or 0
        )

        return (
            top_excess * concentration_score,
            impact,
            concentration_score,
        )


    ranked = sorted(
        candidate_dims,
        key=dimension_score,
        reverse=True,
    )

    if not ranked:

        findings = {
            "metric": metric,
            "window": f"{t0} to {t1}",
            "scope": scope,
            "baseline_rate": round(
                baseline,
                4,
            ),
            "incident_rate": round(
                incident,
                4,
            ),
            "rate_multiple": (
                round(rate_multiple, 1)
                if rate_multiple is not None
                else None
            ),
            "incident_sessions": incident_sessions,
            "status": "anomaly_confirmed_no_culprit",
            "reason": (
                "An anomaly was confirmed, but no dimension "
                "contained enough evidence for attribution."
            ),
            "region_hint": region_hint,
            "device_hint": device_hint,
        }

        report = (
            "### Anomaly Confirmed\n\n"
            f"**Scope:** `{scope}`\n\n"
            "The incident window differs materially from the "
            "historical baseline, but RootCause could not attribute "
            "the spike to a specific dimension with sufficient "
            "evidence."
        )

        return {
            "report": report,
            "findings": findings,
            "chart": {
                "labels": [],
                "overall": [],
                "culprit": [],
            },
            "spec": spec,
            "engine": getattr(
                self.engine,
                "name",
                self.cfg.engine,
            ),
        }

    top_dim, top_info = ranked[0]

    top_value = (
        top_info["top"]["value"]
        if top_info["top"]
        else "unknown"
    )

    # =========================================================
    # STAGE 5 — DRILL INTO INTERACTING FACTORS
    # =========================================================

    best = None

    for other_dim in DIMENSIONS:

        if other_dim == top_dim:
            continue

        rows = _clean(
            await self.engine.query(
                drill_sql(
                    self.table,
                    top_dim,
                    top_value,
                    other_dim,
                    t0,
                    t1,
                    region_hint,
                    device_hint,
                )
            )
        )

        add_scores(
            rows,
            baseline,
        )

        conc, top = concentration(
            rows
        )

                if top:
                    candidate_score = (
                        float(top.get("excess") or 0)
                        * float(conc or 0)
                    )

                    current_score = (
                        float(best.get("excess") or 0)
                        * float(best.get("concentration") or 0)
                        if best
                        else -1
                    )

                    if candidate_score > current_score:
                        best = {
                            "dim": other_dim,
                            "concentration": conc,
                            "score": candidate_score,
                            **top,
                        }

    if best is None:

        best = {
            "dim": top_dim,
            "value": top_value,
            "rate": incident,
            "n": incident_sessions,
            "concentration": 1.0,
            "excess": 0.0,
        }

    secondary_dim = best["dim"]
    secondary_value = best["value"]

    # =========================================================
    # STAGE 6 — BUILD SMOKING-GUN TIME SERIES
    # =========================================================

    ts = await self.engine.query(
        timeseries_sql(
            self.table,
            top_dim,
            top_value,
            secondary_dim,
            secondary_value,
            t1,
        )
    )

    chart = {
        "labels": [
            str(row.get("hour"))
            for row in ts
        ],
        "overall": [
            _num(row.get("overall_rate"))
            for row in ts
        ],
        "culprit": [
            (
                _num(row.get("culprit_rate"))
                if row.get("culprit_rate") is not None
                else None
            )
            for row in ts
        ],
    }

    # =========================================================
    # STAGE 7 — SYNTHESIZE EVIDENCE
    # =========================================================

    suggested = self._suggest(
        top_dim,
        top_value,
        secondary_dim,
        secondary_value,
    )

    findings = {
        "metric": metric,
        "window": f"{t0} to {t1}",
        "scope": scope,

        "baseline_rate": round(
            baseline,
            4,
        ),

        "incident_rate": round(
            incident,
            4,
        ),

        "rate_multiple": (
            round(rate_multiple, 1)
            if rate_multiple is not None
            else None
        ),

        "incident_sessions": incident_sessions,

        "primary_factor": (
            f"{top_dim} = {top_value}"
        ),

        "primary_concentration": round(
            top_info["concentration"],
            3,
        ),

        "secondary_factor": (
            f"{secondary_dim} = {secondary_value}"
        ),

        "culprit_segment_rate": round(
            _num(best.get("rate")),
            4,
        ),

        "culprit_segment_sessions": int(
            _num(best.get("n"))
        ),

        "suggested_action": suggested,

        "status": "anomaly_confirmed",

        "region_hint": region_hint,
        "device_hint": device_hint,
    }

    report = await asyncio.to_thread(
        self.gemini.write_report,
        incident_text,
        findings,
    )

    return {
        "report": report,
        "findings": findings,
        "chart": chart,
        "spec": spec,
        "engine": getattr(
            self.engine,
            "name",
            self.cfg.engine,
        ),
    }

@staticmethod
def _suggest(
    top_dim,
    top_value,
    secondary_dim,
    secondary_value,
) -> str:

    for dim, value in (
        (top_dim, top_value),
        (secondary_dim, secondary_value),
    ):

        if dim in _MITIGATION:
            return _MITIGATION[dim].format(
                value=value
            )

    return (
        f"investigate the {top_dim}={top_value} / "
        f"{secondary_dim}={secondary_value} segment"
    )