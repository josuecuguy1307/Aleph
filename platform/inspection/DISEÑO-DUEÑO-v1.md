# DISEÑO — EL DUEÑO DEL CICLO DE VIDA · v1

**Fecha:** 2026-08-03 · **Rama:** `design/dueno-ciclo-vida` · **Base:** `main @ 4e01fa6`
**Estado: PAPEL.** Cero código de producto. Esto es el documento contra el que se construye.

Cada afirmación sobre lo que hoy existe lleva `archivo:línea`. Cada decisión lleva su
alternativa descartada y por qué. Lo que no se midió está en §9 y dice que no se midió.

---

## §0 · EL ÁRBOL REAL, MEDIDO

### 0.1 · Hoy hay SIETE lugares que spawnean, y cada uno es dueño de lo que spawnea

| Quién | Dónde | Cuándo muere lo que levanta |
|---|---|---|
| el pool de un run | `platform/assembler/restaurador.py:289` | `recipe_assembler.py:3424-3426` — `finally: for srv in started: srv.stop()` |
| la **Sesión VIVA** | `platform/assembler/session.py:333` | `session.py:450-456` — `close()`, idempotente |
| la **acción aprobada** | `platform/assembler/recipe_assembler.py:3574` | `recipe_assembler.py:3621` — inmediato |
| el **verificador** (y el calentador, que lo llama) | `product/backend/app/phase1/conexiones_verificador.py:329` | `:355`, `:360`, `:520` — y un **segundo spawn** para la prueba doble en `:507`, cerrado en `:513` |
| el **probe BYO** | `platform/inspection/byo_mcp.py:322` | `:329`, `:348` |
| **Motor B** | `platform/inspection/inspect_run.py:90` | `:92` |
| `dispatch/liveness` | `platform/inspection/dispatch/liveness.py:131` | `:141` — *sin cablear a ninguna ruta* |

**El patrón es siempre el mismo: quien lo levanta lo mata, en un `finally`.** No hay una
tabla de vivos, no hay un archivo de PIDs (medido: no existe ninguno en el árbol), y nadie
sabe qué levantó otro.

### 0.2 · El costo de que nadie sostenga

`product/backend/app/phase1/calentar_cinturon.py:9-14` lo dice con todas las letras, y es
el punto de partida de este diseño:

> ⚠️ CALIENTA, NO SOSTIENE. Los servidores se apagan al terminar de medir. Sostenerlos entre
> el «abrir» y el primer mensaje exige un dueño del ciclo de vida que hoy no existe —quién los
> mata, qué pasa con N agentes abiertos, qué pasa si el sidecar reinicia, el techo de memoria—
> y un dueño a medias filtra procesos, que es la clase de bug que ya costó 9 GB de `_MEI`
> huérfanos.

O sea: **hoy el usuario paga el arranque DOS veces.** Una al abrir (el calentador mide y
apaga) y otra en el primer mensaje (el run levanta de nuevo). Ese es el §6 que este diseño
viene a cerrar.

### 0.3 · Cuánto cuesta un server, medido hoy en esta máquina

Cinco servers reales del registro, RSS del **árbol completo** (`ps -eo pid,ppid,rss,command`,
descontando el ruido del propio `ps`):

| entidad | runtime | procesos | RSS |
|---|---|---|---|
| `sqlite` | uvx | **2** | 119 MB |
| `fetch` | uvx | **2** | 159 MB |
| `github` | npx | **2** | 168 MB |
| `filesystem` | npx | **2** | 180 MB |
| `context7` | npx | **2** | 199 MB |

**Todo server son DOS procesos**: el lanzador (`uv tool uvx` / `npm exec`) **no se va** —
se queda vivo de padre. Eso importa para §3: un registro de un PID por conexión describe la
mitad del árbol.

**El costo marginal es LINEAL.** Tres instancias de `sqlite`, acumulado: `+116,3 MB` →
`+229,6 MB` → `+342,5 MB`. La segunda cuesta 113 MB y la tercera 113 MB: **compartir páginas
entre instancias del mismo server no ahorra prácticamente nada.** Ése es el argumento
cuantitativo de §2 (refcount) y de §4 (techo).

### 0.4 · Cuánto cuesta el handshake (lo que un dueño ahorra)

Spawn + `initialize` + `tools/list`, con caché de uvx/npx caliente:

| `fetch` | `filesystem` | `context7` | `github` | `sqlite` |
|---|---|---|---|---|
| 274 ms | 485 ms | 538 ms | 691 ms | 819 ms |

Un agente con 6 piezas paga **~3 s** de arranque por run. Sostener la conexión lo lleva a 0
para el segundo mensaje en adelante. Eso es lo que se compra.

### 0.5 · Lo que el sidecar hace HOY al cerrarse

`product/backend/app/main.py:168-182` — el `finally` del lifespan cancela el purge loop, para
el pool de workers y cierra el almacén SQLite. **No mata ningún proceso MCP** — porque no
sabe cuáles hay. Los que quedan vivos los hereda `launchd` y los limpia, si acaso, el
barrido de `_MEI` del próximo arranque (`deploy/fase4/sidecar_serve.py:178-265`).

