# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: project.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-18
Ultimo cambio: 2026-11-19

Descripción: Continuidad de un proyecto entre cuentas y entre agentes de IA.

- Preparación de un repositorio ('agyswitcher init'): AGENTS.md como reglas comunes para
  cualquier agente, ficheros mínimos que remiten a AGENTS.md para cada agente (Gemini/agy,
  Claude, Copilot, Cursor; ChatGPT/Codex leen AGENTS.md directamente) y la memoria del
  proyecto en dev_mem/ (ESTADO.md, TODO.md). Nunca sobrescribe ficheros existentes.
- Instrucciones de traspaso ('agyswitcher handoff'): texto para pedir al agente que guarde
  el estado antes de cambiar de cuenta y texto para retomarlo después. Se pueden
  personalizar por proyecto en '.agyswitcher.toml'.
- Aviso de cuota baja: umbral a partir del cual conviene guardar el estado a tiempo.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agyswitcher.config import LOW_QUOTA_DEFAULT, is_valid_low_quota
from agyswitcher.models import AccountQuotaInfo

PROJECT_CONFIG_NAME = ".agyswitcher.toml"
"""Fichero de configuración de AgySwitcher dentro de un proyecto."""

HANDOFF_FILE_NAME = "HANDOFF.md"
"""Nombre del fichero markdown de traspaso entre sesiones."""

LOW_QUOTA_PERCENT = LOW_QUOTA_DEFAULT
"""Porcentaje restante por defecto a partir del cual se avisa para guardar el estado a tiempo."""

DEFAULT_SAVE_PROMPT = (
    "Vamos a cambiar de cuenta. Guarda ahora el estado del proyecto siguiendo AGENTS.md: "
    "actualiza dev_mem/ESTADO.md (situación actual, último cambio verificado y siguientes "
    "pasos), dev_mem/TODO.md y el diario de hoy en dev_mem/AAAA-MM-DD.md, con todo lo "
    "necesario para que otra sesión continúe sin contexto previo. Confirma cuando termines."
)

DEFAULT_RESUME_PROMPT = (
    "Continuamos el trabajo en una nueva sesión. Lee AGENTS.md, dev_mem/ESTADO.md, "
    "dev_mem/TODO.md, el diario más reciente de dev_mem/ y dev_mem/HANDOFF.md (o HANDOFF.md "
    "si existe). Resume en pocas líneas dónde estamos y cuál es el siguiente paso, y espera mi "
    "confirmación antes de seguir."
)

AGENT_POINTER_FILES: dict[str, str] = {
    "gemini": "GEMINI.md",
    "claude": "CLAUDE.md",
    "copilot": ".github/copilot-instructions.md",
    "cursor": ".cursor/rules/agents.mdc",
}
"""Fichero que lee cada agente. ChatGPT/Codex y otros leen AGENTS.md directamente."""

DEFAULT_AGENTS: tuple[str, ...] = ("gemini", "claude")


class ProjectError(Exception):
    """Error de preparación o configuración de un proyecto."""


@dataclass(frozen=True)
class HandoffPrompts:
    """Instrucciones de traspaso de un proyecto."""

    save: str
    resume: str
    source: Path | None = None
    """Fichero '.agyswitcher.toml' del que se leyeron (None si son las de por defecto)."""
    error: str | None = None
    """Motivo por el que no se pudo leer la configuración del proyecto (se usan las de por defecto)."""


@dataclass
class ScaffoldResult:
    """Ficheros creados y omitidos (ya existían) al preparar un proyecto."""

    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    merged: list[Path] = field(default_factory=list)
    """Ficheros existentes a los que se añadió la parte que les faltaba (modo --merge)."""


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------


MEMORY_MARK = "<!-- agyswitcher:memoria -->"
"""Marca que identifica la sección de memoria añadida por AgySwitcher (evita duplicarla)."""

MEMORY_HEADING = "## Memoria del proyecto (`dev_mem/`)"

POINTER_MARK = "<!-- agyswitcher:agents -->"
"""Marca del aviso que remite a AGENTS.md en los ficheros de cada agente."""


