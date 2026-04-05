"""TRIBE v2 sidecar HTTP service for R.A.I.N. integration.

Wraps Facebook Research's TRIBE v2 brain-encoding model behind a minimal
FastAPI server so the Rust-side ``tribev2_predict`` tool can call it over HTTP.

Usage::

    python server.py                      # 0.0.0.0:8100
    python server.py --port 9000          # custom port
    python server.py --cache-dir ./cache  # custom HuggingFace cache

License: TRIBE v2 is CC-BY-NC 4.0 (non-commercial use only).
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tribev2_sidecar")

app = FastAPI(title="TRIBE v2 Sidecar", version="0.1.0")

# Global model handle — loaded once at startup.
_model = None


class PredictRequest(BaseModel):
    input_type: str  # "video", "audio", or "text"
    input_value: str  # file path or raw text


class SegmentSummary(BaseModel):
    index: int
    mean_activation: float
    max_activation: float
    min_activation: float


class PredictResponse(BaseModel):
    shape: str
    num_segments: int
    segments: list[SegmentSummary]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=_model is not None)


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    if req.input_type not in ("video", "audio", "text"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid input_type '{req.input_type}'. Must be 'video', 'audio', or 'text'.",
        )

    if not req.input_value.strip():
        raise HTTPException(status_code=400, detail="input_value must not be empty.")

    if req.input_type in ("video", "audio"):
        path = Path(req.input_value)
        if not path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"File not found: {req.input_value}",
            )

    try:
        if req.input_type == "text":
            preds = _predict_text(req.input_value)
        elif req.input_type == "audio":
            preds = _predict_audio(req.input_value)
        else:
            preds = _predict_video(req.input_value)
    except Exception as exc:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    segments = []
    for i in range(preds.shape[0]):
        row = preds[i]
        segments.append(
            SegmentSummary(
                index=i,
                mean_activation=float(np.mean(row)),
                max_activation=float(np.max(row)),
                min_activation=float(np.min(row)),
            )
        )

    return PredictResponse(
        shape=str(preds.shape),
        num_segments=preds.shape[0],
        segments=segments,
    )


def _predict_video(file_path: str) -> np.ndarray:
    """Run prediction on a video file."""
    df = _model.get_events_dataframe(video_path=file_path)
    preds, _segments = _model.predict(events=df)
    return preds


def _predict_audio(file_path: str) -> np.ndarray:
    """Run prediction on an audio file."""
    df = _model.get_events_dataframe(audio_path=file_path)
    preds, _segments = _model.predict(events=df)
    return preds


def _predict_text(text: str) -> np.ndarray:
    """Run prediction on raw text by writing a temporary text file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as tmp:
        tmp.write(text)
        tmp_path = tmp.name

    try:
        df = _model.get_events_dataframe(text_path=tmp_path)
        preds, _segments = _model.predict(events=df)
        return preds
    finally:
        os.unlink(tmp_path)


def main() -> None:
    global _model  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="TRIBE v2 sidecar service")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8100, help="Bind port (default: 8100)")
    parser.add_argument(
        "--cache-dir",
        default="./cache",
        help="HuggingFace model cache directory (default: ./cache)",
    )
    args = parser.parse_args()

    logger.info("Loading TRIBE v2 model (cache_dir=%s) ...", args.cache_dir)
    from tribev2 import TribeModel

    _model = TribeModel.from_pretrained("facebook/tribev2", cache_folder=args.cache_dir)
    logger.info("TRIBE v2 model loaded successfully.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