---

## §1 · CICLO DE VIDA — ¿quién mata y cuándo?

### 1.1 · Las cuatro causas de muerte, en orden de prioridad

| # | Causa | Quién la dispara | Latencia |
|---|---|---|---|
| 1 | **lápida** (`habilitado=false`) | el usuario, desde la card | **inmediata** |
| 2 | **cierre del sidecar** | el lifespan | inmediata, y completa |
| 3 | **techo de recursos** | el dueño (§4) | inmediata sobre la víctima LRU |
| 4 | **ociosidad** | el dueño | ver 1.2 |

**La lápida manda SIEMPRE y va primero.** Es la regla ya sellada en tres lugares
(`conexiones_repo.py:352-362` la escribe; `restaurador.py:183-191` la separa de «¿puedo?»
a propósito; `calentar_cinturon.py:116-117` no calienta lo apagado). Apagar una entidad
**mata su conexión viva ya**, no espera a la ociosidad: si el usuario dice «no corras esto»
y el proceso sigue vivo cinco minutos, la lápida es decorativa.

### 1.2 · Ociosidad: **N = 10 minutos**, y por qué ese número

**Propuesta: 10 minutos sin un `call_tool` ni un `list_tools`.**

La medición de arriba da los dos lados de la balanza:

- **lo que se gana sosteniendo**: 274-819 ms por server, ~3 s por agente de 6 piezas.
- **lo que cuesta sostener**: ~113 MB por conexión, lineal.

10 minutos es la ventana en la que una conversación sigue siendo *la misma* conversación.
Por debajo (2-3 min) se paga el re-arranque en medio de una charla con pausas normales —
leer una respuesta larga, atender otra cosa. Por encima (30-60 min) se sostienen 113 MB por
un usuario que ya se fue.

**No es un número medido: es una apuesta declarada.** Lo honesto es que sea **configurable**
(`ALEPH_DUENO_OCIOSIDAD_S`, default 600) y que el dueño **cuente** los re-arranques por
ociosidad, para que la próxima sesión lo ajuste con datos en vez de con opinión.

**Alternativa descartada — ociosidad por agente abierto en vez de por reloj**: matar cuando
el usuario cierra la pestaña del agente. Se descarta porque el sidecar **no sabe** cuándo se
cierra una pestaña: la Sala es una webview y no hay un `beforeunload` confiable, y un
heartbeat del front para sostener procesos convierte un bug de red en una fuga de memoria.
El reloj no depende de nadie.

### 1.3 · Un server a mitad de un `tool_call` cuando vence la ociosidad

**Propuesta: la ociosidad NO puede interrumpir una llamada en curso. El préstamo (§6) la
bloquea.**

Mientras una entidad está **prestada**, no es candidata a morir por ociosidad ni por techo.
El reloj de ociosidad arranca cuando el refcount llega a 0. Una llamada en curso mantiene el
refcount en ≥1 por construcción.

Esto es medible hoy: `MCPServer._rpc` toma `self._lock` durante toda la llamada
(`platform/assembler/assembler.py:289`), o sea que el cliente viejo ya serializa. **El puente
NO lo hace** — medido: el único `_lock` de `transporte_sdk.py` es el de `_CapturaStderr`
(`:229`), y `call_tool` no toma ninguno. Ver §2.4: eso es una diferencia real que el dueño
tiene que resolver, no heredar sin mirar.

**Alternativa descartada — timeout duro que mata igual**: se descarta porque convierte un
problema de memoria en un problema de corrección. Una tool que tarda 3 minutos (un fetch
grande, un backtest) no está ociosa: está trabajando. Matarla devuelve al usuario un
`-32000` que el diagnóstico va a clasificar como «el server se murió», que es mentira: lo
matamos nosotros. Si hace falta un tope superior, es un **timeout de llamada** (que ya
existe, `rpc_timeout`), no el reloj de ociosidad.

### 1.4 · Cierre del sidecar

**Propuesta: el `finally` del lifespan (`main.py:168`) llama `dueño.apagar_todo()`, que hace
`stop()` sobre cada conexión viva — y `stop()` ya es el cierre del SDK.**

Ese cierre está medido en las sesiones 1-2: cierra stdin, espera 2 s, y **si el hijo no
salió** manda SIGTERM al **grupo** (el hijo nace con `start_new_session=True`) y SIGKILL 2 s
después. Con `fetch` real, cero supervivientes.

⚠️ **Con el matiz que ya se midió y que no hay que olvidar**: el SDK sólo escala **si el
hijo no se muere solo**. Un server bien educado que sale al cerrarse stdin y que dejó hijos
propios los deja huérfanos igual — igual que el cliente viejo. El dueño no arregla eso; lo
que sí hace es **saber quiénes son**, que es lo que permite el barrido de §3.

**El apagado total es en PARALELO**, no secuencial: 12 conexiones × hasta 4 s de escalada
serían 48 s de cierre. `restaurador.py:360-370` ya usa un `ThreadPoolExecutor` para levantar
en paralelo; el apagado copia ese patrón.

