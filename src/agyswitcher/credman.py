# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
"""
Módulo: credman.py

Autor: Gabriel Marti
Website & Contact: https://gabimarti.github.io/
Fecha inicio: 2026-11-23
Ultimo cambio: 2026-11-23

Descripción: Gestión segura de credenciales y slots de sesión en Windows Credential Manager.

Interactúa con la API Win32 Advapi32.dll mediante ctypes para leer, escribir y alternar
credenciales genéricas (CRED_TYPE_GENERIC) bajo el espacio de nombres 'gemini:antigravity'.
Permite crear slots de sesión (gemini:antigravity:slot:<alias>) para alternar cuentas
rápidamente sin almacenar tokens en archivos de disco ni registros de texto plano.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from collections.abc import Iterable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agyswitcher.models import is_valid_email

# Constantes del espacio de nombres de Credential Manager
ACTIVE_TARGET = "gemini:antigravity"
"""Target principal de Windows Credential Manager que lee y escribe Antigravity CLI."""

SLOT_PREFIX = "gemini:antigravity:slot:"
"""Prefijo para targets de sesión hermanas (slots) gestionados por AgySwitcher."""

CRED_TYPE_GENERIC = 1
"""Tipo de credencial genérica de Windows Credential Manager."""

CRED_PERSIST_SESSION = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_PERSIST_ENTERPRISE = 3

ERROR_NOT_FOUND = 1168
"""Código Win32 de elemento no encontrado (0x490 / ERROR_NOT_FOUND)."""


class CredManError(Exception):
    """Excepción base para errores en el Administrador de credenciales de Windows."""


class CredManPlatformError(CredManError):
    """Lanzada cuando se intenta usar CredMan en un sistema operativo no compatible (no-Windows)."""


class CredManNotFoundError(CredManError):
    """Lanzada cuando un target o slot solicitado no existe en Credential Manager."""


class CredManCorruptError(CredManError):
    """Lanzada cuando el blob de la credencial no tiene un formato válido o esperado."""


class CredManEmailMismatchError(CredManError):
    """Lanzada cuando el email contenido en el slot no coincide con el email esperado de la cuenta."""


# ---------------------------------------------------------------------------
# Estructuras nativas Win32 (Advapi32.dll)
# ---------------------------------------------------------------------------


class FILETIME(ctypes.Structure):
    """Estructura FILETIME de Win32 para marcas de tiempo de 64 bits."""

    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]

    def to_datetime(self) -> datetime:
        """Convierte FILETIME (intervalos de 100ns desde 1601-01-01) a datetime UTC."""
        ft = (self.dwHighDateTime << 32) + self.dwLowDateTime
        if ft == 0:
            return datetime.fromtimestamp(0, tz=UTC)
        epoch_100ns = ft - 116444736000000000
        epoch_seconds = epoch_100ns / 10_000_000
        return datetime.fromtimestamp(epoch_seconds, tz=UTC)


class CREDENTIALW(ctypes.Structure):
    """Estructura CREDENTIALW de Win32 para la API de Credential Manager."""

    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
PPCREDENTIALW = ctypes.POINTER(PCREDENTIALW)


DISABLE_ENV_VAR = "AGYSWITCHER_DISABLE_CREDMAN"
"""Si vale '1', AgySwitcher no usa Credential Manager (demos, simulaciones y pruebas)."""


def _get_advapi32() -> Any:
    """Carga y configura los prototipos de función de Advapi32.dll en Windows.

    Raises:
        CredManPlatformError: Fuera de Windows o con AGYSWITCHER_DISABLE_CREDMAN=1.
    """
    if os.environ.get(DISABLE_ENV_VAR, "").strip() == "1":
        raise CredManPlatformError(
            f"Credential Manager deshabilitado por la variable {DISABLE_ENV_VAR}."
        )
    if sys.platform != "win32":
        raise CredManPlatformError(
            "Windows Credential Manager solo está disponible en la plataforma Windows."
        )

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        PPCREDENTIALW,
    ]
    advapi32.CredReadW.restype = wintypes.BOOL

    advapi32.CredWriteW.argtypes = [PCREDENTIALW, wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL

    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL

    advapi32.CredEnumerateW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(PPCREDENTIALW),
    ]
    advapi32.CredEnumerateW.restype = wintypes.BOOL

    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    return advapi32


# ---------------------------------------------------------------------------
# Modelo de datos de credencial
# ---------------------------------------------------------------------------


@dataclass
class CredentialData:
    """Datos de una credencial de Windows Credential Manager."""

    target_name: str
    user_name: str
    blob: bytes
    persist: int = CRED_PERSIST_LOCAL_MACHINE
    last_written: datetime | None = None

    def extract_email(self) -> str | None:
        """Extrae el email de 'id_token_email' del blob JSON de la credencial.

        Devuelve:
            El email si es válido según EMAIL_PATTERN; None si el blob no es JSON,
            no contiene el campo o el formato no es válido.
        """
        if not self.blob:
            return None
        try:
            data = json.loads(self.blob.decode("utf-8"))
            if isinstance(data, dict):
                email = data.get("id_token_email")
                if isinstance(email, str) and is_valid_email(email):
                    return email
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return None

    def is_valid_agy_blob(self) -> bool:
        """Verifica si el blob contiene la estructura JSON esperada de Antigravity.

        Comprueba que sea un JSON que contenga 'id_token_email' válido,
        'auth_method' y el objeto 'token'.
        """
        if not self.blob:
            return False
        try:
            data = json.loads(self.blob.decode("utf-8"))
            if not isinstance(data, dict):
                return False
            email = data.get("id_token_email")
            if not isinstance(email, str) or not is_valid_email(email):
                return False
            return "auth_method" in data and "token" in data
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False


# ---------------------------------------------------------------------------
# Identificadores de target y slot
# ---------------------------------------------------------------------------


def slot_target_name(alias: str) -> str:
    """Devuelve el target en Credential Manager correspondiente al slot de un alias."""
    return f"{SLOT_PREFIX}{alias}"


def is_slot_target(target_name: str) -> bool:
    """Indica si un target corresponde a un slot gestionado por AgySwitcher."""
    return target_name.startswith(SLOT_PREFIX)


def alias_from_slot_target(target_name: str) -> str | None:
    """Extrae el alias de un target de slot; None si no coincide con el prefijo."""
    if is_slot_target(target_name):
        return target_name[len(SLOT_PREFIX) :]
    return None


# ---------------------------------------------------------------------------
# Operaciones Win32 de bajo nivel
# ---------------------------------------------------------------------------


def read_credential(target_name: str) -> CredentialData | None:
    """Lee una credencial genérica de Windows Credential Manager.

    Args:
        target_name: Nombre exacto del target a leer.

    Returns:
        CredentialData si el target existe; None si no existe (ERROR_NOT_FOUND).

    Raises:
        CredManPlatformError: Si se ejecuta en un sistema que no es Windows.
        CredManError: Si se produce un error inesperado de la API Win32.
    """
    advapi32 = _get_advapi32()
    p_cred = PCREDENTIALW()

    ok = advapi32.CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(p_cred))
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise CredManError(
            f"Error al leer '{target_name}' de Credential Manager (Win32 Error: {err})."
        )

    try:
        cred = p_cred.contents
        blob_size = cred.CredentialBlobSize
        raw_bytes = b""
        if blob_size > 0 and cred.CredentialBlob:
            raw_bytes = bytes(
                ctypes.cast(
                    cred.CredentialBlob,
                    ctypes.POINTER(ctypes.c_char * blob_size),
                ).contents
            )

        last_written = cred.LastWritten.to_datetime()
        return CredentialData(
            target_name=cred.TargetName or target_name,
            user_name=cred.UserName or "antigravity",
            blob=raw_bytes,
            persist=cred.Persist,
            last_written=last_written,
        )
    finally:
        advapi32.CredFree(p_cred)


def write_credential(
    target_name: str,
    blob: bytes,
    user_name: str = "antigravity",
    persist: int = CRED_PERSIST_LOCAL_MACHINE,
) -> None:
    """Escribe o actualiza una credencial genérica en Windows Credential Manager.

    Args:
        target_name: Nombre del target a escribir.
        blob: Contenido binario del secreto (JSON en UTF-8).
        user_name: Nombre de usuario asociado (por defecto 'antigravity').
        persist: Nivel de persistencia (por defecto Local Machine).

    Raises:
        CredManPlatformError: Si se ejecuta en un sistema que no es Windows.
        CredManError: Si la llamada Win32 CredWriteW falla.
    """
    advapi32 = _get_advapi32()

    blob_size = len(blob)
    blob_buf = None
    blob_ptr = None
    if blob_size > 0:
        blob_buf = (ctypes.c_byte * blob_size).from_buffer_copy(blob)
        blob_ptr = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))

    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target_name
    cred.Comment = None
    cred.CredentialBlobSize = blob_size
    cred.CredentialBlob = blob_ptr
    cred.Persist = persist
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = user_name

    ok = advapi32.CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        err = ctypes.get_last_error()
        raise CredManError(
            f"Error al escribir '{target_name}' en Credential Manager (Win32 Error: {err})."
        )


def delete_credential(target_name: str) -> bool:
    """Elimina una credencial genérica de Windows Credential Manager.

    Args:
        target_name: Nombre del target a eliminar.

    Returns:
        True si fue eliminada; False si no existía.

    Raises:
        CredManPlatformError: Si se ejecuta en un sistema que no es Windows.
        CredManError: Si la llamada Win32 CredDeleteW falla con un error inesperado.
    """
    advapi32 = _get_advapi32()

    ok = advapi32.CredDeleteW(target_name, CRED_TYPE_GENERIC, 0)
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return False
        raise CredManError(
            f"Error al eliminar '{target_name}' de Credential Manager (Win32 Error: {err})."
        )
    return True


def list_slot_targets() -> list[str]:
    """Lista todos los nombres de targets en Credential Manager que corresponden a slots.

    Returns:
        Lista ordenada de nombres de target que empiezan con SLOT_PREFIX.
    """
    try:
        advapi32 = _get_advapi32()
    except CredManPlatformError:
        return []

    count = wintypes.DWORD(0)
    p_creds = PPCREDENTIALW()

    ok = advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(p_creds))
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return []
        raise CredManError(
            f"Error al enumerar credenciales en Credential Manager (Win32 Error: {err})."
        )

    try:
        targets: list[str] = []
        for i in range(count.value):
            target = p_creds[i].contents.TargetName
            if target and is_slot_target(target):
                targets.append(target)
        targets.sort()
        return targets
    finally:
        advapi32.CredFree(p_creds)


def list_slot_aliases() -> list[str]:
    """Lista los alias de cuentas que tienen un slot registrado en Credential Manager."""
    targets = list_slot_targets()
    aliases = [alias_from_slot_target(t) for t in targets]
    return [a for a in aliases if a is not None]


# ---------------------------------------------------------------------------
# Operaciones de alto nivel sobre slots
# ---------------------------------------------------------------------------


def has_slot(alias: str) -> bool:
    """Indica si existe un slot en Credential Manager para el alias especificado."""
    try:
        return read_credential(slot_target_name(alias)) is not None
    except CredManPlatformError:
        return False


def get_slot_email(alias: str) -> str | None:
    """Devuelve el email asociado al slot del alias; None si no existe o no es válido."""
    try:
        cred = read_credential(slot_target_name(alias))
        return cred.extract_email() if cred else None
    except CredManPlatformError:
        return None


def get_active_email() -> str | None:
    """Devuelve el email asociado a la credencial activa actual de agy ('gemini:antigravity')."""
    try:
        cred = read_credential(ACTIVE_TARGET)
        return cred.extract_email() if cred else None
    except CredManPlatformError:
        return None


def save_slot_from_active(alias: str, expected_email: str | None = None) -> str:
    """Copia la sesión activa de 'gemini:antigravity' al slot 'gemini:antigravity:slot:<alias>'.

    Args:
        alias: Alias de la cuenta que recibirá la copia de la sesión actual.
        expected_email: Si se proporciona, valida que la sesión pertenezca a este email.

    Returns:
        El email verificado de la sesión guardada en el slot.

    Raises:
        CredManNotFoundError: Si 'gemini:antigravity' no existe en el almacén.
        CredManCorruptError: Si el blob de la sesión no tiene la estructura de Antigravity.
        CredManEmailMismatchError: Si el email activo no coincide con expected_email.
    """
    active_cred = read_credential(ACTIVE_TARGET)
    if active_cred is None:
        raise CredManNotFoundError(
            f"No existe la credencial activa '{ACTIVE_TARGET}' en Windows Credential Manager."
        )

    if not active_cred.is_valid_agy_blob():
        raise CredManCorruptError(
            f"La credencial activa '{ACTIVE_TARGET}' no tiene un formato válido de Antigravity."
        )

    active_email = active_cred.extract_email()
    if not active_email:
        raise CredManCorruptError(
            f"No se pudo extraer un correo electrónico válido de '{ACTIVE_TARGET}'."
        )

    if expected_email and active_email.lower() != expected_email.lower():
        raise CredManEmailMismatchError(
            f"La sesión activa pertenece a '{active_email}', pero se esperaba '{expected_email}'."
        )

    target = slot_target_name(alias)
    write_credential(
        target_name=target,
        blob=active_cred.blob,
        user_name=active_cred.user_name,
        persist=active_cred.persist,
    )
    return active_email


@dataclass(frozen=True)
class SlotCapture:
    """Resultado de 'capture_active_slot' cuando se ha escrito un slot."""

    alias: str
    """Alias de la cuenta cuyo slot se ha escrito."""
    email: str
    """Email de la sesión guardada."""
    created: bool
    """True si la cuenta no tenía slot; False si se ha actualizado uno existente."""


def find_alias_for_email(email: str, emails_by_alias: Mapping[str, str | None]) -> str | None:
    """Devuelve el único alias cuyo email coincide (sin distinguir mayúsculas), o None.

    Si varias cuentas comparten el email, devuelve None: no se puede saber de cuál es la sesión.
    """
    wanted = email.strip().lower()
    matches = [
        alias
        for alias, acc_email in emails_by_alias.items()
        if acc_email and acc_email.strip().lower() == wanted
    ]
    return matches[0] if len(matches) == 1 else None


def capture_active_slot(emails_by_alias: Mapping[str, str | None]) -> SlotCapture | None:
    """Guarda la sesión activa de agy en el slot de la cuenta registrada a la que pertenece.

    Un inicio de sesión hecho directamente en agy (``/logout`` + ``/login``) no pasa por el
    cambio guiado, así que su slot no se crea en ese momento. Esta función lo crea (o lo
    actualiza con el token más reciente) en cuanto AgySwitcher ve la sesión. El dueño se
    determina por el email de la propia credencial, no por la cuenta activa del estado, para
    que un slot solo contenga la sesión de su cuenta.

    Args:
        emails_by_alias: Email registrado de cada alias.

    Returns:
        Un SlotCapture si se ha escrito el slot; None si no hay sesión válida, no pertenece a
        una única cuenta registrada, el slot ya era idéntico o no hay Credential Manager.

    Raises:
        CredManError: Si falla una llamada Win32 de lectura o escritura.
    """
    try:
        active = read_credential(ACTIVE_TARGET)
    except CredManPlatformError:
        return None
    if active is None or not active.is_valid_agy_blob():
        return None
    email = active.extract_email()
    if not email:
        return None
    alias = find_alias_for_email(email, emails_by_alias)
    if alias is None:
        return None

    target = slot_target_name(alias)
    current = read_credential(target)
    if current is not None and current.blob == active.blob:
        return None
    write_credential(
        target_name=target,
        blob=active.blob,
        user_name=active.user_name,
        persist=active.persist,
    )
    return SlotCapture(alias=alias, email=email, created=current is None)


def promote_slot_to_active(alias: str, expected_email: str) -> str:
    """Promueve el slot 'gemini:antigravity:slot:<alias>' a la credencial activa 'gemini:antigravity'.

    No guarda la sesión saliente: quien llama debe hacerlo antes con 'capture_active_slot', que
    la guarda en el slot de su dueño real (por su email) y no en el de la cuenta que el estado
    cree activa. Tras escribir, relee la credencial activa y comprueba su email.

    Args:
        alias: Alias de la cuenta cuyo slot se activará.
        expected_email: Email registrado de la cuenta; el slot debe pertenecer a él.

    Returns:
        El email verificado de la cuenta que ha quedado activa.

    Raises:
        CredManEmailMismatchError: Si falta expected_email o el slot es de otro email.
        CredManNotFoundError: Si el slot solicitado no existe.
        CredManCorruptError: Si el blob del slot está corrupto o incompleto.
        CredManError: Si la relectura no confirma la escritura o falla una llamada Win32.
    """
    if not expected_email or not expected_email.strip():
        raise CredManEmailMismatchError(
            f"La cuenta '{alias}' no tiene email registrado: no se puede comprobar su slot."
        )

    slot_target = slot_target_name(alias)
    slot_cred = read_credential(slot_target)
    if slot_cred is None:
        raise CredManNotFoundError(
            f"No existe el slot '{alias}' ({slot_target}) en Windows Credential Manager."
        )

    if not slot_cred.is_valid_agy_blob():
        raise CredManCorruptError(
            f"El slot '{alias}' no contiene datos válidos de sesión de Antigravity."
        )

    slot_email = slot_cred.extract_email()
    if not slot_email:
        raise CredManCorruptError(
            f"No se pudo extraer un correo electrónico válido del slot '{alias}'."
        )

    if slot_email.lower() != expected_email.strip().lower():
        raise CredManEmailMismatchError(
            f"El slot '{alias}' pertenece a '{slot_email}', pero se esperaba '{expected_email}'."
        )

    write_credential(
        target_name=ACTIVE_TARGET,
        blob=slot_cred.blob,
        user_name=slot_cred.user_name,
        persist=slot_cred.persist,
    )

    written = read_credential(ACTIVE_TARGET)
    if written is None or written.blob != slot_cred.blob:
        raise CredManError(
            f"No se pudo confirmar la sesión de '{alias}' en '{ACTIVE_TARGET}' tras escribirla "
            "(¿otro programa la ha cambiado a la vez?)."
        )
    return slot_email


def list_orphan_slots(known_aliases: Iterable[str]) -> list[str]:
    """Alias con slot en Credential Manager que no corresponden a ninguna cuenta registrada."""
    known = set(known_aliases)
    return [alias for alias in list_slot_aliases() if alias not in known]


SLOT_OK = "ok"
SLOT_ORPHAN = "orphan"
SLOT_MISMATCH = "mismatch"


@dataclass(frozen=True)
class SlotInfo:
    """Metadatos de un slot (nunca su contenido secreto)."""

    alias: str
    email: str | None
    """Email de la sesión del slot; None si el slot no es legible."""
    status: str
    """SLOT_OK, SLOT_ORPHAN (alias sin cuenta) o SLOT_MISMATCH (no es de la cuenta)."""


def list_slots(emails_by_alias: Mapping[str, str | None]) -> list[SlotInfo]:
    """Inventario de los slots con su email y si corresponden a su cuenta registrada.

    Un slot es huérfano si su alias no está registrado, y no coincidente si la cuenta no
    tiene email, el slot no es legible o su email es otro (no debe promoverse nunca).

    Returns:
        Lista ordenada por alias; vacía si no hay Credential Manager.

    Raises:
        CredManError: Si falla una llamada Win32.
    """
    infos: list[SlotInfo] = []
    for alias in list_slot_aliases():
        try:
            cred = read_credential(slot_target_name(alias))
        except CredManPlatformError:
            return []
        email = cred.extract_email() if cred and cred.is_valid_agy_blob() else None
        if alias not in emails_by_alias:
            status = SLOT_ORPHAN
        else:
            account_email = emails_by_alias[alias]
            same = bool(email and account_email and email.lower() == account_email.lower())
            status = SLOT_OK if same else SLOT_MISMATCH
        infos.append(SlotInfo(alias=alias, email=email, status=status))
    return infos


def is_available() -> bool:
    """Indica si el Administrador de credenciales de Windows se puede usar en este sistema."""
    try:
        _get_advapi32()
    except CredManPlatformError:
        return False
    return True


def delete_slot(alias: str) -> bool:
    """Elimina el slot de una cuenta de Windows Credential Manager.

    Returns:
        True si el slot existía y fue eliminado; False si no existía.
    """
    return delete_credential(slot_target_name(alias))
