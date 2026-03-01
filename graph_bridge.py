"""Bridge module for a local Knowledge Hypergraph engine.

This module exposes ``HypergraphManager`` with two backend modes:

1. Native mode (default): uses ``networkx`` + ``scikit-learn`` TF-IDF analysis.
2. Placeholder mode: reserved for a future Graph-R1 backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class GraphBuildStats:
    """Simple metadata about the currently built graph."""

    documents: int = 0
    keywords: int = 0
    edges: int = 0


class HypergraphManager:
    """Knowledge hypergraph manager with pluggable backend modes.

    Parameters
    ----------
    library_path:
        Folder that contains markdown files used for graph construction.
    max_keywords:
        Upper bound on keyword nodes in native mode.
    """

    def __init__(self, library_path: str, max_keywords: int = 250) -> None:
        self.library_path = Path(library_path)
        self.max_keywords = max_keywords
        self.graph = nx.Graph()
        self.mode = self._detect_mode()
        self.stats = GraphBuildStats()

    def _detect_mode(self) -> str:
        """Detect backend mode.

        Graph-R1 detection is intentionally lightweight and does not yet enable full usage.
        """
        try:
            import graph_r1  # noqa: F401

            return "graph-r1"
        except ImportError:
            return "native"

    def build(self) -> None:
        """Build/rebuild the hypergraph using the selected backend."""
        if self.mode == "graph-r1":
            self._build_graph_r1_placeholder()
        else:
            self._build_native_graph()

    def _read_documents(self) -> List[Tuple[str, str]]:
        files = sorted(self.library_path.glob("*.md"))
        docs: List[Tuple[str, str]] = []

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                content = file_path.read_text(encoding="latin-1").strip()
            if content:
                docs.append((file_path.name, content))

        return docs

    def _build_native_graph(self) -> None:
        docs = self._read_documents()
        self.graph.clear()

        if not docs:
            self.stats = GraphBuildStats()
            return

        doc_names = [name for name, _ in docs]
        texts = [text for _, text in docs]

        vectorizer = TfidfVectorizer(
            stop_words="english",
            lowercase=True,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b",
        )
        matrix = vectorizer.fit_transform(texts)
        terms = np.array(vectorizer.get_feature_names_out())

        presence = matrix.copy()
        presence.data = np.ones_like(presence.data)
        doc_freq = np.asarray(presence.sum(axis=0)).ravel().astype(int)
        idf = vectorizer.idf_

        candidate_indices = np.where(doc_freq >= 2)[0]
        if candidate_indices.size == 0:
            self.stats = GraphBuildStats(documents=len(doc_names), keywords=0, edges=0)
            for doc_name in doc_names:
                self.graph.add_node(doc_name, node_type="document")
            return

        max_df_allowed = max(2, int(np.ceil(len(doc_names) * 0.4)))
        rare_indices = np.array([idx for idx in candidate_indices if doc_freq[idx] <= max_df_allowed])
        if rare_indices.size == 0:
            rare_indices = candidate_indices

        ranked_indices = sorted(
            rare_indices.tolist(),
            key=lambda idx: (-idf[idx], doc_freq[idx], terms[idx]),
        )
        selected_indices = ranked_indices[: self.max_keywords]
        selected_terms = terms[selected_indices]

        for doc_name in doc_names:
            self.graph.add_node(doc_name, node_type="document")

        keyword_nodes = [f"kw::{term}" for term in selected_terms]
        for keyword_node, term in zip(keyword_nodes, selected_terms):
            self.graph.add_node(keyword_node, node_type="keyword", keyword=term)

        for row_idx, doc_name in enumerate(doc_names):
            row = matrix.getrow(row_idx)
            present_term_indices = row.indices
            for term_idx in present_term_indices:
                if term_idx in selected_indices:
                    term = terms[term_idx]
                    keyword_node = f"kw::{term}"
                    weight = float(row[0, term_idx])
                    self.graph.add_edge(doc_name, keyword_node, weight=weight)

        self.stats = GraphBuildStats(
            documents=len(doc_names),
            keywords=len(keyword_nodes),
            edges=self.graph.number_of_edges(),
        )

    def _build_graph_r1_placeholder(self) -> None:
        """Placeholder hook for future Graph-R1 integration.

        For now, this intentionally falls back to native behavior so functionality
        remains complete when Graph-R1 is unavailable or not yet integrated.
        """
        self._build_native_graph()

    def query(self, topic: str, max_links: int = 5) -> str:
        """Query the graph for hidden connections around a topic keyword."""
        if self.mode == "graph-r1":
            return self._query_graph_r1_placeholder(topic=topic, max_links=max_links)
        return self._query_native(topic=topic, max_links=max_links)

    def _resolve_keyword_node(self, topic: str) -> Optional[str]:
        normalized = topic.strip().lower()
        if not normalized:
            return None

        exact_node = f"kw::{normalized}"
        if exact_node in self.graph:
            return exact_node

        keyword_nodes = [n for n, attrs in self.graph.nodes(data=True) if attrs.get("node_type") == "keyword"]
        contains_match = [n for n in keyword_nodes if normalized in n]
        if contains_match:
            return sorted(contains_match, key=len)[0]

        return None

    def _query_native(self, topic: str, max_links: int = 5) -> str:
        if self.graph.number_of_nodes() == 0:
            return "Knowledge hypergraph is empty. Build the graph before querying."

        keyword_node = self._resolve_keyword_node(topic)
        if not keyword_node:
            return f"No keyword node found for topic '{topic}'."

        first_hop_docs = sorted(
            n for n in self.graph.neighbors(keyword_node) if self.graph.nodes[n].get("node_type") == "document"
        )
        if len(first_hop_docs) < 2:
            keyword = self.graph.nodes[keyword_node].get("keyword", topic)
            return f"Keyword '{keyword}' found, but not enough linked documents for hidden connections."

        hidden_links: List[str] = []
        seen: set[Tuple[str, str, str]] = set()

        for doc_a in first_hop_docs:
            connected_keywords = [
                n for n in self.graph.neighbors(doc_a) if self.graph.nodes[n].get("node_type") == "keyword"
            ]
            for bridge_keyword_node in connected_keywords:
                bridge_keyword = self.graph.nodes[bridge_keyword_node].get("keyword", bridge_keyword_node)
                doc_neighbors = [
                    n
                    for n in self.graph.neighbors(bridge_keyword_node)
                    if self.graph.nodes[n].get("node_type") == "document" and n != doc_a
                ]
                for doc_b in doc_neighbors:
                    pair = tuple(sorted((doc_a, doc_b)))
                    link_key = (pair[0], pair[1], bridge_keyword)
                    if link_key in seen:
                        continue
                    seen.add(link_key)
                    hidden_links.append(
                        f"Found hidden link between {pair[0]} and {pair[1]} via shared concept {bridge_keyword}."
                    )
                    if len(hidden_links) >= max_links:
                        return "\n".join(hidden_links)

        if hidden_links:
            return "\n".join(hidden_links)

        keyword = self.graph.nodes[keyword_node].get("keyword", topic)
        return f"Keyword '{keyword}' found, but no 2-hop hidden document connections were discovered."

    def _query_graph_r1_placeholder(self, topic: str, max_links: int = 5) -> str:
        """Placeholder query hook for future Graph-R1 integration."""
        return self._query_native(topic=topic, max_links=max_links)