---

## §2 · COMPARTIR ENTRE AGENTES

### 2.1 · La clave de una conexión NO es la entidad. Es `(user_id, entity_id)`

El registro ya lo dice: `UNIQUE (user_id, entity_id)` (`platform/db/schema_sqlite.sql:477`).
Una conexión lleva la credencial del usuario adentro del proceso hijo, así que compartir
entre usuarios es una fuga, no una optimización.

**Y esto no es teórico.** `platform/assembler/recipe_assembler.py:844-850` documenta el
incidente que ya pasó:

> el run A podía expandir `${PUPPET_WORKDIR}` / `${*_API_KEY}` contra el env del run B →
> workdir errado + INYECCIÓN de la key BYOK de A en el config de un server de B (fuga
> cross-user)

Se arregló expandiendo sobre el dict del run en vez de sobre `os.environ`. Un dueño que
comparta por `entity_id` a secas **reintroduce exactamente esa fuga**, con otro mecanismo.

### 2.2 · Qué hay adentro de una conexión que impide compartir — medido

| Qué | De dónde sale | ¿Compartible entre dos agentes del MISMO usuario? |
|---|---|---|
| `command`, `args` | fila del registro | **sí** — es de la entidad |
| `env` (credencial expandida) | `credential_broker.make_user_resolver` por `user_id` | **sí**, dentro del mismo usuario |
| `cwd` | fila del registro (`conexiones.cwd`) | **sí** — es de la entidad |
| **`PUPPET_WORKDIR`** | **`tempfile.mkdtemp(prefix="puppet-work-")` POR RUN** (`recipe_assembler.py:802-805`) | ❌ **NO** |

**`PUPPET_WORKDIR` es el que rompe.** Es un temp dir nuevo por run, y hay servers que lo
hornean en el proceso al arrancar: `filesystem` lo usa como **allow-list de directorios** y
`memory` escribe en `${PUPPET_WORKDIR}/memory.json` (`recipe_assembler.py:786-787`). Dos
agentes que compartieran ese proceso compartirían el sandbox de archivos y el archivo de
memoria — que es peor que gastar 113 MB de más.

### 2.3 · La decisión: refcount por `(user_id, entity_id, huella_de_spawn)`

**Propuesta:** la clave de la tabla de vivos es la terna, donde `huella_de_spawn` es un hash
del `(command, args, env efectivo, cwd)` **ya expandidos**. Dos pedidos con la misma huella
comparten proceso y suben el refcount; con huella distinta, son dos conexiones distintas y
conviven.

Consecuencia medida, sin forzar nada:

- `github`, `context7`, `exa`, `zotero`, `sqlite`, `fetch` → **comparten**. Su `env` no
  depende del run: sale de la fila y del llavero del usuario.
- `filesystem`, `memory` y cualquiera que use `${PUPPET_WORKDIR}` → **no comparten**, porque
  su huella cambia por run. **No es una excepción cableada a mano: cae sola de la regla.**

**Alternativa descartada A — compartir por `entity_id` y punto**: es lo que pide la
intuición y es la fuga de 2.1. Descartada.

**Alternativa descartada B — declarar en el catálogo qué entidad es compartible**: una
lista a mano que hay que mantener y que se desactualiza el día que un belt agrega
`${PUPPET_WORKDIR}` a su config. La huella lo deduce del dato real. Descartada por la misma
razón por la que el spec del bundle declara «LA REGLA, no la lista de excepciones».

**Alternativa descartada C — hacer `PUPPET_WORKDIR` por-usuario en vez de por-run**, para
que todo comparta. Es tentador y **cambia el aislamiento entre runs**, que es una decisión
de producto con consecuencias de seguridad (dos runs del mismo usuario verían los archivos
del otro). No entra en un diseño de transporte. Se anota en §9.

### 2.4 · Concurrencia sobre una conexión compartida — el hueco que abre el SDK

Dos agentes compartiendo un proceso pueden llamar **a la vez**. Medido:

- el cliente viejo **serializa**: `_rpc` toma `self._lock` toda la llamada
  (`assembler.py:289`).
- el puente **no**: `ServidorSDK.call_tool` no toma ningún lock (`transporte_sdk.py:470-487`;
  el único `_lock` del módulo es el de `_CapturaStderr`, `:229`).

JSON-RPC correlaciona por `id`, así que el SDK **soporta** concurrencia — pero nunca la
ejercitamos, y el spawn compartido sería la primera vez.

**Propuesta: el dueño serializa por conexión (un lock por entrada de la tabla) en v1**, y se
mide la concurrencia real antes de soltarla. Costo: dos agentes que llaman a `github` a la
vez se encolan. Es el mismo comportamiento que hoy tienen dos runs *dentro* del cliente
viejo, así que no es una regresión — es no estrenar una capacidad sin medirla.

