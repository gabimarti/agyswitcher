# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: models.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-23

Descripción: Modelos de datos de AgySwitcher.

Define las estructuras que representan una cuenta gestionada (Account)
y el estado global de la aplicación (AppState).
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

EMAIL_PATTERN = re.compile(r"^[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+$")
"""Formato de email aceptado (mismo criterio que los patrones de los logs de agy)."""

STORED_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""Alias admitido al cargar config.json (más permisivo que el de creación, por compatibilidad)."""

MAX_SWITCH_HISTORY = 200
"""Número máximo de entradas que se conservan en el historial de cambios."""

QUOTA_POOLS: tuple[str, str] = ("gemini", "external")
"""Pools de cuota de cada cuenta, en orden de preferencia."""

QUOTA_RESET_FALLBACK = timedelta(days=7)
"""Reinicio estimado de un pool agotado cuando no hay fecha de reinicio fiable (cuota semanal)."""


def parse_utc(value: object) -> datetime | None:
    """Convierte una fecha ISO en datetime con zona (UTC si no la trae); None si no es válida."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def is_valid_email(value: str) -> bool:
    """Indica si 'value' tiene formato de email admitido (sin espacios ni marcado)."""
    return bool(EMAIL_PATTERN.match(value))


MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
"""ID de modelo admitido: no empieza por '-' (no puede parecer una opción) ni lleva espacios."""


def is_valid_model_id(value: str) -> bool:
    """Indica si 'value' es un ID de modelo seguro para pasarlo a agy como argumento."""
    return bool(MODEL_ID_PATTERN.match(value))


@dataclass
class AccountQuotaInfo:
    """Métricas y tiempos de reinicio semanal de cuota para una cuenta."""

    gemini_percent: int | None = None
    gemini_reset_time: datetime | None = None
    external_percent: int | None = None
    external_reset_time: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "gemini_percent": self.gemini_percent,
            "gemini_reset_time": self.gemini_reset_time.isoformat()
            if self.gemini_reset_time
            else None,
            "external_percent": self.external_percent,
            "external_reset_time": self.external_reset_time.isoformat()
            if self.external_reset_time
            else None,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AccountQuotaInfo:
        gemini_pct = data.get("gemini_percent")
        gemini_rt = data.get("gemini_reset_time")
        external_pct = data.get("external_percent")
        external_rt = data.get("external_reset_time")
        upd = data.get("updated_at")

        gemini_dt: datetime | None = None
        if isinstance(gemini_rt, str) and gemini_rt.strip():
            with contextlib.suppress(ValueError, TypeError):
                gemini_dt = datetime.fromisoformat(gemini_rt)

        external_dt: datetime | None = None
        if isinstance(external_rt, str) and external_rt.strip():
            with contextlib.suppress(ValueError, TypeError):
                external_dt = datetime.fromisoformat(external_rt)

        updated_dt: datetime = datetime.now(UTC)
        if isinstance(upd, str) and upd.strip():
            with contextlib.suppress(ValueError, TypeError):
                updated_dt = datetime.fromisoformat(upd)

        return cls(
            gemini_percent=int(gemini_pct) if isinstance(gemini_pct, (int, float)) else None,
            gemini_reset_time=gemini_dt,
            external_percent=int(external_pct) if isinstance(external_pct, (int, float)) else None,
            external_reset_time=external_dt,
            updated_at=updated_dt,
        )


