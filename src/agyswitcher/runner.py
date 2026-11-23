# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: runner.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-23

Descripción: Módulo runner para la ejecución segura de Antigravity CLI (agy) en Windows.

Proporciona localización del ejecutable agy.exe, sanitización en memoria
de credenciales y secretos, y ciclo de vida de procesos hijo.
"""

from __future__ import annotations

import contextlib
import csv
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


class RunnerError(Exception):
    """Error base de ejecución del runner."""


class AgyNotFoundError(RunnerError):
    """No se encontró el ejecutable agy.exe en el sistema."""


# Patrones de redacción de información sensible en salidas y trazas
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+[a-zA-Z0-9_\-\.]+")
_AUTH_HEADER_PATTERN = re.compile(r"(?i)\b(authorization\s*[:=]\s*)[^\r\n,;]+")
_TOKEN_PARAM_PATTERN = re.compile(
    r"(?i)\b((?:access_token|refresh_token|token|api_key)\s*[:=]\s*['\"]?)[^'\"\s,;&]+(['\"]?)"
)
_COOKIE_PATTERN = re.compile(r"(?i)\b(cookie\s*[:=]\s*)[^\r\n]+")
_URL_TOKEN_PATTERN = re.compile(r"(?i)([?&](?:access_token|refresh_token|token|api_key)=)[^&\s,;]+")


def sanitize_line(line: str) -> str:
    """Redacta tokens, contraseñas, cookies y cabeceras de autorización de una línea.

    Args:
        line: Cadena de texto a sanitizar.

    Returns:
        Cadena con todos los patrones sensibles reemplazados por [REDACTED].
    """
    sanitized = _BEARER_PATTERN.sub(r"\1 [REDACTED]", line)
    sanitized = _AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", sanitized)
    sanitized = _TOKEN_PARAM_PATTERN.sub(r"\1[REDACTED]\2", sanitized)
    sanitized = _COOKIE_PATTERN.sub(r"\1[REDACTED]", sanitized)
    sanitized = _URL_TOKEN_PATTERN.sub(r"\1[REDACTED]", sanitized)
    return sanitized


AGY_PATH_ENV = "AGYSWITCHER_AGY"
"""Variable de entorno con la ruta absoluta de agy (la fija el instalador; útil en pruebas)."""

AGY_SOURCE_ENV = AGY_PATH_ENV
AGY_SOURCE_PATH = "PATH"
AGY_SOURCE_INSTALL = "ruta de instalación"

_BATCH_SUFFIXES = frozenset({".bat", ".cmd"})
_BATCH_UNSAFE_CHARS = frozenset('&|<>^%"\r\n')
"""Caracteres que cmd.exe interpreta aunque el argumento vaya entre comillas."""


@dataclass(frozen=True)
class AgyLocation:
    """Ejecutable de agy encontrado y de dónde sale."""

    path: Path
    source: str
    """AGY_SOURCE_ENV, AGY_SOURCE_PATH o AGY_SOURCE_INSTALL."""
    warning: str | None = None
    """Aviso si AGYSWITCHER_AGY tiene un valor que no se pudo usar."""


def _agy_exe_name() -> str:
    return "agy.exe" if os.name == "nt" else "agy"


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))
    except OSError:
        return False


def _safe_path_dirs(path_value: str) -> list[Path]:
    """Carpetas absolutas del PATH, sin entradas vacías ni relativas (como '.' o 'bin')."""
    dirs: list[Path] = []
    for entry in path_value.split(os.pathsep):
        cleaned = os.path.expandvars(entry.strip().strip('"'))
        if not cleaned:
            continue
        candidate = Path(cleaned)
        if candidate.is_absolute():
            dirs.append(candidate)
    return dirs


def _install_dir_candidate() -> Path | None:
    """Ruta en la que instala agy su instalador oficial (%LOCALAPPDATA%/agy/bin/agy.exe)."""
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if os.name != "nt" or not local or not Path(local).is_absolute():
        return None
    return Path(local) / "agy" / "bin" / "agy.exe"


def locate_agy() -> AgyLocation:
    """Localiza agy sin buscar nunca en la carpeta actual.

    Orden: la variable AGYSWITCHER_AGY (ruta absoluta a un fichero existente), las carpetas
    absolutas del PATH (solo ``agy.exe``, no scripts ``.cmd``/``.bat``) y la ruta de
    instalación oficial. A diferencia de ``shutil.which``, no se mira la carpeta actual:
    un proyecto con un ``agy.cmd`` propio no puede hacerse pasar por agy.

    Raises:
        AgyNotFoundError: Si no se encuentra agy.
    """
    warning: str | None = None
    custom = os.environ.get(AGY_PATH_ENV, "").strip().strip('"')
    if custom:
        custom_path = Path(custom)
        if custom_path.is_absolute() and _is_executable_file(custom_path):
            return AgyLocation(custom_path.resolve(), AGY_SOURCE_ENV)
        warning = (
            f"{AGY_PATH_ENV} no apunta a un ejecutable válido ({custom}); "
            "se busca agy en el PATH. Revisa la instalación con 'agyswitcher doctor'."
        )

    name = _agy_exe_name()
    for folder in _safe_path_dirs(os.environ.get("PATH", "")):
        candidate = folder / name
        if _is_executable_file(candidate):
            return AgyLocation(candidate.resolve(), AGY_SOURCE_PATH, warning)

    installed = _install_dir_candidate()
    if installed is not None and _is_executable_file(installed):
        return AgyLocation(installed.resolve(), AGY_SOURCE_INSTALL, warning)

    raise AgyNotFoundError(
        "No se encontró agy.exe en el PATH. "
        "Verifica que Antigravity CLI esté instalado en el sistema "
        f"o indica su ruta completa en la variable {AGY_PATH_ENV}."
    )


def find_agy_executable() -> Path:
    """Ruta absoluta del ejecutable de agy (ver 'locate_agy').

    Raises:
        AgyNotFoundError: Si agy no se encuentra.
    """
    return locate_agy().path


def system_tool(name: str) -> str:
    """Ruta absoluta de una utilidad de Windows en System32 (evita la búsqueda en la carpeta actual)."""
    if os.name != "nt":
        return name
    root = os.environ.get("SYSTEMROOT", "").strip() or r"C:\Windows"
    return str(Path(root) / "System32" / name)


def check_batch_args(executable: str | Path, args: Sequence[str]) -> None:
    """Rechaza argumentos peligrosos si el ejecutable es un script de cmd.exe.

    Un ``.cmd``/``.bat`` se ejecuta a través de cmd.exe, que interpreta ``&``, ``|``, ``%``...
    aunque Python ponga comillas. Con un ``.exe`` no se comprueba nada.

    Raises:
        RunnerError: Si algún argumento contiene caracteres que cmd.exe interpretaría.
    """
    if Path(str(executable)).suffix.lower() not in _BATCH_SUFFIXES:
        return
    for arg in args:
        if any(ch in _BATCH_UNSAFE_CHARS for ch in arg):
            raise RunnerError(
                "agy es un script de cmd.exe y un argumento contiene caracteres especiales "
                '(& | < > ^ % " o saltos de línea); no se ejecuta por seguridad.'
            )


AGY_PROCESS_NAMES = frozenset({"agy.exe", "antigravity.exe", "antigravity ide.exe"})
"""Procesos (en minúsculas) que pueden tener abiertos ficheros de ~/.gemini: CLI e IDE."""


def find_running_agy_processes(timeout: float = 10.0) -> list[str] | None:
    """Lista los procesos de agy o del IDE de Antigravity en ejecución.

    Args:
        timeout: Tiempo máximo de espera de 'tasklist' en segundos.

    Returns:
        Nombres de imagen (sin repetir, ordenados) de los procesos encontrados; lista vacía
        si no hay ninguno o el sistema no es Windows; None si no se pudo comprobar.
    """
    if os.name != "nt":
        return []
    try:
        res = subprocess.run(
            [system_tool("tasklist.exe"), "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    found: set[str] = set()
    for row in csv.reader(res.stdout.splitlines()):
        if row and row[0].strip().lower() in AGY_PROCESS_NAMES:
            found.add(row[0].strip())
    return sorted(found)


def kill_process_tree(pid: int) -> None:
    """Termina forzosamente un proceso y todo su árbol de procesos hijo en Windows.

    Args:
        pid: Identificador de proceso (PID) a finalizar.
    """
    if os.name == "nt":
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            subprocess.run(
                [system_tool("taskkill.exe"), "/T", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
                timeout=5.0,
            )
    else:
        sig = getattr(signal, "SIGKILL", signal.SIGTERM)
        with contextlib.suppress(OSError):
            os.kill(pid, sig)


def run_captured(
    cmd: list[str],
    *,
    timeout: float,
    kill_grace: float = 3.0,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando no interactivo capturando su salida, con un tiempo máximo garantizado.

    A diferencia de ``subprocess.run(..., timeout=...)``, no puede quedarse bloqueado en
    Windows cuando el proceso deja procesos nietos con las tuberías abiertas: al expirar el
    tiempo termina todo el árbol de procesos y la espera posterior también está acotada.
    La entrada estándar se conecta a ``DEVNULL`` para que el hijo nunca espere teclado.

    Args:
        cmd: Comando y argumentos (sin shell).
        timeout: Segundos máximos de espera del comando.
        kill_grace: Segundos máximos para recoger la salida tras terminar el árbol.

    Returns:
        CompletedProcess con el código de salida y la salida capturada como texto UTF-8.

    Raises:
        subprocess.TimeoutExpired: Si el comando excede ``timeout`` (el árbol ya está terminado).
        OSError: Si el proceso no se puede lanzar.
        RunnerError: Si el ejecutable es un script ``.cmd``/``.bat`` y algún argumento no es seguro.
    """
    if cmd:
        check_batch_args(cmd[0], cmd[1:])
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_and_reap(proc, kill_grace)
        raise subprocess.TimeoutExpired(cmd, timeout) from None
    except KeyboardInterrupt:
        _kill_and_reap(proc, kill_grace)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _kill_and_reap(proc: subprocess.Popen[str], grace: float) -> None:
    """Termina el árbol del proceso y espera de forma acotada a que se cierren sus tuberías."""
    kill_process_tree(proc.pid)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=grace)


