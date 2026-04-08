"""Context management — reads and indexes the research paper library."""

from __future__ import annotations

import bisect
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import Config
from .sanitize import sanitize_text


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

    def _discover_files(self) -> List[Path]:
        """Discover candidate research files, optionally including nested directories."""

        skip_dirs = set(self.config.library_exclude_dirs)
        allowed_suffixes = (".md", ".txt", ".py")
        exclude_patterns = ["SOUL", "LOG", "MEETING"]
        candidates = []

        if self.config.recursive_library_scan:
            for root, dirs, files in os.walk(self.lab_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                parent_name = os.path.basename(root)
                is_hello_os_dir = parent_name == "hello_os"

                for file in files:
                    name_lower = file.lower()
                    if not name_lower.endswith(allowed_suffixes):
                        continue
                    name_upper = file.upper()
                    if any(p in name_upper for p in exclude_patterns):
                        continue
                    if file in skip_dirs:
                        continue

                    is_md_txt = name_lower.endswith((".md", ".txt"))
                    is_valid_py = False
                    if name_lower.endswith(".py"):
                        if file == "hello_os.py":
                            is_valid_py = True
                        elif is_hello_os_dir:
                            is_valid_py = True

                    if is_md_txt or is_valid_py:
                        candidates.append(Path(root) / file)

        else:
            for f in self.lab_path.iterdir():
                if not f.is_file():
                    continue
                name = f.name
                name_lower = name.lower()
                if not name_lower.endswith(allowed_suffixes):
                    continue
                if name in skip_dirs:
                    continue
                name_upper = name.upper()
                if any(p in name_upper for p in exclude_patterns):
                    continue

                is_md_txt = name_lower.endswith((".md", ".txt"))
                is_valid_py = False
                if name_lower.endswith(".py"):
                    if name == "hello_os.py":
                        is_valid_py = True
                    elif self.lab_path.name == "hello_os":
                        is_valid_py = True

                if is_md_txt or is_valid_py:
                    candidates.append(f)

        return sorted(candidates)[: self.config.max_library_files]

    def get_library_context(self, verbose: bool = False) -> Tuple[str, List[str]]:
        """Read COMPLETE papers from local library."""

        self.loaded_papers = {}
        self.global_context_index = ""
        self.context_offsets = []
        self.offset_keys = []
        self.paper_list = []

        if verbose:
            print(f"\n\U0001f4c2 Accessing Research Library at: {self.lab_path}")

        if not self.lab_path.exists():
            print(f"\u274c Library path does not exist: {self.lab_path}")
            return "Library not accessible.", []

        buffer = []
        all_files = self._discover_files()

        if verbose:
            scope = "recursive" if self.config.recursive_library_scan else "top-level"
            print(f"   \u2022 Scan mode: {scope}; files discovered: {len(all_files)}")

        if not all_files:
            print("\u26a0\ufe0f  No research papers found in library.")
            return "No research papers found in library.", []

        if verbose:
            print(f"   \u2713 Found {len(all_files)} papers.\n")

        total_chars = 0
        current_offset = 0
        index_parts = []

        for filepath in all_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                paper_ref = str(filepath.relative_to(self.lab_path))
                self.loaded_papers[paper_ref] = content
                self.paper_list.append(paper_ref)

                content_lower = content.lower()
                self.context_offsets.append((current_offset, paper_ref))
                index_parts.append(content_lower)
                current_offset += len(content_lower) + 1

                remaining_budget = self.config.total_context_length - total_chars

                if remaining_budget > 1000:
                    safe_content = sanitize_text(content)
                    to_include = min(len(safe_content), self.config.context_snippet_length, remaining_budget)
                    buffer.append(f"--- PAPER: {paper_ref} ---\n{safe_content[:to_include]}\n")
                    total_chars += to_include

                    if verbose:
                        coverage = (to_include / len(content)) * 100 if len(content) > 0 else 100
                        print(f"     \u2713 Loaded: {paper_ref} ({to_include:,} chars, {coverage:.0f}% coverage)")
                else:
                    if verbose:
                        print(f"     \u26a0 Skipped {paper_ref} (budget exhausted)")

            except Exception as e:
                if verbose:
                    print(f"     \u2717 Error reading {filepath.name}: {e}")
                continue

        self.global_context_index = "\0".join(index_parts)
        self.offset_keys = [o[0] for o in self.context_offsets]
        combined = "\n".join(buffer)

        if verbose:
            print(f"\n   \U0001f4ca Total context loaded: {len(combined):,} characters")
            print(f"   \U0001f4ca Papers with full coverage: {len([p for p in self.loaded_papers.keys()])}")

        return combined, self.paper_list

    def verify_citation(self, quote: str, fuzzy: bool = True) -> Optional[str]:
        """Verify if a quote exists in loaded papers using global index."""

        quote_clean = quote.strip().lower()

        if len(quote_clean.split()) < 3:
            return None

        windows_to_check = []

        if fuzzy:
            quote_words = quote_clean.split()
            if len(quote_words) > 3:
                raw_windows = [
                    " ".join(quote_words[:5]),
                    " ".join(quote_words[:8]) if len(quote_words) >= 8 else None,
                    " ".join(quote_words[2:7]) if len(quote_words) >= 7 else None,
                ]
                windows_to_check = [w for w in raw_windows if w]
        else:
            windows_to_check = [quote_clean]

        best_offset = -1
        for window in windows_to_check:
            idx = self.global_context_index.find(window)
            if idx != -1:
                if best_offset == -1 or idx < best_offset:
                    best_offset = idx

        if best_offset != -1:
            paper_idx = bisect.bisect_right(self.offset_keys, best_offset) - 1
            if 0 <= paper_idx < len(self.context_offsets):
                return self.context_offsets[paper_idx][1]

        return None
