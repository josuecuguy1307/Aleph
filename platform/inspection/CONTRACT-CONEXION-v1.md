# CONTRATO DE CONEXIÓN MCP v1 — 📝 REDACTADO, pendiente de congelamiento

> **Estado: REDACTADO el 2026-07-31 · revisión 4. Pendiente de revisión y congelamiento.**
> Confirmado contra el código REAL del worktree `fix/una-tarjeta` @ `58270fb`, no contra
> una idea: cada afirmación sobre el estado actual lleva `archivo:línea` verificado, y lo
> que no se pudo verificar dice **«sin verificar»** en vez de afirmarse.
>
> **Revisión 3 cierra los tres huecos que la 2 dejó abiertos:** la receta HTTP tiene dónde
> vivir (`url` + los dos campos de headers, migración v4 del cliente); `cwd` y `timeout_ms`
> pasaron de declarados a **ejecutables**; y «restaurar deja la pieza en amarillo» quedó
> escrito como **regla** en §3 en vez de seguir siendo una consecuencia accidental. Los tres
> están marcados en su sección, no listados acá.
>
> **Revisión 4 pone la lápida a funcionar (§4).** `habilitado` existía en el registro y no
> lo leía nadie; ahora el restaurador lo obedece **salteando** la pieza — que NO es lo
> mismo que caer al fallback, y la diferencia es toda la sección. Las dos acciones quedan
> separadas y las dos viven adentro de `[Revisar]`: desconectar deja la llave, borrar la
> llave es aparte y con confirmación. Con esto el verbo 12 pasa de «no existe» a existente
> (§5): quedan **7 existen · 4 parciales · 1 no existe**.
> **Cambios incompatibles ⇒ nueva versión + migración, jamás edición silenciosa de v1.**
> Owner: pendiente de asignación en la revisión.

Fuente de verdad de **«qué es una conexión a un servicio externo, qué se guarda de ella, y
qué garantiza cada verbo»**. Todo lo que conecte, pruebe, repare o desconecte un servidor
MCP codea contra ESTE contrato.

**Dónde vive este archivo:** `platform/inspection/`. Es el directorio que ya concentra la
mayoría del código específico de conexiones MCP —`mcp_resolver.py`, `mcp_registry.py`,
`mcp_matcher.py`, `mcp_http_client.py`, `byo_mcp.py`, `byo_mcp_server.py`—, igual que
`CONTRACT-AUTH-v1-FROZEN.md` vive en `platform/auth/` junto a `supabase_jwt.py`. **No va en
`reports/`**: una auditoría previa encontró contratos vivos escondidos ahí, donde nadie los
busca.

---

## 0. La invariante madre

> **El registro guarda CÓMO RECONSTRUIR una conexión. Nunca guarda un proceso, un PID, un
> descriptor ni una sesión viva.**

Un proceso muere con la app. Una receta sobrevive. Reabrir Aleph es **volver a ejecutar la
receta**, no resucitar nada. Todo lo demás de este contrato se deriva de esa línea.

---

## 1. EL REGISTRO — una fila por entidad

Una **entidad** es un servicio conectable: un servidor MCP de terceros, un servidor MCP
propio, o una cuenta con credencial. Una fila por entidad; nunca una fila por proceso ni
por sesión.

### Dónde vive — **tabla nueva en `aleph.db`**

Tres razones, en orden:

1. **Es el único almacén con migraciones, backup y WAL.** SQLite del cliente ya corre en
   modo WAL (`platform/db/session_manager` equivalente: `platform/db/sqlite_db.py`), tiene
   backup (`platform/db/backup.py`) y tiene carril de evolución de esquema.
2. **`motor_estado.json` es caché, no fuente de verdad.** Guarda veredictos y evidencia
   (`product/backend/app/phase1/motor_verdad.py:166-178`, escritura en `:208`); perderlo
   debe costar una re-verificación, no una conexión.
3. **`puppets.config` ataría la conexión al agente**, que es exactamente lo contrario de
   «un servicio = una entidad». Un servidor equipado en tres agentes tendría tres verdades.

### Alcance — **por usuario**

La fila lleva `user_id`, siguiendo la forma que el esquema ya tomó en `keys`:
`UNIQUE (user_id, provider)` (`platform/db/schema_sqlite.sql:151`). Hoy es teórico en una
app monousuario, pero el esquema ya eligió y la coherencia cuesta cero ahora; retrofitear
`user_id` después cuesta una migración de datos.

### Campos

| Grupo | Campo | Qué es |
|---|---|---|
| **identidad** | `entity_id` | identificador estable de la entidad |
| | `user_id` | dueño de la conexión |
| | `nombre_visible` | lo que ve el usuario |
| | **`transporte`** | `stdio` \| `http` — **explícito** |
| **receta** | `command` | el ejecutable |
| | `args` | argumentos |
| | **`cwd`** | working directory del proceso hijo |
| | `env_template` | plantilla de entorno con placeholders `${VAR}` — **nombres, jamás valores** (§2) |
| | `env_publico` | literales **públicos declarados** que viajan tal cual (§2) |
| | **`timeout_ms`** | tope por request, en milisegundos |
| **receta HTTP** | **`url`** | endpoint del MCP remoto |
| | **`headers_template`** | headers con referencias `${VAR}` — **nombres, jamás valores** (§2) |
| | **`headers_publico`** | headers **públicos declarados** que viajan tal cual (§2) |
| **credencial** | `credencial_ref` | referencia **por nombre**, jamás el valor (§2) |
| | `scopes` | permisos otorgados |
| | `cuenta` | qué cuenta autorizó |
| **protocolo** | **`era`** | era del protocolo con la que se habló |
| | **`version_negociada`** | lo que devolvió el `initialize` |
| | `server_info` | nombre/versión que declaró el servidor |
| **capacidad** | `tools_snapshot` | lista de tools de la última verificación exitosa |
| | `fingerprint` | firma de la configuración probada |
| | `recipe_version` | versión del esquema de la receta, para migrar |
| **estado** | **`habilitado`** | la lápida (§4) |
| | `ultimo_veredicto` | resultado de la última verificación |
| | `causa` | causa tipada, si no está sano |
| | `ultima_verificacion` | cuándo se midió |

### Los seis campos NUEVOS

Estos **no existen hoy en ninguna de las cuatro fuentes** (§9.2) y se declaran como nuevos
en v1:

1. **`cwd`** — ✅ **EJECUTABLE desde 2026-07-31.** El formato `.mcp.json` de Aleph sigue sin
   declararlo (ninguno de los 16 archivos del catálogo tiene la clave), así que el backfill
   lo deja vacío a propósito y ninguna fila de HOY lo usa. Pero el camino existe entero: el
   registro lo guarda, `MCPServer.__init__` lo acepta y lo pasa a `Popen`
   (`platform/assembler/assembler.py`), y el restaurador lo lee de la fila. Una entidad con
   `cwd` declarado se levanta con ese working directory en vez de caer al fallback.
