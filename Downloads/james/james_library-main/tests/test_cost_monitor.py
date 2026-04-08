from __future__ import annotations

from pathlib import Path

import pytest

from james_library.utilities.cost_monitor import BudgetExceededError, CostMonitor


def test_update_cost_accumulates_session_total_for_gpt_4o(tmp_path: Path) -> None:
    monitor = CostMonitor(session_id="session-a", workspace_root=tmp_path)

    delta = monitor.update_cost(
        model_name="gpt-4o",
        prompt_tokens=2_000,
        completion_tokens=1_000,
    )

    assert delta == pytest.approx(0.025)
    assert monitor.session_cost == pytest.approx(0.025)


def test_check_budget_raises_when_limit_hit(tmp_path: Path) -> None:
    monitor = CostMonitor(session_id="session-b", workspace_root=tmp_path)
    monitor.update_cost(
        model_name="o1-preview",
        prompt_tokens=40_000,
        completion_tokens=10_000,
    )

    with pytest.raises(BudgetExceededError) as exc_info:
        monitor.check_budget(1.00)

    assert exc_info.value.total_spent == pytest.approx(1.20)
    assert exc_info.value.limit == pytest.approx(1.00)
    assert "$1.00" in str(exc_info.value)


def test_session_cost_reloads_from_sqlite_for_same_session(tmp_path: Path) -> None:
    first = CostMonitor(session_id="session-c", workspace_root=tmp_path)
    first.update_cost(
        model_name="claude-3-5-sonnet",
        prompt_tokens=1_000,
        completion_tokens=500,
    )

    resumed = CostMonitor(session_id="session-c", workspace_root=tmp_path)

    assert resumed.session_cost == pytest.approx(first.session_cost)


def test_price_map_includes_required_aliases(tmp_path: Path) -> None:
    monitor = CostMonitor(session_id="session-d", workspace_root=tmp_path)

    assert monitor.update_cost("gpt-4o", 1_000_000, 0) == pytest.approx(5.0)
    assert monitor.update_cost("o1-preview", 1_000_000, 0) == pytest.approx(15.0)
    assert monitor.update_cost("claude-3-5-sonnet", 1_000_000, 0) == pytest.approx(3.0)
