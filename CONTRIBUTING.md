# Cómo contribuir a AgySwitcher

¡Gracias por tu interés! Las contribuciones son bienvenidas: informes de errores, ideas,
mejoras de la documentación y código.

## Antes de empezar

- Lee el [manual](docs/manual/index.md) y, si vas a tocar código, la
  [arquitectura](docs/architecture.md).
- Para cambios grandes, abre primero una *issue* para comentarlo.
- **Nunca incluyas datos reales** en issues, commits, tests ni capturas: ni emails de tus
  cuentas, ni tokens, ni rutas personales. Usa direcciones `@example.com`.

## Entorno de desarrollo

Requisitos: Windows 10/11, Python 3.11+ y Git.

```powershell
git clone https://github.com/gabimarti/agyswitcher.git
cd agyswitcher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Comprobaciones

Todas deben pasar antes de enviar un *pull request* (son las mismas que ejecuta la
integración continua):

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

Los tests aíslan la carpeta personal: nunca tocan tu `%USERPROFILE%\.gemini` ni tu
`%USERPROFILE%\.agyswitcher` reales.

## Normas del código

- Python moderno con anotaciones de tipo en las funciones públicas.
- `snake_case` para módulos, funciones y variables; `PascalCase` para clases;
  `UPPER_SNAKE_CASE` para constantes.
- **Mensajes para el usuario en español**; identificadores y código en inglés.
- Errores esperados con excepciones específicas; nunca `except Exception` genérico.
- Toda llamada a procesos externos con *timeout* y limpieza de recursos; sin `shell=True`.
- Cada fichero de código empieza con la cabecera de licencia:

  ```python
  # SPDX-License-Identifier: GPL-3.0-or-later
  # Copyright (C) 2026 Gabriel Marti
  ```

## Seguridad y privacidad (obligatorio)

AgySwitcher **no lee, copia ni guarda** tokens OAuth, contraseñas ni cookies, **no automatiza
el inicio de sesión de Google** y **no modifica** `%USERPROFILE%\.gemini`. Las contribuciones
que cambien estos principios no se aceptarán. Si encuentras un problema de seguridad, sigue
[SECURITY.md](SECURITY.md) en lugar de abrir una issue pública.

## Pull requests

- Cambios pequeños y enfocados, con tests para la lógica nueva o modificada.
- Actualiza la documentación (`README.md`, `docs/`) y el `CHANGELOG.md` (sección
  *Sin publicar*) si cambias el comportamiento.
- Describe qué cambia y cómo lo has comprobado.

## Licencia

Al contribuir aceptas que tu aportación se distribuya bajo la licencia del proyecto,
[GPL-3.0-or-later](LICENSE).
