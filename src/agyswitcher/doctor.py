# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: doctor.py
Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-20
Ultimo cambio: 2026-11-23
Descripción: Diagnóstico de la instalación ('agyswitcher doctor').

Reúne en una lista de comprobaciones el estado de agy, de los datos de AgySwitcher, de la
sesión detectada en los logs y del proyecto actual. Solo lee: no modifica ficheros, no
consulta la cuota (no gasta nada) y nunca lee tokens ni credenciales. Para que la salida
se pueda compartir al pedir ayuda, los emails se enmascaran por defecto y la carpeta
personal se muestra como '~'.
"""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from agyswitcher.config import (
    ConfigError,
    Settings,
    app_home_dir,
    default_config_path,
    load_accounts,
    load_settings,
)
from agyswitcher.credman import (
    SLOT_MISMATCH,
    SLOT_OK,
    SLOT_ORPHAN,
    CredManError,
    SlotInfo,
    get_active_email,
    list_slots,
)
from agyswitcher.credman import is_available as credman_is_available
from agyswitcher.models import Account, AppState
from agyswitcher.project import (
    PROJECT_CONFIG_NAME,
    find_project_config,
    resolve_low_quota_threshold,
)
from agyswitcher.rotator import quota_data_time
from agyswitcher.runner import (
    AGY_PATH_ENV,
    AgyNotFoundError,
    RunnerError,
    find_running_agy_processes,
    locate_agy,
    run_captured,
)
from agyswitcher.state import StateError, default_state_path, load_state
from agyswitcher.usage import detect_active_email
from agyswitcher.version import full_version

AGY_VERSION_TIMEOUT = 15.0
"""Segundos máximos para 'agy --version'."""

ACTIVE_QUOTA_MAX_AGE = timedelta(hours=24)
"""Antigüedad a partir de la cual se sugiere actualizar la cuota de la cuenta activa."""

OTHER_QUOTA_MAX_AGE = timedelta(days=7)
"""Antigüedad (un ciclo semanal) a partir de la cual el dato de otra cuenta está desfasado."""

QUOTA_POOLS_CHECKED = ("gemini", "external")


class CheckStatus(Enum):
    """Resultado de una comprobación, de mejor a peor."""

    OK = "ok"
    INFO = "info"
    WARN = "aviso"
    FAIL = "error"


@dataclass(frozen=True)
class Check:
    """Una comprobación del diagnóstico."""

    name: str
    status: CheckStatus
    detail: str
    hint: str | None = None


@dataclass(frozen=True)
class DoctorOptions:
    """Opciones de presentación del diagnóstico."""

    show_emails: bool = False


def mask_email(email: str) -> str:
    """Enmascara la parte local de un email: 'personal@example.com' -> 'pe***@example.com'."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    visible = local[:2] if len(local) > 3 else local[:1]
    return f"{visible}***@{domain}"


