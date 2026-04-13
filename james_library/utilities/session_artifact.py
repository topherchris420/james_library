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
    schema_version: str = "rain-session-artifact/v1"

    def __post_init__(self) -> None:
        self.artifact_root = Path(self.artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.path = self.artifact_root / f"session_{self.session_id}.json"
        self.started_at = _utc_now_iso()
        self._turns: list[dict[str, Any]] = []

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

        for quote, source in verified:
            if source not in provenance:
                provenance.append(source)
            evidence.append(Evidence(source=source, quote=quote))

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

        self._turns.append(
            {
                "index": len(self._turns) + 1,
                "timestamp": _utc_now_iso(),
                "agent": agent_name,
                "content": content,
                "metadata": {
                    "verified_count": len(metadata.get("verified", [])),
                    "unverified_count": len(metadata.get("unverified", [])),
                    "citation_rate": metadata.get("citation_rate", 0.0),
                },
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
        payload = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "status": status,
            "topic": self.topic,
            "model": self.model,
            "recursive_depth": self.recursive_depth,
            "started_at": self.started_at,
            "completed_at": _utc_now_iso(),
            "library_path": self.library_path,
            "log_path": self.log_path,
            "loaded_papers_count": len(self.loaded_papers),
            "loaded_papers": self.loaded_papers,
            "metrics": metrics or {},
            "summary": summary or "",
            "turns": self._turns,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))
