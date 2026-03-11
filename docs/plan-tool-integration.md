# PlanTool Integration Guide

This document explains how to use the new PlanTool in ZeroClaw to enable explicit planning and task tracking for complex multi-step work.

## Overview

The PlanTool provides a structured way to:
- Create execution plans with tasks
- Track task status (pending/in_progress/done/blocked)
- Manage task dependencies
- Maintain context across multiple tool calls
- Improve visibility into multi-step workflows

## Tool Interface

The PlanTool supports these actions:

### `create`
Create a new plan with optional description and session ID.

```json
{
  "action": "create",
  "title": "Implement REST API",
  "description": "Build a secure REST API with authentication",
  "session_id": "optional-session-id"
}
```

### `add_task`
Add a task to an existing plan.

```json
{
  "action": "add_task",
  "plan_id": "plan-uuid",
  "title": "Design database schema",
  "description": "Create tables and relationships",
  "dependencies": ["task-uuid-1", "task-uuid-2"]
}
```

### `update_task`
Update task status.

```json
{
  "action": "update_task",
  "plan_id": "plan-uuid",
  "task_id": "task-uuid",
  "status": "in_progress"  // pending, in_progress, done, blocked
}
```

### `show`
Display a human-readable plan summary.

```json
{
  "action": "show",
  "plan_id": "plan-uuid"
}
```

### `list`
List all plans (optionally filtered by session).

```json
{
  "action": "list",
  "session_id": "optional-session-id"
}
```

### `next_tasks`
Show tasks that are ready to start (no incomplete dependencies).

```json
{
  "action": "next_tasks",
  "plan_id": "plan-uuid"
}
```

## Integration Points

### 1. Tool Registry

The PlanTool is automatically included in the full tool registry via `all_tools_with_runtime()` in `src/tools/mod.rs`. It receives:
- Memory backend for persistence
- Security policy for access control
- Observer for event emission

### 2. Observability

New observer events were added to `src/observability/traits.rs`:
- `PlanCreated { plan_id, title }`
- `PlanTaskAdded { plan_id, task_id }`
- `PlanTaskUpdated { plan_id, task_id, status }`

### 3. Agent Integration (Optional)

The `src/agent/plan_integration.rs` module provides convenience functions:
- `should_auto_plan(message)` - Detect if a message likely needs planning
- `generate_initial_plan(message, session_id)` - Heuristic plan generation
- `suggest_next_action(plan)` - Get next actionable tasks
- `emit_plan_events(observer, plan)` - Emit plan events

These are deliberately lightweight and opt-in to keep the core loop simple.

## Usage Patterns

### Manual Planning
For complex requests, agents can explicitly create plans:

1. Create a plan with `plan create`
2. Add tasks with `plan add_task`
3. Work through tasks using `plan next_tasks`
4. Update status with `plan update_task`
5. Review progress with `plan show`

### Semi-Automated Planning
Use the integration helpers:

```rust
use crate::agent::plan_integration::*;

// In the agent loop, before processing:
if should_auto_plan(&user_input) {
    let plan = generate_initial_plan(&user_input, session_id);
    emit_plan_events(&observer, &plan);
    // Store plan and suggest next actions
}
```

### Delegation with Plans
Subagents can receive plan context:

```json
{
  "action": "delegate",
  "agent": "specialist",
  "prompt": "Implement the authentication module",
  "context": "Current plan: Implement REST API. Next task: Design database schema"
}
```

## Storage

Plans are stored in the configured memory backend under keys like `plan:{uuid}` with category `Custom("plan")`. This means:
- SQLite memory: persists across restarts
- In-memory memory: session-scoped
- Markdown memory: human-readable files

## Security

The PlanTool respects the security policy:
- Requires `ToolOperation::Act` permission
- No filesystem access (uses memory backend only)
- No external dependencies

## Examples

### Example 1: API Development
```
User: "Implement a secure REST API with user authentication"

Agent: I'll create a plan for this complex task.

[plan create title="Secure REST API" description="Build REST API with authentication"]
Created plan 'Secure REST API' with ID: abc-123

[plan add_task plan_id="abc-123" title="Design API endpoints"]
Added task 'def-456' to plan 'abc-123'

[plan add_task plan_id="abc-123" title="Implement authentication"]
Added task 'ghi-789' to plan 'abc-123'

[plan add_task plan_id="abc-123" title="Add validation and error handling"]
Added task 'jkl-012' to plan 'abc-123'

[plan show]
Plan: Secure REST API
  Build REST API with authentication

🔵 pending (3):
  - Design API endpoints
  - Implement authentication
  - Add validation and error handling

[plan next_tasks]
Next ready tasks (3):
🔵 Design API endpoints (ID: def-456)
🔵 Implement authentication (ID: ghi-789)
🔵 Add validation and error handling (ID: jkl-012)
```

### Example 2: Research Task
```
User: "Research the best database options for our high-traffic application"

Agent: I'll create a research plan.

[plan create title="Database Research" description="Evaluate databases for high-traffic app"]
Created plan 'Database Research' with ID: xyz-789

[plan add_task plan_id="xyz-789" title="Gather requirements"]
Added task 'req-111' to plan 'xyz-789'

[plan add_task plan_id="xyz-789" title="Research PostgreSQL"]
Added task 'pg-222' to plan 'xyz-789'

[plan add_task plan_id="xyz-789" title="Research MongoDB"]
Added task 'mongo-333' to plan 'xyz-789'

[plan add_task plan_id="xyz-789" title="Compare performance"]
Added task 'perf-444' to plan 'xyz-789' dependencies=["req-111"]

[plan update_task plan_id="xyz-789" task_id="req-111" status="done"]
Updated task 'req-111' to status 'done'

[plan next_tasks]
Next ready tasks (2):
🔵 Research PostgreSQL (ID: pg-222)
🔵 Research MongoDB (ID: mongo-333)
```

## Testing

The PlanTool includes comprehensive tests in `src/tools/plan.rs`:
- Plan creation and management
- Task dependencies and status updates
- Next task calculation
- Integration with memory backend

Run tests with:
```bash
cargo test plan
```

## Future Enhancements

Potential improvements:
- LLM-driven plan generation instead of heuristics
- Plan templates for common patterns
- Cross-session plan continuity
- Plan export/import formats
- Integration with delegation tool
- Visual plan rendering in web interface

## Migration from Ad-hoc

To migrate existing agents to use planning:
1. Identify multi-step patterns in your prompts
2. Add plan creation for complex requests
3. Break down work into explicit tasks
4. Use plan status to track progress
5. Leverage next_tasks for focus

This improves reliability, observability, and context management without changing the core agent loop.
