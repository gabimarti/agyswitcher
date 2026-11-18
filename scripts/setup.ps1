# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
# scripts/setup.ps1
# Proposito  : Prepara el entorno de trabajo para ejecutar AgySwitcher.
#              Crea el entorno virtual Python (.venv), instala el paquete
#              y sus dependencias, y muestra el comando de activacion.
# Uso        : .\scripts\setup.ps1           (desde la raiz del repositorio)
#              .\scripts\setup.ps1 -Rebuild  (elimina y recrea el .venv)
# Requisitos : Python 3.11+ instalado y accesible en el PATH.
# Idempotente: Si, salvo con -Rebuild.
# Creado     : 2026-11-06

param(
    [switch]$Rebuild   # Si se pasa, borra el .venv antes de recrearlo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Ruta del repositorio (el script esta en scripts/, un nivel dentro de la raiz)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".venv"

Write-Host ""
Write-Host "=== AgySwitcher - Setup del entorno ===" -ForegroundColor Cyan
Write-Host ""

# Verificar que Python esta disponible
try {
    $PythonVersion = & python --version 2>&1
    Write-Host "Python encontrado: $PythonVersion" -ForegroundColor Green
} catch {
    Write-Error "Python no encontrado. Instala Python 3.11 o superior y asegurate de que este en el PATH."
    exit 1
}

# Eliminar el entorno si se pide reconstruir
if ($Rebuild -and (Test-Path $VenvPath)) {
    Write-Host "Eliminando entorno virtual existente..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VenvPath
}

# Crear el entorno virtual si no existe
if (-not (Test-Path $VenvPath)) {
    Write-Host "Creando entorno virtual en .venv ..." -ForegroundColor Cyan
    & python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Error al crear el entorno virtual."
        exit $LASTEXITCODE
    }
    Write-Host "Entorno virtual creado." -ForegroundColor Green
} else {
    Write-Host ".venv ya existe, omitiendo creacion." -ForegroundColor Gray
}

# Rutas de pip y python del entorno virtual
$PipExe    = Join-Path $VenvPath "Scripts\pip.exe"
$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"

Write-Host "Actualizando pip..." -ForegroundColor Cyan
& $PipExe install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Instalando AgySwitcher y dependencias..." -ForegroundColor Cyan
& $PipExe install -e "." --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Error al instalar las dependencias."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host " Entorno listo. Para activarlo ejecuta:" -ForegroundColor Green
Write-Host ""
Write-Host "   .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""
Write-Host " Despues ya puedes usar:" -ForegroundColor Green
Write-Host ""
Write-Host "   agyswitcher --help" -ForegroundColor White
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host ""
