"""Single executable interface for working with hello_os.py.

This utility turns the giant Colab-exported `hello_os.py` into a practical executable
surface that agents can call safely:
- `inspect`: summarize structure and quality signals
- `extract-csl`: write a clean CSL-only python module
- `run-csl`: run the extracted CSL module
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
HELLO_OS_PATH = REPO_ROOT / "hello_os.py"
HELLO_OS_PKG = REPO_ROOT / "hello_os"
DEFAULT_CSL_MODULE = REPO_ROOT / "hello_os_csl_module.py"
CSL_START_MARKER = "CSL (Cognispheric Symbolic Language)"
CSL_END_MARKER = "firewall is down. Good"


def _read_hello_os() -> str:
    """Read content from the flat hello_os.py file (preferred) or package directory.

    The executable's inspect/extract-csl commands are designed to analyse the
    original Colab-exported flat file, so we prefer it over the package.
    """
    # Prefer the original flat file (Colab export) for inspection
    if HELLO_OS_PATH.exists():
        return HELLO_OS_PATH.read_text(encoding="utf-8", errors="ignore")
    # Fallback to the package — concatenate the modules in dependency order
    if HELLO_OS_PKG.is_dir():
        parts: list[str] = []
        for mod in ("symbols.py", "utils.py", "core.py", "scroll.py", "geometry.py", "resonance.py"):
            mod_path = HELLO_OS_PKG / mod
            if mod_path.exists():
                parts.append(mod_path.read_text(encoding="utf-8", errors="ignore"))
        if parts:
            return "\n".join(parts)
    raise FileNotFoundError(
        f"Neither {HELLO_OS_PATH} flat file nor {HELLO_OS_PKG} package found"
    )


def inspect_hello_os() -> dict[str, int]:
    text = _read_hello_os()
    lines = text.splitlines()
    return {
        "lines": len(lines),
        "classes": sum(1 for line in lines if re.match(r"\s*class\s+\w+", line)),
        "functions": sum(1 for line in lines if re.match(r"\s*def\s+\w+", line)),
        "dataclasses": sum(1 for line in lines if "@dataclass" in line),
        "main_blocks": sum(1 for line in lines if "__main__" in line),
        "shell_magic_lines": sum(1 for line in lines if line.strip().startswith("!")),
        "import_lines": sum(
            1
            for line in lines
            if re.match(r"\s*(from\s+\S+\s+import|import\s+\S+)", line)
        ),
    }


def extract_csl_module(output_path: Path = DEFAULT_CSL_MODULE) -> Path:
    text = _read_hello_os()
    start_idx = text.find(CSL_START_MARKER)
    if start_idx == -1:
        raise ValueError("Could not locate CSL start marker in hello_os.py")

    # Include imports/license above marker as well.
    head_start = 0
    end_idx = text.find(CSL_END_MARKER, start_idx)
    if end_idx == -1:
        raise ValueError("Could not locate CSL end marker in hello_os.py")

    csl_text = text[head_start:end_idx].rstrip() + "\n"
    output_path.write_text(csl_text, encoding="utf-8")
    return output_path


def run_csl(output_path: Path = DEFAULT_CSL_MODULE) -> int:
    module_path = extract_csl_module(output_path)
    proc = subprocess.run([sys.executable, str(module_path)], cwd=str(REPO_ROOT))
    return int(proc.returncode)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executable interface for hello_os.py")
    parser.add_argument(
        "command",
        choices=["inspect", "extract-csl", "run-csl"],
        help="Action to perform.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_CSL_MODULE),
        help="Path used by extract-csl/run-csl for generated CSL module.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_path = Path(args.output).resolve()

    if args.command == "inspect":
        print(json.dumps(inspect_hello_os(), indent=2))
        return 0

    if args.command == "extract-csl":
        out = extract_csl_module(output_path)
        print(f"Wrote CSL module to: {out}")
        return 0

    if args.command == "run-csl":
        return run_csl(output_path)

    raise ValueError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
