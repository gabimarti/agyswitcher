# Arquitectura Técnica — AgySwitcher

**Versión:** 0.1 (Borrador inicial — Fase 1)  
**Fecha:** 2026-11-03  
**Estado:** Documento de diseño, sin implementación de código aún.

---

## 1. Propósito y Principios de Diseño

**AgySwitcher** es un orquestador externo, seguro y nativo para Windows que envuelve
Antigravity CLI (`agy`) para gestionar múltiples cuentas de Google y reaccionar ante
el agotamiento de cuota (rate limit) de forma transparente para el usuario.

### Principios rectores

| Principio | Descripción |
| :--- | :--- |
| **No invasivo** | No modifica los archivos internos de `agy`, ni accede, descifra ni exporta tokens OAuth. |
| **Windows nativo** | Usa `pathlib.Path`, `shutil.which` y APIs de consola de Windows en lugar de construcciones POSIX. |
| **Seguro por diseño** | Cualquier dato proveniente de procesos hijos (`agy`) se trata como no confiable. Los patrones sensibles se redactan antes de cualquier log. |
| **Transparente** | El usuario siempre sabe qué cuenta está activa. Las rotaciones automáticas se notifican explícitamente; las manuales requieren confirmación. |
| **Sin privilegios especiales** | No requiere ejecución como Administrador ni modo Developer de Windows para sus operaciones núcleo. |

---

## 2. Visión General del Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                   USUARIO (PowerShell / Windows Terminal)    │
└──────────────────────────────┬──────────────────────────────┘
                               │  agyswitcher run / watch
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               AGYSWITCHER ORCHESTRATOR (CLI Python)          │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Cuentas      │  │   Runner     │  │  Quota Detector   │  │
│  │ (add/list/   │  │  (run/watch) │  │  + Rotator +      │  │
│  │  status)     │  │              │  │  Session (rotate) │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬──────────┘  │
│         │                 │                   │              │
│  ┌──────▼─────────────────▼───────────────────▼───────────┐ │
│  │             State Manager                               │ │
│  │  %USERPROFILE%\.agyswitcher\config.json                 │ │
│  │  %USERPROFILE%\.agyswitcher\state.json                  │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │  subprocess (agy.exe)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                        AGY.EXE                               │
│    C:\Users\<User>\AppData\Local\agy\bin\agy.exe             │
│    Lee configuración de: %USERPROFILE%\.gemini\              │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTPS / gRPC
                           ▼
                    [ Gemini API / Google ]
```

---

## 3. Cuentas, sesión de `agy` y cambio de cuenta

### 3.1 Hallazgos empíricos

1. **`agy.exe`** lee su configuración, historial, conversaciones, MCP y *skills* de
   `%USERPROFILE%\.gemini\` (subcarpetas `antigravity-cli`, `antigravity`, `config`,
   `skills`...). El IDE de Antigravity comparte esa carpeta.
2. **La sesión de Google no está en `%USERPROFILE%\.gemini`** (verificado el 2026-11-18).
   `agy` guarda **una única sesión** en el Administrador de credenciales de Windows, en una
   entrada de nombre fijo. La cuenta solo cambia cuando el usuario cierra sesión
   (`/logout`) e inicia sesión con otra cuenta en el navegador. AgySwitcher no lee, copia
   ni modifica esa entrada.
3. Al completar un inicio de sesión (y también al arrancar con la sesión guardada), `agy`
   escribe en sus logs `OAuth: authenticated successfully as <email>`. Es la señal usada
   para verificar un cambio de cuenta (§3.3).
4. La detección de cuota se realiza leyendo `%USERPROFILE%\.gemini\antigravity-cli\cli.log`
   y los logs rotados de `antigravity-cli\log\`, además de la salida de `agy` en `run`.

### 3.2 Decisión de diseño: carpeta `.gemini` única y compartida

`%USERPROFILE%\.gemini` es **común a todas las cuentas** y AgySwitcher **no la modifica**.
Así, al cambiar de cuenta cuando la actual agota su cuota, se conservan historial,
conversaciones, servidores MCP y *skills*, y se puede continuar el mismo proyecto.

> [!NOTE]
> Hasta el 2026-11-18 AgySwitcher mantenía un perfil por cuenta y conmutaba `.gemini`
> mediante NTFS Directory Junctions. Se abandonó porque no cambiaba la cuenta de Google
> (hallazgo 2) y separaba justo lo que interesa compartir. Se eliminaron `migrate`, el
> intercambio de junctions y la siembra de perfiles.

### 3.3 Ciclo de vida de un cambio de cuenta (cambio guiado)

`rotate <alias>` / `set-active <alias>` cuando cambia la cuenta (`_guided_account_switch`
en `cli.py`):

```
1. La cuenta destino debe tener email registrado (si no, no hay forma de verificar)
2. Aviso si hay procesos agy.exe / Antigravity*.exe: seguirán con la cuenta anterior
   hasta que se reinicien (find_running_agy_processes)
