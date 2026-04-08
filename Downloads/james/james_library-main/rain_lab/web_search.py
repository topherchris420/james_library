"""DuckDuckGo web search manager with retry logic and caching."""

from __future__ import annotations

import time
import warnings
from typing import Dict, List, Tuple

from .config import Config
from .sanitize import sanitize_text

# Optional: DuckDuckGo search support
DDG_AVAILABLE = False
DDG_PACKAGE = None

try:
    from ddgs import DDGS

    DDG_AVAILABLE = True
    DDG_PACKAGE = "ddgs"
except ImportError:
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*renamed.*")
            from duckduckgo_search import DDGS

        DDG_AVAILABLE = True
        DDG_PACKAGE = "duckduckgo_search"
    except ImportError:
        pass


class WebSearchManager:
    """Handles DuckDuckGo web searches for supplementary research context."""

    def __init__(self, config: Config):
        self.config = config
        self.search_cache: Dict[str, List[Dict]] = {}
        self.enabled = config.enable_web_search and DDG_AVAILABLE
        self.max_retries = 3
        self.retry_delay = 2.0

    def search(self, query: str, verbose: bool = False) -> Tuple[str, List[Dict]]:
        """Search DuckDuckGo and return formatted results plus raw data."""

        if not self.enabled:
            if self.config.enable_web_search and verbose:
                print("\n\u26a0\ufe0f  Web search disabled: No DDG package installed")
                print("   Install with: pip install ddgs")
            return "", []

        if query in self.search_cache:
            if verbose:
                print(f"\n\U0001f504 Using cached web results for: '{query}'")
            return self._format_results(self.search_cache[query]), self.search_cache[query]

        if verbose:
            print(f"\n\U0001f310 Searching web for: '{query}'...")

        for attempt in range(self.max_retries):
            try:
                results = []

                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    with DDGS() as ddgs:
                        for r in ddgs.text(query, max_results=self.config.web_search_results):
                            results.append(
                                {"title": r.get("title", ""), "body": r.get("body", ""), "href": r.get("href", "")}
                            )

                self.search_cache[query] = results

                if results:
                    if verbose:
                        print(f"   \u2713 Found {len(results)} web results")
                        for i, r in enumerate(results, 1):
                            title_preview = r["title"][:60] + "..." if len(r["title"]) > 60 else r["title"]
                            print(f"      {i}. {title_preview}")
                    return self._format_results(results), results
                else:
                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay * (attempt + 1)
                        if verbose:
                            print(
                                f"   \u26a0 No results (attempt {attempt + 1}/{self.max_retries}),"
                                f" retrying in {delay:.1f}s..."
                            )
                        time.sleep(delay)
                    else:
                        if verbose:
                            print(f"   \u26a0 No web results found after {self.max_retries} attempts")
                            print("   \U0001f4a1 Possible causes: rate limiting, network issues, or overly specific query")
                        return "", []

            except Exception as e:
                error_msg = str(e).lower()

                if "ratelimit" in error_msg or "429" in error_msg:
                    reason = "Rate limited by DuckDuckGo"
                elif "timeout" in error_msg:
                    reason = "Request timed out"
                elif "connection" in error_msg or "network" in error_msg:
                    reason = "Network connection error"
                else:
                    reason = str(e)

                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (attempt + 1)
                    if verbose:
                        print(f"   \u26a0 {reason} (attempt {attempt + 1}/{self.max_retries}), retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    if verbose:
                        print(f"   \u26a0 Web search failed after {self.max_retries} attempts: {reason}")
                        print("   \U0001f4a1 Meeting will proceed with local papers only")
                    return "", []

        return "", []

    def _sanitize_text(self, text: str) -> str:
        return sanitize_text(text)

    def _format_results(self, results: List[Dict]) -> str:
        """Format results for agent context."""
        if not results:
            return ""

        formatted = ["\n### WEB SEARCH RESULTS (cite as [from web: title])"]

        for r in results:
            safe_title = self._sanitize_text(r.get("title", ""))
            safe_body = self._sanitize_text(r.get("body", ""))
            formatted.append(f"**{safe_title}**")
            formatted.append(f"{safe_body}")
            formatted.append(f"Source: {r.get('href', '')}\n")

        return "\n".join(formatted)