2. **`timeout_ms`** — ✅ **EJECUTABLE por el camino del registro.** `_timeout_de`
   (`platform/assembler/restaurador.py:190-199`) lo convierte a segundos y se lo pasa a
   `MCPServer`; vacío cae al default de siempre (`rpc_timeout: float = 30.0`,
   `platform/assembler/assembler.py:42`). El backfill lo deja vacío a propósito, así que
   hoy todas las filas usan el default — pero por decisión ausente, no por falta de camino.
   Fuera del restaurador nadie lo pasa: `byo_mcp.py:206` es el único otro caller y usa su
   propio `timeout`.
3. **`transporte` explícito** — hoy se deduce de la forma del registro: si hay `command` se
   asume stdio, si hay `url` se asume HTTP. La deducción vive repartida entre
   `platform/inspection/mcp_resolver.py` (paso 3) y el ruteo de belts; **no hay un campo que
   lo declare**.
4. **`era`** — el protocolo MCP se partió en dos eras (handshake `initialize` vs
   `server/discover`). El cliente propio solo conoce la primera:
   `PROTOCOL_VERSION = "2024-11-05"` (`platform/assembler/assembler.py:34`) y
   `_PROTOCOL_VERSION = "2024-11-05"` (`platform/inspection/mcp_http_client.py:26`).
5. **`version_negociada`** — se calcula pero se pierde: vive en
   `MCPServer._protocol_evidence` (`platform/assembler/assembler.py:60`), en memoria, y solo
   sale por `diagnostico()` (`:167`) mientras el proceso vive.
6. **`habilitado`** — ✅ **VIVO desde 2026-07-31.** El registro lo guarda, dos acciones lo
   escriben (`desconectar` / `reconectar`) y el restaurador lo OBEDECE salteando la pieza.
   Ver §4, que es donde vive la sección entera.

### La receta HTTP — `url` + los dos campos de headers

Un servidor HTTP **no tiene `command` ni `args`**: tiene un endpoint y unos headers. Hasta la
v4 del schema el registro no tenía dónde ponerlos, así que una conexión HTTP se guardaba
incompleta y en silencio — el §0 dice que la fila es la receta, y esa fila no alcanzaba para
reconstruir nada.

**Los headers se parten igual que el entorno, por la misma razón (§2).** Un token en un
header es tan secreto como en una env var. `headers_template` lleva las referencias
(`Authorization: "Bearer ${TOKEN}"`), `headers_publico` los literales declarados
(`X-Client: "Aleph/1.0"`). Es el mismo guard y la misma función de reparto: `repartir_env`
no distingue entre uno y otro, y **no debe**, porque mantener dos criterios parecidos es
cómo se desincronizan.

> La única diferencia de forma es que un header **embebe** la referencia y una env var suele
> ser la referencia entera. Por eso el criterio es «contiene `${VAR}`», no «es `${VAR}`».

**Lo que esto NO resuelve.** Un MCP HTTP en Aleph se ejecuta hoy como un **proxy stdio**:
`byo_mcp.py:290-297` escribe `python3 byo_mcp_server.py manifest.json`. Entonces:

- `transporte` de una conexión HTTP-por-BYO es **`stdio`**, y tiene que seguir siéndolo: el
  puente es la receta ejecutable, la que el restaurador corre hoy. Marcarla `http` rompería
  la restauración de un servidor que hoy vuelve solo.
- `url` y los headers se guardan **igual**, porque hoy viven **solo** dentro de
  `manifest.json`. Si ese archivo se pierde, la conexión no se puede reconstruir aunque la
  fila esté completa. Copiarlos al registro es exactamente el hueco que cierra la v4.
- Una conexión **HTTP nativa** (`url` sin `command`) se guarda entera pero **no se levanta**:
  el restaurador la rechaza con causa `http_por_puente_stdio_no_cableado`. El hueco que queda
  es de *ejecución*, no de *almacenamiento*, y ahora tiene nombre.

**En esta instalación hay cero conexiones HTTP**: los 15 servidores del catálogo son stdio
(verificado 2026-07-31 recorriendo los `.mcp.json` de `catalog/`, `platform/`, `product/`,
`org/` y `qa/belts`). Las tres columnas nacen vacías. El camino está probado con belts
sintéticos en `test_conexiones_backfill.py`, no con datos reales — porque no hay.

### `recipe_version` desconocida → se marca con causa, jamás se ignora en silencio

**Migrar hacia adelante está bien; adivinar hacia atrás no.** Una fila cuyo `recipe_version`
es mayor que el que esta build conoce **no se levanta y no se descarta**: se muestra en la
lista con su causa tipada y un mensaje honesto — *la creó una versión más nueva de Aleph*.

El usuario no tiene que deducir por qué una pieza desapareció. Una entidad que se borra sola
del diorama porque el binario no la entiende es exactamente el fallo mudo que el contrato
del org prohíbe (`CLAUDE.md §4.h`, «FALLO VISIBLE, JAMÁS MUDO»).

### `tools_snapshot` — evidencia, no contrato

El snapshot es **la lista de tools que se vieron en la última verificación exitosa**, no una
promesa. Cuando el servidor cambia sus tools, **el snapshot se actualiza** en la próxima
verificación y listo.

Lo que sí importa —que desapareció una tool de la que depende un método equipado— **no lo
detecta el registro**: lo detecta el match de `requires[]` contra el belt. Son dos
responsabilidades distintas y el registro no debe fingir que cubre la segunda.

### Qué NO va en el registro

- Ningún PID, descriptor, handle ni `Popen`.
- Ningún `Mcp-Session-Id`. Hoy vive en `MCPHttpClient` en memoria
  (`platform/inspection/mcp_http_client.py:60-90`) y **no es recuperable ni inyectable**.
  Una sesión HTTP no se restaura: se abre de nuevo.
- Ningún valor de credencial (§2).

---

## 2. REPARTO DE SECRETOS

### La línea

| Va al **Keychain** | Va al **Registro** |
|---|---|
| API keys | el **nombre** de cada env var secreta (`env_template`) |
| refresh tokens · access tokens | los **valores públicos declarados** (`env_publico`) |
| **los valores secretos** de las env vars de un server STDIO | `scopes`, `cuenta`, y todo lo demás del §1 |

> **El registro nunca contiene un valor de credencial.** Sí contiene valores **públicos
> declarados como tales**. No es lo mismo, y la diferencia vive en el esquema, no en el
> criterio de quien escribe.

### El entorno del hijo vive en DOS columnas

```
env_template   {VAR: "${VAR}"}    referencias al llavero. NUNCA un valor.
env_publico    {VAR: "valor"}     literales PÚBLICOS, declarados como tales.
```

**Al spawnear se juntan las dos.** Si un nombre estuviera en ambas, gana `env_template`:
nunca un literal por encima del llavero.