def _terminate_cleanly(proc: subprocess.Popen[str], grace_period: float = 2.0) -> None:
    """Intenta terminar el subproceso limpiamente y recurre a taskkill si expira el tiempo."""
    if proc.poll() is not None:
        return

    try:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=grace_period)
    except (subprocess.TimeoutExpired, OSError):
        kill_process_tree(proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            proc.wait(timeout=1.0)


def run_agy_process(
    args: list[str],
    *,
    cwd: Path | str | None = None,
    on_line: Callable[[str], None] | None = None,
    executable_path: Path | None = None,
    grace_period: float = 2.0,
    echo_output: bool = True,
) -> int:
    """Ejecuta agy.exe como subproceso hijo con streaming en tiempo real y sanitización.

    Args:
        args: Argumentos de línea de comandos a pasar a agy.exe.
        cwd: Directorio de trabajo para la ejecución (None usa el actual).
        on_line: Callback opcional invocado por cada línea sanitizada recibida.
        executable_path: Ruta explícita a agy.exe (None busca en PATH).
        grace_period: Tiempo en segundos a esperar tras señal antes de forzar cierre.
        echo_output: Si es True, retransmite la salida al terminal (sys.stdout).

    Returns:
        Código de salida del proceso (0 para éxito, != 0 para fallo, 130 si fue interrumpido).

    Raises:
        AgyNotFoundError: Si agy.exe no se localiza en el PATH.
        RunnerError: Si ocurre un error al lanzar o gestionar el subproceso.
        Las excepciones lanzadas por 'on_line' se propagan sin envolver, tras terminar el hijo.
    """
    exe = executable_path if executable_path is not None else find_agy_executable()
    check_batch_args(exe, args)
    cmd = [str(exe), *args]

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except OSError as err:
        raise RunnerError(f"Error al iniciar el subproceso '{exe}': {err}") from err

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                sanitized = sanitize_line(raw_line)
                if echo_output:
                    sys.stdout.write(sanitized)
                    sys.stdout.flush()
                if on_line is not None:
                    on_line(sanitized)
        proc.wait()
        return proc.returncode
    except KeyboardInterrupt:
        return 130
    except OSError as err:
        # Fallos de E/S al leer la tubería del hijo o escribir en la consola.
        raise RunnerError(f"Error durante la ejecución del proceso agy: {err}") from err
    finally:
        # Limpieza garantizada ante cualquier salida (incluidos errores del callback
        # 'on_line', que se propagan con su tipo original). No-op si ya terminó.
        _terminate_cleanly(proc, grace_period=grace_period)
