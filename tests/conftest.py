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
    return fake_home