**Por qué dos columnas y no un guard más blando.** El caso índice es `secedgar`, que
declara `SEC_EDGAR_USER_AGENT: "Aleph (contact@aleph.app)"` — el identificador que SEC
EDGAR **exige** para saber quién le pega, público por diseño, y sin el cual la API rechaza
el request. Es hoy **el único literal de los 16 `.mcp.json` del catálogo**.

Con una sola columna había dos salidas y las dos malas: ablandar el guard (y entonces
`env_template` deja de ser una promesa legible — cualquier secreto se cuela) u omitir el
campo (y entonces el conector se reconstruye roto). **Con dos columnas el guard sigue
exactamente igual de duro sobre `env_template` — un literal ahí sigue levantando
`SecretoEnElRegistro` — y lo público queda DECLARADO en vez de tolerado por excepción.**

Se descartó una allowlist de nombres permitidos: hay que mantenerla y se desactualiza.
Dos columnas no se desactualizan.

**Dónde vive el criterio:** `conexiones_repo.repartir_env()` — un `${VAR}` es una
referencia, cualquier otra cosa es un literal público. Es el único lugar que lo decide.

### Las dos reglas de lectura

1. **Secreto ausente → warning y sigue.** Que un secreto opcional no esté configurado no es
   una falla de la conexión.
2. **Secreto que falla al leerse → aborta la conexión.** Keychain bloqueado, permiso
   denegado, ítem corrupto: se corta antes de spawnear. **Arrancar sin credencial da un
   error peor y más tarde** — el servidor levanta, la primera tool devuelve 401, y la causa
   que ve el usuario apunta al servicio en vez de al llavero.

### El vault actual queda como FALLBACK

`platform/gates/vault.py` implementa `CredentialVault` (`:49`) con `put`/`delete`/`names`/
`has` (`:70-85`) sobre un `vault.enc` cifrado con una clave Fernet derivada de un secreto
maestro (`_derive_fernet_key`, `:37`).

**Está implementado y su archivo nunca se creó en la instalación real.** Verificado:
`aleph_paths.vault_path()` (`platform/aleph_paths.py:93-96`) lo declara en
`data_root()/vault.enc`, y en `~/Library/Application Support/Aleph/` **ese archivo no
existe**.

**No se retira.** Queda como camino de respaldo para el caso en que el Keychain no esté
disponible o el usuario lo rechace. Lo que sí cambia es que deja de ser un segundo camino
ambiguo: **el Keychain es el primario; el vault solo entra si el Keychain falla.**

### Lo que hoy está vivo, para referencia

La ruta de credencial que sí funciona en la instalación real es la tabla `keys`, cifrada con
Fernet (`platform/db/db.py:217-222`), con keyfile en `<data_dir>/secrets/enc.key`
(`platform/aleph_paths.py:135-146`, modo `0600` verificado en disco). Escritura:
`centro_conexiones._guardar` (`product/backend/app/phase1/centro_conexiones.py:1389`).
Lectura: `credential_broker.make_user_resolver`
(`product/backend/app/phase1/credential_broker.py:163`) → `child_env` del subproceso.

---

## 3. LOS TRES COLORES · y la clasificación interna

### Los tres colores — y no hay un cuarto

| | Qué significa |
|---|---|
| 🟢 **verde** | anda |
| 🟡 **amarillo** | no lo probé todavía · lo estoy reintentando · **está roto y necesita que actúes** |
| ⚪ **gris** | no está conectado |

> **No hay rojo en la plataforma.** Un conector roto es **amarillo con su botón**.

El amarillo no es un estado tibio: es «esto no está andando». Lo que distingue los tres
casos que caen en amarillo **no es el color, es si hay botón**:

- reintentando → amarillo, sin botón (Aleph está trabajando);
- nunca probado → amarillo, con [Probar];
- roto → amarillo, **con el botón que lo arregla**.

### Restaurar NO pinta verde — la pieza queda AMARILLA

**Regla, no consecuencia.** Cuando el restaurador levanta una pieza desde el registro, esa
pieza queda en **🟡 «no lo probé todavía»**. No verde, no rota. El `verify` corre después y
es el único que decide el color.

Esto ya es lo que pasa hoy por omisión —la restauración no escribe en `motor_estado.json`—
pero estaba pasando **por accidente**, y un invariante que depende de que nadie agregue una
línea no es un invariante. Queda escrito para que sacarlo sea una decisión visible.

**Por qué levantar no es andar.** Un proceso que arranca no es una conexión que sirve. El
propio motor ya lo dice en dos lugares:

- un servidor que saluda pero lista **0 tools** se marca ROTO
  (`product/backend/app/phase1/centro_conexiones.py:1024-1032`);
- `_estado_fila` exige **todos** los requisitos en HECHO para dar PROBADO (`:1092-1093`).

Si la restauración sembrara un veredicto, estaría afirmando las dos cosas sin haber medido
ninguna. **Un verde falso es peor que un amarillo honesto**: el amarillo trae `[Probar]` y el
usuario llega a la verdad en un clic; el verde falso lo manda a usar un agente que va a
fallar en medio de una tarea, con la causa ya perdida.

**Lo que esto deja explícitamente afuera de v1:** cablear la clave `<belt_ref>#<server>` para
que la restauración alimente `motor_verdad`. No es un olvido — es la decisión de arriba.

### La clasificación interna: TEMPORAL vs PERMANENTE

> **El usuario nunca ve las palabras «temporal» ni «permanente».** Son categorías del motor.
> **Las dos pintan amarillo.** Lo único que deciden es si Aleph reintenta callado o muestra
> el botón.

**TEMPORAL** — sin internet · timeout · servidor saturado · HTTP 500 · rate limit · el
proceso se murió.

- **Reintenta callado.** Backoff con jitter, con techo.
- **JAMÁS vuelve a pedir la credencial.** Un fallo temporal no es una credencial inválida; y
  pedirla de nuevo entrena al usuario a repegar llaves que estaban bien.
- Amarillo **sin botón** mientras reintenta.

**PERMANENTE** — token revocado · llave inválida · scope insuficiente · el programa se
desinstaló · el addon no está activado.

- **Para.** No reintenta.
- Amarillo **con el botón** que resuelve la causa.

### El tope de reintentos — la forma, no el número

**El contrato fija la forma; el número se calibra fuera de este documento.**

- Backoff **con techo**: el intervalo crece pero no crece para siempre.
- Tras **N fallos consecutivos**, para y muestra el botón.
- **El contador se resetea** con: cualquier conexión exitosa · cualquier acción del usuario
  sobre esa entidad · reabrir la app.

Un contador que no se resetea convierte un problema de red de ayer en una conexión muerta de
hoy.

### Lo que hay hoy

