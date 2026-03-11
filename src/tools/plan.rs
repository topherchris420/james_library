use super::traits::{Tool, ToolResult};
use crate::memory::{Memory, MemoryCategory};
use crate::observability::{Observer, ObserverEvent};
use crate::security::SecurityPolicy;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use uuid::Uuid;

/// Task status for plan items
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    InProgress,
    Done,
    Blocked,
}

impl std::fmt::Display for TaskStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TaskStatus::Pending => write!(f, "pending"),
            TaskStatus::InProgress => write!(f, "in_progress"),
            TaskStatus::Done => write!(f, "done"),
            TaskStatus::Blocked => write!(f, "blocked"),
        }
    }
}

/// A single task in a plan
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanTask {
    pub id: String,
    pub title: String,
    pub description: Option<String>,
    pub status: TaskStatus,
    pub created_at: String,
    pub updated_at: String,
    pub dependencies: Vec<String>, // task IDs this task depends on
}

/// A plan containing multiple tasks
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Plan {
    pub id: String,
    pub title: String,
    pub description: Option<String>,
    pub tasks: Vec<PlanTask>,
    pub created_at: String,
    pub updated_at: String,
    pub session_id: Option<String>,
}

impl Plan {
    /// Create a new plan with generated timestamps
    pub fn new(title: String, description: Option<String>, session_id: Option<String>) -> Self {
        let now = chrono::Utc::now().to_rfc3339();
        Self {
            id: Uuid::new_v4().to_string(),
            title,
            description,
            tasks: Vec::new(),
            created_at: now.clone(),
            updated_at: now,
            session_id,
        }
    }

    /// Add a task to the plan
    pub fn add_task(&mut self, title: String, description: Option<String>) -> String {
        let now = chrono::Utc::now().to_rfc3339();
        let task = PlanTask {
            id: Uuid::new_v4().to_string(),
            title,
            description,
            status: TaskStatus::Pending,
            created_at: now.clone(),
            updated_at: now,
            dependencies: Vec::new(),
        };
        let task_id = task.id.clone();
        self.tasks.push(task);
        self.updated_at = now;
        task_id
    }

    /// Update task status
    pub fn update_task_status(&mut self, task_id: &str, status: TaskStatus) -> bool {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == task_id) {
            task.status = status;
            task.updated_at = chrono::Utc::now().to_rfc3339();
            self.updated_at = task.updated_at.clone();
            true
        } else {
            false
        }
    }

    /// Get tasks by status
    pub fn tasks_by_status(&self, status: TaskStatus) -> Vec<&PlanTask> {
        self.tasks.iter().filter(|t| t.status == status).collect()
    }

    /// Get next pending tasks (no dependencies on incomplete tasks)
    pub fn next_tasks(&self) -> Vec<&PlanTask> {
        let completed_ids: std::collections::HashSet<_> = self
            .tasks
            .iter()
            .filter(|t| t.status == TaskStatus::Done)
            .map(|t| &t.id)
            .collect();

        self.tasks
            .iter()
            .filter(|t| {
                t.status == TaskStatus::Pending
                    && t.dependencies.iter().all(|dep_id| completed_ids.contains(dep_id))
            })
            .collect()
    }

    /// Render a human-readable summary
    pub fn render_summary(&self) -> String {
        let mut lines = vec![format!("Plan: {}", self.title)];
        if let Some(desc) = &self.description {
            lines.push(format!("  {}", desc));
        }
        lines.push(String::new());

        let status_counts = [
            (TaskStatus::Pending, "🔵"),
            (TaskStatus::InProgress, "🟡"),
            (TaskStatus::Done, "✅"),
            (TaskStatus::Blocked, "🔴"),
        ];

        for (status, icon) in &status_counts {
            let tasks = self.tasks_by_status(status.clone());
            if !tasks.is_empty() {
                lines.push(format!("{} {} ({}):", icon, status, tasks.len()));
                for task in tasks {
                    lines.push(format!("  - {}", task.title));
                    if let Some(desc) = &task.description {
                        lines.push(format!("    {}", desc));
                    }
                }
                lines.push(String::new());
            }
        }

        if self.tasks.is_empty() {
            lines.push("No tasks in this plan.".to_string());
        }

        lines.join("\n")
    }
}

