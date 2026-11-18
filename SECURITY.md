# Política de seguridad

## Versiones con soporte

Se corrigen los problemas de seguridad en la última versión publicada.

## Cómo informar de una vulnerabilidad

**No abras una issue pública.** Usa una de estas vías privadas:

1. En GitHub: pestaña **Security → Report a vulnerability** del repositorio (aviso privado).
2. Por email: [contact@gabimarti.slmail.me](mailto:contact@gabimarti.slmail.me).

Incluye una descripción, los pasos para reproducirlo y la versión
(`agyswitcher --version`). **No envíes tokens, contraseñas ni datos reales de tus
cuentas**; si hacen falta ejemplos, usa datos ficticios.

Recibirás una respuesta lo antes posible. Cuando haya corrección, se publicará una nueva
versión y se reconocerá tu aviso si lo deseas.

## Qué se considera vulnerabilidad

Por diseño, AgySwitcher:

- no lee, copia, descifra ni guarda tokens OAuth, contraseñas ni cookies;
- no automatiza el inicio de sesión de Google;
- no modifica `%USERPROFILE%\.gemini` ni la sesión de `agy`;
- filtra los datos sensibles de las salidas que procesa y no envía nada a ningún servicio.

Cualquier situación en la que no se cumpla alguno de estos puntos (por ejemplo, un token o
una cabecera de autorización que aparezca sin filtrar en una salida o un registro) es una
vulnerabilidad.
