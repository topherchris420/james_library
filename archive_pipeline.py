#!/usr/bin/env python3
"""Build a printable QR ledger archive for the James Library repository.

The pipeline is intentionally local-first:

1. Remove volatile development artifacts.
2. Resolve and lock Python dependencies with uv.
3. Generate archive restore metadata.
4. Package the repository into a tar.gz payload and checksum it.
5. Fragment the payload into fixed-size raw chunks.
6. Encode each fragment as a high-density QR image.
7. Stitch QR images into a 300 DPI print ledger PNG.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterable, Sequence
from functools import cache, lru_cache
from pathlib import Path

ARCHIVE_NAME = "james_library_archive.tar.gz"
CHECKSUM_NAME = "checksum.txt"
README_ARCHIVE_NAME = "README_ARCHIVE.md"
PRINT_LEDGER_NAME = "james_library_print_matrix.png"
WORK_DIR_NAME = ".archive_pipeline_tmp"
RUNTIME_DIR_NAME = "archive_runtimes"
FRAGMENTS_DIR_NAME = "fragments"
QR_DIR_NAME = "qr_png"
MANIFEST_NAME = "fragments_manifest.json"

CLEAN_DIR_NAMES = frozenset({".venv", "__pycache__", ".pytest_cache", ".uv"})
SKIP_CLEAN_DIR_NAMES = frozenset({".git", RUNTIME_DIR_NAME, WORK_DIR_NAME})
VOLATILE_FILE_SUFFIXES = (
    ".log",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite-journal",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".sqlite3-journal",
)

UV_CANDIDATES = ("uv", "uv.exe")
ZEROCLAW_CANDIDATES = (
    "zeroclaw",
    "zeroclaw.exe",
    "zero_claw",
    "zero_claw.exe",
    "rain",
    "rain.exe",
)
GODOT_CANDIDATES = (
    "godot",
    "godot.exe",
    "godot_runner",
    "godot_runner.exe",
    "Godot.exe",
)
QR_VERSION_40_ALIGNMENT_POSITIONS = (6, 30, 58, 86, 114, 142, 170)
QR_VERSION_40_BLOCKS = {
    "L": {"ecc": 30, "groups": ((19, 118), (6, 119))},
    "M": {"ecc": 28, "groups": ((18, 47), (31, 48))},
    "Q": {"ecc": 30, "groups": ((34, 24), (34, 25))},
    "H": {"ecc": 30, "groups": ((20, 15), (61, 16))},
}
QR_FORMAT_ECC_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}


class PipelineError(RuntimeError):
    """Raised when the archive pipeline cannot continue safely."""


@dataclasses.dataclass(frozen=True)
class PipelineConfig:
    root: Path
    chunk_size: int = 2000
    qr_version: int = 40
    qr_error_correction: str = "M"
    qr_scale: int = 3
    qr_margin: int = 4
    page_width: int = 2550
    page_height: int = 3300
    dpi: int = 300
    dry_run: bool = False
    keep_temp: bool = True
    max_master_pixels: int = 400_000_000
    verbose: bool = False


@dataclasses.dataclass(frozen=True)
class FragmentManifest:
    archive_name: str
    archive_size: int
    chunk_size: int
    total_fragments: int
    last_fragment_padding: int
    sha256: str

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True) + "\n"


def configure_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("archive_pipeline")


def parse_args(argv: Sequence[str] | None = None) -> PipelineConfig:
    parser = argparse.ArgumentParser(
        description="Package this repository as a printable sequential QR-code archive ledger.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Repository root to archive. Defaults to the directory containing archive_pipeline.py.",
    )
    parser.add_argument("--chunk-size", type=int, default=2000, help="Raw fragment size in bytes.")
    parser.add_argument("--qr-version", type=int, default=40, help="QR version to force for all fragments.")
    parser.add_argument(
        "--qr-error-correction",
        choices=("L", "M", "Q", "H"),
        default="M",
        help="QR error correction level. M fits 2000-byte fragments in version 40.",
    )
    parser.add_argument("--qr-scale", type=int, default=3, help="QR module pixel scale.")
    parser.add_argument("--qr-margin", type=int, default=4, help="QR quiet-zone margin in modules.")
    parser.add_argument("--page-width", type=int, default=2550, help="Ledger sheet width in pixels.")
    parser.add_argument("--page-height", type=int, default=3300, help="Ledger sheet height in pixels.")
    parser.add_argument("--dpi", type=int, default=300, help="Ledger image DPI metadata.")
    parser.add_argument(
        "--max-master-pixels",
        type=int,
        default=400_000_000,
        help="Abort before creating a master PNG larger than this many pixels.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log cleanup and packaging actions without writing, deleting, or encoding files.",
    )
    parser.add_argument(
        "--clean-temp-after",
        action="store_true",
        help="Remove the temporary fragment and QR image directory after the ledger is written.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    if args.chunk_size <= 0:
        parser.error("--chunk-size must be positive")
    if args.qr_scale <= 0:
        parser.error("--qr-scale must be positive")
    if args.qr_margin < 0:
        parser.error("--qr-margin must be zero or positive")
    if args.page_width <= 0 or args.page_height <= 0:
        parser.error("--page-width and --page-height must be positive")
    if args.dpi <= 0:
        parser.error("--dpi must be positive")

    return PipelineConfig(
        root=args.root,
        chunk_size=args.chunk_size,
        qr_version=args.qr_version,
        qr_error_correction=args.qr_error_correction,
        qr_scale=args.qr_scale,
        qr_margin=args.qr_margin,
        page_width=args.page_width,
        page_height=args.page_height,
        dpi=args.dpi,
        dry_run=args.dry_run,
        keep_temp=not args.clean_temp_after,
        max_master_pixels=args.max_master_pixels,
        verbose=args.verbose,
    )


def ensure_root(path: Path) -> Path:
    try:
        root = path.expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise PipelineError(f"Repository root does not exist: {path}") from exc
    if not root.is_dir():
        raise PipelineError(f"Repository root is not a directory: {root}")
    return root


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def is_volatile_file(path: Path) -> bool:
    lower_name = path.name.lower()
    return any(lower_name.endswith(suffix) for suffix in VOLATILE_FILE_SUFFIXES)


def remove_path(path: Path, root: Path, logger: logging.Logger, dry_run: bool) -> None:
    try:
        resolved = path.resolve()
        if resolved == root.resolve() or not is_relative_to(resolved, root):
            raise PipelineError(f"Refusing to remove path outside repository root: {path}")
        if dry_run:
            logger.info("[dry-run] would remove %s", path)
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        logger.info("Removed volatile path: %s", path.relative_to(root))
    except FileNotFoundError:
        logger.debug("Cleanup target already absent: %s", path)
    except Exception as exc:
        raise PipelineError(f"Failed to remove volatile path {path}: {exc}") from exc


def cleanup_environment(root: Path, logger: logging.Logger, dry_run: bool = False) -> list[Path]:
    logger.info("Detected operating system: %s (%s)", platform.system(), platform.platform())
    targets: list[Path] = []
    walk_errors: list[str] = []

    def on_walk_error(error: OSError) -> None:
        walk_errors.append(str(error))
        logger.warning("Cleanup walk skipped path: %s", error)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=on_walk_error):
        current = Path(dirpath)
        retained_dirs: list[str] = []
        for dirname in dirnames:
            child = current / dirname
            if dirname in SKIP_CLEAN_DIR_NAMES:
                logger.debug("Skipping cleanup traversal into %s", child)
                continue
            if dirname in CLEAN_DIR_NAMES:
                targets.append(child)
                continue
            retained_dirs.append(dirname)
        dirnames[:] = retained_dirs

        for filename in filenames:
            child = current / filename
            if is_volatile_file(child):
                targets.append(child)

    logger.info("Found %d volatile cleanup target(s)", len(targets))
    for target in targets:
        try:
            remove_path(target, root, logger, dry_run)
        except PipelineError as exc:
            logger.error("%s", exc)
            raise

    if walk_errors:
        logger.warning("Cleanup completed with %d traversal warning(s)", len(walk_errors))
    return targets


def executable_name_candidates(names: Iterable[str]) -> list[str]:
    candidates: list[str] = []
    for name in names:
        candidates.append(name)
        if os.name == "nt" and not name.lower().endswith((".exe", ".cmd", ".bat")):
            candidates.append(f"{name}.exe")
    return list(dict.fromkeys(candidates))


def find_runtime_executable(runtime_dir: Path, candidates: Iterable[str], use_path: bool = True) -> Path | None:
    for name in executable_name_candidates(candidates):
        candidate = runtime_dir / name
        if candidate.is_file():
            return candidate

    for pattern in ("godot*", "Godot*", "zeroclaw*", "zero_claw*"):
        if not any(token in pattern.lower() for token in (str(c).lower().split(".")[0] for c in candidates)):
            continue
        for candidate in sorted(runtime_dir.glob(pattern)):
            if candidate.is_file():
                return candidate

    if use_path:
        for name in executable_name_candidates(candidates):
            found = shutil.which(name)
            if found:
                return Path(found)
    return None


def ensure_archive_runtimes(root: Path, logger: logging.Logger, dry_run: bool = False) -> Path:
    runtime_dir = root / RUNTIME_DIR_NAME
    if runtime_dir.exists() and not runtime_dir.is_dir():
        raise PipelineError(f"{runtime_dir} exists but is not a directory")

    if not runtime_dir.exists():
        if dry_run:
            logger.info("[dry-run] would create %s", runtime_dir)
        else:
            runtime_dir.mkdir(parents=True)
            logger.info("Created %s", runtime_dir)
        logger.warning(
            "Place the prebuilt ZeroClaw Rust binary, Godot engine runner, and standalone uv executable in %s",
            runtime_dir,
        )

    missing: list[str] = []
    if not find_runtime_executable(runtime_dir, ZEROCLAW_CANDIDATES, use_path=False):
        missing.append("ZeroClaw Rust binary")
    if not find_runtime_executable(runtime_dir, GODOT_CANDIDATES, use_path=False):
        missing.append("Godot engine runner")
    if not find_runtime_executable(runtime_dir, UV_CANDIDATES, use_path=False):
        missing.append("standalone uv executable")

    if missing:
        logger.warning("archive_runtimes is missing: %s", ", ".join(missing))
    return runtime_dir


def command_display(command: Sequence[object]) -> str:
    return " ".join(str(part) for part in command)


def run_command(
    command: Sequence[object],
    logger: logging.Logger,
    *,
    cwd: Path | None = None,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    logger.debug("Running command: %s", command_display(command))
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PipelineError(f"Command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"Command timed out after {timeout}s: {command_display(command)}") from exc
    except Exception as exc:
        raise PipelineError(f"Failed to run command {command_display(command)}: {exc}") from exc

    if result.stdout.strip():
        logger.debug("stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        logger.debug("stderr: %s", result.stderr.strip())
    if check and result.returncode != 0:
        raise PipelineError(
            "Command failed with exit code "
            f"{result.returncode}: {command_display(command)}\n{result.stderr.strip()}"
        )
    return result


def pyproject_declares_dependencies(pyproject: Path, logger: logging.Logger) -> bool:
    if not pyproject.exists():
        return False
    try:
        if sys.version_info >= (3, 11):
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            dependency_groups = data.get("dependency-groups", {})
            return bool(
                project.get("dependencies")
                or project.get("optional-dependencies")
                or dependency_groups
            )
    except Exception as exc:
        logger.debug("Falling back to text scan for pyproject dependency detection: %s", exc)

    try:
        text = pyproject.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PipelineError(f"Unable to read {pyproject}: {exc}") from exc

    project_section = re.search(r"(?ms)^\[project\]\s*(.*?)(?:^\[|\Z)", text)
    if project_section and re.search(r"(?m)^\s*(dependencies|optional-dependencies)\s*=", project_section.group(1)):
        return True
    return bool(re.search(r"(?m)^\[dependency-groups\]", text))


def find_uv(runtime_dir: Path) -> Path | None:
    return find_runtime_executable(runtime_dir, UV_CANDIDATES, use_path=True)


def compile_requirements(root: Path, runtime_dir: Path, logger: logging.Logger, dry_run: bool = False) -> Path:
    requirements = root / "requirements.txt"
    pyproject = root / "pyproject.toml"
    requirements_in = root / "requirements.in"
    tmp_requirements = root / "requirements.txt.tmp"
    uv = find_uv(runtime_dir)
    if not uv:
        raise PipelineError(
            "uv was not found on PATH or in archive_runtimes. "
            "Place a standalone uv executable in archive_runtimes or install uv before archiving."
        )

    if pyproject_declares_dependencies(pyproject, logger):
        source = pyproject
        logger.info("Compiling strict requirements.txt from pyproject.toml")
    elif requirements_in.exists():
        source = requirements_in
        logger.info("Compiling strict requirements.txt from requirements.in")
    elif requirements.exists():
        source = requirements
        logger.info("Compiling strict requirements.txt from existing requirements.txt constraints")
    else:
        source = None
        logger.info("No dependency source file found; freezing the active uv environment")

    if dry_run:
        if source:
            logger.info("[dry-run] would run: %s pip compile %s -o %s", uv, source, requirements)
        else:
            logger.info("[dry-run] would run uv pip freeze and write %s", requirements)
        return requirements

    if source:
        compile_command = [uv, "pip", "compile", source, "-o", tmp_requirements, "--generate-hashes"]
        try:
            run_command(compile_command, logger, cwd=root, timeout=900)
        except PipelineError as hash_error:
            logger.warning("uv compile with hashes failed; retrying without hashes: %s", hash_error)
            run_command([uv, "pip", "compile", source, "-o", tmp_requirements], logger, cwd=root, timeout=900)
        try:
            tmp_requirements.replace(requirements)
        except OSError as exc:
            raise PipelineError(f"Failed to replace {requirements} with compiled lockfile: {exc}") from exc
    else:
        freeze_commands: list[list[object]] = [[uv, "pip", "freeze"]]
        if not os.environ.get("VIRTUAL_ENV"):
            freeze_commands.append([uv, "pip", "freeze", "--system"])

        last_error: PipelineError | None = None
        for command in freeze_commands:
            try:
                result = run_command(command, logger, cwd=root, timeout=300)
                requirements.write_text(result.stdout, encoding="utf-8")
                break
            except PipelineError as exc:
                last_error = exc
        else:
            raise PipelineError(f"Unable to freeze active environment with uv: {last_error}") from last_error

    if not requirements.exists() or requirements.stat().st_size == 0:
        raise PipelineError("Compiled requirements.txt is missing or empty")
    logger.info("Wrote strict dependency lockfile: %s", requirements)
    return requirements


def runtime_version(executable: Path | None, logger: logging.Logger) -> str:
    if not executable:
        return "not detected"
    for args in (["--version"], ["version"], ["-V"]):
        try:
            result = run_command([executable, *args], logger, timeout=20, check=False)
        except PipelineError as exc:
            logger.debug("Version probe failed for %s %s: %s", executable, args, exc)
            continue
        output = (result.stdout.strip() or result.stderr.strip()).splitlines()
        if output:
            return output[0].strip()
    return f"detected at {executable}, version probe unavailable"


def collect_stack_metadata(root: Path, runtime_dir: Path, logger: logging.Logger) -> dict[str, str]:
    uv_path = find_uv(runtime_dir)
    zeroclaw_path = find_runtime_executable(runtime_dir, ZEROCLAW_CANDIDATES, use_path=True)
    godot_path = find_runtime_executable(runtime_dir, GODOT_CANDIDATES, use_path=True)
    return {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repository_root": str(root),
        "os": f"{platform.system()} {platform.release()} ({platform.platform()})",
        "python": sys.version.replace("\n", " "),
        "uv": runtime_version(uv_path, logger),
        "zeroclaw": runtime_version(zeroclaw_path, logger),
        "godot": runtime_version(godot_path, logger),
    }


def write_archive_readme(root: Path, metadata: dict[str, str], logger: logging.Logger, dry_run: bool = False) -> Path:
    path = root / README_ARCHIVE_NAME
    content = f"""# James Library Physical Archive

