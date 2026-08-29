"""Compute the incident time window.

For a reliable, repeatable demo the incident is planted in "yesterday evening"
(20:00-23:00). This helper returns that window as ClickHouse-friendly strings.
Pass an explicit date (YYYY-MM-DD) to target a different evening.
"""
from __future__ import annotations

import datetime as dt

FMT = "%Y-%m-%d %H:%M:%S"
START_HOUR = 20
END_HOUR = 23


def default_incident_window(incident_date: str | None = None) -> tuple[str, str]:
    if incident_date:
        day = dt.datetime.strptime(incident_date, "%Y-%m-%d").date()
    else:
        day = (dt.datetime.utcnow() - dt.timedelta(days=1)).date()
    t0 = dt.datetime(day.year, day.month, day.day, START_HOUR, 0, 0)
    t1 = dt.datetime(day.year, day.month, day.day, END_HOUR, 0, 0)
    return t0.strftime(FMT), t1.strftime(FMT)
