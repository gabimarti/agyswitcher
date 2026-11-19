# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del motor de rotación de cuentas y pools (rotator.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agyswitcher.models import Account, AccountQuotaInfo, AppState
from agyswitcher.rotator import (
    account_reset_estimate,
    default_live_dir,
    record_rotation,
    select_next_candidate,
    suggest_account_to_check,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
"""Momento de referencia: un día después de los agotamientos de ejemplo (2026-11-04)."""


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
    assert select_next_candidate(accounts, state, now=NOW) is None


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


def _both_exhausted(alias: str, iso: str, state: AppState) -> None:
    state.gemini_quota_exhausted[alias] = iso
    state.external_quota_exhausted[alias] = iso


def test_select_next_candidate_accepts_pool_whose_reset_passed() -> None:
    """Un pool agotado cuyo reinicio previsto (agotamiento + 7 días) ya pasó se considera utilizable."""
    accounts = {"a": Account(alias="a"), "b": Account(alias="b")}
    state = AppState(active="a")
    _both_exhausted("a", "2026-11-04T12:00:00+00:00", state)
    _both_exhausted("b", "2026-11-01T12:00:00+00:00", state)  # reinicio previsto: 11-08

    assert select_next_candidate(accounts, state, now=NOW) is None
    later = datetime(2026, 11, 9, tzinfo=UTC)
    assert select_next_candidate(accounts, state, now=later) == ("b", "gemini")


def test_select_next_candidate_prefers_confirmed_pool_over_reset_passed() -> None:
    """Una cuenta sin pools agotados va antes que otra con el reinicio ya pasado (sin confirmar)."""
    accounts = {"a": Account(alias="a"), "b": Account(alias="b"), "c": Account(alias="c")}
    state = AppState(active="a")
    _both_exhausted("a", "2026-11-04T12:00:00+00:00", state)
    _both_exhausted("b", "2026-10-01T12:00:00+00:00", state)
    assert select_next_candidate(accounts, state, now=NOW) == ("c", "gemini")


def test_select_next_candidate_uses_stored_reset_time() -> None:
    """Si hay fecha de reinicio guardada posterior al agotamiento, se usa en lugar de los 7 días."""
    accounts = {"a": Account(alias="a"), "b": Account(alias="b")}
    state = AppState(active="a")
    _both_exhausted("a", "2026-11-04T12:00:00+00:00", state)
    _both_exhausted("b", "2026-11-04T12:00:00+00:00", state)
    state.accounts_quota["b"] = AccountQuotaInfo(
        gemini_reset_time=datetime(2026, 11, 5, 6, 0, tzinfo=UTC)
    )
    assert select_next_candidate(accounts, state, now=NOW) == ("b", "gemini")


def test_estimated_reset_ignores_reset_time_older_than_exhaustion() -> None:
    """Una fecha de reinicio anterior al agotamiento es de otro periodo: se estima a 7 días."""
    state = AppState()
    state.gemini_quota_exhausted["a"] = "2026-11-04T12:00:00+00:00"
    state.accounts_quota["a"] = AccountQuotaInfo(
        gemini_reset_time=datetime(2026, 11, 1, tzinfo=UTC)
    )
    assert state.estimated_reset("a", "gemini") == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert state.is_pool_blocked("a", "gemini", NOW)
    assert not state.is_pool_blocked("a", "external", NOW)


def test_naive_exhaustion_timestamp_is_treated_as_utc() -> None:
    state = AppState()
    state.gemini_quota_exhausted["a"] = "2026-11-04T12:00:00"
    assert state.estimated_reset("a", "gemini") == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def test_unreadable_exhaustion_timestamp_stays_blocked() -> None:
    state = AppState()
    state.gemini_quota_exhausted["a"] = "no-es-fecha"
    assert state.is_pool_blocked("a", "gemini", NOW + timedelta(days=365))


def test_account_reset_estimate_is_earliest_pool() -> None:
    state = AppState()
    state.gemini_quota_exhausted["a"] = "2026-11-04T12:00:00+00:00"
    state.external_quota_exhausted["a"] = "2026-11-02T12:00:00+00:00"
    assert account_reset_estimate(state, "a") == datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert account_reset_estimate(state, "otra") is None


def test_suggest_account_to_check_picks_earliest_reset_excluding_active() -> None:
    accounts = {"a": Account(alias="a"), "b": Account(alias="b"), "c": Account(alias="c")}
    state = AppState(active="a")
    _both_exhausted("a", "2026-11-01T12:00:00+00:00", state)
    _both_exhausted("b", "2026-11-04T12:00:00+00:00", state)
    _both_exhausted("c", "2026-11-03T12:00:00+00:00", state)
    assert suggest_account_to_check(accounts, state, exclude="a") == "c"
    assert suggest_account_to_check({"a": accounts["a"]}, state, exclude="a") is None


def test_suggest_account_to_check_tie_prefers_oldest_data() -> None:
    """Con el mismo reinicio previsto, se sugiere la cuenta cuyo dato es más antiguo."""
    accounts = {"b": Account(alias="b"), "c": Account(alias="c")}
    state = AppState()
    _both_exhausted("b", "2026-11-04T12:00:00+00:00", state)
    _both_exhausted("c", "2026-11-04T12:00:00+00:00", state)
    reset = datetime(2026, 11, 8, tzinfo=UTC)
    state.accounts_quota["b"] = AccountQuotaInfo(
        gemini_reset_time=reset, updated_at=datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
    )
    state.accounts_quota["c"] = AccountQuotaInfo(
        gemini_reset_time=reset, updated_at=datetime(2026, 11, 4, 13, 0, tzinfo=UTC)
    )
    assert suggest_account_to_check(accounts, state) == "c"
