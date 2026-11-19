# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: clipboard.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-19
Ultimo cambio: 2026-11-19

Descripción: Copia de texto al portapapeles de Windows.

Usa directamente la API de Windows (user32/kernel32) mediante ctypes, sin dependencias
externas ni procesos auxiliares, y con texto Unicode (CF_UNICODETEXT). En otros sistemas
no copia nada. Solo se usa para las instrucciones de traspaso, nunca para datos sensibles.
"""

from __future__ import annotations

import ctypes
import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
OPEN_ATTEMPTS = 5
"""Intentos de abrir el portapapeles (otro programa puede tenerlo abierto un instante)."""
OPEN_RETRY_DELAY = 0.05


def _win32_set_text(text: str) -> bool:
    """Escribe 'text' en el portapapeles de Windows. Devuelve False si no fue posible."""
    if sys.platform != "win32":
        return False
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    data = text.encode("utf-16-le") + b"\x00\x00"

    for attempt in range(OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            break
        if attempt < OPEN_ATTEMPTS - 1:
            time.sleep(OPEN_RETRY_DELAY)
    else:
        return False

    try:
        if not user32.EmptyClipboard():
            return False
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            # Si SetClipboardData falla, la memoria sigue siendo nuestra.
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def copy_to_clipboard(text: str) -> bool:
    """Copia 'text' al portapapeles.

    Returns:
        True si se copió; False si no es posible (otro sistema, portapapeles ocupado o
        error de la API). Nunca lanza excepciones por fallos del portapapeles.
    """
    try:
        return _win32_set_text(text)
    except OSError:
        return False
