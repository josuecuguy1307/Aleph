# MAPA DE ERRORES — SDK oficial (`mcp==2.0.0`) → causas tipadas de Aleph

**Rama:** `feat/sdk-transporte-1` · escrito en la **sesión 1** (2026-08-02) como papel ·
**EJECUTADO en la sesión 2** (2026-08-03).

> **§7 no es un hallazgo: es un REQUISITO VINCULANTE** para cuando se construya DCR
> (paso 4). Leerlo antes de escribir la primera línea de ese paso.
>
> **§8 es la corrección de la sesión 2**: qué de este mapa se confirmó al implementarlo,
> qué estaba mal, y las tres regresiones que sólo aparecieron cuando se recableó de verdad.
> Leerlo junto con cada sección — lo de arriba quedó como se MIDIÓ, pero no todo lo que se
> DEDUJO de esas mediciones resultó cierto.

Cada fila de abajo se **provocó y se midió** en esta sesión; ninguna se dedujo leyendo el
SDK, salvo las dos marcadas `[leída, no provocada]`, que están marcadas justamente porque
no se provocaron.

Reproducir:

```
venv-con-mcp-2.0.0/bin/python platform/inspection/verify_transporte_sdk.py
venv-con-mcp-2.0.0/bin/python platform/inspection/verify_lado_a_lado_http.py
```

---

## 0 · La forma cruda de un error del SDK

Todo lo que no sea un `MCPError` limpio llega **envuelto en `BaseExceptionGroup`**, a veces
dos veces: anyio corre el transporte y la sesión en task groups anidados. El mensaje de la
capa de afuera es siempre `"unhandled errors in a TaskGroup"`, que no le sirve a nadie.
`transporte_sdk._forma()` baja hasta la hoja (máximo 8 niveles) antes de reportar.

**Regla para la sesión 2: ningún clasificador puede mirar `str(e)` de la excepción que
atrapa. Tiene que desenvolver primero.**

---

## 1 · STDIO — el arranque

| Qué pasó | Forma del SDK | Cliente viejo | Causa tipada nuestra | ¿Alcanza? |
|---|---|---|---|---|
| El comando no existe | `FileNotFoundError: [Errno 2] No such file or directory: '…'` (levantada por `stdio_client`, **no** es `MCPError`) | `detail` con el mismo `FileNotFoundError`, `exit_code=None`, `stderr=""` | `C_ARRANQUE` (`arranque`) | ✅ idéntico |
| Arranca y no contesta `initialize` | `MCPError: Request 'initialize' timed out` (**-32001**) | `detail`: «el proceso arrancó pero no respondió al saludo initialize de MCP», `exit_code=None`, `stderr` capturado | `C_ARRANQUE` | ✅ y el SDK dice **por qué** (timeout) donde el viejo sólo decía «no respondió» |
| Muere durante el handshake | `MCPError: Connection closed` (**-32000**) | `detail` igual que arriba pero **`exit_code=3`**, `stderr` capturado | `C_ARRANQUE` | ⚠️ **se pierde el exit code** — ver §4 |
| Arranca, habla, no publica tools | `list_tools()` devuelve `[]` (sin excepción) | ídem | `C_SIN_TOOLS` (`sin_tools`) | ✅ idéntico |

En los tres casos de falla, `ServidorSDK.start()` devuelve `False` y deja el porqué en
`diagnostico()["detail"]`, exactamente como `MCPServer.start()`. **Ningún consumidor
necesita cambiar la forma de preguntar.**

---

## 2 · STDIO — las formas de terminar un `tools/call`

`MCPServer.call_tool` devuelve **un string**, y el verificador lo guarda tal cual como
evidencia (`_llamar()` → `_clasificar()`). El puente devuelve el MISMO string, error por
error. Las seis formas, medidas:

