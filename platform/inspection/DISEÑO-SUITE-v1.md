# DISEÑO · SUITE DE CERTIFICACIÓN v1

**Escrito:** 2026-08-03 · **Base:** `main @ 7838eb9` (SDK + dueño + repair completos)
**Estado:** DISEÑO + RECONOCIMIENTO. Cero código.

Lo que falta antes de la certificación final en la `.app` es una **suite**: algo que corra
sola y diga si una conexión sirve, sin depender de que alguien se acuerde de probar. Este
documento decide cómo, y **mide qué hay hoy** — no qué debería haber.

Cada afirmación lleva su `archivo:línea`, verificada por `verify_citas_diseno_suite.py`.

---

## §0 · TRES CORRECCIONES AL PEDIDO, MEDIDAS ANTES DE DISEÑAR

Van primero porque cambian el trabajo.

### 0.1 · No son 11 pasos: son **12 verbos**

El contrato dice «LOS 12 VERBOS» (`CONTRACT-CONEXION-v1.md:476`) y su propio conteo cierra
en doce: **7 existen · 4 parciales · 1 no existe** (`CONTRACT-CONEXION-v1.md:491`). El
reparto del §2 va sobre los doce.

### 0.2 · ~~`onshape` **no es OAuth**, y no hay pieza que conectar~~ — **CORREGIDO 2026-08-03**

> ## ⛔ ESTA SECCIÓN ESTABA MAL. LAS DOS AFIRMACIONES ERAN FALSAS.
>
> **onshape ES OAuth, y su pieza existe.** Lo que sigue abajo se conserva tachado porque la
> lección de método vale más que el error: **una ausencia medida con `grep` sobre `main` no
> es una ausencia.** El trabajo estaba completo, verificado y **sin commitear** en un
> worktree hermano (`feat/oauth-onshape`, del 29-jul). Un `grep` sobre el árbol actual no ve
> eso, y las dos afirmaciones de esta sección salieron de ahí.
>
> Lo que hay hoy en `main` (`c930b1c`), medido:
>
> - **`catalog/connectors/onboarding/onshape.json`** declara `"auth_method": "oauth"`, con
>   `authorize_url`/`token_url` de `oauth.onshape.com`, **PKCE S256 obligatorio**, loopback
>   en `http://localhost:8765/oauth/callback` y seis scopes con su `action_class`.
> - **`product/belts/ingenieria/onshape_server.py`** existe: MCP por stdio con seis tools,
>   y la superficie nace de los scopes **concedidos** (`tools/list` no publica una operación
>   si su scope no vino en `token_response.scope`).
> - **El consentimiento OAuth se dio** y la lectura real corrió contra la cuenta:
>   `onshape_whoami` → `Thomas Aleph`. Las cuatro de escritura frenan en B4 por diseño.
>
> **Por qué «no anduvo» durante meses, medido:** el `client_secret` guardado estaba
> **vencido** (Onshape lo regeneró y el archivo local quedó con el viejo) y al `client_id`
> se le había **perdido el padding `=` de base64** al guardarlo — 39 chars en vez de 40.
> Ninguna de las dos es un bug de código, y las dos son silenciosas.
>
> **Consecuencia para esta suite:** el arquetipo OAuth ya no es uno solo. Ver §3.

<details><summary>El texto original, conservado (era falso)</summary>

Dos hechos, los dos medidos:

- **No es OAuth.** Su ficha declara `"auth_method": "personal_token"` con
  `"auth": {"scheme": "basic"}` y **dos** campos (`access_key` + `secret_key`)
  — `catalog/connectors/onboarding/onshape.json:3`, `:29`. Es un par de llaves con Basic
  auth, self-serve. Nunca hubo una app OAuth que registrar.
- **No existe un servidor MCP de onshape.** `grep` sobre todos los `*.mcp.json` de
  `catalog/`, `platform/` y `product/` no devuelve ninguno, y el barrido del verificador
  sobre las 62 entidades del catálogo tampoco lo lista. Lo único que existe es la ficha de
  **onboarding** — o sea el guion para pedirle las llaves al usuario, sin pieza detrás.

**El arquetipo OAuth existe, pero es otro.** De 28 fichas: 20 `personal_token`, 7 `oauth`,
1 `keyless`. Los siete OAuth reales son `gmail`, `google_drive`, `google_calendar`,
`classroom`, `slack`, `orcid`, `xero` (`catalog/connectors/onboarding/`).

