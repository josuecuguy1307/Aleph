/* cuarto.live.js — VISTA EN VIVO DEL RECON dentro del Cuarto (FASE 2 del motor).
 *
 * Consume el stream de eventos del motor de inspección por el MISMO canal SSE que
 * ya usa el run (/v1/spaces/{id}/stream, eventos nombrados) y lo ANIMA en Pixi,
 * "alive como first-class": un software externo APARECE en la escena, LATE mientras
 * se analiza, y se SOLIDIFICA en un capability-block cuando la tool queda observada.
 * Es el DINÁMICA DIAGRAMA TALLER: build = use. El agente se cablea y el Cuarto lo muestra.
 *
 * Estado en MEMORIA + push del backend — sin localStorage ni storage del browser.
 * Additivo: no toca el builder; se activa sólo con ?recon=<spaceId>.
 *
 * Ciclo de eventos:
 *   recon.conectado        → "conectado"
 *   software.detectado     → aparece la tarjeta del software (host/title)
 *   inspeccion.analizando  → late/escanea (rings), muestra # requests
 *   accion.observada       → flash + muestra la request aislada (METHOD path)
 *   tool.sintetizada       → se solidifica en un capability-block (placeTile) → "listo"
 */
import { isoToScreen } from "./cuarto.scene.schema.js";

const STATE_COLOR = {
  conectado: 0x46b1ff,
  analizando: 0xffc24b,
  observada: 0x9af7e6,
  sintetizada: 0x57e08a,
};
// category → zona destino (misma regla C3 del render): write/send → entrega
const CAT_ZONE = { read: "fuentes", process: "mesa", write: "entrega", send: "entrega" };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function openSSE(url) {
  return new Promise((resolve) => {
    let settled = false;
    const es = new EventSource(url);
    es.onopen = () => { if (!settled) { settled = true; resolve(es); } };
    es.onerror = () => { if (!settled) { settled = true; es.close(); resolve(null); } };
  });
}
async function openSSERetry(url, tries = 80, gap = 250) {
  for (let i = 0; i < tries; i++) {
    const es = await openSSE(url);
    if (es) return es;
    await sleep(gap);
  }
  return null;
}

/**
 * Arranca la vista en vivo.
 * @param {object} opts
 * @param {object} opts.api     - el api devuelto por mountCuarto
 * @param {string} opts.spaceId - id del space que el motor está emitiendo
 * @param {function} [opts.onState] - callback(stateText, kind) para el HUD
 */
