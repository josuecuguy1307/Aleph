# DISEÑO · REPAIR v1

**Escrito:** 2026-08-03 · **Base:** `main @ 71b446f` (el dueño completo, D1-D5 + §9.2)
**Estado:** DISEÑO. Cero código de producto en esta rama.

Este documento decide **qué pasa cuando algo falla DESPUÉS de estar conectado**. Cada
afirmación sobre el árbol lleva su `archivo:línea`. Cada decisión lleva la alternativa que
se descartó y por qué.

> ### ESTADO DE CONSTRUCCIÓN
>
> | sesión | estado |
> |---|---|
> | **R1** — el evento y nada más | **CONSTRUIDA** · `verify_evento_muerte.py` |
> | **R2** — la clasificación, pura | **CONSTRUIDA** · `repair_clasificar.py` + `test_repair_clasificar.py` (48 tests) |
> | **R3** — el camino temporal | **CONSTRUIDA** · `repair.py` + `test_repair.py` (35) + `verify_repair_temporal.py`. Perilla `ALEPH_REPAIR`, default **off** |
> | **R4** — el camino permanente | **CONSTRUIDA** · `repair_fijar_version.py` + `test_repair_boton.py` (34) |
> | **R5** — la escalada y el fantasma | **CONSTRUIDA** · el auto-ajuste + `test_repair_escalada.py` (19) + `verify_repair_e2e.py` |
>
> **REPAIR ESTÁ COMPLETO.** Perilla `ALEPH_REPAIR`, default **off**.
>
> ⚠️ **§1.1 describe el árbol ANTES de R1 y se deja tal cual**, porque es el diagnóstico que
> justifica todo lo demás — borrarlo dejaría las decisiones sin su porqué. Lo que R1 cambió:
> el dueño ahora **emite** un evento tipado por muerte (`dueno.Dueno.suscribir`), y **se
> entera aunque nadie pida**, por el push del EOF del transporte y por el vigía del
> cosechador como red de seguridad. Los timeouts quedan anotados con su reloj (§6).
>
> ⚠️⚠️ **CORRECCIÓN DE DISEÑO SELLADA POR PERSONA USUARIA (R5) — el §4.2.1 cambia de dueño.**
>
> **El ajuste de versión es AUTOMÁTICO, sin botón y sin confirmación.** La receta es
> territorio de **Aleph**, no del usuario: corregirla no exige permiso. El §4.2.1 la trataba
> como una acción con efecto que pedía confirmar, y eso le mandaba al usuario un trámite por
> un problema que no creó.
>
>     server viejo + versión buena conocida
>       → repair corrige la receta (UPDATE a la fila · JAMÁS al catálogo)
>       → relevanta → VIVO: ✅, y en el [?] queda «se ajustó automáticamente el <fecha>».
>                     El usuario no ve card ni botón.
>       → si NO alcanza: recién ahí card + escalada con traza. UN intento, sin loops.
>
> Los botones quedan SOLO para territorio del usuario: **[Revisar llave]** ·
> **[Instalar lo que falta]** · la escalada. `servidor_incompatible` sale de `CAMINOS` y pasa
> a `SIN_BOTON`. **El candado jamás-al-catálogo y los seis negativos de R4 siguen intactos**:
> lo único que cambió es QUIÉN dispara la acción ya construida.
>
> ⚠️ **R4 CORRIGIÓ UN SUPUESTO DEL §4.2.1.** El paso 2 decía que el pin propuesto sale del
> registro: «la última versión que dio veredicto verde». Medido antes de construir:
> `server_info` estaba **VACÍO en las 42 filas** y `ultimo_veredicto` **NULL en las 42**. El
> transporte SÍ captura el `serverInfo` del saludo, pero `conexiones_verificador` sólo
> persistía `conexion` y `credencial` — el dato que el botón necesita no existía. R4 lo
> graba (sólo cuando el veredicto es VIVO: la versión de un server roto no es «la que
> anduvo») y, mientras no haya una versión buena conocida, **no propone un pin**: pinear la
> que corre sería congelar la rotura.
>
> La otra medición del §4.1 sí se confirmó: **la línea de estado ALCANZA**. La tabla canónica
> `CAMINOS` (`cuarto.semaforo.js`) ya tenía botón para 11 de las 12 causas permanentes; R4
> agregó UNA entrada (`servidor_incompatible` → [Fijar la versión]) y **cero UI nueva**.
>
> ⚠️ **R3 CORRIGIÓ UN SUPUESTO DEL §3.** El diseño hablaba de que repair «reintenta», y no
> puede: `_Conexion` guarda command/args/cwd y **NO el `env`** (`dueno.py:442-450`), que es
> donde viven las credenciales resueltas. Nadie puede reconstruir un spec para re-spawnear.
> Repair quedó como **política** y el dueño como **actor**: repair observa, cuenta, abre el
> breaker y contesta si el próximo `pedir()` pasa (hook `dueno.poner_guardia`). Es mejor que
> lo diseñado — repair no spawnea (la frontera del §8 de `test_frontera_dueno` sigue intacta)
> y no toca una credencial ni de lejos, o sea que el §3.5 se cumple por construcción.
>
> R2 agrega **dos causas del verificador que el §2.2 no lista** (`sin_tools`,
> `sin_tool_sondeable` → permanentes, escalada): la tabla del diseño salió del vocabulario
> del motor y ésas son del verificador. Queda declarado acá y en el módulo.
>
> Las citas de este documento se re-numeran cuando el código se mueve, y eso lo obliga
> `verify_citas_diseno_repair.py`: R1 movió 20 líneas citadas y la vara las cazó todas.

---

## §0 · EL PUNTO DE PARTIDA (sellado, no se re-discute)

**Repair es el verbo que decide qué pasa cuando algo falla después de estar conectado.**

    detectar → clasificar → temporal se arregla callado
                          → permanente va directo al botón correcto
                          → escalada a humano CON TRAZA

La frontera con el dueño ya está sellada en `DISEÑO-DUEÑO-v1.md`: **«re-levantar es el dueño
haciendo su trabajo; reparar es cambiar el mundo».** El comentario vive en el código:
`dueno.py:925` — `# RECONNECT-ONCE (§5.3) — el dueño haciendo su trabajo, no repair.`

Y de ahí sale la restricción madre de todo este documento:

> **reparar = cambiar el mundo = las acciones con efecto piden confirmación.**

### 0.1 · Lo que NO es repair

| no es | por qué |
|---|---|
| reintentar la tool que falló | eso es del loop del agente, y repetir una tool con efecto es repetir el efecto |
| re-levantar una vez | ya lo hace el dueño (`dueno.py:926-929`) |
| medir el catálogo | ya lo hace el verificador (`conexiones_verificador.py:498`) |
| pintar la card | ya lo hace el Centro (`centro_conexiones.py`, 1.812 líneas) |
| una taxonomía nueva | hay dos y se usan las dos — §2 |

---

## §1 · LA FRONTERA EXACTA DUEÑO / REPAIR

### 1.1 · LO MEDIDO: hoy no cruza NADA

Esto es el hallazgo que ordena todo el resto.

