/* cuarto.render.js — the Pixi-native runtime for el Cuarto (Aleph).
 *
 * Pure vanilla ESM + PixiJS v8 (global `PIXI`). Loads cuarto.scene.json + atlas.png,
 * validates against the schema, and renders the iso room from the descriptor — using
 * the SAME isoToScreen()/isoDepth() the contract defines (no second projection).
 *
 * This is the "mapa vivo": a deliberate diorama, not generic decoration.
 *   · ROL DE ACCIÓN por color, legible en la PIEZA (F1): lee = verde · procesa = violeta ·
 *       actúa = ámbar. La capa de agrupado por acción es la LENTE toggle (F4), no el piso.
 *   · 5 ÁTOMOS legible by SHAPE, drawn procedurally (no arbolitos/esferas):
 *       NÚCLEO (cristal · el agente) · TOOL (chip) · CONTEXTO/MEMORIA (tambor) ·
 *       GATE (candado sobre una tool que toca afuera) · CONEXIÓN (el logo del servicio).
 *   · CABLEADO (dotted) + la línea de ECO de retorno al núcleo.
 *   · CÁMARA movible: pan (arrastrar el piso) · zoom (rueda) · rotar el plano (iso 4-vías).
 *
 * ALIVE is first-class: idle motion (núcleo pulsa, zonas respiran, piezas flotan),
 * reactive hover/click (glow + scale → onZoneClick/onPropClick), state juice
 * (setWired / setZoneActive / pulse), and the eco loop driven by REAL run events.
 *
 * Animation is a tiny per-tick lerp toward a target (no tween lib): cheap, 60fps.
 */

import { isoToScreen, isoDepth, screenToIso, validateCuartoScene } from "./cuarto.scene.schema.js";
import { resolveIcon, ICON_PATHS } from "./cuarto.icons.js";   // [iconos] glifo de dominio (contrato puro + paths vendored)
import { identidadDe, detalleDe, svcName as _svcNameID } from "./cuarto.identidad.js"; // [P5] identidad ÚNICA por pieza (cero labels gemelos)

// [i18n-bi Ola B2] el <canvas> Pixi NO lo alcanza el MutationObserver de i18n.js → los
// labels horneados se traducen acá por window.t (idioma del run; reload re-evalúa); fallback = ES.
// Labels de debug que quedan en ES a propósito (no on-camera): la validación de escena
// ("cuarto.scene.json failed validation"), los flags "perm:"/"enab:" del overlay dev.
const TR = (k, fb) => { const s = (typeof window !== "undefined" && window.t) ? window.t(k) : null; return (s && s !== k) ? s : fb; };

// ── Aleph canon: rol-de-acción → color/etiqueta. F4: el rol vive en la PIEZA (F1) y los
// grupos se nombran por VERBO de acción (lee/procesa/actúa). "Mesa" se eliminó como nombre.
const ZONE_DEF = {
  fuentes: { color: 0x35d18f, glow: 0x6af2b0, label: TR("cuarto.zone.lee.label","Lee"),         sub: TR("cuarto.zone.lee.sub","trae dato") },
  mesa:    { color: 0x9a7cff, glow: 0xc4adff, label: TR("cuarto.zone.procesa.label","Procesa"), sub: TR("cuarto.zone.procesa.sub","transforma") },
  entrega: { color: 0xf2b13c, glow: 0xffcf6b, label: TR("cuarto.zone.actua.label","Actúa"),     sub: TR("cuarto.zone.actua.sub","saca") },
  nucleo:  { color: 0xb389ff, glow: 0xe6d6ff, label: TR("cuarto.zone.nucleo.label","Núcleo"),   sub: TR("cuarto.zone.nucleo.sub","el agente") },
};

// category → zona destino + color del átomo (regla C3: read→fuentes · process→mesa ·
// write/send→entrega). El color del átomo = el color de su zona → coherencia visual.
const CATEGORY = {
  read:    { role: "fuentes", color: ZONE_DEF.fuentes.color },
  process: { role: "mesa",    color: ZONE_DEF.mesa.color },
  write:   { role: "entrega", color: ZONE_DEF.entrega.color },
  send:    { role: "entrega", color: ZONE_DEF.entrega.color },
};
const CATEGORY_ROLES = new Set(["fuentes", "mesa", "entrega"]);

// átomos especiales (no-tool): su forma los identifica, no su zona
const ATOM_COLOR = { contexto: 0xff8fcf, conexion: 0x46d6c8, gate: 0xffb454, memoria: 0x22d3ee };   // 2c · memoria compartida = cyan
const ECO_COLOR = 0x4fd6c0;

// ── TEMA del CANVAS (light · dark) ──────────────────────────────────────────────
// El chrome HTML lo themea el CSS (html[data-theme]); esto repinta lo que vive DENTRO
// del canvas Pixi (fondo · piso · paredes · etiquetas) y se conmuta en vivo por
// api.setTheme(mode). El bloque `dark` reproduce EXACTO los colores previos → el modo
// oscuro queda byte-idéntico. Las piezas (núcleo/tools/conexión/gate) usan colores
// saturados que leen bien sobre ambos fondos, así que no dependen del tema.
const THEME = {
  // glyphInk = tinta del glifo de dominio (protagonista monocromo). Gris claro en dark / gris-malva en
  // light → lee sobre el PISO original de cada tema (el zócalo volvió al color único, no carga hue).
  // [identidad visual] los dos bloques se alinearon a la piel de la plataforma
  // (aleph-tokens.css). Antes el piso era azul-grisáceo en oscuro y SEPIA en claro —
  // el mismo diorama que el chrome violeta de alrededor, pintado con otra paleta: era
  // la mitad del "parece de mundos diferentes". Las piezas (núcleo/tools/conexión/gate)
  // NO se tocan: son los colores de dominio, saturados y espejados en el CSS.
  dark:  { bg: 0x131322, floorA: 0x2A2B47, floorB: 0x232338, wall: 0x2e2f48, floorLine: 0x4E4F7E,
           zoneSub: 0xa7a3c8, zoneTagGlow: true,  labelFill: 0xedebfa, labelStroke: 0x131322, glyphInk: 0x908eac },
  light: { bg: 0xf0f3f7, floorA: 0xdde5f0, floorB: 0xeaf0f7, wall: 0xd7d3ec, floorLine: 0xc9d6e6,
           zoneSub: 0x565377, zoneTagGlow: false, labelFill: 0x241f45, labelStroke: 0xffffff, glyphInk: 0x63608a },
};
let PALT = THEME.dark; // tema activo del canvas (lo conmuta api.setTheme)

const approach = (cur, target, k) => cur + (target - cur) * k;
const easeOutBack = (x) => 1 + 2.4 * Math.pow(x - 1, 3) + 1.4 * Math.pow(x - 1, 2);
// ── SLOTS · perillas de previsualización fluida (tunables — el ojo decide el look) ──
const GHOST_LERP = 0.3;    // SLOTS·B · qué tan rápido el ghost alcanza la celda destino (0..1; ↑ = más seco)
const GLOW_LERP  = 0.18;   // SLOTS·B · fade in/out del foco per-celda
// SLOTS·C · GRID QUE RESPIRA (el piso se activa al colocar/acercarse; reposo = casi invisible) ──
const FLOOR_BREATH_LERP = 0.1;     // ease in/out del piso (suave)
const BREATH_RADIUS     = 3;       // celdas: alcance del halo de proximidad (Chebyshev a la celda activa)
const BREATH_MAX        = 0.5;     // dark · intensidad máx del tint hacia el acento
const BREATH_AMBIENT    = 0.12;    // modo-colocar SIN celda (off-floor) → respiración global muy leve
const BREATH_TINT       = 0x9fb4e0; // dark · acento frío al que tiende el piso al activarse
const LIGHT_BREATH_LO   = 0.8;     // light · alpha del piso en reposo (sutil)
const LIGHT_BREATH_HI   = 1.0;     // light · alpha del piso en modo-colocar
const TAU = Math.PI * 2;

export async function mountCuarto(canvasEl, opts = {}) {
  const sceneUrl = opts.sceneUrl || "./cuarto.scene.json";
  const onZoneClick = opts.onZoneClick || (() => {});
  const onPropClick = opts.onPropClick || (() => {});
  const onTilePlaced = opts.onTilePlaced || (() => {});
  const onModoChange = opts.onModoChange || (() => {});   // [reforma · k] el +N del anillo avisa
  const onMultiCableIntent = opts.onMultiCableIntent || (() => Promise.resolve({ ok: true }));
  const onMultiNotice = opts.onMultiNotice || (() => {});

  // ── load + validate (fail loud) ───────────────────────────────────────────
  const scene = await fetch(sceneUrl).then((r) => {
    if (!r.ok) throw new Error(`cuarto: cannot load ${sceneUrl} (${r.status})`);
    return r.json();
  });
  const v = validateCuartoScene(scene);
  if (!v.ok) throw new Error("cuarto.scene.json failed validation:\n  - " + v.errors.join("\n  - "));

  const { grid } = scene;
  let N = Math.max(grid.cols, grid.rows); // rotación iso asume grilla cuadrada; CRECE con el mesh (C5)
  const baseDir = sceneUrl.slice(0, sceneUrl.lastIndexOf("/") + 1);

  // ── stage size + origin (centrar la sala) ─────────────────────────────────
  const bounds = sceneBounds(scene);
  const W = scene.meta.canvasWidth || Math.ceil(bounds.w + 160);
  const H = scene.meta.canvasHeight || Math.ceil(bounds.h + 220);
  const origin = scene.meta.origin || {
    x: Math.round(W / 2 - (bounds.minX + bounds.maxX) / 2),
    y: Math.round(110 - bounds.minY),
  };

  const app = new PIXI.Application();
  await app.init({
    canvas: canvasEl, width: W, height: H,
    backgroundColor: scene.meta.background || "#0b0e14",
    antialias: true, resolution: Math.min(2, window.devicePixelRatio || 1), autoDensity: true,
  });

  // ── atlas → per-frame textures (sólo piso + paredes; el resto es procedural) ─
  const baseTex = await PIXI.Assets.load(baseDir + scene.atlas.image);
  baseTex.source.scaleMode = "nearest";
  const tex = {};
  for (const [name, f] of Object.entries(scene.atlas.frames)) {
    tex[name] = new PIXI.Texture({ source: baseTex.source, frame: new PIXI.Rectangle(f.x, f.y, f.w, f.h) });
  }

  // ── CÁMARA: cameraRoot (pan+zoom) → world (rotación por re-proyección iso) ──
  // arranca con un leve zoom + nudge para que el diorama llene el escenario.
  const cam = { x: 0, y: 22, scale: 1.12, rot: 0 };
  const camHome = { x: 0, y: 22, scale: 1.12, rot: 0 };
  const cameraRoot = new PIXI.Container();
  app.stage.addChild(cameraRoot);
  const world = new PIXI.Container();
  world.sortableChildren = true;
  cameraRoot.addChild(world);
  // D2 · capa de PLANTADO de piezas: raíz = world; al ENTRAR a un recinto-agente apunta al child-world
  // (hermano de world bajo cameraRoot). placeTileInternal/placeRecintoInternal cuelgan de acá → los hijos
  // del recinto se montan en SU propio contenedor sin borrar al padre (que queda oculto detrás, §3.2).
  let placeLayer = world;
  // D2 · STACK DE ESCENAS (estado; las funciones enter/exit/pushInto viven junto a la cámara, más abajo).
  let activeWorld = world;      // contenedor de la escena VIVA (raíz = world; cada hijo tiene el suyo)
  const fractalStack = [];      // frames INMUTABLES del padre — entrar/salir sin corromperlo (invariante §7.2)
  let onFractalChange = null, onFractalDenied = null;   // listeners DOM (breadcrumb / mensaje de tope)
  let onRecintoPanel = null;    // D5 · listener del PANEL DEL RECINTO (identidad+acciones del sub-agente al clicarlo)
  let camTween = null;          // push-in / pull-back ANIMADO, lerpeado en el ticker (:1901)
  let sceneTween = null;        // F2 · crossfade mundo-padre ↔ Cuarto-hijo
  let activeChildScene = null;  // F2 · piso+nucleo+cables del Cuarto fractal activo
  let _enterInFlight = false;    // FIX B (§9·B) · lock SÍNCRONO de re-entrancy: N enters en un solo RTT de fetch bypasseaban el cap + corrompían el stack. Un enter en vuelo → los siguientes {ok:false,reason:'busy'}.
  function finishSceneTween() {
    const prior = sceneTween; sceneTween = null;
    if (!prior) return;
    if (prior.out) {
      prior.out.visible = prior.hideOut === false;
      prior.out.alpha = prior.outTo ?? 0;
      if (prior.destroyOut) {
        try { cameraRoot.removeChild(prior.out); prior.out.destroy({ children: true }); } catch (_) {}
      }
    }
    if (prior.in && !prior.in.destroyed) {
      prior.in.visible = true; prior.in.alpha = prior.inTo ?? 1;
    }
  }
  // ── SUELO · capa de PISO (la más baja del orden de dibujo) ───────────────────
  // Las 3 capas, en orden, son PISO → CABLES → PIEZAS. El piso vive en su PROPIO
  // container, SIEMPRE al fondo, para que nunca tape los cables. Causa del bug previo:
  // el piso usa zIndex (gx+gy)*10 y a profundidad≥1 (zIndex≥10) pintaba ENCIMA de
  // linkGfx (zIndex fijo 5) → los cables "se hundían" bajo el piso. Con el piso aislado
  // abajo, los cables (z5) quedan ENTRE el piso y las piezas (núcleo/tools z≥6/7) sin
  // tocar nada más del z-stack (zonas/paredes/F4/F5/forge intactos byte-a-byte).
  // Promover linkGfx a su propio cableLayer es trabajo de la capa de arriba.
  const floorLayer = new PIXI.Container();
  floorLayer.sortableChildren = true;   // el piso conserva su orden iso interno (depth*10)
  floorLayer.zIndex = -1;               // < todo lo demás en world (el mínimo restante es zoneG=1)
  floorLayer.eventMode = "none";
  world.addChild(floorLayer);
  let floorDirty = true;
  const applyCam = () => {
    cameraRoot.scale.set(cam.scale); cameraRoot.position.set(cam.x, cam.y);
    floorDirty = true;
  };
  applyCam();

  // rotación iso: mapea coord lógica → coord de display según cam.rot (0..3)
  const rotPt = (gx, gy, r) => {
    r = ((r % 4) + 4) % 4;
    if (r === 1) return { x: gy, y: N - 1 - gx };
    if (r === 2) return { x: N - 1 - gx, y: N - 1 - gy };
    if (r === 3) return { x: N - 1 - gy, y: gx };
    return { x: gx, y: gy };
  };
  const invRotPt = (gx, gy, r) => rotPt(gx, gy, (4 - (r % 4)) % 4);
  // ── SUELO · BASE-DE-CELDA CANÓNICA (única — NO reescribir, sólo reusar) ───────
  // toScreen(gx,gy) ES el punto donde una celda toca el piso en pantalla: el centro del
  // rombo iso, vía isoToScreen() del contrato (cuarto.scene.schema.js). Auditado: es la
  // ÚNICA conversión celda→pantalla del Cuarto — no hay proyección divergente (cuarto.live.js
  // pasa por api.viewPoint→toScreen; el isoToScreen que importa es sólo fallback de viewPoint).
  // Toda pieza se PLANTA acá: placeNode() ancla node.gfx a toScreen(node.gx,node.gy); cada
  // pieza vive en su celda (gx,gy), no en píxeles sueltos; la lista de piezas es model.pieces
  // + placedById (cero grafo paralelo). La base de una pieza = la base de su celda = toScreen.
  const toScreen = (gx, gy) => { const d = rotPt(gx, gy, cam.rot); return isoToScreen(d.x, d.y, grid, origin); };
  const depthAt = (gx, gy, z) => { const d = rotPt(gx, gy, cam.rot); return isoDepth(d.x, d.y, z); };
  const zIndexOf = (gx, gy, z, layer) => depthAt(gx, gy, z) * 10 + layer;

  const animated = [];   // todo lo que el ticker idle mueve
  const layoutable = []; // todo lo que se reubica al rotar

  const registerLayout = (node) => { layoutable.push(node); placeNode(node); };
  function placeNode(node) {
    if (node.computeGxGy) { const c = node.computeGxGy(); node.gx = c.gx; node.gy = c.gy; } // nodos atados a una zona (adders)
    const p = toScreen(node.gx, node.gy);
    node.sx = p.x; node.sy = p.y;
    if (node.gfx) { node.gfx.position.set(p.x, p.y); node.gfx.zIndex = zIndexOf(node.gx, node.gy, node.z || 0, node.layer || 0); }
    if (node.baseY != null) node.baseY = p.y;
    if (node.redraw) node.redraw(node);
  }
  // ── POSICIÓN · SETTLE (imán suave al soltar) ──────────────────────────────────
  // El SUELO de celda (toScreen) es la base canónica: una pieza siempre vive en su celda (gx,gy).
  // placeNode() PLANTA instantáneo (lo usa relayout: rotar/crecer/tema = reproyección dura). Para
  // SOLTAR/MOVER/ORDENAR usamos un SETTLE: la pieza se imanta al centro de su celda con un ease
  // tranquilo (no salto seco). Lee el objetivo VIVO toScreen(gx,gy) cada tick → sobrevive una
  // rotación a mitad de viaje. Sólo mueve POSICIÓN (sx/baseY/gfx.x) — JAMÁS toca model.relationships;
  // rebuildLinks resuelve los extremos de sx/baseY igual que en el drag en vivo (F3).
  const settling = new Set();          // piezas easeando hacia su celda
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const SETTLE_K = 0.14;               // ease tranquilo (no resorte brusco)
  function startSettle(node) {
    if (node.kind !== "tile" && node.kind !== "nucleo") { placeNode(node); return; } // el resto se planta duro
    node.ex = node.gfx.position.x;     // arranca desde donde está (la pieza no salta)
    node.ey = node.baseY != null ? node.baseY : node.gfx.position.y;
    node.gfx.zIndex = zIndexOf(node.gx, node.gy, node.z || 0, node.layer || 0);
    settling.add(node);
  }
  function settleTick() {
    if (!settling.size) return;
    for (const node of settling) {
      if (!node.gfx || node.gfx.destroyed) { settling.delete(node); continue; } // pieza removida a mitad de viaje
      const p = toScreen(node.gx, node.gy);            // objetivo VIVO (cámara/rotación-aware)
      node.ex = approach(node.ex, p.x, SETTLE_K);
      node.ey = approach(node.ey, p.y, SETTLE_K);
      node.sx = node.ex; node.sy = node.ey; node.baseY = node.ey; // los extremos que lee rebuildLinks siguen a la pieza
      node.gfx.position.x = node.ex;                   // (tick* dibuja la Y desde baseY; acá mandamos la X)
      if (Math.abs(node.ex - p.x) < 0.5 && Math.abs(node.ey - p.y) < 0.5) {
        node.sx = node.ex = p.x; node.sy = node.ey = p.y; node.baseY = p.y; node.gfx.position.x = p.x;
        settling.delete(node);                         // llegó: fija exacto y deja de easear
      }
    }
  }
  app.ticker.add(settleTick);          // corre ANTES del ticker idle → cables 1:1 con la pieza el mismo frame
  const relayout = () => {
    settling.clear(); for (const n of layoutable) placeNode(n); redrawZones();
    floorDirty = true; refreshVisibleFloor(true);
  };

  // ── piso: diamantes iso NEUTROS (F1: el piso ya no codifica el rol; vive en la pieza) ──
  // ADDENDUM 28-jul · SUELO FINITO VIRTUALIZADO.
  // El mundo tiene N×N celdas, pero NO existe una Sprite por celda. `floorNodes` es un pool
  // acotado por el viewport: al panear/zoomar se recicla para las únicas baldosas visibles.
  // Así el costo de memoria permanece constante aunque el borde haya crecido muchas veces.
  const floorNodes = [], wallCells = new Set(), wallSprites = [];
  let visibleFloorCount = 0, floorGrowth = null, floorGrowthEnabled = true;
  // [reforma · f] el VANO del muro del fondo (un hueco por donde se entra), no una puerta:
  // la silueta de puerta murió con makeConexion. La columna sale del dato de la escena.
  const vanoCol = (scene.props.find((p) => p.sprite === "door") || {}).gridX;
  // F1 · el piso ya NO codifica el rol: es neutro. El rol/color vive en la PIEZA, no en la celda.
  // Las zonas siguen dibujándose como regiones inertes (zoneG) hasta que F4 las haga lente toggle.
  function floorTint(gx, gy) {
    return ((gx + gy) % 2) ? PALT.floorA : PALT.floorB; // checker (impar/par), tema-aware
  }

  /* [sistema 2026-07-31] EL PISO SE DESVANECE, NO SE CORTA.
   *
   * Antes el borde era `edge<=0 ? .24 : edge===1 ? .58 : .96` — tres escalones duros, y el
   * anillo externo pasaba de 0.24 a NADA de golpe. Con las paredes puestas ese canto no se
   * notaba (la pared tapaba el final); sin paredes quedó a la vista y el piso se lee como
   * "un cuarto" con límite, cuando lo que queremos decir es lo contrario.
   *
   * Además de estético es FUNCIONAL: un borde que se apaga gradualmente dice "por acá se
   * puede seguir". Cuando entra una pieza nueva y la sala crece, el ojo ya sabía que había
   * más espacio — no aparece un cuarto más grande de la nada.
   *
   * La distancia es Chebyshev (el máximo de los dos ejes), no euclidiana, para que el
   * desvanecido respete la forma CUADRADA de la grilla y no dibuje un círculo adentro.
   * El piso nunca llega a cero: el 0.06 del borde es lo que insinúa la continuidad. */
  function floorFade(gx, gy) {
    const c = (N - 1) / 2;
    if (c <= 0) return 0.96;
    const d = Math.max(Math.abs(gx - c), Math.abs(gy - c)) / c;   // 0 centro · 1 borde
    const t = Math.max(0, 1 - d);
    /* [persona usuaria] El 0.06 del borde apagaba el piso hasta hacerlo invisible una vez que se
       fueron las paredes: "ni se ve". Sube a 0.14 — el piso sigue desvaneciéndose, pero
       nunca deja de existir. Va de la mano con el azul, que también subió de brillo. */
    return 0.14 + (t * t * (3 - 2 * t)) * 0.82;                   // smoothstep
  }
  function floorNodeAt(i) {
    if (floorNodes[i]) return floorNodes[i];
    const s = new PIXI.Sprite(tex.floor); s.anchor.set(0.5, 0.5); s.eventMode = "none";
    floorLayer.addChild(s);
    const node = { kind: "floor", gx: 0, gy: 0, z: 0, layer: 0, gfx: s, breath: 0 };
    floorNodes.push(node);
    return node;
  }
  function visibleFloorBounds() {
    const logical = [];
    for (const [x, y] of [[0, 0], [W, 0], [W, H], [0, H]]) {
      const lp = world.toLocal(new PIXI.Point(x, y));
      const iso = screenToIso(lp.x, lp.y, grid, origin);
      logical.push(invRotPt(iso.gridX, iso.gridY, cam.rot));
    }
    return {
      minX: clamp(Math.floor(Math.min(...logical.map((p) => p.x))) - 2, 0, N - 1),
      maxX: clamp(Math.ceil(Math.max(...logical.map((p) => p.x))) + 2, 0, N - 1),
      minY: clamp(Math.floor(Math.min(...logical.map((p) => p.y))) - 2, 0, N - 1),
      maxY: clamp(Math.ceil(Math.max(...logical.map((p) => p.y))) + 2, 0, N - 1),
    };
  }
  function refreshVisibleFloor(force = false) {
    if (!force && !floorDirty && !floorGrowth) return;
    floorDirty = false;
    const b = visibleFloorBounds();
    let i = 0;
    for (let gy = b.minY; gy <= b.maxY; gy++) for (let gx = b.minX; gx <= b.maxX; gx++) {
      const n = floorNodeAt(i++), p = toScreen(gx, gy);
      n.gx = gx; n.gy = gy; n.gfx.position.set(p.x, p.y);
      n.gfx.zIndex = isoDepth(gx, gy, 0, N);
      n.gfx.tint = floorTint(gx, gy);
      const edgeAlpha = floorFade(gx, gy);   // desvanecido continuo, no escalones
      let born = 1;
      if (floorGrowth && (gx === floorGrowth.to - 1 || gy === floorGrowth.to - 1))
        born = Math.max(0, Math.min(1, floorGrowth.t));
      n.gfx.alpha = edgeAlpha * born;
      n.gfx.scale.set(0.92 + 0.08 * born);
      n.gfx.visible = false;   // el piso lo dibuja el procedural, en los dos temas
    }
    visibleFloorCount = i;
    for (; i < floorNodes.length; i++) floorNodes[i].gfx.visible = false;
    redrawLightFloor();
  }
  function retintFloor() { floorDirty = true; refreshVisibleFloor(true); }
  // El piso/paredes salen de un atlas OSCURO y el tint sólo MULTIPLICA (no puede aclarar una
  // textura oscura). Para el tema CLARO dibujamos un piso PROCEDURAL (diamantes sólidos, color
  // 100% controlable) y ocultamos los sprites oscuros. En dark este layer queda oculto → el
  // diorama oscuro es byte-idéntico.
  const lightFloor = new PIXI.Graphics(); lightFloor.eventMode = "none"; lightFloor.zIndex = 0; lightFloor.visible = true; floorLayer.addChild(lightFloor); // SUELO · piso procedural (tema claro) en la capa de fondo
  function redrawLightFloor() {
    lightFloor.clear();
    /* [persona usuaria · "no se ven los cuadritos"] Esto era `if (PALT !== THEME.light) return;`.
       En oscuro el piso eran SPRITES de un atlas OSCURO, y el tinte sólo MULTIPLICA: no
       puede aclarar una textura oscura. Había un techo duro — por más claro que se pusiera
       el azul, no subía, y las celdas no se distinguían. El procedural dibuja diamantes
       sólidos con color 100% controlable Y CONTORNO, que es lo que define la celda.
       Ahora los dos temas comparten UN camino de render en vez de dos. */
    const hw = grid.tileWidth / 2, hh = grid.tileHeight / 2;
    for (let i = 0; i < visibleFloorCount; i++) {
      const n = floorNodes[i];
      const x = n.gfx.position.x, y = n.gfx.position.y;
      const alpha = floorFade(n.gx, n.gy);   // desvanecido continuo, no escalones
      lightFloor.poly([x, y - hh, x + hw, y, x, y + hh, x - hw, y])
        .fill({ color: floorTint(n.gx, n.gy), alpha }).stroke({ color: PALT.floorLine, width: 1, alpha: Math.min(1, alpha * 1.35) });
    }
  }
  /* [sistema 2026-07-31] LAS PAREDES MURIERON.
   *
   * Eran el marco de la sala: prismas de un atlas OSCURO, tinteados con PALT.wall. Nunca
   * tuvieron una decisión de diseño en tema claro — se las ocultaba (`s.visible = PALT !==
   * THEME.light`), que es otra forma de decir que sobraban. Y en oscuro leían como bloques
   * y columnas alrededor del piso, compitiendo con lo único que importa acá: las piezas.
   * El sistema nuevo además prohíbe el relieve, y una pared es relieve puro.
   *
   * Se conserva la función —la llaman ensureRoom() al crecer la sala y el barrido de props
   * de la escena— pero no dibuja nada. Así `walls: 0` en la telemetría dice la verdad, y
   * el bucle de re-tinte por tema itera un array vacío sin romperse.
   * El piso, las zonas, los cables y las piezas quedan intactos. */
  function addWall(_gx, _gy) { /* sin paredes: el diorama es piso + piezas */ }
  // garantiza piso + paredes (izquierda gx=0 · fondo gy=0 salvo la puerta) hasta un cuadrado n×n
  function ensureRoom(n) {
    for (let gy = 0; gy < n; gy++) addWall(0, gy);
    for (let gx = 1; gx < n; gx++) if (gx !== vanoCol) addWall(gx, 0);
    floorDirty = true;
  }
  ensureRoom(N);
  refreshVisibleFloor(true);

  // ── zonas: bandas iso con relleno + borde + etiqueta (Fuentes/Mesa/Entrega) ─
  const zoneG = new PIXI.Graphics(); zoneG.zIndex = 1; zoneG.eventMode = "none"; world.addChild(zoneG);
  const zoneNodes = [];
  for (const zn of scene.zones) {
    if (!CATEGORY_ROLES.has(zn.role)) continue;
    const def = ZONE_DEF[zn.role];
    const lbl = new PIXI.Container(); lbl.zIndex = 300; lbl.eventMode = "none"; world.addChild(lbl);
    const tag = new PIXI.Text({ text: def.label, style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif",
      fontSize: 12, fontWeight: "500", fill: def.glow, letterSpacing: 1 } });
    const tag2 = new PIXI.Text({ text: "· " + def.sub, style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif",
      fontSize: 10.5, fill: 0x9fb0c4 } });
    tag.anchor.set(0, 0.5); tag2.anchor.set(0, 0.5); tag2.position.set(tag.width + 5, 1);
    lbl.addChild(tag, tag2);
    const node = { kind: "zone", role: zn.role, data: zn, color: def.color, glowC: def.glow,
      phase: Math.random() * TAU, glow: 0, glowTarget: 0, active: 0, activeTarget: 0,
      gx: zn.gridX, gy: zn.gridY, layer: 4, lbl, tag, tag2,
      redraw() { const c = labelAnchor(zn); this.lbl.position.set(c.x, c.y); } };
    zoneNodes.push(node); animated.push(node); registerLayout(node);
  }
  const zonesByRole = {};
  zoneNodes.forEach((n) => (zonesByRole[n.role] ||= []).push(n));

  function labelAnchor(zn) {
    const cs = footScreen(zn);
    const cx = cs.reduce((a, p) => a + p.x, 0) / 4;
    const topY = Math.min(...cs.map((p) => p.y));
    return { x: cx - 30, y: topY - 12 };
  }
  function footScreen(zn) {
    return [[zn.gridX, zn.gridY], [zn.gridX + zn.w, zn.gridY],
      [zn.gridX + zn.w, zn.gridY + zn.h], [zn.gridX, zn.gridY + zn.h]].map(([x, y]) => toScreen(x, y));
  }
  function footPoly(zn) {
    const cs = footScreen(zn), ty = grid.tileHeight / 2;
    return [cs[0].x, cs[0].y - ty, cs[1].x, cs[1].y - ty, cs[2].x, cs[2].y - ty, cs[3].x, cs[3].y - ty];
  }
  function redrawZones() {
    zoneG.clear();
    for (const node of zoneNodes) {
      const poly = footPoly(node.data);
      const a = 0.18 + node.glow * 0.16 + node.active * 0.22;
      zoneG.poly(poly).fill({ color: node.color, alpha: Math.min(0.52, a) });
      zoneG.poly(poly).stroke({ color: node.glowC, width: 1.8, alpha: 0.55 + node.glow * 0.4 + node.active * 0.35 });
    }
  }
  redrawZones();

  // hit-areas por zona (hover/click)
  for (const node of zoneNodes) {
    const hit = new PIXI.Graphics(); hit.zIndex = 2; hit.eventMode = "static"; hit.cursor = "pointer"; hit.alpha = 0.001;
    const draw = () => { hit.clear().poly(footPoly(node.data)).fill(0xffffff); hit.hitArea = hit.getLocalBounds().rectangle; };
    hit.on("pointerover", () => (node.glowTarget = 1));
    hit.on("pointerout", () => (node.glowTarget = 0));
    hit.on("pointertap", () => { node.glow = 1.4; onZoneClick(node.data.id, node.data); });
    world.addChild(hit);
    registerLayout({ kind: "zonehit", gx: node.data.gridX, gy: node.data.gridY, layer: 2, gfx: hit, redraw: draw });
  }

  // ── RECINTO · sub-rama 2 (DIBUJO): muro + halo + stack, VISTA DERIVADA del modelo ─────────────
  // Una Graphics propia (como zoneG), redibujada cada tick por drawRecintos. zIndex 3: sobre las zonas
  // (1) y bajo los cables (5)/piezas (≥6/7) → el recinto es el RECINTO donde las piezas viven. Cámara/
  // rotación/tema-aware GRATIS por footScreen/footPoly→toScreen→rotPt (la misma maquinaria de zonas).
  const recintoG = new PIXI.Graphics(); recintoG.zIndex = 3; recintoG.eventMode = "none"; world.addChild(recintoG);
  // sub-rama 3: footprint EFECTIVO — colapsado = 1×1 (caja chica + stack), expandido = w×h. El muro, el
  // sellado de occupancy y la convergencia de cables leen el efectivo. n.drag = offset px del arrastre vivo.
  const effW = (n) => (n.collapsed ? 1 : n.footprint.w);
  const effH = (n) => (n.collapsed ? 1 : n.footprint.h);
  const recintoFootRect = (n) => ({ gridX: n.gx, gridY: n.gy, w: effW(n), h: effH(n) });
  // centro de PISO del footprint (base del cable, como tileCenter de una tool) + offset del arrastre vivo.
  // Lo usa la convergencia del cable de un hijo OCULTO: "la caja habla por sus hijos".
  function recintoCenter(n) {
    const cs = footScreen(recintoFootRect(n));
    const ox = n.drag ? n.drag.dx : 0, oy = n.drag ? n.drag.dy : 0;
    return { x: (cs[0].x + cs[1].x + cs[2].x + cs[3].x) / 4 + ox, y: (cs[0].y + cs[1].y + cs[2].y + cs[3].y) / 4 + oy };
  }
  // recinto EXPANDIDO cuyo footprint contiene (gx,gy) — para drop-into-recinto-como-hijo (sub-rama 3).
  const recintoAt = (gx, gy) => {
    for (const n of Object.values(placedById)) {
      if (n.kind !== "recinto" || n.collapsed) continue;
      if (gx >= n.gx && gx < n.gx + n.footprint.w && gy >= n.gy && gy < n.gy + n.footprint.h) return n;
    }
    return null;
  };

  // ── paredes (el marco de la sala) — atlas, reubicables al rotar y EXTENSIBLES (C5) ─
  const propsById = {};
  for (const pr of scene.props) if (pr.sprite === "wall") addWall(pr.gridX, pr.gridY);

  // ── NÚCLEO: el agente (cristal facetado) en la zona núcleo ──────────────────
  const nucleoZone = scene.zones.find((z) => z.role === "nucleo") || { gridX: 3, gridY: 1 };
  const nucleo = makeNucleo(); nucleo.eventMode = "static"; nucleo.cursor = "grab";
  const nucleoNode = { kind: "nucleo", id: "nucleo", gx: nucleoZone.gridX, gy: nucleoZone.gridY, z: 0, layer: 6,
    gfx: nucleo, baseY: 0, phase: 0, glow: 0, glowTarget: 0, color: ZONE_DEF.nucleo.color,
    data: { atom: "nucleo", id: "nucleo", label: TR("cuarto.zone.nucleo.label","Núcleo"), role: "nucleo", identity: TR("cuarto.nucleo.identity","Asistente"), model: "opus", name: "", descripcion: "", objective: "" } };
  nucleo.on("pointerover", () => (nucleoNode.glowTarget = 1));
  nucleo.on("pointerout", () => (nucleoNode.glowTarget = 0));
  // F3 · el Núcleo es la ANCLA y a la vez una pieza MÓVIL: arrastrarlo lo lleva libre y TODAS las
  // líneas lo siguen (rebuildLinks resuelve el extremo "nucleo" en vivo). Comparte el camino de
  // arrastre de las tools (tileDrag → tileDragMove/tileDragUp), que distingue clic (umbral 6px →
  // inspector) de mover. NO entra a occupancy ni a la receta: mover el núcleo no toca el modelo.
  nucleo.on("pointerdown", (e) => { if (running) return; tileDrag = { node: nucleoNode, sx: e.global.x, sy: e.global.y, moved: false }; });
  world.addChild(nucleo); animated.push(nucleoNode); registerLayout(nucleoNode);
  propsById["nucleo_orb"] = nucleoNode; propsById["nucleo"] = nucleoNode;

  // [reforma · f] LA PUERTA MCP DEL DECORADO SE FUE CON LA SILUETA. Era una pieza del fondo
  // que no operaba nada (connector:null) y estaba ahí para enseñar la metáfora "puerta +
  // llave": abrir una puerta y que caigan sus tools. Muerta la metáfora, el decorado que la
  // ilustraba es un objeto clickeable que no hace nada — deuda pura sobre el piso (§8.5).
  // El glosario conserva su entrada `mcp_door` para quien llegue por un deep-link viejo.

  // ── piezas dinámicas (tools/átomos colocados) ───────────────────────────────
  const placedById = {};
  // MULTIAGENTE F2 · estado de PRESENTACIÓN solamente. El plan, los `nucleo:false`
  // y los tipos de cable vienen del motor; este objeto no planifica ni ejecuta.
  const multi = {
    modo: null, plan: null, piezas: [], cables: [], restriction: true,
    linkFrom: null, running: false, activeHop: -1, latencies: new Map(),
    visualCables: [],
    fixedControls: true,
  };
  // [reforma · k] estado de LOS DOS MODOS — declarado ACÁ (no junto a su dibujo) porque
  // rebuildModel(), que vive más arriba, lo marca sucio: un `let` más abajo lo dejaría en TDZ.
  let workMode = false, workFocus = null, workNodes = [], workDirty = true;
  // [P5] identidad del piso (id → {base, calificador, label}) — MISMA razón que el `let` de arriba:
  // rebuildModel() llama a relabelAll(), así que su estado se declara ACÁ, fuera de la TDZ.
  let _identidad = new Map();
  const toolLive = new Map();            // `${pieceId}::${tool}` → "calling" | "done" | "error"
  const occupancy = new Map();
  // F2 · modelo de relaciones (única fuente de verdad de las líneas). Shape documentado donde se
  // construye (rebuildModel, sección ECO). Se rehace al alta/baja/gate de piezas, NUNCA al mover.
  const model = { pieces: [], relationships: [] };
  const cellKey = (gx, gy) => `${gx},${gy}`;
  const zoneAt = (gx, gy) => scene.zones.find((z) => CATEGORY_ROLES.has(z.role) &&
    gx >= z.gridX && gx < z.gridX + z.w && gy >= z.gridY && gy < z.gridY + z.h) || null;

  // ── RECINTO · sub-rama 1 (modelo + occupancy; el MURO/halo/colapso es sub-rama 2) ─────────────
  // _isAgentPiece de projection.js es la FUENTE DE VERDAD de "esto es un agente" (projection.js:32,
  // NO editado). El render usa el MISMO predicado → datos (projection → belt.agent_refs[]) y render
  // (kind:"recinto" con hasNucleo) dicen lo MISMO sobre qué es agente. NO se inventa otra lógica.
  const isAgentPiece = (b) => !!b && (b.atom === "agente" || !!b.nucleo);
  // cellFree(gx,gy) ≡ el viejo !occupancy.has(cellKey) (caso 1×1). footprintFree generaliza a w×h: un
  // recinto ocupa un footprint entero. Los finders consultan cellFree (= footprintFree 1×1) → BYTE-
  // IDÉNTICOS sin recintos, recinto-aware con ellos. seal/unsealFootprint marcan TODAS las celdas→recintoId.
  const cellFree = (gx, gy) => !occupancy.has(cellKey(gx, gy));
  const footprintFree = (gx, gy, w, h) => {
    for (let dy = 0; dy < h; dy++) for (let dx = 0; dx < w; dx++) if (!cellFree(gx + dx, gy + dy)) return false;
    return true;
  };
  const sealFootprint = (node) => {              // sub-rama 3: sella el footprint EFECTIVO (1×1 si colapsado)
    for (let dy = 0; dy < effH(node); dy++) for (let dx = 0; dx < effW(node); dx++)
      occupancy.set(cellKey(node.gx + dx, node.gy + dy), node.id);
  };
  const unsealFootprint = (node) => {
    for (let dy = 0; dy < effH(node); dy++) for (let dx = 0; dx < effW(node); dx++)
      if (occupancy.get(cellKey(node.gx + dx, node.gy + dy)) === node.id) occupancy.delete(cellKey(node.gx + dx, node.gy + dy));
  };
  // primer origen de footprint w×h libre (lo usa api.placeRecinto cuando no se da celda explícita).
  const firstFootprintCell = (w, h) => {
    for (let gy = 1; gy <= grid.rows - h; gy++) for (let gx = 1; gx <= grid.cols - w; gx++)
      if ((gx !== nucleoNode.gx || gy !== nucleoNode.gy) && footprintFree(gx, gy, w, h)) return { gx, gy };
    return null;
  };

  // ── C5 · MESH QUE CRECE — DINÁMICO, MULTI-DIRECCIÓN (abajo·derecha·arriba) ──────
  function freeCellInZone(zone) {
    for (let dy = 0; dy < zone.h; dy++) for (let dx = 0; dx < zone.w; dx++) {
      const gx = zone.gridX + dx, gy = zone.gridY + dy;
      if (cellFree(gx, gy)) return { gx, gy };
    }
    return null;
  }
  const zoneFull = (zone) => !freeCellInZone(zone);
  const _rectsHit = (ax, ay, aw, ah, bx, by, bw, bh) => ax < bx + bw && bx < ax + aw && ay < by + bh && by < ay + bh;
  // ¿el rect propuesto pisa OTRA zona (incluido el núcleo)?
  function _overlapsOther(role, gx, gy, w, h) {
    return scene.zones.some((z) => z.role !== role && (CATEGORY_ROLES.has(z.role) || z.role === "nucleo") &&
      _rectsHit(gx, gy, w, h, z.gridX, z.gridY, z.w, z.h));
  }
  // direcciones en las que la zona PUEDE crecer ahora (dinámico):
  //  abajo (frente) y derecha SIEMPRE (derecha empuja a las vecinas); arriba (atrás) si hay
  //  lugar libre hasta el muro de fondo (row0) sin pisar el núcleo ni otra zona.
  function canGrow(zone, dir, by = 1) {
    if (dir === "down" || dir === "right") return true;
    if (dir === "up") { const gy = zone.gridY - by; return gy >= 1 && !_overlapsOther(zone.role, zone.gridX, gy, zone.w, zone.h + by); }
    if (dir === "left") { const gx = zone.gridX - by; return gx >= 1 && !_overlapsOther(zone.role, gx, zone.gridY, zone.w + by, zone.h); }
    return false;
  }
  const growDirs = (zone) => ["down", "right", "up", "left"].filter((d) => canGrow(zone, d, 1));
  // empujar zonas/piezas a la derecha de `fromGx` (para que cualquier zona pueda crecer →)
  function _pushRight(role, fromGx, by) {
    scene.zones.forEach((z) => { if (z.role !== role && z.gridX >= fromGx) z.gridX += by; });
    const moved = Object.values(placedById).filter((nd) => nd.gx >= fromGx);
    moved.forEach((nd) => occupancy.delete(cellKey(nd.gx, nd.gy)));
    moved.forEach((nd) => { nd.gx += by; nd.data.gridX = nd.gx; occupancy.set(cellKey(nd.gx, nd.gy), nd.id); });
  }
  /** Extiende la zona `role` en una DIRECCIÓN (down·right·up·left), por `by`. Mantiene la
   *  grilla CUADRADA (rotación intacta) y las paredes en el marco. by numérico = legacy "down". */
  function growZone(role, dir = "down", by = 1) {
    // FIX A (§9·A · fuga espacial) · DENTRO de un hijo (fractalStack>0) NO se crece la grilla/zonas
    // COMPARTIDAS del padre: N/grid.cols/rows, scene.zones y _pushRight son singletons vivos que el
    // snapshot de enterRecinto NO captura → crecerlos acá corrompería al padre al salir. Block-and-honest.
    if (fractalStack.length > 0) return { role, dir, blocked: true, frozen: true };
    if (typeof dir === "number") { by = dir; dir = "down"; }      // back-compat: growZone(role, n)
    const zone = scene.zones.find((z) => z.role === role);
    if (!zone || !CATEGORY_ROLES.has(role) || !canGrow(zone, dir, by)) return { role, dir, blocked: true };
    if (dir === "down") zone.h += by;
    else if (dir === "right") { _pushRight(role, zone.gridX + zone.w, by); zone.w += by; }
    else if (dir === "up") { zone.gridY -= by; zone.h += by; }
    else if (dir === "left") { zone.gridX -= by; zone.w += by; }
    const need = Math.max(N, ...scene.zones.map((z) => Math.max(z.gridX + z.w, z.gridY + z.h)));
    const grew = need > N;
    if (grew) {
      const from = N;
      N = need; grid.cols = N; grid.rows = N;
      floorGrowth = { from, to: N, t: 0 };
    }
    ensureRoom(N);                  // piso + paredes (marco) al tamaño actual
    retintFloor(); relayout(); fitAll();
    // [punto 34] los ＋ siguen al borde que se acaba de mover. No-op fuera del MODO (piso limpio),
    // así que el auto-expand de zona (forge/live/gate, que entra por acá vía api.freeCell) no cambia.
    refreshAdders();

    (zonesByRole[role] || []).forEach((zn) => { zn.glow = 1.6; zn.activeTarget = 1; });
    return { role, dir, gridX: zone.gridX, gridY: zone.gridY, w: zone.w, h: zone.h, N, grew };
  }

  // ── DENSIDAD · N DERIVADO DEL CONTEO (reel · port del harness 689749d0) ─────────────────────────
  // El mundo CRECE con lo que contiene. N = ceil(1 + √(count/d)) con d≈0.45 → densidad objetivo
  // count/(N−1)² ≈ 0.45 (techo duro 0.60). La grilla es CUADRADA (rotación iso intacta) y las paredes
  // viven en el marco. EXPANDE ANTES de poblar; NUNCA encoge (Math.max con N actual). Modelado sobre la
  // cola de growZone (ensureRoom/relayout/fitAll). pulseRoom() hace que el espacio nuevo "reaccione" →
  // las celdas nuevas se sienten APARECER antes de que caiga la pieza (el feel Minecraft, barato).
  const DENSITY_D = 0.24, DENSITY_MAX = 0.60;   // densidad objetivo ~0.24 (AIRE: piso + cables visibles entre piezas)
  const targetN = (count) => Math.max(N, Math.ceil(1 + Math.sqrt(Math.max(0, count) / DENSITY_D)));
  function growToN(count) {
    // FIX A (§9·A · fuga espacial) · un hijo NO crece la grilla COMPARTIDA del padre. El auto-grow de
    // placeTile-sin-celda cae acá; dentro de un hijo se coloca en una celda YA libre (child scenes son
    // chicas) o se rechaza honesto (balancedFreeCell→null) — jamás muta N/grid/piso del padre.
    if (fractalStack.length > 0) return { N, grew: false, frozen: true };
    const need = targetN(count);
    if (need <= N) return { N, grew: false };
    const from = N;
    N = need; grid.cols = N; grid.rows = N;
    floorGrowth = { from, to: N, t: 0 };
    ensureRoom(N);                                       // piso + paredes al tamaño nuevo (addFloor/addWall dedupe → idempotente)
    retintFloor(); relayout(); fitAll(); pulseRoom();    // reencuadra (cámara se aleja = "este mundo es tuyo") + el espacio nuevo reacciona
    return { N, grew: true };
  }
  // Crecimiento por INTENCIÓN: una pieza soltada en la penúltima fila/columna abre
  // una fila nueva. El borde sigue siendo finito y visible; sólo se desplaza cuando
  // algo real llega a él. No se materializa la malla: cambia N y el pool del viewport.
  function growFloorNear(gx, gy) {
    if (!floorGrowthEnabled || fractalStack.length > 0) return { grew: false, N };
    if (gx < N - 2 && gy < N - 2) return { grew: false, N };
    const from = N;
    N += 1; grid.cols = N; grid.rows = N;
    floorGrowth = { from, to: N, t: 0 };
    ensureRoom(N); relayout(); pulseRoom(); floorDirty = true;
    return { grew: true, from, N };
  }
  // keep-out: celdas que balancedFreeCell NO puebla, para que el mundo CREZCA legible:
  //   (a) el Núcleo + su anillo (Chebyshev ≤ 1) → el centro nunca se tapa;
  //   (b) el TRONCO de cable bajo el Núcleo (su MISMA columna, las celdas inmediatas debajo) → los
  //       cables que salen del Núcleo quedan despejados. Anclado al Núcleo (gx/gy fijos), NO al centro
  //       de la grilla → ESTABLE cuando N crece (si no, el tronco se "mueve" y tapa piezas ya puestas).
  //   Reserva BLANDA: si no hubiera otra celda libre, balancedFreeCell cae fuera del keep-out (mejor
  //   poblar que fallar). Ver balancedFreeCell.
  function keepOut(gx, gy) {
    if (Math.max(Math.abs(gx - nucleoNode.gx), Math.abs(gy - nucleoNode.gy)) <= 1) return true;   // core + anillo
    if (gx === nucleoNode.gx && gy > nucleoNode.gy && gy <= nucleoNode.gy + 3) return true;        // tronco de cable (bajo el Núcleo)
    // 2b · margen de 1 celda alrededor de cada recinto → el círculo del agente RESPIRA (las piezas
    // sueltas no se pegan al anillo). Reserva BLANDA igual que el resto (balancedFreeCell cae si no hay otra).
    for (const rn of Object.values(placedById)) {
      if (rn.kind !== "recinto") continue;
      const fr = recintoFootRect(rn);
      if (gx >= fr.gridX - 1 && gx <= fr.gridX + fr.w && gy >= fr.gridY - 1 && gy <= fr.gridY + fr.h) return true;
    }
    return false;
  }

  // ── afford DELIBERADO: un ＋ en CADA borde válido de cada zona (multi-dirección) ──
  const adderNodes = [];
  const _adderGeom = {
    down:  (z) => ({ gx: z.gridX + (z.w - 1) / 2, gy: z.gridY + z.h, ch: "＋" }),
    right: (z) => ({ gx: z.gridX + z.w, gy: z.gridY + (z.h - 1) / 2, ch: "＋" }),
    up:    (z) => ({ gx: z.gridX + (z.w - 1) / 2, gy: z.gridY - 1, ch: "＋" }),
    left:  (z) => ({ gx: z.gridX - 1, gy: z.gridY + (z.h - 1) / 2, ch: "＋" }),
  };
  //: [Integración #5 · punto 34] MODO agregar-casillas. Apagado por default.
  //
  // SLOTS·A había RETIRADO los ＋ por-zona y dejado este cuerpo tras un `return` (reversible).
  // El retiro fue correcto pero se llevó puesta la función: no sobraba poder extender una zona a
  // mano, sobraba que los ＋ estuvieran visibles por DEFAULT en cada borde de cada zona, ensuciando
  // el piso de forma permanente. Vuelve como MODO: se activa desde el widget de controles (⊙), los
  // ＋ existen mientras dura, y al salir el diorama queda como estaba. Ver CUARTO-HONESTO.md §8.5.
  let addersMode = false;
  function refreshAdders() {
    // La limpieza va SIEMPRE y va PRIMERO — es lo que hace que salir del modo sea de verdad salir.
    // (Antes el `return` estaba ARRIBA de esto, así que la función no podía ni limpiar.)
    adderNodes.splice(0).forEach((node) => {
      [animated, layoutable].forEach((arr) => { const i = arr.indexOf(node); if (i >= 0) arr.splice(i, 1); });
      try { node.gfx.destroy({ children: true }); } catch {}
    });
    // Fuera del modo el piso nace y queda LIMPIO: ningún nodo kind:"adder" entra a la escena
    // (`adderCount()` === 0, que es lo que asserta verify_slots.mjs · A). El auto-expand de zona
    // (forge/live/gate) NO depende de esto: vive en growZone vía api.freeCell — intacto.
    if (!addersMode) return;
    const hw = grid.tileWidth / 2 * 0.7, hh = grid.tileHeight / 2 * 0.7;
    scene.zones.filter((z) => CATEGORY_ROLES.has(z.role)).forEach((zone) => {
      const color = ZONE_DEF[zone.role].color;
      growDirs(zone).forEach((dir) => {
        const geom = _adderGeom[dir];
        const c = new PIXI.Container(); c.eventMode = "static"; c.cursor = "pointer";
        c.hitArea = new PIXI.Rectangle(-hw, -hh, hw * 2, hh * 2);
        const g = new PIXI.Graphics();
        const plus = new PIXI.Text({ text: geom(zone).ch, style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 14, fontWeight: "500", fill: color } });
        plus.anchor.set(0.5);
        c.addChild(g, plus); world.addChild(c);
        const node = { kind: "adder", role: zone.role, dir, gfx: c, z: 0, layer: 6, glow: 0, glowTarget: 0,
          computeGxGy: () => { const q = geom(zone); return { gx: q.gx, gy: q.gy }; },
          redraw() {
            g.clear().poly([0, -hh, hw, 0, 0, hh, -hw, 0])
              .fill({ color, alpha: 0.05 + node.glow * 0.16 }).stroke({ color, width: 1.3, alpha: 0.3 + node.glow * 0.5 });
            plus.alpha = 0.5 + node.glow * 0.45;
          } };
        c.on("pointerover", () => (node.glowTarget = 1));
        c.on("pointerout", () => (node.glowTarget = 0));
        c.on("pointertap", (e) => { e.stopPropagation(); growZone(zone.role, dir, 1); });
        adderNodes.push(node); animated.push(node); registerLayout(node);
      });
    });
  }
  const buildGrowAdders = refreshAdders; // alias (se llama una vez al montar)

  /** [punto 34] Entra/sale del MODO agregar-casillas. Devuelve el estado ya aplicado.
   *  Idempotente: `set(true)` dos veces reconstruye los ＋ (que es lo correcto si la grilla
   *  cambió en el medio) y `set(false)` dos veces deja 0 igual. */
  function setAddersMode(on) {
    addersMode = !!on;
    refreshAdders();
    return addersMode;
  }

  /** clientX/clientY (CSS px) → { gridX, gridY, zone } lógico, cámara-aware. */
  function screenToCell(clientX, clientY) {
    const r = app.canvas.getBoundingClientRect();
    const gp = new PIXI.Point((clientX - r.left) * (W / r.width), (clientY - r.top) * (H / r.height));
    const lp = world.toLocal(gp);
    const f = screenToIso(lp.x, lp.y, grid, origin);
    const log = invRotPt(Math.round(f.gridX), Math.round(f.gridY), cam.rot);
    if (log.x < 0 || log.y < 0 || log.x >= grid.cols || log.y >= grid.rows) return null;
    return { gridX: log.x, gridY: log.y, zone: zoneAt(log.x, log.y) };
  }

  // ── ghost de arrastre ───────────────────────────────────────────────────────
  const ghost = new PIXI.Graphics(); ghost.zIndex = 99990; ghost.visible = false; ghost.eventMode = "none"; world.addChild(ghost);
  // SLOTS·B · FOCO PER-CELDA: un halo SUAVE sobre la celda destino (reemplaza el flood de zona entera).
  // Vive bajo el ghost y sigue su posición YA interpolada → es READ-ONLY sobre el snap (nunca toca occupancy).
  const cellGlow = new PIXI.Graphics(); cellGlow.zIndex = 99985; cellGlow.visible = false; cellGlow.eventMode = "none"; world.addChild(cellGlow);
  let dragTool = null, lastCell = null, activeCell = null;  // SLOTS·C · activeCell = celda bajo el cursor en modo-colocar (proximidad del piso que respira)
  let ghostTX = 0, ghostTY = 0;                          // SLOTS·B · DESTINO del ghost (el ticker interpola hacia acá)
  let glowOn = false, glowColor = 0xffffff, glowA = 0;   // SLOTS·B · estado del foco per-celda (alpha lerpeado en el ticker)
  function drawGhost(color, ok) {
    ghost.clear();
    const hw = grid.tileWidth / 2, hh = grid.tileHeight / 2;
    ghost.poly([0, -hh, hw, 0, 0, hh, -hw, 0]).fill({ color, alpha: ok ? 0.28 : 0.16 })
      .stroke({ color: ok ? color : 0xff6b6b, width: 2, alpha: 0.9 });
  }
  // SLOTS·B · fija el DESTINO del ghost; tickGhostGlow interpola hacia él → el ghost FLUYE (no salta de
  // celda en celda). UN SOLO SEAM cubre los dos caminos de arrastre (paleta + pieza colocada). Si el ghost
  // estaba oculto (reaparición / primer frame del drag) hace snap: evita el "fly-in" desde la celda vieja.
  function ghostTo(x, y) { ghostTX = x; ghostTY = y; if (!ghost.visible) ghost.position.set(x, y); }
  // SLOTS·B · enciende/apaga el foco per-celda (reemplaza highlightZone: foco único, no inundación de grid).
  function focusCell(on, color) { glowOn = !!on; if (color != null) glowColor = color; }
  function beginDrag(tool) { dragTool = tool; ghost.visible = false; } // visible=false → el 1er updateDrag hace snap (sin fly-in)
  // SLOTS·B · cada frame: interpola el ghost hacia su DESTINO (fluye, no salta) y respira el foco per-celda
  // (un halo suave que SIGUE al ghost ya interpolado). Read-only sobre el snap: no toca occupancy ni el modelo.
  function tickGhostGlow() {
    if (ghost.visible) {
      ghost.position.x = approach(ghost.position.x, ghostTX, GHOST_LERP);
      ghost.position.y = approach(ghost.position.y, ghostTY, GHOST_LERP);
    }
    glowA = approach(glowA, glowOn ? 1 : 0, GLOW_LERP);
    if (glowA < 0.02) { cellGlow.visible = false; return; }
    cellGlow.visible = true;
    cellGlow.position.copyFrom(ghost.position);                 // sigue al ghost YA interpolado → foco fluido
    const hw = grid.tileWidth / 2, hh = grid.tileHeight / 2;
    cellGlow.clear()
      .poly([0, -hh, hw, 0, 0, hh, -hw, 0]).fill({ color: glowColor, alpha: 0.12 * glowA })
      .poly([0, -hh * 1.18, hw * 1.18, 0, 0, hh * 1.18, -hw * 1.18, 0]).stroke({ color: glowColor, width: 2, alpha: 0.5 * glowA });
  }
  // SLOTS·C · EL PISO RESPIRA — en reposo es casi invisible; en modo-colocar (dragTool||tileDrag) se
  // intensifica SUAVE, más cerca de la celda activa (Chebyshev). Es el PISO el que se activa, no objetos
  // que compiten. Dark = tint per-celda hacia un acento; light = alpha GLOBAL del piso procedural (un
  // solo Graphics). Read-only sobre el snap: no toca occupancy ni el modelo.
  function tickFloorBreath() {
    const placing = !!dragTool || !!tileDrag;
    /* [persona usuaria · "no se ven los cuadritos"] La respiración en OSCURO tinteaba los sprites celda
       por celda hacia un acento. Esos sprites ya no se dibujan —el piso pasó a ser procedural
       en los dos temas, que es lo único que permite CONTORNO— así que ese camino no movería
       nada y el piso dejaría de responder al modo-colocar. Ahora los dos temas respiran igual:
       por el alpha global del Graphics. Un solo comportamiento en vez de dos, como el render.
       Se conserva `n.breath` en cero para que floorBreath() del panel de diagnóstico siga
       leyendo una cifra válida en vez de undefined. */
    for (let i = 0; i < visibleFloorCount; i++) floorNodes[i].breath = 0;
    lightFloor.alpha = approach(lightFloor.alpha, placing ? LIGHT_BREATH_HI : LIGHT_BREATH_LO, FLOOR_BREATH_LERP);
  }
  function updateDrag(clientX, clientY) {
    if (!dragTool) return null;
    const cell = screenToCell(clientX, clientY); lastCell = cell;
    if (!cell) { ghost.visible = false; focusCell(false); activeCell = null; return null; }   // fuera del piso → sin drop
    const p = toScreen(cell.gridX, cell.gridY);
    ghostTo(p.x, p.y); ghost.visible = true; ghost.zIndex = zIndexOf(cell.gridX, cell.gridY, 1, 9);  // SLOTS·B · destino → lerp
    // F1 · placement LIBRE: cae en cualquier celda del piso (haya zona o no). El color del ghost
    // sale de la PIEZA (su category/átomo), no de la zona. Si la celda está ocupada, al soltar
    // salta a la libre más cercana (freeCellNear) — por eso el piso nunca es "no-drop".
    const free = !occupancy.has(cellKey(cell.gridX, cell.gridY));
    const color = CATEGORY[dragTool.category]?.color ?? ATOM_COLOR[dragTool.atom] ?? 0xffffff;
    drawGhost(color, free);
    focusCell(true, color);                                   // SLOTS·B · foco per-celda en la celda destino (color de la pieza)
    activeCell = { gx: cell.gridX, gy: cell.gridY };          // SLOTS·C · celda activa → el piso respira por proximidad
    return cell;
  }
  // ══ P6 · SEPARACIÓN DE ANILLOS — LA MÉTRICA ES DE PANTALLA, Y VALE EN LAS 4 ROTACIONES ══════
  //
  // El anillo (drawTileAnillo) es una ELIPSE ACHATADA 2:1 dibujada sobre la pieza. La física vivía
  // entera en cell-space, que es isótropo; la pantalla no lo es (tileWidth 64 / tileHeight 32). Dos
  // pares que en celdas miden lo MISMO (√2) quedan a 32 px (diagonal de la SUMA) y a 64 px (diagonal
  // de la DIFERENCIA): el primero cruza anillos, el segundo no. La física era ciega justo al eje
  // donde los anillos efectivamente chocan — por eso no había radio de colisión que ampliar: NO
  // EXISTÍA. `forceRelax` era Coulomb puro y la separación de hoy es un efecto emergente de tres
  // cosas blandas (score de balancedFreeCell · Coulomb sin mínimo · snap del ordenar), ninguna de
  // las cuales garantiza nada. Acá se CONSTRUYE el piso duro.
  //
  // Y hay una segunda capa: `rotPt` INTERCAMBIA los ejes en las rotaciones impares. A rot 1 el par
  // (+1,+1) queda a (64,0) —sano— y el (+1,−1) a (0,32) —cruzado—: exactamente al revés que a rot 0.
  // Un peso anisótropo fijo en cell-space ("pesá la suma 2× la diferencia") pasa el verify a rot par
  // y ROMPE a rot impar. Por eso acá no hay peso: hay MEDICIÓN contra toScreen(), evaluada en las
  // rotaciones. El layout que sale de esta física está limpio SE ROTE COMO SE ROTE — por eso
  // `rotateBy` (que hace relayout+fitAll y NO re-corre orderLayout) ya no puede reintroducir el
  // cruce: no hay nada que re-separar, porque la separación es invariante a la rotación.
  //
  // toScreen()/rotPt() se USAN, jamás se reimplementan (invariante del SUELO: única conversión
  // celda→pantalla). Para leer una rotación que NO es cam.rot sin tocar su definición: rotPt es un
  // GRUPO —rotPt(rotPt(p,k),c) = rotPt(p,k+c)— así que pre-rotar por (r−cam.rot) y pasar por
  // toScreen da exactamente isoToScreen(rotPt(p,r)). Cero trigonometría duplicada.
  const ANILLO_K = 0.78;        // el aro = 78 % del radio del aura   (espejo exacto de drawTileAnillo)
  const ANILLO_SQUASH = 0.62;   // achatado iso del aro               (ídem)
  // 1.0 = anillos TANGENTES. El extra NO es holgura numérica: la pieza VIVA respira (bob ±1.6 px en
  // tickTile) y ESCALA con glow/relevancia (hasta ×1.09), y el anillo, al ser hijo de n.gfx, respira
  // y escala con ella. El objetivo de la física lleva ese margen; el CONTRATO que mide la vara sigue
  // siendo el duro (cero intersección, sep ≥ 1.0) sobre la geometría viva.
  const SEP_AIRE = 1.18;
  // Para DISTANCIAS, rot 2 ≡ rot 0 y rot 3 ≡ rot 1: rotPt(·,2) niega el Δ de display → el Δ de
  // pantalla queda negado, mismo módulo. Dos clases de rotación, no cuatro. (La vara igual mide las
  // 4 explícitas y sobre el dibujo vivo: no le cree a este comentario.)
  const ROTS_SEP = [0, 1];
  /** semiejes del anillo de una pieza, en px de MUNDO. FUENTE ÚNICA: la consumen la física y
   *  drawTileAnillo. NO escribe el cache `_auraR` — la física puede correr ANTES del primer draw,
   *  cuando los bounds del sprite todavía no son definitivos, y cachear ahí envenenaría el dibujo. */
  function anilloRadii(n) {
    const R = (n && n._auraR) || (n && n.art ? auraRadiusOf(n) : 34);
    const a = R * ANILLO_K;
    return { a, b: a * ANILLO_SQUASH };
  }
  /** radio TÍPICO — para una pieza que todavía NO existe (se está soltando desde la paleta y no
   *  tiene sprite del que sacar bounds). El máximo de las vivas: prudente por construcción. */
  function anilloRadiiTipico() {
    let R = 34;
    for (const n of Object.values(placedById)) if (n.kind === "tile" && n._auraR > R) R = n._auraR;
    const a = R * ANILLO_K;
    return { a, b: a * ANILLO_SQUASH };
  }
  /** pantalla de una celda a una rotación ARBITRARIA (ver el truco del grupo, arriba). */
  function screenAtRot(gx, gy, r) {
    const d = rotPt(gx, gy, (((r - cam.rot) % 4) + 4) % 4);
    return toScreen(d.x, d.y);
  }
  /** separación NORMALIZADA de dos anillos en UNA rotación: 1 = tangentes · <1 = se cruzan · >1 = aire.
   *  Las dos elipses son HOMOTÉTICAS (mismo achatado), así que su suma de Minkowski es la elipse de
   *  semiejes sumados → el test es EXACTO, no una cota. */
  function anilloSepEn(pA, rA, pB, rB) {
    const A = rA.a + rB.a, B = rA.b + rB.b;
    return Math.hypot((pA.x - pB.x) / A, (pA.y - pB.y) / B);
  }
  /** la PEOR de las rotaciones — la que manda (si UNA cruza, el layout está roto para el usuario
   *  que toca el botón de rotar). Devuelve además la rotación culpable, que es por donde empuja. */
  function anilloSep(ax, ay, rA, bx, by, rB) {
    let peor = Infinity, rot = 0;
    for (const r of ROTS_SEP) {
      const s = anilloSepEn(screenAtRot(ax, ay, r), rA, screenAtRot(bx, by, r), rB);
      if (s < peor) { peor = s; rot = r; }
    }
    return { sep: peor, rot };
  }
  /** las piezas SUELTAS vivas — las que llevan (o van a llevar) anillo, y por lo tanto hay que
   *  esquivar. Se cuentan TODAS las tiles, tengan tools o no: una pieza gana tools al equiparse y
   *  un layout que sólo separa a las que hoy tienen anillo se rompe en cuanto aparece la primera. */
  const tilesSueltas = (excluir) => Object.values(placedById)
    .filter((n) => n.kind === "tile" && !n.parentId && n !== excluir)
    .map((n) => ({ gx: n.gx, gy: n.gy, rad: anilloRadii(n) }));
  /** ¿la celda (gx,gy) deja el anillo `rad` LIBRE del de todos los de `otros`? */
  function anilloLibre(gx, gy, rad, otros) {
    for (const o of otros) if (anilloSep(gx, gy, rad, o.gx, o.gy, o.rad).sep < SEP_AIRE) return false;
    return true;
  }
  // ── EL MUNDO TIENE QUE DAR EL AIRE QUE EL ANILLO PIDE ────────────────────────────────────────
  // Con separación de anillo la capacidad de la grilla ya no es "celdas libres": es un empaquetado
  // Chebyshev-2 sobre el interior [1,N−1]² → ceil((N−1)/2)² posiciones. Cuando no alcanza, la
  // escalera de fallback cede y el cruce VUELVE. Antes de ceder se pide un mundo más grande por la
  // MISMA cola que ya usa placeTile (growToN — "el mundo CRECE con lo que contiene"), traduciendo
  // "un N más" al `count` equivalente de su fórmula de densidad. Dentro de un recinto growToN es
  // no-op por diseño (un hijo no crece la grilla del padre) → ahí la escalera cede, como hoy.
  const capacidadConAire = (n) => Math.ceil((n - 1) / 2) ** 2;
  const crecerUnPaso = () => !!growToN(Math.floor(DENSITY_D * N * N)).grew;
  // F1 · una celda libre cerca de un objetivo (anillos Chebyshev). Reemplaza el "free en la MISMA
  // zona": ahora el piso entero es válido, así que si la celda soltada está ocupada buscamos la
  // libre más próxima en cualquier dirección.
  function freeCellNear(gx, gy) {
    if (cellFree(gx, gy)) return { gx, gy };   // la celda que soltó el usuario MANDA: intención > aire
    // el REBOTE, en cambio, lo elige el sistema — y el sistema no tiene por qué elegir la de al lado,
    // que es cruce garantizado. Primera pasada con aire de anillo; si la grilla no da, cede (P6).
    const R = Math.max(grid.cols, grid.rows);
    const rad = anilloRadiiTipico(), otros = tilesSueltas(null);
    const barrer = (exigirAire) => {
      for (let r = 1; r <= R; r++)
        for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
          const nx = gx + dx, ny = gy + dy;
          if (nx < 0 || ny < 0 || nx >= grid.cols || ny >= grid.rows) continue;
          if (!cellFree(nx, ny)) continue;
          if (exigirAire && !anilloLibre(nx, ny, rad, otros)) continue;
          return { gx: nx, gy: ny };
        }
      return null;
    };
    return barrer(true) || barrer(false);
  }
  // ── POSICIÓN · BALANCE (force-directed) ──────────────────────────────────────
  // Dos mecanismos sobre el mismo sistema de celda. (1) HUECO BALANCEADO al NACER una pieza: elige la
  // celda libre que menos amontona (lejos del gentío, cerca del frente de trabajo) SIN mover a nadie →
  // "lo que el usuario movió a mano se queda". (2) ORDENAR: relaja TODAS las piezas con un modelo
  // force-directed (se repelen entre sí, un resorte las ata al Núcleo) y las re-asienta en celdas. El
  // force lee/escribe sólo POSICIÓN (gx/gy/occupancy + settle); NUNCA toca model.relationships.
  function balancedFreeCell() {
    // P6 · el keep-out de anillo deja de ser PREFERENCIA del score y pasa a RESTRICCIÓN. El comentario
    // viejo del score ya decía "NO contiguos (aire entre piezas)" — pero −1.6 por vecino nunca prohibió
    // nada: con el frente denso, colocaba adyacente igual. Ahora se mide contra el anillo, en pantalla.
    const pick = (avoidKeepOut, exigirAire) => {
      const cols = grid.cols, rows = grid.rows;                // se re-leen: la grilla puede haber CRECIDO
      const fcx = (cols - 1) / 2, fcy = clamp(nucleoNode.gy + 3, 1, rows - 1); // "frente": centro de la zona de trabajo
      const rad = anilloRadiiTipico(), vecinos = tilesSueltas(null);
      let best = null, bestScore = -Infinity;
      for (let gy = 1; gy < rows; gy++) for (let gx = 1; gx < cols; gx++) {
        if (!cellFree(gx, gy)) continue;
        if (gx === nucleoNode.gx && gy === nucleoNode.gy) continue;
        if (avoidKeepOut && keepOut(gx, gy)) continue;        // reserva BLANDA: Núcleo legible + tronco de cable despejado
        if (exigirAire && !anilloLibre(gx, gy, rad, vecinos)) continue;   // P6 · RESTRICCIÓN, no preferencia
        let minD = Infinity;                                   // ahora en unidades de ANILLO (1 = tangentes), no en celdas
        for (const v of vecinos) { const s = anilloSep(gx, gy, rad, v.gx, v.gy, v.rad).sep; if (s < minD) minD = s; }
        if (!vecinos.length) minD = 0;
        const dF = Math.hypot(gx - fcx, gy - fcy);
        let occN = 0;                                          // vecinos ocupados (8-conexo) → penalizar para ESPARCIR
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { if (!dx && !dy) continue; if (!cellFree(gx + dx, gy + dy)) occN++; }
        const score = Math.sqrt(minD) * 1.6 - dF * 0.5 - occN * 1.6;   // lejos del gentío · cerca del frente · NO contiguos (aire entre piezas)
        if (score > bestScore) { bestScore = score; best = { gx, gy }; }
      }
      return best;
    };
    // ESCALERA. El ORDEN importa y está medido: antes de ceder NADA se PIDE MUNDO, porque crecer no
    // le saca nada a nadie y ceder sí. Recién si el mundo no puede crecer (dentro de un recinto, o
    // topado) se empieza a ceder — y primero el keep-out, después el aire, igual que la escalera de
    // siempre, con "poblar > fallar" al final.
    //   ⚠️ Ceder el keep-out ANTES de crecer parece equivalente y NO lo es: pone piezas sobre el
    //   Núcleo y su tronco de cable. Medido — así rompía verify_reel §CAMBIO 2 (12/0 → 11/1).
    let best = pick(true, true);
    for (let g = 0; !best && g < 4; g++) { if (!crecerUnPaso()) break; best = pick(true, true); }
    return best || pick(false, true) || pick(true, false) || pick(false, false);
  }
  // celda libre/válida (interior, no-núcleo, no en `taken`) más cercana a un punto cell-space.
  // P6 · con `rad`+`colocados` exige además AIRE DE ANILLO contra lo ya asentado y devuelve null si
  // no hay ninguna: este snap final del ordenar era el tercer camino que DESHACÍA el espaciado que la
  // relajación lograba (tomaba "la más cercana", y esa podía ser la de al lado). Sin los dos últimos
  // argumentos el comportamiento es el de siempre (y nunca devuelve null).
  function nearestFreeValidCell(fx, fy, taken, rad, colocados) {
    const buscar = (exigirAire) => {
      let best = null, bd = Infinity;
      for (let gy = 1; gy < grid.rows; gy++) for (let gx = 1; gx < grid.cols; gx++) {
        if (taken.has(cellKey(gx, gy)) || (gx === nucleoNode.gx && gy === nucleoNode.gy)) continue;
        if (exigirAire && !anilloLibre(gx, gy, rad, colocados)) continue;
        const d = Math.hypot(gx - fx, gy - fy);
        if (d < bd) { bd = d; best = { gx, gy }; }
      }
      return best;
    };
    if (rad && colocados) return buscar(true);                // null = "no hay con aire" → decide orderLayout
    return buscar(false) || { gx: clamp(Math.round(fx), 1, grid.cols - 1), gy: clamp(Math.round(fy), 1, grid.rows - 1) };
  }
  // relajación force-directed en cell-space (sim mutado in-place): un resorte suave tira hacia el
  // FRENTE del Núcleo (lo atan los cables → centra la nube, no la deja pegada a la pared) mientras la
  // repulsión Coulomb entre piezas y contra el Núcleo las reparte → distribución orgánica que se
  // equilibra sola y mata el amontonamiento en un cuadrante.
  function forceRelax(sim, attract, nucleus) {
    const N = sim.length; if (!N) return;
    // P6 · el término que faltaba: PISO DURO de separación, medido en PANTALLA. El Coulomb de abajo
    // (1.3/r², cell-space) se conserva intacto — es el que da la distribución orgánica de hoy — pero
    // reparte sin respetar mínimo alguno, y encima mide en un espacio que no es donde chocan los
    // anillos. Esto se SUMA: mientras la separación normalizada esté bajo SEP_AIRE, empuja a lo largo
    // del gradiente EN PANTALLA (que penaliza más el eje achatado, justo donde se tocan) y traduce ese
    // empujón de vuelta a celdas con la jacobiana INVERSA de toScreen, sondeada —no reimplementada—.
    const rad = sim.map((s) => anilloRadii(s.node));
    const aCelda = {};                                       // pantalla→celda, por rotación (afín)
    for (const r of ROTS_SEP) {
      const o = screenAtRot(0, 0, r), ex = screenAtRot(1, 0, r), ey = screenAtRot(0, 1, r);
      const ax = ex.x - o.x, ay = ex.y - o.y, bx = ey.x - o.x, by = ey.y - o.y;
      const det = (ax * by - ay * bx) || 1e-6;
      aCelda[r] = (sx, sy) => ({ x: (by * sx - bx * sy) / det, y: (-ay * sx + ax * sy) / det });
    }
    const SEP_K = 0.35;                                      // ganancia por iteración (ambas piezas se mueven → <0.5)
    for (let it = 0; it < 220; it++) {
      const fxv = new Array(N).fill(0), fyv = new Array(N).fill(0);
      for (let i = 0; i < N; i++) {
        fxv[i] += (attract.x - sim[i].fx) * 0.035;  // resorte al frente del Núcleo (cables) → centra
        fyv[i] += (attract.y - sim[i].fy) * 0.035;
        const dx = sim[i].fx - nucleus.x, dy = sim[i].fy - nucleus.y, d2 = dx * dx + dy * dy || 1e-3, d = Math.sqrt(d2);
        const fa = 1.8 / d2;                        // repulsión contra el Núcleo (no se le sientan encima)
        fxv[i] += (dx / d) * fa; fyv[i] += (dy / d) * fa;
        for (let j = 0; j < N; j++) {
          if (i === j) continue;
          const rx = sim[i].fx - sim[j].fx, ry = sim[i].fy - sim[j].fy, r2 = rx * rx + ry * ry || 1e-3, r = Math.sqrt(r2);
          const f = 1.3 / r2;                       // repulsión entre piezas → se reparten
          fxv[i] += (rx / r) * f; fyv[i] += (ry / r) * f;
          // ── P6 · separación de ANILLOS, en cada clase de rotación ──
          for (const rot of ROTS_SEP) {
            const pi = screenAtRot(sim[i].fx, sim[i].fy, rot), pj = screenAtRot(sim[j].fx, sim[j].fy, rot);
            const A = rad[i].a + rad[j].a, B = rad[i].b + rad[j].b;
            const ux = (pi.x - pj.x) / A, uy = (pi.y - pj.y) / B;
            const s = Math.hypot(ux, uy);
            if (s >= SEP_AIRE) continue;                     // hay aire en esta rotación: nada que hacer
            // ∇s en pantalla ∝ (Δx/A², Δy/B²). Para ganar `falta` de separación hay que moverse
            // `falta·s/|∇(s²)/2|` px a lo largo de esa dirección (1er orden).
            const gx = (pi.x - pj.x) / (A * A), gy = (pi.y - pj.y) / (B * B);
            let gl = Math.hypot(gx, gy);
            let ex2, ey2;
            if (gl < 1e-9) { ex2 = 1; ey2 = 0; gl = 1; }     // centros coincidentes: dirección determinística
            else { ex2 = gx / gl; ey2 = gy / gl; }
            const px = (SEP_AIRE - s) * Math.max(s, 1e-3) / gl * SEP_K;
            const c = aCelda[rot](ex2 * px, ey2 * px);
            fxv[i] += c.x; fyv[i] += c.y;
          }
        }
      }
      for (let i = 0; i < N; i++) {
        sim[i].fx = clamp(sim[i].fx + clamp(fxv[i], -0.5, 0.5), 1, grid.cols - 1);
        sim[i].fy = clamp(sim[i].fy + clamp(fyv[i], -0.5, 0.5), 1, grid.rows - 1);
      }
    }
  }
  /** ORDENAR · reacomoda TODAS las piezas al layout balanceado (force-directed → snap a celda + settle).
   *  Devuelve {moved,total}. No toca model.relationships (sólo posición), igual que mover a mano. */
  function orderLayout() {
    // RECINTO: el force-directed global reordena sólo TOOLS sueltas (excluye recintos y sus hijos). Sin
    // recintos en escena, `tiles` es IDÉNTICO a hoy (el filtro pasa todo: todo es kind:"tile" sin parentId).
    const tiles = Object.values(placedById).filter((n) => n.kind === "tile" && !n.parentId);
    if (!tiles.length) return { moved: 0, total: 0 };
    // P6 · CRECER ANTES DE RELAJAR. Con aire de anillo la capacidad es un empaquetado Chebyshev-2
    // (ver capacidadConAire); si la grilla no la tiene, la física puede converger perfecto y el snap
    // final tener que ceder igual. +2 por el Núcleo y su tronco de cable. Tope de 4 pasos.
    for (let g = 0; g < 4 && capacidadConAire(grid.cols) < tiles.length + 2; g++) if (!crecerUnPaso()) break;
    const anchor = { x: nucleoNode.gx, y: nucleoNode.gy }, N = tiles.length;
    const front = { x: (grid.cols - 1) / 2, y: clamp(anchor.y + 3, 1, grid.rows - 1) }; // frente del Núcleo (zona de trabajo)
    // semilla determinística en anillo alrededor del frente (rompe simetría sin Math.random → tests estables)
    const sim = tiles.map((n, i) => ({ node: n,
      fx: clamp(front.x + Math.cos((TAU * i) / N) * 0.7, 1, grid.cols - 1),
      fy: clamp(front.y + Math.sin((TAU * i) / N) * 0.7, 1, grid.rows - 1) }));
    forceRelax(sim, front, anchor);
    for (const n of tiles) occupancy.delete(cellKey(n.gx, n.gy));      // libera todas antes de reasignar
    sim.sort((a, b) => Math.hypot(a.fx - anchor.x, a.fy - anchor.y) - Math.hypot(b.fx - anchor.x, b.fy - anchor.y));
    const taken = new Set([cellKey(anchor.x, anchor.y)]);
    for (const r of Object.values(placedById)) if (r.kind === "recinto")   // los footprints de recinto son intocables (no se pisan)
      for (let dy = 0; dy < r.footprint.h; dy++) for (let dx = 0; dx < r.footprint.w; dx++) taken.add(cellKey(r.gx + dx, r.gy + dy));
    let moved = 0;
    const colocados = [];                                             // P6 · anillos YA asentados en esta pasada
    for (const s of sim) {
      const rad = anilloRadii(s.node);
      // P6 · primero con aire; si la grilla no da (recinto, o topada), cede — poblar > fallar. NO se
      // crece acá adentro: growToN hace relayout() y limpiaría el settle de las piezas ya asentadas
      // en esta misma pasada (saltarían en seco). El crecimiento es de antes del bucle, y punto.
      const cell = nearestFreeValidCell(s.fx, s.fy, taken, rad, colocados)
                || nearestFreeValidCell(s.fx, s.fy, taken);
      taken.add(cellKey(cell.gx, cell.gy));
      colocados.push({ gx: cell.gx, gy: cell.gy, rad });
      if (s.node.gx !== cell.gx || s.node.gy !== cell.gy) moved++;
      s.node.gx = cell.gx; s.node.gy = cell.gy; s.node.data.gridX = cell.gx; s.node.data.gridY = cell.gy;
      occupancy.set(cellKey(cell.gx, cell.gy), s.node.id);
      s.node.dragging = false; s.node.gfx.zIndex = zIndexOf(cell.gx, cell.gy, 1, 7);
      startSettle(s.node);                                            // todas easean suave a su nueva celda
      if (s.node.data.role) api_setZoneActive(s.node.data.role, true);
      onTilePlaced(s.node.id, cell.gx, cell.gy, s.node.data.role);    // re-sincroniza la receta (cambió de celda)
    }
    pulseRoom(); fitAll();                                            // reencuadra para que el layout nuevo entre completo
    return { moved, total: N };
  }

  function endDrag() {
    const tool = dragTool; dragTool = null; ghost.visible = false; focusCell(false); activeCell = null;
    if (!tool || !lastCell) return null;                       // soltó fuera del piso → cancela
    growFloorNear(lastCell.gridX, lastCell.gridY);
    const cell = freeCellNear(lastCell.gridX, lastCell.gridY); // F1 · cae donde la sueltes (sin zona obligatoria)
    if (!cell) return { full: "piso" };
    const node = placeTileInternal(tool, cell.gx, cell.gy);
    if (node) onTilePlaced(tool.id, cell.gx, cell.gy, node.data.role);
    return node ? { id: tool.id, gridX: cell.gx, gridY: cell.gy, role: node.data.role } : null;
  }
  const cancelDrag = () => { dragTool = null; ghost.visible = false; focusCell(false); activeCell = null; };

  // ── MOVER una pieza YA colocada (arrastrarla por/entre las zonas) ────────────
  let tileDrag = null;
  /** coords globales del renderer (e.global) → celda lógica, cámara-aware. */
  function cellFromGlobal(px, py) {
    const lp = world.toLocal(new PIXI.Point(px, py));
    const f = screenToIso(lp.x, lp.y, grid, origin);
    const log = invRotPt(Math.round(f.gridX), Math.round(f.gridY), cam.rot);
    if (log.x < 0 || log.y < 0 || log.x >= grid.cols || log.y >= grid.rows) return null;
    return { gridX: log.x, gridY: log.y, zone: zoneAt(log.x, log.y) };
  }
  function moveTileTo(node, gx, gy) {
    const occ = (node.parentId && placedById[node.parentId]) ? placedById[node.parentId].localOcc : occupancy; // hijo → occ LOCAL
    occ.delete(cellKey(node.gx, node.gy));
    node.gx = gx; node.gy = gy;
    node.data.gridX = gx; node.data.gridY = gy;     // F1 · el rol NO se reasigna desde el piso: vive en la pieza
    occ.set(cellKey(gx, gy), node.id);
    node.dragging = false; node.gfx.zIndex = zIndexOf(gx, gy, 1, 7);
    startSettle(node);                                // POSICIÓN · imán suave al centro de la celda (no salto seco)
    if (node.data.role) api_setZoneActive(node.data.role, true); // glow por el rol de la PIEZA, no por la celda
    onTilePlaced(node.id, gx, gy, node.data.role); // re-sincroniza la receta (movió de celda)
  }
  function tileDragMove(e) {
    if (!tileDrag) return;
    if (tileDrag.node.kind === "recinto") return recintoDragMove(e);   // sub-rama 3: el recinto se mueve como BLOQUE
    const dx = e.global.x - tileDrag.sx, dy = e.global.y - tileDrag.sy;
    if (!tileDrag.moved) {
      if (Math.hypot(dx, dy) < 6) return;                       // umbral: distinguir clic de arrastre
      tileDrag.moved = true; tileDrag.node.dragging = true;
      tileDrag.node.gfx.zIndex = 99980; app.canvas.style.cursor = "grabbing";
      if (tileDrag.node.kind !== "nucleo") occupancy.delete(cellKey(tileDrag.node.gx, tileDrag.node.gy)); // libera su celda (el núcleo no entra a occupancy)
    }
    const lp = world.toLocal(new PIXI.Point(e.global.x, e.global.y));
    tileDrag.node.gfx.position.set(lp.x, lp.y - 8);             // la pieza sigue al puntero (leve lift)
    // F3 · la LÍNEA sigue a la pieza EN VIVO: re-ancla los extremos (sx/sy/baseY) que rebuildLinks
    // resuelve cada tick (tileCenter usa baseY-16, nucleoPoint usa baseY-56). Antes sólo movíamos el
    // gfx → la línea quedaba pegada a la celda vieja y "saltaba" al soltar (bug F0). NO toca el modelo.
    tileDrag.node.sx = lp.x; tileDrag.node.sy = lp.y - 8; tileDrag.node.baseY = lp.y - 8;
    const cell = cellFromGlobal(e.global.x, e.global.y);
    if (cell) {                                                  // F1 · cualquier celda del piso (con o sin zona)
      const free = !occupancy.has(cellKey(cell.gridX, cell.gridY));
      const p = toScreen(cell.gridX, cell.gridY);
      ghostTo(p.x, p.y); ghost.visible = true; ghost.zIndex = zIndexOf(cell.gridX, cell.gridY, 1, 9);  // SLOTS·B · destino → lerp
      drawGhost(tileDrag.node.color ?? 0xffffff, free);          // color de la PIEZA que se mueve, no de la zona
      focusCell(true, tileDrag.node.color ?? 0xffffff);          // SLOTS·B · foco per-celda en la celda destino
      activeCell = { gx: cell.gridX, gy: cell.gridY };           // SLOTS·C · celda activa → el piso respira por proximidad
    } else { ghost.visible = false; focusCell(false); activeCell = null; }
  }
  // D5 · PANEL DEL RECINTO · identidad NODE-DERIVED (cero grafo paralelo: sale del nodo real, no de un store
  // paralelo). Sólo un recinto-AGENTE (hasNucleo) tiene identidad de sub-agente → un cajón no dispara panel.
  // El enriquecimiento async (piezas count desde la config hija + memoria propia A3) lo hace pixi.html con la
  // config REAL fetcheada por agent_ref; acá sólo entregamos lo que el tile carga honestamente.
  function recintoPanelPayload(n) {
    const d = n.data || {};
    const live = recintoLive.get(n.id) || {};
    const raw = String(d.interiorEstado || "").toLowerCase();
    const canonical = ["detectado", "no_configurado", "premium", "roto", "probado"].includes(raw)
      ? raw : (live.errored || raw === "error" || raw === "failed") ? "roto"
      : (live.held ? "no_configurado" : (live.crossed || raw === "done") ? "probado" : "detectado");
    return { id: n.id, name: agentVisibleName(d.label), model: d.child_model || null,
      purpose: d.purpose || d.objective || d.hint || TR("cuarto.agent.purpose", "Hace una parte del trabajo y devuelve el resultado."),
      pieceCount: Math.max(0, Number(d.interiorCount) || 0), status: canonical,
      agentRef: d.agent_ref || null, sharesMemory: d.sharesMemory !== false, hasNucleo: true };
  }
  function notifyRecintoPanel(n) {
    if (!onRecintoPanel || !n || n.kind !== "recinto" || !n.hasNucleo) return;
    try { onRecintoPanel(recintoPanelPayload(n)); } catch (e) {}
  }
  function tileDragUp(e) {
    if (!tileDrag) return;
    const node = tileDrag.node, moved = tileDrag.moved; tileDrag = null;
    ghost.visible = false; focusCell(false); activeCell = null; app.canvas.style.cursor = "";
    if (node.kind === "recinto") {                            // sub-rama 3: CLIC = toggle colapsar/expandir · ARRASTRE = mover el bloque
      if (!moved) {
        // F2 · una aleph-pieza tiene UNA sola cara exterior. Presionarla abre su
        // inspector; NO colapsa, NO entra y NO revela las piezas de adentro.
        if (node.hasNucleo) {
          node.glow = 1.6; onPropClick(node.id, node.data); notifyRecintoPanel(node); return;
        }
        // 2c · clic CERCA del mini-Aleph (≤34px de su centro) = inspector del SUB-AGENTE (modelo
        // propio); lejos = toggle de siempre. Va por este riel porque el `hit` del recinto es quien
        // recibe el evento (el ancla no hit-testea en el vendored PIXI).
        if (node.art) {
          const ap = node.art.getGlobalPosition();
          if (Math.hypot(e.global.x - ap.x, e.global.y - (ap.y - 9)) <= 34) {
            node.glow = 1.6; onPropClick(node.id, node.data); notifyRecintoPanel(node); return;   // D5 · + panel del recinto (aditivo)
          }
        }
        toggleCollapse(node); return;
      }
      const aw = toScreen(node.gx, node.gy);                  // ancla origen + offset del arrastre → celda destino
      const fi = screenToIso(aw.x + (node.drag ? node.drag.dx : 0), aw.y + (node.drag ? node.drag.dy : 0), grid, origin);
      const log = invRotPt(Math.round(fi.gridX), Math.round(fi.gridY), cam.rot);
      dropRecinto(node, log.x, log.y); return;
    }
    if (!moved) {
      // 2c · el mini-Aleph del recinto PADRE flota sobre sus hijos: un clic dentro de su radio es
      // del SUB-AGENTE (el hijo gana el hit-test por orden de inserción, no por lo que se VE arriba).
      const par = node.parentId ? placedById[node.parentId] : null;
      if (par && par.art) {
        const ap = par.art.getGlobalPosition();
        if (Math.hypot(e.global.x - ap.x, e.global.y - (ap.y - 9)) <= 34) {
          par.glow = 1.6; onPropClick(par.id, par.data); notifyRecintoPanel(par); return;   // D5 · + panel del recinto (aditivo)
        }
      }
      // [reforma · k] EL +N DEL ANILLO ABRE EL MODO TRABAJO ENFOCADO EN ESE MCP. Es el gesto
      // natural: el número dice "hay 6 acá adentro" y tocarlo las baja. Tocar el resto de la
      // pieza sigue abriendo el abanico.
      if (node.anillo && node.anillo.visible && node._anilloPt) {
        const gp = node.gfx.toGlobal({ x: node._anilloPt.x, y: node._anilloPt.y });
        if (Math.hypot(e.global.x - gp.x, e.global.y - gp.y) <= node._anilloPt.r + 4) {
          const srv = node.data && (node.data.server || node.data.ref);
          workMode = true; workFocus = srv || null; workDirty = true;
          onModoChange({ modo: "trabajo", focus: workFocus, de: node.id });
          return;
        }
      }
      node.glow = 1.6; onPropClick(node.id, node.data); return;   // fue un CLIC → inspector
    }
    const cell = cellFromGlobal(e.global.x, e.global.y);
    if (node.kind === "nucleo") {
      // F3 · el NÚCLEO (ancla) se mueve LIBRE pero NO usa occupancy ni receta (no es tool). Snap a la
      // celda soltada (settle suave); si soltó fuera del piso se queda donde estaba. Las líneas ya lo
      // siguen (extremo "nucleo" resuelto en vivo). Mover NO toca el modelo.
      const c = cell || { gridX: node.gx, gridY: node.gy };
      node.gx = c.gridX; node.gy = c.gridY; node.data.gridX = c.gridX; node.data.gridY = c.gridY;
      node.dragging = false; startSettle(node);
      return;
    }
    resolveTileDrop(node, cell);                               // sub-rama 3: adopción/emancipación o el camino normal (mismo en el fixture)
  }
  // Decide qué pasa al soltar una TOOL en `cell`: adoptar a un recinto / emancipar de uno / re-ubicar
  // dentro / o el camino normal (freeCellNear+moveTileTo). Lo comparten el drag (tileDragUp) y el fixture
  // (api.dropTileAt). Sin recintos involucrados, el camino es BYTE-IDÉNTICO al de hoy.
  function resolveTileDrop(node, cell) {
    if (cell) growFloorNear(cell.gridX, cell.gridY);
    const insideR = cell ? recintoAt(cell.gridX, cell.gridY) : null;
    const curParent = node.parentId ? placedById[node.parentId] : null;
    if (insideR && insideR !== curParent) { adoptIntoRecinto(node, insideR, cell); return; }   // → hijo (occ LOCAL)
    if (!insideR && curParent) { emancipate(node, cell); return; }                              // hijo afuera → global
    if (insideR && insideR === curParent) { moveChildWithin(node, insideR, cell); return; }     // re-ubicar dentro
    const dest = cell ? freeCellNear(cell.gridX, cell.gridY) : null;
    if (dest) { moveTileTo(node, dest.gx, dest.gy); }
    else { occupancy.set(cellKey(node.gx, node.gy), node.id); node.dragging = false; startSettle(node); } // fuera del piso → vuelve
  }

  // RECINTO (sub-rama 1): un AGENTE (Núcleo adentro) o un CAJÓN (contenedor con hijos) NO es una tool.
  // Nace kind:"recinto", SELLA su footprint en el occupancy GLOBAL (→ las piezas externas rebotan, no se
  // enciman) y aloja a sus hijos en un occupancy LOCAL (no entran al global). hasNucleo cae del MISMO
  // predicado que projection (agente↔belt.agent_refs[]). El MURO/halo/colapso es sub-rama 2 → acá el
  // recinto es un PLACEHOLDER mínimo y no-interactivo (la interacción es sub-rama 3).
  function childCellWithin(node, i) {
    const w = node.footprint.w, dx = i % w, dy = Math.floor(i / w);
    return { gx: node.gx + Math.min(dx, w - 1), gy: node.gy + Math.min(dy, node.footprint.h - 1) };
  }
  // RECINTO (sub-rama 2): ocultar un hijo = apagar su gfx (tickTile lo respeta) → su cable converge a la
  // caja vía tileCenter. NO toca el modelo ni la occupancy local (sigue ahí; sólo no se dibuja).
  function setHidden(n, on) {
    if (!n) return; n.hidden = !!on;
    if (n.gfx) n.gfx.visible = !n.hidden;
    if (n.label) n.label.visible = false;
  }
  let agentNameGuardEnabled = true;
  function agentVisibleName(value) {
    const identity = window.AlephAgentIdentity;
    if (identity && typeof identity.displayName === "function") return identity.displayName(value);
    const name = String(value || "").trim().replace(/\s+/g, " ");
    const technical = /^(?:(?:agent|agt|puppet)[-_])?[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$|^\d+(?:[-_./]\d+)*$|^(?:agent|puppet)[-_]?\d+$|^[0-9a-f]{20,}$|^(?:aleph|agent|puppet)\s+[\w-]*\s+[0-9a-f]{6,}$|(?:^|\/)(?:agent[-_])?[^/]+\.(?:config\.)?json$/i;
    return name && !technical.test(name) ? name : "Agente sin nombre";
  }
  function uniqueAgentLabel(raw, excludingId = null) {
    const base = String(raw || "").trim() || TR("cuarto.agent.defaultName", "Mi agente");
    if (!agentNameGuardEnabled) return base;
    const used = new Set(Object.values(placedById)
      .filter((n) => n.kind === "recinto" && n.hasNucleo && n.id !== excludingId)
      .map((n) => String((n.data && n.data.label) || "").trim().toLocaleLowerCase()));
    if (!used.has(base.toLocaleLowerCase())) return base;
    let i = 2;
    while (used.has(`${base} ${i}`.toLocaleLowerCase())) i++;
    return `${base} ${i}`;
  }
  function placeRecintoInternal(tool, gx, gy) {
    const kids = tool.children || [];
    const hasNucleo = isAgentPiece(tool);                       // mismo predicado que projection.js
    if (hasNucleo) tool = { ...tool, label: uniqueAgentLabel(tool.label, tool.id) };
    // La aleph-pieza es UNA baldosa, sin importar cuánto tenga adentro. El interior
    // sólo existe al cruzar de escena mediante zoom semántico.
    const w = hasNucleo ? 1 : Math.max(1, (tool.footprint && tool.footprint.w) || tool.w || Math.min(Math.max(1, kids.length), 3));
    const h = hasNucleo ? 1 : Math.max(1, (tool.footprint && tool.footprint.h) || tool.h || Math.ceil(Math.max(1, kids.length) / w));
    if (!footprintFree(gx, gy, w, h)) return null;              // el footprint ENTERO debe estar libre
    const color = hasNucleo ? ZONE_DEF.nucleo.color : 0x8893a7; // agente = violeta de marca · cajón = neutro
    // sub-rama 2: el MURO/halo/stack se dibujan en recintoG (vista derivada del modelo, drawRecintos). El
    // gfx del nodo es un ancla VACÍA (placeNode lo posiciona; el dibujo NO sale de acá). El placeholder se fue.
    const c = new PIXI.Container(); c.eventMode = "none"; placeLayer.addChild(c);
    // sub-rama 3: hit-area INTERACTIVA (polígono del footprint EFECTIVO, redibujado al rotar/colapsar/
    // mover por node.redraw). pointerdown → tileDrag con el nodo recinto (clic = toggle · arrastre = bloque).
    const hit = new PIXI.Graphics(); hit.eventMode = "static"; hit.cursor = "grab"; hit.alpha = 0.001; hit.zIndex = 4; placeLayer.addChild(hit);
    const node = { kind: "recinto", id: tool.id, atomKind: "recinto", hasNucleo, collapsed: !!tool.collapsed,
      footprint: { w, h }, children: [], localOcc: new Map(), drag: null,
      data: { ...tool, atom: tool.atom || (hasNucleo ? "agente" : "recinto"), gridX: gx, gridY: gy, role: null,
        agent_ref: tool.agent_ref || null, nucleo: hasNucleo || undefined,
        interiorCount: Number.isFinite(tool.interiorCount) ? tool.interiorCount : kids.length,
        interiorEstado: tool.interiorEstado || "idle" },
      gfx: c, hit, art: null, gx, gy, z: 1, layer: 7, baseY: 0, phase: Math.random() * TAU, glow: 0, glowTarget: 0, color };
    if (hasNucleo) {
      // Aleph ≠ MCP: la criatura canónica se para sobre la baldosa. El nombre ya
      // distingue a cada sub-Aleph; no se inventan avatares por agente. El átomo/Núcleo
      // NO se duplica acá: es otra marca y `nucleo:false` sigue siendo sólo un dato del
      // plan. Ningún worker efímero pasa por este constructor.
      node.art = makeAlephCreature();
      node.art.zIndex = 6; c.zIndex = 6;
      c.addChild(node.art);
      const chip = new PIXI.Text({ text: "", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 12,
        fontWeight: "500", fill: PALT.labelFill, stroke: { color: PALT.labelStroke, width: 3 } } });
      chip.anchor.set(0.5, 1); chip.zIndex = 7; chip.eventMode = "none";
      node.chip = chip; c.addChild(chip);
      node.rechip = () => {
        const count = Math.max(0, Number(node.data.interiorCount) || 0);
        chip.text = `${agentVisibleName(node.data.label)}\n${count} ${count === 1
          ? TR("cuarto.agent.piece.one", "pieza") : TR("cuarto.agent.piece.many", "piezas")}`;
      };
      node.rechip();
      const latency = new PIXI.Text({ text: "", style: {
        fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 11,
        fontWeight: "500", fill: 0xffffff, stroke: { color: 0x131322, width: 4 },
      } });
      latency.anchor.set(0.5, 0); latency.visible = false; latency.zIndex = 8;
      latency.eventMode = "none"; node.latencyChip = latency; c.addChild(latency);
      // Puerto visible: el gesto de cablear es tocar puerto A y luego puerto B.
      // La restricción local corre antes de avisar al controlador que llama `/plan`.
      const port = new PIXI.Graphics();
      port.circle(0, 0, 6).fill({ color: 0x17172a, alpha: 0.96 })
        .stroke({ color: ZONE_DEF.nucleo.glow, width: 2, alpha: 0.9 });
      port.eventMode = "static"; port.cursor = "crosshair"; port.zIndex = 8;
      port.on("pointertap", (e) => {
        if (e && e.stopPropagation) e.stopPropagation();
        if (!multi.linkFrom) { multi.linkFrom = node.id; node.glowTarget = 1; return; }
        const from = multi.linkFrom; multi.linkFrom = null;
        const first = placedById[from]; if (first) first.glowTarget = 0;
        requestAgentCable(from, node.id, "entregar");
      });
      node.port = port; c.addChild(port);
    }
    node.redraw = () => {   // hit = UNIÓN del muro (footPoly, cara superior) + el piso (footScreen) → toda la caja es clicable
      const fr = recintoFootRect(node), fs = footScreen(fr);
      hit.clear().poly(footPoly(fr)).poly([fs[0].x, fs[0].y, fs[1].x, fs[1].y, fs[2].x, fs[2].y, fs[3].x, fs[3].y]).fill(0xffffff);
      hit.hitArea = hit.getLocalBounds().rectangle;
    };
    hit.on("pointerdown", (e) => { if (running) return; tileDrag = { node, sx: e.global.x, sy: e.global.y, moved: false }; });
    placedById[tool.id] = node; animated.push(node);
    sealFootprint(node);                                        // sella el footprint GLOBAL → footprintFree rebota piezas externas
    registerLayout(node);
    // Un aleph JAMÁS dibuja el interior desde afuera. Los `kids` viejos sólo sirven
    // como contador; se rehidratan en el child-world al entrar. Los cajones no-Aleph
    // conservan la mecánica previa.
    (!hasNucleo ? kids : []).forEach((ct, i) => {                // hijos en occupancy LOCAL, dentro del footprint
      const cell = childCellWithin(node, i);
      const cn = placeTileInternal(ct, cell.gx, cell.gy, { parent: node });
      if (cn) node.children.push(cn.id);
    });
    if (node.collapsed) node.children.forEach((cid) => setHidden(placedById[cid], true)); // colapsado de nacimiento → hijos ocultos
    rebuildModel();
    return node;
  }

  // ── RECINTO · sub-rama 3 (INTERACCIÓN): toggle · drag del bloque · adopción/emancipación ──────
  // Todo opera sobre el modelo ya existente (kind:"recinto" + children + parentId). El dibujo de ambos
  // estados es sub-rama 2; acá va el CONTROL. Sin recintos en escena, NADA de esto se invoca.
  function rebuildLocalOcc(n) {
    n.localOcc.clear();
    for (const cid of n.children) { const cn = placedById[cid]; if (cn) n.localOcc.set(cellKey(cn.gx, cn.gy), cid); }
  }
  function relocateRecinto(n, ngx, ngy) {        // mueve recinto+hijos manteniendo posición relativa (NO sella ni settle)
    const dgx = ngx - n.gx, dgy = ngy - n.gy; if (!dgx && !dgy) return;
    n.gx = ngx; n.gy = ngy; n.data.gridX = ngx; n.data.gridY = ngy;
    for (const cid of n.children) { const cn = placedById[cid]; if (!cn) continue; cn.gx += dgx; cn.gy += dgy; cn.data.gridX = cn.gx; cn.data.gridY = cn.gy; }
    rebuildLocalOcc(n);
  }
  // DROP del bloque: snap del footprint a celdas + REBOTE si chocaría (reusa footprintFree/seal de sub-rama 1).
  function dropRecinto(n, ngx, ngy) {
    unsealFootprint(n);                                          // libera su propio footprint (no auto-colisiona)
    ngx = clamp(ngx, 0, grid.cols - effW(n)); ngy = clamp(ngy, 0, grid.rows - effH(n));
    const free = footprintFree(ngx, ngy, effW(n), effH(n));
    if (free) relocateRecinto(n, ngx, ngy);                      // libre → mueve el bloque; ocupado → rebota (se queda)
    sealFootprint(n); n.drag = null;
    for (const cid of n.children) { const cn = placedById[cid]; if (cn) { cn.dragging = false; startSettle(cn); } }
    startSettle(n); if (n.redraw) n.redraw(n); onTilePlaced(n.id, n.gx, n.gy, null);
    return free;
  }
  // COLAPSAR/EXPANDIR (el dibujo de ambos ya existe en sub-rama 2; acá el CONTROL + el reflujo del footprint).
  function collapseRecinto(n) {
    if (n.collapsed) return;
    unsealFootprint(n); n.collapsed = true; sealFootprint(n);    // w×h → 1×1: libera las celdas extra del global
    n.children.forEach((cid) => setHidden(placedById[cid], true));
    if (n.redraw) n.redraw(n); rebuildModel();
  }
  function expandRecinto(n) {
    if (!n.collapsed) return;
    unsealFootprint(n); n.collapsed = false;                    // 1×1 → w×h
    if (!footprintFree(n.gx, n.gy, n.footprint.w, n.footprint.h)) {   // ¿cabe en su sitio? si no, REFLUJO (reubica el bloque)
      const free = firstFootprintCell(n.footprint.w, n.footprint.h); if (free) relocateRecinto(n, free.gx, free.gy);
    }
    sealFootprint(n);
    n.children.forEach((cid) => { setHidden(placedById[cid], false); const cn = placedById[cid]; if (cn) startSettle(cn); });
    if (n.redraw) n.redraw(n); rebuildModel();
  }
  const toggleCollapse = (n) => (n.collapsed ? expandRecinto(n) : collapseRecinto(n));
  // drag VIVO del bloque: el muro (n.drag offset en drawRecintos) y los hijos visibles siguen al puntero.
  function recintoDragMove(e) {
    const node = tileDrag.node, dx = e.global.x - tileDrag.sx, dy = e.global.y - tileDrag.sy;
    if (!tileDrag.moved) { if (Math.hypot(dx, dy) < 6) return; tileDrag.moved = true; app.canvas.style.cursor = "grabbing"; }
    const lp = world.toLocal(new PIXI.Point(e.global.x, e.global.y)), sp = world.toLocal(new PIXI.Point(tileDrag.sx, tileDrag.sy));
    node.drag = { dx: lp.x - sp.x, dy: lp.y - sp.y };
    for (const cid of node.children) {                          // hijos VISIBLES siguen al bloque (sus cables siguen por sx/baseY)
      const cn = placedById[cid]; if (!cn || cn.hidden) continue;
      cn.dragging = true; const base = toScreen(cn.gx, cn.gy);
      cn.sx = base.x + node.drag.dx; cn.sy = base.y + node.drag.dy; cn.baseY = cn.sy; cn.gfx.position.set(cn.sx, cn.sy);
    }
  }
  // ── adopción / emancipación (drop-into-recinto-como-hijo y al revés) ──────────────────────────
  function detachFromOcc(node) {                                // saca el nodo de su occupancy actual + de la lista del padre
    const p = node.parentId ? placedById[node.parentId] : null;
    (p ? p.localOcc : occupancy).delete(cellKey(node.gx, node.gy));
    if (p) p.children = p.children.filter((x) => x !== node.id);
  }
  function freeCellInFootprint(R, gx, gy) {                     // celda LOCAL libre dentro del footprint de R, cerca de (gx,gy)
    const cx = clamp(gx, R.gx, R.gx + R.footprint.w - 1), cy = clamp(gy, R.gy, R.gy + R.footprint.h - 1);
    if (!R.localOcc.has(cellKey(cx, cy))) return { gx: cx, gy: cy };
    for (let dy = 0; dy < R.footprint.h; dy++) for (let dx = 0; dx < R.footprint.w; dx++) {
      const x = R.gx + dx, y = R.gy + dy; if (!R.localOcc.has(cellKey(x, y))) return { gx: x, gy: y };
    }
    return { gx: cx, gy: cy };
  }
  function adoptIntoRecinto(node, R, cell) {                    // pieza suelta (o de otro recinto) → HIJO de R (occ LOCAL)
    detachFromOcc(node); node.parentId = R.id;
    const dest = freeCellInFootprint(R, cell.gridX, cell.gridY);
    node.gx = dest.gx; node.gy = dest.gy; node.data.gridX = dest.gx; node.data.gridY = dest.gy;
    R.localOcc.set(cellKey(dest.gx, dest.gy), node.id); R.children.push(node.id);
    setHidden(node, R.collapsed); node.dragging = false; node.gfx.zIndex = zIndexOf(dest.gx, dest.gy, 1, 7);
    startSettle(node); onTilePlaced(node.id, dest.gx, dest.gy, node.data.role); rebuildModel();
  }
  function emancipate(node, cell) {                             // HIJO arrastrado afuera → vuelve al global (pierde parentId)
    detachFromOcc(node); node.parentId = null; node.hidden = false; if (node.gfx) node.gfx.visible = true;
    const c = cell ? freeCellNear(cell.gridX, cell.gridY) : balancedFreeCell(), dest = c || { gx: node.gx, gy: node.gy };
    node.gx = dest.gx; node.gy = dest.gy; node.data.gridX = dest.gx; node.data.gridY = dest.gy;
    occupancy.set(cellKey(dest.gx, dest.gy), node.id);
    node.dragging = false; node.gfx.zIndex = zIndexOf(dest.gx, dest.gy, 1, 7);
    startSettle(node); onTilePlaced(node.id, dest.gx, dest.gy, node.data.role); rebuildModel();
  }
  function moveChildWithin(node, R, cell) {                     // re-ubicar un hijo DENTRO del mismo recinto (occ LOCAL)
    R.localOcc.delete(cellKey(node.gx, node.gy));
    const dest = freeCellInFootprint(R, cell.gridX, cell.gridY);
    node.gx = dest.gx; node.gy = dest.gy; node.data.gridX = dest.gx; node.data.gridY = dest.gy;
    R.localOcc.set(cellKey(dest.gx, dest.gy), node.id); node.dragging = false; startSettle(node);
    onTilePlaced(node.id, dest.gx, dest.gy, node.data.role);
  }

  /** NOMBRE de servicio para la etiqueta del diorama: el server/backed_by titleizado (como el reel:
   *  freecad→"Freecad", forged-zapier→"Forged Zapier", resolved-stripe→"Resolved Stripe"). NO es la
   *  descripción del card (que es español-source). Piezas sin server (Memoria/Núcleo) caen a su label. */
  const _svcName = _svcNameID;

  /** [P5] IDENTIDAD ÚNICA — recalcula el label de CADA pieza del piso contra todas las demás.
   *  Dos piezas jamás quedan con el mismo texto: si colisionan (mismo server) o una es
   *  confundible con otra ("Cad" ⊂ "Freecad"), el calificador honesto aparece SOLO. Se llama
   *  desde rebuildModel() → cubre colocar, sacar y rehidratar sin tocar ningún call-site.
   *  (`_identidad` se declara arriba, junto a workDirty, por la misma regla de TDZ.) */
  function relabelAll() {
    const tiles = Object.values(placedById).filter((n) => n.kind === "tile" && n.label);
    _identidad = identidadDe(tiles.map((n) => n.data));
    tiles.forEach((n) => {
      const id = _identidad.get(n.data.id ?? n.id);
      const txt = (id && id.label) || _svcName(n.data.server) || n.data.label || "Tool";
      if (n.label.text !== txt) n.label.text = txt;
    });
  }

  /* ══ [FIX-P11 · §4] LA IDENTIDAD DE UNA PIEZA NO ES SU `id` ═════════════════════════
   * EL BUG MEDIDO (caminata 2026-07-27): KiCad entró TRES veces al Cuarto — tres piezas en
   * el diorama, doble fila cada una en el panel. P5 había puesto una guarda contra esto
   * (`if (placedById[tool.id]) return null`), y la guarda funciona… para el único camino
   * que la puede activar: el catálogo interno, que reusa el id del átomo.
   *
   * Los otros caminos de equipar fabrican un id NUEVO en cada pasada:
   *     cuarto.forge.js → `id: _uid(server)`  ("kicad-a3f1", "kicad-9c02", "kicad-77bd"…)
   * Tres ids distintos → tres entradas distintas en `placedById` → la guarda mira, no
   * encuentra nada, y coloca la gemela. Equipar dos veces "el mismo" MCP no agrega ninguna
   * capacidad: es el MISMO servidor, las MISMAS tools, la misma llave.
   *
   * La cura es preguntar por lo que hace única a una pieza DE VERDAD: el servidor al que
   * apunta. `belt_ref#server` cuando los dos existen (dos belts pueden traer un `kicad`
   * cada uno y ésos SÍ son piezas distintas), y si no, el conector o el server pelado.
   * Las piezas sin ninguna de esas señas (átomos estructurales: núcleo, memoria, gate) no
   * tienen identidad de servicio y se dedupean como siempre, por id. */
  /* …y la identidad es SERVIDOR + CAPACIDAD, no sólo el servidor. Es la corrección que la
   * vara `verify_slots` cazó de inmediato: su fixture siembra `buscar_dato` y `transformar`,
   * DOS piezas distintas del MISMO server (`tmdb`). Deduplicar por servidor pelado se comía
   * la segunda — y "una pieza = un MCP" resultó ser falso: un MCP puede respaldar varias
   * capacidades, y cada una es su propia pieza en el piso. Lo que NO puede repetirse es la
   * misma capacidad del mismo servidor, que es el caso KiCad (tres veces la misma cosa).
   *
   * La capacidad se lee, en orden, de: `key` (estable por átomo del catálogo), las `tools`
   * ordenadas, o el label. La `key` se NORMALIZA sacándole la procedencia (`resolved:` /
   * `forged:`): el mismo servidor traído dos veces del registro tiene que colisionar consigo
   * mismo aunque el prefijo cambie de pasada. */
  function _capacidadDe(tool) {
    const k = String(tool.key || "").trim().toLowerCase().replace(/^(resolved|forged|byo|synth):/, "");
    if (k) return k;
    const tools = Array.isArray(tool.tools) ? tool.tools.filter(Boolean).map(String).slice().sort() : [];
    if (tools.length) return "t:" + tools.join(",").toLowerCase();
    return "l:" + String(tool.label || "").trim().toLowerCase();
  }

  function identidadDeTool(tool) {
    if (!tool) return null;
    const kind = tool.atom || "tool";
    if (kind !== "tool" && kind !== "conexion") return null;   // estructurales: sin servicio
    const srv = String(tool.server || tool.backed_by || "").trim().toLowerCase();
    const belt = String(tool.belt_ref || "").trim().toLowerCase();
    const conn = String(tool.connector || "").trim().toLowerCase();
    const cap = _capacidadDe(tool);
    if (belt && srv) return "belt:" + belt + "#" + srv + "|" + cap;
    if (srv) return "srv:" + srv + "|" + cap;
    if (conn) return "conn:" + conn + "|" + cap;
    const ref = String(tool.ref || "").trim().toLowerCase();
    return ref ? "ref:" + ref + "|" + cap : null;
  }
  const placedByIdentity = new Map();          // identidad → id de la pieza que la ocupa

  /** ¿Esta pieza YA está en el piso? Devuelve el id de la que está, o null. Es lo que TODO
   *  camino de equipar tiene que preguntar antes de colocar — para poder decir la verdad
   *  ("ya la tenés, te la marco") en vez de callarse o inventar que faltó lugar. */
  function yaColocadaPor(tool) {
    if (!tool) return null;
    if (typeof tool === "string") return placedById[tool] ? tool : null;
    if (tool.id && placedById[tool.id]) return tool.id;
    const idn = identidadDeTool(tool);
    if (!idn) return null;
    const dueño = placedByIdentity.get(idn);
    return dueño && placedById[dueño] ? dueño : null;
  }

  /** crea un átomo colocado VIVO (drop-pop, bob, prende su zona). */
  function placeTileInternal(tool, gx, gy, opts) {
    opts = opts || {}; const parent = opts.parent || null;
    // RECINTO: una pieza-AGENTE (Núcleo adentro) o con hijos NO se aplana a tool → nace recinto, con el
    // MISMO predicado de projection.js (datos↔render alineados). Sin parent y sin ser agente/contenedor,
    // el camino de tool queda BYTE-IDÉNTICO. (Un recinto no se anida dentro de otro en sub-rama 1.)
    if (!parent && isAgentPiece(tool)) {
      const ref = String(tool.agent_ref || tool.ref || "");
      const repeated = ref && Object.values(placedById).some((n) =>
        n.kind === "recinto" && n.hasNucleo && String(n.data.agent_ref || n.data.ref || "") === ref);
      if (repeated) {
        onMultiNotice({ ok: false, cause: "aleph_repetido",
          message: "este Aleph ya está en la cadena", beforePlan: true });
        return null;
      }
    }
    if (!parent && (isAgentPiece(tool) || (tool.children && tool.children.length))) return placeRecintoInternal(tool, gx, gy);
    const occ = parent ? parent.localOcc : occupancy;            // hijo → occupancy LOCAL del recinto; tool suelta → global (igual que hoy)
    // [P5] DEDUPE del flujo de equipar: una pieza YA en el piso no se equipa dos veces. Sin esta
    // guarda, placeTile(mismo id) creaba un segundo nodo y pisaba placedById[id] → la primera
    // quedaba huérfana (viva en `animated`, fuera del modelo) y el piso mostraba dos gemelas.
    if (placedById[tool.id]) return null;
    // [FIX-P11 · §4] …y el MISMO servicio tampoco entra dos veces aunque traiga un id nuevo.
    // Esta es la guarda que los caminos con `_uid(server)` esquivaban. Va acá —en el ÚNICO
    // punto por el que pasa toda pieza que nace— para que no exista un camino de equipar,
    // presente o futuro, que pueda saltearla. Los caminos de arriba preguntan antes para
    // poder DECIR la verdad; éste es el que garantiza que no ocurra.
    if (!parent && yaColocadaPor(tool)) return null;
    if (occ.has(cellKey(gx, gy))) return null;                   // F1 · NO se exige zona: cae en cualquier celda libre
    const atomKind = tool.atom && ATOM_COLOR[tool.atom] ? tool.atom : "tool";
    const cat = CATEGORY[tool.category];
    const color = atomKind === "tool" ? (cat?.color ?? 0xffffff) : ATOM_COLOR[atomKind];
    // F1 · el ROL vive en la PIEZA: una tool se tipa por su category (no por la celda donde cae) y
    // conserva ese rol la muevas donde la muevas. Los átomos no-tool (núcleo/contexto/conexión/gate)
    // NO tienen rol de flujo (spec §1) → role = null, no lo heredan del piso.
    const role = atomKind === "tool" ? (tool.role || cat?.role || "mesa") : null;

    let art;
    if (atomKind === "contexto") art = makeContexto(color);
    else if (atomKind === "conexion") art = makeConexion(color, tool);   // [ticket 8] toolData → placa de marca si el servicio es conocido
    else if (atomKind === "gate") art = makeGate(color);
    else if (atomKind === "memoria") art = makeMemoria(color);   // 2c · la base compartida de los agentes
    else art = makeToolPiece(color, tool);   // [iconos] toolData → glifo de dominio (resolveIcon)
    // F5 · el candado YA NO va sobre el ícono: vive SOBRE LA LÍNEA (drawGates lee model kind:"gate").

    const label = new PIXI.Text({ text: _svcName(tool.server) || tool.label || "Tool",
      style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 11, fill: PALT.labelFill,
        stroke: { color: PALT.labelStroke, width: 3 }, align: "center" } });
    label.anchor.set(0.5, 1); label.position.set(0, -40); label.visible = false; // se revela al hover/seleccionar (anti-superposición)
    const c = new PIXI.Container(); c.addChild(art, label); c.eventMode = "static"; c.cursor = "grab";
    placeLayer.addChild(c);

    const node = { kind: "tile", id: tool.id, atomKind, gated: !!tool.gated, parentId: parent ? parent.id : null,
      data: { ...tool, atom: atomKind, gridX: gx, gridY: gy, role },
      gfx: c, art, gx, gy, z: 1, layer: 7, baseY: 0, phase: Math.random() * TAU, glow: 0, glowTarget: 0, dropT: 0, color };
    c.on("pointerover", () => (node.glowTarget = 1));
    c.on("pointerout", () => (node.glowTarget = 0));
    // arrastrar = mover la pieza; clic sin mover = abrir el inspector (lo decide tileDragUp)
    c.on("pointerdown", (e) => { if (running) return; tileDrag = { node, sx: e.global.x, sy: e.global.y, moved: false }; });
    node.label = label;
    animated.push(node); placedById[tool.id] = node; occ.set(cellKey(gx, gy), tool.id);
    // [FIX-P11 · §4] el índice por IDENTIDAD se llena acá y se vacía en removeTile: si no se
    // vaciara, quitar KiCad y volver a equiparlo sería imposible (diría "ya está" sobre un
    // piso vacío) — un dedupe que no se olvida es una prohibición.
    { const _idn = identidadDeTool(tool); if (_idn && !parent) placedByIdentity.set(_idn, tool.id); }
    registerLayout(node); if (role) api_setZoneActive(role, true);
    rebuildModel(); // F2 · la pieza nueva entra al modelo (ida+eco si es tool; permanent/enables según tipo)
    return node;
  }
  function removeTile(id) {
    const n = placedById[id]; if (!n) return;
    // [FIX-P11 · §4] la identidad se libera SIEMPRE (recinto o tool): quitar una pieza tiene
    // que dejarla equipable otra vez. Sólo se borra si el dueño de la identidad es ESTA
    // pieza — si no, quitar una gemela vieja liberaría el lugar de la que quedó viva.
    { const _idn = identidadDeTool(n.data); if (_idn && placedByIdentity.get(_idn) === id) placedByIdentity.delete(_idn); }
    if (n.kind === "recinto") {                                // RECINTO: baja a sus hijos + DESELLA el footprint global
      for (const cid of n.children.slice()) removeTile(cid);
      unsealFootprint(n); gateState.delete(id); settling.delete(n);
      [animated, layoutable].forEach((arr) => { const i = arr.indexOf(n); if (i >= 0) arr.splice(i, 1); });
      if (n.hit) n.hit.destroy();                                 // sub-rama 3: la hit-area interactiva se va con el recinto
      n.gfx.destroy({ children: true }); delete placedById[id];
      rebuildModel(); return;
    }
    const occ = (n.parentId && placedById[n.parentId]) ? placedById[n.parentId].localOcc : occupancy; // hijo → occ LOCAL del padre
    occ.delete(cellKey(n.gx, n.gy)); gateState.delete(id); settling.delete(n); // F5 · freno y settle se van con la pieza
    [animated, layoutable].forEach((arr) => { const i = arr.indexOf(n); if (i >= 0) arr.splice(i, 1); });
    n.gfx.destroy({ children: true }); delete placedById[id];
    if (n.parentId && placedById[n.parentId]) { const p = placedById[n.parentId]; p.children = p.children.filter((x) => x !== id); }
    const role = n.data.role;
    if (role && !Object.values(placedById).some((m) => m.data.role === role)) api_setZoneActive(role, false);
    rebuildModel(); // F2 · el modelo refleja la baja de la pieza
  }
  const api_setZoneActive = (role, on) => (zonesByRole[role] || []).forEach((n) => (n.activeTarget = on ? 1 : 0));

  // ── ECO: el loop hecho visible (links dotted + token volviendo al núcleo) ───
  const linkGfx = new PIXI.Graphics(); linkGfx.zIndex = 5; linkGfx.eventMode = "none"; world.addChild(linkGfx);
  // F5 · capa de GATES: el candado se monta SOBRE la línea de la tool (spec §1/§2). zIndex>linkGfx
  // para dibujarse encima del cable. Es VISTA DERIVADA del modelo (kind:"gate") + del estado de freno.
  /* [FIX-P3 · §4] EL CANDADO SUBE DE CAPA. Vivía en zIndex 6 —justo encima del cable (5) y
     DEBAJO de toda pieza (30–100+)—, que alcanzaba cuando el punto caía a mitad del trayecto,
     sobre piso vacío. Ahora el candado está pegado al cable CERCA de su pieza, y ahí abajo la
     pieza se lo comería: un candado tapado es un candado que no frena nada que se vea. Sube a
     la capa que el «semáforo de la tapa» ya había demostrado que se lee siempre (400, sobre
     las etiquetas de zona a 300; los artefactos de drag siguen ganando a 99980+). */
  const gateGfx = new PIXI.Graphics(); gateGfx.zIndex = 400; gateGfx.eventMode = "none"; world.addChild(gateGfx);
  // [ticket 5 · GATE ADVISOR] capa del CANDADO FANTASMA: la compuerta SUGERIDA, dibujada en el
  // CABLE EXACTO de la tool consecuente que aún no tiene gate. Vista DERIVADA por frame (como
  // gateGfx) de n.data._advisor.sugerir && !gated — el advisor sólo PROPONE: poner el gate real
  // pasa por applyGhostGate (tap acá o botón del inspector, MISMO camino). Fantasma ≠ barrera.
  const ghostGfx = new PIXI.Graphics(); ghostGfx.zIndex = 400; ghostGfx.eventMode = "static"; ghostGfx.cursor = "pointer"; world.addChild(ghostGfx);
  let _ghostPts = [];
  function applyGhostGate(id) {
    const n = placedById[id]; if (!n) return false;
    n.gated = true; n.data.gated = true; rebuildModel();     // el gate REAL entra al modelo (kind:"gate")
    try { window.dispatchEvent(new CustomEvent("cuarto:ghostgate", {
      detail: { id, why: (n.data._advisor || {}).why || null } })); } catch (e) {}
    return true;
  }
  // [FIX-P3 · §4] estado VIVO de EL candado de cada pieza (id → "held"|"rejected"|"firme"|
  // "alerta"). Antes era el estado del «candado de la tapa», que era el SEGUNDO candado; la
  // capa `lidGfx` murió con él. El Map sobrevive porque el estado sigue siendo el mismo dato
  // —qué está frenando esta pieza— sólo que ahora lo dibuja un único candado, sobre el cable.
  const _lidStates = new Map();
  ghostGfx.on("pointertap", (e) => {
    const p = ghostGfx.toLocal(e.global);
    let hit = null, best = 18 * 18;                          // radio de gracia ~18px alrededor del candado
    for (const g of _ghostPts) { const d2 = (g.x - p.x) ** 2 + (g.y - p.y) ** 2; if (d2 < best) { best = d2; hit = g; } }
    if (hit) applyGhostGate(hit.id);
  });
  // F5 · estado de FRENO por tool (id → "held" | "rejected"); ausente = candado inerte (no frenó).
  // Lo mueven los eventos REALES del run (gate_waiting → held; OK → release; NO → rejected). NUNCA
  // muta el modelo de relaciones — sólo cómo se PINTA el gate de esa línea.
  const gateState = new Map();
  // D4 · FRONTERA VIVA · estado de RUN por recinto-agente (id → {running,held,errored,crossed}). Lo
  // MUEVEN los eventos ESTRUCTURALES REALES del padre (sub_agent_started/finished), NUNCA una animación
  // in-page sin run detrás (§7e = grift). Es el MISMO canal que gateState: sólo cambia cómo se PINTA el
  // muro/halo del recinto — jamás muta el modelo de relaciones. Se lee por api.recintoDraw().
  const recintoLive = new Map();
  // D4 · ANTI-GRIFT (run-level, modelo del PADRE) · `degraded` es la señal honesta "NO es el modelo
  // real" (fallback/OSS respondió). Lo puebla el evento cost/notice/final del run (recipe_assembler:738/
  // 769/2096). Se KEYEA en el campo `degraded`, NO en "un modelo respondió". modelFinal = lo que de
  // verdad contestó (fake-brain|claude-opus-4.8|qwen…) → se muestra HONESTO, jamás se afirma opus si es fake.
  const _antiGrift = { degraded: null, modelFinal: null };
  // PULSO+TABLERO · AURA DE ESTADO por PIEZA PLANA (kind:"tile") · id → {state,t0}. state ∈
  // {calling,held,error,done}. ESPEJO HONESTO de recintoLive (que hace lo mismo para el recinto-agente):
  // lo MUEVEN los MISMOS eventos REALES del run que ya animan el pulso — tool_call_started (calling),
  // tool_call_finished (done, o error SÓLO si el evento trae un status de falla real), gate_waiting (held).
  // Se puebla vía api.tileState desde consumeLive (id ya resuelto por la maquinaria del pulso) Y desde el
  // replay del harness (__cuartoApplyFrontierEvent) → un typo rompe AMBAS rutas. Sin evento → sin entrada →
  // SIN aura (§7e = grift si se fabricara in-page). NO muta el modelo de relaciones: sólo cómo se PINTA el
  // anillo de la pieza (cero geometría nueva). Se LIMPIA en setRunning (junto a gateState/recintoLive) para
  // no dejar auras stale entre runs.
  const tileLive = new Map();
  // CUARTO HONESTO · T2 · §3 · SEMÁFORO de VERDAD por pieza — glifo ESTÁTICO de color (id → {estado,color}),
  // SEPARADO del aura de run (tileLive): el aura late con eventos REALES del run; esto es la verdad
  // VERIFICADA del motor (probado/detectado/roto/no_configurado/premium). No pulsa. El badge accionable
  // (con botón-workflow) vive en el DOM (inspector/lista); acá sólo el color. La push cuarto.tileVerdad().
  const tileVerdad = new Map();
  const ecoTokens = []; let running = false;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // CABLES · base-de-celda: el cable nace y muere en el PISO (toScreen = centro del rombo), no a
  // medio glifo — así sale de adentro de los cubos. Núcleo y tool comparten esta base; el anillo de
  // bundling y la comba (bezier) los pone rebuildLinks. Lo que LEE estos puntos (gate F5 vía
  // gatePointOf, Eco vía pointOf, lente F4) viaja CON el cable: su lógica queda intacta, sólo baja
  // el ancla al piso → el candado sigue SOBRE la línea, el token vuelve POR el cable.
  const nucleoPoint = () => ({ x: nucleoNode.sx, y: nucleoNode.baseY });
  // RECINTO (sub-rama 2): el cable de un hijo OCULTO (colapsado) converge a la CAJA, no al hijo-fantasma
  // — "la caja habla por sus hijos" (patrón F3: re-ancla el extremo, NO toca el modelo; rebuildLinks lo
  // re-resuelve cada frame). El recinto resuelve a su centro de footprint. Una tool/núcleo normal →
  // {sx,baseY} BYTE-IDÉNTICO (sin n.hidden ni kind:"recinto" no entra a ninguna rama).
  const tileCenter = (n) => {
    if (n.kind === "recinto") return recintoCenter(n);
    if (n.hidden && n.parentId && placedById[n.parentId]) return recintoCenter(placedById[n.parentId]);
    return { x: n.sx, y: n.baseY };
  };
  function dashedLine(g, a, b, dash, gap) {
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len; let d = 0;
    while (d < len) { const s = d, e = Math.min(len, d + dash); g.moveTo(a.x + ux * s, a.y + uy * s).lineTo(a.x + ux * e, a.y + uy * e); d += dash + gap; }
  }
  // ╔══ MODELO DE RELACIONES (F2) — CONTRATO COMPARTIDO que leen F3/F4/F5 (no lo muten) ══════════╗
  // El modelo es la ÚNICA fuente de verdad de QUÉ líneas existen. Las posiciones en pantalla NO
  // definen relaciones; sólo resuelven los EXTREMOS al dibujar. Mover una pieza (F3) reubica los
  // extremos, jamás cambia el modelo. La lente (F4) y los encendidos por evento (F5) leen de acá.
  //
  //   model.pieces[]        = [{ id, type, role }]
  //       id    : "nucleo" | <id de pieza colocada>
  //       type  : "nucleo" | "tool" | "contexto" | "conexion"
  //       role  : rol de flujo SÓLO si type==="tool" ("fuentes"|"mesa"|"entrega"); si no → null
  //               (spec §1: sólo las Tools se tipan por rol)
  //
  //   model.relationships[] = combinación de:
  //       { kind:"ida",       from:"nucleo", to:<toolId> }   // el Núcleo llama a la tool (cable)
  //       { kind:"eco",       from:<toolId>, to:"nucleo" }   // la tool devuelve al Núcleo (retorno)
  //       { kind:"permanent", from:<ctxId>,  to:"nucleo" }   // Contexto: vínculo permanente (no flujo)
  //       { kind:"enables",   from:<cxId>,   to:<toolId> }   // Conexión habilita esa tool (cuelga)
  //       { kind:"gate",      on:<toolId> }                  // candado SOBRE la línea de esa tool
  //
  // INVARIANTES: cero relaciones tool↔tool; cada tool tiene EXACTAMENTE una "ida" + una "eco";
  // toda "ida"/"eco" toca el Núcleo. rebuildModel() corre al alta/baja/gate de piezas, NUNCA al
  // mover (mover sólo cambia posición). Se expone read-only por api.relationModel().
  // ╚════════════════════════════════════════════════════════════════════════════════════════════╝
  function rebuildModel() {
    workDirty = true;   // [reforma · k] cambió la estructura → el despliegue de tools se rehace
    relabelAll();       // [P5] cambió el piso → la identidad de CADA pieza se recalcula contra el resto
    const pieces = [{ id: "nucleo", type: "nucleo", role: null }];
    const rels = [];
    const placed = Object.values(placedById);
    for (const n of placed) {
      if (n.kind === "recinto") {                                // RECINTO: nodo compuesto (type:"recinto")
        pieces.push({ id: n.id, type: "recinto", role: null, hasNucleo: !!n.hasNucleo, children: n.children.slice() });
        // 2b · el SUB-AGENTE cuelga del Núcleo padre: jerarquía real de delegación (no una llamada
        // suelta). Sigue el invariante núcleo-céntrico: la relación toca el Núcleo, jamás tool↔tool.
        // Sin modo multiagente conserva el cable jerárquico previo. Declarado un
        // modo, las únicas relaciones entre Alephs salen de `plan.cables[]`.
        if (n.hasNucleo && !multi.modo) rels.push({ kind: "agente", from: n.id, to: "nucleo" });
        continue;                                                // no aporta ida/eco propio: sus hijos los aportan
      }
      const type = n.atomKind;                                   // tool | contexto | conexion
      const role = type === "tool" ? (n.data.role || "mesa") : null;
      const piece = { id: n.id, type, role };
      if (n.parentId) piece.parentId = n.parentId;               // RECINTO: el hijo apunta a su padre (modelo plano + 1 campo)
      pieces.push(piece);
      if (type === "tool") {
        rels.push({ kind: "ida", from: "nucleo", to: n.id });    // Núcleo→Tool (llamada)
        rels.push({ kind: "eco", from: n.id, to: "nucleo" });    // Tool→Núcleo (retorno = Eco)
        if (n.gated || n.data.gated) rels.push({ kind: "gate", on: n.id }); // candado sobre esa línea
      } else if (type === "contexto") {
        rels.push({ kind: "permanent", from: n.id, to: "nucleo" }); // vínculo permanente (no flujo)
      } else if (type === "memoria") {
        // 2c · memoria COMPARTIDA: permanente al Núcleo + "comparte" a cada sub-agente CONECTADO (los
        // conectados la leen/escriben — el runtime la baja como MEMORY_FILE_PATH compartido). No es flujo.
        rels.push({ kind: "permanent", from: n.id, to: "nucleo" });
        // STEP 2·B2 · la línea teal = MEMBRESÍA real (ya NO un blanket a TODO agente): sólo los
        // sub-agentes CONECTADOS al bus reciben "comparte". Membresía = flag por-pieza `sharesMemory`
        // (DEFAULT true → un Cuarto existente conserva el look de hoy; el executor lo espeja en
        // recipe.memory.members). Desconectar uno (api.setSharesMemory(id,false)) le SACA su línea
        // sin tocar las demás; projection deja de emitir su slug en members.
        for (const rn of placed) if (rn.kind === "recinto" && rn.hasNucleo && rn.data.sharesMemory !== false)
          rels.push({ kind: "comparte", from: n.id, to: rn.id });
      }
    }
    // Conexión → tools que habilita: inferido por server/connector compartido ("cuelgan de la puerta").
    for (const cx of placed) {
      if (cx.atomKind !== "conexion") continue;
      const ck = cx.data.server || cx.data.connector;
      if (!ck) continue;
      for (const n of placed) {
        if (n.atomKind !== "tool") continue;
        const tk = n.data.server || n.data.connector;
        if (tk && tk === ck) rels.push({ kind: "enables", from: cx.id, to: n.id });
      }
    }
    for (const c of multi.cables) {
      const from = agentNodeFor(c.from), to = agentNodeFor(c.to);
      if (from && to) rels.push({ kind: "agent_link", from: from.id, to: to.id, tipo: c.tipo || "entregar" });
    }
    model.pieces = pieces; model.relationships = rels;
    computeRelevance();                                           // C2 · brillo ambiente: deriva n.relevance de las señales ricas
  }
  // C2 · RELEVANCIA (doc §12: "brilla más lo más conectado"). El grado CRUDO es PLANO para tools (el
  // modelo es ESTRELLA: toda tool tiene grado 2 al Núcleo) → la relevancia se DERIVA de las señales
  // ricas que SÍ varían: un recinto por su nº de hijos, una conexión por su fan-out de `enables` (tools
  // que habilita). Se normaliza 0..1 (suave) y la leen drawRecintos (muro/halo) y tickTile (tint). El
  // Núcleo ya manda como hub (tickNucleo, no se toca) y NO está en placedById → no recibe relevancia.
  // Una tool suelta queda en 0 (honesto: el grado es plano; no se inventa brillo).
  function computeRelevance() {
    const enablesCount = {};
    for (const r of model.relationships) if (r.kind === "enables") enablesCount[r.from] = (enablesCount[r.from] || 0) + 1;
    for (const n of Object.values(placedById)) {
      let raw = 0;
      if (n.kind === "recinto") raw = n.children ? n.children.length : 0;      // agente/cajón: más sub-piezas = más relevante
      else if (n.atomKind === "conexion") raw = enablesCount[n.id] || 0;        // conexión: cuántas tools habilita (fan-out)
      n.relevance = Math.min(1, raw / 5);                                       // normalizado suave (≈5 hijos/tools = tope)
    }
  }
  // punto en pantalla (cámara-aware) de una pieza del modelo — resuelve los EXTREMOS al dibujar.
  const pointOf = (id) => id === "nucleo" ? nucleoPoint() : (placedById[id] ? tileCenter(placedById[id]) : null);
  // P3-CIERRE · DUEÑO, NO HUB FIJO. Hoy la relación `ida` hace dueño al Núcleo; mañana puede
  // hacer dueño a un agente. El ancla del candado se declara una sola vez como el
  // «cable de la pieza a su DUEÑO» y nunca con un nombre de dueño concreto.
  function duenoDePieza(pieceId) {
    const rel = model.relationships.find((r) => r.kind === "ida" && r.to === pieceId);
    return rel ? rel.from : null;
  }
  function cablePiezaADueno(pieceId) {
    const duenoId = duenoDePieza(pieceId);
    const dueno = duenoId ? pointOf(duenoId) : null;
    const pieza = pointOf(pieceId);
    if (!dueno || !pieza) return null;
    const dx = pieza.x - dueno.x, dy = pieza.y - dueno.y, L = Math.hypot(dx, dy) || 1;
    const inicio = { x: dueno.x + (dx / L) * CABLE_RING,
                     y: dueno.y + (dy / L) * CABLE_RING };
    const control = combaCtrl(inicio, pieza);
    const en = (t) => { const u = 1 - t;
      return { x: u * u * inicio.x + 2 * u * t * control.x + t * t * pieza.x,
               y: u * u * inicio.y + 2 * u * t * control.y + t * t * pieza.y }; };
    return { duenoId, dueno, pieza, inicio, control, en };
  }
  /* ══ [FIX-P3 · §4] EL CANDADO, VERSIÓN FINAL (sellada 26-jul) ═══════════════════════════
   * Tres posiciones tuvo esto y las tres estuvieron mal por el mismo motivo: el candado NO
   * pertenecía a nada.
   *   1. sobre el ícono de la pieza  → tapaba el glifo, y decía «la pieza está cerrada»
   *      cuando lo que se frena es lo que la pieza HACE.
   *   2. a GATE_T del segmento RECTO Núcleo→pieza → quedaba encima de la curva del cable
   *      pero no SOBRE ella: flotando a un costado, custodiando aire (FU-1).
   *   3. [reforma · j] en el hombro de la pieza → dejó de flotar sobre el cable… y pasó a
   *      flotar al lado de la pieza. Y como el «candado-semáforo de la tapa» seguía vivo en
   *      su propia esquina, en las capturas se veían DOS CANDADOS SUELTOS por pieza.
   *
   * La versión sellada: UNO por pieza, PEGADO AL CABLE que va de la pieza a su DUEÑO — que es
   * literalmente por donde pasa lo que esa pieza hace, y por lo tanto donde se frena. El
   * punto se evalúa sobre la MISMA bezier que dibuja `drawCable` (mismo arranque en el
   * anillo, mismo punto de control de la comba), así que está SOBRE la curva, no cerca: si
   * la comba cambia, el candado se mueve con ella. Cerca de la pieza (t alto) para que se lea
   * de quién es. `a`/`b` se conservan porque el hit-test y el tramo frenado los usan. */
  /* DÓNDE sobre el cable: a GATE_ATRAS px de la pieza, medidos SOBRE LA CURVA hacia atrás.
   * Una fracción fija del trayecto (t = 0.6, t = 0.78…) no sirve: con la pieza lejos el
   * candado queda flotando en medio del piso, y con la pieza cerca queda debajo del propio
   * disco de la pieza — que es la otra forma de no pertenecer a nada. La distancia fija lo
   * pone SIEMPRE en el mismo lugar relativo: justo antes de que el cable entre a la pieza.
   * El clamp evita los dos extremos (cable cortísimo → no se mete en el Núcleo). */
  const GATE_ATRAS = 34, GATE_T_MIN = 0.28, GATE_T_MAX = 0.86;
  function gatePointOf(toolId) {
    const cable = cablePiezaADueno(toolId);
    if (!cable) return null;
    // recorre la curva desde la pieza hacia atrás hasta juntar GATE_ATRAS px de arco
    let t = GATE_T_MAX, acc = 0, prev = cable.en(1);
    for (let i = 1; i <= 40; i++) {
      const tt = 1 - i / 40, q = cable.en(tt);
      acc += Math.hypot(q.x - prev.x, q.y - prev.y); prev = q;
      if (acc >= GATE_ATRAS) { t = tt; break; }
    }
    t = Math.max(GATE_T_MIN, Math.min(GATE_T_MAX, t));
    const p = cable.en(t);
    return { x: p.x, y: p.y, a: cable.inicio, b: cable.pieza, c: cable.control,
             dueno: cable.dueno, duenoId: cable.duenoId, en: cable.en, t };
  }
  /* ¿ESTA pieza toca afuera? El candado sólo existe sobre lo que SALE al mundo (mandar,
   * pagar, publicar, escribir). Una pieza de pura lectura no lleva candado NI se le ofrece:
   * no hay nada que frenar, y un candado sobre una lectura promete una protección falsa.
   * Gemelo exacto de `tocaAfuera()` en el chrome — la UI y el diorama no pueden discrepar
   * sobre si una pieza tiene candado o no. SIN DATO ⇒ NO: es una afirmación, y una
   * afirmación sin evidencia no se dibuja. */
  function tocaAfueraN(n) {
    if (!n) return false;
    // GEMELO EXACTO de `tocaAfuera()` en el chrome, primera rama incluida: una pieza YA
    // asegurada es, por definición, una que toca afuera — la decisión se tomó. Sin esta
    // rama el diorama no dibujaba el candado de una pieza gateada que todavía no tenía
    // clasificación del advisor: el chrome ofrecía [Ver el candado] y el cable no mostraba
    // ninguno. Dos predicados que discrepan sobre el mismo hecho es peor que uno flojo.
    if (n.gated || (n.data && n.data.gated)) return true;
    const adv = n.data && n.data._advisor;
    if (!adv) return false;
    return !!(adv.sugerir || adv.piso || (adv.clases || []).length);
  }

  // ── CABLES · FORMA FINAL (geometría + estilo) ────────────────────────────────
  // Decisión de diseño FIRME: el cable vive SIEMPRE en la capa plana entre el piso y las piezas
  // (linkGfx.zIndex=5 < toda pieza ≥6/7) → NO hay profundidad por-segmento, el cable nunca pasa por
  // delante ni tapa un glifo. Forma: base→base, comba (bezier con el medio levantado sobre el piso),
  // color por ROL DEL DESTINO, foco al hover, bundling en un anillo del Núcleo, y fade suave.
  const CABLE_RING = 15;                                   // anillo de salida del Núcleo (bundling)
  const ROLE_COLOR = { fuentes: ZONE_DEF.fuentes.color, mesa: ZONE_DEF.mesa.color, entrega: ZONE_DEF.entrega.color };
  const ROLE_GLOW  = { fuentes: ZONE_DEF.fuentes.glow,  mesa: ZONE_DEF.mesa.glow,  entrega: ZONE_DEF.entrega.glow };
  // fade por-cable: { appear (aparición 0→1), focus (0→1 al enfocarse) } animados con approach.
  const linkFx = new Map();
  const cableFx = (key) => { let f = linkFx.get(key); if (!f) linkFx.set(key, f = { appear: 0, focus: 0 }); return f; };
  // comba: punto de control del bezier = medio del tramo LEVANTADO (−y) sobre el piso. La altura
  // escala con la distancia (clamp) → tramos cortos comban poco, largos un arco mayor, nunca recto.
  const combaCtrl = (a, b) => { const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    return { x: mx, y: my - Math.max(14, Math.min(64, Math.hypot(b.x - a.x, b.y - a.y) * 0.2)) }; };
  const quadPts = (a, c, b, n = 14) => { const p = []; for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t; p.push({ x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y }); } return p; };
  // dash a lo largo de una polilínea (la comba muestreada) con fase continua entre segmentos.
  function dashedPath(g, pts, dash, gap) {
    let acc = 0; const period = dash + gap;
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], seg = Math.hypot(b.x - a.x, b.y - a.y); if (!seg) continue;
      const ux = (b.x - a.x) / seg, uy = (b.y - a.y) / seg; let d = 0;
      while (d < seg) { const phase = acc % period;
        if (phase < dash) { const r = Math.min(dash - phase, seg - d); g.moveTo(a.x + ux * d, a.y + uy * d).lineTo(a.x + ux * (d + r), a.y + uy * (d + r)); d += r; acc += r; }
        else { const r = Math.min(period - phase, seg - d); d += r; acc += r; }
      }
    }
  }

  // F2 · las líneas SE DERIVAN DEL MODELO (no de iterar posiciones). Corre cada tick: re-resuelve
  // los extremos (posición viva) pero el CONJUNTO de líneas lo manda model.relationships.
  function rebuildLinks(t = 0) {
    linkGfx.clear();
    multi.visualCables = [];
    const nb = nucleoPoint();                              // base del Núcleo (piso)
    // FOCO: la pieza con más glow (hover/seleccion/run) manda; su cable va al 100% + grueso, el resto
    // cae a ~25%. Leo el glow VIVO (no muto nada) → el foco entra y sale con su propio fade.
    let focusGlow = 0, focusId = null;
    for (const id in placedById) { const g = placedById[id].glow; if (g > focusGlow) { focusGlow = g; focusId = id; } }
    const anyFocus = focusGlow > 0.5;
    const seen = new Set();
    // dibuja UN cable combado (base→base), con fade/foco por-cable. `lit` = es el cable enfocado.
    const drawCable = (key, a, b, baseCol, glowCol, lit, o) => {
      seen.add(key);
      const fx = cableFx(key);
      fx.appear = approach(fx.appear, 1, 0.12);
      fx.focus  = approach(fx.focus, lit ? 1 : 0, 0.16);
      const dim = anyFocus ? (0.25 + 0.75 * fx.focus) : 1; // sin-foco → 25%; el enfocado → 100%
      const alpha = Math.min(1, (o.alpha + 0.3 * fx.focus) * fx.appear * dim);
      const width = o.width + 1.5 * fx.focus;
      const col = mix(baseCol, glowCol, 0.3 + 0.7 * fx.focus);
      const ctrl = combaCtrl(a, b);
      if (o.dashed) { dashedPath(linkGfx, quadPts(a, ctrl, b), o.dash, o.gap); linkGfx.stroke({ color: col, width, alpha }); }
      else { linkGfx.moveTo(a.x, a.y).quadraticCurveTo(ctrl.x, ctrl.y, b.x, b.y).stroke({ color: col, width, alpha }); }
    };
    // 1) cables de flujo Núcleo→Tool (una "ida" por tool). Color por ROL DEL DESTINO. El anillo
    //    reparte la salida del Núcleo por ángulo (no todas del mismo punto). El Eco vuelve por aquí.
    //    F5 · si la tool está FRENADA (gateState==="held"), el flujo se ENERGIZA hasta el candado y se
    //    APAGA después: el cable LITERALMENTE para en el gate (spec §2 paso 4) — tratamiento intacto.
    const heldIda = [];
    for (const rel of model.relationships) if (rel.kind === "ida") {
      const tn = placedById[rel.to], cable = cablePiezaADueno(rel.to);
      if (!tn || !cable) continue;
      const a = cable.inicio, b = cable.pieza;
      if (gateState.get(rel.to) === "held") { heldIda.push({ a, b, id: rel.to }); continue; }
      const role = tn.data.role || "mesa";
      drawCable("ida:" + rel.to, a, b, ROLE_COLOR[role] || ECO_COLOR, ROLE_GLOW[role] || ECO_COLOR,
                anyFocus && focusId === rel.to, { alpha: 0.62, width: 1.9 });
    }
    if (heldIda.length) {
      // Los dos tramos conservan la MISMA Bézier del cable entero. Dibujarlos como rectas
      // dejaba el candado sobre la curva matemática pero flotando respecto del cable VISIBLE.
      const tramo = (gp, desde, hasta, pasos = 18) =>
        Array.from({ length: pasos + 1 }, (_, i) => gp.en(desde + (hasta - desde) * i / pasos));
      // tramo gate→tool: tenue (el flujo NO pasó el candado)
      for (const h of heldIda) {
        const gp = gatePointOf(h.id);
        if (gp) dashedPath(linkGfx, tramo(gp, gp.t, 1), 7, 5);
      }
      linkGfx.stroke({ color: 0x6b4a2a, width: 1.2, alpha: 0.28 });
      // tramo dueño→gate: vivo y pulsante (el flujo llegó hasta acá y frena)
      for (const h of heldIda) {
        const gp = gatePointOf(h.id);
        if (gp) dashedPath(linkGfx, tramo(gp, 0, gp.t), 6, 4);
      }
      linkGfx.stroke({ color: ATOM_COLOR.gate, width: 2.4, alpha: 0.7 + 0.3 * Math.sin(t * 6) });
    }
    // 2) Contexto: vínculo permanente al Núcleo (tenue, dashed fino — no es flujo).
    //    Memoria COMPARTIDA es un contexto especial: cyan sólido y prominente (paridad frames 30-36
    //    de 1v.mp4 — la línea Memory→Núcleo se ve tan viva como las que van a cada agente).
    for (const rel of model.relationships) if (rel.kind === "permanent") {
      const cn = placedById[rel.from]; if (!cn) continue;
      const isMem = cn.atomKind === "memoria";
      drawCable("perm:" + rel.from, tileCenter(cn), nb, isMem ? ATOM_COLOR.memoria : ATOM_COLOR.contexto, isMem ? 0x9af0ff : 0xffd0ec,
                anyFocus && focusId === rel.from, isMem ? { alpha: 0.68, width: 1.8 } : { alpha: 0.42, width: 1.2, dashed: true, dash: 2, gap: 4 });
    }
    // 3) Conexión → tools que habilita ("cuelgan de la puerta"; no toca el Núcleo, no es flujo).
    for (const rel of model.relationships) if (rel.kind === "enables") {
      const cn = placedById[rel.from], tn = placedById[rel.to]; if (!cn || !tn) continue;
      drawCable("enab:" + rel.from + ">" + rel.to, tileCenter(cn), tileCenter(tn), ATOM_COLOR.conexion, 0x8af0e6,
                anyFocus && (focusId === rel.from || focusId === rel.to), { alpha: 0.38, width: 1, dashed: true, dash: 3, gap: 6 });
    }
    // 3b) 2c · MEMORIA→SUB-AGENTE ("comparte"): cyan sólido y prominente — no es flujo ida/eco, pero
    // en el reel (frames 30-36) se ve tan vívido como el resto del fan-out; NO va tenue/punteado.
    for (const rel of model.relationships) if (rel.kind === "comparte") {
      const mn = placedById[rel.from], rn = placedById[rel.to]; if (!mn || !rn) continue;
      drawCable("comp:" + rel.from + ">" + rel.to, tileCenter(mn), recintoCenter(rn), ATOM_COLOR.memoria, 0x9af0ff,
                anyFocus && (focusId === rel.from || focusId === rel.to), { alpha: 0.68, width: 1.8 });
    }
    // 4) 2b · CABLE-AGENTE: el sub-agente (recinto con Núcleo propio) cuelga del Núcleo padre.
    //    Más grueso que el cable de una tool — es JERARQUÍA (delegación), y el eco de una
    //    delegación REAL viaja por acá (consumeLive → ecoFire/ecoReturn con el id del recinto).
    for (const rel of model.relationships) if (rel.kind === "agente") {
      const rn = placedById[rel.from]; if (!rn) continue;
      drawCable("agent:" + rel.from, recintoCenter(rn), nb, ZONE_DEF.nucleo.color, ZONE_DEF.nucleo.glow,
                anyFocus && focusId === rel.from, { alpha: 0.5, width: 2.6 });
    }
    // F2 · cables tipados por FORMA. `entregar` termina en una sola flecha.
    // `delegar` suma el eco punteado y una flecha de vuelta; no hay labels que
    // obliguen a leer para distinguirlos.
    const arrowAt = (tip, from, color) => {
      const ang = Math.atan2(tip.y - from.y, tip.x - from.x), len = 9, wing = 4.8;
      const bx = tip.x - Math.cos(ang) * len, by = tip.y - Math.sin(ang) * len;
      linkGfx.poly([tip.x, tip.y,
        bx + Math.cos(ang + Math.PI / 2) * wing, by + Math.sin(ang + Math.PI / 2) * wing,
        bx + Math.cos(ang - Math.PI / 2) * wing, by + Math.sin(ang - Math.PI / 2) * wing])
        .fill({ color, alpha: 0.92 });
    };
    for (const rel of model.relationships) if (rel.kind === "agent_link") {
      const aNode = placedById[rel.from], bNode = placedById[rel.to];
      if (!aNode || !bNode) continue;
      const a = recintoCenter(aNode), b = recintoCenter(bNode);
      const lit = anyFocus && (focusId === rel.from || focusId === rel.to);
      drawCable("multi:" + rel.from + ">" + rel.to, a, b, ZONE_DEF.nucleo.color, ZONE_DEF.nucleo.glow,
        lit, { alpha: 0.78, width: 2.4 });
      const ctrl = combaCtrl(a, b);
      arrowAt(b, ctrl, ZONE_DEF.nucleo.glow);                    // entregar-y-suelta: UNA punta
      const visual = { from: rel.from, to: rel.to, tipo: rel.tipo || "entregar",
        arrows: 1, echo: false };
      if (rel.tipo === "delegar") {
        drawCable("multi-eco:" + rel.to + ">" + rel.from, b, a, ECO_COLOR, 0xa8fff0,
          lit, { alpha: 0.62, width: 1.5, dashed: true, dash: 4, gap: 5 });
        const backCtrl = combaCtrl(b, a);
        arrowAt(a, backCtrl, 0xa8fff0);                           // ida y eco
        visual.arrows = 2; visual.echo = true;
      }
      multi.visualCables.push(visual);
    }
    // poda el fade de cables que ya no existen (sin fuga de estado ni foco viejo).
    for (const k of linkFx.keys()) if (!seen.has(k)) linkFx.delete(k);
  }
  /* ══ [FIX-P3 · §4] EL CANDADO — UNO POR PIEZA, SOBRE SU CABLE ══════════════════════════
   * Antes acá se dibujaban DOS candados por pieza, en dos lugares y con dos vocabularios:
   *   · el GATE (gateGfx) / el FANTASMA del advisor (ghostGfx) sobre `gatePointOf`, y
   *   · el «candado-semáforo de la TAPA» (lidGfx) en la esquina del glifo.
   * La doctrina que los justificaba —«contención ≠ permiso: la tapa REPORTA, el cable
   * PERMITE»— es verdadera y aun así se veía mal: dos candados sueltos por pieza, uno de
   * ellos custodiando una esquina. Un candado es una promesa de que algo se frena; dos
   * promesas del mismo hecho es ruido, y el ojo no sabe cuál mirar.
   *
   * La versión sellada (26-jul) es UNO por pieza, pegado a su cable al Núcleo, con UN
   * vocabulario de estados que absorbe lo que decían los dos:
   *   held     → rojo que pulsa + anillo «stop»   (el run está frenado ACÁ, ahora)
   *   rejected → tenue y tachado                  (se rechazó el permiso)
   *   firme    → cerrado, ámbar del gate          (candado puesto, o piso del sistema)
   *   alerta   → arco DESENCAJADO, respirando     (el advisor lo propone; todavía no está)
   *   —        → nada                             (la pieza sólo lee: nada que frenar)
   * El estado se DERIVA por frame y jamás muta el modelo. `_lidStates` conserva su nombre
   * porque es lo que lee `api.lidLock`, pero ahora describe EL candado, no una tapa. */
  function drawGates(t = 0) {
    gateGfx.clear(); ghostGfx.clear();
    _ghostPts = []; _lidStates.clear();
    // el universo de piezas a mirar: las del modelo (gate real), las frenadas por el run, y
    // las colocadas (que pueden tener una sugerencia viva del advisor).
    const ids = new Set();
    for (const rel of model.relationships) if (rel.kind === "gate") ids.add(rel.on);
    for (const id of gateState.keys()) ids.add(id);
    for (const n of Object.values(placedById)) if (n.atomKind === "tool" && !n.hidden) ids.add(n.id);
    for (const id of ids) {
      const n = placedById[id]; if (!n || n.hidden) continue;
      const state = gateState.get(id);
      const gated = !!(n.gated || n.data.gated);
      const adv = n.data._advisor;
      // ¿toca afuera? Si no, no hay candado — ni puesto, ni propuesto. Un gate declarado
      // sobre una pieza de pura lectura tampoco se dibuja: sería un candado sobre aire.
      // (Las frenadas por un run REAL se dibujan igual: si el motor frenó ahí, tocó afuera.)
      if (!state && !tocaAfueraN(n)) continue;
      let est = null;
      if (state === "held") est = "held";
      else if (state === "rejected") est = "rejected";
      else if (gated || (adv && adv.piso)) est = "firme";
      else if (adv && adv.sugerir) est = "alerta";
      if (!est) continue;
      const gp = gatePointOf(id); if (!gp) continue;
      _lidStates.set(id, est);
      // el candado ALERTA es el que todavía se puede aceptar de un toque: va al hit-test.
      if (est === "alerta") _ghostPts.push({ id, x: gp.x, y: gp.y });
      // El fantasma vive en su capa (ghostGfx, más atrás) y el candado real en la suya: son
      // el MISMO candado en dos momentos, y nunca se dibujan los dos — `est` es uno solo.
      const g = est === "alerta" ? ghostGfx : gateGfx;
      const held = est === "held", rejected = est === "rejected", alerta = est === "alerta";
      const pulse = held ? 0.5 + 0.5 * Math.sin(t * 6) : 0;
      const breathe = alerta ? 0.5 + 0.5 * Math.sin(t * 2.2 + (n.phase || 0)) : 0;
      const col = held ? 0xff5a4d : rejected ? 0x7a4a4a : ATOM_COLOR.gate;
      const bw = 7, bh = 6, by = gp.y + 1;
      if (held) g.circle(gp.x, gp.y, 12 + pulse * 5).stroke({ color: 0xff5a4d, width: 2, alpha: 0.3 + pulse * 0.45 });
      if (alerta) {
        // halo respirando (y zona clickeable): se ve PROPUESTA, no barrera.
        g.circle(gp.x, gp.y, 11).fill({ color: ATOM_COLOR.gate, alpha: 0.05 + 0.05 * breathe });
        g.circle(gp.x, gp.y, 9 + breathe * 2.5).stroke({ color: ATOM_COLOR.gate, width: 1.2, alpha: 0.22 + 0.28 * breathe });
      } else {
        // pastilla para leerse sobre el cable y sobre cualquier fondo del piso
        g.circle(gp.x, gp.y, 8.5).fill({ color: col, alpha: held ? 0.22 + pulse * 0.2 : 0.13 });
      }
      // el arc() CONTINÚA el path actual (semántica canvas): sin el moveTo al punto de
      // arranque del arco, el candado anterior se conecta con éste → línea stray cruzando
      // la escena. Pasó, y por eso el idiom se repite igual en las dos ramas.
      if (alerta) {
        // arco DESENCAJADO (corrido a la derecha) = candado todavía ABIERTO, aún sin poner.
        g.moveTo(gp.x + 2.5 - 3, by - bh / 2 - 0.5)
         .arc(gp.x + 2.5, by - bh / 2 - 0.5, 3, Math.PI, 0).stroke({ color: ATOM_COLOR.gate, width: 1.2, alpha: 0.55 + 0.2 * breathe });
        g.roundRect(gp.x - bw / 2, by - bh / 2, bw, bh, 1.6).fill({ color: 0x0a0d13, alpha: 0.01 })
         .stroke({ color: ATOM_COLOR.gate, width: 1.2, alpha: 0.55 + 0.25 * breathe });
      } else {
        g.moveTo(gp.x - 3, by - bh / 2 - 0.5)
         .arc(gp.x, by - bh / 2 - 0.5, 3, Math.PI, 0).stroke({ color: held ? 0xffd6c8 : 0xffe6b0, width: 1.6, alpha: 0.9 });
        g.roundRect(gp.x - bw / 2, by - bh / 2, bw, bh, 1.6)
         .fill({ color: col, alpha: held ? 1 : 0.85 }).stroke({ color: 0x2a1c0a, width: 0.8, alpha: 0.55 });
      }
      if (rejected) g.moveTo(gp.x - 4.5, gp.y - 4.5).lineTo(gp.x + 4.5, gp.y + 4.5)
        .moveTo(gp.x + 4.5, gp.y - 4.5).lineTo(gp.x - 4.5, gp.y + 4.5).stroke({ color: 0xff9a9a, width: 1.4, alpha: 0.8 });
      try { g.beginPath(); } catch (_) {}      // corta el path entre candados (anti-stray)
    }
  }
  // El pulso del RUN viaja por estos tokens. `opts` da el LOOK por dirección (ida = energía del Núcleo
  // saliendo; eco = respuesta de la tool volviendo). Sin opts → look del Eco (byte-idéntico a antes).
  function spawnToken(from, to, dur, opts = {}) {
    return new Promise((resolve) => {
      const core = opts.core ?? 0x9af7e6, ring = opts.ring ?? ECO_COLOR;
      const g = new PIXI.Graphics();
      g.circle(0, 0, 5).fill({ color: core }).circle(0, 0, 9).stroke({ color: ring, width: 2, alpha: 0.6 });
      g.zIndex = 99995; g.eventMode = "none"; g.position.set(from.x, from.y); world.addChild(g);
      ecoTokens.push({ g, from, to, t: 0, dur, resolve });
    });
  }
  // PULSO · look del destello de IDA (Núcleo→tool): la energía del Núcleo (violeta) saliendo a llamar la tool.
  const IDA_CORE = 0xd8c8ff, IDA_RING = 0xb389ff, IDA_DUR = 460;
  // PULSO+TABLERO · paleta del AURA por estado — REUSA las familias de color YA vivas en el diorama, un
  // tono por estado, cero colores nuevos: calling=violeta del destello de IDA (Núcleo→tool); done=teal del
  // ECO (la tool volvió); held=ámbar del gate (mismo 0xffb454 del muro-espera); error=rojo del muro-error
  // (mismo 0xff6b5e). Es la MISMA semántica cromática que drawRecintos usa para el recinto-agente.
  const AURA_STATE = {
    calling: { core: IDA_CORE, ring: IDA_RING },   // violeta — llamada en vuelo
    done:    { core: 0x9af7e6, ring: ECO_COLOR },  // teal — asentada OK
    held:    { core: 0xffd9a0, ring: 0xffb454 },   // ámbar — frenada en el gate (espera tu OK)
    error:   { core: 0xffb0a8, ring: 0xff6b5e },   // rojo — terminó con status de falla real
  };
  const _ecoLog = [];   // registro READ-ONLY de destellos disparados {tileId, dir, dur} — SÓLO para verify; no dibuja nada.
  const setRunning = (on) => { running = !!on; if (api) api.running = !!on; if (on) { gateState.clear(); _ecoLog.length = 0; recintoLive.clear(); tileLive.clear(); _antiGrift.degraded = null; _antiGrift.modelFinal = null; } }; // F5 · arranca sin frenos (ni log) viejos · D4 · ni frontera viva vieja · PULSO+TABLERO · ni auras de estado viejas
  const ecoFire = (tileId) => { const n = placedById[tileId]; if (!n) return; n.glowTarget = 1; n.glow = 1.5; if (n.data.role) api_setZoneActive(n.data.role, true); };
  // PULSO·A · el destello de IDA: espejo de ecoReturn al revés — un token que VIAJA del Núcleo a la tool
  // (relación "ida" del modelo). ANTI-GRIFT/F5: NO sale sobre una tool FRENADA (el flujo para en el candado,
  // no lo cruza). El glow lo pone ecoFire aparte; esto es sólo el destello viajero.
  const ecoFireSpark = (tileId) => {
    const n = placedById[tileId]; if (!n) return Promise.resolve();
    if (gateState.get(tileId) === "held") return Promise.resolve();   // tile frenado → sin ida (no cruza el gate)
    // 2b · DELEGACIÓN: si el destino es un recinto-AGENTE, la ida viaja por el CABLE-AGENTE
    // (Núcleo→sub-agente, relación kind:"agente"), no por una ida de tool que no existe.
    if (n.kind === "recinto" && n.hasNucleo) {
      const from = nucleoPoint(), to = recintoCenter(n);
      _ecoLog.push({ tileId, dir: "ida", dur: IDA_DUR, from: { x: from.x, y: from.y }, to: { x: to.x, y: to.y } });
      return spawnToken(from, to, IDA_DUR, { core: IDA_CORE, ring: IDA_RING }).then(() => { n.glowTarget = 1; n.glow = 1.6; });
    }
    const rel = model.relationships.find((r) => r.kind === "ida" && r.to === tileId);
    const from = (rel && pointOf(rel.from)) || nucleoPoint();
    const to = (rel && pointOf(rel.to)) || tileCenter(n);
    _ecoLog.push({ tileId, dir: "ida", dur: IDA_DUR, from: { x: from.x, y: from.y }, to: { x: to.x, y: to.y } });
    return spawnToken(from, to, IDA_DUR, { core: IDA_CORE, ring: IDA_RING }).then(() => { n.glowTarget = 1; n.glow = 1.6; });
  };
  // PULSO·C · la duración del ECO refleja la latencia REAL de la tool (wall_s del evento finished),
  // clampada a un rango legible: una tool muy lenta no hace un destello eterno ni una muy rápida uno
  // invisible. Sin wall_s (cosmético/playEco) → la duración fija de antes. El RITMO entre tools ya lo
  // da el orden real de los eventos; esto suma la DURACIÓN real de cada uno.
  const ECO_DUR_MIN = 200, ECO_DUR_MAX = 2000, ECO_DUR_DEFAULT = 520;
  const ecoDur = (wall_s) => {
    if (typeof wall_s !== "number" || !isFinite(wall_s) || wall_s <= 0) return ECO_DUR_DEFAULT;
    return Math.max(ECO_DUR_MIN, Math.min(ECO_DUR_MAX, wall_s * 1000));
  };
  // F2 · el retorno se DIBUJA DESDE EL MODELO: usa la relación "eco" (tool→núcleo) de esa tool.
  const ecoReturn = (tileId, wall_s) => {
    const rn = placedById[tileId];
    // 2b · DELEGACIÓN: el eco de un sub-agente vuelve por el cable-agente (sub-agente→Núcleo,
    // "el hijo reporta al padre" del canon del video) con la duración real del wall_s.
    if (rn && rn.kind === "recinto" && rn.hasNucleo) {
      const from = recintoCenter(rn), to = nucleoPoint(), dur = ecoDur(wall_s);
      _ecoLog.push({ tileId, dir: "eco", dur, from: { x: from.x, y: from.y }, to: { x: to.x, y: to.y } });
      return spawnToken(from, to, dur).then(() => { nucleoNode.glow = 1.4; rn.glowTarget = 0; });
    }
    const rel = model.relationships.find((r) => r.kind === "eco" && r.from === tileId);
    const from = (rel && pointOf(rel.from)) || (placedById[tileId] ? tileCenter(placedById[tileId]) : nucleoPoint());
    const to = (rel && pointOf(rel.to)) || nucleoPoint();
    const dur = ecoDur(wall_s);
    _ecoLog.push({ tileId, dir: "eco", dur, from: { x: from.x, y: from.y }, to: { x: to.x, y: to.y } });
    return spawnToken(from, to, dur).then(() => { nucleoNode.glow = 1.4; const n = placedById[tileId]; if (n) n.glowTarget = 0; });
  };
  async function ecoFinal() { nucleoNode.glow = 1.9; zoneNodes.forEach((z) => (z.glowTarget = 1)); await sleep(480); zoneNodes.forEach((z) => (z.glowTarget = 0)); }
  // F2 · recorre las tools DEL MODELO (ida → Eco por cada una). El caller de producción es el RUN
  // (cuarto.pixi.html → consumeLive): mapea eventos SSE reales a ecoFire/ecoReturn por tool. playEco
  // es el MISMO recorrido disparable a mano (demo/verificación), sourced del modelo.
  async function playEco(order) {
    if (running) return;
    const ids = (order && order.length) ? order.filter((id) => placedById[id])
      : model.relationships.filter((r) => r.kind === "ida").map((r) => r.to);
    if (!ids.length) return;
    setRunning(true);
    for (const id of ids) { ecoFire(id); await sleep(260); await ecoReturn(id); await sleep(150); }
    await ecoFinal(); setRunning(false);
  }
  const stopEco = () => { setRunning(false); ecoTokens.splice(0).forEach((k) => { k.g.destroy(); k.resolve && k.resolve(); }); };

  // ── MULTIAGENTE F2 · consumo del plan sellado (cero motor) ───────────────
  const agentSlug = (ref) => String(ref || "").split("/").pop().replace(/\.config\.json$|\.json$/, "");
  function agentNodeFor(key) {
    return Object.values(placedById).find((n) => n.kind === "recinto" && n.hasNucleo &&
      (n.id === key || n.data.agent_ref === key || agentSlug(n.data.agent_ref) === key)) || null;
  }
  function localCableCheck(fromId, toId, tipo) {
    if (!multi.restriction || multi.modo !== "cadena") return { ok: true };
    const from = agentNodeFor(fromId), to = agentNodeFor(toId);
    const a = from ? agentSlug(from.data.agent_ref) : String(fromId);
    const b = to ? agentSlug(to.data.agent_ref) : String(toId);
    if (a === b) return { ok: false, cause: "cadena_ciclo", message: "una cadena no admite bucles", beforePlan: true };
    if (tipo === "delegar") return { ok: false, cause: "cadena_tipo",
      message: "cadena sólo admite entregar-y-suelta", beforePlan: true };
    if (multi.cables.some((c) => c.from === b && c.to === a))
      return { ok: false, cause: "cadena_ciclo", message: "una cadena no admite A↔B", beforePlan: true };
    if (multi.cables.some((c) => c.from === a || c.to === b))
      return { ok: false, cause: "cadena_bifurcacion", message: "una cadena no admite bifurcaciones", beforePlan: true };
    return { ok: true, from: a, to: b, tipo: tipo || "entregar" };
  }
  async function requestAgentCable(fromId, toId, tipo = "entregar") {
    const local = localCableCheck(fromId, toId, tipo);
    if (!local.ok) { try { onMultiNotice(local); } catch (_) {} return local; }
    const from = agentNodeFor(fromId), to = agentNodeFor(toId);
    if (!from || !to) return { ok: false, cause: "aleph_no_existe", message: "Elige dos Alephs del lienzo" };
    const cable = { from: agentSlug(from.data.agent_ref), to: agentSlug(to.data.agent_ref), tipo };
    const candidate = multi.cables.concat(cable);
    let verdict;
    try { verdict = await onMultiCableIntent({ cable, cables: candidate, modo: multi.modo }); }
    catch (error) { verdict = { ok: false, cause: "plan_no_disponible", message: String(error && error.message || error) }; }
    if (verdict && verdict.ok) {
      multi.cables = (verdict.plan && verdict.plan.cables) ? verdict.plan.cables.slice() : candidate;
      if (verdict.plan) applyMultiPlan(verdict.plan, verdict.piezas_aleph || multi.piezas);
      else rebuildModel();
    } else if (verdict) {
      try { onMultiNotice(verdict); } catch (_) {}
    }
    return verdict || { ok: false, cause: "plan_sin_respuesta" };
  }
  function applyMultiPlan(plan, piezas) {
    multi.plan = plan || null;
    multi.modo = (plan && plan.modo) || multi.modo;
    multi.piezas = Array.isArray(piezas) ? piezas.slice() : multi.piezas;
    multi.cables = plan && Array.isArray(plan.cables) ? plan.cables.slice() : [];
    nucleoNode.data._multiModo = multi.modo || null;
    nucleoNode.data._agentLinks = multi.cables.map((c) => ({ from: c.from, to: c.to, tipo: c.tipo || "entregar" }));
    const eslabones = plan && Array.isArray(plan.eslabones) ? plan.eslabones : [];
    Object.values(placedById).forEach((n) => {
      if (n.kind !== "recinto" || !n.hasNucleo) return;
      const e = eslabones.find((x) => x.agent_ref === n.data.agent_ref || x.slug === agentSlug(n.data.agent_ref));
      n.nucleoDerived = e ? e.nucleo !== false : true;          // LEÍDO del /plan; nunca calculado
      if (n.coreArt) n.coreArt.visible = n.nucleoDerived;
    });
    rebuildModel();
    return { ok: true, modo: multi.modo, cables: multi.cables.length };
  }
  function multiRunStart(plan) {
    if (plan) applyMultiPlan(plan, multi.piezas);
    multi.running = true; multi.activeHop = 0; multi.latencies.clear();
    const n = multi.plan && multi.plan.eslabones && agentNodeFor(multi.plan.eslabones[0] && multi.plan.eslabones[0].agent_ref);
    if (n) { n.glowTarget = 1; n.glow = 1.6; }
    return multiState();
  }
  function multiHop(index, latencyMs) {
    const es = multi.plan && multi.plan.eslabones || [];
    const prev = agentNodeFor(es[multi.activeHop] && es[multi.activeHop].agent_ref);
    if (prev) prev.glowTarget = 0;
    multi.running = true; multi.activeHop = Math.max(0, Math.min(es.length - 1, index | 0));
    const n = agentNodeFor(es[multi.activeHop] && es[multi.activeHop].agent_ref);
    if (n) {
      n.glowTarget = 1; n.glow = 1.7;
      if (Number.isFinite(Number(latencyMs))) multi.latencies.set(n.id, Number(latencyMs));
    }
    return multiState();
  }
  function multiRunStop() {
    const es = multi.plan && multi.plan.eslabones || [];
    const n = agentNodeFor(es[multi.activeHop] && es[multi.activeHop].agent_ref);
    if (n) n.glowTarget = 0;
    multi.running = false; multi.activeHop = -1;                 // chips quedan vacíos en reposo
    return multiState();
  }
  function multiState() {
    return {
      modo: multi.modo, plan: multi.plan, cables: multi.cables.slice(),
      visualCables: multi.visualCables.slice(),
      running: multi.running, activeHop: multi.activeHop,
      displayedLatencies: multi.running ? [...multi.latencies.entries()].map(([id, ms]) => ({ id, ms })) : [],
      restriction: multi.restriction,
    };
  }
  async function playMeasuredRun(run, delayMs = 360) {
    const saltos = run && Array.isArray(run.saltos) ? run.saltos : [];
    if (!saltos.length) { multiRunStop(); return multiState(); }
    multi.running = true;
    for (let i = 0; i < saltos.length; i++) {
      multiHop(i, Number(saltos[i].latencia_ms));
      await sleep(delayMs);
    }
    multiRunStop(); return multiState();
  }

  // ── CÁMARA: pan (arrastrar área vacía) · zoom/rotate vía API ────────────────
  let panning = null;
  app.stage.eventMode = "static";
  app.stage.hitArea = new PIXI.Rectangle(0, 0, W, H);
  app.stage.on("pointerdown", (e) => {
    if (dragTool || e.target !== app.stage) return; // clic en pieza/zona → no paneamos
    panning = { x: e.global.x, y: e.global.y, camx: cam.x, camy: cam.y };
    app.canvas.style.cursor = "grabbing";
  });
  app.stage.on("pointermove", (e) => {
    if (!panning) return;
    cam.x = panning.camx + (e.global.x - panning.x); cam.y = panning.camy + (e.global.y - panning.y); applyCam();
  });
  app.stage.on("globalpointermove", (e) => { if (tileDrag) tileDragMove(e); }); // mover una pieza colocada
  const onStageUp = (e) => { if (tileDrag) tileDragUp(e); panning = null; app.canvas.style.cursor = ""; };
  app.stage.on("pointerup", onStageUp); app.stage.on("pointerupoutside", onStageUp);

  const panBy = (dx, dy) => { cam.x += dx; cam.y += dy; applyCam(); };
  const SEMANTIC_IN = 1.72, SEMANTIC_OUT = 1.48;
  let lastSemanticAnchor = null;
  function agentAtScreen(cx, cy) {
    // Muralla anti-fractal: el Núcleo gana el hit-test aunque una baldosa se
    // solape visualmente detrás. La rueda sobre el Núcleo sólo acerca la cámara;
    // abrir su Mente sigue reservado al gesto de presionar.
    try {
      const core = nucleoNode.gfx && nucleoNode.gfx.getBounds();
      if (core && cx >= core.x && cx <= core.x + core.width &&
        cy >= core.y && cy <= core.y + core.height) return null;
    } catch (_) {}
    for (const n of Object.values(placedById)) {
      if (n.kind !== "recinto" || !n.hasNucleo) continue;
      try {
        const b = n.hit && n.hit.getBounds();
        if (b && cx >= b.x && cx <= b.x + b.width && cy >= b.y && cy <= b.y + b.height) return n;
      } catch (_) {}
      const p = recintoCenter(n), sx = cam.x + p.x * cam.scale, sy = cam.y + p.y * cam.scale;
      if (Math.hypot(cx - sx, cy - sy) <= 42 * cam.scale) return n;
    }
    return null;
  }
  function zoomAt(factor, cx, cy) {
    const old = cam.scale, next = Math.max(0.42, Math.min(2.6, old * factor)); // min bajo: cuarto grande entra
    if (next === old) return;
    if (cx == null) { cx = W / 2; cy = H / 2; }
    if (factor > 1 && old < SEMANTIC_IN && next >= SEMANTIC_IN) {
      const n = agentAtScreen(cx, cy);
      if (n) {
        const ctr = recintoCenter(n);
        const before = { x: cam.x + ctr.x * cam.scale, y: cam.y + ctr.y * cam.scale };
        lastSemanticAnchor = { id: n.id, cursor: { x: cx, y: cy }, before, after: null };
        enterRecinto(n.id, { anchor: { x: cx, y: cy } }).then((res) => {
          lastSemanticAnchor.result = res;
          if (res && res.ok) lastSemanticAnchor.after = res.anchor && res.anchor.screen;
        });
        return;
      }
    }
    if (factor < 1 && fractalStack.length > 0 && next <= SEMANTIC_OUT) {
      exitRecinto(); return;
    }
    const wx = (cx - cam.x) / old, wy = (cy - cam.y) / old;
    cam.scale = next; cam.x = cx - wx * next; cam.y = cy - wy * next; applyCam();
  }
  const pulseRoom = () => { zoneNodes.forEach((z) => (z.glow = 1.2)); nucleoNode.glow = 1.4; };
  const rotateBy = (dir) => { cam.rot = (((cam.rot + dir) % 4) + 4) % 4; relayout(); fitAll(); pulseRoom(); };

  // ── FIT-ALL: encuadrar TODO (zonas + núcleo + piezas) sin tener que panear ──
  // Calcula el bounding box en coords de mundo (pre-cámara) de la sala visible y
  // ajusta cam.scale/x/y para que entre en W×H con margen. Se recalcula al crecer/rotar/resize.
  function roomScreenBounds() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    const hw = grid.tileWidth / 2, hh = grid.tileHeight / 2;
    const consider = (gx, gy, topPad = 52) => { // topPad: piezas/núcleo suben ~50px sobre su celda
      const p = toScreen(gx, gy);
      minX = Math.min(minX, p.x - hw); maxX = Math.max(maxX, p.x + hw);
      minY = Math.min(minY, p.y - hh - topPad); maxY = Math.max(maxY, p.y + hh);
    };
    // las 4 esquinas de cada zona (rota con cam.rot) + el núcleo + las piezas (suben ~52px)
    scene.zones.forEach((z) => {
      consider(z.gridX, z.gridY); consider(z.gridX + z.w - 1, z.gridY);
      consider(z.gridX, z.gridY + z.h - 1); consider(z.gridX + z.w - 1, z.gridY + z.h - 1);
    });
    Object.values(placedById).forEach((n) => consider(n.gx, n.gy));
    if (!isFinite(minX)) { minX = 0; minY = 0; maxX = W; maxY = H; }
    return { minX, minY, maxX, maxY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) };
  }
  // insets: alto los paneles abiertos (paleta izq / inspector der) no tapan la sala
  let fitInsets = { leftPx: 0, rightPx: 0 };
  const setInsets = (o) => { fitInsets = o || { leftPx: 0, rightPx: 0 }; };
  function fitAll(pad = 1.12) {
    // El botón ⊙ es ENCUADRAR TODO también dentro de un hijo: nunca queda inutilizado
    // por haber cruzado un nivel fractal. El snapshot del padre restaura su cámara al salir.
    const rect = app.canvas.getBoundingClientRect();
    const k = rect.width ? W / rect.width : 1;                 // CSS px → render px
    const iL = (fitInsets.leftPx || 0) * k, iR = (fitInsets.rightPx || 0) * k;
    const availW = Math.max(80, W - iL - iR);
    const b = roomScreenBounds();
    const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
    cam.scale = Math.max(0.42, Math.min(2.6, Math.min(availW / (b.w * pad), H / (b.h * pad))));
    cam.x = iL + availW / 2 - cx * cam.scale; cam.y = H / 2 - cy * cam.scale; applyCam();
    return { ...cam };
  }
  const resetCam = () => { cam.rot = 0; relayout(); return fitAll(); };

  // ╔══ D2 · FRACTAL — zoom semántico + stack de escenas (§3.2) ═══════════════════════════════════╗
  // ENTRAR a un recinto-agente = push-in de cámara + cargar SU receta en el MISMO motor (child-world),
  // con el padre GUARDADO byte-idéntico (no se MUTA). SALIR = pull-back + restaurar al padre exacto.
  // Navegación de ESCENA, no modal. El invariante gate §7.2 (padre == snapshot) es load-bearing.
  const MAX_DEPTH_UI = 3;   // espejo exacto del guard sellado del motor; topar siempre avisa causa.
  const fractalState = () => ({ depth: fractalStack.length,
    stack: fractalStack.map((f) => ({ agentRef: f.agentRef, label: f.label })),
    atRoot: fractalStack.length === 0 });
  const notifyFractal = () => { try { onFractalChange && onFractalChange(fractalState()); } catch (e) {} };
  const notifyDenied = (res) => { try { onFractalDenied && onFractalDenied(res); } catch (e) {} };

  // push-in: enmarca el footprint del recinto (footScreen) y centra en recintoCenter, ease-out ~380ms.
  const easeOutCubic = (e) => 1 - Math.pow(1 - e, 3);
  const tweenCamTo = (tx, ty, ts) => { camTween = { fx: cam.x, fy: cam.y, fs: cam.scale, tx, ty, ts, t: 0, dur: 0.38 }; };
  function pushIntoNode(n, anchor) {
    const cs = footScreen(recintoFootRect(n));            // 4 esquinas del footprint (world-local, cámara-aware)
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const p of cs) { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }
    const ctr = recintoCenter(n);                          // centro (incluye offset de arrastre vivo)
    const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY);
    const fill = 0.55;                                     // el footprint llena ~55% del viewport (push-in con aire)
    const fitScale = Math.min((W * fill) / bw, (H * fill) / bh);
    // Al cruzar no agrandamos la pieza: convertimos de escena y dejamos el
    // Cuarto hijo en escala de lectura, listo para otro nivel del continuum.
    const ts = Math.max(0.86, Math.min(1.28, fitScale));
    // ANCLA: la baldosa permanece exactamente debajo del cursor. Centrarla sería
    // teletransportar la cámara y romper el gesto continuo de mapa.
    const ax = anchor && Number.isFinite(anchor.x) ? anchor.x : W / 2;
    const ay = anchor && Number.isFinite(anchor.y) ? anchor.y : H / 2;
    tweenCamTo(ax - ctr.x * ts, ay - ctr.y * ts, ts);
    return { screen: { x: ax, y: ay }, world: { x: ctr.x, y: ctr.y },
      camera: { x: ax - ctr.x * ts, y: ay - ctr.y * ts, scale: ts } };
  }

  // Un nivel fractal no es una lista: es otro Cuarto. Este scaffold vive dentro
  // del child-world y repite las cuatro capas esenciales del nivel raíz.
  const CHILD_ARC = [[1, 4], [3, 5], [5, 4], [1, 2], [5, 2], [3, 1]];
  function makeChildRoom(layer, label) {
    const floor = new PIXI.Graphics(); floor.zIndex = -1; floor.eventMode = "none";
    const cables = new PIXI.Graphics(); cables.zIndex = 5; cables.eventMode = "none";
    const core = makeNucleo(); core.zIndex = 6; core.eventMode = "none";
    const coreCell = { gx: 3, gy: 2 }, cp = toScreen(coreCell.gx, coreCell.gy);
    core.position.set(cp.x, cp.y - 4);
    const title = new PIXI.Text({ text: label || TR("cuarto.fractal.room", "Cuarto"),
      style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 12,
        fontWeight: "500", fill: PALT.labelFill, stroke: { color: PALT.labelStroke, width: 3 } } });
    title.anchor.set(0.5, 1); title.position.set(cp.x, cp.y - 68); title.zIndex = 7;
    layer.addChild(floor, cables, core, title);
    const hw = grid.tileWidth / 2, hh = grid.tileHeight / 2;
    for (let gy = 0; gy < 7; gy++) for (let gx = 0; gx < 7; gx++) {
      const p = toScreen(gx, gy), edge = Math.min(gx, gy, 6 - gx, 6 - gy);
      const alpha = edge === 0 ? 0.2 : edge === 1 ? 0.5 : 0.86;
      floor.poly([p.x, p.y - hh, p.x + hw, p.y, p.x, p.y + hh, p.x - hw, p.y])
        .fill({ color: floorTint(gx, gy), alpha })
        .stroke({ color: PALT === THEME.light ? PALT.floorLine : 0x7978ad, width: 0.8, alpha: alpha * 0.35 });
    }
    return { layer, floor, cables, core, coreCell, title, childIds: [] };
  }
  function drawChildRoom(s, time) {
    if (!s || !s.layer || s.layer.destroyed) return;
    tickAtomArt(s.core, time, 0.2);
    const cp = toScreen(s.coreCell.gx, s.coreCell.gy);
    s.cables.clear();
    for (const id of s.childIds) {
      const n = placedById[id]; if (!n || !n.gfx || n.gfx.destroyed) continue;
      const p = tileCenter(n);
      s.cables.moveTo(cp.x, cp.y - 46).lineTo(p.x, p.y)
        .stroke({ color: n.color || 0xb389ff, width: 1.5, alpha: 0.64 });
    }
  }
  function childRoomState() {
    const s = activeChildScene;
    if (!s) return null;
    const labels = s.childIds.map((id) => placedById[id]).filter(Boolean)
      .map((n) => ({ node: n, visual: n.label || n.chip })).filter((x) => x.visual);
    let overlaps = 0;
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i].visual.getBounds(), b = labels[j].visual.getBounds();
      if (a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y) overlaps++;
    }
    return { floor: !!s.floor, nucleus: !!s.core, cableCount: s.childIds.length,
      childCount: s.childIds.length,
      namedCount: labels.filter((x) => x.visual.visible !== false && x.visual.text.trim()).length,
      labelOverlaps: overlaps, parentAlpha: fractalStack.length ? fractalStack[fractalStack.length - 1].prevWorld.alpha : 1 };
  }

  // ENTRAR — recintoId debe ser un recinto-AGENTE (hasNucleo). opts.recipe = receta del hijo INYECTADA
  // (harness / preload D5). Sin ella intenta fetch por agent_ref (DIFERIDO a D4; el harness stubea /v1).
  async function enterRecinto(recintoId, opts) {
    opts = opts || {};
    // FIX B (§9·B) · lock de re-entrancy ANTES de cualquier await: dos dblclick / botones "Entrar" en un
    // solo RTT de fetch pasaban todos el cap y empujaban frames fantasma. El segundo enter en vuelo aborta.
    if (_enterInFlight) { const r = { ok: false, reason: "busy" }; notifyDenied(r); return r; }
    if (fractalStack.length >= MAX_DEPTH_UI) { const r = { ok: false, reason: "depth_cap", depth: fractalStack.length }; notifyDenied(r); return r; }
    const node = placedById[recintoId];
    if (!node || node.kind !== "recinto" || !node.hasNucleo) { const r = { ok: false, reason: "not_agent" }; notifyDenied(r); return r; }
    // Completar el crossfade previo antes de encadenar otro salto evita que un
    // breadcrumb profundo deje child-worlds huérfanos bajo la escena activa.
    finishSceneTween();
    _enterInFlight = true;
    try {
    const agentRef = node.data.agent_ref || null;
    const label = agentVisibleName(node.data.label);
    let childRecipe = opts.recipe || null;
    if (!childRecipe && typeof window.__cuartoFetchChildRecipe === "function") {   // (b) fetch por agent_ref — real en D4
      try { childRecipe = await window.__cuartoFetchChildRecipe(agentRef); } catch (e) { childRecipe = null; }
    }
    // FIX B · RE-VALIDAR tras el await: el nodo pudo removerse/moverse y la profundidad cambiar mientras el
    // fetch estaba en vuelo. Sin esto, un enter tardío empujaría un frame contra un padre ya distinto.
    if (placedById[recintoId] !== node) { const r = { ok: false, reason: "node_changed" }; notifyDenied(r); return r; }
    if (fractalStack.length >= MAX_DEPTH_UI) { const r = { ok: false, reason: "depth_cap", depth: fractalStack.length }; notifyDenied(r); return r; }
    if (!childRecipe) {
      node.data.interiorEstado = "error";
      const r = { ok: false, reason: "no_recipe", agentRef }; notifyDenied(r); return r;
    }
    const recipeToTiles = window.__recipeMod && window.__recipeMod.recipeToTiles;
    if (typeof recipeToTiles !== "function") {
      node.data.interiorEstado = "error";
      const r = { ok: false, reason: "no_rehydrator" }; notifyDenied(r); return r;
    }
    const catalog = (window.__catalog && window.__catalog.entries)
      || (window.__atoms && window.__atoms.list) || [];   // entidad primero: conserva diorama_symbol y topología
    const childTiles = recipeToTiles(childRecipe, catalog);

    const anchorTarget = pushIntoNode(node, opts.anchor);   // push-in anclado ANTES del crossfade

    // SNAPSHOT inmutable del padre — mismos objetos/arrays (JSON idéntico al restaurar). El padre NO se muta.
    const frame = { agentRef, label, cam: { ...cam },
      placed: { ...placedById }, occ: [...occupancy], pieces: model.pieces, rels: model.relationships,
      animated: animated.slice(), layoutable: layoutable.slice(), settling: [...settling], gate: [...gateState],
      prevWorld: activeWorld, prevChildScene: activeChildScene };
    const parentWorld = activeWorld;
    const childWorld = new PIXI.Container(); childWorld.sortableChildren = true; cameraRoot.addChild(childWorld);
    childWorld.alpha = 0;
    frame.childWorld = childWorld; activeWorld = childWorld; placeLayer = childWorld;
    activeChildScene = makeChildRoom(childWorld, label);
    frame.childScene = activeChildScene;
    // vaciar las colecciones VIVAS (el padre está a salvo en el frame)
    for (const k of Object.keys(placedById)) delete placedById[k];
    occupancy.clear(); settling.clear(); gateState.clear();
    animated.length = 0; layoutable.length = 0;
    rebuildModel();                                                    // modelo hijo LIMPIO (sólo Núcleo); reasigna model.pieces (no muta el snapshot)
    fractalStack.push(frame);
    // cargar la receta del HIJO en el motor (SIEMPRE con catálogo). Una pieza-agente cae a recinto vacío.
    for (let i = 0; i < childTiles.length; i++) {
      const tile = childTiles[i], arc = CHILD_ARC[i % CHILD_ARC.length];
      placeTileInternal({ id: tile.id, key: tile.key, label: tile.label, category: tile.category, atom: tile.atom,
        server: tile.server, ref: tile.ref, tools: tile.tools, belt_ref: tile.belt_ref, connector: tile.connector,
        service: tile.service, servers: tile.servers, belt_refs: tile.belt_refs, credential: tile.credential,
        toolCount: tile.toolCount, serverCount: tile.serverCount, connectors: tile.connectors, toolsDetail: tile.toolsDetail,
        agent_ref: tile.agent_ref, nucleo: tile.nucleo, sharesMemory: tile.sharesMemory, role: tile.role },
        arc[0], arc[1]);
      const child = placedById[tile.id];
      if (child) {
        activeChildScene.childIds.push(child.id);
        if (child.label) { child.alwaysLabel = true; child.label.visible = true; }
      }
    }
    sceneTween = { out: parentWorld, in: childWorld, outFrom: parentWorld.alpha,
      outTo: 0.2, inFrom: 0, inTo: 1, hideOut: false, t: 0, dur: 0.38 };
    notifyFractal();
    return { ok: true, depth: fractalStack.length, agentRef, label,
      childCount: childTiles.length, anchor: anchorTarget };
    } finally { _enterInFlight = false; }   // FIX B · el lock se libera SIEMPRE (éxito, rechazo tardío o throw)
  }

  // SALIR — pop del stack → descartar el child-world → restaurar al padre BYTE-IDÉNTICO → pull-back.
  function exitRecinto() {
    if (fractalStack.length === 0) return { ok: false, reason: "at_root", depth: 0 };
    finishSceneTween();
    const frame = fractalStack.pop();
    const childLeaving = activeWorld;
    for (const k of Object.keys(placedById)) delete placedById[k];    // baja los nodos del hijo (su gfx ya murió con el child-world)
    occupancy.clear(); settling.clear(); gateState.clear();
    animated.length = 0; layoutable.length = 0;
    // RESTAURAR al padre: mismos objetos/arrays → relationModel() vuelve byte-idéntico al snapshot (§7.2)
    for (const k of Object.keys(frame.placed)) placedById[k] = frame.placed[k];
    for (const [k, v] of frame.occ) occupancy.set(k, v);
    for (const s of frame.settling) settling.add(s);
    for (const [k, v] of frame.gate) gateState.set(k, v);
    for (const n of frame.animated) animated.push(n);
    for (const n of frame.layoutable) layoutable.push(n);
    model.pieces = frame.pieces; model.relationships = frame.rels;    // ← INVARIANTE anti-corrupción del padre
    activeWorld = frame.prevWorld; activeChildScene = frame.prevChildScene;
    placeLayer = activeWorld; activeWorld.visible = true; activeWorld.alpha = 0.2;
    cam.rot = frame.cam.rot; relayout();                              // rot restaurado + reproyecta la escena del padre
    tweenCamTo(frame.cam.x, frame.cam.y, frame.cam.scale);            // pull-back a la cámara guardada
    sceneTween = { out: childLeaving, in: activeWorld, outFrom: 1, outTo: 0,
      inFrom: 0.2, inTo: 1, t: 0, dur: 0.38, destroyOut: true };
    notifyFractal();
    return { ok: true, depth: fractalStack.length };
  }
  const exitTo = (level) => { level = Math.max(0, level | 0); while (fractalStack.length > level) exitRecinto(); return { ok: true, depth: fractalStack.length }; };

  // AFFORDANCE DE ENTRADA · doble-click sobre un recinto-agente = ENTRAR (el single-click sigue siendo
  // toggle/inspector en tileDragUp — NO se toca). Hit-test por celda (cellFromGlobal) → recinto efectivo.
  app.canvas.addEventListener("dblclick", (ev) => {
    if (running) return;
    const r = app.canvas.getBoundingClientRect();
    const gx = (ev.clientX - r.left) * (app.screen.width / r.width);
    const gy = (ev.clientY - r.top) * (app.screen.height / r.height);
    const cell = cellFromGlobal(gx, gy); if (!cell) return;
    let hitN = null;
    for (const n of Object.values(placedById)) {
      if (n.kind !== "recinto" || !n.hasNucleo) continue;
      if (cell.gridX >= n.gx && cell.gridX < n.gx + effW(n) && cell.gridY >= n.gy && cell.gridY < n.gy + effH(n)) { hitN = n; break; }
    }
    if (hitN) enterRecinto(hitN.id);   // sin opts.recipe → fetch por agent_ref (D4); no crashea si no resuelve
  });

  // ╔══ CONSTELACIÓN · 3 VISTAS — CAPA ADITIVA (draw-pass aparte; generaliza la LENTE F4) ═════════╗
  // La MISMA física estrella del force (capa 2 + doc §6/§7): el Núcleo es el hub, las piezas orbitan.
  // Esta capa NO mueve piezas y NO muta el modelo (model.pieces/relationships intactos) — sólo
  // SUPERPONE un agrupado VISUAL (halo + centroide + tether), tal cual la lente F4, conmutable sin
  // recargar. Tres vistas (doc §6) sobre la MISMA data, reagrupada por una keyFn distinta:
  //   · "servicio"  (default al PRENDER) = server || connector       → "ah, conecté mi EDGAR" (sale del dato de inspección)
  //   · "funcion"   = role (lee/procesa/actúa)                       → ES la lente F4, ahora SUBSUMIDA acá
  //   · "relacion"  = membresía de recinto || conexión que habilita  → "lo más conectado"
  // Los recintos-agente (drawRecintos) siguen ABAJO, intactos: estos cúmulos son EFÍMEROS (overlay),
  // NO crean recintos reales (eso tocaría modelo/occupancy). Default al MONTAR = "off" → idéntico a
  // hoy: orbitar crudo, sin halos. La vista "funcion" reproduce la lente F4 (verbos + colores de zona).
  let viewMode = "off"; // "off" | "servicio" | "funcion" | "relacion"
  // colores saturados (leen bien en light y dark, como las piezas) — paleta estable por orden de clave.
  const VIEW_PALETTE = [
    { color: ZONE_DEF.fuentes.color, glow: ZONE_DEF.fuentes.glow },
    { color: ZONE_DEF.mesa.color,    glow: ZONE_DEF.mesa.glow },
    { color: ZONE_DEF.entrega.color, glow: ZONE_DEF.entrega.glow },
    { color: 0x46b1ff, glow: 0x8fd2ff },
    { color: 0xff6f91, glow: 0xffa6bd },
    { color: 0x5ad1c8, glow: 0x9bece4 },
    { color: 0xe6c34a, glow: 0xf6dd86 },
  ];
  // vista "funcion" = lente F4 EXACTA: tools por rol, orden del camino (lee→procesa→actúa) + verbos + colores de zona.
  // [merge constelación×B2] verbos/subs traducibles vía TR() (i18n-bi Ola B2; window.t, fallback ES) — reconciliado al unir.
  const LENS_GROUPS = [
    { role: "fuentes", color: ZONE_DEF.fuentes.color, glow: ZONE_DEF.fuentes.glow, verb: TR("cuarto.lens.lee.verb","lee"),         sub: TR("cuarto.zone.lee.sub","trae dato") },
    { role: "mesa",    color: ZONE_DEF.mesa.color,    glow: ZONE_DEF.mesa.glow,    verb: TR("cuarto.lens.procesa.verb","procesa"), sub: TR("cuarto.zone.procesa.sub","transforma") },
    { role: "entrega", color: ZONE_DEF.entrega.color, glow: ZONE_DEF.entrega.glow, verb: TR("cuarto.lens.actua.verb","actúa"),     sub: TR("cuarto.zone.actua.sub","saca") },
  ];
  const viewHalo = new PIXI.Graphics(); viewHalo.zIndex = 3; viewHalo.eventMode = "none"; viewHalo.visible = false; world.addChild(viewHalo);
  const viewFlow = new PIXI.Graphics(); viewFlow.zIndex = 6; viewFlow.eventMode = "none"; viewFlow.visible = false; world.addChild(viewFlow);
  const viewLabels = new PIXI.Container(); viewLabels.zIndex = 320; viewLabels.eventMode = "none"; viewLabels.visible = false; world.addChild(viewLabels);
  // pool de etiquetas (los grupos son dinámicos por vista): se reusan por índice, las sobrantes se ocultan.
  const viewLabelPool = [];
  function getViewLabel(i) {
    let w = viewLabelPool[i];
    if (!w) {
      w = new PIXI.Container();
      const t1 = new PIXI.Text({ text: "", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 13, fontWeight: "500", fill: 0xffffff, letterSpacing: 1 } });
      const t2 = new PIXI.Text({ text: "", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 10.5, fill: 0x9fb0c4 } });
      t1.anchor.set(0.5, 1); t2.anchor.set(0.5, 0); t2.position.set(0, 2);
      w.addChild(t1, t2); w.__t1 = t1; w.__t2 = t2; viewLabels.addChild(w); viewLabelPool[i] = w;
    }
    return w;
  }
  // siglas conocidas → MAYÚSCULA (en vez de titularizarse) en la vista servicio; el resto, titleize normal.
  const VIEW_ACRONYMS = new Set(["tmdb", "edgar", "sec", "kb", "api", "mcp", "sql", "csv", "pdf", "url", "ai", "id", "edi", "edx", "edgr"]);
  const _viewTitleize = (s) => String(s || "").replace(/[_-]+/g, " ").split(" ").filter(Boolean)
    .map((w) => VIEW_ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : (w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
  // F4 · las bandas fijas del piso (F2 inertes) y sus etiquetas quedan OCULTAS: la vista las sustituye.
  zoneG.visible = false; zoneNodes.forEach((n) => { if (n.lbl) n.lbl.visible = false; });

  // clave de agrupado por vista (sobre una pieza colocada NO-recinto, NO-oculta).
  const serviceKey = (n) => n.data.server || n.data.connector || "—";
  const relationKey = (n) => {
    if (n.atomKind === "conexion") return n.id;                       // la conexión es su propio hub
    if (n.parentId) return n.parentId;                                // membresía de recinto
    const k = n.data.server || n.data.connector;                     // ¿la habilita una conexión? (mismo server)
    if (k) for (const cx of Object.values(placedById))
      if (cx.atomKind === "conexion" && (cx.data.server || cx.data.connector) === k) return cx.id;
    return "—";                                                      // suelta (sin recinto ni conexión)
  };
  // arma los grupos ORDENADOS de la vista activa: [{ key, label, sub, color, glow, pts[] }].
  function buildViewGroups(mode) {
    if (mode === "funcion") {                                        // lente F4 EXACTA: tools por rol, orden+verbos+colores fijos
      const byRole = {};
      for (const n of Object.values(placedById)) {
        if (n.atomKind !== "tool" || n.kind === "recinto" || n.hidden) continue;
        (byRole[n.data.role || "mesa"] ||= []).push(tileCenter(n));
      }
      return LENS_GROUPS.map((g) => ({ key: g.role, label: g.verb, sub: "· " + g.sub, color: g.color, glow: g.glow, pts: byRole[g.role] || [] }))
        .filter((g) => g.pts.length);
    }
    const keyOf = mode === "servicio" ? serviceKey : relationKey;    // servicio | relacion → grupos dinámicos
    const buckets = new Map();
    for (const n of Object.values(placedById)) {
      if (n.kind === "recinto" || n.hidden) continue;
      if (n.atomKind !== "tool" && n.atomKind !== "conexion") continue;
      const k = keyOf(n); if (k == null) continue;
      let arr = buckets.get(k); if (!arr) buckets.set(k, arr = []);
      arr.push(tileCenter(n));
    }
    const labelFor = (k) => {
      if (mode === "relacion") { if (k === "—") return "sueltas"; const p = placedById[k]; return p ? (p.data.label || k) : k; }
      return k === "—" ? "sin origen" : _viewTitleize(k);
    };
    return [...buckets.keys()].sort().map((k, i) => {
      const pts = buckets.get(k), pal = VIEW_PALETTE[i % VIEW_PALETTE.length];
      return { key: k, label: labelFor(k), sub: "· " + pts.length, color: pal.color, glow: pal.glow, pts };
    }).filter((g) => g.pts.length);
  }
  // dibuja la vista activa: halo por grupo + tether de cada pieza al centroide + camino al Núcleo +
  // etiqueta. El "camino" pulsa ciclando por los grupos (ambient; se atenúa en run real → mandan los
  // encendidos por evento de F5). Lee SÓLO del modelo/posición; no escribe nada.
  function drawView(time) {
    viewHalo.clear(); viewFlow.clear();
    const groups = buildViewGroups(viewMode), nuc = nucleoPoint();
    const active = (running || !groups.length) ? -1 : Math.floor((time % (groups.length * 2.4)) / 2.4) % groups.length;
    let li = 0;
    groups.forEach((g, gi) => {
      const pts = g.pts; if (!pts.length) return;
      const cx = pts.reduce((a, p) => a + p.x, 0) / pts.length, cy = pts.reduce((a, p) => a + p.y, 0) / pts.length;
      let r = 30; for (const p of pts) r = Math.max(r, Math.hypot(p.x - cx, p.y - cy) + 34);
      const hot = gi === active ? 0.5 + 0.5 * Math.sin(time * 5) : 0;
      // halo del grupo (las piezas de ese cúmulo, juntas) + tethers al centroide
      viewHalo.circle(cx, cy, r).fill({ color: g.color, alpha: 0.06 + hot * 0.05 })
              .circle(cx, cy, r).stroke({ color: g.glow, width: 1.6, alpha: 0.34 + hot * 0.5 });
      for (const p of pts) viewHalo.moveTo(cx, cy).lineTo(p.x, p.y);
      viewHalo.stroke({ color: g.glow, width: 1, alpha: 0.2 + hot * 0.4 });
      const lab = getViewLabel(li++); lab.visible = true; lab.position.set(cx, cy - r - 8);
      if (lab.__t1.text !== g.label) lab.__t1.text = g.label;
      lab.__t1.style.fill = g.glow;
      if (lab.__t2.text !== g.sub) lab.__t2.text = g.sub;
      // camino iluminado Núcleo↔grupo (el Eco vuelve por el mismo cable; mismo estilo que F4)
      const fa = running ? 0.14 : 0.42;
      viewFlow.moveTo(nuc.x, nuc.y).lineTo(cx, cy)
              .stroke({ color: g.color, width: gi === active ? 3.2 : 1.6, alpha: fa + (gi === active ? 0.4 : 0) });
    });
    for (let i = li; i < viewLabelPool.length; i++) if (viewLabelPool[i]) viewLabelPool[i].visible = false;
  }
  // conmuta la vista. "off" (default al montar) = orbitar crudo, idéntico a hoy. Devuelve el modo activo.
  function setView(mode) {
    viewMode = (mode === "servicio" || mode === "funcion" || mode === "relacion") ? mode : "off";
    const on = viewMode !== "off";
    viewHalo.visible = viewFlow.visible = viewLabels.visible = on;
    if (!on) { viewHalo.clear(); viewFlow.clear(); viewLabelPool.forEach((w) => w && (w.visible = false)); }
    // [iconos] el glifo de dominio se ENCIENDE con la lente (toma el color de rol) y vuelve a
    // monocromo al apagar. Event-driven (sólo al conmutar) → el ticker/drawView quedan byte-iguales.
    for (const n of Object.values(placedById)) {
      if (n.atomKind === "tool" && n.art && n.art.__domainTint) n.art.__domainTint(on, n.color);
    }
    pulseRoom();
    return viewMode;
  }
  // ╚════════════════════════════════════════════════════════════════════════════════════════════╝

  // ╔══ 1a · COREOGRAFÍA DE INSPECCIÓN (Motor B) — DRAW-PASS APARTE (como la lente F4) ════════════╗
  // Renderiza el STREAM del contrato POST /v1/inspect/forge (6 capas) SIN tocar el modelo de
  // relaciones (F2), ni rebuildLinks, ni el drag (F3), ni el gate (F5). Es overlay PURO en `world`
  // (cámara-aware vía nucleoPoint): la pieza-target se "conecta" al Núcleo, el Núcleo se enciende
  // mirándola, nacen tools-FANTASMA en abanico, cada una PULSA al validar y se vuelve SÓLIDA
  // (tool.validada) o se DESVANECE con su motivo (tool.descartada). CERO-TEATRO: una transición
  // ocurre SÓLO cuando llega su evento REAL (lo dispara api.forge.* desde cuarto.inspect.js). Las
  // fantasmas NUNCA son piezas reales (no placeTile, no occupancy, no receta, no rebuildModel) — el
  // sellado/equip es 1-B. La coreografía termina en "listas para sellar" (mcp.forjado).
  const FORGE_COL = { proposed: 0x5a6376, validating: 0x46d6c8, validated: 0x57e08a,
                      discarded: 0x7a4a4a, target: 0x46b1ff, beam: 0x9af7e6 };
  const forgeCables = new PIXI.Graphics(); forgeCables.zIndex = 7; forgeCables.eventMode = "none"; forgeCables.visible = false; world.addChild(forgeCables);
  const forgeFx = new PIXI.Graphics(); forgeFx.zIndex = 8; forgeFx.eventMode = "none"; forgeFx.visible = false; world.addChild(forgeFx);
  const forgeNodes = new PIXI.Container(); forgeNodes.zIndex = 330; forgeNodes.sortableChildren = true; forgeNodes.eventMode = "none"; forgeNodes.visible = false; world.addChild(forgeNodes);
  const forge = { on: false, target: null, observing: 0, observingTarget: 0, ghosts: new Map(), order: [], forged: false, forgedT: 0 };

  function makeForgeGhost(name, sub) {
    const cont = new PIXI.Container(); cont.alpha = 0;
    const halo = new PIXI.Graphics();
    const body = new PIXI.Graphics(); // diamante en BLANCO → se tinta por estado (proposed/validating/validated/discarded)
    body.poly([0, -11, 20, 0, 0, 11, -20, 0]).fill({ color: 0xffffff, alpha: 0.92 }).stroke({ color: 0xffffff, width: 1.4, alpha: 0.55 });
    const dot = new PIXI.Graphics(); dot.circle(0, 0, 2.4).fill({ color: 0x0b0e14, alpha: 0.7 });
    const lbl = new PIXI.Text({ text: name, style: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 9.5, fontWeight: "500", fill: 0xeaf0fb, align: "center" } });
    lbl.anchor.set(0.5, 0); lbl.position.set(0, 14);
    const note = new PIXI.Text({ text: "", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 8.5, fill: 0xff9a9a, align: "center", wordWrap: true, wordWrapWidth: 132 } });
    note.anchor.set(0.5, 0); note.position.set(0, 26); note.alpha = 0;
    cont.addChild(halo, body, dot, lbl, note);
    // queue/stateT = MIN-DWELL por estado: el stream emite validando+validada (o validando+descartada)
    // en el MISMO task JS → sin dwell el estado intermedio se sobrescribe antes de renderizar un frame
    // y el PULSO nunca se vería. La cola NO inventa transiciones (cada una viene de su evento real);
    // sólo garantiza que un evento ya recibido se VEA un mínimo antes de aplicar el siguiente. Cero-teatro.
    return { name, sub: sub || "", state: "proposed", queue: [], stateT: null, motivo: "", cont, halo, body, lbl, note, appear: 0, glow: 0, fade: 1, tx: null, ty: null, dead: false };
  }
  function makeForgeTarget(label, host) {
    const cont = new PIXI.Container(); cont.alpha = 0;
    const box = new PIXI.Graphics();
    const title = new PIXI.Text({ text: label || "Target", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif", fontSize: 11, fontWeight: "500", fill: 0xeaf0fb } });
    title.anchor.set(0.5); title.position.set(0, -5);
    const sub = new PIXI.Text({ text: host || "", style: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 9, fill: 0x9fb0c4 } });
    sub.anchor.set(0.5); sub.position.set(0, 9);
    cont.addChild(box, title, sub);
    return { cont, box, title, sub, connected: false, appear: 0 };
  }
  // abanico FRENTE al Núcleo (hacia la cámara = abajo en pantalla); achatado para sensación iso.
  function forgeLayoutFan() {
    const nuc = nucleoPoint();
    const live = forge.order.map((nm) => forge.ghosts.get(nm)).filter((g) => g && !g.dead);
    const n = live.length; if (!n) return;
    const R = 118 + Math.min(110, n * 10);
    const spread = Math.min(Math.PI * 1.05, 0.42 + n * 0.2);
    live.forEach((g, i) => {
      const frac = n <= 1 ? 0.5 : i / (n - 1);
      const ang = (Math.PI / 2) + (frac - 0.5) * spread;   // centrado hacia abajo (frente al Núcleo)
      g.tx = nuc.x + Math.cos(ang) * R;
      g.ty = nuc.y + Math.sin(ang) * R * 0.66;
    });
  }
  function drawForge(time) {
    forgeCables.clear(); forgeFx.clear();
    if (!forge.on) return;
    const nuc = nucleoPoint();
    // ── pieza-target: aparece, se "conecta" al Núcleo, el Núcleo la mira (observando) ──
    if (forge.target) {
      const tg = forge.target;
      tg.appear = approach(tg.appear, 1, 0.12);
      const tx = nuc.x - 150, ty = nuc.y - 64;
      tg.cont.position.set(tx, ty); tg.cont.alpha = tg.appear;
      const acc = tg.connected ? FORGE_COL.target : 0x6f7890;
      const glow = tg.connected ? 0.5 + 0.5 * Math.sin(time * 3) : 0;
      tg.box.clear();
      tg.box.roundRect(-78, -20, 156, 40, 10).fill({ color: 0x121724, alpha: 0.96 }).stroke({ color: acc, width: 2, alpha: 0.5 + 0.4 * glow });
      tg.box.roundRect(-72, -14, 5, 28, 2).fill({ color: acc, alpha: 0.9 });
      if (tg.connected) {
        dashedLine(forgeCables, { x: tx + 78, y: ty }, nuc, 7, 5);
        forgeCables.stroke({ color: FORGE_COL.target, width: 1.8, alpha: 0.45 + 0.3 * Math.sin(time * 4) });
      }
      if (forge.observing > 0.02) {
        forgeFx.moveTo(nuc.x, nuc.y).lineTo(tx + 42, ty + 8)
               .stroke({ color: FORGE_COL.beam, width: 2.4, alpha: (0.2 + 0.3 * Math.abs(Math.sin(time * 2.5))) * forge.observing });
        forgeFx.circle(nuc.x, nuc.y, 16 + 5 * Math.sin(time * 3)).stroke({ color: ZONE_DEF.nucleo.glow, width: 2, alpha: 0.3 * forge.observing });
        nucleoNode.glow = Math.max(nucleoNode.glow, 1.2 * forge.observing);   // anim sólo (no toca el modelo)
      }
    }
    forge.observing = approach(forge.observing, forge.observingTarget, 0.06);
    // ── fantasmas: nacen grises, PULSAN teal al validar, → SÓLIDAS verdes o se DESVANECEN ──
    forgeLayoutFan();
    for (const name of [...forge.order]) {
      const g = forge.ghosts.get(name); if (!g) continue;
      g.appear = approach(g.appear, 1, 0.14);
      // min-dwell: aplica a lo sumo UNA transición por frame, y sólo si el estado actual ya se vio lo
      // mínimo (proposed≈0.2s · validating≈0.45s para que el PULSO teal sea perceptible). terminal=0.
      if (g.stateT == null) g.stateT = time;
      const dwell = g.state === "proposed" ? 0.20 : g.state === "validating" ? 0.45 : 0;
      if (g.queue.length && (time - g.stateT) >= dwell) {
        g.state = g.queue.shift(); g.stateT = time;
        if (g.state === "validated") g.glow = 1.4;
      }
      if (g.tx != null) g.cont.position.set(approach(g.cont.position.x || g.tx, g.tx, 0.2),
                                            approach(g.cont.position.y || g.ty, g.ty, 0.2));
      const col = FORGE_COL[g.state] || FORGE_COL.proposed;
      let alpha = g.appear, scale = 0.85 + 0.15 * g.appear;
      g.halo.clear();
      if (g.state === "proposed") {
        alpha *= 0.58;
      } else if (g.state === "validating") {
        const p = 0.5 + 0.5 * Math.sin(time * 8);
        scale *= 1 + 0.12 * p; alpha = g.appear;
        g.halo.circle(0, 0, 18 + p * 8).stroke({ color: col, width: 2, alpha: 0.2 + 0.5 * p });
      } else if (g.state === "validated") {
        alpha = g.appear;
        g.halo.circle(0, 0, 16).stroke({ color: col, width: 1.6, alpha: 0.45 });
        g.halo.moveTo(-4, 0).lineTo(-1, 4).lineTo(6, -6).stroke({ color: 0xffffff, width: 1.8, alpha: 0.9 });
      } else if (g.state === "discarded") {
        g.fade = approach(g.fade, 0, 0.055); alpha = g.appear * g.fade; g.note.alpha = g.fade;
        if (g.fade < 0.04) g.dead = true;
      }
      g.body.tint = col; g.cont.alpha = alpha; g.cont.scale.set(scale);
      const gp = { x: g.cont.position.x, y: g.cont.position.y };
      if (g.state === "validated") { dashedLine(forgeCables, nuc, gp, 8, 4); forgeCables.stroke({ color: col, width: 2, alpha: 0.55 }); }
      else if (g.state === "validating") { dashedLine(forgeCables, nuc, gp, 6, 4); forgeCables.stroke({ color: col, width: 2.2, alpha: 0.5 + 0.4 * Math.sin(time * 8) }); }
      else if (g.state === "discarded") { dashedLine(forgeCables, nuc, gp, 5, 6); forgeCables.stroke({ color: col, width: 1, alpha: 0.25 * g.fade }); }
      else { dashedLine(forgeCables, nuc, gp, 4, 7); forgeCables.stroke({ color: col, width: 1, alpha: 0.32 * g.appear }); }
      if (g.dead) { try { g.cont.destroy({ children: true }); } catch {} forge.ghosts.delete(name); forge.order = forge.order.filter((x) => x !== name); }
    }
    // ── mcp.forjado: las SOBREVIVIENTES (validadas) listas para sellar (anillo verde; equip = 1-B) ──
    if (forge.forged) {
      forge.forgedT = Math.min(1, forge.forgedT + 0.02);
      const p = 0.5 + 0.5 * Math.sin(time * 2.5);
      for (const name of forge.order) {
        const g = forge.ghosts.get(name); if (!g || g.state !== "validated") continue;
        const gp = g.cont.position;
        forgeFx.circle(gp.x, gp.y, 20 + p * 6).stroke({ color: FORGE_COL.validated, width: 2, alpha: (0.3 + 0.3 * p) * forge.forgedT });
      }
    }
  }
  function forgeReset() {
    forge.on = false; forge.observing = 0; forge.observingTarget = 0; forge.forged = false; forge.forgedT = 0;
    if (forge.target) { try { forge.target.cont.destroy({ children: true }); } catch {} }
    forge.target = null;
    for (const g of forge.ghosts.values()) { try { g.cont.destroy({ children: true }); } catch {} }
    forge.ghosts.clear(); forge.order = [];
    try { forgeNodes.removeChildren(); } catch {}
    forgeCables.clear(); forgeFx.clear();
    forgeCables.visible = forgeFx.visible = forgeNodes.visible = false;
  }
  function forgeEnsure(name, meta) {
    let g = forge.ghosts.get(name);
    if (!g) { g = makeForgeGhost(name, (meta && meta.endpoint) || ""); forge.ghosts.set(name, g); forge.order.push(name); forgeNodes.addChild(g.cont); }
    return g;
  }
  // encola una transición REAL (la dispara su evento del stream); el dwell de drawForge decide cuándo
  // se APLICA (para que cada estado se vea). No se encola dos veces el mismo estado consecutivo.
  function forgeEnqueue(g, s) { if (g.state !== s && g.queue[g.queue.length - 1] !== s) g.queue.push(s); }
  // API de la coreografía — la maneja el consumidor (cuarto.inspect.js) con eventos REALES del stream.
  const forgeApi = {
    begin(opts = {}) {
      forgeReset(); forge.on = true;
      forgeCables.visible = forgeFx.visible = forgeNodes.visible = true;
      const host = (opts.host || (opts.url ? String(opts.url).replace(/^https?:\/\//, "").split("/")[0] : "")) || "target";
      forge.target = makeForgeTarget(opts.label || host, host);
      forgeNodes.addChild(forge.target.cont);
      pulseRoom();
    },
    session(meta = {}) { if (!forge.target) return; forge.target.connected = true; if (meta.host) forge.target.sub.text = meta.host; },
    observe() { forge.observingTarget = 1; },
    propose(t = {}) { const name = t.name || t.nombre; if (name) forgeEnsure(name, t); },
    validating(name) { if (!name) return; forgeEnqueue(forgeEnsure(name), "validating"); },
    validated(name) { if (!name) return; forgeEnqueue(forgeEnsure(name), "validated"); },
    // nota = PIXI.Text (no admite SVG inline): usa la ✕ TIPOGRÁFICA del set dejado (OS-estable, vector,
    // renderiza idéntico en todo OS), no el emoji/ballot ✗. Cero color-emoji, coherente con §2.5.
    discarded(name, motivo) { if (!name) return; const g = forgeEnsure(name); g.motivo = motivo || ""; g.note.text = motivo ? ("✕ " + String(motivo).slice(0, 80)) : "descartada"; forgeEnqueue(g, "discarded"); },
    forged() { forge.forged = true; forge.observingTarget = 0; },
    end() { forge.observingTarget = 0; },     // coreografía consumida: deja el estado final dibujado
    clear() { forgeReset(); },
    get on() { return forge.on; },
    stats: () => ({ on: forge.on, ghosts: forge.order.length, connected: !!(forge.target && forge.target.connected),
      validated: [...forge.ghosts.values()].filter((g) => g.state === "validated").length,
      validating: [...forge.ghosts.values()].filter((g) => g.state === "validating").length,
      discarded: [...forge.ghosts.values()].filter((g) => g.state === "discarded").length,
      forged: forge.forged }),
  };
  // ╚════════════════════════════════════════════════════════════════════════════════════════════╝

  // ── RECINTO · DIBUJO (sub-rama 2): muro + halo-que-late (solo agente) + stack (colapsado) ──────
  // Vista DERIVADA (recorre kind:"recinto"); NO muta el modelo ni mueve piezas. Muro = footPoly (reusa
  // la maquinaria de zonas, cámara/rotación/tema-aware). Halo = ritmo del Núcleo (tickNucleo: sin(t*3)),
  // SÓLO si hasNucleo. Stack = aspecto del estado COLAPSADO (su CONTROL/toggle es sub-rama 3). Guarda en
  // n._draw los params reales del frame (lo lee api.recintoDraw para distinguir agente↔cajón sin fabricar).
  function drawRecintos(t) {
    recintoG.clear();
    for (const n of Object.values(placedById)) {
      if (n.kind !== "recinto") continue;
      let poly = footPoly(recintoFootRect(n));
      if (n.drag) poly = poly.map((v, i) => (i % 2 === 0 ? v + n.drag.dx : v + n.drag.dy)); // sub-rama 3: arrastre vivo del bloque
      const agent = !!n.hasNucleo;
      if (agent) {
        // F2 · BALDOSA CON RELIEVE: cara superior + dos cantos. El MCP sigue
        // siendo su caja cerrada en makeToolPiece; acá nunca dibujamos el interior.
        const p = [];
        for (let i = 0; i < 8; i += 2) p.push({ x: poly[i], y: poly[i + 1] });
        const depth = 9;
        recintoG.poly([p[1].x, p[1].y, p[2].x, p[2].y, p[2].x, p[2].y + depth, p[1].x, p[1].y + depth])
          .fill({ color: 0x302767, alpha: 0.96 }).stroke({ color: 0x17142f, width: 1.5, alpha: 0.9 });
        recintoG.poly([p[2].x, p[2].y, p[3].x, p[3].y, p[3].x, p[3].y + depth, p[2].x, p[2].y + depth])
          .fill({ color: 0x211c4f, alpha: 0.98 }).stroke({ color: 0x17142f, width: 1.5, alpha: 0.9 });

        const lv = recintoLive.get(n.id) || {};
        const active = multi.running && multi.activeHop >= 0 &&
          ((multi.plan && multi.plan.eslabones || [])[multi.activeHop] || {}).agent_ref === n.data.agent_ref;
        const state = lv.errored || /^(error|roto|failed)$/.test(String(n.data.interiorEstado || ""))
          ? "error" : lv.held ? "held" : (lv.running || active) ? "working"
          : lv.crossed || n.data.interiorEstado === "done" ? "done" : "idle";
        const stateColor = { idle: 0x8d8aa8, working: 0xb389ff, held: 0xffb454,
          error: 0xff6b5e, done: 0x57e08a }[state];
        const pulse = state === "working" ? 0.5 + 0.5 * Math.sin(t * 6 + n.phase) : 0;
        recintoG.poly(poly).fill({ color: 0x51459b, alpha: 0.42 + pulse * 0.16 })
          .stroke({ color: 0xc9c6ff, width: 1.8 + pulse, alpha: 0.82 });
        const cx = p.reduce((s, q) => s + q.x, 0) / 4, cy = p.reduce((s, q) => s + q.y, 0) / 4;
        const rx = Math.max(25, Math.max(...p.map((q) => Math.abs(q.x - cx))) + 5);
        recintoG.ellipse(cx, cy + 1, rx, Math.max(13, rx * 0.36))
          .stroke({ color: stateColor, width: 2.2 + pulse * 2.4, alpha: 0.78 + pulse * 0.2 });
        n._draw = {
          structure: "baldosa", hasNucleo: n.nucleoDerived !== false,
          alephCreature: !!(n.art && n.art.__alephCreature),
          atomMark: !!n.coreArt, interiorVisible: false,
          counter: Math.max(0, Number(n.data.interiorCount) || 0),
          ring: true, ringState: state, ringColor: stateColor,
          running: state === "working", latencyVisible: !!(n.latencyChip && n.latencyChip.visible),
        };
        continue;
      }
      const rel = n.relevance || 0;                                   // C2 · relevancia (nº de hijos, normalizada 0..1)
      const wallCol = agent ? ZONE_DEF.nucleo.color : 0x8893a7;        // agente=violeta / cajón=neutro slate
      const wallGlow = agent ? ZONE_DEF.nucleo.glow : 0xc2ccdd;
      // D4 · FRONTERA VIVA · el muro ENCIENDE con el estado REAL del run (sub_agent_started/finished del
      // padre, vía recintoLive). SÓLO agente (un cajón no corre). running=viola encendido y pulso rápido;
      // held=ámbar ("espera tu OK"); error=rojo. Idle → byte-idéntico a antes (lv vacío → runK=0).
      const lv = recintoLive.get(n.id) || {};
      const liveRun = agent && !!lv.running, liveHeld = agent && !!lv.held, liveErr = agent && !!lv.errored;
      const runK = liveRun ? (0.55 + 0.45 * Math.sin(t * 6 + n.phase)) : 0;   // pulso RÁPIDO event-driven mientras corre
      const litCol = liveErr ? 0xff6b5e : liveHeld ? 0xffb454 : wallCol;      // error > held > run/idle
      const litStroke = (liveRun || liveHeld || liveErr);
      // 2b · el AGENTE lleva CÍRCULO como cara (canon del video); su muro recede a placa tenue.
      // El cajón conserva la caja de siempre. La interacción vive en el footprint — intacta.
      recintoG.poly(poly).fill({ color: litCol, alpha: (agent ? 0.05 : 0.08) + rel * 0.05 + runK * 0.14 + (liveHeld ? 0.10 : 0) + (liveErr ? 0.12 : 0) });
      recintoG.poly(poly).stroke({ color: 0x0b0e14, width: 3.5, alpha: agent ? 0.12 : 0.22 });
      recintoG.poly(poly).stroke({ color: litStroke ? litCol : wallGlow, width: agent ? (1 + runK * 2 + (liveHeld || liveErr ? 1.5 : 0)) : 2, alpha: (agent ? 0.3 : 0.74) + runK * 0.5 + (liveHeld || liveErr ? 0.4 : 0) });
      // HALO que LATE — SÓLO agente: ahora late sobre el ANILLO elíptico iso (la cara nueva), mismo
      // ritmo del Núcleo. C2 · la relevancia (nº de hijos) lo ENGROSA e INTENSIFICA — intacto.
      let haloAlpha = 0, haloWidth = 0, ringRadius = 0;
      if (agent) {
        const cx = (poly[0] + poly[2] + poly[4] + poly[6]) / 4, cy = (poly[1] + poly[3] + poly[5] + poly[7]) / 4;
        for (let i = 0; i < 8; i += 2) ringRadius = Math.max(ringRadius, Math.abs(poly[i] - cx));
        ringRadius += 14;                                              // aire entre muro y anillo
        // D4 · corriendo → el halo late MÁS RÁPIDO (event-driven) y MÁS FUERTE; held/error lo tiñen.
        const freq = liveRun ? 6 : 3;                                  // idle = ritmo del Núcleo (sin(t*3)); running = doble
        const pulse = 0.5 + 0.5 * Math.sin(t * freq + n.phase);
        const runBoost = liveRun ? 1 : 0;
        const haloCol = liveErr ? 0xff6b5e : liveHeld ? 0xffb454 : ZONE_DEF.nucleo.glow;
        haloWidth = 1.6 + 2.4 * pulse + rel * 3 + runBoost * (2 + 2.5 * pulse);
        haloAlpha = 0.2 + 0.32 * pulse + rel * 0.28 + runBoost * 0.25;  // C2 · relevancia LEÍBLE · D4 · encendido de run
        recintoG.ellipse(cx, cy, ringRadius, ringRadius * 0.55).fill({ color: litCol, alpha: 0.05 + rel * 0.04 + runK * 0.05 });
        recintoG.ellipse(cx, cy, ringRadius, ringRadius * 0.55).stroke({ color: haloCol, width: haloWidth, alpha: haloAlpha });
        recintoG.ellipse(cx, cy, ringRadius + 5, (ringRadius + 5) * 0.55).stroke({ color: litCol, width: 1, alpha: 0.16 });
      } else if (rel > 0) {
        // C2 · cajón con hijos: anillo de relevancia (no LATE como el agente, pero brilla más con más hijos)
        recintoG.poly(poly).stroke({ color: wallGlow, width: 1.5 + rel * 2.5, alpha: 0.2 + rel * 0.4 });
      }
      // §3.3 · GLIFO PORTAL — SÓLO recinto-AGENTE (un cajón no es un mundo): micro-ícono iso de 3 láminas
      // apiladas en la esquina superior del muro = "hay MUNDO adentro / entra". Mismo material del diorama
      // (violeta nucleo + stroke tenue del muro). Aparece colapsado también (promesa de mundo interior).
      if (agent) {
        let ci = 0, cyMin = Infinity;                                  // vértice de MENOR y del muro = esquina superior
        for (let i = 0; i < 8; i += 2) if (poly[i + 1] < cyMin) { cyMin = poly[i + 1]; ci = i; }
        const px = poly[ci], py = poly[ci + 1] - 9, pw = 8.5, ph = 4, gap = 3.6;
        const portalPulse = liveRun ? (0.5 + 0.5 * Math.sin(t * 6 + n.phase)) : 0;   // D4 · el portal PULSA mientras corre (reusa el canal de halo)
        for (let L = 2; L >= 0; L--) {                                 // 3 láminas (de atrás hacia adelante)
          const oy = py - L * gap;
          recintoG.poly([px, oy - ph, px + pw, oy, px, oy + ph, px - pw, oy])
            .fill({ color: ZONE_DEF.nucleo.color, alpha: 0.16 + 0.13 * (2 - L) + portalPulse * 0.22 })
            .stroke({ color: ZONE_DEF.nucleo.glow, width: 1 + portalPulse, alpha: 0.45 + 0.14 * (2 - L) + portalPulse * 0.3 });
        }
        // D4 · lo que CRUZA de vuelta al padre = el RESULTADO bridged (§1). Terminado con result cruzado →
        // punto teal "el bridge volvió". NO son los pasos internos del hijo (esos NO cruzan — quedan en el log).
        if (lv.crossed) recintoG.circle(px + pw + 4, py - 2 * gap, 2.4).fill({ color: 0x57e08a, alpha: 0.9 });
      }
      const stackCount = n.collapsed ? drawRecintoStack(n, poly, agent ? ZONE_DEF.nucleo.glow : wallGlow) : 0;
      n._draw = { hasNucleo: agent, collapsed: !!n.collapsed, wallColor: wallCol, haloActive: agent, haloAlpha, haloWidth, stackCount, relevance: rel,
                  ring: agent, ringRadius, portal: agent,   // 2b · cara-círculo · §3.3 · portal = pieza-mundo (agente), medible
                  // D4 · FRONTERA VIVA medible: estado del run desde eventos ESTRUCTURALES REALES del padre.
                  running: liveRun, held: liveHeld, errored: liveErr, crossed: agent && !!lv.crossed,
                  runDegraded: agent && !!_antiGrift.degraded,          // FIX trivial (§9) · RUN-level (modelo del PADRE), NO la degradación propia del hijo — renombrado de `degraded` para que ningún consumidor lo lea como interior del hijo
                  // FIX C (§9·C · grift-inverso) · busCrosses DERIVADO del modelo, no de un default: el bus B2
                  // sólo cruza si existe una relación `comparte` al recinto (= hay pieza-memoria Y el agente es
                  // miembro del bus). Así el campo medible NO puede discrepar del cable teal (rebuildModel) ni
                  // del runtime (projection sólo emite recipe.memory si hay bloque memoria). Sin memoria → false.
                  busCrosses: agent && model.relationships.some((r) => r.kind === "comparte" && r.to === n.id) && (n.data.sharesMemory !== false) };
    }
  }
  // P3-CIERRE aplicado a los nombres que son identidad: no truncar y no permitir
  // que dos chips de sub-Aleph adyacentes ocupen el mismo rectángulo de pantalla.
  function layoutAgentLabels() {
    const agents = Object.values(placedById)
      .filter((n) => n.kind === "recinto" && n.hasNucleo && n.chip && n.chip.visible !== false)
      .sort((a, b) => (a.gfx.y - b.gfx.y) || (a.gfx.x - b.gfx.x));
    const accepted = [];
    for (const n of agents) {
      let tries = 0;
      while (tries++ < 8) {
        const b = n.chip.getBounds();
        const hit = accepted.find((a) => b.x < a.x + a.width + 4 && b.x + b.width + 4 > a.x &&
          b.y < a.y + a.height + 4 && b.y + b.height + 4 > a.y);
        if (!hit) { accepted.push(b); break; }
        n.chip.position.y -= (Math.min(b.height, hit.height) + 6) / Math.max(0.42, cam.scale);
      }
    }
  }
  function agentLabelState() {
    const labels = Object.values(placedById)
      .filter((n) => n.kind === "recinto" && n.hasNucleo && n.chip)
      .map((n) => { const b = n.chip.getBounds(); return { id: n.id, text: n.chip.text, x: b.x, y: b.y, width: b.width, height: b.height }; });
    let overlaps = 0;
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
      const a = labels[i], b = labels[j];
      if (a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y) overlaps++;
    }
    return { labels, overlaps };
  }
  // STACK ("hay algo adentro") cuando el recinto está COLAPSADO: cards apiladas sobre el centro del
  // footprint (molde forgeLayoutFan: glifos en torno al padre, acá apilados). Devuelve children.length.
  function drawRecintoStack(n, poly, col) {
    const cx = (poly[0] + poly[2] + poly[4] + poly[6]) / 4, cy = (poly[1] + poly[3] + poly[5] + poly[7]) / 4;
    const cnt = n.children.length, k = Math.min(cnt, 4);
    for (let i = k - 1; i >= 0; i--) {
      const oy = cy - 14 - i * 6;
      recintoG.poly([cx, oy - 8, cx + 15, oy, cx, oy + 8, cx - 15, oy])
        .fill({ color: 0x121724, alpha: 0.95 }).stroke({ color: col, width: 1.4, alpha: 0.55 + 0.1 * (k - i) });
    }
    return cnt;
  }

  // 2a · criatura del recinto-agente: se ancla al CENTRO del footprint cada frame
  // (recintoCenter ya trae el offset del arrastre vivo → sigue drag/rotación/colapso gratis).
  function tickRecintoArt(n, t) {
    const ctr = recintoCenter(n);
    n.art.position.set(ctr.x - n.gfx.x, ctr.y - n.gfx.y - 15);
    n.art.scale.set(0.72 + 0.025 * Math.sin(t * 2 + n.phase));
    if (n.chip) {                                               // 2b · chip sobre el mini-Aleph, tamaño de pantalla constante
      n.chip.position.set(n.art.position.x, n.art.position.y - 38);
      n.chip.scale.set(multi.fixedControls ? 1 / cam.scale : 1);
    }
    if (n.port) {
      n.port.position.set(n.art.position.x + 31, n.art.position.y + 21);
      n.port.scale.set(multi.fixedControls ? 1 / cam.scale : 1); // control zoom-invariante
    }
    if (n.latencyChip) {
      const ms = multi.latencies.get(n.id);
      n.latencyChip.visible = !!multi.running && Number.isFinite(ms);
      n.latencyChip.text = n.latencyChip.visible ? `${Math.round(ms)} ms` : "";
      n.latencyChip.position.set(n.art.position.x, n.art.position.y + 25);
      n.latencyChip.scale.set(multi.fixedControls ? 1 / cam.scale : 1);
    }
  }

  // PULSO+TABLERO · AURA DE ESTADO sobre las piezas que YA pulsan (cero geometría nueva). ELECCIÓN de
  // implementación: NO va en tickTile (kernel de animación a nivel de MÓDULO, fuera de este closure → no
  // ve `tileLive`/`AURA_STATE`), sino en un PASE POR-FRAME acá dentro (espejo de drawRecintos, que hace lo
  // mismo para el recinto-agente y también corre en el heartbeat). El anillo se dibuja como HIJO del
  // contenedor de la pieza (index 0 + zIndex −1 → SIEMPRE bajo art+label, jamás ocluye el glifo) para que
  // viaje con el transform de la pieza (pan/zoom/rotación/posición/escala-de-nacimiento) GRATIS — igual que
  // el zócalo. Sin entrada en tileLive → aura oculta → dibujo BYTE-IDÉNTICO a hoy. Radio derivado de los
  // bounds del arte (cacheado en n._auraR; el arte no cambia de tamaño). Intensidad RIDE n.glow (el canal
  // existente que ecoFire sube y ecoReturn deja decaer) → el aura late con el mismo pulso que la pieza.
  function auraRadiusOf(n) {
    try { const b = n.art.getLocalBounds(); const rr = Math.max(Math.abs(b.x), Math.abs(b.x + b.width)); return rr > 10 ? rr + 8 : 34; }
    catch (_) { return 34; }
  }
  function drawTileAuras(t) {
    for (const n of Object.values(placedById)) {
      if (n.kind !== "tile") continue;                              // GUARD: el recinto-agente lleva su HALO en drawRecintos → jamás doble-anillo
      const lv = tileLive.get(n.id);
      if (!lv || n.hidden || !n.gfx || n.gfx.destroyed) { if (n.aura) n.aura.visible = false; continue; } // sin estado / oculto en recinto colapsado → sin aura
      if (!n.aura) { n.aura = new PIXI.Graphics(); n.aura.eventMode = "none"; n.aura.zIndex = -1; n.gfx.addChildAt(n.aura, 0); } // bajo art+label
      const P = AURA_STATE[lv.state] || AURA_STATE.calling;
      const active = lv.state === "calling" || lv.state === "held"; // trabajando / esperando OK → late RÁPIDO; asentada (done/error) → LENTO
      const pulse = 0.5 + 0.5 * Math.sin(t * (active ? 6 : 3) + n.phase);
      const gk = 0.3 + 0.7 * Math.min(1, n.glow);                   // RIDE el canal glow existente (ecoFire↑ / ecoReturn↓); piso 0.3 = legible aun sin glow
      const r = n._auraR || (n._auraR = auraRadiusOf(n));
      const ax = 0, ay = -6;                                        // centro del glifo (domain.position, makeToolPiece)
      const a = n.aura; a.visible = true; a.clear();
      a.ellipse(ax, ay, r, r * 0.62).fill({ color: P.core, alpha: (0.05 + 0.06 * pulse) * gk });
      a.ellipse(ax, ay, r, r * 0.62).stroke({ color: P.ring, width: (1.4 + 2.2 * pulse) * gk, alpha: (0.28 + 0.34 * pulse) * gk });
      a.ellipse(ax, ay, r + 4, (r + 4) * 0.62).stroke({ color: P.core, width: 1, alpha: 0.14 * gk });
    }
  }

  // §3 · glifo ESTÁTICO del semáforo de verdad: un punto de color en el hombro de la pieza. Cero pulso
  // (lo distingue del aura de run). color = número PIXI (viene del motor vía cuarto.tileVerdad); null/
  // ausente → sin punto. Es hijo `n.verdad` del gfx (viaja con pan/zoom), dibujado sobre el glifo.
  const VERDAD_RING = 0x0b0e14;   // aro oscuro para contraste en cualquier fondo
  function drawTileVerdad() {
    for (const n of Object.values(placedById)) {
      if (n.kind !== "tile") { if (n.verdad) n.verdad.visible = false; continue; }
      const v = tileVerdad.get(n.id);
      // [reforma · g] con anillo, el color YA lo dice el anillo: dos marcas del mismo estado en
      // la misma pieza es ruido. El punto queda para las piezas SIN tools (memoria, contexto…).
      const conAnillo = !!((n.data && n.data.tools) || []).length;
      if (conAnillo || !v || v.color == null || n.hidden || !n.gfx || n.gfx.destroyed) { if (n.verdad) n.verdad.visible = false; continue; }
      if (!n.verdad) { n.verdad = new PIXI.Graphics(); n.verdad.eventMode = "none"; n.verdad.zIndex = 40; n.gfx.addChild(n.verdad); }
      const r = n._auraR || (n._auraR = auraRadiusOf(n));
      const cx = r * 0.62, cy = -6 - r * 0.5;   // hombro superior-derecho del glifo (centro en 0,-6)
      const g = n.verdad; g.visible = true; g.clear();
      g.circle(cx, cy, 4.6).fill({ color: VERDAD_RING, alpha: 0.9 });
      g.circle(cx, cy, 3.4).fill({ color: v.color, alpha: 1 });
    }
  }

  /* [reforma · g] EL ANILLO — FIRMA, NO DISPLAY.
   * Dice exactamente tres cosas y ninguna más:
   *   EXISTE  → la pieza tiene tools adentro (sin tools no hay anillo, y eso también es un dato)
   *   COLOR   → el PEOR estado real del motor de verdad para esa pieza (nunca un color inventado)
   *   NÚMERO  → cuántas tools son
   * Prohibido lo que lo convertiría en display: segmentos por tool, nombres, íconos por tool.
   * Para eso está el widget (se abre con [Ver tools]) — el anillo es la firma que se lee de un
   * vistazo desde el otro lado del cuarto, no una lista dibujada en miniatura.
   * Estático a propósito: el pulso es de la corrida (drawTileAuras), no del inventario. */
  const ANILLO_NEUTRO = 0x8a93a6;   // sin lectura del motor todavía → gris, jamás verde
  function drawTileAnillo() {
    for (const n of Object.values(placedById)) {
      const tools = (n.kind === "tile" && n.data && n.data.tools) || [];
      const vivo = n.kind === "tile" && tools.length && !n.hidden && n.gfx && !n.gfx.destroyed;
      if (!vivo) { if (n.anillo) n.anillo.visible = false; continue; }
      if (!n.anillo) {
        n.anillo = new PIXI.Container(); n.anillo.eventMode = "none"; n.anillo.zIndex = 39;
        n.anilloG = new PIXI.Graphics();
        n.anilloN = new PIXI.Text({ text: "", style: { fontFamily: "Hanken Grotesk, system-ui, sans-serif",
          fontSize: 9, fontWeight: "500", fill: 0xffffff, align: "center" } });
        n.anilloN.anchor.set(0.5);
        n.anillo.addChild(n.anilloG, n.anilloN);
        n.gfx.addChild(n.anillo);
      }
      const v = tileVerdad.get(n.id);
      const col = (v && v.color != null) ? v.color : ANILLO_NEUTRO;
      // P6 · la geometría del aro sale de anilloRadii() — FUENTE ÚNICA compartida con la física
      // (así el radio de colisión y el radio dibujado no pueden desincronizarse). El CACHE `_auraR`
      // se escribe ACÁ, en el draw, donde los bounds del sprite ya son definitivos; la física lo lee
      // sin escribirlo. Dibujo byte-idéntico al de antes: a = _auraR·0.78 y b = a·0.62.
      if (!n._auraR) n._auraR = auraRadiusOf(n);
      const { a: r, b: rb } = anilloRadii(n);
      const cy = -6;
      const g = n.anilloG; n.anillo.visible = true; g.clear();
      g.ellipse(0, cy, r, rb).stroke({ color: col, width: 1.6, alpha: 0.85 });
      // el número, en una pastilla sobre el aro (abajo-derecha) — un dato, no una leyenda
      const px = r * 0.72, py = cy + rb * 0.72;
      g.circle(px, py, 6.4).fill({ color: PALT.labelStroke, alpha: 0.92 });
      g.circle(px, py, 6.4).stroke({ color: col, width: 1.2, alpha: 0.95 });
      n.anilloN.text = String(tools.length);
      n.anilloN.position.set(px, py);
      n.anilloN.style.fill = col;
      n._anilloPt = { x: px, y: py, r: 9 };   // [reforma·k] hit del +N → modo trabajo enfocado
      // [reforma · k] PUNTO VIVO: si una tool de esta pieza corre mientras mirás el modo MCPs,
      // la etiqueta lo dice. No se llama "en vivo" en ninguna parte: es un punto, y punto.
      if (!workMode) {
        let activa = false;
        for (const [k, v] of toolLive) { if (v === "calling" && k.startsWith(n.id + "::")) { activa = true; break; } }
        if (activa) g.circle(-px, py, 3.2).fill({ color: 0x22c55e, alpha: 0.95 });
      }
    }
  }

  /* ══ [reforma · k] LOS DOS MODOS ═══════════════════════════════════════════════════
   * MODO MCPs (default, compacto) — una pieza por MCP. Es el estado de reposo.
   * MODO TRABAJO (desplegado)     — cada tool BAJA como pieza, con forma de herramienta,
   *                                 con el color de SU zona y su nombre REAL debajo.
   *
   * Tres reglas que lo mantienen honesto:
   *  · las piezas-MCP NO se mueven al cambiar de modo (el cuarto no se rebaraja bajo el pie);
   *  · el modo trabajo JAMÁS dibuja orden ni flechas — eso es el Método, no el inventario:
   *    la línea al padre es un lazo de pertenencia, sin punta y sin dirección;
   *  · la ACTIVIDAD es una CAPA, no un modo: una tool corriendo late en los dos modos. En
   *    modo MCPs late en la etiqueta de su pieza (punto vivo); acá late la tool.
   * Inactivo no es "apagado": es la VERDAD TÉCNICA — el nombre con el que el modelo la llama.
   */
  const workLayer = new PIXI.Container(); workLayer.zIndex = 6; workLayer.eventMode = "none";
  world.addChild(workLayer);

  function limpiarWork() {
    workNodes.forEach((w) => { try { w.gfx.destroy({ children: true }); } catch (e) {} });
    workNodes = [];
    workLayer.removeChildren();
  }
  /* P3-CIERRE · ETIQUETAS DE TOOLS. El abanico angular anterior comprimía N nombres en
   * el mismo semicírculo y, desde cinco tools, garantizaba solapes. Acá se empaquetan las
   * CAJAS REALES del texto en una mesa común bajo sus piezas: columnas tan anchas como su
   * label y filas tan altas como el label más alto. 46+ tools no cambian el gap: agregan
   * filas. La lista sigue perteneciendo a cada MCP por el tether, sin fingir orden de run. */
  const TOOL_LABEL_MAX_W = 116, TOOL_LABEL_GAP_X = 14, TOOL_LABEL_GAP_Y = 10;
  function layoutEtiquetasTools(items) {
    const n = items.length;
    if (!n) return;
    const cols = Math.max(1, Math.min(10, Math.ceil(Math.sqrt(n * 1.45))));
    const rows = Math.ceil(n / cols);
    const colW = Array(cols).fill(0), rowH = Array(rows).fill(0);
    items.forEach((w, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      colW[col] = Math.max(colW[col], Math.ceil(w.label.width) + TOOL_LABEL_GAP_X);
      // 12px desde el centro de la llave al inicio del texto + aire hasta la fila siguiente.
      rowH[row] = Math.max(rowH[row], 12 + Math.ceil(w.label.height) + TOOL_LABEL_GAP_Y);
    });
    const totalW = colW.reduce((a, b) => a + b, 0);
    const colX = []; let x = -totalW / 2;
    for (let col = 0; col < cols; col++) { colX[col] = x + colW[col] / 2; x += colW[col]; }
    const rowY = []; let y = 42;
    for (let row = 0; row < rows; row++) { rowY[row] = y; y += rowH[row]; }
    items.forEach((w, i) => {
      w.offsetX = colX[i % cols];
      w.offsetY = rowY[Math.floor(i / cols)];
    });
  }
  function rebuildWork() {
    limpiarWork();
    if (!workMode) return;
    for (const n of Object.values(placedById)) {
      if (n.kind !== "tile" || n.hidden) continue;
      const srv = n.data && (n.data.server || n.data.ref);
      if (workFocus && srv !== workFocus) continue;
      const det = (n.data.toolsDetail && n.data.toolsDetail.length)
        ? n.data.toolsDetail : ((n.data.tools || []).map((t) => ({ name: t, zone: n.data.role || n.data.zone })));
      det.forEach((d, i) => {
        const zone = d.zone || n.data.role || n.data.zone || "mesa";
        const col = (ZONE_DEF[zone] || ZONE_DEF.mesa).color;
        const c = new PIXI.Container();
        const g = new PIXI.Graphics();
        // FORMA DE HERRAMIENTA (la llave open-end de makeToolPiece, acá visible y en chico):
        // en modo trabajo lo que se ve son herramientas, no logos — el logo es del MCP.
        g.poly([-2, 8, -2, -4, -5.5, -4, -5.5, -11, -2, -11, -2, -7.5,
                2, -7.5, 2, -11, 5.5, -11, 5.5, -4, 2, -4, 2, 8])
          .fill({ color: mix(col, 0xffffff, 0.3) }).stroke({ color: mix(col, 0x000000, 0.4), width: 1 });
        g.rotation = -0.42;
        const halo = new PIXI.Graphics();
        const label = new PIXI.Text({ text: d.name, style: {
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 8.5,
          fill: PALT.labelFill, stroke: { color: PALT.labelStroke, width: 3 }, align: "center",
          wordWrap: true, wordWrapWidth: TOOL_LABEL_MAX_W, breakWords: true, whiteSpace: "normal" } });
        label.anchor.set(0.5, 0); label.position.set(0, 12);
        c.addChild(halo, g, label);
        workLayer.addChild(c);
        workNodes.push({ gfx: c, halo, label, parent: n, tool: d.name, i, total: det.length, col,
                         offsetX: 0, offsetY: 0 });
      });
    }
    // Una sola grilla para todo lo desplegado: incluso el modo global no permite que dos
    // MCPs pisen sus etiquetas entre sí. En focus, naturalmente, la mesa queda bajo uno.
    layoutEtiquetasTools(workNodes);
  }
  function drawWork(t) {
    if (!workMode) { if (workNodes.length) limpiarWork(); return; }
    if (workDirty) { workDirty = false; rebuildWork(); }
    const padres = [...new Set(workNodes.map((w) => w.parent))]
      .filter((p) => p && !p.hidden && p.gfx && !p.gfx.destroyed);
    const anchorX = padres.length ? padres.reduce((s, p) => s + p.sx, 0) / padres.length : 0;
    const anchorY = padres.length ? Math.max(...padres.map((p) => p.baseY)) + 16 : 0;
    for (const w of workNodes) {
      const p = w.parent;
      if (!p || p.hidden || !p.gfx || p.gfx.destroyed) { w.gfx.visible = false; continue; }
      w.gfx.visible = true;
      w.gfx.position.set(anchorX + w.offsetX, anchorY + w.offsetY);
      const live = toolLive.get(p.id + "::" + w.tool);
      const activa = live === "calling";
      const pulse = activa ? 0.5 + 0.5 * Math.sin(t * 6 + w.i) : 0;
      w.halo.clear();
      if (activa) w.halo.circle(0, -2, 13 + pulse * 5).stroke({ color: w.col, width: 1.6, alpha: 0.3 + pulse * 0.45 });
      else if (live === "error") w.halo.circle(0, -2, 11).stroke({ color: 0xef4444, width: 1.4, alpha: 0.55 });
      w.gfx.alpha = activa ? 1 : 0.9;
    }
    // el LAZO de pertenencia: sin punta, sin dirección, sin orden (eso es el Método)
    workTether.clear();
    for (const w of workNodes) {
      if (!w.gfx.visible) continue;
      const p = w.parent;
      workTether.moveTo(p.sx, p.baseY).lineTo(w.gfx.x, w.gfx.y - 2)
        .stroke({ color: w.col, width: 1, alpha: 0.22 });
    }
  }
  const workTether = new PIXI.Graphics(); workTether.zIndex = 5; workTether.eventMode = "none";
  world.addChild(workTether);

  // ── heartbeat ───────────────────────────────────────────────────────────────
  let t = 0;
  app.ticker.add((tick) => {
    t += tick.deltaMS / 1000;
    if (floorGrowth) {
      floorGrowth.t += tick.deltaMS / 260;
      floorDirty = true;
      if (floorGrowth.t >= 1) floorGrowth = null;
    }
    refreshVisibleFloor();
    // D2 · push-in / pull-back: lerpea cam.{x,y,scale} hacia el destino (ease-out) y maneja applyCam.
    // Mientras dura, ES quien mueve la cámara (fitAll está congelado si depth>0). Al terminar, se limpia.
    if (camTween) {
      camTween.t += tick.deltaMS / 1000;
      const e = Math.min(1, camTween.t / camTween.dur), s = easeOutCubic(e);
      cam.x = camTween.fx + (camTween.tx - camTween.fx) * s;
      cam.y = camTween.fy + (camTween.ty - camTween.fy) * s;
      cam.scale = camTween.fs + (camTween.ts - camTween.fs) * s;
      applyCam();
      if (e >= 1) camTween = null;
    }
    if (sceneTween) {
      sceneTween.t += tick.deltaMS / 1000;
      const e = Math.min(1, sceneTween.t / sceneTween.dur);
      const outFrom = sceneTween.outFrom ?? 1, outTo = sceneTween.outTo ?? 0;
      const inFrom = sceneTween.inFrom ?? 0, inTo = sceneTween.inTo ?? 1;
      if (sceneTween.out) sceneTween.out.alpha = outFrom + (outTo - outFrom) * e;
      if (sceneTween.in) sceneTween.in.alpha = inFrom + (inTo - inFrom) * e;
      if (e >= 1) {
        if (sceneTween.out) {
          sceneTween.out.visible = sceneTween.hideOut === false;
          sceneTween.out.alpha = outTo;
          if (sceneTween.destroyOut) {
            try { cameraRoot.removeChild(sceneTween.out); sceneTween.out.destroy({ children: true }); } catch (_) {}
          }
        }
        if (sceneTween.in) sceneTween.in.alpha = inTo;
        sceneTween = null;
      }
    }
    for (const n of animated) {
      n.glow = approach(n.glow, n.glowTarget, 0.16);
      if (n.kind === "zone") tickZone(n);
      else if (n.kind === "tile") { tickTile(n, t); if (n.label && n.label.visible) n.label.scale.set(1 / cam.scale); } // label = tamaño de pantalla constante
      else if (n.kind === "nucleo") tickNucleo(n, t);
      else if (n.kind === "recinto" && n.art) tickRecintoArt(n, t);   // 2a · mini-Aleph del agente (centro del footprint)
      else if (n.kind === "conexion") tickConexion(n, t);
      else if (n.kind === "adder" && n.redraw) n.redraw();
    }
    for (let i = ecoTokens.length - 1; i >= 0; i--) {
      const k = ecoTokens[i]; k.t += tick.deltaMS / k.dur;
      const e = Math.min(1, k.t), s = e * e * (3 - 2 * e);
      k.g.position.set(k.from.x + (k.to.x - k.from.x) * s, k.from.y + (k.to.y - k.from.y) * s);
      k.g.scale.set(1 + 0.5 * Math.sin(e * Math.PI));
      if (k.t >= 1) { k.g.destroy(); ecoTokens.splice(i, 1); k.resolve(); }
    }
    tickGhostGlow();                                                 // SLOTS·B · ghost fluido + foco per-celda (previsualización)
    tickFloorBreath();                                               // SLOTS·C · el piso respira (proximidad + modo-colocar)
    drawChildRoom(activeChildScene, t);                              // F2 · Cuarto hijo = piso+nucleo+cables+piezas
    if (!activeChildScene) {
      redrawZones(); drawRecintos(t); layoutAgentLabels(); drawTileAuras(t); drawTileVerdad(); drawTileAnillo(); drawWork(t); rebuildLinks(t); drawGates(t);
      if (viewMode !== "off") drawView(t);    // overlays del padre quedan congelados y completos al atenuarse
      drawForge(t);
    }
    linkGfx.alpha = (viewMode !== "off" ? 0.3 : (running ? 0.9 : 0.55)) + 0.12 * Math.sin(t * 2);
  });

  // SLOTS·A — sin buildGrowAdders al montar: el piso nace LIMPIO (0 adders); el auto-place balanceado
  // reemplaza al ＋ manual. El alias buildGrowAdders/refreshAdders sigue definido pero es no-op.
  rebuildModel();    // F2 · modelo inicial (sólo el Núcleo hasta que se coloquen piezas)

  // ── TEMA vivo: repinta lo que vive DENTRO del canvas (el chrome HTML es CSS) ──
  function applyTheme(mode) {
    PALT = (mode === "light") ? THEME.light : THEME.dark;
    const light = PALT === THEME.light;
    try { app.renderer.background.color = PALT.bg; } catch (e) {}
    retintFloor();
    for (let i = 0; i < floorNodes.length; i++) floorNodes[i].gfx.visible = i < visibleFloorCount && !light;
    for (const s of wallSprites) { s.tint = PALT.wall; s.visible = !light; } // paredes (atlas oscuro) ocultas en light
    lightFloor.visible = true; redrawLightFloor();   // procedural en ambos temas
    for (const n of zoneNodes) {
      if (n.tag)  n.tag.style.fill  = PALT.zoneTagGlow ? ZONE_DEF[n.role].glow : ZONE_DEF[n.role].color;
      if (n.tag2) n.tag2.style.fill = PALT.zoneSub;
    }
    for (const id in placedById) {
      const lb = placedById[id].label;
      if (lb) { lb.style.fill = PALT.labelFill; lb.style.stroke = { color: PALT.labelStroke, width: 3 }; }
    }
  }
  // arranca matcheando el tema de la página (sin flash); dark = idéntico a antes.
  try { applyTheme(document.documentElement.getAttribute("data-theme")); } catch (e) {}

  // [i18n Ola D] re-lee window.t para los labels HORNEADOS del canvas (zonas + lente):
  // el diorama se re-rotula al CAMBIAR locale EN VIVO (antes solo en build/reload). Lo
  // dispara cuarto.pixi.html ante el evento 'aleph:langchange' de i18n.setLang.
  function relabel() {
    ZONE_DEF.fuentes.label = TR("cuarto.zone.lee.label", "Lee");
    ZONE_DEF.fuentes.sub = TR("cuarto.zone.lee.sub", "trae dato");
    ZONE_DEF.mesa.label = TR("cuarto.zone.procesa.label", "Procesa");
    ZONE_DEF.mesa.sub = TR("cuarto.zone.procesa.sub", "transforma");
    ZONE_DEF.entrega.label = TR("cuarto.zone.actua.label", "Actúa");
    ZONE_DEF.entrega.sub = TR("cuarto.zone.actua.sub", "saca");
    ZONE_DEF.nucleo.label = TR("cuarto.zone.nucleo.label", "Núcleo");
    ZONE_DEF.nucleo.sub = TR("cuarto.zone.nucleo.sub", "el agente");
    for (const n of zoneNodes) {
      const def = ZONE_DEF[n.role]; if (!def) continue;
      if (n.tag) n.tag.text = def.label;
      if (n.tag2) { n.tag2.text = "· " + def.sub; n.tag2.position.set(n.tag.width + 5, 1); }
    }
    for (const n of Object.values(placedById)) if (n.rechip) n.rechip();   // 2b · chips de agente re-traducidos en vivo
    // lente: drawView re-lee LENS_GROUPS cada frame → con actualizar el array alcanza.
    LENS_GROUPS[0].verb = TR("cuarto.lens.lee.verb", "lee"); LENS_GROUPS[0].sub = TR("cuarto.zone.lee.sub", "trae dato");
    LENS_GROUPS[1].verb = TR("cuarto.lens.procesa.verb", "procesa"); LENS_GROUPS[1].sub = TR("cuarto.zone.procesa.sub", "transforma");
    LENS_GROUPS[2].verb = TR("cuarto.lens.actua.verb", "actúa"); LENS_GROUPS[2].sub = TR("cuarto.zone.actua.sub", "saca");
  }

  // ── host-facing API ─────────────────────────────────────────────────────────
  const api = {
    app, scene, origin, grid, relabel,
    /** conmuta el tema del canvas en vivo ("light"|"dark") — el chrome lo hace el CSS. */
    setTheme: applyTheme,
    beginDrag, updateDrag, endDrag, cancelDrag, screenToCell,
    placeTile(tool, gridX, gridY) {
      // POSICIÓN · sin celda explícita → (1) CRECE el mundo al conteo (densidad ≤0.60) ANTES de poblar,
      // (2) HUECO BALANCEADO (la pieza nace donde menos amontona). Con celda (drag-drop / rehidratar) se
      // respeta tal cual: lo manual manda (no se fuerza expansión).
      if (gridX == null || gridY == null) {
        const next = occupancy.size + 1;                  // celdas ocupadas TRAS colocar esta pieza
        growToN(next);                                    // EXPANDIR primero → DESPUÉS poblar (orden, no al revés)
        const dens = next / Math.pow(N - 1, 2);           // capacidad real = (N−1)² (fila/col 0 = paredes)
        if (dens > DENSITY_MAX) console.warn(`[cuarto] densidad ${dens.toFixed(3)} > ${DENSITY_MAX} (n=${next}, N=${N}) — grilla saturada`);
        const c = balancedFreeCell(); if (!c) return null; gridX = c.gx; gridY = c.gy;
      } else growFloorNear(gridX, gridY);
      const n = placeTileInternal(tool, gridX, gridY);
      if (n) onTilePlaced(tool.id, gridX, gridY, n.data.role);
      return n ? { id: tool.id, gridX, gridY, role: n.data.role } : null;
    },
    removeTile,
    /** RECINTO (sub-rama 1) · fixture headless: crea un recinto (AGENTE si nucleo/agent_ref, CAJÓN si
     *  sólo children) con su footprint w×h SELLADO y sus hijos en occupancy LOCAL. Devuelve {id,gridX,
     *  gridY,w,h,hasNucleo,children}. El MURO/halo/colapso es sub-rama 2 (acá el recinto es placeholder). */
    placeRecinto(rect, childrenTools) {
      rect = rect || {};
      const kids = childrenTools || rect.children || [];
      const w = Math.max(1, rect.w || (rect.footprint && rect.footprint.w) || Math.min(Math.max(1, kids.length), 3));
      const h = Math.max(1, rect.h || (rect.footprint && rect.footprint.h) || Math.ceil(Math.max(1, kids.length) / w));
      let gx = rect.gridX, gy = rect.gridY;
      if (gx == null || gy == null) { const free = firstFootprintCell(w, h); if (!free) return null; gx = free.gx; gy = free.gy; }
      // 2c-fix: normalizar nucleo ANTES de decidir atom — con hasNucleo:true el atom debe ser
      // "agente" (antes isAgentPiece(rect) corría sin ver hasNucleo → data.atom quedaba "recinto"
      // y el inspector trataba al sub-agente como TOOL).
      const nuc = rect.nucleo != null ? rect.nucleo : !!rect.hasNucleo;
      const tool = { id: rect.id || ("recinto-" + Object.keys(placedById).length), label: rect.label || "Recinto",
        atom: rect.atom || (nuc ? "agente" : "recinto"), nucleo: nuc,
        agent_ref: rect.agent_ref || null, sharesMemory: rect.sharesMemory,   // STEP 2·B2 · membresía del bus (undefined = conectado)
        interiorCount: rect.interiorCount, interiorEstado: rect.interiorEstado,
        footprint: { w, h }, children: kids };
      const n = placeRecintoInternal(tool, gx, gy);
      if (n) onTilePlaced(n.id, gx, gy, null);
      return n ? { id: n.id, label: n.data.label, gridX: gx, gridY: gy, w, h,
        hasNucleo: n.hasNucleo, children: n.children.slice() } : null;
    },
    /** RECINTO (sub-rama 2) · estado de DIBUJO por fixture (el CONTROL/toggle es sub-rama 3): colapsar
     *  OCULTA los hijos (sus cables convergen a la caja) y muestra el STACK. NO reflowa el mesh (sub-rama 3). */
    setRecintoCollapsed(id, on = true) {
      const n = placedById[id]; if (!n || n.kind !== "recinto") return false;
      if (!!on === !!n.collapsed) return true;                  // ya está en ese estado
      on ? collapseRecinto(n) : expandRecinto(n); return true;  // sub-rama 3: reflujo real del footprint (1×1 ↔ w×h)
    },
    /** RECINTO (sub-rama 3) · alterna colapsado↔expandido (lo que hace el CLIC en el recinto). */
    toggleRecinto(id) { const n = placedById[id]; if (!n || n.kind !== "recinto") return false; toggleCollapse(n); return true; },
    /** RECINTO (sub-rama 3) · mueve el recinto como BLOQUE (recinto+hijos) a un origen de celda, con
     *  REBOTE si el footprint chocaría. Mismo camino que el drag (dropRecinto). true si movió. */
    moveRecinto(id, gx, gy) { const n = placedById[id]; if (!n || n.kind !== "recinto") return false; return dropRecinto(n, gx, gy); },
    /** RECINTO (sub-rama 3) · qué recinto EXPANDIDO contiene esa celda (id), o null — para tests de drop-into. */
    recintoOf: (gx, gy) => { const r = recintoAt(gx, gy); return r ? r.id : null; },
    /** parentId vivo de una pieza (null si suelta) — para tests de adopción/emancipación. */
    parentOf: (id) => { const n = placedById[id]; return n ? (n.parentId || null) : null; },
    /** RECINTO (sub-rama 3) · suelta una TOOL en (gx,gy) por el MISMO camino que el drag (resolveTileDrop):
     *  adopta/emancipa/re-ubica. Fixture determinístico del drop-into-recinto. */
    dropTileAt(id, gx, gy) { const n = placedById[id]; if (!n || n.kind === "recinto") return false; resolveTileDrop(n, { gridX: gx, gridY: gy, zone: zoneAt(gx, gy) }); return true; },
    /** RECINTO (sub-rama 3) · estado vivo del recinto (collapsed, footprint efectivo, hijos+hidden) — para tests. */
    recintoState: (id) => { const n = placedById[id]; if (!n || n.kind !== "recinto") return null;
      return { id, collapsed: !!n.collapsed, gx: n.gx, gy: n.gy, footprint: { w: n.footprint.w, h: n.footprint.h }, eff: { w: effW(n), h: effH(n) },
        children: n.children.map((cid) => { const c = placedById[cid]; return c ? { id: cid, hidden: !!c.hidden, gx: c.gx, gy: c.gy } : null; }).filter(Boolean) }; },
    /** RECINTO (sub-rama 2) · gancho de "hijo oculto" (verifica la convergencia del cable sin el toggle). */
    setChildHidden(id, on = true) { const n = placedById[id]; if (!n || !n.parentId) return false; setHidden(n, on); return true; },
    /** punto en pantalla (mundo, cámara-aware) de una pieza — resuelve un hijo OCULTO a la caja. Para tests/F5. */
    screenPointOf: (id) => pointOf(id),
    // 2c · posición del mini-Aleph en px CSS del canvas (el canvas puede estar estirado por CSS:
    // getGlobalPosition da coords LÓGICAS del stage) — para verificar el tap real desde afuera
    // [C · Cuarto limpio · item 1] resuelve TAMBIÉN los props (el Núcleo vive en propsById, no en
    // placedById) y cae a .gfx cuando el nodo no tiene arte propio (el Núcleo dibuja en .gfx). Sin
    // esto artScreenOf("nucleo") devolvía null y su closet se iba a la esquina: el popup del Núcleo
    // quedaba DESANCLADO mientras el de las piezas sí se pegaba al sprite. Mismo contrato de salida.
    artScreenOf: (id) => {
      const n = placedById[id] || propsById[id]; if (!n) return null;
      const g = n.art || n.gfx; if (!g) return null;
      const p = g.getGlobalPosition(), r = app.canvas.getBoundingClientRect();
      return { x: p.x * (r.width / app.screen.width), y: p.y * (r.height / app.screen.height) };
    },
    /** Centro de la baldosa en px CSS relativos al canvas (ancla del zoom semántico). */
    agentAnchorScreen: (id) => {
      const n = agentNodeFor(id); if (!n) return null;
      const c = recintoCenter(n), p = cameraRoot.toGlobal(new PIXI.Point(c.x, c.y));
      const r = app.canvas.getBoundingClientRect();
      return { x: p.x * (r.width / app.screen.width), y: p.y * (r.height / app.screen.height) };
    },
    /** RECINTO (sub-rama 2) · snapshot REAL de lo que drawRecintos dibujó este frame (params del último
     *  draw, no fabricación). Lo lee el verify para distinguir agente (halo) de cajón. */
    recintoDraw: () => Object.values(placedById).filter((n) => n.kind === "recinto").map((n) => ({ id: n.id, ...(n._draw || {}) })),
    /** F2 · estructura y controles del frame realmente dibujado, en screen-space. */
    pieceStructure: (id) => {
      const n = placedById[id]; if (!n) return null;
      return n.kind === "recinto" ? ((n._draw && n._draw.structure) || null)
        : (n.art && n.art.__structure) || null;
    },
    agentControlBounds: (id) => {
      const n = agentNodeFor(id); if (!n) return null;
      const box = (g) => {
        if (!g || !g.visible) return null;
        const b = g.getBounds(), x = Number.isFinite(b.x) ? b.x : b.minX, y = Number.isFinite(b.y) ? b.y : b.minY;
        const width = Number.isFinite(b.width) ? b.width : b.maxX - b.minX;
        const height = Number.isFinite(b.height) ? b.height : b.maxY - b.minY;
        return { x, y, width, height };
      };
      return { counter: box(n.chip), port: box(n.port), latency: box(n.latencyChip) };
    },
    /** F2 · mover una pieza a otra celda por código (mismo camino que el drag: moveTileTo). NO toca
     *  el modelo de relaciones (mover = sólo posición). Devuelve true si movió. Útil para F3/tests. */
    moveTile(id, gx, gy) {
      const n = placedById[id]; if (!n) return false;
      const occ = occupancy.get(cellKey(gx, gy)); if (occ && occ !== id) return false;
      moveTileTo(n, gx, gy); return true;
    },
    placedTiles: () => Object.values(placedById).map((n) => ({ ...n.data })),
    /** data VIVA de una pieza (no copia) — editarla afecta la receta (inspector/deep-link). */
    pieceData: (id) => { const n = placedById[id]; return n ? n.data : null; },
    /** NOMBRE de servicio (server titleizado, como el reel) — lo usa el diorama, la lista y el inspector. */
    svcName: _svcName,
    /** texto RENDERIZADO de la etiqueta del diorama (verificación de paridad con el reel). */
    pieceLabelText: (id) => { const n = placedById[id]; return n && n.label ? n.label.text : null; },
    /** [P5] ¿esta pieza YA está en el piso? — el flujo de equipar pregunta ANTES para poder decir
     *  la verdad ("ya la tenés") en vez del viejo "no quedó hueco libre", que sería mentira. */
    /** [P5] ¿esta pieza YA está en el piso? Acepta un id (contrato original de P5) o la TOOL
     *  entera — y con la tool mira la IDENTIDAD del servicio, no el id sintético. [FIX-P11 §4] */
    yaColocada: (t) => (typeof t === "string" || t == null ? !!placedById[t] : !!yaColocadaPor(t)),
    /** [FIX-P11 · §4] el ID de la pieza que YA ocupa esta identidad, o null. Es lo que deja
     *  DECIR «KiCad ya está en El Cuarto» y encima señalarla con el destello. */
    yaColocadaPor,
    /** [FIX-P11 · §4] la clave de identidad de una tool (para varas y diagnóstico). */
    identidadDeTool,
    /** [P5] identidad de UNA pieza: {base, calificador, label, colision, confundible}. */
    pieceIdentidad: (id) => _identidad.get(id) || null,
    /** [P5] DETALLE completo de la pieza — server, origen/belt y QUÉ la distingue. Es lo que
     *  el closet/inspector muestra un clic adentro: el label es corto, el detalle vive acá. */
    pieceDetalle: (id) => { const n = placedById[id]; return n ? detalleDe(n.data, _identidad.get(id)) : null; },
    /** [P5] todas las etiquetas del diorama — la vara asserta CERO pares idénticos. */
    dioramaLabels: () => Object.values(placedById)
      .filter((n) => n.kind === "tile" && n.label)
      .map((n) => ({ id: n.data.id ?? n.id, label: n.label.text })),
    /** data VIVA del núcleo (su modelo/identidad/objetivo) — editarla afecta la receta. */
    nucleoData: () => nucleoNode.data,
    /** C5 · mesh: extender una zona (manual o auto). Devuelve {role,w,h,N,grew}. */
    growZone, zoneFull: (role) => { const z = scene.zones.find((x) => x.role === role); return z ? zoneFull(z) : false; },
    growDirs: (role) => { const z = scene.zones.find((x) => x.role === role); return z ? growDirs(z) : []; },
    /** una celda libre en la zona `role`, creciéndola si está llena (lo usa la forja/chat). */
    freeCell: (role) => { let z = scene.zones.find((x) => x.role === role && CATEGORY_ROLES.has(role)); if (!z) return null;
      let c = freeCellInZone(z); if (!c) { growZone(role, 1); c = freeCellInZone(z); } return c; },
    /** SLOTS·A · nº de nodos kind:"adder" VIVOS en la escena (read-only, para el verify).
     *  Debe ser 0 fuera del MODO agregar-casillas — que es el default (ver `adders`). */
    adderCount: () => adderNodes.length,
    /** [punto 34] MODO agregar-casillas: los ＋ por-zona existen SÓLO mientras está activo.
     *  Se prende desde el widget de controles (⊙), nunca con un botón suelto en el diorama
     *  (CUARTO-HONESTO.md §8.5). `on` es el estado, `set`/`toggle` lo cambian y devuelven
     *  el estado YA aplicado — sin leer `viewMode`, que es el bug que cazó T6 §8.4 con la
     *  lente ("off" es un string truthy). Acá el estado es booleano de verdad. */
    adders: {
      get on() { return addersMode; },
      set: (v) => setAddersMode(v),
      toggle: () => setAddersMode(!addersMode),
    },
    /** SLOTS·B · estado del ghost/foco (read-only, para el verify): posición RENDER vs DESTINO (prueba el lerp). */
    ghostState: () => ({ visible: ghost.visible, x: ghost.position.x, y: ghost.position.y, tx: ghostTX, ty: ghostTY, glowOn, glowA, glowVisible: cellGlow.visible }),
    /** SLOTS·C · estado del piso que respira (read-only, para el verify): pico de respiración + alpha del piso claro. */
    floorBreath: () => { let mx = 0; for (let i = 0; i < visibleFloorCount; i++) mx = Math.max(mx, floorNodes[i].breath || 0); return { max: mx, lightAlpha: lightFloor.alpha, placing: !!dragTool || !!tileDrag, light: PALT === THEME.light }; },
    /** SLOTS·D · escala+dropT VIVOS de una pieza (read-only, para el verify del nacimiento 0.9→1.0). */
    tileScale: (id) => { const n = placedById[id]; return n && n.gfx ? { scale: n.gfx.scale.x, dropT: n.dropT, alpha: n.gfx.alpha } : null; },
    gridSize: () => ({ cols: grid.cols, rows: grid.rows, N }),
    /** Addendum 28-jul · vara/calibración viva del suelo finito virtualizado. */
    floorGrowth: {
      state: () => ({ enabled: floorGrowthEnabled, growing: !!floorGrowth, N,
        pool: floorNodes.length, visible: visibleFloorCount, logical: N * N }),
      setEnabled: (on) => (floorGrowthEnabled = !!on),
      near: (gx, gy) => growFloorNear(gx, gy),
    },
    /** Identidad medible: nombres obligatorios/únicos y cajas sin overlap. */
    agentNames: {
      state: agentLabelState,
      setGuardEnabled: (on) => (agentNameGuardEnabled = !!on),
    },
    /** FIX A (§9·A) · snapshot ESPACIAL read-only de los singletons COMPARTIDOS que enterRecinto NO
     *  serializa (N/grid, scene.zones, floorNodes.length, gx/gy de cada pieza). El harness lo captura
     *  ANTES de entrar y DESPUÉS de salir → assert byte-idéntico prueba que un edit-adentro no corrompió
     *  al padre. relationModel() es CIEGO a esto (no serializa gx/gy ni grid), por eso este snapshot. */
    spatialSnapshot: () => ({
      N, cols: grid.cols, rows: grid.rows,
      zones: scene.zones.map((z) => ({ role: z.role, gridX: z.gridX, gridY: z.gridY, w: z.w, h: z.h })),
      floorNodes: N * N,
      pieces: Object.values(placedById).map((n) => ({ id: String(n.id), gx: n.gx, gy: n.gy }))
        .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
    }),
    /** DENSIDAD (reel, read-only) · n = celdas ocupadas, cap = (N−1)², value = n/cap, max = techo duro. */
    density: () => { const n = occupancy.size, cap = Math.pow(N - 1, 2); return { n, N, cap, value: cap ? n / cap : 0, max: DENSITY_MAX }; },
    // 2a · estado del átomo (read-only, para verificación): beads vivos + cara + órbitas estáticas.
    atomState: () => {
      const c = nucleoNode.gfx;
      const snap = (g) => ({ x: +g.x.toFixed(2), y: +g.y.toFixed(2), alpha: +g.alpha.toFixed(3), scale: +g.scale.x.toFixed(3) });
      const recs = {};
      for (const [id, n] of Object.entries(placedById))
        if (n.kind === "recinto") recs[id] = { art: !!n.art, beads: n.art && n.art.__beads ? n.art.__beads.length : 0,
                                               chip: n.chip ? n.chip.text : null };   // 2b · el chip visible, medible
      return { beads: (c.__beads || []).map((b) => snap(b.g)), face: !!c.__face,
               orbits: c.__ring ? c.__ring.children.length : 0, ringRotation: c.__ring ? c.__ring.rotation : null,
               recintos: recs };
    },
    /** DENSIDAD · crece la grilla al conteo (N = ceil(1+√(count/0.45))). Devuelve {N,grew}. Para el reel/tests. */
    growToN,
    meshStats: () => ({ floor: N * N, floorPool: floorNodes.length, visibleFloor: visibleFloorCount,
      virtualized: true, walls: wallCells.size, N }),
    zones: () => scene.zones.filter((z) => CATEGORY_ROLES.has(z.role)).map((z) => ({ role: z.role, gridX: z.gridX, gridY: z.gridY, w: z.w, h: z.h })),
    // F5 · gatear/desgatear: el candado lo dibuja drawGates SOBRE LA LÍNEA (no en el ícono). Al
    // desgatear, además, suelta cualquier freno vivo de esa tool.
    setGated(id, on = true) { const n = placedById[id]; if (!n) return; n.gated = !!on; if (!on) gateState.delete(id); rebuildModel(); },
    /** STEP 2·B2 · MEMBRESÍA del bus de memoria compartida (la línea teal por-agente). on=false
     *  DESCONECTA ese sub-agente del cilindro → rebuildModel deja de emitir su "comparte" (y
     *  projection lo saca de recipe.memory.members). Default true = conectado. rebuildModel corre
     *  ACÁ (alta/baja/gate lo disparan; MOVER no) → la línea aparece/desaparece al instante. */
    setSharesMemory(id, on = true) { const n = placedById[id]; if (!n) return false; n.data.sharesMemory = !!on; rebuildModel(); return true; },
    /** STEP 2·B2 · membresía VIVA de una pieza-agente (read-only, para tests/UI): true = conectado al bus. */
    sharesMemory: (id) => { const n = placedById[id]; return n ? (n.data.sharesMemory !== false) : null; },
    /** punto en PANTALLA (cámara-aware) de una celda lógica — lo usa cuarto.live.js. */
    viewPoint(gx, gy) { const w = toScreen(gx, gy); return world.toGlobal(new PIXI.Point(w.x, w.y)); },
    playEco, stopEco, running: false, setRunning, ecoFire, ecoFireSpark, ecoReturn, ecoFinal,
    /** PULSO · registro READ-ONLY de los destellos disparados este run ({tileId, dir:"ida"|"eco", dur}) — para verify. */
    ecoLog: () => _ecoLog.slice(),
    // ── F5 · ENCENDIDOS DEL GATE = eventos reales. El gate FRENA sobre la línea (spec §2 paso 4).
    // Estos sólo cambian el ESTADO de freno (gateState) y leen el modelo para ubicar el candado;
    // NUNCA mutan el modelo de relaciones. Los llama el RUN (consumeLive) con eventos SSE reales:
    //   gate_waiting → gateHold (el flujo para en el candado, NO hay Eco)
    //   OK del usuario (approve real) → gateRelease (+ el caller dispara ecoReturn = la tool corrió)
    //   NO del usuario / rechazo     → gateReject (queda frenado, marcado)
    gateHold(toolId) {
      const n = placedById[toolId]; if (!n) return false;
      // OJO · RIESGO #1 (NO negociable): un freno REAL dentro de un recinto COLAPSADO → AUTO-EXPANDIR. El
      // invariante F5 es sagrado: el freno SIEMPRE se ve. Una caja cerrada que lo ocultara = invariante roto.
      if (n.parentId) { const p = placedById[n.parentId]; if (p && p.collapsed) expandRecinto(p); }
      gateState.set(toolId, "held"); n.glowTarget = 1; n.glow = 1.6; nucleoNode.glow = 1.5; return true;
    },
    gateRelease(toolId) { const had = gateState.has(toolId); gateState.delete(toolId); return had; },
    gateReject(toolId) { if (placedById[toolId]) { gateState.set(toolId, "rejected"); const n = placedById[toolId]; n.glowTarget = 0; } },
    isGateHeld: (toolId) => gateState.get(toolId) === "held",
    gatesHeld: () => [...gateState.entries()].filter(([, s]) => s === "held").map(([id]) => id),
    gateClearAll() { gateState.clear(); },
    // ── D4 · FRONTERA VIVA · el recinto-agente se ENCIENDE con los eventos ESTRUCTURALES REALES del
    // padre (sub_agent_started/finished), JAMÁS con una animación in-page sin run detrás (§7e = grift).
    // Mismo canal que gateHold: sólo cambian cómo se PINTA el muro; NUNCA mutan el modelo de relaciones.
    // Los llaman el RUN real (consumeLive) Y el REPLAY de eventos capturados de un run real
    // (window.__cuartoReplayEvent). El hijo corre con on_event=None → sólo llega el evento estructural
    // del árbol; los pasos internos del hijo NO se streamean (RIEL#5) — no prometemos un feed de su interior.
    recintoRun(id, on = true) {
      const n = placedById[id]; if (!n || n.kind !== "recinto" || !n.hasNucleo) return false;
      const lv = recintoLive.get(id) || {};
      if (on) { lv.running = true; lv.held = false; lv.errored = false; n.glowTarget = 1; n.glow = 1.5; } else lv.running = false;
      recintoLive.set(id, lv); return true;
    },
    /** D4 · sub_agent_finished(slug,status,held,result) → apaga el run; held>0 (o status:'gate') → "espera
     *  tu OK"; status:'error' → tinte rojo; result = bridge JSON {sub_agente,ok,resultado,truncado,error}
     *  → marca CRUZÓ (§1: sólo el resultado cruza al padre; los pasos del hijo quedan en el log, NO cruzan). */
    recintoFinish(id, ev = {}) {
      const n = placedById[id]; if (!n || n.kind !== "recinto" || !n.hasNucleo) return false;
      const lv = recintoLive.get(id) || {};
      lv.running = false;
      lv.held = (Number(ev.held) || 0) > 0 || ev.status === "gate";
      lv.errored = ev.status === "error";
      let crossed = false;
      if (typeof ev.result === "string" && ev.result) {
        try { const b = JSON.parse(ev.result); crossed = !!b && typeof b === "object" && ("sub_agente" in b) && ("resultado" in b); } catch {}
      }
      lv.crossed = crossed;
      if (lv.held) { n.glowTarget = 1; n.glow = 1.6; } else n.glowTarget = lv.errored ? 0 : 0.2;
      recintoLive.set(id, lv); return true;
    },
    /** D4 · ANTI-GRIFT · puebla el estado degradado del RUN (modelo del PADRE) desde el evento
     *  cost/notice/final REAL (recipe_assembler:738/769/2096). `degraded` = señal honesta "NO es el
     *  modelo real"; modelFinal = lo que DE VERDAD contestó. Se KEYEA en `degraded`, no en el modelo. */
    runVerdict(v = {}) {
      if (v.degraded !== undefined) { const d = (v.degraded === false ? null : (v.degraded ?? null)); if (d) _antiGrift.degraded = d; }  // STICKY: la 1ª caída manda (durable record["degraded"]); un cost limpio posterior NO la borra
      if (v.model_final !== undefined && v.model_final !== null) _antiGrift.modelFinal = String(v.model_final);
      return { degraded: _antiGrift.degraded, modelFinal: _antiGrift.modelFinal };
    },
    /** D4 · lectura ANTI-GRIFT (read-only, HUD/verify): isDegraded keyea el banner "no es el modelo";
     *  realBrain sólo true si contestó un modelo real (no fake-brain, no degradado). */
    antiGrift: () => ({ degraded: _antiGrift.degraded, modelFinal: _antiGrift.modelFinal,
      isDegraded: !!_antiGrift.degraded,
      realBrain: !!_antiGrift.modelFinal && !/fake/i.test(_antiGrift.modelFinal) && !_antiGrift.degraded }),
    /** D4 · estado VIVO de un recinto (read-only, verify): {running,held,errored,crossed} o null. */
    recintoLiveState: (id) => { const lv = recintoLive.get(id); return lv ? { running: !!lv.running, held: !!lv.held, errored: !!lv.errored, crossed: !!lv.crossed } : null; },
    /** D4 · limpia toda la frontera viva (arranque de run / aislamiento de tests). */
    recintoLiveClear() { recintoLive.clear(); _antiGrift.degraded = null; _antiGrift.modelFinal = null; },
    // ── PULSO+TABLERO · AURA DE ESTADO = eventos REALES del run. Mismo canal que gateHold/recintoRun:
    // sólo cambian el ESTADO que pinta el anillo (tileLive); NUNCA mutan el modelo de relaciones. Los
    // llama el RUN real (consumeLive, con el id ya resuelto por la maquinaria del pulso) Y el replay del
    // harness (__cuartoApplyFrontierEvent) → producción y verificación ejercitan el MISMO mapeo.
    /** PULSO+TABLERO · estado del aura de una PIEZA PLANA (kind:"tile"). state ∈ {calling,held,error,done};
     *  falsy → BORRA el aura. GUARDA kind:"tile": un recinto-agente NUNCA entra acá (lleva su halo en
     *  drawRecintos → sin doble-anillo). Devuelve true si aplicó. NO toca glow: el aura RIDE el n.glow que
     *  ecoFire ya movió (spec §2: "reusar canal n.glow existente"). */
    tileState(id, state) {
      const n = placedById[id]; if (!n || n.kind !== "tile") return false;
      if (!state) { tileLive.delete(id); return true; }
      tileLive.set(id, { state, t0: Date.now() });
      return true;
    },
    /** PULSO+TABLERO · estado VIVO del aura de una pieza (read-only, verify): {state} o null. */
    tileLiveState: (id) => { const lv = tileLive.get(id); return lv ? { state: lv.state } : null; },
    /** §3 · SEMÁFORO DE VERDAD por pieza (glifo estático, SEPARADO del aura de run). v = {estado,color}
     *  (color = número PIXI) o falsy para BORRAR. GUARDA kind:"tile". Devuelve true si aplicó. */
    tileVerdad(id, v) {
      const n = placedById[id]; if (!n || n.kind !== "tile") return false;
      if (!v || v.color == null) { tileVerdad.delete(id); return true; }
      tileVerdad.set(id, { estado: v.estado || null, color: v.color }); return true;
    },
    /** §3 · lo puesto por tileVerdad (read-only, verify): {estado,color} o null. */
    tileVerdadState: (id) => { const v = tileVerdad.get(id); return v ? { estado: v.estado, color: v.color } : null; },
    /* [reforma · k] LOS DOS MODOS. setModo("trabajo", {focus}) despliega; setModo("mcps") recoge.
     * Las piezas-MCP no se mueven: lo que cambia es qué MÁS se dibuja, no dónde está nada. */
    setModo(m, opts) {
      const on = m === "trabajo";
      const foco = (opts && opts.focus) || null;
      if (on === workMode && foco === workFocus) return { modo: workMode ? "trabajo" : "mcps", focus: workFocus };
      workMode = on; workFocus = on ? foco : null; workDirty = true;
      if (!on) limpiarWork();
      return { modo: workMode ? "trabajo" : "mcps", focus: workFocus };
    },
    modo: () => ({ modo: workMode ? "trabajo" : "mcps", focus: workFocus,
                   tools: workNodes.map((w) => ({ tool: w.tool, de: w.parent.id })) }),
    /** P3-CIERRE · bounding boxes VIVOS de los labels que PIXI dibujó, en coordenadas
     *  globales. La vara de cero-overlap no confía en el algoritmo: mide el resultado. */
    toolLabelBoxes: () => workNodes.filter((w) => w.gfx.visible && w.label && !w.label.destroyed)
      .map((w) => {
        const b = w.label.getBounds();
        const left = Number.isFinite(b.x) ? b.x : b.minX;
        const top = Number.isFinite(b.y) ? b.y : b.minY;
        const right = Number.isFinite(b.width) ? left + b.width : b.maxX;
        const bottom = Number.isFinite(b.height) ? top + b.height : b.maxY;
        return { pieza: w.parent.id, tool: w.tool, left, top, right, bottom,
                 width: right - left, height: bottom - top };
      }),
    /** La ACTIVIDAD es capa, no modo: esto la empuja y vale en los dos modos. */
    toolLive(pieceId, tool, state) {
      const k = pieceId + "::" + tool;
      if (!state) toolLive.delete(k); else toolLive.set(k, state);
      return true;
    },
    /** ¿hay alguna tool de esta pieza corriendo AHORA? (el punto de la etiqueta en modo MCPs) */
    piezaConActividad(pieceId) {
      for (const [k, v] of toolLive) if (v === "calling" && k.startsWith(pieceId + "::")) return true;
      return false;
    },
    /** [reforma · q] la pieza SE DESPEGA mientras su abanico está abierto (sube + sombra).
     *  Es la misma pieza levantándose, no un cartel que aparece al lado. */
    pieceLift(id, on) {
      const n = placedById[id]; if (!n) return false;
      Object.values(placedById).forEach((m) => { if (m !== n) m.liftTarget = 0; });
      n.liftTarget = on ? 1 : 0;
      return true;
    },
    pieceLiftState: (id) => { const n = placedById[id]; return n ? { lift: n.lift || 0, target: n.liftTarget || 0 } : null; },
    /** Cara funcional del diorama. La marca no participa en esta superficie. */
    tileCara(id) {
      const n = placedById[id]; if (!n || !n.art) return null;
      return { symbol: n.art.__dioramaSymbol || null,
               tieneCara: !!n.art.__dioramaSymbolFace };
    },
    /** [reforma · g] la FIRMA del anillo, tal como se dibuja: {tools, color, estado, visible}. */
    tileAnillo: (id) => {
      const n = placedById[id]; if (!n) return null;
      const tools = ((n.data && n.data.tools) || []).length;
      const v = tileVerdad.get(id);
      return { tools, estado: (v && v.estado) || null,
               color: (v && v.color != null) ? v.color : (tools ? ANILLO_NEUTRO : null),
               visible: !!(n.anillo && n.anillo.visible) };
    },
    /** P6 · la GEOMETRÍA VIVA de los anillos DIBUJADOS, en px de MUNDO (pre-cámara): centro y
     *  semiejes YA escalados por el transform real de la pieza (bob del idle, lift del abanico,
     *  escala de nacimiento/glow/relevancia). Es lo que la vara mide para el assert de solape —
     *  no una constante, no el modelo, no lo que la física creyó: lo que está en pantalla. */
    anillosGeom: () => Object.values(placedById)
      .filter((n) => n.kind === "tile" && n.anillo && n.anillo.visible && !n.hidden && n.gfx && !n.gfx.destroyed)
      .map((n) => {
        const k = n.gfx.scale.x, R = anilloRadii(n);
        return { id: n.id, gx: n.gx, gy: n.gy, k,
                 cx: n.gfx.position.x, cy: n.gfx.position.y + (-6) * k,
                 a: R.a * k, b: R.b * k };
      }),
    /** P6 · la separación que la FÍSICA usa entre dos celdas, en la peor rotación (1 = tangentes).
     *  Para calibrar la vara en rojo y para explicar un fallo sin adivinar. */
    anilloSepCeldas: (ax, ay, bx, by) => {
      const rad = anilloRadiiTipico();
      return anilloSep(ax, ay, rad, bx, by, rad);
    },
    anilloAire: () => SEP_AIRE,
    /** PULSO+TABLERO · snapshot REAL de lo que drawTileAuras dibujó (el HIJO Graphics vivo, no el Map) —
     *  para el verify de "diff evento↔dibujo = 0" (§3.1). {has,visible,state,r} o null si no hay pieza. */
    tileAura: (id) => { const n = placedById[id]; if (!n) return null;
      const lv = tileLive.get(id);
      return { has: !!n.aura, visible: !!(n.aura && n.aura.visible), state: lv ? lv.state : null, r: n._auraR || null }; },
    /** PULSO+TABLERO · limpia todas las auras de estado (arranque de run / aislamiento de tests). */
    tileLiveClear() { tileLive.clear(); },
    // ── D2 · FRACTAL (zoom semántico) — API REAL (el botón "Entrar" de D5 llama al MISMO enter) ──
    /** ENTRAR a un recinto-agente: push-in + carga SU receta en el mismo motor (padre guardado byte-idéntico).
     *  opts.recipe = receta del hijo inyectada (D5 preload / harness). Devuelve {ok, depth,...} — NUNCA tira. */
    enter: enterRecinto,
    /** SALIR un nivel: pull-back + restaura al padre byte-idéntico. Devuelve {ok, depth}. */
    exit: exitRecinto,
    /** SALTO de breadcrumb: sale hasta `level` (0 = raíz). Devuelve {ok, depth}. */
    exitTo,
    /** estado del stack de escenas (read-only): {depth, stack:[{agentRef,label}], atRoot}. */
    fractal: fractalState,
    /** registra el listener del breadcrumb (se dispara en cada enter/exit con fractalState()). */
    setFractalListener: (fn) => { onFractalChange = (typeof fn === "function") ? fn : null; },
    /** registra el listener de RECHAZO (tope de profundidad, etc.) — para el mensaje honesto de la UI. */
    setFractalDeniedListener: (fn) => { onFractalDenied = (typeof fn === "function") ? fn : null; },
    /** D5 · registra el listener del PANEL DEL RECINTO. Se dispara al CLIC (sin entrar) sobre el mini-Aleph
     *  de un recinto-AGENTE con la identidad NODE-DERIVED {id,name,model,agentRef,sharesMemory,hasNucleo}.
     *  Aditivo al inspector: NO cambia toggleCollapse (clic lejos) ni enter (dblclic). */
    setRecintoPanelListener: (fn) => { onRecintoPanel = (typeof fn === "function") ? fn : null; },
    /** F2 · el mundo raíz no desaparece al entrar: queda como contexto atenuado alrededor. */
    worldVisible: () => world.visible && world.alpha > 0,
    /** F2 · evidencia del Cuarto hijo completo (piso+nucleo+cables+nombres+padre atenuado). */
    fractalVisual: childRoomState,
    /** D2/F2 · un salto de miga completo debe volver a una sola escena PIXI. */
    worldLayers: () => ({ total: cameraRoot.children.length,
      visible: cameraRoot.children.filter((child) => child.visible && child.alpha > 0).length }),
    /** F2 · modelo de relaciones (read-only) — CONTRATO de F3/F4/F5. { pieces:[], relationships:[] }. */
    relationModel: () => model, relations: () => model.relationships, pieces: () => model.pieces,
    /** F2 · contrato visual multiagente. `plan` es la respuesta del motor sellado. */
    multiagente: {
      setMode(modo) {
        multi.modo = modo || null; multi.plan = null; multi.cables = [];
        nucleoNode.data._multiModo = multi.modo;
        nucleoNode.data._agentLinks = [];
        Object.values(placedById).forEach((n) => {
          if (n.kind === "recinto" && n.hasNucleo) { n.nucleoDerived = true; if (n.coreArt) n.coreArt.visible = true; }
        });
        rebuildModel(); return multiState();
      },
      applyPlan: applyMultiPlan,
      state: multiState,
      connect: requestAgentCable,
      checkCable: localCableCheck,
      setRestriction(on) { multi.restriction = !!on; return multi.restriction; },
      setFixedControls(on) { multi.fixedControls = !!on; return multi.fixedControls; },
      hasAgent(ref) { return !!agentNodeFor(ref); },
      setInterior(id, value) {
        const n = agentNodeFor(id); if (!n) return false;
        value = value || {};
        if (Number.isFinite(Number(value.count))) n.data.interiorCount = Number(value.count);
        if (value.estado) n.data.interiorEstado = value.estado;
        if (n.rechip) n.rechip();
        return true;
      },
      runStart: multiRunStart, hop: multiHop, runStop: multiRunStop, playMeasured: playMeasuredRun,
      // Muralla medible: este renderer sólo acepta piezas de receta. Los workers
      // efímeros no tienen constructor ni colección dentro del diorama.
      workersRendered: () => 0,
      gestures: () => ({ zoomCoreOpensMind: false, pressAlephZooms: false,
        zoomAlephEntersRoom: true, pressCoreOpensMind: true }),
    },
    setWired(id, on = true) { const n = propsById[id]; if (n) n.glowTarget = on ? 1 : 0; },
    setZoneActive: api_setZoneActive,
    pulse(id) { const n = propsById[id] || placedById[id] || (zonesByRole[id]?.[0]); if (n) n.glow = 1.6; },
    cam: { panBy, zoomAt, rotateBy, reset: resetCam, fit: fitAll, setInsets, get state() { return { ...cam }; },
      semanticAnchor: () => lastSemanticAnchor ? JSON.parse(JSON.stringify(lastSemanticAnchor)) : null,
      /** D2 · push-in ANIMADO que enmarca el footprint de un recinto (lerpeado en el ticker). */
      pushInto(recintoId, anchor) { const n = placedById[recintoId]; if (!n || n.kind !== "recinto") return false; pushIntoNode(n, anchor); return true; } },
    /** POSICIÓN · reacomoda todo al layout balanceado (force-directed). Lo cablea el botón "ordenar". */
    order: orderLayout,
    layout: { order: orderLayout, balancedCell: balancedFreeCell },
    /** F4 · lente de flujo — SUBSUMIDA en la vista "funcion" (compat: cuarto.pixi.html usa lens.toggle/set). */
    lens: { toggle: () => setView(viewMode === "funcion" ? "off" : "funcion"), set: (on) => setView(on ? "funcion" : "off"), get on() { return viewMode === "funcion"; } },
    /** CONSTELACIÓN · 3 vistas (doc §6): reagrupa el overlay SIN tocar el modelo. set("servicio"|"funcion"|"relacion"|"off");
     *  cycle() recorre off→servicio→funcion→relacion→off (default al prender = "servicio"). get() = modo activo. */
    view: { set: (mode) => setView(mode), get: () => viewMode,
      cycle: () => setView({ off: "servicio", servicio: "funcion", funcion: "relacion", relacion: "off" }[viewMode]),
      modes: ["servicio", "funcion", "relacion"] },
    /** CONSTELACIÓN · snapshot READ-ONLY de los grupos (modo actual o el `mode` pedido) — para tests/UI, NO muta nada. */
    viewState: (mode) => { const m = (mode === "servicio" || mode === "funcion" || mode === "relacion") ? mode : viewMode;
      return { mode: viewMode, groups: m === "off" ? [] : buildViewGroups(m).map((g) => ({ key: g.key, label: g.label, count: g.pts.length })) }; },
    /** C2 · relevancia derivada por pieza (id→0..1) — read-only, para tests/UI. NO incluye al Núcleo (no lleva relevancia). */
    relevance: () => Object.fromEntries(Object.values(placedById).map((n) => [n.id, n.relevance || 0])),
    /** glow VIVO de una pieza (hover/pulse) — read-only, para tests (verifica que el hover-glow sigue vivo, aparte de la relevancia). */
    nodeGlow: (id) => { const n = placedById[id]; return n ? n.glow : null; },
    /** [iconos] glifo de dominio de una tool — read-only, para tests: {icon, tint, ink}. NO muta. */
    glyph: (id) => { const n = placedById[id]; if (!n || n.atomKind !== "tool" || !n.art) return null;
      const dom = n.art.children[n.art.children.length - 1];           // 3er hijo = glifo de dominio
      return { icon: resolveIcon(n.data), tint: dom ? dom.tint : null, ink: PALT.glyphInk }; },
    /** Símbolo funcional de una pieza — read-only para pruebas visuales. */
    dioramaSymbol: (id) => { const n = placedById[id]; if (!n || !n.art || !n.art.__dioramaSymbol) return null;
      return { symbol: n.art.__dioramaSymbol,
               shown: !!(n.art.__dioramaSymbolFace && n.art.__dioramaSymbolFace.visible) }; },
    /** [ticket 5] ids con candado FANTASMA vivo (sugerencia sin gate) — read-only, para tests/UI. */
    advisorGhosts: () => _ghostPts.map((g) => g.id),
    /** [ticket 5] acepta la sugerencia del advisor: pone el gate REAL en esa pieza (mismo camino
     *  que el tap sobre el fantasma — emite "cuarto:ghostgate" para el microcopy del chrome). */
    applyGhost: (id) => applyGhostGate(id),
    /** [FIX-P3 · §4] EL candado de una pieza — read-only:
     *    "held" (frenó una corrida real, ahora) | "rejected" (permiso rechazado) |
     *    "firme" (puesto, o piso del sistema) | "alerta" (propuesto, aún sin poner) |
     *    null (la pieza sólo lee: no lleva candado ni se le ofrece).
     *  `lidLock` conserva su nombre —lo llaman las varas— pero ya no hay «tapa»: hay UN
     *  candado por pieza, y esto es su estado. */
    lidLock: (id) => _lidStates.get(id) || null,
    /** [FIX-P3 · §4] EL candado ENTERO: estado + dónde cayó + a qué distancia está del cable
     *  que va de la pieza a su DUEÑO. `dCable` es lo que hace medible «pegado al cable, jamás
     *  flotando»: es la distancia mínima del candado a la bezier real del cable, en px. */
    candado: (id) => {
      const est = _lidStates.get(id) || null;
      if (!est) return null;
      const gp = gatePointOf(id); if (!gp) return null;
      const cable = quadPts(gp.a, gp.c, gp.b, 96);
      let d = Infinity;
      for (const q of cable) d = Math.min(d, Math.hypot(q.x - gp.x, q.y - gp.y));
      const b = tileCenter(placedById[id]);
      const dDueno = Math.hypot(gp.dueno.x - gp.x, gp.dueno.y - gp.y);
      const r = 12;
      return { estado: est, x: gp.x, y: gp.y, dCable: d,
               dPieza: Math.hypot(b.x - gp.x, b.y - gp.y),
               duenoId: gp.duenoId, dDueno,
               dNucleo: dDueno, // alias de compatibilidad para la vara P3 anterior
               bbox: { left: gp.x - r, top: gp.y - r, right: gp.x + r, bottom: gp.y + r },
               cable };
    },
    /** [FIX-P3 · §4] todos los candados vivos del cuarto — para contar que hay UNO por pieza. */
    candados: () => [..._lidStates.keys()],
    /** 1a · coreografía de inspección del Motor B (draw-pass aparte). La maneja cuarto.inspect.js
     *  con los eventos REALES del stream POST /v1/inspect/forge. CERO-TEATRO: cada transición sólo
     *  por su evento. No toca el modelo de relaciones (F2/F3/F4/F5) ni coloca piezas reales. */
    forge: forgeApi,
    destroy() { app.destroy(true, { children: true }); },
  };
  fitAll(); // arranca ENCUADRADO (Fuentes+Mesa+Entrega juntas) — sin panear para ver todo
  return api;
}

// ── kernels de animación ─────────────────────────────────────────────────────
function tickTile(n, t) {
  if (n.hidden) { if (n.gfx) n.gfx.visible = false; if (n.label) n.label.visible = false; return; } // RECINTO: hijo OCULTO (colapsado)
  if (n.label) n.label.visible = !!n.alwaysLabel || n.glow > 0.12; // dentro del Cuarto hijo el nombre es parte del mapa
  if (n.dragging) return; // se está arrastrando: no pisar su posición con el idle
  const c = n.gfx;
  n.dropT = approach(n.dropT, 1, 0.16);
  const settle = Math.min(1, n.dropT);
  // SLOTS·D · NACIMIENTO SUTIL: la escala emerge de 0.9 → 1.0 (sin overshoot, sin partir de 0) — la pieza
  // "nace", no salta. El fade (alpha, abajo) da el "emerge". En reposo (settle=1) → 1.0, byte-idéntico a hoy.
  const birth = 0.9 + 0.1 * settle;
  // C2 · brillo ambiente por relevancia (conexión con fan-out): término SUAVE que respira, ADITIVO al
  // hover-glow (n.glow, intacto). Una tool suelta tiene rel=0 → este término es 0 → byte-idéntico a hoy.
  const rel = n.relevance || 0;
  // [reforma · q] LA PIEZA SE DESPEGA. Cuando su abanico está abierto, la pieza sube unos
  // píxeles y deja sombra: el menú no es un cartel que aparece al lado, es ESA pieza la que
  // se levantó para mostrar lo que tiene. Sin lift (0) el dibujo es byte-idéntico al de hoy.
  n.lift = approach(n.lift || 0, n.liftTarget || 0, 0.22);
  const lift = n.lift < 0.002 ? 0 : n.lift;
  c.scale.set(birth * (1 + n.glow * 0.05 + rel * 0.04 + lift * 0.05));
  c.y = n.baseY - settle * (3 + 1.6 * Math.sin(t * 2 + n.phase)) - lift * 9;
  if (lift || n.sombra) {
    if (!n.sombra) { n.sombra = new PIXI.Graphics(); n.sombra.eventMode = "none"; n.sombra.zIndex = -2; c.addChildAt(n.sombra, 0); }
    const g = n.sombra; g.clear();
    if (lift) g.ellipse(0, 9 + lift * 9, 20 + lift * 5, 7 + lift * 2).fill({ color: 0x000000, alpha: 0.06 + 0.14 * lift });
  }
  c.alpha = 0.2 + 0.8 * settle;
  if (n.art && n.art.__tint) n.art.__tint(mix(n.color, 0xffffff, 0.06 + 0.1 * Math.sin(t * 2.2 + n.phase) + n.glow * 0.45 + rel * (0.12 + 0.06 * Math.sin(t * 1.6 + n.phase))));
}
function tickZone(n) { n.active = approach(n.active, n.activeTarget, 0.12); if (n.lbl) n.lbl.alpha = 0.72 + n.glow * 0.28 + n.active * 0.28; }
function tickNucleo(n, t) {
  if (n.dragging) return;                                           // F3 · arrastrándose: el drag manda x/y, no el idle
  const c = n.gfx;
  c.y = n.baseY - 4 * Math.sin(t * 1.5 + n.phase);
  c.scale.set(1 + 0.04 * Math.sin(t * 2.2) + n.glow * 0.07);
  tickAtomArt(c, t, n.glow);
}
// vida del átomo (core pulsa + beads viajan con profundidad frente/atrás) — compartida por el
// Núcleo principal y el mini-Aleph de un recinto-agente. Cero redraws: solo position/scale/alpha.
function tickAtomArt(c, t, glow = 0) {
  if (c.__core) c.__core.alpha = 0.78 + 0.22 * Math.sin(t * 3) + glow * 0.25;
  if (!c.__beads) return;
  for (const b of c.__beads) {
    const ang = t * 1.7 + b.k * 2.0944;                             // 2π/3 de separación entre beads
    const lx = Math.cos(ang) * 20, ly = Math.sin(ang) * 7;          // punto paramétrico de SU elipse
    b.g.position.set(lx * b.cos - ly * b.sin, lx * b.sin + ly * b.cos);
    const front = 0.5 + 0.5 * Math.sin(ang);                        // canon del mock: sin>0 = adelante
    b.g.scale.set(0.75 + 0.55 * front);
    b.g.alpha = 0.4 + 0.6 * front;
  }
}
function tickConexion(n, t) { const c = n.gfx; if (c.__glow) c.__glow.alpha = 0.3 + 0.25 * Math.sin(t * 2 + n.phase) + n.glow * 0.4; c.scale.set(1 + n.glow * 0.05); }

// ── shapes procedurales de los átomos (iso 2.5D) ─────────────────────────────
function isoBox(g, halfW, halfH, height, top, left, right) {
  const ty = -height;
  g.poly([-halfW, 0, 0, halfH, 0, halfH + ty, -halfW, ty]).fill({ color: left });
  g.poly([halfW, 0, 0, halfH, 0, halfH + ty, halfW, ty]).fill({ color: right });
  g.poly([0, ty - halfH, halfW, ty, 0, ty + halfH, -halfW, ty]).fill({ color: top });
}
// [iconos] glifo de dominio Lucide (monocromo) en PIXI v8 vía GraphicsContext.svg. Se dibuja
// en BLANCO y el color lo manda el TINT (glyphInk en reposo · color de rol con la lente). El path
// sale de ICON_PATHS (vendored); nombre fuera del mapa → fallback duro a "puzzle" → universalidad
// también en el DRAW. Nunca lanza: si el parser falla, el glifo queda vacío y la pieza sigue intacta.
function makeDomainGlyph(name) {
  const inner = ICON_PATHS[name] || ICON_PATHS.puzzle;
  let g;
  try {
    const svg = `<svg viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
    g = new PIXI.Graphics().svg(svg);   // BLANCO → el color lo manda el tint
    g.pivot.set(12, 12);                // Lucide es 24×24 → centrar el glifo en su pivote
  } catch (_) { g = new PIXI.Graphics(); /* draw seguro: glifo vacío, la pieza sigue intacta */ }
  return g;
}
// La cara funcional sólo conoce el enum ya curado por la entidad. No resuelve marcas,
// nombres ni capacidades. Los logos originales permanecen en las superficies HTML.
const DIORAMA_SYMBOLS = new Set([
  "buscar", "leer", "escribir", "datos", "codigo", "media",
  "comunicacion", "almacenamiento", "calculo", "generico",
]);
const _dioramaSymbolTex = new Map(); // símbolo → Promise<PIXI.Texture>

function dioramaSymbolTexture(symbol) {
  if (!_dioramaSymbolTex.has(symbol)) {
    const url = new URL(`./symbols/aleph-${symbol}.svg`, import.meta.url).href;
    _dioramaSymbolTex.set(symbol, PIXI.Assets.load(url));
  }
  return _dioramaSymbolTex.get(symbol);
}

function attachDioramaSymbol(c, genericGlyph, toolData, sizePx, at) {
  const declared = String(toolData && toolData.diorama_symbol || "").trim().toLowerCase();
  const symbol = DIORAMA_SYMBOLS.has(declared) ? declared : "generico";
  dioramaSymbolTexture(symbol).then((tex) => {
    if (c.destroyed || c.__dioramaSymbolFace) return;
    const sp = new PIXI.Sprite(tex);
    sp.anchor.set(0.5);
    sp.width = sizePx;
    sp.height = sizePx;
    sp.position.set(at ? at.x : 0, at ? at.y : -6);
    if (genericGlyph) {
      genericGlyph.visible = false;
      c.addChildAt(sp, c.getChildIndex(genericGlyph));
    } else {
      c.addChild(sp);
    }
    c.__dioramaSymbolFace = sp;
    c.__dioramaSymbol = symbol;
  }).catch(() => {
    // El glifo procedural existente sigue visible si el asset local no puede cargarse.
  });
}
function makeToolPiece(color, toolData) {
  // REEL · JERARQUÍA INVERTIDA (sólo eso — el COLOR volvió al original): el GLIFO DE DOMINIO es el
  // PROTAGONISTA (grande, centrado, MONOCROMO glyphInk) y la LLAVE recede a INVISIBLE (alpha 0) pero
  // queda VIVA y cableada a __tint/lente. El ZÓCALO vuelve al diamante FAINT de color de zona original
  // (un solo tono por pieza, como en main pre-reforma) → el piso queda en su color único, sin mosaico.
  // Billboard "gratis": la rotación de cámara va a las coords de grilla (toScreen/rotPt), no al
  // contenedor del arte → el glifo SIEMPRE mira a cámara aunque el zócalo viva en el plano iso.
  const c = new PIXI.Container();
  c.__structure = "caja";
  const plate = new PIXI.Graphics();
  plate.poly([0, -8, 26, 5, 0, 18, -26, 5]).fill({ color, alpha: 0.18 }).stroke({ color, width: 1, alpha: 0.5 });
  const face = mix(color, 0xffffff, 0.26), edge = mix(color, 0x000000, 0.42);
  const wrench = new PIXI.Graphics();
  // mango + mandíbula abierta (open-end): se conserva la silueta de llave, pero INVISIBLE (alpha 0).
  wrench.poly([-4, 16, -4, -8, -11, -8, -11, -22, -4, -22, -4, -15,
               4, -15, 4, -22, 11, -22, 11, -8, 4, -8, 4, 16])
    .fill({ color: face }).stroke({ color: edge, width: 2, join: "round" });
  wrench.rotation = -0.42; wrench.position.set(0, -5);
  wrench.alpha = 0;                  // REEL · recede a invisible; SIGUE viva (cableada a __tint/lente)
  // glifo de dominio PROTAGONISTA: grande + centrado; MONOCROMO (glyphInk, lee sobre el piso del tema).
  const domain = makeDomainGlyph(resolveIcon(toolData));
  domain.scale.set(1.3); domain.position.set(0, -6);
  domain.tint = PALT.glyphInk;       // tinte neutro FIJO (NO sigue n.color — fuera del role-__tint)
  c.addChild(plate, wrench, domain); // orden: [plate, wrench, domain] — domain SIGUE siendo el ÚLTIMO hijo (contrato api.glyph)
  // el role-__tint (tickTool, cada frame) sigue tocando SÓLO la llave (invisible, pero cableada) → el glifo queda monocromo…
  c.__tint = (tint) => { wrench.tint = tint; };
  // …salvo cuando la LENTE DE FLUJO (F4) está ON: ahí el glifo toma el color de acción (lo prende setView).
  c.__domainTint = (on, accent) => { domain.tint = on ? accent : PALT.glyphInk; };
  attachDioramaSymbol(c, domain, toolData, 40);
  return c;
}
function makeContexto(color) {
  // MEMORIA/CONTEXTO → base de datos (cilindro con discos apilados = ícono canónico de DB).
  const c = new PIXI.Container();
  const plate = new PIXI.Graphics();
  plate.poly([0, -8, 26, 5, 0, 18, -26, 5]).fill({ color, alpha: 0.18 }).stroke({ color, width: 1, alpha: 0.5 });
  const drum = new PIXI.Graphics();
  const rx = 15, ry = 6, top = -28, bot = 2;
  const side = mix(color, 0x000000, 0.16), edge = mix(color, 0x000000, 0.42), band = mix(color, 0xffffff, 0.3);
  drum.rect(-rx, top, rx * 2, bot - top).fill({ color: side });        // cuerpo (lados)
  drum.ellipse(0, bot, rx, ry).fill({ color: side }).stroke({ color: edge, width: 1.6 }); // fondo
  drum.moveTo(-rx, top).lineTo(-rx, bot).moveTo(rx, top).lineTo(rx, bot).stroke({ color: edge, width: 1.6 }); // aristas
  [top + 18, top + 9].forEach((y) => drum.ellipse(0, y, rx, ry).stroke({ color: band, width: 1.4, alpha: 0.7 })); // discos
  drum.ellipse(0, top, rx, ry).fill({ color: mix(color, 0xffffff, 0.34) }).stroke({ color: edge, width: 1.6 }); // tapa
  c.addChild(plate, drum);
  c.__tint = (tint) => { drum.tint = tint; };
  return c;
}
// 2c · MEMORIA · COMPARTIDA → tambor de DB cyan con anillo doble ("todos leen/escriben acá").
// Distinta del contexto (rosa, por-agente): esta es UNA base para el cuarto entero.
function makeMemoria(color = ATOM_COLOR.memoria) {
  const c = makeContexto(color);
  const shared = new PIXI.Graphics();
  shared.ellipse(0, 8, 24, 10).stroke({ color, width: 1.4, alpha: 0.55 });
  shared.ellipse(0, 8, 29, 12.5).stroke({ color, width: 1, alpha: 0.3 });
  c.addChildAt(shared, 0);
  return c;
}
// F5 · el candado del Gate ya NO es un badge sobre el ícono: se dibuja SOBRE LA LÍNEA de la tool
// que custodia (drawGates, derivado de model.relationships kind:"gate" + del estado de freno).
function makeConexion(color = ATOM_COLOR.conexion, toolData) {
  // [reforma · f] MURIÓ LA PUERTA. Acá se dibujaba un vano arqueado con hoja y picaporte, y el
  // logo del servicio iba de PLACA encima, a 13px: la estructura era nuestra y la identidad,
  // una calcomanía. Al mirarlo, uno veía "una puerta" — no Gmail. La conexión ahora se dibuja
  // como cualquier pieza: el zócalo de su zona y, de cara, el símbolo funcional al
  // mismo tamaño que las demás. Lo que la distingue es su color de zona y su anillo, no una
  // metáfora arquitectónica que nadie pidió.
  const c = new PIXI.Container();
  const glow = new PIXI.Graphics(); glow.ellipse(0, 4, 22, 10).fill({ color, alpha: 0.18 });
  const plate = new PIXI.Graphics();
  plate.poly([0, -8, 26, 5, 0, 18, -26, 5]).fill({ color, alpha: 0.18 }).stroke({ color, width: 1, alpha: 0.5 });
  const domain = makeDomainGlyph(resolveIcon(toolData));
  domain.scale.set(1.3); domain.position.set(0, -6);
  domain.tint = PALT.glyphInk;
  c.addChild(glow, plate, domain);
  c.__glow = glow; c.__tint = () => {};   // el color vive en el zócalo; la cara del servicio no se tiñe
  c.__domainTint = (on, accent) => { domain.tint = on ? accent : PALT.glyphInk; };
  attachDioramaSymbol(c, domain, toolData, 40);
  return c;
}
// F2 · la criatura de Aleph, aislada del átomo. Es el MISMO centro vivo del `--mark`
// del arranque de Sala (hexágono violeta + ojos ⌒⌒), sin sus órbitas: en una baldosa
// de sub-Aleph las órbitas serían una segunda marca peleando con la criatura.
function makeAlephCreature() {
  const c = new PIXI.Container();
  const shadow = new PIXI.Graphics();
  shadow.ellipse(0, 7, 15, 5).fill({ color: 0x090914, alpha: 0.3 });
  const body = new PIXI.Graphics();
  const r = 17, pts = [];
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 3;
    pts.push(r * Math.cos(a), -15 + r * Math.sin(a));
  }
  body.circle(0, -15, 22).fill({ color: 0x8e8bf5, alpha: 0.14 });
  body.poly(pts).fill({ color: 0x8e8bf5 })
    .stroke({ color: 0xc9c6ff, width: 1.8, alpha: 0.9 });
  const face = new PIXI.Graphics();
  face.moveTo(-8.3, -13.7).quadraticCurveTo(-5.0, -18.0, -1.7, -13.7)
    .moveTo(1.7, -13.7).quadraticCurveTo(5.0, -18.0, 8.3, -13.7)
    .stroke({ color: 0x211e3a, width: 2.3, cap: "round" });
  c.addChild(shadow, body, face);
  c.__alephCreature = true;
  return c;
}
function makeNucleo(opts = {}) {
  // NÚCLEO → el átomo de Aleph (mascota canon): core HEXAGONAL con la cara ⌒⌒ + órbitas
  // achatadas ESTÁTICAS + beads que VIAJAN por la órbita con profundidad frente/atrás
  // (tickAtomArt). Nada rota en plano → el motivo React (3 elipses girando) quedó atrás.
  // opts.mini → variante 0.5× sin pedestal para el sub-núcleo de un recinto-agente.
  const V = { deep: 0x2a2150, edge: 0xb389ff, orbit: 0xc4adff, core: 0xe6d6ff };
  const RX = 20, RY = 7;                       // ~2.85:1 (canon del mock aleph-diorama)
  const c = new PIXI.Container();
  if (!opts.mini) {
    const base = new PIXI.Graphics();
    base.ellipse(0, 4, 24, 11).fill({ color: V.edge, alpha: 0.14 });
    base.poly([0, -3, 16, 4, 0, 11, -16, 4]).fill({ color: V.deep, alpha: 0.9 }).stroke({ color: V.edge, width: 1.4, alpha: 0.7 }); // pedestal iso
    c.addChild(base);
  }
  const ring = new PIXI.Container(); ring.position.set(0, -18);   // órbitas FIJAS (los beads viajan, el aro no gira)
  [0, 60, 120].forEach((deg) => {
    const o = new PIXI.Graphics();
    o.ellipse(0, 0, RX, RY).stroke({ color: V.orbit, width: 1.5, alpha: 0.55 });
    o.rotation = deg * Math.PI / 180;
    ring.addChild(o);
  });
  const beadsG = new PIXI.Container(); beadsG.position.set(0, -18);
  const beads = [0, 60, 120].map((deg, k) => {
    const g = new PIXI.Graphics();
    g.circle(0, 0, 3.4).fill({ color: V.edge, alpha: 0.3 });      // halo suave
    g.circle(0, 0, 1.9).fill({ color: V.core });                  // bead
    beadsG.addChild(g);
    const rot = deg * Math.PI / 180;
    return { g, k, cos: Math.cos(rot), sin: Math.sin(rot) };
  });
  const core = new PIXI.Container(); core.position.set(0, -18);   // hex + cara = la mascota
  const hex = new PIXI.Graphics();
  const HR = 9.5, pts = [];
  for (let i = 0; i < 6; i++) { const a = -Math.PI / 2 + i * Math.PI / 3; pts.push(HR * Math.cos(a), HR * Math.sin(a)); }
  hex.circle(0, 0, 13).fill({ color: V.edge, alpha: 0.12 });      // glow suave bajo el hex
  hex.poly(pts).fill({ color: mix(V.edge, 0xffffff, 0.18) }).stroke({ color: mix(V.edge, 0xffffff, 0.45), width: 1.4, alpha: 0.9 });
  const face = new PIXI.Graphics();                               // ⌒⌒ · los ojos felices del canon
  face.moveTo(-5.2, 0.6).quadraticCurveTo(-3.1, -2.8, -1.0, 0.6)
      .moveTo(1.0, 0.6).quadraticCurveTo(3.1, -2.8, 5.2, 0.6)
      .stroke({ color: V.deep, width: 1.7, cap: "round" });
  core.addChild(hex, face);
  c.addChild(ring, beadsG, core);
  c.__core = core; c.__ring = ring; c.__beads = beads; c.__face = face;
  if (opts.mini) c.scale.set(0.5);
  return c;
}
function makeGate(color = ATOM_COLOR.gate) {
  // GATE → candado: cuerpo + arco (shackle) en U invertida = silueta inequívoca de candado,
  // distinta de la puerta. Pieza colocable (atomKind "gate"); NO toca el candado-sobre-la-línea (F5).
  const c = new PIXI.Container();
  const plate = new PIXI.Graphics();
  plate.poly([0, -8, 26, 5, 0, 18, -26, 5]).fill({ color, alpha: 0.18 }).stroke({ color, width: 1, alpha: 0.5 });
  const face = mix(color, 0xffffff, 0.24), edge = mix(color, 0x000000, 0.42), hole = mix(color, 0x0b0e14, 0.6);
  const shackle = new PIXI.Graphics();
  shackle.moveTo(-8, -9).lineTo(-8, -16).arc(0, -16, 8, Math.PI, 2 * Math.PI).lineTo(8, -9)
    .stroke({ color: edge, width: 3.4, cap: "round", join: "round" });
  const body = new PIXI.Graphics();
  body.roundRect(-13, -12, 26, 24, 4).fill({ color: face }).stroke({ color: edge, width: 2 });
  const key = new PIXI.Graphics();
  key.circle(0, -2, 3).fill({ color: hole }).poly([-1.6, -1, 1.6, -1, 1, 7, -1, 7]).fill({ color: hole }); // ojo de cerradura
  c.addChild(plate, shackle, body, key);
  c.__tint = (tint) => { body.tint = tint; };
  return c;
}

// ── geometría / util ──────────────────────────────────────────────────────────
function sceneBounds(scene) {
  const { grid } = scene; let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const o = { x: 0, y: 0 };
  const consider = (gx, gy, padTop = 0) => { const p = isoToScreen(gx, gy, grid, o);
    minX = Math.min(minX, p.x - grid.tileWidth / 2); maxX = Math.max(maxX, p.x + grid.tileWidth / 2);
    minY = Math.min(minY, p.y - grid.tileHeight / 2 - padTop); maxY = Math.max(maxY, p.y + grid.tileHeight / 2); };
  for (const t of scene.tiles) consider(t.gridX, t.gridY);
  for (const p of scene.props) consider(p.gridX, p.gridY, 90);
  return { minX, minY, maxX, maxY, w: maxX - minX, h: maxY - minY };
}
function mix(a, b, t) {
  t = Math.max(0, Math.min(1, t));
  const ar = (a >> 16) & 255, ag = (a >> 8) & 255, ab = a & 255;
  const br = (b >> 16) & 255, bg = (b >> 8) & 255, bb = b & 255;
  return ((ar + (br - ar) * t) << 16) | ((ag + (bg - ag) * t) << 8) | (ab + (bb - ab) * t);
}