export async function startLiveRecon({ api, spaceId, onState = () => {} }) {
  const PIXI = window.PIXI;
  const stage = api.app.stage;
  const { scene, origin } = api;
  const { grid } = scene;

  // ── capa overlay propia (sobre todo lo demás) ──
  const layer = new PIXI.Container();
  layer.zIndex = 100000;
  layer.sortableChildren = true;
  stage.addChild(layer);
  if (stage.sortableChildren !== true) stage.sortableChildren = true;

  // posición de "entrada": arriba-centro de la escena (como entrando por la puerta MCP)
  const W = api.app.screen.width, H = api.app.screen.height;
  const entry = { x: W * 0.5, y: Math.max(54, H * 0.12) };

  // ── la tarjeta del SOFTWARE detectado ──
  const card = new PIXI.Container();
  card.position.set(entry.x, entry.y);
  card.alpha = 0;
  layer.addChild(card);

  const ring = new PIXI.Graphics();      // anillos de escaneo
  ring.zIndex = 0; card.addChild(ring);
  const box = new PIXI.Graphics();
  box.zIndex = 1; card.addChild(box);
  const title = new PIXI.Text({
    text: "", style: { fontFamily: "ui-sans-serif, system-ui, sans-serif",
      fontSize: 13, fontWeight: "500", fill: 0xeaf0fb, align: "center" },
  });
  title.anchor.set(0.5); title.position.set(0, -7); title.zIndex = 2; card.addChild(title);
  const sub = new PIXI.Text({
    text: "", style: { fontFamily: "var(--font-mono)", fontSize: 10,
      fill: 0x9fb0c4, align: "center" },
  });
  sub.anchor.set(0.5); sub.position.set(0, 12); sub.zIndex = 2; card.addChild(sub);

  const BW = 196, BH = 50;
  function drawBox(color, glow) {
    box.clear();
    box.roundRect(-BW / 2, -BH / 2, BW, BH, 12)
      .fill({ color: 0x121724, alpha: 0.96 })
      .stroke({ color, width: 2, alpha: 0.6 + 0.4 * glow });
    // barra-acento arriba
    box.roundRect(-BW / 2 + 8, -BH / 2 + 6, 6, BH - 12, 3).fill({ color, alpha: 0.9 });
  }
  drawBox(STATE_COLOR.conectado, 0);

  // ── estado animable ──
  const st = {
    color: STATE_COLOR.conectado, colorTarget: STATE_COLOR.conectado,
    glow: 0, glowTarget: 1, pulse: 0, ringT: 0, scanning: false,
    appear: 0, alive: true,
  };
  const approach = (a, b, k) => a + (b - a) * k;

  let tk = 0;
  const ticker = (tick) => {
    if (!st.alive) return;
    tk += tick.deltaMS / 1000;
    st.appear = approach(st.appear, 1, 0.12);
    card.alpha = st.appear;
    st.glow = approach(st.glow, st.glowTarget, 0.12);
    const breathe = st.scanning ? (1 + 0.04 * Math.sin(tk * 8)) : (1 + 0.02 * Math.sin(tk * 2.2));
    card.scale.set((0.7 + 0.3 * st.appear) * breathe);
    card.y = entry.y - 4 * Math.sin(tk * 1.6);
    drawBox(st.color, 0.5 + 0.5 * Math.sin(tk * (st.scanning ? 7 : 2.4)));
    // anillos de escaneo
    ring.clear();
    if (st.scanning) {
      st.ringT += tick.deltaMS / 900;
      for (let i = 0; i < 3; i++) {
        const p = (st.ringT + i / 3) % 1;
        ring.ellipse(0, 0, (BW / 2 + 6) + p * 70, (BH / 2 + 6) + p * 34)
          .stroke({ color: st.color, width: 2, alpha: (1 - p) * 0.5 });
      }
    }
  };
  api.app.ticker.add(ticker);

  function setColor(c) { st.color = c; st.colorTarget = c; }
  function destroyCard() {
    st.alive = false;
    api.app.ticker.remove(ticker);
    try { card.destroy({ children: true }); } catch {}
    try { layer.destroy({ children: true }); } catch {}
  }

  // ── elegir una celda libre en la zona destino ──
  function freeCellInRole(role) {
    const zone = scene.zones.find((z) => z.role === role);
    if (!zone) return null;
    const placed = new Set(api.placedTiles().map((t) => `${t.gridX},${t.gridY}`));
    for (let dy = 0; dy < zone.h; dy++) {
      for (let dx = 0; dx < zone.w; dx++) {
        const gx = zone.gridX + dx, gy = zone.gridY + dy;
        if (!placed.has(`${gx},${gy}`)) return { gx, gy };
      }
    }
    return null;
  }

  // ── handlers por tipo de evento ──
  let reqCount = 0;
  const handlers = {
    "recon.conectado": () => onState("conectado al motor", "conectado"),

    "software.detectado": (e) => {
      setColor(STATE_COLOR.conectado);
      st.glowTarget = 1; st.appear = Math.max(st.appear, 0.01);
      title.text = e.label || e.title || "Software detectado";
      sub.text = e.host || e.url || "";
      onState(`detecté <b>${title.text}</b>`, "conectado");
    },

    "inspeccion.analizando": (e) => {
      setColor(STATE_COLOR.analizando);
      st.scanning = true;
      if (typeof e.requests === "number") reqCount = e.requests;
      sub.text = reqCount ? `analizando · ${reqCount} requests` : "analizando…";
      onState(`analizando${reqCount ? ` · ${reqCount} requests` : "…"}`, "analizando");
    },

    "accion.observada": (e) => {
      setColor(STATE_COLOR.observada);
      st.scanning = false; st.glow = 1.6;
      const label = e.method && e.path ? `${e.method} ${e.path}` : (e.label || "acción observada");
      sub.text = label;
      onState(`acción observada · <b>${label}</b>`, "observada");
    },

    "tool.sintetizada": async (e) => {
      setColor(STATE_COLOR.sintetizada);
      st.scanning = false; st.glow = 1.6;
      const category = e.category || "write";
      const role = CAT_ZONE[category] || "entrega";
      sub.text = "sintetizando tool…";
      onState(`sintetizando <b>${e.label || "tool"}</b>…`, "sintetizada");

      // SOLIDIFICAR: la tarjeta viaja hacia la celda destino y nace el capability-block.
      // Si la capability TOCA AFUERA (write/send → entrega) nace GATEADA (con candado).
      const cell = freeCellInRole(role);
      if (cell) {
        // punto en PANTALLA de la celda (cámara-aware: respeta pan/zoom/rotación)
        const target = api.viewPoint ? api.viewPoint(cell.gx, cell.gy) : isoToScreen(cell.gx, cell.gy, grid, origin);
        const from = { x: card.x, y: card.y };
        const dur = 620; let tt = 0;
        await new Promise((resolve) => {
          const travel = (tick) => {
            tt += tick.deltaMS / dur;
            const p = Math.min(1, tt), s = p * p * (3 - 2 * p);
            card.x = from.x + (target.x - from.x) * s;
            card.y = from.y + (target.y - 90 - from.y) * s;
            card.scale.set((0.7 + 0.3) * (1 - 0.45 * s));
            card.alpha = 1 - 0.85 * s;
            if (p >= 1) { api.app.ticker.remove(travel); resolve(); }
          };
          api.app.ticker.add(travel);
        });
        const toolId = "recon-" + Date.now();
        const gated = category === "write" || category === "send"; // toca el mundo externo
        api.placeTile({ id: toolId, key: "recon", label: e.label || "Tool", category, gated,
          server: null, atom: "tool", role,
          method: e.method, path: e.path, fields: e.fields }, cell.gx, cell.gy);
        api.pulse(toolId);
      }
      destroyCard();
      onState(`listo · <b>${e.label || "tool"}</b> es un capability-block`, "listo");
    },
  };

  // ── abrir el stream y enrutar ──
  onState("conectando al motor…", "conectando");
  const es = await openSSERetry(`/v1/spaces/${spaceId}/stream`);
  if (!es) { onState("no pude conectar al stream del motor", "error"); return null; }
  onState("conectado al motor", "conectado");

  const dispatch = (m) => {
    let e; try { e = JSON.parse(m.data); } catch { return; }
    const type = e.type || m.type;
    const h = handlers[type];
    if (h) h(e);
  };
  Object.keys(handlers).forEach((name) => es.addEventListener(name, dispatch));
  ["final", "done", "closed"].forEach((name) =>
    es.addEventListener(name, () => { try { es.close(); } catch {} }));
  es.onmessage = dispatch; // fallback para frames sin nombre

  return { es, close() { try { es.close(); } catch {} destroyCard(); } };
}
