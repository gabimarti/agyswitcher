# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Gabriel Marti
# packaging/build.ps1
# Proposito  : Compila el ejecutable de AgySwitcher (PyInstaller, modo carpeta), el ZIP portable,
#              el instalador (Inno Setup) y el fichero SHA256SUMS.txt en dist/.
# Uso        : .\packaging\build.ps1                         (compilacion local, numero 0)
#              .\packaging\build.ps1 -BuildNumber 45
#              .\packaging\build.ps1 -SkipInstaller           (solo exe y ZIP)
#              .\packaging\build.ps1 -Python python -Iscc "C:\...\ISCC.exe"
# Requisitos : Python con AgySwitcher y PyInstaller instalados (pip install -e ".[build]");
#              Inno Setup 6 para el instalador.
# Notas      : El numero de compilacion se escribe temporalmente en src/agyswitcher/_build.py y se
#              restaura siempre al terminar.

param(
    [int]$BuildNumber = 0,
    [string]$Python = "",
    [string]$Iscc = "",
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $Root "dist"
# Ficheros intermedios fuera del repositorio: las carpetas sincronizadas (OneDrive, Google
# Drive...) bloquean ficheros mientras los suben y PyInstaller no podría limpiarlos.
$Work = Join-Path ([IO.Path]::GetTempPath()) "agyswitcher-build"
$BuildPy = Join-Path $Root "src\agyswitcher\_build.py"

function Write-Step([string]$Text) { Write-Host "=== $Text ===" -ForegroundColor Cyan }

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

if (-not $Python) {
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
    $Python = if (Test-Path $venvPy) { $venvPy } else { "python" }
}

$Version = (& $Python -c "import agyswitcher; print(agyswitcher.__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "No se pudo leer la version de agyswitcher." }
Write-Step "AgySwitcher $Version (compilacion $BuildNumber)"

if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
New-Item -ItemType Directory -Force $Dist, $Work | Out-Null

$OriginalBuild = [IO.File]::ReadAllText($BuildPy)
try {
    $content = $OriginalBuild -replace "BUILD_NUMBER: int \| None = None", "BUILD_NUMBER: int | None = $BuildNumber"
    if ($content -eq $OriginalBuild) { throw "No se encontro BUILD_NUMBER en _build.py." }
    [IO.File]::WriteAllText($BuildPy, $content, [Text.UTF8Encoding]::new($false))

    Write-Step "Recurso de version"
    $VersionInfo = Join-Path $Work "version_info.txt"
    Invoke-Checked $Python @((Join-Path $PSScriptRoot "make_version_info.py"), "$BuildNumber", $VersionInfo)

    Write-Step "PyInstaller"
    Invoke-Checked $Python @(
        "-m", "PyInstaller", (Join-Path $PSScriptRoot "entry.py"),
        "--name", "agyswitcher", "--onedir", "--console", "--noconfirm", "--clean",
        "--paths", (Join-Path $Root "src"),
        "--collect-submodules", "rich",
        "--python-option", "X utf8",
        "--version-file", $VersionInfo,
        "--distpath", $Dist, "--workpath", (Join-Path $Work "pyinstaller"), "--specpath", $Work
    )
}
finally {
    [IO.File]::WriteAllText($BuildPy, $OriginalBuild, [Text.UTF8Encoding]::new($false))
}

$AppDir = Join-Path $Dist "agyswitcher"
$Exe = Join-Path $AppDir "agyswitcher.exe"

Write-Step "Prueba de humo"
$smokeHome = Join-Path $Work "smoke-home"
if (Test-Path $smokeHome) { Remove-Item $smokeHome -Recurse -Force }
$env:AGYSWITCHER_HOME = $smokeHome
try {
    $out = (& $Exe --version) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $out -notmatch [regex]::Escape("$Version (compilaci")) {
        throw "--version inesperado: $out"
    }
    Write-Host "  $out"
    # La salida redirigida debe ser UTF-8 (modo UTF-8 de Python): 'ó' = C3 B3.
    $raw = Join-Path $Work "smoke-version.txt"
    cmd /c "`"$Exe`" --version > `"$raw`""
    $hex = ([IO.File]::ReadAllBytes($raw) | ForEach-Object { '{0:x2}' -f $_ }) -join ' '
    if ($hex -notmatch "c3 b3") { throw "La salida redirigida no es UTF-8: $hex" }
    & $Exe --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "--help ha fallado" }
    & $Exe list --cached | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "list --cached ha fallado" }
    $demo = Join-Path $Work "smoke-project"
    if (Test-Path $demo) { Remove-Item $demo -Recurse -Force }
    New-Item -ItemType Directory $demo | Out-Null
    & $Exe init $demo --dry-run | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "init --dry-run ha fallado" }
}
finally {
    Remove-Item Env:\AGYSWITCHER_HOME -ErrorAction SilentlyContinue
}

Write-Step "Documentacion"
# README, licencia, cambios y docs/ (manual y tutoriales) dentro de la carpeta del programa:
# los usan tanto el ZIP portable como el instalador, y los enlaces del README funcionan.
Copy-Item (Join-Path $Root "README.md"), (Join-Path $Root "LICENSE"), (Join-Path $Root "CHANGELOG.md") $AppDir
Copy-Item (Join-Path $Root "docs") (Join-Path $AppDir "docs") -Recurse

Write-Step "ZIP portable"
# Con Python (zipfile) y no con Compress-Archive: PowerShell 5.1 guarda las rutas internas con
# '\', fuera del estándar ZIP, y otras herramientas no recrean bien las carpetas.
$ZipBase = Join-Path $Dist "AgySwitcher-$Version-portable"
Invoke-Checked $Python @("-c", "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'agyswitcher')", $ZipBase, $Dist)

if (-not $SkipInstaller) {
    Write-Step "Instalador (Inno Setup)"
    if (-not $Iscc) {
        $candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        )
        $Iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $Iscc) { throw "No se encontro ISCC.exe (Inno Setup 6). Usa -Iscc o -SkipInstaller." }
    }
    $parts = ($Version -split '[^0-9]+')[0..2]
    $FileVersion = "$($parts -join '.').$BuildNumber"
    Invoke-Checked $Iscc @(
        "/Q",
        "/DAppVersion=$Version", "/DFileVersion=$FileVersion",
        "/DSourceDir=$AppDir", "/DRepoRoot=$Root", "/DOutputDir=$Dist",
        (Join-Path $PSScriptRoot "agyswitcher.iss")
    )
}

Write-Step "SHA-256"
$Sums = Join-Path $Dist "SHA256SUMS.txt"
Get-ChildItem $Dist -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content $Sums -Encoding ascii
Get-Content $Sums
Write-Host "`nResultado en: $Dist" -ForegroundColor Green
