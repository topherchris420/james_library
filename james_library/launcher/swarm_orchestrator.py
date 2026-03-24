"""Peer Review Swarm Simulation for R.A.I.N. Lab.

Spins up temporary adversarial reviewer agents to debate a research document,
then synthesizes their critiques into a structured Peer_Review_Report.md.

Fully async and isolated from the main R.A.I.N. Lab agent context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    tomllib = None


# ---------------------------------------------------------------------------
# 1. Reviewer Persona Generator
# ---------------------------------------------------------------------------

# Maps broad topic keywords to specialized reviewer archetypes.
_DOMAIN_PERSONAS: dict[str, list[dict[str, str]]] = {
    "physics": [
        {
            "role": "Skeptical Physicist",
            "focus": "conservation laws, dimensional analysis, thermodynamic limits",
            "attack": "demand numerical estimates and unit-checked derivations for every claim",
        },
        {
            "role": "Rigorous Mathematician",
            "focus": "proof structure, convergence, boundary conditions, analytic continuation",
            "attack": "reject hand-waving; require explicit axioms, lemmas, and QED closures",
        },
        {
            "role": "Experimentalist",
            "focus": "measurement methodology, error bars, reproducibility, control experiments",
            "attack": "challenge any prediction that lacks a concrete, falsifiable experimental protocol",
        },
        {
            "role": "Adversarial Statistician",
            "focus": "p-hacking, overfitting, sample size, Bayesian priors, multiple comparisons",
            "attack": "flag every statistical claim that lacks power analysis or confidence intervals",
        },
    ],
    "biology": [
        {
            "role": "Molecular Biologist",
            "focus": "pathway specificity, off-target effects, protein-protein interactions",
            "attack": "demand Western blots, knockouts, or CRISPR controls for mechanistic claims",
        },
        {
            "role": "Biostatistician",
            "focus": "sample sizes, multiple testing correction, effect sizes, replication",
            "attack": "reject any conclusion drawn from n < 3 or uncorrected p-values",
        },
        {
            "role": "Evolutionary Skeptic",
            "focus": "selection pressure, phylogenetic confounds, neutral drift",
            "attack": "challenge adaptationist narratives that lack phylogenetic comparative analysis",
        },
    ],
    "computer_science": [
        {
            "role": "Complexity Theorist",
            "focus": "asymptotic bounds, NP-hardness reductions, approximation ratios",
            "attack": "demand formal runtime proofs; reject empirical-only complexity claims",
        },
        {
            "role": "Systems Adversary",
            "focus": "concurrency bugs, cache coherence, failure modes, tail latency",
            "attack": "stress-test every architecture claim with adversarial workload scenarios",
        },
        {
            "role": "Formal Methods Purist",
            "focus": "invariants, pre/post-conditions, model checking, type safety",
            "attack": "reject correctness claims without formal specification or proof sketch",
        },
    ],
    "default": [
        {
            "role": "Methodological Skeptic",
            "focus": "internal validity, confounds, causal inference, logical fallacies",
            "attack": "systematically enumerate every hidden assumption and logical gap",
        },
        {
            "role": "Quantitative Auditor",
            "focus": "numerical accuracy, unit consistency, order-of-magnitude sanity checks",
            "attack": "verify every number; flag unsourced statistics and suspiciously round figures",
        },
        {
            "role": "Reproducibility Enforcer",
            "focus": "data availability, code sharing, protocol detail, independent replication",
            "attack": "reject any result that cannot be independently reproduced from the paper alone",
        },
        {
            "role": "Logical Rigorist",
            "focus": "deductive validity, modus ponens chains, hidden premises, circular reasoning",
            "attack": "map the full argument graph and flag every non-sequitur or unstated axiom",
        },
    ],
}

# Topic keywords mapped to domain keys.
_KEYWORD_DOMAIN_MAP: dict[str, str] = {
    "quantum": "physics",
    "resonance": "physics",
    "acoustic": "physics",
    "frequency": "physics",
    "wave": "physics",
    "thermodynamic": "physics",
    "gravity": "physics",
    "electro": "physics",
    "gene": "biology",
    "protein": "biology",
    "cell": "biology",
    "neural": "biology",
    "evolution": "biology",
    "algorithm": "computer_science",
    "complexity": "computer_science",
    "distributed": "computer_science",
    "compiler": "computer_science",
    "runtime": "computer_science",
    "machine learning": "computer_science",
}


def _detect_domain(topic: str) -> str:
    """Infer the primary domain from the paper topic string."""
    topic_lower = topic.lower()
    for keyword, domain in _KEYWORD_DOMAIN_MAP.items():
        if keyword in topic_lower:
            return domain
    return "default"


def generate_reviewer_personas(
    topic: str,
    count: int = 4,
) -> list[dict[str, str]]:
    """Build adversarial reviewer personas tailored to *topic*.

    Returns up to *count* persona dicts, each with keys:
      name, role, focus, attack, system_prompt
    """
    domain = _detect_domain(topic)
    pool = list(_DOMAIN_PERSONAS.get(domain, _DOMAIN_PERSONAS["default"]))

    # Always mix in at least one cross-domain skeptic when the pool is domain-specific.
    if domain != "default":
        pool.append(_DOMAIN_PERSONAS["default"][0])  # Methodological Skeptic

    selected = pool[:count]
    # Guarantee the cross-domain skeptic is included if we added one.
    if domain != "default" and len(pool) > count and pool[-1] not in selected:
        selected[-1] = pool[-1]

    personas: list[dict[str, str]] = []
    for idx, spec in enumerate(selected):
        name = f"Reviewer_{chr(65 + idx)}"  # Reviewer_A, Reviewer_B, ...
        system_prompt = _build_reviewer_system_prompt(name, spec, topic)
        personas.append(
            {
                "name": name,
                "role": spec["role"],
                "focus": spec["focus"],
                "attack": spec["attack"],
                "system_prompt": system_prompt,
            }
        )
    return personas


def _build_reviewer_system_prompt(name: str, spec: dict[str, str], topic: str) -> str:
    return f"""# IDENTITY