**Alternativa descartada — soltar la concurrencia desde v1**: se descarta porque el primer
síntoma de un cruce de respuestas sería una tool devolviendo el resultado de otra, y eso
aparece como «el server contestó cualquier cosa» tres pantallas más tarde. Estrenar
concurrencia y estrenar proceso compartido en el mismo commit hace indistinguible cuál de
las dos rompió.

---

## §3 · REINICIO Y READOPCIÓN

### 3.1 · Dónde vive el registro de procesos

**Propuesta: `aleph_paths.procesos_path()` → `<data_root>/procesos.jsonl`**, junto a
`outbox_path()` (`platform/aleph_paths.py:132`). El precedente exacto ya está: la sesión de
rutas movió los diez resolvedores a `aleph_paths` justo para que nada quedara bajo el bundle
(`_MEIPASS` se borra al cerrar).

**Alternativa descartada — en la base**: el registro de conexiones es la fuente de verdad de
*qué tiene equipado el usuario*, no de *qué procesos hay ahora*. Meter PIDs ahí mezcla una
tabla que sobrevive reinstalaciones con un dato que no sobrevive un reboot, y obliga a una
migración de schema para algo efímero. Descartada.

### 3.2 · Formato, y **cuándo** se escribe

Una línea JSON por conexión, **escrita ANTES del spawn** y con `fsync`:

```json
{"clave": "<user>|<entity>|<huella>", "entity_id": "github", "user_id": "…",
 "comando": "npx", "args": ["…"], "nacido_en": 1754...,
 "pid": null, "pids": [], "estado": "naciendo"}
```

y **re-escrita** apenas el spawn devuelve, con `pid` y `pids` (los DOS del árbol, ver 0.3) y
`estado: "vivo"`.

**El orden es la garantía, y es la restricción sellada**: *huérfanos imposibles POR
CONSTRUCCIÓN — todo PID nace registrado ANTES del spawn*. La línea `naciendo` sin `pid` es
lo que cubre la ventana entre el `fork` y el momento en que sabemos el pid: si el sidecar
muere justo ahí, el próximo arranque ve una entrada `naciendo` con `comando` y `nacido_en`,
y **puede barrer por comando+hora aunque no tenga el pid**.

**Alternativa descartada — escribir después del spawn**: es la ventana por la que se
escaparon los 9 GB de `_MEI`. Un proceso que existe y no está anotado es, por definición, un
huérfano en potencia. Descartada.

### 3.3 · Readopción con verificación de identidad

Los PIDs se reciclan. El diseño copia la doctrina que ya está escrita en el barrido de
`_MEI` (`deploy/fase4/sidecar_serve.py:237-256`), que se **autoverifica**:

> si el barrido no encuentra nuestro propio PID entre los procesos que cree nuestros,
> entonces no está mirando lo que cree, y la respuesta honesta es `None` — «no sé» — que
> hace que no se borre nada.

Al arrancar, por cada línea del `procesos.jsonl`:

1. ¿existe el pid? (`os.kill(pid, 0)`) — si no, **entrada muerta**.
2. ¿su `command` coincide con el anotado? (`ps -o command=`) — si no, **pid reciclado**.
3. ¿su hora de arranque es **posterior** a `nacido_en` menos tolerancia? (`ps -o lstart=`) —
   si no, **pid reciclado**.
4. Si 1-3 dan sí: **candidato a readopción**.

**Y acá viene la decisión incómoda: un candidato verificado NO se readopta en v1. Se mata.**

**Por qué.** Readoptar significa recuperar los *streams* stdin/stdout del proceso, y esos
descriptores murieron con el sidecar anterior. No hay forma de volver a hablarle a un MCP
stdio cuyo padre se fue: el protocolo vive en el pipe, no en el pid. Readoptar de verdad
exigiría un transporte distinto (socket, o un supervisor intermedio que sobreviva al
sidecar), que es otro diseño.

Entonces la operación honesta al arrancar es **barrer, no readoptar**: matar todo lo anotado
que siga vivo y verificado como nuestro, y vaciar el archivo. El usuario paga un handshake
(274-819 ms) la primera vez después de un reinicio, que es exactamente lo que paga hoy.

**Lo que sí se gana, y es todo el punto:** hoy esos procesos **no se matan** — sobreviven al
reinicio del sidecar y sólo los caza el barrido de `_MEI`, que mira directorios, no procesos.
Con el archivo, un reinicio deja **cero** MCPs colgados.

**Alternativa descartada — readopción real por socket**: cambiar el transporte de todos los
servers stdio a un socket para poder reconectar. Es rehacer el transporte que acabamos de
migrar, y los servers del catálogo hablan stdio porque así los publican sus autores.
Descartada por costo desproporcionado frente a 800 ms.

---

## §4 · TECHO DE RECURSOS

### 4.1 · El número

Con ~113 MB por conexión (0.3, marginal medido):

| vivos | RSS |
|---|---|
| 6 | ~0,7 GB |
| **8** | **~0,9 GB** |
| 12 | ~1,4 GB |
| 20 | ~2,3 GB |

**Propuesta: tope de 8 conexiones vivas simultáneas, configurable
(`ALEPH_DUENO_MAX_VIVAS`, default 8).**

