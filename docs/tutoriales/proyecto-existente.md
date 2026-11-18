# Tutorial: incorporar AgySwitcher a un proyecto existente

Tu proyecto ya existe y quizá ya tiene sus propias reglas para agentes (`AGENTS.md`,
`CLAUDE.md`, `GEMINI.md`...). AgySwitcher se incorpora **sin sobrescribir nada**.

Si aún no has registrado tus cuentas, haz antes el paso 1 del
[tutorial de proyecto nuevo](proyecto-nuevo.md#1-registra-tus-cuentas-una-sola-vez).

## 1. Mira qué haría

```powershell
cd C:\ruta\a\mi-proyecto
agyswitcher init --merge --dry-run
```

Verás tres tipos de línea:

- **Se crearía:** ficheros que no existen (por ejemplo `dev_mem/ESTADO.md`).
- **Se completaría:** ficheros existentes a los que les falta algo. A `AGENTS.md` se le
  añadiría al final la sección *Memoria del proyecto*; a `CLAUDE.md`, `GEMINI.md`... un
  aviso que remite a `AGENTS.md`.
- **Ya existe (no se toca):** ficheros que ya tienen lo necesario.

Si usas otros agentes, indícalos: `--agents gemini,claude,copilot,cursor`.

## 2. Aplica

```powershell
agyswitcher init --merge
```

Lo añadido va al final de cada fichero, separado por una línea en blanco y con una marca
(`<!-- agyswitcher:... -->`) para no repetirlo si vuelves a ejecutar `init --merge`. El resto
del contenido no cambia.

## 3. Revisa tus reglas

Abre `AGENTS.md` y comprueba que la sección añadida encaja con tus reglas:

- Si tu proyecto ya tenía otro sistema de notas (por ejemplo `docs/NOTAS.md`), adapta la
  sección para usar el tuyo, o mueve tus notas a `dev_mem/`.
- Si tus reglas estaban solo en `CLAUDE.md` o `GEMINI.md` y `init` ha creado un `AGENTS.md`
  nuevo, conviene **mover las reglas comunes a `AGENTS.md`** y dejar en cada fichero de
  agente solo lo específico de ese agente. Así todos los agentes siguen las mismas reglas.
- Si usas otras rutas, ajusta también las instrucciones de `.agyswitcher.toml`
  (ver [Continuidad del proyecto](../manual/continuidad.md#personalizar-las-instrucciones-agyswitchertoml)).

## 4. Primer estado

`dev_mem/ESTADO.md` se crea con una plantilla vacía. La forma más rápida de rellenarlo es
pedírselo al agente:

> *«Lee AGENTS.md. Revisa el proyecto y rellena dev_mem/ESTADO.md (situación actual, último
> cambio verificado, siguientes pasos y contexto clave) y dev_mem/TODO.md con lo que veas
> pendiente. Crea también el diario de hoy en dev_mem/.»*

Revisa lo que escriba y corrige lo que haga falta: será el punto de partida de cualquier
sesión futura.

## 5. Decide si `dev_mem/` se publica

```powershell
Add-Content .gitignore "dev_mem/"    # si no quieres publicarlo
```

## 6. A partir de aquí

El ciclo es el mismo que en un proyecto nuevo: aviso de cuota baja → `agyswitcher handoff
save` → `agyswitcher set-active <alias>` → instrucción para retomar. Ver los pasos 5 a 8 del
[tutorial de proyecto nuevo](proyecto-nuevo.md#5-cuando-la-cuota-baja).