You are {name}, a {spec['role']}.

# MANDATE
You have been summoned to a blind adversarial peer review of a research document
on the topic: "{topic}".

Your sole purpose is to find flaws. You are NOT here to praise the work.

# DOMAIN FOCUS
{spec['focus']}

# ATTACK VECTOR
{spec['attack']}

# ANTI-SYCOPHANCY RULES (MANDATORY)
- NEVER start with praise or compliments.
- NEVER use phrases like "interesting work", "great effort", "well-written".
- Lead EVERY response with the most critical flaw you have identified.
- If another reviewer's critique is weak or wrong, say so directly.
- Assign a severity to each flaw: [CRITICAL], [MAJOR], [MINOR].
- If you find NO flaws, state "NO FLAWS FOUND" (this should be extremely rare).

# RESPONSE FORMAT
Each response must follow this structure:
1. FLAWS IDENTIFIED (numbered, with severity tags)
2. RESPONSE TO OTHER REVIEWERS (agree/disagree with specific critiques)
3. REMAINING CONCERNS (unresolved issues from prior rounds)

Keep responses focused and under 200 words per turn."""


# ---------------------------------------------------------------------------
# 2. Swarm Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class SwarmConfig:
    """Tunable parameters for a peer-review swarm session."""

    rounds: int = 6
    max_tokens_per_turn: int = 512
    temperature: float = 0.4
    model_name: str = ""
    base_url: str = ""
    api_key: str = "not-needed"
    timeout: float = 120.0


@dataclass
class SwarmTranscript:
    """Immutable record of one completed swarm debate."""

    session_id: str
    topic: str
    document_hash: str
    personas: list[dict[str, str]]
    turns: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    total_duration_s: float = 0.0


@dataclass
class AgentToolScope:
    """Manifest-defined tool access scopes for one specialist."""

    allowed: list[str] = field(default_factory=list)


@dataclass
class AgentMemoryRouting:
    """Manifest-defined memory and RAG routing hints."""

    categories: list[str] = field(default_factory=list)
    session_id: str | None = None


@dataclass
class AgentIdentity:
    """Strict agent identity contract sourced from manifest."""

    agent_id: str
    display_name: str
    role: str
    system_prompt: str


@dataclass
class AgentManifest:
    """Schema-first manifest replacing loose *_SOUL.md files."""

    schema_version: str
    identity: AgentIdentity
    tools: AgentToolScope = field(default_factory=AgentToolScope)
    memory: AgentMemoryRouting = field(default_factory=AgentMemoryRouting)


def load_agent_manifest(manifest_path: str | Path) -> AgentManifest:
    """Load a strict TOML agent manifest from disk."""
    path = Path(manifest_path)
    if tomllib is None:
        raise RuntimeError("tomllib unavailable; Python 3.11+ required for TOML manifests")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    identity = raw.get("identity", {})
    return AgentManifest(
        schema_version=str(raw.get("schema_version", "")),
        identity=AgentIdentity(
            agent_id=str(identity.get("id", "")),
            display_name=str(identity.get("display_name", "")),
            role=str(identity.get("role", "")),
            system_prompt=str(identity.get("system_prompt", "")),
        ),
        tools=AgentToolScope(allowed=list(raw.get("tools", {}).get("allowed", []))),
        memory=AgentMemoryRouting(
            categories=list(raw.get("memory", {}).get("categories", [])),
            session_id=raw.get("memory", {}).get("session_id"),
        ),
    )


async def run_blackboard_lab(
    query: str,
    manifests: list[AgentManifest],
    config: SwarmConfig | None = None,
) -> dict[str, Any]:
    """Prototype blackboard orchestrator for multi-specialist collaboration.

    Each specialist receives the same shared room context plus a role-specific
    sub-task. The output is synthesized into a single response envelope.
    """
    cfg = config or SwarmConfig(rounds=1, temperature=0.3, max_tokens_per_turn=384)
    model = cfg.model_name or os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    base_url = cfg.base_url or os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    api_key = cfg.api_key or os.environ.get("LM_STUDIO_API_KEY", "not-needed")

    try:
        import openai as _openai
    except ImportError as exc:
        raise RuntimeError("openai package required for lab orchestration: pip install openai") from exc

    try:
        import httpx
        timeout = httpx.Timeout(min(15.0, cfg.timeout), read=cfg.timeout, write=15.0, connect=15.0)
        client = _openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    except ImportError:
        client = _openai.OpenAI(base_url=base_url, api_key=api_key)

    room_context = (
        "You are operating in a shared lab blackboard. "
        "Read peer notes and contribute only your specialist perspective."
    )
    per_agent_notes: list[dict[str, str]] = []

    for manifest in manifests:
        memory_hint = ", ".join(manifest.memory.categories) if manifest.memory.categories else "default"
        tool_hint = ", ".join(manifest.tools.allowed) if manifest.tools.allowed else "none"
        user_message = (
            f"{room_context}\n\n"
            f"User query: {query}\n"
            f"Your role: {manifest.identity.role}\n"
            f"Allowed tools: {tool_hint}\n"
            f"Memory routes: {memory_hint}\n\n"
            f"Provide findings, assumptions, and one recommended next step."
        )
        response = await _call_llm_async(
            client=client,
            model=model,
            system_prompt=manifest.identity.system_prompt,
            user_message=user_message,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens_per_turn,
        )
        per_agent_notes.append(
            {
                "agent_id": manifest.identity.agent_id,
                "agent_name": manifest.identity.display_name,
                "role": manifest.identity.role,
                "notes": response,
            }
        )

    synthesis_prompt = (
        "You are the lab chair. Synthesize specialist notes into one integrated answer.\n\n"
        f"User query: {query}\n\n"
        f"Specialist notes:\n{json.dumps(per_agent_notes, ensure_ascii=False, indent=2)}"
    )
    synthesis = await _call_llm_async(
        client=client,
        model=model,
        system_prompt="Synthesize into a concise multi-perspective answer with clear action items.",
        user_message=synthesis_prompt,
        temperature=0.2,
        max_tokens=768,
    )

    return {"query": query, "specialist_notes": per_agent_notes, "synthesized_response": synthesis}


async def _call_llm_async(
    client: Any,
    model: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Non-blocking LLM call via asyncio executor (openai client is sync)."""
    loop = asyncio.get_running_loop()

    def _sync_call() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    return await loop.run_in_executor(None, _sync_call)


