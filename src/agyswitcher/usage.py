# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: usage.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-19

Descripción: Módulo de consulta y análisis de cuota en vivo y estado de autenticación.

Permite verificar si la sesión de Antigravity CLI (agy) está autenticada
y parsear la cuota consumida/restante y los tiempos de reinicio semanal
de los pools 'gemini' y 'external'.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agyswitcher.models import AccountQuotaInfo, AppState, is_valid_email
from agyswitcher.runner import RunnerError, find_agy_executable, run_captured, sanitize_line
from agyswitcher.session import read_log_tail

DEFAULT_QUOTA_TTL_SECONDS: float = 180.0
"""Tiempo por defecto (segundos) de validez de las métricas de cuota antes de considerarlas obsoletas (3 min)."""


def is_quota_stale(
    info: AccountQuotaInfo | None,
    ttl_seconds: float = DEFAULT_QUOTA_TTL_SECONDS,
    now: datetime | None = None,
) -> bool:
    """Comprueba si la información de cuota está ausente, sin fecha o ha superado el TTL.

    Args:
        info: Objeto AccountQuotaInfo con las métricas guardadas de la cuenta.
        ttl_seconds: Tiempo máximo en segundos para considerar frescos los datos guardados.
        now: Momento de referencia (None usa datetime.now(UTC)).

    Returns:
        True si los datos están obsoletos o ausentes y requieren refresco.
    """
    if info is None or info.updated_at is None:
        return True
    current = now if now is not None else datetime.now(UTC)
    return (current - info.updated_at).total_seconds() > ttl_seconds


_AUTH_ERROR_PATTERNS = [
    re.compile(r"(?i)\b(?:please\s+log\s+in|not\s+logged\s+in|authentication\s+required)\b"),
    re.compile(r"(?i)\b(?:sign\s+in\s+with\s+google|unauthorized|invalid\s+credentials)\b"),
    re.compile(r"(?i)\b(?:login\s+to\s+continue|session\s+expired)\b"),
]

_PERCENT_PATTERN = re.compile(r"(\d{1,3})%")
_TIMESTAMP_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\b")

_EMAIL_AUTH_PATTERNS = [
    re.compile(r"applyAuthResult:\s+email=([\w\.\-\+]+@[\w\.\-]+)", re.IGNORECASE),
    re.compile(r"OAuth:\s+authenticated successfully as\s+([\w\.\-\+]+@[\w\.\-]+)", re.IGNORECASE),
    re.compile(r"Cache\(userInfo\).*?([\w\.\-\+]+@[\w\.\-]+)", re.IGNORECASE),
]


def detect_active_email(
    base_dir: Path | None = None,
    max_scan_lines: int = 2000,
) -> str | None:
    """Detecta de forma segura el email de la cuenta de Google activa en agy.

    Inspecciona en modo solo-lectura las líneas recientes de cli.log y archivos
    rotados en ~/.gemini/antigravity-cli/log, buscando eventos de autenticación
    satisfactoria. No accede a tokens, cookies ni secretos. De cada fichero solo lee
    el final (MAX_NEW_BYTES_PER_FILE) y solo devuelve emails con formato válido.
    Ordena todos los archivos de registro por fecha de modificación para evaluar
    siempre la sesión más reciente.

    Args:
        base_dir: Directorio raíz de antigravity-cli (None usa ~/.gemini/antigravity-cli).
        max_scan_lines: Cantidad máxima de líneas recientes a analizar por archivo.

    Returns:
        Cadena con el email de Google autenticado, o None si no se detecta sesión.
    """
    root = base_dir or (Path.home() / ".gemini" / "antigravity-cli")
    candidates: list[Path] = []

    primary_log = root / "cli.log"
    if primary_log.is_file():
        candidates.append(primary_log)

    log_dir = root / "log"
    if log_dir.is_dir():
        with contextlib.suppress(OSError):
            candidates.extend(
                p for p in log_dir.iterdir() if p.is_file() and p.name.endswith(".log")
            )

    def _safe_mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    candidates.sort(key=_safe_mtime, reverse=True)

    for log_path in candidates[:10]:
        try:
            text = read_log_tail(log_path)
        except OSError:
            continue

        lines = text.splitlines()[-max_scan_lines:]
        for line in reversed(lines):
            for pattern in _EMAIL_AUTH_PATTERNS:
                match = pattern.search(line)
                if match:
                    email = match.group(1).strip()
                    if is_valid_email(email):
                        return email
    return None


