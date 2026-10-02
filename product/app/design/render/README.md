# `render/` — módulo RENDER de Aleph (owner: T3) · **INTERFAZ CONGELADA**

> El canvas de la Sala (y cualquier preview del Cuarto) convierte la salida del agente
> en **obra renderada**, nunca texto crudo. Este módulo es esa conversión. T1 (Cuarto) y
> T2 (Sala) lo **importan**; no lo editan. Cambiar la forma de abajo = avisar al integrador.

---

## La interfaz (congelada · F0)

```js
render(artifactType, payload) → DOMNode
```

- **Síncrono.** Devuelve el nodo DOM **ya** (listo para `appendChild`). Los tipos que
  necesitan CDN (markdown/math, three.js) cuelgan el nodo y lo **hidratan** cuando las
  libs cargan — el contrato `→ DOMNode` se respeta siempre.
- `artifactType` = un nombre **canónico del vocabulario único** o cualquiera de sus
  **alias** (`vocabulary.js`, generado desde `platform/artifacts/vocabulary.py`). Fuera
  de la unión → `informe` (fallback). Los 11 que este módulo **dibuja**, abajo.
- `payload` = el artefacto (`{ type, content, ... }`) **o** un string suelto (= content).

```js
import { render, ready } from "../render/render.js";   // ESM (Cuarto/Sala)
canvas.appendChild(render("informe", artifact));

// global (script clásico): window.AlephRender.render(...)
// hidratación lista (tests/screenshots): await ready(node)  → Promise<node>
```

Conveniencias (NO son el contrato, son azúcar sobre `render`):
- `mount(el, type, payload) → node` — **desmonta** lo que hubiera en `el` y cuelga el nodo.
- `renderArtifact(payload) → node` — lee `payload.type`.
- `ready(node) → Promise<node>` — resuelve cuando terminó de hidratar.

### El ciclo de vida (Gate 4 · Fase 2 · 2.4) — **`unmount` es parte del contrato**

```js
unmount(nodeOrHost) → nº de nodos desmontados
onTeardown(node, fn)          // registrá acá lo que tu pantalla tiene que soltar
isDead(node) → bool           // ¿ya se desmontó? (lo mira la hidratación tardía)
```

Sacar un nodo del DOM **no apaga lo que ese nodo prendió**. `unmount` apaga los timers
registrados, le pone `about:blank` a cada iframe **antes** de sacarlo (documento + contexto
WebGL), marca el nodo muerto para que una hidratación tardía no lo resucite, y vacía el host.
Es simétrico: **montar desmonta lo anterior**.

`onTeardown` es la pieza que faltaba para lo pesado: una pantalla React (o cualquier cosa con
suscripciones o estado en un registro global) no fugaba por el nodo sino por el **registro que
lo apunta**, y no tenía dónde declarar su liberación.

Medido en `qa/verify_unmount_sin_fugas.mjs` (12 ciclos × 6 tipos + 24 pantallas de ~1,5 MB):

| | sin desmontar | con `unmount` |
|---|---|---|
| timers vivos al soltar el nodo | **13** (se auto-frenan ~1,4 s después) | **0**, en el acto |
| pantallas retenidas por el registro global | **26** | **0** |
| crecimiento del heap de JS | **+20,6 MB** | **+0,2 MB** |

---

## Los 10 tipos y su `payload`

| `artifactType` | qué es | campos de `payload` |
|---|---|---|
| `informe`   | prosa md/html + math + tablas GFM + citas + ` ```chart ` | `content` (md), `citations?:[{id,label,url}]` |
| `planilla`  | grilla tabular + barra de fórmula | `cols?:[]`, `rows?:[[]]` **o** `content` (tabla markdown) |
| `web`       | preview real en iframe **aislado** | `content` (html) |
| `documento` | memo/carta/documento (serif) · alias: `doc`, `document` | `content` (md) |
| `cad`       | malla 3D three.js (FreeCAD) | `content` (STL ascii / OBJ / glTF) o `url`, `format?:"stl"\|"stl-bin"\|"obj"\|"gltf"\|"glb"` |
| `schematic` | esquemático SVG (KiCad) | `content` (svg) o `url`/data-uri |
| `fieldplot` | campo escalar (OpenFOAM/FEM) | `grid:{nx,ny,values[],min?,max?,unit?}` **o** `image` (url/data-uri); `limit?` (umbral del material → escala verde→rojo) |
| `dicom`     | visor médico read-only | `pixels:{width,height,data[],wc,ww}` **o** `image`+`meta`, `meta:{PatientName,Modality,...}` |
| `convergence` | el LOOP visible: it.N + métrica±delta + veredicto FALLA→PASA + stepping/autoplay | `metric:{name,unit?,goal:"min"\|"max"}`, `limit?`, `iterations:[{n?,value?,grid?}\|{...,curve:[]}]`, `autoplay?:false` |
| `volume3d`  | volumen 3D rotable (marching cubes) | `vertices_b64` (float32 xyz), `faces_b64` (uint32), `color?:[r,g,b]`, `structure?` |

Todos aceptan `title?`.

**Alias vs delegación** (Gate 4 · Fase 2 · 2.3 — antes estaban mezclados en un solo mapa):

- **Alias = IDENTIDAD**, y no los decide este módulo: salen del vocabulario único
  (`doc→documento`, `table→planilla`, `md→informe`, `html→web`, `mesh→cad`,
  `svg/diagrama/diagram→schematic`, `heatmap/field→fieldplot`, `serie/timeseries→linechart`).
  Son los mismos que el almacén acepta al persistir.
- **Delegación = DIBUJO**, y sí la decide este módulo (`DELEGATES`): `dashboard→informe`
  (los ` ```chart ` son ciudadanos de primera ahí), `3d→cad` (no hay visor de escena acá;
  la Sala sí lo tiene), `codigo→informe` (markdown + highlight).
