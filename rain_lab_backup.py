"""Create a local snapshot zip for the R.A.I.N. Lab workspace."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "backups",
    "openclaw-main",
    "vers3dynamics_lab",
    "rlm-main",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {"runtime_events.jsonl"}


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _collect_files(library: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, filenames in os.walk(library):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in filenames:
            if name in EXCLUDED_FILES:
                continue
            candidate = root_path / name
            if candidate.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if candidate.is_symlink():
                continue
            files.append(candidate)
    return files


def create_backup(
    library: Path,
    output_zip: Path,
    *,
    allow_external_output: bool = False,
) -> dict[str, object]:
    library = library.expanduser().resolve()
    output_zip = output_zip.expanduser().resolve()

    if not library.exists() or not library.is_dir():
        raise FileNotFoundError(f"Library path not found: {library}")

    default_backup_root = (library / "backups").resolve()
    if not allow_external_output and not _is_relative_to(output_zip, default_backup_root):
        raise ValueError(
            f"Refusing to write backup outside {default_backup_root}. "
            "Set RAIN_ALLOW_EXTERNAL_BACKUP_PATH=1 to override."
        )

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    files = _collect_files(library)

    total_bytes = 0
    with ZipFile(output_zip, mode="w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            rel = path.relative_to(library)
            archive.write(path, arcname=str(rel))
            total_bytes += path.stat().st_size
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "library_path": str(library),
            "file_count": len(files),
            "total_bytes": total_bytes,
        }
        archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2))

    return {
        "ok": True,
        "output": str(output_zip),
        "file_count": len(files),
        "total_bytes": total_bytes,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a local R.A.I.N. Lab backup zip.")
    parser.add_argument(
        "--library",
        type=str,
        default=str(Path(__file__).resolve().parent),
        help="Workspace root to snapshot (defaults to repo root).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional output zip path. Default: <library>/backups/rain_lab_backup_<timestamp>.zip",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    library = Path(args.library)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = library / "backups" / f"rain_lab_backup_{timestamp}.zip"
    output = Path(args.output) if args.output else default_output
    allow_external = os.environ.get("RAIN_ALLOW_EXTERNAL_BACKUP_PATH", "").strip() in {
        "1",
        "true",
        "yes",
        "on",
    }

    try:
        result = create_backup(library=library, output_zip=output, allow_external_output=allow_external)
    except Exception as exc:
        error = {"ok": False, "error": str(exc)}
        print(json.dumps(error) if args.json else f"Backup failed: {exc}")
        return 1

    if args.json:
        print(json.dumps(result))
    else:
        print(f"Backup created: {result['output']}")
        print(f"Files: {result['file_count']}, bytes: {result['total_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
