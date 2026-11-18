# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: dashboard.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-06

Descripción: Módulo de construcción y renderizado del Dashboard TUI para AgySwitcher.

Proporciona componentes visuales con Rich para monitorizar de un vistazo
el estado global de las cuentas, pools de cuotas, sesión y conmutaciones.
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table

from agyswitcher.models import Account, AppState
from agyswitcher.usage import UsageReport, format_time_remaining


def render_quota_bar(remaining_percent: int, length: int = 12) -> str:
    """Genera una barra de progreso textual ASCII coloreada según el nivel.

    Args:
        remaining_percent: Porcentaje restante (0 a 100).
        length: Número de bloques visuales en la barra.

    Returns:
        Cadena con formato Rich.
    """
    pct = max(0, min(100, remaining_percent))
    filled = int(round((pct / 100.0) * length))
    bar = "=" * filled + "-" * (length - filled)
    if pct >= 50:
        return f"[green][{bar}] {pct}%[/green]"
    if pct >= 20:
        return f"[yellow][{bar}] {pct}%[/yellow]"
    return f"[red][{bar}] {pct}%[/red]"


def build_system_summary_panel(
    accounts: dict[str, Account],
    state: AppState,
    usage_report: UsageReport | None = None,
) -> Panel:
    """Construye el panel superior de resumen general del sistema.

    Args:
        accounts: Catálogo de cuentas configuradas.
        state: Estado global de la aplicación.
        usage_report: Informe opcional de consulta en vivo con agy.

    Returns:
        Panel de Rich con datos clave de la sesión y cuentas.
    """
    total = len(accounts)
    fully_exhausted = sum(1 for a in accounts if state.is_account_fully_exhausted(a))
    available = total - fully_exhausted

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()
    grid.add_column(style="bold cyan")
    grid.add_column()

    active_acc = state.active or "Ninguna"
    active_style = "[bold green]" if state.active else "[bold red]"
    active_display = f"{active_style}{active_acc}[/]"

    pool_display = f"[bold]{state.active_model_group}[/bold]"
    if state.active:
        gemini_ok = state.active not in state.gemini_quota_exhausted
        ext_ok = state.active not in state.external_quota_exhausted
        g_tag = "[green]G:OK[/green]" if gemini_ok else "[red]G:KO[/red]"
        e_tag = "[green]E:OK[/green]" if ext_ok else "[red]E:KO[/red]"
        pool_display = f"{pool_display} ({g_tag} / {e_tag})"

    grid.add_row("Cuenta activa:", active_display, "Pool actual:", pool_display)

    counts_str = (
        f"[green]{available} disp[/green] / [red]{fully_exhausted} agotadas[/red] (total: {total})"
    )
    grid.add_row("Cuentas:", counts_str, "Historial:", f"{len(state.switch_history)} rotaciones")

    if usage_report is not None:
        auth_tag = (
            "[bold green]Conectada / Activa[/bold green]"
            if usage_report.is_authenticated
            else "[bold red]No autenticada[/bold red]"
        )
        grid.add_row(
            "Sesion Google:",
            auth_tag,
            "Comprobado:",
            usage_report.timestamp.strftime("%H:%M:%S UTC"),
        )

    return Panel(
        grid,
        title="[bold]AgySwitcher -- Centro de Control[/bold]",
        box=box.ROUNDED,
        border_style="cyan",
        expand=False,
    )


