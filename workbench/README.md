

# R.A.I.N. Workbench

A three-panel governance workbench for the R.A.I.N. operating loop.

## Run Locally

**Prerequisites:** Node.js

1. Install dependencies:
   `npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
3. Run the app:
   `npm run dev`

---

## Integration Plan — Connecting the Workbench to R.A.I.N. Architecture

### Current State

The workbench is a standalone Angular 21 app with a three-panel layout (Subject → Matter → Levers) that generates **mock** tensions, levers, and scenarios via `RainService`. It makes zero calls to the R.A.I.N. backend.

The R.A.I.N. Rust backend (Axum gateway) already exposes:
- **REST API** — `/api/status`, `/api/config`, `/api/tools`, `/api/memory`, `/api/meeting/*`, `/api/doctor`, `/api/cost`, `/api/cron`, `/api/health`
- **SSE stream** — `/api/events` (LLM requests, tool calls, memory events, agent lifecycle)
- **WebSocket** — `/ws/chat` (interactive agent chat with streaming responses)
- **Auth** — Bearer token via `/pair` endpoint

The two systems are complementary but disconnected. This plan bridges them.

---

### Phase 1 — Plumbing & Health Link

**Goal:** Establish HTTP connectivity and prove the workbench can talk to the backend.

- [ ] Add `provideHttpClient()` to Angular `appConfig` providers
- [ ] Create `ApiService` with configurable base URL (env-driven, default `http://localhost:3000`)
- [ ] Wire `/api/status` → display live system status (provider, model, uptime, channel health) in `TopNavComponent` replacing the static "SYS.STATUS: ONLINE" indicator
- [ ] Wire `/api/health` → show per-component health in the Lever panel's system logs section
- [ ] Handle auth: implement token acquisition via `/pair` and attach Bearer token to requests
- [ ] Add connection-error fallback so the UI degrades gracefully when the backend is unreachable (current mock mode as offline fallback)

**Deliverable:** The workbench shows real system status from a running R.A.I.N. instance. The green "ONLINE" badge reflects actual backend reachability.

---

### Phase 2 — Real-Time Event Stream

**Goal:** Replace simulated AI terminal output with live backend events.

- [ ] Connect to `/api/events` SSE stream in `RainService`
- [ ] Route incoming events by type:
  - `llm_request` / `llm_response` → AI terminal output in `TensionPanelComponent`
  - `tool_call` / `tool_result` → tool execution log entries
  - `memory_event` → memory activity indicators
  - `error` → surface in system logs
- [ ] Feed live events into the artifact bar's rotating display
- [ ] Add reconnection logic with exponential backoff on SSE disconnect

**Deliverable:** The center panel's AI terminal shows real agent activity as it happens. Logs section fills with genuine runtime events.

---

### Phase 3 — Agent Chat via WebSocket

**Goal:** Let users interact with the R.A.I.N. agent directly from the workbench.

- [ ] Create `ChatService` wrapping the `/ws/chat` WebSocket (token via query param)
- [ ] Add a chat input in the Tension panel (alongside or replacing Use/Build/AAC modes)
- [ ] Handle WebSocket message types: `chunk` (streaming text), `tool_call`, `tool_result`, `done`
- [ ] Display streaming responses in the AI terminal with typewriter effect
- [ ] Surface tool calls inline (name, parameters, result) as expandable log entries

**Deliverable:** Users can send messages to the agent and watch it think, call tools, and respond — all within the workbench UI.

---

### Phase 4 — Governance Loop Integration

**Goal:** Bridge the workbench's governance model (Tensions/Levers/Scenarios) with backend intelligence.

- [ ] Replace mock `runPhase()` logic — send the input context (stakes, constraints, non-negotiables, horizon) to the agent via WebSocket or a new dedicated endpoint
- [ ] Parse agent responses into structured Tensions (conflict detection) and Levers (actionable demands)
- [ ] Wire Scenario generation to agent reasoning: Use/Build mode sends lever configurations to the agent for evaluation
- [ ] Connect blocking-question modal to agent ambiguity detection (agent requests clarification → modal surfaces it)
- [ ] Persist phase results to backend memory via `/api/memory`

**Deliverable:** "INITIATE PHASE" triggers real agent analysis. Tensions and levers come from LLM reasoning over the user's input, not hardcoded arrays.

---

### Phase 5 — Config, Tools & Memory Management

**Goal:** Expose backend administration through the workbench.

- [ ] Wire `/api/config` GET/PUT → settings modal for viewing/editing R.A.I.N. configuration
- [ ] Wire `/api/tools` → display registered tool catalog with parameter schemas
- [ ] Wire `/api/memory` CRUD → browsable memory panel (search, create, delete entries)
- [ ] Wire `/api/cron` → cron job viewer/editor
- [ ] Wire `/api/cost` → cost tracking dashboard in metrics or lever panel
- [ ] Wire `/api/doctor` → run diagnostics from UI, display results

**Deliverable:** The workbench becomes a full operational dashboard — not just governance input, but runtime administration.

---

### Phase 6 — Embedded Build & Meeting Integration

**Goal:** Ship the workbench as part of the R.A.I.N. binary and integrate meeting workflows.

- [ ] Add Angular build output to `web/dist/` so the Rust binary serves it via `rust-embed` at `/_app/*`
- [ ] Wire `/api/meeting/start` / `/api/meeting/stop` / `/api/meeting/status` → meeting controls in the UI
- [ ] Display live meeting transcript (multi-agent turns) via SSE or WebSocket
- [ ] Export meeting artifacts (logs, citations) through the Lever panel's existing JSON/CSV export
- [ ] Remove standalone dev-server dependency for production — the workbench runs inside R.A.I.N.

**Deliverable:** `cargo run -- serve` starts the gateway with the workbench embedded. One binary, one port, full UI.

---

### Architecture Alignment Reference

| Workbench Concept | Backend Surface | Integration Point |
|---|---|---|
| SYS.STATUS indicator | `GET /api/status` | Phase 1 |
| AI terminal output | `GET /api/events` (SSE) | Phase 2 |
| Agent chat | `/ws/chat` (WebSocket) | Phase 3 |
| Tensions / Levers / Scenarios | Agent reasoning via chat or custom endpoint | Phase 4 |
| Blocking question modal | Agent clarification requests | Phase 4 |
| System logs | `/api/events` + `/api/health` | Phase 1–2 |
| Settings / Config | `GET/PUT /api/config` | Phase 5 |
| Tool catalog | `GET /api/tools` | Phase 5 |
| Memory panel | `/api/memory` CRUD | Phase 5 |
| Data export (JSON/CSV) | Client-side (Papaparse) + backend data | Phase 5 |
| Meeting controls | `/api/meeting/*` | Phase 6 |
| Embedded serving | `/_app/*` via `rust-embed` | Phase 6 |
