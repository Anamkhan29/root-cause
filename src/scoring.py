"""Attribution math for the Rank and Drill stages.

For a dimension value v during the incident window, with n_v sessions, incident
rate r_v, and baseline rate r_bar:

  excess    E_v = n_v * max(r_v - r_bar, 0)          # events attributable to v
  lift          = (r_v - r_bar) / r_bar               # relative severity
  score(v)      = lift * log(1 + n_v)                 # severity weighted by volume

Concentration of a dimension D = max_v(E_v) / sum_v(E_v). A value near 1 means the
anomaly lives in a single value (a clear culprit); a low value means it is spread
out and the agent should keep decomposing.
"""
from __future__ import annotations

import math


def add_scores(rows: list[dict], baseline_rate: float) -> list[dict]:
    for r in rows:
        n = r["n"]
        rate = r["rate"]
        r["excess"] = n * max(rate - baseline_rate, 0.0)
        r["lift"] = (rate - baseline_rate) / baseline_rate if baseline_rate > 0 else 0.0
        r["score"] = r["lift"] * math.log(1 + n)
    return rows


def concentration(rows: list[dict]) -> tuple[float, dict | None]:
    total = sum(r["excess"] for r in rows)
    if total <= 0 or not rows:
        return 0.0, None
    top = max(rows, key=lambda r: r["excess"])
    return top["excess"] / total, top


def total_excess(rows: list[dict]) -> float:
    return sum(r["excess"] for r in rows)
