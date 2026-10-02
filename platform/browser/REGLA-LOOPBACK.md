# LA REGLA DE LOOPBACK DEL CINTURÓN — v1

**Escrita ANTES del código** (pedido del dueño, 2026-08-18). El código que la implementa es
`platform/browser/loopback.py`; la vara que la rompe es `qa/verify_regla_loopback.py`.

## Por qué existe

El escenario que se quiere es: **el agente levanta un servidor propio y lo navega**. Hoy eso
es imposible — `platform/inspection/loop/guard.py` bloquea loopback fail-closed, resolviendo
DNS y mirando cada IP. Es anti-SSRF deliberado y **no se toca**: la excepción es del
cinturón, no de él.

## La pregunta que decide todo: ¿cualquier loopback, o sólo el nuestro?

**Sólo el nuestro.** Y no es prudencia abstracta — está medido qué escucha en loopback en
esta máquina cuando Aleph corre:

| quién | dónde | evidencia |
|---|---|---|
| **el propio sidecar de Aleph** — Home, Capa 0 y **toda `/v1`** | `127.0.0.1:<port>` | `deploy/fase4/aleph-shell/src-tauri/src/lib.rs:4,10,55` |
| los packs de los seis workspaces | `127.0.0.1:<puerto>` | `platform/workspaces/pack.py:119` (`s.bind(("127.0.0.1", 0))`) |
| el motor de búsqueda y el de research | ídem | `platform/sala/{busqueda,research}/arranque.sh` |

Un agente con permiso sobre «cualquier loopback» puede navegar al **backend de Aleph** con
la sesión del usuario ya puesta en el navegador. Eso no es browser use: es una escalada de
privilegios con forma de feature. Por eso la regla es de **allowlist por puerto**, no de
excepción de rango.

---

## La regla

### R1 · Sólo puertos que el propio run registró

Navegar a un host que resuelva a loopback se permite **si y sólo si** el puerto está en el
registro de este `run_id`. Cualquier otro puerto de `127.0.0.0/8` (o `::1`) se **deniega**.

### R2 · Cómo se sabe que un puerto es «nuestro»: **porque lo dio la casa**

El agente **nunca elige un puerto**. Levanta un proceso por una tool de la casa, y esa tool:

1. pide un puerto con `pack.puerto_libre()` (`platform/workspaces/pack.py:109`) — el mismo
   mecanismo que ya usan los seis packs;
2. lo anota en el registro bajo `(run_id, puerto)` con el PID del proceso;
3. se lo devuelve al agente.

El registro **vive en memoria del proceso del sidecar y muere con el run** — no es un
archivo, no se hereda entre runs, y no hay forma de que el agente escriba en él. Si el
agente inventa un puerto, no está en el registro y se deniega con causa tipada.

> **Un puerto anotado no es un puerto abierto para siempre**: al cerrar el proceso, la tool
> lo desanota. El ciclo es el mismo `enter`/`leave` simétrico de F4 — levantar al entrar,
> apagar al salir, jamás huérfanos.

### R3 · Lo que sigue bloqueado, siempre, aunque alguien lo registre

- **El puerto del propio sidecar de Aleph** — lista negra dura, gana sobre el registro.
- `169.254.169.254` y `fd00:ec2::254` — metadata de nube.
- Link-local, multicast, reservadas, `0.0.0.0`, `::`.
- **Redes privadas** (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`): el agente no navega la
  LAN del usuario. Eso es otra decisión y no está tomada.
- Todo esquema que no sea `http`/`https`.
- Todo el resto de `127.0.0.0/8` que no esté en el registro del run.

### R4 · Se resuelve DNS y se mira CADA IP

Un hostname que resuelve a loopback **es** loopback y pasa por R1. Esto tapa `localtest.me`,
`*.nip.io`, `*.localho.st` y cualquier rebind.

> **Esto NO se delega a browser-use, y es una decisión medida.** Su `SecurityWatchdog`
> (`browser_use/browser/watchdogs/security_watchdog.py:138-174`) sólo reconoce **IPs
> literales** —eso sí, con canonicalización WHATWG contra formas decimal/hex/octal— pero
> **no resuelve DNS**: un hostname cae a `return False` y pasa al manejo de allowlist. Y
> peor, su `_is_url_allowed:216-221` **permite todo** cuando no hay ni `allowed_domains` ni
> `prohibited_domains`: es **fail-open** por defecto, lo contrario del guard de la casa.
>
> Entonces la regla se aplica **del lado de Aleph, antes de entregarle la URL**, y
> `allowed_domains` de browser-use se usa como **segunda cerca más gruesa**, nunca como la
> primera.

### R5 · Fail-closed

Sin `run_id`, sin registro, con una URL que no parsea, con un DNS que no resuelve, o ante
**cualquier** excepción → **deny**. Ante la duda, no.

### R6 · El guard de inspección no se toca

`platform/inspection/loop/guard.py` sigue negando loopback fail-closed. La excepción vive en
`platform/browser/loopback.py` y **sólo la consume la tool del cinturón**. Que sigan siendo
dos cosas distintas es parte de la regla, y la vara lo verifica.

---

## La vara, y por qué PUEDE dar rojo

`qa/verify_regla_loopback.py`. Cada caso afirma una **denegación**, así que aflojar el guard
la pone en rojo — no en verde silencioso. Los casos:

| # | caso | esperado | qué rojo destapa |
|---|---|---|---|
| 1 | `127.0.0.1:<puerto NO registrado>` | **deny** | alguien abrió el rango en vez del puerto |
| 2 | `127.0.0.1:<puerto registrado>` | allow | la regla no se volvió inútil (el único caso que afirma un sí) |
| 3 | `localtest.me:<NO registrado>` (DNS→127.0.0.1) | **deny** | **se dejó de resolver DNS** — el rojo que sólo aparece si el instrumento es el correcto |
| 4 | `169.254.169.254` **estando registrado** | **deny** | la lista negra dura dejó de ganarle al registro |
| 5 | `192.168.1.1:<registrado>` | **deny** | se coló la LAN |
| 6 | el puerto del sidecar, **registrado a mano** | **deny** | la lista negra del propio backend se cayó |
| 7 | **sin `run_id`** | **deny** | se perdió el fail-closed |
| 8 | `file:///etc/passwd`, `gopher://` | **deny** | se aceptó un esquema que no es http(s) |
| 9 | `PublicHTTPGuard().check("http://127.0.0.1")` | **deny** | **alguien aflojó el guard de inspección** (R6) |

**El fixture no siembra el registro.** Es la trampa de esta semana —«tres casos salieron
verdes porque el fixture traía una pista»—: acá el registro arranca **vacío** y cada caso que
necesita un puerto lo anota explícitamente. Un caso que se olvide de anotar da deny, que es
lo correcto, y no un verde prestado.

**Y la vara se prueba cayendo**: la corrida imprime el resultado de re-ejecutar los casos 1,
3 y 7 contra un guard deliberadamente aflojado. Si esos tres no dan rojo con el guard
aflojado, **la vara no mide nada** y lo dice.
