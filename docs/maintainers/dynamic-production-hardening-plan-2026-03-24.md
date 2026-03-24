# Dynamic Production Hardening Plan (2026-03-24)

This plan translates current repository signals (tests, lint, runbooks, and release gates) into a staged hardening path for production readiness.

## 1) Immediate Stabilization (P0)

### 1.1 Restore deterministic CI test outcomes

Address and triage failing Rust tests observed during local validation:

- `agent::agent::tests::from_config_passes_extra_headers_to_custom_provider`
- `agent::agent::tests::load_agent_manifest_reads_toml_schema`
- `channels::transcription::tests::local_whisper_*`
- `commands::update::tests::test_version_comparison_ignores_non_numeric_segments`
- `tools::tests::filter_tool_pool_matches_mcp_alias_patterns`

Why this is first: non-deterministic or failing CI blocks safe deploy and rollback confidence.

### 1.2 Lock and verify release gates before deployment

Run and enforce the existing release and operations checks as non-optional for production tags:

- `RELEASE_CHECKLIST.md`
- `docs/PRODUCTION_READINESS.md`
- `docs/operations-runbook.md`

## 2) Dynamic Safety Controls (P1)

### 2.1 Runtime health loop with auto-failover

Automate recurring execution of baseline checks to detect drift quickly:

- `python rain_lab.py --mode validate`
- `python rain_lab.py --mode status`
- `python rain_health_check.py`

Escalate to degraded mode if any signal fails; block autonomous high-risk actions until healthy.

### 2.2 Sidecar and launcher resilience budget enforcement

Treat sidecar restart budget as a strict SLO from production gates.
If restart budget is exceeded, fail fast and capture launcher lifecycle logs for forensic triage.

### 2.3 Backup/restore drill cadence

Operationalize recurring backup verification and restoration tests, not just one-time release checks.

## 3) Security and Boundary Hardening (P1)

### 3.1 Tighten transitive tool exposure rules

The MCP alias filtering test regression indicates risk around allowlist translation.
Before production:

- ensure alias matching is exact and principle-of-least-privilege compliant
- add negative tests for wildcard overreach
- make deny behavior explicit in error output

### 3.2 Network call determinism for local providers

Transcription failures returning 403 in mocked paths suggest mismatch between expected and actual outbound call behavior.
Add stricter request-shape tests (headers, endpoint paths, and auth behavior) and avoid implicit fallback behavior.

### 3.3 Config and manifest contract checks

Manifest allowlist mismatch indicates contract drift (`web_search` vs resolved tool names).
Introduce schema-level compatibility tests for manifest aliases and canonical tool IDs.

## 4) Observability and Operability (P2)

### 4.1 Production signal dashboard from existing artifacts

Use launcher JSONL and health outputs to build a minimal dashboard for:

- startup success rate
- sidecar restart count
- command failure classes
- backup success/failure trend

### 4.2 Structured failure catalog

Map frequent failures (provider auth, transcription API errors, update parsing, tool filter mismatch) to actionable runbook steps with direct remediation commands.

## 5) Deployment Controls (P2)

### 5.1 Progressive rollout profile

Ship with conservative defaults first:

- narrow tool allowlists
- lower concurrency for external side effects
- strict approval mode where required

Then gradually open capability only after SLO stability windows pass.

### 5.2 Rollback-first release automation

Every production deployment should have:

- immutable release tag
- previous-known-good rollback target
- scripted rollback verification using the same runbook checks

## Exit Criteria

Declare production readiness only when all of the following are true:

1. Rust and Python lint/test suites are green in CI and locally reproducible.
2. Production readiness gates in `docs/PRODUCTION_READINESS.md` all pass.
3. Recovery drills (backup + restore + service restart) succeed on schedule.
4. Security boundary tests for tools/channels/providers show deny-by-default behavior.
5. Observability signals are captured and reviewed for each release.
