# Root Cause

**Turn a plain-English streaming incident into an answer.** Root Cause is an agent that investigates billions of playback events and returns the culprit in seconds.

An on-call engineer types something like *"rebuffering spiked last night in the Southeast."* Root Cause runs a fixed, seven-stage diagnostic over the playback data in ClickHouse and returns a grounded root-cause report plus the smoking-gun chart — no hand-written SQL.

Built for the **Agentic Cinema** hackathon on the **ClickHouse** track. Reasoning runs on **Gemini** (Google Cloud / Vertex AI); the data lives in **ClickHouse**, reachable through either the native driver or the **official ClickHouse MCP server**.

---

## How it works

The diagnostic is a deterministic pipeline. The control flow is fixed; Gemini only parses the incident and writes the narrative, and ClickHouse answers the queries.

1. **Scope** — Gemini parses the incident into a structured spec (metric, region hint).
2. **Confirm** — measure the KPI in the incident window vs the prior 7-day baseline.
3. **Decompose** — `GROUP BY` across candidate dimensions (region, device, OS, app version, CDN PoP, ISP, title).
4. **Rank** — score each dimension by how concentrated the anomaly is.
5. **Drill** — break the top culprit value down by the other dimensions to find the interaction.
6. **Synthesize** — Gemini writes the root-cause report from the findings.
7. **Recommend** — propose a mitigation (roll back a version, drain a PoP, …).

The attribution math (stages 4–5): for a dimension value `v` with `n_v` sessions, incident rate `r_v`, and baseline rate `r̄`, the excess is `E_v = n_v · max(r_v − r̄, 0)`, and a dimension's concentration is `max_v(E_v) / Σ_v(E_v)`. A concentration near 1 means the anomaly lives in one value — a clear culprit. See `src/scoring.py`.

```
             Chat / CLI
                 │
                 ▼
        Root Cause pipeline  ── Gemini on Vertex AI (parse + narrate)   [Google Cloud]
                 │
                 ▼
        ClickHouse engine
         ├─ direct: clickhouse-connect driver                          [ClickHouse]
         └─ mcp:    official ClickHouse MCP server (run_select_query)  [ClickHouse]
                 │
                 ▼
        playback_events  (billions of sessions in ClickHouse Cloud)
```

---

## Prerequisites

- Python 3.10+
- A **Google Cloud** project with the Vertex AI API enabled, and credentials on your machine (`gcloud auth application-default login`). New accounts get free credits.
- A **ClickHouse** instance — [ClickHouse Cloud](https://clickhouse.com/cloud) has a free trial. From the console, open **Connect** to get your host, port (`8443`), and password.

---

## Setup

```bash
git clone <your-repo-url> && cd root-cause
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in your ClickHouse + Google Cloud values
```

Authenticate to Google Cloud (so the Gemini/Vertex client can find credentials):

```bash
gcloud auth application-default login
```

Create the table and load synthetic data (with one planted anomaly):

```bash
python setup_db.py
```

This inserts ~30M baseline sessions and ~200k planted incident sessions (app version `4.2.1` on CDN PoP `LAX`, in the Southeast, during yesterday evening). It prints the incident window and a ready-to-run command when it finishes. You can shrink the dataset for a quick start: `python setup_db.py --baseline 5000000 --incident 100000`.

> The anomaly is planted in **yesterday evening's** window. Seed and demo on the same day so the timestamps line up, or target a specific evening with `--incident-date YYYY-MM-DD` on **both** `setup_db.py` and `main.py`.

---

## Run

**CLI:**

```bash
python main.py "Rebuffering spiked last night in the Southeast"
```

**Web app (local):**

```bash
uvicorn app:app --reload
# open http://localhost:8000
```

**Use the ClickHouse MCP server instead of the driver:**

```bash
pip install mcp-clickhouse
python main.py "Rebuffering spiked last night in the Southeast" --engine mcp
```

Both engines run the identical pipeline; `--engine mcp` routes every query through ClickHouse's official MCP server (read-only). `direct` is the reliable default; `mcp` showcases the MCP integration.

---

## Deploy to Cloud Run (hosted URL)

```bash
gcloud run deploy root-cause \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "CLICKHOUSE_HOST=...,CLICKHOUSE_PASSWORD=...,GOOGLE_CLOUD_PROJECT=...,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-flash"
```

Cloud Run builds the `Dockerfile`, injects `PORT`, and gives you the public URL for your submission. Grant the service account access to Vertex AI, and set the remaining ClickHouse env vars (`CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_SECURE`, `CLICKHOUSE_DATABASE`).

---

## Where the required services are called (for judging)

Both integrations are imported and called at runtime — not just named here.

- **Google Cloud (Gemini on Vertex AI):** `src/gemini.py` — `genai.Client(vertexai=True, project=…, location=…)` and `client.models.generate_content(...)`, called from stages 1 and 6/7 in `src/pipeline.py`.
- **ClickHouse:**
  - `src/clickhouse_client.py` — the `clickhouse-connect` driver (`client.query(sql)`), the default engine.
  - `src/clickhouse_mcp.py` — the official **ClickHouse MCP server** via the `mcp` client (`session.call_tool("run_select_query", …)`), the `--engine mcp` path.
  - Queries: `src/queries.py`. Data setup: `setup_db.py`, `schema.sql`.

**How it maps to the judging criteria:** *Technological implementation* — a deterministic multi-stage agent, Gemini on Vertex, and two interchangeable ClickHouse engines including the native MCP server. *Design* — a complete product (CLI, web UI, one-command data setup, Cloud Run deploy), not a proof of concept. *Potential impact* — cuts live streaming-incident triage from many manual queries to one sentence. *Quality of the idea* — reframes root-cause analysis as a deterministic search that an agent owns end to end.

---

## Notes / version-sensitive spots

Written against current documented APIs and syntax-checked, but these are the first places to look if something doesn't line up with your installed versions:

- **`GEMINI_MODEL`** — set it to a model your project can access. `gemini-2.5-flash` is a safe default; bump to a Gemini 3.x model if that's what your project lists.
- **`GOOGLE_CLOUD_LOCATION`** — `global` serves most current models; `us-central1` also works. If a model isn't found, try switching this.
- **MCP row shape** — `src/clickhouse_mcp.py` parses several result formats defensively, but `mcp-clickhouse` versions vary. If `--engine mcp` returns empty rows, use the default `direct` engine.

## License

MIT — see [LICENSE](LICENSE).
