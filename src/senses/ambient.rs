//! Ephemeral environment awareness.
//!
//! Ambient facts live in a fixed-capacity, TTL'd ring buffer in RAM. The
//! buffer never touches the `Memory` trait: facts expire, the buffer dies
//! with the process, and nothing here is persisted. Promotion into permanent
//! memory is exclusively the episodic ingestor's job (with provenance), per
//! `docs/autonomous-runtime-design.md` §2.4.

use chrono::{DateTime, Utc};
use std::collections::VecDeque;

/// Rough token estimate used for the render budget (chars / 4).
fn approx_tokens(text: &str) -> usize {
    text.len().div_ceil(4)
}

/// One observed fact about the environment. The TTL is mandatory: there are
/// no immortal ambient facts.
#[derive(Debug, Clone)]
pub struct AmbientFact {
    pub source: String,
    /// One-line, pre-sanitized rendering. Callers must not place secrets or
    /// raw payloads here — this text reaches the system prompt.
    pub text: String,
    pub observed_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
    /// How many raw events coalesced into this line.
    pub fold_count: u64,
}

/// Fixed-capacity ring of keyed ambient facts, newest last.
pub struct AmbientContextBuffer {
    capacity: usize,
    facts: VecDeque<(String, AmbientFact)>,
}

impl AmbientContextBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(1),
            facts: VecDeque::new(),
        }
    }

    /// Insert or refresh a fact. An existing key is replaced and moved to the
    /// most-recent position; when full, the oldest fact is evicted.
    pub fn upsert(&mut self, key: impl Into<String>, fact: AmbientFact) {
        let key = key.into();
        self.facts.retain(|(k, _)| *k != key);
        self.facts.push_back((key, fact));
        while self.facts.len() > self.capacity {
            self.facts.pop_front();
        }
    }

    /// Drop expired facts; returns how many were pruned.
    pub fn prune_expired(&mut self, now: DateTime<Utc>) -> usize {
        let before = self.facts.len();
        self.facts.retain(|(_, fact)| fact.expires_at > now);
        before - self.facts.len()
    }

    pub fn len(&self) -> usize {
        self.facts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.facts.is_empty()
    }

    /// Render the buffer as a prompt section, newest facts first, truncated
    /// to the token budget. Expired facts are pruned first. Returns `None`
    /// when nothing is renderable.
    ///
    /// The render is deterministic for a given buffer state and `now`, so
    /// identical environments produce identical prompts.
    pub fn render(&mut self, token_budget: usize, now: DateTime<Utc>) -> Option<String> {
        self.prune_expired(now);
        if self.facts.is_empty() {
            return None;
        }

        const HEADER: &str =
            "## Environment (ephemeral — observations expire; do not store as facts)";
        let mut out = String::from(HEADER);
        let mut used = approx_tokens(HEADER);
        let mut rendered = 0usize;

        for (_, fact) in self.facts.iter().rev() {
            let folds = if fact.fold_count > 0 {
                format!(" (×{} events)", fact.fold_count + 1)
            } else {
                String::new()
            };
            let line = format!(
                "\n- [{}] {} {}{}",
                fact.observed_at.format("%H:%M:%SZ"),
                fact.source,
                fact.text,
                folds
            );
            let cost = approx_tokens(&line);
            if used + cost > token_budget {
                break;
            }
            out.push_str(&line);
            used += cost;
            rendered += 1;
        }

        if rendered == 0 { None } else { Some(out) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fact(source: &str, text: &str, ttl_secs: i64) -> AmbientFact {
        let now = Utc::now();
        AmbientFact {
            source: source.to_string(),
            text: text.to_string(),
            observed_at: now,
            expires_at: now + chrono::Duration::seconds(ttl_secs),
            fold_count: 0,
        }
    }

    #[test]
    fn upsert_replaces_same_key_and_moves_to_newest() {
        let mut buf = AmbientContextBuffer::new(8);
        buf.upsert("hw:temp", fact("peripheral:nucleo-0", "temp_c=40.1", 60));
        buf.upsert("fs:papers", fact("fswatch", "2 files changed", 60));
        buf.upsert("hw:temp", fact("peripheral:nucleo-0", "temp_c=41.2", 60));

        assert_eq!(buf.len(), 2);
        let rendered = buf.render(1000, Utc::now()).unwrap();
        // Refreshed fact is newest, so it renders first and only once.
        assert_eq!(rendered.matches("temp_c=").count(), 1);
        assert!(rendered.contains("temp_c=41.2"));
        let temp_pos = rendered.find("temp_c=41.2").unwrap();
        let fs_pos = rendered.find("2 files changed").unwrap();
        assert!(temp_pos < fs_pos);
    }

    #[test]
    fn capacity_evicts_oldest() {
        let mut buf = AmbientContextBuffer::new(2);
        buf.upsert("a", fact("s", "first", 60));
        buf.upsert("b", fact("s", "second", 60));
        buf.upsert("c", fact("s", "third", 60));

        assert_eq!(buf.len(), 2);
        let rendered = buf.render(1000, Utc::now()).unwrap();
        assert!(!rendered.contains("first"));
        assert!(rendered.contains("second"));
        assert!(rendered.contains("third"));
    }

    #[test]
    fn expired_facts_are_pruned_from_render() {
        let mut buf = AmbientContextBuffer::new(8);
        buf.upsert("stale", fact("s", "old reading", -10));
        buf.upsert("fresh", fact("s", "new reading", 60));

        let rendered = buf.render(1000, Utc::now()).unwrap();
        assert!(!rendered.contains("old reading"));
        assert!(rendered.contains("new reading"));
        assert_eq!(buf.len(), 1);
    }

    #[test]
    fn render_returns_none_when_empty_or_all_expired() {
        let mut buf = AmbientContextBuffer::new(8);
        assert!(buf.render(1000, Utc::now()).is_none());
        buf.upsert("stale", fact("s", "gone", -10));
        assert!(buf.render(1000, Utc::now()).is_none());
        assert!(buf.is_empty());
    }

    #[test]
    fn render_respects_token_budget_keeping_newest() {
        let mut buf = AmbientContextBuffer::new(16);
        for i in 0..16 {
            buf.upsert(
                format!("k{i}"),
                fact(
                    "source",
                    &format!("reading number {i} with some padding text"),
                    60,
                ),
            );
        }
        // Budget for the header plus only a few lines.
        let rendered = buf.render(60, Utc::now()).unwrap();
        assert!(rendered.contains("reading number 15"));
        assert!(!rendered.contains("reading number 0 "));
    }

    #[test]
    fn fold_count_is_rendered() {
        let mut buf = AmbientContextBuffer::new(8);
        let mut f = fact("peripheral:nucleo-0", "temp_c=41.2", 60);
        f.fold_count = 11;
        buf.upsert("hw:temp", f);
        let rendered = buf.render(1000, Utc::now()).unwrap();
        assert!(rendered.contains("(×12 events)"));
    }

    #[test]
    fn render_carries_ephemerality_instruction() {
        let mut buf = AmbientContextBuffer::new(8);
        buf.upsert("a", fact("s", "x", 60));
        let rendered = buf.render(1000, Utc::now()).unwrap();
        assert!(rendered.contains("do not store as facts"));
    }
}
