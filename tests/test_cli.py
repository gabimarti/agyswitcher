# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests del entry point CLI de AgySwitcher."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from agyswitcher.cli import app
from agyswitcher.config import load_accounts
from agyswitcher.models import AccountQuotaInfo
from agyswitcher.runner import AgyNotFoundError, RunnerError
from agyswitcher.state import load_state, save_state
from agyswitcher.usage import AuthRequiredError, PoolUsage, UsageReport

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla las rutas de config.json y state.json para todos los tests de CLI."""
    dummy_config = tmp_path / "config.json"
    dummy_state = tmp_path / "state.json"
    monkeypatch.setattr("agyswitcher.cli.load_accounts", lambda: load_accounts(dummy_config))
    monkeypatch.setattr(
        "agyswitcher.cli.save_accounts",
        lambda accs: __import__("agyswitcher.config", fromlist=["save_accounts"]).save_accounts(
            accs, dummy_config
        ),
    )
    monkeypatch.setattr("agyswitcher.cli.load_state", lambda: load_state(dummy_state))
    monkeypatch.setattr(
        "agyswitcher.cli.save_state",
        lambda st: __import__("agyswitcher.state", fromlist=["save_state"]).save_state(
            st, dummy_state
        ),
    )
    # También en los módulos importados si se llaman directamente
    monkeypatch.setattr("agyswitcher.config.default_config_path", lambda: dummy_config)
    monkeypatch.setattr("agyswitcher.state.default_state_path", lambda: dummy_state)
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: None)
    monkeypatch.setattr("agyswitcher.usage.detect_active_email", lambda: None)
    # Nunca consultar procesos reales del sistema desde los tests.
    monkeypatch.setattr("agyswitcher.cli.find_running_agy_processes", lambda: [])
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage",
        lambda *args, **kwargs: (_ for _ in ()).throw(AgyNotFoundError("Mocked agy not found")),
    )


def _login_ok(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Simula que el usuario inicia sesión en agy con la cuenta destino (cambio guiado)."""
    from agyswitcher.session import LoginWaitResult, LoginWaitStatus

    def _wait(expected_email: str, *_a: object, **_k: object) -> LoginWaitResult:
        return LoginWaitResult(LoginWaitStatus.VERIFIED, expected_email)

    mock = MagicMock(side_effect=_wait)
    monkeypatch.setattr("agyswitcher.cli.wait_for_login", mock)
    return mock


