# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests del módulo de portapapeles (sin tocar el portapapeles real)."""

from __future__ import annotations

import pytest

from agyswitcher import clipboard


def test_copy_returns_false_when_api_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_text: str) -> bool:
        raise OSError("portapapeles ocupado")

    monkeypatch.setattr(clipboard, "_win32_set_text", _boom)
    assert clipboard.copy_to_clipboard("hola") is False


def test_copy_returns_api_result(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _ok(text: str) -> bool:
        seen.append(text)
        return True

    monkeypatch.setattr(clipboard, "_win32_set_text", _ok)
    assert clipboard.copy_to_clipboard("ñandú ✓") is True
    assert seen == ["ñandú ✓"]


def test_tests_never_touch_real_clipboard() -> None:
    """conftest sustituye la escritura real: copiar no hace nada durante los tests."""
    assert clipboard.copy_to_clipboard("x") is False