**El vocabulario de causas existe y es cerrado**, con clasificador puro:
`product/backend/app/phase1/diagnostico_conectores.py:203` (`_clasificar`), que —según su
propio docstring de cabecera— *"recibe hechos ya medidos y devuelve el único objeto que las
superficies deben pintar. No ejecuta probes, no consulta la red"*. Su contrato público
`veredicto` v1 ya trae `estado`, `causa`, `escalon`, `corrio`, `patron`, `evidencia`,
`camino` y `presentacion`.

**Lo que NO hay: reintento automático.** No existe backoff, ni tope de intentos, ni
respawn de un proceso muerto. `MCPServer.stop()`
(`platform/assembler/assembler.py:248-264`) termina el proceso; nada lo vuelve a levantar.
La única reparación implementada es **humana**: `remedios_conectores.py` propone el comando
y `centro_conexiones._mano()`
(`product/backend/app/phase1/centro_conexiones.py:181`) lo entrega como
`{comando, doc, por_que}`.

**La clasificación temporal/permanente por causa es nueva en v1.** El motor ya distingue las
causas; lo que no existe es la **política** que decide, a partir de la causa, si reintentar
o parar.

---

## 4. LA LÁPIDA — dos acciones distintas, no una

### DESCONECTAR

- Apaga la conexión y cierra el proceso.
- **La llave se queda.**
- La receta **permanece en el registro**, marcada `habilitado = false`.
- **La restauración la saltea al arrancar: no revive sola.**
- Volver a conectar = **un click, sin reconfigurar nada**.

### BORRAR LA LLAVE

- Acción **separada**, con confirmación explícita.
- Quita la credencial del Keychain.
- Volver a conectar **exige pegarla de nuevo**.

### Por qué son dos

Desconectar es una decisión operativa reversible («ahora no lo quiero corriendo»). Borrar la
llave es una decisión de seguridad («no quiero que Aleph siga teniendo esto»). Fundirlas
obliga a pagar el costo de la segunda cada vez que se quiere la primera.

### La lápida es POR ENTIDAD

Consecuencia directa de «un servicio = una entidad = una fila» (§1). Desconectar un servidor
lo apaga **para todos los agentes que lo tengan equipado**.

**Y la pieza no desaparece del diorama de ninguno de ellos:** sigue ahí, apagada, con su
botón. El agente se abre como lo armó (§7); una pieza que se evapora porque el usuario la
desconectó desde otro lado es la misma clase de fallo mudo que prohíbe `recipe_version`
desconocida (§1).

### Dónde viven — **adentro de `[Revisar]`, que ya existe**

**Verificado:** `[Revisar]` **ya es la acción por fila** en la pantalla Conectores, al lado
del estado. `product/app/design/conectores/conectores.ui.js:387-389`:

```js
const actionLabel = conectado
  ? L("Revisar", "Review")
  : L("Conectar", "Connect");
```

La misma etiqueta aparece además en el resumen de cabecera, para la entidad que requiere
atención (`conectores.ui.js:344`).

**Desconectar y Borrar llave se agregan ADENTRO de algo que ya existe.** No hay que crear un
punto de entrada nuevo ni tocar la fila: `[Revisar]` ya está en su lugar y ya distingue
conectado de no-conectado.

### Apagar NO es un fallback — la distinción que sostiene la sección

El restaurador tiene un fallback escalonado: si una fila falta o no se puede ejecutar, cae
al `.mcp.json` y lo reporta. **Una fila apagada NO entra en ese camino.** Son dos preguntas
distintas y el código las hace por separado:

| | Pregunta | Consecuencia |
|---|---|---|
| `_por_que_no_sirve()` | ¿**PUEDO** ejecutar esta fila? | no → cae al `.mcp.json` |
| `_esta_apagada()` | ¿**DEBO** ejecutar esta fila? | no → no se ejecuta, y punto |

Si apagar cayera al fallback, la pieza revivría por el catálogo en el run siguiente y
desconectar no serviría **de nada**. El fallback existe para que nada se pierda; aplicado a
una lápida sería justo lo que la rompe.

Consecuencia en el parte de daños: una pieza apagada **no cuenta como caída**. Va con su
propia etiqueta (`fuente = "lapida"`) y su propia clave. Nombrarla entre las que «no
arrancaron» sería devolverle al usuario su propia decisión como si fuera un fallo — y
cuando *todas* las piezas de una receta están apagadas, el error lo dice así y manda a
Conectores, en vez de mandar a arreglar algo que no está roto.

### La lápida vive SOLO en el registro

Vaciar `conexiones` no rompe Aleph —todo vuelve por el camino viejo— pero **resucita lo que
el usuario apagó**, porque un `.mcp.json` no sabe nada de `habilitado`. Es la consecuencia
inevitable de que apagar sea un dato del usuario y no del catálogo. Queda escrito para que
no se descubra de casualidad: hasta la lápida, «borrar la tabla no cambia el comportamiento»
era un invariante verdadero, y **dejó de serlo a propósito**.

### Lo que existe hoy — ✅ IMPLEMENTADO (2026-07-31)

| Pieza | Dónde |
|---|---|
| `habilitado` | columna del registro (migración de cliente v3) |
| `desconectar` / `reconectar` | `conexiones_repo` — un UPDATE, **jamás un upsert**: apagar una entidad que no existe levanta `EntidadInexistente` en vez de fabricarle una lápida a un fantasma |
| el salteo al restaurar | `restaurador._esta_apagada` + `FUENTE_LAPIDA` |
| las dos acciones HTTP | `POST /v1/conexiones/{entity_id}/desconectar` · `…/reconectar` |
| **borrar la llave** | `DELETE /v1/conexiones/key/{provider}` — **ya existía**, y no se tocó |
| el gris de la lista | `GET /v1/conexiones/apagadas`, una llamada por pantalla |
| los dos botones | adentro de `[Revisar]` (`wizard.js`, zona `wz-lapida`) |

**Borrar la llave no se construyó en esta sesión: ya estaba.** Lo que faltaba era la otra
mitad — desconectar sin perder la credencial— y que las dos convivieran en el mismo panel
con la jerarquía visual correcta: un botón normal arriba, un link chico y apagado abajo.

`account_deletion.py:207` revoca tokens OAuth, pero eso es el borrado de la cuenta entera,
no una desconexión selectiva. Sigue siendo otra cosa.

---

## 5. LOS 12 VERBOS