def display_path(path: Path) -> str:
    """Ruta con la carpeta personal sustituida por '~' (no revela el nombre de usuario)."""
    try:
        return str(Path("~") / path.resolve().relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


def _show_email(email: str, options: DoctorOptions) -> str:
    return email if options.show_emails else mask_email(email)


def _age_text(age: timedelta) -> str:
    """Antigüedad legible en español ('3 días', '5 h', '20 min')."""
    if age >= timedelta(days=2):
        return f"{age.days} días"
    if age >= timedelta(hours=1):
        return f"{int(age.total_seconds() // 3600)} h"
    return f"{max(int(age.total_seconds() // 60), 0)} min"


# ---------------------------------------------------------------------------
# Comprobaciones individuales
# ---------------------------------------------------------------------------


def check_versions() -> Check:
    """Versión de AgySwitcher, de Python y del sistema (informativo)."""
    detail = (
        f"AgySwitcher {full_version()} · Python {platform.python_version()} · "
        f"{platform.system()} {platform.release()}"
    )
    return Check("Versiones", CheckStatus.INFO, detail)


def check_agy(version_timeout: float = AGY_VERSION_TIMEOUT) -> Check:
    """agy localizado de forma segura, de dónde sale y su versión ('agy --version', no consume cuota)."""
    try:
        location = locate_agy()
    except AgyNotFoundError:
        return Check(
            "Antigravity CLI (agy)",
            CheckStatus.FAIL,
            "agy no está en el PATH.",
            "Instala Antigravity CLI o añade su carpeta al PATH y abre una consola nueva. "
            f"Si está en otra ruta, indícala completa en la variable {AGY_PATH_ENV}.",
        )
    exe = location.path
    origin = f"origen: {location.source}"
    try:
        result = run_captured([str(exe), "--version"], timeout=version_timeout)
    except subprocess.TimeoutExpired:
        return Check(
            "Antigravity CLI (agy)",
            CheckStatus.WARN,
            f"{display_path(exe)} no respondió a --version en {version_timeout:.0f} s.",
        )
    except (OSError, RunnerError) as err:
        reason = err.strerror if isinstance(err, OSError) and err.strerror else err
        return Check(
            "Antigravity CLI (agy)",
            CheckStatus.WARN,
            f"No se pudo ejecutar {display_path(exe)}: {reason}.",
        )
    lines = (result.stdout or "").strip().splitlines()
    version = lines[0].strip()[:40] if result.returncode == 0 and lines else "desconocida"
    detail = f"versión {version} · {display_path(exe)} · {origin}"
    if location.warning:
        return Check(
            "Antigravity CLI (agy)",
            CheckStatus.WARN,
            f"{detail}. {location.warning}",
            f"Corrige o borra la variable {AGY_PATH_ENV} (reinstalar AgySwitcher la actualiza).",
        )
    if exe.suffix.lower() != ".exe" and os.name == "nt":
        return Check(
            "Antigravity CLI (agy)",
            CheckStatus.WARN,
            f"{detail}. agy no es un .exe: se ejecuta a través de cmd.exe.",
            f"Indica en {AGY_PATH_ENV} la ruta del agy.exe real si es posible.",
        )
    return Check("Antigravity CLI (agy)", CheckStatus.OK, detail)


def check_data_dir() -> Check:
    """Carpeta de datos de AgySwitcher (y si viene de AGYSWITCHER_HOME)."""
    home = app_home_dir()
    origin = " (AGYSWITCHER_HOME)" if os.environ.get("AGYSWITCHER_HOME") else ""
    if home.is_dir():
        return Check("Carpeta de datos", CheckStatus.OK, f"{display_path(home)}{origin}")
    return Check(
        "Carpeta de datos",
        CheckStatus.INFO,
        f"{display_path(home)}{origin} aún no existe.",
        "Se crea al registrar la primera cuenta con 'agyswitcher add'.",
    )


def check_settings(settings: Settings | None, error: str | None) -> Check:
    """Ajustes globales de config.json."""
    if settings is None:
        return Check(
            "Ajustes",
            CheckStatus.FAIL,
            f"{display_path(default_config_path())}: {error}",
            "Corrige o renombra config.json (se perderían las cuentas registradas).",
        )
    pct = settings.low_quota_percent
    threshold = f"{pct} %" if pct is not None else "por defecto"
    copy = "sí" if settings.auto_copy else "no"
    return Check(
        "Ajustes",
        CheckStatus.OK,
        f"aviso de cuota baja: {threshold} · copia al portapapeles: {copy}",
    )


def check_accounts(accounts: dict[str, Account] | None, error: str | None) -> Check:
    """Cuentas registradas en config.json."""
    if error is not None:
        return Check(
            "Cuentas",
            CheckStatus.FAIL,
            f"{display_path(default_config_path())}: {error}",
            "Corrige el fichero o restáuralo desde una copia.",
        )
    if not accounts:
        return Check(
            "Cuentas",
            CheckStatus.WARN,
            "No hay cuentas registradas.",
            "Registra una con 'agyswitcher add <alias> --email <email>'.",
        )
    without_email = sorted(a for a, acc in accounts.items() if not acc.email)
    detail = f"{len(accounts)} registradas"
    if without_email:
        return Check(
            "Cuentas",
            CheckStatus.WARN,
            f"{detail}. Sin email: {', '.join(without_email)}.",
            "Sin email no se puede verificar el cambio de cuenta: vuelve a registrarlas con "
            "'agyswitcher add <alias> --email <email>'.",
        )
    return Check("Cuentas", CheckStatus.OK, detail)


def check_state(state: AppState | None, error: str | None) -> Check:
    """Legibilidad de state.json."""
    if state is None:
        return Check(
            "Estado",
            CheckStatus.FAIL,
            f"{display_path(default_state_path())}: {error}",
            "Renombra state.json: se volverá a crear (se pierden los datos de cuota guardados).",
        )
    pool = "Gemini" if state.active_model_group == "gemini" else "Otros"
    return Check("Estado", CheckStatus.OK, f"legible · pool activo: {pool}")


def check_active_account(accounts: dict[str, Account], state: AppState) -> Check:
    """Que haya cuenta activa y esté registrada."""
    if not accounts:
        return Check("Cuenta activa", CheckStatus.INFO, "Sin cuentas registradas.")
    if state.active is None:
        return Check(
            "Cuenta activa",
            CheckStatus.WARN,
            "No hay ninguna cuenta activa.",
            "Elige una con 'agyswitcher set-active <alias>'.",
        )
    if state.active not in accounts:
        return Check(
            "Cuenta activa",
            CheckStatus.FAIL,
            f"La cuenta activa '{state.active}' ya no está registrada.",
            "Elige otra con 'agyswitcher set-active <alias>'.",
        )
    return Check("Cuenta activa", CheckStatus.OK, state.active)


def check_session(
    accounts: dict[str, Account],
    state: AppState,
    session_email: str | None,
    options: DoctorOptions,
) -> Check:
    """Sesión de agy (Credential Manager o sus logs) frente a la cuenta activa de AgySwitcher."""
    if session_email is None:
        return Check(
            "Sesión de agy",
            CheckStatus.WARN,
            "No se detecta ninguna sesión en los logs de agy.",
            "Abre agy e inicia sesión con tu cuenta de Google.",
        )
    shown = _show_email(session_email, options)
    owner = next(
        (
            alias
            for alias, acc in sorted(accounts.items())
            if acc.email and acc.email.lower() == session_email.lower()
        ),
        None,
    )
    if owner is None:
        return Check(
            "Sesión de agy",
            CheckStatus.WARN,
            f"{shown}, que no corresponde a ninguna cuenta registrada.",
            "Regístrala con 'agyswitcher add <alias> --email <email>' o inicia sesión en agy "
            "con una cuenta registrada.",
        )
    if state.active is not None and owner != state.active:
        return Check(
            "Sesión de agy",
            CheckStatus.WARN,
            f"{shown} ('{owner}'), pero la cuenta activa es '{state.active}'.",
            "Ejecuta 'agyswitcher sync' para que AgySwitcher refleje la sesión real, o "
            f"'agyswitcher set-active {state.active}' para volver a esa cuenta. Mientras no "
            f"coincidan, la cuota se atribuye a '{owner}'.",
        )
    return Check("Sesión de agy", CheckStatus.OK, f"{shown} ('{owner}')")


def check_quota_data(accounts: dict[str, Account], state: AppState, now: datetime) -> list[Check]:
    """Antigüedad de los datos de cuota y pools agotados cuyo reinicio ya pasó."""
    if not accounts:
        return []
    checks: list[Check] = []
    active = state.active if state.active in accounts else None
    if active is not None:
        updated = quota_data_time(state, active)
        if updated is None:
            checks.append(
                Check(
                    "Cuota de la cuenta activa",
                    CheckStatus.WARN,
                    f"Sin datos de cuota de '{active}'.",
                    "Consulta la cuota con 'agyswitcher usage'.",
                )
            )
        elif now - updated > ACTIVE_QUOTA_MAX_AGE:
            checks.append(
                Check(
                    "Cuota de la cuenta activa",
                    CheckStatus.WARN,
                    f"El dato de '{active}' tiene {_age_text(now - updated)}.",
                    "Actualízalo con 'agyswitcher usage'.",
                )
            )
        else:
            checks.append(
                Check(
                    "Cuota de la cuenta activa",
                    CheckStatus.OK,
                    f"dato de hace {_age_text(now - updated)}",
                )
            )

    others = sorted(a for a in accounts if a != active)
    stale = []
    for alias in others:
        updated = quota_data_time(state, alias)
        if updated is None:
            stale.append(f"{alias} (sin datos)")
        elif now - updated > OTHER_QUOTA_MAX_AGE:
            stale.append(f"{alias} ({_age_text(now - updated)})")
    if stale:
        checks.append(
            Check(
                "Cuota de otras cuentas",
                CheckStatus.INFO,
                f"Datos antiguos o ausentes: {', '.join(stale)}.",
                "Es normal: solo se puede consultar la cuota de la cuenta con sesión. Se "
                "actualiza al cambiar a esa cuenta.",
            )
        )

    recovered = []
    for alias in sorted(accounts):
        for pool in QUOTA_POOLS_CHECKED:
            if not state.is_pool_exhausted(alias, pool):
                continue
            reset = state.estimated_reset(alias, pool)
            if reset is not None and reset <= now:
                recovered.append(f"{alias} ({'Gemini' if pool == 'gemini' else 'Otros'})")
    if recovered:
        checks.append(
            Check(
                "Cuotas agotadas",
                CheckStatus.INFO,
                f"Ya pasó el reinicio previsto de: {', '.join(recovered)}.",
                "Probablemente vuelven a tener cuota; se confirma al cambiar a esa cuenta.",
            )
        )
    return checks


def check_slots(
    accounts: dict[str, Account], slots: list[SlotInfo] | None, options: DoctorOptions
) -> Check:
    """Slots de sesión: huérfanos, de otra cuenta y cuentas que aún no tienen slot."""
    if slots is None:
        return Check(
            "Slots de sesión",
            CheckStatus.INFO,
            "Credential Manager no disponible: no hay conmutación instantánea.",
        )
    orphans = [s.alias for s in slots if s.status == SLOT_ORPHAN]
    mismatched = [s for s in slots if s.status == SLOT_MISMATCH]
    if orphans or mismatched:
        parts = []
        if orphans:
            parts.append(f"sin cuenta registrada: {', '.join(orphans)}")
        if mismatched:
            shown = ", ".join(
                f"{s.alias} ({_show_email(s.email, options) if s.email else 'ilegible'})"
                for s in mismatched
            )
            parts.append(f"no son de su cuenta: {shown}")
        return Check(
            "Slots de sesión",
            CheckStatus.WARN,
            "; ".join(parts) + ".",
            "Bórralos con 'agyswitcher slots clean' y prepara de nuevo el slot de esas cuentas "
            "con un 'agyswitcher set-active <alias>' guiado.",
        )
    with_slot = {s.alias for s in slots if s.status == SLOT_OK}
    missing = sorted(a for a in accounts if a not in with_slot)
    detail = f"{len(with_slot)} de {len(accounts)} cuentas con slot"
    if missing:
        return Check(
            "Slots de sesión",
            CheckStatus.INFO,
            f"{detail}. Sin slot: {', '.join(missing)}.",
            "Prepara su slot una sola vez con 'agyswitcher set-active <alias>' (cambio guiado): "
            "después cambiarás a ellas sin navegador.",
        )
    return Check("Slots de sesión", CheckStatus.OK, detail)


def check_agy_processes(processes: list[str] | None) -> Check:
    """Procesos de agy o del IDE abiertos (informativo)."""
    if processes is None:
        return Check(
            "Procesos de agy",
            CheckStatus.WARN,
            "No se pudo consultar la lista de procesos (tasklist).",
        )
    if not processes:
        return Check("Procesos de agy", CheckStatus.OK, "ninguno abierto")
    return Check(
        "Procesos de agy",
        CheckStatus.INFO,
        f"abiertos: {', '.join(processes)}",
        "Una sesión abierta sigue con la cuenta con la que arrancó: tras cambiar de cuenta, "
        "cierra y vuelve a abrir agy.",
    )


def check_project(cwd: Path, global_low_quota: int | None) -> list[Check]:
    """Preparación del proyecto de la carpeta actual para la continuidad entre cuentas."""
    shown = display_path(cwd)
    has_agents = (cwd / "AGENTS.md").is_file()
    has_memory = (cwd / "dev_mem").is_dir()
    if has_agents and has_memory:
        project = Check("Proyecto actual", CheckStatus.OK, f"{shown}: AGENTS.md y dev_mem/")
    elif has_agents or has_memory:
        missing = "dev_mem/" if has_agents else "AGENTS.md"
        project = Check(
            "Proyecto actual",
            CheckStatus.WARN,
            f"{shown}: falta {missing}.",
            "Ejecuta 'agyswitcher init --merge' para completar lo que falte sin sobrescribir.",
        )
    else:
        project = Check(
            "Proyecto actual",
            CheckStatus.INFO,
            f"{shown} no está preparado para continuar entre cuentas.",
            "Si es la carpeta de un proyecto, ejecuta 'agyswitcher init'.",
        )
    checks = [project]

    threshold = resolve_low_quota_threshold(cwd, global_low_quota)
    config = find_project_config(cwd)
    if threshold.error:
        checks.append(
            Check(
                "Configuración del proyecto",
                CheckStatus.WARN,
                f"{display_path(config) if config else PROJECT_CONFIG_NAME}: {threshold.error}",
                "Se usa el umbral global o el de por defecto hasta que se corrija.",
            )
        )
    elif config is not None:
        checks.append(
            Check(
                "Configuración del proyecto",
                CheckStatus.OK,
                f"{display_path(config)} · umbral de cuota baja: {threshold.percent} % "
                f"({threshold.source})",
            )
        )
    return checks


# ---------------------------------------------------------------------------
# Diagnóstico completo
# ---------------------------------------------------------------------------


def session_email() -> str | None:
    """Email de la sesión de agy: Credential Manager primero y, si no hay, sus registros."""
    try:
        email = get_active_email()
    except CredManError:
        email = None
    return email or detect_active_email()


def read_slots(accounts: dict[str, Account]) -> list[SlotInfo] | None:
    """Inventario de slots (solo metadatos); None si Credential Manager no está disponible."""
    if not credman_is_available():
        return None
    try:
        return list_slots({alias: acc.email for alias, acc in accounts.items()})
    except CredManError:
        return None


def run_doctor(
    cwd: Path,
    options: DoctorOptions | None = None,
    now: datetime | None = None,
    *,
    email_detector: Callable[[], str | None] = session_email,
    process_lister: Callable[[], list[str] | None] = find_running_agy_processes,
    slot_reader: Callable[[dict[str, Account]], list[SlotInfo] | None] = read_slots,
) -> list[Check]:
    """Ejecuta todas las comprobaciones en orden y devuelve sus resultados."""
    opts = options or DoctorOptions()
    moment = now or datetime.now(UTC)

    accounts: dict[str, Account] | None = None
    accounts_error: str | None = None
    try:
        accounts = load_accounts()
    except ConfigError as err:
        accounts_error = str(err)

    state: AppState | None = None
    state_error: str | None = None
    try:
        state = load_state()
    except StateError as err:
        state_error = str(err)

    settings: Settings | None = None
    settings_error: str | None = None
    try:
        settings = load_settings()
    except ConfigError as err:
        settings_error = str(err)

    checks = [
        check_versions(),
        check_agy(),
        check_data_dir(),
        check_settings(settings, settings_error),
        check_accounts(accounts, accounts_error),
        check_state(state, state_error),
    ]
    if accounts is not None and state is not None:
        checks.append(check_active_account(accounts, state))
        checks.append(check_session(accounts, state, email_detector(), opts))
        checks.append(check_slots(accounts, slot_reader(accounts), opts))
        checks.extend(check_quota_data(accounts, state, moment))
    checks.append(check_agy_processes(process_lister()))
    checks.extend(check_project(cwd, settings.low_quota_percent if settings else None))
    return checks


def worst_status(checks: list[Check]) -> CheckStatus:
    """Peor resultado de la lista (OK si está vacía)."""
    order = [CheckStatus.OK, CheckStatus.INFO, CheckStatus.WARN, CheckStatus.FAIL]
    return max((c.status for c in checks), key=order.index, default=CheckStatus.OK)
