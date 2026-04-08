"""Rust daemon HTTP bridge client for local Rust daemon orchestration."""

from __future__ import annotations

from typing import Any, Dict, List


class RustDaemonClient:
    """HTTP bridge client for local Rust daemon orchestration."""

    def __init__(self, base_url: str, timeout_s: float):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)))

    def request_agent_response(
        self,
        *,
        agent_name: str,
        topic: str,
        context_block: str,
        recent_chat: str,
        mission: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "agent": agent_name,
            "topic": topic,
            "context": context_block,
            "recent_chat": recent_chat,
            "mission": mission,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response = self.client.post(f"{self.base_url}/v1/agents/respond", json=payload)
        response.raise_for_status()
        data = response.json()
        content = (data.get("content") or "").strip()
        if not content:
            raise RuntimeError("Rust daemon returned empty content")
        return content

    def poll_events(self) -> List[Dict[str, Any]]:
        try:
            response = self.client.get(f"{self.base_url}/v1/events/poll")
            if response.status_code >= 400:
                return []
            data = response.json()
            events = data.get("events", [])
            if isinstance(events, list):
                return [event for event in events if isinstance(event, dict)]
            return []
        except Exception:
            return []
