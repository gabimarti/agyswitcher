# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del analizador y consultor de cuota (usage.py)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agyswitcher.models import AppState
from agyswitcher.runner import AgyNotFoundError
from agyswitcher.usage import (
    AuthRequiredError,
    PoolUsage,
    UsageError,
    UsageReport,
    detect_active_email,
    fetch_usage,
    format_time_remaining,
    parse_usage_output,
    update_state_from_usage_report,
)


def test_pool_usage_properties() -> None:
    pool = PoolUsage(
        pool="gemini",
        display_name="Gemini Models",
        metric="Weekly Limit Remaining",
        remaining_percent=95,
        reset_time=datetime(2026, 11, 12, 9, 32, 16, tzinfo=UTC),
        reset_raw="2026-11-12T09:32:16Z",
    )
    assert pool.consumed_percent == 5
    assert not pool.is_exhausted
    d = pool.to_dict()
    assert d["pool"] == "gemini"
    assert d["consumed_percent"] == 5
    assert d["is_exhausted"] is False

    exhausted_pool = PoolUsage(
        pool="external",
        display_name="Claude and GPT models",
        metric="Weekly Limit Remaining",
        remaining_percent=0,
        reset_time=None,
        reset_raw="",
    )
    assert exhausted_pool.consumed_percent == 100
    assert exhausted_pool.is_exhausted is True


def test_format_time_remaining() -> None:
    now = datetime(2026, 11, 5, 10, 0, 0, tzinfo=UTC)

    assert format_time_remaining(None) == "Desconocido"

    # 3 días y 4 horas
    t1 = now + timedelta(days=3, hours=4, minutes=10)
    assert format_time_remaining(t1, now=now) == "3d 4h"

    # 5 horas y 30 minutos
    t2 = now + timedelta(hours=5, minutes=30)
    assert format_time_remaining(t2, now=now) == "5h 30m"

    # 45 minutos
    t3 = now + timedelta(minutes=45)
    assert format_time_remaining(t3, now=now) == "45m"

    # Pasado
    t4 = now - timedelta(minutes=10)
    assert format_time_remaining(t4, now=now) == "En reinicio"


def test_parse_usage_output_valid_tsv() -> None:
    sample = (
        "Gemini Models\tWeekly Limit Remaining\t95%\t2026-11-12T09:32:16Z\n"
        "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-11-12T10:05:32Z\n"
    )
    report = parse_usage_output(sample)
    assert report.is_authenticated is True
    assert "gemini" in report.pools
    assert "external" in report.pools

    gemini = report.pools["gemini"]
    assert gemini.remaining_percent == 95
    assert gemini.consumed_percent == 5
    assert gemini.reset_time == datetime(2026, 11, 12, 9, 32, 16, tzinfo=UTC)

    external = report.pools["external"]
    assert external.remaining_percent == 100
    assert external.consumed_percent == 0
    assert external.reset_time == datetime(2026, 11, 12, 10, 5, 32, tzinfo=UTC)


def test_parse_usage_output_space_separated() -> None:
    sample = (
        "Gemini Models    Weekly Limit Remaining    60%    2026-11-12T09:32:16Z\n"
        "Claude and GPT models    Weekly Limit Remaining    20%    2026-11-12T10:05:32Z\n"
    )
    report = parse_usage_output(sample)
    assert report.is_authenticated is True
    assert report.pools["gemini"].remaining_percent == 60
    assert report.pools["external"].remaining_percent == 20


def test_parse_usage_output_empty_or_whitespace() -> None:
    report = parse_usage_output("")
    assert report.is_authenticated is False
    assert len(report.pools) == 0


def test_parse_usage_output_auth_error_detected() -> None:
    sample = "Please log in using Google to use Antigravity CLI."
    report = parse_usage_output(sample)
    assert report.is_authenticated is False
    assert len(report.pools) == 0


def test_fetch_usage_success(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout_sample = (
        "Gemini Models\tWeekly Limit Remaining\t95%\t2026-11-12T09:32:16Z\n"
        "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-11-12T10:05:32Z\n"
    )
    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=stdout_sample, stderr=""))
    monkeypatch.setattr("agyswitcher.usage.run_captured", mock_run)

    report = fetch_usage(agy_path=Path("C:/dummy/agy.exe"))
    assert report.is_authenticated is True
    assert report.pools["gemini"].remaining_percent == 95
    mock_run.assert_called_once()


def test_fetch_usage_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["agy"], timeout=5.0)

    monkeypatch.setattr("agyswitcher.usage.run_captured", _timeout)
    with pytest.raises(UsageError, match="Tiempo de espera agotado"):
        fetch_usage(timeout=5.0, agy_path=Path("C:/dummy/agy.exe"))


def test_fetch_usage_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(
        return_value=MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: unauthorized, please log in with google to proceed.",
        )
    )
    monkeypatch.setattr("agyswitcher.usage.run_captured", mock_run)

    with pytest.raises(AuthRequiredError, match="Sesión no iniciada"):
        fetch_usage(agy_path=Path("C:/dummy/agy.exe"))


