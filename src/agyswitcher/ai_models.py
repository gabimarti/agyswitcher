# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: ai_models.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-06
Ultimo cambio: 2026-11-23

Descripción: Catálogo, detección y gestión de modelos de IA de Antigravity.

Permite listar los modelos expuestos por ``agy models``, clasificarlos
en sus respectivos pools de cuota (``gemini`` o ``external``) y gestionar
la inyección automática del modelo preferido en las llamadas al CLI.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from agyswitcher.models import is_valid_model_id
from agyswitcher.runner import AgyNotFoundError, find_agy_executable, run_captured


class ModelsError(Exception):
    """Error al consultar o procesar los modelos de Antigravity."""


class ModelNotFoundError(ModelsError):
    """El modelo especificado no existe o no se encuentra disponible."""


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AIModel:
    """Representa un modelo de IA disponible en Antigravity CLI."""

    id: str
    display_name: str
    pool: str  # "gemini" | "external"


# Modelos conocidos por defecto (fallback cuando agy no está disponible o sin red)
KNOWN_MODELS: list[AIModel] = [
    AIModel(id="gemini-3.8-flash-high", display_name="Gemini 3.8 Flash (High)", pool="gemini"),
    AIModel(id="gemini-3.8-flash-medium", display_name="Gemini 3.8 Flash (Medium)", pool="gemini"),
    AIModel(id="gemini-3.8-flash-low", display_name="Gemini 3.8 Flash (Low)", pool="gemini"),
    AIModel(id="claude-sonnet-4-6", display_name="Claude Sonnet 4.6 (Thinking)", pool="external"),
    AIModel(
        id="claude-opus-4-6-thinking",
        display_name="Claude Opus 4.6 (Thinking)",
        pool="external",
    ),
    AIModel(id="gpt-oss-120b-medium", display_name="GPT-OSS 120B (Medium)", pool="external"),
]


# ---------------------------------------------------------------------------
# Clasificación de pools
# ---------------------------------------------------------------------------


def classify_model_pool(model_id: str) -> str:
    """Determina a qué pool de cuota pertenece un modelo según su ID.

    Reglas de Antigravity:
    - Modelos con prefijo o nombre 'gemini': pool 'gemini'.
    - Modelos con prefijo 'claude', 'gpt' o cualquier otro: pool 'external'.

    Args:
        model_id: Identificador técnico del modelo (ej. 'gemini-3.8-flash-high').

    Returns:
        'gemini' o 'external'.
    """
    clean_id = model_id.strip().lower()
    if "gemini" in clean_id:
        return "gemini"
    return "external"


# ---------------------------------------------------------------------------
# Parseo de salida de agy models
# ---------------------------------------------------------------------------


def parse_models_output(raw_output: str) -> list[AIModel]:
    """Parsea la salida de texto plano de ``agy models``.

    El formato emitido por agy suele ser:
        Fetching available models...
        gemini-3.8-flash-high\tGemini 3.8 Flash (High)
        claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)

    Args:
        raw_output: Salida completa capturada del comando.

    Returns:
        Lista de instancias :class:`AIModel` encontradas.
    """
    models: list[AIModel] = []
    lines = raw_output.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Descartar cabeceras o mensajes de estado
        if stripped.lower().startswith("fetching"):
            continue

        # Intentar división por tabulador (formato estándar de agy)
        if "\t" in stripped:
            parts = stripped.split("\t", maxsplit=1)
            model_id = parts[0].strip()
            display_name = parts[1].strip() if len(parts) > 1 else model_id
        else:
            # Fallback a división por espacios múltiples
            parts = stripped.split(maxsplit=1)
            model_id = parts[0].strip()
            display_name = parts[1].strip() if len(parts) > 1 else model_id

        # Si el ID parece válido (no es una frase informativa)
        if model_id and not model_id.startswith(("Error", "Warning", "[", "#")):
            pool = classify_model_pool(model_id)
            models.append(AIModel(id=model_id, display_name=display_name, pool=pool))

    return models


# ---------------------------------------------------------------------------
# Consulta en vivo de modelos
# ---------------------------------------------------------------------------


def fetch_available_models(
    agy_path: Path | None = None,
    timeout: float = 8.0,
    fallback_to_known: bool = True,
) -> list[AIModel]:
    """Ejecuta ``agy models`` y devuelve el catálogo de modelos disponibles.

    Args:
        agy_path: Ruta explícita a agy.exe o None para auto-detección.
        timeout: Segundos máximos de espera para el subproceso.
        fallback_to_known: Si es True, en caso de fallo devuelve KNOWN_MODELS.

    Returns:
        Lista de :class:`AIModel`.

    Raises:
        ModelsError: Si agy falla y fallback_to_known es False.
    """
    try:
        exe = agy_path if agy_path is not None else find_agy_executable()
    except AgyNotFoundError as err:
        if fallback_to_known:
            return list(KNOWN_MODELS)
        raise ModelsError(f"No se encontró el ejecutable de agy: {err}") from err

    cmd = [str(exe), "models"]
    try:
        proc = run_captured(cmd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if fallback_to_known:
            return list(KNOWN_MODELS)
        raise ModelsError(f"Tiempo de espera agotado al consultar modelos ({timeout}s)") from exc
    except OSError as exc:
        if fallback_to_known:
            return list(KNOWN_MODELS)
        raise ModelsError(f"Error del sistema al invocar agy models: {exc}") from exc

    if proc.returncode != 0:
        if fallback_to_known:
            return list(KNOWN_MODELS)
        raise ModelsError(f"agy models falló con código {proc.returncode}: {proc.stderr.strip()}")

    parsed = parse_models_output(proc.stdout)
    if not parsed and fallback_to_known:
        return list(KNOWN_MODELS)

    return parsed


# ---------------------------------------------------------------------------
# Inyección de argumentos CLI
# ---------------------------------------------------------------------------


def inject_preferred_model_args(
    args: list[str],
    preferred_model: str | None,
) -> list[str]:
    """Inyecta el argumento ``--model <id>`` si no se ha especificado explícitamente.

    Args:
        args: Lista de argumentos que se enviarán a agy.
        preferred_model: ID del modelo preferido a inyectar (o None si no hay).

    Returns:
        Nueva lista de argumentos (posiblemente con ``--model`` añadido). Un ID que no cumple
        ``MODEL_ID_PATTERN`` (por ejemplo, uno que empieza por '-') no se inyecta.
    """
    new_args = list(args)
    if preferred_model is None or not is_valid_model_id(preferred_model.strip()):
        return new_args

    # Si ya se pasa --model o -m manualmente, no sobreescribir
    for arg in new_args:
        if arg in ("--model", "-m") or arg.startswith("--model="):
            return new_args

    # Inyectar al principio de los argumentos para agy
    return ["--model", preferred_model.strip(), *new_args]
