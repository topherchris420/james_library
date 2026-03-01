"""Shared text-sanitization utilities and pre-compiled regex patterns."""

import re

# --- PRE-COMPILED REGEX PATTERNS ---

RE_QUOTE_DOUBLE = re.compile(r'"([^"]+)"')

RE_QUOTE_SINGLE = re.compile(r"'([^']+)'")

RE_CORRUPTION_CAPS = re.compile(r'[A-Z]{8,}')

RE_WEB_SEARCH_COMMAND = re.compile(r"\[SEARCH:\s*(.*?)\]", re.IGNORECASE)

RE_CORRUPTION_PATTERNS = [

    re.compile(p, re.IGNORECASE) for p in [

        r'\|eoc_fim\|',           # End of context markers

        r'ARILEX|AIVERI|RIECK',   # Common corruption sequences

        r'ingly:\w*scape',        # Gibberish compound words

        r':\s*\n\s*:\s*\n',       # Empty lines with colons

        r'##\d+\s*\(',            # Markdown header gibberish

        r'SING\w{10,}',           # Long corrupt strings starting with SING

        r'[A-Z]{4,}:[A-Z]{4,}',   # Multiple caps words with colons

    ]

]

def sanitize_text(text: str) -> str:

    """Sanitize external content to prevent prompt injection and control token attacks"""

    if not text:

        return ""

    # 1. Remove LLM control tokens and known corruption markers

    for token in ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "|eoc_fim|"]:

        text = text.replace(token, "[TOKEN_REMOVED]")

    # 2. Neutralize '###' headers that could simulate system/user turns

    text = text.replace("###", ">>>")

    # 3. Prevent recursive search triggers

    text = text.replace("[SEARCH:", "[SEARCH;")

    return text.strip()