def test_version() -> None:
    """--version debe mostrar el número de versión y salir con código 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "agyswitcher" in result.output
    from agyswitcher import __version__

    assert __version__ in result.output


def test_no_args_shows_help() -> None:
    """Sin argumentos muestra la ayuda (typer no_args_is_help=True → exit_code=2 según Click)."""
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "agyswitcher" in result.output.lower() or "Usage" in result.output


def test_add_first_account_becomes_active() -> None:
    """La primera cuenta registrada se guarda y se establece automáticamente como activa."""
    result = runner.invoke(app, ["add", "cuenta-1"])
    assert result.exit_code == 0
    assert "registrada y establecida como cuenta activa" in result.output

    state = load_state()
    assert state.active == "cuenta-1"

    accounts = load_accounts()
    assert "cuenta-1" in accounts


def test_add_second_account_keeps_first_active() -> None:
    """Una segunda cuenta registrada no sobrescribe la cuenta activa existente."""
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["add", "cuenta-2"])
    assert result.exit_code == 0
    assert "registrada correctamente" in result.output

    state = load_state()
    assert state.active == "cuenta-1"

    accounts = load_accounts()
    assert "cuenta-1" in accounts
    assert "cuenta-2" in accounts


def test_add_duplicate_account_fails() -> None:
    """Intentar agregar un alias que ya existe debe fallar con código 1."""
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["add", "cuenta-1"])
    assert result.exit_code == 1
    assert "ya está registrada" in result.output


def test_add_invalid_alias_fails() -> None:
    """Nombres con caracteres no permitidos o vacíos deben fallar con código 1."""
    result_invalid = runner.invoke(app, ["add", "cuenta con espacios"])
    assert result_invalid.exit_code == 1
    assert "no es válido" in result_invalid.output

    result_chars = runner.invoke(app, ["add", "cuenta/slash"])
    assert result_chars.exit_code == 1
    assert "no es válido" in result_chars.output


def test_list_no_accounts() -> None:
    """Listar sin cuentas debe informar al usuario cómo agregar una."""
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No hay cuentas configuradas" in result.output
    assert "agyswitcher add" in result.output


def test_list_with_accounts_shows_status() -> None:
    """Listar muestra las cuentas con la activa primero y ordenadas por fecha de reinicio más próxima."""
    runner.invoke(app, ["add", "cuenta-activa"])
    runner.invoke(app, ["add", "cuenta-standby"])
    runner.invoke(app, ["add", "cuenta-parcial"])
    runner.invoke(app, ["add", "cuenta-agotada"])

    # Simular cuotas agotadas
    state = load_state()
    state.gemini_quota_exhausted["cuenta-parcial"] = "2026-11-03T20:00:00+00:00"
    state.gemini_quota_exhausted["cuenta-agotada"] = "2026-11-03T20:00:00+00:00"
    state.external_quota_exhausted["cuenta-agotada"] = "2026-11-03T20:00:00+00:00"
    save_state(state)

    result = runner.invoke(app, ["list"], env={"COLUMNS": "120"})
    assert result.exit_code == 0
    output = result.output

    assert "* cuenta-activa" in output
    assert "cuenta-standby" in output
    assert "cuenta-parcial" in output
    assert "0% (agotado)" in output
    assert "cuenta-agotada" in output
    # La columna 'Estado' se ha eliminado; no debe haber etiquetas redundantes
    assert "[ACTIVA]" not in output
    assert "[DISPONIBLE]" not in output
    assert "[PARCIAL]" not in output
    assert "[AGOTADA]" not in output
    assert "Cuota" in output
    assert "Gemini / Otros" in output
    assert "Reinicio Cuota" in output

    # La cuenta activa debe aparecer antes que las cuentas secundarias
    idx_activa = output.index("* cuenta-activa")
    idx_parcial = output.index("cuenta-parcial")
    idx_standby = output.index("cuenta-standby")
    assert idx_activa < idx_parcial
    assert idx_parcial < idx_standby


def test_list_with_metrics_and_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """List muestra porcentajes guardados y soporta --live para refrescar."""
    runner.invoke(app, ["add", "amanda", "--email", "amanda@example.com"])
    runner.invoke(app, ["add", "beto", "--email", "beto@example.com"])

    state = load_state()
    reset_dt = datetime.now(UTC) + timedelta(days=6, hours=5)
    state.update_account_quota(
        "beto",
        gemini_percent=90,
        gemini_reset_time=reset_dt,
        external_percent=80,
    )
    save_state(state)

    # Simular fetch_usage para --live
    mock_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=70,
                reset_time=reset_dt,
                reset_raw="2026-11-13T19:00:00Z",
            ),
            "external": PoolUsage(
                pool="external",
                display_name="Claude and GPT models",
                metric="Weekly Limit Remaining",
                remaining_percent=95,
                reset_time=reset_dt,
                reset_raw="2026-11-13T19:00:00Z",
            ),
        },
    )
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", lambda timeout=10.0: mock_report)

    result = runner.invoke(app, ["list", "--live"], env={"COLUMNS": "120"})
    assert result.exit_code == 0
    output = result.output

    assert "amanda" in output
    assert "70%" in output
    assert "95%" in output
    assert "beto" in output
    assert "90%" in output
    assert "80%" in output
    assert "en 6d" in output or "en 7d" in output


def test_list_auto_refreshes_when_quota_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """List sin flags refresca automáticamente si la cuota de la cuenta activa tiene más de 180s."""
    runner.invoke(app, ["add", "amanda", "--email", "amanda@example.com"])

    state = load_state()
    # Forzar fecha de actualización hace 5 minutos (300s > TTL de 180s)
    stale_dt = datetime.now(UTC) - timedelta(seconds=300)
    reset_dt = datetime.now(UTC) + timedelta(days=6)
    state.update_account_quota(
        "amanda", gemini_percent=50, external_percent=50, gemini_reset_time=reset_dt
    )
    state.accounts_quota["amanda"].updated_at = stale_dt
    save_state(state)

    fresh_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=88,
                reset_time=reset_dt,
                reset_raw="2026-11-13T19:00:00Z",
            ),
        },
    )
    mock_fetch = MagicMock(return_value=fresh_report)
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", mock_fetch)

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert mock_fetch.called
    assert "88%" in result.output

    st = load_state()
    assert st.accounts_quota["amanda"].gemini_percent == 88


def test_list_uses_cache_when_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    """List no consulta fetch_usage si la cuota de la cuenta activa es reciente (<180s)."""
    runner.invoke(app, ["add", "amanda", "--email", "amanda@example.com"])

    state = load_state()
    recent_dt = datetime.now(UTC) - timedelta(seconds=30)
    reset_dt = datetime.now(UTC) + timedelta(days=6)
    state.update_account_quota(
        "amanda", gemini_percent=77, external_percent=77, gemini_reset_time=reset_dt
    )
    state.accounts_quota["amanda"].updated_at = recent_dt
    save_state(state)

    mock_fetch = MagicMock()
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", mock_fetch)

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert not mock_fetch.called
    assert "77%" in result.output


def test_list_cached_flag_skips_fetch_usage_even_if_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """List con --cached no consulta agy aunque la cuota haya expirado el TTL."""
    runner.invoke(app, ["add", "amanda", "--email", "amanda@example.com"])

    state = load_state()
    stale_dt = datetime.now(UTC) - timedelta(days=2)
    state.update_account_quota("amanda", gemini_percent=42, external_percent=42)
    state.accounts_quota["amanda"].updated_at = stale_dt
    save_state(state)

    mock_fetch = MagicMock()
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", mock_fetch)

    result = runner.invoke(app, ["list", "--cached"])
    assert result.exit_code == 0
    assert not mock_fetch.called
    assert "42%" in result.output


def test_get_earliest_reset_time_logic() -> None:
    """get_earliest_reset_time devuelve el menor timestamp entre pools o fallback."""
    from agyswitcher.cli import get_earliest_reset_time
    from agyswitcher.models import AccountQuotaInfo, AppState

    state = AppState()
    # Caso 1: sin información
    assert get_earliest_reset_time("acc1", None, state) is None

    # Caso 2: con reset times directos
    dt1 = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
    dt2 = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
    info = AccountQuotaInfo(gemini_reset_time=dt1, external_reset_time=dt2)
    assert get_earliest_reset_time("acc1", info, state) == dt2

    # Caso 3: fallback con cuota agotada (+7 días)
    state.gemini_quota_exhausted["acc2"] = "2026-11-05T10:00:00+00:00"
    assert get_earliest_reset_time("acc2", None, state) == datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def test_list_sorting_order_active_first_then_resets() -> None:
    """List siempre coloca la cuenta activa primero y luego ordena de menor a mayor tiempo de reinicio."""
    runner.invoke(app, ["add", "z_activa"])
    runner.invoke(app, ["add", "standby_lejano"])
    runner.invoke(app, ["add", "standby_temprano"])
    runner.invoke(app, ["add", "standby_sin_datos"])

    state = load_state()
    now = datetime.now(UTC)
    state.update_account_quota(
        "standby_lejano",
        gemini_percent=50,
        gemini_reset_time=now + timedelta(days=5),
    )
    state.update_account_quota(
        "standby_temprano",
        gemini_percent=20,
        gemini_reset_time=now + timedelta(days=1),
    )
    save_state(state)

    result = runner.invoke(app, ["list", "--cached"], env={"COLUMNS": "120"})
    assert result.exit_code == 0
    output = result.output

    idx_activa = output.index("* z_activa")
    idx_temprano = output.index("standby_temprano")
    idx_lejano = output.index("standby_lejano")
    idx_sin_datos = output.index("standby_sin_datos")

    assert idx_activa < idx_temprano < idx_lejano < idx_sin_datos


def test_list_refresh_all_only_queries_session_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """--refresh-all solo consulta la cuenta con sesión (agy solo tiene una) y lo explica."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])
    fetch = MagicMock(
        return_value=UsageReport(
            is_authenticated=True,
            active_email=None,
            pools={
                "gemini": PoolUsage(
                    pool="gemini",
                    display_name="Gemini Models",
                    metric="Weekly Limit Remaining",
                    remaining_percent=85,
                    reset_time=datetime.now(UTC) + timedelta(days=3),
                    reset_raw="2026-11-14T12:00:00Z",
                )
            },
        )
    )
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", fetch)

    result = runner.invoke(app, ["list", "--refresh-all"])

    assert result.exit_code == 0
    assert "agy solo tiene una sesión" in result.output
    assert fetch.call_count == 1
    st_final = load_state()
    assert st_final.active == "cuenta-1"
    assert st_final.accounts_quota.get("cuenta-1") is not None
    assert st_final.accounts_quota.get("cuenta-2") is None


def test_list_attributes_quota_to_session_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la sesión de agy es de otra cuenta, la cuota se guarda en esa cuenta, no en la activa."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage",
        MagicMock(
            return_value=UsageReport(
                is_authenticated=True,
                active_email="DOS@example.com",
                pools={
                    "gemini": PoolUsage(
                        pool="gemini",
                        display_name="Gemini Models",
                        metric="Weekly Limit Remaining",
                        remaining_percent=85,
                        reset_time=datetime.now(UTC) + timedelta(days=3),
                        reset_raw="2026-11-14T12:00:00Z",
                    )
                },
            )
        ),
    )

    result = runner.invoke(app, ["list", "--live"])

    assert result.exit_code == 0
    st_final = load_state()
    assert st_final.accounts_quota.get("cuenta-2") is not None
    assert st_final.accounts_quota.get("cuenta-1") is None


