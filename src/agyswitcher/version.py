# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: version.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-18
Ultimo cambio: 2026-11-18

Descripción: Versión de AgySwitcher.

La versión semántica (MAJOR.MINOR.PATCH) tiene una única fuente: '__version__' en
'agyswitcher/__init__.py' (pyproject.toml la lee de ahí). La revisión es el número de
compilación de '_build.py', que solo existe en los ejecutables oficiales.
"""

from __future__ import annotations

import re

from agyswitcher import __version__
from agyswitcher._build import BUILD_NUMBER

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def semver_parts(version: str = __version__) -> tuple[int, int, int]:
    """Devuelve (MAJOR, MINOR, PATCH) de una versión semántica.

    Raises:
        ValueError: Si la versión no empieza por MAJOR.MINOR.PATCH.
    """
    match = _SEMVER.match(version)
    if match is None:
        raise ValueError(f"Versión no válida: {version!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def windows_file_version(
    version: str = __version__, build: int | None = BUILD_NUMBER
) -> tuple[int, int, int, int]:
    """Versión de 4 números para el recurso de versión del .exe (build 0 si no hay)."""
    return (*semver_parts(version), build or 0)


def full_version(version: str = __version__, build: int | None = BUILD_NUMBER) -> str:
    """Texto de versión para el usuario: '0.9.0' o '0.9.0 (compilación 45)'."""
    if build is None:
        return version
    return f"{version} (compilación {build})"
