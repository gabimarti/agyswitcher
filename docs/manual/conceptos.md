# Conceptos

## Una sola sesión activa en `agy` y slots de sesión

`agy` guarda **una única sesión de Google activa** en el *Administrador de credenciales de
Windows* (bajo el nombre `gemini:antigravity`). En cada momento hay una sola cuenta con la
sesión activa en `agy`.

Para alternar cuentas de forma cómoda y sin tener que pasar por el navegador cada vez,
AgySwitcher gestiona **slots de sesión** (`gemini:antigravity:slot:<alias>`) dentro del propio
almacén seguro de Windows:
- **Protección nativa con DPAPI:** Los tokens residen exclusivamente en el Administrador de
  credenciales de Windows, cifrados y protegidos por el sistema operativo. AgySwitcher
  **nunca guarda contraseñas ni tokens en archivos de configuración ni registros**.
- **Conmutación instantánea:** Al cambiar a una cuenta que tiene slot guardado (aparece con
  la etiqueta `[slot]` en `list`), AgySwitcher promueve la credencial destino a la sesión
  activa al instante, sincronizando previamente el token de la cuenta saliente en su propio
  slot para proteger rotaciones recientes de tokens.
- **Cambio guiado como alternativa:** Si una cuenta aún no dispone de slot (o si la sesión
  caducó), AgySwitcher recurre automáticamente al cambio guiado en el navegador y guarda el
  slot tras verificar el inicio de sesión.

## Una carpeta común para todas las cuentas

`agy` guarda tu historial, conversaciones, servidores MCP y *skills* en
`%USERPROFILE%\.gemini`. Esa carpeta es **la misma para todas tus cuentas** y AgySwitcher
no la modifica. Por eso, al cambiar de cuenta, sigues teniendo todo tu contexto.

## Cuentas y cuenta activa

- Una **cuenta** es un alias que eliges (`personal`, `trabajo`...) asociado a un email de
  Google. Lo registras con `agyswitcher add`.
- La **cuenta activa** es la que AgySwitcher considera que tiene la sesión iniciada en
  `agy`. Si alguna vez no coinciden (por ejemplo, porque cambiaste de cuenta en `agy` sin
  usar AgySwitcher), `list` y `status` te avisan y `agyswitcher sync` lo corrige.

## Pools de cuota

La cuota semanal de cada cuenta está dividida en dos **pools** independientes:

| Pool | Modelos | Nombre en AgySwitcher |
| :--- | :--- | :--- |
| `gemini` | Modelos Gemini | Gemini |
| `external` | Claude, GPT-OSS y otros | Otros |

Cuando se agota el pool activo de una cuenta, a menudo puedes seguir con su otro pool sin
cambiar de cuenta. Cada pool tiene su propia fecha de reinicio.

## Cuota consultada y cuota guardada

`agy` solo informa de la cuota **de la cuenta con la sesión iniciada**. AgySwitcher guarda
ese dato en la cuenta correspondiente y muestra para las demás el último valor conocido
(de cuando tuvieron la sesión). Por eso la cuota de una cuenta se actualiza cuando cambias
a ella: `set-active` y `rotate` la consultan al terminar el cambio.

Ese dato guardado puede estar desfasado. Una cuenta agotada se vuelve a tener en cuenta
cuando llega su **reinicio previsto** (la fecha de reinicio que dio `agy` o, si no se
conoce, siete días después de agotarse), aunque queda **sin confirmar** hasta que cambias a
ella. Google a veces restablece la cuota antes de esa fecha: si todas las cuentas figuran
agotadas, AgySwitcher lo indica como «según los datos guardados», muestra la antigüedad del
dato y el reinicio previsto de cada cuenta, y te sugiere comprobar primero la de reinicio
más próximo.

## Cambio de cuenta y slots

Al ejecutar `agyswitcher set-active <alias>` o `agyswitcher rotate`:

1. **Si la cuenta destino tiene slot guardado (`[slot]`):**
   - El cambio es **instantáneo**: AgySwitcher promueve la sesión de la cuenta destino a la
     activa de `agy` al momento, sin abrir el navegador ni pedirte ejecutar `/logout`.
   - Si tenías sesiones de `agy` abiertas, el cambio surte efecto en las nuevas consolas o al
     reiniciarlas.
2. **Si la cuenta no tiene slot guardado (o si la sesión guardada expiró):**
   - Se inicia el **cambio guiado**:
     a. Te indica el email con el que debes iniciar sesión.
     b. En `agy`, ejecutas `/logout` e inicias sesión con ese email en el navegador.
     c. AgySwitcher detecta el inicio de sesión en los registros de `agy`, registra el cambio
        y guarda automáticamente el nuevo slot en Credential Manager para el futuro.
     d. Te muestra la instrucción para que el agente retome el proyecto.

Si inicias sesión con otra cuenta te avisa y sigue esperando; si cancelas (`Ctrl+C`) o se
acaba el tiempo, la cuenta activa no cambia.

## Continuidad del proyecto

Lo que debe sobrevivir a un cambio de cuenta o de agente vive **en tu proyecto**, en
ficheros que cualquier agente puede leer:

- `AGENTS.md`: reglas comunes y el procedimiento de memoria.
- `dev_mem/ESTADO.md`, `dev_mem/TODO.md` y un diario por día.

Antes de cambiar de cuenta pides al agente que guarde el estado; después, que lo lea y
continúe. Ver [Continuidad del proyecto](continuidad.md).

## Seguridad

- No se guardan tokens, contraseñas ni cookies; las salidas de `agy` que procesa
  AgySwitcher se filtran para ocultar datos sensibles.
- Todo es local: no se envía nada a ningún servicio.
