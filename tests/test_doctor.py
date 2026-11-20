# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests del diagnóstico 'agyswitcher doctor'."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agyswitcher import doctor
from agyswitcher.cli import app
from agyswitcher.config import save_accounts
from agyswitcher.doctor import (
    Check,
    CheckStatus,
    DoctorOptions,
    check_accounts,
    check_active_account,
    check_agy,
    check_agy_processes,
    check_project,
    check_quota_data,
    check_session,
    display_path,
    mask_email,
    run_doctor,
    worst_status,
)
from agyswitcher.models import Account, AccountQuotaInfo, AppState
from agyswitcher.runner import AgyNotFoundError
from agyswitcher.state import save_state

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
runner = CliRunner()


def _accounts() -> dict[str, Account]:
    return {
        "personal": Account(alias="personal", email="personal@example.com"),
        "trabajo": Account(alias="trabajo", email="trabajo@example.com"),
    }


@pytest.fixture
def no_agy(monkeypatch: pytest.MonkeyPatch) -> None:
    """agy no instalado: ninguna comprobación lanza procesos reales."""

    def _missing() -> Path:
        raise AgyNotFoundError("no agy")

    monkeypatch.setattr(doctor, "find_agy_executable", _missing)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def test_mask_email_hides_local_part() -> None:
    assert mask_email("personal@example.com") == "pe***@example.com"
    assert mask_email("abc@example.com") == "a***@example.com"
    assert mask_email("sin-arroba") == "***"


def test_display_path_replaces_home() -> None:
    inside = Path.home() / "proyectos" / "demo"
    assert display_path(inside) == str(Path("~") / "proyectos" / "demo")
    outside = Path("Z:/otro/sitio")
    assert display_path(outside) == str(outside)


def test_worst_status_orders_by_severity() -> None:
    checks = [
        Check("a", CheckStatus.OK, ""),
        Check("b", CheckStatus.WARN, ""),
        Check("c", CheckStatus.INFO, ""),
    ]
    assert worst_status(checks) is CheckStatus.WARN
    assert worst_status([]) is CheckStatus.OK


# ---------------------------------------------------------------------------
# agy
# ---------------------------------------------------------------------------


def test_check_agy_missing_is_error(no_agy: None) -> None:
    assert check_agy().status is CheckStatus.FAIL


def test_check_agy_reports_version(monkeypatch: pytest.MonkeyPatch) -> None:
    exe = Path.home() / "agy" / "agy.exe"
    monkeypatch.setattr(doctor, "find_agy_executable", lambda: exe)
    monkeypatch.setattr(
        doctor,
        "run_captured",
        lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "1.5.13\n", ""),
    )
    check = check_agy()
    assert check.status is CheckStatus.OK
    assert "1.5.13" in check.detail
    assert str(Path("~") / "agy" / "agy.exe") in check.detail