> **DECISIÓN 0.A — el cuarto arquetipo pasa a ser `google_drive`, y `onshape` se reclasifica
> como el arquetipo «ficha sin pieza».**
>
> `google_drive` es OAuth de verdad, **está equipado por este usuario** (fila en el registro,
> `env_template` con `${GDRIVE_TOKEN}` y tres alias más desde §9.2) y tiene servidor propio
> (`product/belts/cowork/drive_server.py`). Es el que puede certificar el verbo `authorize`.
>
> **Alternativa descartada: resucitar onshape igual.** No hay nada que resucitar — no falló
> un registro de app, falta la pieza entera. Construir un MCP de onshape para tener el
> arquetipo sería construir producto adentro de una suite.

</details>

> **De la DECISIÓN 0.A no sobrevive nada, y por partida doble.** Su premisa —que onshape no
> era OAuth— era falsa (arriba). Y su conclusión —que el arquetipo OAuth pasaba a ser
> `google_drive`— también cayó, por un motivo distinto y medido aparte: **la app OAuth de
> Google nunca se registró**, así que `google_drive` no puede ejercitar `authorize` ni una
> vez. Los dos errores tienen la misma forma: se eligió el arquetipo por lo que el catálogo
> DECÍA, sin ejercitar el camino. El §3 tiene la corrección completa.
>
> **El arquetipo OAuth es `onshape`, y es OAuth self-serve:** el usuario autoriza su propia
> cuenta contra una app que persona usuaria registró, con **PKCE S256** y **listener loopback efímero**
> — un camino distinto del redirect-al-backend, y hoy el único de los cuatro con el ciclo
> entero medido de punta a punta.

### 0.3 · El diagnóstico exacto de por qué onshape «no anduvo»

Lo pedido era no dejarlo en «no anduvo». El propio conector lo dice, y coincide con lo medido:

    "validated_with_test_key": false
    "NO confirmé en vivo el label 'Create new API key', el prefijo/forma exactos de cada
     llave, ni el endpoint sessioninfo/versión. Sin test key, no validé."
    "dev-portal.onshape.com/keys es self-serve pero exige aceptar términos de desarrollador
     (fricción, no admin-gate)."
                                    — `catalog/connectors/onboarding/onshape.json:63`

Y **la llave no está en ninguna parte del entorno**, verificado en los tres lugares donde
podría estar: el `env` de la shell (nada con `onshape`), `infra/.env` — **que no existe; sólo
hay `infra/.env.example`** — y ese mismo ejemplo, que tampoco la menciona.

| paso | estado |
|---|---|
| registrar una app OAuth | **nunca aplicó**: onshape usa par de llaves, no OAuth |
| crear el par en `dev-portal.onshape.com/keys` | **self-serve**, pero exige aceptar términos de desarrollador |
| tener la llave a mano | **NO existe** en env, `infra/.env` (ausente) ni `.env.example` |
| validar contra `/api/users/sessioninfo` | **nunca se hizo** — sin llave no hay qué validar |
| que exista un MCP de onshape | **no existe** |

**Lo que falta es una decisión de producto, no un arreglo:** aceptar los términos de
desarrollador de Onshape con una cuenta, generar el par, y decidir si se construye la pieza.
Va a la lista de persona usuaria (§5) como tarea con dos salidas posibles, no como bug.

---

## §1 · GRABAR / REPLAYAR

### 1.1 · Hoy no existe nada

Medido: no hay grabación ni replay de conexiones MCP en el árbol. Lo que existe con nombres
parecidos es otra cosa — `guard_replay` (`platform/safety/guards.py:58`) es el guard
anti-SSRF de la tool sintetizada, y `events_replay` del flywheel es de eventos de UI.

### 1.2 · La forma

**Perilla, estilo Goose:** `ALEPH_GRABAR=<slug>` graba · `ALEPH_REPLAY=<slug>` reproduce ·
sin ninguna de las dos, todo corre como hoy. Mismo patrón que `ALEPH_DUENO`,
`ALEPH_TRANSPORTE` y `ALEPH_REPAIR`: **se lee en un solo lugar y en cada llamada**
(`dueno.py:110-112` es el molde).

> **DECISIÓN 1.A — se graba en la frontera del TRANSPORTE, no en la del proceso.**
>
> El punto es `transporte.servidor_stdio()` (`platform/inspection/transporte.py:175`): es el
> único lugar por donde pasan los dos clientes, y `test_frontera_transporte.py` ya lo
> congela. Un `ServidorGrabador` que envuelve al real y anota `initialize` / `list_tools` /
> `call_tool` con su respuesta.
>
> **Alternativa descartada: grabar el stdio crudo (bytes del pipe).** Es más fiel y sirve
> para cualquier cliente futuro, pero (a) el JSON-RPC del SDK trae ids que cambian entre
> corridas y habría que normalizarlos para comparar, y (b) no captura el
> `diagnostico()` —stderr, `murio`, `t_eof`, los timeouts de R1— que es justo lo que hace
> útil una grabación cuando algo falla. Se graba el nivel donde ya está el significado.