def test_status_no_accounts() -> None:
    """Status sin cuentas debe indicar que no hay cuentas y sugerir agyswitcher add."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No hay cuentas configuradas" in result.output
    assert "agyswitcher add" in result.output


def test_status_with_active_account() -> None:
    """Status muestra la cuenta activa, pool activo y resumen de pools."""
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    output = result.output

    assert "cuenta-1" in output
    assert "[ACTIVA]" in output
    assert "Pool activo:" in output
    assert "gemini" in output
    assert "Total cuentas:" in output
    assert "Disponibles:" in output
    assert "Historial:" in output


def test_status_with_cooldown_active_account() -> None:
    """Status avisa si la cuenta activa actual tiene pools de cuota agotados."""
    runner.invoke(app, ["add", "cuenta-1"])

    # Caso 1: Solo gemini agotado
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-03T20:00:00+00:00"
    save_state(state)

    result_partial = runner.invoke(app, ["status"])
    assert result_partial.exit_code == 0
    assert "Pool Gemini agotado en 'cuenta-1'" in result_partial.output
    assert "Cuotas agotadas por pool" in result_partial.output

    # Caso 2: Ambos agotados
    state = load_state()
    state.external_quota_exhausted["cuenta-1"] = "2026-11-03T20:30:00+00:00"
    save_state(state)

    result_full = runner.invoke(app, ["status"])
    assert result_full.exit_code == 0
    assert "[AGOTADA]" in result_full.output
    assert "tiene ambos pools de cuota" in result_full.output


def test_status_with_no_active_account() -> None:
    """Status advierte si hay cuentas registradas pero ninguna está activa."""
    runner.invoke(app, ["add", "cuenta-1"])

    state = load_state()
    state.active = None
    save_state(state)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    output = result.output

    assert "Ninguna" in output
    assert "Advertencia: No hay ninguna cuenta activa válida" in output


def test_status_with_multiple_accounts_and_cooldowns() -> None:
    """Status refleja los totales y detalles de cooldowns con múltiples cuentas y pools."""
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["add", "cuenta-2"])
    runner.invoke(app, ["add", "cuenta-3"])

    state = load_state()
    state.gemini_quota_exhausted["cuenta-3"] = "2026-11-03T20:30:00+00:00"
    state.external_quota_exhausted["cuenta-3"] = "2026-11-03T20:30:00+00:00"
    save_state(state)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    output = result.output

    assert "cuenta-1" in output
    assert "[ACTIVA]" in output
    assert "3" in output
    assert "2" in output
    assert "cuenta-3" in output
    assert "Cuotas agotadas por pool" in output


# ---------------------------------------------------------------------------
# Tests del comando rotate
# ---------------------------------------------------------------------------


def test_rotate_no_accounts_fails() -> None:
    """rotate sin cuentas registradas debe fallar con código 1."""
    result = runner.invoke(app, ["rotate"])
    assert result.exit_code == 1
    assert "No hay cuentas configuradas" in result.output


def test_rotate_to_unknown_alias_fails() -> None:
    """rotate a un alias inexistente debe fallar con código 1."""
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["rotate", "cuenta-fantasma"])
    assert result.exit_code == 1
    assert "no está registrada" in result.output


def test_rotate_to_specific_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """rotate a un alias registrado cambia la cuenta activa y persiste en state.json."""
    _login_ok(monkeypatch)
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])

    result = runner.invoke(app, ["rotate", "cuenta-2"])
    assert result.exit_code == 0
    assert "Rotado a cuenta 'cuenta-2'" in result.output

    state = load_state()
    assert state.active == "cuenta-2"
    assert len(state.switch_history) == 1


def test_rotate_auto_swaps_pool_when_current_exhausted() -> None:
    """rotate automático conmuta al pool alternativo de la cuenta si el actual está agotado."""
    runner.invoke(app, ["add", "cuenta-1"])
    state = load_state()
    state.active = "cuenta-1"
    state.active_model_group = "gemini"
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)

    result = runner.invoke(app, ["rotate"])
    assert result.exit_code == 0
    assert "Cambiado pool en cuenta activa 'cuenta-1'" in result.output
    assert load_state().active_model_group == "external"


def test_rotate_auto_swaps_to_next_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """rotate automático conmuta a la siguiente cuenta si la activa tiene ambos pools agotados."""
    _login_ok(monkeypatch)
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:30:00Z"
    save_state(state)

    result = runner.invoke(app, ["rotate"])
    assert result.exit_code == 0
    assert "Rotado a cuenta 'cuenta-2'" in result.output
    assert load_state().active == "cuenta-2"


def test_rotate_auto_fails_when_all_accounts_exhausted() -> None:
    """rotate automático falla con código 1 si todas las cuentas tienen ambos pools agotados."""
    runner.invoke(app, ["add", "cuenta-1"])
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:30:00Z"
    save_state(state)

    result = runner.invoke(app, ["rotate"])
    assert result.exit_code == 1
    assert "Todas las cuentas configuradas tienen su cuota agotada" in result.output


# ---------------------------------------------------------------------------
# Tests del comando watch
# ---------------------------------------------------------------------------


def test_watch_no_accounts() -> None:
    """watch sin cuentas informa y sale limpiamente."""
    result = runner.invoke(app, ["watch", "--once"])
    assert result.exit_code == 0
    assert "No hay cuentas configuradas" in result.output


def test_watch_once_detects_quota_and_rotates(tmp_path: Path) -> None:
    """watch detecta cuota agotada en el log indicado y rota automáticamente."""
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["add", "cuenta-2"])

    fake_log = tmp_path / "cli.log"
    fake_log.write_text(
        "Session log starting...\n"
        "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for gemini\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["watch", "--once", "--log-file", str(fake_log)])
    assert result.exit_code == 0
    assert "Detectada cuota agotada" in result.output

    state = load_state()
    assert "cuenta-1" in state.gemini_quota_exhausted


# ---------------------------------------------------------------------------
# Tests del comando run
# ---------------------------------------------------------------------------


def test_run_no_accounts_fails() -> None:
    """run sin cuentas configuradas debe fallar con código 1."""
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "No hay cuentas configuradas" in result.output


def test_run_no_active_account_fails() -> None:
    """run sin cuenta activa válida debe fallar con código 1."""
    runner.invoke(app, ["add", "cuenta-1"])

    state = load_state()
    state.active = None
    save_state(state)

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "No hay ninguna cuenta activa válida" in result.output


def test_run_agy_not_found_fails() -> None:
    """run cuando agy.exe no está en PATH debe fallar con código 1."""
    runner.invoke(app, ["add", "cuenta-1"])

    with patch(
        "agyswitcher.cli.run_agy_process", side_effect=AgyNotFoundError("agy no encontrado")
    ):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "No se encontró agy.exe" in result.output


def test_run_runner_error_fails() -> None:
    """run cuando el runner lanza RunnerError debe fallar con código 1."""
    runner.invoke(app, ["add", "cuenta-1"])

    with patch("agyswitcher.cli.run_agy_process", side_effect=RunnerError("fallo en proceso")):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Error al ejecutar agy" in result.output


def test_run_with_args_passes_through() -> None:
    """run con argumentos invoca run_agy_process con esos args y propaga el exit code."""
    runner.invoke(app, ["add", "cuenta-1"])

    captured_args: list[list[str]] = []

    def fake_runner(args: list[str], **_kwargs: object) -> int:
        captured_args.append(args)
        return 0

    with patch("agyswitcher.cli.run_agy_process", side_effect=fake_runner):
        result = runner.invoke(app, ["run", "--", "--print", "hola"])

    # sys.exit(0) en typer.testing se recoge como exit_code=0
    assert result.exit_code == 0
    assert captured_args == [["--print", "hola"]]


def test_run_propagates_nonzero_exit_code() -> None:
    """run propaga el código de salida del proceso hijo cuando no es 0."""
    runner.invoke(app, ["add", "cuenta-1"])

    with patch("agyswitcher.cli.run_agy_process", return_value=42):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 42


def test_run_uses_real_agy_process() -> None:
    """run invoca run_agy_process usando Python como subproceso real (smoke test)."""
    runner.invoke(app, ["add", "cuenta-1"])

    # Usamos el intérprete de Python actual como ejecutable real para evitar
    # depender de que agy.exe esté instalado en el entorno de CI.
    code = "import sys; print('ok'); sys.exit(0)"

    from agyswitcher.runner import run_agy_process as real_runner

    lines: list[str] = []
    exit_code = real_runner(
        ["-c", code],
        executable_path=Path(sys.executable),
        on_line=lines.append,
        echo_output=False,
    )
    assert exit_code == 0
    assert any("ok" in line for line in lines)


def test_run_detects_quota_exhaustion_in_real_time() -> None:
    """run detecta un error de cuota en el stream de salida y actualiza state.json."""
    runner.invoke(app, ["add", "cuenta-1"])

    def fake_runner_with_quota(
        args: list[str],
        *,
        on_line: object = None,
        **_kwargs: object,
    ) -> int:
        if callable(on_line):
            on_line(
                "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for gemini-flash\n"
            )
        return 1

    with patch("agyswitcher.cli.run_agy_process", side_effect=fake_runner_with_quota):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    state = load_state()
    assert "cuenta-1" in state.gemini_quota_exhausted


def test_usage_no_accounts() -> None:
    """usage avisa si no hay cuentas configuradas."""
    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "No hay cuentas configuradas" in result.output


def test_usage_success_renders_and_syncs() -> None:
    """usage muestra tabla de cuotas, reporta autenticación y sincroniza cooldowns."""
    from agyswitcher.usage import PoolUsage, UsageReport

    runner.invoke(app, ["add", "cuenta-1"])
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)

    fake_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=80,
                reset_time=None,
                reset_raw="2026-11-12T09:32:16Z",
            ),
            "external": PoolUsage(
                pool="external",
                display_name="Claude and GPT models",
                metric="Weekly Limit Remaining",
                remaining_percent=0,
                reset_time=None,
                reset_raw="",
            ),
        },
    )

    with patch("agyswitcher.cli.fetch_usage", return_value=fake_report):
        result = runner.invoke(app, ["usage"])

    assert result.exit_code == 0
    assert "Autenticada y Activa" in result.output
    assert "Gemini Models" in result.output
    assert "80%" in result.output
    assert "Cooldown levantado" in result.output

    updated_state = load_state()
    # Gemini fue restaurado porque remaining_percent > 0
    assert "cuenta-1" not in updated_state.gemini_quota_exhausted
    # External fue marcado porque remaining_percent <= 0
    assert "cuenta-1" in updated_state.external_quota_exhausted


def test_usage_auth_required_error() -> None:
    """usage reporta error claro cuando no se ha iniciado sesión."""
    from agyswitcher.usage import AuthRequiredError

    runner.invoke(app, ["add", "cuenta-1"])

    with patch(
        "agyswitcher.cli.fetch_usage",
        side_effect=AuthRequiredError("Sesión no iniciada en Google."),
    ):
        result = runner.invoke(app, ["usage"])

    assert result.exit_code == 1
    assert "Error de autenticación" in result.output


def test_status_with_live_flag() -> None:
    """status --live consulta métricas en tiempo real de la cuenta activa."""
    from agyswitcher.usage import PoolUsage, UsageReport

    runner.invoke(app, ["add", "cuenta-1"])

    fake_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=95,
                reset_time=None,
                reset_raw="2026-11-12T09:32:16Z",
            )
        },
    )

    with patch("agyswitcher.cli.fetch_usage", return_value=fake_report):
        result = runner.invoke(app, ["status", "--live"])

    assert result.exit_code == 0
    assert "Métricas en vivo" in result.output
    assert "95%" in result.output


def test_dashboard_no_accounts() -> None:
    """dashboard sin cuentas muestra aviso informativo."""
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 0
    assert "No hay cuentas configuradas" in result.output


def test_dashboard_renders_tables_and_summary() -> None:
    """dashboard con cuentas muestra matriz y centro de control."""
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["dashboard"])
    assert result.exit_code == 0
    assert "Centro de Control" in result.output
    assert "Matriz de Cuentas" in result.output
    assert "cuenta-1" in result.output


def test_dashboard_with_live_flag() -> None:
    """dashboard --live incorpora métricas de cuota y sesión."""
    from agyswitcher.usage import PoolUsage, UsageReport

    runner.invoke(app, ["add", "cuenta-1"])

    fake_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=90,
                reset_time=None,
                reset_raw="2026-11-12T09:32:16Z",
            )
        },
    )

    with patch("agyswitcher.cli.fetch_usage", return_value=fake_report):
        result = runner.invoke(app, ["dashboard", "--live"])

    assert result.exit_code == 0
    assert "Conectada / Activa" in result.output
    assert "90%" in result.output


def test_add_with_explicit_email() -> None:
    result = runner.invoke(app, ["add", "mi-cuenta", "--email", "custom@example.com"])
    assert result.exit_code == 0
    assert "mi-cuenta" in result.output
    assert "custom@example.com" in result.output

    accounts = load_accounts()
    assert accounts["mi-cuenta"].email == "custom@example.com"


def test_add_detects_email_and_switches_when_email_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Primera cuenta con email A
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "user_a@example.com")
    runner.invoke(app, ["add", "cuenta-a"])

    state = load_state()
    assert state.active == "cuenta-a"

    # Segunda cuenta detectando email B (cambio de sesión en agy)
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "user_b@example.com")
    result = runner.invoke(app, ["add", "cuenta-b"])
    assert result.exit_code == 0

    state = load_state()
    assert state.active == "cuenta-b"
    accounts = load_accounts()
    assert accounts["cuenta-b"].email == "user_b@example.com"


def test_remove_account_force() -> None:
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["add", "cuenta-2"])

    result = runner.invoke(app, ["remove", "cuenta-2", "--force"])
    assert result.exit_code == 0
    assert "eliminada correctamente" in result.output

    accounts = load_accounts()
    assert "cuenta-2" not in accounts
    assert "cuenta-1" in accounts


def test_remove_account_interactive_cancel() -> None:
    runner.invoke(app, ["add", "cuenta-1"])
    result = runner.invoke(app, ["remove", "cuenta-1"], input="n\n")
    assert result.exit_code == 0
    assert "Operación cancelada" in result.output

    accounts = load_accounts()
    assert "cuenta-1" in accounts


def test_remove_active_account_leaves_no_active_and_suggests_sync() -> None:
    """Sin iniciar sesión no se puede activar otra cuenta: queda sin activa y se sugiere sync."""
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["add", "cuenta-2"])

    result = runner.invoke(app, ["remove", "cuenta-1", "--force"])
    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    assert "Ahora no hay cuenta activa" in flat
    assert "agyswitcher sync" in flat

    state = load_state()
    assert state.active is None


def test_set_active_command(monkeypatch: pytest.MonkeyPatch) -> None:
    _login_ok(monkeypatch)
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])

    result = runner.invoke(app, ["set-active", "cuenta-2"])
    assert result.exit_code == 0
    assert "Cuenta activa establecida en 'cuenta-2'" in result.output

    state = load_state()
    assert state.active == "cuenta-2"


def test_set_active_refreshes_quota_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """set-active refresca y persiste métricas de cuota al conmutar a una cuenta."""
    _login_ok(monkeypatch)
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])

    mock_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=92,
                reset_time=datetime.now(UTC) + timedelta(days=4),
                reset_raw="2026-11-15T12:00:00Z",
            ),
            "external": PoolUsage(
                pool="external",
                display_name="Claude and GPT models",
                metric="Weekly Limit Remaining",
                remaining_percent=88,
                reset_time=datetime.now(UTC) + timedelta(days=4),
                reset_raw="2026-11-15T12:00:00Z",
            ),
        },
    )
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", lambda timeout=10.0: mock_report)

    result = runner.invoke(app, ["set-active", "cuenta-2"])
    assert result.exit_code == 0
    assert "Cuota sincronizada: Gemini 92% | Otros 88%" in result.output

    st = load_state()
    assert st.active == "cuenta-2"
    assert st.accounts_quota["cuenta-2"].gemini_percent == 92


def test_sync_active_account_success(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "beta@example.com"])

    # Forzar cuenta-1 como activa
    runner.invoke(app, ["set-active", "cuenta-1"])
    assert load_state().active == "cuenta-1"

    # Simular que en agy la sesión activa es beta@example.com
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "beta@example.com")
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "Sincronizado: Cuenta activa cambiada de 'cuenta-1' a 'cuenta-2'" in result.output

    assert load_state().active == "cuenta-2"


def test_sync_active_account_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: None)

    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "No se detectó ninguna sesión activa de Google" in result.output


def test_sync_active_account_with_live_fetch_usage_refreshes_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "beta@example.com"])
    runner.invoke(app, ["set-active", "cuenta-1"])

    fake_report = UsageReport(
        is_authenticated=True,
        active_email="beta@example.com",
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=90,
                reset_time=datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC),
                reset_raw="2026-11-17T10:00:00Z",
            ),
            "external": PoolUsage(
                pool="external",
                display_name="Claude and GPT models",
                metric="Weekly Limit Remaining",
                remaining_percent=50,
                reset_time=datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC),
                reset_raw="2026-11-17T10:00:00Z",
            ),
        },
    )
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", lambda timeout=10.0: fake_report)

    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "Sincronizado: Cuenta activa cambiada de 'cuenta-1' a 'cuenta-2'" in result.output
    assert "Cuota sincronizada: Gemini 90% | Otros 50%" in result.output

    st = load_state()
    assert st.active == "cuenta-2"
    assert st.accounts_quota["cuenta-2"].gemini_percent == 90
    assert st.accounts_quota["cuenta-2"].external_percent == 50


def test_sync_active_account_auth_required_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage",
        lambda timeout=10.0: (_ for _ in ()).throw(AuthRequiredError("Token expirado")),
    )

    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "Sesión no iniciada en Google" in result.output


def test_usage_identity_mismatch_prevents_cooldown_contamination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "beta@example.com"])
    runner.invoke(app, ["set-active", "cuenta-1"])

    # Simular que cuenta-1 tiene cooldown de gemini
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-06T10:00:00Z"
    save_state(state)

    from agyswitcher.usage import PoolUsage, UsageReport

    fake_report = UsageReport(
        is_authenticated=True,
        active_email="beta@example.com",  # Sesión real pertenece a cuenta-2
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=100,  # 100% cuota
                reset_time=None,
                reset_raw="2026-11-13T09:46:01Z",
            )
        },
    )

    with patch("agyswitcher.cli.fetch_usage", return_value=fake_report):
        result = runner.invoke(app, ["usage"])

    assert result.exit_code == 0
    assert "Desajuste de cuenta detectado" in result.output
    assert "No se modificará el estado de cuota de 'cuenta-1'" in result.output

    # Verificar que el cooldown de cuenta-1 NO fue levantado
    state_after = load_state()
    assert "cuenta-1" in state_after.gemini_quota_exhausted


# ---------------------------------------------------------------------------
# Comando models y preferencia de modelos
# ---------------------------------------------------------------------------


def test_models_no_accounts() -> None:
    """models falla si no hay cuentas configuradas."""
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 1
    assert "No hay cuentas configuradas" in result.output


def test_models_list_renders_table() -> None:
    """models lista los modelos de agy indicando su pool y cuota."""
    runner.invoke(app, ["add", "cuenta-1"])

    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "Modelos de Antigravity" in result.output
    assert "gemini-3.8" in result.output
    assert "claude-sonnet" in result.output
    assert "gemini" in result.output
    assert "external" in result.output
    assert "[DISPONIBLE]" in result.output


def test_models_set_and_clear_preferred() -> None:
    """models --set fija el modelo preferido y --clear lo elimina."""
    runner.invoke(app, ["add", "cuenta-1"])

    # Fijar modelo para pool gemini
    res_set = runner.invoke(app, ["models", "--set", "gemini-3.8-flash-high"])
    assert res_set.exit_code == 0
    assert "Modelo preferido para el pool 'gemini'" in res_set.output
    assert "gemini-3.8-flash-high" in res_set.output

    # Fijar modelo para pool external
    res_set_ext = runner.invoke(app, ["models", "-s", "claude-sonnet-4-6"])
    assert res_set_ext.exit_code == 0
    assert "Modelo preferido para el pool 'external'" in res_set_ext.output

    # Listar y verificar que aparece la marca de preferido
    res_list = runner.invoke(app, ["models"])
    assert res_list.exit_code == 0
    assert "★ Preferido" in res_list.output

    # Verificar que se persistió en config.json
    accounts = load_accounts()
    assert accounts["cuenta-1"].get_preferred_model("gemini") == "gemini-3.8-flash-high"
    assert accounts["cuenta-1"].get_preferred_model("external") == "claude-sonnet-4-6"

    # Limpiar preferencias
    res_clear = runner.invoke(app, ["models", "--clear"])
    assert res_clear.exit_code == 0
    assert "Preferencias de modelos eliminadas" in res_clear.output

    accounts_after = load_accounts()
    assert accounts_after["cuenta-1"].preferred_models == {}


@patch("agyswitcher.cli.run_agy_process")
def test_run_injects_preferred_model(mock_process: MagicMock) -> None:
    """run inyecta automáticamente --model si hay preferencia para el pool activo."""
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["models", "--set", "gemini-3.8-flash-high"])

    mock_process.return_value = 0
    result = runner.invoke(app, ["run", "--", "tarea-prueba"])

    assert result.exit_code == 0
    # Verificar que run_agy_process recibió los argumentos con --model inyectado
    mock_process.assert_called_once()
    passed_args = mock_process.call_args[1]["args"]
    assert passed_args == ["--model", "gemini-3.8-flash-high", "tarea-prueba"]


@patch("agyswitcher.cli.run_agy_process")
def test_run_respects_explicit_model_flag(mock_process: MagicMock) -> None:
    """run respeta el flag --model si el usuario lo proporciona explícitamente."""
    runner.invoke(app, ["add", "cuenta-1"])
    runner.invoke(app, ["models", "--set", "gemini-3.8-flash-high"])

    mock_process.return_value = 0
    result = runner.invoke(
        app, ["run", "--", "--model", "claude-opus-4-6-thinking", "tarea-prueba"]
    )

    assert result.exit_code == 0
    mock_process.assert_called_once()
    passed_args = mock_process.call_args[1]["args"]
    # No debe duplicar ni pisar el modelo explícito
    assert passed_args == ["--model", "claude-opus-4-6-thinking", "tarea-prueba"]


# ---------------------------------------------------------------------------
# Tests de detección de desajuste de sesión (Paso 3 de reconciliación)
# ---------------------------------------------------------------------------


def test_list_shows_session_mismatch_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """list muestra advertencia de desajuste si el email de agy difiere de la cuenta activa."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "beta@example.com"])
    runner.invoke(app, ["set-active", "cuenta-1"])

    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "beta@example.com")

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Desajuste de cuenta detectado" in result.output
    assert "beta@example.com" in result.output
    assert "cuenta-2" in result.output
    assert "agyswitcher sync" in result.output


