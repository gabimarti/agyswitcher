# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""Tests unitarios del módulo credman (Windows Credential Manager)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

from agyswitcher.credman import (
    ACTIVE_TARGET,
    CRED_PERSIST_LOCAL_MACHINE,
    ERROR_NOT_FOUND,
    FILETIME,
    SLOT_PREFIX,
    CredentialData,
    CredManCorruptError,
    CredManEmailMismatchError,
    CredManError,
    CredManNotFoundError,
    CredManPlatformError,
    alias_from_slot_target,
    delete_credential,
    delete_slot,
    get_active_email,
    get_slot_email,
    has_slot,
    is_slot_target,
    list_slot_aliases,
    list_slot_targets,
    promote_slot_to_active,
    read_credential,
    save_slot_from_active,
    slot_target_name,
    write_credential,
)

# ---------------------------------------------------------------------------
# Helpers y Fixtures
# ---------------------------------------------------------------------------


def _make_blob(
    email: str = "test@example.com",
    auth_method: str = "oauth",
    token: dict[str, Any] | None = None,
) -> bytes:
    data = {
        "auth_method": auth_method,
        "id_token_email": email,
        "token": token or {"access_token": "fake_token_abc", "token_type": "Bearer"},
    }
    return json.dumps(data).encode("utf-8")


@pytest.fixture()
def fake_credman(monkeypatch: pytest.MonkeyPatch) -> dict[str, CredentialData]:
    """Emula Windows Credential Manager en memoria para pruebas de lógica de alto nivel."""
    store: dict[str, CredentialData] = {}

    def mock_read(target_name: str) -> CredentialData | None:
        return store.get(target_name)

    def mock_write(
        target_name: str,
        blob: bytes,
        user_name: str = "antigravity",
        persist: int = CRED_PERSIST_LOCAL_MACHINE,
    ) -> None:
        store[target_name] = CredentialData(
            target_name=target_name,
            user_name=user_name,
            blob=blob,
            persist=persist,
            last_written=datetime.now(tz=UTC),
        )

    def mock_delete(target_name: str) -> bool:
        if target_name in store:
            del store[target_name]
            return True
        return False

    def mock_list_targets() -> list[str]:
        targets = [t for t in store if is_slot_target(t)]
        targets.sort()
        return targets

    monkeypatch.setattr("agyswitcher.credman.read_credential", mock_read)
    monkeypatch.setattr("agyswitcher.credman.write_credential", mock_write)
    monkeypatch.setattr("agyswitcher.credman.delete_credential", mock_delete)
    monkeypatch.setattr("agyswitcher.credman.list_slot_targets", mock_list_targets)

    return store


# ---------------------------------------------------------------------------
# Tests de Helpers y Conversión
# ---------------------------------------------------------------------------


def test_slot_target_helpers() -> None:
    """Valida los helpers de nombres y prefijos de targets de slots."""
    target = slot_target_name("cuenta-a")
    assert target == f"{SLOT_PREFIX}cuenta-a"
    assert is_slot_target(target) is True
    assert is_slot_target(ACTIVE_TARGET) is False
    assert is_slot_target("otro:target:distinto") is False

    assert alias_from_slot_target(target) == "cuenta-a"
    assert alias_from_slot_target(ACTIVE_TARGET) is None
    assert alias_from_slot_target("otro:target") is None


def test_credential_data_extract_email() -> None:
    """CredentialData extrae el email correctamente según varios formatos de blob."""
    # Email válido
    data = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=_make_blob("usuario@example.com"),
    )
    assert data.extract_email() == "usuario@example.com"

    # Email inválido
    bad_email_data = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=json.dumps({"id_token_email": "no-es-un-correo"}).encode("utf-8"),
    )
    assert bad_email_data.extract_email() is None

    # Sin campo id_token_email
    no_email_data = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=json.dumps({"otro_campo": 123}).encode("utf-8"),
    )
    assert no_email_data.extract_email() is None

    # JSON no objeto
    list_data = CredentialData(target_name="test", user_name="antigravity", blob=b"[]")
    assert list_data.extract_email() is None

    # Blob corrupto / no JSON
    corrupt_data = CredentialData(target_name="test", user_name="antigravity", blob=b"not-json")
    assert corrupt_data.extract_email() is None

    # Blob vacío
    empty_data = CredentialData(target_name="test", user_name="antigravity", blob=b"")
    assert empty_data.extract_email() is None


