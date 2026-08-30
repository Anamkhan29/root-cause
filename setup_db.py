"""One-time database setup for RootCause.

Creates realistic synthetic playback telemetry with:

1. Historical baseline traffic distributed across all dimensions.
2. Normal traffic during the incident window.
3. A concentrated anomaly with one identifiable root-cause dimension.

Examples:

    python setup_db.py --incident-date 2026-08-29

    python setup_db.py \
        --baseline 10000000 \
        --incident 200000 \
        --incident-date 2026-08-29

    python setup_db.py \
        --incidents 3 \
        --incident-date 2026-08-29
"""

from __future__ import annotations

import argparse
import random

from dotenv import load_dotenv

load_dotenv()

import clickhouse_connect

from src.config import Config
from src.window import default_incident_window


# ============================================================
# DIMENSION POOLS
# ============================================================

REGIONS = [
    "Northeast",
    "Southeast",
    "Midwest",
    "West",
    "Southwest",
]

DEVICES = [
    "Smart TV",
    "Mobile",
    "Web",
    "Tablet",
    "Console",
]

OSES = [
    "tvOS",
    "Android",
    "iOS",
    "Windows",
    "Roku",
]

APPS = [
    "4.1.0",
    "4.1.5",
    "4.2.0",
    "4.2.1",
    "4.3.0",
]

CDNS = [
    "LAX",
    "ATL",
    "ORD",
    "JFK",
    "DFW",
    "SEA",
]

ISPS = [
    "Comcast",
    "Verizon",
    "ATT",
    "Spectrum",
    "Cox",
]

TITLES = [
    "Aurora Nights",
    "The Long Haul",
    "Reef",
    "Skyline",
    "Undercurrent",
    "Paper Moon",
]

ERRCODES = [
    "2000",
    "2100",
    "3050",
    "4004",
]


# ============================================================
# SQL ARRAY HELPERS
# ============================================================

REGIONS_SQL = str(REGIONS).replace('"', "'")
DEVICES_SQL = str(DEVICES).replace('"', "'")
OSES_SQL = str(OSES).replace('"', "'")
APPS_SQL = str(APPS).replace('"', "'")
CDNS_SQL = str(CDNS).replace('"', "'")
ISPS_SQL = str(ISPS).replace('"', "'")
TITLES_SQL = str(TITLES).replace('"', "'")
ERRCODES_SQL = str(ERRCODES).replace('"', "'")


# ============================================================
# INCIDENT SCENARIOS
# ============================================================

ROOT_CAUSE_TYPES = [
    "cdn_pop",
    "app_version",
    "isp",
    "device",
]


def make_scenarios(count: int) -> list[dict]:
    """Create distinct synthetic incident scenarios."""

    scenarios = []

    used = set()

    while len(scenarios) < count:

        root_type = random.choice(ROOT_CAUSE_TYPES)

        region = random.choice(REGIONS)

        if root_type == "cdn_pop":
            root_value = random.choice(CDNS)

        elif root_type == "app_version":
            root_value = random.choice(APPS)

        elif root_type == "isp":
            root_value = random.choice(ISPS)

        elif root_type == "device":
            root_value = random.choice(DEVICES)

        else:
            root_value = random.choice(CDNS)

        signature = (
            region,
            root_type,
            root_value,
        )

        if signature in used:
            continue

        used.add(signature)

        scenario = {
            "region": region,
            "root_dimension": root_type,
            "root_value": root_value,

            # Anomaly severity
            "rebuffer_rate": random.randint(25, 55),

            # Playback error rate
            "error_rate": random.randint(3, 15),
        }

        scenarios.append(scenario)

    return scenarios


# ============================================================
# BASELINE TRAFFIC
# ============================================================

def baseline_insert(
    table: str,
    n: int,
    t0: str,
) -> str:
    """Generate baseline traffic for the 7 days before incident."""

    return f"""
INSERT INTO {table}
(
    event_time,
    session_id,
    user_id,
    country,
    region,
    device,
    os,
    app_version,
    cdn_pop,
    isp,
    title,
    watch_seconds,
    rebuffered,
    rebuffer_ms,
    errored,
    error_code
)

SELECT

    toDateTime('{t0}')
        - toIntervalSecond(
            1 + rand() % (7 * 24 * 3600)
        ) AS event_time,

    generateUUIDv4() AS session_id,

    rand64() % 5000000 AS user_id,

    'US' AS country,

    {REGIONS_SQL}[
        (rand() % {len(REGIONS)}) + 1
    ] AS region,

    {DEVICES_SQL}[
        (rand() % {len(DEVICES)}) + 1
    ] AS device,

    {OSES_SQL}[
        (rand() % {len(OSES)}) + 1
    ] AS os,

    {APPS_SQL}[
        (rand() % {len(APPS)}) + 1
    ] AS app_version,

    {CDNS_SQL}[
        (rand() % {len(CDNS)}) + 1
    ] AS cdn_pop,

    {ISPS_SQL}[
        (rand() % {len(ISPS)}) + 1
    ] AS isp,

    {TITLES_SQL}[
        (rand() % {len(TITLES)}) + 1
    ] AS title,

    rand() % 7200 AS watch_seconds,

    toUInt8(
        rand() % 100 < 3
    ) AS rebuffered,

    if(
        rand() % 100 < 3,
        rand() % 8000 + 500,
        0
    ) AS rebuffer_ms,

    toUInt8(
        rand() % 100 < 1
    ) AS errored,

    if(
        rand() % 100 < 1,
        {ERRCODES_SQL}[
            (rand() % {len(ERRCODES)}) + 1
        ],
        ''
    ) AS error_code

FROM numbers({n})
""".strip()


