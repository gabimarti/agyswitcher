# Registro de cambios

Todos los cambios relevantes de AgySwitcher se documentan en este fichero.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el
proyecto sigue el [versionado semántico](https://semver.org/lang/es/) (`MAJOR.MINOR.PATCH`).
Los ejecutables oficiales añaden un número de compilación: `MAJOR.MINOR.PATCH.BUILD`.

## [Sin publicar]

### Corregido

- `agyswitcher add` (y cualquier consulta de cuota o de modelos) podía dejar la consola
  bloqueada si `agy` no terminaba a tiempo: ahora la espera tiene un límite real, se
  termina `agy` con todos sus procesos y `agy` nunca se queda esperando entrada de teclado.

## [1.0.0] - 2026-11-18

Primera versión pública: ejecutable e instalador para Windows, manual, tutoriales y web.

### Añadido

- Web de usuario (MkDocs Material) con portada, manual, tutoriales y pantallazos,
  publicada en GitHub Pages.
- Manual de usuario en `docs/manual/` (instalación, conceptos, referencia de comandos,
  continuidad del proyecto, problemas frecuentes y desinstalación) y tutoriales para
  proyectos nuevos y existentes en `docs/tutoriales/`.
- Ejecutable de Windows (`agyswitcher.exe`) con recurso de versión, instalador para el
  usuario actual (sin administrador; añade AgySwitcher al `PATH` y crea desinstalador),
  ZIP portable y `SHA256SUMS.txt`, compilados automáticamente al publicar una versión.
- `agyswitcher init --merge`: completa ficheros existentes sin tocar su contenido (añade a
  `AGENTS.md` la sección de memoria y a los ficheros de cada agente el aviso que remite a
  `AGENTS.md`; en `CLAUDE.md`, la importación `@AGENTS.md`). Respeta los saltos de línea del
  fichero y no duplica lo ya añadido.

### Corregido

- `set-active`, `status --live` y `dashboard --live` ya no guardan la cuota consultada en
  una cuenta distinta de la que tiene la sesión iniciada en `agy`.

### Cambiado

- `remove` de la cuenta activa ya no activa otra cuenta (no tendría la sesión iniciada en
  `agy`): deja la cuenta activa vacía y sugiere `sync` o `set-active`.
- Ayuda de los comandos actualizada al funcionamiento actual (`set-active`, `rotate`,
  `watch`, `sync`, `run`) y con tildes corregidas.
- README reducido a presentación, instalación rápida y enlaces al manual.
- Cabecera `SPDX-License-Identifier: GPL-3.0-or-later` en todos los ficheros de código
  (comprobada por los tests), `CONTRIBUTING.md`, `SECURITY.md`, plantillas de issues y
  metadatos del paquete (clasificadores y enlaces).
- Los datos de prueba usan solo direcciones `@example.com`.
- Licencia: AgySwitcher se distribuye bajo la **GPL-3.0-or-later** (texto completo en
  `LICENSE`). Sustituye a la mención a MIT que figuraba por error en el README y en
  `pyproject.toml`.

## [0.9.0] - 2026-11-18

Versión candidata previa a la 1.0.0. Reorienta AgySwitcher hacia su objetivo: seguir
trabajando en el mismo proyecto con otra cuenta cuando la actual agota su cuota.

### Añadido

- `agyswitcher init`: prepara un proyecto para continuar entre cuentas y agentes de IA
  (`AGENTS.md` común, `GEMINI.md`, `CLAUDE.md`, Copilot y Cursor que remiten a él,
  `dev_mem/ESTADO.md`, `dev_mem/TODO.md` y `.agyswitcher.toml`). Nunca sobrescribe.
- `agyswitcher handoff [save|resume]`: instrucciones para guardar el estado antes de
  cambiar de cuenta y para retomarlo después, personalizables por proyecto.
- Aviso de cuota baja (15 % o menos en el pool activo) en `list`, `status` y `run`.
- Cambio de cuenta guiado y verificado en `rotate <alias>` y `set-active <alias>`: indica
  con qué email iniciar sesión en `agy` y confirma el cambio leyendo los logs
  (`--timeout`). Tras el cambio muestra la instrucción para retomar el proyecto.
- Versión con fuente única y número de compilación para los ejecutables
  (`agyswitcher --version`).
- Variable de entorno `AGYSWITCHER_HOME` para usar otra carpeta de datos.

### Cambiado

- `%USERPROFILE%\.gemini` es una carpeta única compartida por todas las cuentas y
  AgySwitcher no la modifica: historial, conversaciones, servidores MCP y *skills* se
  conservan al cambiar de cuenta.
- `watch` cambia de pool en la misma cuenta y, para cambiar de cuenta, propone la
  siguiente y el comando a ejecutar (cambiar de cuenta requiere iniciar sesión).
- `list` guarda la cuota en la cuenta cuyo email coincide con la sesión de `agy`;
  `add` solo activa la cuenta y consulta su cuota si la sesión es de esa cuenta;
  `sync` alinea la cuenta activa con la sesión real.
- Limpieza de procesos de `agy` garantizada y sin capturas genéricas de excepciones.

### Eliminado

- Perfiles por cuenta mediante NTFS Directory Junctions y el comando `migrate`: no
  cambiaban la cuenta de Google (`agy` guarda una única sesión en el Administrador de
  credenciales de Windows) y separaban el contexto que interesa conservar.

### Obsoleto

- `list --refresh-all`: equivale a `list --live`, porque solo se puede consultar la cuota
  de la cuenta con sesión iniciada.

## [0.1.0] - 2026-11-05

Primera versión funcional.

### Añadido

- Catálogo de cuentas (`add`, `remove`, `list`, `status`, `set-active`, `sync`) con el
  email de Google detectado de la sesión de `agy`.
- Cuota semanal por pool (Gemini / Otros) con porcentajes y tiempos de reinicio
  (`usage`, `list`, `status --live`).
- Ejecución de `agy` con streaming, sanitización de datos sensibles y detección de cuota
  agotada (`run`), y supervisión de logs (`watch`).
- Gestión de modelos y modelo preferido por pool (`models`).
- Panel de control en terminal (`dashboard`).
- Script de instalación para usuarios (`scripts/setup.ps1`).