3. offsets = snapshot_log_offsets()     (marca de los logs actuales)
4. Instrucciones: en agy, /logout e iniciar sesión con <email destino>
5. wait_for_login(email, offsets, timeout)   (sondeo cada 2 s; avisa de otras cuentas)
   - VERIFIED            -> record_rotation(): state.json + historial
   - TIMEOUT / CANCELLED -> state.json intacto; si se detectó otra sesión, sugerir `sync`
```

La verificación (`session.py`) busca el evento de inicio de sesión **solo en el contenido
escrito después de la marca** (`detect_new_login_email`): un inicio de sesión antiguo no
cuenta y las líneas a medio escribir no se evalúan.

Un cambio de **pool** dentro de la misma cuenta no requiere sesión y se registra
directamente (`record_rotation`).

### 3.4 Continuidad del proyecto (`project.py`)

El contexto que debe sobrevivir a un cambio de cuenta o de agente vive **en el propio
proyecto**, no en `agy`:

- `agyswitcher init` crea `AGENTS.md` (reglas comunes y protocolo de memoria), los ficheros
  de cada agente que remiten a él (`GEMINI.md`, `CLAUDE.md`, Copilot, Cursor),
  `dev_mem/ESTADO.md`, `dev_mem/TODO.md` y `.agyswitcher.toml`. Escribe con `open("x")`:
  nunca sobrescribe. Con `--merge`, a los ficheros existentes les añade al final el bloque
  que les falte (sección de memoria en `AGENTS.md`; aviso que remite a `AGENTS.md` en los de
  cada agente, con `@AGENTS.md` en `CLAUDE.md`), marcado con `<!-- agyswitcher:... -->`;
  no lo repite si ya está (por marca o por contenido), respeta CRLF/LF y rechaza ficheros
  que no estén en UTF-8.
- `agyswitcher handoff [save|resume]` muestra las instrucciones de traspaso, leídas de
  `.agyswitcher.toml` (búsqueda hacia arriba desde la carpeta actual; `tomllib`) o las de
  por defecto si no existe o está mal formado.
- `LOW_QUOTA_PERCENT` (15 %): `list`, `status` y `run` avisan para guardar el estado a
  tiempo y proponen la siguiente cuenta.

### 3.5 Atribución de cuota

Como solo hay una sesión, `agy -p /usage` siempre informa de la cuota **de la cuenta con
sesión iniciada**. AgySwitcher guarda ese informe en la cuenta cuyo email coincide con el
del informe (`_report_owner`), aunque no sea la activa; `add` solo consulta la cuota si la
sesión es de la cuenta que se registra, y `list --refresh-all` no puede recorrer cuentas
(equivale a `--live`).

---

## 4. Esquema de Datos Locales

Los datos de AgySwitcher viven en `%USERPROFILE%\.agyswitcher\` (`config.app_home_dir`).
La variable de entorno `AGYSWITCHER_HOME` sustituye esa carpeta (pruebas, demostraciones
con cuentas ficticias). Los tests la eliminan del entorno para no salir del HOME aislado.

### `config.json` — Configuración persistente

```jsonc
{
  "version": 1,
  "live_dir": "C:\\Users\\<User>\\.gemini",
  "switch_policy": {
    "mode": "guided",                        // cambio de cuenta siempre guiado
    "candidate_strategy": "balanced",        // "balanced" | "round-robin" | "manual"
    "quota_reset_hours": 24,
    "short_usage_threshold_percent": 10,
    "refresh_failure_threshold": 2
  },
  "log_watch": {
    "log_dir": "C:\\Users\\<User>\\.gemini\\antigravity-cli\\log",
    "primary_log": "C:\\Users\\<User>\\.gemini\\antigravity-cli\\cli.log"
  }
}
```

### `state.json` — Estado de ejecución

```jsonc
{
  "active": "cuenta-personal",              // alias de la cuenta activa, o null
  "accounts": {
    "cuenta-personal": {
      "alias": "cuenta-personal",
      "email": "personal@example.com",
      "status": "active",                   // "active" | "cooldown" | "exhausted" | "unknown"
      "last_used_at": "2026-11-03T17:00:00Z",
      "quota_reset_at": null,               // estimación de reinicio de cuota
      "refresh_failure_count": 0
    }
  },
  "switch_history": [],                     // lista de eventos de cambio de cuenta
  "log_watch_cursors": {}                   // offset por archivo de log (no datos sensibles)
}
```

---

## 5. Módulo Runner y Subprocesos (`run`)

### 5.1 Resolución del ejecutable `agy` en Windows

```python
import shutil