| # | Verbo | Qué significa en Aleph | Qué garantiza | Dónde vive hoy |
|---|---|---|---|---|
| 1 | **resolve** | de «servicio + credencial del usuario» a una receta ejecutable, sin que el usuario pegue un MCP a mano | que el servidor elegido es el legítimo, no un impostor | **existe** — `platform/inspection/mcp_resolver.py:192` (`resolve_service`, 6 pasos) + `mcp_registry.py` + `mcp_matcher.py` |
| 2 | **prepare** | dejar el runtime en condiciones antes de conectar: PATH real, intérprete, programa instalado | que el `connect` no falle por algo que se podía anticipar | **parcial** — disperso: `deploy/fase4/sidecar_serve.py:140` (`ensure_user_path`) · `platform/aleph_paths.py:109` (`python_executable`) · `product/backend/app/phase1/remedios_conectores.py` (propone, **no ejecuta**) |
| 3 | **authorize** | obtener y renovar la credencial del usuario para el servicio | que el token viaja cifrado y nunca al manifest | **existe** — `platform/connectors/oauth_flow.py:41` (`mint_state`), `:114` (`build_authorize_url`) · `product/backend/app/phase1/credential_broker.py:70` (`_maybe_refresh_oauth`), `:163` (`make_user_resolver`) |
| 4 | **connect** | abrir el canal con el servidor | que hay un canal o un error tipado, nunca un silencio | **parcial · DUPLICADO** — `platform/assembler/assembler.py:172` (`start`, stdio) · `platform/inspection/mcp_http_client.py:60` (HTTP) |
| 5 | **initialize** | el saludo MCP y la negociación de versión | que se sabe con qué versión se está hablando, o se falla cerrado | **parcial · DUPLICADO** — `assembler.py:186-215` (dentro de `start`) · `mcp_http_client.py:176`. Los dos escritos a mano, los dos clavados en `2024-11-05` (`assembler.py:34`, `mcp_http_client.py:26`) |
| 6 | **list_tools** | qué sabe hacer el servidor | que la lista es real, no declarada | **existe** — `assembler.py:229` · `mcp_http_client.py:194`. Filtro por servidor en `puppets.config.belt.tool_filters`, aplicado en `ToolRegistry` (`assembler.py:331`) |
| 7 | **verify** | medir requisito por requisito si la conexión sirve, y por qué no | **nunca verde sin evidencia** | **existe** — `motor_verdad.py:1509` (`probar`), `:1562` (`estado`), `:231` (`huella_de`) · `centro_conexiones.py:987` (`_checklist_mcp`), `:1096` (`correr_checklist`) · `diagnostico_conectores.py:203` (`_clasificar`) |
| 8 | **invoke** | ejecutar una tool | que el resultado es del servidor, o un error tipado | **existe** — `assembler.py:235` (`call_tool`) · `mcp_http_client.py:199` · `ToolRegistry.call` (`assembler.py:379`) |
| 9 | **persist** | guardar cómo reconstruir | que reabrir la app no pierde nada reconstruible | **no existe como tal** — disperso en 4 fuentes (§9.2). Ninguna guarda una conexión: guardan pedazos |
| 10 | **restore** | volver a levantar desde el registro | que lo que se levanta es lo que estaba, no un default | **parcial** — implícito y **sin nombre**: `platform/assembler/belt_resolver.py:125` (`resolve_belt_ref`), `:196` (`resolve_belt_refs`) → `recipe_assembler.py:768` (`_expand_server_cfg`) |
| 11 | **repair** | volver a poner sana una conexión rota | que un fallo temporal no se le presenta al usuario como trabajo suyo | **parcial · humano, no automático** — `remedios_conectores.py` propone · `centro_conexiones.py:181` (`_mano`) entrega el comando. **Cero reintento automático** |
| 12 | **disconnect** | apagar, con lápida | que no revive sola y que la llave sobrevive | **existe** — `conexiones_repo.desconectar/reconectar` · `restaurador._esta_apagada` (salteo, NO fallback) · `POST /v1/conexiones/{id}/desconectar` · los dos botones en `wizard.js` (zona `wz-lapida`). `assembler.stop` sigue matando el proceso al terminar el run: eso es el fin de una sesión, no una lápida |

**Conteo verificado: 7 existen · 4 parciales · 1 no existe.**

El único que sigue sin existir es **`persist`** (9): el registro ya guarda cómo reconstruir,
pero quien lo escribe es el backfill, no el flujo de conectar. Una conexión nueva sigue
naciendo repartida en las cuatro fuentes del §9.2.

### El verde tiene que haber MEDIDO la credencial

**Listar herramientas no prueba la llave.** Un servidor MCP arranca y publica su catálogo
igual con una credencial inválida: la llave recién viaja cuando se **llama** una tool. Los
tres requisitos originales —`spec` · `handshake` · `tools`— no la tocaban ninguno.

**Medido (2026-07-31, app instalada):** con `clave-falsa-de-prueba-0000` pegada a los diez
conectores sin llave, **siete quedaron 🟢 «Conectado» con tools completas** — coingecko,
context7, github, globalfishingwatch, gmail, massive, opensanctions. El fallo real aparecía
después, en medio de una tarea del usuario. Es la sorpresa en vivo que el producto prohíbe.

**El cuarto requisito** llama **UNA** tool de lectura y decide. Corre en el mismo spawn que
el handshake: una llamada JSON-RPC más, sin proceso extra.

| | |
|---|---|
| hay llave **+ tool declarada** | se corre → 🟢, o el fallo **con su causa** |
| hay llave **+ sin declarar** | 🟡 «se confirma en el primer uso». **Nunca verde** |
| **sin llave** | el requisito no aplica y **no bloquea** |

Amarillo y no rojo en la rama del medio: no medimos, y «no lo sé» no es «está mal».

### La tool la elige el CATÁLOGO, no el código

Campo nuevo en la entrada del server, al lado del comando y la llave:

```json
"prueba_credencial": {
  "tool": "whoami",
  "args": {},
  "por_que": "cero argumentos, cero costo, y es LECTURA. `create_item` ESCRIBE."
}
```

**Una tool cualquiera no sirve.** Tiene que ser de lectura, barata, y devolver algo
determinista sin argumentos que haya que inventar. Eso lo sabe quien curó el conector, no
el código: desde adentro, `whoami` y `create_item` son indistinguibles.

> ⚠️ **JAMÁS una tool de escritura.** Probar una escritura **es** escribir: manda el mail,
> crea el issue, borra el archivo. Verificar la llave de Gmail mandando un correo arruina la
> verificación silenciosa y viola la regla de que nada con efecto externo corre sin
> autorización. La prueba de credencial es **siempre** de lectura, sin excepción.

Lo único que el código puede garantizar —y garantiza— es que **sólo se llama lo declarado,
con los argumentos declarados**: nada que venga del usuario llega a un `call_tool`, y una
tool que el servidor no publica no se invoca (se reporta como declaración vieja del
catálogo, no como culpa de la credencial).

**El registro público no tiene curación**, así que sus entradas caen enteras en la rama
amarilla. Y eso está bien: es la verdad, y es exactamente el valor del piso curado — el piso
puede prometer verde porque alguien eligió con qué probarlo.

### La regla de frescura del `verify`

**El veredicto no caduca por reloj: caduca por causa.** Está implementado y **no se toca** —
`estado()` pasa `ttl=None` (`product/backend/app/phase1/motor_verdad.py:1562-1580`) y la
invalidación real la da `huella_de` (`:231-243`), la firma de la configuración probada.

