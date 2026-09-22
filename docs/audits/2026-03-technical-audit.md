# Technical audit — R.A.I.N. Lab / james_library

Inspected 2026-09-22 against the working tree. This file is a maintainer audit, not a product claim. Paths below were read in that tree.

## 1. What the system actually is

R.A.I.N. Lab's user-facing product is a Python process. `python rain_lab.py` is a thin wrapper around `james_library/launcher/rain_lab.py` (~3,000 lines), which subprocesses either `rain_lab_meeting_chat_version.py` (~3,700 lines, default `chat` mode) or `rain_lab_meeting.py` (~1,700 lines, `rlm` mode). Both load four persona files (`JAMES_SOUL.md`, `JASMINE_SOUL.md`, `LUCA_SOUL.md`, `ELENA_SOUL.md`), call an OpenAI-compatible HTTP endpoint, and write a transcript. Beside that product sits a large Rust agent runtime (`src/`, package `rain-labs`, binary `rain`, ~392 Rust files) with its own providers, tools, memory, security policy, and channels. The Python meeting loop does not call `rain`. `python/` is a separate LangGraph tool package. `crates/` holds satellite crates (`logic_prover`, `rain-bench`, `robot-kit`, `buzz-agent`, `aardvark-sys`), not the meeting runtime.

## 2. What is genuinely strong or novel

These are real, and they are more interesting than the marketing panel.

**Bounded meeting recovery, with an honest contract.** `james_library/utilities/meeting_recovery.py` escalates repetition through evidence → alternative → wrap-up, with cooldown and a terminal wrap-up. `docs/meeting-recovery.md` states that similarity is a scheduling signal, not evidence that a hypothesis is false. `tests/test_meeting_recovery.py` and `tests/test_meeting_recovery_integration.py` cover the controller. The chat loop records recovery as `SYSTEM` turns in the session JSON (`rain_lab_meeting_chat_version.py`, `_check_meeting_progress`).

**A session artifact with an explicit grounding envelope.** `james_library/utilities/session_artifact.py` writes `rain-session-artifact/v1` JSON. `james_library/utilities/truth_layer.py` sets `grounded` / `red_badge` from whether provenance and evidence lists are non-empty. Chat mode records each turn through this writer. That schema is the right object to evaluate. The verifier that fills it is not (section 3).

**Post-hoc quote checks against a loaded corpus.** `CitationAnalyzer` in `rain_lab_meeting_chat_version.py` extracts quotes longer than three words and asks `ContextManager.verify_citation` to find them in an in-memory index of loaded files. `james_library/utilities/rain_metrics.py` separately scores fuzzy quote overlap, novel-claim density, and critique-change rate, and can append `metrics_log.jsonl`. The machinery exists. The match rule and the corpus boundary do not make the score mean "this sentence is in a paper."

**SOUL files are schema-checked, not just prose.** `tests/test_soul_schema.py` and `tests/test_soul_files.py` require YAML frontmatter and the four named files. `Agent.load_soul` in `agents.py` appends a tool contract (including `verify_logic`) onto the markdown. The chat meeting does not use that class (section 3).

**A propositional SAT solver that is actually a solver.** `crates/logic_prover/src/lib.rs` is a DPLL implementation with a C ABI (`verify_logic`). `james_library/utilities/tools.py` contains a parallel pure-Python DPLL (`_verify_logic_python`). Propositional satisfiability is a legitimate, narrow tool. The meeting copy treats a SAT result as a stand-in for physical plausibility (section 3).

**Experiment protocol as a separate epistemic boundary.** `james_library/services/experiment_protocol/` versions a manifest, hashes it, separates R.A.I.N. reasoning from a CIRCLE witness, keeps adversarial critique beside the first interpretation, and sets `requires_human_review=True` so a next experiment is a proposal. Fixtures cover positive control, negative control, artifact-only, and insufficient sample (`fixtures.py`). Tests live in `james_library/tests/test_experiment_protocol.py`. The launcher exposes this as `--mode experiment`. It is not called by the four-agent meeting. That separation is the correct shape; it is also why a meeting transcript is not an experiment.

