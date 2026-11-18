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
| [`run`](#run) | Ejecutar `agy` con detección de cuota |
| [`watch`](#watch) | Vigilar los registros de `agy` |
| [`models`](#models) | Modelos disponibles y preferidos |
| [`init`](#init) | Preparar un proyecto para continuar entre cuentas y agentes |
| [`handoff`](#handoff) | Instrucciones para guardar y retomar el trabajo |

---

## add

Registra una cuenta con un alias (letras, números, `-` y `_`; hasta 64 caracteres).

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
de cuenta.

## remove

Elimina una cuenta y su información de cuota. Pide confirmación salvo con `--force` (`-f`).
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

Al final avisa si la cuota del pool activo es baja (15 % o menos) o si la sesión de `agy`
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

Cambia a otra cuenta con el **cambio guiado** (ver [Conceptos](conceptos.md#el-cambio-de-cuenta-guiado)).

```powershell
agyswitcher set-active trabajo
agyswitcher set-active trabajo --timeout 600
```

| Opción | Descripción |
| :--- | :--- |
| `--timeout <segundos>` | Tiempo máximo de espera del inicio de sesión (por defecto 300). |

Pasos: te muestra el email; en `agy` ejecutas `/logout` e inicias sesión con él; AgySwitcher
lo verifica, registra el cambio, consulta la cuota de la nueva cuenta y te muestra la
instrucción para retomar el proyecto. Si es la cuenta que ya está activa, no pide nada.

## rotate

Sin argumentos, elige automáticamente:

1. Si al pool activo se le acabó la cuota y el otro pool de la misma cuenta está libre,
   cambia de pool (no requiere iniciar sesión).
2. Si no, cambia a la siguiente cuenta con cuota mediante el cambio guiado.

Con un alias (`agyswitcher rotate trabajo`) cambia a esa cuenta. Admite `--timeout` como
`set-active`.

## sync

Detecta con qué cuenta tienes la sesión iniciada en `agy` y la marca como activa (además de
actualizar su cuota). Úsalo si cambiaste de cuenta en `agy` sin AgySwitcher. Si la cuenta
activa no tenía email, le asigna el detectado.

## run

Ejecuta `agy` mostrando su salida, detecta en ella la cuota agotada y la anota. Antes de
lanzar avisa si la cuota es baja. Todo lo que va después de `--` se pasa a `agy`. Si tienes
un modelo preferido para el pool activo (ver [`models`](#models)), se añade `--model`
automáticamente salvo que indiques otro.

```powershell
agyswitcher run -- --help
agyswitcher run -- --model claude-sonnet-4-6 -p "Hola"
```

## watch

Vigila los registros de `agy` (por defecto `%USERPROFILE%\.gemini\antigravity-cli\cli.log`).
Al detectar cuota agotada la anota y:

- si la cuenta tiene libre el otro pool, cambia de pool;
- si no, **propone** la siguiente cuenta con cuota y el comando para cambiar, y te recuerda
  guardar el estado (`handoff save`). No cambia de cuenta por sí mismo.

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

Muestra las instrucciones de traspaso del proyecto actual, listas para copiar y pegar en el
agente.

```powershell
agyswitcher handoff save     # guardar el estado antes de cambiar de cuenta
agyswitcher handoff resume   # retomar después del cambio
agyswitcher handoff          # ambas
```