def _memory_section() -> str:
    return f"""{MEMORY_MARK}
{MEMORY_HEADING}

El trabajo puede continuar en otra sesión, con otra cuenta o con otro agente. Para que
nadie pierda el contexto:

- **Al empezar una sesión:** lee `dev_mem/ESTADO.md`, `dev_mem/TODO.md`, el diario más
  reciente (`dev_mem/AAAA-MM-DD.md`) y `dev_mem/HANDOFF.md` (o `HANDOFF.md` si existe) antes
  de hacer nada.
- **Durante el trabajo:** anota en el diario del día las decisiones, cambios y problemas.
- **Al terminar una tarea, o cuando se pida "guardar estado":** actualiza
  - `dev_mem/ESTADO.md`: situación actual, último cambio verificado y siguientes pasos;
  - `dev_mem/TODO.md`: tareas pendientes con prioridad y estado;
  - `dev_mem/AAAA-MM-DD.md`: diario de la sesión;
  - `dev_mem/HANDOFF.md`: si se prepara un traspaso de cuenta o sesión.
- El estado debe bastar para que otra sesión continúe **sin contexto previo**.
- No guardes secretos, tokens, contraseñas ni datos personales en `dev_mem/`.
"""


def _agents_md(project_name: str) -> str:
    return f"""# AGENTS.md — {project_name}

Instrucciones comunes para **cualquier agente de IA** que trabaje en este proyecto
(Antigravity/Gemini, Claude, ChatGPT/Codex, Copilot, Cursor u otros). Los ficheros propios
de cada agente (`GEMINI.md`, `CLAUDE.md`...) solo remiten a este documento.

{_memory_section()}
## Proyecto

- **Propósito:** _(describe en dos o tres líneas qué hace el proyecto)_
- **Stack:** _(lenguaje, framework, versiones)_
- **Cómo ejecutar las pruebas:** _(comando)_
- **Convenciones:** _(estilo, idioma de los mensajes, estructura de carpetas)_

## Reglas

- Haz cambios pequeños y verificables; ejecuta las pruebas antes de dar algo por terminado.
- Si cambias el comportamiento o la estructura, actualiza la documentación y `dev_mem/`.
"""


def _pointer_md(agents_file: str = "AGENTS.md") -> str:
    return (
        f"{POINTER_MARK}\n"
        "Las instrucciones de este proyecto están en "
        f"[{agents_file}]({agents_file}). Léelo y síguelo antes de empezar, en especial la "
        "sección de memoria del proyecto (`dev_mem/`).\n"
    )


def _gemini_md() -> str:
    return "# GEMINI.md\n\n" + _pointer_md()


def _claude_md() -> str:
    # '@AGENTS.md' importa el fichero en Claude Code.
    return "# CLAUDE.md\n\n@AGENTS.md\n\n" + _pointer_md()


def _copilot_md() -> str:
    return "# Instrucciones para Copilot\n\n" + _pointer_md("../AGENTS.md")


def _cursor_mdc() -> str:
    return (
        "---\ndescription: Reglas comunes del proyecto\nalwaysApply: true\n---\n\n"
        + _pointer_md("../../AGENTS.md")
    )


_POINTER_TEMPLATES = {
    "gemini": _gemini_md,
    "claude": _claude_md,
    "copilot": _copilot_md,
    "cursor": _cursor_mdc,
}


def _estado_md(project_name: str) -> str:
    return f"""# ESTADO DEL PROYECTO — {project_name}

**Fecha de última actualización:** _(AAAA-MM-DD)_

## Situación actual

_(fase, qué funciona, qué no)_

## Último cambio verificado

_(qué se hizo y cómo se comprobó)_

## Siguientes pasos

1. _(siguiente tarea concreta)_

## Contexto clave

_(decisiones, rutas, comandos o avisos que otra sesión necesita saber)_
"""


def _todo_md(project_name: str) -> str:
    return f"""# TODO — {project_name}

**Prioridades:** P0 (bloqueante), P1 (alta), P2 (media), P3 (baja)

## Tareas

- [ ] **[P1]** _(primera tarea)_
"""