def test_status_shows_session_mismatch_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """status muestra advertencia de desajuste si el email en agy no coincide con la cuenta activa."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "alpha@example.com"])

    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "unknown@example.com")

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Desajuste de cuenta detectado" in result.output
    assert "unknown@example.com" in result.output
    assert "cuenta-1" in result.output
    assert "agyswitcher sync" in result.output


def test_check_session_mismatch_logic() -> None:
    """check_session_mismatch detecta adecuadamente las distintas variantes de discrepancia."""
    from agyswitcher.cli import check_session_mismatch
    from agyswitcher.models import Account

    accounts = {
        "acc1": Account(alias="acc1", email="acc1@example.com"),
        "acc2": Account(alias="acc2", email="acc2@example.com"),
        "no_email": Account(alias="no_email", email=None),
    }

    # Sin cuenta activa
    assert check_session_mismatch(accounts, None, "acc1@example.com") is None

    # Sin email detectado
    assert check_session_mismatch(accounts, "acc1", None) is None

    # Mismo email (sin desajuste)
    assert check_session_mismatch(accounts, "acc1", "acc1@example.com") is None

    # Desajuste con match en otra cuenta
    res = check_session_mismatch(accounts, "acc1", "acc2@example.com")
    assert res == ("acc2@example.com", "acc2")

    # Desajuste con email desconocido
    res_unknown = check_session_mismatch(accounts, "acc1", "other@example.com")
    assert res_unknown == ("other@example.com", None)

    # Cuenta activa sin email, pero el detectado pertenece a acc2
    res_no_email = check_session_mismatch(accounts, "no_email", "acc2@example.com")
    assert res_no_email == ("acc2@example.com", "acc2")

    # Cuenta activa sin email y detectado no pertenece a ninguna
    res_no_conflict = check_session_mismatch(accounts, "no_email", "random@example.com")
    assert res_no_conflict is None


def test_add_active_account_refreshes_quota_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Al registrar una cuenta que queda activa, add refresca y persiste métricas de cuota."""
    from agyswitcher.usage import PoolUsage, UsageReport

    fake_report = UsageReport(
        is_authenticated=True,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=85,
                reset_time=None,
                reset_raw="2026-11-15T12:00:00Z",
            ),
            "external": PoolUsage(
                pool="external",
                display_name="Claude and GPT models",
                metric="Weekly Limit Remaining",
                remaining_percent=70,
                reset_time=None,
                reset_raw="2026-11-15T12:00:00Z",
            ),
        },
    )

    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "metrics@example.com")
    with patch("agyswitcher.cli.fetch_usage", return_value=fake_report):
        result = runner.invoke(app, ["add", "cuenta-activa-metrics"])

    assert result.exit_code == 0
    assert "registrada y establecida como cuenta activa" in result.output
    assert "Cuota sincronizada: Gemini 85% | Otros 70%" in result.output

    state = load_state()
    assert "cuenta-activa-metrics" in state.accounts_quota
    info = state.accounts_quota["cuenta-activa-metrics"]
    assert info.gemini_percent == 85
    assert info.external_percent == 70


