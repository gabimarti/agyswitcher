# Conceptos

## Una sola sesión de Google en `agy`

`agy` guarda **una única sesión de Google** en el *Administrador de credenciales de
Windows*. En cada momento hay una sola cuenta con la sesión iniciada, y para usar otra hay
que cerrar sesión en `agy` (`/logout`) e iniciarla con la otra cuenta en el navegador.

AgySwitcher **no lee, copia ni modifica** esa sesión ni tus contraseñas, y **nunca inicia
sesión por ti**. Lo que hace es decirte con qué cuenta entrar y comprobar después que lo
has hecho.

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
a ella.

## El cambio de cuenta guiado

`agyswitcher set-active <alias>` (o `rotate`) no puede cambiar la cuenta por sí mismo.
Sigue estos pasos:

1. Te indica el email de la cuenta destino.
2. Tú, en `agy`, ejecutas `/logout` e inicias sesión con ese email.
3. AgySwitcher espera a ver ese inicio de sesión en los registros de `agy` (solo cuenta uno
   **posterior** a la petición) y entonces registra el cambio.
4. Te muestra la instrucción para que el agente retome el proyecto.

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