### 1.3 · El path — **DECLARADO, no escondido**

    platform/inspection/grabaciones/<arquetipo>/<paso>.json

Ejemplo: `platform/inspection/grabaciones/fred/03-list_tools.json`.

> **DECISIÓN 1.B — dentro del repo y versionadas.**
>
> **Alternativa descartada: `~/Library/Application Support/Aleph/grabaciones/`.** Es donde
> viven `aleph.db` y `procesos.jsonl`, así que sería el lugar «natural». Se descarta porque
> una grabación **es un fixture, no un dato del usuario**: tiene que viajar con el commit
> que la hizo válida, y en CI —donde no hay Application Support— no existiría. Que estén en
> el repo también las hace revisables en el diff, que es donde se nota si una grabación
> trae algo que no debería.
>
> **Alternativa descartada: `qa/` o `reports/`.** Ahí viven evidencias de corridas pasadas
> (`reports/step-4.5-e2e/`); una grabación es un insumo de ejecución, no un informe.

### 1.4 · El formato

```json
{
  "arquetipo": "fred",  "paso": "list_tools",  "transporte": "stdio",
  "grabado_en": "2026-08-03T…",  "huella_receta": "a1b2c3d4e5f6",
  "peticion":  {"metodo": "tools/list", "args": {}},
  "respuesta": {"tools": [...]},
  "diagnostico": {"stderr": "…", "exit_code": null, "murio": false,
                  "server_info": {"name": "…", "version": "…"}}
}
```

**`huella_receta` es la que decide si la grabación sirve** — es la misma huella de 12 hex del
dueño (`dueno.py:150-186`), calculada sobre el env DECLARADO desde §9.2. Si la receta cambia,
la huella cambia, y la grabación deja de corresponder a lo que se está probando.

⚠️ **NINGUNA GRABACIÓN GUARDA UNA CREDENCIAL.** Se graba con la llave-basura que el
verificador ya usa (`BASURA = "clave-falsa-de-prueba-0000"`,
`conexiones_verificador.py:45`), y todo lo grabado pasa por el mismo `OutputScrubber` que R5
puso en la traza — con la lección de R5 incluida: **`.scrub()` devuelve un `ScrubReport`, no
un string** (`repair.py`, `_limpiar_traza`). Un verde falso ahí ya costó una vez.

### 1.5 · Qué pasa cuando una grabación queda vieja

> **DECISIÓN 1.C — AVISA Y FALLA. No se regraba sola.**
>
> Al replayar se compara la `huella_receta` de la grabación con la de la receta viva. Si no
> coinciden, la suite se pone **roja** y dice qué cambió, con el comando exacto para regrabar.
>
> **Alternativa descartada: regrabar automáticamente.** Es cómodo y es exactamente cómo una
> suite deja de significar algo: la grabación se actualiza sola contra el comportamiento
> nuevo —incluido el que rompió algo— y el verde de mañana ya no dice lo mismo que el de hoy.
> Regrabar es una decisión con autor, igual que declarar en el catálogo.
>
> **Alternativa descartada: ignorar la desactualización y replayar igual.** Peor: verde sobre
> una receta que ya no existe.

---

## §2 · EL REPARTO — LOS 12 VERBOS, UNO POR UNO

**ROBOT** = corre en CI, sin humano, contra grabaciones. **PERSONA USUARIA** = va a su lista (§5).

| # | verbo | quién | por qué |
|---|---|---|---|
| 1 | **resolve** | 🤖 ROBOT | es una consulta a un registry con cache; el registry público ya se midió intermitente-lento (`reports/step-4.5-e2e/S0-preflight.md:99`), así que **se replaya** o el CI hereda esa flakiness |
| 2 | **prepare** | 🤖 + 👤 | el ROBOT verifica que `ensure_user_path` y el intérprete resuelven; **instalar un programa que falta es de persona usuaria** — es su máquina |
| 3 | **authorize** | 👤 **PERSONA USUARIA** | un consentimiento OAuth es un navegador y una cuenta real. Nada que un robot pueda hacer sin fingir. El robot sí verifica **después**: que el token quedó cifrado y que no está en el manifest (§4) |
| 4 | **connect** | 🤖 ROBOT | grabable de punta a punta |
| 5 | **initialize** | 🤖 ROBOT | el saludo y la versión negociada son deterministas; `verify_transporte_sdk.py` ya cubre el puente |
| 6 | **list_tools** | 🤖 ROBOT | grabable |
| 7 | **verify** | 🤖 ROBOT | es el motor midiendo; ya corre solo sobre las 62 (`conexiones_verificador.py:576`) |
| 8 | **invoke** | 🤖 + 👤 | lectura pura: robot. **Una tool con efecto la ejecuta persona usuaria**: probar una escritura ES escribir (CLAUDE.md) |
| 9 | **persist** | 🤖 ROBOT | el verbo que **no existe** (`CONTRACT-CONEXION-v1.md:489`). La suite lo prueba como está: que el registro reconstruya |
| 10 | **restore** | 🤖 ROBOT | `verify_calentador_restore_sdk.py` ya lo cubre |
| 11 | **repair** | 🤖 ROBOT | **completo desde R5**, con perilla. `verify_repair_e2e.py` ya recorre el ciclo entero |
| 12 | **disconnect** | 🤖 ROBOT | la lápida es determinista; `verify_sesion_dueno.py` ya prueba que mata aunque esté prestada |

