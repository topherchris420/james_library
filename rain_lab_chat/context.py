"""Research paper context loading and citation verification."""

import os
import bisect
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

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

                # Prune skip_dirs in-place to prevent traversing them

                dirs[:] = [d for d in dirs if d not in skip_dirs]

                # Pre-calculate parent dir check for .py files

                # If root ends with "hello_os", then files in it are inside hello_os package

                parent_name = os.path.basename(root)

                is_hello_os_dir = (parent_name == "hello_os")

                for file in files:

                    # 1. Fast suffix check (string op, no object creation)

                    name_lower = file.lower()

                    if not name_lower.endswith(allowed_suffixes):

                        continue

                    # 2. Check exclusions

                    name_upper = file.upper()

                    if any(p in name_upper for p in exclude_patterns):

                        continue

                    if file in skip_dirs:

                        continue

                    # 3. Apply specific filtering rules

                    # Rule: .md/.txt are always allowed. .py only if hello_os.py or inside hello_os dir.

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

                name_upper = name.upper()

                if any(p in name_upper for p in exclude_patterns):

                    continue

                is_md_txt = name_lower.endswith((".md", ".txt"))

                is_valid_py = False

                if name_lower.endswith(".py"):

                    if name == "hello_os.py":

                        is_valid_py = True

                    # Check if the library itself is the hello_os package folder

                    elif self.lab_path.name == "hello_os":

                        is_valid_py = True

                if is_md_txt or is_valid_py:

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

            print(f"\n📂 Accessing Research Library at: {self.lab_path}")

        

        if not self.lab_path.exists():

            print(f"❌ Library path does not exist: {self.lab_path}")

            return "Library not accessible.", []

        

        buffer = []

        

        # Load all valid text files (recursive by default)

        all_files = self._discover_files()

        if verbose:

            scope = "recursive" if self.config.recursive_library_scan else "top-level"

            print(f"   • Scan mode: {scope}; files discovered: {len(all_files)}")

        

        if not all_files:

            print("⚠️  No research papers found in library.")

            return "No research papers found in library.", []

        if verbose:

            print(f"   ✓ Found {len(all_files)} papers.\n")

        

        total_chars = 0

        current_offset = 0

        index_parts = []

        

        for filepath in all_files:

            try:

                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:

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

                            print(f"     ✓ Loaded: {paper_ref} ({to_include:,} chars, {coverage:.0f}% coverage)")

                    else:

                        if verbose:

                            print(f"     ⚠ Skipped {paper_ref} (budget exhausted)")

                    

            except Exception as e:

                if verbose:

                    print(f"     ✗ Error reading {filepath.name}: {e}")

                continue

        

        # Finalize global index

        self.global_context_index = "\0".join(index_parts)

        self.offset_keys = [o[0] for o in self.context_offsets]

        combined = "\n".join(buffer)

        

        if verbose:

            print(f"\n   📊 Total context loaded: {len(combined):,} characters")

            print(f"   📊 Papers with full coverage: {len([p for p in self.loaded_papers.keys()])}")

        

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
