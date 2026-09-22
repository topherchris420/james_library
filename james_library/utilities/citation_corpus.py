"""Local citation corpus: which files may count as papers, and exact quote spans.

Product markdown (README, souls, logs, docs/, assets/) is not evidence unless
``include_product_surface`` is set. A quote verifies only when the full
normalized span occurs in one corpus file.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

MIN_QUOTE_WORDS = 3

_BLOCKED_DIR_NAMES = frozenset({"docs", "assets"})
_DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        "meeting_archives",
    }
)
_PRODUCT_NAME_MARKERS = ("SOUL", "LOG", "MEETING")
_PRODUCT_NAME_PREFIXES = (
    "readme",
    "start_here",
    "contributing",
    "security",
    "architecture",
    "license",
)


@dataclass(frozen=True)
class CitationMatch:
    """A full-quote hit inside one corpus file."""

    source: str
    span_start: int
    span_end: int


def is_product_surface_name(name: str) -> bool:
    """Return True for README, SOUL, LOG, LICENSE, and the other product filenames."""

    upper = name.upper()
    lower = name.lower()
    if any(marker in upper for marker in _PRODUCT_NAME_MARKERS):
        return True
    return any(lower.startswith(prefix) for prefix in _PRODUCT_NAME_PREFIXES)


def resolve_corpus_root(library_path: str | Path, corpus_dir: str | None = None) -> Path:
    """Pick the directory whose files are allowed to verify citations.

    Order: explicit ``corpus_dir``, then ``RAIN_CORPUS_DIR``, then
    ``<library>/papers`` when that directory exists, otherwise ``library_path``.
    """

    library = Path(library_path).expanduser()
    explicit = (corpus_dir or "").strip() or (os.environ.get("RAIN_CORPUS_DIR") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = library / candidate
        return candidate
    papers = library / "papers"
    if papers.is_dir():
        return papers
    return library


def discover_corpus_files(
    root: str | Path,
    *,
    recursive: bool = False,
    exclude_dirs: set[str] | frozenset[str] | None = None,
    max_files: int = 400,
    include_product_surface: bool = False,
    allow_hello_os_py: bool = False,
) -> list[Path]:
    """List corpus files under ``root``, skipping product surface by default."""

    root_path = Path(root)
    if not root_path.is_dir():
        return []

    skipped_dirs = set(_DEFAULT_EXCLUDE_DIRS)
    skipped_dirs.update(_BLOCKED_DIR_NAMES)
    if exclude_dirs:
        skipped_dirs.update(exclude_dirs)

    found: list[Path] = []

    def keep(path: Path) -> bool:
        if not path.is_file():
            return False
        name = path.name
        if name.startswith("_") or name in skipped_dirs:
            return False
        if _path_has_blocked_parent(path, root_path):
            return False
        if not include_product_surface and is_product_surface_name(name):
            return False
        return _is_corpus_file(path, root_path, allow_hello_os_py=allow_hello_os_py)

    if recursive:
        for dirpath, dirs, files in os.walk(root_path):
            dirs[:] = [item for item in dirs if item not in skipped_dirs and not item.startswith(".")]
            for filename in files:
                candidate = Path(dirpath) / filename
                if keep(candidate):
                    found.append(candidate)
    else:
        for candidate in root_path.iterdir():
            if keep(candidate):
                found.append(candidate)

    found.sort()
    if max_files >= 0:
        return found[:max_files]
    return found


def find_quote_span(content: str, quote: str) -> tuple[int, int] | None:
    """Return ``[start, end)`` in ``content`` for the full quote, or None.

    Matching is case-insensitive and collapses whitespace. The returned indexes
    refer to the original ``content`` string. A quote shorter than three words
    never matches. A five-word prefix of a longer quote does not match.
    """

    normalized_quote = " ".join(quote.split()).lower()
    if len(normalized_quote.split()) < MIN_QUOTE_WORDS:
        return None
    normalized, origins = _normalize_with_origins(content)
    index = normalized.find(normalized_quote)
    if index < 0:
        return None
    start = origins[index]
    end = origins[index + len(normalized_quote) - 1] + 1
    return start, end


def verify_quote(papers: dict[str, str], quote: str) -> CitationMatch | None:
    """Find ``quote`` in ``papers`` values. Keys are the source names stored on a hit."""

    for source in sorted(papers):
        span = find_quote_span(papers[source], quote)
        if span is None:
            continue
        return CitationMatch(source=source, span_start=span[0], span_end=span[1])
    return None


def hash_corpus_files(paths: list[Path], root: str | Path) -> list[dict[str, str]]:
    """SHA-256 each corpus file. Paths are relative to ``root`` when possible."""

    root_path = Path(root).resolve()
    rows: list[dict[str, str]] = []
    for path in paths:
        resolved = path.resolve()
        try:
            rel = resolved.relative_to(root_path).as_posix()
        except ValueError:
            rel = path.name
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        rows.append({"path": rel, "sha256": digest})
    rows.sort(key=lambda row: row["path"])
    return rows


def citation_console_status(metadata: dict | None) -> str:
    """Classify a turn for the console: ``verified``, ``ungrounded``, or ``silent``.

    ``ungrounded`` is only used when quotes were required and none verified.
    Callers must not print a success checkmark for that status.
    """

    if not metadata:
        return "silent"
    if metadata.get("verified"):
        return "verified"
    if metadata.get("require_quotes") and metadata.get("citation_success") is False:
        return "ungrounded"
    return "silent"


def _path_has_blocked_parent(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return any(part.lower() in _BLOCKED_DIR_NAMES for part in relative.parts[:-1])


def _is_corpus_file(path: Path, root: Path, *, allow_hello_os_py: bool) -> bool:
    lower = path.name.lower()
    if lower.endswith((".md", ".txt")):
        return True
    if not allow_hello_os_py or not lower.endswith(".py"):
        return False
    if path.name == "hello_os.py":
        return True
    return path.parent.name == "hello_os" or root.name == "hello_os"


def _normalize_with_origins(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace to single spaces and map each normalized char to an original index."""

    chars: list[str] = []
    origins: list[int] = []
    pending_space = False
    started = False
    for index, char in enumerate(text):
        if char.isspace():
            if started:
                pending_space = True
            continue
        if pending_space:
            chars.append(" ")
            origins.append(index)
            pending_space = False
        chars.append(char.lower())
        origins.append(index)
        started = True
    return "".join(chars), origins
