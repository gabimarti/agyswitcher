# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del catálogo y gestión de modelos de IA (ai_models.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agyswitcher.ai_models import (
    KNOWN_MODELS,
    AIModel,
    classify_model_pool,
    fetch_available_models,
    inject_preferred_model_args,
    parse_models_output,
)


def test_classify_model_pool() -> None:
    """Verifica la clasificación de modelos en los pools gemini y external."""
    assert classify_model_pool("gemini-3.8-flash-high") == "gemini"
    assert classify_model_pool("gemini-pro") == "gemini"
    assert classify_model_pool("GEMINI-ULTRA") == "gemini"
    assert classify_model_pool("claude-sonnet-4-6") == "external"
    assert classify_model_pool("claude-opus-4-6-thinking") == "external"
    assert classify_model_pool("gpt-oss-120b-medium") == "external"
    assert classify_model_pool("custom-unknown-model") == "external"


def test_parse_models_output_standard_tab_separated() -> None:
    """Parsea correctamente la salida real tabulada de agy models."""
    sample = (
        "Fetching available models...\n"
        "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
        "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
        "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
    )
    models = parse_models_output(sample)
    assert len(models) == 3
    assert models[0] == AIModel("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)", "gemini")
    assert models[1] == AIModel("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)", "external")
    assert models[2] == AIModel("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)", "external")


def test_parse_models_output_space_separated_or_minimal() -> None:
    """Parsea salidas alternativas con espacios o sin nombre explícito."""
    sample = "gemini-flash-lite\nclaude-haiku-3.5 Anthropic Claude Haiku\n"
    models = parse_models_output(sample)
    assert len(models) == 2
    assert models[0].id == "gemini-flash-lite"
    assert models[0].display_name == "gemini-flash-lite"
    assert models[0].pool == "gemini"
    assert models[1].id == "claude-haiku-3.5"
    assert models[1].display_name == "Anthropic Claude Haiku"
    assert models[1].pool == "external"


def test_parse_models_output_empty_or_errors() -> None:
    """Ignora líneas vacías y mensajes de error."""
    assert parse_models_output("") == []
    assert parse_models_output("Fetching available models...\n\n") == []
    assert parse_models_output("Error: unauthorized\nWarning: high load\n") == []


@patch("agyswitcher.ai_models.find_agy_executable")
@patch("agyswitcher.ai_models.run_captured")
def test_fetch_available_models_success(mock_run: MagicMock, mock_find: MagicMock) -> None:
    """fetch_available_models ejecuta agy models y parsea su salida."""
    mock_find.return_value = Path("C:/mock/agy.exe")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "gemini-flash-test\tGemini Test\n"
    mock_run.return_value = mock_proc

    result = fetch_available_models(timeout=5.0)
    assert len(result) == 1
    assert result[0].id == "gemini-flash-test"
    mock_run.assert_called_once_with(
        ["C:\\mock\\agy.exe", "models"],
        timeout=5.0,
    )


@patch("agyswitcher.ai_models.find_agy_executable")
@patch("agyswitcher.ai_models.run_captured")
def test_fetch_available_models_fallback_on_error(
    mock_run: MagicMock, mock_find: MagicMock
) -> None:
    """En caso de timeout o error no cero, hace fallback a KNOWN_MODELS si está habilitado."""
    mock_find.return_value = Path("C:/mock/agy.exe")
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="agy models", timeout=5.0)

    result = fetch_available_models(fallback_to_known=True)
    assert result == KNOWN_MODELS


def test_inject_preferred_model_args() -> None:
    """Verifica la inyección correcta del flag --model."""
    # Sin modelo preferido -> argumentos idénticos
    assert inject_preferred_model_args(["--help"], None) == ["--help"]
    assert inject_preferred_model_args(["--help"], "") == ["--help"]

    # Con modelo preferido -> inyecta al principio
    injected = inject_preferred_model_args(["--prompt", "hola"], "gemini-3.8-flash-high")
    assert injected == ["--model", "gemini-3.8-flash-high", "--prompt", "hola"]

    # Si ya se pasa --model explícito -> no duplica ni sobreescribe
    already_explicit = ["--model", "claude-opus-4-6-thinking", "run-something"]
    assert (
        inject_preferred_model_args(already_explicit, "gemini-3.8-flash-high") == already_explicit
    )

    # Con alias corto -m
    with_short = ["-m", "gpt-oss-120b-medium", "task"]
    assert inject_preferred_model_args(with_short, "gemini-3.8-flash-high") == with_short

    # Con formato --model=...
    with_eq = ["--model=gemini-pro", "task"]
    assert inject_preferred_model_args(with_eq, "claude-sonnet-4-6") == with_eq


@pytest.mark.parametrize("model_id", ["--evil", "-x", "a b", "a&b", "x" * 200])
def test_inject_preferred_model_skips_invalid_ids(model_id: str) -> None:
    """Un ID inválido (empieza por '-', espacios, metacaracteres, demasiado largo) no se inyecta."""
    assert inject_preferred_model_args(["--help"], model_id) == ["--help"]
