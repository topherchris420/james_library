"""Output guardrails: corruption detection, identity cleanup, and prefix stripping."""

import re
from typing import Tuple

from rain_lab_chat._sanitize import RE_CORRUPTION_CAPS, RE_CORRUPTION_PATTERNS

# Agent names used for identity-confusion filtering
_KNOWN_AGENTS = ("James", "Jasmine", "Luca", "Elena")

def is_corrupted_response(text: str) -> Tuple[bool, str]:
    """Detect corrupted/garbled LLM outputs using multiple heuristics.

    Returns (is_corrupted, reason) tuple.
    """
    if not text or len(text.strip()) < 10:
        return True, "Response too short"

    # Heuristic 1: Too many consecutive uppercase letters (token corruption)
    if RE_CORRUPTION_CAPS.search(text):
        return True, "Excessive consecutive capitals detected"

    # Heuristic 2: High ratio of special characters (gibberish)
    special_chars = sum(1 for c in text if c in ':;/\\|<>{}[]()@#$%^&*+=~`')
    if len(text) > 20 and special_chars / len(text) > 0.15:
        return True, "Too many special characters"

    # Heuristic 3: Common corruption patterns
    for pattern in RE_CORRUPTION_PATTERNS:
        if pattern.search(text):
            return True, f"Corruption pattern detected: {pattern.pattern[:20]}"

    # Heuristic 4: Too many empty lines or lines with just punctuation
    lines = text.split('\n')
    empty_lines = sum(1 for line in lines if len(line.strip()) <= 2)
    if len(lines) > 5 and empty_lines / len(lines) > 0.5:
        return True, "Too many empty lines"

    # Heuristic 5: Average word length too high (concatenated garbage)
    words = text.split()
    if words:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len > 15:
            return True, "Average word length too high (likely corrupted)"

    return False, ""

def detect_repeated_intro(content: str) -> bool:
    """Return True if James is repeating his opening-meeting template on a later turn."""
    lowered = content.lower()
    return (
        lowered.startswith("hey team")
        or "today we're looking into" in lowered
        or "today we're talking about" in lowered
    )

def strip_agent_prefix(response: str, agent_name: str) -> str:
    """Strip duplicate agent name prefixes from the response.

    Handles patterns like:
    - "James: ..."
    - "James (R.A.I.N. Lab Lead): ..."
    - "James (R.A.I.N. Lab): ..."
    """
    pattern = rf'^{re.escape(agent_name)}\s*(?:\([^)]*\))?\s*:\s*'
    cleaned = re.sub(pattern, '', response, count=1)
    return cleaned.strip()

def clean_identity(content: str, agent_name: str) -> str:
    """Remove self-prefix and lines where the agent speaks as OTHER team members."""
    # Remove agent speaking as self
    if content.startswith(f"{agent_name}:"):
        content = content.replace(f"{agent_name}:", "", 1).strip()

    # Remove lines where agent speaks as OTHER team members (identity confusion)
    cleaned_lines = []
    for line in content.split('\n'):
        is_other_agent_line = False
        for other in _KNOWN_AGENTS:
            if other != agent_name and line.strip().startswith(f"{other}:"):
                is_other_agent_line = True
                break
        if not is_other_agent_line:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines).strip()

def complete_truncated(content: str) -> str:
    """Try to end truncated content at the last complete sentence, or add ellipsis."""
    for end in ['. ', '! ', '? ']:
        if end in content:
            last_end = content.rfind(end)
            if last_end > len(content) * 0.5:
                return content[:last_end + 1]
    return content.rstrip(',;:') + "..."
