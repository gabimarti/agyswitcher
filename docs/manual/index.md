# Manual de AgySwitcher

*Switch accounts. Keep coding.*

> **Versión:** 1.4.1 · [Registro de cambios](https://github.com/gabimarti/agyswitcher/blob/main/CHANGELOG.md)

AgySwitcher te ayuda a trabajar con **varias cuentas de Google en Antigravity CLI (`agy`)**:
sabe cuánta cuota le queda a cada una, te avisa antes de que se agote, te indica la
siguiente cuenta disponible, te guía al cambiar de cuenta y comprueba que lo has hecho bien.
Además prepara tus proyectos para que **la siguiente sesión, con otra cuenta o incluso con
otro agente de IA, sepa dónde lo dejaste**.

## Contenido

1. [Instalación](instalacion.md): con el instalador o desde el código fuente.
2. [Uso en el día a día](dia-a-dia.md): para quién es, la rutina de trabajo y casos
   prácticos. **Empieza por aquí.**
3. [Conceptos](conceptos.md): cómo funciona y por qué.
4. [Referencia de comandos](comandos.md): todos los comandos y sus opciones.
5. [Continuidad del proyecto](continuidad.md): `init`, `handoff`, aviso de cuota baja y
   `.agyswitcher.toml`.
6. [Varios agentes y proveedores](multiagente.md): combinar `agy` con Claude Code, Codex,
   Copilot o Cursor sobre el mismo proyecto.
7. [Problemas frecuentes](problemas.md): mensajes habituales y cómo resolverlos.
8. [Desinstalación](desinstalacion.md).

## Tutoriales

- [Empezar un proyecto nuevo con AgySwitcher](../tutoriales/proyecto-nuevo.md)
- [Incorporar AgySwitcher a un proyecto existente](../tutoriales/proyecto-existente.md)

## Resumen en un minuto

```powershell
agyswitcher add personal --email personal@example.com   # registra tus cuentas
agyswitcher add trabajo  --email trabajo@example.com --no-activate
agyswitcher list                                         # cuota de cada cuenta

cd C:\ruta\a\mi-proyecto
agyswitcher init                                         # prepara el proyecto

# ...trabajas con agy hasta que AgySwitcher avisa de cuota baja...
agyswitcher handoff save        # pega la instrucción en agy: guarda el estado
agyswitcher set-active trabajo  # /logout + inicio de sesión guiado y verificado
                                # y te muestra la instrucción para retomar
```
