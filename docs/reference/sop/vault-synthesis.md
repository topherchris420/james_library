# Vault Synthesis SOP — Librarian of Resonance (Elena)

## Purpose

This Standard Operating Procedure defines the rigid workflow Elena follows to synthesize new experimental findings into the research vault (`papers/`). It ensures structural integrity, bidirectional traceability, and preservation of foundational physics equations.

---

## Trigger Conditions

**Activation:** This SOP is triggered **only** after a successful **Resonance Validation** session has been completed and formally acknowledged.

**Prerequisites:**
- [ ] Resonance Validation session completed without critical errors
- [ ] Raw experimental data or telemetry has been processed into structured findings
- [ ] James or the research team has explicitly authorized synthesis

---

## Workflow

### Phase 1 — Discovery

1. **Locate relevant existing documents**
   - Use `glob_search` with pattern `papers/*.md` to enumerate all vault documents
   - Identify documents that contain related concepts using `file_read`
   - Map existing wikilinks to understand cross-referencing patterns

2. **Assess existing coverage**
   - For each new finding, determine if a target document already exists
   - If target exists, proceed to Phase 2
   - If no target exists, prepare a new document via `file_write`

### Phase 2 — Structural Injection

1. **Read target document(s) in full**
   - Use `file_read` to retrieve complete content
   - Identify all existing foundational physics equations (markers: LaTeX `$...$`, `$$...$$`, or markdown equations)
   - Locate optimal insertion points (logical sections, not mid-equation)

2. **Draft new content**
   - Write new findings in the same voice and format as existing content
   - **Never delete or modify existing physics equations**
   - Add new data only as additional paragraphs, subsections, or appended notes
   - Use wikilink syntax `[[Document Name]]` for all cross-references

3. **Verify bidirectional links**
   - For each forward wikilink added, confirm the target document links back
   - If reciprocal link is missing, add `[[This Document]]` to the target using `file_edit`

### Phase 3 — Write-Back with Collision Protection

1. **Acquire file lock**
   - Before writing, check for lock file: `.vault.lock/{filename}.lock`
   - If lock exists, wait up to 30 seconds before retrying
   - If lock persists, log a warning and proceed with best-effort (see Phase 4)

2. **Write content**
   - Use `file_edit` for existing documents (append/inject only)
   - Use `file_write` only for new documents
   - After successful write, remove lock file

### Phase 4 — Post-Synthesis Audit

1. **Verify vault consistency**
   - Confirm all new wikilinks resolve to existing documents
   - Confirm no foundational equations were modified or deleted
   - Run a quick `glob_search` to ensure no orphaned lock files remain

2. **Generate commit message**
   - Format: `vault: synthesize {document} after Resonance Validation — {brief description}`
   - Example: `vault: synthesize Coherence Depth after Resonance Validation — add TRIBE v2 friction telemetry`

3. **Git operations** (if authorized)
   - Stage modified files: `git add papers/*.md`
   - Commit with generated message

---

## Collision Handling

| Scenario | Action |
|----------|--------|
| Lock file exists | Wait 30s, retry once. Log warning if persists. |
| Concurrent write detected | Best-effort merge: append with `[CONCURRENT UPDATE]` marker |
| File modified during read | Re-read and re-evaluate insertion point |
| Wikilink target missing | Do not create new document unless finding is seminal; log instead |

---

## Wikilink Syntax Contract

- **Intra-vault links:** `[[Document Name]]` (relative to `papers/` directory)
- **Bidirectional requirement:** Every forward link must have a reciprocal back-link
- **Link format:** `[[This Document]]` or `[[Document Name]]` — no URLs, no markdown footnotes
- **Unresolved links:** Report in synthesis summary for maintainer review

---

## Example Synthesis

**Trigger:** Resonance Validation session completes with TRIBE v2 friction coefficient data.

**Step 1:** `glob_search("papers/*.md")` → identifies `Dynamic Resonance Rooting (Friction Mechanism).md` as relevant.

**Step 2:** `file_read("papers/Dynamic Resonance Rooting (Friction Mechanism).md")` → finds existing equation `$F_f = \mu \cdot N$`.

**Step 3:** `file_edit` → inject new telemetry section after existing content:
```
## TRIBE v2 Friction Telemetry

Measured friction coefficient $\mu$ increased by 12.3% under resonance conditions.
Cross-reference: [[Coherence Depth]]
```

**Step 4:** Add reciprocal link in `Coherence Depth.md`:
```
Cross-reference: [[Dynamic Resonance Rooting (Friction Mechanism)]]
```

**Step 5:** `git commit -m "vault: synthesize Dynamic Resonance Rooting after Resonance Validation — add TRIBE v2 friction telemetry"`
