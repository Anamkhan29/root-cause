"""One-time database setup.

Creates the playback_events table and populates it with a large synthetic event
stream plus one deliberately planted anomaly (app_version 4.2.1 on CDN PoP LAX in
the Southeast, during yesterday evening's window). Prints the incident window and
a ready-to-run command.

Usage:
  python setup_db.py                    # ~30M baseline + 200k incident rows, yesterday's window
  python setup_db.py --baseline 10000000 --incident 150000 --incident-date 2026-08-29
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()

import clickhouse_connect

from src.config import Config
from src.window import default_incident_window

# Dimension pools for the synthetic generator (kept in sync with the story).
REGIONS = "['Northeast','Southeast','Midwest','West','Southwest']"
DEVICES = "['Smart TV','Mobile','Web','Tablet','Console']"
OSES = "['tvOS','Android','iOS','Windows','Roku']"
APPS = "['4.1.0','4.1.5','4.2.0','4.2.1','4.3.0']"
CDNS = "['LAX','ATL','ORD','JFK','DFW','SEA']"
ISPS = "['Comcast','Verizon','ATT','Spectrum','Cox']"
TITLES = "['Aurora Nights','The Long Haul','Reef','Skyline','Undercurrent','Paper Moon']"
ERRCODES = "['2000','2100','3050','4004']"

# The planted culprit.
BAD_REGION = "Southeast"
BAD_APP = "4.2.1"
BAD_CDN = "LAX"
WINDOW_SECONDS = 3 * 3600


def baseline_insert(table: str, n: int) -> str:
    return f"""
INSERT INTO {table}
(event_time, session_id, user_id, country, region, device, os, app_version, cdn_pop, isp, title,
 watch_seconds, rebuffered, rebuffer_ms, errored, error_code)
SELECT
  now() - toIntervalSecond(rand() % (7*24*3600))              AS event_time,
  generateUUIDv4()                                            AS session_id,
  rand64() % 5000000                                          AS user_id,
  'US'                                                        AS country,
  {REGIONS}[(rand() % 5) + 1]                                 AS region,
  {DEVICES}[(rand() % 5) + 1]                                 AS device,
  {OSES}[(rand() % 5) + 1]                                    AS os,
  {APPS}[(rand() % 5) + 1]                                    AS app_version,
  {CDNS}[(rand() % 6) + 1]                                    AS cdn_pop,
  {ISPS}[(rand() % 5) + 1]                                    AS isp,
  {TITLES}[(rand() % 6) + 1]                                  AS title,
  rand() % 7200                                               AS watch_seconds,
  toUInt8(rand() % 100 < 3)                                   AS rebuffered,
  if(rand() % 100 < 3, rand() % 8000 + 500, 0)               AS rebuffer_ms,
  toUInt8(rand() % 100 < 1)                                   AS errored,
  if(rand() % 100 < 1, {ERRCODES}[(rand() % 4) + 1], '')     AS error_code
FROM numbers({n})
""".strip()


def incident_insert(table: str, n: int, t0: str) -> str:
    return f"""
INSERT INTO {table}
(event_time, session_id, user_id, country, region, device, os, app_version, cdn_pop, isp, title,
 watch_seconds, rebuffered, rebuffer_ms, errored, error_code)
SELECT
  toDateTime('{t0}') + toIntervalSecond(rand() % {WINDOW_SECONDS})  AS event_time,
  generateUUIDv4()                                                  AS session_id,
  rand64() % 5000000                                                AS user_id,
  'US'                                                              AS country,
  '{BAD_REGION}'                                                    AS region,
  {DEVICES}[(rand() % 5) + 1]                                       AS device,
  {OSES}[(rand() % 5) + 1]                                          AS os,
  '{BAD_APP}'                                                       AS app_version,
  '{BAD_CDN}'                                                       AS cdn_pop,
  {ISPS}[(rand() % 5) + 1]                                          AS isp,
  {TITLES}[(rand() % 6) + 1]                                        AS title,
  rand() % 3600                                                     AS watch_seconds,
  toUInt8(rand() % 100 < 60)                                        AS rebuffered,
  if(rand() % 100 < 60, rand() % 15000 + 2000, 0)                  AS rebuffer_ms,
  toUInt8(rand() % 100 < 2)                                         AS errored,
  ''                                                                AS error_code
FROM numbers({n})
""".strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Set up ClickHouse with synthetic playback data")
    ap.add_argument("--baseline", type=int, default=30_000_000, help="baseline session count")
    ap.add_argument("--incident", type=int, default=200_000, help="planted incident session count")
    ap.add_argument("--incident-date", default=None, help="YYYY-MM-DD of the incident evening (default: yesterday)")
    args = ap.parse_args()

    cfg = Config.from_env()
    t0, t1 = default_incident_window(args.incident_date)

    client = clickhouse_connect.get_client(
        host=cfg.ch_host, port=cfg.ch_port, username=cfg.ch_user,
        password=cfg.ch_password, secure=cfg.ch_secure, database=cfg.ch_database,
    )

    with open("schema.sql", "r", encoding="utf-8") as fh:
        client.command(fh.read())
    print(f"table '{cfg.table}' ready")

    print(f"inserting {args.baseline:,} baseline sessions (server-side, may take a moment)…")
    client.command(baseline_insert(cfg.table, args.baseline))

    print(f"inserting {args.incident:,} planted incident sessions ({BAD_APP} x {BAD_CDN}, {BAD_REGION})…")
    client.command(incident_insert(cfg.table, args.incident, t0))

    total = client.query(f"SELECT count() FROM {cfg.table}").result_rows[0][0]
    print(f"\ndone. {total:,} total rows.")
    print(f"incident window: {t0}  ..  {t1}")
    print("\nnow run a diagnosis:")
    date_flag = f" --incident-date {args.incident_date}" if args.incident_date else ""
    print(f'  python main.py "Rebuffering spiked last night in the Southeast"{date_flag}')


if __name__ == "__main__":
    main()