**El dueño detecta muerte, pero no la CUENTA a nadie.** Cuando `pedir()` encuentra una
conexión muerta hace tres cosas y ninguna es un evento:

```
dueno.py:926    if self._parece_muerta(con):
dueno.py:927        self._contadores["muertes"] += 1
dueno.py:1165        self._cerrar(con, motivo="murió y se pidió de nuevo")
```

- `self._contadores["muertes"]` es **un entero global del proceso**, publicado en
  `estado()["eventos"]` (`dueno.py:1193`). No dice **cuál** conexión murió, ni de quién era,
  ni cuándo, ni cómo, ni cuántas veces le pasó a esa entidad.
- `_cerrar` (`dueno.py:1152-1171`) borra la fila de la tabla, vuelca el libro y llama a
  `stop()`. **No emite nada.**

**Y la detección es PEREZOSA.** `_parece_muerta` (`dueno.py:1004-1008`) sólo se consulta dentro
de `pedir()` (`dueno.py:926`). Una conexión que muere mientras nadie pide **no se entera
nadie** hasta el próximo `pedir()`, que puede no llegar nunca. El cosechador
(`dueno.py:860`) mira ociosidad, no salud.

**Pero el instante exacto de la muerte YA SE CONOCE, y se tira.** El transporte tiene un
hilo drenando el stderr del hijo, y su `finally` marca la muerte en el EOF del pipe:

```
transporte_sdk.py:296      finally:
transporte_sdk.py:296-297      self._murio.set()
```

`murio` (`transporte_sdk.py:251-257`) está documentado como «lo único observable sobre la
muerte del hijo cuando el transporte no expone el proceso», y `soltar_escritura()`
(`transporte_sdk.py:264-274`) existe **exactamente** para que ese EOF llegue en el momento
de la muerte y no en el `stop()` — con una medición adentro: «`os._exit(7)` en el hijo
dejaba `murio=False`».

O sea: **hay una señal push, precisa, con el stderr de los últimos 32 KB
(`transporte_sdk.py:223`) pegado al lado, y hoy no la consume nadie.** El dueño la ignora y
hace polling con `ps` cuando alguien vuelve a pedir.

> **DECISIÓN 1.A — La frontera se cruza con un EVENTO TIPADO que emite el dueño, alimentado
> por la señal `murio` del transporte, no por el polling de `ps`.**
>
> **Alternativa descartada: que repair haga polling del `estado()` del dueño.** Es lo más
> barato de construir y es lo que el contador de hoy invita a hacer. Se descarta por tres
> mediciones: (a) `estado()["eventos"]["muertes"]` es un escalar — dos muertes de entidades
> distintas son indistinguibles de dos muertes de la misma, y toda la política de §3
> (breaker por entidad) necesita saber cuál; (b) el polling llega tarde por definición y el
> stderr del hijo ya se pudo rotar fuera del buffer de 32 KB; (c) `_cerrar` ya borró la fila
> de `self._tabla` (`dueno.py:1165`), así que para cuando repair mire el `estado()` la
> conexión muerta **ya no está ahí**. Un observador externo no puede reconstruir lo que el
> dueño borró en el mismo lock.

### 1.2 · CUÁNDO exactamente es «caso de repair»

Tres disparadores, y ninguno es «murió».

| # | disparador | por qué ÉSE es el umbral |
|---|---|---|
| **R1** | **segunda muerte de la misma clave dentro de `VENTANA_S`** | la primera muerte es el reconnect-once del dueño: es su trabajo y sale gratis. La segunda dice que re-levantar no alcanza. La clave es `(user_id, entity_id, huella)` (`dueno.py:217-218`) |
| **R2** | **muerte DURANTE un `call_tool`** | acá hay alguien esperando. Aunque sea la primera, el reconnect-once no lo salva: el resultado de esa tool ya se perdió |
| **R3** | **fallo de ARRANQUE** (`start()` devolvió False, o `pedir()` levantó `DuenoError`) | nunca llegó a estar vivo; el reconnect-once no aplica porque no hay nada que re-levantar |

**R1 · el reloj.** `VENTANA_S = 120`. Sale de una medición existente, no de la intuición: el
handshake medido es **274-819 ms** (`DISEÑO-DUEÑO-v1.md:109`), así que 120 s son ~150 handshakes — un margen donde «volvió a morir» significa que
vuelve a morir, no que el reloj era corto. Fuera de la ventana, el contador de esa clave se
resetea y la muerte vuelve a ser gratis.

> **Alternativa descartada: repair desde la PRIMERA muerte.** Convierte cada reinicio normal
> de un server (un `npx` que se actualiza, una máquina que suspende) en un caso de repair con
> breaker y traza. Se descarta porque contradice la frontera sellada: si repair actúa en la
> primera, el reconnect-once del dueño deja de existir de hecho — hace el trabajo y después
> viene otro a rehacerlo.

> **Alternativa descartada para R2: tratarla como una muerte más.** El `call_tool` que se
> comió la muerte devuelve hoy un string `[MCP error: …]` (`dueno.py:624-648`) y el loop
> sigue como si nada. Sin R2, un server que muere en cada llamada y revive en cada `pedir()`
> **nunca** acumula dos muertes en la tabla y es invisible para siempre. R2 es lo que lo caza.

### 1.3 · EL EVENTO (el contrato de la frontera)

```python
MuerteMCP = {
  # QUIÉN
  "clave":       "u-123|github|a1b2c3d4e5f6",   # dueno.py:217-218
  "user_id":     "u-123",
  "entity_id":   "github",
  "huella":      "a1b2c3d4e5f6",
  # CÓMO
  "disparador":  "R1" | "R2" | "R3",
  "motivo":      "murió y se pidió de nuevo",   # el `motivo` de _cerrar, dueno.py:1152
  "stderr":      "...",                          # transporte_sdk.py:592 (tope 32 KB, :223)
  "stderr_lineas": 41, "stderr_bytes": 3120,     # transporte_sdk.py:601-602
  "exit_code":   None,                           # SIEMPRE None y con motivo — ver abajo
  "exit_code_fuente": "no expuesto: stdio_client (mcp 2.0.0)…",  # transporte_sdk.py:594-595
  "murio_por_eof": True,                         # transporte_sdk.py:296
  "senal":       None,
  "pids":        [4471, 4472],                   # dueno.py:1144
  # CUÁNTAS VECES
  "muertes_en_ventana": 2,
  "nacida_en":   1754251200.0,                   # dueno.py:1181
  "vivio_s":     41.7,
  "ts":          1754251241.7,
}
```

**`exit_code` es `None` a propósito y viaja con su motivo.** El transporte lo documenta:
«`exit_code` es `None` SIEMPRE y dice por qué: `stdio_client` no expone el proceso. Inventar
un cero acá sería exactamente el pecado que el contrato de `MCPServer` prohíbe»
(`transporte_sdk.py:584-586`). Repair **no** puede inventarlo: clasifica sin él (§2) y lo
dice en la traza.

**`senal` hoy es `None` y ése es un hueco declarado.** Ver §9.

