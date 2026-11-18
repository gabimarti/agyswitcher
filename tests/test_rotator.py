# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del motor de rotación de cuentas y pools (rotator.py)."""

from __future__ import annotations

from pathlib import Path

from agyswitcher.models import Account, AppState
from agyswitcher.rotator import default_live_dir, record_rotation, select_next_candidate


def test_select_next_candidate_empty_accounts() -> None:
    state = AppState()
    assert select_next_candidate({}, state) is None


def test_select_next_candidate_rotates_pool_within_active_account() -> None:
    """Si el pool actual está agotado pero el alternativo está libre, rota pool en la misma cuenta."""
    accounts = {"cuenta-1": Account(alias="cuenta-1")}
    state = AppState(
        active="cuenta-1",
        active_model_group="gemini",
        gemini_quota_exhausted={"cuenta-1": "2026-11-04T12:00:00Z"},
    )
    candidate = select_next_candidate(accounts, state)
    assert candidate == ("cuenta-1", "external")


def test_select_next_candidate_rotates_to_next_account_when_active_exhausted() -> None:
    """Si la cuenta activa tiene ambos pools agotados, selecciona la siguiente cuenta disponible."""
    accounts = {
        "cuenta-1": Account(alias="cuenta-1"),
        "cuenta-2": Account(alias="cuenta-2"),
    }
    state = AppState(
        active="cuenta-1",
        active_model_group="gemini",
        gemini_quota_exhausted={"cuenta-1": "2026-11-04T12:00:00Z"},
        external_quota_exhausted={"cuenta-1": "2026-11-04T12:30:00Z"},
    )
    candidate = select_next_candidate(accounts, state)
    assert candidate == ("cuenta-2", "gemini")


def test_select_next_candidate_returns_none_when_all_exhausted() -> None:
    """Retorna None si todas las cuentas configuradas tienen ambos pools agotados."""
    accounts = {
        "cuenta-1": Account(alias="cuenta-1"),
        "cuenta-2": Account(alias="cuenta-2"),
    }
    state = AppState(
        active="cuenta-1",
        gemini_quota_exhausted={
            "cuenta-1": "2026-11-04T12:00:00Z",
            "cuenta-2": "2026-11-04T12:00:00Z",
        },
        external_quota_exhausted={
            "cuenta-1": "2026-11-04T12:30:00Z",
            "cuenta-2": "2026-11-04T12:30:00Z",
        },
    )
    assert select_next_candidate(accounts, state) is None


def test_select_next_candidate_circular_round_robin() -> None:
    """La selección de candidatos prioriza circularmente la siguiente cuenta a la activa."""
    accounts = {
        "a": Account(alias="a"),
        "b": Account(alias="b"),
        "c": Account(alias="c"),
    }
    # Si 'b' es la activa y se agota, 'c' debe ser elegida antes que 'a'
    state = AppState(
        active="b",
        gemini_quota_exhausted={"b": "2026-11-04T12:00:00Z"},
        external_quota_exhausted={"b": "2026-11-04T12:30:00Z"},
    )
    candidate = select_next_candidate(accounts, state)
    assert candidate == ("c", "gemini")


def test_record_rotation_account_change_updates_state_and_history(tmp_path: Path) -> None:
    """Un cambio de cuenta actualiza activa, pool e historial y persiste el estado."""
    state_file = tmp_path / "state.json"
    state = AppState(active="cuenta-1", active_model_group="gemini")

    msg = record_rotation("cuenta-2", "external", state, state_path=state_file)

    assert "Rotado a cuenta 'cuenta-2'" in msg
    assert state.active == "cuenta-2"
    assert state.active_model_group == "external"
    assert "cuenta-1 (gemini) -> cuenta-2 (external)" in state.switch_history[-1]
    assert state_file.exists()


def test_record_rotation_pool_change_and_reaffirm(tmp_path: Path) -> None:
    """Cambio de pool en la misma cuenta y reafirmación quedan registrados."""
    state_file = tmp_path / "state.json"
    state = AppState(active="cuenta-1", active_model_group="gemini")

    msg = record_rotation("cuenta-1", "external", state, state_path=state_file)
    assert "Cambiado pool" in msg
    assert state.active_model_group == "external"

    msg = record_rotation("cuenta-1", "external", state, state_path=state_file)
    assert "reafirmada" in msg
    assert len(state.switch_history) == 2


def test_record_rotation_from_no_active(tmp_path: Path) -> None:
    state = AppState()
    msg = record_rotation("cuenta-1", "gemini", state, state_path=tmp_path / "s.json")
    assert "Rotado a cuenta 'cuenta-1'" in msg
    assert "ninguna (gemini) -> cuenta-1" in state.switch_history[-1]


def test_default_live_dir_is_user_gemini() -> None:
    assert default_live_dir() == Path.home() / ".gemini"
