# PLAN-ICONOS — glifo de dominio sobre las tools del Cuarto

> Estado: **APLICADO** (rebase sobre `main` @ 32d295d con `slots` ya aterrizado). El diff de
> §3 está EN `cuarto.render.js`; verificado en frío (`verify_icons.mjs`) y EN VIVO
> (`verify_icons_live.mjs`, Playwright) + regresión recinto/constelación/slots VERDE.
> El bloque de abajo se conserva como el plan original (el diff documentado), por si hace
> falta re-aplicarlo. NOTA de implementación: el wire de la lente F4 terminó en `setView`
> (event-driven), NO en `drawView` → el ticker quedó byte-igual; y `makeDomainGlyph`
> devuelve un `PIXI.Graphics` (no Container) para tint confiable en Pixi v8.

---

## 1. Qué prepara esta rama (sin tocar render)

- **`cuarto.icons.js`** — módulo ESM PURO (sin estado, sin PIXI). Exporta
  `resolveIcon(toolData) → "<lucide-name>"` determinística, más las tablas y helpers
  (`categoryOf`, `GALLERY`, `MOTHER_ICON`, `LEVEL2`, `SERVER_ICON`, `CONNECTOR_ICON`,
  `KEYWORD_ICON`, `ARMARIO_ICON`, `CATEGORY_KEYWORDS`, `ALL_ICONS`).
- **`verify_icons.mjs`** — test EN FRÍO (headless, sin render/backend/browser):
  `node verify_icons.mjs`. Verde: 110 glifos verificados + 36 casos de resolución + helpers.

### Cadena de resolución (de más fuerte a default)
```
resolveIcon(toolData)   // toolData = el `tool`/n.data del Cuarto: {server, connector, tools[], armario, …}
  (1) server conocido            → SERVER_ICON
  (2) connector conocido         → CONNECTOR_ICON
  (3) slug forjado/resuelto      → strip(forged-/resolved-[-:_]) → CATEGORY_KEYWORDS → MOTHER_ICON
      (también matchea un server/connector con nombre PERO fuera de tabla → universalidad)
  (4) keywords de tools[]        → KEYWORD_ICON (send_→mail, quote→trending-up, dicom→heart-pulse, …)
  (5) armario (5 cubos)          → ARMARIO_ICON (mundo→globe · archivos→folder · saberes→book-open · apps→blocks · datos→database)
  (6) DEFAULT                    → "puzzle"  (+ GALLERY() ofrecible en la forja)
```
**Universalidad garantizada:** cualquier MCP cae a un glifo coherente; el desconocido cae
a `puzzle` y se ofrece `GALLERY(categoria|glifo)` (las variantes nivel-2 de las 21 madre).

El `tool` que llega a `placeTool` (vía `normalizeAtom`, `cuarto.catalog.js:99`) trae
top-level `server` · `connector` · `tools[]` · `armario` → el contrato lee esos campos sin tocar nada.

---

## 2. Verificación Lucide (en frío)

- Versión de referencia: **lucide-static@1.21.0** (1986 glifos; árbol de archivos de jsdelivr).
- **Único candidato inexistente:** `scan-3d` → **reemplazado por `axis-3d`** (CAD/3D, variante nivel-2).
- Se prefieren los nombres **canónicos nuevos** sobre alias deprecados (que aún existen como
  archivo, pero conviene no anclarse a ellos): `chart-line` (no `line-chart`),
  `chart-column` (no `bar-chart`), `chart-candlestick` (no `candlestick-chart`).
- `verify_icons.mjs` lleva embebido el set verificado **y** re-valida en vivo contra la lista
  autoritativa si está a mano (`$LUCIDE_NAMES` o `/tmp/lucide_names.txt`) → 110/110 existen.

(El detalle completo de las 21 madre, variantes nivel-2 y `SERVER_ICON`/`CONNECTOR_ICON`
reales del repo vive en `cuarto.icons.js`; el test imprime la matriz entrada→ícono.)

---

## 3. DIFF DE INTEGRACIÓN (escrito, **NO aplicado**)

> Aplicar **después** de que `slots` aterrice y se rebase. `slots` toca esta misma zona, así
> que los números de línea de abajo (anchors de `main` @ 7b63bcb) se moverán: ubicar por el
> texto, no por la línea. Es un cambio chico y localizado: 1 import + 1 call-site + ~6 líneas
> en `makeToolPiece` + 1 helper + 1 entrada de paleta + el wire del lente F4.

### 3.1 Import (junto al import existente, top de `cuarto.render.js`)
```diff
  import { isoToScreen, isoDepth, screenToIso, validateCuartoScene } from "./cuarto.scene.schema.js";
+ import { resolveIcon } from "./cuarto.icons.js";   // [iconos] glifo de dominio (contrato puro)
```

### 3.2 Call-site (`cuarto.render.js:914` — pasar el toolData)
```diff
-    else art = makeToolPiece(color);
+    else art = makeToolPiece(color, tool);   // [iconos] toolData → glifo de dominio
```