> **DECISIÓN 1.B — El evento lo emite el dueño, no lo arma repair.** El dueño es el único que
> tiene el `motivo`, la clave y el `srv` en la mano dentro del mismo lock, antes de
> `self._tabla.pop` (`dueno.py:1165`). Que repair lo reconstruya después es imposible por
> construcción.
>
> **Alternativa descartada: que el dueño llame directamente a repair.** Ata el dueño a repair
> y rompe la frontera en la dirección contraria: el dueño pasaría a saber que existe una
> política de reintentos. Se emite a un **suscriptor opcional** (`dueno.suscribir(fn)`); sin
> suscriptor el dueño se comporta exactamente como hoy — que además es lo que mantiene verde
> a `verify_dueno.py` (100 ✓) sin tocarlo.

---

## §2 · CLASIFICACIÓN TEMPORAL / PERMANENTE

### 2.1 · REPAIR NO INVENTA TAXONOMÍA. HAY DOS Y SE USAN LAS DOS.

| taxonomía | dónde | qué cubre |
|---|---|---|
| **causas del motor** — 25 valores | `motor_verdad.py:129-137` (`CAUSAS`) | el vocabulario CERRADO que ya pinta la UI · eran 19 hasta que **gate2 · F1c** sumó las seis selladas (§2.2 bis) |
| **traductor del SDK** — 35 tests | `traductor_errores.py`, `test_traductor_errores.py` (35 casos colectados) | error crudo del SDK → causa nuestra |

El traductor ya expone las cuatro entradas que repair necesita: `codigo_de`
(`traductor_errores.py:87`), `contesto` (`:112`), `causa_de_corte` (`:131`),
`detalle_de_arranque` (`:182`) y `evidencia_de_arranque` (`:228`).

**Y ya existe un precedente de reintentabilidad que repair NO puede contradecir.** El F1 de
gate2 (mergeado en `98756c7`) declara:

```
errores_modelo.py:113-127   _REINTENTABLES = frozenset({
                                SIN_RED, TIMEOUT, RATE_LIMIT, PROVEEDOR_CAIDO, SIN_RUNTIME,
                                CLI_OCUPADO, RUNTIME_OCUPADO, SESION_PERDIDA })   # ← F1c
errores_modelo.py:189-190   reintentable: bool = False
                            retry_after_s: Optional[float] = None
```

> **DECISIÓN 2.A — «temporal» de repair ≡ `reintentable` de `errores_modelo`, extendido a las
> causas de conexión que ese módulo no cubre.** Una sola definición de retryability en el
> producto.
>
> **Alternativa descartada: un enum propio `TEMPORAL/PERMANENTE`.** Se descarta porque
> tendríamos dos listas que dicen lo mismo sobre `TIMEOUT` y `RATE_LIMIT` y que se van a
> separar el día que alguien toque una sola — es el mismo fallo que el adaptador duplicado
> que D5 tuvo que unificar (`dueno.py:544-559`).

### 2.2 · LA TABLA COMPLETA

**El usuario JAMÁS ve las palabras «temporal» ni «permanente».** Son de este documento y del
código; la UI ve `causa` y un botón.

| causa (`motor_verdad.py`) | clase | qué hace repair |
|---|---|---|
| `sin_red` :63 | **temporal** | backoff §3 · 🟡 |
| `timeout` :67 | **gris → §2.3** | backoff §3 con el desempate de 2.3 |
| `rate_limit` :83 | **temporal** | backoff §3, respetando `retry_after_s` si vino |
| `proveedor_caido` :90 | **temporal** | backoff §3 · breaker más corto (§3.4) |
| `error_upstream` :67 | **temporal, 1 sola vuelta** | un reintento; si repite, escala (§5) — **ver §2.2 bis: la fila cambió de significado sin cambiar de valor** |
| `sin_respuesta` (`conexiones_verificador.py:89`) | **temporal** | backoff §3 |
| `arranque` (`:85`) | **gris → §2.3** | depende del stderr |
| `key_invalida` :81 | **permanente** | → **[Revisar llave]** (§4) |
| `falta_key` / `key_ausente` :62,:80 | **permanente** | → **[Conectar]** (§4) |
| `sin_credito` :82 | **permanente** | → **[Revisar llave]** con copy propio |
| `sin_sesion` / `cli_no_logueado` :65,:72 | **permanente** | → **[Reconectar]** (§4) |
| `plan_insuficiente` :76 | **permanente** | → **[Revisar plan]** |
| `modelo_no_disponible` :84 | **permanente** | → **[Revisar llave]** |
| `cli_no_instalado` :64 | **permanente** | → **[Descargar]** (§4) |
| `cli_version_vieja` :71 | **permanente** | → **[Actualizar]** |
| `cli_sin_permisos` :75 | **permanente** | → mano_humana (§4.3) |
| `cli_interactivo_colgado` :74 | **permanente** | → mano_humana |
| `servidor_incompatible` :92 | **permanente** | → **[Fijar la versión]** (§4.2) |
| `no_es_mcp` :93 | **permanente** | → escalada, sin botón: no hay arreglo del usuario |
| `falla_de_aleph` :89 | **permanente** | → **[Copiar el reporte]** — es culpa nuestra, y el código ya lo dice: «la única causa cuyo camino no es un arreglo del usuario» (`motor_verdad.py:85-88`) |
| `fallo_desconocido` :94 | **permanente** | → escalada con traza cruda (§5) |

### 2.2 bis · LAS SEIS DE GATE 2 · F1c, Y LA FILA `error_upstream` RESUELTA

Seis fases de Gate 2 midieron un fallo, no encontraron un nombre que lo dijera sin mentir,
usaron la aproximación más honesta que había y **escribieron el hueco en su propio código**.
F1c los cerró: las seis causas existen en `motor_verdad.CAUSAS` y esta tabla las clasifica.

| causa (nueva) | antes era | clase | qué hace repair |
|---|---|---|---|
| `cli_ocupado` | `rate_limit` + `origen:"aleph"` | **temporal** | backoff §3 · 🟡 |
| `runtime_ocupado` | `timeout` + `motivo` en evidencia | **temporal** | backoff §3 · 🟡 |
| `sesion_perdida` | `falla_de_aleph` | **temporal** | backoff §3 · 🟡 |
| `contexto_excedido` | `error_upstream` | **permanente** | → mano_humana: acortar el pedido |
| `politica_de_contenido` | `error_upstream` | **permanente** | → mano_humana: reformular |
| `turno_detenido` | *sin causa* | **permanente** | → **`sin_alarma`** (§2.2 ter) |

**LA FILA `error_upstream`, RESUELTA.** Su clase no cambia — sigue siendo *temporal, una
sola vuelta* — pero **lo que cubre sí**, y por eso el veredicto ahora es honesto. Hasta F1c
esa fila se comía tres cosas distintas:

1. *el pedido llegó mal armado* (JSON roto, un campo que falta) — reintentar puede salir
   bien: un 400 transitorio existe. **Ésta es la única que la fila sigue cubriendo, y para
   ésta «una vuelta» siempre fue la respuesta correcta.**