async def run_swarm(
    document: str,
    topic: str,
    config: SwarmConfig | None = None,
) -> SwarmTranscript:
    """Run an isolated adversarial peer-review swarm.

    Args:
        document: The full markdown text of the paper to review.
        topic: Short description of the paper's subject area.
        config: Optional tuning knobs. Defaults are sane for local LM Studio.

    Returns:
        A SwarmTranscript containing the full debate record.
    """
    cfg = config or SwarmConfig()

    # Resolve model/endpoint from env if not provided.
    model = cfg.model_name or os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    base_url = cfg.base_url or os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    api_key = cfg.api_key or os.environ.get("LM_STUDIO_API_KEY", "not-needed")

    # Lazy import so the module can be loaded without openai installed.
    try:
        import openai as _openai
    except ImportError as exc:
        raise RuntimeError("openai package required for swarm orchestration: pip install openai") from exc

    try:
        import httpx
        timeout = httpx.Timeout(min(15.0, cfg.timeout), read=cfg.timeout, write=15.0, connect=15.0)
        client = _openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    except ImportError:
        client = _openai.OpenAI(base_url=base_url, api_key=api_key)

    # Generate adversarial personas.
    personas = generate_reviewer_personas(topic, count=4)

    session_id = f"swarm_{uuid.uuid4().hex[:12]}"
    doc_hash = f"{len(document)}_{hash(document) & 0xFFFFFFFF:08x}"
    t_start = time.monotonic()

    transcript = SwarmTranscript(
        session_id=session_id,
        topic=topic,
        document_hash=doc_hash,
        personas=[{k: v for k, v in p.items() if k != "system_prompt"} for p in personas],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    # Truncate document to avoid context overflow on small models.
    max_doc_chars = 12_000
    doc_excerpt = document[:max_doc_chars]
    if len(document) > max_doc_chars:
        doc_excerpt += "\n\n[... DOCUMENT TRUNCATED FOR REVIEW ...]"

    # Build the shared document context (injected once per turn).
    doc_context = (
        f"# DOCUMENT UNDER REVIEW\n"
        f"Topic: {topic}\n\n"
        f"{doc_excerpt}"
    )

    debate_log: list[str] = []

    for round_num in range(1, cfg.rounds + 1):
        for persona in personas:
            # Build the per-turn user message with debate history.
            recent_debate = "\n".join(debate_log[-16:]) if debate_log else "[No prior discussion]"

            user_msg = (
                f"{doc_context}\n\n"
                f"# DEBATE TRANSCRIPT (Round {round_num}/{cfg.rounds})\n"
                f"{recent_debate}\n\n"
                f"# YOUR TURN\n"
                f"Provide your critique for this round. "
                f"Address other reviewers' points where relevant."
            )

            try:
                response_text = await _call_llm_async(
                    client=client,
                    model=model,
                    system_prompt=persona["system_prompt"],
                    user_message=user_msg,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens_per_turn,
                )
            except Exception as e:
                response_text = f"[ERROR: {type(e).__name__}: {e}]"
                logger.warning("Swarm LLM call failed for %s: %s", persona["name"], e)

            turn_record = {
                "round": round_num,
                "reviewer": persona["name"],
                "role": persona["role"],
                "content": response_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            transcript.turns.append(turn_record)
            debate_log.append(f"[{persona['name']} ({persona['role']})] {response_text}")

    t_end = time.monotonic()
    transcript.finished_at = datetime.now(timezone.utc).isoformat()
    transcript.total_duration_s = round(t_end - t_start, 2)

    return transcript


# ---------------------------------------------------------------------------
# 3. Synthesizer - compress debate into structured report
# ---------------------------------------------------------------------------

_SYNTHESIZER_SYSTEM_PROMPT = """You are the Peer Review Synthesizer.

You receive the raw transcript of an adversarial multi-reviewer debate about a
research document. Your job is to compress it into a clear, actionable report.

# OUTPUT FORMAT (Markdown, use these exact headings)

## Executive Summary
One paragraph: overall assessment and confidence level.

## Critical Flaws
Numbered list. Each item: description, which reviewer(s) raised it, severity.

## Mathematical / Logical Errors
Numbered list of specific errors with page/section references where possible.

## Methodological Concerns
Issues with experimental design, statistical analysis, or reproducibility.

## Points of Reviewer Consensus
Critiques that multiple reviewers independently agreed on (strongest signal).

## Points of Reviewer Disagreement
Where reviewers contradicted each other (requires author judgment).

## Suggested Revisions
Prioritized action items for the author, ordered by severity.

## Reviewer Confidence Scores
For each reviewer, estimate how confident/substantiated their critiques were (1-5).

# RULES
- Be ruthlessly concise. No filler.
- Preserve severity tags: [CRITICAL], [MAJOR], [MINOR].
- If reviewers raised the same flaw independently, flag it as HIGH CONFIDENCE.
- Do NOT add new critiques. Only synthesize what reviewers actually said."""


async def synthesize_report(
    transcript: SwarmTranscript,
    config: SwarmConfig | None = None,
) -> str:
    """Compress a swarm transcript into a structured Peer_Review_Report.

    Returns the report as a markdown string.
    """
    cfg = config or SwarmConfig()
    model = cfg.model_name or os.environ.get("LM_STUDIO_MODEL", "qwen2.5-coder-7b-instruct")
    base_url = cfg.base_url or os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
    api_key = cfg.api_key or os.environ.get("LM_STUDIO_API_KEY", "not-needed")

    try:
        import openai as _openai
    except ImportError as exc:
        raise RuntimeError("openai package required: pip install openai") from exc

    try:
        import httpx
        timeout = httpx.Timeout(15.0, read=cfg.timeout, write=15.0, connect=15.0)
        client = _openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    except ImportError:
        client = _openai.OpenAI(base_url=base_url, api_key=api_key)

    # Build a condensed version of the debate for the synthesizer.
    debate_lines: list[str] = []
    for turn in transcript.turns:
        debate_lines.append(
            f"### [{turn['reviewer']} - {turn['role']}] (Round {turn['round']})\n"
            f"{turn['content']}\n"
        )
    debate_text = "\n".join(debate_lines)

    # Truncate if the debate is very long.
    max_debate_chars = 20_000
    if len(debate_text) > max_debate_chars:
        debate_text = debate_text[:max_debate_chars] + "\n\n[... DEBATE TRUNCATED ...]"

    user_msg = (
        f"# PEER REVIEW SWARM TRANSCRIPT\n"
        f"Topic: {transcript.topic}\n"
        f"Session: {transcript.session_id}\n"
        f"Reviewers: {len(transcript.personas)}\n"
        f"Rounds: {transcript.turns[-1]['round'] if transcript.turns else 0}\n"
        f"Duration: {transcript.total_duration_s}s\n\n"
        f"{debate_text}\n\n"
        f"# TASK\n"
        f"Synthesize the above debate into the required report format."
    )

    loop = asyncio.get_running_loop()

    def _sync_call() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYNTHESIZER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        return response.choices[0].message.content.strip()

    report = await loop.run_in_executor(None, _sync_call)

    # Prepend metadata header.
    header = (
        f"# Peer Review Report\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| Session | `{transcript.session_id}` |\n"
        f"| Topic | {transcript.topic} |\n"
        f"| Reviewers | {', '.join(p['name'] + ' (' + p['role'] + ')' for p in transcript.personas)} |\n"
        f"| Rounds | {transcript.turns[-1]['round'] if transcript.turns else 0} |\n"
        f"| Duration | {transcript.total_duration_s}s |\n"
        f"| Generated | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} |\n\n"
        f"---\n\n"
    )

    return header + report


# ---------------------------------------------------------------------------
# 4. invoke_peer_review - tool-callable entry point
# ---------------------------------------------------------------------------

async def invoke_peer_review(
    document: str,
    topic: str,
    rounds: int = 6,
    output_path: str | None = None,
    model_name: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Callable tool for main R.A.I.N. Lab agents (James, Luca, etc.).

    Runs a full peer-review swarm in isolation and returns the synthesized
    report. The main agent's context is NOT polluted by the raw debate.

    Args:
        document: Full markdown text of the paper to review.
        topic: Short topic description for persona generation.
        rounds: Number of debate rounds (default 6).
        output_path: Optional path to write Peer_Review_Report.md.
        model_name: LLM model override (default: env / qwen2.5-coder-7b-instruct).
        base_url: LLM endpoint override (default: env / localhost:1234).

    Returns:
        Dict with keys: report (str), transcript_summary (dict), output_file (str|None).
    """
    cfg = SwarmConfig(
        rounds=max(3, min(rounds, 12)),  # Clamp to sane range.
        model_name=model_name,
        base_url=base_url,
    )

    # Phase 1: Run the adversarial debate.
    transcript = await run_swarm(document=document, topic=topic, config=cfg)

    # Phase 2: Synthesize the report.
    report = await synthesize_report(transcript, config=cfg)

    # Phase 3: Optionally persist to disk.
    output_file = None
    if output_path:
        out = Path(output_path)
    else:
        archive_dir = Path(os.environ.get("JAMES_LIBRARY_PATH", ".")) / "meeting_archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        out = archive_dir / f"Peer_Review_Report_{transcript.session_id}.md"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    output_file = str(out)
    logger.info("Peer review report written to %s", output_file)

    # Also persist the raw transcript as JSONL for auditability.
    transcript_path = out.parent / (out.stem + ".transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as f:
        for turn in transcript.turns:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    return {
        "report": report,
        "transcript_summary": {
            "session_id": transcript.session_id,
            "topic": transcript.topic,
            "reviewers": len(transcript.personas),
            "rounds": cfg.rounds,
            "total_turns": len(transcript.turns),
            "duration_s": transcript.total_duration_s,
        },
        "output_file": output_file,
    }


def invoke_peer_review_sync(
    document: str,
    topic: str,
    rounds: int = 6,
    output_path: str | None = None,
    model_name: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Synchronous wrapper for invoke_peer_review.

    Use this from non-async contexts (e.g., the RLM tool injection layer).
    Creates a new event loop if none is running.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = invoke_peer_review(
        document=document,
        topic=topic,
        rounds=rounds,
        output_path=output_path,
        model_name=model_name,
        base_url=base_url,
    )

    if loop and loop.is_running():
        # We're inside an existing event loop (e.g., Jupyter, async framework).
        # Schedule as a task and block via threading to avoid deadlock.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
