"""Citation extraction and verification."""

from typing import Dict, List

from rain_lab_chat._sanitize import RE_QUOTE_DOUBLE, RE_QUOTE_SINGLE
from rain_lab_chat.context import ContextManager

class CitationAnalyzer:

    """Tracks and verifies citations in agent responses"""

    

    def __init__(self, context_manager: ContextManager):

        self.context_manager = context_manager

        self.total_quotes_found = 0

        self.verified_quotes = 0

    

    def extract_quotes(self, text: str) -> List[str]:

        """Extract quoted text from response"""

        # Match text in "quotes" or 'quotes' using pre-compiled patterns

        quotes = RE_QUOTE_DOUBLE.findall(text)

        quotes.extend(RE_QUOTE_SINGLE.findall(text))

        return [q for q in quotes if len(q.split()) > 3]  # Only meaningful quotes

    

    def analyze_response(self, agent_name: str, response: str) -> Dict[str, any]:

        """Analyze citation quality of response"""

        quotes = self.extract_quotes(response)

        self.total_quotes_found += len(quotes)

        

        verified = []

        unverified = []

        

        for quote in quotes:

            source = self.context_manager.verify_citation(quote)

            if source:

                verified.append((quote, source))

                self.verified_quotes += 1

            else:

                unverified.append(quote)

        

        has_speculation = "[SPECULATION]" in response.upper() or "[THEORY]" in response.upper()

        

        return {

            'quotes_found': len(quotes),

            'verified': verified,

            'unverified': unverified,

            'has_speculation_tag': has_speculation,

            'citation_rate': len(verified) / len(quotes) if quotes else 0

        }

    

    def get_stats(self) -> str:

        """Get overall citation statistics"""

        if self.total_quotes_found == 0:

            return "No quotes analyzed yet."

        

        rate = (self.verified_quotes / self.total_quotes_found) * 100

        return f"Citation Rate: {self.verified_quotes}/{self.total_quotes_found} ({rate:.1f}% verified)"

# --- DIRECTOR ---