def test_credential_data_is_valid_agy_blob() -> None:
    """is_valid_agy_blob valida la presencia de los campos requeridos por agy."""
    # Válido
    data = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=_make_blob("valido@example.com"),
    )
    assert data.is_valid_agy_blob() is True

    # Falta token
    no_token = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=json.dumps({"auth_method": "oauth", "id_token_email": "a@example.com"}).encode(
            "utf-8"
        ),
    )
    assert no_token.is_valid_agy_blob() is False

    # Falta auth_method
    no_method = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=json.dumps({"id_token_email": "a@example.com", "token": {}}).encode("utf-8"),
    )
    assert no_method.is_valid_agy_blob() is False

    # Email inválido
    invalid_email = CredentialData(
        target_name="test",
        user_name="antigravity",
        blob=json.dumps(
            {
                "auth_method": "oauth",
                "id_token_email": "invalido",
                "token": {},
            }
        ).encode("utf-8"),
    )
    assert invalid_email.is_valid_agy_blob() is False

    # Vacío
    assert (
        CredentialData(target_name="test", user_name="antigravity", blob=b"").is_valid_agy_blob()
        is False
    )


def test_filetime_to_datetime() -> None:
    """FILETIME convierte correctamente marcas de tiempo de 64 bits a datetime UTC."""
    ft_zero = FILETIME()
    ft_zero.dwLowDateTime = 0
    ft_zero.dwHighDateTime = 0
    assert ft_zero.to_datetime() == datetime.fromtimestamp(0, tz=UTC)

    # 2026-11-23 12:00:00 UTC en 100ns FILETIME
    dt = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
    epoch_seconds = int(dt.timestamp())
    epoch_100ns = (epoch_seconds * 10_000_000) + 116444736000000000
    ft_custom = FILETIME()
    ft_custom.dwLowDateTime = epoch_100ns & 0xFFFFFFFF
    ft_custom.dwHighDateTime = (epoch_100ns >> 32) & 0xFFFFFFFF

    converted = ft_custom.to_datetime()
    assert converted.year == 2026
    assert converted.month == 11
    assert converted.day == 23
    assert converted.hour == 12


# ---------------------------------------------------------------------------
# Tests de Operaciones de Alto Nivel (con fake_credman)
# ---------------------------------------------------------------------------


def test_has_slot_and_get_slot_email(
    fake_credman: dict[str, CredentialData],
) -> None:
    """has_slot y get_slot_email detectan la presencia e identidad de un slot."""
    assert has_slot("cuenta-1") is False
    assert get_slot_email("cuenta-1") is None

    fake_credman[slot_target_name("cuenta-1")] = CredentialData(
        target_name=slot_target_name("cuenta-1"),
        user_name="antigravity",
        blob=_make_blob("cuenta1@example.com"),
    )

    assert has_slot("cuenta-1") is True
    assert get_slot_email("cuenta-1") == "cuenta1@example.com"


def test_get_active_email(fake_credman: dict[str, CredentialData]) -> None:
    """get_active_email devuelve el correo de la credencial gemini:antigravity."""
    assert get_active_email() is None

    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=_make_blob("activa@example.com"),
    )
    assert get_active_email() == "activa@example.com"


def test_save_slot_from_active_success(
    fake_credman: dict[str, CredentialData],
) -> None:
    """save_slot_from_active clona la sesión activa en el slot correspondiente."""
    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=_make_blob("activa@example.com"),
    )

    email = save_slot_from_active("cuenta-guardada")
    assert email == "activa@example.com"

    slot_key = slot_target_name("cuenta-guardada")
    assert slot_key in fake_credman
    assert fake_credman[slot_key].extract_email() == "activa@example.com"


def test_save_slot_from_active_with_expected_email(
    fake_credman: dict[str, CredentialData],
) -> None:
    """save_slot_from_active valida que el email coincida con expected_email."""
    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=_make_blob("activa@example.com"),
    )

    # Coincide (case-insensitive)
    email = save_slot_from_active("alias-1", expected_email="ACTIVA@example.com")
    assert email == "activa@example.com"

    # No coincide
    with pytest.raises(CredManEmailMismatchError) as exc_info:
        save_slot_from_active("alias-1", expected_email="otra@example.com")
    assert "activa@example.com" in str(exc_info.value)
    assert "otra@example.com" in str(exc_info.value)


