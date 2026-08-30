"""Fixed SQL templates for the deterministic diagnostic.

The control flow is fixed; only the parameters (time window, dimension names,
selected values) change. Dimension names come from the DIMENSIONS allow-list
below, and values are sourced from prior query results.
"""
from __future__ import annotations

DIMENSIONS = [
    "region",
    "device",
    "os",
    "app_version",
    "cdn_pop",
    "isp",
    "title",
]

METRIC_COLUMN = "rebuffered"


def _escape(value: str) -> str:
    """Escape a string used as a SQL literal."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _scope_where(
    region_hint: str | None = None,
    device_hint: str | None = None,
) -> str:
    """Build optional investigation scope filters."""
    filters = []

    if region_hint:
        filters.append(f"region = '{_escape(region_hint)}'")

    if device_hint:
        filters.append(f"device = '{_escape(device_hint)}'")

    if not filters:
        return ""

    return " AND " + " AND ".join(filters)


def confirm_sql(
    table: str,
    t0: str,
    t1: str,
    region_hint: str | None = None,
    device_hint: str | None = None,
) -> str:
    """Confirm anomaly within the requested investigation scope."""

    scope = _scope_where(region_hint, device_hint)

    return f"""
SELECT
  avgIf(
    {METRIC_COLUMN},
    event_time >= toDateTime('{t0}')
    AND event_time < toDateTime('{t1}')
  ) AS incident_rate,

  avgIf(
    {METRIC_COLUMN},
    event_time >= toDateTime('{t0}') - INTERVAL 7 DAY
    AND event_time < toDateTime('{t0}')
  ) AS baseline_rate,

  countIf(
    event_time >= toDateTime('{t0}')
    AND event_time < toDateTime('{t1}')
  ) AS incident_sessions,

  countIf(
    event_time >= toDateTime('{t0}') - INTERVAL 7 DAY
    AND event_time < toDateTime('{t0}')
  ) AS baseline_sessions

FROM {table}
WHERE 1 = 1
{scope}
""".strip()


def decompose_sql(
    table: str,
    dim: str,
    t0: str,
    t1: str,
    region_hint: str | None = None,
    device_hint: str | None = None,
) -> str:
    """Decompose the anomaly within the requested investigation scope."""

    scope = _scope_where(region_hint, device_hint)

    return f"""
SELECT
  {dim} AS value,
  count() AS n,
  avg({METRIC_COLUMN}) AS rate

FROM {table}

WHERE event_time >= toDateTime('{t0}')
  AND event_time < toDateTime('{t1}')
  {scope}

GROUP BY {dim}
ORDER BY n DESC
""".strip()


def drill_sql(
    table: str,
    top_dim: str,
    top_value: str,
    other_dim: str,
    t0: str,
    t1: str,
    region_hint: str | None = None,
    device_hint: str | None = None,
) -> str:
    """Drill into the strongest dimension within the investigation scope."""

    scope = _scope_where(region_hint, device_hint)
    top_value = _escape(top_value)

    return f"""
SELECT
  {other_dim} AS value,
  count() AS n,
  avg({METRIC_COLUMN}) AS rate

FROM {table}

WHERE event_time >= toDateTime('{t0}')
  AND event_time < toDateTime('{t1}')
  AND {top_dim} = '{top_value}'
  {scope}

GROUP BY {other_dim}
ORDER BY n DESC
""".strip()


def timeseries_sql(
    table: str,
    top_dim: str,
    top_value: str,
    secondary_dim: str,
    secondary_value: str,
    t1: str,
    region_hint: str | None = None,
    device_hint: str | None = None,
) -> str:
    """Hourly culprit rate vs scoped overall rate."""

    scope = _scope_where(region_hint, device_hint)

    top_value = _escape(top_value)
    secondary_value = _escape(secondary_value)

    seg = (
        f"{top_dim} = '{top_value}' "
        f"AND {secondary_dim} = '{secondary_value}'"
    )

    return f"""
SELECT
  toStartOfHour(event_time) AS hour,
  round(avg({METRIC_COLUMN}), 4) AS overall_rate,
  round(avgIf({METRIC_COLUMN}, {seg}), 4) AS culprit_rate,
  countIf({seg}) AS culprit_sessions

FROM {table}

WHERE event_time >= toDateTime('{t1}') - INTERVAL 24 HOUR
  AND event_time < toDateTime('{t1}')
  {scope}

GROUP BY hour
ORDER BY hour
""".strip()

