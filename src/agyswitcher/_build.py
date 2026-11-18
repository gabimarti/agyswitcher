# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Número de compilación (revisión) de AgySwitcher.

En el código fuente vale None. La compilación oficial del ejecutable sustituye este
fichero con el número de compilación antes de empaquetar, de modo que la versión completa
queda como MAJOR.MINOR.PATCH.BUILD (también en las propiedades del .exe).
"""

BUILD_NUMBER: int | None = None