Verde es verde. Un veredicto viejo no se atenúa, no se degrada y no se re-pinta: sigue siendo
lo último que se midió hasta que algo cambie la causa o alguien vuelva a medir.

---

## 6. CUÁNDO ARRANCA UNA CONEXIÓN

> **No al abrir la app. No con un switch del usuario.**

**Momento primario — al abrir el agente en el Cuarto.** Se levantan **sus piezas
equipadas**, no el catálogo entero. Un agente con cuatro piezas levanta cuatro.

**Red de seguridad — cuando el modelo pide una tool.** Si la pieza que la sirve todavía no
está levantada, se levanta ahí.

**Y la garantía que ata las dos:** si el modelo pide una tool de una pieza que **está
levantando**, la llamada **espera**. No falla, no devuelve «tool no disponible», no
reintenta desde cero.

**La espera tiene tope: el `timeout` por entidad del §1.** Al vencer, causa tipada — y es
**temporal**, así que amarillo y reintento callado (§3). No hay espera infinita y no hay
rojo.

### Lo que hay hoy

Hoy las conexiones se levantan **dentro de un run**, no al abrir el agente:
`recipe_assembler.assemble_and_run` (`platform/assembler/recipe_assembler.py:1432`) spawnea
los servidores del belt en `:2052` (`_asm.MCPServer(...)` + `srv.start()`), y hay un segundo
sitio de spawn en `:3450`. **No existe un momento «abrir el agente» separado del «correr el
agente»**, ni una espera por pieza levantándose.

---

## 7. QUÉ VE EL USUARIO AL ABRIR UN AGENTE

> **El agente se abre COMO LO ARMÓ.**

- **Todas sus piezas.** No un subconjunto sano, no las que hoy funcionan: las que él eligió.
- **Las rotas se ven rotas**, en amarillo y con su botón.
- **El aviso va AL ABRIR, nunca en medio del trabajo.** Descubrir que una pieza está caída
  cuando el modelo ya empezó a usarla es la peor versión del mismo dato.

Consecuencia directa del §3: al abrir, lo que está reintentando se ve amarillo sin botón, y
lo que está roto se ve amarillo con el botón que lo resuelve. **Nada se esconde por estar
roto, y nada grita en rojo.**

---

## 8. CONECTORES PROPIOS ≠ AJENOS

| | Conector **propio** (escrito por nosotros) | Conector **de terceros** |
|---|---|---|
| Transporte | **MCP por streams en memoria — sin proceso** | spawn de proceso (stdio) o HTTP |
| PATH | no aplica | aplica (§9.4) |
| Cierre del árbol de procesos | no aplica | aplica |
| Credenciales | igual (§2) | igual (§2) |

**Camino preferente para lo propio: streams en memoria.** Un conector nuestro escrito en
Python no necesita ser un proceso para hablar MCP. Serlo le agrega tres clases enteras de
fallo —resolución del ejecutable, herencia de entorno, huérfanos al cerrar— que no aportan
nada, porque el código ya está adentro del sidecar.

### Lo que hay hoy

**Ningún conector propio usa streams en memoria.** Verificado: no hay ninguna implementación
de MCP en memoria en `platform/assembler/`, `platform/inspection/` ni
`product/backend/app/`. Los **22 archivos `*server*.py`** bajo `product/belts/` (de 27 `.py`
totales, sin contar tests) son código nuestro y **se spawnean como procesos externos**, por
el mismo camino que un servidor de terceros.

---

## 9. EL ESTADO ACTUAL — verificado contra `58270fb`

### 9.1 · No existía ninguna tabla de conexiones — ✅ RESUELTO: existe `conexiones`

**Ya no es el estado actual.** La tabla se construyó (migración de cliente v3, ampliada a la
v4 con la receta HTTP) y el restaurador es su primer lector. El diagnóstico de abajo se
conserva porque es **la evidencia de por qué hizo falta**: era el hueco, no un olvido.

<details>
<summary>El diagnóstico original, contra <code>58270fb</code></summary>

Verificado en los **dos dialectos** y en las **19 migraciones**:

- `platform/db/schema_sqlite.sql` — **20** tablas.
- `platform/db/schema.sql` (Postgres) — 8 tablas (baseline).
- `platform/db/migrations/*.sql` — 19 archivos, **26** tablas distintas.
- La base instalada (`~/Library/Application Support/Aleph/aleph.db`) — **21** tablas.

Búsqueda de semántica de conexión (`conexion|connection|connector|mcp_|extension`) en los
tres archivos de esquema y las 19 migraciones: **ninguna tabla**. Los únicos `server TEXT`
son campos de auditoría —`held_actions.server` (`schema_sqlite.sql:352`) y
`billing_ledger.server` (`migrations/0017_billing_columnas_reales.sql:22`)— que registran a
qué belt server perteneció una acción o un cargo.

</details>

### 9.2 · El estado vive repartido en cuatro fuentes

| # | Fuente | Qué guarda | Dónde |
|---|---|---|---|
| 1 | `puppets.config` (SQLite, columna JSON) | `belt.belt_refs[]`, `belt.tool_filters`, `keys{}` | `platform/db/schema_sqlite.sql:74-86` |
| 2 | archivos `.mcp.json` | `mcpServers{name:{command,args,env,description}}` | `catalog/**` y `data/synth_belts/<user>/<slug>/` (`platform/inspection/byo_mcp.py:260-261`) |
| 3 | `motor_estado.json` | veredicto, causa, transporte, latencia, `tools[]`, `huella` | `platform/aleph_paths.data_root()/motor_estado.json` (`motor_verdad.py:166-178`, escritura en `:208`) |
| 4 | tabla `keys` | credenciales cifradas Fernet | `schema_sqlite.sql:142-153` |

**Ninguna de las cuatro guarda una conexión. Guardan pedazos, y el pegamento es implícito.**

### 9.3 · 48 servicios vs 58 servidores — resuelto: **son unidades distintas**

La app instalada dice **«Tus servicios 48»**. Un conteo del catálogo da **58**. Los dos son
correctos: **cuentan cosas distintas.**

| | Qué cuenta | Cuántos |
|---|---|---|
| **48** — la app | **SERVICIOS** (entidades) que tienen al menos un servidor | lo que muestra `localCount` |
| **58** — el catálogo | **SERVIDORES MCP únicos por nombre** en `catalog/**/*.mcp.json` | 58 (en 73 declaraciones, 16 archivos) |

**El 48 sale de `#localCount`** (`product/app/design/Conectores.dc.html:175`), que
`renderLocales` llena con `items.length`
(`product/app/design/conectores/conectores.ui.js:352, 369`). Los `items` vienen de
`cargarLocales` (`:578-597`), que llama `loadCapabilityCatalog`
(`product/app/design/cuarto/cuarto.catalog.js:495`) y **filtra**:

```js
const entries = (catalog.entries || []).filter(
  (entry) => entry && entry.service && Array.isArray(entry.servers) && entry.servers.length
);
```