@dataclass
class Account:
    """Cuenta/perfil gestionado por AgySwitcher."""

    alias: str
    added_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    email: str | None = None
    preferred_models: dict[str, str] = field(default_factory=dict)

    def get_preferred_model(self, pool: str) -> str | None:
        """Devuelve el ID del modelo preferido para el pool dado, o None si no hay."""
        return self.preferred_models.get(pool)

    def set_preferred_model(self, pool: str, model_id: str) -> None:
        """Establece el ID del modelo preferido para el pool indicado."""
        self.preferred_models[pool] = model_id

    def clear_preferred_models(self, pool: str | None = None) -> None:
        """Limpia la preferencia de modelos para el pool indicado o para todos si es None."""
        if pool is None:
            self.preferred_models.clear()
        else:
            self.preferred_models.pop(pool, None)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "alias": self.alias,
            "added_at": self.added_at.isoformat(),
        }
        if self.email is not None:
            data["email"] = self.email
        if self.preferred_models:
            data["preferred_models"] = dict(self.preferred_models)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Account:
        """Crea la cuenta desde config.json.

        Raises:
            KeyError: Si faltan campos obligatorios.
            ValueError: Si el alias o el email no tienen un formato válido.
        """
        alias = str(data["alias"])
        if not STORED_ALIAS_PATTERN.match(alias):
            raise ValueError(f"alias no válido: {alias!r}")
        email = data.get("email")
        if isinstance(email, str) and email.strip() and not is_valid_email(email.strip()):
            raise ValueError(f"email no válido en la cuenta {alias!r}: {email!r}")
        pref_raw = data.get("preferred_models")
        preferred_models: dict[str, str] = {}
        if isinstance(pref_raw, dict):
            preferred_models = {str(k): str(v) for k, v in pref_raw.items()}

        return cls(
            alias=alias,
            added_at=datetime.fromisoformat(str(data["added_at"])),
            email=email.strip() if isinstance(email, str) and email.strip() else None,
            preferred_models=preferred_models,
        )


