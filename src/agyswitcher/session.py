# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: session.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-18
Ultimo cambio: 2026-11-20

Descripción: Verificación de inicios de sesión de agy mediante contenido nuevo de los logs.

agy guarda una única sesión de Google en el almacén de credenciales del sistema; la
cuenta solo cambia cuando el usuario cierra e inicia sesión en agy. Para confirmar un
cambio de cuenta hay que comprobar que el usuario ha iniciado sesión DESPUÉS de empezar
el cambio. Este módulo toma una marca de los logs (tamaño de cada fichero) y busca el
evento de inicio de sesión solo en lo escrito a partir de esa marca, de modo que un
inicio de sesión antiguo que ya estuviera en los logs no cuenta como verificación.

Solo se leen líneas de log; nunca tokens ni credenciales. Su contenido se trata como
dato no confiable.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_LOGIN_EVENT_PATTERN = re.compile(
    r"OAuth:\s+authenticated successfully as\s+([\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+)",
    re.IGNORECASE,
)
"""Evento que agy escribe al completar un inicio de sesión (también 'consumerOAuth:')."""

MAX_NEW_BYTES_PER_FILE = 4 * 1024 * 1024
"""Máximo de bytes nuevos analizados por fichero; si hay más, se analizan los últimos."""


def default_session_log_dir() -> Path:
    """Directorio de logs de agy en la carpeta viva (~/.gemini/antigravity-cli)."""
    return Path.home() / ".gemini" / "antigravity-cli"


def _session_log_files(base_dir: Path) -> list[Path]:
    """Devuelve 'cli.log' y los ficheros 'log/*.log' existentes bajo 'base_dir'."""
    files: list[Path] = []
    primary = base_dir / "cli.log"
    if primary.is_file():
        files.append(primary)
    log_dir = base_dir / "log"
    if log_dir.is_dir():
        with contextlib.suppress(OSError):
            files.extend(p for p in log_dir.iterdir() if p.is_file() and p.suffix == ".log")
    return files


def snapshot_log_offsets(base_dir: Path | None = None) -> dict[Path, int]:
    """Toma una marca de los logs: el tamaño actual de cada fichero.

    Args:
        base_dir: Directorio de antigravity-cli (None usa el de la carpeta viva).

    Returns:
        Diccionario ruta -> tamaño en bytes. Los ficheros que no se pueden consultar se omiten
        (se analizarán completos más adelante, lo que es conservador pero seguro).
    """
    root = base_dir or default_session_log_dir()
    offsets: dict[Path, int] = {}
    for path in _session_log_files(root):
        with contextlib.suppress(OSError):
            offsets[path] = path.stat().st_size
    return offsets


def extract_login_email(text: str) -> str | None:
    """Devuelve el email del ÚLTIMO evento de inicio de sesión del texto, o None."""
    email: str | None = None
    for match in _LOGIN_EVENT_PATTERN.finditer(text):
        email = match.group(1).strip()
    return email


def read_log_tail(path: Path) -> str:
    """Lee como mucho los últimos MAX_NEW_BYTES_PER_FILE bytes del log, en líneas completas.

    Raises:
        OSError: Si el fichero no se puede leer.
    """
    return _read_new_complete_lines(path, 0)


def _read_new_complete_lines(path: Path, start: int) -> str:
    """Lee el contenido escrito desde 'start' hasta el último salto de línea completo."""
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        if size < start:
            start = 0  # El fichero se ha truncado o recreado: todo su contenido es nuevo.
        start = max(start, size - MAX_NEW_BYTES_PER_FILE)
        handle.seek(start)
        data = handle.read(size - start)
    last_newline = data.rfind(b"\n")
    if last_newline < 0:
        return ""  # Línea aún a medio escribir: se evaluará en la siguiente consulta.
    return data[: last_newline + 1].decode("utf-8", errors="replace")


