"""Deterministic Provenance Bundle Manager.

Creates and verifies a write-once experiment bundle:
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
import re
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
            "rain_interpretation": (
                "DERIVED" if analysis.get("model_identity") == "R.A.I.N.-Deterministic-Templates"
                else "MODEL_INFERRED"
            ),
        },
        "safety_status": "ENGINEERING_REVIEW_ONLY",
    }


def save_experiment_bundle(
    base_dir: Path,
    manifest: dict[str, Any],
    result: dict[str, Any],
    analysis: dict[str, Any],
    logs: list[str] | None = None,
    *,
    research_record: dict[str, Any] | None = None,
) -> Path:
    """Save a new self-describing bundle; refuse to overwrite an existing experiment."""
    exp_id = manifest["experiment_id"]
    if not isinstance(exp_id, str) or not re.fullmatch(r"EXP-[0-9A-Fa-f]{8,}", exp_id):
        raise ValueError("Invalid experiment ID")
    bundle_dir = base_dir / "experiments" / exp_id
    bundle_dir.mkdir(parents=True, exist_ok=False)
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

    if research_record is not None:
        (bundle_dir / "research.json").write_text(canonical_json_str(research_record), encoding="utf-8")

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
    """Check complete local inventory without following caller-supplied paths or symlinks.

    This detects missing/modified files, not authenticity or scientific correctness.
    """
    required = {"manifest.json", "manifest.sha256", "result.json", "analysis.json", "provenance.json"}
    try:
        if bundle_dir.is_symlink() or not bundle_dir.is_dir():
            raise ValueError("Expected a real bundle directory")
        checksum_file = bundle_dir / "checksums.json"
        if checksum_file.is_symlink():
            raise ValueError("Symlinked checksum inventory")
        recorded_checksums = json.loads(checksum_file.read_text(encoding="utf-8"))
        if not isinstance(recorded_checksums, dict) or not required.issubset(recorded_checksums):
            raise ValueError("Incomplete checksum inventory")
        actual_files = set()
        for path in bundle_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlinks are not allowed inside a bundle")
            if path.is_file() and path != checksum_file:
                actual_files.add(path.relative_to(bundle_dir).as_posix())
        mismatches = []
        for rel_path, expected_hash in recorded_checksums.items():
            parts = rel_path.split("/")
            if (not rel_path or "\\" in rel_path or ":" in rel_path
                    or any(part in {"", ".", ".."} for part in parts)):
                raise ValueError("Unsafe checksum path")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
                raise ValueError("Invalid checksum digest")
            if rel_path not in actual_files:
                mismatches.append(f"Missing file: {rel_path}")
                continue
            actual_hash = hashlib.sha256((bundle_dir / rel_path).read_bytes()).hexdigest()
            if actual_hash != expected_hash.lower():
                mismatches.append(f"Checksum mismatch for {rel_path}")
        for extra in sorted(actual_files - set(recorded_checksums)):
            mismatches.append(f"Untracked file: {extra}")
        manifest_file = bundle_dir / "manifest.json"
        expected_manifest_sha = (bundle_dir / "manifest.sha256").read_text(encoding="utf-8").strip()
        if calculate_sha256(manifest_file.read_bytes()) != expected_manifest_sha.lower():
            mismatches.append("manifest.sha256 mismatch with manifest.json")
        return {"valid": not mismatches, "mismatches": mismatches, "checked_files": list(recorded_checksums)}
    except (OSError, ValueError, TypeError) as exc:
        return {"valid": False, "error": str(exc)}