def test_check_agy_timeout_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "find_agy_executable", lambda: Path("agy.exe"))

    def _timeout(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(doctor, "run_captured", _timeout)
    assert check_agy().status is CheckStatus.WARN


# ---------------------------------------------------------------------------
# Cuentas, cuenta activa y sesión
# ---------------------------------------------------------------------------


def test_check_accounts_variants() -> None:
    assert check_accounts(None, "malformado").status is CheckStatus.FAIL
    assert check_accounts({}, None).status is CheckStatus.WARN
    assert check_accounts(_accounts(), None).status is CheckStatus.OK
    no_email = {"viejo": Account(alias="viejo")}
    check = check_accounts(no_email, None)
    assert check.status is CheckStatus.WARN
    assert "viejo" in check.detail


def test_check_active_account_variants() -> None:
    accounts = _accounts()
    assert check_active_account(accounts, AppState()).status is CheckStatus.WARN
    assert check_active_account(accounts, AppState(active="borrada")).status is CheckStatus.FAIL
    assert check_active_account(accounts, AppState(active="personal")).status is CheckStatus.OK


def test_check_session_matches_active_and_masks_email() -> None:
    check = check_session(
        _accounts(), AppState(active="personal"), "personal@example.com", DoctorOptions()
    )
    assert check.status is CheckStatus.OK
    assert "pe***@example.com" in check.detail
    assert "personal@example.com" not in check.detail


def test_check_session_shows_email_when_asked() -> None:
    check = check_session(
        _accounts(),
        AppState(active="personal"),
        "Personal@Example.com",
        DoctorOptions(show_emails=True),
    )
    assert check.status is CheckStatus.OK
    assert "Personal@Example.com" in check.detail


def test_check_session_other_account_is_warning() -> None:
    check = check_session(
        _accounts(), AppState(active="personal"), "trabajo@example.com", DoctorOptions()
    )
    assert check.status is CheckStatus.WARN
    assert "trabajo" in check.detail
    assert check.hint is not None and "set-active trabajo" in check.hint


def test_check_session_unknown_or_missing() -> None:
    state = AppState(active="personal")
    unknown = check_session(_accounts(), state, "otra@example.com", DoctorOptions())
    assert unknown.status is CheckStatus.WARN
    missing = check_session(_accounts(), state, None, DoctorOptions())
    assert missing.status is CheckStatus.WARN


# ---------------------------------------------------------------------------
# Datos de cuota
# ---------------------------------------------------------------------------


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


def test_quota_data_fresh_active_and_stale_others() -> None:
    state = AppState(active="personal")
    state.accounts_quota["personal"] = AccountQuotaInfo(
        gemini_percent=80, updated_at=NOW - timedelta(hours=2)
    )
    state.accounts_quota["trabajo"] = AccountQuotaInfo(
        gemini_percent=50, updated_at=NOW - timedelta(days=9)
    )
    checks = _by_name(check_quota_data(_accounts(), state, NOW))
    assert checks["Cuota de la cuenta activa"].status is CheckStatus.OK
    others = checks["Cuota de otras cuentas"]
    assert others.status is CheckStatus.INFO
    assert "trabajo (9 días)" in others.detail


def test_quota_data_active_missing_or_old_is_warning() -> None:
    state = AppState(active="personal")
    checks = _by_name(check_quota_data(_accounts(), state, NOW))
    assert checks["Cuota de la cuenta activa"].status is CheckStatus.WARN

    state.accounts_quota["personal"] = AccountQuotaInfo(updated_at=NOW - timedelta(days=2))
    checks = _by_name(check_quota_data(_accounts(), state, NOW))
    assert checks["Cuota de la cuenta activa"].status is CheckStatus.WARN


def test_quota_data_reports_exhausted_pool_past_reset() -> None:
    state = AppState(active="personal")
    state.accounts_quota["personal"] = AccountQuotaInfo(updated_at=NOW)
    state.accounts_quota["trabajo"] = AccountQuotaInfo(
        gemini_reset_time=NOW - timedelta(days=1), updated_at=NOW - timedelta(days=3)
    )
    state.gemini_quota_exhausted["trabajo"] = (NOW - timedelta(days=3)).isoformat()
    checks = _by_name(check_quota_data(_accounts(), state, NOW))
    assert "trabajo (Gemini)" in checks["Cuotas agotadas"].detail


def test_quota_data_without_accounts_is_empty() -> None:
    assert check_quota_data({}, AppState(), NOW) == []


# ---------------------------------------------------------------------------
# Procesos y proyecto
# ---------------------------------------------------------------------------


def test_check_agy_processes_variants() -> None:
    assert check_agy_processes([]).status is CheckStatus.OK
    assert check_agy_processes(["agy.exe"]).status is CheckStatus.INFO
    assert check_agy_processes(None).status is CheckStatus.WARN


def test_check_project_states(tmp_path: Path) -> None:
    assert check_project(tmp_path, None)[0].status is CheckStatus.INFO
    (tmp_path / "AGENTS.md").write_text("# Reglas\n", encoding="utf-8")
    partial = check_project(tmp_path, None)[0]
    assert partial.status is CheckStatus.WARN
    assert "dev_mem/" in partial.detail
    (tmp_path / "dev_mem").mkdir()
    assert check_project(tmp_path, None)[0].status is CheckStatus.OK


def test_check_project_reports_project_threshold_and_errors(tmp_path: Path) -> None:
    toml = tmp_path / ".agyswitcher.toml"
    toml.write_text("[quota]\nlow_percent = 25\n", encoding="utf-8")
    config = _by_name(check_project(tmp_path, 15))["Configuración del proyecto"]
    assert config.status is CheckStatus.OK
    assert "25 %" in config.detail

    toml.write_text("[quota]\nlow_percent = 150\n", encoding="utf-8")
    config = _by_name(check_project(tmp_path, 15))["Configuración del proyecto"]
    assert config.status is CheckStatus.WARN


# ---------------------------------------------------------------------------
# Diagnóstico completo y comando
# ---------------------------------------------------------------------------


def test_run_doctor_full_healthy_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = Path.home() / "agy.exe"
    monkeypatch.setattr(doctor, "find_agy_executable", lambda: exe)
    monkeypatch.setattr(
        doctor,
        "run_captured",
        lambda cmd, timeout: subprocess.CompletedProcess(cmd, 0, "1.5.13\n", ""),
    )
    save_accounts(_accounts())
    state = AppState(active="personal")
    state.accounts_quota["personal"] = AccountQuotaInfo(updated_at=NOW)
    state.accounts_quota["trabajo"] = AccountQuotaInfo(updated_at=NOW)
    save_state(state)
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    (tmp_path / "dev_mem").mkdir()

    checks = run_doctor(
        tmp_path,
        now=NOW,
        email_detector=lambda: "personal@example.com",
        process_lister=lambda: [],
    )
    assert worst_status(checks) is CheckStatus.INFO
    names = [c.name for c in checks]
    assert names[0] == "Versiones"
    assert "Sesión de agy" in names


def test_run_doctor_broken_config_is_error(
    tmp_path: Path, no_agy: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Path.home() / ".agyswitcher" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text("{no es json", encoding="utf-8")
    checks = _by_name(
        run_doctor(tmp_path, now=NOW, email_detector=lambda: None, process_lister=lambda: [])
    )
    assert checks["Cuentas"].status is CheckStatus.FAIL
    assert checks["Ajustes"].status is CheckStatus.FAIL
    assert "Sesión de agy" not in checks


def test_cli_doctor_exit_codes_and_masking(
    tmp_path: Path, no_agy: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "personal@example.com")
    monkeypatch.setattr("agyswitcher.cli.find_running_agy_processes", lambda: [])
    monkeypatch.chdir(tmp_path)
    save_accounts(_accounts())
    save_state(AppState(active="personal"))

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1  # agy no está en el PATH
    assert "pe***@example.com" in result.output
    assert "personal@example.com" not in result.output

    shown = runner.invoke(app, ["doctor", "--show-emails"])
    assert "personal@example.com" in shown.output
