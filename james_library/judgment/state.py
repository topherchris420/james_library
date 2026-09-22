"""Deterministic allowlist rendering. No file, corpus, transcript or memory access."""

from hashlib import sha256

from .contracts import ClaimEvidence, JudgmentState, StateTruncation

MAX_FIELD_CHARACTERS = 4000
MAX_STATE_CHARACTERS = 24000
_FIELDS = (
    ("claim", "CLAIM"), ("method", "METHOD"), ("observations", "OBSERVATIONS"),
    ("quantitative_results", "QUANTITATIVE RESULTS"), ("tool_evidence", "SIMULATION / TOOL EVIDENCE"),
    ("peer_critique", "PEER CRITIQUE"), ("formal_logic_result", "FORMAL LOGIC RESULT"),
    ("known_limitations", "KNOWN LIMITATIONS"), ("source_identifiers", "SOURCE IDENTIFIERS"),
)
_TRUNCATED = "\n[TRUNCATED: evidence omitted]"


def build_state(evidence: ClaimEvidence) -> JudgmentState:
    sections: list[str] = []
    truncated: list[str] = []
    original_size = 0
    # Reserve space for all headings, explicit markers, and host validation statuses.
    remaining = MAX_STATE_CHARACTERS - 1000
    for field, heading in _FIELDS:
        value = "\n".join(evidence.source_identifiers) if field == "source_identifiers" else getattr(evidence, field)
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip() or "[NOT SUPPLIED]"
        original_size += len(value)
        limit = min(MAX_FIELD_CHARACTERS, remaining)
        if len(value) > limit:
            truncated.append(field)
            value = value[:max(0, limit - len(_TRUNCATED))] + _TRUNCATED
        remaining = max(0, remaining - len(value))
        sections.append(f"{heading}:\n{value}")
    sections.append(f"HOST VALIDATION STATUS:\nformal={evidence.formal_status.value}; "
                    f"numerical={evidence.numerical_status.value}")
    text = "\n\n".join(sections) + "\n"
    truncation = StateTruncation(bool(truncated), tuple(truncated), original_size, len(text),
                                 MAX_FIELD_CHARACTERS, MAX_STATE_CHARACTERS)
    return JudgmentState(text, sha256(text.encode("utf-8")).hexdigest(), truncation,
                         evidence.formal_status, evidence.numerical_status,
                         any(value.strip() for value in (evidence.observations, evidence.quantitative_results,
                                                         evidence.tool_evidence)),
                         any(source.strip() for source in evidence.source_identifiers))