def find_agy_executable() -> Path:
    """Localiza agy.exe en el PATH del sistema."""
    exe = shutil.which("agy")
    if exe is None:
        raise FileNotFoundError(
            "No se encontró agy.exe en el PATH. "
            "Verifica que Antigravity CLI esté instalado."
        )
    return Path(exe)
```

`agy` en Windows es un **binario nativo** (`agy.exe`, no `.cmd`):
`C:\Users\<User>\AppData\Local\agy\bin\agy.exe` (v1.4.12 confirmado en este sistema).

> [!NOTE]
> No se requiere `shell=True`. `shutil.which("agy")` resuelve correctamente
> `agy.exe` en Windows respetando `PATHEXT`. El uso de `shell=True` está
> **prohibido** salvo necesidad justificada documentada (ver `AGENTS.md`).

### 5.2 Streaming de salida y sanitización

El Runner captura `stdout` y `stderr` de `agy.exe` mediante un hilo lector
dedicado para permitir streaming en tiempo real **sin bloquear el bucle principal**,
y aplica sanitización antes de cualquier escritura en log:

```
agy.exe stdout/stderr
    │
    ▼ (hilo lector)
SanitizingReader
    ├── Redacta patrones: token=, authorization:, cookie:, refresh_token=, access_token=
    ├── Pasa al ConsoleOutput (reenvía al terminal del usuario tal cual)
    └── Escribe en log (solo líneas sanitizadas)
    │
    ▼
QuotaDetector.feed(line)   ← analiza cada línea en busca de señales de cuota agotada
```

### 5.3 Señales y terminación limpia en Windows

Windows no soporta `os.killpg()`. La terminación del árbol de procesos hijo se
gestiona así:

```python
import subprocess, os, signal

# Enviar Ctrl+C al grupo de consola del proceso hijo
proc.send_signal(signal.CTRL_C_EVENT)

# Si no termina en timeout → forzar cierre del árbol completo
subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], check=False)
```

Los subprocesos `agy` se crean con `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`
para permitir el envío de `CTRL_C_EVENT` / `CTRL_BREAK_EVENT` de forma aislada.

Las consultas no interactivas (`agy -p /usage`, `agy models`) usan `runner.run_captured`
en lugar de `subprocess.run(..., timeout=...)`. En Windows, si el proceso deja nietos que
heredan las tuberías, `subprocess.run` se bloquea indefinidamente tras el timeout porque
espera el fin de la salida. `run_captured` conecta `stdin` a `DEVNULL`, termina el árbol
con `taskkill /T /F` al expirar el tiempo y acota también la espera posterior.

---

## 6. Detector de Cuota y Motor de Rotación

### 6.1 Fuentes de señal de cuota agotada

AgySwitcher detecta el agotamiento de cuota por dos vías complementarias:

**Vía A — Streaming de stdout/stderr de `agy`** (tiempo real):
- Patrones de texto en la salida de `agy` indicativos de rate limit o cuota agotada.
- Ejemplos de patrones a detectar (sin comprometer la seguridad del log):
  - `"429"` / `"RESOURCE_EXHAUSTED"` / `"quota"` / `"rate limit"` / `"too many requests"`

**Vía B — Log file watch** (modo `watch`):
- Lectura incremental de los archivos de log de `agy` en
  `%USERPROFILE%\.gemini\antigravity-cli\log\cli-<timestamp>.log`,
  con seguimiento de offset por archivo (`log-watch.json`).
- Permite detectar errores en sesiones `agy` lanzadas externamente (sin pasar por AgySwitcher).

### 6.2 Algoritmo de rotación — Standby Pool

```
Cuentas registradas: [A (activa), B (standby), C (standby)]