8 es lo que entra en ~1 GB, que es un techo defendible para una `.app` de escritorio que
además tiene adentro un sidecar Python de 164 MB y una webview. Y con refcount (§2.3), 8
conexiones alcanzan para **más de 8 piezas**: los agentes comparten `github`, `context7`,
`exa`.

### 4.2 · El tope de 12 del calentador NO se hereda: se subordina

`calentar_cinturon.py:46` tiene `MAX_PIEZAS = 12`. **Son dos topes distintos y hay que
decirlo:** 12 es cuántas piezas se **miden** al abrir (un tope de *latencia* — 12 handshakes
secuenciales); 8 es cuántas quedan **vivas** (un tope de *memoria*).

**Propuesta:** el calentador sigue midiendo hasta 12, y **le pide al dueño** las que quepan.
Las que no entren se miden como hoy (spawn → medir → apagar) y se reportan medidas pero no
sostenidas. Lo medido y no sostenido **se reporta por nombre**, igual que hoy se reporta
`sin_medir` (`calentar_cinturon.py:121-122`) — nunca se pierde en silencio.

### 4.3 · La víctima: LRU, con dos exclusiones duras

Cuando entra la novena y el tope es 8, muere la **menos recientemente usada**, salvo:

1. **las prestadas** (refcount > 0) — nunca. Ver §1.3.
2. **la que se está pidiendo** — obvio, pero hay que escribirlo: un tope de 1 con una
   entidad prestada no puede hacer que el dueño se mate a sí mismo.

Si TODAS las vivas están prestadas y llega un pedido nuevo, **el tope cede y se levanta
igual**, con un evento de sobrecupo. La alternativa —hacer esperar al usuario a que otro
agente suelte— convierte un techo de memoria en un deadlock de producto.

**Alternativa descartada — matar por tamaño (la más grande primero)**: suena eficiente y es
peor. La más grande suele ser la más usada (`context7`, 199 MB), así que se paga su handshake
una y otra vez. LRU aproxima «la que no vas a necesitar».

---

## §5 · FRONTERA CON REPAIR

### 5.1 · Qué es repair hoy, medido

`product/backend/app/phase1/remedios_conectores.py:1-12`: una **cascada de propuestas**, con
orden sellado, que **nunca ejecuta** (`:10-11`) — devuelve un `remedio_id` que el endpoint resuelve del
lado servidor y que exige `confirmado:true`. Y `restaurador.py:44` es explícito: *«NO
reintenta, no hace backoff, no repara»*. Medido: **no hay un solo reintento en el árbol**.

### 5.2 · Lo que el dueño expone: un evento tipado, y nada más

El dueño **detecta** la muerte por dos vías, las dos ya medidas en la sesión 2 del SDK:

- el proceso salió → `diagnostico()["murio"] = True` (EOF del pipe de stderr);
- una llamada devolvió `-32000 Connection closed` (`traductor_errores.CONEXION_MUERTA`).

y emite **`conexion.murio`**:

```json
{"clave": "...", "entity_id": "github", "cuando": 1754...,
 "como": "sin_respuesta",              // causa TIPADA nuestra, vía traductor_errores
 "codigo": -32000,                     // el del SDK, si lo hubo
 "stderr": "…",                        // con los caps de siempre: 32 KB · 80 líneas
 "exit_code": null,                    // None es «no medible», jamás un cero inventado
 "prestada_a": ["run:abc", "sesion:def"]}
```

Los campos son exactamente los que `diagnostico_conectores` ya sabe leer
(`diagnostico_conectores.py:61`, `_evidencia_publica`), así que repair no aprende un
vocabulario nuevo. **Y `stderr` no lleva llaves**: el evento se arma desde `diagnostico()`,
que ya está acotado y ya pasa por el scrubber del veredicto.

### 5.3 · El `reconnect-once` perezoso vive en el **DUEÑO**, no en repair

**Propuesta:** si `pedir(entidad)` encuentra su entrada muerta, el dueño **la vuelve a
levantar una vez, en silencio**, y lo cuenta. Si el re-levantado también falla, ahí sí emite
`conexion.murio` y devuelve el fallo.

**Por qué en el dueño y no en repair.** Son dos cosas distintas con dos nombres parecidos:

- **re-levantar** es *el dueño haciendo su trabajo*: nadie pidió una conexión «viva desde
  hace 10 minutos», pidieron **una conexión**. Que el proceso se haya muerto mientras nadie
  miraba es un detalle de implementación del dueño, igual que hoy cada run levanta el suyo
  sin llamarle a eso «reparar».
- **reparar** es *cambiar algo del mundo* para que la próxima vez ande: instalar un runtime,
  pedir una credencial, corregir un comando. Eso exige `confirmado:true` y una decisión
  humana (`remedios_conectores.py:10-11`).

**Y el límite es duro: UNA vez, por pedido, sin backoff.** Un dueño que reintenta en bucle
es un dueño que oculta un server roto detrás de latencia, y el diagnóstico —que es lo mejor
que tiene este árbol— deja de ver el fallo. Si el segundo intento falla, el fallo sale
entero, con su stderr.