class LogFollower:
    """Sigue las líneas nuevas de los logs de agy a partir de una marca.

    La marca se toma al crearlo. Los ficheros que aparecen después (agy crea un log nuevo en
    cada arranque) se leen desde el principio. Solo devuelve líneas completas; una línea a
    medio escribir se entrega en la siguiente consulta. ``cli.log`` es un enlace duro al log
    más reciente de ``log/``, así que una misma línea puede llegar dos veces: quien la procese
    debe tolerar duplicados.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._root = base_dir or default_session_log_dir()
        self._offsets = snapshot_log_offsets(self._root)

    def poll(self) -> list[str]:
        """Devuelve las líneas completas escritas desde la consulta anterior."""
        lines: list[str] = []
        for path in _session_log_files(self._root):
            start = self._offsets.get(path, 0)
            try:
                with path.open("rb") as handle:
                    size = handle.seek(0, 2)
                    if size < start:
                        start = 0  # Truncado o recreado: todo su contenido es nuevo.
                    start = max(start, size - MAX_NEW_BYTES_PER_FILE)
                    handle.seek(start)
                    data = handle.read(size - start)
            except OSError:
                continue
            last_newline = data.rfind(b"\n")
            if last_newline < 0:
                self._offsets[path] = start
                continue
            self._offsets[path] = start + last_newline + 1
            text = data[: last_newline + 1].decode("utf-8", errors="replace")
            lines.extend(text.splitlines())
        return lines


def detect_new_login_email(
    offsets: dict[Path, int],
    base_dir: Path | None = None,
) -> str | None:
    """Busca un inicio de sesión de agy en el contenido escrito después de la marca.

    Args:
        offsets: Marca tomada con 'snapshot_log_offsets'. Los ficheros que no figuran en
            ella se consideran nuevos y se analizan desde el principio.
        base_dir: Directorio de antigravity-cli (None usa el de la carpeta viva).

    Returns:
        Email del inicio de sesión más reciente posterior a la marca, o None si no lo hay.
    """
    root = base_dir or default_session_log_dir()
    found: list[tuple[float, str]] = []
    for path in _session_log_files(root):
        try:
            mtime = path.stat().st_mtime
            text = _read_new_complete_lines(path, offsets.get(path, 0))
        except OSError:
            continue
        email = extract_login_email(text)
        if email:
            found.append((mtime, email))
    if not found:
        return None
    return max(found, key=lambda item: item[0])[1]


DEFAULT_LOGIN_TIMEOUT = 300.0
"""Tiempo máximo por defecto (segundos) para esperar el inicio de sesión del usuario."""

DEFAULT_POLL_INTERVAL = 2.0
"""Intervalo de sondeo de los logs (segundos)."""


class LoginWaitStatus(Enum):
    """Resultado de la espera de un inicio de sesión."""

    VERIFIED = "verified"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class LoginWaitResult:
    """Resultado de 'wait_for_login'."""

    status: LoginWaitStatus
    detected_email: str | None
    """Último email de inicio de sesión detectado tras la marca (None si no hubo ninguno)."""


def wait_for_login(
    expected_email: str,
    offsets: dict[Path, int],
    *,
    base_dir: Path | None = None,
    timeout: float = DEFAULT_LOGIN_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    on_other_login: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> LoginWaitResult:
    """Espera a que el usuario inicie sesión en agy con 'expected_email'.

    Sondea los logs escritos después de la marca 'offsets'. Si se detecta un inicio de
    sesión con otra cuenta, se notifica (una vez por email distinto) y se sigue esperando,
    para que el usuario pueda repetir el inicio de sesión con la cuenta correcta.
    Ctrl+C durante la espera devuelve CANCELLED.

    Args:
        expected_email: Email de la cuenta destino (se compara sin distinguir mayúsculas).
        offsets: Marca tomada con 'snapshot_log_offsets' antes de pedir el inicio de sesión.
        base_dir: Directorio de antigravity-cli (None usa el de la carpeta viva).
        timeout: Tiempo máximo de espera en segundos.
        poll_interval: Segundos entre comprobaciones.
        on_other_login: Llamada con el email cuando se inicia sesión con otra cuenta.
        sleep: Función de espera (inyectable en tests).
        clock: Reloj monótono (inyectable en tests).

    Returns:
        LoginWaitResult con el estado final y el último email detectado.
    """
    expected = expected_email.strip().lower()
    deadline = clock() + timeout
    last_email: str | None = None
    notified: set[str] = set()
    try:
        while True:
            email = detect_new_login_email(offsets, base_dir)
            if email:
                last_email = email
                if email.lower() == expected:
                    return LoginWaitResult(LoginWaitStatus.VERIFIED, email)
                if email.lower() not in notified:
                    notified.add(email.lower())
                    if on_other_login is not None:
                        on_other_login(email)
            if clock() >= deadline:
                return LoginWaitResult(LoginWaitStatus.TIMEOUT, last_email)
            sleep(poll_interval)
    except KeyboardInterrupt:
        return LoginWaitResult(LoginWaitStatus.CANCELLED, last_email)
