"""Deterministic Provenance Bundle Manager.

Creates and verifies the complete immutable experiment bundle:
experiments/
  EXP-XXXXXXXX/
    manifest.json
    manifest.sha256
    result.json
    analysis.json
    provenance.json
    checksums.json
    logs/
    data/
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .manifest import calculate_sha256, canonical_json_str


def build_provenance_trace(
    manifest: dict[str, Any],
    result: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Construct an auditable end-to-end provenance graph linking conclusion to manifest."""
    return {
        "schema_version": "1.0.0",
        "experiment_id": manifest["experiment_id"],
        "trial_id": manifest["trial_id"],
        "execution_id": result["execution_id"],
        "trace_chain": {
            "conclusion": analysis["conclusion"],
            "conclusion_confidence": analysis["conclusion_confidence"],
            "analysis_manifest_sha256": analysis["manifest_sha256"],
            "analysis_result_sha256": analysis["result_sha256"],
            "result_manifest_sha256": result["manifest_sha256"],
            "circle_session_references": result.get("circle_session_references", []),
            "circle_intervention_references": result.get("circle_intervention_references", []),
            "raw_artifact_references": result.get("raw_artifact_references", []),
            "manifest_experiment_id": manifest["experiment_id"],
            "manifest_trial_id": manifest["trial_id"],
        },
        "epistemic_provenance_levels": {
            "manifest": "PREREGISTERED_PLAN",
            "circle_evidence": result.get("provenance", "SIMULATED"),
            "statistical_analysis": analysis.get("provenance", "DERIVED"),
            "rain_interpretation": "MODEL_INFERRED",
        },
        "safety_status": "ENGINEERING_REVIEW_ONLY",
    }


def save_experiment_bundle(
    base_dir: Path,
    manifest: dict[str, Any],
    result: dict[str, Any],
    analysis: dict[str, Any],
    logs: list[str] | None = None,
) -> Path:
    """Save an immutable, self-describing experiment bundle with complete checksums."""
    exp_id = manifest["experiment_id"]
    bundle_dir = base_dir / "experiments" / exp_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = bundle_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    data_dir = bundle_dir / "data"
    data_dir.mkdir(exist_ok=True)

    # 1. manifest.json and manifest.sha256
    manifest_content = canonical_json_str(manifest)
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(manifest_content, encoding="utf-8")

    manifest_hash = calculate_sha256(manifest_content)
    sha_path = bundle_dir / "manifest.sha256"
    sha_path.write_text(manifest_hash + "\n", encoding="utf-8")

    # 2. Copy or write data artifacts
    embedded_data = result.get("_embedded_data")
    if embedded_data:
        data_path = data_dir / "measurements.json"
        data_path.write_text(canonical_json_str(embedded_data), encoding="utf-8")

    # 3. result.json (clean copy without large in-memory transients)
    clean_result = {k: v for k, v in result.items() if not k.startswith("_")}
    result_content = canonical_json_str(clean_result)
    result_path = bundle_dir / "result.json"
    result_path.write_text(result_content, encoding="utf-8")

    # 4. analysis.json
    analysis_content = canonical_json_str(analysis)
    analysis_path = bundle_dir / "analysis.json"
    analysis_path.write_text(analysis_content, encoding="utf-8")

    # 5. provenance.json
    provenance_obj = build_provenance_trace(manifest, result, analysis)
    prov_content = canonical_json_str(provenance_obj)
    prov_path = bundle_dir / "provenance.json"
    prov_path.write_text(prov_content, encoding="utf-8")

    # 6. logs
    if logs:
        log_path = logs_dir / "session.log"
        log_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    # 7. checksums.json (compute sha256 for all files in bundle except checksums.json)
    checksums: dict[str, str] = {}
    for file_path in sorted(bundle_dir.rglob("*")):
        if file_path.is_file() and file_path.name != "checksums.json":
            rel_path = file_path.relative_to(bundle_dir).as_posix()
            data = file_path.read_bytes()
            checksums[rel_path] = hashlib.sha256(data).hexdigest()

    checksum_path = bundle_dir / "checksums.json"
    checksum_path.write_text(canonical_json_str(checksums), encoding="utf-8")

    return bundle_dir


def verify_bundle_integrity(bundle_dir: Path) -> dict[str, Any]:
    """Verify that all files in a bundle match their recorded checksums and manifest sha256."""
    checksum_file = bundle_dir / "checksums.json"
    if not checksum_file.exists():
        return {"valid": False, "error": "checksums.json missing"}

    try:
        recorded_checksums = json.loads(checksum_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"valid": False, "error": f"Failed to parse checksums.json: {e}"}

    mismatches = []
    for rel_path, expected_hash in recorded_checksums.items():
        target = bundle_dir / rel_path
        if not target.exists():
            mismatches.append(f"Missing file: {rel_path}")
            continue
        actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_hash.lower() != expected_hash.lower():
            mismatches.append(f"Checksum mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}")

    manifest_sha_file = bundle_dir / "manifest.sha256"
    if manifest_sha_file.exists():
        expected_manifest_sha = manifest_sha_file.read_text(encoding="utf-8").strip()
        manifest_file = bundle_dir / "manifest.json"
        if manifest_file.exists():
            actual_manifest_sha = calculate_sha256(manifest_file.read_text(encoding="utf-8"))
            if actual_manifest_sha.lower() != expected_manifest_sha.lower():
                mismatches.append(f"manifest.sha256 mismatch with manifest.json")

    return {
        "valid": len(mismatches) == 0,
        "mismatches": mismatches,
        "checked_files": list(recorded_checksums.keys()),
    }
