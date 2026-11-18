# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: state.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-06

Descripción: Gestión del estado de ejecución de AgySwitcher.

Lee y escribe ``~/.agyswitcher/state.json``, que registra la cuenta
activa, los cooldowns de cuota y el historial de cambios.  La escritura
es atómica (temporal + rename), igual que en config.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from agyswitcher.config import app_home_dir
from agyswitcher.models import AppState


class StateError(Exception):
    """Error al leer o escribir el estado."""


# ---------------------------------------------------------------------------
# Ruta por defecto
# ---------------------------------------------------------------------------


def default_state_path() -> Path:
    """Devuelve la ruta de state.json (ver 'app_home_dir')."""
    return app_home_dir() / "state.json"


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def load_state(state_path: Path | None = None) -> AppState:
    """Carga el estado desde state.json.

    - Si el fichero no existe → devuelve :class:`AppState` vacío por defecto.
    - Si el JSON está malformado → lanza :exc:`StateError`.
    """
    path = state_path or default_state_path()
    if not path.exists():
        return AppState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"state.json malformado: {exc}") from exc

    try:
        return AppState.from_dict(raw)
    except (KeyError, ValueError) as exc:
        raise StateError(f"Estructura de state.json inválida: {exc}") from exc


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def save_state(state: AppState, state_path: Path | None = None) -> None:
    """Persiste el estado en state.json de forma atómica."""
    path = state_path or default_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