2. *el pedido no entra en la ventana* → ahora `contexto_excedido`;
3. *el proveedor se negó por su política* → ahora `politica_de_contenido`.

Las dos que se fueron eran exactamente las que hacían mentir a la fila: **el mismo texto
demasiado largo no va a entrar la segunda vez, y una negativa repetida sigue siendo la misma
negativa**. Se gastaba una llamada entera —tokens del usuario— para volver a leer lo mismo,
y después se escalaba (§5) por algo que no tenía escalada posible. La fila no se toca porque
lo que estaba mal nunca fue la fila: era el cajón.

### 2.2 ter · `sin_alarma` — LA SEXTA ACCIÓN, Y POR QUÉ EL §2.2 NO LA TENÍA

`turno_detenido` es la única causa del vocabulario que **no nombra un fallo**: alguien
apretó «parar» y el sistema hizo lo que se le pidió. La tabla del §2.2 salió de un
vocabulario donde toda causa era un fallo, así que sus cinco acciones dan por sentado que
hay algo roto — y las cinco mienten acá, cada una a su manera:

| acción | qué haría | por qué miente |
|---|---|---|
| `backoff` / `una_vuelta` | reintentar | **deshace la decisión del usuario** — el peor de los cinco |
| `boton` | ofrecer un arreglo | no hay nada que arreglar |
| `mano_humana` | pedir un comando | por su propia acción |
| `escalar` | levantar una alarma (§5) | por un funcionamiento correcto |

Por eso se agrega `SIN_ALARMA`: ni reintento, ni botón, ni escalada, ni alarma. La
invariante «todo permanente termina en algo que el usuario pueda ver» sigue en pie para
todo lo demás — habla de **fallos**, y su test tiene esta única excepción declarada por
nombre, para que una segunda causa no pueda esconderse ahí.

### 2.3 · LOS GRISES, Y CÓMO SE DESEMPATAN

**`timeout` — ¿red caída o server colgado?** La pregunta correcta no es cuál de los dos, sino
**si hay alguien vivo del otro lado**, y eso ya se puede medir sin inventar nada:

| señal | de dónde | lee |
|---|---|---|
| `murio` | `transporte_sdk.py:296` | el proceso **murió** → no es la red: es el server |
| `murio == False` + timeout | ídem | el proceso **vive y no contesta** → colgado |
| `sin_red` ya distinguido | `motor_verdad.py:90` documenta `proveedor_caido` como «5xx/timeout **CON internet verificado OK**» | la distinción red/proveedor YA está resuelta en el motor |

> **DECISIÓN 2.B — el desempate del `timeout` lo da `murio`, no un ping.**
>
> **Alternativa descartada: que repair haga su propio chequeo de red (un ping/DNS).** Se
> descarta por la restricción sellada **«solo lecturas en cualquier verificación de repair»**
> — un ping es una lectura, sí, pero abre la puerta a que repair mida por su cuenta y termine
> con un veredicto distinto al del motor para la misma pieza. Dos verdades sobre la misma
> conexión es exactamente lo que el motor existe para evitar. Repair **pregunta**, no mide.

**`arranque` — ¿el server está roto o falta algo?** Ya está clasificado y repair sólo lee:
`diagnostico_conectores.py:246-253` mapea un traceback con
`ModuleNotFoundError/ImportError/AttributeError` a `SERVIDOR_INCOMPATIBLE` («Este servidor
está roto o es incompatible — **no es tu configuración**»), y `:258-262` mapea
`ENOENT/command not found` a `cli_no_instalado`. Los dos son **permanentes** y cada uno tiene
su botón.

**`429` con `Retry-After`.** `retry_after_s` ya existe en el contrato
(`errores_modelo.py:190`). Si viene, **manda sobre la curva de §3**: el proveedor sabe mejor
que nuestro backoff. Si no viene, curva normal.

---

## §3 · LA POLÍTICA DE REINTENTOS (el camino temporal)

### 3.1 · La curva

```
espera(n) = min(BASE * 2**(n-1), TOPE) * (1 + random.uniform(-JITTER, +JITTER))

BASE = 1 s · TOPE = 30 s · JITTER = 0,25 · MAX_INTENTOS = 5 · MAX_TOTAL_S = 90
```

Los intentos caen en ~1 · 2 · 4 · 8 · 16 s ± 25 %, y el tope de 90 s corta antes que los 5
intentos si la curva se estira.

**Por qué esos números, medidos y no elegidos:**

- **`BASE = 1 s`** contra un handshake de **274-819 ms** (`DISEÑO-DUEÑO-v1.md:109`): el primer reintento nunca pisa un
  arranque que todavía estaba en curso.
- **`MAX_TOTAL_S = 90`** contra `OCIOSIDAD_S = 600` (`dueno.py:78`): la ventana entera de
  repair cabe seis veces dentro de la vida de una conexión ociosa. Repair no puede tardar más
  que lo que el dueño tarda en tirar la conexión, o estaría reparando algo que ya no existe.
- **`JITTER = 0,25`** porque el calentador levanta el cinturón **en paralelo**
  (`dueno.py:803-805` usa un `ThreadPoolExecutor` para apagar; el restaurador levanta igual,
  `restaurador.py` con `_MAX_PARALELO`). Sin jitter, seis piezas que caen juntas por la misma
  red reintentan juntas para siempre.

> **Alternativa descartada: reintento inmediato + backoff después.** Es el patrón habitual
> («retry once, then back off») y acá sobra: el reintento inmediato **ya lo hizo el dueño**
> (`dueno.py:926-929`). Agregarlo sería el tercer intento sin espera sobre el mismo server.

### 3.2 · Por conexión o por entidad: **LAS DOS, y no es una duda**

| nivel | llave | qué cuenta |
|---|---|---|
| **reintentos** | **por CONEXIÓN** — `(user_id, entity_id, huella)` (`dueno.py:217-218`) | dos huellas distintas son dos procesos distintos (§2.3 del diseño del dueño); reintentar una no dice nada de la otra |
| **breaker** | **por ENTIDAD + usuario** — `(user_id, entity_id)` | si `github` falla con dos recetas distintas, el problema es `github`, no la receta |

**Nunca por entidad sola, sin usuario.** Un breaker global por `entity_id` deja que la llave
vencida de un usuario le abra el breaker a todos los demás — es la fuga del §2.1 del diseño
del dueño con otra ropa: compartir de más.

### 3.3 · El circuit breaker

| | |
|---|---|
| **abre** | 3 ciclos de repair agotados (5 intentos cada uno) para la misma `(user_id, entity_id)` dentro de 10 min |
| **dura** | 5 min, y **no** se reintenta solo mientras está abierto |
| **medio-abierto** | al vencer, **UN** intento. Verde → cierra. Rojo → vuelve a abrir 5 min más, hasta 3 veces; a la tercera **escala** (§5) y queda abierto hasta acción humana |
| **lo cierra** | (a) el medio-abierto verde · (b) **el usuario tocando el botón** · (c) la lápida (`apagar_entidad`, `dueno.py:1140`) · (d) un cambio de huella — receta nueva ⇒ breaker nuevo |