def test_add_active_account_graceful_on_fetch_usage_error() -> None:
    """Si fetch_usage falla al añadir una cuenta activa, el registro se completa con éxito sin error."""
    from agyswitcher.usage import UsageError

    with patch(
        "agyswitcher.cli.fetch_usage",
        side_effect=UsageError("Fallo simulado al consultar cuota"),
    ):
        result = runner.invoke(app, ["add", "cuenta-tolerante"])

    assert result.exit_code == 0
    assert "registrada y establecida como cuenta activa" in result.output

    state = load_state()
    assert state.active == "cuenta-tolerante"


def test_add_standby_account_skips_fetch_usage() -> None:
    """Al registrar una cuenta que NO queda activa, no se consulta fetch_usage."""
    # Primera cuenta queda activa
    runner.invoke(app, ["add", "cuenta-1"])

    mock_usage = MagicMock()
    with patch("agyswitcher.cli.fetch_usage", mock_usage):
        # Segunda cuenta sin --activate queda en standby
        result = runner.invoke(app, ["add", "cuenta-2", "--no-activate"])

    assert result.exit_code == 0
    assert "registrada correctamente" in result.output
    # No debe invocarse fetch_usage ya que la sesión en vivo no corresponde a la cuenta standby
    mock_usage.assert_not_called()


