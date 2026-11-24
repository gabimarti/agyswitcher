# Desinstalación

## Instalado con el instalador

Desinstala desde *Configuración → Aplicaciones → Aplicaciones instaladas → AgySwitcher*, o
desde *Inicio → AgySwitcher → Desinstalar AgySwitcher*. Se borra la carpeta de instalación
y se quita del `PATH` de tu usuario. También se borra la variable `AGYSWITCHER_AGY` si la
creó el instalador (una que hubieras definido tú se conserva). Tus datos (ver abajo) se
conservan.

## Versión portable

Borra la carpeta donde descomprimiste el ZIP.

## Instalado desde el código fuente

Basta con borrar la carpeta donde clonaste el repositorio (incluye el entorno `.venv`).

## Datos de AgySwitcher

Tus cuentas, cuotas e historial están en `%USERPROFILE%\.agyswitcher\` (o en la carpeta de
`AGYSWITCHER_HOME` si la definiste). Si no vas a volver a usar AgySwitcher, puedes borrarla:

```powershell
Remove-Item "$env:USERPROFILE\.agyswitcher" -Recurse
```

## Sesiones guardadas (slots)

Las sesiones guardadas de tus cuentas siguen en el Administrador de credenciales de Windows
por si vuelves a instalar AgySwitcher (el desinstalador te lo recuerda al terminar). Para
borrarlas, **antes de desinstalar** ejecuta:

```powershell
agyswitcher slots clean --all
```

Si ya desinstalaste, bórralas en *Panel de control → Administrador de credenciales →
Credenciales de Windows*: son las que empiezan por `gemini:antigravity:slot:`. No borres
`gemini:antigravity`: es la sesión de `agy`.

## Lo que no se toca

- `%USERPROFILE%\.gemini`: AgySwitcher nunca lo modifica. La sesión de `agy` queda con la
  última cuenta que usaste.
- Los ficheros que `init` creó en tus proyectos (`AGENTS.md`, `dev_mem/`, `GEMINI.md`,
  `CLAUDE.md`, `.agyswitcher.toml`...): son tuyos y siguen siendo útiles para cualquier
  agente aunque desinstales AgySwitcher.