**Nueve robot, tres con parte humana** (2, 3, 8), y de ésos sólo el **3** es enteramente de
persona usuaria.

### 2.1 · El Inspector CLI como segunda opinión

`npx @modelcontextprotocol/inspector --cli` — el inspector oficial, útil donde nuestro
veredicto podría estar equivocado por ser nuestro: **pasos 5, 6 y 8**. Si los dos dicen lo
mismo, el veredicto no depende de nuestro cliente.

⚠️ **NO ESTÁ EN EL ÁRBOL NI INSTALADO**, medido: cero referencias en el repo y `npx` intentó
descargarlo (se canceló). Entra como **opcional**: si no está, la suite lo dice y sigue —
nunca se cuelga esperando una descarga, que es exactamente lo que pasó al medirlo.

⚠️ **SU BUG CONOCIDO, y hay que manejarlo al revés de lo natural:** cuando el server no
arranca, el Inspector reporta el fallo **en el `message`** y el **exit code no lo refleja**.
Hay que **parsear `ENOENT` del mensaje ANTES de mirar el exit code** — al revés se lee un
`0` y se cree que el server anduvo. Es el mismo tipo de trampa que R1 midió con `McpError`:
el canal que parece autoritativo (el tipo, el exit code) no lo es.

---

## §3 · LOS 4 ARQUETIPOS — ESTADO REAL, MEDIDO HOY

> ### CORRECCIÓN DE ARQUETIPOS (persona usuaria, 2026-08-03): `google_drive` sale, `onshape` es el OAuth
>
> Siguen siendo **cuatro**, pero no los mismos cuatro. La casilla OAuth se la queda `onshape`
> y `google_drive` sale de la suite.
>
> **El motivo, medido en su propia ficha:** `google_drive.json` **no tiene `client_id`**. Lee
> `GOOGLE_CLIENT_ID` del entorno (`oauth.client_id_env`) y **`infra/.env` no existe en ningún
> worktree** — o sea que esa variable no tiene de dónde salir. La ficha además se autodeclara
> sin validar: `validated_with_test_key: false`, `anchor_ok: false`, y en sus notas *«REQUIERE
> app OAuth de Google registrada + verificación para estos scopes»*. **La app nunca se
> registró** (papeleo pendiente de Google).
>
> Y eso es lo que lo saca: **un arquetipo que no se puede ejercitar no certifica un verbo.**
> `google_drive` no puede dar el paso de `authorize` ni una vez, así que tenerlo en la suite
> sería tener una casilla que siempre reporta «pendiente» — que es ruido, no cobertura.
> Vuelve el día que la app exista.
>
> ⚠️ **UNA PRECISIÓN SOBRE EL SEGUNDO MOTIVO, PORQUE ESTABA MAL ATRIBUIDO.** La corrección
> llegó diciendo que a `google_drive` además lo excluye `loopback_ok: false`. Medido: **la
> ficha de `google_drive` no declara ese campo** —ni `redirect_uri`—, porque no va por
> loopback sino por el Caso A clásico con redirect al backend. **`loopback_ok: false` es de
> `onshape`**, y dice lo contrario de lo que ese argumento supone: Onshape **exige
> `client_secret` en el canje aun con PKCE S256**, así que el loopback de cliente público
> puro no le alcanza. Aplicada al pie de la letra, esa regla excluiría a `onshape`, que es
> justo el que se conserva. Se anota acá para que nadie la reaplique más adelante creyendo
> que sostenía la decisión: **la decisión se sostiene sola con la app no registrada.**
>
> **La salvedad de `onshape`, dicha y no tapada:** su `verification.loopback_verdict` es
> *«la distribución necesita account broker; el secreto local es sólo un override de
> desarrollo fuera del bundle»*. O sea que el arquetipo OAuth de la suite hoy corre sobre un
> secreto **de desarrollo**, y el camino distribuible todavía no existe. Eso no lo invalida
> para certificar el verbo —el ciclo completo se midió de punta a punta— pero es una
> limitación que la suite tiene que arrastrar visible, no una letra chica.

