---
hide:
  - navigation
---

# AgySwitcher

**Trabaja con varias cuentas de Google en Antigravity CLI (`agy`) y sigue con el mismo
proyecto cuando una cuenta se queda sin cuota.**

[Descargar para Windows](https://github.com/gabimarti/agyswitcher/releases){ .md-button .md-button--primary }
[Leer el manual](manual/index.md){ .md-button }

---

## El problema

Cuando la cuota semanal de tu cuenta se agota en mitad de una tarea, cambiar a otra cuenta
es fácil; lo difícil es **no perder el hilo**: qué estabas haciendo, qué quedaba pendiente y
qué decisiones habías tomado. Y con varias cuentas, saber cuál tiene cuota y cuándo se
reinicia cada una se vuelve un trabajo en sí mismo.

## Qué hace AgySwitcher

<div class="grid cards" markdown>

- **Cuota de todas tus cuentas**

    Porcentaje restante de cada pool (Gemini / Otros), fecha de reinicio y cuál es la
    siguiente cuenta disponible, en una sola tabla.

- **Aviso a tiempo**

    Cuando la cuota baja del 15 %, te avisa para que el agente guarde el estado del
    proyecto **antes** de quedarse sin tokens.

- **Cambio de cuenta guiado y verificado**

    Te dice con qué email iniciar sesión en `agy` y comprueba que lo has hecho, para no
    mezclar las cuotas de una cuenta con las de otra.

- **El proyecto recuerda dónde estabas**

    `agyswitcher init` prepara tu proyecto con `AGENTS.md` y una memoria en `dev_mem/`
    que la siguiente sesión, con otra cuenta o con otro agente, lee para continuar.

- **Para cualquier agente**

    Funciona con Antigravity/Gemini, Claude, ChatGPT/Codex, GitHub Copilot y Cursor: todos
    leen las mismas reglas desde `AGENTS.md`.

- **Seguro por diseño**

    No lee ni guarda contraseñas ni tokens, nunca inicia sesión por ti, no modifica la
    carpeta de `agy` y no envía nada fuera de tu equipo.

</div>

## Así se ve

=== "Cuentas y cuota"

    ![agyswitcher list: tabla de cuentas con cuota y aviso de cuota baja](assets/capturas/lista.svg)

=== "Cambio de cuenta guiado"

    ![agyswitcher set-active: instrucciones, verificación e instrucción para retomar](assets/capturas/cambio-guiado.svg)

=== "Preparar un proyecto"

    ![agyswitcher init: ficheros creados en el proyecto](assets/capturas/init.svg)

=== "Guardar el estado"

    ![agyswitcher handoff save: instrucción para que el agente guarde el estado](assets/capturas/handoff-save.svg)

*Pantallazos generados con cuentas ficticias.*

## Cómo funciona

`agy` guarda **una única sesión de Google** y su carpeta de trabajo (historial,
conversaciones, MCP, *skills*) es común a todas las cuentas. AgySwitcher se apoya en eso:

```mermaid
flowchart LR
    A["Cuota baja<br/>(aviso ≤ 15 %)"] --> B["agyswitcher handoff save<br/>el agente guarda el estado<br/>en dev_mem/"]
    B --> C["agyswitcher set-active trabajo<br/>/logout + inicio de sesión<br/>(verificado)"]
    C --> D["Instrucción para retomar<br/>el agente lee dev_mem/<br/>y continúa"]
    D --> A
```

Más detalle en [Conceptos](manual/conceptos.md).

## Empieza en cinco minutos

```powershell
agyswitcher add personal --email personal@example.com
agyswitcher add trabajo  --email trabajo@example.com --no-activate
cd C:\Proyectos\MiProyecto
agyswitcher init
agyswitcher list
```

Sigue el [tutorial de proyecto nuevo](tutoriales/proyecto-nuevo.md) o el de
[proyecto existente](tutoriales/proyecto-existente.md).

## Requisitos

Windows 10 u 11 y Antigravity CLI (`agy`). Con el [instalador](manual/instalacion.md) no
necesitas Python ni permisos de administrador.

---

AgySwitcher es software libre bajo licencia
[GPL-3.0-or-later](https://github.com/gabimarti/agyswitcher/blob/main/LICENSE). Código fuente,
incidencias y contribuciones en
[GitHub](https://github.com/gabimarti/agyswitcher).
