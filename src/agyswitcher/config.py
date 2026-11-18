# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: config.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-06

Descripción: Gestión de la configuración persistente de AgySwitcher.

Lee y escribe ``~/.agyswitcher/config.json``, que contiene la lista
de cuentas registradas.  La escritura es atómica: se escribe primero
en un fichero temporal y se renombra, para evitar corrupción si el
proceso termina de forma inesperada.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agyswitcher.models import Account


class ConfigError(Exception):
    """Error al leer o escribir la configuración."""


# ---------------------------------------------------------------------------
# Ruta por defecto
# ---------------------------------------------------------------------------


APP_HOME_ENV = "AGYSWITCHER_HOME"
"""Variable de entorno para usar otra carpeta de datos (pruebas, demostraciones)."""


def app_home_dir() -> Path:
    """Carpeta de datos de AgySwitcher (config.json, state.json).

    Por defecto '%USERPROFILE%\\.agyswitcher'. Si la variable AGYSWITCHER_HOME tiene un
    valor, se usa esa carpeta (las rutas relativas se resuelven desde la carpeta actual).
    """
    custom = os.environ.get(APP_HOME_ENV, "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return Path.home() / ".agyswitcher"


def default_config_path() -> Path:
    """Devuelve la ruta de config.json."""
    return app_home_dir() / "config.json"


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def load_accounts(config_path: Path | None = None) -> dict[str, Account]:
    """Carga la lista de cuentas desde config.json.

    - Si el fichero no existe → devuelve diccionario vacío.
    - Si el JSON está malformado → lanza :exc:`ConfigError`.
    """
    path = config_path or default_config_path()
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json malformado: {exc}") from exc

    try:
        return {alias: Account.from_dict(data) for alias, data in raw.get("accounts", {}).items()}
    except (KeyError, ValueError) as exc:
        raise ConfigError(f"Estructura de config.json inválida: {exc}") from exc


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def save_accounts(accounts: dict[str, Account], config_path: Path | None = None) -> None:
    """Persiste la lista de cuentas en config.json de forma atómica."""
    path = config_path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"accounts": {alias: acc.to_dict() for alias, acc in accounts.items()}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