def test_fetch_usage_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_run = MagicMock(
        return_value=MagicMock(
            returncode=2,
            stdout="",
            stderr="Internal server crash 500",
        )
    )
    monkeypatch.setattr("agyswitcher.usage.run_captured", mock_run)

    with pytest.raises(UsageError, match="finalizó con código 2"):
        fetch_usage(agy_path=Path("C:/dummy/agy.exe"))


def test_fetch_usage_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_not_found() -> Path:
        raise AgyNotFoundError("agy not found")

    monkeypatch.setattr("agyswitcher.usage.find_agy_executable", _raise_not_found)
    with pytest.raises(AgyNotFoundError):
        fetch_usage(agy_path=None)


def test_detect_active_email_from_apply_auth_result(tmp_path: Path) -> None:
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1106 10:00:00 cache.go:100] Starting\n"
        "I1106 10:00:01 server_oauth.go:221] applyAuthResult: email=tester@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    email = detect_active_email(base_dir=tmp_path)
    assert email == "tester@example.com"


def test_detect_active_email_from_oauth_line(tmp_path: Path) -> None:
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1106 10:00:00 keyring.go:64] keyringAuth: loaded token\n"
        "I1106 10:00:01 server_oauth.go:226] OAuth: authenticated successfully as dev.user@example.com\n",
        encoding="utf-8",
    )
    email = detect_active_email(base_dir=tmp_path)
    assert email == "dev.user@example.com"


def test_detect_active_email_from_rotated_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    rotated_file = log_dir / "cli-20261106-100000.log"
    rotated_file.write_text(
        "I1106 10:00:01 server_oauth.go:221] applyAuthResult: email=rotated@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    email = detect_active_email(base_dir=tmp_path)
    assert email == "rotated@example.com"


def test_detect_active_email_prefers_newer_rotated_log_over_stale_cli_log(tmp_path: Path) -> None:
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1106 10:00:01 server_oauth.go:221] applyAuthResult: email=stale@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    # cli.log con mtime antiguo
    os.utime(cli_log, (1000, 1000))

    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    newer_rotated = log_dir / "cli-20261110-180000.log"
    newer_rotated.write_text(
        "I1110 18:00:01 server_oauth.go:221] applyAuthResult: email=fresh@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    # newer_rotated con mtime más reciente
    os.utime(newer_rotated, (2000, 2000))

    email = detect_active_email(base_dir=tmp_path)
    assert email == "fresh@example.com"


def test_detect_active_email_prefers_newer_cli_log_over_stale_rotated_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    older_rotated = log_dir / "cli-20261110-170000.log"
    older_rotated.write_text(
        "I1110 17:00:01 server_oauth.go:221] applyAuthResult: email=old_rotated@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    os.utime(older_rotated, (1000, 1000))

    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1110 19:00:01 server_oauth.go:221] applyAuthResult: email=new_primary@example.com, authMethod=consumer\n",
        encoding="utf-8",
    )
    os.utime(cli_log, (2000, 2000))

    email = detect_active_email(base_dir=tmp_path)
    assert email == "new_primary@example.com"


def test_detect_active_email_returns_none_when_empty(tmp_path: Path) -> None:
    assert detect_active_email(base_dir=tmp_path) is None


def test_update_state_from_usage_report() -> None:
    """update_state_from_usage_report persiste métricas y sincroniza cooldowns."""
    state = AppState(active="amanda")
    now = datetime(2026, 11, 6, 19, 0, 0, tzinfo=UTC)
    reset_gemini = datetime(2026, 11, 13, 19, 0, 0, tzinfo=UTC)

    pools = {
        "gemini": PoolUsage(
            pool="gemini",
            display_name="Gemini Models",
            metric="Weekly Limit Remaining",
            remaining_percent=85,
            reset_time=reset_gemini,
            reset_raw="2026-11-13T19:00:00Z",
        ),
        "external": PoolUsage(
            pool="external",
            display_name="Claude and GPT models",
            metric="Weekly Limit Remaining",
            remaining_percent=0,
            reset_time=None,
            reset_raw="",
        ),
    }
    report = UsageReport(
        is_authenticated=True,
        pools=pools,
        timestamp=now,
    )

    changed = update_state_from_usage_report(state, "amanda", report, sync_cooldowns=True)
    assert changed is True
    assert "amanda" in state.accounts_quota
    info = state.accounts_quota["amanda"]
    assert info.gemini_percent == 85
    assert info.gemini_reset_time == reset_gemini
    assert info.external_percent == 0
    assert info.updated_at == now

    # Cooldowns sincronizados: external al 0% entra en cooldown
    assert "amanda" in state.external_quota_exhausted
    assert "amanda" not in state.gemini_quota_exhausted

    # Segunda lectura con external recuperado
    pools_recovered = {
        "gemini": pools["gemini"],
        "external": PoolUsage(
            pool="external",
            display_name="Claude and GPT models",
            metric="Weekly Limit Remaining",
            remaining_percent=100,
            reset_time=reset_gemini,
            reset_raw="",
        ),
    }
    report_recovered = UsageReport(
        is_authenticated=True,
        pools=pools_recovered,
        timestamp=now,
    )
    update_state_from_usage_report(state, "amanda", report_recovered, sync_cooldowns=True)
    assert state.accounts_quota["amanda"].external_percent == 100
    assert "amanda" not in state.external_quota_exhausted  # cooldown levantado


