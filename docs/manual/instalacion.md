# Instalación

## Requisitos

- Windows 10 u 11.
- **Antigravity CLI (`agy`)** instalado y accesible desde la consola (`agy --help` debe
  funcionar en PowerShell o en Windows Terminal).
- Al menos una cuenta de Google con la que hayas iniciado sesión en `agy`.

## Opción A — Instalador para Windows (recomendada)

No necesitas Python ni el código fuente, ni permisos de administrador.

1. Descarga `AgySwitcher-<versión>-setup.exe` de la página de
   [*Releases*](https://github.com/gabimarti/agyswitcher/releases) del repositorio.
2. *(Recomendado)* Comprueba que el fichero no se ha alterado: compara su huella con la de
   `SHA256SUMS.txt`, publicado en la misma página.

   ```powershell
   Get-FileHash .\AgySwitcher-1.0.0-setup.exe -Algorithm SHA256
   ```

3. Ejecuta el instalador. Como el ejecutable aún no está firmado digitalmente, Windows
   puede mostrar **«Windows protegió su PC»** (SmartScreen): pulsa **Más información** y
   después **Ejecutar de todas formas**.
4. Acepta la licencia (GPL v3) y termina el asistente.
5. Abre una consola **nueva** (PowerShell o Windows Terminal) y comprueba:

   ```powershell
   agyswitcher --version
   ```

El instalador:

- instala AgySwitcher solo para tu usuario en `%LOCALAPPDATA%\Programs\AgySwitcher`;
- añade esa carpeta al `PATH` de tu usuario (por eso hace falta una consola nueva);
- copia el manual y los tutoriales en la carpeta `docs` de la instalación y crea accesos en
  el menú Inicio (*AgySwitcher*);
- registra un desinstalador en *Configuración → Aplicaciones*.

### Versión portable (ZIP)

Si prefieres no instalar nada, descarga `AgySwitcher-<versión>-portable.zip`, descomprímelo
donde quieras y ejecuta `agyswitcher.exe` desde esa carpeta (o añádela tú al `PATH`).

### Actualizar

Descarga e instala la versión nueva encima de la anterior: se conservan tus cuentas y tu
configuración (están en `%USERPROFILE%\.agyswitcher`, fuera de la carpeta de instalación).

## Opción B — Desde el código fuente

Para quien quiera usar la última versión del código o colaborar en el desarrollo.

Requisitos adicionales: **Python 3.11 o superior** y **Git**.

### Con el script de instalación

```powershell
git clone https://github.com/gabimarti/agyswitcher.git
cd agyswitcher
.\scripts\setup.ps1          # crea .venv e instala AgySwitcher y sus dependencias
.\.venv\Scripts\Activate.ps1 # activa el entorno en esta consola
agyswitcher --version
```

`.\scripts\setup.ps1 -Rebuild` borra el entorno virtual y lo crea de nuevo (útil si se ha
dañado o tras cambiar de versión de Python).

### Manual

```powershell
git clone https://github.com/gabimarti/agyswitcher.git
cd agyswitcher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Con el código fuente, cada vez que abras una consola nueva tendrás que activar el entorno
(`.\.venv\Scripts\Activate.ps1`) antes de usar `agyswitcher`, o llamarlo con su ruta
completa (`C:\ruta\agyswitcher\.venv\Scripts\agyswitcher.exe`).

### Actualizar

```powershell
cd C:\ruta\agyswitcher
git pull
.\scripts\setup.ps1
```

### Para desarrollo

```powershell
python -m pip install -e ".[dev]"   # pytest, ruff y mypy
pytest
```

### Vista previa de la web

```powershell
python -m pip install -e ".[docs]"
mkdocs serve      # http://127.0.0.1:8000
```

### Compilar el ejecutable y el instalador

Requiere PyInstaller (`python -m pip install -e ".[build]"`) e
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (por ejemplo,
`winget install JRSoftware.InnoSetup`).

```powershell
.\packaging\build.ps1                 # compilación local (número de compilación 0)
.\packaging\build.ps1 -SkipInstaller  # solo el ejecutable y el ZIP
```

El resultado queda en `dist\`: la carpeta del ejecutable, el ZIP portable, el instalador y
`SHA256SUMS.txt`. Las versiones oficiales las compila GitHub Actions al publicar una
etiqueta `vX.Y.Z`, con el número de ejecución como número de compilación.

## Primer arranque

AgySwitcher guarda sus datos en `%USERPROFILE%\.agyswitcher\` (`config.json` con tus
cuentas y `state.json` con la cuenta activa, las cuotas y el historial). Se crea sola la
primera vez. Si defines la variable de entorno `AGYSWITCHER_HOME`, se usa esa carpeta en su
lugar.

Siguiente paso: lee los [conceptos](conceptos.md) y registra tus cuentas con
[`add`](comandos.md#add).