def test_save_slot_from_active_errors(
    fake_credman: dict[str, CredentialData],
) -> None:
    """save_slot_from_active lanza excepciones apropiadas si no existe o es corrupta."""
    # No existe credencial activa
    with pytest.raises(CredManNotFoundError):
        save_slot_from_active("alias-1")

    # Credencial activa con blob no válido
    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=b"corrupto",
    )
    with pytest.raises(CredManCorruptError):
        save_slot_from_active("alias-1")


def test_promote_slot_to_active_success(
    fake_credman: dict[str, CredentialData],
) -> None:
    """promote_slot_to_active promueve el slot a la credencial activa principal."""
    slot_key = slot_target_name("destino")
    fake_credman[slot_key] = CredentialData(
        target_name=slot_key,
        user_name="antigravity",
        blob=_make_blob("destino@example.com"),
    )

    email = promote_slot_to_active("destino")
    assert email == "destino@example.com"

    assert ACTIVE_TARGET in fake_credman
    assert fake_credman[ACTIVE_TARGET].extract_email() == "destino@example.com"


def test_promote_slot_to_active_syncs_outgoing_account(
    fake_credman: dict[str, CredentialData],
) -> None:
    """promote_slot_to_active sincroniza la sesión saliente antes de promover la nueva."""
    # Sesión activa actual (cuenta saliente con token renovado)
    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=_make_blob("saliente@example.com", token={"access_token": "token_renovado"}),
    )

    # Slot de la cuenta entrante
    slot_entrante = slot_target_name("entrante")
    fake_credman[slot_entrante] = CredentialData(
        target_name=slot_entrante,
        user_name="antigravity",
        blob=_make_blob("entrante@example.com"),
    )

    # Promover entrante con sincronización de la saliente
    email = promote_slot_to_active("entrante", sync_outgoing_alias="saliente")
    assert email == "entrante@example.com"

    # La activa es ahora la entrante
    assert fake_credman[ACTIVE_TARGET].extract_email() == "entrante@example.com"

    # El slot de la saliente recibió la sincronización con el token renovado
    slot_saliente = slot_target_name("saliente")
    assert slot_saliente in fake_credman
    assert b"token_renovado" in fake_credman[slot_saliente].blob


def test_promote_slot_to_active_errors(
    fake_credman: dict[str, CredentialData],
) -> None:
    """promote_slot_to_active valida existencia, integridad y coincidencia de email."""
    # Slot no existe
    with pytest.raises(CredManNotFoundError):
        promote_slot_to_active("inexistente")

    # Slot corrupto
    bad_slot = slot_target_name("corrupto")
    fake_credman[bad_slot] = CredentialData(
        target_name=bad_slot,
        user_name="antigravity",
        blob=b"corrupto",
    )
    with pytest.raises(CredManCorruptError):
        promote_slot_to_active("corrupto")

    # Discrepancia de email
    good_slot = slot_target_name("cuenta-a")
    fake_credman[good_slot] = CredentialData(
        target_name=good_slot,
        user_name="antigravity",
        blob=_make_blob("cuenta-a@example.com"),
    )
    with pytest.raises(CredManEmailMismatchError):
        promote_slot_to_active("cuenta-a", expected_email="esperaba-otro@example.com")


def test_delete_slot(fake_credman: dict[str, CredentialData]) -> None:
    """delete_slot elimina la credencial del slot y devuelve el booleano correcto."""
    slot_key = slot_target_name("para-borrar")
    fake_credman[slot_key] = CredentialData(
        target_name=slot_key,
        user_name="antigravity",
        blob=_make_blob("borrar@example.com"),
    )

    assert delete_slot("para-borrar") is True
    assert slot_key not in fake_credman
    assert delete_slot("para-borrar") is False


def test_list_slot_aliases(fake_credman: dict[str, CredentialData]) -> None:
    """list_slot_aliases devuelve ordenados los alias con slot registrado."""
    fake_credman[slot_target_name("beta")] = CredentialData(
        target_name=slot_target_name("beta"),
        user_name="antigravity",
        blob=b"{}",
    )
    fake_credman[slot_target_name("alfa")] = CredentialData(
        target_name=slot_target_name("alfa"),
        user_name="antigravity",
        blob=b"{}",
    )
    fake_credman[ACTIVE_TARGET] = CredentialData(
        target_name=ACTIVE_TARGET,
        user_name="antigravity",
        blob=b"{}",
    )

    aliases = list_slot_aliases()
    assert aliases == ["alfa", "beta"]


