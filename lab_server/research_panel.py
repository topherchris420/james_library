from __future__ import annotations

import asyncio
import uuid
from typing import Any

from james_library.launcher.swarm_orchestrator import (
    AgentIdentity,
    AgentManifest,
    AgentMemoryRouting,
    AgentToolScope,
    SwarmConfig,
    run_blackboard_lab,
)
from rain_lab_runtime import (
    RuntimeState,
    extract_provenance,
    load_runtime_config,
    score_grounding_confidence,
    trace_runtime_state,
    validate_runtime_config,
)

_PANEL_TITLE = "Bell Labs-style panel"


def _research_panel_manifests() -> list[AgentManifest]:
    specs = [
        (
            "mechanism-hunter",
            "Mechanism Hunter",
            "Mechanistic modeler",
            (
                "Find the strongest causal explanation. Cite every strong claim "
                "as [from filename.md] or [from web: source]. Mark weak leaps "
                "as [HYPOTHESIS]."
            ),
        ),
        (
            "evidence-auditor",
            "Evidence Auditor",
            "Evidence skeptic",
            (
                "Separate what is actually supported from what is merely "
                "plausible. Demand citations and label gaps clearly."
            ),
        ),
        (
            "adjacent-scout",
            "Adjacent Scout",
            "Cross-disciplinary scout",
            "Bring in overlooked adjacent fields, analogies, and literature. Cite specific sources whenever possible.",
        ),
        (
            "experiment-designer",
            "Experiment Designer",
            "Experiment strategist",
            (
                "Turn the debate into concrete tests, measurements, or next "
                "readings. Cite evidence for why each next step matters."
            ),
        ),
    ]
    manifests: list[AgentManifest] = []
    for agent_id, display_name, role, system_prompt in specs:
        manifests.append(
            AgentManifest(
                schema_version="1.0",
                identity=AgentIdentity(
                    agent_id=agent_id,
                    display_name=display_name,
                    role=role,
                    system_prompt=system_prompt,
                ),
                tools=AgentToolScope(allowed=["web_search", "paper_search"]),
                memory=AgentMemoryRouting(categories=["research"]),
            )
        )
    return manifests


def _normalize_panel_note(note: dict[str, Any]) -> dict[str, Any]:
    content = str(note.get("notes", "")).strip()
    evidence = extract_provenance(content)
    return {
        "agent_name": str(note.get("agent_name", "")),
        "role": str(note.get("role", "")),
        "content": content,
        "evidence_sources": [item.source for item in evidence],
        "grounded": bool(evidence),
        "confidence": score_grounding_confidence(content, evidence),
    }


def _build_research_panel_trace_state(question: str) -> RuntimeState:
    state = RuntimeState(
        session_id=str(uuid.uuid4())[:8],
        query=question,
        mode="research_panel",
        agent=_PANEL_TITLE,
    )
    state.add_event("research_panel_started", {"question_chars": len(question)})
    return state


async def run_research_panel(question: str) -> dict[str, Any]:
    config = load_runtime_config()
    trace_state = _build_research_panel_trace_state(question)

    try:
        validate_runtime_config(config)
    except Exception as exc:
        trace_state.status = "error"
        trace_state.add_event("research_panel_failed", {"error": str(exc), "kind": "config"})
        trace_runtime_state(trace_state, config, error=str(exc))
        raise

    try:
        envelope = await run_blackboard_lab(
            query=question,
            manifests=_research_panel_manifests(),
            config=SwarmConfig(
                rounds=1,
                temperature=0.25,
                max_tokens_per_turn=420,
                max_context_tokens=6_000,
                model_name=config.llm_model,
                base_url=config.llm_base_url,
                api_key=config.llm_api_key or "not-needed",
                timeout=config.llm_timeout_s,
            ),
        )
    except asyncio.CancelledError:
        trace_state.status = "canceled"
        trace_state.add_event("research_panel_failed", {"error": "operation canceled", "kind": "canceled"})
        trace_runtime_state(trace_state, config, error="operation canceled")
        raise
    except Exception as exc:
        trace_state.status = "error"
        trace_state.add_event("research_panel_failed", {"error": str(exc), "kind": "runtime"})
        trace_runtime_state(trace_state, config, error=str(exc))
        raise

    panel = [_normalize_panel_note(note) for note in envelope["specialist_notes"]]
    synthesis = str(envelope["synthesized_response"]).strip()
    synthesis_evidence = extract_provenance(synthesis)

    result = {
        "question": question,
        "panel_title": _PANEL_TITLE,
        "panel": panel,
        "synthesis": synthesis,
        "synthesis_evidence_sources": [item.source for item in synthesis_evidence],
        "grounded": bool(synthesis_evidence),
        "confidence": score_grounding_confidence(synthesis, synthesis_evidence),
    }

    trace_state.status = "ok"
    trace_state.add_event(
        "research_panel_completed",
        {
            "panel_notes": len(panel),
            "synthesis_chars": len(synthesis),
            "grounded": result["grounded"],
        },
    )
    trace_runtime_state(
        trace_state,
        config,
        response={
            "answer": synthesis,
            "confidence": result["confidence"],
            "provenance": result["synthesis_evidence_sources"],
            "status": "ok",
            "mode": "research_panel",
            "agent": _PANEL_TITLE,
            "grounded": result["grounded"],
            "red_badge": not result["grounded"],
        },
        panel_count=len(panel),
    )

    return result
