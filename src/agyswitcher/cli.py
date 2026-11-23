# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: cli.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-20

Descripción: Entry point de la interfaz de línea de comandos de AgySwitcher.
"""

from __future__ import annotations

import contextlib
import re
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from agyswitcher import __app_name__
from agyswitcher.ai_models import (
    classify_model_pool,
    fetch_available_models,
    inject_preferred_model_args,
)
from agyswitcher.clipboard import copy_to_clipboard
from agyswitcher.config import (
    LOW_QUOTA_MAX,
    LOW_QUOTA_MIN,
    ConfigError,
    Settings,
    default_config_path,
    load_accounts,
    load_settings,
    save_accounts,
    save_settings,
)
from agyswitcher.dashboard import build_dashboard_view
from agyswitcher.doctor import CheckStatus, DoctorOptions, run_doctor, worst_status
from agyswitcher.models import Account, AccountQuotaInfo, AppState, is_valid_email
from agyswitcher.project import (
    AGENT_POINTER_FILES,
    DEFAULT_AGENTS,
    ProjectError,
    handoff_file_path,
    load_handoff_prompts,
    low_quota_percent,
    parse_agents,
    resolve_low_quota_threshold,
    scaffold_project,
    write_handoff_file,
)
from agyswitcher.quota import QuotaDetector
from agyswitcher.rotator import (
    account_reset_estimate,
    default_live_dir,
    quota_data_time,
    record_rotation,
    select_next_candidate,
    suggest_account_to_check,
)
from agyswitcher.runner import (
    AgyNotFoundError,
    RunnerError,
    find_running_agy_processes,
    run_agy_process,
)
from agyswitcher.session import (
    DEFAULT_LOGIN_TIMEOUT,
    LogFollower,
    LoginWaitStatus,
    snapshot_log_offsets,
    wait_for_login,
)
from agyswitcher.state import StateError, load_state, save_state
from agyswitcher.usage import (
    AuthRequiredError,
    UsageError,
    UsageReport,
    detect_active_email,
    fetch_usage,
    format_time_remaining,
    update_state_from_usage_report,
)
from agyswitcher.version import full_version

ALIAS_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9_-]{0,62}[a-zA-Z0-9])?$")
"""Alias de una cuenta nueva: empieza y termina por letra o número (no puede parecer una opción)."""

USAGE_FETCH_ERRORS: tuple[type[Exception], ...] = (RunnerError, UsageError, OSError)
"""Errores esperables al consultar la cuota con agy (incluye AgyNotFoundError y AuthRequiredError)."""
console = Console()

app = typer.Typer(
    name=__app_name__,
    help="Gestor de cuentas y cuotas para Antigravity CLI (agy) en Windows.\n\nSwitch accounts. Keep coding.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{__app_name__} {full_version()}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(  # noqa: FBT001
        False,
        "--version",
        "-V",
        help="Mostrar la versión y salir.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """AgySwitcher — Orquestador de cuentas para agy en Windows."""


def _report_owner(accounts: dict[str, Account], state: AppState, report: UsageReport) -> str | None:
    """Alias al que pertenece un informe de cuota de agy (la cuenta con sesión iniciada).

    Si el informe trae el email de la sesión, se usa el alias con ese email (None si no está
    registrado); si no lo trae, se asume la cuenta activa. Evita atribuir a una cuenta la
    cuota de otra.
    """
    if report.active_email:
        email = report.active_email.lower()
        return next(
            (a for a, acc in accounts.items() if acc.email and acc.email.lower() == email),
            None,
        )
    return state.active


def _print_prompt(title: str, text: str) -> None:
    """Muestra una instrucción para pegar en el agente, sin ajustes de línea que estorben al copiar."""
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    typer.echo(text)
    console.rule()


def _load_settings_or_default() -> Settings:
    """Ajustes globales; si config.json no se puede leer, los de por defecto."""
    try:
        return load_settings()
    except ConfigError:
        return Settings()


def _auto_copy(text: str) -> bool:
    """Copia 'text' al portapapeles si la copia automática está activada. True si se copió."""
    return _load_settings_or_default().auto_copy and copy_to_clipboard(text)


def _print_resume_hint() -> None:
    """Tras un cambio de cuenta verificado, muestra la instrucción para retomar el proyecto."""
    cwd = Path.cwd()
    prompts = load_handoff_prompts(cwd)
    handoff_file = handoff_file_path(cwd)
    console.print("\n[bold]Para retomar el trabajo con la nueva cuenta[/bold], indica en agy:")
    if handoff_file.is_file():
        try:
            rel = handoff_file.relative_to(cwd)
        except ValueError:
            rel = handoff_file
        console.print(f"  [bold cyan]Lee {rel} y continúa[/bold cyan]\n")
    _print_prompt("Retomar", prompts.resume)
    if _auto_copy(prompts.resume):
        console.print("[dim]Instrucción copiada al portapapeles.[/dim]")


def _warn_low_quota(accounts: dict[str, Account], state: AppState) -> None:
    """Avisa si a la cuenta activa le queda poca cuota en el pool activo (guardar estado a tiempo)."""
    alias = state.active
    if not alias or alias not in accounts:
        return
    settings = _load_settings_or_default()
    threshold = resolve_low_quota_threshold(Path.cwd(), settings.low_quota_percent)
    if threshold.error:
        console.print(
            f"[yellow]Umbral de cuota baja de {threshold.project_file} ignorado: "
            f"{escape(threshold.error)}.[/yellow]"
        )
    pool = state.active_model_group
    pct = low_quota_percent(state.accounts_quota.get(alias), pool, threshold.percent)
    if pct is None:
        return
    pool_name = "Gemini" if pool == "gemini" else "Otros"
    console.print(
        f"\n[bold yellow][!] Cuota baja en '{alias}' ({pool_name}: {pct} % restante, umbral "
        f"{threshold.percent} %).[/bold yellow] Antes de que se agote, pide a agy que guarde el "
        "estado del proyecto."
    )
    save_prompt = load_handoff_prompts(Path.cwd()).save
    if settings.auto_copy and copy_to_clipboard(save_prompt):
        console.print(
            "La instrucción para guardar el estado está en el portapapeles: pégala en agy "
            "(también la muestra [bold cyan]agyswitcher handoff save[/bold cyan])."
        )
    else:
        console.print(
            "Ejecuta [bold cyan]agyswitcher handoff save[/bold cyan] y pega la instrucción en agy."
        )
    candidate = select_next_candidate(accounts, state)
    if candidate and candidate[0] != alias:
        console.print(f"[dim]Siguiente cuenta con cuota: '{candidate[0]}'.[/dim]")


def _format_age(moment: datetime, now: datetime) -> str:
    """Antigüedad legible de un momento pasado (ej. '2d 3h', '45m', 'menos de 1m')."""
    total = int((now - moment).total_seconds())
    if total < 60:
        return "menos de 1m"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {rest // 60}m"
    return f"{rest // 60}m"


def _print_all_exhausted(
    accounts: dict[str, Account], state: AppState, now: datetime | None = None
) -> None:
    """Explica que todas las cuentas figuran agotadas según los datos guardados y qué comprobar.

    Los datos de las cuentas sin sesión pueden estar desfasados: Google a veces restablece la
    cuota antes de la fecha prevista y solo se confirma iniciando sesión con esa cuenta.
    """
    current = now or datetime.now(UTC)
    console.print(
        "[bold red]Según los datos guardados, todas las cuentas tienen la cuota agotada.[/bold red]"
    )
    console.print(
        "[dim]Google a veces restablece la cuota antes de la fecha prevista; solo se confirma "
        "iniciando sesión con la cuenta.[/dim]"
    )
    for alias in sorted(accounts):
        data_time = quota_data_time(state, alias)
        reset = account_reset_estimate(state, alias)
        age = f"dato de hace {_format_age(data_time, current)}" if data_time else "sin datos"
        reset_desc = (
            f"reinicio en {format_time_remaining(reset, current)} "
            f"({reset.strftime('%d/%m %H:%M')} UTC)"
            if reset
            else "reinicio desconocido"
        )
        active_mark = " (activa)" if alias == state.active else ""
        console.print(f"  - {escape(alias)}{active_mark}: {age}; {reset_desc}")

    suggested = suggest_account_to_check(accounts, state, exclude=state.active)
    if suggested:
        console.print(
            f"Comprueba primero '[bold]{escape(suggested)}[/bold]' (reinicio más próximo); "
            "set-active consulta su cuota:"
        )
        console.print(
            f"  [bold cyan]agyswitcher set-active {escape(suggested)}[/bold cyan]", soft_wrap=True
        )


def _refresh_quota_after_switch(alias: str, accounts: dict[str, Account], state: AppState) -> None:
    """Consulta la cuota en vivo tras un cambio de cuenta y actualiza los datos guardados.

    Confirma (o descarta) que la cuota de la cuenta esté agotada: los datos guardados de una
    cuenta sin sesión pueden estar desfasados. Si la consulta falla, solo lo indica.
    """
    was_exhausted = [p for p in ("gemini", "external") if state.is_pool_exhausted(alias, p)]
    try:
        report = fetch_usage(timeout=10.0)
    except USAGE_FETCH_ERRORS:
        report = None
    if report is None or not report.pools or _report_owner(accounts, state, report) != alias:
        console.print(
            "[dim]No se pudo consultar la cuota en vivo. Compruébala con "
            "'agyswitcher list --live'.[/dim]"
        )
        return

    update_state_from_usage_report(state, alias, report)
    with contextlib.suppress(StateError):
        save_state(state)
    info = state.accounts_quota.get(alias)
    if info:
        gem_p = f"{info.gemini_percent}%" if info.gemini_percent is not None else "—"
        ext_p = f"{info.external_percent}%" if info.external_percent is not None else "—"
        console.print(f"[dim]Cuota sincronizada: Gemini {gem_p} | Otros {ext_p}[/dim]")
    for pool in was_exhausted:
        pool_name = "Gemini" if pool == "gemini" else "Otros"
        if state.is_pool_exhausted(alias, pool):
            console.print(f"[yellow]Confirmado: la cuota de {pool_name} sigue agotada.[/yellow]")
        else:
            console.print(f"[green]✓ La cuota de {pool_name} vuelve a estar disponible.[/green]")


def _guided_account_switch(
    target_alias: str,
    target_pool: str,
    accounts: dict[str, Account],
    state: AppState,
    timeout: float,
) -> str:
    """Cambia de cuenta de forma guiada y verificada.

    agy guarda una única sesión de Google en el Administrador de credenciales de Windows y
    ~/.gemini es común a todas las cuentas (historial, conversaciones, MCP y skills). Cambiar
    de cuenta consiste en cerrar e iniciar sesión en agy; AgySwitcher indica con qué email,
    espera a ver ese inicio de sesión en los logs y solo entonces registra el cambio.

    Returns:
        Mensaje del cambio registrado.

    Raises:
        typer.Exit: Con código 1 si no se verificó el cambio (estado intacto).
    """
    keep_msg = f"La cuenta activa sigue siendo '{state.active or 'ninguna'}'."

    target_email = accounts[target_alias].email
    if not target_email:
        typer.secho(
            f"Error: la cuenta '{target_alias}' no tiene email registrado y sin él no se puede "
            "verificar el inicio de sesión. Vuelve a registrarla con "
            f"'agyswitcher remove {target_alias}' y "
            f"'agyswitcher add {target_alias} --email <correo> --no-activate'.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.secho(keep_msg, fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    running = find_running_agy_processes()
    if running:
        console.print(
            f"[yellow]Hay sesiones abiertas ({', '.join(running)}). Puedes cambiar de cuenta en "
            "una de ellas; las demás seguirán con la cuenta anterior hasta que las reinicies.[/yellow]"
        )

    offsets = snapshot_log_offsets()
    minutes = max(1, round(timeout / 60))
    console.print(
        Panel(
            f"Cambio a '[bold]{target_alias}[/bold]'. En agy (una sesión abierta o una nueva):\n\n"
            "  1. Ejecuta [bold cyan]/logout[/bold cyan].\n"
            f"  2. Inicia sesión con [bold cyan]{target_email}[/bold cyan].\n\n"
            f"[dim]Esperando el inicio de sesión (máx. {minutes} min). "
            "Ctrl+C para cancelar.[/dim]",
            title="Cambio de cuenta guiado",
            box=box.ROUNDED,
        )
    )

    def _on_other_login(email: str) -> None:
        owner = next(
            (a for a, acc in accounts.items() if acc.email and acc.email.lower() == email.lower()),
            None,
        )
        owner_desc = f" (cuenta '{owner}')" if owner else ""
        console.print(
            f"[bold red][!][/bold red] Sesión iniciada con [bold]{email}[/bold]{owner_desc}, "
            f"no con [bold cyan]{target_email}[/bold cyan]. Ejecuta /logout en agy e inicia "
            "sesión con la cuenta correcta. Sigo esperando..."
        )

    result = wait_for_login(target_email, offsets, timeout=timeout, on_other_login=_on_other_login)

    if result.status is LoginWaitStatus.VERIFIED:
        try:
            return record_rotation(target_alias, target_pool, state)
        except StateError as err:
            typer.secho(
                f"Sesión verificada, pero no se pudo guardar el estado: {err}. "
                "Ejecuta 'agyswitcher sync' para corregirlo.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(code=1) from err

    reason = (
        "Cancelado por el usuario."
        if result.status is LoginWaitStatus.CANCELLED
        else f"No se detectó el inicio de sesión con {target_email} a tiempo."
    )
    typer.secho(f"\n{reason}", fg=typer.colors.YELLOW)
    if result.detected_email:
        console.print(
            f"[yellow]agy tiene ahora la sesión de {result.detected_email}: ejecuta "
            "'agyswitcher sync' para que AgySwitcher lo refleje.[/yellow]"
        )
    typer.secho(keep_msg, fg=typer.colors.YELLOW)
    raise typer.Exit(code=1)


@app.command(
    help="Registra una nueva cuenta con un alias. Ejemplo: agyswitcher add trabajo",
)
def add(
    alias: Annotated[str, typer.Argument(help="Nombre identificativo de la cuenta a registrar.")],
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            "-e",
            help="Email de Google a asociar (opcional; si se omite, se detecta de la sesión activa en agy).",
        ),
    ] = None,
    activate: Annotated[
        bool | None,
        typer.Option(
            "--activate/--no-activate",
            help="Establecer esta cuenta como la cuenta activa tras registrarla.",
        ),
    ] = None,
) -> None:
    """Registra una nueva cuenta vinculándola a su email de Google."""
    clean_alias = alias.strip()
    if not ALIAS_PATTERN.match(clean_alias):
        typer.secho(
            f"Error: El alias '{alias}' no es válido. "
            "Usa de 1 a 64 letras, números, guiones o guiones bajos, empezando y terminando por "
            "letra o número.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if clean_alias in accounts:
        typer.secho(
            f"Error: La cuenta '{clean_alias}' ya está registrada.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    clean_email = email.strip() if email and email.strip() else None
    if clean_email is not None and not is_valid_email(clean_email):
        typer.secho(
            f"Error: '{clean_email}' no tiene formato de email válido (ejemplo: nombre@example.com).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    detected_email = detect_active_email()
    target_email = clean_email or detected_email

    if target_email:
        console.print(f"Sesión de Google identificada: [bold cyan]{target_email}[/bold cyan]")
        for existing_alias, existing_acc in accounts.items():
            if existing_acc.email and existing_acc.email.lower() == target_email.lower():
                console.print(
                    f"[bold yellow][!] Advertencia:[/bold yellow] El email '{target_email}' ya está asociado "
                    f"a la cuenta registrada '[bold]{existing_alias}[/bold]'."
                )
    else:
        console.print(
            "[yellow]Aviso: No se detectó ninguna sesión activa de Google en los logs de agy.[/yellow]"
        )
        console.print(
            "[dim]Puedes iniciar sesión con 'agy' o pasar el email con --email <correo>.[/dim]"
        )

    accounts[clean_alias] = Account(alias=clean_alias, email=target_email)
    try:
        save_accounts(accounts)
    except ConfigError as err:
        typer.secho(f"Error al guardar la configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    email_suffix = f" ({target_email})" if target_email else ""
    active_email_val = (
        accounts[state.active].email if state.active and state.active in accounts else None
    )
    session_matches = bool(
        detected_email and target_email and detected_email.lower() == target_email.lower()
    )
    session_is_other = bool(detected_email) and not session_matches
    if activate is True:
        should_activate = not session_is_other
        if session_is_other:
            console.print(
                f"[yellow]agy tiene la sesión de {detected_email}, no de esta cuenta: no se "
                f"activa. Para usarla: 'agyswitcher set-active {clean_alias}'.[/yellow]"
            )
    elif activate is False:
        should_activate = False
    elif state.active is None or state.active not in accounts:
        should_activate = not session_is_other
    else:
        should_activate = session_matches and (
            active_email_val is None or active_email_val.lower() != (detected_email or "").lower()
        )

    if should_activate:
        state.active = clean_alias
        try:
            save_state(state)
        except StateError as err:
            typer.secho(f"Error al guardar el estado: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err
        typer.secho(
            f"Cuenta '{clean_alias}'{email_suffix} registrada y establecida como cuenta activa.",
            fg=typer.colors.GREEN,
        )

        # Cuota solo si agy tiene la sesión de esta cuenta (si no, sería la de otra cuenta).
        try:
            if not session_matches:
                raise UsageError("La sesión de agy no es de esta cuenta.")
            report = fetch_usage(timeout=10.0)
            if report and report.pools:
                update_state_from_usage_report(state, clean_alias, report)
                with contextlib.suppress(StateError):
                    save_state(state)
                g_pool = report.pools.get("gemini")
                e_pool = report.pools.get("external")
                g_str = f"{g_pool.remaining_percent}%" if g_pool else "—"
                e_str = f"{e_pool.remaining_percent}%" if e_pool else "—"
                console.print(f"[dim]Cuota sincronizada: Gemini {g_str} | Otros {e_str}[/dim]")
        except (AgyNotFoundError, AuthRequiredError, UsageError, RunnerError):
            pass
    else:
        typer.secho(
            f"Cuenta '{clean_alias}'{email_suffix} registrada correctamente.",
            fg=typer.colors.GREEN,
        )


@app.command(
    name="remove",
    help="Elimina una cuenta registrada en AgySwitcher. Ejemplo: agyswitcher remove trabajo",
)
def remove_account(
    alias: Annotated[str, typer.Argument(help="Alias de la cuenta a eliminar.")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Eliminar sin confirmación interactiva.",
        ),
    ] = False,
) -> None:
    """Elimina una cuenta registrada de la configuración y limpia su estado."""
    clean_alias = alias.strip()
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if clean_alias not in accounts:
        typer.secho(
            f"Error: La cuenta '{clean_alias}' no existe.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    if not force:
        confirm = typer.confirm(f"¿Estás seguro de que deseas eliminar la cuenta '{clean_alias}'?")
        if not confirm:
            console.print("[yellow]Operación cancelada.[/yellow]")
            return

    del accounts[clean_alias]
    try:
        save_accounts(accounts)
    except ConfigError as err:
        typer.secho(f"Error al guardar la configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    state.gemini_quota_exhausted.pop(clean_alias, None)
    state.external_quota_exhausted.pop(clean_alias, None)

    if state.active == clean_alias:
        # La cuenta activa es la de la sesión de agy: no se puede elegir otra sin iniciar sesión.
        state.active = None
        try:
            save_state(state)
        except StateError as err:
            typer.secho(f"Error al guardar el estado: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err
        if accounts:
            console.print(
                f"[yellow]La cuenta activa era '{clean_alias}'. Ahora no hay cuenta activa: "
                "ejecuta 'agyswitcher sync' para usar la cuenta con la que tienes sesión en agy, "
                "o 'agyswitcher set-active <alias>' para cambiar a otra.[/yellow]"
            )
        else:
            console.print(
                f"[yellow]La cuenta activa era '{clean_alias}'. No quedan más cuentas registradas.[/yellow]"
            )
    else:
        try:
            save_state(state)
        except StateError as err:
            typer.secho(f"Error al guardar el estado: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err

    typer.secho(f"Cuenta '{clean_alias}' eliminada correctamente.", fg=typer.colors.GREEN)


@app.command(
    name="set-active",
    help=(
        "Cambia a otra cuenta con el cambio guiado: indica con qué email iniciar sesión en agy y "
        "lo verifica. Ejemplo: agyswitcher set-active trabajo"
    ),
)
def set_active(
    alias: Annotated[str, typer.Argument(help="Alias de la cuenta que se desea activar.")],
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Segundos máximos de espera del inicio de sesión."),
    ] = DEFAULT_LOGIN_TIMEOUT,
) -> None:
    """Marca explícitamente una cuenta registrada como activa."""
    clean_alias = alias.strip()
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if clean_alias not in accounts:
        typer.secho(
            f"Error: La cuenta '{clean_alias}' no está registrada en AgySwitcher.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    switched = clean_alias != state.active
    if switched:
        _guided_account_switch(clean_alias, state.active_model_group, accounts, state, timeout)
    else:
        try:
            save_state(state)
        except StateError as err:
            typer.secho(f"Error al guardar el estado: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err

    acc = accounts[clean_alias]
    email_suffix = f" ({acc.email})" if acc.email else ""
    typer.secho(
        f"Cuenta activa establecida en '{clean_alias}'{email_suffix}.",
        fg=typer.colors.GREEN,
    )
    if switched:
        _print_resume_hint()

    _refresh_quota_after_switch(clean_alias, accounts, state)


@app.command(
    name="sync",
    help="Hace activa la cuenta con la que tienes la sesión iniciada en agy. Ejemplo: agyswitcher sync",
)
def sync_active_account() -> None:
    """Detecta la cuenta de Google con sesión iniciada en agy y la activa en AgySwitcher."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        console.print(
            "No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una."
        )
        return

    # Intentar consultar agy -p /usage en vivo para forzar autenticación y traer cuota fresca
    report: UsageReport | None = None
    try:
        report = fetch_usage(timeout=10.0)
    except AuthRequiredError as err:
        typer.secho(
            f"Sesión no iniciada en Google: {err}\n"
            "Asegúrate de haber iniciado sesión con 'agy' de forma interactiva.",
            fg=typer.colors.YELLOW,
        )
        return
    except (AgyNotFoundError, UsageError, RunnerError):
        report = None

    detected_email = (
        report.active_email if report and report.active_email else None
    ) or detect_active_email()
    if not detected_email:
        typer.secho(
            "No se detectó ninguna sesión activa de Google en los logs de agy. "
            "Asegúrate de haber iniciado sesión con 'agy'.",
            fg=typer.colors.YELLOW,
        )
        return

    console.print(f"Sesión activa detectada en agy: [bold cyan]{detected_email}[/bold cyan]")

    matching = [
        alias
        for alias, acc in accounts.items()
        if acc.email and acc.email.lower() == detected_email.lower()
    ]

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if matching:
        target_alias = matching[0]
        if report and report.pools:
            update_state_from_usage_report(state, target_alias, report)

        if state.active == target_alias:
            save_state(state)
            console.print(
                f"[green]✓ La cuenta activa ya está sincronizada con '{target_alias}' ({detected_email}).[/green]"
            )
        else:
            prev = state.active or "ninguna"
            state.active = target_alias
            save_state(state)
            console.print(
                f"[green]✓ Sincronizado: Cuenta activa cambiada de '{prev}' a '{target_alias}' ({detected_email}).[/green]"
            )

        info = state.accounts_quota.get(target_alias)
        if info:
            gem_p = f"{info.gemini_percent}%" if info.gemini_percent is not None else "—"
            ext_p = f"{info.external_percent}%" if info.external_percent is not None else "—"
            console.print(f"[dim]Cuota sincronizada: Gemini {gem_p} | Otros {ext_p}[/dim]")
    else:
        # Si la cuenta activa no tiene email asignado aún, vincularlo
        if state.active and accounts[state.active].email is None:
            accounts[state.active].email = detected_email
            save_accounts(accounts)
            if report and report.pools:
                update_state_from_usage_report(state, state.active, report)
                save_state(state)
            console.print(
                f"[green]✓ Vinculado el email '{detected_email}' a la cuenta activa actual '{state.active}'.[/green]"
            )
            info = state.accounts_quota.get(state.active)
            if info:
                gem_p = f"{info.gemini_percent}%" if info.gemini_percent is not None else "—"
                ext_p = f"{info.external_percent}%" if info.external_percent is not None else "—"
                console.print(f"[dim]Cuota sincronizada: Gemini {gem_p} | Otros {ext_p}[/dim]")
        else:
            console.print(
                f"[yellow][!] El email detectado '{detected_email}' no coincide con ninguna cuenta registrada.[/yellow]"
            )
            console.print(
                f"Usa [bold cyan]agyswitcher add <alias> --email {detected_email}[/bold cyan] para registrarla."
            )