El origen es el endpoint **`/v1/connector-entities`**
(`product/app/design/cuarto/cuarto.catalog.js:283`), servido por
`connector_entities.build_entities` (`product/backend/app/phase1/connector_entities.py:305`).

**Las tres razones de la diferencia, en el código:**

1. **Un servicio agrupa uno o más servidores.** El propio catálogo lo separa:
   `entityCount` = servicios, y `mcpCount` = `entities.reduce((n, e) => n + e.servers.length, 0)`
   = servidores (`cuarto.catalog.js:537-539`). Son dos números distintos por diseño.
2. **Las credenciales sin tools no cuentan como servicio.** Comentario textual en
   `cuarto.catalog.js:512-514`: *"Modelo nuevo: un SERVICIO por pieza. Las credenciales sin
   tools quedan como perfiles internos/dormidos; jamás reaparecen como piezas APPS de 0
   tools."*
3. **La lista incluye builtins y respeta la búsqueda.** `entries` mezcla
   `BUILTIN_CATALOG_ENTRIES` con las entidades (`cuarto.catalog.js:506, 525`), y
   `localCount` refleja el resultado **después del filtro de búsqueda**
   (`conectores.ui.js:361-369`) — con el buscador vacío es el total, con texto es el subconjunto.

**El número correcto para «cuántos servicios ofrece Aleph» es el de la app: 48.** El 58 es
«cuántos servidores MCP declara el catálogo», que es una métrica de implementación, no de
producto. **El contrato cuenta ENTIDADES, o sea servicios** (§1).

### 9.4 · El PATH real del usuario

`ensure_user_path()` **aparece una sola vez en producción**:
`deploy/fase4/sidecar_serve.py:233`, dentro de `main()`, **antes** de importar la app
(`:243`). Resuelve el PATH uniendo login shell (`$SHELL -l -c`, `:94-110`), tabla de
directorios estándar + globs de nvm/asdf (`:47-60`) y el PATH heredado, cacheado con
`lru_cache` (`:111-137`).

**Tres sidecars hermanos la omiten** —`product/backend/conexiones_sidecar.py`,
`motor_sidecar.py`, `modelos_sidecar.py`— y montan los mismos routers que sondean MCP
(`build_motor_router`, `build_conexiones_router`).

**Y el comando no se resuelve a ruta absoluta antes del spawn**: `_expand_server_cfg`
(`recipe_assembler.py:768-783`) expande `${VAR}` y pasa el `command` tal cual a
`subprocess.Popen` (`assembler.py:179`). No hay `shutil.which` sobre el comando.

#### La decisión: `ensure_user_path()` se muda a un módulo compartido

**El fix no se replica en los tres sidecars uno por uno.** Replicarlo trata el síntoma:
mañana hay un cuarto entrypoint y vuelve a faltar.

**El problema de fondo es que vive en un entrypoint en vez de vivir cerca del código que
spawnea.** Un `main()` es el peor lugar posible para una precondición del spawn: la
precondición viaja por herencia de proceso, y cualquier camino que no pase por ese `main()`
la pierde en silencio.

**Dónde iría: `platform/aleph_paths.py`.** Cuatro razones:

1. **Ya es el módulo de «dónde están las cosas en esta máquina»** — `user_data_dir()`,
   `resource_root()`, `vault_path()`, `enc_key_path()`. El PATH del usuario es exactamente
   ese tipo de dato.
2. **Ya resuelve un problema hermano, y lo resuelve mal por no tener esto al lado.**
   `python_executable()` (`:109-131`) hace `shutil.which("python3")` contra el PATH heredado
   — o sea que **hoy depende de que `ensure_user_path()` haya corrido en otro archivo**. Con
   los dos en el mismo módulo, la dependencia deja de ser implícita.
3. **Ya es frozen-aware** (`sys.frozen`, `_MEIPASS`), que es la mitad del problema que
   `_child_env()` resuelve al restaurar `DYLD_*_ORIG` (`sidecar_serve.py:80-92`).
4. **Ya lo importa todo el árbol**, incluidos los tres sidecars hermanos.

`deploy/fase4/sidecar_serve.py` mantiene su llamada en el boot (que sigue siendo el momento
correcto para pagarla una vez) pero **pasa a importarla, no a definirla**.

### 9.5 · El watchdog anti-huérfano funciona

`_watch_parent(parent_pid)` (`deploy/fase4/sidecar_serve.py:194-210`) vigila el PID del
shell Tauri con `os.kill(pid, 0)` y cierra el sidecar cuando el padre desaparece. El shell
se lo pasa: `--parent-pid` (`deploy/fase4/aleph-shell/src-tauri/src/lib.rs:266-272`).

**Es el equivalente en espacio de usuario de `PR_SET_PDEATHSIG`, y funciona en macOS.**
Evidencia de que se disparó en producción, en `~/Library/Logs/app.aleph.desktop/Aleph.log`:

```
[sidecar] el shell (pid 26481) murió — cerrando (anti-huérfano)
[worker] parando pool (graceful)…
[db] almacén cerrado: 4 conexiones
[sidecar] cli_brain detenido; procesos CLI terminados=0
```

**Alcance:** cubre el sidecar y los procesos CLI registrados. **No cubre los servidores
MCP**, que no tienen registro ni grupo de proceso propio (`MCPServer.stop()`,
`assembler.py:248-264`, es `terminate()` sobre un PID pelado).

### 9.6 · `connect` e `initialize` están duplicados

Dos implementaciones de JSON-RPC 2.0 escritas a mano, sin nada compartido:

| | STDIO | HTTP |
|---|---|---|
| Archivo | `platform/assembler/assembler.py:28-330` | `platform/inspection/mcp_http_client.py:60-251` |
| Correlación por id | contador bajo `threading.Lock` (`:268-270`), descarta lo que no matchee (`:284-294`) | propio |
| `initialize` | `:186-215` | `:176` |
| `tools/list` | `:229` | `:194` |
| `tools/call` | `:235` | `:199` |
| Versión | `2024-11-05` (`:34`), acepta `{2024-11-05, 2025-03-26}` (`:39`) | `2024-11-05` (`:26`) |

---

## 10. FUERA DE ALCANCE

### El SDK oficial de MCP NO se adopta en v1

**Decisión diferida, con razón escrita.** Tres motivos:

1. **Reemplaza poco.** Sustituiría `MCPServer` (`assembler.py:28-330`, ~300 líneas) y
   `mcp_http_client.py` (251 líneas) — alrededor del **11%** de la capa de conexión. No toca
   `mcp_resolver` + `mcp_registry` + `mcp_matcher`, `centro_conexiones`,
   `diagnostico_conectores`, `remedios_conectores` ni `byo_mcp`.