| # | Qué pasó | Forma del SDK | String que devuelve el puente | Causa tipada |
|---|---|---|---|---|
| 1 | La tool anduvo | `CallToolResult(is_error=False)` | el texto pelado | — (`VIVA`) |
| 2 | La tool falló **adentro** | `CallToolResult(is_error=True)` | `[tool error] <texto>` | `VIVA` + la credencial decide (un 401 vive acá) |
| 3 | El server contestó **error JSON-RPC** | `MCPError` con el code del server (medido: **-32602** `Invalid params`) | `[MCP error: {'code': -32602, …}]` | `VIVA` — el canal funciona, la llamada no |
| 4 | La tool **se colgó** | `MCPError` **-32001** `Request 'tools/call' timed out` | `[MCP error: {'code': -32001, …}]` | `C_TIMEOUT` (`timeout`) |
| 5 | El server **se murió** | `MCPError` **-32000** `Connection closed` | `[MCP error: {'code': -32000, …}]` | `C_SIN_RESPUESTA` (`sin_respuesta`) |
| 6 | El server pide **input** al usuario | `RuntimeError` (`allow_input_required=False`, el default) `[leída, no provocada]` | `[MCP error: RuntimeError: …]` | sin causa equivalente hoy — **decisión pendiente** |

Y una séptima que no es de `tools/call` pero cae en el mismo `except`:
`UnexpectedClaimedResult` cuando un server usa una extensión con *claims*
(`allow_claimed=False` por default) `[leída, no provocada]`.

**Los códigos -32000 y -32001 son la pieza clave del re-cableo.** Hoy `_clasificar()`
distingue «no contestó» de «tardó» por regex sobre texto libre
(`C_TIMEOUT if re.search(r"time", texto, re.I) else C_SIN_RESPUESTA`). Con el SDK eso pasa
a ser un **número**, y la regex se puede retirar. Es la única mejora de diagnóstico que el
SDK regala gratis.

Después de que el server muere, `list_tools()` devuelve `[]` y `diagnostico()["murio"]` es
`True` — mismo comportamiento observable que el cliente viejo con un `proc.poll()` no-nulo.

---

## 3 · HTTP — y acá el SDK **aplasta** la capa de transporte

Medido contra `https://mcp.exa.ai/mcp` (byo-ai-exa-exa) y contra fallas provocadas:

| Qué pasó | Forma del SDK, **sola** | Cliente viejo | Lo que el puente recupera |
|---|---|---|---|
| DNS no resuelve | `MCPError` **-32000** `Connection closed` | `[Errno 8] nodename nor servname provided, or not known` | `red_detalle: ConnectError: [Errno 8] nodename nor servname…` |
| Puerto cerrado | `MCPError` **-32000** `Connection closed` | `[Errno 61] Connection refused` | `red_detalle: ConnectError: All connection attempts failed` |
| El server corta a mitad | `MCPError` **-32000** `Connection closed` | error de socket | `red_detalle` vacío + `http_status` del último response |
| HTTP 405 con un HTML | `MCPError` **-32603** `Server returned an error response` | `http_status: 405` + **el cuerpo** | `http_status: 405` |

**Las tres primeras filas son el MISMO error para el SDK y TRES remedios distintos para el
usuario** («escribiste mal la URL» ≠ «el server está caído» ≠ «se cortó»). Y el 405 sin
status deja a `diagnostico_conectores` sin poder separar **401 (credencial)** de **404
(URL mala)** de **5xx (proveedor caído)** — que es literalmente su trabajo.

Por eso el puente le pasa al SDK **su propio `httpx2.AsyncClient`** con un transporte que
anota `ultimo_status` y `ultima_falla` (`transporte_sdk._transporte_que_recuerda`). Con eso
la evidencia vuelve a tener `http_status` y un motivo de red distinguible, verificado lado a
lado contra el cliente viejo (§6 de `verify_lado_a_lado_http.py`).

**Lo único que sigue perdido: el CUERPO del error HTTP.** El cliente viejo lo guardaba
(32 KB cap) y lo publicaba en `evidencia.respuesta`. Leerlo en el transporte rompería el
stream que el SDK todavía tiene que consumir. Queda como decisión de la sesión 2: o se
acepta la pérdida, o el transporte bufferea el cuerpo **sólo cuando el status es de error**
y lo re-inyecta.

Y una nota que no es un error pero se persiste: **`protocolVersion` cambia**. El cliente
viejo pide `2024-11-05` clavado en una constante; el SDK negocia lo que el server ofrezca
(exa: `2025-11-25`; fetch: `2025-11-25`). El registro guarda esto en `era` y
`version_negociada`, así que migrar mueve datos del registro. No es un bug: es una decisión.

