/* metodo.graph.js — MODO WORKFLOW: pantalla propia, grafo Obsidian VIVO (ORDEN §6).
 *
 * PROHIBIDO n8n/Zapier: cero cajitas, cero flechas de secuencia, cero grid,
 * CERO NUMERACIÓN de ningún tipo. La dirección es TEMPORAL: la actividad ES la
 * narrativa del orden.
 *
 * Topología: Núcleo al centro + SOLO las piezas que el método toca (executor
 * de sus pasos). Edges finos y orgánicos, SIEMPRE pieza↔Núcleo, NUNCA
 * pieza↔pieza (invariante núcleo-céntrico).
 *
 * Capa de vida (telemetría REAL del espinazo, no coreografía):
 *   chispa  → donde la actividad está AHORA (tool en una pieza · razonamiento
 *             en el Núcleo), con ida+Eco Núcleo↔pieza.
 *   brasa   → al completarse decae ~30s a un residuo tenue que NO se apaga
 *             hasta el fin del run (al cerrar se ve la estela completa).
 *   dormida → piezas del método aún no tocadas.
 *   checkpoint → chispa congelada en el Núcleo, pulso lento tipo respiración.
 *   fallo   → pieza trabada pulsa en ámbar lento + icono de diagnóstico;
 *             click → card de remedios (§5, la misma que la Sala).
 * Edición en vivo: SOLO con run pausado → editar → reanudar. */

import { MetodoAPI, openSpine, scrubSecrets } from "./metodo.api.js";

const trM = (k, fb) => { const s = window.t ? window.t(k) : null; return (s && s !== k) ? s : fb; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

const EMBER_FLOOR = 0.16;   // la brasa nunca baja de acá hasta el fin del run
const EMBER_SECS = 30;      // decaimiento chispa→brasa

function injectCSS() {
  if (document.getElementById("met-gr-css")) return;
  const s = document.createElement("style"); s.id = "met-gr-css";
  /* [sistema 2026-07-31] El chrome DOM del grafo (chips y cajón) entra al sistema: cero
   * bordes, superficie + radio en vez de línea, --font-ui en vez de familias hardcodeadas.
   * La PALETA DEL CANVAS no se toca: el lienzo del grafo tiene su propio fondo (--grafo-bg)
   * en los dos temas y sus colores son de pintura, no de piel. */
  s.textContent = [
    ".gr-chip{display:inline-flex;align-items:center;gap:6px;font:300 11.5px var(--font-ui);border-radius:var(--r-full);padding:5px 12px;border:0;background:var(--paper2);color:var(--muted)}",
    ".gr-chip .dot{width:7px;height:7px;border-radius:50%;background:var(--muted)}",
    ".gr-chip.run .dot{background:var(--accent);animation:grPulse 1.4s ease-in-out infinite}",
    ".gr-chip.wait{background:var(--amber-bg);color:var(--amber)}",
    ".gr-chip.wait .dot{background:var(--amber);animation:grBreath 2.8s ease-in-out infinite}",
    ".gr-chip.fail{background:var(--amber-bg);color:var(--amber)}",
    ".gr-chip.fail .dot{background:var(--amber);animation:grPulse 2.2s ease-in-out infinite}",
    "@keyframes grPulse{0%,100%{opacity:1}50%{opacity:.35}}",
    "@keyframes grBreath{0%,100%{transform:scale(1);opacity:.9}50%{transform:scale(1.5);opacity:.5}}",
    /* drawer del grafo: lista de pasos (solo lectura) + card de remedios */
    ".grd-h{display:flex;align-items:center;gap:9px;margin:2px 0 14px}",
    ".grd-h b{font:400 var(--fs-xl) var(--font-ui);letter-spacing:var(--tracking-title);color:var(--ink);flex:1}",
    ".grd-close{border:0;background:var(--paper2);color:var(--muted);border-radius:var(--r-sm);width:27px;height:27px;cursor:pointer}",
    ".grd-close:hover{color:var(--ink)}",
    ".grd-step{padding:11px 14px;border:0;background:var(--paper2);border-radius:var(--r-md);margin-bottom:8px;font:300 13px/1.55 var(--font-ui)}",
    ".grd-step .phn{display:block;font:300 10.5px var(--font-ui);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:3px}",
    ".grd-step .ck{color:var(--amber);font-size:11px;margin-left:6px}",
    ".grd-note{font:300 12px var(--font-ui);color:var(--muted);margin:10px 0}",
    ".grfail{border:0;background:var(--amber-bg);border-radius:var(--r-lg);padding:15px 17px;margin-bottom:12px;animation:fadeUp .2s ease both}",
    ".grfail b{display:block;color:var(--amber);font:400 12px var(--font-ui);letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}",
    ".grfail .stx{font:400 var(--fs-md) var(--font-ui);margin-bottom:6px}",
    ".grfail .diag{font:300 12.5px/1.55 var(--font-ui);color:var(--muted);margin-bottom:12px}",
    ".grfail .acts{display:flex;flex-direction:column;gap:6px}",
    ".grfail .acts button{text-align:left;border:0;background:var(--paper);color:var(--ink);border-radius:var(--r-md);padding:10px 14px;font:400 12.5px/1.35 var(--font-ui);cursor:pointer}",
    ".grfail .acts button:hover{filter:brightness(1.1)}",
    ".grfail .free{display:flex;gap:6px;margin-top:8px}",
    ".grfail .free input{flex:1;border:0;background:var(--paper)!important;color:var(--ink);border-radius:var(--r-md);padding:9px 13px;font:300 12.5px/1.3 var(--font-ui);outline:none}",
    ".grfail .free input:focus{background:var(--accent-soft)!important}",
  ].join("\n");
  document.head.appendChild(s);
}

/* rand determinista por índice (layout estable, red que respira sin sorteo) */
function seeded(i) { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); }