**(d) es la que importa y sale de §9.2.** La huella se calcula sobre el env DECLARADO en la
receta (`dueno.py:150-186` (docstring de `huella`); «Del hash NO sale ningún valor» en `:173`). Si el usuario cambia la receta o pega una llave nueva, la huella
cambia, y **un breaker abierto sobre la huella vieja no puede bloquear la nueva**. Sin esta
regla, «arreglé la llave y sigue sin andar» durante 5 minutos.

> **Alternativa descartada: sin breaker, sólo el tope de intentos.** Con `MAX_TOTAL_S = 90`
> por ciclo, una entidad rota permanentemente y pedida en loop por un agente autónomo
> reintenta 90 s de cada 90 s para siempre. El breaker es lo que convierte «falla siempre» en
> «falla y deja de costar».

### 3.4 · Lo que el usuario ve mientras: **🟡 y nada más**

Durante todo el camino temporal la card queda en **🟡**. Sin contador de intentos, sin
«reintentando 3/5», sin barra. Cuando sale, sale a 🟢 (calló) o a 🔴 con botón (escaló).

> **Alternativa descartada: mostrar el progreso de los reintentos.** Es la tentación obvia y
> es exactamente lo que la restricción sellada prohíbe: **el usuario nunca ve
> «temporal/permanente»** — y un «reintentando 3/5» es esa palabra dicha con números. Un
> usuario que ve reintentos empieza a esperar el reintento y a decidir si cancelarlo, o sea
> que le pasamos a él una decisión que repair existe para tomar sola.
>
> ⚠️ **Esto NO contradice «FALLO VISIBLE, JAMÁS MUDO»** y hay que ver por qué: el 🟡 **es**
> el fallo visible. La regla prohíbe que algo se rompa y la UI siga como si nada; no obliga a
> narrar el mecanismo. Lo que jamás puede pasar es terminar en 🟢 sin haberse arreglado, o
> quedarse en 🟡 para siempre — por eso `MAX_TOTAL_S` y el breaker son topes duros y la
> escalada de §5 es obligatoria.

### 3.5 · LA REGLA SELLADA: jamás re-pedir credencial por error temporal

Repair **nunca** dispara un flujo de credencial (ni `[Reconectar]`, ni `[Revisar llave]`, ni
un modal de BYOK) por una causa de la columna temporal.

**Y hay un precedente medido de por qué duele:** `conectores.ui.js:262-266` ya distingue
«La sesión venció ≠ la llave es inválida», con el comentario «La primera se arregla
reconectando —el camino funciona y la llave no—» (`conectores.ui.js:205`). Confundir un
temporal con un problema de credencial le pide al usuario que vaya a buscar una llave que
está perfecta. Es el peor fallo posible de repair: le pasa trabajo al humano por un problema
que se iba a arreglar solo.

**Corolario operativo:** el camino temporal **no toca `keys`** (la tabla) ni el broker. Ni
lectura ni escritura. Si una causa temporal repite hasta escalar, la escalada de §5 muestra
traza — no un botón de credencial.

---

## §4 · PERMANENTE → EL BOTÓN

### 4.1 · Repair NO crea UI. Alimenta la que existe.

El contrato de la card ya tiene los dos campos:

```
centro_conexiones.py:20   {id, titulo, estado, causa, detalle, evidencia, mano_humana, ts, ms}
centro_conexiones.py:22   causa ∈ motor_verdad.CAUSAS | None      (SÓLO si roto)
centro_conexiones.py:24   mano_humana = {comando, doc, por_que} | None
```

Y el que decide qué botón se pinta ya existe: `Sem.caminoDe(roto.estado)` →
`data-action="${camino.accion}"` (`conectores.ui.js:440-449`), normalizado en
`diagnostico_conectores.py:377` (`normalizar_camino`).

> **DECISIÓN 4.A — repair escribe `causa` y (si hace falta) `mano_humana`, y NADA MÁS.** El
> botón lo elige el mapa que ya existe.
>
> **Alternativa descartada: que el evento de repair lleve el botón.** Pondría el mapa
> causa→botón en dos lugares (repair y `caminoDe`) y el día que se agregue una causa habría
> que acordarse de los dos. La causa es el dato; el botón es la presentación.

### 4.2 · El mapa, y el botón que nace acá

| causa | botón | qué ejecuta | dónde vive hoy |
|---|---|---|---|
| `sin_sesion` | **[Reconectar]** | el flujo OAuth | `oauth_flow.py` · el absoluto de expiración en `:224-228` |
| `key_invalida` · `sin_credito` | **[Revisar llave]** | rotar credencial | `conectores.ui.js:884` (`rotarCredencial`) |
| `falta_key` | **[Conectar]** | alta de credencial | ídem |
| `cli_no_instalado` | **[Descargar]** | `mano_humana.comando` + `doc` | `centro_conexiones.py:270` ya emite este req con `ayuda` |
| `cli_version_vieja` | **[Actualizar]** | `mano_humana.comando` | `motor_verdad.py:71` |
| `servidor_incompatible` | **[Fijar la versión]** | **NO EXISTE — nace acá, §4.2.1** | `diagnostico_conectores.py:253` da la causa; no hay acción |
| `falla_de_aleph` | **[Copiar el reporte]** | portapapeles | `motor_verdad.py:85-88` |

#### 4.2.1 · **[Fijar la versión]** — el botón que la clase 3 dejó pendiente

**Qué problema resuelve, medido:** un belt declara `npx -y @scope/pkg` sin versión (es el
patrón de casi todo el catálogo — p.ej. `catalog/templates/medicina/belt-medicina.mcp.json`
declara `openfda` como `npx -y @cyanheads/openfda-mcp-server`). El día que el paquete publica
una versión incompatible, el server arranca y revienta con un traceback, y
`diagnostico_conectores.py:246-253` lo tipa correctamente como `servidor_incompatible` — pero
**no hay nada que el usuario pueda apretar**.

**Qué ejecuta, exactamente:**

1. **lee** la versión que está corriendo hoy — de la evidencia que el diagnóstico ya guarda
   (`evidencia_de_arranque`, `traductor_errores.py:228`) o del `server_info` que el registro
   ya persiste (columna `server_info`, `conexiones` — `conexiones_repo.py:89`);
2. **propone** el pin: `@scope/pkg` → `@scope/pkg@<última versión que dio veredicto verde>`.
   Esa versión sale del registro: es la que estaba cuando `ultimo_veredicto` fue verde;
3. **pide confirmación** — reparar = cambiar el mundo. Muestra el antes y el después del
   `args` textual;
4. **escribe** la receta del usuario: `args` de esa fila, vía `conexiones_repo.upsert_entidad`
   (`conexiones_repo.py:266`), **UPDATE jamás upsert** — la fila ya existe, y crear una sería
   fabricarle al usuario una entidad que no equipó (CLAUDE.md §1);
5. **la huella cambia** ⇒ el breaker viejo queda inerte por §3.3(d) ⇒ el próximo `pedir()`
   levanta un proceso nuevo con la versión fijada. No hace falta invalidar nada a mano.

