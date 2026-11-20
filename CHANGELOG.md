# Registro de cambios

Todos los cambios relevantes de AgySwitcher se documentan en este fichero.

## [Sin publicar]

### Añadido

- Enlace al artículo «Programar con agentes de IA a coste cero: cuotas, contexto y
  continuidad» en el README y en la portada de la web.

### Corregido

- `run` no detectaba la cuota agotada con `agy` en modo interactivo: el aviso
  «Individual quota reached» no estaba entre los mensajes reconocidos y, además, en ese modo
  `agy` no lo envía por la salida que vigila AgySwitcher. Ahora `run` también sigue los
  registros de `agy` mientras está abierto (solo sus líneas de error) y el aviso pide salir de
  `agy` para indicar cómo continuar.
- Web, página de arquitectura: los diagramas dibujados con caracteres de caja se veían
  desalineados; ahora son diagramas Mermaid (se adaptan al modo claro y oscuro), la estructura
  de módulos es una tabla y las listas de las vías de detección de cuota se muestran bien.
- Página de arquitectura: se quitan la nota sobre el diseño anterior (perfiles por cuenta) y
  la tabla de decisiones pendientes, ya resueltas.
- Hoja de ruta reescrita: qué hace AgySwitcher hoy, versiones publicadas y próximas mejoras,
  sin la historia del diseño anterior.

## [1.3.0] - 2026-11-20

Diagnóstico con `agyswitcher doctor`, guías de uso para el día a día y para combinar varios
agentes, y web renovada.

### Añadido

- Comando `agyswitcher doctor`: diagnóstico de la instalación (agy y su versión, cuentas,
  estado, sesión de `agy` frente a la cuenta activa, antigüedad de los datos de cuota,
  procesos abiertos y preparación del proyecto actual) con cómo arreglar cada problema. Solo
  lee, enmascara los emails para poder compartir la salida y sale con código 1 si algo falla.
  La plantilla de errores de GitHub pide su salida.
- Guías nuevas en el manual: «Uso en el día a día» (para quién es, rutina de trabajo, casos
  prácticos y chuleta) y «Varios agentes y proveedores» (combinar `agy` con Claude Code,
  Codex, Copilot o Cursor sobre el mismo `AGENTS.md` y `dev_mem/`). La portada y el README
  explican a quién va dirigido.
- Sección «Apoya el proyecto» en la portada de la web y en el README con un botón para invitar
  a un café en Ko-fi (en la web, enlace directo sin cargar scripts de terceros), y botón
  «Sponsor» en GitHub.

### Cambiado

- La web se construye con Zensical (aspecto clásico) en lugar de MkDocs Material, con la
  misma configuración y las mismas direcciones.
- Logotipo de la cabecera de la web un 25 % más grande, sin cambiar la altura de la cabecera.
- El instalador se compila con Inno Setup 6.7.4 y las dependencias fijadas de la compilación
  se han revisado.

## [1.2.0] - 2026-11-19

Umbral de cuota baja configurable con las instrucciones listas en el portapapeles, avisos
más útiles cuando todas las cuentas figuran agotadas, logotipo y revisión de seguridad.

### Añadido

- Cuando todas las cuentas figuran agotadas, `run`, `watch` y `rotate` lo indican como
  «según los datos guardados» (Google a veces restablece la cuota antes de tiempo), muestran
  la antigüedad del dato y el reinicio previsto de cada cuenta, y sugieren comprobar primero
  la de reinicio más próximo.
- `rotate` consulta la cuota de la nueva cuenta al terminar el cambio, como `set-active`, e
  indica si la cuota que figuraba agotada vuelve a estar disponible o sigue agotada.
- Comando `agyswitcher config` para ver y cambiar los ajustes globales: umbral del aviso de
  cuota baja (`low-quota`, por defecto 15 %) y copia automática al portapapeles
  (`auto-copy`). Un proyecto puede fijar su propio umbral en `.agyswitcher.toml`
  (`[quota] low_percent`), que tiene prioridad.
- `agyswitcher handoff save|resume --copy` copia la instrucción al portapapeles.
- El aviso de cuota baja deja en el portapapeles la instrucción para guardar el estado, y el
  cambio de cuenta verificado, la de retomar (se desactiva con `config auto-copy off`).
- Logotipo de AgySwitcher en el README y la web (con variante para modo oscuro), favicon de
  la web e icono en el ejecutable y el instalador, que muestra también el lema.

### Cambiado

- Una cuenta agotada vuelve a tenerse en cuenta al elegir la siguiente cuenta cuando pasa su
  reinicio previsto (se avisa de que está sin confirmar). Antes seguía descartada hasta
  consultar su cuota en vivo.
- Los alias nuevos deben empezar y terminar por letra o número (ya no se aceptan `-`, `_` ni
  alias que empiecen por guion, que se confundían con opciones). Las cuentas existentes no
  se ven afectadas.
- `agyswitcher add --email` comprueba que el email tenga un formato válido.

### Corregido

- Un texto con corchetes (en un email escrito a mano o en la salida de `agy`, por ejemplo en
  `agyswitcher models` o en los errores de `status --live`) ya no hace fallar el comando; se
  muestra tal cual. Un `config.json` editado con un alias o email inválido da un error claro.
- La detección de la cuenta activa lee solo el final de cada registro de `agy`.
- El historial de cambios de cuenta conserva solo las 200 entradas más recientes.

### Seguridad

- Las líneas de error de cuota que se analizan se sanean (tokens, cabeceras) antes de
  guardarse en memoria.
- Las acciones de GitHub de los flujos de compilación, pruebas y web se fijan por SHA, con
  actualizaciones mediante Dependabot.
- Los ejecutables publicados se compilan con versiones exactas de todas las dependencias,
  verificadas por hash, y con una versión fija de Inno Setup verificada por SHA-256.

## [1.1.0] - 2026-11-19

`run` te indica cómo continuar cuando se agota la cuota y `add` ya no puede bloquear la consola.

### Añadido

- `agyswitcher run`: si se agota la cuota mientras usas `agy`, avisa en el momento y, al
  salir, cambia al otro pool de la misma cuenta o propone la siguiente cuenta con cuota y el
  comando para cambiar (como `watch`).

### Corregido

- `agyswitcher watch` ya no propone cambiar de cuenta cuando se agota el pool que no estás
  usando.
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