# ============================================================
# NORMAL INCIDENT WINDOW TRAFFIC
# ============================================================

def normal_incident_insert(
    table: str,
    n: int,
    t0: str,
) -> str:
    """Generate normal mixed traffic during the incident window."""

    return f"""
INSERT INTO {table}
(
    event_time,
    session_id,
    user_id,
    country,
    region,
    device,
    os,
    app_version,
    cdn_pop,
    isp,
    title,
    watch_seconds,
    rebuffered,
    rebuffer_ms,
    errored,
    error_code
)

SELECT

    toDateTime('{t0}')
        + toIntervalSecond(
            rand() % (3 * 3600)
        ) AS event_time,

    generateUUIDv4() AS session_id,

    rand64() % 5000000 AS user_id,

    'US' AS country,

    {REGIONS_SQL}[
        (rand() % {len(REGIONS)}) + 1
    ] AS region,

    {DEVICES_SQL}[
        (rand() % {len(DEVICES)}) + 1
    ] AS device,

    {OSES_SQL}[
        (rand() % {len(OSES)}) + 1
    ] AS os,

    {APPS_SQL}[
        (rand() % {len(APPS)}) + 1
    ] AS app_version,

    {CDNS_SQL}[
        (rand() % {len(CDNS)}) + 1
    ] AS cdn_pop,

    {ISPS_SQL}[
        (rand() % {len(ISPS)}) + 1
    ] AS isp,

    {TITLES_SQL}[
        (rand() % {len(TITLES)}) + 1
    ] AS title,

    rand() % 7200 AS watch_seconds,

    toUInt8(
        rand() % 100 < 3
    ) AS rebuffered,

    if(
        rand() % 100 < 3,
        rand() % 8000 + 500,
        0
    ) AS rebuffer_ms,

    toUInt8(
        rand() % 100 < 1
    ) AS errored,

    if(
        rand() % 100 < 1,
        {ERRCODES_SQL}[
            (rand() % {len(ERRCODES)}) + 1
        ],
        ''
    ) AS error_code

FROM numbers({n})
""".strip()


# ============================================================
# ANOMALY INSERT
# ============================================================

