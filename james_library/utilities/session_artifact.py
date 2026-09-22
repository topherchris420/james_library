"""Session artifact writer for replayable R.A.I.N. Lab meetings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from james_library.utilities.truth_layer import Evidence, build_grounded_response


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _span_index(spans: Any) -> dict[tuple[str, str], tuple[int | None, int | None]]:
    indexed: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    if not isinstance(spans, list):
        return indexed
    for item in spans:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote")
        source = item.get("source")
        if not isinstance(quote, str) or not isinstance(source, str):
            continue
        indexed[(quote, source)] = (_as_int(item.get("span_start")), _as_int(item.get("span_end")))
    return indexed


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _iter_verified(
    verified: Any,
    span_by_key: dict[tuple[str, str], tuple[int | None, int | None]],
) -> list[tuple[str, str, int | None, int | None]]:
    rows: list[tuple[str, str, int | None, int | None]] = []
    if not isinstance(verified, list):
        return rows
    for entry in verified:
        if isinstance(entry, dict):
            quote = entry.get("quote")
            source = entry.get("source")
            if not isinstance(quote, str) or not isinstance(source, str):
                continue
            rows.append((quote, source, _as_int(entry.get("span_start")), _as_int(entry.get("span_end"))))
            continue
        if not isinstance(entry, (tuple, list)) or len(entry) < 2:
            continue
        quote, source = entry[0], entry[1]
        if not isinstance(quote, str) or not isinstance(source, str):
            continue
        span_start = _as_int(entry[2]) if len(entry) > 2 else None
        span_end = _as_int(entry[3]) if len(entry) > 3 else None
        if span_start is None or span_end is None:
            span_start, span_end = span_by_key.get((quote, source), (span_start, span_end))
        rows.append((quote, source, span_start, span_end))
    return rows


def _confidence_from_metadata(metadata: dict[str, Any]) -> float:
    verified = len(metadata.get("verified", []))
    unverified = len(metadata.get("unverified", []))
    total = verified + unverified
    if total <= 0:
        return 0.2
    return round(max(0.2, min(0.95, verified / total)), 2)


@dataclass
class SessionArtifactWriter:
    artifact_root: Path | str
    session_id: str
    topic: str
    model: str
    recursive_depth: int
    library_path: str
    log_path: str
    loaded_papers: list[str] = field(default_factory=list)
    corpus_files: list[dict[str, str]] = field(default_factory=list)
    schema_version: str = "rain-session-artifact/v1"

    def __post_init__(self) -> None:
        self.artifact_root = Path(self.artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.path = self.artifact_root / f"session_{self.session_id}.json"
        self.started_at = _utc_now_iso()
        self._turns: list[dict[str, Any]] = []
        self._judgments: list[dict[str, Any]] = []

    def record_judgment(self, envelope: Any) -> None:
        """Checkpoint one typed judgment without mixing it into grounded turns."""
        from james_library.judgment import JudgmentEnvelope

        if not isinstance(envelope, JudgmentEnvelope):
            raise TypeError("record_judgment requires a JudgmentEnvelope")
        self._judgments.append(envelope.to_dict())
        self._write_payload(status="in_progress", metrics={}, summary="")

    def record_turn(
        self,
        *,
        agent_name: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = metadata or {}
        verified = metadata.get("verified", [])
        provenance: list[str] = []
        evidence: list[Evidence] = []

        span_by_key = _span_index(metadata.get("verified_spans"))
        for quote, source, span_start, span_end in _iter_verified(verified, span_by_key):
            if source not in provenance:
                provenance.append(source)
            evidence.append(
                Evidence(
                    source=source,
                    quote=quote,
                    span_start=span_start,
                    span_end=span_end,
                )
            )

        grounded_response = build_grounded_response(
            answer=content,
            confidence=_confidence_from_metadata(metadata),
            provenance=provenance,
            evidence=evidence,
            repro_steps=[
                f"Load local paper corpus from {self.library_path}",
                f"Review transcript in {self.log_path}",
            ],
        )

        turn_metadata = {
            "verified_count": len(metadata.get("verified", [])),
            "unverified_count": len(metadata.get("unverified", [])),
            "citation_rate": metadata.get("citation_rate", 0.0),
        }
        if "citation_success" in metadata:
            turn_metadata["citation_success"] = bool(metadata.get("citation_success"))
        if "require_quotes" in metadata:
            turn_metadata["require_quotes"] = bool(metadata.get("require_quotes"))
        if isinstance(metadata.get("recovery"), dict):
            turn_metadata["recovery"] = dict(metadata["recovery"])

        self._turns.append(
            {
                "index": len(self._turns) + 1,
                "timestamp": _utc_now_iso(),
                "agent": agent_name,
                "content": content,
                "metadata": turn_metadata,
                "grounded_response": grounded_response,
            }
        )

    def finalize(
        self,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> Path:
        return self._write_payload(status=status, metrics=metrics or {}, summary=summary or "")

    def _write_payload(
        self,
        *,
        status: str,
        metrics: dict[str, Any],
        summary: str,
    ) -> Path:
        payload = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "status": status,
            "topic": self.topic,
            "model": self.model,
            "recursive_depth": self.recursive_depth,
            "started_at": self.started_at,
            "completed_at": _utc_now_iso() if status != "in_progress" else "",
            "library_path": self.library_path,
            "log_path": self.log_path,
            "loaded_papers_count": len(self.loaded_papers),
            "loaded_papers": self.loaded_papers,
            "corpus_files": list(self.corpus_files),
            "metrics": metrics,
            "summary": summary,
            "turns": self._turns,
            "judgments": self._judgments,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
        return self.path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))
