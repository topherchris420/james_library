"""Tests for the circuit breaker integration with the stagnation monitor."""

import json

import pytest

from circuit_breaker import (
    CircuitBreakerVerdict,
    LogicFormula,
    ProverResult,
    _extract_propositions,
    _formula_to_readable,
    format_override_message,
    invoke_logic_prover,
    parse_argument_to_formula,
    run_circuit_breaker,
)
from hypothesis_tree import HypothesisTree
from stagnation_monitor import StagnationMonitor


# ---------------------------------------------------------------------------
# parse_argument_to_formula
# ---------------------------------------------------------------------------


class TestParseArgument:
    def test_simple_conjunction(self):
        formula = parse_argument_to_formula("resonance occurs AND plate is circular")
        assert len(formula.variables) == 2
        assert len(formula.clauses) == 2  # two unit clauses
        assert all(len(c) == 1 for c in formula.clauses)

    def test_simple_disjunction(self):
        formula = parse_argument_to_formula("frequency is 432 Hz OR frequency is 440 Hz")
        assert len(formula.variables) == 2
        assert len(formula.clauses) == 1  # single clause with two literals
        assert len(formula.clauses[0]) == 2

    def test_implication(self):
        formula = parse_argument_to_formula("if the plate is thin then resonance amplifies")
        assert len(formula.variables) == 2
        # IF A THEN B => [-A, B]
        assert len(formula.clauses) == 1
        clause = formula.clauses[0]
        assert clause[0] < 0  # negated antecedent
        assert clause[1] > 0  # positive consequent

    def test_negation_handling(self):
        formula = parse_argument_to_formula("not dampened AND resonance strong")
        assert len(formula.variables) == 2
        # First proposition starts with "not" so literal is negative.
        assert formula.clauses[0][0] < 0
        assert formula.clauses[1][0] > 0

    def test_mixed_and_or(self):
        formula = parse_argument_to_formula("plate is circular AND frequency matches OR medium is water")
        assert len(formula.variables) == 3
        # Distributed: (A AND B) OR C => [A,C], [B,C]
        assert len(formula.clauses) == 2

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_argument_to_formula("")

    def test_unparseable_falls_back_to_unit_clauses(self):
        # A single proposition with no connectives => one unit clause.
        formula = parse_argument_to_formula("resonance frequency is exactly 432 Hz")
        assert len(formula.variables) == 1
        assert len(formula.clauses) == 1

    def test_to_prover_json_schema(self):
        formula = parse_argument_to_formula("A and B")
        payload = formula.to_prover_json(node_id=42, hypothesis="test")
        assert "variables" in payload
        assert "clauses" in payload
        assert payload["metadata"]["source_node"] == 42
        # Ensure it's valid JSON.
        json.dumps(payload)


# ---------------------------------------------------------------------------
# _extract_propositions
# ---------------------------------------------------------------------------


class TestExtractPropositions:
    def test_and_split(self):
        props = _extract_propositions("X AND Y")
        assert len(props) == 2

    def test_or_split(self):
        props = _extract_propositions("X OR Y")
        assert len(props) == 2

    def test_deduplication(self):
        props = _extract_propositions("X AND X AND Y")
        # "X" appears twice but should be deduplicated.
        assert len(props) == 2

    def test_if_then(self):
        props = _extract_propositions("if rain then wet")
        assert len(props) == 2


# ---------------------------------------------------------------------------
# _formula_to_readable
# ---------------------------------------------------------------------------


class TestFormulaReadable:
    def test_unit_clauses(self):
        f = LogicFormula(variables=["P1", "P2"], clauses=[[1], [2]], source_text="")
        assert _formula_to_readable(f) == "P1 AND P2"

    def test_disjunction(self):
        f = LogicFormula(variables=["P1", "P2"], clauses=[[1, 2]], source_text="")
        assert _formula_to_readable(f) == "(P1 OR P2)"

    def test_negation(self):
        f = LogicFormula(variables=["P1", "P2"], clauses=[[-1, 2]], source_text="")
        assert _formula_to_readable(f) == "(NOT P1 OR P2)"

    def test_empty(self):
        f = LogicFormula(variables=[], clauses=[], source_text="")
        assert _formula_to_readable(f) == "(empty)"


# ---------------------------------------------------------------------------
# format_override_message
# ---------------------------------------------------------------------------


class TestFormatOverride:
    def test_unsat_message_contains_false(self):
        f = LogicFormula(variables=["P1"], clauses=[[1]], source_text="test")
        r = ProverResult(satisfiable=False, assignment={}, raw_output="")
        msg = format_override_message(0, "test hypothesis", f, r)
        assert "SYSTEM_OVERRIDE" in msg
        assert "FALSE" in msg
        assert "must pivot" in msg

    def test_sat_message_contains_consistent(self):
        f = LogicFormula(variables=["P1"], clauses=[[1]], source_text="test")
        r = ProverResult(satisfiable=True, assignment={"P1": True}, raw_output="")
        msg = format_override_message(0, "test hypothesis", f, r)
        assert "SYSTEM_OVERRIDE" in msg
        assert "satisfiable" in msg.lower()
        assert "P1=True" in msg


