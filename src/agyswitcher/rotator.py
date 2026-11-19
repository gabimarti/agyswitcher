# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: rotator.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-18

Descripción: Módulo de rotación de cuentas y pools para AgySwitcher.

Selecciona la siguiente cuenta o pool con cuota disponible y registra los cambios en
el estado. Desde 2026-11-18 AgySwitcher no modifica ~/.gemini: es una carpeta única
compartida por todas las cuentas (historial, conversaciones, MCP y skills comunes) y la
cuenta de Google solo cambia cuando el usuario inicia sesión en agy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agyswitcher.models import Account, AppState
from agyswitcher.state import save_state


def default_live_dir() -> Path:
    """Devuelve la ruta donde agy.exe guarda su configuración y logs (~/.gemini)."""
    return Path.home() / ".gemini"


def select_next_candidate(
    accounts: dict[str, Account],
    state: AppState,
) -> tuple[str, str] | None:
    """Selecciona la siguiente cuenta y pool disponible según la política de cascada.

    Cascada de selección:
    1. Si la cuenta activa tiene el pool alternativo disponible, se rota de pool
       manteniendo la misma cuenta (ej. gemini -> external).
    2. Si ambos pools de la cuenta activa están agotados (o no hay activa), se
       busca entre el resto de cuentas la primera que tenga al menos un pool libre.

    Args:
        accounts: Diccionario de cuentas registradas.
        state: Estado actual de la aplicación.

    Returns:
        Tupla (alias_cuenta, pool_a_usar) o None si todas las cuentas están agotadas.
    """
    if not accounts:
        return None

    # Caso 1: Intentar pool alternativo en la cuenta activa actual
    active = state.active
    if active and active in accounts:
        curr_pool = state.active_model_group
        other_pool = "external" if curr_pool == "gemini" else "gemini"
        other_exhausted = (
            active in state.external_quota_exhausted
            if other_pool == "external"
            else active in state.gemini_quota_exhausted
        )
        curr_exhausted = (
            active in state.gemini_quota_exhausted
            if curr_pool == "gemini"
            else active in state.external_quota_exhausted
        )

        # Si el pool actual está agotado pero el otro está libre -> rotar al otro pool
        if curr_exhausted and not other_exhausted:
            return active, other_pool

    # Caso 2: Buscar en el resto de cuentas
    sorted_aliases = sorted(accounts.keys())
    # Ordenar circularmente empezando por la cuenta siguiente a la activa
    if active and active in sorted_aliases:
        idx = sorted_aliases.index(active)
        ordered_candidates = sorted_aliases[idx + 1 :] + sorted_aliases[:idx]
    else:
        ordered_candidates = sorted_aliases

    for candidate in ordered_candidates:
        available_pool = state.available_group_for(candidate)
        if available_pool is not None:
            return candidate, available_pool

    # Si la cuenta activa aún tiene su pool actual disponible (ej. forzar rotate preventivo)
    if active and active in accounts and not state.is_account_fully_exhausted(active):
        available_pool = state.available_group_for(active)
        if available_pool is not None:
            return active, available_pool

    return None


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
