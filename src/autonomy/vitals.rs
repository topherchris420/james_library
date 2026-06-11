//! In-loop stagnation and dead-end detection.
//!
//! Ports the detector semantics of the Python `stagnation_monitor.py` so they
//! can run inside the Rust reasoning loop: a dead end is a run of consecutive
//! near-duplicate outputs; stagnation is a sliding window of low-novelty
//! outputs with low variance. Similarity uses character-trigram Jaccard to
//! avoid new dependencies.
//!
//! This module is wired into the tool-call loop in a follow-up phase; the
//! monitor itself is self-contained and fully testable.

use crate::config::VitalsConfig;
use std::collections::{HashSet, VecDeque};

/// Verdict for one observed loop iteration.
#[derive(Debug, Clone, PartialEq)]
pub enum VitalsVerdict {
    Healthy,
    /// Consecutive near-duplicate outputs: the agent is repeating itself.
    DeadEnd {
        similarity: f64,
    },
    /// Sustained low-novelty window: the agent is circling without progress.
    Stagnant {
        novelty_mean: f64,
    },
}

/// Recommended response to a non-healthy verdict, graded by how many times
/// this turn has already been corrected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Intervention {
    /// Inject a course-correction message into history and continue.
    Redirect { prompt: String },
    /// End the turn with the best partial answer and run consolidation.
    YieldAndConsolidate,
    /// End the turn and notify the out-of-band channel.
    AlertOutOfBand,
}

const DEAD_END_REDIRECT_PROMPT: &str = "Your recent responses are near-duplicates. The current \
     approach is not converging. Step back, state what has been ruled out, and try a materially \
     different approach or report the blocker explicitly.";

const STAGNATION_NUDGE_PROMPT: &str = "Your recent responses show little new information. \
     Summarize concrete progress so far, then either change strategy or conclude with what is \
     known and what remains blocked.";

/// Sliding-window monitor over assistant outputs within a single turn.
pub struct VitalsMonitor {
    config: VitalsConfig,
    recent: VecDeque<String>,
    novelty: VecDeque<f64>,
    consecutive_dupes: usize,
}

impl VitalsMonitor {
    pub fn new(config: VitalsConfig) -> Self {
        Self {
            config,
            recent: VecDeque::new(),
            novelty: VecDeque::new(),
            consecutive_dupes: 0,
        }
    }

    /// Observe one assistant output and return the current verdict.
    /// Dead-end detection takes precedence over stagnation.
    pub fn observe(&mut self, output: &str) -> VitalsVerdict {
        let max_similarity = self
            .recent
            .iter()
            .map(|prev| trigram_similarity(prev, output))
            .fold(0.0_f64, f64::max);

        self.recent.push_back(output.to_string());
        while self.recent.len() > self.config.dead_end_window.max(1) {
            self.recent.pop_front();
        }

        let novelty = 1.0 - max_similarity;
        self.novelty.push_back(novelty);
        while self.novelty.len() > self.config.stagnation_window.max(1) {
            self.novelty.pop_front();
        }

        // Dead end: N consecutive near-duplicates.
        if max_similarity >= self.config.dead_end_similarity {
            self.consecutive_dupes += 1;
            if self.consecutive_dupes >= self.config.dead_end_window.max(1) {
                return VitalsVerdict::DeadEnd {
                    similarity: max_similarity,
                };
            }
        } else {
            self.consecutive_dupes = 0;
        }

        // Stagnation: full window of low-novelty, low-variance outputs.
        if self.novelty.len() >= self.config.stagnation_window.max(1) {
            let n = self.novelty.len() as f64;
            let mean = self.novelty.iter().sum::<f64>() / n;
            let variance = self.novelty.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n;
            if mean < self.config.stagnation_novelty_mean
                && variance < self.config.stagnation_novelty_variance
            {
                return VitalsVerdict::Stagnant { novelty_mean: mean };
            }
        }

        VitalsVerdict::Healthy
    }

    /// Graded intervention ladder: redirect first, then yield, then alert.
    pub fn intervention_for(
        verdict: &VitalsVerdict,
        prior_escalations: u32,
    ) -> Option<Intervention> {
        match (verdict, prior_escalations) {
            (VitalsVerdict::Healthy, _) => None,
            (VitalsVerdict::DeadEnd { .. }, 0) => Some(Intervention::Redirect {
                prompt: DEAD_END_REDIRECT_PROMPT.to_string(),
            }),
            (VitalsVerdict::Stagnant { .. }, 0) => Some(Intervention::Redirect {
                prompt: STAGNATION_NUDGE_PROMPT.to_string(),
            }),
            (_, 1) => Some(Intervention::YieldAndConsolidate),
            (_, _) => Some(Intervention::AlertOutOfBand),
        }
    }

    /// Reset all window state (call at turn boundaries).
    pub fn reset(&mut self) {
        self.recent.clear();
        self.novelty.clear();
        self.consecutive_dupes = 0;
    }
}