# ---------------------------------------------------------------------------
# invoke_logic_prover (offline / no WASM runtime available)
# ---------------------------------------------------------------------------


class TestInvokeLogicProver:
    def test_fallback_when_no_runtime(self, tmp_path):
        """When neither runtime API nor CLI is available, returns fail-safe UNSAT."""
        f = LogicFormula(variables=["P1"], clauses=[[1]], source_text="test")
        result = invoke_logic_prover(f, plugin_dir=tmp_path)
        assert not result.satisfiable
        assert "unavailable" in result.raw_output


# ---------------------------------------------------------------------------
# run_circuit_breaker (end-to-end with HypothesisTree)
# ---------------------------------------------------------------------------


class TestRunCircuitBreaker:
    def test_basic_circuit_breaker(self):
        tree = HypothesisTree()
        nid = tree.add_root("resonance occurs AND plate is circular")
        verdict = run_circuit_breaker(tree, node_id=nid)
        assert isinstance(verdict, CircuitBreakerVerdict)
        assert verdict.triggered
        assert verdict.formula is not None
        assert verdict.prover_result is not None
        assert "SYSTEM_OVERRIDE" in verdict.override_message

    def test_circuit_breaker_with_ucb1_selection(self):
        tree = HypothesisTree()
        tree.add_root("if frequency is high then amplitude drops")
        tree.add_root("plate geometry is irrelevant OR medium matters")
        verdict = run_circuit_breaker(tree)
        assert verdict.triggered
        assert "SYSTEM_OVERRIDE" in verdict.override_message

    def test_empty_tree_does_not_trigger(self):
        tree = HypothesisTree()
        verdict = run_circuit_breaker(tree)
        assert not verdict.triggered
        assert "skipped" in verdict.override_message.lower()

    def test_invalid_node_id_does_not_trigger(self):
        tree = HypothesisTree()
        tree.add_root("some hypothesis")
        verdict = run_circuit_breaker(tree, node_id=999)
        assert not verdict.triggered


# ---------------------------------------------------------------------------
# StagnationMonitor + Circuit Breaker integration
# ---------------------------------------------------------------------------


class TestStagnationMonitorCircuitBreaker:
    def test_circuit_breaker_fires_on_stagnation(self):
        tree = HypothesisTree()
        tree.add_root("resonance occurs AND plate is circular")

        monitor = StagnationMonitor(
            hypothesis_tree=tree,
            dead_end_window=2,
            dead_end_threshold=0.95,
            dead_end_consecutive=2,
        )
        same = "Exactly the same text every single turn."
        monitor.check(same)
        monitor.check(same)
        verdict = monitor.check(same)

        assert verdict.is_circuit_breaker
        assert "SYSTEM_OVERRIDE" in verdict.intervention_prompt

    def test_without_tree_falls_back_to_generic(self):
        monitor = StagnationMonitor(
            dead_end_window=2,
            dead_end_threshold=0.95,
            dead_end_consecutive=2,
        )
        same = "Exactly the same text every single turn."
        monitor.check(same)
        monitor.check(same)
        verdict = monitor.check(same)

        assert not verdict.is_circuit_breaker
        assert verdict.is_dead_end
        assert "Dead-end loop detected" in verdict.intervention_prompt

    def test_tree_can_be_attached_later(self):
        monitor = StagnationMonitor(
            dead_end_window=2,
            dead_end_threshold=0.95,
            dead_end_consecutive=2,
        )

        # First: no tree — generic intervention.
        same = "Exactly the same text every single turn."
        monitor.check(same)
        monitor.check(same)
        v1 = monitor.check(same)
        assert not v1.is_circuit_breaker

        monitor.reset()

        # Attach tree and retry.
        tree = HypothesisTree()
        tree.add_root("if dampening is low then resonance amplifies")
        monitor.hypothesis_tree = tree

        monitor.check(same)
        monitor.check(same)
        v2 = monitor.check(same)
        assert v2.is_circuit_breaker
        assert "SYSTEM_OVERRIDE" in v2.intervention_prompt

    def test_normal_conversation_unaffected(self):
        tree = HypothesisTree()
        tree.add_root("test hypothesis")

        monitor = StagnationMonitor(hypothesis_tree=tree)
        verdict = monitor.check("Fresh and original scientific discussion point.")
        assert not verdict.is_dead_end
        assert not verdict.is_stagnant
        assert not verdict.is_circuit_breaker
        assert verdict.intervention_prompt is None
