# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de la capa de almacenamiento: models, config y state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agyswitcher.config import ConfigError, load_accounts, save_accounts
from agyswitcher.models import Account, AccountQuotaInfo, AppState
from agyswitcher.state import StateError, load_state, save_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture()
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


# ---------------------------------------------------------------------------
# Account model
# ---------------------------------------------------------------------------


def test_account_roundtrip() -> None:
    """Account se serializa y deserializa sin pérdida de datos."""
    acc = Account(
        alias="cuenta-a",
        email="user@example.com",
        preferred_models={"gemini": "gemini-3.8-flash-high"},
    )
    deserialized = Account.from_dict(acc.to_dict())
    assert deserialized.alias == "cuenta-a"
    assert deserialized.email == "user@example.com"
    assert deserialized.added_at == acc.added_at
    assert deserialized.get_preferred_model("gemini") == "gemini-3.8-flash-high"
    assert deserialized.get_preferred_model("external") is None

    # Métodos setter y clear
    acc.set_preferred_model("external", "claude-sonnet-4-6")
    assert acc.get_preferred_model("external") == "claude-sonnet-4-6"
    acc.clear_preferred_models("gemini")
    assert acc.get_preferred_model("gemini") is None
    assert acc.get_preferred_model("external") == "claude-sonnet-4-6"
    acc.clear_preferred_models()
    assert acc.preferred_models == {}

    # Retrocompatibilidad con diccionarios antiguos sin campo 'email' ni 'preferred_models'
    legacy_data = {"alias": "cuenta-legacy", "added_at": acc.added_at.isoformat()}
    legacy_acc = Account.from_dict(legacy_data)
    assert legacy_acc.alias == "cuenta-legacy"
    assert legacy_acc.email is None
    assert legacy_acc.preferred_models == {}


# ---------------------------------------------------------------------------
# AppState model
# ---------------------------------------------------------------------------


def test_appstate_defaults() -> None:
    state = AppState()
    assert state.active is None
    assert state.active_model_group == "gemini"
    assert state.gemini_quota_exhausted == {}
    assert state.external_quota_exhausted == {}
    assert state.switch_history == []


def test_appstate_roundtrip() -> None:
    state = AppState(
        active="cuenta-a",
        active_model_group="external",
        gemini_quota_exhausted={"cuenta-b": "2026-11-03T18:00:00+00:00"},
        external_quota_exhausted={"cuenta-c": "2026-11-03T19:00:00+00:00"},
    )
    restored = AppState.from_dict(state.to_dict())
    assert restored.active == "cuenta-a"
    assert restored.active_model_group == "external"
    assert restored.gemini_quota_exhausted == state.gemini_quota_exhausted
    assert restored.external_quota_exhausted == state.external_quota_exhausted


def test_appstate_is_account_fully_exhausted() -> None:
    """is_account_fully_exhausted solo es True cuando ambos pools están agotados."""
    state = AppState(
        gemini_quota_exhausted={"cuenta-a": "2026-11-03T18:00:00+00:00"},
        external_quota_exhausted={
            "cuenta-a": "2026-11-03T19:00:00+00:00",
            "cuenta-b": "2026-11-03T19:00:00+00:00",
        },
    )
    assert state.is_account_fully_exhausted("cuenta-a") is True
    assert state.is_account_fully_exhausted("cuenta-b") is False  # solo external
    assert state.is_account_fully_exhausted("cuenta-c") is False  # ninguno


def test_appstate_available_group_for() -> None:
    """available_group_for devuelve el primer pool libre, o None si agotada."""
    state = AppState(
        gemini_quota_exhausted={"cuenta-a": "2026-11-03T18:00:00+00:00"},
        external_quota_exhausted={"cuenta-b": "2026-11-03T19:00:00+00:00"},
    )
    # cuenta-a: gemini agotado → disponible external
    assert state.available_group_for("cuenta-a") == "external"
    # cuenta-b: external agotado → disponible gemini
    assert state.available_group_for("cuenta-b") == "gemini"
    # cuenta-c: ninguno agotado → disponible gemini (preferido)
    assert state.available_group_for("cuenta-c") == "gemini"

    state_full = AppState(
        gemini_quota_exhausted={"cuenta-x": "2026-11-03T18:00:00+00:00"},
        external_quota_exhausted={"cuenta-x": "2026-11-03T19:00:00+00:00"},
    )
    assert state_full.available_group_for("cuenta-x") is None


# ---------------------------------------------------------------------------
# config.py — load_accounts
# ---------------------------------------------------------------------------