Barrido del verificador sobre las 62 del catálogo, `main @ 7838eb9`; la fila de onshape
medida sobre `main @ c930b1c`:

| arquetipo | pieza | ¿corre hoy? | qué le falta |
|---|---|---|---|
| **llave + stdio** | `fred` | **SÍ** · `arranca=True · conexion=viva` · en el registro con `credencial_ref=fred` | nada para correr. `credencial=sin_medir`: la llave existe pero **no se probó contra el proveedor** |
| **HTTP** | `exa` | **SÍ** · `viva` · **`credencial=verde`** — el único con credencial PROBADA | nada. Es el arquetipo más sano |
| **Descarga** | `freecad` | **SÍ** · `viva` · `credencial=no_aplica` | **FreeCAD está instalado** (`/Applications/FreeCAD.app` + `freecadcmd` presentes). Pero el belt además exige el **addon** `FreeCADMCP` en `~/Library/Application Support/FreeCAD/v1-1/Mod/` — eso **no se verificó** |
| **OAuth self-serve** (PKCE + loopback) | **`onshape`** | **SÍ, y es el único de los cuatro con el ciclo COMPLETO medido**: consentimiento dado, token y scopes cifrados en el vault, lectura real ejecutada (`onshape_whoami` → `Thomas Aleph`) por `ServidorSDK` | **no está equipado en ningún belt**: `belt-onshape.mcp.json` existe pero no lo referencia ninguna receta y no declara `base_matrix`. Sus tools no aparecen en el cinturón de ningún agente. Y para distribuir hace falta el account broker (`loopback_ok: false`) |
| ~~**OAuth clásico**~~ | ~~`google_drive`~~ | **FUERA DE LA SUITE** (corrección de arriba) | la app OAuth de Google **nunca se registró**; sin `client_id` no hay `authorize` que ejercitar. Vuelve cuando exista |

**Y un quinto que la suite tiene que mirar aunque no sea arquetipo:** `fred_official`
—`arranca=False · conexion=rota · causa=arranque`— es la única de las cinco piezas
relacionadas que está rota, y es la variante «oficial» del mismo servicio que `fred`. Dos
piezas para el mismo proveedor, una viva y otra rota, es exactamente el tipo de cosa que una
suite existe para no dejar pasar.

---

## §3·bis · LA LEY DE NOMBRES — SE NOMBRA POR TIPO, JAMÁS POR SERVICIO

> **Sellada por persona usuaria, 2026-08-03.** Vigilada por `qa/verify_nombres_suite.py`, vara
> permanente y bloqueante.

Las varas del arnés se nombran por **tipo de conexión**. El conector concreto es un
**parámetro** del arnés —un ejemplar, un fixture— nunca parte del nombre del archivo.

| arnés | cubre | ejemplar HOY |
|---|---|---|
| `qa/verify_oauth.py` | todo OAuth | `onshape` |
| `qa/verify_llave_stdio.py` | todo llave + stdio | `fred` |
| `qa/verify_http.py` | todo HTTP | `exa` |
| `qa/verify_descarga.py` | todo Descarga | `freecad` |

**LOS CUATRO SON PERMANENTES: son arquitectura, no una lista de tareas.** Cada conector que
exista o que llegue cae en uno de los cuatro, y su tipo siempre está ahí para probarlo. Lo
único que rota son los **ejemplares** —hoy `onshape` encarna OAuth, mañana puede encarnarlo
otro— y los **fixtures**, que se suman cuando un bug real enseña un caso nuevo.

**Por qué es una ley y no una preferencia.** Un archivo por servicio parece inocente y hace
dos daños. El primero: el arnés se fragmenta, y lo que se prueba deja de ser «el camino
OAuth» para ser «lo que se le ocurrió probar a quien tocó onshape». El segundo, peor: cuando
llega el conector 29, **nadie sabe qué se le tiene que exigir**, porque el contrato del tipo
no está escrito en ningún lado — está repartido en N archivos que se parecen. Con un arnés
por tipo, sumar un conector es sumar un ejemplar, y lo que se le exige **ya está decidido**.

