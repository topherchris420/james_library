//! Routines engine — loads and dispatches event-triggered automations.

use super::{MatchStrategy, Routine, RoutineDispatchResult, RoutineEvent};
use parking_lot::Mutex;
use std::collections::HashMap;
use std::time::Instant;

/// Engine that evaluates incoming events against configured routines.
pub struct RoutinesEngine {
    routines: Vec<Routine>,
    /// Last-fired timestamps for cooldown enforcement.
    cooldowns: Mutex<HashMap<String, Instant>>,
}

impl RoutinesEngine {
    /// Create a new engine with the given routines.
    pub fn new(routines: Vec<Routine>) -> Self {
        Self {
            routines,
            cooldowns: Mutex::new(HashMap::new()),
        }
    }

    /// Evaluate an event against all routines and return matching results.
    pub fn evaluate(&self, event: &RoutineEvent) -> Vec<RoutineDispatchResult> {
        let mut results = Vec::new();

        for routine in &self.routines {
            if !routine.enabled {
                continue;
            }

            if routine.event.source != event.source {
                continue;
            }

            if !self.matches(
                &routine.event.strategy,
                &routine.event.pattern,
                &event.payload,
            ) {
                continue;
            }

            // Check cooldown
            if routine.cooldown_secs > 0 {
                let mut cooldowns = self.cooldowns.lock();
                if let Some(last) = cooldowns.get(&routine.name) {
                    if last.elapsed().as_secs() < routine.cooldown_secs {
                        continue;
                    }
                }
                cooldowns.insert(routine.name.clone(), Instant::now());
            }

            results.push(RoutineDispatchResult {
                routine_name: routine.name.clone(),
                success: true,
                message: format!("Routine '{}' matched event", routine.name),
            });
        }

        results
    }

    fn matches(&self, strategy: &MatchStrategy, pattern: &str, payload: &str) -> bool {
        match strategy {
            MatchStrategy::Exact => payload == pattern,
            MatchStrategy::Glob => glob_match(pattern, payload),
            MatchStrategy::Regex => regex::Regex::new(pattern)
                .map(|re| re.is_match(payload))
                .unwrap_or(false),
        }
    }
}

/// Simple glob matching (supports * and ?).
fn glob_match(pattern: &str, text: &str) -> bool {
    let mut p = pattern.chars().peekable();
    let mut t = text.chars().peekable();

    while p.peek().is_some() || t.peek().is_some() {
        match (p.peek(), t.peek()) {
            (Some('*'), _) => {
                p.next();
                if p.peek().is_none() {
                    return true;
                }
                while t.peek().is_some() {
                    if glob_match(
                        &p.clone().collect::<String>(),
                        &t.clone().collect::<String>(),
                    ) {
                        return true;
                    }
                    t.next();
                }
                return false;
            }
            (Some('?'), Some(_)) => {
                p.next();
                t.next();
            }
            (Some(pc), Some(tc)) if *pc == *tc => {
                p.next();
                t.next();
            }
            _ => return false,
        }
    }
    true
}