class UsageError(Exception):
    """Error al consultar o procesar la cuota de agy."""


class AuthRequiredError(UsageError):
    """La sesión de agy no está autenticada o las credenciales son inválidas."""


@dataclass(frozen=True)
class PoolUsage:
    """Métricas de consumo y límite semanal para un pool de modelos."""

    pool: str
    display_name: str
    metric: str
    remaining_percent: int
    reset_time: datetime | None
    reset_raw: str

    @property
    def consumed_percent(self) -> int:
        """Porcentaje de cuota consumido."""
        return max(0, 100 - self.remaining_percent)

    @property
    def is_exhausted(self) -> bool:
        """Indica si el pool está completamente agotado."""
        return self.remaining_percent <= 0

    def to_dict(self) -> dict[str, object]:
        return {
            "pool": self.pool,
            "display_name": self.display_name,
            "metric": self.metric,
            "remaining_percent": self.remaining_percent,
            "consumed_percent": self.consumed_percent,
            "reset_time": self.reset_time.isoformat() if self.reset_time else None,
            "reset_raw": self.reset_raw,
            "is_exhausted": self.is_exhausted,
        }


@dataclass(frozen=True)
class UsageReport:
    """Informe consolidado de autenticación y estado de cuotas."""

    is_authenticated: bool
    pools: dict[str, PoolUsage] = field(default_factory=dict)
    raw_output: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    active_email: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "is_authenticated": self.is_authenticated,
            "pools": {k: v.to_dict() for k, v in self.pools.items()},
            "raw_output": self.raw_output,
            "timestamp": self.timestamp.isoformat(),
            "active_email": self.active_email,
        }


def format_time_remaining(
    reset_time: datetime | None,
    now: datetime | None = None,
) -> str:
    """Calcula el tiempo relativo legible restante hasta el reinicio de cuota.

    Args:
        reset_time: Momento de reseteo semanal de la cuota.
        now: Momento de referencia (por defecto datetime.now(UTC)).

    Returns:
        Cadena descriptiva (ej: '6d 22h', '3h 15m', '42m' o 'En reinicio').
    """
    if reset_time is None:
        return "Desconocido"

    current = now if now is not None else datetime.now(UTC)
    delta = reset_time - current

    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "En reinicio"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def parse_usage_output(
    output: str,
    active_email: str | None = None,
) -> UsageReport:
    """Analiza la salida textual del comando 'agy -p /usage'.

    Args:
        output: Salida completa devuelta por agy.
        active_email: Email de la cuenta activa si ya se ha detectado.

    Returns:
        UsageReport con el estado de autenticación y los pools detectados.
    """
    clean_text = output.strip()
    if not clean_text:
        return UsageReport(
            is_authenticated=False,
            pools={},
            raw_output=output,
            active_email=active_email,
        )

    # Verificar si la salida contiene errores explícitos de login
    for pattern in _AUTH_ERROR_PATTERNS:
        if pattern.search(clean_text):
            return UsageReport(
                is_authenticated=False,
                pools={},
                raw_output=clean_text,
                active_email=active_email,
            )

    pools: dict[str, PoolUsage] = {}
    lines = clean_text.splitlines()

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        pool_key: str | None = None
        display_name = ""

        if "gemini" in line_str.lower():
            pool_key = "gemini"
            display_name = "Gemini Models"
        elif "claude" in line_str.lower() or "gpt" in line_str.lower():
            pool_key = "external"
            display_name = "Claude and GPT models"

        if pool_key is None:
            continue

        percent_match = _PERCENT_PATTERN.search(line_str)
        if not percent_match:
            continue
        remaining_percent = max(0, min(100, int(percent_match.group(1))))

        ts_match = _TIMESTAMP_PATTERN.search(line_str)
        reset_time: datetime | None = None
        reset_raw = ""
        if ts_match:
            reset_raw = ts_match.group(1)
            try:
                # Normalizar terminación Z a offset UTC compatible con ISO
                iso_str = reset_raw.replace("Z", "+00:00")
                reset_time = datetime.fromisoformat(iso_str)
            except ValueError:
                reset_time = None

        metric_name = "Weekly Limit Remaining"
        if "\t" in line_str:
            parts = [p.strip() for p in line_str.split("\t") if p.strip()]
            if len(parts) >= 2:
                metric_name = parts[1]

        pools[pool_key] = PoolUsage(
            pool=pool_key,
            display_name=display_name,
            metric=metric_name,
            remaining_percent=remaining_percent,
            reset_time=reset_time,
            reset_raw=reset_raw,
        )

    is_auth = len(pools) > 0
    return UsageReport(
        is_authenticated=is_auth,
        pools=pools,
        raw_output=clean_text,
        active_email=active_email,
    )