Evento: cuota agotada en cuenta A
  │
  ▼
Selección de candidato (política "balanced"):
  ├── Filtrar: excluir cuentas en estado "exhausted" o "cooldown" vigente
  ├── Ordenar por: quota_reset_at ASC (las con cuota disponible más antes, primero)
  └── Seleccionar: B (mejor candidata)
  │
  ▼
Cambio:
  ├── Registrar A con: cuota agotada en el pool afectado
  ├── Si A tiene el otro pool libre -> cambio de pool (sin sesión)
  └── Si no -> proponer B con su email: "agyswitcher set-active B"
                (cambio guiado, §3.3: requiere que el usuario inicie sesión)
```

### 6.3 Estimación del reinicio de cuota

La política de cuota de Gemini / Antigravity es de 24 horas desde el primer uso
del período. `quota_reset_at` se estima como:

```
quota_reset_at = last_used_at + 24h
```

Este valor es una **estimación local**, no un dato autoritativo de la API de Google.
Se actualiza si se detecta que la cuenta vuelve a funcionar antes de ese tiempo.

---

## 7. Interfaz de Línea de Comandos (CLI)

### Comandos planificados

| Comando | Descripción |
| :--- | :--- |
| `agyswitcher add <alias>` | Registra una cuenta con su email (detectado de la sesión de `agy` o con `--email`). |
| `agyswitcher list` | Lista las cuentas con su cuota, reinicio y disponibilidad. |
| `agyswitcher status` | Estado detallado de la cuenta activa, pools e historial reciente. |
| `agyswitcher run [-- agy args]` | Lanza `agy` con streaming sanitizado y detección de cuota. |
| `agyswitcher rotate [<alias>]` | Cambia de pool o, mediante el cambio guiado, a la siguiente cuenta (o al alias indicado). |
| `agyswitcher set-active <alias>` | Cambio guiado a la cuenta indicada. |
| `agyswitcher sync` | Alinea la cuenta activa con la sesión real de `agy`. |
| `agyswitcher watch` | Monitorea los logs de `agy`; cambia de pool o propone la siguiente cuenta al agotarse la cuota. |

### Ejemplo de flujo de uso

```powershell
# Registrar dos cuentas
agyswitcher add personal --email personal@example.com
agyswitcher add trabajo --email trabajo@example.com --no-activate

# Ver el estado
agyswitcher list
# ┌─────────────┬──────────┬───────────────────────┐
# │ Alias       │ Estado   │ Reset estimado cuota   │
# ├─────────────┼──────────┼───────────────────────┤
# │ personal ★  │ activa   │ -                      │
# │ trabajo     │ standby  │ -                      │
# └─────────────┴──────────┴───────────────────────┘

# Lanzar agy con detección de cuota
agyswitcher run -- --model "claude-sonnet" -p "Hola"