# ---------------------------------------------------------------------------
# Tests de Compatibilidad de Plataforma y Fallbacks
# ---------------------------------------------------------------------------


def test_non_windows_platform_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """En sistemas que no sean Windows, credman maneja la ausencia de API sin fallar."""
    monkeypatch.setattr("sys.platform", "linux")

    # Las operaciones de consulta segura devuelven valores neutros
    assert has_slot("cualquiera") is False
    assert get_slot_email("cualquiera") is None
    assert get_active_email() is None
    assert list_slot_targets() == []
    assert list_slot_aliases() == []

    # Las operaciones directas de bajo nivel o mutaciones lanzan CredManPlatformError
    with pytest.raises(CredManPlatformError):
        read_credential("test")

    with pytest.raises(CredManPlatformError):
        write_credential("test", b"")

    with pytest.raises(CredManPlatformError):
        delete_credential("test")


# ---------------------------------------------------------------------------
# Tests de Operaciones Win32 Reales e Intercepción de Errores
# ---------------------------------------------------------------------------


@pytest.mark.real_credman
@pytest.mark.skipif(sys.platform != "win32", reason="Requiere Windows")
def test_real_win32_credential_roundtrip() -> None:
    """Valida un ciclo real de escritura, lectura, enumeración y borrado en Windows."""
    test_target = "gemini:antigravity:slot:__test_unit_roundtrip__"
    delete_credential(test_target)
    try:
        assert read_credential(test_target) is None
        blob = _make_blob("realwin32@example.com")
        write_credential(test_target, blob, user_name="antigravity")

        cred = read_credential(test_target)
        assert cred is not None
        assert cred.target_name == test_target
        assert cred.user_name == "antigravity"
        assert cred.blob == blob
        assert cred.extract_email() == "realwin32@example.com"

        targets = list_slot_targets()
        assert test_target in targets

        assert delete_credential(test_target) is True
        assert read_credential(test_target) is None
        assert delete_credential(test_target) is False
    finally:
        delete_credential(test_target)


def test_low_level_win32_read_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_credential devuelve None cuando Win32 reporta ERROR_NOT_FOUND."""

    class MockAdvapi32:
        def CredReadW(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", lambda: MockAdvapi32())
    monkeypatch.setattr("ctypes.get_last_error", lambda: ERROR_NOT_FOUND)

    assert read_credential("no_existe") is None


def test_low_level_win32_read_generic_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_credential lanza CredManError ante errores inesperados de la API."""

    class MockAdvapi32:
        def CredReadW(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", lambda: MockAdvapi32())
    monkeypatch.setattr("ctypes.get_last_error", lambda: 5)  # ERROR_ACCESS_DENIED

    with pytest.raises(CredManError) as exc_info:
        read_credential("bloqueado")
    assert "Win32 Error: 5" in str(exc_info.value)


def test_low_level_win32_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """write_credential lanza CredManError si CredWriteW retorna FALSE."""

    class MockAdvapi32:
        def CredWriteW(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", lambda: MockAdvapi32())
    monkeypatch.setattr("ctypes.get_last_error", lambda: 87)

    with pytest.raises(CredManError) as exc_info:
        write_credential("falla", b"contenido")
    assert "Win32 Error: 87" in str(exc_info.value)


def test_low_level_win32_delete_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_credential lanza CredManError ante un error inesperado al borrar."""

    class MockAdvapi32:
        def CredDeleteW(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", lambda: MockAdvapi32())
    monkeypatch.setattr("ctypes.get_last_error", lambda: 1312)

    with pytest.raises(CredManError) as exc_info:
        delete_credential("error")
    assert "Win32 Error: 1312" in str(exc_info.value)


def test_low_level_win32_enumerate_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_slot_targets maneja ERROR_NOT_FOUND devolviendo [] y lanza ante otros errores."""

    class MockAdvapi32:
        def CredEnumerateW(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr("agyswitcher.credman._get_advapi32", lambda: MockAdvapi32())

    # ERROR_NOT_FOUND -> lista vacía
    monkeypatch.setattr("ctypes.get_last_error", lambda: ERROR_NOT_FOUND)
    assert list_slot_targets() == []

    # Error inesperado -> lanza CredManError
    monkeypatch.setattr("ctypes.get_last_error", lambda: 5)
    with pytest.raises(CredManError) as exc_info:
        list_slot_targets()
    assert "Win32 Error: 5" in str(exc_info.value)
