"""Gemini client for RootCause."""

from __future__ import annotations

import json
import os

from google import genai
from google.genai import types

from .config import Config


class GeminiClient:
    def __init__(self, cfg: Config):
        self.model = cfg.gemini_model
        self.client = None

        api_key = os.getenv("GEMINI_API_KEY")

        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                return
            except Exception:
                pass

        try:
            self.client = genai.Client(
                vertexai=True,
                project=cfg.gcp_project,
                location=cfg.gcp_location,
            )
        except Exception:
            self.client = None

    def parse_incident(self, text: str) -> dict:
        fallback = {
            "metric": "rebuffer_rate",
            "region_hint": None,
            "device_hint": None,
            "summary": text,
        }

        if self.client is None:
            return fallback

        prompt = f"""
You are triaging a video-streaming quality incident.

Incident: "{text}"

Return ONLY valid JSON with these keys:
- metric: one of "rebuffer_rate" or "error_rate"
- region_hint: Northeast, Southeast, Midwest, West, Southwest, or null
- device_hint: Smart TV, Mobile, Web, Tablet, Console, or null
- summary: one concise sentence
"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )

            if response.text:
                parsed = json.loads(response.text)
                return {
                    "metric": parsed.get("metric", "rebuffer_rate"),
                    "region_hint": parsed.get("region_hint"),
                    "device_hint": parsed.get("device_hint"),
                    "summary": parsed.get("summary", text),
                }

        except Exception:
            pass

        return fallback

    def write_report(
        self,
        incident_text: str,
        findings: dict,
    ) -> str:

        if self.client is None:
            return self._fallback_report(findings)

        prompt = f"""
Write a concise streaming root-cause report.

Use ONLY the provided findings.
Do not invent numbers.

Incident:
{incident_text}

Findings:
{json.dumps(findings, indent=2, default=str)}

Use Markdown sections:
### Verdict
### What changed
### Primary signal
### Likely culprit
### Recommended mitigation

Keep it under 200 words.
"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                ),
            )

            if response.text and response.text.strip():
                return response.text.strip()

        except Exception:
            pass

        return self._fallback_report(findings)

    @staticmethod
    def _fallback_report(findings: dict) -> str:
        baseline = float(findings.get("baseline_rate") or 0)
        incident = float(findings.get("incident_rate") or 0)
        multiple = findings.get("rate_multiple")
        sessions = int(findings.get("incident_sessions") or 0)

        primary = findings.get(
            "primary_factor",
            "unknown",
        )

        concentration = float(
            findings.get("primary_concentration") or 0
        )

        secondary = findings.get(
            "secondary_factor",
            "unknown",
        )

        culprit_rate = float(
            findings.get("culprit_segment_rate") or 0
        )

        culprit_sessions = int(
            findings.get("culprit_segment_sessions") or 0
        )

        action = findings.get(
            "suggested_action",
            "investigate the affected segment",
        )

        if multiple is None:
            anomaly_description = (
                "a newly emerged anomaly with no measurable "
                "historical baseline"
            )
        else:
            anomaly_description = f"{multiple}x anomaly"

        return f"""### Root Cause Identified

**Verdict:** The incident metric increased from {baseline:.1%} to {incident:.1%}, representing **{anomaly_description}** and affecting **{sessions:,} sessions**.

**What changed:** The incident rate was significantly above the historical baseline.

**Primary signal:** The anomaly is concentrated around **{primary}**, accounting for approximately **{concentration:.1%}** of the excess signal.

**Likely culprit:** The strongest correlated segment is **{secondary}**, with a metric rate of **{culprit_rate:.1%}** across **{culprit_sessions:,} sessions**.

**Recommended mitigation:** **{action}.**

*Report generated from deterministic ClickHouse evidence.*
"""

