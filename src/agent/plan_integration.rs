//! Integration hooks for the PlanTool with the agent loop.
//!
//! This module provides optional convenience functions to automatically
//! create and manage plans during complex multi-step tasks. The integration
//! is deliberately lightweight and opt-in to keep the core loop simple.

use crate::observability::{Observer, ObserverEvent};
use crate::tools::plan::{Plan, PlanTask, TaskStatus};
use std::sync::Arc;

/// Detect if a user message likely needs a plan.
///
/// Returns true if the message contains keywords that suggest multi-step work.
pub fn should_auto_plan(message: &str) -> bool {
    let keywords = [
        "plan", "step", "phase", "task", "break down", "outline", "strategy",
        "implement", "build", "create", "develop", "design", "research",
        "analyze", "investigate", "multiple", "several", "various", "complex",
    ];
    
    let message_lower = message.to_lowercase();
    keywords.iter().any(|k| message_lower.contains(k)) && message.len() > 50
}

/// Generate an initial plan from a user message.
///
/// This is a simple heuristic-based planner that breaks down common
/// patterns into basic tasks. Real-world usage would typically have the
/// LLM generate the plan structure instead.
pub fn generate_initial_plan(message: &str, session_id: Option<String>) -> Plan {
    let mut plan = Plan::new(
        "Auto-generated plan".to_string(),
        Some(format!("Plan for: {}", &message[..message.len().min(100)])),
        session_id,
    );

    let message_lower = message.to_lowercase();

    // Simple heuristic task generation
    if message_lower.contains("research") || message_lower.contains("investigate") {
        plan.add_task(
            "Research and information gathering".to_string(),
            Some("Collect relevant information and context".to_string()),
        );
    }

    if message_lower.contains("implement") || message_lower.contains("build") || message_lower.contains("create") {
        plan.add_task(
            "Implementation".to_string(),
            Some("Write the code or create the artifacts".to_string()),
        );
    }

    if message_lower.contains("test") || message_lower.contains("verify") {
        plan.add_task(
            "Testing and validation".to_string(),
            Some("Test the implementation and verify it works".to_string()),
        );
    }

    if message_lower.contains("document") || message_lower.contains("explain") {
        plan.add_task(
            "Documentation".to_string(),
            Some("Document the approach and results".to_string()),
        );
    }

    // Always add a review task for complex requests
    if message.len() > 200 {
        plan.add_task(
            "Review and finalize".to_string(),
            Some("Review the work and make final adjustments".to_string()),
        );
    }

    // If no specific tasks were added, add generic ones
    if plan.tasks.is_empty() {
        plan.add_task(
            "Analyze the request".to_string(),
            Some("Understand what needs to be done".to_string()),
        );
        plan.add_task(
            "Execute the work".to_string(),
            Some("Perform the main task".to_string()),
        );
        plan.add_task(
            "Review results".to_string(),
            Some("Verify the outcome is correct".to_string()),
        );
    }

    plan
}

/// Emit plan-related observer events for visibility.
pub fn emit_plan_events(observer: &Arc<dyn Observer>, plan: &Plan) {
    observer.record_event(&ObserverEvent::PlanCreated {
        plan_id: plan.id.clone(),
        title: plan.title.clone(),
    });

    for task in &plan.tasks {
        observer.record_event(&ObserverEvent::PlanTaskAdded {
            plan_id: plan.id.clone(),
            task_id: task.id.clone(),
        });
    }
}

/// Suggest next actions based on plan status.
///
/// Returns a string suggesting what the agent should focus on next,
/// or None if the plan is complete or no next steps are available.
pub fn suggest_next_action(plan: &Plan) -> Option<String> {
    let next_tasks = plan.next_tasks();

    if next_tasks.is_empty() {
        let pending = plan.tasks_by_status(TaskStatus::Pending);
        let in_progress = plan.tasks_by_status(TaskStatus::InProgress);
        let blocked = plan.tasks_by_status(TaskStatus::Blocked);

        if !in_progress.is_empty() {
            Some(format!(
                "Continue with in-progress tasks: {}",
                in_progress.iter().map(|t| t.title.as_str()).collect::<Vec<_>>().join(", ")
            ))
        } else if !blocked.is_empty() {
            Some(format!(
                "Resolve blocked tasks: {}",
                blocked.iter().map(|t| &t.title).collect::<Vec<_>>().join(", ")
            ))
        } else if !pending.is_empty() {
            Some("Review task dependencies and update status as needed".to_string())
        } else {
            None // All tasks are done
        }
    } else {
        Some(format!(
            "Focus on next ready tasks: {}",
            next_tasks.iter().map(|t| &t.title).collect::<Vec<_>>().join(", ")
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::observability::traits::{Observer, ObserverMetric};

    struct TestObserver;
    impl Observer for TestObserver {
        fn record_event(&self, _event: &ObserverEvent) {}
        fn record_metric(&self, _metric: &ObserverMetric) {}
        fn name(&self) -> &str {
            "test"
        }
        fn as_any(&self) -> &dyn std::any::Any {
            self
        }
    }

    #[test]
    fn test_should_auto_plan() {
        assert!(should_auto_plan("Please implement a REST API with authentication"));
        assert!(should_auto_plan("Research the best approach for data migration"));
        assert!(should_auto_plan("I need to build a complex multi-step pipeline"));
        
        assert!(!should_auto_plan("What time is it?"));
        assert!(!should_auto_plan("Hello"));
        assert!(!should_auto_plan("Simple question"));
    }

    #[test]
    fn test_generate_initial_plan() {
        let plan = generate_initial_plan(
            "Implement a REST API with authentication and testing",
            Some("session-123".to_string()),
        );

        assert_eq!(plan.title, "Auto-generated plan");
        assert!(plan.description.unwrap().contains("REST API"));
        assert_eq!(plan.session_id, Some("session-123".to_string()));
        
        // Should have tasks for implementation and testing
        let task_titles: Vec<_> = plan.tasks.iter().map(|t| &t.title).collect();
        assert!(task_titles.iter().any(|t| t.contains("Implementation")));
        assert!(task_titles.iter().any(|t| t.contains("Testing")));
    }

    #[test]
    fn test_suggest_next_action() {
        let mut plan = Plan::new(
            "Test Plan".to_string(),
            None,
            Some("session-1".to_string()),
        );

        let task1 = plan.add_task("Task 1".to_string(), None);
        let task2 = plan.add_task("Task 2".to_string(), None);
        plan.add_task("Task 3".to_string(), None);

        // Initially, all tasks should be ready
        let suggestion = suggest_next_action(&plan);
        assert!(suggestion.is_some());
        assert!(suggestion.unwrap().contains("Task 1"));

        // Mark first task as in progress
        plan.update_task_status(&task1, TaskStatus::InProgress);
        let suggestion = suggest_next_action(&plan);
        assert!(suggestion.is_some());
        assert!(suggestion.unwrap().contains("Task 2")); // Task 2 should still be ready

        // Mark first task as done, second depends on it
        plan.update_task_status(&task1, TaskStatus::Done);
        if let Some(task) = plan.tasks.iter_mut().find(|t| t.id == task2) {
            task.dependencies.push(task1);
        }
        let suggestion = suggest_next_action(&plan);
        assert!(suggestion.is_some());
        assert!(suggestion.unwrap().contains("Task 3")); // Task 3 should be ready
    }
}