/// Tool for creating and managing execution plans
pub struct PlanTool {
    memory: Arc<dyn Memory>,
    security: Arc<SecurityPolicy>,
    observer: Arc<dyn Observer>,
}

impl PlanTool {
    pub fn new(
        memory: Arc<dyn Memory>,
        security: Arc<SecurityPolicy>,
        observer: Arc<dyn Observer>,
    ) -> Self {
        Self {
            memory,
            security,
            observer,
        }
    }

    fn plan_key(plan_id: &str) -> String {
        format!("plan:{}", plan_id)
    }

    async fn store_plan(&self, plan: &Plan) -> anyhow::Result<()> {
        let json = serde_json::to_string(plan)?;
        self.memory
            .store(
                &Self::plan_key(&plan.id),
                &json,
                MemoryCategory::Custom("plan".to_string()),
                plan.session_id.as_deref(),
            )
            .await
    }

    async fn load_plan(&self, plan_id: &str) -> anyhow::Result<Option<Plan>> {
        if let Some(entry) = self.memory.get(&Self::plan_key(plan_id)).await? {
            let plan: Plan = serde_json::from_str(&entry.content)?;
            Ok(Some(plan))
        } else {
            Ok(None)
        }
    }

    async fn list_plans(&self, session_id: Option<&str>) -> anyhow::Result<Vec<Plan>> {
        let entries = self
            .memory
            .list(
                Some(&MemoryCategory::Custom("plan".to_string())),
                session_id,
            )
            .await?;
        let mut plans = Vec::new();
        for entry in entries {
            if let Ok(plan) = serde_json::from_str::<Plan>(&entry.content) {
                plans.push(plan);
            }
        }
        // Sort by updated_at desc
        plans.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
        Ok(plans)
    }
}

#[async_trait]
impl Tool for PlanTool {
    fn name(&self) -> &str {
        "plan"
    }

    fn description(&self) -> &str {
        "Create and manage execution plans with tasks. Use this to break down complex work into steps, track progress, and maintain context across multiple tool calls."
    }

    fn parameters_schema(&self) -> serde_json::Value {
        serde_json::json!({
            "type": "object",
            "additionalProperties": false,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "show", "add_task", "update_task", "next_tasks"],
                    "description": "Action to perform"
                },
                "plan_id": {
                    "type": "string",
                    "description": "Plan ID (required for show, add_task, update_task, next_tasks)"
                },
                "title": {
                    "type": "string",
                    "description": "Plan title (required for create) or task title (required for add_task)"
                },
                "description": {
                    "type": "string",
                    "description": "Optional description for plan or task"
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (required for update_task)"
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "blocked"],
                    "description": "New status for task (required for update_task)"
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Task IDs this task depends on (optional for add_task)"
                }
            },
            "required": ["action"]
        })
    }

    async fn execute(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let action = args
            .get("action")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'action' parameter"))?;

        if let Err(error) = self
            .security
            .enforce_tool_operation(crate::security::policy::ToolOperation::Act, "plan")
        {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(error),
            });
        }

        match action {
            "create" => self.create_plan(args).await,
            "list" => self.list_plans_action(args).await,
            "show" => self.show_plan(args).await,
            "add_task" => self.add_task(args).await,
            "update_task" => self.update_task(args).await,
            "next_tasks" => self.next_tasks(args).await,
            _ => Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!("Unknown action: {}", action)),
            }),
        }
    }
}