---

## 4 · EL COSTO OCULTO — lo que hay que re-cablear en la sesión 2

Los tres lugares que el veredicto ya había identificado, con el dato exacto que consumen:

### 4.1 · `diagnostico_conectores.py`

Lee de la evidencia: `stderr`, **`exit_code`**, `http_status`, `respuesta`, `red`,
`protocolo{cliente,servidor,incompatible}`, `detail`, `command`
(`_evidencia_publica`, líneas 61-84; `crudo_de`, 86-101).

| Campo | ¿Lo da el puente? |
|---|---|
| `stderr`, `stderr_lineas`, `stderr_bytes`, los dos caps | ✅ idénticos (32 KB · 80 líneas) |
| `command`, `detail` | ✅ |
| `protocolo` | ✅ `{cliente:"sdk", servidor:<negociada>, negociacion:"aceptada"}` — **pero `cliente` ya no es una fecha**, y `_versiones_protocolo()` espera dos revisiones para atribuir una deriva. **Re-cableo obligatorio.** |
| `http_status`, `red` | ✅ recuperados por el transporte propio |
| **`exit_code`** | ❌ **NO**. Ver 4.3 |

### 4.2 · `motor_verdad._entorno_de_belts()` / `conexiones_verificador._spawn()`

`_spawn` construye `env` y se lo pasa a `MCPServer(env=…)` con la semántica «esto es el
entorno COMPLETO del hijo». El puente respeta esa semántica (`entorno_hijo()`), **con dos
diferencias declaradas**:

1. **El PATH lo pisa Aleph al final, siempre.** `ensure_user_path()` sólo agrega
   directorios (nunca saca `/usr/bin:/bin`), así que no puede angostar nada.
2. `stdio_client` arma el env como `get_default_environment() | nuestro`: las claves
   **ausentes** del nuestro se cuelan desde `os.environ`. Con los entornos reales del
   verificador (todos derivados de `os.environ`) la fuga es **vacía** — medido, y publicado
   en `diagnostico()["entorno"]["inyectadas_por_el_sdk"]` para que nunca sea invisible.

### 4.3 · `exit_code` — el único agujero sin fondo

`stdio_client` hace `yield read_stream, write_stream` y **se queda el objeto `Process` en
el closure**. No hay `.returncode` ni `.pid` públicos, ni un `StdioTransport` que lo exponga
(`mcp 2.0.0`, revisado entero). Medido: donde el cliente viejo reporta `exit_code: 3`, el
puente reporta `None`.

El contrato de `MCPServer.diagnostico()` es explícito: **`exit_code=None` significa «seguía
vivo» y jamás se convierte en un cero inventado.** El puente respeta eso al pie de la letra
y agrega dos campos para no mentir por omisión:

- `exit_code_fuente`: por qué es `None`.
- `murio`: `True`/`False`, del EOF del pipe de stderr (el pipe da EOF cuando muere el
  último proceso del árbol que lo tiene abierto). **No es el exit code y no se disfraza de
  uno.** Requiere soltar nuestra copia del extremo de escritura apenas el hijo tiene la
  suya — si no, un server que se cayó a mitad de sesión se ve idéntico a uno vivo (medido).

**Las tres salidas para la sesión 2, en orden de costo:**

| Opción | Qué cuesta | Qué se pierde |
|---|---|---|
| a. Aceptar `murio` en lugar de `exit_code` | re-cablear `crudo_de()` y las reglas que hoy leen `exit_code` | el código numérico (hoy se usa para «exit 127 ⇒ comando no encontrado») |
| b. Spawn propio + `ClientSession` sobre nuestros streams | perder el cierre de árbol del SDK, que es el motivo de adoptarlo | nada del diagnóstico |
| c. Pedirlo upstream | tiempo ajeno | nada, si entra |

Recomendación para la sesión 2: **(a)**, con (c) en paralelo. (b) devuelve el problema que
vinimos a resolver.

---

## 5 · Lo que el cierre del SDK **NO** arregla

`_stop_server_process` cierra stdin, **espera 2 s** y sólo **si el hijo no salió** manda
SIGTERM al grupo y SIGKILL 2 s después. Medido en macOS con las dos formas:

