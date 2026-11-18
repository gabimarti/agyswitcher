# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: quota.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-06

Descripción: Módulo de detección y análisis de errores de cuota para Antigravity CLI (agy).

Analiza las salidas de consola y logs en tiempo real para identificar eventos
de cuota agotada o rate limits, clasificándolos en el pool correspondiente
('gemini' o 'external').
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

# Patrones generales de cuota agotada o limitación de tasa (HTTP 429 / RESOURCE_EXHAUSTED)
QUOTA_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"(?i)\b(?:quota\s+exceeded|exhausted\s+(?:your\s+)?quota|out\s+of\s+quota)\b"),
    re.compile(r"(?i)\b(?:rate\s+limit(?:ed)?|too\s+many\s+requests)\b"),
    re.compile(r"(?i)\b(?:resource[_\s]?exhausted)\b"),
    re.compile(r"(?i)\b(?:weekly\s+limit\s+(?:reached|exhausted|exceeded))\b"),
    re.compile(r"(?i)\b(?:http\s+(?:status\s+)?429|status(?:\s*code)?\s*[:=]?\s*429)\b"),
    re.compile(r"(?i)\b(?:error\s+429\b)"),
]

# Patrones para inferir si el error pertenece específicamente al pool 'gemini' o 'external'
GEMINI_INDICATORS: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:gemini(?:-[a-zA-Z0-9_\-\.]+)?|google\s+generative|google\s+ai)\b"
)
EXTERNAL_INDICATORS: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:claude(?:-[a-zA-Z0-9_\-\.]+)?|anthropic|gpt(?:-[a-zA-Z0-9_\-\.]+)?|openai)\b"
)


@dataclass(frozen=True)
class QuotaEvent:
    """Representa un evento de cuota agotada interceptado."""

    pool: str
    raw_message: str
    detected_pattern: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, str]:
        return {
            "pool": self.pool,
            "raw_message": self.raw_message,
            "detected_pattern": self.detected_pattern,
            "timestamp": self.timestamp.isoformat(),
        }


class QuotaDetector:
    """Analizador en streaming para interceptar eventos de agotamiento de cuota."""

    def __init__(self, default_pool: str = "gemini") -> None:
        """Inicializa el detector con un pool por defecto en caso de ambigüedad.

        Args:
            default_pool: Pool asumido si el mensaje de error no menciona un modelo
                          explícito ('gemini' o 'external').
        """
        self.default_pool = default_pool if default_pool in {"gemini", "external"} else "gemini"

    def determine_pool(self, text: str) -> str:
        """Determina a qué pool ('gemini' o 'external') se atribuye el error."""
        has_gemini = bool(GEMINI_INDICATORS.search(text))
        has_external = bool(EXTERNAL_INDICATORS.search(text))

        if has_external and not has_gemini:
            return "external"
        if has_gemini and not has_external:
            return "gemini"
        return self.default_pool

    def detect_in_line(self, line: str) -> QuotaEvent | None:
        """Analiza una sola línea de texto en busca de patrones de cuota agotada.

        Args:
            line: Línea de texto emitida por agy o leída de logs.

        Returns:
            QuotaEvent si se identificó un error de cuota; None en caso contrario.
        """
        clean_line = line.strip()
        if not clean_line:
            return None

        for pattern in QUOTA_PATTERNS:
            match = pattern.search(clean_line)
            if match:
                detected_kw = match.group(0)
                target_pool = self.determine_pool(clean_line)
                return QuotaEvent(
                    pool=target_pool,
                    raw_message=clean_line,
                    detected_pattern=detected_kw,
                )

        return None

    def detect_in_text(self, text: str) -> list[QuotaEvent]:
        """Analiza un bloque de texto multilínea y retorna todos los eventos de cuota hallados."""
        events: list[QuotaEvent] = []
        for line in text.splitlines():
            event = self.detect_in_line(line)
            if event is not None:
                events.append(event)
        return events