def test_load_accounts_missing_file(config_file: Path) -> None:
    """Fichero inexistente → diccionario vacío, sin excepción."""
    assert load_accounts(config_file) == {}


def test_load_accounts_empty_accounts(config_file: Path) -> None:
    config_file.write_text(json.dumps({"accounts": {}}), encoding="utf-8")
    assert load_accounts(config_file) == {}


def test_load_accounts_valid(config_file: Path) -> None:
    acc = Account(alias="trabajo")
    save_accounts({"trabajo": acc}, config_file)
    loaded = load_accounts(config_file)
    assert "trabajo" in loaded
    assert loaded["trabajo"].alias == "trabajo"


def test_load_accounts_corrupt_json(config_file: Path) -> None:
    config_file.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ConfigError, match="malformado"):
        load_accounts(config_file)


def test_load_accounts_invalid_structure(config_file: Path) -> None:
    config_file.write_text(json.dumps({"accounts": {"x": {"wrong": "keys"}}}), encoding="utf-8")
    with pytest.raises(ConfigError, match="inválida"):
        load_accounts(config_file)


# ---------------------------------------------------------------------------
# config.py — save_accounts
# ---------------------------------------------------------------------------


def test_save_accounts_creates_file(config_file: Path) -> None:
    save_accounts({"personal": Account(alias="personal")}, config_file)
    assert config_file.exists()


def test_save_accounts_atomic_no_tmp_left(config_file: Path) -> None:
    """El fichero .tmp no debe quedar tras una escritura exitosa."""
    save_accounts({"personal": Account(alias="personal")}, config_file)
    assert not config_file.with_suffix(".tmp").exists()


def test_save_load_accounts_roundtrip(config_file: Path) -> None:
    accounts = {
        "alpha": Account(alias="alpha"),
        "beta": Account(alias="beta"),
    }
    save_accounts(accounts, config_file)
    loaded = load_accounts(config_file)
    assert set(loaded.keys()) == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# state.py — load_state
# ---------------------------------------------------------------------------


def test_load_state_missing_file(state_file: Path) -> None:
    """Fichero inexistente → AppState vacío, sin excepción."""
    state = load_state(state_file)
    assert state.active is None


def test_load_state_corrupt_json(state_file: Path) -> None:
    state_file.write_text("no es json", encoding="utf-8")
    with pytest.raises(StateError, match="malformado"):
        load_state(state_file)


def test_load_state_valid(state_file: Path) -> None:
    original = AppState(active="alpha")
    save_state(original, state_file)
    loaded = load_state(state_file)
    assert loaded.active == "alpha"


# ---------------------------------------------------------------------------
# state.py — save_state
# ---------------------------------------------------------------------------


def test_save_state_creates_file(state_file: Path) -> None:
    save_state(AppState(active="alpha"), state_file)
    assert state_file.exists()


def test_save_state_atomic_no_tmp_left(state_file: Path) -> None:
    save_state(AppState(), state_file)
    assert not state_file.with_suffix(".tmp").exists()


def test_save_load_state_roundtrip(state_file: Path) -> None:
    original = AppState(
        active="alpha",
        active_model_group="external",
        gemini_quota_exhausted={"beta": "2026-11-03T18:00:00+00:00"},
        external_quota_exhausted={"gamma": "2026-11-03T19:00:00+00:00"},
        switch_history=["beta", "alpha"],
    )
    save_state(original, state_file)
    loaded = load_state(state_file)
    assert loaded.active == "alpha"
    assert loaded.active_model_group == "external"
    assert loaded.gemini_quota_exhausted == original.gemini_quota_exhausted
    assert loaded.external_quota_exhausted == original.external_quota_exhausted
    assert loaded.switch_history == original.switch_history


def test_account_quota_info_roundtrip() -> None:
    """AccountQuotaInfo se serializa y deserializa preservando porcentajes y fechas."""
    from datetime import UTC, datetime

    reset_time = datetime(2026, 11, 13, 18, 0, 0, tzinfo=UTC)
    now = datetime(2026, 11, 6, 18, 0, 0, tzinfo=UTC)
    quota = AccountQuotaInfo(
        gemini_percent=85,
        gemini_reset_time=reset_time,
        external_percent=100,
        external_reset_time=reset_time,
        updated_at=now,
    )
    data = quota.to_dict()
    restored = AccountQuotaInfo.from_dict(data)
    assert restored.gemini_percent == 85
    assert restored.gemini_reset_time == reset_time
    assert restored.external_percent == 100
    assert restored.external_reset_time == reset_time
    assert restored.updated_at == now

    # Valores nulos y tipos vacíos
    empty_quota = AccountQuotaInfo.from_dict({})
    assert empty_quota.gemini_percent is None
    assert empty_quota.gemini_reset_time is None
    assert empty_quota.external_percent is None
    assert empty_quota.external_reset_time is None