@dataclass
class AppState:
    """Estado global de ejecución: cuenta activa, pools de cuota e historial.

    Las cuotas de Antigravity se gestionan en dos pools semanales independientes
    por cuenta de Google:

    - ``gemini``: Gemini Flash, Gemini Pro y sus variantes de effort.
    - ``external``: Claude Opus, Claude Sonnet, GPT-OSS.

    ``active_model_group`` indica qué pool está usando la sesión activa.
    Una cuenta se considera completamente agotada cuando aparece en ambos dicts.
    """

    active: str | None = None
    active_model_group: str = "gemini"
    gemini_quota_exhausted: dict[str, str] = field(default_factory=dict)
    external_quota_exhausted: dict[str, str] = field(default_factory=dict)
    switch_history: list[str] = field(default_factory=list)
    accounts_quota: dict[str, AccountQuotaInfo] = field(default_factory=dict)

    def append_history(self, event: str) -> None:
        """Añade un evento al historial conservando solo los MAX_SWITCH_HISTORY más recientes."""
        self.switch_history.append(event)
        if len(self.switch_history) > MAX_SWITCH_HISTORY:
            del self.switch_history[: len(self.switch_history) - MAX_SWITCH_HISTORY]

    def _exhausted_dict(self, pool: str) -> dict[str, str]:
        return self.gemini_quota_exhausted if pool == "gemini" else self.external_quota_exhausted

    def is_pool_exhausted(self, alias: str, pool: str) -> bool:
        """Indica si el pool figura como agotado en los datos guardados (sin mirar el reinicio)."""
        return alias in self._exhausted_dict(pool)

    def exhausted_since(self, alias: str, pool: str) -> datetime | None:
        """Momento en que se registró el pool como agotado (None si no lo está o no es legible)."""
        return parse_utc(self._exhausted_dict(pool).get(alias))

    def estimated_reset(self, alias: str, pool: str) -> datetime | None:
        """Reinicio previsto de un pool agotado.

        Usa la fecha de reinicio guardada si es posterior al agotamiento; si no la hay (o es
        de un periodo anterior), estima agotamiento + QUOTA_RESET_FALLBACK. None si el pool no
        figura como agotado o la fecha de agotamiento no es legible.
        """
        since = self.exhausted_since(alias, pool)
        if since is None:
            return None
        info = self.accounts_quota.get(alias)
        reset = None
        if info is not None:
            reset = info.gemini_reset_time if pool == "gemini" else info.external_reset_time
        if reset is not None:
            if reset.tzinfo is None:
                reset = reset.replace(tzinfo=UTC)
            if reset > since:
                return reset
        return since + QUOTA_RESET_FALLBACK

    def is_pool_blocked(self, alias: str, pool: str, now: datetime | None = None) -> bool:
        """Indica si el pool está agotado y su reinicio previsto aún no ha llegado.

        Un pool agotado cuyo reinicio previsto ya pasó se considera probablemente disponible
        (sin confirmar hasta consultar la cuota en vivo con esa cuenta).
        """
        if not self.is_pool_exhausted(alias, pool):
            return False
        reset = self.estimated_reset(alias, pool)
        if reset is None:
            return True
        return (now or datetime.now(UTC)) < reset

    def usable_group_for(self, alias: str, now: datetime | None = None) -> str | None:
        """Pool utilizable de la cuenta: primero uno no agotado; si no, uno con el reinicio ya pasado."""
        for pool in QUOTA_POOLS:
            if not self.is_pool_exhausted(alias, pool):
                return pool
        for pool in QUOTA_POOLS:
            if not self.is_pool_blocked(alias, pool, now):
                return pool
        return None

    def is_account_fully_exhausted(self, alias: str) -> bool:
        """Devuelve True si la cuenta tiene ambos pools de cuota agotados."""
        return alias in self.gemini_quota_exhausted and alias in self.external_quota_exhausted

    def available_group_for(self, alias: str) -> str | None:
        """Devuelve el primer pool disponible para la cuenta, o None si está agotada."""
        if alias not in self.gemini_quota_exhausted:
            return "gemini"
        if alias not in self.external_quota_exhausted:
            return "external"
        return None

    def update_account_quota(
        self,
        alias: str,
        gemini_percent: int | None = None,
        gemini_reset_time: datetime | None = None,
        external_percent: int | None = None,
        external_reset_time: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Actualiza o crea las métricas y tiempos de reset de cuota para una cuenta."""
        now = updated_at or datetime.now(UTC)
        existing = self.accounts_quota.get(alias)
        if existing is None:
            self.accounts_quota[alias] = AccountQuotaInfo(
                gemini_percent=gemini_percent,
                gemini_reset_time=gemini_reset_time,
                external_percent=external_percent,
                external_reset_time=external_reset_time,
                updated_at=now,
            )
        else:
            if gemini_percent is not None:
                existing.gemini_percent = gemini_percent
            if gemini_reset_time is not None:
                existing.gemini_reset_time = gemini_reset_time
            if external_percent is not None:
                existing.external_percent = external_percent
            if external_reset_time is not None:
                existing.external_reset_time = external_reset_time
            existing.updated_at = now

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "active_model_group": self.active_model_group,
            "gemini_quota_exhausted": self.gemini_quota_exhausted,
            "external_quota_exhausted": self.external_quota_exhausted,
            "switch_history": self.switch_history,
            "accounts_quota": {k: v.to_dict() for k, v in self.accounts_quota.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AppState:
        active = data.get("active")
        model_group = data.get("active_model_group", "gemini")
        gemini_raw = data.get("gemini_quota_exhausted")
        external_raw = data.get("external_quota_exhausted")
        history_raw = data.get("switch_history")
        quota_raw = data.get("accounts_quota")

        gemini_quota: dict[str, str] = {}
        if isinstance(gemini_raw, dict):
            gemini_quota = {str(k): str(v) for k, v in gemini_raw.items()}

        external_quota: dict[str, str] = {}
        if isinstance(external_raw, dict):
            external_quota = {str(k): str(v) for k, v in external_raw.items()}

        switch_history: list[str] = []
        if isinstance(history_raw, list):
            switch_history = [str(item) for item in history_raw][-MAX_SWITCH_HISTORY:]

        accounts_quota: dict[str, AccountQuotaInfo] = {}
        if isinstance(quota_raw, dict):
            for k, v in quota_raw.items():
                if isinstance(v, dict):
                    accounts_quota[str(k)] = AccountQuotaInfo.from_dict(v)

        return cls(
            active=str(active) if isinstance(active, str) else None,
            active_model_group=str(model_group) if isinstance(model_group, str) else "gemini",
            gemini_quota_exhausted=gemini_quota,
            external_quota_exhausted=external_quota,
            switch_history=switch_history,
            accounts_quota=accounts_quota,
        )
