from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from james_library.launcher import swarm_orchestrator as orchestrator
from james_library.utilities.cost_monitor import BudgetExceededError, CostMonitor


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(prompt_tokens, completion_tokens)


class _FakeCompletions:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.called = 0

    def create(self, **_: object) -> _FakeResponse:
        self.called += 1
        return self._response


class _FakeChat:
    def __init__(self, response: _FakeResponse) -> None:
        self.completions = _FakeCompletions(response)


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.chat = _FakeChat(response)


def test_resolve_max_task_budget_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("JAMES_MAX_TASK_BUDGET", "2.50")

    assert orchestrator._resolve_max_task_budget(None) == pytest.approx(2.50)


def test_call_llm_async_updates_cost_monitor_and_logs_cost(tmp_path: Path, caplog) -> None:
    monitor = CostMonitor(session_id="swarm-cost-a", workspace_root=tmp_path)
    runtime = orchestrator.SwarmRuntimeState(
        session_id="swarm-cost-a",
        cost_monitor=monitor,
        max_task_budget=1.00,
    )
    client = _FakeClient(_FakeResponse("answer", prompt_tokens=2_000, completion_tokens=1_000))

    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            orchestrator._call_llm_async(
                client=client,
                model="gpt-4o",
                messages=[{"role": "system", "content": "Be precise."}],
                temperature=0.2,
                max_tokens=128,
                max_context_tokens=1_000,
                runtime_state=runtime,
            )
        )

    assert result == "answer"
    assert runtime.cost_monitor.session_cost == pytest.approx(0.025)
    assert client.chat.completions.called == 1
    assert any("[COST]" in record.message for record in caplog.records)


def test_call_llm_async_halts_when_budget_prompt_rejects_continue(tmp_path: Path) -> None:
    monitor = CostMonitor(session_id="swarm-cost-b", workspace_root=tmp_path)
    monitor.update_cost("o1-preview", prompt_tokens=40_000, completion_tokens=10_000)
    runtime = orchestrator.SwarmRuntimeState(
        session_id="swarm-cost-b",
        cost_monitor=monitor,
        max_task_budget=1.00,
        budget_prompt=lambda _error, _limit: None,
    )
    client = _FakeClient(_FakeResponse("should-not-run", prompt_tokens=1, completion_tokens=1))

    with pytest.raises(BudgetExceededError):
        asyncio.run(
            orchestrator._call_llm_async(
                client=client,
                model="o1-preview",
                messages=[{"role": "system", "content": "Budget test"}],
                temperature=0.2,
                max_tokens=64,
                max_context_tokens=1_000,
                runtime_state=runtime,
            )
        )

    assert client.chat.completions.called == 0


def test_call_llm_async_can_raise_budget_limit_after_overrun(tmp_path: Path) -> None:
    monitor = CostMonitor(session_id="swarm-cost-c", workspace_root=tmp_path)
    runtime = orchestrator.SwarmRuntimeState(
        session_id="swarm-cost-c",
        cost_monitor=monitor,
        max_task_budget=0.01,
        budget_prompt=lambda _error, _limit: 1.50,
    )
    client = _FakeClient(_FakeResponse("answer", prompt_tokens=2_000, completion_tokens=1_000))

    result = asyncio.run(
        orchestrator._call_llm_async(
            client=client,
            model="gpt-4o",
            messages=[{"role": "system", "content": "Raise budget"}],
            temperature=0.2,
            max_tokens=64,
            max_context_tokens=1_000,
            runtime_state=runtime,
        )
    )

    assert result == "answer"
    assert runtime.max_task_budget == pytest.approx(1.50)
