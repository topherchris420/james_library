#!/usr/bin/env python3
"""Repository integrity checks for CI."""

from __future__ import annotations

import pathlib


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC_DUPLICATE_TREE = REPO_ROOT / "src" / "src"
BUILD_SCRIPT = REPO_ROOT / "build.rs"
WEB_DIST = REPO_ROOT / "web" / "dist"
WEB_DIST_INDEX = WEB_DIST / "index.html"

def main() -> int:
    errors: list[str] = []

    if SRC_DUPLICATE_TREE.exists():
        errors.append(
            "Duplicate source tree detected at src/src. Remove it to avoid drift and ambiguous ownership."
        )

    if not BUILD_SCRIPT.exists() and not WEB_DIST_INDEX.exists():
        errors.append(
            "Missing web dashboard assets fallback: add build.rs or check in web/dist/index.html."
        )

    if errors:
        print("Repository integrity guard failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repository integrity guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
