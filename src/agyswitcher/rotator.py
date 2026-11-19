# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: rotator.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-19

Descripción: Módulo de rotación de cuentas y pools para AgySwitcher.

Selecciona la siguiente cuenta o pool con cuota disponible y registra los cambios en
el estado. Desde 2026-11-18 AgySwitcher no modifica ~/.gemini: es una carpeta única
compartida por todas las cuentas (historial, conversaciones, MCP y skills comunes) y la
cuenta de Google solo cambia cuando el usuario inicia sesión en agy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agyswitcher.models import QUOTA_POOLS, Account, AppState
from agyswitcher.state import save_state


def default_live_dir() -> Path:
    """Devuelve la ruta donde agy.exe guarda su configuración y logs (~/.gemini)."""
    return Path.home() / ".gemini"


def _other_pool(pool: str) -> str:
    return "external" if pool == "gemini" else "gemini"


def _circular_order(accounts: dict[str, Account], active: str | None) -> list[str]:
    """Alias del resto de cuentas, empezando por la siguiente a la activa."""
    aliases = sorted(accounts)
    if active and active in aliases:
        idx = aliases.index(active)
        return aliases[idx + 1 :] + aliases[:idx]
    return aliases


def select_next_candidate(
    accounts: dict[str, Account],
    state: AppState,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Selecciona la siguiente cuenta y pool disponible según la política de cascada.

    Primero se buscan pools que no figuran como agotados:

    1. El pool alternativo de la cuenta activa, si el actual está agotado (no exige
       iniciar sesión).
    2. El resto de cuentas, en orden circular a partir de la activa.

    Si no hay ninguno, se aceptan pools agotados cuyo reinicio previsto ya pasó (Google
    puede haber restablecido la cuota; queda sin confirmar hasta consultarla en vivo), en
    el mismo orden. Por último, la cuenta activa si conserva algún pool utilizable.

    Args:
        accounts: Diccionario de cuentas registradas.
        state: Estado actual de la aplicación.
        now: Momento de referencia (por defecto, ahora en UTC).

    Returns:
        Tupla (alias_cuenta, pool_a_usar) o None si todas las cuentas están agotadas.
    """
    if not accounts:
        return None
    current = now or datetime.now(UTC)
    active = state.active if state.active in accounts else None
    others = _circular_order(accounts, active)

    def _active_other_pool(usable: bool) -> tuple[str, str] | None:
        if active is None:
            return None
        curr_pool = state.active_model_group
        other_pool = _other_pool(curr_pool)
        if not state.is_pool_exhausted(active, curr_pool):
            return None
        free = (
            not state.is_pool_blocked(active, other_pool, current)
            if usable
            else not state.is_pool_exhausted(active, other_pool)
        )
        return (active, other_pool) if free else None

    # Pools que no figuran como agotados.
    found = _active_other_pool(usable=False)
    if found:
        return found
    for candidate in others:
        for pool in QUOTA_POOLS:
            if not state.is_pool_exhausted(candidate, pool):
                return candidate, pool

    # Pools agotados con el reinicio previsto ya pasado (sin confirmar).
    found = _active_other_pool(usable=True)
    if found:
        return found
    for candidate in others:
        for pool in QUOTA_POOLS:
            if not state.is_pool_blocked(candidate, pool, current):
                return candidate, pool

    # La cuenta activa aún tiene un pool utilizable (ej. forzar rotate preventivo).
    if active is not None:
        pool_left = state.usable_group_for(active, current)
        if pool_left is not None:
            return active, pool_left

    return None


def account_reset_estimate(state: AppState, alias: str) -> datetime | None:
    """Reinicio previsto más próximo entre los pools agotados de una cuenta (None si no hay)."""
    resets = [r for pool in QUOTA_POOLS if (r := state.estimated_reset(alias, pool)) is not None]
    return min(resets) if resets else None


def quota_data_time(state: AppState, alias: str) -> datetime | None:
    """Momento del dato de cuota más reciente guardado para una cuenta (None si no hay)."""
    times = [t for pool in QUOTA_POOLS if (t := state.exhausted_since(alias, pool)) is not None]
    info = state.accounts_quota.get(alias)
    if info is not None:
        updated = info.updated_at
        times.append(updated if updated.tzinfo is not None else updated.replace(tzinfo=UTC))
    return max(times) if times else None


def suggest_account_to_check(
    accounts: dict[str, Account],
    state: AppState,
    exclude: str | None = None,
) -> str | None:
    """Cuenta que conviene comprobar cuando todas figuran agotadas.

    Elige la de reinicio previsto más próximo; en caso de empate, la de dato más antiguo
    (es la que más probablemente esté desfasada). Las cuentas sin reinicio conocido van al
    final.

    Args:
        accounts: Cuentas registradas.
        state: Estado actual.
        exclude: Alias a descartar (normalmente la cuenta activa, ya comprobada).

    Returns:
        El alias sugerido, o None si no queda ninguna cuenta que sugerir.
    """
    latest = datetime.max.replace(tzinfo=UTC)
    earliest = datetime.min.replace(tzinfo=UTC)
    candidates = [a for a in sorted(accounts) if a != exclude]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda a: (
            account_reset_estimate(state, a) or latest,
            quota_data_time(state, a) or earliest,
        ),
    )


def record_rotation(
    target_alias: str,
    target_pool: str,
    state: AppState,
    *,
    state_path: Path | None = None,
) -> str:
    """Registra en el estado (y persiste) un cambio de cuenta o de pool.

    Solo escribe 'state.json'. Un cambio de cuenta solo debe registrarse tras verificar
    que el usuario ha iniciado sesión en agy con esa cuenta (cambio guiado).

    Args:
        target_alias: Alias de la cuenta activa tras el cambio.
        target_pool: Pool de modelos activo tras el cambio.
        state: Estado de la aplicación a modificar.
        state_path: Ruta de state.json (None usa la default).

    Returns:
        Mensaje descriptivo del cambio realizado.

    Raises:
        StateError: Si no se puede guardar el estado.
    """
    now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    prev_alias = state.active or "ninguna"
    prev_pool = state.active_model_group
    is_account_change = prev_alias != target_alias
    is_pool_change = not is_account_change and prev_pool != target_pool

    state.active = target_alias
    state.active_model_group = target_pool

    if is_account_change:
        event_desc = f"{now_iso}: {prev_alias} ({prev_pool}) -> {target_alias} ({target_pool})"
        message = f"Rotado a cuenta '{target_alias}' con pool '{target_pool}'."
    elif is_pool_change:
        event_desc = f"{now_iso}: {target_alias} cambio de pool: {prev_pool} -> {target_pool}"
        message = f"Cambiado pool en cuenta activa '{target_alias}': {prev_pool} -> {target_pool}."
    else:
        event_desc = f"{now_iso}: {target_alias} ({target_pool}) reafirmada"
        message = f"Cuenta activa '{target_alias}' reafirmada con pool '{target_pool}'."

    state.append_history(event_desc)
    save_state(state, state_path=state_path)
    return message