**Corolario, y también vigilado:** un bug de un conector concreto entra como **caso del
arnés de su tipo**, jamás como archivo propio. Un bug es evidencia de que al tipo le faltaba
un caso; archivarlo aparte lo esconde del próximo conector que lo va a sufrir igual.

### Los transitorios, con vencimiento automático

Dos archivos existentes violan la ley, y los dos nacieron antes que ella:

| archivo | se absorbe en | qué es |
|---|---|---|
| `qa/verify_onshape_oauth.py` | `verify_oauth.py` | las calibraciones del ciclo completo (PKCE, loopback, scope→superficie, refresh, revocación) |
| `qa/verify_onshape_lectura_real.py` | `verify_oauth.py` | el caso «con consentimiento dado, el tipo OAuth entrega datos» |

**La excepción vence sola.** `verify_nombres_suite.py` los tiene declarados con su arnés
destino: en cuanto `verify_oauth.py` exista, los dos tienen que haber desaparecido — y si
siguen ahí, la vara se pone **roja** hasta que se borren. Una excepción sin vencimiento es
una excepción para siempre.

> **La lista de servicios sale del CATÁLOGO, no de una constante.** Son las fichas de
> `connectors/onboarding/` **más** los `mcpServers` de todos los belts — 71 nombres hoy.
> Escribirla a mano haría que el conector 29 entrara sin que nadie lo mirara, que es el
> agujero que esta vara existe para tapar. (Y son las dos fuentes por algo medido: mirando
> sólo las fichas, `freecad` «no existía» — las piezas de tipo Descarga no tienen ficha de
> onboarding porque no piden credencial sino una app instalada.)

---

## §4 · EL CHECK PENDIENTE: BYO HEADERS EN CLARO

> ### ✅ CERRADO EN S4 (2026-08-04). Lo de abajo es el diagnóstico ORIGINAL, y se deja tal cual.
>
> Se deja porque un diseño que borra el problema cuando lo arregla pierde la única parte que
> vale releer: **por qué** era un problema. El estado de hoy:
>
> · los valores de los headers van **cifrados al llavero** (Fernet, `repo.upsert_key`), como
>   cualquier otra credencial del producto — o sea que el BYO-HTTP dejó de ser el único
>   camino que esquivaba la regla «nombres, jamás valores»;
> · el `manifest.json` guarda un placeholder `${VAR:Header}` y queda en **`0600`** siempre,
>   tenga o no headers (un permiso condicionado a que hoy haya secreto se olvida el día que
>   lo haya);
> · **falla cerrado**: si el llavero no está disponible, NO se escribe el manifest. Un BYO
>   registrado con el token en claro es peor que un BYO no registrado — el usuario puede
>   volver a pegarlo, el token filtrado no se despega;
> · el puente ya sabía expandir `${VAR}` en runtime (`byo_mcp_server._expand_env`); S4 le
>   agregó la forma `${VAR:Header}` porque los headers viajan como **un paquete JSON en UNA
>   fila del vault**: una credencial en la UI, una rotación, un borrado.
>
> `verify_byo_headers.py` —escrito ROJO en S1 a propósito— pasó a verde **sin que se le
> tocara una aserción**; lo único que cambió es el ARRANGE (el vault de prueba necesita
> schema y un dueño, justamente porque el camino nuevo falla cerrado). Queda de guardia.

**Verificado en el código, y la respuesta es SÍ.**

```
byo_mcp.py:413-421
    manifest = {
        "url": probe["url"],
        "headers": probe.get("headers") or {},      ← el token, TAL CUAL
        "allowed_tools": tool_names,
        "label": nice,
    }
    manifest_path.write_text(json.dumps(manifest, …), encoding="utf-8")
```

Los headers que el usuario pega —que es donde vive un `Authorization: Bearer …`— van
**verbatim a un `manifest.json` en disco, sin cifrar**. Dos líneas más abajo el propio código
los reconoce como secreto: `has_secret = bool((probe.get("headers") or {}))`
(`byo_mcp.py:422`).

**Empíricamente en esta máquina:** hay **un** manifest forjado
(`~/Library/Application Support/Aleph/synth_belts/…/byo-ai-exa-exa/manifest.json`) y su
`headers` está **vacío** —ese MCP de exa es keyless por URL— así que **hoy no hay ningún
token filtrado**. Pero el camino está vivo y sus permisos son **`-rw-r--r--`: legible por
cualquier proceso o usuario de la máquina.**

Contrasta con la regla que el resto del producto sí cumple: el registro guarda **nombres,
jamás valores** (`env_template`), con un guard duro que levanta si a alguien se le escapa un
literal (`conexiones_repo.py:135`, `_sin_secretos`). El BYO-HTTP es el único camino que
esquiva esa regla.

