"""R.A.I.N. Lab — hosted web server for lab.vers3dynamics.com.

Wraps rain_lab_runtime.run_rain_lab behind a minimal FastAPI interface.
Deploy to maritime.sh via GitHub. Configure via environment variables:

  LM_STUDIO_BASE_URL  — LLM API base URL  (e.g. https://api.openai.com/v1)
  LM_STUDIO_API_KEY   — API key
  LM_STUDIO_MODEL     — model name        (e.g. gpt-4o-mini)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make repo root importable when running from lab_server/ or from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from rain_lab_runtime import run_rain_lab
from james_library.launcher.rain_lab import BEGINNER_PRESETS, _render_beginner_topic

_STATIC_DIR = Path(__file__).parent / "static"
_VALID_PRESETS = set(BEGINNER_PRESETS) | {"free"}
_MAX_TOPIC_CHARS = 500

app = FastAPI(title="R.A.I.N. Lab", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


class DebateRequest(BaseModel):
    topic: str
    preset: str = "startup-debate"

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic must not be empty")
        return v[:_MAX_TOPIC_CHARS]

    @field_validator("preset")
    @classmethod
    def preset_valid(cls, v: str) -> str:
        if v not in _VALID_PRESETS:
            raise ValueError(f"preset must be one of: {sorted(_VALID_PRESETS)}")
        return v


class DebateResponse(BaseModel):
    topic: str
    preset: str
    result: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.post("/debate", response_model=DebateResponse)
async def debate(req: DebateRequest) -> DebateResponse:
    preset_name = None if req.preset == "free" else req.preset
    display_topic, query = _render_beginner_topic(req.topic, preset_name)

    result = await run_rain_lab(query=query, mode="rlm")

    if result.startswith(("R.A.I.N. runtime error", "R.A.I.N. runtime config error", "R.A.I.N. runtime canceled")):
        raise HTTPException(status_code=500, detail=result)

    return DebateResponse(topic=display_topic, preset=req.preset, result=result)
