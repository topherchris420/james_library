"""Hypothesis Tree State Machine for R.A.I.N. Lab meetings.

Upgrades linear chat-based reasoning to a branching, scientific state machine.
Each node represents a distinct hypothesis that agents explore via UCB1-based
selection.  Nodes can be marked as proven, disproven (pruned), or active.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeStatus(Enum):
    """Lifecycle status of a hypothesis node."""

    ACTIVE = "active"
    PROVEN = "proven"
    DISPROVEN = "disproven"


@dataclass
class HypothesisNode:
    """A single hypothesis in the exploration tree.

    Attributes:
        node_id:       Unique stable identifier (auto-assigned by the tree).
        hypothesis:    Plain-text description of this hypothesis.
        parent_id:     ID of the parent node, or ``None`` for root nodes.
        status:        Current lifecycle status.
        visits:        Number of times this node has been selected for exploration.
        total_score:   Cumulative peer-critique score received across visits.
        children_ids:  IDs of child hypotheses branching from this one.
        evidence:      Free-form notes collected during exploration.
        disproof_reason: Explanation when marked disproven.
    """

    node_id: int
    hypothesis: str
    parent_id: int | None = None
    status: NodeStatus = NodeStatus.ACTIVE
    visits: int = 0
    total_score: float = 0.0
    children_ids: list[int] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    disproof_reason: str = ""

    @property
    def mean_score(self) -> float:
        if self.visits == 0:
            return 0.0
        return self.total_score / self.visits

    @property
    def is_leaf(self) -> bool:
        return len(self.children_ids) == 0


# ---------------------------------------------------------------------------
# Tree structure
# ---------------------------------------------------------------------------

class HypothesisTree:
    """Branching hypothesis tree with UCB1-based exploration.

    Usage::

        tree = HypothesisTree()
        root = tree.add_root("Acoustic resonance at 432 Hz on steel plate")
        tree.add_child(root, "Resonance amplified by circular geometry")
        tree.add_child(root, "Resonance dampened by plate thickness > 2mm")

        node = tree.select()           # UCB1 selection
        tree.record_result(node, 7.0)  # peer-critique score
        tree.disprove(node, "Citations contradicted by local corpus")
    """

    def __init__(self, exploration_weight: float = 1.41) -> None:
        if exploration_weight < 0:
            raise ValueError("exploration_weight must be >= 0")
        self._nodes: dict[int, HypothesisNode] = {}
        self._next_id: int = 0
        self._exploration_weight = exploration_weight

    # -- Accessors ----------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self._nodes)

    def get(self, node_id: int) -> HypothesisNode:
        """Return a node by ID or raise KeyError."""
        return self._nodes[node_id]

    def active_nodes(self) -> list[HypothesisNode]:
        """Return all nodes with ACTIVE status."""
        return [n for n in self._nodes.values() if n.status == NodeStatus.ACTIVE]

    def proven_nodes(self) -> list[HypothesisNode]:
        return [n for n in self._nodes.values() if n.status == NodeStatus.PROVEN]

    def disproven_nodes(self) -> list[HypothesisNode]:
        return [n for n in self._nodes.values() if n.status == NodeStatus.DISPROVEN]

    # -- Mutations ----------------------------------------------------------

    def _alloc_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add_root(self, hypothesis: str) -> int:
        """Add a root-level hypothesis. Returns the node ID."""
        nid = self._alloc_id()
        self._nodes[nid] = HypothesisNode(node_id=nid, hypothesis=hypothesis.strip())
        return nid

    def add_child(self, parent_id: int, hypothesis: str) -> int:
        """Branch a new child hypothesis from an existing node. Returns the child ID."""
        parent = self._nodes[parent_id]
        if parent.status == NodeStatus.DISPROVEN:
            raise ValueError(f"Cannot branch from disproven node {parent_id}")
        nid = self._alloc_id()
        node = HypothesisNode(
            node_id=nid,
            hypothesis=hypothesis.strip(),
            parent_id=parent_id,
        )
        self._nodes[nid] = node
        parent.children_ids.append(nid)
        return nid

    def record_result(self, node_id: int, score: float) -> None:
        """Record a peer-critique score for a visit to this node."""
        node = self._nodes[node_id]
        if node.status == NodeStatus.DISPROVEN:
            raise ValueError(f"Cannot record results for disproven node {node_id}")
        node.visits += 1
        node.total_score += score

    def add_evidence(self, node_id: int, note: str) -> None:
        """Append an evidence note to a node."""
        self._nodes[node_id].evidence.append(note.strip())

    def prove(self, node_id: int) -> None:
        """Mark a hypothesis as proven (accepted by discovery gate)."""
        node = self._nodes[node_id]
        node.status = NodeStatus.PROVEN

    def disprove(self, node_id: int, reason: str) -> None:
        """Mark a hypothesis as disproven and recursively prune active children."""
        node = self._nodes[node_id]
        node.status = NodeStatus.DISPROVEN
        node.disproof_reason = reason.strip()
        for child_id in node.children_ids:
            child = self._nodes[child_id]
            if child.status == NodeStatus.ACTIVE:
                self.disprove(child_id, f"Parent hypothesis {node_id} disproven")

    # -- UCB1 selection -----------------------------------------------------

    def select(self) -> int:
        """Select the best active node to explore next using UCB1.

        Returns the node_id of the selected node.
        Raises ValueError if no active nodes exist.
        """
        candidates = self.active_nodes()
        if not candidates:
            raise ValueError("No active hypothesis nodes available for selection")

        total_visits = sum(n.visits for n in candidates)

        # Prefer unvisited nodes first (infinite UCB).
        unvisited = [n for n in candidates if n.visits == 0]
        if unvisited:
            # Among unvisited, prefer leaves (more specific hypotheses).
            leaves = [n for n in unvisited if n.is_leaf]
            pick = leaves[0] if leaves else unvisited[0]
            return pick.node_id

        # UCB1: exploitation + exploration
        c = self._exploration_weight
        log_total = math.log(total_visits)

        def ucb1(node: HypothesisNode) -> float:
            exploitation = node.mean_score / 10.0  # normalize to [0, 1]
            exploration = c * math.sqrt(log_total / node.visits)
            return exploitation + exploration

        best = max(candidates, key=ucb1)
        return best.node_id

    # -- Reporting ----------------------------------------------------------

    def get_exploration_summary(self) -> str:
        """Return a human-readable summary of the tree state."""
        if not self._nodes:
            return "Hypothesis tree is empty."

        lines = ["HYPOTHESIS TREE STATE:", "=" * 50]
        for node in self._nodes.values():
            indent = "  "
            if node.parent_id is not None:
                # Simple depth estimation
                depth = 0
                pid = node.parent_id
                while pid is not None and depth < 10:
                    depth += 1
                    pid = self._nodes[pid].parent_id if pid in self._nodes else None
                indent = "  " + "  " * depth

            status_icon = {
                NodeStatus.ACTIVE: "[ ]",
                NodeStatus.PROVEN: "[+]",
                NodeStatus.DISPROVEN: "[X]",
            }[node.status]

            score_str = f"avg={node.mean_score:.1f}" if node.visits > 0 else "unvisited"
            lines.append(
                f"{indent}{status_icon} #{node.node_id}: {node.hypothesis} "
                f"(visits={node.visits}, {score_str})"
            )
        return "\n".join(lines)

    def get_current_hypothesis_prompt(self, node_id: int) -> str:
        """Generate a meeting-injection prompt that frames discussion around a node."""
        node = self._nodes[node_id]
        ancestry = self._get_ancestry(node_id)

        parts = [
            "### CURRENT HYPOTHESIS UNDER TEST",
            f"Hypothesis #{node.node_id}: {node.hypothesis}",
        ]

        if ancestry:
            parts.append("\nDerivation chain:")
            for ancestor in ancestry:
                parts.append(f"  <- #{ancestor.node_id}: {ancestor.hypothesis}")

        if node.evidence:
            parts.append("\nPrior evidence collected:")
            for e in node.evidence[-3:]:  # last 3 to keep prompt short
                parts.append(f"  - {e}")

        parts.append(
            "\nALL discussion this iteration MUST directly test, support, or refute "
            "the hypothesis above. Cite evidence from the research corpus."
        )
        return "\n".join(parts)

    def _get_ancestry(self, node_id: int) -> list[HypothesisNode]:
        """Walk up the tree and return ancestors (nearest first), excluding self."""
        ancestors: list[HypothesisNode] = []
        pid = self._nodes[node_id].parent_id
        depth = 0
        while pid is not None and depth < 20:
            ancestors.append(self._nodes[pid])
            pid = self._nodes[pid].parent_id
            depth += 1
        return ancestors

    def to_dict(self) -> dict[str, Any]:
        """Serialize tree state for logging / persistence."""
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "hypothesis": n.hypothesis,
                    "parent_id": n.parent_id,
                    "status": n.status.value,
                    "visits": n.visits,
                    "total_score": n.total_score,
                    "children_ids": n.children_ids,
                    "evidence": n.evidence,
                    "disproof_reason": n.disproof_reason,
                }
                for n in self._nodes.values()
            ],
            "next_id": self._next_id,
        }