**Rust security defaults are stricter than the Python meeting.** `src/security/policy.rs` defaults to `AutonomyLevel::Supervised` and `workspace_only: true`. `src/security/pairing.rs` treats non-loopback binds as public. TRIBE v2 is off unless `[tribev2] enabled = true` (`src/config/schema/security.rs`). `docs/project/product-boundary.md` is more accurate than the README: channels, hardware, TRIBE, and web deploy are opt-in.

**Python CI actually runs the product tests.** `.github/workflows/ci.yml` runs `pytest` on Python 3.10, 3.11, and 3.12. `.github/workflows/tests.yml` runs `pytest -q` on 3.11. Requirements are pinned (`requirements-pinned.txt`, `requirements-dev-pinned.txt`). Rust lint/build lives in `.github/workflows/ci-run.yml` and does not execute a meeting.

## 3. What is weak or overclaimed

**The default corpus is the repository, so product copy can "verify."** `DEFAULT_LIBRARY_PATH` in `rain_lab_meeting_chat_version.py` is the directory containing that file (the repo root). `_discover_files` keeps top-level `.md` and `.txt` unless the name contains `SOUL`, `LOG`, or `MEETING`. There are 28 top-level markdown files, including `README.md`. `verify_citation` lowercases the quote and searches the first 5 words, then 8, then a middle window, as a substring of a concatenated index. A five-word window from the README sample dialogue can resolve to a "paper." Chat mode refuses to start when `paper_list` is empty, so a fresh clone "succeeds" by reading its own docs.

**`require_quotes` does not require quotes.** `Config.require_quotes = True` is never read. `CitationAnalyzer` records unverified quotes and still returns the turn. The meeting prints a check mark only when something verified; it does not drop, rewrite, or badge the spoken text. `red_badge` is computed later by the artifact writer from whether any quote happened to match. A turn with no quotes gets confidence 0.2 and `grounded: false`, and the meeting continues.

**Session eval rewards fluency markers.** `james_library/utilities/session_eval.py` scores disagreement by substring hits on `disagree`, `however`, `but `, `wrong`, and similar tokens, and actionability by `next step`, `measure`, `run `, `test `. `benchmark_data/session_eval_gold.json` has three topics and thresholds on those ratios. A model can pass by saying "however" and "next step" without a quote that exists in a paper. `session_replay.py` shells out to a live `rain_lab.py --mode chat` run. CI does not run that replay. Nothing in CI fails a meeting for being ungrounded.

**Demo mode is a template, and the README exchange is not a run.** `_build_demo_session_markdown` in `james_library/launcher/rain_lab.py` writes fixed Founder/Skeptic/Builder paragraphs. The generated note says no model was used. `README.md` "See It In Action" is a authored dialogue (Landauer bound, `10⁴⁵` joules, `verify_logic()`). It is not an artifact from `meeting_archives/`. Treating it as evidence of the system is a category error.

**The five-stage "mandatory" protocol is not the meeting.** `james_library/launcher/meeting_workflow.py` defines hypothesis → simulation → synthesis → peer critique → discovery, with accept at score ≥ 8. Nothing in the meeting runners imports `MeetingWorkflow` (only `hello_os.py` has an unrelated `create_workflow`). `agents.py` still injects that protocol into souls as mandatory, including "trigger Godot/local physics verification." Chat mode rotates four agents for `max_turns` (default 25, wrap-up after turn 10) and never calls `set_peer_critique` or `finalize_discovery_gate`.

**Three agent implementations.** `agents.py`, the `Agent` class inside `rain_lab_meeting.py`, and `RainLabAgentFactory` inside `rain_lab_meeting_chat_version.py`. Chat does not import `agents.py`. Extended personas (Alex, Sarah, Diana) exist only on `create_extended_team` and are not the default meeting.