def _toml_string(text: str) -> str:
    return '"""\n' + text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '\n"""'


def _project_toml() -> str:
    return (
        "# Configuración de AgySwitcher para este proyecto.\n"
        "# Instrucciones que muestra 'agyswitcher handoff' para traspasar el trabajo\n"
        "# entre cuentas o agentes. Puedes adaptarlas a tu forma de trabajar.\n\n"
        "[handoff]\n"
        f"save_prompt = {_toml_string(DEFAULT_SAVE_PROMPT)}\n\n"
        f"resume_prompt = {_toml_string(DEFAULT_RESUME_PROMPT)}\n\n"
        "# Aviso de cuota baja: porcentaje restante (1-99) a partir del cual se avisa para\n"
        "# guardar el estado. Sin indicarlo se usa el valor global\n"
        "# ('agyswitcher config low-quota'), por defecto 20.\n"
        "# [quota]\n"
        "# low_percent = 20\n"
    )


# ---------------------------------------------------------------------------
# Preparación del proyecto
# ---------------------------------------------------------------------------


def parse_agents(value: str) -> tuple[str, ...]:
    """Convierte 'gemini,claude' en una tupla validada de agentes.

    Raises:
        ProjectError: Si algún agente no está soportado.
    """
    names = tuple(dict.fromkeys(a.strip().lower() for a in value.split(",") if a.strip()))
    unknown = [a for a in names if a not in AGENT_POINTER_FILES]
    if unknown:
        valid = ", ".join(sorted(AGENT_POINTER_FILES))
        raise ProjectError(
            f"Agente no soportado: {', '.join(unknown)}. Valores válidos: {valid}. "
            "ChatGPT/Codex no necesitan fichero propio: leen AGENTS.md."
        )
    return names


def planned_files(root: Path, project_name: str, agents: tuple[str, ...]) -> dict[Path, str]:
    """Ficheros (ruta -> contenido) que prepara 'init' para los agentes indicados."""
    files: dict[Path, str] = {
        root / "AGENTS.md": _agents_md(project_name),
        root / "dev_mem" / "ESTADO.md": _estado_md(project_name),
        root / "dev_mem" / "TODO.md": _todo_md(project_name),
        root / PROJECT_CONFIG_NAME: _project_toml(),
    }
    for agent in agents:
        files[root / AGENT_POINTER_FILES[agent]] = _POINTER_TEMPLATES[agent]()
    return files


def _merge_block(root: Path, path: Path, agents: tuple[str, ...]) -> str | None:
    """Bloque que falta en un fichero existente (modo merge), o None si no falta nada."""
    if path == root / "AGENTS.md":
        return _memory_section()
    pointer_paths = {root / AGENT_POINTER_FILES[a]: AGENT_POINTER_FILES[a] for a in agents}
    rel = pointer_paths.get(path)
    if rel is None:
        return None
    if rel == AGENT_POINTER_FILES["claude"]:
        # Claude Code solo carga el contenido de otro fichero con la importación '@'.
        return _pointer_md() + "\n@AGENTS.md\n"
    depth = rel.count("/")
    return _pointer_md("../" * depth + "AGENTS.md")


def _already_has(path: Path, text: str) -> bool:
    """Indica si el fichero ya contiene lo que 'merge' añadiría."""
    if path.name == "AGENTS.md":
        return MEMORY_MARK in text or MEMORY_HEADING in text
    return POINTER_MARK in text or "AGENTS.md" in text


def _append_block(path: Path, block: str, dry_run: bool) -> bool:
    """Añade 'block' al final de 'path' respetando sus saltos de línea. True si añadió algo."""
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as err:
        raise ProjectError(f"'{path}' no está en UTF-8; no se modifica.") from err
    except OSError as err:
        raise ProjectError(f"No se pudo leer '{path}': {err.strerror or err}.") from err
    if _already_has(path, text):
        return False
    if dry_run:
        return True
    newline = "\r\n" if "\r\n" in text else "\n"
    addition = block.rstrip("\n").replace("\n", newline) + newline
    if not text.strip():
        separator = ""
    elif text.endswith("\n"):
        separator = newline  # una línea en blanco entre el contenido y el bloque
    else:
        separator = newline * 2
    try:
        with path.open("ab") as handle:
            handle.write((separator + addition).encode("utf-8"))
    except OSError as err:
        raise ProjectError(f"No se pudo escribir '{path}': {err.strerror or err}.") from err
    return True


