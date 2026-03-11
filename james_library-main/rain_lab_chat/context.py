"""Research paper context loading and citation verification."""

import bisect
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rain_lab_chat._logging import get_logger
from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

log = get_logger(__name__)

NON_PAPER_STEMS = {
    "AGENTS",
    "ARCHITECTURE",
    "BACKUP_RESTORE",
    "BINARY_RELEASES",
    "CHANGELOG",
    "CLAUDE",
    "CONTRIBUTING",
    "FIRST_RUN_CHECKLIST",
    "GODOT_SCENE_THEME_BLUEPRINT",
    "INSTALL_RAIN",
    "LICENSE",
    "PRODUCT_ROADMAP",
    "PRODUCTION_READINESS",
    "PULL_REQUEST_TEMPLATE",
    "README",
    "README_JAMES_READER",
    "README_SIMPLE",
    "RELEASE_CHECKLIST",
    "SECURITY",
    "SOUL",
    "TROUBLESHOOTING",
}
EXCLUDE_TAGS = {"SOUL", "LOG", "MEETING"}
TITLE_CONNECTOR_WORDS = {"a", "an", "and", "for", "from", "in", "is", "of", "on", "the", "to", "via", "with"}
TITLE_TOKEN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?")


class ContextManager:
    """Reads and manages research paper context - FULL PAPER MODE"""

    def __init__(self, config: Config):

        self.config = config

        self.lab_path = Path(config.library_path)

        self.loaded_papers: Dict[str, str] = {}

        self.global_context_index: str = ""

        self.context_offsets: List[Tuple[int, str]] = []

        self.offset_keys: List[int] = []

        self.paper_list: List[str] = []
        self.paper_title_allowlist = {
            title.strip().casefold() for title in config.paper_title_allowlist if title.strip()
        }

    def _has_obvious_paper_title(self, path: Path) -> bool:
        """Allow only human-readable title-style paper filenames."""
        stem = path.stem.strip()
        if not stem:
            return False

        if self.paper_title_allowlist:
            return stem.casefold() in self.paper_title_allowlist

        upper_stem = stem.upper()
        if upper_stem in NON_PAPER_STEMS:
            return False

        # Exclude code-like names (snake_case, kebab-case, dotted module names, numeric IDs).
        if any(ch in stem for ch in ("_", "/", "\\")):
            return False
        if "." in stem and " " not in stem:
            return False
        if any(ch.isdigit() for ch in stem):
            return False

        tokens = TITLE_TOKEN_RE.findall(stem)
        if len(tokens) < 2:
            return False

        for token in tokens:
            if token.lower() in TITLE_CONNECTOR_WORDS:
                continue
            if not token[0].isupper():
                return False

        return True

    def _has_excluded_tag(self, path: Path) -> bool:
        tokens = re.findall(r"[A-Z]+", path.stem.upper())
        return any(tag in tokens for tag in EXCLUDE_TAGS)

    def _discover_files(self) -> List[Path]:
        """Discover candidate research files, optionally including nested directories."""

        skip_dirs = set(self.config.library_exclude_dirs)

        allowed_suffixes = (".md", ".txt")

        candidates = []

        if self.config.recursive_library_scan:
            for root, dirs, files in os.walk(self.lab_path):
                # Prune skip_dirs in-place to prevent traversing them

                dirs[:] = [d for d in dirs if d not in skip_dirs]

                for file in files:
                    # 1. Fast suffix check (string op, no object creation)

                    name_lower = file.lower()

                    if not name_lower.endswith(allowed_suffixes):
                        continue

                    # 2. Check exclusions

                    if self._has_excluded_tag(Path(file)):
                        continue

                    if file in skip_dirs:
                        continue

                    candidate = Path(root) / file
                    if self._has_obvious_paper_title(candidate):
                        candidates.append(candidate)

        else:
            # Non-recursive scan (top-level only)

            for f in self.lab_path.iterdir():
                if not f.is_file():
                    continue

                name = f.name

                name_lower = name.lower()

                if not name_lower.endswith(allowed_suffixes):
                    continue

                if name in skip_dirs:
                    continue

                if self._has_excluded_tag(f):
                    continue

                if self._has_obvious_paper_title(f):
                    candidates.append(f)

        return sorted(candidates)[: self.config.max_library_files]

    def get_library_context(self, verbose: bool = False) -> Tuple[str, List[str]]:
        """Read COMPLETE papers from local library"""

        # Ensure repeated calls don't keep stale/duplicated state.

        self.loaded_papers = {}

        self.global_context_index = ""

        self.context_offsets = []

        self.offset_keys = []

        self.paper_list = []

        if verbose:
            log.info("Accessing Research Library at: %s", self.lab_path)

        if not self.lab_path.exists():
            log.error("Library path does not exist: %s", self.lab_path)

            return "Library not accessible.", []

        buffer = []

        # Load all valid text files (recursive by default)

        all_files = self._discover_files()

        if verbose:
            scope = "recursive" if self.config.recursive_library_scan else "top-level"

            log.info("Scan mode: %s; files discovered: %d", scope, len(all_files))

        if not all_files:
            log.warning("No research papers found in library.")

            return "No research papers found in library.", []

        if verbose:
            log.info("Found %d papers.", len(all_files))

        total_chars = 0

        current_offset = 0

        index_parts = []

        for filepath in all_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    # Store FULL content for citation verification

                    paper_ref = str(filepath.relative_to(self.lab_path))

                    self.loaded_papers[paper_ref] = content

                    self.paper_list.append(paper_ref)

                    # Build Global Index for fast O(1) searches

                    content_lower = content.lower()

                    self.context_offsets.append((current_offset, paper_ref))

                    index_parts.append(content_lower)

                    current_offset += len(content_lower) + 1  # +1 for delimiter

                    # Include full paper up to snippet length (25k = essentially full)

                    remaining_budget = self.config.total_context_length - total_chars

                    if remaining_budget > 1000:
                        # SANITIZE CONTENT before adding to prompt

                        safe_content = sanitize_text(content)

                        to_include = min(len(safe_content), self.config.context_snippet_length, remaining_budget)

                        buffer.append(f"--- PAPER: {paper_ref} ---\n{safe_content[:to_include]}\n")

                        total_chars += to_include

                        # Show what percentage of paper was loaded

                        if verbose:
                            coverage = (to_include / len(content)) * 100 if len(content) > 0 else 100

                            log.info("Loaded: %s (%s chars, %.0f%% coverage)", paper_ref, f"{to_include:,}", coverage)

                    else:
                        if verbose:
                            log.info("Skipped %s (budget exhausted)", paper_ref)

            except Exception as e:
                if verbose:
                    log.warning("Error reading %s: %s", filepath.name, e)

                continue

        # Finalize global index

        self.global_context_index = "\0".join(index_parts)

        self.offset_keys = [o[0] for o in self.context_offsets]

        combined = "\n".join(buffer)

        if verbose:
            log.info("Total context loaded: %s characters", f"{len(combined):,}")
            log.info("Papers with full coverage: %d", len(list(self.loaded_papers.keys())))

        return combined, self.paper_list

    def verify_citation(self, quote: str, fuzzy: bool = True) -> Optional[str]:
        """Verify if a quote exists in loaded papers using global index"""

        quote_clean = quote.strip().lower()

        # Skip very short quotes

        if len(quote_clean.split()) < 3:
            return None

        windows_to_check = []

        if fuzzy:
            quote_words = quote_clean.split()

            if len(quote_words) > 3:
                # Check multiple word windows for better matching

                # Try first 5 words, then first 8, then middle section

                raw_windows = [
                    " ".join(quote_words[:5]),
                    " ".join(quote_words[:8]) if len(quote_words) >= 8 else None,
                    " ".join(quote_words[2:7]) if len(quote_words) >= 7 else None,
                ]

                # Filter out None values once

                windows_to_check = [w for w in raw_windows if w]

        else:
            windows_to_check = [quote_clean]

        # Use global index search

        best_offset = -1

        for window in windows_to_check:
            # Find earliest occurrence in global index

            idx = self.global_context_index.find(window)

            if idx != -1:
                # If we found a match, check if it's earlier than previous matches

                if best_offset == -1 or idx < best_offset:
                    best_offset = idx

        if best_offset != -1:
            # Map offset to paper using binary search

            # bisect_right returns insertion point to maintain order

            paper_idx = bisect.bisect_right(self.offset_keys, best_offset) - 1

            if 0 <= paper_idx < len(self.context_offsets):
                return self.context_offsets[paper_idx][1]

        return None


# --- WEB SEARCH MANAGER ---
