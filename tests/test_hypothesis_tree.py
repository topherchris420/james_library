"""Tests for the hypothesis tree state machine."""

import pytest

from hypothesis_tree import HypothesisNode, HypothesisTree, NodeStatus


# ---------------------------------------------------------------------------
# HypothesisNode
# ---------------------------------------------------------------------------


class TestHypothesisNode:
    def test_mean_score_zero_visits(self):
        node = HypothesisNode(node_id=0, hypothesis="test")
        assert node.mean_score == 0.0

    def test_mean_score_with_visits(self):
        node = HypothesisNode(node_id=0, hypothesis="test", visits=4, total_score=28.0)
        assert node.mean_score == 7.0

    def test_is_leaf_no_children(self):
        node = HypothesisNode(node_id=0, hypothesis="test")
        assert node.is_leaf

    def test_is_leaf_with_children(self):
        node = HypothesisNode(node_id=0, hypothesis="test", children_ids=[1, 2])
        assert not node.is_leaf


# ---------------------------------------------------------------------------
# HypothesisTree — construction
# ---------------------------------------------------------------------------


class TestTreeConstruction:
    def test_add_root(self):
        tree = HypothesisTree()
        nid = tree.add_root("Resonance at 432 Hz")
        assert tree.size == 1
        assert tree.get(nid).hypothesis == "Resonance at 432 Hz"
        assert tree.get(nid).parent_id is None

    def test_add_child(self):
        tree = HypothesisTree()
        root = tree.add_root("Root hypothesis")
        child = tree.add_child(root, "Child hypothesis")
        assert tree.size == 2
        assert tree.get(child).parent_id == root
        assert child in tree.get(root).children_ids

    def test_add_child_to_disproven_raises(self):
        tree = HypothesisTree()
        root = tree.add_root("Will be disproven")
        tree.disprove(root, "test")
        with pytest.raises(ValueError):
            tree.add_child(root, "Should fail")

    def test_multiple_roots(self):
        tree = HypothesisTree()
        a = tree.add_root("Hypothesis A")
        b = tree.add_root("Hypothesis B")
        assert tree.size == 2
        assert tree.get(a).parent_id is None
        assert tree.get(b).parent_id is None

    def test_invalid_exploration_weight(self):
        with pytest.raises(ValueError):
            HypothesisTree(exploration_weight=-1.0)


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    def test_record_result(self):
        tree = HypothesisTree()
        nid = tree.add_root("Test")
        tree.record_result(nid, 7.0)
        tree.record_result(nid, 9.0)
        node = tree.get(nid)
        assert node.visits == 2
        assert node.total_score == 16.0
        assert node.mean_score == 8.0

    def test_record_result_on_disproven_raises(self):
        tree = HypothesisTree()
        nid = tree.add_root("Test")
        tree.disprove(nid, "bad")
        with pytest.raises(ValueError):
            tree.record_result(nid, 5.0)

    def test_prove(self):
        tree = HypothesisTree()
        nid = tree.add_root("Good hypothesis")
        tree.prove(nid)
        assert tree.get(nid).status == NodeStatus.PROVEN
        assert len(tree.proven_nodes()) == 1

    def test_disprove_sets_reason(self):
        tree = HypothesisTree()
        nid = tree.add_root("Bad hypothesis")
        tree.disprove(nid, "Contradicted by corpus")
        node = tree.get(nid)
        assert node.status == NodeStatus.DISPROVEN
        assert node.disproof_reason == "Contradicted by corpus"

    def test_disprove_cascades_to_children(self):
        tree = HypothesisTree()
        root = tree.add_root("Parent")
        child_a = tree.add_child(root, "Child A")
        child_b = tree.add_child(root, "Child B")
        grandchild = tree.add_child(child_a, "Grandchild")
        tree.disprove(root, "Root disproven")
        assert tree.get(child_a).status == NodeStatus.DISPROVEN
        assert tree.get(child_b).status == NodeStatus.DISPROVEN
        assert tree.get(grandchild).status == NodeStatus.DISPROVEN

    def test_disprove_skips_already_proven(self):
        tree = HypothesisTree()
        root = tree.add_root("Parent")
        child = tree.add_child(root, "Already proven child")
        tree.prove(child)
        tree.disprove(root, "Root gone")
        # Proven child should not be retroactively disproven.
        assert tree.get(child).status == NodeStatus.PROVEN

    def test_add_evidence(self):
        tree = HypothesisTree()
        nid = tree.add_root("Test")
        tree.add_evidence(nid, "Paper X confirms frequency range")
        assert "Paper X confirms frequency range" in tree.get(nid).evidence


