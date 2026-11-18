# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Punto de entrada del ejecutable de AgySwitcher (PyInstaller)."""

from agyswitcher.cli import app

if __name__ == "__main__":
    app(prog_name="agyswitcher")