def build_accounts_table(
    accounts: dict[str, Account],
    state: AppState,
    usage_report: UsageReport | None = None,
) -> Table:
    """Construye la matriz comparativa de cuentas y pools de cuota.

    Args:
        accounts: Catálogo de cuentas configuradas.
        state: Estado global de la aplicación.
        usage_report: Métricas en vivo opcionales para la cuenta activa.

    Returns:
        Table de Rich con el detalle por cuenta.
    """
    table = Table(
        title="Matriz de Cuentas y Disponibilidad de Pools",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Cuenta", style="bold")
    table.add_column("Email Google")
    table.add_column("Estado")
    table.add_column("Pool Gemini")
    table.add_column("Pool External (Claude/GPT)")
    table.add_column("Registrada el (UTC)")

    for alias in sorted(accounts.keys()):
        acc = accounts[alias]
        is_active = alias == state.active
        gemini_exhausted = alias in state.gemini_quota_exhausted
        external_exhausted = alias in state.external_quota_exhausted

        email_col = acc.email if acc.email else "[dim]no vinculado[/dim]"

        # Columna Cuenta
        if is_active:
            name_col = f"[bold green]* {alias} (activa)[/bold green]"
            status_col = "[green][ACTIVA][/green]"
        elif gemini_exhausted and external_exhausted:
            name_col = f"  {alias}"
            status_col = "[red][AGOTADA][/red]"
        elif gemini_exhausted or external_exhausted:
            name_col = f"  {alias}"
            status_col = "[yellow][PARCIAL][/yellow]"
        else:
            name_col = f"  {alias}"
            status_col = "[blue][DISPONIBLE][/blue]"

        # Pool Gemini
        if is_active and usage_report and "gemini" in usage_report.pools:
            p = usage_report.pools["gemini"]
            rel_t = format_time_remaining(p.reset_time)
            gemini_col = f"{render_quota_bar(p.remaining_percent)} [dim]({rel_t})[/dim]"
        elif gemini_exhausted:
            gemini_col = "[red]Agotado (cooldown)[/red]"
        else:
            gemini_col = "[green]Disponible[/green]"

        # Pool External
        if is_active and usage_report and "external" in usage_report.pools:
            p = usage_report.pools["external"]
            rel_t = format_time_remaining(p.reset_time)
            ext_col = f"{render_quota_bar(p.remaining_percent)} [dim]({rel_t})[/dim]"
        elif external_exhausted:
            ext_col = "[red]Agotado (cooldown)[/red]"
        else:
            ext_col = "[green]Disponible[/green]"

        date_col = acc.added_at.strftime("%Y-%m-%d %H:%M")
        table.add_row(name_col, email_col, status_col, gemini_col, ext_col, date_col)

    return table


def build_history_panel(state: AppState, max_entries: int = 4) -> Panel:
    """Construye el panel inferior con las conmutaciones recientes.

    Args:
        state: Estado global de la aplicación.
        max_entries: Número máximo de entradas a mostrar.

    Returns:
        Panel de Rich con las últimas rotaciones registradas.
    """
    entries = state.switch_history[-max_entries:] if state.switch_history else []
    if not entries:
        content: Any = "[dim]Sin rotaciones registradas todavía.[/dim]"
    else:
        grid = Table.grid(padding=(0, 1))
        grid.add_column(style="dim")
        grid.add_column()
        for idx, entry in enumerate(reversed(entries), 1):
            grid.add_row(f"#{idx}", entry)
        content = grid

    return Panel(
        content,
        title="[bold]Últimos Cambios de Cuenta / Pool[/bold]",
        box=box.ROUNDED,
        border_style="yellow",
        expand=False,
    )


def build_dashboard_view(
    accounts: dict[str, Account],
    state: AppState,
    usage_report: UsageReport | None = None,
) -> RenderableType:
    """Compone la vista integral completa del Dashboard TUI.

    Args:
        accounts: Catálogo de cuentas configuradas.
        state: Estado global de la aplicación.
        usage_report: Métricas opcionales obtenidas en vivo.

    Returns:
        Objeto RenderableType componible para la consola o Live display.
    """
    if not accounts:
        return Panel(
            "[yellow]No hay cuentas configuradas en AgySwitcher.\n"
            "Usa [bold]agyswitcher add <alias>[/bold] para registrar tu primera cuenta.[/yellow]",
            title="[bold]AgySwitcher -- Dashboard[/bold]",
            box=box.ROUNDED,
            border_style="yellow",
        )

    summary = build_system_summary_panel(accounts, state, usage_report=usage_report)
    matrix = build_accounts_table(accounts, state, usage_report=usage_report)
    history = build_history_panel(state)

    return Group(summary, matrix, history)
