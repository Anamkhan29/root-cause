"""Fixed SQL templates for the deterministic diagnostic.

The control flow is fixed; only the parameters (time window, dimension names,
selected values) change. Dimension names come from the DIMENSIONS allow-list
below, and values are sourced from prior query results, so these templates are
not exposed to free-form user input.
"""
from __future__ import annotations

# Candidate dimensions the agent decomposes the anomaly across.
DIMENSIONS = ["region", "device", "os", "app_version", "cdn_pop", "isp", "title"]

# The KPI under investigation for this build.
METRIC_COLUMN = "rebuffered"  # 1 if the session experienced a rebuffer


def confirm_sql(table: str, t0: str, t1: str) -> str:
    """Stage 2 — confirm the anomaly: incident-window rate vs the prior 7-day baseline."""
    return f"""
SELECT
  avgIf({METRIC_COLUMN}, event_time >= toDateTime('{t0}') AND event_time < toDateTime('{t1}'))                                   AS incident_rate,
  avgIf({METRIC_COLUMN}, event_time >= toDateTime('{t0}') - INTERVAL 7 DAY AND event_time < toDateTime('{t0}'))                  AS baseline_rate,
  countIf(event_time >= toDateTime('{t0}') AND event_time < toDateTime('{t1}'))                                                  AS incident_sessions,
  countIf(event_time >= toDateTime('{t0}') - INTERVAL 7 DAY AND event_time < toDateTime('{t0}'))                                 AS baseline_sessions
FROM {table}
""".strip()


def decompose_sql(table: str, dim: str, t0: str, t1: str) -> str:
    """Stage 3 — decompose: per-value count and metric rate within the incident window."""
    return f"""
SELECT {dim} AS value, count() AS n, avg({METRIC_COLUMN}) AS rate
FROM {table}
WHERE event_time >= toDateTime('{t0}') AND event_time < toDateTime('{t1}')
GROUP BY {dim}
ORDER BY n DESC
""".strip()


def drill_sql(table: str, top_dim: str, top_value: str, other_dim: str, t0: str, t1: str) -> str:
    """Stage 5 — drill: within the top culprit value, break the anomaly down by another dimension."""
    return f"""
SELECT {other_dim} AS value, count() AS n, avg({METRIC_COLUMN}) AS rate
FROM {table}
WHERE event_time >= toDateTime('{t0}') AND event_time < toDateTime('{t1}')
  AND {top_dim} = '{top_value}'
GROUP BY {other_dim}
ORDER BY n DESC
""".strip()


def timeseries_sql(table: str, top_dim: str, top_value: str,
                   secondary_dim: str, secondary_value: str, t1: str) -> str:
    """Smoking-gun chart — hourly rate for the culprit segment vs overall, last 24h."""
    seg = f"{top_dim} = '{top_value}' AND {secondary_dim} = '{secondary_value}'"
    return f"""
SELECT
  toStartOfHour(event_time)                                       AS hour,
  round(avg({METRIC_COLUMN}), 4)                                  AS overall_rate,
  round(avgIf({METRIC_COLUMN}, {seg}), 4)                         AS culprit_rate,
  countIf({seg})                                                  AS culprit_sessions
FROM {table}
WHERE event_time >= toDateTime('{t1}') - INTERVAL 24 HOUR AND event_time < toDateTime('{t1}')
GROUP BY hour
ORDER BY hour
""".strip()
