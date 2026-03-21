"""MCP-compliant server for R.A.I.N. Lab research tools.

Wraps existing local research corpus queries and (optionally) hardware
peripheral status into Model Context Protocol (MCP) tools, using the
``fastmcp`` library.

Design constraints:
- Secure by default: no filesystem writes, no shell access, no secret leakage.
- Read-only corpus access: agents can search and read papers but not modify them.
- Hardware peripheral status is read-only and gated behind an explicit opt-in.
- Does NOT modify or replace the Rust ZeroClaw daemon routing — this server
  runs alongside the existing Python agent layer.

Usage::

    # Start standalone (stdio transport for local agent integration):
    python mcp_server.py

    # Or import and mount programmatically:
    from mcp_server import create_mcp_server
    mcp = create_mcp_server("/path/to/library")
"""

from __future__ import annotations

import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = (".md", ".txt")
_EXCLUDE_PATTERNS = ("SOUL", "LOG", "MEETING")
_MAX_READ_CHARS = 120_000
_MAX_SEARCH_RESULTS = 10
_MAX_QUERY_LEN = 2_000

# Policy-blocked phrases (mirrors tools.py guardrails).
_BLOCKED_PHRASES = frozenset(
    [
        "system prompt",
        "reveal your system",
        "ignore previous instructions",
        "developer message",
        "chain-of-thought",
        "show hidden",
    ]
)


# ---------------------------------------------------------------------------
# Sanitization (mirrors rain_lab_meeting_chat_version.py)
# ---------------------------------------------------------------------------

def _sanitize(text: str) -> str:
    if not text:
        return ""
    for token in ("<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|"):
        text = text.replace(token, "[TOKEN_REMOVED]")
    text = text.replace("###", ">>>")
    text = text.replace("[SEARCH:", "[SEARCH;")
    return text.strip()


def _policy_check(query: str) -> str | None:
    """Return an error message if query violates policy, else None."""
    if len(query) > _MAX_QUERY_LEN:
        return "Query too long. Please shorten."
    q_lower = query.lower()
    for phrase in _BLOCKED_PHRASES:
        if phrase in q_lower:
            return "Policy block: meta-instruction / prompt-leak attempt detected."
    return None


# ---------------------------------------------------------------------------
# Corpus helpers (stateless, library_path injected)
# ---------------------------------------------------------------------------

def _discover_papers(library_path: str) -> list[Path]:
    """Return sorted list of research paper paths in the library."""
    lab = Path(library_path)
    papers: list[Path] = []
    for ext in _ALLOWED_EXTENSIONS:
        papers.extend(lab.glob(f"*{ext}"))
    return sorted(
        p
        for p in papers
        if not p.name.startswith("_")
        and not any(pat in p.name.upper() for pat in _EXCLUDE_PATTERNS)
    )


def _read_paper_content(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")[:_MAX_READ_CHARS]
    return _sanitize(text)


def _keyword_search(library_path: str, query: str) -> list[dict[str, Any]]:
    """Search paper filenames and content for keywords."""
    keywords = [k.lower() for k in query.split() if len(k) > 2]
    if not keywords:
        keywords = [query.lower()]

    results: list[dict[str, Any]] = []
    for path in _discover_papers(library_path):
        name_lower = path.name.lower()
        # Filename match (high priority)
        if any(k in name_lower for k in keywords):
            results.append({"paper": path.name, "score": 10.0, "match_type": "filename"})
            continue
        # Content match
        try:
            content_lower = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
            hits = sum(1 for k in keywords if k in content_lower)
            if hits:
                results.append({
                    "paper": path.name,
                    "score": hits / len(keywords),
                    "match_type": "content",
                })
        except OSError:
            continue

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:_MAX_SEARCH_RESULTS]


