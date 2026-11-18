# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests de verificación de inicio de sesión por contenido nuevo de logs (5f-2a)."""

from __future__ import annotations

import os
from pathlib import Path

from agyswitcher.session import (
    LoginWaitResult,
    LoginWaitStatus,
    detect_new_login_email,
    extract_login_email,
    snapshot_log_offsets,
    wait_for_login,
)

LOGIN_A = "I1118 10:00:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as a@example.com\n"
LOGIN_B = "I1118 10:05:00.000000  1 server_oauth.go:226] OAuth: authenticated successfully as b@example.com\n"
CONSUMER_B = "I1118 10:05:00.000000  1 browser.go:167] consumerOAuth: authenticated successfully as b@example.com\n"
NOISE = (
    "I1118 10:01:00.000000  1 keyring.go:10] keyringAuth: loaded token, expiry=x expired=false\n"
)


def _base(tmp_path: Path) -> Path:
    base = tmp_path / "antigravity-cli"
    (base / "log").mkdir(parents=True)
    return base


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(text)


def test_extract_login_email_returns_last_event() -> None:
    assert extract_login_email(LOGIN_A + NOISE + LOGIN_B) == "b@example.com"
    assert extract_login_email(CONSUMER_B) == "b@example.com"
    assert extract_login_email(NOISE) is None


def test_old_login_before_snapshot_is_ignored(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, LOGIN_A)
    offsets = snapshot_log_offsets(base)
    _append(log, NOISE)
    assert detect_new_login_email(offsets, base) is None


def test_login_after_snapshot_is_detected(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, LOGIN_A)
    offsets = snapshot_log_offsets(base)
    _append(log, NOISE + LOGIN_B)
    assert detect_new_login_email(offsets, base) == "b@example.com"


def test_new_log_file_is_read_from_start(tmp_path: Path) -> None:
    base = _base(tmp_path)
    _append(base / "cli.log", LOGIN_A)
    offsets = snapshot_log_offsets(base)
    _append(base / "log" / "cli-2.log", CONSUMER_B)
    assert detect_new_login_email(offsets, base) == "b@example.com"


def test_truncated_file_is_read_from_start(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, LOGIN_A * 5)
    offsets = snapshot_log_offsets(base)
    log.write_text(LOGIN_B, encoding="utf-8", newline="")
    assert detect_new_login_email(offsets, base) == "b@example.com"


def test_incomplete_line_is_not_trusted(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, NOISE)
    offsets = snapshot_log_offsets(base)
    _append(log, LOGIN_B.rstrip("\n")[:-4])  # 'b@example' a medio escribir
    assert detect_new_login_email(offsets, base) is None
    _append(log, LOGIN_B.rstrip("\n")[-4:] + "\n")
    assert detect_new_login_email(offsets, base) == "b@example.com"


def test_most_recent_file_wins(tmp_path: Path) -> None:
    base = _base(tmp_path)
    offsets = snapshot_log_offsets(base)
    older = base / "log" / "old.log"
    newer = base / "log" / "new.log"
    _append(older, LOGIN_A)
    _append(newer, LOGIN_B)
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    assert detect_new_login_email(offsets, base) == "b@example.com"


def test_missing_dir_returns_none(tmp_path: Path) -> None:
    base = tmp_path / "missing"
    assert snapshot_log_offsets(base) == {}
    assert detect_new_login_email({}, base) is None


# ---------------------------------------------------------------------------
# 5f-2b: espera del inicio de sesión
# ---------------------------------------------------------------------------


class _FakeClock:
    """Reloj y espera simulados: cada 'sleep' avanza el tiempo y puede escribir en el log."""

    def __init__(self, on_sleep: list[str], log: Path) -> None:
        self.now = 0.0
        self.pending = list(on_sleep)
        self.log = log
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds
        if self.pending:
            _append(self.log, self.pending.pop(0))


def test_wait_for_login_verifies_expected_email(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, LOGIN_A)
    offsets = snapshot_log_offsets(base)
    fake = _FakeClock([NOISE, LOGIN_B], log)

    result = wait_for_login(
        "B@example.com", offsets, base_dir=base, timeout=60, sleep=fake.sleep, clock=fake.clock
    )

    assert result == LoginWaitResult(LoginWaitStatus.VERIFIED, "b@example.com")
    assert fake.sleeps == 2


def test_wait_for_login_reports_other_account_once_and_keeps_waiting(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    offsets = snapshot_log_offsets(base)
    fake = _FakeClock([LOGIN_A, NOISE, LOGIN_B], log)
    others: list[str] = []

    result = wait_for_login(
        "b@example.com",
        offsets,
        base_dir=base,
        timeout=60,
        on_other_login=others.append,
        sleep=fake.sleep,
        clock=fake.clock,
    )

    assert result.status is LoginWaitStatus.VERIFIED
    assert others == ["a@example.com"]


def test_wait_for_login_ignores_old_login_and_times_out(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    _append(log, LOGIN_B)  # Inicio de sesión antiguo del perfil destino: no cuenta.
    offsets = snapshot_log_offsets(base)
    fake = _FakeClock([], log)

    result = wait_for_login(
        "b@example.com",
        offsets,
        base_dir=base,
        timeout=10,
        poll_interval=2,
        sleep=fake.sleep,
        clock=fake.clock,
    )

    assert result == LoginWaitResult(LoginWaitStatus.TIMEOUT, None)
    assert fake.sleeps == 5


def test_wait_for_login_ctrl_c_cancels(tmp_path: Path) -> None:
    base = _base(tmp_path)
    log = base / "cli.log"
    offsets = snapshot_log_offsets(base)
    _append(log, LOGIN_A)

    def _interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    result = wait_for_login("b@example.com", offsets, base_dir=base, sleep=_interrupt)

    assert result == LoginWaitResult(LoginWaitStatus.CANCELLED, "a@example.com")