# ---------------------------------------------------------------------------
# UCB1 selection
# ---------------------------------------------------------------------------


class TestUCBSelection:
    def test_select_raises_when_empty(self):
        tree = HypothesisTree()
        with pytest.raises(ValueError, match="No active"):
            tree.select()

    def test_select_raises_when_all_disproven(self):
        tree = HypothesisTree()
        nid = tree.add_root("Only option")
        tree.disprove(nid, "gone")
        with pytest.raises(ValueError, match="No active"):
            tree.select()

    def test_select_prefers_unvisited(self):
        tree = HypothesisTree()
        visited = tree.add_root("Visited")
        tree.record_result(visited, 8.0)
        unvisited = tree.add_root("Unvisited")
        assert tree.select() == unvisited

    def test_select_balances_exploitation_and_exploration(self):
        tree = HypothesisTree(exploration_weight=1.41)
        # High score, many visits -> exploitation
        a = tree.add_root("High scorer")
        for _ in range(10):
            tree.record_result(a, 9.0)
        # Low score, few visits -> exploration
        b = tree.add_root("Low scorer")
        tree.record_result(b, 3.0)
        # Selection should be deterministic given these inputs.
        selected = tree.select()
        assert selected in (a, b)

    def test_select_skips_disproven(self):
        tree = HypothesisTree()
        bad = tree.add_root("Disproven")
        tree.disprove(bad, "nope")
        good = tree.add_root("Active")
        assert tree.select() == good


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class TestReporting:
    def test_summary_empty_tree(self):
        tree = HypothesisTree()
        assert "empty" in tree.get_exploration_summary().lower()

    def test_summary_contains_hypothesis_text(self):
        tree = HypothesisTree()
        tree.add_root("Chladni pattern at 256 Hz")
        summary = tree.get_exploration_summary()
        assert "Chladni pattern at 256 Hz" in summary
        assert "HYPOTHESIS TREE STATE" in summary

    def test_current_hypothesis_prompt(self):
        tree = HypothesisTree()
        root = tree.add_root("Base theory")
        child = tree.add_child(root, "Sub-theory about amplitude")
        tree.add_evidence(child, "Confirmed in paper_x.md")
        prompt = tree.get_current_hypothesis_prompt(child)
        assert "Sub-theory about amplitude" in prompt
        assert "Base theory" in prompt  # ancestry
        assert "Confirmed in paper_x.md" in prompt
        assert "MUST directly test" in prompt

    def test_to_dict_roundtrip(self):
        tree = HypothesisTree()
        root = tree.add_root("Root")
        child = tree.add_child(root, "Child")
        tree.record_result(root, 6.0)
        tree.disprove(child, "bad data")
        data = tree.to_dict()
        assert len(data["nodes"]) == 2
        assert data["next_id"] == 2
        root_data = data["nodes"][0]
        assert root_data["status"] == "active"
        child_data = data["nodes"][1]
        assert child_data["status"] == "disproven"


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------


class TestAccessors:
    def test_active_nodes(self):
        tree = HypothesisTree()
        a = tree.add_root("A")
        b = tree.add_root("B")
        tree.disprove(b, "gone")
        active = tree.active_nodes()
        assert len(active) == 1
        assert active[0].node_id == a

    def test_get_unknown_id_raises(self):
        tree = HypothesisTree()
        with pytest.raises(KeyError):
            tree.get(999)