def scaffold_project(
    root: Path,
    agents: tuple[str, ...] = DEFAULT_AGENTS,
    *,
    project_name: str | None = None,
    dry_run: bool = False,
    merge: bool = False,
) -> ScaffoldResult:
    """Prepara 'root' para trabajar con varias cuentas o agentes sin perder el contexto.

    Crea solo los ficheros que no existen (nunca sobrescribe). Con 'merge', a los ficheros
    existentes les añade al final lo que les falte: la sección de memoria a AGENTS.md y el
    aviso que remite a AGENTS.md a los ficheros de cada agente. El resto de su contenido no
    se toca, y no se añade dos veces (se reconoce por marca o por contenido).

    Args:
        root: Carpeta raíz del proyecto (debe existir).
        agents: Agentes para los que crear el fichero que remite a AGENTS.md.
        project_name: Nombre mostrado en las plantillas (None usa el nombre de la carpeta).
        dry_run: Si es True, no escribe nada (solo informa).
        merge: Completar los ficheros existentes en lugar de omitirlos.

    Returns:
        ScaffoldResult con los ficheros creados, completados y omitidos (o los que lo serían).

    Raises:
        ProjectError: Si 'root' no es una carpeta o no se puede leer o escribir un fichero.
    """
    if not root.is_dir():
        raise ProjectError(f"'{root}' no existe o no es una carpeta.")
    name = project_name or root.resolve().name
    result = ScaffoldResult()
    for path, content in planned_files(root, name, agents).items():
        if path.exists():
            block = _merge_block(root, path, agents) if merge else None
            if block is not None and _append_block(path, block, dry_run):
                result.merged.append(path)
            else:
                result.skipped.append(path)
            continue
        if not dry_run:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
            except FileExistsError:
                result.skipped.append(path)
                continue
            except OSError as err:
                raise ProjectError(f"No se pudo crear '{path}': {err.strerror or err}.") from err
        result.created.append(path)
    return result


# ---------------------------------------------------------------------------
# Instrucciones de traspaso
# ---------------------------------------------------------------------------


def find_project_config(start: Path) -> Path | None:
    """Busca '.agyswitcher.toml' en 'start' y sus carpetas superiores."""
    current = start.resolve()
    for folder in (current, *current.parents):
        candidate = folder / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_handoff_prompts(start: Path) -> HandoffPrompts:
    """Instrucciones de traspaso del proyecto que contiene 'start' (o las de por defecto).

    Un fichero ilegible o mal formado no es un error fatal: se usan las de por defecto y se
    indica el motivo en 'error'.
    """
    config = find_project_config(start)
    if config is None:
        return HandoffPrompts(DEFAULT_SAVE_PROMPT, DEFAULT_RESUME_PROMPT)
    try:
        with config.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as err:
        return HandoffPrompts(
            DEFAULT_SAVE_PROMPT, DEFAULT_RESUME_PROMPT, source=config, error=str(err)
        )
    section = data.get("handoff")
    handoff = section if isinstance(section, dict) else {}
    save = handoff.get("save_prompt")
    resume = handoff.get("resume_prompt")
    return HandoffPrompts(
        save=save.strip() if isinstance(save, str) and save.strip() else DEFAULT_SAVE_PROMPT,
        resume=(
            resume.strip() if isinstance(resume, str) and resume.strip() else DEFAULT_RESUME_PROMPT
        ),
        source=config,
    )


def handoff_file_path(root: Path) -> Path:
    """Ruta del fichero de traspaso: dev_mem/HANDOFF.md si dev_mem/ existe, o HANDOFF.md en root."""
    dev_mem = root / "dev_mem"
    if dev_mem.is_dir():
        return dev_mem / HANDOFF_FILE_NAME
    return root / HANDOFF_FILE_NAME


