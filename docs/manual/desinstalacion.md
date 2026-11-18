# Desinstalación

## Instalado con el instalador

Desinstala desde *Configuración → Aplicaciones → Aplicaciones instaladas → AgySwitcher*, o
desde *Inicio → AgySwitcher → Desinstalar AgySwitcher*. Se borra la carpeta de instalación
y se quita del `PATH` de tu usuario. Tus datos (ver abajo) se conservan.

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

## Lo que no se toca

- `%USERPROFILE%\.gemini` y tu sesión de `agy`: AgySwitcher nunca los modifica.
- Los ficheros que `init` creó en tus proyectos (`AGENTS.md`, `dev_mem/`, `GEMINI.md`,
  `CLAUDE.md`, `.agyswitcher.toml`...): son tuyos y siguen siendo útiles para cualquier
  agente aunque desinstales AgySwitcher.
