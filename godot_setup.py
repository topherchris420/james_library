"""Automatic Godot 4 runtime setup for R.A.I.N. Lab.

Downloads the correct Godot 4 editor binary for the current OS and stores it
under ``.godot_runtime/`` in the repo root.  The launcher (``rain_lab.py``)
and health check (``rain_health_check.py``) automatically discover the binary
from this directory, so no manual ``RAIN_GODOT_BIN`` configuration is needed.

Usage
-----
    python godot_setup.py                  # interactive (prompts before download)
    python godot_setup.py --yes            # non-interactive (CI / scripts)
    python godot_setup.py --version 4.4.1  # pin a specific version
    python godot_setup.py --check          # just check if Godot is available
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import shutil
import stat
import zipfile
from pathlib import Path

try:
    import urllib.error
    import urllib.request
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = REPO_ROOT / ".godot_runtime"
MARKER_FILE = RUNTIME_DIR / ".godot_version"

# Godot GitHub release URL pattern
_RELEASE_BASE = "https://github.com/godotengine/godot/releases/download"

# Default Godot version to download
DEFAULT_GODOT_VERSION = "4.4.1"

# Platform → (archive_suffix, executable_name_inside_zip)
_PLATFORM_MAP = {
    ("Windows", "AMD64"): ("win64.exe.zip", "Godot_v{version}-stable_win64.exe"),
    ("Windows", "x86_64"): ("win64.exe.zip", "Godot_v{version}-stable_win64.exe"),
    ("Windows", "ARM64"): ("win64.exe.zip", "Godot_v{version}-stable_win64.exe"),
    ("Linux", "x86_64"): ("linux.x86_64.zip", "Godot_v{version}-stable_linux.x86_64"),
    ("Linux", "aarch64"): ("linux.arm64.zip", "Godot_v{version}-stable_linux.arm64"),
    ("Darwin", "x86_64"): ("macos.universal.zip", "Godot.app/Contents/MacOS/Godot"),
    ("Darwin", "arm64"): ("macos.universal.zip", "Godot.app/Contents/MacOS/Godot"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_platform() -> tuple[str, str]:
    """Return (system, machine) normalised to match _PLATFORM_MAP keys."""
    system = platform.system()          # Windows, Linux, Darwin
    machine = platform.machine()        # AMD64, x86_64, aarch64, arm64
    return system, machine


def _get_platform_info(version: str) -> tuple[str, str, str] | None:
    """Return (download_url, zip_name, exe_name_inside_zip) or None."""
    system, machine = _detect_platform()
    key = (system, machine)
    if key not in _PLATFORM_MAP:
        return None
    archive_suffix, exe_template = _PLATFORM_MAP[key]
    exe_name = exe_template.format(version=version)
    zip_name = f"Godot_v{version}-stable_{archive_suffix}"
    url = f"{_RELEASE_BASE}/{version}-stable/{zip_name}"
    return url, zip_name, exe_name


def _local_binary_name(version: str) -> str:
    """Determine the final binary name stored in .godot_runtime/."""
    system, _ = _detect_platform()
    if system == "Windows":
        return f"godot_v{version}.exe"
    if system == "Darwin":
        return f"godot_v{version}"
    return f"godot_v{version}"


def get_installed_binary() -> Path | None:
    """Return the path to an already-downloaded Godot binary, or None."""
    if not RUNTIME_DIR.exists():
        return None
    # Look for any godot* executable in the runtime dir
    for child in sorted(RUNTIME_DIR.iterdir(), reverse=True):
        if child.name.startswith("godot_v") and child.is_file():
            return child
    # macOS: check for Godot.app bundle
    app_bundle = RUNTIME_DIR / "Godot.app" / "Contents" / "MacOS" / "Godot"
    if app_bundle.exists():
        return app_bundle
    return None


def get_installed_version() -> str | None:
    """Read the pinned version from the marker file."""
    if MARKER_FILE.exists():
        return MARKER_FILE.read_text(encoding="utf-8").strip()
    return None


# ---------------------------------------------------------------------------
# Download & Install
# ---------------------------------------------------------------------------


def download_godot(version: str, verbose: bool = True) -> Path:
    """Download and extract Godot binary. Returns path to the executable."""
    if not HAS_URLLIB:
        raise RuntimeError("urllib is not available — cannot download Godot automatically.")

    info = _get_platform_info(version)
    if info is None:
        system, machine = _detect_platform()
        raise RuntimeError(
            f"No Godot download available for {system}/{machine}. "
            f"Please install Godot 4 manually and set RAIN_GODOT_BIN."
        )

    url, zip_name, exe_inside_zip = info
    local_bin_name = _local_binary_name(version)
    system, _ = _detect_platform()

    # Create runtime directory
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"  Downloading Godot {version} for {platform.system()} {platform.machine()}...")
        print(f"  URL: {url}")

    # Download
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RAIN-Lab-Setup/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Download failed (HTTP {exc.code}): {url}\n"
            f"Check that Godot version {version} exists at:\n"
            f"  https://github.com/godotengine/godot/releases/tag/{version}-stable"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc

    if verbose:
        size_mb = len(data) / (1024 * 1024)
        print(f"  Downloaded {size_mb:.1f} MB")

    # Extract
    if verbose:
        print(f"  Extracting...")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if system == "Darwin":
            # macOS: extract the full Godot.app bundle
            zf.extractall(RUNTIME_DIR)
            dest = RUNTIME_DIR / "Godot.app" / "Contents" / "MacOS" / "Godot"
            if dest.exists():
                dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        else:
            # Windows/Linux: extract just the executable
            # Find the executable entry (may be at root or nested)
            exe_entry = None
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1] if "/" in name else name
                if basename == exe_inside_zip.rsplit("/", 1)[-1]:
                    exe_entry = name
                    break
            if exe_entry is None:
                # Fallback: pick the largest file
                entries = [(info.file_size, info.filename) for info in zf.infolist() if not info.is_dir()]
                entries.sort(reverse=True)
                if entries:
                    exe_entry = entries[0][1]

            if exe_entry is None:
                raise RuntimeError(f"Could not find Godot executable in downloaded archive.")

            dest = RUNTIME_DIR / local_bin_name
            with zf.open(exe_entry) as src, open(dest, "wb") as dst:
                dst.write(src.read())

            # Make executable on Linux
            if system != "Windows":
                dest.chmod(dest.stat().st_mode | stat.S_IEXEC)

    # Write version marker
    MARKER_FILE.write_text(version, encoding="utf-8")

    if verbose:
        print(f"  ✓ Installed to: {dest}")

    return dest


# ---------------------------------------------------------------------------
# Check / Status
# ---------------------------------------------------------------------------


def check_godot_status(verbose: bool = True) -> dict:
    """Check Godot availability. Returns status dict."""
    result = {
        "installed": False,
        "binary_path": None,
        "version": None,
        "system_godot": None,
    }

    # Check .godot_runtime/
    local_bin = get_installed_binary()
    if local_bin:
        result["installed"] = True
        result["binary_path"] = str(local_bin)
        result["version"] = get_installed_version()
        if verbose:
            print(f"  ✓ Godot found: {local_bin}")
            print(f"    Version: {result['version'] or 'unknown'}")
        return result

    # Check system PATH
    for name in ("godot4", "godot"):
        found = shutil.which(name)
        if found:
            result["installed"] = True
            result["binary_path"] = found
            result["system_godot"] = found
            if verbose:
                print(f"  ✓ Godot found on PATH: {found}")
            return result

    # Check RAIN_GODOT_BIN env var
    env_bin = os.environ.get("RAIN_GODOT_BIN", "").strip()
    if env_bin and Path(env_bin).exists():
        result["installed"] = True
        result["binary_path"] = env_bin
        if verbose:
            print(f"  ✓ Godot found via RAIN_GODOT_BIN: {env_bin}")
        return result

    if verbose:
        print("  ✗ Godot not found.")
        print("    Run: python godot_setup.py")
    return result


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def uninstall_godot(verbose: bool = True) -> bool:
    """Remove the .godot_runtime/ directory."""
    if RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
        if verbose:
            print(f"  ✓ Removed {RUNTIME_DIR}")
        return True
    if verbose:
        print("  Nothing to remove.")
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatic Godot 4 runtime setup for R.A.I.N. Lab.",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=DEFAULT_GODOT_VERSION,
        help=f"Godot version to download (default: {DEFAULT_GODOT_VERSION}).",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt (for CI/scripts).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check if Godot is available, don't download.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the downloaded Godot runtime.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    print()
    print("=" * 60)
    print("  R.A.I.N. Lab — Godot Runtime Setup")
    print("=" * 60)
    print()

    # --uninstall
    if args.uninstall:
        uninstall_godot()
        return 0

    # --check
    if args.check:
        status = check_godot_status(verbose=True)
        return 0 if status["installed"] else 1

    # Check if already installed
    existing = get_installed_binary()
    installed_ver = get_installed_version()
    if existing and installed_ver == args.version:
        print(f"  ✓ Godot {args.version} is already installed.")
        print(f"    Path: {existing}")
        print()
        return 0

    if existing and installed_ver != args.version:
        print(f"  Godot {installed_ver} is installed, upgrading to {args.version}...")
    else:
        system, machine = _detect_platform()
        print(f"  Platform: {system} {machine}")

        info = _get_platform_info(args.version)
        if info is None:
            print(f"\n  ✗ No Godot download available for {system}/{machine}.")
            print(f"    Please install Godot 4 manually: https://godotengine.org/download")
            print(f"    Then set: RAIN_GODOT_BIN=/path/to/godot")
            return 1

        url, _, _ = info
        print(f"  Version: {args.version}")
        print(f"  Source:  {url}")
        print()

    # Confirm
    if not args.yes:
        try:
            answer = input("  Download and install? [Y/n] ").strip().lower()
            if answer and answer not in ("y", "yes"):
                print("  Cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return 0

    print()

    try:
        binary_path = download_godot(args.version, verbose=True)
    except RuntimeError as exc:
        print(f"\n  ✗ {exc}")
        return 1

    print()
    print("  ✓ Godot setup complete!")
    print(f"    Binary: {binary_path}")
    print()
    print("  The R.A.I.N. Lab launcher will automatically find this binary.")
    print("  Try: python rain_lab.py --mode chat --ui auto --topic \"hello world\"")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
