"""Gemini access via the Google Gen AI SDK, configured for Vertex AI
(the Gemini Enterprise Agent Platform). This is the Google Cloud call path.

Gemini plays two narrow, load-bearing roles in the pipeline:
  1. parse_incident — turn a plain-English incident into a structured spec.
  2. write_report   — turn the pipeline's findings into a grounded root-cause report.
The model never writes SQL and never supplies numbers; it only interprets.
"""
from __future__ import annotations

import json

from google import genai
from google.genai import types

from .config import Config


class GeminiClient:
    def __init__(self, cfg: Config):
        self.model = cfg.gemini_model
        # vertexai=True routes calls through Google Cloud (Vertex / Agent Platform).
        self.client = genai.Client(
            vertexai=True,
            project=cfg.gcp_project,
            location=cfg.gcp_location,
        )

    def parse_incident(self, text: str) -> dict:
        prompt = (
            "You are triaging a video-streaming quality incident. "
            "Extract structured fields from the report below.\n\n"
            f'Incident: "{text}"\n\n'
            "Return a JSON object with keys:\n"
            '  metric: one of "rebuffer_rate" or "error_rate"\n'
            "  region_hint: a US region name if one is mentioned, else null\n"
            "  summary: a one-sentence restatement of the incident\n"
        )
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            return json.loads(resp.text)
        except Exception:
            # Fail safe: the pipeline still runs on the default metric.
            return {"metric": "rebuffer_rate", "region_hint": None, "summary": text}

    def write_report(self, incident_text: str, findings: dict) -> str:
        prompt = (
            "Write a concise root-cause report for an on-call streaming engineer. "
            "Use ONLY the numbers in the findings; do not invent any figure.\n\n"
            f'Incident as reported: "{incident_text}"\n\n'
            f"Findings (JSON):\n{json.dumps(findings, default=str, indent=2)}\n\n"
            "Structure the report as Markdown with these parts:\n"
            "1. A one-line verdict.\n"
            "2. What changed: baseline vs incident rate, and how many sessions were affected.\n"
            "3. The culprit segment: the primary and secondary factors and how concentrated the anomaly is.\n"
            "4. A concrete recommended mitigation.\n"
            "Keep it under 200 words."
        )
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2),
            )
            return resp.text or ""
        except Exception as exc:  # pragma: no cover - surface a usable message
            return f"_Report generation failed ({exc}). Raw findings:_\n\n```json\n{json.dumps(findings, default=str, indent=2)}\n```"
