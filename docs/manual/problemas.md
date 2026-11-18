# Problemas frecuentes

## Al cambiar de cuenta

**`set-active` sigue esperando y no termina.**
AgySwitcher espera a que inicies sesión en `agy` con el email indicado. En una ventana de
`agy` ejecuta `/logout` e inicia sesión en el navegador con **ese** email. Si necesitas más
tiempo, usa `--timeout 600`. Para cancelar, `Ctrl+C`: la cuenta activa no cambia.

**«Sesión iniciada con … no con …».**
Es normal si abres `agy` sin cerrar sesión antes: `agy` carga la sesión guardada al
arrancar. Ejecuta `/logout` e inicia sesión con la cuenta correcta; AgySwitcher sigue
esperando.

**Otras ventanas de `agy` siguen usando la cuenta anterior.**
Cada proceso de `agy` carga la sesión al arrancar. Cierra y vuelve a abrir esas ventanas.

**«No tiene email registrado».**
Sin email no se puede verificar el cambio. Vuelve a registrar la cuenta con su email:
`agyswitcher remove <alias>` y `agyswitcher add <alias> --email <correo> --no-activate`.

**Cancelé, pero sí llegué a iniciar sesión con otra cuenta.**
Ejecuta `agyswitcher sync`: marcará como activa la cuenta con la que tienes la sesión.

## Cuentas y cuota

**«Desajuste de cuenta detectado» en `list` o `status`.**
La sesión de `agy` es de una cuenta distinta de la activa (por ejemplo, cambiaste de cuenta
directamente en `agy`). Ejecuta `agyswitcher sync`.

**La cuota de una cuenta no se actualiza.**
`agy` solo informa de la cuota de la cuenta con la sesión iniciada. La de las demás se
actualiza cuando cambias a ellas. `list --refresh-all` no puede consultar varias cuentas.

**`add` no activa la cuenta nueva.**
Solo se activa si la sesión de `agy` es de esa cuenta. Para usarla:
`agyswitcher set-active <alias>`.

**No hay cuenta activa después de `remove`.**
Ejecuta `agyswitcher sync` (cuenta de la sesión actual) o `agyswitcher set-active <alias>`.

## Proyecto y continuidad

**`init` dice «Ya existe (no se toca)».**
`init` nunca sobrescribe. Si quieres que complete tus ficheros con lo que les falta, usa
`agyswitcher init --merge` (prueba antes con `--dry-run`).

**`init --merge` dice que un fichero no está en UTF-8.**
AgySwitcher no modifica ficheros con otra codificación para no estropearlos. Guárdalo como
UTF-8 desde tu editor y repite.

**`handoff` muestra las instrucciones por defecto y no las mías.**
Comprueba que estás dentro de la carpeta del proyecto (o una subcarpeta) y que
`.agyswitcher.toml` tiene la sección `[handoff]`. Si el fichero tiene un error de formato,
`handoff` lo indica.

## Instalación

**«Windows protegió su PC» al ejecutar el instalador.**
Es el aviso de SmartScreen para programas sin firma digital. Pulsa **Más información** →
**Ejecutar de todas formas**. Si quieres asegurarte de que el fichero es el original,
compara su SHA-256 (`Get-FileHash <fichero>`) con `SHA256SUMS.txt` de la página de
*Releases*.

**El antivirus marca `agyswitcher.exe` como sospechoso.**
Ocurre a veces con programas empaquetados con PyInstaller que no están firmados. Comprueba
el SHA-256 como en el punto anterior; si coincide, puedes añadir una excepción o usar la
instalación desde el código fuente.

**Tras instalar, `agyswitcher` no se reconoce como comando.**
El instalador añade AgySwitcher al `PATH` de tu usuario, pero las consolas que ya estaban
abiertas no lo ven. Abre una consola nueva.

**«No se encontró agy.exe».**
Antigravity CLI no está en el `PATH`. Comprueba que `agy --help` funciona en una consola
nueva.

**`agyswitcher` no se reconoce como comando (instalación desde el código fuente).**
Activa el entorno virtual (`.\.venv\Scripts\Activate.ps1`) en esa consola, o usa la ruta
completa del ejecutable dentro de `.venv\Scripts\`.
