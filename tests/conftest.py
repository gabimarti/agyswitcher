# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Configuración común de pytest para AgySwitcher.

Aísla el directorio personal del usuario en TODOS los tests: ``Path.home()``,
``USERPROFILE`` y ``HOME`` apuntan a un directorio temporal. Así ningún test puede
leer, migrar ni conmutar el ``~/.gemini`` real ni escribir en ``~/.agyswitcher``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirige el directorio personal a una carpeta temporal por test."""
    fake_home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    # Una AGYSWITCHER_HOME del entorno real desviaría los datos fuera del HOME aislado.
    monkeypatch.delenv("AGYSWITCHER_HOME", raising=False)
    # Ni la ruta de agy del instalador ni la ruta de instalación real de agy: ningún test
    # debe encontrar ni lanzar el agy real del usuario.
    monkeypatch.delenv("AGYSWITCHER_AGY", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(fake_home / "AppData" / "Local"))
    # Ningún test debe escribir en el portapapeles real del usuario.
    monkeypatch.setattr("agyswitcher.clipboard._win32_set_text", lambda _text: False)
    return fake_home


@pytest.fixture(autouse=True)
def _isolate_credman(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Impide que los tests lean o modifiquen el Administrador de credenciales real.

    Sin esto, comandos como 'remove' o 'set-active' llamarían a CredDeleteW/CredWriteW sobre
    los slots reales del usuario si un alias de prueba coincidiera con uno suyo. Con la API
    deshabilitada, credman se comporta como en un sistema sin Credential Manager (sin slots).
    Los tests que necesitan la API real se marcan con 'real_credman' y solo usan targets de
    prueba; los que simulan la API la sustituyen ellos mismos.
    """
    if request.node.get_closest_marker("real_credman"):
        return
    from agyswitcher.credman import CredManPlatformError

    def _disabled() -> object:
        raise CredManPlatformError("Credential Manager real deshabilitado en los tests.")

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", _disabled)