export function mountGrafo(cfg) {
  injectCSS();
  const { section, canvas, drawer, strip, toast, onEditPaso } = cfg;
  const say = toast || function () {};
  let method = cfg.method;
  const live = cfg.live || null;   // { spaceId, runId, puppetId } | null

  /* ── modelo del grafo: Núcleo + piezas que el método toca ── */
  const nodes = [];   // [0] = núcleo
  // mapa SIN prototipo: un executor llamado 'constructor' es contenido, no una clave heredada
  const byKey = Object.create(null);
  function buildNodes() {
    nodes.length = 0; for (const k in byKey) delete byKey[k];
    const core = { key: "nucleo", label: trM("met.gr.nucleo", "Núcleo"), core: true,
      x: 0, y: 0, vx: 0, vy: 0, heat: 0, ember: false, active: false, failed: null, steps: [] };
    nodes.push(core); byKey.nucleo = core;
    (method.steps || []).forEach((s, i) => {
      const ex = s.executor && String(s.executor).trim();
      if (!ex) { core.steps.push(s.id); return; }
      const k = norm(ex);
      if (!byKey[k]) {
        const n = { key: k, label: ex, core: false, x: 0, y: 0, vx: 0, vy: 0,
          heat: 0, ember: false, active: false, failed: null, steps: [],
          rest: 150 + seeded(i) * 80, ph: seeded(i * 7) * Math.PI * 2 };
        nodes.push(n); byKey[k] = n;
      }
      byKey[k].steps.push(s.id);
    });
    layoutInit();
  }
  function layoutInit() {
    const W = canvas.clientWidth || 900, H = canvas.clientHeight || 600;
    const core = nodes[0]; core.x = W / 2; core.y = H / 2;
    const pieces = nodes.slice(1);
    pieces.forEach((n, i) => {
      const a = (i / Math.max(1, pieces.length)) * Math.PI * 2 + seeded(i * 3) * 0.7;
      n.x = core.x + Math.cos(a) * n.rest; n.y = core.y + Math.sin(a) * n.rest;
    });
  }
  function matchNode(name) {
    const k = norm(name); if (!k) return null;
    if (byKey[k]) return byKey[k];
    for (const key in byKey) { if (key !== "nucleo" && (key.includes(k) || k.includes(key))) return byKey[key]; }
    return null;
  }
  /* pieza materializada POR LA TELEMETRÍA: en el camino Simple (executor=null en
   * todos los pasos — el default del producto) el método no declara piezas, pero
   * el run SÍ las toca. La tool real que dispara crea su nodo al vuelo — sigue
   * siendo "SOLO lo que el método toca" (tocado de verdad), topología intacta.
   * (Review HIGH: sin esto, un método Simple rendía un Núcleo solo.) */
  function addPiece(name) {
    const raw = String(name || "").trim(); const k = norm(raw);
    if (!k || k === "nucleo") return null;
    if (byKey[k]) return byKey[k];
    const core = nodes[0]; const i = nodes.length;
    const a = seeded(i * 13) * Math.PI * 2;
    const n = { key: k, label: raw, core: false, x: core.x + Math.cos(a) * 60, y: core.y + Math.sin(a) * 60,
      vx: 0, vy: 0, heat: 0, ember: false, active: false, failed: null, steps: [],
      rest: 150 + seeded(i) * 80, ph: seeded(i * 7) * Math.PI * 2 };
    nodes.push(n); byKey[k] = n;
    return n;
  }

  /* ── estado del run ── */
  const run = { live: !!live, runId: (live && live.runId) || null, started: false,
    closed: false, paused: false, checkpoint: false, failed: false };

  /* ── partículas (ida + Eco por el edge) ── */
  const parts = [];
  function spark(node) {
    if (!node) return;
    node.heat = 1; node.active = true; node.ember = true;
    if (!node.core) {
      parts.push({ n: node, t: 0, dir: 1 });    // Núcleo → pieza (ida)
      parts.push({ n: node, t: 0, dir: -1, delay: 0.55 });   // pieza → Núcleo (Eco)
    }
    run.started = true;
  }
  function endActive(node) { if (node) node.active = false; }

  /* ── telemetría real → vida del grafo ── */
  function feed(ev) {
    const t = ev && (ev.type || ev.kind); if (!t) return;
    if (t === "tool_call_finished") {
      const nm = ev.tool || ev.tool_raw;
      const n = matchNode(nm) || addPiece(nm) || nodes[0];
      spark(n); setTimeout(() => endActive(n), 900);
      if (run.checkpoint) { run.checkpoint = false; }   // hubo actividad → el gate se destrabó
    }
    else if (t === "method_step_started") {
      const n = ev.executor ? (matchNode(ev.executor) || addPiece(ev.executor) || nodes[0]) : nodes[0];
      if (n.failed) n.failed = null;
      spark(n);
    }
    else if (t === "method_step_done") {
      const n = ev.executor ? matchNode(ev.executor) : nodes[0];
      endActive(n || nodes[0]);
    }
    else if (t === "gate_waiting" || t === "method_checkpoint_waiting") {
      run.checkpoint = true; nodes[0].heat = Math.max(nodes[0].heat, 0.9); nodes[0].ember = true; run.started = true;
    }
    else if (t === "method_step_failed") {
      const n = (ev.executor && (matchNode(ev.executor) || addPiece(ev.executor))) || (ev.tool && (matchNode(ev.tool) || addPiece(ev.tool))) || nodes[0];
      n.failed = { stepId: ev.step_id || null, diagnosis: ev.diagnosis || ev.detail || "",
        remedies: ev.remedies || null };
      n.ember = true; n.heat = Math.max(n.heat, EMBER_FLOOR); run.failed = true; run.started = true;
    }
    else if (t === "method_paused") { run.paused = true; }
    else if (t === "method_resumed") { run.paused = false; }
    else if (t === "closed") { run.closed = true; run.checkpoint = false; }
    paintStrip();
  }

  /* ── espinazo vivo (run real) ── */
  let spine = null;
  if (live && live.spaceId) spine = openSpine(live.spaceId, feed);

  /* ── strip (estado + pausa/reanudar + editar) ── */
  function stateLabel() {
    if (!run.live) return { cls: "", txt: trM("met.gr.sin_run", "sin run — el método respira") };
    if (run.closed) return { cls: run.failed ? "fail" : "", txt: run.failed ? trM("met.gr.fallo_fin", "terminó con un paso trabado") : trM("met.gr.terminado", "terminó — la estela queda a la vista") };
    if (run.failed) return { cls: "fail", txt: trM("met.gr.fallo", "un paso está trabado — tú mandas") };
    if (run.paused) return { cls: "", txt: trM("met.gr.pausado", "pausado — edita y reanuda") };
    if (run.checkpoint) return { cls: "wait", txt: trM("met.gr.checkpoint", "checkpoint — el proceso te espera") };
    if (run.started) return { cls: "run", txt: trM("met.gr.corriendo", "corriendo") };
    return { cls: "run", txt: trM("met.gr.esperando", "esperando actividad del run…") };
  }
  function paintStrip() {
    strip.nombre.textContent = method.name || "";
    const st = stateLabel();
    strip.estado.innerHTML = '<span class="gr-chip ' + st.cls + '"><span class="dot"></span>' + esc(st.txt) + "</span>";
    const p = strip.pausa;
    if (run.live && !run.closed) {
      p.hidden = false;
      p.textContent = run.paused ? ("▶ " + trM("met.gr.reanudar", "Reanudar")) : ("⏸ " + trM("met.gr.pausar", "Pausar"));
    } else p.hidden = true;
    // edición en vivo: SOLO pausado (ORDEN §6). Sin run: editar siempre.
    strip.editar.hidden = run.live ? !(run.paused && !run.closed) : false;
  }
  strip.pausa.onclick = async () => {
    if (!run.runId) { say(esc(trM("met.gr.sin_runid", "El run aún no registró su id — un momento."))); return; }
    try {
      if (run.paused) { await MetodoAPI.resumeRun(run.runId, method); run.paused = false; }
      else { await MetodoAPI.pauseRun(run.runId); run.paused = true; }
    } catch (e) { say(esc(trM("met.gr.err_pausa", "No pude cambiar la pausa.")) + " · " + esc(e.message)); }
    paintStrip();
  };
  strip.editar.onclick = () => { if (onEditPaso) onEditPaso(null); };

  /* ── drawer: pasos de una pieza (lectura) · card de remedios (§5) ── */
  function openDrawerSteps(node) {
    const ids = node.steps || [];
    const steps = (method.steps || []).filter((s) => ids.includes(s.id) || (node.core && !s.executor));
    drawer.classList.add("on");
    let h = '<div class="grd-h"><b' + (node.core ? "" : ' data-no-tm') + ">" + esc(node.core ? trM("met.gr.nucleo", "Núcleo") : node.label) + '</b><button class="grd-close" data-grd-close>✕</button></div>';
    if (node.failed) h += failCardHTML(node);
    steps.forEach((s) => {
      // §8: el texto del paso y el nombre de fase son CONTENIDO del usuario → data-no-tm
      h += '<div class="grd-step" data-no-tm>' + (s.phase ? ('<span class="phn">' + esc(s.phase) + "</span>") : "") +
        esc(s.text) + (s.checkpoint ? ('<span class="ck">◈ ' + esc(trM("met.checkpoints", "checkpoints").replace(/s$/, "")) + "</span>") : "") + "</div>";
    });
    if (run.live && !run.paused && !run.closed && !node.failed)
      h += '<div class="grd-note">' + esc(trM("met.gr.pausa_para_editar", "Pausa el run para editar — única edición en vivo permitida.")) + "</div>";
    drawer.innerHTML = h;
    drawer.querySelector("[data-grd-close]").onclick = closeDrawer;
    if (node.failed) wireFailCard(node);
  }
  function closeDrawer() { drawer.classList.remove("on"); drawer.innerHTML = ""; }

  function failCardHTML(node) {
    const f = node.failed || {};
    const step = (method.steps || []).find((s) => s.id === f.stepId);
    const sug = f.remedies && (f.remedies.suggested_label || f.remedies.suggested);
    // [H6] diagnosis/step/sugerencia vienen de EVENTOS del espinazo → scrub SIEMPRE
    // (mismo trato que la Sala le da al MISMO evento — review de seguridad)
    return '<div class="grfail" data-fail>' +
      "<b>" + esc(trM("met.gr.fail_h", "Paso sin evidencia — tú mandas")) + "</b>" +
      (step ? ('<div class="stx" data-no-tm>' + esc(scrubSecrets(step.text)) + "</div>") : "") +
      '<div class="diag">' + esc(trM("met.gr.fail_diag", "Diagnóstico:")) + " " + esc(scrubSecrets(f.diagnosis || trM("met.gr.fail_sin_diag", "sin diagnóstico del motor"))) + "</div>" +
      '<div class="acts">' +
      (sug ? ('<button data-rem="apply">' + esc(trM("met.gr.fail_aplicar", "Aplicar la solución sugerida")) + " · " + esc(scrubSecrets(String(sug))) + "</button>") : "") +
      '<button data-rem="retry">' + esc(trM("met.gr.fail_retry", "Reintentar ahora")) + "</button>" +
      '<button data-rem="retry_in">' + esc(trM("met.gr.fail_retry5", "Reintentar en 5 min")) + "</button>" +
      '<button data-rem="skip">' + esc(trM("met.gr.fail_saltar", "Saltar este paso (queda en auditoría)")) + "</button>" +
      '<button data-rem="edit">' + esc(trM("met.gr.fail_editar", "Editar el paso")) + "</button>" +
      "</div>" +
      '<div class="free"><input data-rem-free placeholder="' + esc(trM("met.gr.fail_libre_ph", "o dile qué hacer con tus palabras…")) + '">' +
      '<button class="met-btn sec" data-rem-send>' + esc(trM("met.gr.fail_enviar", "Enviar")) + "</button></div></div>";
  }
  function wireFailCard(node) {
    const f = node.failed || {};
    drawer.querySelectorAll("[data-rem]").forEach((b) => b.onclick = async () => {
      const act = b.getAttribute("data-rem");
      if (act === "edit") {
        // editar el paso = pausa primero (única edición en vivo permitida)
        try { if (run.live && !run.paused && run.runId) { await MetodoAPI.pauseRun(run.runId); run.paused = true; paintStrip(); } }
        catch (e) { say(esc(trM("met.gr.err_pausa", "No pude cambiar la pausa.")) + " · " + esc(e.message)); return; }
        if (onEditPaso) onEditPaso(f.stepId ? [f.stepId] : null);
        return;
      }
      try {
        await MetodoAPI.remedy(run.runId, f.stepId, act, act === "retry_in" ? { minutes: 5 } : null);
        node.failed = null; run.failed = false; closeDrawer(); paintStrip();
      } catch (e) { say(esc(trM("met.gr.err_remedio", "No pude aplicar ese remedio.")) + " · " + esc(e.message)); }
    });
    const send = drawer.querySelector("[data-rem-send]");
    if (send) send.onclick = async () => {
      const v = drawer.querySelector("[data-rem-free]").value.trim(); if (!v) return;
      try {
        await MetodoAPI.remedy(run.runId, f.stepId, "free_text", { text: v });
        node.failed = null; run.failed = false; closeDrawer(); paintStrip();
      } catch (e) { say(esc(trM("met.gr.err_remedio", "No pude aplicar ese remedio.")) + " · " + esc(e.message)); }
    };
  }

  function clickNode(node) {
    if (!node) return;
    if (node.failed) { openDrawerSteps(node); return; }
    // sin run, o run pausado → panel editor (metodo.html decide el montaje)
    if (!run.live || (run.paused && !run.closed)) { if (onEditPaso) onEditPaso(node.core ? null : node.steps.slice()); return; }
    openDrawerSteps(node);   // run corriendo → lectura (el método no se edita en caliente)
  }

  /* ── canvas: física + render ── */
  const ctx = canvas.getContext("2d");
  let W = 0, H = 0, DPR = 1, raf = 0, last = 0, tGlobal = 0;
  let reduced = false;
  try { reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}
  const COL = { ink: "#EDEBFA", faint: "#6E6B92", accent: "#8E8BF5", deep: "#C9C6FF", amber: "#E0A23C", line: "#2E2F48" };
  function refreshTokens() {
    try {
      const cs = getComputedStyle(document.documentElement);
      ["ink", "faint", "accent", "amber", "line"].forEach((k) => {
        const v = cs.getPropertyValue("--" + (k === "deep" ? "accent-deep" : k)).trim(); if (v) COL[k] = v;
      });
      const d = cs.getPropertyValue("--accent-deep").trim(); if (d) COL.deep = d;
    } catch (e) {}
  }
  refreshTokens();
  const thObs = new MutationObserver(refreshTokens);
  try { thObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); } catch (e) {}

  function resize() {
    DPR = window.devicePixelRatio || 1;
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.max(1, W * DPR); canvas.height = Math.max(1, H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  const ro = new ResizeObserver(() => { const c = nodes[0]; const ox = c ? c.x : 0, oy = c ? c.y : 0; resize(); if (c) { const dx = W / 2 - ox, dy = H / 2 - oy; nodes.forEach((n) => { n.x += dx; n.y += dy; }); } });
  ro.observe(canvas);

  function physics(dt) {
    const core = nodes[0];
    // el Núcleo respira anclado al centro
    core.vx += (W / 2 - core.x) * 0.02; core.vy += (H / 2 - core.y) * 0.02;
    for (let i = 1; i < nodes.length; i++) {
      const n = nodes[i];
      // resorte pieza↔Núcleo (LA única arista)
      const dx = core.x - n.x, dy = core.y - n.y, d = Math.max(24, Math.hypot(dx, dy));
      const f = (d - n.rest) * 0.004;
      n.vx += (dx / d) * f * d * 0.016; n.vy += (dy / d) * f * d * 0.016;
      // repulsión pieza↔pieza (espacio, no conexión)
      for (let j = 1; j < nodes.length; j++) {
        if (i === j) continue;
        const m = nodes[j];
        const rx = n.x - m.x, ry = n.y - m.y, rd = Math.max(30, Math.hypot(rx, ry));
        const rf = 2600 / (rd * rd);
        n.vx += (rx / rd) * rf; n.vy += (ry / rd) * rf;
      }
      // drift orgánico: la red respira aún sin run
      if (!reduced) {
        n.vx += Math.sin(tGlobal * 0.5 + n.ph) * 0.045;
        n.vy += Math.cos(tGlobal * 0.42 + n.ph * 1.7) * 0.045;
      }
    }
    nodes.forEach((n) => {
      if (n === dragN) { n.vx = 0; n.vy = 0; return; }
      n.vx *= 0.86; n.vy *= 0.86;
      const vmax = 3.2; n.vx = Math.max(-vmax, Math.min(vmax, n.vx)); n.vy = Math.max(-vmax, Math.min(vmax, n.vy));
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(30, Math.min(W - 30, n.x)); n.y = Math.max(30, Math.min(H - 30, n.y));
    });
  }
  function decay(dt) {
    nodes.forEach((n) => {
      if (n.active) return;
      const floor = (n.ember && !runFullyOff()) ? EMBER_FLOOR : (n.ember ? EMBER_FLOOR : 0);
      if (n.heat > floor) n.heat = Math.max(floor, n.heat - dt / EMBER_SECS);
    });
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i];
      if (p.delay && p.delay > 0) { p.delay -= dt; continue; }
      p.t += dt / 0.8;
      if (p.t >= 1) parts.splice(i, 1);
    }
  }
  function runFullyOff() { return false; }   // la brasa queda hasta que la pantalla se cierre (estela)

  function alpha(c, a) {
    // c = '#rrggbb' (tokens de la casa) → rgba
    const m = /^#?([0-9a-f]{6})$/i.exec(c.trim());
    if (!m) return c;
    const v = parseInt(m[1], 16);
    return "rgba(" + ((v >> 16) & 255) + "," + ((v >> 8) & 255) + "," + (v & 255) + "," + a + ")";
  }
  function edgePoint(core, n, t, wob) {
    // curva cuadrática con control desplazado (orgánico, nada de flechas)
    const mx = (core.x + n.x) / 2, my = (core.y + n.y) / 2;
    const dx = n.x - core.x, dy = n.y - core.y, d = Math.max(1, Math.hypot(dx, dy));
    const ox = -dy / d, oy = dx / d;
    const cx = mx + ox * wob, cy = my + oy * wob;
    const a = 1 - t;
    return { x: a * a * core.x + 2 * a * t * cx + t * t * n.x, y: a * a * core.y + 2 * a * t * cy + t * t * n.y, cx, cy };
  }
  function draw() {
    ctx.clearRect(0, 0, W, H);
    const core = nodes[0];
    // edges pieza↔Núcleo
    for (let i = 1; i < nodes.length; i++) {
      const n = nodes[i];
      const wob = Math.sin(tGlobal * 0.35 + n.ph) * 14;
      const { cx, cy } = edgePoint(core, n, 0.5, wob);
      const glow = Math.max(n.heat, core.heat * 0.3);
      ctx.beginPath(); ctx.moveTo(core.x, core.y); ctx.quadraticCurveTo(cx, cy, n.x, n.y);
      ctx.strokeStyle = alpha(COL.accent, 0.08 + glow * 0.30); ctx.lineWidth = 1 + glow * 0.8; ctx.stroke();
    }
    // partículas ida+Eco
    parts.forEach((p) => {
      if (p.delay && p.delay > 0) return;
      const t = p.dir === 1 ? p.t : 1 - p.t;
      const wob = Math.sin(tGlobal * 0.35 + p.n.ph) * 14;
      const pt = edgePoint(core, p.n, Math.min(1, Math.max(0, t)), wob);
      const g = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, 7);
      g.addColorStop(0, alpha(COL.deep, 0.95)); g.addColorStop(1, alpha(COL.deep, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(pt.x, pt.y, 7, 0, Math.PI * 2); ctx.fill();
    });
    // nodos
    nodes.forEach((n) => {
      const r = n.core ? 15 : 8;
      const breath = reduced ? 0 : Math.sin(tGlobal * 0.8 + (n.ph || 0)) * 0.06 + 0.06;
      let h = n.heat;
      // checkpoint: chispa congelada en el Núcleo, respiración lenta
      let ckPulse = 0;
      if (n.core && run.checkpoint) ckPulse = (Math.sin(tGlobal * (Math.PI * 2 / 2.8)) + 1) / 2;
      // fallo: pulso ámbar lento
      let failPulse = 0;
      if (n.failed) failPulse = (Math.sin(tGlobal * (Math.PI * 2 / 2.2)) + 1) / 2;
      const base = 0.22 + breath;   // dormido: tenue que respira
      const lit = Math.min(1, base + h * 0.85);
      const colMain = n.failed ? COL.amber : (h > 0.02 || n.core ? COL.accent : COL.faint);
      // halo
      const halo = r * (2.1 + h * 1.9 + ckPulse * 1.4 + failPulse * 1.2);
      const g = ctx.createRadialGradient(n.x, n.y, r * 0.4, n.x, n.y, halo);
      g.addColorStop(0, alpha(colMain, 0.32 * lit + failPulse * 0.25 + (n.core ? ckPulse * 0.3 : 0)));
      g.addColorStop(1, alpha(colMain, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, halo, 0, Math.PI * 2); ctx.fill();
      // cuerpo
      ctx.beginPath(); ctx.arc(n.x, n.y, r + (n.core ? ckPulse * 2.4 : 0) + (reduced ? 0 : Math.sin(tGlobal + (n.ph || 0)) * 0.6), 0, Math.PI * 2);
      ctx.fillStyle = alpha(n.failed ? COL.amber : (h > 0.02 ? COL.deep : COL.faint), Math.max(0.35, lit));
      ctx.fill();
      // icono de diagnóstico en pieza trabada (glifo, JAMÁS un número)
      if (n.failed) {
        ctx.fillStyle = alpha(COL.amber, 0.6 + failPulse * 0.4);
        ctx.beginPath(); ctx.arc(n.x + r + 7, n.y - r - 5, 7, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#1a1508"; ctx.font = "700 10px 'Outfit',system-ui,sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText("!", n.x + r + 7, n.y - r - 4.4);
      }
      // etiqueta (nombre de la pieza — sin números, sin orden gráfico)
      ctx.font = (n.core ? "600 12.5px" : "500 11px") + " 'Outfit',system-ui,sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillStyle = alpha(COL.ink, 0.35 + lit * 0.55);
      ctx.fillText(n.label, n.x, n.y + r + 7);
    });
  }
  function loop(ts) {
    if (destroyed) return;
    const dt = Math.min(0.1, last ? (ts - last) / 1000 : 0.016); last = ts; tGlobal += dt;
    physics(dt); decay(dt); draw();
    raf = requestAnimationFrame(loop);
  }

  /* ── interacción: hover + drag + click ── */
  let dragN = null, downAt = null;
  function nodeAt(mx, my) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i]; const r = (n.core ? 15 : 8) + 14;
      if ((mx - n.x) * (mx - n.x) + (my - n.y) * (my - n.y) <= r * r) return n;
    }
    return null;
  }
  function evPos(e) { const b = canvas.getBoundingClientRect(); return { x: e.clientX - b.left, y: e.clientY - b.top }; }
  // handlers NOMBRADOS: el canvas sobrevive entre montajes (vive en metodo.html) —
  // destroy() los remueve o cada re-montaje duplicaría clicks con estado muerto.
  const onPtrDown = (e) => {
    if (destroyed) return;
    const p = evPos(e); const n = nodeAt(p.x, p.y);
    if (n) { dragN = n; downAt = { x: p.x, y: p.y, t: Date.now() }; canvas.setPointerCapture(e.pointerId); }
  };
  const onPtrMove = (e) => {
    if (destroyed) return;
    const p = evPos(e);
    if (dragN) { dragN.x = p.x; dragN.y = p.y; }
    else canvas.style.cursor = nodeAt(p.x, p.y) ? "pointer" : "default";
  };
  const onPtrUp = (e) => {
    if (destroyed) return;
    const p = evPos(e);
    if (dragN && downAt && Math.hypot(p.x - downAt.x, p.y - downAt.y) < 6 && Date.now() - downAt.t < 600) clickNode(dragN);
    dragN = null; downAt = null;
  };
  canvas.addEventListener("pointerdown", onPtrDown);
  canvas.addEventListener("pointermove", onPtrMove);
  canvas.addEventListener("pointerup", onPtrUp);

  /* ── arranque ── */
  buildNodes(); resize(); paintStrip();
  let destroyed = false;
  raf = requestAnimationFrame(loop);

  return {
    feed,
    setMethod(m) { method = m; buildNodes(); paintStrip(); },
    nodes: () => nodes.map((n) => ({ key: n.key, label: n.label, core: !!n.core, heat: n.heat, ember: n.ember, active: n.active, failed: !!n.failed, steps: n.steps.slice(), x: n.x, y: n.y })),
    edges: () => nodes.slice(1).map((n) => ["nucleo", n.key]),   // topología: SIEMPRE pieza↔Núcleo
    state: () => ({ live: run.live, closed: run.closed, paused: run.paused, checkpoint: run.checkpoint, failed: run.failed, started: run.started }),
    destroy() {
      destroyed = true; cancelAnimationFrame(raf);
      if (spine) spine.stop = true;
      canvas.removeEventListener("pointerdown", onPtrDown);
      canvas.removeEventListener("pointermove", onPtrMove);
      canvas.removeEventListener("pointerup", onPtrUp);
      try { ro.disconnect(); thObs.disconnect(); } catch (e) {}
      closeDrawer();
    },
    /* hooks de verificación (probado, no razonado) */
    _clickNode: (key) => clickNode(byKey[norm(key)] || byKey[key]),
    _tick: (secs) => { decay(secs); },
    _setRunId: (id) => { run.runId = id; },
  };
}
