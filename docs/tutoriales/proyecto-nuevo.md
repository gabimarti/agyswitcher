# Tutorial: empezar un proyecto nuevo con AgySwitcher

Este tutorial te lleva desde una carpeta vacía hasta el primer cambio de cuenta sin perder
el contexto. Suponemos que ya tienes AgySwitcher [instalado](../manual/instalacion.md) y dos
cuentas de Google.

## 1. Registra tus cuentas (una sola vez)

Con la sesión de `agy` iniciada con tu primera cuenta:

```powershell
agyswitcher add personal --email personal@example.com
agyswitcher add trabajo  --email trabajo@example.com --no-activate
agyswitcher list
```

`personal` queda como cuenta activa. La cuota de `trabajo` aparecerá cuando cambies a ella.

## 2. Crea y prepara el proyecto

```powershell
mkdir C:\Proyectos\MiProyecto
cd C:\Proyectos\MiProyecto
git init                 # opcional
agyswitcher init
```

`init` crea `AGENTS.md`, `GEMINI.md`, `CLAUDE.md`, `dev_mem/ESTADO.md`, `dev_mem/TODO.md` y
`.agyswitcher.toml`. Si también usas Copilot o Cursor:
`agyswitcher init --agents gemini,claude,copilot,cursor`.

## 3. Describe el proyecto en `AGENTS.md`

Abre `AGENTS.md` y completa la sección **Proyecto**: propósito, tecnologías, cómo ejecutar
las pruebas y convenciones. Si aún no lo sabes, no pasa nada: puedes pedírselo al agente
más adelante («cuando decidamos el stack, actualiza la sección Proyecto de AGENTS.md»).

Decide si `dev_mem/` se publica. Si no:

```powershell
Add-Content .gitignore "dev_mem/"
```

## 4. Primera sesión con el agente

```powershell
agy
```

Como primera instrucción, pide que lea las reglas: *«Lee AGENTS.md y dev_mem/ y empecemos:
quiero que el proyecto haga…»*. A partir de aquí trabajas con normalidad. Por las reglas de
`AGENTS.md`, el agente irá anotando en el diario de `dev_mem/`.

## 5. Cuando la cuota baja

Consulta de vez en cuando `agyswitcher list` (o lanza `agy` con `agyswitcher run`). Cuando
al pool activo le quede un 15 % o menos, verás:

```text
[!] Cuota baja en 'personal' (Gemini: 12 % restante, umbral 15 %). Antes de que se agote,
pide a agy que guarde el estado del proyecto.
La instrucción para guardar el estado está en el portapapeles: pégala en agy (también la
muestra agyswitcher handoff save).
Siguiente cuenta con cuota: 'trabajo'.
```

> Si solo se ha agotado un pool, quizá puedas seguir con el otro de la misma cuenta:
> `agyswitcher rotate` cambia de pool sin iniciar sesión.

## 6. Guarda el estado

```powershell
agyswitcher handoff save
```

Copia la instrucción, pégala en `agy` y espera a que el agente confirme que ha actualizado
`dev_mem/ESTADO.md`, `TODO.md` y el diario.

## 7. Cambia de cuenta

```powershell
agyswitcher set-active trabajo
```

En `agy`: `/logout` e inicia sesión con `trabajo@example.com`. AgySwitcher lo detecta,
registra el cambio y te muestra la instrucción para retomar.

## 8. Retoma

Pega en `agy` la instrucción que te mostró AgySwitcher (o `agyswitcher handoff resume`). El
agente leerá la memoria del proyecto, te resumirá dónde estabais y esperará tu confirmación.

Ya estás trabajando con la segunda cuenta, con el mismo historial de `agy` y con el
contexto del proyecto intacto. El ciclo se repite cada vez que una cuenta se queda sin
cuota.
