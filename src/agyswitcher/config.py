# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: config.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-19

Descripción: Gestión de la configuración persistente de AgySwitcher.

Lee y escribe ``~/.agyswitcher/config.json``, que contiene la lista
de cuentas registradas (``accounts``) y los ajustes globales (``settings``).  La escritura es atómica: se escribe primero
en un fichero temporal y se renombra, para evitar corrupción si el
proceso termina de forma inesperada.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from agyswitcher.models import Account

LOW_QUOTA_DEFAULT = 20
"""Umbral por defecto (porcentaje restante) del aviso de cuota baja."""

LOW_QUOTA_MIN = 1
LOW_QUOTA_MAX = 99


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


@dataclass
class Settings:
    """Ajustes globales de AgySwitcher (sección ``settings`` de config.json)."""

    low_quota_percent: int | None = None
    """Umbral global del aviso de cuota baja (None: el valor por defecto)."""
    auto_copy: bool = False
    """Copiar automáticamente al portapapeles las instrucciones de traspaso."""

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"auto_copy": self.auto_copy}
        if self.low_quota_percent is not None:
            data["low_quota_percent"] = self.low_quota_percent
        return data

    @classmethod
    def from_dict(cls, data: object) -> Settings:
        """Crea los ajustes a partir del JSON; los valores inválidos se ignoran."""
        if not isinstance(data, dict):
            return cls()
        low = data.get("low_quota_percent")
        auto_copy = data.get("auto_copy")
        return cls(
            low_quota_percent=low if is_valid_low_quota(low) else None,
            auto_copy=auto_copy if isinstance(auto_copy, bool) else False,
        )


def is_valid_low_quota(value: object) -> bool:
    """Indica si 'value' es un umbral de cuota baja admitido (entero de 1 a 99)."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and LOW_QUOTA_MIN <= value <= LOW_QUOTA_MAX
    )


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def _read_raw(path: Path) -> dict[str, object]:
    """Contenido de config.json como diccionario ({} si no existe)."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json malformado: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Estructura de config.json inválida: se esperaba un objeto.")
    return raw


def _write_raw(path: Path, payload: dict[str, object]) -> None:
    """Escribe config.json de forma atómica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_settings(config_path: Path | None = None) -> Settings:
    """Carga los ajustes globales de config.json (los de por defecto si no hay)."""
    return Settings.from_dict(_read_raw(config_path or default_config_path()).get("settings"))


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Guarda los ajustes globales conservando las cuentas de config.json."""
    path = config_path or default_config_path()
    payload = _read_raw(path)
    payload["settings"] = settings.to_dict()
    _write_raw(path, payload)


def load_accounts(config_path: Path | None = None) -> dict[str, Account]:
    """Carga la lista de cuentas desde config.json.

    - Si el fichero no existe → devuelve diccionario vacío.
    - Si el JSON está malformado → lanza :exc:`ConfigError`.
    """
    raw = _read_raw(config_path or default_config_path())
    accounts = raw.get("accounts", {})
    if not isinstance(accounts, dict):
        raise ConfigError("Estructura de config.json inválida: 'accounts' no es un objeto.")
    try:
        return {alias: Account.from_dict(data) for alias, data in accounts.items()}
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigError(f"Estructura de config.json inválida: {exc}") from exc


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def save_accounts(accounts: dict[str, Account], config_path: Path | None = None) -> None:
    """Persiste la lista de cuentas en config.json de forma atómica (conserva los ajustes)."""
    path = config_path or default_config_path()
    try:
        payload = _read_raw(path)
    except ConfigError:
        payload = {}
    payload["accounts"] = {alias: acc.to_dict() for alias, acc in accounts.items()}
    _write_raw(path, payload)
