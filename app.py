"""Root Cause — web app (FastAPI), deployable to Cloud Run.

Serves a minimal chat + chart UI and a /diagnose endpoint that runs the pipeline.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.config import Config
from src.gemini import GeminiClient
from src.pipeline import DiagnosticPipeline, make_engine
from src.window import default_incident_window

app = FastAPI(title="Root Cause")


class DiagnoseRequest(BaseModel):
    incident: str
    incident_date: str | None = None
    engine: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/diagnose")
async def diagnose(req: DiagnoseRequest) -> JSONResponse:
    cfg = Config.from_env()
    if req.engine:
        cfg.engine = req.engine
    t0, t1 = default_incident_window(req.incident_date)

    gemini = GeminiClient(cfg)
    engine = make_engine(cfg)
    try:
        async with engine as e:
            pipeline = DiagnosticPipeline(cfg, e, gemini)
            result = await pipeline.run(req.incident, t0, t1)
        result["window"] = {"start": t0, "end": t1}
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