# ---------------------------------------------------------------------------
# Fase 5f-2b: cambio de cuenta guiado y verificado
# ---------------------------------------------------------------------------


def _two_accounts() -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])


def _login_result(monkeypatch: pytest.MonkeyPatch, status: str, email: str | None) -> MagicMock:
    from agyswitcher.session import LoginWaitResult, LoginWaitStatus

    mock = MagicMock(return_value=LoginWaitResult(LoginWaitStatus(status), email))
    monkeypatch.setattr("agyswitcher.cli.wait_for_login", mock)
    return mock


def test_rotate_guided_waits_for_target_email_and_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """El cambio solo se registra tras verificar el inicio de sesión con el email destino."""
    _two_accounts()
    wait = _login_ok(monkeypatch)

    result = runner.invoke(app, ["rotate", "cuenta-2", "--timeout", "30"])

    assert result.exit_code == 0, result.output
    assert "/logout" in result.output
    assert "dos@example.com" in result.output
    assert wait.call_args.args[0] == "dos@example.com"
    assert wait.call_args.kwargs["timeout"] == 30
    state = load_state()
    assert state.active == "cuenta-2"
    assert "cuenta-1 (gemini) -> cuenta-2" in state.switch_history[-1]


def test_rotate_guided_timeout_keeps_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin inicio de sesión a tiempo, la cuenta activa y el historial no cambian."""
    _two_accounts()
    _login_result(monkeypatch, "timeout", None)

    result = runner.invoke(app, ["rotate", "cuenta-2"])

    assert result.exit_code == 1
    assert "No se detectó el inicio de sesión con dos@example.com" in result.output
    assert "La cuenta activa sigue siendo 'cuenta-1'" in result.output
    state = load_state()
    assert state.active == "cuenta-1"
    assert state.switch_history == []


def test_rotate_guided_cancel_with_other_login_suggests_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si se cancela tras iniciar sesión con otra cuenta, se sugiere 'sync'."""
    _two_accounts()
    _login_result(monkeypatch, "cancelled", "otra@example.com")

    result = runner.invoke(app, ["rotate", "cuenta-2"])

    assert result.exit_code == 1
    assert "Cancelado por el usuario" in result.output
    assert "agyswitcher sync" in result.output
    assert load_state().active == "cuenta-1"


