# Varios agentes y proveedores

AgySwitcher gestiona las cuentas y la cuota de Antigravity CLI (`agy`), pero la forma en que
prepara tus proyectos **no depende de ningún agente ni proveedor**. Puedes usar `agy` gratis
para el día a día y combinarlo con Claude Code, Codex de ChatGPT, GitHub Copilot o Cursor
cuando lo necesites: todos entienden la misma estructura y el mismo contexto del proyecto.

## Por qué funciona

Cada agente busca sus instrucciones en un fichero distinto. En lugar de mantener varias copias
(que acaban diciendo cosas diferentes), `agyswitcher init` crea **un único documento de reglas,
`AGENTS.md`**, y en cada fichero específico solo pone un aviso que remite a él:

```text
mi-proyecto/
├── AGENTS.md                          <- reglas comunes y memoria
├── GEMINI.md                          <- Antigravity / Gemini: "lee AGENTS.md"
├── CLAUDE.md                          <- Claude Code: importa @AGENTS.md
├── .github/copilot-instructions.md    <- GitHub Copilot (opcional)
├── .cursor/rules/agents.mdc           <- Cursor (opcional)
├── .agyswitcher.toml                  <- instrucciones de guardar y retomar
└── dev_mem/                           <- memoria compartida
    ├── ESTADO.md                      <- dónde estamos y qué sigue
    ├── TODO.md                        <- tareas con prioridad
    └── AAAA-MM-DD.md                  <- diario de cada sesión
```

| Agente | Qué fichero lee | Cómo llega a `AGENTS.md` |
| :--- | :--- | :--- |
| Antigravity CLI (`agy`) / Gemini | `GEMINI.md` | Le indica que lea `AGENTS.md`. |
| Claude Code | `CLAUDE.md` | Lo importa con `@AGENTS.md`. |
| Codex (ChatGPT) y otros | `AGENTS.md` | Lo leen directamente; no necesitan fichero propio. |
| GitHub Copilot | `.github/copilot-instructions.md` | Le indica que lea `AGENTS.md`. |
| Cursor | `.cursor/rules/agents.mdc` | Regla siempre activa que remite a `AGENTS.md`. |

`AGENTS.md` es un formato abierto que adoptan cada vez más agentes, así que un agente nuevo
probablemente lo entienda sin hacer nada.

Por defecto `init` crea los ficheros de Gemini y Claude. Para añadir Copilot y Cursor:

```powershell
agyswitcher init --agents gemini,claude,copilot,cursor
```

Si el proyecto ya tenía alguno de esos ficheros, `agyswitcher init --merge` les añade solo el
aviso que falte, sin tocar lo que ya hay.

## La memoria es común

La sección de memoria de `AGENTS.md` pide a **cualquier** agente lo mismo:

- al empezar, leer `dev_mem/ESTADO.md`, `dev_mem/TODO.md` y el diario más reciente;
- durante el trabajo, anotar decisiones y cambios en el diario del día;
- al terminar o cuando se le pida «guardar estado», actualizar esos ficheros para que otra
  sesión pueda seguir **sin contexto previo**.

Por eso da igual quién escribió la última entrada: la siguiente sesión, sea del agente que
sea, parte de la misma información.

## Las instrucciones de traspaso sirven para todos

`agyswitcher handoff save` y `agyswitcher handoff resume` generan instrucciones en lenguaje
normal, sin nada específico de `agy`. Puedes pegarlas en cualquier agente:

```powershell
agyswitcher handoff save -c     # copiada: pégala en el agente que vas a dejar
agyswitcher handoff resume -c   # copiada: pégala en el agente con el que sigues
```

## Ejemplo: `agy` gratis + otro agente para tareas concretas

1. **Día a día con `agy`.** Programas con `agy` y AgySwitcher reparte el trabajo entre tus
   cuentas de Google, como se explica en [Uso en el día a día](dia-a-dia.md).
2. **Una tarea especial.** Quieres que Claude Code revise la arquitectura o que Codex escriba
   las pruebas que faltan. Antes de cambiar, pega en `agy` la instrucción de
   `handoff save`.
3. **Abres el otro agente en la misma carpeta.** Lee `CLAUDE.md` (o `AGENTS.md`), pega la
   instrucción de `handoff resume` y el agente se pone al día con `dev_mem/`.
4. **Al terminar**, pídele que guarde el estado. Cuando vuelvas a `agy`, la nueva sesión
   sabrá qué hizo el otro agente.

También sirve al revés: si empiezas con un agente de pago y se te acaba el plan o el
presupuesto del mes, puedes seguir con `agy` sin perder el hilo.

!!! note "Qué gestiona AgySwitcher y qué no"
    El seguimiento de cuota, los avisos y el cambio de cuenta guiado son solo para `agy`.
    Los demás agentes usan sus propias cuentas y planes; AgySwitcher no los toca. Lo que sí
    comparten todos es la estructura del proyecto y su memoria.

## Consejos

- **Un solo sitio para las reglas.** Escribe las normas del proyecto en `AGENTS.md`, no en
  `CLAUDE.md` ni en `GEMINI.md`, para que todos los agentes lean lo mismo.
- **Guarda el estado al cambiar de agente**, igual que al cambiar de cuenta.
- **Diles quién eres en el diario.** Pide a cada agente que indique en la entrada del diario
  con qué herramienta trabajó; ayuda a entender el historial.
- **Usa Git como red de seguridad**: un commit antes de pasar el proyecto a otro agente.

Más detalle sobre `init`, `handoff` y `.agyswitcher.toml` en
[Continuidad del proyecto](continuidad.md).
