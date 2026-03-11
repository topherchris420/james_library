"""DuckDuckGo web search with optional Scrapling integration."""

import time
import warnings
from typing import Dict, List, Tuple

from rain_lab_chat._logging import get_logger
from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config

log = get_logger(__name__)

# Optional: DuckDuckGo search support
DDG_AVAILABLE = False
DDG_PACKAGE = None
DDGS = None
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

# Optional: Scrapling for full-content fetching
SCRAPLING_AVAILABLE = False
try:
    from scrapling.fetchers import StealthyFetcher

    SCRAPLING_AVAILABLE = True
except ImportError:
    StealthyFetcher = None


class WebSearchManager:
    """Handles DuckDuckGo web searches for supplementary research context"""

    def __init__(self, config: Config):

        self.config = config

        self.search_cache: Dict[str, List[Dict]] = {}

        self.enabled = config.enable_web_search and DDG_AVAILABLE

        self.max_retries = 3

        self.retry_delay = 2.0  # seconds between retries

    def search(self, query: str, verbose: bool = False) -> Tuple[str, List[Dict]]:
        """Search DuckDuckGo and return formatted results plus raw data"""

        if not self.enabled:
            if self.config.enable_web_search and verbose:
                log.warning("Web search disabled: No DDG package installed. Install with: pip install ddgs")

            return "", []

        # Check cache

        if query in self.search_cache:
            if verbose:
                log.info("Using cached web results for: '%s'", query)

            return self._format_results(self.search_cache[query]), self.search_cache[query]

        if verbose:
            log.info("Searching web for: '%s'", query)

        # Retry loop with exponential backoff

        for attempt in range(self.max_retries):
            try:
                results = []

                # Suppress any deprecation warnings during search

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
                        log.info("Found %d web results", len(results))
                        for i, r in enumerate(results, 1):
                            title_preview = r["title"][:60] + "..." if len(r["title"]) > 60 else r["title"]
                            log.debug("  %d. %s", i, title_preview)

                    return self._format_results(results), results

                else:
                    # No results but no error - may be rate limited or bad query

                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay * (attempt + 1)
                        if verbose:
                            log.info("No results (attempt %d/%d), retrying in %.1fs", attempt + 1, self.max_retries, delay)
                        time.sleep(delay)

                    else:
                        if verbose:
                            log.warning("No web results after %d attempts", self.max_retries)
                        return "", []

            except Exception as e:
                error_msg = str(e).lower()

                # Identify specific error types for better messaging

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
                        log.warning("%s (attempt %d/%d), retrying in %.1fs", reason, attempt + 1, self.max_retries, delay)
                    time.sleep(delay)

                else:
                    if verbose:
                        log.warning("Web search failed after %d attempts: %s", self.max_retries, reason)
                    return "", []

        return "", []

    def _sanitize_text(self, text: str) -> str:
        """Sanitize web content to prevent prompt injection and control token attacks"""

        return sanitize_text(text)

    def _format_results(self, results: List[Dict]) -> str:
        """Format results for agent context, optionally enriching with full page content."""
        if not results:
            return ""

        formatted = ["\n### WEB SEARCH RESULTS (cite as [from web: title])"]
        for r in results:
            safe_title = self._sanitize_text(r.get("title", ""))
            safe_body = self._sanitize_text(r.get("body", ""))
            formatted.append(f"**{safe_title}**")
            formatted.append(f"{safe_body}")
            formatted.append(f"Source: {r.get('href', '')}\n")

        # Scrapling: fetch full page content from top result for richer context
        if SCRAPLING_AVAILABLE and results:
            page_content = self._fetch_page_content(results[0].get("href", ""))
            if page_content:
                formatted.append("### FULL PAGE CONTENT (top result)")
                formatted.append(page_content)

        return "\n".join(formatted)

    def _fetch_page_content(self, url: str, max_chars: int = 2000) -> str:
        """Use Scrapling's StealthyFetcher to extract full page text from a URL.

        Returns extracted text truncated to max_chars, or empty string on failure.
        Only runs when scrapling is installed (SCRAPLING_AVAILABLE is True).
        """
        if not SCRAPLING_AVAILABLE or not StealthyFetcher or not url:
            return ""

        try:
            page = StealthyFetcher.fetch(url)
            # Extract text from body, stripping HTML
            body = page.css_first("body")
            if body is None:
                return ""

            # Remove script and style elements
            for tag in body.css("script, style, nav, footer, header"):
                tag.remove()

            text = body.text(separator="\n", strip=True)
            # Clean up excessive whitespace
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            clean_text = "\n".join(lines)

            if len(clean_text) > max_chars:
                # Truncate at last sentence boundary within budget
                truncated = clean_text[:max_chars]
                last_period = truncated.rfind(".")
                if last_period > max_chars * 0.5:
                    truncated = truncated[: last_period + 1]
                clean_text = truncated + "\n[...truncated]"

            return self._sanitize_text(clean_text)

        except Exception as e:
            log.debug("Scrapling fetch failed for %s: %s", url, e)
            return ""