def test_rotate_guided_requires_target_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin email en la cuenta destino no se puede verificar: no se espera ni se cambia nada."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--no-activate"])
    wait = _login_ok(monkeypatch)

    result = runner.invoke(app, ["rotate", "cuenta-2"])

    assert result.exit_code == 1
    assert "no tiene email registrado" in result.output
    wait.assert_not_called()
    assert load_state().active == "cuenta-1"


def test_rotate_guided_warns_about_open_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con sesiones de agy abiertas se avisa (seguirán con la cuenta anterior) y se continúa."""
    _two_accounts()
    monkeypatch.setattr(
        "agyswitcher.cli.find_running_agy_processes", lambda: ["agy.exe", "Antigravity IDE.exe"]
    )
    _login_ok(monkeypatch)

    result = runner.invoke(app, ["rotate", "cuenta-2"])

    assert result.exit_code == 0, result.output
    assert "agy.exe, Antigravity IDE.exe" in result.output
    assert load_state().active == "cuenta-2"


def test_watch_proposes_account_change_without_switching(tmp_path: Path) -> None:
    """Con ambos pools agotados, watch propone la siguiente cuenta pero no cambia la activa."""
    _two_accounts()
    state = load_state()
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)
    fake_log = tmp_path / "cli.log"
    fake_log.write_text(
        "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for gemini\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["watch", "--once", "--log-file", str(fake_log)])

    assert result.exit_code == 0
    assert "Siguiente cuenta con cuota: 'cuenta-2' (dos@example.com)" in result.output
    assert "agyswitcher set-active cuenta-2" in result.output
    assert load_state().active == "cuenta-1"


def test_add_activate_refuses_when_session_is_other_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add --activate no activa una cuenta si agy tiene la sesión de otra."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    monkeypatch.setattr("agyswitcher.cli.detect_active_email", lambda: "uno@example.com")
    fetch = MagicMock()
    monkeypatch.setattr("agyswitcher.cli.fetch_usage", fetch)

    result = runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--activate"])

    assert result.exit_code == 0
    assert "agyswitcher set-active cuenta-2" in result.output
    assert load_state().active == "cuenta-1"
    fetch.assert_not_called()


def test_rotate_pool_change_does_not_wait_for_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cambiar de pool en la misma cuenta no requiere iniciar sesión."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)
    wait = _login_ok(monkeypatch)

    result = runner.invoke(app, ["rotate"])

    assert result.exit_code == 0
    assert "Cambiado pool" in result.output
    wait.assert_not_called()


def test_set_active_same_account_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reafirmar la cuenta ya activa no pide iniciar sesión."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    wait = _login_ok(monkeypatch)

    result = runner.invoke(app, ["set-active", "cuenta-1"])

    assert result.exit_code == 0
    wait.assert_not_called()


# ---------------------------------------------------------------------------
# Continuidad del proyecto: init, handoff y aviso de cuota baja
# ---------------------------------------------------------------------------


def test_init_creates_files_and_reports(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--agents", "gemini,claude"])

    assert result.exit_code == 0, result.output
    assert "Creado: AGENTS.md" in result.output
    assert (tmp_path / "GEMINI.md").exists()
    assert (tmp_path / "dev_mem" / "ESTADO.md").exists()

    again = runner.invoke(app, ["init", str(tmp_path)])
    assert "Ya existe (no se toca): AGENTS.md" in again.output


def test_init_rejects_unknown_agent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--agents", "gemini,chatgpt"])
    assert result.exit_code == 1
    assert "leen AGENTS.md" in result.output
    assert list(tmp_path.iterdir()) == []


def test_init_dry_run(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "Se crearía: AGENTS.md" in result.output
    assert list(tmp_path.iterdir()) == []


def test_handoff_uses_project_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".agyswitcher.toml").write_text(
        '[handoff]\nsave_prompt = "GUARDA-PERSONAL"\nresume_prompt = "RETOMA-PERSONAL"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["handoff"])
    assert result.exit_code == 0
    assert "GUARDA-PERSONAL" in result.output
    assert "RETOMA-PERSONAL" in result.output

    only_save = runner.invoke(app, ["handoff", "save"])
    assert "GUARDA-PERSONAL" in only_save.output
    assert "RETOMA-PERSONAL" not in only_save.output

    bad = runner.invoke(app, ["handoff", "otro"])
    assert bad.exit_code == 1


def _set_quota(alias: str, gemini: int | None) -> None:
    state = load_state()
    state.accounts_quota[alias] = AccountQuotaInfo(gemini_percent=gemini, external_percent=90)
    save_state(state)


def test_list_warns_on_low_quota_of_active_pool() -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    runner.invoke(app, ["add", "cuenta-2", "--email", "dos@example.com", "--no-activate"])
    _set_quota("cuenta-1", 10)

    result = runner.invoke(app, ["list", "--cached"])

    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    assert "Cuota baja en 'cuenta-1'" in flat
    assert "agyswitcher handoff save" in flat
    assert "Siguiente cuenta con cuota: 'cuenta-2'" in flat


def test_list_does_not_warn_with_enough_quota() -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    _set_quota("cuenta-1", 60)

    result = runner.invoke(app, ["list", "--cached"])

    assert "Cuota baja" not in result.output


def test_run_warns_on_low_quota_before_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    _set_quota("cuenta-1", 5)
    monkeypatch.setattr("agyswitcher.cli.run_agy_process", lambda **_k: 0)

    result = runner.invoke(app, ["run", "--", "--help"])

    assert "Cuota baja en 'cuenta-1'" in result.output


def test_verified_switch_shows_resume_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _two_accounts()
    _login_ok(monkeypatch)
    (tmp_path / ".agyswitcher.toml").write_text(
        '[handoff]\nresume_prompt = "RETOMA-AQUI"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["set-active", "cuenta-2"])

    assert result.exit_code == 0, result.output
    assert "RETOMA-AQUI" in result.output


# ---------------------------------------------------------------------------
# Atribución de cuota: solo a la cuenta cuyo email coincide con el informe de agy
# ---------------------------------------------------------------------------


def _report_for(email: str | None, pct: int = 42) -> UsageReport:
    return UsageReport(
        is_authenticated=True,
        active_email=email,
        pools={
            "gemini": PoolUsage(
                pool="gemini",
                display_name="Gemini Models",
                metric="Weekly Limit Remaining",
                remaining_percent=pct,
                reset_time=datetime.now(UTC) + timedelta(days=3),
                reset_raw="2026-11-21T12:00:00Z",
            )
        },
    )


def test_set_active_ignores_quota_report_of_other_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si tras el cambio agy informa de otra cuenta, no se guarda esa cuota en la destino."""
    _two_accounts()
    _login_ok(monkeypatch)
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage", MagicMock(return_value=_report_for("otra@example.com"))
    )

    result = runner.invoke(app, ["set-active", "cuenta-2"])

    assert result.exit_code == 0, result.output
    assert "Cuota sincronizada" not in result.output
    assert load_state().accounts_quota.get("cuenta-2") is None