Generated at: {metadata["generated_at_utc"]}

## Execution Stack

- Repository root: `{metadata["repository_root"]}`
- Operating system: `{metadata["os"]}`
- Python: `{metadata["python"]}`
- uv: `{metadata["uv"]}`
- ZeroClaw Rust binary: `{metadata["zeroclaw"]}`
- Godot engine runner: `{metadata["godot"]}`

## Multi-Agent Orchestration Summary

James Library is the Python research and workflow layer for the R.A.I.N. Lab runtime.
The lab is organized around four role-specialized agents:

- James: Lead Scientist. Draws directly from the research corpus, cites metrics, and states when data is missing.
- Jasmine: Hardware Architect. Checks theoretical proposals against material, actuator, thermal, and build constraints.
- Luca: Field Tomographer. Looks for geometric and topological patterns, then grounds intuition in math.
- Elena: Quantum Information Theorist. Demands formal rigor, verifies logic, and catches inconsistent assumptions.

The orchestration pattern is a multi-agent research meeting: James frames the question,
Jasmine pressure-tests implementation feasibility, Luca maps structure and geometry,
and Elena verifies the formal constraints before the lab records conclusions.

## Offline Restore Instructions

1. Reconstruct `james_library_archive.tar.gz` from the printed QR ledger fragments.
2. Verify the archive with the SHA-256 value stored in `checksum.txt`.
3. Extract the archive into a clean directory.
4. Confirm the extracted `archive_runtimes` directory contains:
   - the prebuilt ZeroClaw Rust binary,
   - the Godot engine runner,
   - a standalone `uv` executable for the target platform.