| Caso | Puente | Cliente viejo |
|---|---|---|
| Server que **se cuelga** (ignora SIGTERM, no sale al cerrarse stdin) + nieto terco | **0 supervivientes** | el nieto queda **huérfano** |
| Server **bien educado** (sale solo al cerrarse stdin) + nieto terco | el nieto queda huérfano | el nieto queda huérfano |
| `fetch` real (`uvx mcp-server-fetch`) | 0 supervivientes | 0 supervivientes (`uv` reenvía la señal) |

**El cierre del SDK es más riguroso SÓLO cuando el server no se muere solo.** No es una red
que atrape todo huérfano: un server que sale limpio y dejó hijos propios los deja igual.
Con `fetch` —el server real del registro— los dos clientes se ven idénticos. Decirlo así
importa: la ganancia existe y es real, pero es más chica que «el SDK mata el árbol».

---

## 6 · Resumen para decidir en la sesión 2

**A favor de migrar:** códigos numéricos (-32000/-32001) en vez de regex sobre texto ·
cierre de árbol en el caso del server colgado · handshake mantenido por otros · negociación
de protocolo al día (`2025-11-25` vs nuestro `2024-11-05` clavado).

**En contra / a pagar:** `exit_code` se pierde · el cuerpo del error HTTP se pierde ·
`protocolo.cliente` deja de ser una fecha y hay que re-cablear `_versiones_protocolo()` ·
el registro cambia (`era`, `version_negociada`) · toda excepción hay que desenvolverla de
`BaseExceptionGroup` · +13 paquetes (1.20 MB comprimidos / 5.16 MB en disco).

**Neutro:** el entorno del hijo sigue siendo nuestro y está verificado · la interfaz sync
no cambia para ningún consumidor · el stderr se captura igual, con los mismos caps.

---

## 7 · REQUISITO VINCULANTE — la validación de redirect-URI es NUESTRA (DCR, paso 4)

**Esto no es un hallazgo del SDK: es una obligación de Aleph.** Se anota acá porque el
motivo se midió en esta sesión y quien construya DCR va a leer este archivo.

### La regla

> **Al construir DCR (paso 4), Aleph valida el `redirect_uri` — antes de ponerlo en el
> cable y antes de actuar sobre cualquiera que el servidor devuelva. Un `redirect_uri` que
> no pase la validación aborta el flujo con un error visible. No hay modo permisivo, ni
> flag, ni excepción «para probar».**

Válido = **exactamente** esta forma, y nada más:

```
http://127.0.0.1:<PUERTO>/<ruta que abrimos nosotros>
```

- **esquema `http` literal.** No `https` (no hay TLS en loopback), no `javascript:`,
  `data:`, `file:`, `vscode:` ni ningún esquema de app.
- **host `127.0.0.1` literal**, no `localhost`. `localhost` pasa por resolución de nombres
  y puede terminar en otro lado; la IP literal no (RFC 8252 §7.3 lo recomienda por esto).
  Si algún día hace falta IPv6, se agrega `[::1]` **explícitamente**, no por analogía.
- **puerto**: un entero, el que **nosotros** abrimos en esta corrida. No un puerto fijo
  compilado, no uno que venga de config.
- **ruta**: la que registramos nosotros. Sin `userinfo` (`user:pass@`), sin query ni
  fragmento colados.
- Se valida sobre la URL **ya parseada**, no con una regex sobre el string.

### Por qué somos el único guard — medido en esta sesión

1. **El SDK no valida NADA.** `redirect_uris` es `list[AnyUrl]` de pydantic tanto en
   `OAuthClientMetadata` (lo que mandamos) como en `OAuthClientInformationFull` (lo que
   aceptamos del servidor). Los dos aceptan `javascript:alert(document.cookie)`,
   `data:text/html,<script>alert(1)</script>` y `file:///etc/passwd`; a
   `'  javascript:alert(1)  '` **le come los espacios y lo da por bueno**. En
   `mcp/client/auth/oauth2.py` no aparece ni una vez `javascript`, `127.0.0.1`, `localhost`
   ni `loopback`: cero allow-list de esquemas en todo el camino de OAuth del cliente.
