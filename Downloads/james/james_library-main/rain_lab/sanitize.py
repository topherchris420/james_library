"""Text sanitization and pre-compiled regex patterns for prompt injection defence."""

from __future__ import annotations

import re

# --- PRE-COMPILED REGEX PATTERNS ---

RE_QUOTE_DOUBLE = re.compile(r'"([^"]+)"')

RE_QUOTE_SINGLE = re.compile(r"'([^']+)'")

RE_CORRUPTION_CAPS = re.compile(r"[A-Z]{8,}")

RE_WEB_SEARCH_COMMAND = re.compile(r"\[SEARCH:\s*(.*?)\]", re.IGNORECASE)

RE_CORRUPTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\|eoc_fim\|",
        r"ARILEX|AIVERI|RIECK",
        r"ingly:\w*scape",
        r":\s*\n\s*:\s*\n",
        r"##\d+\s*\(",
        r"SING\w{10,}",
        r"[A-Z]{4,}:[A-Z]{4,}",
    ]
]

# --- RESONANCE / FREQUENCY DETECTION ---

RE_FREQUENCY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:hz|hertz)",
    re.IGNORECASE,
)

RE_RESONANCE_KEYWORDS = re.compile(
    r"\b(?:resonan(?:ce|t)|cymati(?:c|cs)|chladni|nodal|standing\s+wave|harmonic|"
    r"vibrat(?:e|ion|ional)|frequenc(?:y|ies)|acoustic|waveform|oscillat(?:e|ion)|"
    r"eigenfrequen(?:cy|cies)|anti[-\s]?node|amplitude)\b",
    re.IGNORECASE,
)

_CONTROL_TOKENS = [
    "\x3c|endoftext|\x3e",
    "\x3c|im_start|\x3e",
    "\x3c|im_end|\x3e",
    "|eoc_fim|",
]


def sanitize_text(text: str) -> str:
    """Sanitize external content to prevent prompt injection and control token attacks."""

    if not text:
        return ""

    for token in _CONTROL_TOKENS:
        text = text.replace(token, "[TOKEN_REMOVED]")

    text = text.replace("###", ">>>")

    text = text.replace("[SEARCH:", "[SEARCH;")

    return text.strip()