> **DECISIÓN 4.A — entra a la suite como check de SEGURIDAD, con dos aserciones.**
>
> 1. forjar un BYO-HTTP con un header falso reconocible y **exigir que no aparezca en el
>    manifest** → hoy **falla**, y tiene que fallar: es el bug;
> 2. exigir que el manifest **no sea legible por otros** (`0600`).
>
> **Alternativa descartada: arreglarlo en esta sesión.** Es diseño y reconocimiento; y el
> arreglo no es de una línea — hay que decidir si el header va al llavero cifrado (como el
> resto) o si el manifest se cifra. Eso es una sesión de construcción con su vara.

---

## §5 · LA LISTA DE PERSONA USUARIA

**Un archivo, no una UI.** Path declarado: `platform/inspection/TAREAS-CERTIFICACION.md`,
regenerado por la suite en cada corrida.

### 5.1 · El formato

```markdown
# Tareas para persona usuaria · certificación
Generado por la suite el 2026-08-03 14:22 · main @ 7838eb9
Quedan 3 tareas. El robot ya hizo 9 de los 12 pasos.

---
## 1 · Darle permiso a Google Drive          ⏱ 2 minutos

**Qué hacer**
1. Abrí Aleph y andá a Conexiones.
2. Buscá «Google Drive» y tocá **Conectar**.
3. Se abre el navegador con la pantalla de Google. Elegí tu cuenta.
4. Google te va a pedir permiso para **ver tus archivos**. Tocá **Permitir**.

**Qué tenés que ver al terminar**
La tarjeta de Google Drive en 🟢 y abajo «probado». Si queda 🔴, copiá lo que
dice y pegámelo.

**Por qué no lo hace el robot**
Es tu cuenta y tu consentimiento. Un robot que lo hiciera solo estaría
entrando a tu Google, y eso no lo puede decidir un test.
---
```

**Las cinco reglas del formato**, cada una con su motivo:

1. **Pasos numerados, un solo verbo cada uno.** «Tocá Conectar», no «configurá la conexión».
2. **Sin jerga.** No aparecen «OAuth», «token», «endpoint» ni «MCP». La tarea 3 del §2 se
   llama «darle permiso a Google Drive», que es lo que la persona va a hacer.
3. **«Qué tenés que ver» siempre**, y en términos de pantalla —🟢, un texto— no de logs. Es
   la única forma de que persona usuaria sepa si terminó bien sin leer un archivo.
4. **«Por qué no lo hace el robot», siempre.** Sin eso la lista se lee como que el robot es
   flojo. Con eso se lee como una frontera.
5. **Tiempo estimado.** Cambia si se hace ahora o después.

> **DECISIÓN 5.A — la lista se REGENERA entera en cada corrida, no se edita.**
>
> Una tarea que ya no hace falta **desaparece**; una nueva aparece arriba. Si persona usuaria la
> tacha a mano y la suite la vuelve a escribir, es que el paso sigue sin estar hecho — y
> eso es información, no un choque.
>
> **Alternativa descartada: una lista con checkboxes que persiste.** Se desincroniza:
> queda un ✅ de algo que se rompió después, y una lista que miente sobre lo hecho es peor
> que no tenerla.

### 5.2 · Las tres tareas de HOY, medidas

1. **Darle permiso a Google Drive** — el único verbo enteramente humano (§2, paso 3).
2. **Confirmar el addon de FreeCAD** — el belt exige `FreeCADMCP` en
   `~/Library/Application Support/FreeCAD/v1-1/Mod/` y **no está verificado**. FreeCAD sí
   está instalado.
3. **Decidir qué se hace con Onshape** — con las dos salidas escritas: (a) aceptar los
   términos de desarrollador y generar el par de llaves, o (b) **sacarlo del catálogo**,
   porque hoy hay una ficha de onboarding que le promete al usuario una pieza que no existe.

---

## §6 · LO QUE NO CUBRE

1. **No prueba la `.app`.** Todo esto corre contra el árbol. El ciclo abrir → escribir →
   cerrar con cero procesos MCP después es la certificación, y es otra cosa.
2. **No prueba HTTP de verdad.** El verificador declara que el transporte http «no está
   cableado» (`conexiones_verificador.py:589-592`); `exa` corre por stdio. El arquetipo HTTP
   se certifica por el camino BYO (§4), que es el único HTTP vivo.
3. **No cubre el fallo parcial**: un server vivo cuyas tools devuelven basura sin error. Mismo
   hueco que declaró repair (§9.4 de `DISEÑO-REPAIR-v1.md`).