### 3.3 `makeToolPiece` (`cuarto.render.js:1869-1885`) — glifo como **3er hijo**, después de plate+wrench, antes del return
```diff
-function makeToolPiece(color) {
-  // TOOL → llave inglesa (silueta sólida, sin ícono de dominio: la llave sola y limpia).
+function makeToolPiece(color, toolData) {
+  // TOOL → llave inglesa (silueta sólida) + GLIFO DE DOMINIO (3er hijo, monocromo en reposo).
   const c = new PIXI.Container();
   const plate = new PIXI.Graphics();
   plate.poly([0, -8, 26, 5, 0, 18, -26, 5]).fill({ color, alpha: 0.18 }).stroke({ color, width: 1, alpha: 0.5 });
   const face = mix(color, 0xffffff, 0.26), edge = mix(color, 0x000000, 0.42);
   const wrench = new PIXI.Graphics();
   wrench.poly([-4, 16, -4, -8, -11, -8, -11, -22, -4, -22, -4, -15,
                4, -15, 4, -22, 11, -22, 11, -8, 4, -8, 4, 16])
     .fill({ color: face }).stroke({ color: edge, width: 2, join: "round" });
   wrench.rotation = -0.42;           // en diagonal, como una llave apoyada
   wrench.position.set(0, -5);
-  c.addChild(plate, wrench);
-  c.__tint = (tint) => { wrench.tint = tint; };
+  // [iconos] glifo de dominio: pequeño, sobre la cabeza de la llave; monocromo en reposo.
+  const domain = makeDomainGlyph(resolveIcon(toolData));   // PIXI.Container con el path Lucide
+  domain.position.set(9, -16); domain.scale.set(0.5);
+  domain.tint = PALT.glyphInk;                             // tinte neutro FIJO (no sigue n.color)
+  c.addChild(plate, wrench, domain);
+  // el role-tint (idle + flujo de la llave) sigue tocando SOLO la llave → el glifo queda monocromo…
+  c.__tint = (tint) => { wrench.tint = tint; };
+  // …salvo cuando el LENTE DE FLUJO (F4) está ON: ahí el glifo toma el color de acción.
+  c.__domainTint = (on, accent) => { domain.tint = on ? accent : PALT.glyphInk; };
   return c;
}
```

### 3.4 Helper nuevo `makeDomainGlyph` (junto a los demás `make*`) — dibuja el path Lucide
```js
// [iconos] dibuja un glifo Lucide monocromo en PIXI v8 (GraphicsContext.svg). El path 'd'
// sale de ICON_PATHS (mapa vendored, lucide-static@1.21.0, solo los glifos que se usan).
// Universalidad también en el DRAW: si el nombre no está en el mapa → cae a ICON_PATHS.puzzle.
function makeDomainGlyph(name) {
  const c = new PIXI.Container();
  const d = ICON_PATHS[name] || ICON_PATHS.puzzle;   // fallback duro → nunca vacío
  const g = new PIXI.Graphics().svg(`<svg viewBox="0 0 24 24"><path d="${d}"/></svg>`);
  g.pivot.set(12, 12);                               // Lucide es 24×24 → centrar
  c.addChild(g);
  return c;
}
// ICON_PATHS = { "trending-up": "...", "mail": "...", "puzzle": "...", … }  // vendored aparte
```
> El `ICON_PATHS` se vendora en el paso de integración (un objeto chico `nombre→path 'd'` con
> los ~110 glifos que `ALL_ICONS` puede emitir, copiados de lucide-static@1.21.0, MIT). No se
> agrega Lucide como dependencia; son strings estáticos. `puzzle` es obligatorio (default).

### 3.5 Paleta — `PALT.glyphInk` (tinte neutro, theme-aware)
```diff
  const PALT = {
    …
+   glyphInk: /* dark */ 0x9aa3b2,   // tinte monocromo del glifo en reposo (claro/oscuro vía theme.js)
  };
```

### 3.6 Wire del LENTE DE FLUJO (F4) — "color sólo con el lente" (mismo paso, seam aparte)
Donde el toggle F4 prende/apaga (la draw-pass del lente, `drawLens`), por cada nodo tool:
```js
// lente ON → el glifo de dominio toma el color de acción del rol (lee/procesa/actúa);
// lente OFF → vuelve a monocromo. (El __tint de la llave NO cambia: F4 ya la maneja.)
if (n.art && n.art.__domainTint) n.art.__domainTint(lensOn, ACTION_COLOR[n.data.role] ?? PALT.glyphInk);
```
> `ACTION_COLOR` = el mapa de color por rol que F4 ya usa (lee=verde · procesa=violeta ·
> actúa=ámbar). Si F4 expone otro nombre, usar el suyo. Sin este wire el glifo queda monocromo
> siempre (degradación segura, no rompe nada).

---

## 4. Por qué no choca con `slots` ni con `i18n`

- **`cuarto.icons.js` es archivo NUEVO** → cero conflicto de merge con `slots` (que edita
  `cuarto.render.js`). La integración (§3) sí toca `render.js`, por eso se difiere: se aplica
  sobre el `render.js` ya con `slots`, ubicando los anchors por texto.
- **i18n:** el glifo es un dato visual, no texto on-camera → el MutationObserver de `i18n.js`
  no lo alcanza ni le importa. `resolveIcon` no traduce; las etiquetas humanas siguen por `window.t`.
- El cambio es **aditivo y de degradación segura**: sin `ICON_PATHS[name]` → `puzzle`; sin el
  wire F4 → glifo monocromo permanente. En ningún camino se rompe el render base.

## 5. Riesgos / notas

- **Anchors móviles:** `slots` + `i18n` mueven las líneas 914/1869 → buscar por texto
  (`else art = makeToolPiece(color)` y `function makeToolPiece(color)`).
- **PIXI v8 `Graphics.svg()`** es la vía de dibujo (el repo ya corre Pixi v8, `vendor/pixi.min.js`).
  Si se prefiere no parsear SVG en runtime, alternativa: pre-trazar cada path a `poly`/`moveTo`
  una vez. El contrato (`resolveIcon`) no cambia en ninguno de los dos casos.
- **`scan-3d` no existe** en Lucide 1.21.0 → ya reemplazado por `axis-3d` en el módulo.
- El `SERVER_ICON`/`CONNECTOR_ICON` cubren los servers/connectors de HOY; cuando entren nuevos
  al catálogo, agregar su fila (o dejar que caigan por categoría/keyword — ya funciona).