def fetch_usage(
    timeout: float = 15.0,
    agy_path: Path | None = None,
) -> UsageReport:
    """Ejecuta 'agy -p /usage' y devuelve el informe analizado de cuotas.

    Args:
        timeout: Tiempo máximo de espera en segundos.
        agy_path: Ruta explícita al binario agy (None busca en el PATH).

    Returns:
        UsageReport con las métricas de consumo y autenticación.

    Raises:
        AgyNotFoundError: Si agy.exe no se localiza en el sistema.
        AuthRequiredError: Si el subproceso falla por requerir inicio de sesión.
        UsageError: Si la llamada a agy falla o excede el tiempo de espera.
    """
    exe = agy_path if agy_path is not None else find_agy_executable()
    cmd = [str(exe), "-p", "/usage"]

    try:
        proc = run_captured(cmd, timeout=timeout)
    except subprocess.TimeoutExpired as err:
        raise UsageError(
            f"Tiempo de espera agotado ({timeout}s) al consultar la cuota de agy."
        ) from err
    except OSError as err:
        raise RunnerError(f"Error al ejecutar agy: {err}") from err

    combined_output = f"{proc.stdout}\n{proc.stderr}".strip()
    sanitized_output = sanitize_line(combined_output)

    active_email = detect_active_email()
    report = parse_usage_output(proc.stdout, active_email=active_email)

    if proc.returncode != 0:
        for pattern in _AUTH_ERROR_PATTERNS:
            if pattern.search(sanitized_output):
                raise AuthRequiredError(
                    "Sesión no iniciada en Google. Ejecuta 'agy' interactivamente para autenticarte."
                )
        raise UsageError(
            f"El comando 'agy -p /usage' finalizó con código {proc.returncode}: {sanitized_output}"
        )

    if not report.is_authenticated:
        for pattern in _AUTH_ERROR_PATTERNS:
            if pattern.search(sanitized_output):
                raise AuthRequiredError(
                    "Sesión no iniciada en Google. Ejecuta 'agy' interactivamente para autenticarte."
                )

    return report


def update_state_from_usage_report(
    state: AppState,
    alias: str,
    report: UsageReport,
    sync_cooldowns: bool = True,
) -> bool:
    """Actualiza las métricas de cuota y sincroniza los cooldowns de un alias a partir de un UsageReport.

    Args:
        state: Instancia de AppState a modificar en memoria.
        alias: Alias de la cuenta asociada al informe.
        report: Informe de cuotas obtenido de agy.
        sync_cooldowns: Si es True, sincroniza también los diccionarios de cooldown
            gemini_quota_exhausted y external_quota_exhausted.

    Returns:
        True si hubo alguna actualización o cambio en el estado.
    """
    if not report.is_authenticated or not report.pools:
        return False

    gemini_pool = report.pools.get("gemini")
    external_pool = report.pools.get("external")

    gemini_pct = gemini_pool.remaining_percent if gemini_pool else None
    gemini_rt = gemini_pool.reset_time if gemini_pool else None
    external_pct = external_pool.remaining_percent if external_pool else None
    external_rt = external_pool.reset_time if external_pool else None

    state.update_account_quota(
        alias=alias,
        gemini_percent=gemini_pct,
        gemini_reset_time=gemini_rt,
        external_percent=external_pct,
        external_reset_time=external_rt,
        updated_at=report.timestamp,
    )

    state_changed = True

    if sync_cooldowns:
        now_iso = report.timestamp.isoformat()
        if gemini_pool:
            if gemini_pool.is_exhausted:
                # Se renueva la fecha si el reinicio previsto ya pasó: el dato era antiguo.
                if not state.is_pool_blocked(alias, "gemini", report.timestamp):
                    state.gemini_quota_exhausted[alias] = now_iso
            elif alias in state.gemini_quota_exhausted:
                del state.gemini_quota_exhausted[alias]

        if external_pool:
            if external_pool.is_exhausted:
                # Se renueva la fecha si el reinicio previsto ya pasó: el dato era antiguo.
                if not state.is_pool_blocked(alias, "external", report.timestamp):
                    state.external_quota_exhausted[alias] = now_iso
            elif alias in state.external_quota_exhausted:
                del state.external_quota_exhausted[alias]

    return state_changed