> **Alternativa descartada: que [Fijar la versión] toque el CATÁLOGO.** Es lo que arreglaría
> el problema «para todos». Se descarta: el catálogo es dato curado con autor (CLAUDE.md, «el
> guard no inventa; el catálogo declara»), y un botón de UI que reescribe el catálogo desde
> la máquina de un usuario convierte un dato auditado en uno mutable por accidente. Repair
> arregla **la receta de ese usuario**; que el catálogo se pinee es una decisión de catálogo.

> **Alternativa descartada: fijar automáticamente sin preguntar.** Es una acción con efecto
> —cambia con qué código corre el agente— y la restricción sellada dice que pide
> confirmación.

### 4.3 · Cuando no hay botón: `mano_humana`

`cli_sin_permisos` y `cli_interactivo_colgado` no tienen arreglo que podamos ejecutar. El
contrato ya tiene el lugar: `mano_humana = {comando, doc, por_que}`
(`centro_conexiones.py:24`), descrito como «el paso que NO podemos resolver solos». Repair lo
llena y no pretende un botón.

### 4.4 · La lápida manda

Antes de cualquier cosa —clasificar, reintentar, escalar— repair chequea que la entidad no
esté apagada. El predicado ya existe y es el mismo que usa el restaurador:
`restaurador.py:193-200` (`habilitado is False` ⇒ apagada), con el encabezado explícito en
`restaurador.py:30`: «LA LÁPIDA (§4) NO ES UN FALLBACK MÁS. Una fila con `habilitado = false`
se SALTEA».

Y desde D5 la lápida además **mata el proceso aunque esté prestado**
(`centro_conexiones.py`, `_lapida` → `apagar_entidad`, `dueno.py:1140`). O sea que una
desconexión durante un ciclo de repair produce una muerte que repair **debe ignorar**: es la
decisión del usuario, no un fallo.

> **Regla:** el evento de §1.3 con `motivo == "lápida del usuario"` **no entra a repair**. Se
> descarta el ciclo en curso y se cierra el breaker de esa entidad.

---

## §5 · LA ESCALADA

### 5.1 · Cuándo

Tres puertas, cualquiera alcanza: (a) `MAX_INTENTOS`/`MAX_TOTAL_S` agotados sin verde;
(b) el breaker llegó a su tercer medio-abierto rojo; (c) causa **permanente sin botón**
(`no_es_mcp`, `fallo_desconocido`).

### 5.2 · Cómo se ve: **card, jamás modal**

La card pasa a 🔴 con su `causa`, su botón si lo hay, y **la traza plegada**.

> **Alternativa descartada: un modal.** Un modal interrumpe y exige atención ahora. La mitad
> de las escaladas van a ocurrir con el usuario mirando otra cosa —o sin usuario, §5.4— y un
> modal que nadie cierra bloquea la app. La card ya es el canal: `centro_conexiones.py:1118`
> ya ordena los rotos poniendo primero «el que trae `mano_humana`», o sea el que el humano
> tiene que arreglar primero. Repair hereda ese orden.

### 5.3 · Qué lleva la traza (lo que se intentó)

```
entidad · huella (12 hex, no reversible — dueno.py:150-181)
por qué empezó      R1/R2/R3 + causa clasificada
qué se intentó      n intentos, con el instante y el resultado de cada uno
por qué paró        tope de intentos | tope de tiempo | breaker
lo crudo            stderr del hijo (≤32 KB, transporte_sdk.py:223)
                    exit_code: None + su motivo (transporte_sdk.py:594-595)
                    murio_por_eof
```

**La huella se puede publicar y las llaves no.** El diseño del dueño ya lo sella: «Del hash
NO sale ningún valor… la huella puede viajar a `estado()` y a los logs sin violar “llaves
jamás en logs”» (`dueno.py`, docstring de `huella`). El stderr **sí** puede traer una llave
si el server la imprime: **la traza pasa por el scrubber que ya existe**
(`OutputScrubber`, usado en `session.py` y expuesto por `gates/runtime_integration.py`).

### 5.4 · «El usuario no está» (agente corriendo solo)

Es el caso que más importa y el que un modal rompe.

| | |
|---|---|
| **repair actúa igual** | el camino temporal es callado por definición: no necesita a nadie |
| **permanente sin humano** | **no** se ejecuta el botón. Ninguna acción con efecto corre sin confirmación, y «el usuario no está» no es una confirmación |
| **el agente se entera** | por donde ya se entera: `[MCP error: …]` (`dueno.py:624-648`). El loop decide si sigue sin esa herramienta o para |
| **queda constancia** | la card queda 🔴 con la traza, esperando. Cuando el humano vuelve, el trabajo ya está hecho: sabe qué pasó y qué apretar |

> **Alternativa descartada: auto-ejecutar el botón cuando no hay nadie.** «Reconectar solo»
> suena inofensivo hasta que es `[Fijar la versión]` cambiando con qué código corre un agente
> autónomo, o un flujo OAuth que abre un navegador que nadie va a ver.

---

## §6 · EL FANTASMA

### 6.1 · Qué es, y qué parte de esto está medida

**Reportado (CERT-PARCIAL, corridas de certificación de persona usuaria — no reproducible, y NO
encontrado en el árbol: `grep -rl "CERT-PARCIAL"` sobre todo el repo no devuelve nada):** un
cierre-solo intermitente a **t+30-45 s**, graceful.

Lo trato como reportado, no como medido. Lo que sigue es la instrumentación que lo atraparía
cuando vuelva.

### 6.2 · ¿La traza de repair lo cazaría? **HOY NO, y se puede ver por qué**

| lo que haría falta | ¿existe? |
|---|---|
| saber el **instante** de la muerte | **sí** — `transporte_sdk.py:296`, EOF del pipe |
| saber si fue **graceful** | **parcial** — `murio` es un booleano; no distingue salida limpia de SIGKILL |
| el **stderr** de los últimos segundos | **sí** — `transporte_sdk.py:592`, tope 32 KB |
| **cuánto vivió** | **sí, calculable** — `nacida_en` (`dueno.py:1181`) |
| que alguien lo **anote** | **NO** — hoy el dueño ni se entera si nadie pide (§1.1) |

**Los 30-45 s son el dato que acusa.** No coinciden con nada nuestro: `OCIOSIDAD_S = 600`
(`dueno.py:78`), `rpc_timeout` por defecto 30 s (`dueno.py:963`) y el timeout de la sonda es 45 s (`conexiones_verificador.py:407`, `:419`). **Que la ventana reportada sea exactamente 30-45 s y que nuestros dos timeouts sean 30
y 45 es demasiada coincidencia para no medirlo.**

### 6.3 · La instrumentación que lo atrapa (diseño, no código)

1. **Anotar SIEMPRE, aunque nadie pida.** Un `on_muerte` disparado desde el hilo drenador
   (`transporte_sdk.py:296`) hacia el dueño, y del dueño al suscriptor. Es lo que convierte
   una muerte silenciosa en un dato.
2. **`vivio_s` en cada evento.** Un histograma de `vivio_s` con un pico en 30-45 s señala un
   timeout nuestro; disperso señala el server.