- `imagen` y `galeria` son canónicos y este módulo **no los cubre** a propósito
  (`NOT_COVERED`): los dibuja `sala/render.js`. `AlephRender.coverage()` lo dice.

Ejemplos reales y completos de cada uno: **`samples.js`** (`SAMPLES[type]`).

> **Registro del integrador** — TYPES creció 8→10 (`convergence` 83fd8a9 · `volume3d`
> 6d7bca1) y hoy son **11** (`linechart`); **ya no se declara**: es `Object.keys(RENDERERS)`,
> así que no puede prometer un tipo que no dibuja ni callarse uno que sí (Gate 4 · 2.3).
> En esa misma obra la llave `doc` pasó a llamarse `documento` —el nombre canónico, el que
> el almacén persiste— y `doc` sigue entrando como alias: la interfaz no cambió, los
> nombres aceptados sólo crecieron.
> Este README y el done-bar se sinceraron en la ola sala-renderers (antes decían
> "8 tipos" y el card convergence contaba ✓ vacío). Productores vivos por tipo: FEM/CFD →
> fieldplot+convergence · quant → convergence(curve) · electrónica → convergence+planilla ·
> medicina → volume3d+imagen. **Nota:** el camino `dicom` de píxeles crudos (window/level
> interactivo) hoy NO tiene productor vivo — medicina emite `imagen` data-uri con W/L ya
> aplicado; el renderer y su sample se conservan como capacidad demo-only.

---

## Principios (por qué es seguro y liviano)

- **Tier 0–1, motor invisible.** Nada de VM/stack pesado. Las libs 3D/SVG corren
  **dentro de un iframe sandbox** (origen opaco, `sandbox="allow-scripts"`, sin
  `allow-same-origin`) o se dibujan con **canvas/DOM API**. three.js se carga de CDN
  *adentro* del iframe — nunca en la página del producto.
- **Render, no ejecución.** El html/markdown del modelo se **sanitiza** (DOMPurify); los
  ` ```chart ` se dibujan como **SVG por DOM API** (sin inyección); el código vivo
  (`web`/`cad`) sólo corre aislado y **jamás toca la sesión/BYOK**.
- **Self-contained.** `render.js` inyecta su propio CSS una vez (`#aleph-render-css`).
  T1/T2 sólo importan el `.js`. Cero dependencia de `sala/` ni `cuarto/`.
- **Honesto.** Payload vacío/ilegible → estado vacío explícito o error visible con el
  crudo en un `<details>`; nunca un fake ni tags crudos.

## Estilo / theming

Cada nodo es `.aleph-render.ar-<tipo>`. Los colores salen de CSS vars con default oscuro
(matchea la Sala): overridealos sin tocar el módulo —

```css
.aleph-render{ --ar-bg:#0e1118; --ar-fg:#e6eaf4; --ar-mut:#8b95ac; --ar-line:#222838; --ar-acc:#6c8cff; }
```

---

## DONE-BAR (verificado, no auto-reportado)

`render.demo.html` renderiza los **10 tipos** con los payloads reales de `samples.js`
(carga `../i18n.js` antes del módulo — sin él, las claves `render.*` salen crudas y el
verify lo marca ROJO). `verify.mjs` lo abre en Chromium headless y endurece el verde:
todo type con sample, cero `.ar-empty`/`.ar-err`, asserts estructurales por tipo
(grilla con filas, heatmap, stepper de convergencia con veredicto PASA, charts), mirada
**adentro** de los iframes (cad/volume3d con canvas three, web con botón) y candado
anti-claves-crudas. Guarda `screenshots/render-donebar.png`.

```bash
node verify.mjs        # → { pass:true, demo:{ok:10,total:10}, fails:[] }, exit 0
```

Última corrida: **10/10 hidratados, fails:[], 0 errores de consola.**

## Archivos

| archivo | qué es |
|---|---|
| `render.js` | el módulo (interfaz congelada + 10 renderers + CSS). **Lo que T1/T2 importan.** |
| `samples.js` | un payload real por tipo (geometría/campo/phantom generados, no pegados) |
| `render.demo.html` | la galería de los 10 tipos (DONE-BAR visual) |
| `verify.mjs` | verificación headless endurecida (sirve design/, abre, chequea, screenshot) — dev tool |