# Si se agota la cuota → AgySwitcher propone "trabajo"; el cambio se hace con
# agyswitcher set-active trabajo  (/logout + inicio de sesión guiado y verificado)
```

---

## 8. Límites de Seguridad

| Regla | Detalle |
| :--- | :--- |
| **No tocar credenciales ni `.gemini`** | La sesión de Google (Administrador de credenciales) nunca se lee, copia ni modifica. `%USERPROFILE%\.gemini` no se modifica; de sus logs solo se leen líneas para detectar cuota y eventos de inicio de sesión. |
| **Sanitización obligatoria** | Antes de escribir cualquier línea en log, se redactan patrones: `token`, `authorization`, `cookie`, `refresh_token`, `access_token`. |
| **Sin `shell=True`** | Toda invocación de subprocesos usa listas de argumentos explícitas. |
| **Rutas con `pathlib.Path`** | Todas las rutas se construyen y validan con `pathlib.Path`. No se aceptan rutas de fuentes externas sin validación previa. |
| **Inicio de sesión manual** | AgySwitcher nunca automatiza el inicio de sesión de Google: solo indica el email y verifica el resultado en los logs. |
| **No telemetría** | No se envía ningún dato a servicios remotos. Todo el estado es local. |

---

## 9. Estructura del Paquete Python (Fase 2+)

```
agyswitcher/src/agyswitcher/
├── __init__.py
├── cli.py                  # Entry point CLI (typer) y cambio de cuenta guiado
├── config.py               # Lectura y escritura de config.json
├── state.py                # Lectura y escritura atómica de state.json
├── models.py               # Account, AppState, AccountQuotaInfo
├── runner.py               # Lanzador de agy.exe (streaming, señales, sanitización, procesos)
├── quota.py                # Detector de cuota agotada en líneas y logs
├── usage.py                # Consulta de cuota (/usage) y detección del email de la sesión
├── rotator.py              # Selección de la siguiente cuenta/pool y registro de cambios
├── session.py              # Verificación de inicio de sesión por contenido nuevo de logs
├── version.py              # Versión semántica, número de compilación y versión de Windows
├── _build.py              # Número de compilación (None en el código fuente)
├── project.py              # init (AGENTS.md, dev_mem/), handoff y umbral de cuota baja
├── ai_models.py            # Modelos disponibles y preferencias por pool
└── dashboard.py            # Panel TUI
```

---

## 10. Empaquetado y distribución

- `packaging/entry.py`: punto de entrada del ejecutable.
- `packaging/make_version_info.py`: recurso de versión de Windows (`MAJOR.MINOR.PATCH.BUILD`,
  descripción, copyright y licencia) a partir de `version.py`.
- `packaging/build.ps1`: escribe el número de compilación en `_build.py` (y lo restaura
  siempre), ejecuta PyInstaller en modo carpeta (`--onedir`, modo UTF-8 de Python para que la
  salida redirigida sea UTF-8), hace una prueba de humo con `AGYSWITCHER_HOME` temporal, genera
  el ZIP portable, el instalador y `SHA256SUMS.txt`. Los ficheros intermedios van a la carpeta
  temporal del sistema (las carpetas sincronizadas en la nube bloquean ficheros).
- `packaging/agyswitcher.iss` (Inno Setup 6): instalación por usuario sin administrador en
  `%LOCALAPPDATA%\Programs\AgySwitcher`, PATH del usuario (se retira al desinstalar),
  manual y tutoriales en `docs\`, licencia GPL en el asistente. No borra
  `%USERPROFILE%\.agyswitcher`.
- GitHub Actions: `ci.yml` (pruebas en cada push) y `release.yml` (al publicar `vX.Y.Z`:
  comprueba que la etiqueta coincide con `__version__`, compila con el número de ejecución
  y publica la release con las notas del CHANGELOG).
- Sin firma de código por ahora (aviso de SmartScreen documentado; SHA-256 publicados).
- Web: MkDocs Material (`mkdocs.yml`) sobre `docs/` (portada `docs/index.md`, manual,
  tutoriales y documentación técnica). `ci.yml` la construye en modo estricto (enlaces rotos
  = error); `docs.yml` la publica en GitHub Pages cuando el repositorio es público. Los
  pantallazos (`docs/assets/capturas/*.svg`) se generan con cuentas ficticias.

---

## 11. Decisiones Pendientes

| Decisión | Opciones | Criterio de elección |
| :--- | :--- | :--- |
| **Framework CLI** | `typer` (más ergonómico) vs `argparse` (stdlib) | Preferir `typer` si se acepta la dependencia; sino `argparse`. Decidir en Fase 2. |
| **Modo de cambio de cuenta** | Resuelto (2026-11-18): siempre guiado; requiere que el usuario inicie sesión. | — |
| **Copia inicial de perfil en `add`** | Obsoleta: ya no hay perfiles por cuenta. | — |