3. **Correlacionar con el último `call_tool`.** Si toda muerte-fantasma cae ~30 s después de
   la última llamada, es un idle-timeout del server, no nuestro.
4. **Distinguir graceful de violento.** Ver §9 — hoy no se puede, y es el hueco que más
   pesa para este caso concreto.
5. **Retener el `procesos.jsonl` de la conexión muerta.** Hoy `_cerrar` (`dueno.py:1165`) la
   saca de la tabla y `_volcar` (`dueno.py:1196-1199`) reescribe el archivo entero — **la fila
   de la muerta desaparece**. Para el fantasma hace falta que la última fila sobreviva a su
   propia muerte.

> **DECISIÓN 6.A — el evento de muerte se emite SIEMPRE, aun cuando no sea caso de repair
> (§1.2).** Repair filtra después.
>
> **Alternativa descartada: emitir sólo cuando dispara repair.** Con R1 (segunda muerte),
> la primera muerte —que es justo la que el fantasma produce— nunca se anotaría. El fantasma
> es un caso de **una** muerte, no de dos.

---

## §7 · DÓNDE VIVE

### 7.1 · La forma

**`platform/inspection/repair.py`** — módulo propio, suscriptor del dueño.

| | |
|---|---|
| **quién lo arranca** | el lifespan de `main.py`, donde ya se arranca el barrido del dueño (`main.py:173`) |
| **quién lo apaga** | el mismo `finally` donde ya se llama `apagar_todo` (`main.py:206`) |
| **hilo** | **uno solo**, con una cola de eventos. No un hilo por conexión |
| **perilla** | `ALEPH_REPAIR=off|on`, default **`off`**, leída en **un solo lugar**, igual que `dueno.encendido()` (`dueno.py:110-112`) |
| **sin suscriptor** | el dueño se comporta **exactamente** como hoy |

> **Alternativa descartada: dentro de `dueno.py`.** El dueño ya son 1.061 líneas y su frontera
> está sellada y testeada (`test_frontera_dueno.py`, 8 sitios de spawn). Meter la política de
> reintentos adentro lo convierte en dos cosas, y la primera regla de este documento es que
> re-levantar y reparar son verbos distintos.

> **Alternativa descartada: un hilo por conexión en repair.** El dueño ya tiene tope de 8
> vivas (`dueno.py:86`), así que serían ≤8 hilos — pero cada uno durmiendo su backoff con su
> propio reloj hace imposible el tope global `MAX_TOTAL_S` y el breaker por entidad. Una cola
> y un hilo tienen un solo reloj.

### 7.2 · Qué persiste, y dónde

| dato | dónde | por qué |
|---|---|---|
| intentos del ciclo en curso | **memoria** | muere con el proceso, y está bien: al reiniciar, el barrido de arranque (`dueno.py:1202`) ya mató todo — no hay ciclo que continuar |
| breaker abierto | **memoria** | ídem. Un breaker que sobrevive al reinicio le niega al usuario el arreglo más obvio, que es reiniciar |
| la **traza** de una escalada | **registro**, en la fila de la entidad | tiene que sobrevivir: es lo que el humano lee cuando vuelve |
| el histograma del fantasma (§6) | `procesos.jsonl` extendido | ya existe y ya es del dueño (`dueno.py:228-235`) |

**Si toca el registro: UPDATE, JAMÁS UPSERT.** La fila de la entidad existe (repair sólo
actúa sobre algo que estuvo conectado), y `upsert_entidad` sólo pisa los campos que se le
pasan (`conexiones_repo.py:270-271`). La traza va a `causa` + evidencia de la fila que ya
está; **nunca** crea una fila.

> **Alternativa descartada: persistir el breaker en el registro.** Sobrevive al reinicio y a
> primera vista es más «serio». Se descarta por dos razones: (a) le quita al usuario el
> reinicio como arreglo; (b) el registro es «lo que este usuario tiene» (CLAUDE.md), no el
> estado transitorio de una política de reintentos.

### 7.3 · El contrato con el dueño, en una línea

```python
dueno.suscribir(fn)     # fn(MuerteMCP) -> None · llamada FUERA del lock del dueño
```

**Fuera del lock, y es la parte que puede romper todo.** `_cerrar` corre con `self._lock`
tomado (`dueno.py:767`, `pedir` y `apagar_*`). Si el suscriptor se llamara adentro, un repair
que hace `pedir()` para reintentar se auto-bloquearía con el `RLock` reentrante del mismo
hilo… o peor, con otro hilo esperando. El evento se **encola** dentro del lock y se
**entrega** afuera.

---

## §8 · CÓMO SE RESPETA CADA RESTRICCIÓN SELLADA

| restricción | dónde se cumple en este diseño |
|---|---|
| reparar = cambiar el mundo ⇒ confirmación | §4.2.1 paso 3 · §5.4 (no se auto-ejecuta sin humano) |
| la lápida manda | §4.4 · predicado ya existente `restaurador.py:193-200` |
| jamás re-pedir credencial por temporal | §3.5 · el camino temporal no toca `keys` ni el broker |
| FALLO VISIBLE, JAMÁS MUDO | §3.4 (🟡 **es** el fallo visible) · §5 (la escalada es obligatoria, con topes duros) |
| el usuario nunca ve «temporal/permanente» | §2.2 (la tabla es interna) · §3.4 (sin contador de reintentos) |
| solo lecturas en cualquier verificación | §2.3 (repair **pregunta** al motor, no mide) |

---

## §9 · LO QUE NO CUBRE

Honesto y sin adornos.

1. **No distingue graceful de violento.** `murio` es un booleano de EOF
   (`transporte_sdk.py:251-257`) y `exit_code` es `None` **siempre** por una limitación real
   del SDK (`stdio_client` no expone el `Process` — `transporte_sdk.py:594-595`). Sin eso,
   «se cerró solo» y «lo mató el OOM killer» se ven igual. **Es el hueco que más pesa para
   §6**, y arreglarlo no es de repair: es del transporte.
2. **`senal` es siempre `None`** por lo mismo. El campo está en el evento (§1.3) para no
   cambiar el contrato cuando exista.
3. **No repara HTTP.** Todo este diseño es stdio. El verificador ya declara que el transporte
   http «no está cableado por este verificador» (`conexiones_verificador.py:509-512`).
4. **No cubre el fallo PARCIAL**: un server vivo cuyas tools devuelven basura sin error. Ahí
   no hay muerte, no hay causa tipada y no hay disparador. Es otro problema.
5. **No decide si el agente debe seguir sin la herramienta.** Repair informa; el loop decide.
6. **No hay reintento de la tool que falló**, por diseño (§0.1): repetir una tool con efecto
   es repetir el efecto.
7. **La correlación del fantasma (§6.3) necesita datos que hoy no se guardan.** Hasta que la
   sesión R1 del plan corra, §6 es una hipótesis instrumentable, no un diagnóstico.