**Alternativa descartada — reconnect en repair**: repair tendría que suscribirse al evento,
decidir, y pedirle al dueño que levante — tres saltos para lo que el dueño ya iba a hacer,
y una ventana en la que el consumidor está esperando una conexión que nadie está levantando.
Descartada.

**Alternativa descartada — sin reconnect (que falle y que repair proponga)**: es más puro y
peor para el usuario. Un server que se murió por un OOM del sistema hace 8 minutos haría
fallar el primer mensaje del usuario con un diagnóstico correcto pero inútil («murió»),
cuando levantarlo de nuevo funciona. Descartada.

---

## §6 · LA API DEL DUEÑO

```python
# platform/inspection/dueno.py — SINGLETON por proceso del sidecar

def pedir(user_id, entity_id, *, spec, motivo) -> Prestamo
def estado() -> dict
def apagar(clave, *, motivo) -> bool
def apagar_todo(*, motivo) -> int
```

### 6.1 · El préstamo es un context manager, y esa es la decisión

```python
with dueno.pedir(uid, "github", spec=spec, motivo="run:abc") as prestamo:
    tools = prestamo.list_tools()
    salida = prestamo.call_tool("search_code", {...})
# al salir: refcount--, arranca el reloj de ociosidad. El proceso NO se mata.
```

`Prestamo` expone **la misma interfaz sync de siempre** —`list_tools`, `call_tool`,
`diagnostico`— y **no expone `stop()`**. Ésa es la frontera: quien pide una conexión no
puede matarla. Para eso está `apagar(clave, motivo)`, que es del dueño y de la lápida.

**Alternativa descartada — `pedir()`/`soltar()` sueltos**: el brief los nombraba y es la
forma obvia. Se descarta porque **un `soltar()` que no se llama es una fuga**, y el árbol
tiene siete lugares que hoy hacen `finally: srv.stop()` justamente porque sin `finally` se
escapan procesos. Un context manager hace el `finally` obligatorio. `soltar()` queda como
método interno del préstamo, para el caso raro de un consumidor que no puede usar `with`.

### 6.2 · Qué pasa si el proceso muere MIENTRAS está prestado

**Propuesta: el préstamo se entera en la llamada, no antes.** `call_tool` devuelve el string
de error de siempre (`[MCP error: {'code': -32000, …}]`), que es exactamente lo que el
consumidor ya sabe leer y lo que `traductor_errores.contesto()` ya clasifica. El dueño, en
paralelo, marca la entrada muerta y emite `conexion.murio`.

**El dueño NO re-levanta bajo un préstamo vivo.** Re-levantar en medio de un préstamo
devolvería un proceso *nuevo* al consumidor sin decírselo: sin el estado de la sesión MCP,
sin el `initialize` que el consumidor cree haber hecho, y con los `id` de JSON-RPC
reiniciados. Eso es peor que un error honesto. El reconnect-once (§5.3) es **al pedir**, que
es el único momento en que el consumidor todavía no cree nada.

### 6.3 · `estado()` — la tabla de vivos

```json
{"vivas": [{"clave": "...", "entity_id": "github", "user_id": "…",
            "pids": [4711, 4712], "nacida_en": 1754..., "ultimo_uso": 1754...,
            "refcount": 2, "prestada_a": ["run:abc", "sesion:def"],
            "transporte": "sdk-stdio", "rss_kb": 172000}],
 "tope": 8, "ociosidad_s": 600,
 "eventos": {"reconnect_once": 3, "muertes": 1, "desalojos_lru": 0, "sobrecupo": 0}}
```

Los contadores no son adorno: son con lo que se ajusta el `N=10 min` de §1.2 y el `8` de §4.1
en la sesión siguiente, con datos en vez de con opinión. `rss_kb` es best-effort (`ps`), y si
no se puede medir va `null`, no 0.

---

## §7 · MIGRACIÓN SIN BIG BANG

El orden lo decide **qué tan reversible es cada paso**, no qué tan valioso.

| # | Consumidor | Por qué en ese orden | Vara verde que lo cierra |
|---|---|---|---|
| **1** | **el verificador** (`conexiones_verificador._spawn`) | Es el único que hoy **mide y apaga** en el mismo aliento. No sostiene nada, así que pasarlo al dueño **no cambia el ciclo de vida de nada** — sólo cambia quién hace el spawn. Es el paso más barato de revertir. | `verify_migracion_stdio.py` **sin tocar**: los mismos 9 de 9 veredictos idénticos. Es la vara heredada del SDK y sirve tal cual. |
| **2** | **el calentador** (§6) | Acá aparece el valor: el calentador deja de apagar y **sostiene** hasta el tope. Es el primer paso con conexiones vivas entre requests. | `verify_calentador_restore_sdk.py` parte A sigue dando el mismo veredicto por pieza + **nueva**: tras calentar, `estado()` muestra las piezas vivas, y a los N minutos el reloj las apaga. |
| **3** | **el run** (`restaurador` ← `assemble_and_run`) | El que de verdad cierra el §6: el primer mensaje ya no paga el spawn. Es el más riesgoso porque toca el pool de un run y el refcount se estrena de verdad. | La regresión completa en los dos entornos + **nueva**: dos runs del mismo usuario con `github` levantan **UN** proceso (`estado().refcount == 2`), y `filesystem` levanta **dos** (huellas distintas — §2.3). |
| **4** | **la Sesión VIVA** (`session.py`) | Último porque es el único con estado conversacional propio y el que menos gana (ya sostiene entre mensajes por su cuenta, `session.py:450`). | La Sesión sigue cerrando sin dejar procesos, y al cerrar **no mata** una conexión que otro agente tiene prestada. |

