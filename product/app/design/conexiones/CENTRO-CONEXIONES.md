# CENTRO DE CONEXIONES — el carril "conectar", de punta a punta

**Rama:** `feat/centro-conexiones` · **Base:** `7e58901` (HEAD de `fix/sala-viva`, terminal A)
**Paso 0 verificado:** `product/backend/app/phase1/motor_verdad.py` con el vocabulario
ampliado (`cli_no_instalado`, `cli_no_logueado`=`sin_sesion`, `cli_interactivo_colgado`,
`key_ausente`=`falta_key`, `plan_insuficiente`, `cli_version_vieja`, `cli_sin_permisos`,
`key_invalida`, `sin_credito`, `rate_limit`, `modelo_no_disponible`).

---

## 1 · Qué había roto (la caminata) y dónde quedó arreglado

| # | Lo que reportó la caminata | Dónde vive el arreglo |
|---|---|---|
| 1 | `[Reintentar]` obsoleto: repite el ping que falla y te deja igual | `cuarto/cuarto.semaforo.js` (badge) + `conexiones/centro.ui.js` (fila) |
| 2 | El flujo de conexión vive apilado dentro del closet, sin espacio | `Conexiones.dc.html` (pantalla dedicada) + `conexiones/cuarto.hook.js` (redirección) |
| 3 | "Agregar key" no funciona | `Conexiones.dc.html` (formulario real) + `POST /v1/conexiones/key` |
| 4 | El closet de MCPs no tiene salida visible | `conexiones/cuarto.hook.js` (✕ · Escape · click afuera) |
| 5 | El tab Código es estático/ambiguo | `conexiones/codigo.js` (§4 de este documento) |

Causa raíz de (3), medida y no supuesta: `Settings.dc.html::addKey()` usa `window.prompt()`.
Dentro de la app de escritorio (WKWebView) `prompt()` devuelve `null`, y el flujo muere en su
primera línea (`if(!provider) return;`) **sin decir nada**. El Centro lo reemplaza por un
formulario de verdad, con validación en vivo y veredicto visible.

---

## 2 · Arquitectura

```
Conexiones.dc.html          la pantalla (dedicada, como Métodos — no un modal)
  conexiones/centro.api.js  cliente de /v1/conexiones/* (lista · checklist SSE · llave)
  conexiones/centro.ui.js   los dos niveles: lista escaneable + sub-checklist en vivo
  conexiones/cuarto.hook.js puente ADITIVO Cuarto→Centro (una línea para la terminal C)
  conexiones/codigo.js      el tab Código deja de ser ambiguo (§4)

product/backend/app/phase1/centro_conexiones.py    el MOTOR DE REQUISITOS
  GET    /v1/conexiones                  nivel 1 · filas + conteo (barato: cache del motor)
  GET    /v1/conexiones/requisitos/{fam} la definición (para pintar ○ antes de correr nada)
  POST   /v1/conexiones/checklist        nivel 2 · SSE, 1 o N filas en paralelo, con latido
  POST   /v1/conexiones/key              pegás → valida en vivo → guarda cifrada → conectada
  DELETE /v1/conexiones/key/{provider}
```

**No duplica el Motor de Verdad (T1): lo usa.** El motor contesta "¿está probado, y si no,
por qué?" — sirve para el semáforo. El Centro contesta la otra pregunta: **qué falta
exactamente, requisito por requisito**. Mismo vocabulario CERRADO de causas, mismos probers
(`prueba_cli`/`prueba_key`/`prueba_mcp`), misma cache TTL. Lo que agrega es granularidad y el
afinado de causa que el semáforo colapsa a propósito (401/403 → `falta_key` para el
semáforo; `key_invalida` ≠ `sin_credito` ≠ `rate_limit` para el checklist).

### Los requisitos (§C del mandato)

**CLI — 8** (contra el detector D2 real y el argv real que se usaría para correr):
`binario` · `version` (piso por CLI, overrideable por env) · `sesion` · `no_interactivo`
(las banderas de verdad: `-p`/`exec` + salida de máquina + stdin cerrado) · `permisos`
(tools apagadas de fábrica + `assert_argv_safe`) · `cwd` (se crea y se borra una carpeta
efímera de verdad) · `plan` (de tu sesión; `[Probar a fondo]` gasta una corrida mínima real)
· `concurrencia` (el servicio local + corridas en vuelo).