/// Character-trigram Jaccard similarity in `[0.0, 1.0]`, case-insensitive
/// and whitespace-normalized. Two empty strings are identical (1.0).
pub(crate) fn trigram_similarity(a: &str, b: &str) -> f64 {
    let ta = trigram_set(a);
    let tb = trigram_set(b);
    if ta.is_empty() && tb.is_empty() {
        return 1.0;
    }
    if ta.is_empty() || tb.is_empty() {
        return 0.0;
    }
    let intersection = ta.intersection(&tb).count() as f64;
    let union = ta.union(&tb).count() as f64;
    intersection / union
}

fn trigram_set(text: &str) -> HashSet<[char; 3]> {
    let normalized: Vec<char> = text
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
        .chars()
        .collect();
    normalized.windows(3).map(|w| [w[0], w[1], w[2]]).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn monitor() -> VitalsMonitor {
        VitalsMonitor::new(VitalsConfig::default())
    }

    #[test]
    fn identical_strings_have_full_similarity() {
        assert!((trigram_similarity("the same text", "the same text") - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn disjoint_strings_have_zero_similarity() {
        assert!(trigram_similarity("abcdef", "uvwxyz") < f64::EPSILON);
    }

    #[test]
    fn similarity_ignores_case_and_whitespace_runs() {
        assert!(
            (trigram_similarity("Checking   The Logs", "checking the logs") - 1.0).abs()
                < f64::EPSILON
        );
    }

    #[test]
    fn varied_outputs_stay_healthy() {
        let mut m = monitor();
        let outputs = [
            "Inspecting the gateway pairing flow for bind-safety regressions.",
            "Memory consolidation completed; twelve entries merged into three.",
            "Telegram listener reconnected after exponential backoff.",
            "Cron scheduler executed the nightly digest job successfully.",
            "Peripheral nucleo-0 reports all GPIO lines nominal.",
            "No further action needed; system idle.",
        ];
        for out in outputs {
            assert_eq!(m.observe(out), VitalsVerdict::Healthy);
        }
    }

    #[test]
    fn repeated_identical_outputs_flag_dead_end() {
        let mut m = monitor();
        let repeated = "I will try reading the configuration file again to find the issue.";
        // First observation has no history; duplicates accumulate afterwards.
        assert_eq!(m.observe(repeated), VitalsVerdict::Healthy);
        assert_eq!(m.observe(repeated), VitalsVerdict::Healthy);
        assert_eq!(m.observe(repeated), VitalsVerdict::Healthy);
        match m.observe(repeated) {
            VitalsVerdict::DeadEnd { similarity } => assert!(similarity >= 0.95),
            other => panic!("expected DeadEnd, got {other:?}"),
        }
    }

    #[test]
    fn paraphrased_low_novelty_outputs_flag_stagnation() {
        // Long shared prefix with a small varying tail: similar enough to be
        // low-novelty, distinct enough to dodge the dead-end threshold.
        let base = "The system reviewed the archive pipeline configuration and verified that \
                    every stage completed without reporting actionable changes in module";
        let variants = [
            "alpha", "bravo", "delta", "gamma", "omega", "kappa", "sigma",
        ];
        let outputs: Vec<String> = variants.iter().map(|v| format!("{base} {v}.")).collect();

        // Verify the fixture sits in the intended band before driving the
        // monitor, so threshold drift fails loudly here rather than silently.
        for pair in outputs.windows(2) {
            let sim = trigram_similarity(&pair[0], &pair[1]);
            assert!(
                sim > 0.85 && sim < 0.95,
                "fixture out of band: similarity {sim}"
            );
        }

        let mut m = monitor();
        let mut saw_stagnant = false;
        for out in &outputs {
            if let VitalsVerdict::Stagnant { novelty_mean } = m.observe(out) {
                assert!(novelty_mean < 0.15);
                saw_stagnant = true;
            }
        }
        assert!(saw_stagnant, "expected stagnation verdict");
    }

    #[test]
    fn reset_clears_window_state() {
        let mut m = monitor();
        let repeated = "Identical output repeated several times in a row for the test.";
        for _ in 0..3 {
            m.observe(repeated);
        }
        m.reset();
        assert_eq!(m.observe(repeated), VitalsVerdict::Healthy);
    }

    #[test]
    fn intervention_ladder_escalates() {
        let dead_end = VitalsVerdict::DeadEnd { similarity: 0.99 };
        assert!(matches!(
            VitalsMonitor::intervention_for(&dead_end, 0),
            Some(Intervention::Redirect { .. })
        ));
        assert_eq!(
            VitalsMonitor::intervention_for(&dead_end, 1),
            Some(Intervention::YieldAndConsolidate)
        );
        assert_eq!(
            VitalsMonitor::intervention_for(&dead_end, 2),
            Some(Intervention::AlertOutOfBand)
        );
        assert_eq!(
            VitalsMonitor::intervention_for(&VitalsVerdict::Healthy, 0),
            None
        );
    }
}
