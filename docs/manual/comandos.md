# Referencia de comandos

Todas las órdenes muestran su ayuda con `--help` (por ejemplo, `agyswitcher add --help`).
`agyswitcher --version` muestra la versión instalada.

| Comando | Para qué |
| :--- | :--- |
| [`add`](#add) | Registrar una cuenta |
| [`remove`](#remove) | Eliminar una cuenta |
| [`list`](#list) | Ver todas las cuentas con su cuota |
| [`status`](#status) | Estado detallado de la cuenta activa |
| [`usage`](#usage) | Cuota y sesión en vivo |
| [`dashboard`](#dashboard) | Panel de control en la terminal |
| [`set-active`](#set-active) | Cambiar a otra cuenta (cambio guiado) |
| [`rotate`](#rotate) | Cambiar de pool o a la siguiente cuenta con cuota |
| [`sync`](#sync) | Alinear la cuenta activa con la sesión real de `agy` |
| [`run`](#run) | **Flujo principal:** ejecutar `agy` con supervisión y detección de cuota |
| [`watch`](#watch) | *Modo avanzado:* vigilar registros de `agy` en segundo plano (para IDEs) |
| [`models`](#models) | Modelos disponibles y preferidos |
| [`init`](#init) | Preparar un proyecto para continuar entre cuentas y agentes |
| [`handoff`](#handoff) | Instrucciones para guardar y retomar el trabajo |
| [`config`](#config) | Ajustes: umbral de cuota baja y copia al portapapeles |
| [`doctor`](#doctor) | Diagnóstico de la instalación |

---

## add

Registra una cuenta con un alias: hasta 64 letras, números, `-` y `_`, empezando y terminando
por letra o número (por ejemplo `personal` o `cuenta-2`). El email debe tener un formato válido
(`nombre@example.com`).

```powershell
agyswitcher add personal                         # detecta el email de la sesión de agy
agyswitcher add trabajo --email trabajo@example.com --no-activate
```

| Opción | Descripción |
| :--- | :--- |
| `--email`, `-e` | Email de Google. Si se omite, se detecta de la sesión de `agy`. |
| `--activate` / `--no-activate` | Forzar o impedir que pase a ser la cuenta activa. |

Solo se activa (y se consulta su cuota) si la sesión de `agy` es de esa cuenta, o si es la
primera que registras. **Registra siempre el email**: sin él no se puede verificar el cambio
de cuenta. Después prepara su slot con un primer [`set-active`](#set-active) guiado: ver la
[preparación](dia-a-dia.md#2-prepara-el-slot-de-cada-cuenta).

## remove

Elimina una cuenta, su información de cuota y su slot de sesión en Windows Credential Manager
(si disponía de uno). Pide confirmación salvo con `--force` (`-f`).
Si era la cuenta activa, no queda ninguna activa: ejecuta [`sync`](#sync) o
[`set-active`](#set-active).

```powershell
agyswitcher remove trabajo
agyswitcher remove trabajo --force
```

## list

Lista las cuentas con su email, el porcentaje restante de cada pool (Gemini / Otros) y la
fecha de reinicio. La cuenta activa aparece primero; el resto, por el reinicio más próximo.

| Opción | Descripción |
| :--- | :--- |
| *(ninguna)* | Refresca la cuenta activa si sus datos tienen más de 3 minutos. |
| `--live`, `-l` | Consulta ya la cuota de la cuenta con sesión iniciada. |
| `--cached`, `-c` | Solo datos guardados, sin consultar a `agy`. |
| `--refresh-all`, `-a` | Obsoleto: equivale a `--live`. |

Al final avisa si la cuota del pool activo es baja (20 % o menos por defecto; ver
[`config`](#config)) o si la sesión de `agy`
no coincide con la cuenta activa.

## status

Estado detallado de la cuenta activa, pools y cuentas agotadas. Con `--live` (`-l`) consulta
la cuota y la sesión en vivo. También avisa de cuota baja.

## usage

Consulta en vivo la sesión de `agy` y la cuota semanal de los dos pools, con barras y tiempo
hasta el reinicio.

| Opción | Descripción |
| :--- | :--- |
| `--sync` / `--no-sync` | Guardar o no el resultado en el estado local. |
| `--timeout <segundos>` | Tiempo máximo de la consulta (por defecto 15). |

## dashboard

Panel de control en la terminal: resumen, cuentas con barras de cuota e historial de cambios.

| Opción | Descripción |
| :--- | :--- |
| `--live`, `-l` | Consultar métricas en vivo. |
| `--watch`, `-w` | Refrescar continuamente (salir con `Ctrl+C`). |
| `--interval`, `-i <segundos>` | Intervalo de refresco con `--watch` (por defecto 3). |

## set-active

Cambia a otra cuenta con conmutación instantánea si dispone de slot o mediante el
**cambio guiado** si no (ver [Conceptos](conceptos.md#cambio-de-cuenta-y-slots)).

```powershell
agyswitcher set-active trabajo
agyswitcher set-active trabajo --timeout 600
```

| Opción | Descripción |
| :--- | :--- |
| `--timeout <segundos>` | Tiempo máximo de espera del inicio de sesión (por defecto 300). |

Si la cuenta destino dispone de slot guardado en Windows Credential Manager (`[slot]` en `list`),
el cambio es inmediato. Si no tiene slot o la sesión caducó, se realiza el cambio guiado:
te muestra el email; en `agy` ejecutas `/logout` e inicias sesión con él; AgySwitcher
lo verifica, guarda su slot para futuros cambios instantáneos, registra el cambio, consulta
la cuota de la nueva cuenta y te muestra la instrucción para retomar el proyecto. Si es la
cuenta que ya está activa, no pide nada.

## rotate

Sin argumentos, elige automáticamente:

1. Si al pool activo se le acabó la cuota y el otro pool de la misma cuenta está libre,
   cambia de pool (no requiere iniciar sesión).
2. Si no, conmuta a la siguiente cuenta con cuota (instantáneamente si tiene slot CredMan o
   mediante el cambio guiado si no).

Si ninguna cuenta tiene cuota libre, elige una cuyo reinicio previsto ya haya pasado
(avisando de que está sin confirmar). Si todas siguen agotadas según los datos guardados,
muestra la antigüedad del dato y el reinicio previsto de cada cuenta, y te sugiere cuál
comprobar primero (ver [Conceptos](conceptos.md#cuota-consultada-y-cuota-guardada)). Al
terminar el cambio de cuenta consulta la cuota de la nueva cuenta.

Con un alias (`agyswitcher rotate trabajo`) cambia a esa cuenta. Admite `--timeout` como
`set-active`.

## sync

Detecta con qué cuenta tienes la sesión iniciada en `agy` y la marca como activa (además de
actualizar su cuota). Úsalo si cambiaste de cuenta en `agy` sin AgySwitcher. Si la cuenta
activa no tenía email, le asigna el detectado.

## run

Es el **flujo de trabajo principal y recomendado** para programar con `agy` en el día a día.
En lugar de abrir `agy` directamente por tu cuenta, lanzarlo a través de `agyswitcher run`
ofrece las siguientes ventajas integradas:

1. **Revisión de frescura al arrancar:** antes de iniciar `agy`, comprueba si la cuota guardada
   tiene más de 3 minutos (o no existe) y la consulta en vivo de forma segura. Si está por
   debajo del umbral (20 % por defecto), te avisa antes de que te sumerjas en la sesión para
   que guardes el estado a tiempo.
2. **Inyección automática de modelo preferido:** si configuraste un modelo preferido para el
   pool activo (ver [`models`](#models)), `run` añade automáticamente `--model <id>` sin que
   tengas que escribirlo cada vez (salvo que indiques otro explícitamente).
3. **Supervisión pasiva en tiempo real:** mientras `agy` está abierto en modo interactivo,
   sigue sus registros de error (`cli.log`) en segundo plano sin ralentizar la consola ni
   lanzar procesos concurrentes.
4. **Propuesta y guía al agotarse la cuota:** si durante la sesión se agota la cuota del pool
   en uso, emite un aviso visual/sonoro inmediato y, al salir de `agy` (`/exit`), te indica cómo
   continuar:
   - si la misma cuenta tiene libre el otro pool, rota de pool automáticamente (solo tienes
     que volver a ejecutar `agyswitcher run`);
   - si no, propone la siguiente cuenta con cuota, indica el comando para cambiar (`set-active`)
     y te recuerda guardar el estado (`handoff save`);
   - si todas figuran agotadas, sugiere cuál comprobar primero, como en [`rotate`](#rotate).
5. **Paso transparente de argumentos:** todo lo que indiques después de `--` se envía directamente
   a `agy`.

```powershell
agyswitcher run                                     # Sesión interactiva normal (flujo principal recomendado)
agyswitcher run -- --continue                       # Retomar la conversación más reciente de agy
agyswitcher run -- -p "Analiza los errores en tests" # Consulta puntual directa sin abrir TUI
agyswitcher run -- --model claude-sonnet-4-6        # Forzar un modelo específico para esta sesión
agyswitcher run -- --help                           # Ver las opciones nativas de agy
```

## watch

Es un **modo observador avanzado**. Vigila los registros de `agy` (por defecto
`%USERPROFILE%\.gemini\antigravity-cli\cli.log`) en segundo plano.

**¿Cuándo se usa?**

- Únicamente si prefieres **no** lanzar `agy` desde AgySwitcher, por ejemplo porque abres `agy`
  directamente en el terminal integrado de Visual Studio Code, Cursor u otro IDE.
- En ese escenario, abres una segunda consola independiente y dejas `agyswitcher watch`
  ejecutándose en paralelo para que supervise la cuota mientras programas en el IDE.
- **Nota:** Si utilizas `agyswitcher run`, **no necesitas `watch`**, ya que `run` incluye
  esta misma supervisión internamente en segundo plano.

Al detectar cuota agotada la anota y:

- si la cuenta tiene libre el otro pool, cambia de pool;
- si no, **propone** la siguiente cuenta con cuota y el comando para cambiar, y te recuerda
  guardar el estado (`handoff save`). No cambia de cuenta por sí mismo;
- si todas figuran agotadas, te sugiere qué cuenta comprobar primero, como
  [`rotate`](#rotate).

Si lo que se agota es el pool que no estás usando, solo lo anota.

| Opción | Descripción |
| :--- | :--- |
| `--interval`, `-i <segundos>` | Intervalo de comprobación (por defecto 2). |
| `--once` | Una sola comprobación y salir. |
| `--from-start` | Leer el registro desde el principio. |
| `--log-file <ruta>` | Vigilar otro fichero de registro. |

## models

Lista los modelos de `agy` clasificados por pool y permite fijar un modelo preferido por
pool y cuenta, que `run` usa automáticamente.

```powershell
agyswitcher models
agyswitcher models --set gemini-3.8-flash-high
agyswitcher models --set claude-sonnet-4-6 --account trabajo
agyswitcher models --clear
```

| Opción | Descripción |
| :--- | :--- |
| `--set`, `-s <modelo>` | Fijar el modelo preferido de su pool. |
| `--clear` | Borrar las preferencias de la cuenta. |
| `--account`, `-a <alias>` | Cuenta a configurar (por defecto, la activa). |

## init

Prepara un proyecto para continuar entre cuentas y agentes. Ver
[Continuidad del proyecto](continuidad.md#preparar-un-proyecto-init).

```powershell
agyswitcher init
agyswitcher init C:\ruta\proyecto --agents gemini,claude,copilot,cursor
agyswitcher init --merge
agyswitcher init --dry-run
```

| Opción | Descripción |
| :--- | :--- |
| `path` | Carpeta del proyecto (por defecto, la actual). |
| `--agents`, `-a` | Agentes: `gemini`, `claude`, `copilot`, `cursor` (por defecto `gemini,claude`). |
| `--name` | Nombre del proyecto en las plantillas (por defecto, el de la carpeta). |
| `--merge` | Completar ficheros existentes con lo que les falte. |
| `--dry-run` | Mostrar qué haría sin escribir nada. |

## handoff

Muestra las instrucciones de traspaso del proyecto actual y gestiona el fichero `HANDOFF.md`.
Al ejecutar `save`, guarda automáticamente `dev_mem/HANDOFF.md` (o `HANDOFF.md` en la raíz)
con las notas de traspaso y el prompt para que el siguiente agente retome el trabajo sin
depender del portapapeles.

```powershell
agyswitcher handoff save                              # guardar HANDOFF.md y ver la instrucción
agyswitcher handoff save --note "Falta probar en Win" # añadir notas de estado al fichero
agyswitcher handoff resume                            # ver cómo retomar después del cambio
agyswitcher handoff                                   # ambas
agyswitcher handoff save -c                           # además, copiarla al portapapeles
```

| Opción | Descripción |
| :--- | :--- |
| `--note`, `-n` | Nota opcional sobre el estado actual para incluir en `HANDOFF.md`. |
| `--copy`, `-c` | Copia la instrucción al portapapeles (con `save` o `resume`). |

## config

Muestra o cambia los ajustes globales (se guardan en `config.json`).

```powershell
agyswitcher config                     # ver los ajustes
agyswitcher config low-quota 25        # avisar con un 25 % o menos
agyswitcher config low-quota default   # volver al valor por defecto (20 %)
agyswitcher config auto-copy on        # activar copia al portapapeles
```

| Ajuste | Valores | Para qué |
| :--- | :--- | :--- |
| `low-quota` | 1-99 o `default` | Umbral del aviso de cuota baja (por defecto 20 %). |
| `auto-copy` | `on` / `off` | Copiar automáticamente al portapapeles (por defecto `off`, ya que el login de Google puede sobrescribir el portapapeles; se recomienda el fichero `HANDOFF.md`). |

Un proyecto puede tener su propio umbral en `.agyswitcher.toml`, que tiene prioridad sobre
el global (ver [Continuidad](continuidad.md#aviso-de-cuota-baja)).

## doctor

Revisa en un solo paso que todo esté en orden y explica cómo arreglar lo que no lo esté:

- Qué `agy` se usa, de dónde sale (`AGYSWITCHER_AGY`, `PATH` o ruta de instalación) y
  su versión.
- Carpeta de datos, ajustes, cuentas registradas (y si alguna no tiene email) y estado.
- Cuenta activa y si coincide con la sesión que `agy` tiene iniciada.
- Antigüedad de los datos de cuota y cuentas agotadas cuyo reinicio ya pasó.
- Procesos de `agy` abiertos.
- Si la carpeta actual está preparada con `agyswitcher init` (`AGENTS.md` y `dev_mem/`) y
  si su `.agyswitcher.toml` es válido.

Solo lee: no cambia nada, no consulta la cuota y no lee tokens. Los emails aparecen
enmascarados (`pe***@example.com`) y tu carpeta personal como `~`, para que puedas pegar la
salida al pedir ayuda. Termina con código 1 si alguna comprobación falla.

| Opción | Descripción |
| :--- | :--- |
| `--show-emails` | Mostrar los emails completos. |