def incident_insert(
    table: str,
    n: int,
    t0: str,
    scenario: dict,
) -> str:
    """Insert anomaly traffic.

    Region is fixed so natural-language region investigation works.

    Only ONE additional dimension is fixed as the actual culprit.
    All other dimensions remain randomized.

    This prevents every dimension from having 100% concentration.
    """

    root_dimension = scenario["root_dimension"]
    root_value = scenario["root_value"]

    # Default randomized expressions
    device_expr = (
        f"{DEVICES_SQL}[(rand() % {len(DEVICES)}) + 1]"
    )

    app_expr = (
        f"{APPS_SQL}[(rand() % {len(APPS)}) + 1]"
    )

    cdn_expr = (
        f"{CDNS_SQL}[(rand() % {len(CDNS)}) + 1]"
    )

    isp_expr = (
        f"{ISPS_SQL}[(rand() % {len(ISPS)}) + 1]"
    )

    # Make exactly one dimension the culprit
    if root_dimension == "device":
        device_expr = f"'{root_value}'"

    elif root_dimension == "app_version":
        app_expr = f"'{root_value}'"

    elif root_dimension == "cdn_pop":
        cdn_expr = f"'{root_value}'"

    elif root_dimension == "isp":
        isp_expr = f"'{root_value}'"

    return f"""
INSERT INTO {table}
(
    event_time,
    session_id,
    user_id,
    country,
    region,
    device,
    os,
    app_version,
    cdn_pop,
    isp,
    title,
    watch_seconds,
    rebuffered,
    rebuffer_ms,
    errored,
    error_code
)

SELECT

    toDateTime('{t0}')
        + toIntervalSecond(
            rand() % (3 * 3600)
        ) AS event_time,

    generateUUIDv4() AS session_id,

    rand64() % 5000000 AS user_id,

    'US' AS country,

    '{scenario["region"]}' AS region,

    {device_expr} AS device,

    {OSES_SQL}[
        (rand() % {len(OSES)}) + 1
    ] AS os,

    {app_expr} AS app_version,

    {cdn_expr} AS cdn_pop,

    {isp_expr} AS isp,

    {TITLES_SQL}[
        (rand() % {len(TITLES)}) + 1
    ] AS title,

    rand() % 3600 AS watch_seconds,

    toUInt8(
        rand() % 100 < {scenario["rebuffer_rate"]}
    ) AS rebuffered,

    if(
        rand() % 100 < {scenario["rebuffer_rate"]},
        rand() % 15000 + 2000,
        0
    ) AS rebuffer_ms,

    toUInt8(
        rand() % 100 < {scenario["error_rate"]}
    ) AS errored,

    if(
        rand() % 100 < {scenario["error_rate"]},
        '5000',
        ''
    ) AS error_code

FROM numbers({n})
""".strip()


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    ap = argparse.ArgumentParser(
        description=(
            "Set up ClickHouse with realistic "
            "synthetic playback telemetry"
        )
    )

    ap.add_argument(
        "--baseline",
        type=int,
        default=30_000_000,
        help="historical baseline session count",
    )

    ap.add_argument(
        "--normal-incident",
        type=int,
        default=500_000,
        help="normal sessions during incident window",
    )

    ap.add_argument(
        "--incident",
        type=int,
        default=200_000,
        help="anomalous sessions per incident",
    )

    ap.add_argument(
        "--incidents",
        type=int,
        default=1,
        help="number of distinct synthetic incidents",
    )

    ap.add_argument(
        "--incident-date",
        default=None,
        help=(
            "YYYY-MM-DD of incident evening "
            "(default: yesterday)"
        ),
    )

    args = ap.parse_args()

    cfg = Config.from_env()

    t0, t1 = default_incident_window(
        args.incident_date
    )

    client = clickhouse_connect.get_client(
        host=cfg.ch_host,
        port=cfg.ch_port,
        username=cfg.ch_user,
        password=cfg.ch_password,
        secure=cfg.ch_secure,
        database=cfg.ch_database,
    )

    # --------------------------------------------------------
    # Reset table
    # --------------------------------------------------------

    print()
    print("Resetting dataset...")

    client.command(
        f"DROP TABLE IF EXISTS {cfg.table}"
    )

    with open(
        "schema.sql",
        "r",
        encoding="utf-8",
    ) as fh:
        client.command(fh.read())

    print(
        f"Table '{cfg.table}' ready."
    )

    # --------------------------------------------------------
    # Historical baseline
    # --------------------------------------------------------

    print()
    print(
        f"Inserting "
        f"{args.baseline:,} historical baseline sessions..."
    )

    client.command(
        baseline_insert(
            cfg.table,
            args.baseline,
            t0,
        )
    )

    # --------------------------------------------------------
    # Normal incident traffic
    # --------------------------------------------------------

    print()
    print(
        f"Inserting "
        f"{args.normal_incident:,} normal sessions "
        f"during incident window..."
    )

    client.command(
        normal_incident_insert(
            cfg.table,
            args.normal_incident,
            t0,
        )
    )

    # --------------------------------------------------------
    # Generate anomalies
    # --------------------------------------------------------

    scenarios = make_scenarios(
        args.incidents
    )

    print()
    print(
        f"Generating "
        f"{args.incidents} synthetic incident(s)..."
    )

    for i, scenario in enumerate(
        scenarios,
        start=1,
    ):

        print()
        print(
            f"INCIDENT {i}"
        )

        print(
            f"  Region:       "
            f"{scenario['region']}"
        )

        print(
            f"  Root cause:   "
            f"{scenario['root_dimension']} = "
            f"{scenario['root_value']}"
        )

        print(
            f"  Rebuffer:     "
            f"{scenario['rebuffer_rate']}%"
        )

        print(
            f"  Error rate:   "
            f"{scenario['error_rate']}%"
        )

        client.command(
            incident_insert(
                cfg.table,
                args.incident,
                t0,
                scenario,
            )
        )

    # --------------------------------------------------------
    # Final stats
    # --------------------------------------------------------

    total = client.query(
        f"SELECT count() FROM {cfg.table}"
    ).result_rows[0][0]

    print()
    print("=" * 60)

    print(
        f"Done. {total:,} total rows."
    )

    print(
        f"Incident window: "
        f"{t0} .. {t1}"
    )

    print()
    print("TEST COMMANDS")
    print("=" * 60)

    for scenario in scenarios:

        region = scenario["region"]

        print()

        print(
            f'python main.py '
            f'"Rebuffering spiked last night in the {region}" '
            f'--incident-date {args.incident_date}'
        )

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()