**The hypothesis tree does not branch.** Chat constructs a `HypothesisTree`, adds one root equal to the topic, and never calls `add_child`. UCB1 in `james_library/utilities/hypothesis_tree.py` therefore selects a single node. `_update_hypothesis_after_turn` disproves that node when a turn has ≥3 unverified quotes and zero verified quotes. Those "unverified quotes" are any quotation marks whose five-word window missed the index, including quotes of other agents. Pruning is not a scientific result.

**`verify_logic` in the Python tool path does not call the Rust/WASM solver.** `tools.py` imports `subprocess` inside `verify_logic` and then calls `_verify_logic_python`. The docstring says it bridges to the WASM plugin. SOUL text tells Elena that a SAT/UNSAT result is formal verification of the hypothesis. Propositional SAT cannot check Landauer's bound, energy, or geometry. The README sample uses `verify_logic()` as if it had.

**RLM mode replaces the model's first turn.** In `rain_lab_meeting.py` `ResearchCouncil.run`, if preferred files exist, the first response is overwritten with a fixed `read_paper(...)` block plus "Hey team, so today we're talking about…". Later turns strip tool calls. Several refusal phrases are also replaced with that same opener. The transcript can show tool use the model did not produce. Model calls are capped and timed out, which is good, but the override makes the opener non-evidence.

**TRIBE v2 is not inside the research meeting, and the output cannot validate a brain region.** README section "TRIBE v2 Brain Encoding" and the comparison table say the meeting runs TRIBE and returns activation across 20,484 vertices so you can check whether a stimulus engages the regions a hypothesis names. The Python meeting never references `tribev2`. The Rust tool `src/tools/tribev2.rs` POSTs to a sidecar and formats `mean` / `max` / `min` per segment. `tools/tribev2_sidecar/server.py` computes those scalars with `np.mean` / `np.max` / `np.min` and discards the vertex vector. No parcellation, no region label, no atlas. The sidecar has no authentication. `README` in that directory documents `--host 0.0.0.0`. File paths are opened if they exist on the sidecar host. TRIBE v2 is CC-BY-NC 4.0 inside an MIT-or-Apache Rust tree; the config comment records the license, the dependency does not vendor the weights (`tools/tribev2_sidecar/requirements.txt` installs `tribev2` from GitHub).

**"No cloud calls" is not the default chat configuration.** Chat `enable_web_search` defaults to `True` and uses DuckDuckGo (`WebSearchManager`). `DEFAULT_MODEL_NAME` falls back to `minimax-m2.7:cloud` while `base_url` falls back to `http://127.0.0.1:11434/v1`. A stock run asks Ollama for a cloud model id and fails `test_connection`, or, if that name is aliased, still searches the web unless `--no-web` is passed. `rain_lab_meeting.py` speaks via `edge-tts` when installed, which sends utterance text to a Microsoft endpoint. Chat prefers local `pyttsx3` and falls back to `edge-tts`. Temperature defaults to 0.7 (`--temp` / `Config.temperature`). There is no seed.

**Product-boundary vs README.** `docs/project/product-boundary.md` says the stable core includes the Rust `rain` runtime's provider, tool, memory, security, and gateway contracts. The command `python rain_lab.py` never starts `rain`. A reader who trusts the boundary doc will look for meeting behavior in Rust and will not find it. A reader who trusts the README developer section (before this change) was pointed at `python/` and `crates/` for the meeting. Those paths are wrong. `README.md` also called Luca a "Field Topographer" in the table and a "Field Tomographer" in the link; `LUCA_SOUL.md` says Tomographer.

**Graph-R1 is a name for the native graph.** `james_library/utilities/graph_bridge.py` `_build_graph_r1_placeholder` calls `_build_native_graph`. Keyword co-occurrence is fine. Calling the mode `graph-r1` is not.