# ---------------------------------------------------------------------------
# Revisión de seguridad (2026-11-19): INFO-01 y emails detectados válidos
# ---------------------------------------------------------------------------


def test_detect_active_email_reads_only_the_end_of_big_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Solo se lee el final de cada log: un evento anterior a ese tramo no cuenta."""
    monkeypatch.setattr("agyswitcher.session.MAX_NEW_BYTES_PER_FILE", 1024)
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as viejo@example.com\n"
        + ("x" * 80 + "\n") * 100,
        encoding="utf-8",
    )
    assert detect_active_email(base_dir=tmp_path) is None

    with cli_log.open("a", encoding="utf-8") as handle:
        handle.write(
            "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as nuevo@example.com\n"
        )
    assert detect_active_email(base_dir=tmp_path) == "nuevo@example.com"


def test_detect_active_email_ignores_malformed_addresses(tmp_path: Path) -> None:
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as valido@example.com\n"
        "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as sin-dominio@localhost\n",
        encoding="utf-8",
    )
    assert detect_active_email(base_dir=tmp_path) == "valido@example.com"


def test_sync_renews_exhaustion_date_when_reset_already_passed() -> None:
    """Si la consulta confirma el agotado y el reinicio previsto ya pasó, se renueva la fecha."""
    from datetime import UTC, datetime

    from agyswitcher.models import AppState
    from agyswitcher.usage import PoolUsage, UsageReport, update_state_from_usage_report

    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    state = AppState()
    state.gemini_quota_exhausted["a"] = "2026-11-01T12:00:00+00:00"  # reinicio previsto 11-08
    state.external_quota_exhausted["a"] = "2026-11-18T12:00:00+00:00"  # aún vigente
    report = UsageReport(
        is_authenticated=True,
        timestamp=now,
        pools={
            "gemini": PoolUsage("gemini", "Gemini", "Weekly", 0, None, ""),
            "external": PoolUsage("external", "Otros", "Weekly", 0, None, ""),
        },
    )
    update_state_from_usage_report(state, "a", report)
    assert state.gemini_quota_exhausted["a"] == now.isoformat()
    assert state.external_quota_exhausted["a"] == "2026-11-18T12:00:00+00:00"
    assert state.is_pool_blocked("a", "gemini", now)


def test_is_quota_stale_handles_none_or_missing_date() -> None:
    from agyswitcher.models import AccountQuotaInfo
    from agyswitcher.usage import is_quota_stale

    assert is_quota_stale(None) is True

    info_no_date = AccountQuotaInfo()
    object.__setattr__(info_no_date, "updated_at", None)
    assert is_quota_stale(info_no_date) is True


def test_is_quota_stale_considers_ttl() -> None:
    from agyswitcher.models import AccountQuotaInfo
    from agyswitcher.usage import DEFAULT_QUOTA_TTL_SECONDS, is_quota_stale

    now = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)

    # Actualizado hace 60 segundos (< 180s): fresco
    info_fresh = AccountQuotaInfo(updated_at=now - timedelta(seconds=60))
    assert is_quota_stale(info_fresh, now=now) is False

    # Actualizado hace 200 segundos (> 180s): obsoleto
    info_stale = AccountQuotaInfo(updated_at=now - timedelta(seconds=200))
    assert is_quota_stale(info_stale, now=now) is True

    # Comprobación de TTL personalizado
    assert is_quota_stale(info_fresh, ttl_seconds=30.0, now=now) is True
    assert is_quota_stale(info_stale, ttl_seconds=300.0, now=now) is False
    assert DEFAULT_QUOTA_TTL_SECONDS == 180.0


def test_detect_active_email_ignores_lines_without_glog_header(tmp_path: Path) -> None:
    """Un texto que imita el evento pero no es una línea de log de agy no cuenta."""
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as "
        "real@example.com\n"
        "usuario dijo: OAuth: authenticated successfully as falso@example.com\n"
        "I1124 10:00:01.000000  1 chat.go:10] Cache(userInfo) otro@example.com\n",
        encoding="utf-8",
    )
    assert detect_active_email(base_dir=tmp_path) == "real@example.com"


def test_detect_active_email_rejects_non_ascii_addresses(tmp_path: Path) -> None:
    """Los emails con caracteres no ASCII no se aceptan como sesión de agy."""
    cli_log = tmp_path / "cli.log"
    cli_log.write_text(
        "I1124 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as "
        "usuarió@exámple.com\n",
        encoding="utf-8",
    )
    assert detect_active_email(base_dir=tmp_path) is None