**Qué convive durante la transición.** Exactamente el mismo patrón que funcionó con el SDK:
el dueño arranca detrás de una perilla, `ALEPH_DUENO=off|on` (default `off` hasta el paso 3),
leída **en un solo lugar**, y quien no está migrado sigue spawneando como hoy. Un proceso
levantado por el dueño y uno levantado a mano **conviven sin verse** — el único riesgo real
es contar dos veces la memoria, y por eso el tope de §4 se aplica sólo a lo que el dueño
levantó, que es lo único que puede desalojar.

**Y la vara de cada paso es la misma que la del SDK, por la misma razón:** si un veredicto
cambia de valor para el mismo servidor, es un bug de la migración, no una mejora. Se reporta
y se para.

---

## §8 · CÓMO CADA RESTRICCIÓN SELLADA QUEDA RESPETADA

| Restricción | Dónde la respeta este diseño |
|---|---|
| **la lápida manda SIEMPRE** | §1.1 — causa de muerte #1, inmediata, por encima de la ociosidad y del techo |
| **UPDATE jamás upsert** | El dueño **no escribe el registro de conexiones**. Su archivo es otro (`procesos.jsonl`, §3.1) y es efímero. Quien persiste mediciones sigue siendo el verificador |
| **FALLO VISIBLE, JAMÁS MUDO** | §5.2 (`conexion.murio` tipado) · §4.2 (lo medido y no sostenido se reporta por nombre) · §4.3 (evento de sobrecupo) · §6.3 (contadores) |
| **el PATH del hijo sale de Aleph** | El dueño spawnea por `inspection.transporte`, que ya fuerza `entorno_hijo()` (`transporte_sdk.py:171-183`). No se agrega un segundo camino de spawn |
| **llaves jamás en logs** | El evento de §5.2 se arma desde `diagnostico()`, que ya está acotado; la tabla de §6.3 publica `entity_id` y `pids`, nunca `env` |
| **el registro es fuente única** | El `spec` con el que se pide una conexión sale del registro, como hoy (`restaurador.py:238-252`, `_cfg_desde_fila`). El dueño no tiene una segunda opinión sobre qué comando corre una entidad |
| **huérfanos imposibles POR CONSTRUCCIÓN** | §3.2 — la línea se escribe **antes** del spawn, con `fsync`, y la entrada `naciendo` cubre la ventana en que todavía no hay pid |
| **el guard de calentar-persiste** | §7 paso 2: la vara del calentador ya corre con `_ConnSinCommit` y **se mantiene**. Una vara que para medir cambia lo que mide no es una vara |

---

## §9 · LO QUE ESTE DISEÑO NO CUBRE

Honestamente, y en orden de cuánto puede doler:

1. **La readopción de verdad.** §3.3 decide **barrer, no readoptar**, porque los pipes
   mueren con el padre. Un usuario que reinicia el sidecar paga el handshake de nuevo. Si
   algún día eso duele, la salida es un supervisor que sobreviva al sidecar — otro diseño,
   más caro que lo que ahorra hoy.

2. **`PUPPET_WORKDIR` por-run sigue siendo por-run.** §2.3 alternativa C: hacerlo
   por-usuario haría compartibles a `filesystem` y `memory`, pero cambia el aislamiento
   entre runs del mismo usuario. Es una decisión de producto con consecuencias de seguridad
   y no entra acá.

   > **MEDIDO EN D4, y es más caro de lo que este párrafo hacía pensar.** No afecta sólo a
   > `filesystem` y `memory`: como la huella hashea el env COMPLETO, basta que
   > `PUPPET_WORKDIR` difiera para partirla en **todas** las piezas, incluso las que nunca
   > leen la variable (`sqlite`, `github`, `fetch`).
   >
   > | quién | qué workdir |
   > |---|---|
   > | el calentador (`motor_verdad._entorno_de_belts`) | `…/T/aleph-probe-workdir` — fijo |
   > | cada run (`recipe_assembler._puppet_run_env:802-805`) | `…/T/puppet-work-XXXXXX` — `mkdtemp` NUEVO por run |
   >
   > Consecuencias, verificadas en `verify_run_dueno.py` §5:
   > · **el primer mensaje NO reusa el cinturón que dejó el calentador** — pagó 3 spawns
   >   sobre 3 piezas ya calientes, 0 reusos;
   > · **dos runs tampoco comparten entre sí**, por el mismo motivo;
   > · o sea que **el arranque doble del §6 sigue vivo**, y no por el recableo del dueño
   >   —que funciona— sino por esta decisión pendiente.
   >
   > Las salidas posibles, todas fuera del alcance de D4:
   > (a) `PUPPET_WORKDIR` estable por `(usuario, agente)` — la más directa, y la que cambia
   >     el aislamiento entre runs;
   > (b) que la huella ignore un conjunto DECLARADO de variables — reintroduce la lista de
   >     excepciones que §2.3 descartó, y una variable mal declarada sí cruzaría procesos;
   > (c) que el calentador use el workdir del *próximo* run — imposible: todavía no existe.