**Tests assert source text, not meeting behavior.** `tests/test_rain_lab_meeting_structure.py` parses `rain_lab_meeting.py` and checks that helper names occur once and that a string `RAIN_MAX_CALLS_PER_TURN` is present. That does not execute a turn.

## 4. Highest-value technical improvements

### P0 — Corpus boundary and a citation check that can fail

**Why.** Every other claim (grounded meetings, eval, hypothesis pruning, "papers not smooth talk") depends on this. Today the default library is the repo, the match is a 5-word substring, and `require_quotes` is dead. An outsider cannot tell a cited paper from the README.

**Scope.** `ContextManager._discover_files` and `verify_citation` in `rain_lab_meeting_chat_version.py`; the same idea in `rain_lab_meeting.py` host file selection; `truth_layer.py` / artifact writer only if the metadata contract changes. No new service.

**Acceptance.** With library = repo root, a quote that occurs only in `README.md` is not a verified paper citation. A quote that occurs only in a file under a designated corpus directory verifies with filename plus character span. A chat turn that was required to quote and did not verify is stored with `grounded: false` and is not printed as a successful citation. A unit test covers both fixtures without a network call.

### P0 — One replayable artifact an outsider can score offline

**Why.** `session_eval.py` can be gamed with discourse markers, and `session_replay.py` needs a live model. Temperature is 0.7 and is not stored. The artifact records model name and topic, not temperature, prompt hash, corpus file hashes, or the raw completion id.

**Scope.** `SessionArtifactWriter.record_turn` / `finalize`, chat loop call site, `session_eval.py` scoring. Keep the existing schema version or bump it explicitly.

**Acceptance.** A completed chat artifact includes temperature, base URL, model id, sha256 of each loaded corpus file, and a hash of the system prompt. Eval fails a fixture whose quotes do not occur in the declared corpus, even if the text contains "however" and "next step." `pytest` runs that fixture with no model process.

### P1 — One meeting state machine, or stop describing the others as mandatory

**Why.** Maintainers cannot change "the meeting" safely. Chat, RLM, `MeetingWorkflow`, and three `Agent` classes diverge, and RLM overwrites the opener. Recovery and artifacts exist only on the chat path.

**Scope.** Pick chat as the product path (it already has artifacts and recovery). Either delete `MeetingWorkflow` from soul prompts or make the chat director call it. Mark `rain_lab_meeting.py` experimental in `docs/project/product-boundary.md` until it writes the same artifact.

**Acceptance.** `python rain_lab.py --help` and `docs/project/product-boundary.md` name one default engine. A grep for `MeetingWorkflow` shows either a call from that engine or no user-facing "mandatory" prompt. A fake-LLM test drives four turns and writes one artifact.

### P1 — Make `verify_logic` either the crate or a clearly labeled propositional check

**Why.** Two solvers will drift. Souls currently tell the model that SAT is hypothesis verification. That will be quoted back as if it were physics.

**Scope.** `james_library/utilities/tools.py` `verify_logic`, `crates/logic_prover`, the four `*_SOUL.md` tool sections, and the RLM prompt if it still advertises the tool.

**Acceptance.** The Python function calls `logic_prover` (or documents and tests the Python DPLL as the only implementation and deletes the unused `subprocess` import). The tool result JSON includes `solver: propositional-dpll` and does not include words like "physically plausible." A soul line that says SAT checks energy or geometry is gone. A test vector matches `crates/logic_prover` on `(A OR B) AND (NOT A)`.

### P1 — TRIBE: either return a map or stop claiming one

**Why.** Mean activation over ~20k vertices cannot confirm a cortical hypothesis. An unauthenticated sidecar that reads arbitrary paths is a local file oracle if it is bound beyond loopback.

**Scope.** `tools/tribev2_sidecar/server.py`, `src/tools/tribev2.rs`, README TRIBE section. Keep `enabled = false`.

**Acceptance.** Predict responses include either a downsampled vertex vector plus atlas id, or the README states that only segment mean/max/min are returned and that region claims are unsupported. The server refuses non-loopback bind unless an explicit token is set, and refuses paths outside a configured directory. The Python meeting does not gain a TRIBE call in this change.