2. **Lo que acota el daño, y por qué no alcanza.** El cliente del SDK usa SIEMPRE su propio
   `client_metadata.redirect_uris[0]` —para la request de autorización (`oauth2.py:397`,
   `:452`) y para la registración (`:713`)—, nunca uno echado por el servidor. O sea que la
   exposición es **exactamente lo que pongamos nosotros ahí**. Eso convierte la ausencia de
   validación en un problema nuestro, no del SDK: el día que un `redirect_uri` llegue desde
   una receta, desde el registro o desde una respuesta de descubrimiento, viaja tal cual y
   no hay una sola baranda en el camino.
3. **El servidor puede sustituir metadata.** RFC 7591 §3.2.1 lo autoriza explícitamente
   («MAY reject or replace any of the client's requested metadata values»), y el modelo del
   SDK está tipado para aceptarlo. Por eso la validación va en **los dos sentidos**: lo que
   mandamos y lo que nos devuelven.

### Dónde va, concretamente

- Al **construir** el `OAuthClientMetadata`, antes de que exista el objeto.
- Al **leer** el `OAuthClientInformationFull` que responde el servidor: si el
  `redirect_uris` que echó no es el nuestro, la registración **no se acepta**.
- Al **rehidratar** una registración persistida: lo guardado en disco no es más confiable
  que lo que llega por la red.

Fallo visible, jamás mudo (CLAUDE.md §1): un `redirect_uri` rechazado se reporta con el
valor ofensor recortado y el motivo, no se corrige en silencio ni se cae a un default.

---

## 8 · LO QUE LA SESIÓN 2 CORRIGIÓ DE ESTE MAPA

Ejecutar el mapa lo puso a prueba. Tres cosas que estaban mal o incompletas, y tres
regresiones que sólo aparecieron cuando el recableo tocó código real.

### 8.1 · `exit_code` NO era «el agujero sin fondo»

§4.3 lo trataba como la pérdida más cara. **Medido: no cambia ningún veredicto.** El campo
se lee en UN solo lugar del clasificador (`crudo_de`, que arma el texto humano) y ninguna
regla se bifurca por él. Lo único que se pierde es la línea `exit code: N` en el detalle que
lee la persona.

Fijado en `test_traductor_errores.py::test_el_exit_code_ausente_no_cambia_ningun_veredicto`,
que compara el veredicto con `127` y con `None` campo por campo.

La opción (b) de §4.3 —spawnear nosotros— queda descartada: no hay nada que comprar. Y el
traductor **tampoco borra** el `exit_code` cuando el transporte SÍ lo mide (el cliente viejo
da `3`): durante la migración conviven, y degradar al que mide sería perder evidencia por
prolijidad.

### 8.2 · La versión que el SDK PIDE no es la que decía la sesión 1

La sesión 1 anotó «el SDK pide la última revisión (`2026-07-28`) y baja». **Falso.**
`ClientSession.initialize()` manda `LATEST_HANDSHAKE_VERSION` = **`2025-11-25`**
(`mcp/client/session.py:619`). `LATEST_PROTOCOL_VERSION` (`2026-07-28`) existe pero sólo se
usa en el camino de `server/discover`.

Se descubrió porque un server de laboratorio que ECHA de vuelta lo que le mandan devolvió
`2025-11-25`. O sea: exa y fetch no «negociaron hacia abajo» — **aceptaron exactamente lo
que se les pidió**. Poner la constante equivocada en `protocolo.solicitada` era anotar que
pedimos algo que nunca pedimos.

### 8.3 · Las TRES regresiones del recableo

Ninguna se veía en el papel. Las tres cambiaban un veredicto, que es lo que la regla madre
prohíbe.

| # | Qué pasaba | Por qué | Dónde se fija |
|---|---|---|---|
| 1 | **Un server MUERTO se reportaba VIVO** | `veredicto_conexion` decidía «¿contestó?» con una regex. `Connection closed` no matchea ninguna de sus palabras (`connection reset` estaba; `connection closed` no), y el texto no vacío caía en la rama VIVA | `test_conexiones_verificador.py::test_un_server_muerto_no_se_reporta_vivo` |
| 2 | **`no_es_mcp` se perdía** → `desconocido` | el clasificador busca la frase literal «no respondió al saludo initialize de MCP»; el puente decía «MCPError: Request 'initialize' timed out» | `test_traductor_errores.py::test_el_arranque_fallido_cae_en_el_mismo_escalon_que_antes` |
| 3 | **`deriva_protocolo` se perdía** → `no_habla_mcp` | el puente sólo armaba el bloque `protocolo` cuando el saludo salía BIEN. Un `-32022` —el único caso en que la deriva es honesta— no dejaba evidencia | `test_diagnostico_conectores.py::test_deriva_de_protocolo_captura_ambas_revisiones[sdk]` |

La #1 es la que importa: silenciosa, y en la dirección peor de las dos.

Y una CUARTA que el mapa sí anticipó y que había que evitar al revés: el clasificador
deduce incompatibilidad de `cliente != servidor`, así que reportar «pedí X, me dieron Y»
sobre un handshake EXITOSO habría etiquetado `deriva_protocolo` **cualquier** fallo
posterior de **cualquier** conexión por el puente. Por eso `protocolo_de()` declara las dos
puntas iguales a la versión negociada cuando la negociación cierra bien, y guarda lo pedido
aparte, en `solicitada`, que es evidencia y no entra en la deducción.

### 8.4 · `mcp==2.0.0` rompe la API 1.x que el árbol ya usaba

No es sólo nuestro puente el que toca el SDK. `platform/connectors/smithery/` lo usaba con
la API vieja, y 2.0.0 la retiró:

    streamablehttp_client        existe en 1.26 · NO existe en 2.0.0
    InitializeResult.serverInfo  1.x · en 2.x es `server_info`
    mcp.server.fastmcp           no existe en 2.0.0

Contraintuitivo y medido: **`mcp 1.26.0` ya exporta los DOS nombres del cliente**
(`streamablehttp_client` y `streamable_http_client`), pero el nuevo sobre `httpx` y el de
2.0.0 sobre `httpx2`, que es otro paquete. El corte no está en 1 vs 2: está en cuál
sobrevive y sobre qué stack HTTP corre.

Se cerró primero con un `mcp_compat.py` que abría el transporte con la API que hubiera.
**En la sesión 3 ese shim se borró**: se midió que nada del producto alcanza la mitad MCP de
smithery (0 filas en el registro · 0 llaves · ningún belt del catálogo la declara · ningún
router la importa) y sin embargo VIAJABA EN EL BUNDLE, porque el spec incluye
`platform/connectors` entero. Se movió a `spikes/smithery/` —donde ya vive `deep-chat`— y
sus dos call-sites pasaron a la API 2.x directa: con el pin ya decidido, un spike que
straddlea dos versiones del SDK es peor que uno que habla la pineada. Razón escrita en
`spikes/smithery/README.md`.

⚠️ **La otra mitad NO se movió.** `connections.py` (conexiones REST per-usuario) es stdlib
pura, no toca el SDK, y está en el **gate de boot** (`arranque.py::MODULOS_PLANOS`): moverla
habría hecho que la `.app` reportara un módulo nuestro ausente. La primera medición de la
sesión 3 no la vio y estuvo a punto de llevársela — el gate de boot la cazó.

`product/tutor-stem/tools/units_mcp.py` (que usa `mcp.server.fastmcp`) **no** corre riesgo:
vive en su propio venv.

### 8.5 · Lo que sigue perdido, y ya no importa tanto

- **El cuerpo del error HTTP** (§3). Sigue sin recuperarse. Con `http_status` de vuelta,
  ninguna regla del clasificador lo necesita — sólo el texto humano.
- **`exit_code`** (§8.1). Cuesta una línea de texto.

### 8.6 · Un incidente, para que no se repita

`calentar()` **persiste** (escribe el registro y hace commit). La primera corrida de
`verify_calentador_restore_sdk.py` —antes de tener el guard— le reescribió al usuario
`version_negociada` en cinco filas (filesystem · fetch · context7 · exa · pandoc) con la
revisión del SDK. Se restauró re-midiéndolas con `ALEPH_TRANSPORTE=viejo` y el registro
volvió a 14× `2024-11-05` + 28 sin dato.

La lección es del método, no del SDK: **una vara que para medir cambia lo que mide no es una
vara.** El guard vive en `_ConnSinCommit` y está documentado ahí.