impl PlanTool {
    async fn create_plan(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let title = args
            .get("title")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'title' for create action"))?
            .trim()
            .to_string();

        if title.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("Title cannot be empty".to_string()),
            });
        }

        let description = args
            .get("description")
            .and_then(|v| v.as_str())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());

        let session_id = args
            .get("session_id")
            .and_then(|v| v.as_str())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());

        let mut plan = Plan::new(title, description, session_id);

        // Auto-add initial task if description suggests steps
        if let Some(desc) = &plan.description {
            if desc.contains("step") || desc.contains("phase") || desc.contains("task") {
                plan.add_task("Initial analysis".to_string(), Some("Break down the request and outline approach".to_string()));
            }
        }

        self.store_plan(&plan).await?;

        self.observer.record_event(&ObserverEvent::PlanCreated {
            plan_id: plan.id.clone(),
            title: plan.title.clone(),
        });

        Ok(ToolResult {
            success: true,
            output: format!("Created plan '{}' with ID: {}", plan.title, plan.id),
            error: None,
        })
    }

    async fn list_plans_action(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let session_id = args
            .get("session_id")
            .and_then(|v| v.as_str())
            .map(|s| s.trim())
            .filter(|s| !s.is_empty());

        let plans = self.list_plans(session_id).await?;

        if plans.is_empty() {
            return Ok(ToolResult {
                success: true,
                output: "No plans found.".to_string(),
                error: None,
            });
        }

        let mut lines = vec!["Plans:".to_string()];
        for plan in plans {
            let completed = plan.tasks_by_status(TaskStatus::Done).len();
            let total = plan.tasks.len();
            let status = if completed == total && total > 0 {
                "✅"
            } else if completed > 0 {
                "🟡"
            } else {
                "🔵"
            };
            lines.push(format!(
                "{} {} ({}): {} - {}/{} tasks",
                status,
                plan.title,
                plan.id,
                plan.updated_at,
                completed,
                total
            ));
        }

        Ok(ToolResult {
            success: true,
            output: lines.join("\n"),
            error: None,
        })
    }

    async fn show_plan(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let plan_id = args
            .get("plan_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'plan_id' for show action"))?
            .trim();

        if plan_id.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("plan_id cannot be empty".to_string()),
            });
        }

        let plan = match self.load_plan(plan_id).await? {
            Some(p) => p,
            None => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(format!("Plan '{}' not found", plan_id)),
                });
            }
        };

        Ok(ToolResult {
            success: true,
            output: plan.render_summary(),
            error: None,
        })
    }

    async fn add_task(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let plan_id = args
            .get("plan_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'plan_id' for add_task action"))?
            .trim();

        let title = args
            .get("title")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'title' for add_task action"))?
            .trim()
            .to_string();

        if plan_id.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("plan_id cannot be empty".to_string()),
            });
        }

        if title.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("title cannot be empty".to_string()),
            });
        }

        let mut plan = match self.load_plan(plan_id).await? {
            Some(p) => p,
            None => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(format!("Plan '{}' not found", plan_id)),
                });
            }
        };

        let description = args
            .get("description")
            .and_then(|v| v.as_str())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());

        let dependencies = args
            .get("dependencies")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str())
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_default();

        let task_id = plan.add_task(title, description);
        if !dependencies.is_empty() {
            if let Some(task) = plan.tasks.iter_mut().find(|t| t.id == task_id) {
                task.dependencies = dependencies;
                task.updated_at = chrono::Utc::now().to_rfc3339();
            }
        }

        self.store_plan(&plan).await?;

        self.observer.record_event(&ObserverEvent::PlanTaskAdded {
            plan_id: plan.id.clone(),
            task_id: task_id.clone(),
        });

        Ok(ToolResult {
            success: true,
            output: format!("Added task '{}' to plan '{}'", task_id, plan.id),
            error: None,
        })
    }

    async fn update_task(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let plan_id = args
            .get("plan_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'plan_id' for update_task action"))?
            .trim();

        let task_id = args
            .get("task_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'task_id' for update_task action"))?
            .trim();

        let status_str = args
            .get("status")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'status' for update_task action"))?
            .trim();

        if plan_id.is_empty() || task_id.is_empty() || status_str.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("plan_id, task_id, and status cannot be empty".to_string()),
            });
        }

        let status = match status_str {
            "pending" => TaskStatus::Pending,
            "in_progress" => TaskStatus::InProgress,
            "done" => TaskStatus::Done,
            "blocked" => TaskStatus::Blocked,
            _ => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(format!("Invalid status: {}", status_str)),
                });
            }
        };

        let mut plan = match self.load_plan(plan_id).await? {
            Some(p) => p,
            None => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(format!("Plan '{}' not found", plan_id)),
                });
            }
        };

        if !plan.update_task_status(task_id, status) {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some(format!("Task '{}' not found in plan '{}'", task_id, plan_id)),
            });
        }

        self.store_plan(&plan).await?;

        self.observer.record_event(&ObserverEvent::PlanTaskUpdated {
            plan_id: plan.id.clone(),
            task_id: task_id.to_string(),
            status: format!("{:?}", status),
        });

        Ok(ToolResult {
            success: true,
            output: format!("Updated task '{}' to status '{}'", task_id, status_str),
            error: None,
        })
    }

    async fn next_tasks(&self, args: serde_json::Value) -> anyhow::Result<ToolResult> {
        let plan_id = args
            .get("plan_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow::anyhow!("Missing 'plan_id' for next_tasks action"))?
            .trim();

        if plan_id.is_empty() {
            return Ok(ToolResult {
                success: false,
                output: String::new(),
                error: Some("plan_id cannot be empty".to_string()),
            });
        }

        let plan = match self.load_plan(plan_id).await? {
            Some(p) => p,
            None => {
                return Ok(ToolResult {
                    success: false,
                    output: String::new(),
                    error: Some(format!("Plan '{}' not found", plan_id)),
                });
            }
        };

        let next_tasks = plan.next_tasks();

        if next_tasks.is_empty() {
            let pending = plan.tasks_by_status(TaskStatus::Pending);
            let in_progress = plan.tasks_by_status(TaskStatus::InProgress);
            let blocked = plan.tasks_by_status(TaskStatus::Blocked);

            let mut lines = vec!["No tasks ready to start.".to_string()];
            if !pending.is_empty() {
                lines.push(format!("🔵 Pending tasks ({}):", pending.len()));
                for task in pending {
                    lines.push(format!("  - {}", task.title));
                }
            }
            if !in_progress.is_empty() {
                lines.push(format!("🟡 In progress ({}):", in_progress.len()));
                for task in in_progress {
                    lines.push(format!("  - {}", task.title));
                }
            }
            if !blocked.is_empty() {
                lines.push(format!("🔴 Blocked ({}):", blocked.len()));
                for task in blocked {
                    lines.push(format!("  - {}", task.title));
                }
            }

            return Ok(ToolResult {
                success: true,
                output: lines.join("\n"),
                error: None,
            });
        }

        let mut lines = vec![format!("Next ready tasks ({}):", next_tasks.len())];
        for task in next_tasks {
            lines.push(format!("🔵 {} (ID: {})", task.title, task.id));
            if let Some(desc) = &task.description {
                lines.push(format!("  {}", desc));
            }
        }

        Ok(ToolResult {
            success: true,
            output: lines.join("\n"),
            error: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::none::NoneMemory;
    use crate::observability::traits::{Observer, ObserverEvent, ObserverMetric};
    use std::sync::Arc;

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

    fn test_tool() -> PlanTool {
        PlanTool::new(
            Arc::new(NoneMemory::default()),
            Arc::new(SecurityPolicy::default()),
            Arc::new(TestObserver),
        )
    }

    #[tokio::test]
    async fn create_plan() {
        let tool = test_tool();
        let result = tool
            .execute(serde_json::json!({
                "action": "create",
                "title": "Test Plan",
                "description": "A test plan for unit testing"
            }))
            .await
            .unwrap();

        assert!(result.success);
        assert!(result.output.contains("Created plan"));
        assert!(result.output.contains("Test Plan"));
        assert!(result.error.is_none());
    }

    #[tokio::test]
    async fn add_and_update_task() {
        let tool = test_tool();

        // Create plan
        let create_result = tool
            .execute(serde_json::json!({
                "action": "create",
                "title": "Task Test Plan"
            }))
            .await
            .unwrap();
        assert!(create_result.success);

        // Extract plan ID from output
        let plan_id = create_result.output.split("ID: ").nth(1).unwrap().trim();

        // Add task
        let add_result = tool
            .execute(serde_json::json!({
                "action": "add_task",
                "plan_id": plan_id,
                "title": "Test Task",
                "description": "A test task"
            }))
            .await
            .unwrap();
        assert!(add_result.success);

        // Show plan
        let show_result = tool
            .execute(serde_json::json!({
                "action": "show",
                "plan_id": plan_id
            }))
            .await
            .unwrap();
        assert!(show_result.success);
        assert!(show_result.output.contains("Test Task"));
        assert!(show_result.output.contains("🔵"));

        // Extract task ID from show output
        let task_id = show_result.output.lines()
            .find(|line| line.contains("Test Task"))
            .and_then(|line| line.split("ID: ").nth(1))
            .map(|s| s.trim_end_matches(')'))
            .unwrap();

        // Update task to in_progress
        let update_result = tool
            .execute(serde_json::json!({
                "action": "update_task",
                "plan_id": plan_id,
                "task_id": task_id,
                "status": "in_progress"
            }))
            .await
            .unwrap();
        assert!(update_result.success);

        // Verify status changed
        let show_result2 = tool
            .execute(serde_json::json!({
                "action": "show",
                "plan_id": plan_id
            }))
            .await
            .unwrap();
        assert!(show_result2.success);
        assert!(show_result2.output.contains("🟡"));
    }

    #[tokio::test]
    async fn next_tasks_with_dependencies() {
        let tool = test_tool();

        // Create plan
        let create_result = tool
            .execute(serde_json::json!({
                "action": "create",
                "title": "Dependency Test Plan"
            }))
            .await
            .unwrap();
        let plan_id = create_result.output.split("ID: ").nth(1).unwrap().trim();

        // Add first task
        let add1 = tool
            .execute(serde_json::json!({
                "action": "add_task",
                "plan_id": plan_id,
                "title": "Task 1"
            }))
            .await
            .unwrap();
        assert!(add1.success);
        let task1_id = add1.output.split("Added task '").nth(1).unwrap().split("'").next().unwrap();

        // Add second task depending on first
        let add2 = tool
            .execute(serde_json::json!({
                "action": "add_task",
                "plan_id": plan_id,
                "title": "Task 2",
                "dependencies": [task1_id]
            }))
            .await
            .unwrap();
        assert!(add2.success);

        // Check next tasks - should only show Task 1
        let next_result = tool
            .execute(serde_json::json!({
                "action": "next_tasks",
                "plan_id": plan_id
            }))
            .await
            .unwrap();
        assert!(next_result.success);
        assert!(next_result.output.contains("Task 1"));
        assert!(!next_result.output.contains("Task 2"));

        // Complete Task 1
        tool.execute(serde_json::json!({
            "action": "update_task",
            "plan_id": plan_id,
            "task_id": task1_id,
            "status": "done"
        }))
        .await
        .unwrap();

        // Now Task 2 should be ready
        let next_result2 = tool
            .execute(serde_json::json!({
                "action": "next_tasks",
                "plan_id": plan_id
            }))
            .await
            .unwrap();
        assert!(next_result2.success);
        assert!(next_result2.output.contains("Task 2"));
    }
}