4. **Las grabaciones envejecen y alguien tiene que regrabarlas.** La suite avisa; no arregla.
5. **El Inspector CLI es opcional y puede no estar.** Cuando falta, esos tres pasos tienen
   una sola opinión: la nuestra.
6. **No mide performance.** El reloj se reporta, nunca gatea — trampa 8 del acta, y la
   lección que `verify_calentador_restore_sdk` ya pagó dos veces.
7. **`persist` se prueba como está, no como debería.** Es el verbo que no existe; la suite
   documenta el hueco, no lo tapa.
8. **No hay arquetipo OAuth certificable hasta que persona usuaria dé el consentimiento.** Hasta
   entonces el paso 3 está declarado y sin cubrir, no verde.

---

## §7 · PLAN DE CONSTRUCCIÓN

| sesión | qué construye | vara verde que la cierra |
|---|---|---|
| **S1** ✅ | **grabar y replayar, y nada más.** El `ServidorGrabador` en la frontera del transporte · las dos perillas · el formato · el path. Sin suite todavía. | Grabar `fred` y replayarlo **sin red y sin llaves** da el MISMO veredicto · una receta cambiada pone la grabación en rojo y dice cómo regrabar · ninguna grabación contiene un secreto (vara con un server que imprime uno) · regresión completa |
| **S2** | **la suite de los 9 pasos robot**, sobre los 4 arquetipos, replayando. Acá nacen los CUATRO ARNESES con su nombre canónico (§3·bis) — `verify_oauth.py` · `verify_llave_stdio.py` · `verify_http.py` · `verify_descarga.py` — y los dos transitorios de onshape se absorben y se borran. | Los 9 verdes con la red apagada · el veredicto por arquetipo idéntico al del barrido en vivo · el Inspector CLI como segunda opinión donde está, y declarado ausente donde no · **su bug manejado**: ENOENT del mensaje antes del exit code |
| **S3** (el check §4 ya entró en S1, ROJO a propósito) | **el check de seguridad BYO** (§4) + **la lista de persona usuaria** (§5). | El check arranca **ROJO** y lo dice con el `archivo:línea` · la lista se genera, se regenera, y una tarea cumplida desaparece sola |
| **S4** | **el arreglo del BYO** (header al llavero o manifest cifrado) — recién con S3 roja y midiendo. | El check de S3 pasa a VERDE · el manifest en `0600` · el token no aparece en disco · regresión completa |

**Vara transversal, en todas:** veredictos idénticos sobre las 62 · regresión en los dos
entornos · cero huérfanos por `ps` filtrado a este worktree · las 12 varas del dueño y de
repair verdes **sin tocarlas** · **`verify_nombres_suite.py` verde** (§3·bis: ninguna vara
nueva nombrada por servicio, y ningún transitorio sobreviviendo a su arnés).

---

## §8 · TABLA DE CITAS

| afirmación | archivo:línea |
|---|---|
| son 12 verbos, no 11 | `CONTRACT-CONEXION-v1.md:476` |
| conteo 7 existen · 4 parciales · 1 no existe | `CONTRACT-CONEXION-v1.md:491` |
| `persist` no existe | `CONTRACT-CONEXION-v1.md:489` |
| onshape es `personal_token`, no OAuth | `catalog/connectors/onboarding/onshape.json:3` |
| onshape usa Basic con dos llaves | `catalog/connectors/onboarding/onshape.json:23` |
| onshape nunca se validó con una llave real | `catalog/connectors/onboarding/onshape.json:63` |
| sólo hay `infra/.env.example`, no `.env` | `ls infra/` |
| el guard anti-SSRF NO es replay de conexiones | `platform/safety/guards.py:58` |
| la perilla se lee en un solo lugar (molde) | `dueno.py:110-112` |
| el switch único del transporte | `platform/inspection/transporte.py:175` |
| la huella de 12 hex | `dueno.py:150-186` |
| la llave-basura del verificador | `conexiones_verificador.py:45` |
| el barrido corre sobre las 62 | `conexiones_verificador.py:576` |
| http no cableado por el verificador | `conexiones_verificador.py:589-592` |
| ~~los headers van en claro al manifest~~ · **cerrado**: el valor va al llavero | `byo_mcp.py:493-499` |
| ~~el código los reconoce como secreto~~ · **cerrado**: el manifest queda en `0600` | `byo_mcp.py:500-512` |
| el registro guarda nombres, jamás valores | `conexiones_repo.py:135` |
| el registry público es intermitente-lento | `reports/step-4.5-e2e/S0-preflight.md:99` |
| freecad exige el addon FreeCADMCP | `catalog/templates/ingenieria/belt-ingenieria.mcp.json` (`requiere_app` de `freecad`) |
