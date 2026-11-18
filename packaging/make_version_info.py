# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Genera el recurso de versión de Windows del ejecutable (formato de PyInstaller).

Uso: python packaging/make_version_info.py <número_de_compilación> <fichero_de_salida>

La versión semántica se lee de agyswitcher.__version__; el número de compilación completa
la versión de Windows (MAJOR.MINOR.PATCH.BUILD) que muestran las propiedades del .exe.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agyswitcher import __version__
from agyswitcher.version import full_version, windows_file_version

TEMPLATE = """# Recurso de versión generado por packaging/make_version_info.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vtuple},
    prodvers={vtuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('0C0A04B0', [
        StringStruct('CompanyName', 'Gabriel Marti'),
        StringStruct('FileDescription', 'AgySwitcher - cuentas y cuotas de Antigravity CLI'),
        StringStruct('FileVersion', '{vdotted}'),
        StringStruct('InternalName', 'agyswitcher'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026 Gabriel Marti. GPL-3.0-or-later.'),
        StringStruct('OriginalFilename', 'agyswitcher.exe'),
        StringStruct('ProductName', 'AgySwitcher'),
        StringStruct('ProductVersion', '{vfull}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])
  ]
)
"""


def render(build: int) -> str:
    """Texto del recurso de versión para el número de compilación indicado."""
    vtuple = windows_file_version(__version__, build)
    return TEMPLATE.format(
        vtuple=vtuple,
        vdotted=".".join(str(n) for n in vtuple),
        vfull=full_version(__version__, build),
    )


def main() -> int:
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        print("Uso: python packaging/make_version_info.py <compilación> <salida>")
        return 2
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(int(sys.argv[1])), encoding="utf-8")
    print(f"Recurso de versión: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
