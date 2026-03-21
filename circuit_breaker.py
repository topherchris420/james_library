"""Circuit Breaker: formal logic intervention for stagnated debates.

When the StagnationMonitor detects agents looping, this module:
1. Extracts the contested hypothesis from the HypothesisTree.
2. Parses the core argument into a boolean logical formula.
3. Invokes the logic_prover WASM plugin via the Python/Rust bridge.
4. Returns a deterministic SYSTEM_OVERRIDE verdict to break the deadlock.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema expected by the logic_prover WASM plugin (DPLL SAT solver)
# ---------------------------------------------------------------------------
# Input JSON:
#   {
#     "variables": ["A", "B", "C"],
#     "clauses": [[1, -2], [3], [-1, 2, 3]],
#     "metadata": {"source_node": 0, "hypothesis": "..."}
#   }
#
# Each clause is a disjunction of signed variable indices (1-based).
# Positive = variable true, negative = variable negated.
# The solver checks satisfiability of the conjunction of all clauses (CNF).
# ---------------------------------------------------------------------------

_LOGIC_PROVER_PLUGIN = "logic_prover"
_DEFAULT_PLUGIN_DIR = Path(__file__).parent / "plugins" / "logic_prover"
_WASM_BINARY = "logic_prover.wasm"

# Template for extracting propositional structure from natural language.
# Used when no LLM is available — a strict regex-based fallback.
_PROPOSITION_PATTERN = re.compile(
    r"(?:if|when|given)\s+(.+?)(?:,?\s*then\s+(.+?))?(?:\s+(?:and|AND)\s+(.+?))?(?:\s+(?:or|OR)\s+(.+?))?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LogicFormula:
    """CNF representation ready for the logic_prover."""

    variables: list[str]
    clauses: list[list[int]]
    source_text: str

    def to_prover_json(self, node_id: int | None = None, hypothesis: str = "") -> dict[str, Any]:
        """Serialize to the logic_prover input schema."""
        return {
            "variables": self.variables,
            "clauses": self.clauses,
            "metadata": {
                "source_node": node_id,
                "hypothesis": hypothesis,
                "source_text": self.source_text,
            },
        }


@dataclass(frozen=True)
class ProverResult:
    """Result from the logic_prover WASM invocation."""

    satisfiable: bool
    assignment: dict[str, bool]
    raw_output: str


@dataclass(frozen=True)
class CircuitBreakerVerdict:
    """Final verdict injected back into the meeting chat."""

    triggered: bool
    formula: LogicFormula | None
    prover_result: ProverResult | None
    override_message: str


# ---------------------------------------------------------------------------
# Step 1: Parse argument text into a boolean formula (CNF)
# ---------------------------------------------------------------------------

def parse_argument_to_formula(argument_text: str) -> LogicFormula:
    """Parse a natural-language argument into a CNF boolean formula.

    This uses a strict template approach:
    - Splits the argument on logical connectives (AND, OR, IF...THEN, NOT).
    - Assigns each atomic proposition a variable name (A, B, C, ...).
    - Builds CNF clauses from the detected structure.

    For complex arguments an LLM can be substituted by replacing this
    function, but the output schema (LogicFormula) stays the same.
    """
    text = argument_text.strip()
    if not text:
        raise ValueError("Cannot parse empty argument text")

    propositions = _extract_propositions(text)
    if not propositions:
        raise ValueError(f"Could not extract propositions from: {text!r}")

    variables = [f"P{i}" for i in range(1, len(propositions) + 1)]
    var_index = {v: i + 1 for i, v in enumerate(variables)}

    clauses = _build_cnf_clauses(text, propositions, var_index)

    return LogicFormula(
        variables=variables,
        clauses=clauses,
        source_text=text,
    )


def _extract_propositions(text: str) -> list[str]:
    """Split argument text into atomic propositions."""
    # Normalize connectives to split tokens.
    normalized = text
    for token in (" AND ", " and ", " & ", " && "):
        normalized = normalized.replace(token, " |SPLIT| ")
    for token in (" OR ", " or ", " | ", " || "):
        normalized = normalized.replace(token, " |SPLIT| ")
    for token in ("IF ", "if ", "WHEN ", "when ", "GIVEN ", "given "):
        normalized = normalized.replace(token, "")
    for token in (" THEN ", " then ", " => ", " -> "):
        normalized = normalized.replace(token, " |SPLIT| ")

    parts = [p.strip().rstrip(".,;") for p in normalized.split("|SPLIT|") if p.strip()]

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _build_cnf_clauses(
    text: str,
    propositions: list[str],
    var_index: dict[str, int],
) -> list[list[int]]:
    """Build CNF clauses reflecting the logical structure.

    Heuristic rules applied (order of precedence):
    - IF A THEN B  =>  (NOT A OR B)  =>  clause [-a, b]
    - A AND B      =>  two unit clauses [a], [b]
    - A OR B       =>  single clause [a, b]
    - Bare propositions => unit clause [a]

    Negation (NOT / not) on a proposition flips the literal sign.
    """
    text_lower = text.lower()
    variables = list(var_index.keys())
    clauses: list[list[int]] = []

    has_implication = any(tok in text_lower for tok in (" then ", " => ", " -> "))
    has_conjunction = any(tok in text_lower for tok in (" and ", " & ", " && "))
    has_disjunction = any(tok in text_lower for tok in (" or ", " | ", " || "))

    def _literal(idx: int, prop_text: str) -> int:
        """Return signed literal; negative if the proposition contains NOT."""
        if prop_text.lower().startswith("not ") or prop_text.lower().startswith("no "):
            return -idx
        return idx

    if has_implication and len(propositions) >= 2:
        # IF P1 THEN P2 [AND P3...] => (-P1 OR P2), unit clauses for extras
        antecedent_lit = _literal(var_index[variables[0]], propositions[0])
        consequent_lit = _literal(var_index[variables[1]], propositions[1])
        clauses.append([-antecedent_lit, consequent_lit])
        for i in range(2, len(propositions)):
            lit = _literal(var_index[variables[i]], propositions[i])
            clauses.append([lit])
    elif has_conjunction and not has_disjunction:
        # Pure conjunction: each proposition is a unit clause.
        for i, prop in enumerate(propositions):
            lit = _literal(var_index[variables[i]], prop)
            clauses.append([lit])
    elif has_disjunction and not has_conjunction:
        # Pure disjunction: single clause with all propositions.
        clause = []
        for i, prop in enumerate(propositions):
            clause.append(_literal(var_index[variables[i]], prop))
        clauses.append(clause)
    elif has_conjunction and has_disjunction:
        # Mixed: (A AND B) OR C => clauses: [a, c], [b, c]
        # Distribute OR over AND (simple 2-part heuristic).
        and_parts: list[int] = []
        or_parts: list[int] = []
        in_or = False
        for i, prop in enumerate(propositions):
            lit = _literal(var_index[variables[i]], prop)
            if i > 0 and _connective_before(text, propositions, i) == "or":
                in_or = True
            if in_or:
                or_parts.append(lit)
            else:
                and_parts.append(lit)
        if or_parts:
            for a in and_parts:
                clauses.append([a] + or_parts)
        else:
            for i, prop in enumerate(propositions):
                clauses.append([_literal(var_index[variables[i]], prop)])
    else:
        # Fallback: treat each proposition as a unit clause.
        for i, prop in enumerate(propositions):
            lit = _literal(var_index[variables[i]], prop)
            clauses.append([lit])

    return clauses


def _connective_before(text: str, propositions: list[str], prop_idx: int) -> str:
    """Determine the connective between proposition prop_idx-1 and prop_idx."""
    if prop_idx < 1:
        return ""
    prev_end = text.lower().find(propositions[prop_idx - 1].lower())
    curr_start = text.lower().find(propositions[prop_idx].lower())
    if prev_end < 0 or curr_start < 0:
        return ""
    between = text[prev_end + len(propositions[prop_idx - 1]):curr_start].lower()
    if " or " in between or " | " in between:
        return "or"
    if " and " in between or " & " in between:
        return "and"
    return ""


# ---------------------------------------------------------------------------
# Step 2: Invoke logic_prover WASM via the Rust/Python bridge
# ---------------------------------------------------------------------------

def invoke_logic_prover(
    formula: LogicFormula,
    node_id: int | None = None,
    hypothesis: str = "",
    *,
    plugin_dir: Path | None = None,
    runtime_api_url: str | None = None,
) -> ProverResult:
    """Invoke the logic_prover WASM plugin and return the result.

    Tries two execution paths in order:
    1. HTTP call to the ZeroClaw runtime API (if runtime_api_url is set).
    2. Direct subprocess invocation via wasmtime/wasmi CLI.

    Both paths send the same JSON payload and expect the same response schema.
    """
    payload = formula.to_prover_json(node_id=node_id, hypothesis=hypothesis)
    payload_json = json.dumps(payload)

    # Path 1: Runtime API (mcp_server / Rust daemon)
    if runtime_api_url:
        result = _invoke_via_runtime_api(runtime_api_url, payload_json)
        if result is not None:
            return result

    # Path 2: Direct WASM invocation via CLI
    wasm_dir = plugin_dir or _DEFAULT_PLUGIN_DIR
    wasm_path = wasm_dir / _WASM_BINARY
    if wasm_path.exists():
        result = _invoke_via_cli(wasm_path, payload_json)
        if result is not None:
            return result

    # Both paths failed — return unsatisfiable as safe default.
    logger.warning("logic_prover: all invocation paths failed; defaulting to UNSAT")
    return ProverResult(
        satisfiable=False,
        assignment={},
        raw_output="logic_prover unavailable — treated as UNSAT (fail-safe)",
    )


def _invoke_via_runtime_api(api_url: str, payload_json: str) -> ProverResult | None:
    """Call the ZeroClaw runtime API to execute the WASM plugin."""
    try:
        import httpx
        url = api_url.rstrip("/") + "/v1/plugins/logic_prover/execute"
        resp = httpx.post(
            url,
            content=payload_json,
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        resp.raise_for_status()
        return _parse_prover_output(resp.text)
    except Exception as exc:
        logger.debug("Runtime API invocation failed: %s", exc)
        return None


def _invoke_via_cli(wasm_path: Path, payload_json: str) -> ProverResult | None:
    """Invoke the WASM binary directly via wasmtime CLI."""
    for runtime_cmd in ("wasmtime", "wasmer"):
        try:
            proc = subprocess.run(
                [runtime_cmd, "run", str(wasm_path), "--", "--input", "-"],
                input=payload_json,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return _parse_prover_output(proc.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _parse_prover_output(raw: str) -> ProverResult:
    """Parse the logic_prover JSON output into a ProverResult."""
    try:
        data = json.loads(raw.strip())
        satisfiable = data.get("satisfiable", False)
        assignment = data.get("assignment", {})
        return ProverResult(
            satisfiable=bool(satisfiable),
            assignment={str(k): bool(v) for k, v in assignment.items()},
            raw_output=raw.strip(),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        # Could not parse — treat raw text as-is.
        is_sat = "satisfiable" in raw.lower() and "unsatisfiable" not in raw.lower()
        return ProverResult(satisfiable=is_sat, assignment={}, raw_output=raw.strip())


# ---------------------------------------------------------------------------
# Step 3: Build the SYSTEM_OVERRIDE message
# ---------------------------------------------------------------------------

def format_override_message(
    node_id: int,
    hypothesis: str,
    formula: LogicFormula,
    result: ProverResult,
) -> str:
    """Format a deterministic SYSTEM_OVERRIDE intervention message."""
    sat_label = "SATISFIABLE (logically consistent)" if result.satisfiable else "UNSATISFIABLE (logically FALSE)"

    formula_repr = _formula_to_readable(formula)

    lines = [
        "SYSTEM_OVERRIDE — Circuit Breaker Intervention",
        "=" * 55,
        f"Contested hypothesis (node #{node_id}): {hypothesis}",
        "",
        f"Extracted logical formula: {formula_repr}",
        f"Formal evaluation result:  {sat_label}",
    ]

    if result.assignment:
        assign_str = ", ".join(f"{k}={v}" for k, v in sorted(result.assignment.items()))
        lines.append(f"Variable assignment:       {assign_str}")

    lines.append("")
    if not result.satisfiable:
        lines.append(
            "The logical formula representing the contested argument has been "
            "formally evaluated as FALSE. The debate must pivot — agents must "
            "abandon this line of reasoning and explore alternative hypotheses."
        )
    else:
        lines.append(
            "The logical formula is satisfiable. The argument is internally "
            "consistent but stagnation persists. Agents must introduce NEW "
            "evidence or branch to a sub-hypothesis to make progress."
        )

    return "\n".join(lines)


def _formula_to_readable(formula: LogicFormula) -> str:
    """Convert CNF clauses back to a human-readable string."""
    if not formula.clauses:
        return "(empty)"

    clause_strs = []
    for clause in formula.clauses:
        literals = []
        for lit in clause:
            idx = abs(lit) - 1
            var = formula.variables[idx] if 0 <= idx < len(formula.variables) else f"?{lit}"
            literals.append(f"NOT {var}" if lit < 0 else var)
        if len(literals) == 1:
            clause_strs.append(literals[0])
        else:
            clause_strs.append(f"({' OR '.join(literals)})")
    return " AND ".join(clause_strs)


# ---------------------------------------------------------------------------
# Unified entry point for the StagnationMonitor
# ---------------------------------------------------------------------------

def run_circuit_breaker(
    hypothesis_tree: Any,
    *,
    node_id: int | None = None,
    plugin_dir: Path | None = None,
    runtime_api_url: str | None = None,
) -> CircuitBreakerVerdict:
    """Execute the full circuit-breaker pipeline.

    Args:
        hypothesis_tree: A ``HypothesisTree`` instance with the current debate state.
        node_id: Specific node to evaluate. If None, uses the tree's UCB1 selection.
        plugin_dir: Override path to the logic_prover plugin directory.
        runtime_api_url: ZeroClaw runtime API URL for WASM execution.

    Returns:
        A ``CircuitBreakerVerdict`` with the override message for chat injection.
    """
    # Determine which node is contested.
    try:
        if node_id is None:
            node_id = hypothesis_tree.select()
        node = hypothesis_tree.get(node_id)
    except (ValueError, KeyError) as exc:
        return CircuitBreakerVerdict(
            triggered=False,
            formula=None,
            prover_result=None,
            override_message=f"Circuit breaker skipped: {exc}",
        )

    hypothesis_text = node.hypothesis

    # Step 1: Parse argument into formula.
    try:
        formula = parse_argument_to_formula(hypothesis_text)
    except ValueError as exc:
        return CircuitBreakerVerdict(
            triggered=False,
            formula=None,
            prover_result=None,
            override_message=f"Circuit breaker skipped — could not parse argument: {exc}",
        )

    # Step 2: Invoke the logic prover.
    prover_result = invoke_logic_prover(
        formula,
        node_id=node_id,
        hypothesis=hypothesis_text,
        plugin_dir=plugin_dir,
        runtime_api_url=runtime_api_url,
    )

    # Step 3: Format the override message.
    override_msg = format_override_message(node_id, hypothesis_text, formula, prover_result)

    return CircuitBreakerVerdict(
        triggered=True,
        formula=formula,
        prover_result=prover_result,
        override_message=override_msg,
    )
