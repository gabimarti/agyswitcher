# Continuidad del proyecto

Cuando una cuenta agota su cuota, el objetivo es que la siguiente sesión, con otra cuenta
o con otro agente de IA, continúe **sabiendo dónde lo dejaste**. Como el historial de
conversación de un agente no siempre se puede retomar, la memoria del proyecto se guarda
en ficheros dentro del propio proyecto.

## Preparar un proyecto (`init`)

```powershell
cd C:\ruta\a\mi-proyecto
agyswitcher init
```

| Fichero | Contenido |
| :--- | :--- |
| `AGENTS.md` | Reglas comunes para cualquier agente y el **procedimiento de memoria**: leer `dev_mem/` al empezar, anotar en el diario y actualizar el estado al terminar o cuando se pida. Incluye una sección *Proyecto* para que la completes. |
| `GEMINI.md` | Para Antigravity/Gemini: remite a `AGENTS.md`. |
| `CLAUDE.md` | Para Claude Code: importa `AGENTS.md` con `@AGENTS.md`. |
| `.github/copilot-instructions.md` | Para GitHub Copilot (con `--agents ...,copilot`). |
| `.cursor/rules/agents.mdc` | Para Cursor (con `--agents ...,cursor`). |
| `dev_mem/ESTADO.md` | Situación actual, último cambio verificado, siguientes pasos y contexto clave. |
| `dev_mem/TODO.md` | Tareas con prioridad. |
| `.agyswitcher.toml` | Instrucciones de traspaso de este proyecto. |

ChatGPT/Codex y otros agentes leen `AGENTS.md` directamente y no necesitan fichero propio.

`init` **nunca sobrescribe**. Si el proyecto ya tiene alguno de esos ficheros, lo deja como
está; con `--merge` les añade al final solo lo que les falte (la sección de memoria a
`AGENTS.md` y el aviso que remite a `AGENTS.md` a los ficheros de cada agente), sin tocar
el resto y sin duplicarlo si ya está. Usa `--dry-run` para ver antes qué haría.

### ¿Publicar `dev_mem/`?

Depende de ti. Si el repositorio es público y `dev_mem/` contiene notas internas, añádelo a
`.gitignore`. Si lo versionas, la memoria viaja con el repositorio (útil si trabajas en
varios equipos). Nunca guardes en `dev_mem/` contraseñas, tokens ni datos personales.

## Traspasar el trabajo (`handoff`)

1. **Antes de cambiar de cuenta**, mientras el agente aún responde:

   ```powershell
   agyswitcher handoff save
   ```

   Copia la instrucción y pégala en `agy`. El agente actualizará `ESTADO.md`, `TODO.md` y
   el diario.

2. **Cambia de cuenta** con `agyswitcher set-active <alias>`.

3. **Después del cambio**, AgySwitcher muestra la instrucción para retomar (también con
   `agyswitcher handoff resume`). Pégala como primera instrucción en `agy`: el agente leerá
   la memoria, te resumirá dónde estáis y esperará tu confirmación.

## Aviso de cuota baja

`list`, `status` y `run` avisan cuando al **pool activo de la cuenta activa** le queda un
**15 % o menos**. Es el momento de guardar el estado: si esperas a que se agote, el agente
ya no podrá hacerlo. El aviso deja en el portapapeles la instrucción de `handoff save`, lista
para pegar en `agy`, e indica la siguiente cuenta con cuota. Del mismo modo, tras un cambio
de cuenta verificado queda copiada la instrucción para retomar. La copia automática se
desactiva con `agyswitcher config auto-copy off`.

El umbral se cambia para todos los proyectos con `agyswitcher config low-quota 20`, o solo
para uno en su `.agyswitcher.toml`, que tiene prioridad:

```toml
[quota]
low_percent = 10
```

## Personalizar las instrucciones (`.agyswitcher.toml`)

`init` crea este fichero con las instrucciones por defecto. Puedes editarlas:

```toml
[handoff]
save_prompt = """
Guarda el estado del proyecto en dev_mem/ESTADO.md y el diario de hoy...
"""

resume_prompt = """
Lee AGENTS.md y dev_mem/ESTADO.md y continúa...
"""
```

AgySwitcher busca `.agyswitcher.toml` en la carpeta actual y, si no está, en las carpetas
superiores, así que funciona desde cualquier subcarpeta del proyecto. Si falta una de las
dos instrucciones, o el fichero tiene un error, se usa la instrucción por defecto (y
`handoff` te avisa del error).