2. **Obliga a un puente sync↔async.** El cliente MCP y el ejecutor son **100% síncronos**:
   `async def` = 0 en `assembler.py`, `recipe_assembler.py`, `mcp_http_client.py` y
   `executor.py`. El SDK es async-only. El código ya cruza la frontera en la dirección fácil
   (`run_in_threadpool` en `product/backend/app/main.py:106,123,231,252`;
   `anyio.to_thread.run_sync` en `product/backend/app/phase1/router.py:2121`) y ya depende
   de `anyio`, pero **la dirección que hace falta —manejar un cliente async desde un bucle
   síncrono— no tiene ningún helper** en el árbol.
3. **Obligaría a re-cablear la taxonomía de errores.** `motor_verdad.dependencia_local`
   (el chequeo pre-spawn), `diagnostico_conectores._clasificar` y
   `centro_conexiones._checklist_mcp` están escritos contra el comportamiento del
   `MCPServer` propio: su `diagnostico()`, su `stderr` capturado, su `exit_code`, sus
   versiones de protocolo. Reemplazar el cliente no los borra, pero los obliga a
   re-clasificar contra otra taxonomía.

**Lo que el SDK sí compraría, para cuando se retome:** salir de `2024-11-05`, un cierre de
proceso con escalada acotada, y dejar de mantener dos handshakes a mano.

### También fuera de alcance de v1

- Cualquier cambio al Motor de Verdad que altere la regla «caduca por causa, no por reloj».
- La reanudación de sesiones HTTP (`Mcp-Session-Id` no es recuperable, §1).

---

## 11. LA PREGUNTA QUE ESTABA ABIERTA — ✅ RESUELTA (2026-07-31, al construir)

**¿Por qué carril migra la tabla del registro, y va también al Postgres del CONTROL?**

**Respuesta: no va a Postgres, y la excepción quedó DECLARADA en el lugar ejecutable.**

- `platform/role.py` estrena **`TABLAS_SOLO_CLIENTE = frozenset({"conexiones"})`**, sumado
  a `tablas_del_cliente()`. No se metió dentro de `TABLAS_CLIENTE` —donde todas las demás
  **sí** tienen gemela en `migrations/*.sql`— justamente para que la excepción se lea:
  el próximo que agregue una tabla tiene que **elegir set**, y elegir es leer por qué.
- Carril de migración: `sqlite_db._MIGRACION_3_REGISTRO_CONEXIONES` (v2→v3), sin
  contraparte en `platform/db/migrations/`. Es la primera migración del cliente que **no**
  espeja una de Postgres, y su comentario lo dice.
- `test_la_cadena_de_migraciones_espeja_el_schema` verifica columna por columna que el DDL
  de las migraciones y el de `schema_sqlite.sql` no diverjan: una DB virgen recibe el `.sql`
  y una desplegada recibe la **cadena entera**, y las dos tienen que quedar con la misma
  forma. Se compara contra la suma y no contra una migración suelta —la v3 sola dejó de
  espejar en cuanto la v4 sumó la receta HTTP, y eso es correcto—, así que el test sigue
  valiendo cuando aparezca la v5 sin que haya que tocarlo.

El texto de la pregunta original, con las dos mitades que tenía, se conserva abajo como
registro de por qué se decidió así.

<details>
<summary>La pregunta, como estaba planteada</summary>

El árbol tiene **dos carriles de evolución de esquema, y no se hablan**:

- **Postgres** — `platform/db/migrations/*.sql` (19 archivos) corridos por
  `platform/db/migrate.py`. Verificado: `migrate.py` **no menciona sqlite ni dialecto**
  (0 hits para `sqlite|dialect|postgres`).
- **SQLite** — `platform/db/schema_sqlite.sql` aplicado por `sqlite_db.crear_schema`
  (`:613`), más bloques `ALTER` escritos a mano en el propio módulo
  (`_MIGRACION_2_TANDA_D`, `sqlite_db.py:645-656`), cuyo comentario dice textual:
  *"Espejo de las migraciones Postgres 0018/0019 y de `schema_sqlite.sql`"*.

O sea: hoy cada tabla nueva se escribe **dos veces**, a mano, y se mantienen sincronizadas
por disciplina.

La pregunta tiene dos mitades:

1. **¿La tabla del registro es solo-cliente?** Una conexión MCP es un concepto del
   escritorio: el CONTROL en Render no spawnea servidores MCP locales. Si es solo-cliente,
   vive únicamente en `schema_sqlite.sql` y **rompe el espejo a propósito, por primera vez**.
2. **Si rompe el espejo, ¿queda declarado?** Un esquema que hasta hoy fue espejo y pasa a
   tener tablas solo-de-un-lado necesita decirlo en algún lado, o el próximo que agregue una
   tabla no va a saber cuál es la regla.

Esto es una decisión de la capa de datos, no de este contrato — pero el contrato la
bloquea hasta que se tome.

</details>

---

## 12. DEUDA CONOCIDA

### ⚠️ LA RECONCILIACIÓN — el trabajo que sigue, y va ANTES de cualquier fuente nueva

> **«Agregué el registro como quinta fuente desconectada en vez de hacer que algo
> reconciliara.»**

Esa frase es el diagnóstico. El §9.2 contaba CUATRO fuentes que no se hablan
(`puppets.config`, los `.mcp.json`, `motor_estado.json`, la tabla `keys`). La tabla
`conexiones` se sumó como **quinta**, no como reemplazo — y una pantalla que lee de cinco
lugares que no se conocen puede contradecirse a sí misma sin que ningún módulo esté mal.

**Medido en la app instalada (2026-07-31), barriendo las 48 filas de Conectores:** 26
entidades medían `probado` y sólo 23 decían «Conectado». Las tres de diferencia —`arxiv`,
`backtest`, `pubmed`— **andaban**, con tools 1/1, y la fila las daba por desconectadas.
Dos fuentes, dos respuestas, ninguna equivocada por su cuenta.

El §4 cerró el caso puntual definiendo **quién manda en qué** (`habilitado` en la luz y la
acción, el veredicto en el texto) y poniendo el levantamiento de la lápida en el punto
único donde se registra la intención de conectar. Eso arregla la contradicción de esa fila.

**No arregla la clase.** Mientras las cinco fuentes sigan sueltas, la próxima superficie
que sume una sexta reabre el mismo agujero en otro lado. La reconciliación —decidir cuál
es la fuente de verdad de cada pregunta, y que el resto derive de ahí— es una sesión propia
y **es prerequisito de agregar cualquier otra fuente**.

### El cliente no tiene script de backup


**El cliente no tiene script de backup.** `platform/db/backup.py` es **`pg_dump`-only**:
respalda el Postgres del control plane, no el SQLite del usuario. Hoy el respaldo del
`aleph.db` se hace a mano con el backup online de SQLite:

```bash
sqlite3 -readonly "$HOME/Library/Application Support/Aleph/aleph.db" \
  ".backup '<destino>.db'"
```

Es WAL-safe y no requiere cerrar la app, pero no está automatizado ni rota nada. **No se
resuelve en este contrato** — es una sesión propia de la capa de datos.