### P2 — Hypothesis tree that branches, or a smaller log

**Why.** UCB1 over one node that never gains children is ceremony. Disproof-by-unverified-quote-count will punish quotation style.

**Scope.** `hypothesis_tree.py` call sites in the chat file only.

**Acceptance.** Either a turn can add one child from an explicit alternative sentence and `select()` can return it, with a test, or the meeting log stops printing `HYPOTHESIS PRUNED` / `HYPOTHESIS SELECTED`.

### P2 — State the Rust/Python split in the product boundary

**Why.** `docs/project/product-boundary.md` lists `rain`'s provider and gateway contracts as the stable core of the research-panel product. They are a second product. Contributors will keep wiring channels and hardware into the meeting story.

**Scope.** That doc only, plus the README architecture list if it drifts again.

**Acceptance.** The boundary doc says the default research meeting is the Python chat engine, and `rain` is an optional runtime that the meeting does not invoke. A cohesion test can lock one sentence.

## 5. Reproducibility and evaluation gaps

An outsider who wants to know whether a meeting was more than fluent generation should do the following. The repo does not currently let them.

1. **Freeze the corpus.** Hash every file the meeting was allowed to read. Today the artifact stores `loaded_papers` names and `library_path`, not hashes, and the default path includes README and other product docs.
2. **Freeze the decode.** Record model id, base URL, temperature, max tokens, and a seed if the server supports one. Chat defaults temperature to 0.7 and does not record it. RLM reads `RAIN_LLM_MODEL` / `LM_STUDIO_MODEL` and otherwise labels the run `minimax-m2.7:cloud` (`rain_lab_meeting.py`).
3. **Freeze the prompt.** Hash the soul plus the context block actually sent. Recursive intellect (`Config.recursive_intellect`, default on, depth 1) adds critique and rewrite calls, so the spoken turn is not the first completion.
4. **Check quotes against bytes.** For each `grounded_response.evidence[].quote`, require the span to occur in the hashed corpus file named by `source`. Reject five-word prefix matches. Reject matches whose source is outside the corpus directory.
5. **Separate controls.** Score a transcript that never saw the corpus (model only) and a transcript that saw the corpus. Report the difference in verified-span rate. Marker scores in `session_eval.py` do not do this.
6. **Do not count the demo or the README scene.** `DEMO_SESSION_*.md` is a template. The README phononic dialogue is authored.
7. **Do not count `verify_logic` SAT as an empirical result.** Store the formula and the model assignment. Satisfiable is not plausible.
8. **Do not count TRIBE segment means as region evidence.** There is no region in the payload.
9. **Human spot check.** `experiment_protocol` already requires human review for a next experiment. The meeting does not. A useful bar is: a person who has the corpus can confirm or reject every `SOURCE` / quoted span in under a few minutes because the artifact has file and span.

`python rain_lab.py --mode replay` is the intended entry (`session_replay.py`). It runs live chat and then the marker eval. It is not a substitute for steps 1–5. CI never runs it.

## 6. Architecture risks

**Two runtimes, one name.** The Python meeting speaks OpenAI chat completions to `RAIN_LLM_BASE_URL` or `http://127.0.0.1:11434/v1`. The Rust binary has its own provider registry (`src/providers/`), config (`config.example.toml` defaults include `minimax`), tools, and gateway. A behavior change in Rust providers does not change a R.A.I.N. Lab meeting. A behavior change in the 3,700-line chat file does not show up in `cargo test`. Reviews that treat the repo as one agent will miss the product path or drown in channel and hardware diffs.

**Sidecar trust.** Godot is supervised by the launcher (`SidecarSpec` in `james_library/launcher/rain_lab.py`) and is optional. TRIBE is a separate process with a different license, a GPU-sized weight download, and no shared security policy with `src/security`. The Rust tool checks `SecurityPolicy` for the tool operation, then forwards `input_value` as a path the sidecar opens. Policy on the Rust side does not constrain the sidecar's filesystem.

