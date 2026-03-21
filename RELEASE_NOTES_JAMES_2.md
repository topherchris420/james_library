# James 2 Release Notes

**Release:** James 2 (v0.3.2)
**Date:** 2026-03-16

## Highlights

James 2 represents a major evolution of the ZeroClaw agent runtime, introducing cognitive reasoning systems, swarm intelligence, episodic memory, MCP server support, academic research tools, and real-time visualization — all built on the high-performance Rust-first architecture.

## New Features

### Cognitive Reasoning Engine
- **Hypothesis Tree State Machine** — UCB1-based selection for autonomous hypothesis exploration and pruning (`hypothesis_tree.py`)
- **Epistemic Failsafe** — Stagnation and dead-end detection to prevent unproductive reasoning loops (`stagnation_monitor.py`)

### Swarm Intelligence
- **Peer Review Swarm Simulation** — Multi-agent swarm orchestrator enabling collaborative peer review workflows (`swarm_orchestrator.py`)

### Episodic Memory Pipeline
- **Action-to-Text Memory Graph** — Converts agent actions into episodic memory graphs for long-term retention and retrieval (`src/hooks/builtin/episodic_memory.rs`, `episodic_memory_ingestor.py`, `graph_bridge.py`)

### MCP Server
- **MCP-Compliant Server** — Model Context Protocol server exposing research corpus and peripherals for external tool integration (`mcp_server.py`)

### Academic Research Tools
- **ArXiv Search Tool** — Full-featured academic paper search integrated into the ZeroClaw tool surface (`src/tools/arxiv_search.rs`)

### Real-Time Visualization
- **Cymatic Resonance Visualization** — Godot-based real-time cymatic resonance display for agent conversation state (`godot_client/`)

### Provider Expansion
- **17 New Providers** — Massive expansion of model provider support with critical bug fixes from upstream

### Networking
- **P2P Gossipsub + Kademlia DHT** — Peer-to-peer networking with gossip-based pub/sub and distributed hash table support
- **WebSocket Visual Events** — Embedded WebSocket server replacing file-tailing bridge for real-time event streaming

## Improvements

### Architecture & Performance
- Extracted agent loop into focused sub-modules for maintainability
- Extracted config loader and proxy modules from monolithic schema
- Removed 9,681 lines of dead code (SOP, SkillForge, MQTT)
- Burned down 5 crate-level clippy suppressions
- Version bumped to v0.3.2

### CI/CD
- Added Termux (aarch64-linux-android) release target
- Improved CI workflow reliability

### Documentation
- Multilingual navigation hub (EN, ZH-CN, JA, RU, FR, VI)
- Rewritten README for non-technical users with platform setup guides
- Identity quick map and runtime flow documentation
- Improved onboarding UX and first-run guidance

### Code Quality
- Enforced E501 line-length linting (120 chars)
- Enforced F401 unused imports linting
- Enforced W291/W293 trailing whitespace rules
- Fixed 70+ broken test compilations
- Unique temp dirs in tests for isolation

## Bug Fixes

- Fixed Signal channel scheduled announcement delivery
- Fixed web dashboard 404 on static assets and SPA fallback
- Fixed Anthropic API empty text content block handling
- Fixed installer guided mode `/dev/stdin` redirect
- Fixed recursion limit for matrix-sdk 0.16 on Rust 1.94+
- Fixed Godot cymatics reset on conversation end
- Added missing `fastmcp` dependency to requirements

## Dependencies

- Updated `Cargo.lock` for v0.3.2
- Added `fastmcp` to Python requirements
- Cleaned up stale cargo tracking from old package name

## Stats

- **104 files changed**
- **4,660 insertions, 520 deletions**
- **156 commits** across the full history

---

Built with the ZeroClaw agent runtime. MIT OR Apache-2.0 licensed.