def write_handoff_file(
    root: Path,
    *,
    prompts: HandoffPrompts | None = None,
    account: str | None = None,
    pool: str | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> Path:
    """Escribe o actualiza el fichero HANDOFF.md en el proyecto.

    Si existe dev_mem/, se guarda en dev_mem/HANDOFF.md; si no, en la raíz del proyecto.
    El fichero contiene las instrucciones para que el siguiente agente retome el contexto
    y las notas de traspaso.

    Returns:
        Ruta del fichero escrito.

    Raises:
        ProjectError: Si no se puede escribir el fichero.
    """
    path = handoff_file_path(root)
    current_time = now or datetime.now(UTC)
    active_prompts = prompts or load_handoff_prompts(root)

    account_line = f"- **Cuenta saliente:** `{account}`\n" if account else ""
    pool_line = f"- **Pool saliente:** `{pool}`\n" if pool else ""
    notes_content = (
        notes.strip()
        if notes and notes.strip()
        else "_(Sin notas adicionales. Lee ESTADO.md y TODO.md para ver el punto exacto de avance)_"
    )

    content = (
        "# HANDOFF — Traspaso de Sesión\n\n"
        f"**Fecha y hora:** {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"{account_line}"
        f"{pool_line}\n"
        "## Instrucción para el nuevo agente\n\n"
        f"{active_prompts.resume}\n\n"
        "## Contexto y reglas del proyecto\n\n"
        "- Reglas e instrucciones comunes: `AGENTS.md`\n"
        "- Estado operativo actual: `dev_mem/ESTADO.md`\n"
        "- Tareas pendientes: `dev_mem/TODO.md`\n\n"
        "## Notas de traspaso\n\n"
        f"{notes_content}\n"
    )

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8", newline="\n")
        tmp_path.replace(path)
    except OSError as err:
        raise ProjectError(
            f"No se pudo escribir el fichero de traspaso '{path}': {err.strerror or err}."
        ) from err

    return path


# ---------------------------------------------------------------------------
# Cuota baja
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LowQuotaThreshold:
    """Umbral del aviso de cuota baja y de dónde sale."""

    percent: int
    source: str
    """'proyecto', 'global' o 'por defecto'."""
    project_file: Path | None = None
    error: str | None = None
    """Motivo por el que se ignoró el valor del proyecto (fichero ilegible o valor inválido)."""


def resolve_low_quota_threshold(start: Path, global_percent: int | None) -> LowQuotaThreshold:
    """Umbral de cuota baja: el del proyecto ('[quota] low_percent'), el global o el de por defecto.

    Un '.agyswitcher.toml' ilegible o con un valor fuera de 1-99 no es fatal: se ignora y se
    indica el motivo en 'error'.
    """
    config = find_project_config(start)
    error: str | None = None
    if config is not None:
        try:
            with config.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as err:
            data = {}
            error = str(err)
        section = data.get("quota")
        value = section.get("low_percent") if isinstance(section, dict) else None
        if isinstance(value, int) and is_valid_low_quota(value):
            return LowQuotaThreshold(value, "proyecto", config)
        if value is not None:
            error = f"[quota] low_percent debe ser un entero de 1 a 99 (es {value!r})"
    if global_percent is not None and is_valid_low_quota(global_percent):
        return LowQuotaThreshold(global_percent, "global", config, error)
    return LowQuotaThreshold(LOW_QUOTA_DEFAULT, "por defecto", config, error)


def low_quota_percent(
    info: AccountQuotaInfo | None, pool: str, threshold: int = LOW_QUOTA_PERCENT
) -> int | None:
    """Porcentaje restante del pool si está por debajo del umbral pero no agotado.

    Returns:
        El porcentaje (1..threshold) si conviene avisar; None en caso contrario o sin datos.
    """
    if info is None:
        return None
    pct = info.gemini_percent if pool == "gemini" else info.external_percent
    if pct is None or pct <= 0 or pct > threshold:
        return None
    return pct