5. On Windows PowerShell, run:

   ```powershell
   $env:PATH = "$(Resolve-Path .\\archive_runtimes);$env:PATH"
   .\\INSTALL_RAIN.cmd
   ```

   On POSIX shells, use the equivalent PATH update before invoking the installer.

`INSTALL_RAIN.cmd` delegates to `INSTALL_RAIN.ps1` and uses `uv` to create the local Python
environment. Keeping `uv` and the native runtime binaries in `archive_runtimes` is what allows
the lab to be restored without network access after the archive has been reconstructed.
"""
    if dry_run:
        logger.info("[dry-run] would write %s", path)
        return path
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"Failed to write {path}: {exc}") from exc
    logger.info("Wrote archive metadata: %s", path)
    return path


def should_exclude_from_tar(path: Path, exclude_paths: set[Path], exclude_names: set[str]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    if resolved in exclude_paths:
        return True
    return path.name in exclude_names


def create_tar_gz(root: Path, logger: logging.Logger, dry_run: bool = False) -> Path:
    archive_path = root / ARCHIVE_NAME
    tmp_archive_path = root / f".{ARCHIVE_NAME}.tmp"
    exclude_paths = {
        archive_path.resolve(),
        tmp_archive_path.resolve(),
        (root / CHECKSUM_NAME).resolve(),
        (root / PRINT_LEDGER_NAME).resolve(),
        (root / WORK_DIR_NAME).resolve(),
    }
    exclude_names = {WORK_DIR_NAME}

    if dry_run:
        logger.info("[dry-run] would create tar.gz archive at %s", archive_path)
        return archive_path

    errors: list[str] = []

    def on_walk_error(error: OSError) -> None:
        errors.append(str(error))
        logger.error("Archive walk failed for path: %s", error)

    try:
        if tmp_archive_path.exists():
            tmp_archive_path.unlink()
        with tarfile.open(tmp_archive_path, "w:gz") as tar:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=on_walk_error):
                current = Path(dirpath)
                retained_dirs: list[str] = []
                for dirname in dirnames:
                    child = current / dirname
                    if should_exclude_from_tar(child, exclude_paths, exclude_names):
                        logger.debug("Excluding directory from archive: %s", child)
                        continue
                    retained_dirs.append(dirname)
                dirnames[:] = retained_dirs

                try:
                    arcname = current.relative_to(root)
                    if str(arcname) != ".":
                        tar.add(current, arcname=str(arcname), recursive=False)
                except Exception as exc:
                    message = f"{current}: {exc}"
                    errors.append(message)
                    logger.error("Failed to add directory to archive: %s", message)

                for filename in filenames:
                    child = current / filename
                    if should_exclude_from_tar(child, exclude_paths, exclude_names):
                        logger.debug("Excluding file from archive: %s", child)
                        continue
                    try:
                        tar.add(child, arcname=str(child.relative_to(root)), recursive=False)
                    except Exception as exc:
                        message = f"{child}: {exc}"
                        errors.append(message)
                        logger.error("Failed to add file to archive: %s", message)

        if errors:
            raise PipelineError(f"Archive creation encountered {len(errors)} error(s); first error: {errors[0]}")
        tmp_archive_path.replace(archive_path)
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Failed to create {archive_path}: {exc}") from exc
    finally:
        if tmp_archive_path.exists():
            try:
                tmp_archive_path.unlink()
            except OSError:
                logger.debug("Could not remove temporary archive %s", tmp_archive_path)

    logger.info("Created payload archive: %s", archive_path)
    return archive_path


def sha256_file(path: Path, logger: logging.Logger, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(block_size), b""):
                digest.update(block)
    except OSError as exc:
        raise PipelineError(f"Failed to hash {path}: {exc}") from exc
    checksum = digest.hexdigest()
    logger.info("Calculated SHA-256 for %s: %s", path.name, checksum)
    return checksum


def write_checksum(root: Path, checksum: str, logger: logging.Logger, dry_run: bool = False) -> Path:
    path = root / CHECKSUM_NAME
    if dry_run:
        logger.info("[dry-run] would write %s", path)
        return path
    try:
        path.write_text(checksum + "\n", encoding="ascii")
    except OSError as exc:
        raise PipelineError(f"Failed to write checksum file {path}: {exc}") from exc
    logger.info("Wrote checksum file: %s", path)
    return path


def prepare_directory(path: Path, root: Path, logger: logging.Logger, dry_run: bool = False) -> None:
    if path.exists():
        remove_path(path, root, logger, dry_run)
    if dry_run:
        logger.info("[dry-run] would create %s", path)
        return
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PipelineError(f"Failed to create directory {path}: {exc}") from exc


def fragment_archive(
    archive_path: Path,
    work_dir: Path,
    root: Path,
    checksum: str,
    chunk_size: int,
    logger: logging.Logger,
    dry_run: bool = False,
) -> tuple[Path, FragmentManifest]:
    if chunk_size <= 0:
        raise PipelineError("chunk_size must be positive")
    fragments_dir = work_dir / FRAGMENTS_DIR_NAME
    archive_size = archive_path.stat().st_size if archive_path.exists() else 0
    total_fragments = max(1, math.ceil(archive_size / chunk_size))
    width = max(3, len(str(total_fragments)))
    last_payload_size = archive_size % chunk_size or chunk_size
    last_padding = chunk_size - last_payload_size if archive_size else chunk_size
    if archive_size and last_payload_size == chunk_size:
        last_padding = 0

    manifest = FragmentManifest(
        archive_name=archive_path.name,
        archive_size=archive_size,
        chunk_size=chunk_size,
        total_fragments=total_fragments,
        last_fragment_padding=last_padding,
        sha256=checksum,
    )

    if dry_run:
        logger.info(
            "[dry-run] would write %d fragment(s) of %d bytes under %s",
            total_fragments,
            chunk_size,
            fragments_dir,
        )
        return fragments_dir, manifest

    prepare_directory(fragments_dir, root, logger, dry_run=False)
    try:
        with archive_path.open("rb") as source:
            for index in range(1, total_fragments + 1):
                chunk = source.read(chunk_size)
                if not chunk and archive_size:
                    raise PipelineError(f"Unexpected end of archive while writing fragment {index}")
                if len(chunk) < chunk_size:
                    chunk += b"\x00" * (chunk_size - len(chunk))
                fragment_path = fragments_dir / f"fragment_{index:0{width}d}"
                fragment_path.write_bytes(chunk)
        (work_dir / MANIFEST_NAME).write_text(manifest.to_json(), encoding="utf-8")
    except OSError as exc:
        raise PipelineError(f"Failed during raw fragmentation: {exc}") from exc

    logger.info(
        "Wrote %d raw fragment(s) of %d bytes to %s",
        total_fragments,
        chunk_size,
        fragments_dir,
    )
    if last_padding:
        logger.info(
            "Final fragment padded with %d zero byte(s); original size is recorded in %s",
            last_padding,
            MANIFEST_NAME,
        )
    return fragments_dir, manifest


def qrencode_path() -> Path | None:
    found = shutil.which("qrencode")
    return Path(found) if found else None


@lru_cache(maxsize=1)
def gf_tables() -> tuple[tuple[int, ...], tuple[int, ...]]:
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for index in range(255):
        exp[index] = value
        log[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        exp[index] = exp[index - 255]
    return tuple(exp), tuple(log)


def gf_multiply(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    exp, log = gf_tables()
    return exp[log[left] + log[right]]


def poly_multiply(left: Sequence[int], right: Sequence[int]) -> list[int]:
    result = [0] * (len(left) + len(right) - 1)
    for left_index, left_value in enumerate(left):
        for right_index, right_value in enumerate(right):
            result[left_index + right_index] ^= gf_multiply(left_value, right_value)
    return result


@cache
def rs_generator(degree: int) -> tuple[int, ...]:
    exp, _log = gf_tables()
    coefficients = [1]
    for index in range(degree):
        coefficients = poly_multiply(coefficients, [1, exp[index]])
    return tuple(coefficients)


def rs_remainder(data: Sequence[int], degree: int) -> list[int]:
    generator = rs_generator(degree)
    result = [0] * degree
    for value in data:
        factor = value ^ result[0]
        result = result[1:] + [0]
        for index in range(degree):
            result[index] ^= gf_multiply(generator[index + 1], factor)
    return result


def append_bits(bits: list[int], value: int, width: int) -> None:
    for offset in range(width - 1, -1, -1):
        bits.append((value >> offset) & 1)


def version40_block_spec(error_correction: str) -> tuple[int, tuple[tuple[int, int], ...]]:
    spec = QR_VERSION_40_BLOCKS[error_correction]
    return int(spec["ecc"]), tuple(spec["groups"])  # type: ignore[arg-type]


def make_version40_data_codewords(data: bytes, error_correction: str) -> list[int]:
    _ecc_words, groups = version40_block_spec(error_correction)
    data_codeword_count = sum(block_count * data_words for block_count, data_words in groups)
    capacity_bits = data_codeword_count * 8

    bits: list[int] = []
    append_bits(bits, 0b0100, 4)  # Byte mode.
    append_bits(bits, len(data), 16)  # Version 10+ byte-mode character count field.
    for value in data:
        append_bits(bits, value, 8)
    if len(bits) > capacity_bits:
        raise PipelineError(
            f"{len(data)} byte(s) exceed QR Version 40-{error_correction} byte-mode capacity"
        )

    bits.extend([0] * min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [
        int("".join(str(bit) for bit in bits[index : index + 8]), 2)
        for index in range(0, len(bits), 8)
    ]
    pad_values = (0xEC, 0x11)
    pad_index = 0
    while len(codewords) < data_codeword_count:
        codewords.append(pad_values[pad_index % 2])
        pad_index += 1
    return codewords


def interleave_version40_codewords(data_codewords: Sequence[int], error_correction: str) -> list[int]:
    ecc_words, groups = version40_block_spec(error_correction)
    blocks: list[list[int]] = []
    ecc_blocks: list[list[int]] = []
    offset = 0

    for block_count, data_words in groups:
        for _ in range(block_count):
            block = list(data_codewords[offset : offset + data_words])
            if len(block) != data_words:
                raise PipelineError("Insufficient data codewords while constructing QR blocks")
            blocks.append(block)
            ecc_blocks.append(rs_remainder(block, ecc_words))
            offset += data_words

    if offset != len(data_codewords):
        raise PipelineError("Unused data codewords remain after QR block construction")

    result: list[int] = []
    max_data_words = max(len(block) for block in blocks)
    for index in range(max_data_words):
        for block in blocks:
            if index < len(block):
                result.append(block[index])
    for index in range(ecc_words):
        for block in ecc_blocks:
            result.append(block[index])
    if len(result) != 3706:
        raise PipelineError(f"QR Version 40 payload should be 3706 codewords, got {len(result)}")
    return result


def set_function_module(
    matrix: list[list[bool]],
    functions: list[list[bool]],
    x: int,
    y: int,
    is_dark: bool,
) -> None:
    size = len(matrix)
    if 0 <= x < size and 0 <= y < size:
        matrix[y][x] = is_dark
        functions[y][x] = True


def draw_finder_pattern(matrix: list[list[bool]], functions: list[list[bool]], left: int, top: int) -> None:
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            x = left + dx
            y = top + dy
            is_core = 0 <= dx <= 6 and 0 <= dy <= 6
            is_dark = is_core and (
                dx in (0, 6)
                or dy in (0, 6)
                or (2 <= dx <= 4 and 2 <= dy <= 4)
            )
            set_function_module(matrix, functions, x, y, is_dark)


def draw_alignment_pattern(matrix: list[list[bool]], functions: list[list[bool]], center_x: int, center_y: int) -> None:
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            distance = max(abs(dx), abs(dy))
            set_function_module(
                matrix,
                functions,
                center_x + dx,
                center_y + dy,
                distance in (0, 2),
            )


def bch_remainder(value: int, polynomial: int, shift: int) -> int:
    value <<= shift
    for bit in range(value.bit_length() - 1, shift - 1, -1):
        if (value >> bit) & 1:
            value ^= polynomial << (bit - shift)
    return value & ((1 << shift) - 1)


def format_bits(error_correction: str, mask: int) -> int:
    data = (QR_FORMAT_ECC_BITS[error_correction] << 3) | mask
    return ((data << 10) | bch_remainder(data, 0x537, 10)) ^ 0x5412


def version_bits(version: int) -> int:
    return (version << 12) | bch_remainder(version, 0x1F25, 12)


def draw_format_bits(
    matrix: list[list[bool]],
    functions: list[list[bool]],
    error_correction: str,
    mask: int,
) -> None:
    size = len(matrix)
    bits = format_bits(error_correction, mask)
    for index in range(6):
        set_function_module(matrix, functions, 8, index, bool((bits >> index) & 1))
    set_function_module(matrix, functions, 8, 7, bool((bits >> 6) & 1))
    set_function_module(matrix, functions, 8, 8, bool((bits >> 7) & 1))
    set_function_module(matrix, functions, 7, 8, bool((bits >> 8) & 1))
    for index in range(9, 15):
        set_function_module(matrix, functions, 14 - index, 8, bool((bits >> index) & 1))
    for index in range(8):
        set_function_module(matrix, functions, size - 1 - index, 8, bool((bits >> index) & 1))
    for index in range(8, 15):
        set_function_module(matrix, functions, 8, size - 15 + index, bool((bits >> index) & 1))
    set_function_module(matrix, functions, 8, size - 8, True)


def draw_version_bits(matrix: list[list[bool]], functions: list[list[bool]], version: int) -> None:
    size = len(matrix)
    bits = version_bits(version)
    for index in range(18):
        is_dark = bool((bits >> index) & 1)
        a = size - 11 + (index % 3)
        b = index // 3
        set_function_module(matrix, functions, a, b, is_dark)
        set_function_module(matrix, functions, b, a, is_dark)


def build_base_qr_matrix(version: int, error_correction: str, mask: int) -> tuple[list[list[bool]], list[list[bool]]]:
    size = version * 4 + 17
    matrix = [[False] * size for _ in range(size)]
    functions = [[False] * size for _ in range(size)]

    draw_finder_pattern(matrix, functions, 0, 0)
    draw_finder_pattern(matrix, functions, size - 7, 0)
    draw_finder_pattern(matrix, functions, 0, size - 7)

    for position in range(8, size - 8):
        dark = position % 2 == 0
        set_function_module(matrix, functions, position, 6, dark)
        set_function_module(matrix, functions, 6, position, dark)

    for center_y in QR_VERSION_40_ALIGNMENT_POSITIONS:
        for center_x in QR_VERSION_40_ALIGNMENT_POSITIONS:
            overlaps_top_left = center_x <= 8 and center_y <= 8
            overlaps_top_right = center_x >= size - 9 and center_y <= 8
            overlaps_bottom_left = center_x <= 8 and center_y >= size - 9
            if overlaps_top_left or overlaps_top_right or overlaps_bottom_left:
                continue
            draw_alignment_pattern(matrix, functions, center_x, center_y)

    draw_format_bits(matrix, functions, error_correction, mask)
    draw_version_bits(matrix, functions, version)
    return matrix, functions


def qr_mask(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return ((y // 2) + (x // 3)) % 2 == 0
    if mask == 5:
        return ((x * y) % 2) + ((x * y) % 3) == 0
    if mask == 6:
        return (((x * y) % 2) + ((x * y) % 3)) % 2 == 0
    if mask == 7:
        return (((x + y) % 2) + ((x * y) % 3)) % 2 == 0
    raise PipelineError(f"Unsupported QR mask: {mask}")


def codewords_to_bits(codewords: Sequence[int]) -> list[int]:
    bits: list[int] = []
    for codeword in codewords:
        append_bits(bits, codeword, 8)
    return bits


def place_data_bits(
    matrix: list[list[bool]],
    functions: list[list[bool]],
    data_bits: Sequence[int],
    mask: int,
) -> None:
    size = len(matrix)
    bit_index = 0
    upward = True
    right = size - 1
    while right >= 1:
        if right == 6:
            right -= 1
        for vertical in range(size):
            y = size - 1 - vertical if upward else vertical
            for column_offset in range(2):
                x = right - column_offset
                if functions[y][x]:
                    continue
                if bit_index >= len(data_bits):
                    raise PipelineError("QR matrix has more data modules than payload bits")
                is_dark = bool(data_bits[bit_index]) ^ qr_mask(mask, x, y)
                matrix[y][x] = is_dark
                bit_index += 1
        upward = not upward
        right -= 2
    if bit_index != len(data_bits):
        raise PipelineError(f"QR matrix placed {bit_index} data bits, expected {len(data_bits)}")


def qr_penalty(matrix: list[list[bool]]) -> int:
    size = len(matrix)
    penalty = 0

    for y in range(size):
        run_color = matrix[y][0]
        run_length = 1
        for x in range(1, size):
            if matrix[y][x] == run_color:
                run_length += 1
            else:
                if run_length >= 5:
                    penalty += 3 + run_length - 5
                run_color = matrix[y][x]
                run_length = 1
        if run_length >= 5:
            penalty += 3 + run_length - 5

    for x in range(size):
        run_color = matrix[0][x]
        run_length = 1
        for y in range(1, size):
            if matrix[y][x] == run_color:
                run_length += 1
            else:
                if run_length >= 5:
                    penalty += 3 + run_length - 5
                run_color = matrix[y][x]
                run_length = 1
        if run_length >= 5:
            penalty += 3 + run_length - 5

    for y in range(size - 1):
        for x in range(size - 1):
            color = matrix[y][x]
            if matrix[y][x + 1] == color and matrix[y + 1][x] == color and matrix[y + 1][x + 1] == color:
                penalty += 3

    pattern = (True, False, True, True, True, False, True, False, False, False, False)
    reverse_pattern = tuple(reversed(pattern))
    for y in range(size):
        row = tuple(matrix[y])
        for x in range(size - 10):
            segment = row[x : x + 11]
            if segment == pattern or segment == reverse_pattern:
                penalty += 40
    for x in range(size):
        column = tuple(matrix[y][x] for y in range(size))
        for y in range(size - 10):
            segment = column[y : y + 11]
            if segment == pattern or segment == reverse_pattern:
                penalty += 40

    dark_count = sum(1 for row in matrix for value in row if value)
    dark_percent = dark_count * 100 / (size * size)
    penalty += int(abs(dark_percent - 50) // 5) * 10
    return penalty


def make_builtin_version40_qr_matrix(data: bytes, error_correction: str) -> list[list[bool]]:
    data_codewords = make_version40_data_codewords(data, error_correction)
    final_codewords = interleave_version40_codewords(data_codewords, error_correction)
    data_bits = codewords_to_bits(final_codewords)

    best_matrix: list[list[bool]] | None = None
    best_penalty: int | None = None
    for mask in range(8):
        matrix, functions = build_base_qr_matrix(40, error_correction, mask)
        place_data_bits(matrix, functions, data_bits, mask)
        penalty = qr_penalty(matrix)
        if best_penalty is None or penalty < best_penalty:
            best_matrix = matrix
            best_penalty = penalty
    if best_matrix is None:
        raise PipelineError("Failed to construct QR matrix")
    return best_matrix


def encode_fragment_with_builtin_qr(
    fragment_path: Path,
    output_path: Path,
    config: PipelineConfig,
) -> None:
    if config.qr_version != 40:
        raise PipelineError("Built-in QR fallback supports QR Version 40 only")
    try:
        from PIL import Image
    except Exception as exc:
        raise PipelineError("Pillow is required for the built-in QR encoder fallback") from exc

    matrix = make_builtin_version40_qr_matrix(fragment_path.read_bytes(), config.qr_error_correction)
    module_count = len(matrix) + 2 * config.qr_margin
    image_size = module_count * config.qr_scale
    image = Image.new("RGB", (image_size, image_size), "white")
    pixels = image.load()

    for y, row in enumerate(matrix):
        for x, is_dark in enumerate(row):
            if not is_dark:
                continue
            left = (x + config.qr_margin) * config.qr_scale
            top = (y + config.qr_margin) * config.qr_scale
            for pixel_y in range(top, top + config.qr_scale):
                for pixel_x in range(left, left + config.qr_scale):
                    pixels[pixel_x, pixel_y] = (0, 0, 0)

    image.save(output_path)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PipelineError(f"Built-in QR encoder did not produce output file: {output_path}")


def qr_error_constant(level: str) -> object:
    try:
        import qrcode.constants as constants
    except Exception as exc:
        raise PipelineError("Python qrcode package is not available") from exc
    mapping = {
        "L": constants.ERROR_CORRECT_L,
        "M": constants.ERROR_CORRECT_M,
        "Q": constants.ERROR_CORRECT_Q,
        "H": constants.ERROR_CORRECT_H,
    }
    return mapping[level]


def encode_fragment_with_qrencode(
    qrencode: Path,
    fragment_path: Path,
    output_path: Path,
    config: PipelineConfig,
    logger: logging.Logger,
) -> None:
    command = [
        qrencode,
        "-8",
        "-v",
        str(config.qr_version),
        "-l",
        config.qr_error_correction,
        "-s",
        str(config.qr_scale),
        "-m",
        str(config.qr_margin),
        "-o",
        output_path,
        "-r",
        fragment_path,
    ]
    run_command(command, logger, timeout=120)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PipelineError(f"qrencode did not produce output file: {output_path}")


def encode_fragment_with_python_qrcode(
    fragment_path: Path,
    output_path: Path,
    config: PipelineConfig,
) -> None:
    try:
        import qrcode
    except Exception:
        try:
            import segno
        except Exception:
            encode_fragment_with_builtin_qr(fragment_path, output_path, config)
            return

        data = fragment_path.read_bytes()
        qr = segno.make(
            data,
            mode="byte",
            version=config.qr_version,
            error=config.qr_error_correction.lower(),
            micro=False,
        )
        qr.save(output_path, scale=config.qr_scale, border=config.qr_margin)
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise PipelineError(f"segno did not produce output file: {output_path}")
        return

    data = fragment_path.read_bytes()
    qr = qrcode.QRCode(
        version=config.qr_version,
        error_correction=qr_error_constant(config.qr_error_correction),
        box_size=config.qr_scale,
        border=config.qr_margin,
    )
    qr.add_data(data, optimize=0)
    qr.make(fit=False)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image.save(output_path)
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PipelineError(f"qrcode did not produce output file: {output_path}")


def encode_fragments_to_qr(
    fragments_dir: Path,
    work_dir: Path,
    root: Path,
    config: PipelineConfig,
    logger: logging.Logger,
) -> Path:
    qr_dir = work_dir / QR_DIR_NAME
    if config.dry_run:
        logger.info("[dry-run] would encode fragments in %s to PNG files under %s", fragments_dir, qr_dir)
        return qr_dir

    prepare_directory(qr_dir, root, logger, dry_run=False)
    fragments = sorted(path for path in fragments_dir.iterdir() if path.is_file() and path.name.startswith("fragment_"))
    if not fragments:
        raise PipelineError(f"No raw fragments found in {fragments_dir}")

    external_qrencode = qrencode_path()
    if external_qrencode:
        logger.info("Encoding %d fragment(s) with qrencode at %s", len(fragments), external_qrencode)
    else:
        logger.warning("qrencode utility not found; falling back to native Python QR encoder if available")

    for index, fragment_path in enumerate(fragments, start=1):
        output_path = qr_dir / f"{fragment_path.name}.png"
        try:
            if external_qrencode:
                encode_fragment_with_qrencode(external_qrencode, fragment_path, output_path, config, logger)
            else:
                encode_fragment_with_python_qrcode(fragment_path, output_path, config)
        except PipelineError as exc:
            if external_qrencode:
                logger.warning("qrencode failed for %s; trying native Python encoder: %s", fragment_path.name, exc)
                encode_fragment_with_python_qrcode(fragment_path, output_path, config)
            else:
                raise
        except Exception as exc:
            raise PipelineError(f"Failed to encode QR image for {fragment_path}: {exc}") from exc
        if index % 100 == 0 or index == len(fragments):
            logger.info("Encoded %d/%d QR fragment PNG(s)", index, len(fragments))

    return qr_dir


def load_font(size: int, bold: bool = False):
    try:
        from PIL import ImageFont
    except Exception as exc:
        raise PipelineError("Pillow is required for ledger stitching. Install Pillow and rerun.") from exc

    names = (
        ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf")
        if bold
        else ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_size(draw: object, text: str, font: object) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def stitch_visuals(
    qr_dir: Path,
    checksum_file: Path,
    output_path: Path,
    config: PipelineConfig,
    logger: logging.Logger,
) -> Path:
    if config.dry_run:
        logger.info("[dry-run] would stitch QR PNGs from %s into %s", qr_dir, output_path)
        return output_path

    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise PipelineError("Pillow is required for ledger stitching. Install Pillow and rerun.") from exc

    png_paths = sorted(qr_dir.glob("fragment_*.png"))
    if not png_paths:
        raise PipelineError(f"No QR PNG files found in {qr_dir}")
    try:
        checksum = checksum_file.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise PipelineError(f"Failed to read checksum file {checksum_file}: {exc}") from exc

    dimensions: list[tuple[int, int]] = []
    for path in png_paths:
        try:
            with Image.open(path) as image:
                dimensions.append(image.size)
        except Exception as exc:
            raise PipelineError(f"Failed to inspect QR image {path}: {exc}") from exc
    max_qr_width = max(width for width, _height in dimensions)
    max_qr_height = max(height for _width, height in dimensions)

    margin = max(90, config.dpi // 3)
    header_height = 210
    label_height = 36
    gutter_x = 36
    gutter_y = 54
    available_width = config.page_width - 2 * margin
    available_height = config.page_height - header_height - margin
    cell_width = max_qr_width + gutter_x
    cell_height = max_qr_height + label_height + gutter_y
    columns = max(1, available_width // cell_width)
    rows = max(1, available_height // cell_height)
    fragments_per_sheet = columns * rows
    sheet_count = math.ceil(len(png_paths) / fragments_per_sheet)
    master_pixels = config.page_width * config.page_height * sheet_count

    if master_pixels > config.max_master_pixels:
        raise PipelineError(
            f"Master ledger would be {master_pixels:,} pixels across {sheet_count} sheets, "
            f"exceeding --max-master-pixels={config.max_master_pixels:,}."
        )

    logger.info(
        "Stitching %d QR PNG(s): %d columns x %d rows per sheet, %d sheet(s)",
        len(png_paths),
        columns,
        rows,
        sheet_count,
    )

    master = Image.new("RGB", (config.page_width, config.page_height * sheet_count), "white")
    draw = ImageDraw.Draw(master)
    header_font = load_font(34, bold=True)
    meta_font = load_font(22)
    label_font = load_font(18, bold=True)

    for sheet_index in range(sheet_count):
        sheet_number = sheet_index + 1
        y_offset = sheet_index * config.page_height
        draw.rectangle(
            [(0, y_offset), (config.page_width - 1, y_offset + config.page_height - 1)],
            outline="black",
            width=3,
        )
        header_text = f"Sheet {sheet_number} of {sheet_count} \u2014 james_library Payload"
        checksum_text = f"SHA-256: {checksum}"
        header_width, _ = text_size(draw, header_text, header_font)
        draw.text(((config.page_width - header_width) // 2, y_offset + 42), header_text, fill="black", font=header_font)
        checksum_width, _ = text_size(draw, checksum_text, meta_font)
        draw.text(
            ((config.page_width - checksum_width) // 2, y_offset + 94),
            checksum_text,
            fill="black",
            font=meta_font,
        )
        draw.line(
            [(margin, y_offset + header_height - 28), (config.page_width - margin, y_offset + header_height - 28)],
            fill="black",
            width=3,
        )

        start = sheet_index * fragments_per_sheet
        end = min(start + fragments_per_sheet, len(png_paths))
        for local_index, png_path in enumerate(png_paths[start:end]):
            row = local_index // columns
            column = local_index % columns
            cell_x = margin + column * cell_width
            cell_y = y_offset + header_height + row * cell_height
            label = png_path.stem
            label_width, _ = text_size(draw, label, label_font)
            draw.text((cell_x + (max_qr_width - label_width) // 2, cell_y), label, fill="black", font=label_font)
            try:
                with Image.open(png_path) as image:
                    qr_image = image.convert("RGB")
                    paste_x = cell_x + (max_qr_width - qr_image.width) // 2
                    paste_y = cell_y + label_height
                    master.paste(qr_image, (paste_x, paste_y))
            except Exception as exc:
                raise PipelineError(f"Failed to paste QR image {png_path}: {exc}") from exc

    try:
        master.save(output_path, dpi=(config.dpi, config.dpi))
    except OSError as exc:
        raise PipelineError(f"Failed to save print ledger {output_path}: {exc}") from exc

    logger.info("Wrote print ledger graphic: %s", output_path)
    return output_path


def run_pipeline(config: PipelineConfig, logger: logging.Logger) -> dict[str, Path | FragmentManifest]:
    root = ensure_root(config.root)
    work_dir = root / WORK_DIR_NAME
    logger.info("Starting archive pipeline in %s", root)

    cleanup_environment(root, logger, dry_run=config.dry_run)
    runtime_dir = ensure_archive_runtimes(root, logger, dry_run=config.dry_run)
    compile_requirements(root, runtime_dir, logger, dry_run=config.dry_run)
    metadata = collect_stack_metadata(root, runtime_dir, logger)
    readme_path = write_archive_readme(root, metadata, logger, dry_run=config.dry_run)
    archive_path = create_tar_gz(root, logger, dry_run=config.dry_run)
    checksum = "0" * 64 if config.dry_run else sha256_file(archive_path, logger)
    checksum_path = write_checksum(root, checksum, logger, dry_run=config.dry_run)
    fragments_dir, manifest = fragment_archive(
        archive_path,
        work_dir,
        root,
        checksum,
        config.chunk_size,
        logger,
        dry_run=config.dry_run,
    )
    qr_dir = encode_fragments_to_qr(fragments_dir, work_dir, root, config, logger)
    ledger_path = stitch_visuals(qr_dir, checksum_path, root / PRINT_LEDGER_NAME, config, logger)

    if not config.keep_temp and work_dir.exists():
        remove_path(work_dir, root, logger, dry_run=config.dry_run)

    logger.info("Archive pipeline complete")
    return {
        "readme": readme_path,
        "archive": archive_path,
        "checksum": checksum_path,
        "fragments_dir": fragments_dir,
        "qr_dir": qr_dir,
        "ledger": ledger_path,
        "manifest": manifest,
    }


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    logger = configure_logging(config.verbose)
    try:
        run_pipeline(config, logger)
    except KeyboardInterrupt:
        logger.error("Archive pipeline interrupted by user")
        return 130
    except PipelineError as exc:
        logger.error("Archive pipeline failed: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected archive pipeline failure: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