**Provider abstraction does not cross the boundary.** Python has no trait/factory for providers; it has one OpenAI client. Rust's provider traits are the extension point documented in `CLAUDE.md` and the README. Implementing `Provider` does not add a model to the meeting. The meeting's only knob is base URL plus model string.

**Prompt-injection surface on retrieved text.** `sanitize_text` strips a few control tokens and rewrites `###` and `[SEARCH:`. That is necessary and incomplete. Web snippets are appended into `full_context` and then into later system prompts. With web search on by default, a result page can instruct the next agent. Local papers get the same channel.

**Duplicated tool bodies.** `james_library/utilities/tools.py` (~1,600 lines) and large sections of `rain_lab_meeting.py` both implement library search, web search, and sanitization. `verify_logic` exists twice (Python and Rust). Drift is already visible: the Python function does not call the crate.

**License and binary size.** Pulling TRIBE into the default story drags a non-commercial research model and a scientific Python stack toward a runtime whose `Cargo.toml` is optimized for a small Rust binary. Keep the sidecar optional, which the config already does, and stop describing it as part of a normal meeting.

**Failure modes worth naming.** Chat exits before any transcript if the local server is down or no file passes the paper filter. RLM `sys.exit`s if `rlm` cannot be imported. First-turn overrides hide model failure behind a canned opener. Timeouts become `"[Timeout waiting for model response.]"` and can still be logged. Recovery can fire on legitimate repeated technical wording because detectors are textual. Hypothesis pruning can fire on quote punctuation. None of these write a structured error artifact the eval harness treats as a failed run; several write a normal-looking meeting.

## 7. What not to build next

- More panelists. `create_extended_team` (Alex, Sarah, Diana) adds voices without a grounding check.
- Another visual client, Godot scene, or share-card variant. The launcher already spends more code on posters and HTML share cards than on citation matching.
- Graph-R1, a new memory backend, or a vector database for the meeting. The compiler already has hashed embeddings and a contradiction pass that pairs negated sentences by subject (`library_compiler.py`). Use that output in the artifact before adding a graph product.
- Wiring TRIBE, hardware, or messaging channels into the default meeting. The product boundary already says they are not required. The README comparison table still sells TRIBE as an in-meeting capability.
- A hosted demo that replays authored dialogue. `rainlabteam.vercel.app` is a distribution choice. It does not answer whether a local meeting is grounded.
- Expanding `logic_prover` to modal or probabilistic logic. The current gap is that the meeting does not call the solver it already has, and propositional SAT is the wrong witness for physical claims.
- More SOUL prose. The four files are already the product's personality layer. Schema tests exist. Behavior tests do not.
- Rust provider or channel work framed as a R.A.I.N. Lab research improvement. That work belongs to the `rain` runtime. It does not change `rain_lab_meeting_chat_version.py`.

## Doc corrections in this change

Factual path and naming fixes only:

- `README.md` developer map: meeting code is the Python chat/RLM scripts and `james_library/`; `src/` is the `rain` binary; `crates/` are satellite crates; `python/` is `R.A.I.N.-tools`.
- `README.md` Luca row: "Field Topographer" → "Field Tomographer", matching `LUCA_SOUL.md` and the link line in the same file.
- Acknowledgments in `README.md`, `README.zh-CN.md`, `README.ja.md`, `README.ru.md`, `README.fr.md`, `README.vi.md`: the ZeroClaw-derived runtime is `src/`, not `crates/`.

Left in place on purpose: the README comparison-table claims about in-meeting TRIBE and "no cloud calls." Those are product claims, not broken paths. They are disputed in section 3. `docs/project/product-boundary.md` still lists the Rust runtime as stable core; section 4 P2 is the proposed edit, not done here, because it changes the product contract rather than a wrong directory.
