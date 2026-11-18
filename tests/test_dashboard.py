# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios para los componentes visuales del Dashboard TUI (dashboard.py)."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.panel import Panel
from rich.table import Table

from agyswitcher.dashboard import (
    build_accounts_table,
    build_dashboard_view,
    build_history_panel,
    build_system_summary_panel,
    render_quota_bar,
)
from agyswitcher.models import Account, AppState
from agyswitcher.usage import PoolUsage, UsageReport


def test_render_quota_bar() -> None:
    high = render_quota_bar(90, length=10)
    assert "90%" in high
    assert "green" in high

    mid = render_quota_bar(35, length=10)
    assert "35%" in mid
    assert "yellow" in mid

    low = render_quota_bar(10, length=10)
    assert "10%" in low
    assert "red" in low

    zero = render_quota_bar(-5, length=10)
    assert "0%" in zero


def test_build_system_summary_panel() -> None:
    accounts = {"cta1": Account(alias="cta1"), "cta2": Account(alias="cta2")}
    state = AppState(active="cta1", active_model_group="gemini")
    report = UsageReport(
        is_authenticated=True,
        pools={},
        timestamp=datetime(2026, 11, 5, 12, 0, 0, tzinfo=UTC),
    )

    panel = build_system_summary_panel(accounts, state, usage_report=report)
    assert isinstance(panel, Panel)
    assert "Centro de Control" in str(panel.title)


def test_build_accounts_table_with_live_report() -> None:
    accounts = {
        "cta1": Account(alias="cta1"),
        "cta2": Account(alias="cta2"),
    }
    state = AppState(
        active="cta1",
        gemini_quota_exhausted={"cta2": "2026-11-04T10:00:00Z"},
        external_quota_exhausted={"cta2": "2026-11-04T10:00:00Z"},
    )
    report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=85,
                reset_time=None,
                reset_raw="",
            )
        },
    )

    table = build_accounts_table(accounts, state, usage_report=report)
    assert isinstance(table, Table)
    assert len(table.rows) == 2


def test_build_history_panel() -> None:
    empty_state = AppState()
    p_empty = build_history_panel(empty_state)
    assert isinstance(p_empty, Panel)

    state_with_history = AppState(switch_history=["swap to cta1", "swap to cta2", "swap pool"])
    p_full = build_history_panel(state_with_history, max_entries=2)
    assert isinstance(p_full, Panel)


def test_build_dashboard_view_empty_and_full() -> None:
    empty_view = build_dashboard_view({}, AppState())
    assert isinstance(empty_view, Panel)

    accounts = {"alpha": Account(alias="alpha")}
    state = AppState(active="alpha")
    full_view = build_dashboard_view(accounts, state)
    assert hasattr(full_view, "renderables")