def test_set_active_stores_quota_when_report_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    _two_accounts()
    _login_ok(monkeypatch)
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage", MagicMock(return_value=_report_for("dos@example.com"))
    )

    result = runner.invoke(app, ["set-active", "cuenta-2"])

    assert "Cuota sincronizada: Gemini 42%" in result.output
    assert load_state().accounts_quota["cuenta-2"].gemini_percent == 42


def test_status_live_stores_quota_in_report_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """status --live guarda la cuota en la cuenta del informe, no en la activa."""
    _two_accounts()
    monkeypatch.setattr(
        "agyswitcher.cli.fetch_usage", MagicMock(return_value=_report_for("dos@example.com", 7))
    )

    runner.invoke(app, ["status", "--live"])

    state = load_state()
    assert state.accounts_quota.get("cuenta-1") is None
    assert state.accounts_quota["cuenta-2"].gemini_percent == 7


# ---------------------------------------------------------------------------
# run: propuesta de cómo continuar tras una cuota agotada (5f)
# ---------------------------------------------------------------------------

_GEMINI_429 = "google.api_core.exceptions.ResourceExhausted: 429 Quota exceeded for gemini\n"
_CLAUDE_429 = "RESOURCE_EXHAUSTED: 429 Quota exceeded for claude-sonnet\n"


def _fake_agy(lines: list[str], code: int = 1) -> object:
    def _runner(args: list[str], *, on_line: object = None, **_kwargs: object) -> int:
        for line in lines:
            if callable(on_line):
                on_line(line)
        return code

    return _runner


def test_run_proposes_next_account_when_active_fully_exhausted() -> None:
    """Con los dos pools de la activa agotados, run propone la siguiente cuenta sin cambiarla."""
    _two_accounts()
    state = load_state()
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)

    with patch("agyswitcher.cli.run_agy_process", side_effect=_fake_agy([_GEMINI_429])):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Cuota agotada (gemini) en 'cuenta-1'" in result.output
    assert "Durante la ejecución se agotó la cuota (gemini)" in result.output
    assert "Siguiente cuenta con cuota: 'cuenta-2' (dos@example.com)" in result.output
    assert "agyswitcher set-active cuenta-2" in result.output
    assert "agyswitcher handoff save" in result.output
    assert load_state().active == "cuenta-1"


def test_run_switches_pool_when_other_pool_available() -> None:
    """Si la activa aún tiene el otro pool, run cambia de pool al terminar agy."""
    _two_accounts()

    with patch("agyswitcher.cli.run_agy_process", side_effect=_fake_agy([_GEMINI_429])):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 1
    assert "Vuelve a ejecutar agyswitcher run" in result.output
    state = load_state()
    assert state.active == "cuenta-1"
    assert state.active_model_group == "external"


def test_run_reports_all_accounts_exhausted() -> None:
    """Si no queda ninguna cuenta con cuota, run lo indica."""
    runner.invoke(app, ["add", "cuenta-1", "--email", "uno@example.com"])
    state = load_state()
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)

    with patch("agyswitcher.cli.run_agy_process", side_effect=_fake_agy([_GEMINI_429])):
        result = runner.invoke(app, ["run"])

    assert "Todas las cuentas tienen la cuota agotada" in result.output
    assert load_state().active == "cuenta-1"


def test_run_proposes_even_if_exhaustion_was_already_recorded() -> None:
    """La propuesta aparece aunque la cuota agotada ya constara en el estado."""
    _two_accounts()
    state = load_state()
    state.gemini_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    state.external_quota_exhausted["cuenta-1"] = "2026-11-04T12:00:00Z"
    save_state(state)

    with patch("agyswitcher.cli.run_agy_process", side_effect=_fake_agy([_GEMINI_429] * 3)):
        result = runner.invoke(app, ["run"])

    assert result.output.count("[AgySwitcher] Cuota agotada") == 1
    assert "agyswitcher set-active cuenta-2" in result.output


def test_run_without_quota_errors_prints_no_proposal() -> None:
    _two_accounts()

    with patch("agyswitcher.cli.run_agy_process", side_effect=_fake_agy(["hola\n"], code=0)):
        result = runner.invoke(app, ["run"])

    assert result.exit_code == 0
    assert "Siguiente cuenta" not in result.output
    assert "Durante la ejecución" not in result.output


def test_watch_keeps_account_when_other_pool_exhausted(tmp_path: Path) -> None:
    """Si se agota el pool que no está en uso, no se propone cambiar de cuenta."""
    _two_accounts()
    fake_log = tmp_path / "cli.log"
    fake_log.write_text(_CLAUDE_429, encoding="utf-8")

    result = runner.invoke(app, ["watch", "--once", "--log-file", str(fake_log)])

    assert result.exit_code == 0
    assert "siguen disponibles" in result.output
    assert "Siguiente cuenta" not in result.output
    state = load_state()
    assert state.active == "cuenta-1"
    assert state.active_model_group == "gemini"
