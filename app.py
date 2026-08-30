"""Root Cause — web app (FastAPI), deployable to Cloud Run."""

from __future__ import annotations

import math

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.config import Config
from src.gemini import GeminiClient
from src.pipeline import DiagnosticPipeline, make_engine
from src.window import default_incident_window

load_dotenv()

app = FastAPI(title="Root Cause")


class DiagnoseRequest(BaseModel):
    incident: str
    incident_date: str | None = None
    engine: str | None = None


def sanitize_for_json(value):
    """Convert NaN and infinity values into JSON-safe None values."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, dict):
        return {
            key: sanitize_for_json(val)
            for key, val in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            sanitize_for_json(item)
            for item in value
        ]

    return value


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/diagnose")
async def diagnose(req: DiagnoseRequest):
    cfg = Config.from_env()

    if req.engine:
        cfg.engine = req.engine

    t0, t1 = default_incident_window(req.incident_date)

    try:
        gemini = GeminiClient(cfg)
        engine = make_engine(cfg)

        async with engine as e:
            pipeline = DiagnosticPipeline(cfg, e, gemini)
            result = await pipeline.run(
                req.incident,
                t0,
                t1,
            )

        result["window"] = {
            "start": str(t0),
            "end": str(t1),
        }

        clean_result = sanitize_for_json(result)

        return JSONResponse(clean_result)

    except Exception as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=500,
        )
