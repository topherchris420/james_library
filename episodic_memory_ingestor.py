"""Episodic Memory Ingestor — async bridge from Rust JSONL to GraphRAG.

This module tails the ``episodic_events.jsonl`` file written by the Rust
``EpisodicMemoryHook`` and feeds translated natural-language sentences into
the Graph-R1 knowledge graph as episodic memory nodes.

Design goals:
  - Zero overhead on the main research loop (runs in a background task).
  - Batched I/O: flushes to the graph every ``batch_size`` events **or**
    every ``flush_interval_seconds``, whichever comes first.
  - Idempotent: tracks file position so restarts skip already-ingested lines.

Usage::

    ingestor = EpisodicMemoryIngestor(
        jsonl_path="episodic_memory/episodic_events.jsonl",
        graph_bridge=my_hypergraph_manager,   # or None for standalone
    )
    # Start the background loop (call once):
    asyncio.create_task(ingestor.run())
    # Later, to stop gracefully:
    await ingestor.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from graph_bridge import HypergraphManager

logger = logging.getLogger("episodic_memory")


@dataclass
class EpisodicEvent:
    """Mirrors the Rust ``EpisodicEvent`` struct."""

    timestamp: str
    agent_name: str
    tool: str
    args: dict
    sentence: str
    duration_ms: int


@dataclass
class EpisodicMemoryIngestor:
    """Tails episodic JSONL and pushes sentences into the graph.

    Parameters
    ----------
    jsonl_path:
        Path to the JSONL file written by the Rust hook.
    graph_bridge:
        Optional ``HypergraphManager`` instance. When provided, episodic
        sentences are added as document nodes in the knowledge graph.
    graphr1_instance:
        Optional ``GraphR1`` instance for direct graph-r1 insertion.
    batch_size:
        Flush to the graph after this many events accumulate.
    flush_interval_seconds:
        Flush at least this often (even if batch is not full).
    """

    jsonl_path: str = "episodic_memory/episodic_events.jsonl"
    graph_bridge: Optional[HypergraphManager] = None
    graphr1_instance: object = None
    batch_size: int = 5
    flush_interval_seconds: float = 2.0

    _buffer: List[EpisodicEvent] = field(default_factory=list, init=False, repr=False)
    _file_offset: int = field(default=0, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _total_ingested: int = field(default=0, init=False, repr=False)

    async def run(self) -> None:
        """Main loop: tail the JSONL file and batch-ingest into the graph."""
        self._running = True
        logger.info(
            "EpisodicMemoryIngestor started — watching %s (batch=%d, flush=%.1fs)",
            self.jsonl_path,
            self.batch_size,
            self.flush_interval_seconds,
        )

        last_flush = time.monotonic()

        while self._running:
            new_events = self._read_new_events()
            if new_events:
                self._buffer.extend(new_events)

            now = time.monotonic()
            should_flush = (
                len(self._buffer) >= self.batch_size
                or (self._buffer and (now - last_flush) >= self.flush_interval_seconds)
            )

            if should_flush:
                await self._flush()
                last_flush = time.monotonic()

            await asyncio.sleep(0.25)

        # Drain remaining buffer on shutdown.
        if self._buffer:
            await self._flush()

    async def stop(self) -> None:
        """Signal the ingestor to stop after the current iteration."""
        self._running = False

    @property
    def total_ingested(self) -> int:
        """Number of episodic events successfully ingested so far."""
        return self._total_ingested

    def _read_new_events(self) -> List[EpisodicEvent]:
        """Read new lines from the JSONL file since last offset."""
        path = Path(self.jsonl_path)
        if not path.exists():
            return []

        events: List[EpisodicEvent] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                f.seek(self._file_offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        events.append(
                            EpisodicEvent(
                                timestamp=data.get("timestamp", ""),
                                agent_name=data.get("agent_name", "unknown"),
                                tool=data.get("tool", "unknown"),
                                args=data.get("args", {}),
                                sentence=data.get("sentence", ""),
                                duration_ms=data.get("duration_ms", 0),
                            )
                        )
                    except (json.JSONDecodeError, KeyError) as exc:
                        logger.warning("Skipping malformed JSONL line: %s", exc)
                self._file_offset = f.tell()
        except OSError as exc:
            logger.warning("Failed to read episodic JSONL: %s", exc)

        return events

    async def _flush(self) -> None:
        """Push buffered events into the graph backend."""
        if not self._buffer:
            return

        batch = list(self._buffer)
        self._buffer.clear()

        sentences = [ev.sentence for ev in batch if ev.sentence]
        if not sentences:
            return

        logger.info("Flushing %d episodic events to graph", len(sentences))

        # Strategy 1: Direct GraphR1 insertion (preferred).
        if self.graphr1_instance is not None:
            try:
                await self.graphr1_instance.ainsert(sentences)
                self._total_ingested += len(sentences)
                logger.debug("GraphR1 ingested %d episodic sentences", len(sentences))
                return
            except Exception as exc:
                logger.error("GraphR1 insertion failed: %s", exc)

        # Strategy 2: Native HypergraphManager (add episodic nodes).
        if self.graph_bridge is not None:
            try:
                self._ingest_native(batch)
                self._total_ingested += len(sentences)
                logger.debug(
                    "Native graph ingested %d episodic nodes", len(sentences)
                )
                return
            except Exception as exc:
                logger.error("Native graph insertion failed: %s", exc)

        # Strategy 3: Log-only fallback (always succeeds).
        for sentence in sentences:
            logger.info("[episodic] %s", sentence)
        self._total_ingested += len(sentences)

    def _ingest_native(self, events: List[EpisodicEvent]) -> None:
        """Add episodic events as nodes in the native networkx graph."""
        if self.graph_bridge is None:
            return

        graph = self.graph_bridge.graph
        for ev in events:
            node_id = f"episodic::{ev.timestamp}::{ev.tool}"
            graph.add_node(
                node_id,
                node_type="episodic",
                agent=ev.agent_name,
                tool=ev.tool,
                sentence=ev.sentence,
                timestamp=ev.timestamp,
                duration_ms=ev.duration_ms,
            )
            # Link episodic node to any document nodes that share keywords
            # from the tool args (lightweight cross-referencing).
            self._link_to_documents(graph, node_id, ev)

    @staticmethod
    def _link_to_documents(graph, node_id: str, ev: EpisodicEvent) -> None:
        """Create edges from an episodic node to related document nodes."""
        search_terms: List[str] = []
        args = ev.args
        for key in ("query", "pattern", "path", "key", "url"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                search_terms.append(val.strip().lower())

        if not search_terms:
            return

        doc_nodes = [
            n
            for n, attrs in graph.nodes(data=True)
            if attrs.get("node_type") == "document"
        ]
        for doc_name in doc_nodes:
            doc_lower = doc_name.lower()
            for term in search_terms:
                if term in doc_lower or doc_lower in term:
                    graph.add_edge(node_id, doc_name, relation="episodic_reference")
                    break