8. **No toca los 4 sitios de spawn fuera del dueño** (`test_frontera_dueno.py`: `byo_mcp`,
   `dispatch/liveness`, `inspect_run`, `run_once`). Repair sólo ve lo que el dueño posee. Un
   fallo en esos caminos **no** llega a repair, y está bien porque ninguno sostiene — pero es
   una asimetría que hay que saber.
9. **`expira_en` de OAuth es un camino SEPARADO, no un caso de repair.** `oauth_flow.py:224-228`
   ya maneja la expiración con un absoluto, y `conectores.ui.js:262-266` ya la distingue de
   una llave inválida. Un token que vence no es un fallo: es lo esperado. Repair **no** lo
   consume; si un vencimiento produce `sin_sesion`, entra por §4 como cualquier permanente.

---

## §10 · PLAN DE CONSTRUCCIÓN

Cinco sesiones. Cada una con su vara verde. Ninguna cablea un consumidor hasta que la
anterior esté verde — la misma regla que el dueño: «un dueño a medias filtra procesos».

| sesión | qué construye | vara verde que la cierra |
|---|---|---|
| **R1** | **el evento y nada más.** `MuerteMCP` (§1.3) · `dueno.suscribir()` · emisión desde `_cerrar` y desde el EOF de `transporte_sdk`. **Sin repair**: el suscriptor de prueba sólo anota. | Vara nueva: matar un hijo a mano produce UN evento con `stderr` no vacío, `vivio_s` coherente y la clave correcta · una muerte **sin que nadie pida** también lo produce (es lo que hoy no pasa) · `verify_dueno.py` 100 ✓ **sin tocar** · regresión completa en los dos entornos |
| **R2** | **la clasificación, pura.** Causa → temporal/permanente reusando `_REINTENTABLES` (`errores_modelo.py:113`) y el traductor. Función pura, sin efectos. | Tabla de §2.2 congelada en test, causa por causa · los 3 grises de §2.3 con su desempate · un test que falla si `motor_verdad.CAUSAS` crece y la tabla no (igual que `test_las_causas_no_derivan` del traductor) |
| **R3** | **el camino temporal.** Backoff, jitter, topes, breaker. Perilla `ALEPH_REPAIR`, default `off`. | Un server que muere 2 veces y revive se arregla **callado** y la card nunca sale de 🟡 · uno que muere siempre agota y escala · el breaker abre, dura, medio-abre y cierra · **la card jamás pide credencial en todo el camino** · cero huérfanos por `ps` |
| **R4** | **el camino permanente.** `causa` + `mano_humana` a la card. **[Fijar la versión]** (§4.2.1) con confirmación. | Cada causa permanente de §2.2 llega con su botón · [Fijar la versión] cambia `args`, la huella cambia, el proceso nuevo levanta con el pin, **UPDATE y el registro sigue en 42 filas** · sin confirmación no escribe nada · la lápida gana (§4.4) |
| **R5** | **la escalada y el fantasma.** Traza con scrubber · card 🔴 ordenada · caso «no hay humano» · la instrumentación de §6.3. | La traza no filtra ni una llave (vara con un server que imprime una a propósito) · agente solo: escala, **no ejecuta** el botón, el loop recibe `[MCP error: …]` · el histograma de `vivio_s` existe y se puede leer |

**Vara transversal, en todas:** veredictos idénticos sobre las 62 del catálogo · regresión
completa en los dos entornos · cero huérfanos por `ps` filtrado a este worktree · las varas
del dueño (`verify_dueno` 100 · `run` · `sesion` · `env_declarado` · `test_frontera_dueno`)
verdes **sin tocarlas**. Si una sesión de repair necesita tocar una vara del dueño, es señal
de que cruzó la frontera.

---

## §11 · TABLA DE CITAS

Todo lo afirmado arriba, verificable en `main @ 71b446f`.

| afirmación | archivo:línea |
|---|---|
| «re-levantar es el dueño, no repair» | `dueno.py:925` |
| reconnect-once y el contador escalar | `dueno.py:926-929` |
| `_parece_muerta` sólo se llama en `pedir()` | `dueno.py:1004-1008`, llamada en `:720` |
| `_cerrar` no emite nada y saca la fila | `dueno.py:1152-1171` |
| `estado()["eventos"]` | `dueno.py:1193` |
| la clave `(user_id, entity_id, huella)` | `dueno.py:217-218` |
| `OCIOSIDAD_S = 600` · `MAX_VIVAS = 8` | `dueno.py:78`, `:86` |
| `encendido()` en un solo lugar | `dueno.py:110-112` |
| `apagar_entidad` (la lápida) | `dueno.py:1140` |
| `_Libro` / `procesos.jsonl` | `dueno.py:228-235` |
| barrido de arranque | `dueno.py:1202` |
| `ServidorPrestado.call_tool` devuelve string | `dueno.py:624-648` |
| muerte por EOF del pipe | `transporte_sdk.py:296` |
| `murio` y por qué no es un exit code | `transporte_sdk.py:251-257` |
| `soltar_escritura` y `os._exit(7)` medido | `transporte_sdk.py:264-274` |
| `diagnostico()` del transporte | `transporte_sdk.py:581-604` |
| `exit_code = None` con motivo | `transporte_sdk.py:584-586`, `:506-507` |
| tope de stderr 32 KB | `transporte_sdk.py:223` |
| las 25 causas | `motor_verdad.py:129-137` |
| `falla_de_aleph` es culpa nuestra | `motor_verdad.py:85-88` |
| `proveedor_caido` = 5xx/timeout con internet OK | `motor_verdad.py:90` |
| `_REINTENTABLES` y `retry_after_s` | `errores_modelo.py:113-127`, `:189-190` |
| traductor: 35 tests colectados | `test_traductor_errores.py` (`pytest --collect-only`) |
| entradas del traductor | `traductor_errores.py:87`, `:112`, `:131`, `:182`, `:228` |
| `servidor_incompatible` desde traceback | `diagnostico_conectores.py:246-253` |
| `cli_no_instalado` desde ENOENT | `diagnostico_conectores.py:258-262` |
| `normalizar_camino` | `diagnostico_conectores.py:377` |
| contrato de la card con `mano_humana` | `centro_conexiones.py:20-24` |
| el roto con `mano_humana` va primero | `centro_conexiones.py:1118-1119` |
| `caminoDe` → `data-action` | `conectores.ui.js:440-449` |
| «La sesión venció ≠ llave inválida» | `conectores.ui.js:205`, `:262-266` |
| `rotarCredencial` | `conectores.ui.js:884` |
| la lápida se SALTEA | `restaurador.py:30`, `:193-200` |
| stderr del hijo en el restaurador | `restaurador.py:111`, `:294-302` |
| `upsert_entidad` sólo pisa lo que se le pasa | `conexiones_repo.py:266`, `:270-271` |
| `expira_en` absoluto de OAuth | `oauth_flow.py:224-228` |
| lifespan: arranque y cierre | `main.py:173`, `:195` |
| http no cableado por el verificador | `conexiones_verificador.py:509-512` |
| `verificar_uno` | `conexiones_verificador.py:498` |
| CERT-PARCIAL no está en el árbol | `grep -rl "CERT-PARCIAL" .` → vacío |
