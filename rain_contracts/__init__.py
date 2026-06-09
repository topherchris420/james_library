"""Cross-language data contracts shared between the Rust runtime and the
Python orchestration tier.

The canonical schemas live in ``src/autonomy/episodic.rs``; modules here are
field-for-field mirrors following the same compatibility contract (additive
optional fields, unknown keys ignored on read).
"""

from rain_contracts.episodic import (
    EPISODIC_SCHEMA_VERSION,
    AffectTrace,
    BehavioralState,
    Episode,
    EpisodicEventV2,
    segment_events,
)

__all__ = [
    "EPISODIC_SCHEMA_VERSION",
    "AffectTrace",
    "BehavioralState",
    "Episode",
    "EpisodicEventV2",
    "segment_events",
]