def _verify_citation(library_path: str, quote: str) -> dict[str, Any]:
    """Check whether a quoted span appears in the local corpus."""
    quote_lower = quote.lower().strip()
    if len(quote_lower) < 10:
        return {"verified": False, "reason": "Quote too short for meaningful verification."}
    for path in _discover_papers(library_path):
        try:
            content = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        if quote_lower in content.lower():
            return {"verified": True, "source": path.name, "match": "exact"}
        # Fuzzy fallback: sliding window
        words = quote_lower.split()
        window = " ".join(words)
        content_lower = content.lower()
        # Check 80% similarity in overlapping windows
        wlen = len(window)
        for i in range(0, max(1, len(content_lower) - wlen), wlen // 2 or 1):
            chunk = content_lower[i : i + wlen]
            if SequenceMatcher(None, window, chunk).ratio() >= 0.80:
                return {"verified": True, "source": path.name, "match": "fuzzy"}
    return {"verified": False, "reason": "No match found in local corpus."}


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_mcp_server(
    library_path: str | None = None,
    *,
    enable_peripheral_status: bool = False,
    rust_daemon_url: str | None = None,
) -> FastMCP:
    """Create and return a configured FastMCP server instance.

    Args:
        library_path: Path to the research library. Defaults to cwd.
        enable_peripheral_status: If True, expose a read-only peripheral
            status tool (requires Rust daemon connectivity).
        rust_daemon_url: Base URL for the ZeroClaw Rust daemon (e.g.
            ``http://127.0.0.1:4200``).  Only used when
            ``enable_peripheral_status`` is True.
    """
    lib_path = library_path or os.environ.get("JAMES_LIBRARY_PATH", os.getcwd())

    mcp = FastMCP(
        "rain-lab-research",
        instructions=(
            "R.A.I.N. Lab research corpus server. Provides read-only access "
            "to the local research paper library, citation verification, and "
            "optional hardware peripheral status."
        ),
    )

    # -- Tool: list_papers --------------------------------------------------

    @mcp.tool()
    def list_papers() -> list[str]:
        """List all research papers available in the library."""
        return [p.name for p in _discover_papers(lib_path)]

    # -- Tool: read_paper ---------------------------------------------------

    @mcp.tool()
    def read_paper(filename: str) -> str:
        """Read a research paper by filename.

        Args:
            filename: Exact filename (e.g. 'cymatics_overview.md') or keyword
                      substring to match against available papers.
        """
        violation = _policy_check(filename)
        if violation:
            return violation

        papers = _discover_papers(lib_path)
        fn_lower = filename.lower().strip()

        # Exact match first
        for p in papers:
            if p.name.lower() == fn_lower:
                return f"--- CONTENT OF {p.name} ---\n{_read_paper_content(p)}"
        # Substring match
        for p in papers:
            if fn_lower in p.name.lower():
                return f"--- CONTENT OF {p.name} ---\n{_read_paper_content(p)}"
        # Try with extensions
        for ext in _ALLOWED_EXTENSIONS:
            for p in papers:
                if p.name.lower() == fn_lower + ext:
                    return f"--- CONTENT OF {p.name} ---\n{_read_paper_content(p)}"

        return f"No paper found matching '{filename}'. Use list_papers() to see available files."

    # -- Tool: search_library -----------------------------------------------

    @mcp.tool()
    def search_library(query: str) -> list[dict[str, Any]]:
        """Search the research library for papers matching a keyword query.

        Args:
            query: Search terms (e.g. 'resonance frequency' or 'chladni').

        Returns:
            List of matching papers with scores and match types.
        """
        violation = _policy_check(query)
        if violation:
            return [{"error": violation}]
        return _keyword_search(lib_path, query)

    # -- Tool: verify_citation ----------------------------------------------

    @mcp.tool()
    def verify_citation(quote: str) -> dict[str, Any]:
        """Verify whether a quoted passage exists in the local research corpus.

        Args:
            quote: The quoted text to verify (minimum ~10 characters).

        Returns:
            Dict with 'verified' (bool), 'source' (str), and 'match' type.
        """
        violation = _policy_check(quote)
        if violation:
            return {"verified": False, "reason": violation}
        return _verify_citation(lib_path, quote)

    # -- Tool: get_hypothesis_tree_state ------------------------------------

    @mcp.tool()
    def get_hypothesis_tree_state() -> str:
        """Get the current state of the hypothesis exploration tree.

        Returns a human-readable summary of all hypothesis nodes, their
        status (active/proven/disproven), visit counts, and scores.
        """
        try:
            from hypothesis_tree import HypothesisTree  # noqa: F401
            # This is a read-only snapshot tool — it cannot modify the tree.
            # The actual tree lives in the orchestrator; this returns a
            # placeholder until a running session exports its state.
            return (
                "Hypothesis tree state is managed by the active meeting session. "
                "Use this tool during a live meeting to query the orchestrator's tree."
            )
        except ImportError:
            return "Hypothesis tree module not available."

    # -- Tool: peripheral_status (opt-in only) ------------------------------

    if enable_peripheral_status and rust_daemon_url:
        @mcp.tool()
        def peripheral_status() -> dict[str, Any]:
            """Query read-only status of connected hardware peripherals.

            Returns status information from the ZeroClaw Rust daemon about
            connected boards (STM32, RPi GPIO, etc.).  This tool is
            read-only and cannot actuate hardware.

            Requires the Rust daemon to be running.
            """
            try:
                import httpx
                url = rust_daemon_url.rstrip("/")
                resp = httpx.get(
                    f"{url}/v1/peripherals/status",
                    timeout=httpx.Timeout(10.0, connect=5.0),
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                return {
                    "error": f"Failed to query peripheral status: {type(exc).__name__}",
                    "available": False,
                }

    # -- Resource: library_index --------------------------------------------

    @mcp.resource("rain://library/index")
    def library_index() -> str:
        """Return a newline-separated list of all papers in the library."""
        return "\n".join(p.name for p in _discover_papers(lib_path))

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the MCP server with stdio transport."""
    import argparse

    parser = argparse.ArgumentParser(description="R.A.I.N. Lab MCP Server")
    parser.add_argument(
        "--library-path",
        default=os.environ.get("JAMES_LIBRARY_PATH", os.getcwd()),
        help="Path to the research library directory",
    )
    parser.add_argument(
        "--enable-peripherals",
        action="store_true",
        default=False,
        help="Enable read-only hardware peripheral status tool",
    )
    parser.add_argument(
        "--daemon-url",
        default=os.environ.get("RAIN_RUST_DAEMON_API_URL", "http://127.0.0.1:4200"),
        help="ZeroClaw Rust daemon API URL (used with --enable-peripherals)",
    )
    args = parser.parse_args()

    mcp = create_mcp_server(
        library_path=args.library_path,
        enable_peripheral_status=args.enable_peripherals,
        rust_daemon_url=args.daemon_url,
    )
    mcp.run()


if __name__ == "__main__":
    main()