@app.command(
    name="init",
    help=(
        "Prepara un proyecto para continuar entre cuentas y agentes de IA: AGENTS.md, "
        "dev_mem/ESTADO.md, dev_mem/TODO.md, .agyswitcher.toml y los ficheros de cada agente "
        "que remiten a AGENTS.md. Nunca sobrescribe. Ejemplo: agyswitcher init --agents gemini,claude"
    ),
)
def init_project(
    path: Annotated[
        Path,
        typer.Argument(help="Carpeta del proyecto (por defecto, la actual)."),
    ] = Path("."),
    agents: Annotated[
        str,
        typer.Option(
            "--agents",
            "-a",
            help=(
                "Agentes para los que crear su fichero: "
                f"{', '.join(sorted(AGENT_POINTER_FILES))} (separados por comas). "
                "ChatGPT/Codex leen AGENTS.md directamente."
            ),
        ),
    ] = ",".join(DEFAULT_AGENTS),
    name: Annotated[
        str | None,
        typer.Option(
            "--name", help="Nombre del proyecto en las plantillas (por defecto, la carpeta)."
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Mostrar qué se crearía sin escribir nada."),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            help=(
                "Completar ficheros existentes: añade a AGENTS.md la sección de memoria y a los "
                "ficheros de cada agente el aviso que remite a AGENTS.md, sin tocar lo demás."
            ),
        ),
    ] = False,
) -> None:
    """Prepara la estructura de continuidad de un proyecto."""
    try:
        agent_list = parse_agents(agents)
        result = scaffold_project(path, agent_list, project_name=name, dry_run=dry_run, merge=merge)
    except ProjectError as err:
        typer.secho(f"Error: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    root = path.resolve()
    verb = "Se crearía" if dry_run else "Creado"
    for created in result.created:
        console.print(f"[green]{verb}:[/green] {created.resolve().relative_to(root)}")
    merged_verb = "Se completaría" if dry_run else "Completado"
    for merged in result.merged:
        console.print(f"[cyan]{merged_verb}:[/cyan] {merged.resolve().relative_to(root)}")
    for skipped in result.skipped:
        console.print(f"[dim]Ya existe (no se toca): {skipped.resolve().relative_to(root)}[/dim]")
    if result.skipped and not merge:
        console.print(
            "[dim]Si tu AGENTS.md o los ficheros de tus agentes ya existían, 'agyswitcher init "
            "--merge' les añade solo lo que les falta.[/dim]"
        )
    if dry_run:
        console.print("[yellow]Simulación: no se ha escrito nada.[/yellow]")
        return
    console.print(
        "\nSiguiente paso: completa la sección [bold]Proyecto[/bold] de AGENTS.md. Si "
        "[bold]dev_mem/[/bold] no debe publicarse, añádelo a tu .gitignore."
    )


@app.command(
    name="handoff",
    help=(
        "Gestiona las instrucciones y el fichero de traspaso (HANDOFF.md) para continuar "
        "el trabajo entre cuentas o agentes: 'save' (guarda el fichero de traspaso y muestra "
        "la instrucción) y 'resume' (muestra cómo retomar). Ejemplo: agyswitcher handoff save"
    ),
)
def handoff(
    which: Annotated[
        str,
        typer.Argument(help="'save', 'resume' o 'all' (por defecto)."),
    ] = "all",
    note: Annotated[
        str | None,
        typer.Option(
            "--note", "-n", help="Nota opcional sobre el estado para incluir en HANDOFF.md."
        ),
    ] = None,
    copy: Annotated[
        bool,
        typer.Option("--copy", "-c", help="Copiar también la instrucción al portapapeles."),
    ] = False,
) -> None:
    """Muestra las instrucciones de traspaso y gestiona el fichero HANDOFF.md."""
    choice = which.strip().lower()
    if choice not in {"save", "resume", "all"}:
        typer.secho("Error: usa 'save', 'resume' o 'all'.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    if copy and choice == "all":
        typer.secho(
            "Error: con --copy indica qué instrucción copiar: 'save' o 'resume'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    cwd = Path.cwd()
    prompts = load_handoff_prompts(cwd)
    if prompts.error:
        console.print(
            f"[yellow]No se pudo leer {prompts.source}: {prompts.error}. "
            "Se usan las instrucciones por defecto.[/yellow]"
        )
    elif prompts.source is None:
        console.print(
            "[dim]Instrucciones por defecto (personalízalas con 'agyswitcher init', que crea "
            ".agyswitcher.toml).[/dim]"
        )
    else:
        console.print(f"[dim]Instrucciones de {prompts.source}[/dim]")

    if choice in {"save", "all"}:
        active_alias = None
        active_pool = None
        try:
            state = load_state()
            active_alias = state.active
            active_pool = state.active_model_group
        except (StateError, ConfigError):
            pass
        try:
            h_path = write_handoff_file(
                cwd,
                prompts=prompts,
                account=active_alias,
                pool=active_pool,
                notes=note,
            )
            try:
                rel_h = h_path.relative_to(cwd)
            except ValueError:
                rel_h = h_path
            console.print(f"[green]✓ Fichero de traspaso guardado en:[/green] [bold]{rel_h}[/bold]")
        except ProjectError as err:
            console.print(
                f"[yellow]Aviso: no se pudo escribir el fichero de traspaso: {err}[/yellow]"
            )

    h_target = handoff_file_path(cwd)
    try:
        h_rel = h_target.relative_to(cwd)
    except ValueError:
        h_rel = h_target

    if choice in {"save", "all"}:
        console.print("\n[bold]Antes de cambiar de cuenta[/bold], pega esto en agy:")
        _print_prompt("Guardar estado", prompts.save)
        if h_target.is_file():
            console.print(
                f"[dim]Al abrir agy con la nueva cuenta, pídele: 'Lee {h_rel} y continúa'.[/dim]"
            )
    if choice in {"resume", "all"}:
        console.print("\n[bold]Después de cambiar de cuenta[/bold], indica en agy:")
        if h_target.is_file():
            console.print(f"  [bold cyan]Lee {h_rel} y continúa[/bold cyan]\n")
        _print_prompt("Retomar", prompts.resume)
    if copy:
        text = prompts.save if choice == "save" else prompts.resume
        if copy_to_clipboard(text):
            console.print("[green]✓ Instrucción copiada al portapapeles.[/green]")
        else:
            typer.secho(
                "No se pudo copiar al portapapeles; copia el texto de arriba.",
                fg=typer.colors.YELLOW,
            )


_ON_VALUES = {"on", "si", "sí", "true", "1"}
_OFF_VALUES = {"off", "no", "false", "0"}


def _show_settings(settings: Settings) -> None:
    """Muestra los ajustes globales y el umbral efectivo en la carpeta actual."""
    low = settings.low_quota_percent
    console.print(f"Ajustes de AgySwitcher ([dim]{default_config_path()}[/dim]):")
    console.print(
        f"  low-quota  Umbral de cuota baja: "
        f"{f'{low} %' if low is not None else '20 % (por defecto)'}"
    )
    console.print(
        "  auto-copy  Copia automática al portapapeles: "
        f"{'activada' if settings.auto_copy else 'desactivada'}"
    )
    threshold = resolve_low_quota_threshold(Path.cwd(), low)
    if threshold.source == "proyecto":
        console.print(
            f"[dim]En esta carpeta manda el proyecto: {threshold.percent} % "
            f"({threshold.project_file}).[/dim]"
        )
    elif threshold.error:
        console.print(
            f"[yellow]Umbral de {threshold.project_file} ignorado: "
            f"{escape(threshold.error)}.[/yellow]"
        )


@app.command(
    name="config",
    help=(
        "Muestra o cambia los ajustes globales: 'low-quota' (umbral del aviso de cuota baja, "
        "1-99 o 'default') y 'auto-copy' (on/off). Ejemplo: agyswitcher config low-quota 20"
    ),
)
def config_command(
    key: Annotated[str | None, typer.Argument(help="Ajuste: 'low-quota' o 'auto-copy'.")] = None,
    value: Annotated[
        str | None,
        typer.Argument(help="Nuevo valor: 1-99 o 'default' (low-quota); on/off (auto-copy)."),
    ] = None,
) -> None:
    """Muestra o cambia los ajustes globales de AgySwitcher."""
    try:
        settings = load_settings()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if key is None:
        _show_settings(settings)
        return

    name = key.strip().lower()
    if name not in {"low-quota", "auto-copy"}:
        typer.secho(
            f"Error: ajuste desconocido '{key}'. Usa 'low-quota' o 'auto-copy'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    if value is None:
        _show_settings(settings)
        return

    raw = value.strip().lower()
    if name == "low-quota":
        if raw == "default":
            settings.low_quota_percent = None
        else:
            try:
                number = int(raw)
            except ValueError:
                number = 0
            if not LOW_QUOTA_MIN <= number <= LOW_QUOTA_MAX:
                typer.secho(
                    f"Error: el umbral debe ser un número de {LOW_QUOTA_MIN} a {LOW_QUOTA_MAX} "
                    "o 'default'.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=1)
            settings.low_quota_percent = number
    else:
        if raw in _ON_VALUES:
            settings.auto_copy = True
        elif raw in _OFF_VALUES:
            settings.auto_copy = False
        else:
            typer.secho("Error: usa 'on' u 'off'.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

    try:
        save_settings(settings)
    except (ConfigError, OSError) as err:
        typer.secho(f"Error al guardar la configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err
    typer.secho("Ajuste guardado.", fg=typer.colors.GREEN)
    _show_settings(settings)


def _format_timestamp(ts_str: str) -> str:
    """Parsea una cadena de fecha ISO o devuelve la cadena original si falla."""
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError):
        return ts_str


def check_session_mismatch(
    accounts: dict[str, Account],
    active_alias: str | None,
    detected_email: str | None = None,
) -> tuple[str, str | None] | None:
    """Comprueba si hay discrepancia entre la cuenta activa y el email en la sesión de agy.

    Args:
        accounts: Diccionario de cuentas configuradas.
        active_alias: Alias de la cuenta actualmente activa.
        detected_email: Email detectado (opcional; si es None se llama a detect_active_email()).

    Returns:
        None si no hay discrepancia detectada (o no se pudo detectar email).
        (detected_email, matching_alias) si hay discrepancia.
    """
    if not active_alias:
        return None
    active_acc = accounts.get(active_alias)
    email_to_check = detected_email if detected_email is not None else detect_active_email()
    if not email_to_check:
        return None

    if active_acc and active_acc.email:
        if active_acc.email.lower() != email_to_check.lower():
            matching_alias = next(
                (
                    alias
                    for alias, acc in accounts.items()
                    if acc.email and acc.email.lower() == email_to_check.lower()
                ),
                None,
            )
            return (email_to_check, matching_alias)
    else:
        matching_alias = next(
            (
                alias
                for alias, acc in accounts.items()
                if acc.email and acc.email.lower() == email_to_check.lower()
            ),
            None,
        )
        if matching_alias and matching_alias != active_alias:
            return (email_to_check, matching_alias)

    return None


def print_session_mismatch_warning(
    detected_email: str,
    active_alias: str,
    matching_alias: str | None,
    active_email: str | None = None,
) -> None:
    """Imprime una advertencia si la sesión activa en agy no coincide con la cuenta activa."""
    acc_desc = f"'{active_alias}'"
    if active_email:
        acc_desc += f" (vinculada a [bold cyan]{active_email}[/bold cyan])"

    console.print(
        f"\n[bold yellow][!] Desajuste de cuenta detectado:[/bold yellow] La sesión activa en agy es "
        f"[bold cyan]{detected_email}[/bold cyan], pero la cuenta activa en AgySwitcher es {acc_desc}."
    )
    if matching_alias:
        console.print(
            f"[yellow]Esa sesión corresponde al alias registrado '[bold]{matching_alias}[/bold]'.[/yellow]"
        )
        console.print(
            f"Sugerencia: Ejecuta [bold cyan]agyswitcher set-active {matching_alias}[/bold cyan] o "
            f"[bold cyan]agyswitcher sync[/bold cyan] para sincronizar."
        )
    else:
        console.print(
            "Sugerencia: Ejecuta [bold cyan]agyswitcher sync[/bold cyan] para sincronizar la cuenta activa."
        )


def get_earliest_reset_time(
    alias: str,
    info: AccountQuotaInfo | None,
    state: AppState,
) -> datetime | None:
    """Calcula la fecha de reinicio semanal más próxima para una cuenta (mínimo entre Gemini y Otros)."""
    resets: list[datetime] = []
    pairs = [
        (info.gemini_reset_time if info else None, state.gemini_quota_exhausted.get(alias)),
        (info.external_reset_time if info else None, state.external_quota_exhausted.get(alias)),
    ]
    for rt, fallback_iso in pairs:
        target = rt
        if target is None and fallback_iso:
            with contextlib.suppress(ValueError, TypeError):
                dt = datetime.fromisoformat(fallback_iso)
                target = dt + timedelta(days=7)
        if target is not None:
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            resets.append(target)
    return min(resets) if resets else None


@app.command(
    name="list",
    help="Lista todas las cuentas configuradas, sus porcentajes de cuota y tiempos de reinicio. Ejemplo: agyswitcher list",
)
def list_accounts(
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            "-l",
            help="Forzar consulta de métricas de cuota en vivo para la cuenta activa antes de listar.",
        ),
    ] = False,
    cached: Annotated[
        bool,
        typer.Option(
            "--cached",
            "-c",
            help="Usar exclusivamente métricas en caché sin consultar agy.exe.",
        ),
    ] = False,
    refresh_all: Annotated[
        bool,
        typer.Option(
            "--refresh-all",
            "-a",
            help=(
                "Obsoleto: equivale a --live. Solo se puede consultar la cuota de la cuenta con "
                "sesión iniciada en agy."
            ),
        ),
    ] = False,
) -> None:
    """Lista todas las cuentas configuradas con porcentajes de cuota y próximo reinicio."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        console.print(
            "No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una."
        )
        return

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if refresh_all:
        console.print(
            "[dim]agy solo tiene una sesión: se consulta la cuota de la cuenta con sesión "
            "iniciada. La del resto se actualiza al cambiar a ellas (set-active).[/dim]"
        )
        live = True

    report: UsageReport | None = None
    should_refresh = live
    if not cached and not live and state.active:
        info = state.accounts_quota.get(state.active)
        if info is None or info.updated_at is None:
            should_refresh = True
        else:
            age = (datetime.now(UTC) - info.updated_at).total_seconds()
            if age > 180:
                should_refresh = True

    if should_refresh and state.active:
        with contextlib.suppress(*USAGE_FETCH_ERRORS):
            report = fetch_usage(timeout=10.0)
            owner = _report_owner(accounts, state, report) if report else None
            if report and report.pools and owner:
                update_state_from_usage_report(state, owner, report)
                with contextlib.suppress(StateError):
                    save_state(state)

    table = Table(
        title="Cuentas configuradas en AgySwitcher",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Cuenta", min_width=12)
    table.add_column("Email", min_width=12)
    table.add_column("Cuota\nGemini / Otros", justify="center", min_width=14)
    table.add_column("Reinicio Cuota\nGemini / Otros", justify="center", min_width=14)
    table.add_column("Registrada (UTC)", justify="center", min_width=12)

    def _pct_str(exhausted: bool, pct: int | None) -> str:
        """Cadena coloreada de porcentaje de cuota para un pool."""
        if exhausted:
            return "[red]0% (agotado)[/red]"
        if pct is not None:
            if pct >= 50:
                return f"[green]{pct}%[/green]"
            if pct >= 20:
                return f"[yellow]{pct}%[/yellow]"
            return f"[red]{pct}%[/red]"
        return "[dim]—[/dim]"

    def _reset_str(reset_time: datetime | None, exhausted: bool, fallback_iso: str | None) -> str:
        """Cadena de reinicio de cuota para un pool."""
        target: datetime | None = reset_time
        if target is None and fallback_iso:
            with contextlib.suppress(ValueError, TypeError):
                target = datetime.fromisoformat(fallback_iso) + timedelta(days=7)
        if target is None:
            return "[dim]—[/dim]"
        rel_t = format_time_remaining(target)
        dt_part = target.strftime("%d/%m %H:%M")
        if rel_t == "En reinicio":
            return "[green]En reinicio[/green]"
        if exhausted:
            return f"[bold yellow]en {rel_t}[/bold yellow] [dim]({dt_part})[/dim]"
        return f"[cyan]en {rel_t}[/cyan] [dim]({dt_part})[/dim]"

    # Ordenación de cuentas: cuenta activa primero, luego por reinicio más próximo ascendente
    active_alias = state.active
    standby_aliases = [a for a in accounts if a != active_alias]

    def _sort_key(alias: str) -> tuple[int, datetime, str]:
        info = state.accounts_quota.get(alias)
        earliest = get_earliest_reset_time(alias, info, state)
        if earliest is None:
            # Cuentas sin fecha de reinicio van al final, ordenadas alfabéticamente
            return (1, datetime.max.replace(tzinfo=UTC), alias)
        # Cuentas con fecha de reinicio más cercana primero
        return (0, earliest, alias)

    standby_aliases.sort(key=_sort_key)

    ordered_aliases = (
        [active_alias] if active_alias and active_alias in accounts else []
    ) + standby_aliases

    for alias in ordered_aliases:
        acc = accounts[alias]
        is_active = alias == state.active
        gemini_exhausted = alias in state.gemini_quota_exhausted
        external_exhausted = alias in state.external_quota_exhausted
        info = state.accounts_quota.get(alias)

        email_str = acc.email if acc.email else "-"

        account_cell = f"[bold green]* {alias}[/bold green]" if is_active else f"  {alias}"

        gemini_pct_str = _pct_str(gemini_exhausted, info.gemini_percent if info else None)
        ext_pct_str = _pct_str(external_exhausted, info.external_percent if info else None)
        quota_col = f"{gemini_pct_str}\n{ext_pct_str}"

        gemini_reset_str = _reset_str(
            info.gemini_reset_time if info else None,
            gemini_exhausted,
            state.gemini_quota_exhausted.get(alias),
        )
        ext_reset_str = _reset_str(
            info.external_reset_time if info else None,
            external_exhausted,
            state.external_quota_exhausted.get(alias),
        )
        reset_col = f"{gemini_reset_str}\n{ext_reset_str}"

        date_str = acc.added_at.strftime("%Y-%m-%d %H:%M")
        table.add_row(
            account_cell,
            email_str,
            quota_col,
            reset_col,
            date_str,
        )

    console.print(table)
    _warn_low_quota(accounts, state)

    active_email_override = report.active_email if (report and report.active_email) else None
    mismatch = check_session_mismatch(accounts, state.active, detected_email=active_email_override)
    if mismatch and state.active:
        det_email, match_alias = mismatch
        act_acc = accounts.get(state.active)
        act_email = act_acc.email if act_acc else None
        print_session_mismatch_warning(det_email, state.active, match_alias, active_email=act_email)


def _render_level_bar(remaining_percent: int, length: int = 15) -> str:
    """Renderiza una barra de progreso textual con código de colores según nivel."""
    filled = int(round((max(0, min(100, remaining_percent)) / 100.0) * length))
    bar_str = "█" * filled + "░" * (length - filled)
    if remaining_percent >= 50:
        return f"[green]{bar_str}[/green]"
    if remaining_percent >= 20:
        return f"[yellow]{bar_str}[/yellow]"
    return f"[red]{bar_str}[/red]"


@app.command(
    help="Muestra el estado detallado de la cuenta activa. Ejemplo: agyswitcher status --live",
)
def status(
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            "-l",
            help="Consultar métricas de cuota y autenticación en vivo para la cuenta activa.",
        ),
    ] = False,
) -> None:
    """Muestra el estado detallado de la cuenta activa y el conjunto de cuotas."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        console.print(
            "No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una."
        )
        return

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    total_accounts = len(accounts)
    gemini_exhausted_count = len(state.gemini_quota_exhausted)
    external_exhausted_count = len(state.external_quota_exhausted)
    fully_exhausted_count = sum(1 for alias in accounts if state.is_account_fully_exhausted(alias))
    available_count = total_accounts - fully_exhausted_count

    active_alias = state.active
    active_account = accounts.get(active_alias) if active_alias else None

    # Determinación del estado de la cuenta activa
    if active_alias is None or active_account is None:
        active_desc = "[bold red]Ninguna[/bold red]"
        added_desc = "N/A"
        pool_desc = "N/A"
    else:
        active_gemini_ok = active_alias not in state.gemini_quota_exhausted
        active_external_ok = active_alias not in state.external_quota_exhausted

        if not active_gemini_ok and not active_external_ok:
            active_desc = f"[bold red]{active_alias} [AGOTADA][/bold red]"
        elif (state.active_model_group == "gemini" and active_gemini_ok) or (
            state.active_model_group == "external" and active_external_ok
        ):
            active_desc = f"[bold green]{active_alias} [ACTIVA][/bold green]"
        else:
            active_desc = f"[bold yellow]{active_alias} [POOL CAMBIADO][/bold yellow]"

        gemini_status = "[green]disponible[/green]" if active_gemini_ok else "[red]agotado[/red]"
        external_status = (
            "[green]disponible[/green]" if active_external_ok else "[red]agotado[/red]"
        )
        pool_desc = (
            f"[bold]{state.active_model_group}[/bold]  "
            f"(gemini: {gemini_status} / external: {external_status})"
        )
        added_desc = active_account.added_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Panel de resumen principal
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()
    grid.add_row("Cuenta activa:", active_desc)
    email_desc = (
        active_account.email
        if active_account and active_account.email
        else "[dim]no vinculado[/dim]"
    )
    grid.add_row("Email Google:", email_desc)
    grid.add_row("Pool activo:", pool_desc)
    grid.add_row("Registrada el:", added_desc)
    grid.add_row("Total cuentas:", str(total_accounts))
    grid.add_row("Disponibles:", f"[green]{available_count}[/green]")
    grid.add_row(
        "Gemini agotadas:",
        f"[yellow]{gemini_exhausted_count}[/yellow]" if gemini_exhausted_count else "0",
    )
    grid.add_row(
        "External agotadas:",
        f"[yellow]{external_exhausted_count}[/yellow]" if external_exhausted_count else "0",
    )
    grid.add_row("Historial:", f"{len(state.switch_history)} cambios registrados")

    panel = Panel(grid, title="[bold]AgySwitcher - Estado[/bold]", box=box.ROUNDED, expand=False)
    console.print(panel)

    # Advertencias si aplican
    mismatch = check_session_mismatch(accounts, active_alias)
    if mismatch and active_alias:
        det_email, match_alias = mismatch
        act_email = active_account.email if active_account else None
        print_session_mismatch_warning(det_email, active_alias, match_alias, active_email=act_email)

    if active_alias is None or active_account is None:
        console.print(
            "\n[bold yellow][!] Advertencia:[/bold yellow] No hay ninguna cuenta activa válida. "
            "Usa 'agyswitcher rotate <alias>' para seleccionar una."
        )
    elif state.is_account_fully_exhausted(active_alias):
        console.print(
            f"\n[bold red][!] Advertencia:[/bold red] La cuenta activa '{active_alias}' "
            "tiene ambos pools de cuota agotados. Usa 'agyswitcher rotate' para cambiar de cuenta."
        )
    elif active_alias in state.gemini_quota_exhausted:
        console.print(
            f"\n[bold yellow][!] Info:[/bold yellow] Pool Gemini agotado en '{active_alias}'. "
            "Usando modelos externos (Claude / GPT-OSS)."
        )
    elif active_alias in state.external_quota_exhausted:
        console.print(
            f"\n[bold yellow][!] Info:[/bold yellow] Pool external agotado en '{active_alias}'. "
            "Usando modelos Gemini."
        )

    # Detalle de cuotas agotadas si existen
    has_gemini_exhausted = bool(state.gemini_quota_exhausted)
    has_external_exhausted = bool(state.external_quota_exhausted)

    if has_gemini_exhausted or has_external_exhausted:
        table_cd = Table(
            title="Cuotas agotadas por pool",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold yellow",
        )
        table_cd.add_column("Cuenta")
        table_cd.add_column("Gemini agotado desde (UTC)")
        table_cd.add_column("External agotado desde (UTC)")

        all_aliases = sorted(
            set(state.gemini_quota_exhausted) | set(state.external_quota_exhausted)
        )
        for alias in all_aliases:
            gemini_ts = (
                _format_timestamp(state.gemini_quota_exhausted[alias])
                if alias in state.gemini_quota_exhausted
                else "-"
            )
            external_ts = (
                _format_timestamp(state.external_quota_exhausted[alias])
                if alias in state.external_quota_exhausted
                else "-"
            )
            table_cd.add_row(alias, gemini_ts, external_ts)
        console.print(table_cd)

    if live:
        if active_alias is None or active_account is None:
            console.print(
                "\n[yellow]No se pueden consultar métricas en vivo porque no hay cuenta activa válida.[/yellow]"
            )
        else:
            console.print(
                f"\n[bold cyan]Consultando métricas en vivo para '{active_alias}'...[/bold cyan]"
            )
            try:
                report = fetch_usage()
                if report.pools:
                    table_live = Table(
                        title=f"Métricas en vivo (cuenta '{active_alias}')",
                        box=box.ROUNDED,
                        show_header=True,
                        header_style="bold cyan",
                    )
                    table_live.add_column("Pool")
                    table_live.add_column("Restante", justify="right")
                    table_live.add_column("Consumido", justify="right")
                    table_live.add_column("Nivel", justify="center")
                    table_live.add_column("Próximo reinicio semanal (UTC)")

                    for pool_key in ("gemini", "external"):
                        p = report.pools.get(pool_key)
                        if p is None:
                            continue
                        time_rel = format_time_remaining(p.reset_time)
                        reset_str = (
                            f"{p.reset_time.strftime('%Y-%m-%d %H:%M:%S')} ({time_rel})"
                            if p.reset_time
                            else (p.reset_raw or "-")
                        )
                        pct_rem_str = (
                            f"[bold green]{p.remaining_percent}%[/bold green]"
                            if p.remaining_percent >= 50
                            else (
                                f"[bold yellow]{p.remaining_percent}%[/bold yellow]"
                                if p.remaining_percent >= 20
                                else f"[bold red]{p.remaining_percent}%[/bold red]"
                            )
                        )
                        table_live.add_row(
                            f"{p.display_name} ({p.pool})",
                            pct_rem_str,
                            f"{p.consumed_percent}%",
                            _render_level_bar(p.remaining_percent),
                            reset_str,
                        )
                    console.print(table_live)
                    owner = _report_owner(accounts, state, report)
                    if owner:
                        update_state_from_usage_report(state, owner, report)
                    with contextlib.suppress(StateError):
                        save_state(state)
            except (AgyNotFoundError, AuthRequiredError, UsageError) as err:
                console.print(
                    f"[bold red]Error al consultar métricas en vivo:[/bold red] {escape(str(err))}"
                )

    _warn_low_quota(accounts, state)


@app.command(
    help="Muestra el panel de control con las cuentas y sus métricas de cuota. Ejemplo: agyswitcher dashboard --watch",
)
def dashboard(
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            "-l",
            help="Consultar métricas de cuota y sesión en vivo con agy.exe.",
        ),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            "-w",
            help="Modo interactivo continuo que actualiza el dashboard periódicamente.",
        ),
    ] = False,
    interval: Annotated[
        float,
        typer.Option(
            "--interval",
            "-i",
            help="Intervalo de refresco en segundos para el modo continuo.",
            min=1.0,
        ),
    ] = 3.0,
) -> None:
    """Muestra el centro de control TUI de AgySwitcher con matriz de cuentas y métricas."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    def _get_usage_report() -> UsageReport | None:
        if not live or not state.active:
            return None
        with contextlib.suppress(*USAGE_FETCH_ERRORS):
            rep = fetch_usage(timeout=10.0)
            owner = _report_owner(accounts, state, rep) if rep else None
            if rep and rep.pools and owner:
                update_state_from_usage_report(state, owner, rep)
                with contextlib.suppress(StateError):
                    save_state(state)
            return rep
        return None

    if not watch:
        report = _get_usage_report()
        view = build_dashboard_view(accounts, state, usage_report=report)
        console.print(view)
        return

    from rich.live import Live

    initial_report = _get_usage_report()
    view = build_dashboard_view(accounts, state, usage_report=initial_report)

    try:
        with Live(view, console=console, refresh_per_second=2, screen=False) as live_display:
            while True:
                time.sleep(interval)
                with contextlib.suppress(ConfigError):
                    accounts = load_accounts()
                with contextlib.suppress(StateError):
                    state = load_state()
                report = _get_usage_report()
                live_display.update(build_dashboard_view(accounts, state, usage_report=report))
    except KeyboardInterrupt:
        console.print("\n[yellow]Modo dashboard detenido por el usuario.[/yellow]")


@app.command(
    help="Consulta la sesión y la cuota semanal restante de los pools Gemini y Otros. Ejemplo: agyswitcher usage",
)
def usage(
    sync: Annotated[
        bool,
        typer.Option(
            "--sync/--no-sync",
            help="Sincronizar automáticamente el estado local de cuotas con las lecturas en vivo.",
        ),
    ] = True,
    timeout: Annotated[
        float,
        typer.Option(help="Timeout en segundos para la consulta a agy.", min=1.0),
    ] = 15.0,
) -> None:
    """Muestra el estado de la sesión y la cuota semanal restante de los pools Gemini y External."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        console.print(
            "No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una."
        )
        return

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    active_alias = state.active
    target_name = active_alias if active_alias else "sin cuenta activa"
    console.print(f"[bold cyan]Consultando métricas de cuota para '{target_name}'...[/bold cyan]")

    try:
        report = fetch_usage(timeout=timeout)
    except AgyNotFoundError as err:
        typer.secho(f"Error: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err
    except AuthRequiredError as err:
        typer.secho(f"Error de autenticación: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err
    except UsageError as err:
        typer.secho(f"Error de consulta de cuota: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    # Panel de autenticación y resumen
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()
    grid.add_row("Cuenta activa:", f"[bold]{active_alias}[/bold]" if active_alias else "Ninguna")
    active_acc = accounts.get(active_alias) if active_alias else None
    email_display = (
        report.active_email
        or (active_acc.email if active_acc and active_acc.email else None)
        or "[dim]no vinculado[/dim]"
    )
    grid.add_row("Email Google:", email_display)
    grid.add_row(
        "Sesión Google:",
        "[bold green]✓ Autenticada y Activa[/bold green]"
        if report.is_authenticated
        else "[bold red]✗ No autenticada[/bold red]",
    )
    grid.add_row("Última comprobación:", report.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"))

    panel = Panel(
        grid,
        title="[bold]AgySwitcher - Autenticación y Cuota[/bold]",
        box=box.ROUNDED,
        expand=False,
    )
    console.print(panel)

    if not report.pools:
        console.print("[yellow]No se detectaron métricas de pools en la salida de agy.[/yellow]")
        return

    # Verificación de desajuste de identidad entre la sesión real y la cuenta activa
    detected_email = report.active_email
    if (
        detected_email
        and active_acc
        and active_acc.email
        and active_acc.email.lower() != detected_email.lower()
    ):
        console.print(
            f"\n[bold yellow][!] Desajuste de cuenta detectado:[/bold yellow] La sesión activa en agy es "
            f"[bold cyan]{detected_email}[/bold cyan], pero la cuenta activa configurada '{active_alias}' "
            f"está vinculada a [bold cyan]{active_acc.email}[/bold cyan]."
        )
        other_matches = [
            alias
            for alias, a in accounts.items()
            if a.email and a.email.lower() == detected_email.lower()
        ]
        if other_matches:
            console.print(
                f"[yellow]Esa sesión corresponde al alias registrado '[bold]{other_matches[0]}[/bold]'.[/yellow]"
            )
            console.print(
                f"Ejecuta [bold cyan]agyswitcher set-active {other_matches[0]}[/bold cyan] o "
                f"[bold cyan]agyswitcher sync[/bold cyan] para conmutar a esa cuenta."
            )
        else:
            console.print(
                "Ejecuta [bold cyan]agyswitcher sync[/bold cyan] para actualizar la cuenta activa."
            )
        console.print(
            f"[dim]No se modificará el estado de cuota de '{active_alias}' para evitar contaminar métricas.[/dim]\n"
        )
        return

    # Auto-vincular email si la cuenta activa no lo tenía registrado
    if detected_email and active_acc and not active_acc.email:
        other_with_email = any(
            a.email and a.email.lower() == detected_email.lower() for a in accounts.values()
        )
        if not other_with_email:
            active_acc.email = detected_email
            with contextlib.suppress(ConfigError):
                save_accounts(accounts)
            console.print(
                f"[dim]✓ Vinculado automáticamente el email '{detected_email}' a la cuenta '{active_alias}'.[/dim]"
            )

    table = Table(
        title="Cuota semanal por pool",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Pool")
    table.add_column("Restante", justify="right")
    table.add_column("Consumido", justify="right")
    table.add_column("Nivel", justify="center")
    table.add_column("Próximo reinicio semanal (UTC)")

    for pool_key in ("gemini", "external"):
        p = report.pools.get(pool_key)
        if p is None:
            continue
        time_rel = format_time_remaining(p.reset_time)
        reset_str = (
            f"{p.reset_time.strftime('%Y-%m-%d %H:%M:%S')} ({time_rel})"
            if p.reset_time
            else (p.reset_raw or "-")
        )
        pct_rem_str = (
            f"[bold green]{p.remaining_percent}%[/bold green]"
            if p.remaining_percent >= 50
            else (
                f"[bold yellow]{p.remaining_percent}%[/bold yellow]"
                if p.remaining_percent >= 20
                else f"[bold red]{p.remaining_percent}%[/bold red]"
            )
        )
        table.add_row(
            f"{p.display_name} ({p.pool})",
            pct_rem_str,
            f"{p.consumed_percent}%",
            _render_level_bar(p.remaining_percent),
            reset_str,
        )

    console.print(table)

    # Sincronización automática de estado y persistencia de métricas
    if active_alias:
        was_gemini_ex = active_alias in state.gemini_quota_exhausted
        was_ext_ex = active_alias in state.external_quota_exhausted
        update_state_from_usage_report(state, active_alias, report, sync_cooldowns=sync)
        if sync:
            if was_gemini_ex and active_alias not in state.gemini_quota_exhausted:
                console.print(
                    f"[green]✓ Cuota de Gemini disponible de nuevo. Cooldown levantado para '{active_alias}'.[/green]"
                )
            if was_ext_ex and active_alias not in state.external_quota_exhausted:
                console.print(
                    f"[green]✓ Cuota de External disponible de nuevo. Cooldown levantado para '{active_alias}'.[/green]"
                )
        try:
            save_state(state)
        except StateError as err:
            typer.secho(
                f"Advertencia al guardar estado: {err}",
                fg=typer.colors.YELLOW,
                err=True,
            )


@app.command(
    help=(
        "Cambia al otro pool de la cuenta activa o, con el cambio guiado, a la siguiente cuenta "
        "con cuota (o al alias indicado). Ejemplo: agyswitcher rotate / agyswitcher rotate trabajo"
    ),
)
def rotate(
    alias: Annotated[
        str,
        typer.Argument(help="Alias destino (vacío = siguiente candidato disponible)."),
    ] = "",
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Segundos máximos de espera del inicio de sesión."),
    ] = DEFAULT_LOGIN_TIMEOUT,
) -> None:
    """Rota manualmente a la siguiente cuenta o pool disponible, o a un alias específico."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        typer.secho(
            "Error: No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    clean_alias = alias.strip()

    if clean_alias:
        if clean_alias not in accounts:
            typer.secho(
                f"Error: La cuenta '{clean_alias}' no está registrada.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)

        target_alias = clean_alias
        target_pool = state.available_group_for(clean_alias) or "gemini"
        if state.is_account_fully_exhausted(clean_alias):
            typer.secho(
                f"Advertencia: La cuenta '{clean_alias}' tiene ambos pools agotados.",
                fg=typer.colors.YELLOW,
            )
    else:
        candidate = select_next_candidate(accounts, state)
        if candidate is None:
            _print_all_exhausted(accounts, state)
            raise typer.Exit(code=1)
        target_alias, target_pool = candidate
        if state.is_pool_exhausted(target_alias, target_pool):
            console.print(
                f"[yellow]El reinicio previsto de '{escape(target_alias)}' ya pasó: su cuota "
                "debería estar disponible (sin confirmar).[/yellow]"
            )

    if target_alias != state.active:
        msg = _guided_account_switch(target_alias, target_pool, accounts, state, timeout)
        typer.secho(msg, fg=typer.colors.GREEN)
        _print_resume_hint()
        _refresh_quota_after_switch(target_alias, accounts, state)
        return

    try:
        msg = record_rotation(target_alias, target_pool, state)
    except StateError as err:
        typer.secho(f"Error al guardar el estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err
    typer.secho(msg, fg=typer.colors.GREEN)


def _propose_after_exhaustion(accounts: dict[str, Account], state: AppState) -> str | None:
    """Reacciona a una cuota agotada de la cuenta activa (ya registrada en ``state``).

    Si el pool activo sigue disponible no hace nada. Si la cuenta activa aún tiene el otro
    pool, cambia de pool (no requiere iniciar sesión). Si no, propone la siguiente cuenta con
    cuota y el comando para cambiar, sin cambiarla: eso exige iniciar sesión en agy.

    Args:
        accounts: Cuentas registradas.
        state: Estado actual (se modifica y guarda si se cambia de pool).

    Returns:
        El pool nuevo si se cambió de pool en la cuenta activa; None en otro caso.

    Raises:
        StateError: Si no se puede guardar el cambio de pool.
    """
    active = state.active
    current_pool = state.active_model_group
    exhausted = (
        state.gemini_quota_exhausted if current_pool == "gemini" else state.external_quota_exhausted
    )
    if active is not None and active not in exhausted:
        typer.secho(
            f"Los modelos del pool activo ({current_pool}) siguen disponibles en '{active}'.",
            fg=typer.colors.CYAN,
        )
        return None

    candidate = select_next_candidate(accounts, state)
    if candidate and state.is_pool_exhausted(*candidate):
        typer.secho(
            f"El reinicio previsto de '{candidate[0]}' ({candidate[1]}) ya pasó: su cuota "
            "debería estar disponible (sin confirmar).",
            fg=typer.colors.YELLOW,
        )
    if candidate and candidate[0] == active:
        # Misma cuenta, otro pool: no requiere iniciar sesión.
        rot_msg = record_rotation(candidate[0], candidate[1], state)
        typer.secho(f"⚡ {rot_msg}", fg=typer.colors.GREEN)
        return candidate[1]
    if candidate:
        # Cambiar de cuenta exige iniciar sesión: solo se propone.
        next_alias = candidate[0]
        next_email = accounts[next_alias].email or "(sin email)"
        typer.secho(
            f"Siguiente cuenta con cuota: '{next_alias}' ({next_email}). "
            f"Para cambiar: agyswitcher set-active {next_alias}",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            "Si el agente aún responde, guarda antes el estado: agyswitcher handoff save",
            fg=typer.colors.CYAN,
        )
    else:
        _print_all_exhausted(accounts, state)
    return None


@app.command(
    help=(
        "Supervisa los logs de agy; al detectar cuota agotada cambia de pool o propone la "
        "siguiente cuenta. Ejemplo: agyswitcher watch"
    ),
)
def watch(
    interval: Annotated[
        float,
        typer.Option("--interval", "-i", help="Intervalo de verificación en segundos."),
    ] = 2.0,
    once: Annotated[
        bool,
        typer.Option("--once", help="Ejecutar una sola comprobación de registros y salir."),
    ] = False,
    from_start: Annotated[
        bool,
        typer.Option("--from-start", help="Leer registros desde el inicio del archivo."),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option("--log-file", help="Ruta alternativa al archivo de log a supervisar."),
    ] = None,
) -> None:
    """Supervisa los registros de agy y rota automáticamente al detectar cuota agotada."""
    target_log = log_file or (default_live_dir() / "antigravity-cli" / "cli.log")

    typer.echo(f"Iniciando modo watch (supervisando: {target_log}). Presiona Ctrl+C para salir.")

    try:
        accounts = load_accounts()
        state = load_state()
    except (ConfigError, StateError) as err:
        typer.secho(f"Error de inicialización: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        typer.secho(
            "No hay cuentas configuradas. Registra una con 'agyswitcher add <alias>'.",
            fg=typer.colors.YELLOW,
        )
        return

    detector = QuotaDetector(default_pool=state.active_model_group)
    last_pos = 0
    if target_log.exists() and not from_start and not once:
        with contextlib.suppress(OSError):
            last_pos = target_log.stat().st_size

    try:
        while True:
            if target_log.exists():
                try:
                    with target_log.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos)
                        new_lines = f.readlines()
                        last_pos = f.tell()

                    for line in new_lines:
                        event = detector.detect_in_line(line)
                        if event is not None and state.active is not None:
                            now_iso = event.timestamp.isoformat()
                            if event.pool == "gemini":
                                state.gemini_quota_exhausted[state.active] = now_iso
                            else:
                                state.external_quota_exhausted[state.active] = now_iso
                            save_state(state)

                            typer.secho(
                                f"\n[!] Detectada cuota agotada ({event.pool}) en cuenta '{state.active}'.",
                                fg=typer.colors.YELLOW,
                            )
                            new_pool = _propose_after_exhaustion(accounts, state)
                            if new_pool is not None:
                                detector.default_pool = new_pool
                except OSError as err:
                    typer.secho(f"Error al leer log: {err}", fg=typer.colors.RED, err=True)

            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("\nModo watch detenido por el usuario.")


_DOCTOR_LABELS = {
    CheckStatus.OK: "[green]OK[/green]",
    CheckStatus.INFO: "[cyan]info[/cyan]",
    CheckStatus.WARN: "[yellow]aviso[/yellow]",
    CheckStatus.FAIL: "[bold red]error[/bold red]",
}


@app.command(name="doctor")
def doctor(
    show_emails: Annotated[
        bool,
        typer.Option(
            "--show-emails",
            help="Mostrar los emails completos (por defecto se enmascaran para poder compartir "
            "la salida).",
        ),
    ] = False,
) -> None:
    """Diagnostica la instalación: agy, cuentas, sesión, datos de cuota y proyecto actual.

    Solo lee: no cambia nada, no consulta la cuota y no lee tokens. Sale con código 1 si
    alguna comprobación falla. Ejemplo: agyswitcher doctor
    """
    checks = run_doctor(
        Path.cwd(),
        DoctorOptions(show_emails=show_emails),
        email_detector=detect_active_email,
        process_lister=find_running_agy_processes,
    )
    table = Table(box=box.ROUNDED, title="Diagnóstico de AgySwitcher", show_lines=False)
    table.add_column("Estado", no_wrap=True)
    table.add_column("Comprobación", style="bold", no_wrap=True)
    table.add_column("Detalle")
    for check in checks:
        detail = escape(check.detail)
        if check.hint and check.status is not CheckStatus.OK:
            detail += "\n[dim]-> " + escape(check.hint) + "[/dim]"
        table.add_row(_DOCTOR_LABELS[check.status], escape(check.name), detail)
    console.print(table)

    counts = {status: sum(c.status is status for c in checks) for status in CheckStatus}
    summary = (
        f"{counts[CheckStatus.FAIL]} errores · {counts[CheckStatus.WARN]} avisos · "
        f"{counts[CheckStatus.OK]} correctas"
    )
    worst = worst_status(checks)
    if worst is CheckStatus.FAIL:
        console.print(f"[bold red]{summary}[/bold red]")
        raise typer.Exit(code=1)
    if worst is CheckStatus.WARN:
        console.print(f"[yellow]{summary}[/yellow]")
    else:
        console.print(f"[green]{summary}. Todo en orden.[/green]")
    if not show_emails:
        console.print("[dim]Los emails aparecen enmascarados; puedes compartir esta salida.[/dim]")


@app.command(
    name="models",
    help="Lista los modelos disponibles de agy y gestiona las preferencias por pool. Ejemplo: agyswitcher models / agyswitcher models --set gemini-3.8-flash-high",
)
def models(
    set_model: Annotated[
        str | None,
        typer.Option(
            "--set",
            "-s",
            help="Establece este modelo como preferido para su pool en la cuenta activa (o la indicada con --account).",
        ),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option(
            "--clear",
            help="Elimina las preferencias de modelos configuradas en la cuenta.",
        ),
    ] = False,
    account: Annotated[
        str | None,
        typer.Option(
            "--account",
            "-a",
            help="Alias de la cuenta a configurar (por defecto: cuenta activa).",
        ),
    ] = None,
) -> None:
    """Lista los modelos disponibles de agy y permite fijar modelos preferidos por pool."""
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        typer.secho(
            "Error: No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    target_alias = account or state.active
    if target_alias is None or target_alias not in accounts:
        target_alias = sorted(accounts.keys())[0]

    target_acc = accounts[target_alias]

    # Opción: limpiar preferencias
    if clear:
        target_acc.clear_preferred_models()
        try:
            save_accounts(accounts)
        except ConfigError as err:
            typer.secho(f"Error al guardar configuración: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err
        console.print(
            f"[green]✓ Preferencias de modelos eliminadas para la cuenta '[bold]{target_alias}[/bold]'.[/green]"
        )
        return

    # Opción: fijar modelo preferido
    if set_model:
        model_id = set_model.strip()
        pool = classify_model_pool(model_id)
        target_acc.set_preferred_model(pool, model_id)
        try:
            save_accounts(accounts)
        except ConfigError as err:
            typer.secho(f"Error al guardar configuración: {err}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from err

        console.print(
            f"[green]✓ Modelo preferido para el pool '[cyan]{pool}[/cyan]' en '[bold]{target_alias}[/bold]' establecido en: [bold cyan]{escape(model_id)}[/bold cyan][/green]"
        )
        if target_alias == state.active and pool == state.active_model_group:
            console.print(
                "[dim]Este modelo se inyectará automáticamente en las próximas ejecuciones de 'agyswitcher run'.[/dim]"
            )
        return

    # Visualización por defecto: listado de modelos
    available_models = fetch_available_models(fallback_to_known=True)

    table = Table(
        title=f"Modelos de Antigravity (Cuenta: '{target_alias}')",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID del Modelo", style="bold")
    table.add_column("Nombre")
    table.add_column("Pool")
    table.add_column("Estado de Cuota")
    table.add_column("Preferencia")

    for m in available_models:
        pool_label = "[cyan]gemini[/cyan]" if m.pool == "gemini" else "[magenta]external[/magenta]"

        # Comprobar cuota para la cuenta objetivo
        if m.pool == "gemini":
            is_exhausted = target_alias in state.gemini_quota_exhausted
        else:
            is_exhausted = target_alias in state.external_quota_exhausted

        status_label = "[red][AGOTADA][/red]" if is_exhausted else "[green][DISPONIBLE][/green]"

        # Comprobar si es el preferido
        pref = target_acc.get_preferred_model(m.pool)
        pref_label = "[bold yellow]★ Preferido[/bold yellow]" if pref == m.id else "[dim]-[/dim]"

        table.add_row(escape(m.id), escape(m.display_name), pool_label, status_label, pref_label)

    console.print(table)

    # Nota de ayuda
    gemini_pref = target_acc.get_preferred_model("gemini") or "predeterminado por agy"
    external_pref = target_acc.get_preferred_model("external") or "predeterminado por agy"
    console.print(
        f"\n[dim]Modelos preferidos actuales en '{target_alias}': "
        f"Gemini: [bold]{escape(gemini_pref)}[/bold] | External: [bold]{escape(external_pref)}[/bold][/dim]"
    )
    console.print(
        "[dim]Usa [bold]agyswitcher models --set <id>[/bold] para configurar un modelo preferido.[/dim]"
    )


_LOG_ERROR_LINE = re.compile(r"^E\d{4}\s")
"""Línea de error de los logs de agy (formato glog: 'E1120 16:53:48.324666 ...')."""

_LOG_POLL_INTERVAL = 1.0
"""Segundos entre lecturas de los logs de agy durante 'run'."""


@app.command(
    help=(
        "Ejecuta agy detectando la cuota agotada (y proponiendo cómo continuar) y avisando de "
        "cuota baja. Ejemplo: agyswitcher run -- --help"
    ),
)
def run(
    args: Annotated[list[str] | None, typer.Argument(help="Argumentos a pasar a agy.")] = None,
) -> None:
    """Lanza agy con la cuenta activa y los argumentos indicados."""
    # Verificar que hay una cuenta activa válida antes de lanzar agy
    try:
        accounts = load_accounts()
    except ConfigError as err:
        typer.secho(f"Error de configuración: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if not accounts:
        typer.secho(
            "Error: No hay cuentas configuradas. Usa 'agyswitcher add <alias>' para registrar una.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        state = load_state()
    except StateError as err:
        typer.secho(f"Error de estado: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from err

    if state.active is None or state.active not in accounts:
        typer.secho(
            "Error: No hay ninguna cuenta activa válida. "
            "Usa 'agyswitcher rotate <alias>' para seleccionar una.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # Inyectar modelo preferido para el pool activo si está configurado
    effective_args = list(args or [])
    active_acc = accounts.get(state.active)
    if active_acc is not None:
        preferred = active_acc.get_preferred_model(state.active_model_group)
        if preferred:
            effective_args = inject_preferred_model_args(effective_args, preferred)

    _warn_low_quota(accounts, state)

    # Lanzar agy con los argumentos proporcionados y monitorizar cuota en tiempo real
    detector = QuotaDetector(default_pool=state.active_model_group)
    detected_pools: list[str] = []

    detection_lock = threading.Lock()

    def _on_process_line(line: str) -> None:
        event = detector.detect_in_line(line)
        if event is None or state.active is None:
            return
        with detection_lock:
            if event.pool not in detected_pools:
                detected_pools.append(event.pool)
                typer.secho(
                    f"\a\n[AgySwitcher] Cuota agotada ({event.pool}) en '{state.active}'. "
                    "Sal de agy (/exit) y te indicaré cómo continuar.",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
            now_iso = event.timestamp.isoformat()
            changed = False
            if event.pool == "gemini" and state.active not in state.gemini_quota_exhausted:
                state.gemini_quota_exhausted[state.active] = now_iso
                changed = True
            elif event.pool == "external" and state.active not in state.external_quota_exhausted:
                state.external_quota_exhausted[state.active] = now_iso
                changed = True

            if changed:
                with contextlib.suppress(StateError):
                    save_state(state)

    def _on_log_line(line: str) -> None:
        # En modo interactivo agy no muestra sus errores en la salida que se captura, pero sí
        # los escribe en sus logs. Solo cuentan las líneas de error (glog 'E'), no las trazas.
        if _LOG_ERROR_LINE.match(line):
            _on_process_line(line)

    stop_following = threading.Event()
    follower = LogFollower()

    def _follow_logs() -> None:
        while not stop_following.wait(_LOG_POLL_INTERVAL):
            for log_line in follower.poll():
                _on_log_line(log_line)

    follow_thread = threading.Thread(target=_follow_logs, name="agy-log-follower", daemon=True)
    follow_thread.start()
    try:
        exit_code = run_agy_process(args=effective_args, on_line=_on_process_line)
    except AgyNotFoundError as err:
        typer.secho(
            f"Error: No se encontró agy.exe. {err}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from err
    except RunnerError as err:
        typer.secho(
            f"Error al ejecutar agy: {err}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from err
    finally:
        stop_following.set()
        follow_thread.join(timeout=_LOG_POLL_INTERVAL * 2)
    for log_line in follower.poll():  # Lo escrito justo antes de cerrarse agy.
        _on_log_line(log_line)

    if detected_pools:
        typer.secho(
            f"\n[!] Durante la ejecución se agotó la cuota ({', '.join(detected_pools)}) "
            f"en la cuenta '{state.active}'.",
            fg=typer.colors.YELLOW,
        )
        try:
            new_pool = _propose_after_exhaustion(accounts, state)
        except StateError as err:
            typer.secho(
                f"No se pudo guardar el cambio de pool: {err}", fg=typer.colors.RED, err=True
            )
        else:
            if new_pool is not None:
                typer.secho(
                    "Vuelve a ejecutar agyswitcher run para continuar con esos modelos.",
                    fg=typer.colors.CYAN,
                )

    sys.exit(exit_code)


if __name__ == "__main__":
    app()
