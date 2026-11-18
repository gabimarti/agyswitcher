# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: models.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-03
Ultimo cambio: 2026-11-06

Descripción: Modelos de datos de AgySwitcher.

Define las estructuras que representan una cuenta gestionada (Account)
y el estado global de la aplicación (AppState).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime


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
        email = data.get("email")
        pref_raw = data.get("preferred_models")
        preferred_models: dict[str, str] = {}
        if isinstance(pref_raw, dict):
            preferred_models = {str(k): str(v) for k, v in pref_raw.items()}

        return cls(
            alias=str(data["alias"]),
            added_at=datetime.fromisoformat(str(data["added_at"])),
            email=str(email) if isinstance(email, str) and email.strip() else None,
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
            switch_history = [str(item) for item in history_raw]

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