**API — 7:** `formato` · `viva` (GET /models con tu llave) · `diagnostico` (401 ≠ 402 ≠ 429,
cada uno con SU arreglo) · `modelo` (¿está en la lista que tu llave alcanza?) · `base_url`
(¿habla OpenAI-compat?) · `streaming` (se pide un stream real y se lee el primer chunk) ·
`persistencia` (last4 + esquema de cifrado leídos del almacén).

**Cuenta — 3** (`credencial` · `viva` · `persistencia`) y **MCP — 3** (`spec` · `handshake` ·
`tools`), los dos sobre el motor.

Cada requisito que exige mano humana sale con **el comando exacto copiable** y el **link a la
doc oficial**. Los que dependen de nosotros (modo no-interactivo, permisos) lo dicen: *"esto
es un bug de Aleph, no algo que arregles vos"*.

---

## 3 · CONTRATO PARA LA TERMINAL C (dueña de `cuarto.pixi.html`)

No toqué ese archivo. Todo lo del lado del Cuarto está construido, probado contra el archivo
REAL (inyectando los módulos en la página) y esperando **dos líneas**:

```html
<!-- salida del closet de MCPs + [Ver conexión] → Centro + gancho del Guía -->
<script type="module" src="../conexiones/cuarto.hook.js"></script>
<!-- tab Código: receta editable+validada, handler declarado solo-lectura -->
<script type="module" src="../conexiones/codigo.js"></script>
```

Con eso queda cableado:

- `#palette` (closet de MCPs): ✕ visible, Escape, click afuera. Cierra llamando a
  `#equipBtn.click()`, o sea que la cámara (`cam.setInsets`) vuelve como siempre.
- `#iprimary` de una pieza `conexion`: navega a `Conexiones.dc.html?svc=<slug>&volver=<aquí>`
  en vez de expandir el nivel 2. Se re-etiqueta a "Ver conexión ↗".
- Evento `cuarto:semaforo-accion` con acción `credencial|configurar|instalar`: intercepta en
  captura y navega al Centro (antes abría el flujo apilado en el closet chico).
- `window.AlephConexiones.abrir(slug)` para el Guía.

**Opcional, sólo si C quiere que el tab Código pueda APLICAR** (hoy sólo valida):

```js
window.__cuartoAplicarReceta = (receta, {clase, pieza}) => boolean | Promise<boolean>
// …o escuchar `cuarto:codigo-aplicar` (detail={receta, clase, pieza}) y preventDefault().
```
Sin ninguno de los dos, `codigo.js` **no muestra** `[Aplicar]` y lo dice explícitamente. No
ofrece un camino que no existe.

**Nota sobre `preflightRow`** (la lista de precondiciones bajo ▶ Ejecutar, en pixi): usa su
propia copia de la lógica del botón, así que el `[Reintentar]` que muta a `[Configurar]` NO
la alcanza. Si C quiere el mismo comportamiento ahí, el cambio es de dos líneas: guardar si
ya se reintentó y, en ese caso, llamar `Sem.despachar("centro", b.res, b.coord.ctx)` en vez
de re-probar.

---

## 4 · §H · AUDITORÍA DEL TAB «CÓDIGO» (pedida explícitamente)

### ¿Qué muestra hoy? (leído de `cuarto.pixi.html::loadCode`)

| Caso | Bloque | Origen |
|---|---|---|
| Núcleo | «Receta · núcleo (live)» | JSON `{meta, model, framing}` armado **en el cliente** con `tilesToRecipe`. Refleja perillas vivas. |
| Pieza con MCP | «Receta · esta pieza (live)» | `pieceSlice(d)`, también client-side. |
| ídem | «Handler MCP (read-only)» | `GET /v1/tools/{ref}/handler` — código real del handler. |
| Pieza nacida de inspección | «Handler (read-only)» | `synthHandler(d)`: una **plantilla en Python inventada en el cliente**. Parecía fuente real. Era lo más engañoso del tab. |

### ¿Existe camino backend para aplicar/validar?

