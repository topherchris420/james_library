"""
R.A.I.N. Lab Memory System

Cross-session entity tracking and research memory.
"""

import json
import os
from datetime import datetime
from pathlib import Path


class ResearchMemory:
    """Persistent memory across research sessions."""

    def __init__(self, library_path: str):
        self.library_path = library_path
        self.memory_dir = os.path.join(library_path, "meeting_archives")
        self.memory_file = os.path.join(self.memory_dir, "research_memory.json")
        self._ensure_memory_dir()

    def _ensure_memory_dir(self):
        """Create memory directory if it doesn't exist."""
        os.makedirs(self.memory_dir, exist_ok=True)

    def _load(self) -> dict:
        """Load memory from file."""
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {"entities": {}, "topics": {}, "connections": [], "last_updated": None}

    def _save(self, mem: dict):
        """Save memory to file."""
        try:
            mem["last_updated"] = datetime.now().isoformat()
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(mem, f, indent=2)
        except Exception as e:
            print(f"Memory save warning: {e}")

    def remember_entity(self, name: str, description: str, entity_type: str = "concept") -> str:
        """Remember an entity across sessions."""
        mem = self._load()
        if "entities" not in mem:
            mem["entities"] = {}

        mem["entities"][name] = {
            "description": description,
            "type": entity_type,
            "first_mentioned": datetime.now().isoformat()
        }
        self._save(mem)
        return f"✓ Remembered: {name} ({entity_type})"

    def recall(self, name: str) -> str:
        """Recall a previously remembered entity."""
        mem = self._load()
        entities = mem.get("entities", {})

        if name in entities:
            e = entities[name]
            return f"{name} ({e['type']}): {e['description']}"
        return f"No memory found for: {name}"

    def list_entities(self, entity_type: str = None) -> str:
        """List all remembered entities."""
        mem = self._load()
        entities = mem.get("entities", {})

        if entity_type:
            filtered = {k: v for k, v in entities.items() if v.get("type") == entity_type}
        else:
            filtered = entities

        if not filtered:
            return "No entities remembered yet."

        lines = ["Remembered entities:"]
        for name, info in filtered.items():
            lines.append(f"  • {name} ({info['type']}): {info['description'][:50]}...")
        return "\n".join(lines)

    def remember_insight(self, topic: str, insight: str) -> str:
        """Remember a key insight about a topic."""
        mem = self._load()
        if "topics" not in mem:
            mem["topics"] = {}

        if topic not in mem["topics"]:
            mem["topics"][topic] = []

        mem["topics"][topic].append({
            "insight": insight,
            "timestamp": datetime.now().isoformat()
        })
        self._save(mem)
        return f"✓ Insight saved for topic: {topic}"

    def recall_insights(self, topic: str) -> str:
        """Recall all insights for a topic."""
        mem = self._load()
        topics = mem.get("topics", {})

        if topic in topics:
            lines = [f"Insights on {topic}:"]
            for i, item in enumerate(topics[topic], 1):
                lines.append(f"  {i}. {item['insight']}")
            return "\n".join(lines)
        return f"No insights recorded for: {topic}"

    def connect_entities(self, entity1: str, entity2: str, relationship: str = "related") -> str:
        """Create a connection between two entities."""
        mem = self._load()
        if "connections" not in mem:
            mem["connections"] = []

        mem["connections"].append({
            "from": entity1,
            "to": entity2,
            "relationship": relationship,
            "timestamp": datetime.now().isoformat()
        })
        self._save(mem)
        return f"✓ Connected: {entity1} --[{relationship}]--> {entity2}"

    def get_research_graph(self) -> str:
        """Get ASCII representation of research connections."""
        mem = self._load()
        connections = mem.get("connections", [])

        if not connections:
            return "No connections yet. Use connect_entities() to link concepts."

        lines = ["RESEARCH GRAPH", "=" * 40]
        for conn in connections[-10:]:  # Last 10 connections
            lines.append(f"{conn['from']} --[{conn['relationship']}]--> {conn['to']}")

        return "\n".join(lines)


# Standalone functions for RLM agent use
_memory = None

def _get_memory():
    """Get or create global memory instance."""
    global _memory
    if _memory is None:
        library_path = os.environ.get("JAMES_LIBRARY_PATH", os.getcwd())
        _memory = ResearchMemory(library_path)
    return _memory


def remember_entity(name: str, description: str, entity_type: str = "concept") -> str:
    """RLM wrapper for remember_entity."""
    return _get_memory().remember_entity(name, description, entity_type)


def recall_entity(name: str) -> str:
    """RLM wrapper for recall."""
    return _get_memory().recall(name)


def list_entities(entity_type: str = None) -> str:
    """RLM wrapper for list_entities."""
    return _get_memory().list_entities(entity_type)


def remember_topic_insight(topic: str, insight: str) -> str:
    """RLM wrapper for remember_insight."""
    return _get_memory().remember_insight(topic, insight)


def recall_topic_insights(topic: str) -> str:
    """RLM wrapper for recall_insights."""
    return _get_memory().recall_insights(topic)


def connect_entities(entity1: str, entity2: str, relationship: str = "related") -> str:
    """RLM wrapper for connect_entities."""
    return _get_memory().connect_entities(entity1, entity2, relationship)


def get_research_graph() -> str:
    """RLM wrapper for get_research_graph."""
    return _get_memory().get_research_graph()