def test_appstate_accounts_quota_roundtrip(state_file: Path) -> None:
    """AppState persiste y restaura correctamente el diccionario accounts_quota."""
    from datetime import UTC, datetime

    state = AppState(active="alpha")
    reset_dt = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
    state.update_account_quota(
        alias="alpha",
        gemini_percent=90,
        gemini_reset_time=reset_dt,
        external_percent=50,
    )

    assert "alpha" in state.accounts_quota
    assert state.accounts_quota["alpha"].gemini_percent == 90
    assert state.accounts_quota["alpha"].external_percent == 50
    assert state.accounts_quota["alpha"].gemini_reset_time == reset_dt

    # Guardar y recargar
    save_state(state, state_file)
    loaded = load_state(state_file)
    assert "alpha" in loaded.accounts_quota
    info = loaded.accounts_quota["alpha"]
    assert info.gemini_percent == 90
    assert info.external_percent == 50
    assert info.gemini_reset_time == reset_dt

    # Actualización incremental con update_account_quota
    loaded.update_account_quota("alpha", gemini_percent=80)
    assert loaded.accounts_quota["alpha"].gemini_percent == 80
    assert loaded.accounts_quota["alpha"].external_percent == 50  # se conserva


def test_home_is_isolated_in_tests() -> None:
    """Salvaguarda: ningún test debe operar sobre el ~/.gemini ni el ~/.agyswitcher reales."""
    import os

    from agyswitcher.config import default_config_path
    from agyswitcher.rotator import default_live_dir

    fake_home = Path(os.environ["USERPROFILE"])
    for path in (default_live_dir(), default_config_path()):
        assert fake_home in path.parents


# ---------------------------------------------------------------------------
# Revisión de seguridad (2026-11-19): HAL-02 (validación al cargar) y HAL-04
# ---------------------------------------------------------------------------


def _write_config(path: Path, alias: str, email: str | None) -> None:
    account: dict[str, object] = {"alias": alias, "added_at": "2026-11-19T10:00:00+00:00"}
    if email is not None:
        account["email"] = email
    path.write_text(json.dumps({"accounts": {alias: account}}), encoding="utf-8")


@pytest.mark.parametrize(
    ("alias", "email"),
    [
        ("cuenta-1", "a[/b]@example.com"),
        ("cuenta-1", "no-es-email"),
        ("[bold]x", "uno@example.com"),
    ],
)
def test_load_accounts_rejects_invalid_alias_or_email(
    tmp_path: Path, alias: str, email: str
) -> None:
    """Un config.json editado a mano con valores inválidos da un error claro, no un fallo posterior."""
    path = tmp_path / "config.json"
    _write_config(path, alias, email)

    with pytest.raises(ConfigError, match="no válido"):
        load_accounts(config_path=path)


def test_load_accounts_keeps_legacy_aliases(tmp_path: Path) -> None:
    """Los alias que ya no se pueden crear (p. ej. '-x') siguen cargando."""
    path = tmp_path / "config.json"
    _write_config(path, "-x", "uno@example.com")

    accounts = load_accounts(config_path=path)

    assert accounts["-x"].email == "uno@example.com"


def test_switch_history_is_capped_when_appending() -> None:
    from agyswitcher.models import MAX_SWITCH_HISTORY

    state = AppState()
    for i in range(MAX_SWITCH_HISTORY + 10):
        state.append_history(f"evento-{i}")

    assert len(state.switch_history) == MAX_SWITCH_HISTORY
    assert state.switch_history[0] == "evento-10"
    assert state.switch_history[-1] == f"evento-{MAX_SWITCH_HISTORY + 9}"


def test_switch_history_is_capped_when_loading(tmp_path: Path) -> None:
    from agyswitcher.models import MAX_SWITCH_HISTORY

    path = tmp_path / "state.json"
    entries = [f"evento-{i}" for i in range(MAX_SWITCH_HISTORY + 50)]
    path.write_text(json.dumps({"switch_history": entries}), encoding="utf-8")

    state = load_state(state_path=path)

    assert state.switch_history == entries[-MAX_SWITCH_HISTORY:]