- **RECETA → SÍ.** `POST /v1/recipes/validate` (`recipe_validator`, contrato taller↔assembler)
  devuelve `{valid, errors[], warnings[], effective_gates}`. Veredicto real. *(Está detrás de
  la sesión: `codigo.js` manda el Bearer él mismo.)*
- **HANDLER → NO.** El tools router es explícitamente READ-ONLY (`app/main.py`: sólo
  `GET /v1/tools/{ref}/handler`; no hay PUT/POST/PATCH). No hay forma de aplicar una edición
  de handler, y fabricar una sería mentir.

### Qué hace `codigo.js` con eso

- **Receta → EDITABLE** (textarea, no un `<pre>` muerto) + `[Validar]` con veredicto real:
  ✓ válida (con avisos + los gates que Security va a hacer cumplir igual) · ✗ **con línea y
  causa**. Valida la receta COMPLETA con la edición aplicada — validar un fragmento suelto
  contra el validador daría un rojo falso ("meta requerido") que no es culpa de lo que editaste.
  Los campos del slice que no son parte del contrato se listan como "no validados".
  `[Revertir]` y `[Copiar]` siempre.
- **Handler → "SOLO LECTURA" visible + `[Copiar]`**, diciendo POR QUÉ (el backend no acepta
  escrituras). El sintetizado además se declara **plantilla, no fuente**.
- **`[Aplicar]`** aparece sólo si C expone el gancho (arriba). Si no, no aparece y se explica.

Detalle: los motores no coinciden al reportar errores de JSON (V8 da `position N`, WebKit
sólo `Unexpected token`). Sin posición no hay línea, y sin línea el error no es accionable —
así que `codigo.js` trae su propio escáner estructural determinista para ubicarlo.

---

## 5 · Cómo se verifica (varas reales, cero mocks de lo que se prueba)

```bash
# backend · motor de requisitos (peer HTTP OpenAI-compat real + SQLite real del cliente)
PYTHONPATH=product/backend:platform:platform/assembler \
  pytest product/backend/app/phase1/test_centro_conexiones.py -q          # 29/29

# la pantalla · WebKit + sidecar FROZEN instalado (:8222) + router nuevo desde fuente (:8223)
node product/app/design/conexiones/verify_conexiones.mjs                  # 55/55

# el puente del Cuarto · WebKit contra cuarto.pixi.html REAL, con los módulos inyectados
node product/app/design/conexiones/verify_cuarto_puente.mjs               # 33/33

# sin regresión en el semáforo (T2)
node product/app/design/cuarto/verify_cuarto_semaforo.mjs                 # 29/29
```

**Por qué DOS sidecares:** el `.app` instalado se congeló antes de que `/v1/conexiones`
existiera, así que el frozen no puede servirlo. El harness proxea `/v1/conexiones/*` al
sidecar de fuente y **todo lo demás** (sesión, llaves, motor, catálogo, validador de recetas)
al binario real. Los dos comparten `ALEPH_DATA_DIR` — y el harness lo COMPRUEBA antes de
medir nada, porque un sidecar viejo colgado en :8222 contesta `/health` y parece sano
apuntando a otra SQLite. Ningún proceso ajeno se toca; el `:25374` del humano está excluido
explícitamente.

El "proveedor de API" del harness es un peer HTTP local que contesta 200/401/402/429 y lista
modelos: por eso `key_invalida ≠ sin_credito ≠ rate_limit` se mide de punta a punta
(UI → backend → HTTP real), no con un stub de la función.

---

## 6 · Lo que NO está

- `[Aplicar]` del tab Código: falta el gancho de C (contrato en §3). Hoy se valida, no se aplica.
- `preflightRow` de pixi mantiene su `[Reintentar]` sin mutación (contrato en §3).
- Filas MCP: salen de los belts sintetizados del usuario y de los que traiga el deep-link
  (`?mcp=<belt_ref>#<server>`). Un belt que no esté en `product/backend/data/synth_belts/`
  no aparece solo.
- `Settings.dc.html::addKey()` sigue usando `prompt()`. No lo toqué (no es mi superficie):
  el camino bueno es que ese botón mande al Centro. Una línea, cuando su dueño quiera.
