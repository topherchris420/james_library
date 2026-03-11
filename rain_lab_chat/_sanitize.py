"""Shared text-sanitization utilities and pre-compiled regex patterns."""

import re
import urllib.parse

# --- PRE-COMPILED REGEX PATTERNS ---

RE_QUOTE_DOUBLE = re.compile(r'"([^"]+)"')

RE_QUOTE_SINGLE = re.compile(r"'([^']+)'")

RE_CORRUPTION_CAPS = re.compile(r"[A-Z]{8,}")

RE_WEB_SEARCH_COMMAND = re.compile(r"\[SEARCH:\s*(.*?)\]", re.IGNORECASE)

RE_CORRUPTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\|eoc_fim\|",  # End of context markers
        r"ARILEX|AIVERI|RIECK",  # Common corruption sequences
        r"ingly:\w*scape",  # Gibberish compound words
        r":\s*\n\s*:\s*\n",  # Empty lines with colons
        r"##\d+\s*\(",  # Markdown header gibberish
        r"SING\w{10,}",  # Long corrupt strings starting with SING
        r"[A-Z]{4,}:[A-Z]{4,}",  # Multiple caps words with colons
    ]
]

# LLM control tokens to strip (OpenAI, Llama, Mistral families)
_CONTROL_TOKENS = [
    # OpenAI / ChatML
    "<|endoftext|>",
    "<|im_start|>",
    "<|im_end|>",
    "|eoc_fim|",  # standalone eoc marker
    # Llama 3 family
    "<|begin_of_text|>",
    "<|end_of_text|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|eot_id|>",
    # Mistral / generic BOS/EOS
    "<s>",
    "</s>",
]

# Role simulation patterns that could trick LLMs into interpreting
# injected text as system/user/assistant boundaries.
_RE_ROLE_SIMULATION = re.compile(
    r"^\s*(SYSTEM|USER|ASSISTANT|HUMAN|AI)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def sanitize_text(text: str) -> str:
    """Sanitize external content to prevent prompt injection and control token attacks."""

    if not text:
        return ""

    # 1. Decode common URL-encoded evasions before stripping tokens.
    #    Only decode %xx sequences; this catches %3C|im_end|%3E style attacks.
    try:
        decoded = urllib.parse.unquote(text)
        if decoded != text:
            text = decoded
    except Exception:
        pass

    # 2. Remove LLM control tokens (OpenAI, Llama, Mistral families)
    for token in _CONTROL_TOKENS:
        text = text.replace(token, "[TOKEN_REMOVED]")

    # 3. Neutralize markdown headers that could simulate system/user turns
    #    (### through ##### — deeper headers are less risky)
    for prefix in ["#####", "####", "###"]:
        text = text.replace(prefix, ">>>" + (">" * (len(prefix) - 3)))

    # 4. Prevent recursive search triggers
    text = text.replace("[SEARCH:", "[SEARCH;")

    # 5. Neutralize role simulation headers
    text = _RE_ROLE_SIMULATION.sub(r"[ROLE_BLOCKED] [\1]", text)

    return text.strip()


def sanitize_url(url: str) -> str:
    """Validate and sanitize a URL; return empty string for dangerous schemes.

    Blocks file://, javascript:, data:, and vbscript: schemes
    that could be used for local file access or code execution.
    """
    if not url or not isinstance(url, str):
        return ""

    stripped = url.strip()
    lower = stripped.lower()

    # Block dangerous URI schemes
    blocked_schemes = ("file://", "javascript:", "data:", "vbscript:", "blob:")
    if any(lower.startswith(scheme) for scheme in blocked_schemes):
        return ""

    # Only allow http/https (and empty scheme for relative URLs)
    if "://" in stripped and not lower.startswith(("http://", "https://")):
        return ""

    return stripped