3. **La concurrencia sobre una conexión compartida queda serializada en v1** (§2.4). No se
   midió cuánto cuesta esa cola con dos agentes activos sobre la misma entidad. Si duele, se
   mide y se suelta — pero después, no en el mismo commit.

4. **Los `N=10 min` y `tope=8` son apuestas, no mediciones.** Están declarados como tales,
   son configurables, y §6.3 instrumenta lo necesario para corregirlos con datos.

5. **El transporte HTTP no entra.** Todo este diseño es sobre **procesos**. Una conexión
   HTTP (`ClienteSdkHttp`) no tiene pid, no ocupa 113 MB y no puede quedar huérfana. Sostener
   sesiones HTTP entre requests es otra pregunta (con `Mcp-Session-Id` y su expiración), y
   mezclarla acá haría que «el dueño de los procesos» dejara de significar algo preciso.

6. **La memoria se mide con `ps rss`, que sobrecuenta páginas compartidas.** El costo
   marginal medido (113 MB, lineal) sugiere que la sobrecuenta es chica para *instancias
   distintas del mismo server*, pero no se midió con `footprint`/`vmmap`. Los números de §4.1
   son un techo, no una precisión.

7. **Multi-usuario real.** La clave es `(user_id, entity_id, huella)` y eso es correcto, pero
   la `.app` de escritorio tiene un usuario. El diseño no se probó con dos sesiones de dos
   usuarios sobre el mismo sidecar.

8. **Qué pasa si el archivo de procesos se corrompe** (disco lleno a mitad de un `fsync`).
   La respuesta obvia es «una línea ilegible se saltea y se reporta», pero no está diseñado
   el barrido de una entrada que no se puede parsear y que sí dejó un proceso vivo.

---

## §10 · PLAN DE CONSTRUCCIÓN

| Sesión | Qué se construye | Vara verde que la cierra |
|---|---|---|
| **D1** | `platform/inspection/dueno.py`: tabla de vivos, refcount, huella de spawn, préstamo como context manager, `estado()`. **Sin cablear a nadie** — perilla en `off`. Y el `procesos.jsonl` con su escritura pre-spawn. | Vara nueva `verify_dueno.py`: dos pedidos de la misma huella dan **un** proceso · huellas distintas dan **dos** · el préstamo bloquea el desalojo · matar el proceso a mano deja la entrada muerta y emite el evento · el archivo tiene la línea `naciendo` **antes** de que exista el pid (verificable matando entre medio). Regresión completa sin cambios: el dueño todavía no lo usa nadie. |
| **D2** | Ciclo de vida: reloj de ociosidad, tope + LRU, `apagar_todo()` en el lifespan, barrido de arranque. | Vara: una conexión ociosa muere a los N s y no antes · una prestada **no** muere · el tope desaloja al LRU y nunca a una prestada · tras un `apagar_todo()` no queda **ningún** proceso (`ps`) · tras un reinicio simulado, el barrido mata lo anotado y no toca un pid reciclado (verificable con un proceso ajeno que reusa el pid). |
| **D3** | Migración pasos 1 y 2 (verificador → calentador). Perilla `ALEPH_DUENO=on`. | `verify_migracion_stdio.py` **sin tocar**: 9/9 idénticos · `verify_calentador_restore_sdk.py` parte A idéntica **+** las piezas quedan vivas en `estado()` y el reloj las apaga. Regresión completa en los dos entornos. |
| **D4** | Migración paso 3 (el run). **Acá muere el §6**: el primer mensaje deja de pagar el spawn. | Dos runs del mismo usuario comparten `github` (`refcount==2`, un solo par de pids) y no comparten `filesystem` · el ahorro medido de punta a punta (ms del primer mensaje, antes vs después) · regresión completa · las 4 varas del SDK verdes. |
| **D5** | Migración paso 4 (Sesión VIVA) + retiro del `ALEPH_TRANSPORTE=viejo` **si la certificación en `.app` ya pasó** (deuda abierta de la sesión 3 del SDK). | La Sesión cierra sin matar lo prestado por otro · regresión completa · certificación en `.app` con el ciclo abrir → escribir → cerrar y **cero** procesos MCP después. |

**Lo que NO se construye hasta que D1 y D2 estén verdes: nada que cablee un consumidor.** Un
dueño a medias filtra procesos, y eso ya costó 9 GB una vez.
