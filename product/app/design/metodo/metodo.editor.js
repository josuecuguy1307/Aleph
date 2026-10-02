/* metodo.editor.js — el EDITOR de la pieza Método (ORDEN_METODO §3).
 *
 * Dos puertas, UN objeto: Simple (texto libre + reordenar + checkpoint + colapsar
 * fases) y Pro (chips executor/evidencia/timeout/reintentos + vista JSON editable).
 * Además: esqueletos de FORMA (prohibido hard-codear profesiones), captura
 * multimodal "Traer mi proceso" (texto/Word/PDF/imagen → structure → pulir) y
 * editar conversando (diff propuesto → aceptar/rechazar).
 *
 * Modelo: pasos PLANOS con campo `phase` (schema §2). El editor mantiene un
 * `phaseOrder` local para que existan fases vacías mientras editas; al guardar
 * viaja como campo ADITIVO `phases: [nombres]` (el backend lo preserva o lo
 * ignora — derivable de los pasos, nunca fuente única de verdad). */

import { MetodoAPI, newStep, newMethod, normalizeMethod, phasesOf, validateMethod, currentUser } from "./metodo.api.js";

const trM = (k, fb) => { const s = window.t ? window.t(k) : null; return (s && s !== k) ? s : fb; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const deep = (o) => JSON.parse(JSON.stringify(o));

/* ── CSS del editor (una vez) ─────────────────────────────────────────── */
function injectCSS() {
  if (document.getElementById("met-ed-css")) return;
  const s = document.createElement("style"); s.id = "met-ed-css";
  /* [sistema 2026-07-31] El editor entra al sistema junto con su pantalla: cero bordes,
   * cero relieves, cero hundidos — jerarquía por sombra + radio. El foco de un campo deja
   * de ser una LÍNEA y pasa a ser un TINTE (--accent-soft, el 8% del color). Las familias
   * hardcodeadas ('Hanken Grotesk') pasan a --font-ui. Los spinners dejan de ser un anillo
   * de borde y pasan a ser un cono enmascarado. Nada de esto toca la funcionalidad: son
   * las mismas clases, los mismos nodos y los mismos handlers.
   *
   * ⚠ POR QUÉ HAY !important EN LOS <input>: aleph-tokens.css trae una regla BASE de
   * controles de formulario cuyo selector es `input:not([type=checkbox]):not([type=radio])
   * :not([type=range]):not([type=color]):not([type=file])` — cinco :not() con argumento de
   * atributo, o sea especificidad (0,5,1). Ninguna regla de clase de este archivo la gana.
   * Sin !important el fondo del campo se lo comía --paper2 y el TINTE DE FOCO no se veía:
   * como el sistema ya no permite marcar el foco con una línea, el campo enfocado quedaba
   * MUDO. Sólo se fuerza `background` de <input>; los <textarea> no lo necesitan (ahí la
   * regla base es sólo `textarea`, 0,0,1). Medido en Playwright, no razonado. */
  s.textContent = [
    ".ed{max-width:860px;margin:0 auto;animation:fadeUp .22s ease both}",
    ".ed.compact{max-width:none;margin:0}",
    ".ed-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}",
    ".ed-name{flex:1;min-width:220px;border:0;background:var(--paper2)!important;outline:none;color:var(--ink);font:200 var(--fs-2xl)/1.25 var(--font-ui);letter-spacing:var(--tracking-title);padding:6px 12px;border-radius:var(--r-md)}",
    ".ed.compact .ed-name{font-size:19px}",
    ".ed-name:focus{background:var(--accent-soft)!important}",
    ".ed-name::placeholder{color:var(--faint)}",
    ".ed-sw{display:inline-flex;background:var(--paper2);border:0;border-radius:var(--r-md);padding:3px;gap:2px}",
    ".ed-sw button{border:0;background:none;color:var(--muted);border-radius:var(--r-sm);padding:6px 12px;font:400 12px/1 var(--font-ui);cursor:pointer}",
    ".ed-sw button:hover{color:var(--ink)}",
    ".ed-sw button.on{background:var(--accent-soft);color:var(--accent-deep)}",
    ".ed-meta{font:300 12px var(--font-ui);color:var(--muted);margin:2px 0 14px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}",
    ".ed-meta .dirty{color:var(--amber)}",
    ".ed-banner{background:var(--amber-bg);border:0;border-radius:var(--r-md);padding:12px 15px;margin:0 0 14px;font:300 12.5px/1.5 var(--font-ui)}",
    ".ed-banner b{display:block;color:var(--amber);font:400 12px var(--font-ui);letter-spacing:.04em;text-transform:uppercase;margin-bottom:3px}",
    /* fases — un POZO por fase dentro del plano de contenido */
    ".ph{background:var(--paper2);border:0;border-radius:var(--r-lg);margin-bottom:12px;overflow:hidden}",
    ".ph-h{display:flex;align-items:center;gap:8px;padding:11px 14px;cursor:default}",
    ".ph-h .chev{border:0;background:none;color:var(--muted);cursor:pointer;font-size:12px;width:22px;height:22px;border-radius:var(--r-xs);transition:transform .16s}",
    ".ph.closed .ph-h .chev{transform:rotate(-90deg)}",
    ".ph-h input{flex:1;border:0;background:none;outline:none;color:var(--ink);font:400 var(--fs-md)/1.3 var(--font-ui);padding:4px 6px;border-radius:var(--r-sm)}",
    ".ph-h input:focus{background:var(--accent-soft)!important}",
    ".ph-h .cnt{font:300 11px var(--font-ui);color:var(--muted);flex:none}",
    ".ph-h .phdel{border:0;background:none;color:var(--muted);cursor:pointer;font-size:12px;border-radius:var(--r-xs);width:22px;height:22px}",
    ".ph-h .phdel:hover{color:var(--red)}",
    ".ph-body{padding:2px 10px 10px}",
    ".ph.closed .ph-body{display:none}",
    /* pasos */
    ".step{display:flex;align-items:flex-start;gap:7px;padding:7px 4px;border-radius:var(--r-md);position:relative}",
    ".step.dragging{opacity:.45}",
    ".step:hover{background:var(--paper)}",
    ".step .grip{cursor:grab;color:var(--muted);font-size:13px;padding:6px 3px 0;user-select:none;touch-action:none}",
    ".step .mv{display:flex;flex-direction:column;gap:1px;padding-top:3px}",
    ".step .mv button{border:0;background:none;color:var(--muted);cursor:pointer;font-size:9px;line-height:1;padding:2px 3px;border-radius:var(--r-2xs)}",
    ".step .mv button:hover{color:var(--ink);background:var(--paper)}",
    ".step .stx{flex:1;min-width:0}",
    ".step .stx textarea{width:100%;border:0;background:none;outline:none;resize:none;color:var(--ink);font:300 var(--fs-md)/1.55 var(--font-ui);padding:7px 8px;border-radius:var(--r-sm);overflow:hidden}",
    ".step .stx textarea:focus{background:var(--accent-soft)}",
    /* el error deja de ser una línea: es un tinte de estado */
    ".step .stx textarea.err{outline:0;background:var(--amber-bg)}",
    ".step .ckb{border:0;background:var(--paper);color:var(--muted);border-radius:var(--r-sm);width:28px;height:28px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex:none;margin-top:3px}",
    ".step .ckb.on{color:var(--amber);background:var(--amber-bg)}",
    ".step .sdel{border:0;background:none;color:var(--muted);cursor:pointer;font-size:12px;border-radius:var(--r-xs);width:24px;height:24px;margin-top:5px;opacity:0}",
    ".step:hover .sdel{opacity:1}",
    ".step .sdel:hover{color:var(--red)}",
    ".step-pro{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 4px;padding-left:2px}",
    ".step-pro input{border:0;background:var(--paper)!important;color:var(--ink);border-radius:var(--r-sm);padding:6px 10px;font:300 11.5px/1.2 var(--font-ui);outline:none}",
    ".step-pro input:focus{background:var(--accent-soft)!important}",
    ".step-pro .pexe{width:200px}.step-pro .pevi{width:170px}.step-pro .ptmo{width:78px}.step-pro .pret{width:86px}",
    ".ph-add{display:flex;gap:7px;padding:4px 4px 2px}",
    ".ph-add input{flex:1;border:0;background:var(--paper)!important;color:var(--ink);border-radius:var(--r-md);padding:9px 12px;font:300 13px/1.3 var(--font-ui);outline:none}",
    ".ph-add input:focus{background:var(--accent-soft)!important}",
    ".ed-addph{display:flex;align-items:center;gap:10px;margin:2px 0 18px}",
    ".ed-addph .hint{font:300 11.5px var(--font-ui);color:var(--muted)}",
    ".drop-mark{height:2px;background:var(--accent);border-radius:var(--r-2xs);margin:0 8px}",
    /* JSON */
    ".ed-json textarea{width:100%;min-height:340px;resize:vertical;border:0;background:var(--paper2);color:var(--ink);border-radius:var(--r-lg);padding:14px;font:400 12px/1.55 var(--font-mono);outline:none}",
    ".ed-json .jerr{color:var(--amber);font:300 12px var(--font-ui);margin:8px 0;white-space:pre-wrap}",
    ".ed-json .foot{display:flex;gap:8px;margin-top:10px}",
    /* conversar / diff */
    ".ed-conv{margin-top:24px;border:0;padding-top:16px}",
    ".ed-conv .row{display:flex;gap:8px}",
    ".ed-conv input{flex:1;border:0;background:var(--paper2);color:var(--ink);border-radius:var(--r-md);padding:11px 15px;font:300 13px/1.3 var(--font-ui);outline:none}",
    ".ed-conv input:focus{background:var(--accent-soft)!important}",
    ".ed-conv .thinking{font:300 12px var(--font-ui);color:var(--muted);margin-top:8px;display:flex;align-items:center;gap:7px}",
    /* el spinner sin borde: un cono de gradiente enmascarado, no un anillo de línea */
    ".ed-conv .thinking .sp{width:13px;height:13px;border:0;border-radius:50%;background:conic-gradient(from 0deg,transparent 0deg,var(--accent) 310deg);-webkit-mask:radial-gradient(circle,transparent 3.4px,#000 4px);mask:radial-gradient(circle,transparent 3.4px,#000 4px);animation:spin .8s linear infinite}",
    ".ed-diff{background:var(--paper2);border:0;border-radius:var(--r-lg);padding:15px 17px;margin-top:12px;animation:fadeUp .2s ease both}",
    ".ed-diff .sum{font:300 12.5px var(--font-ui);color:var(--muted);margin:2px 0 10px}",
    ".dr{display:flex;gap:8px;align-items:baseline;padding:5px 2px;font:300 13px var(--font-ui);border-radius:var(--r-sm)}",
    ".dr .tag{flex:none;font:400 10px var(--font-ui);letter-spacing:.05em;text-transform:uppercase;border-radius:var(--r-full);padding:2px 9px}",
    ".dr.add .tag{background:var(--green-bg);color:var(--green)}",
    ".dr.del .tag{background:var(--amber-bg);color:var(--amber)}",
    ".dr.del .tx{text-decoration:line-through;color:var(--muted)}",
    ".dr.mod .tag{background:var(--accent-soft);color:var(--accent-deep)}",
    ".dr .old{color:var(--muted);text-decoration:line-through;margin-right:6px}",
    ".dr .phn{color:var(--muted);font-size:11px}",
    /* equipar */
    ".ed-equip .chips{display:flex;gap:6px;flex-wrap:wrap;align-items:center}",
    ".ed-chip{display:inline-flex;align-items:center;gap:6px;background:var(--paper2);border:0;border-radius:var(--r-full);padding:6px 12px;font:300 12px var(--font-ui)}",
    ".ed-chip button{border:0;background:none;color:var(--muted);cursor:pointer;font-size:11px;padding:0}",
    ".ed-chip button:hover{color:var(--red)}",
    ".ed-equip select{border:0;background:var(--paper2);color:var(--muted);border-radius:var(--r-full);padding:7px 12px;font:400 12px/1 var(--font-ui);outline:none;cursor:pointer}",
    /* esqueletos (chooser) */
    ".sk-opt{display:flex;flex-direction:column;gap:4px;text-align:left;border:0;background:var(--paper2);color:var(--ink);border-radius:var(--r-lg);padding:15px 17px;cursor:pointer;font:inherit;width:100%}",
    ".sk-opt:hover{background:var(--accent-soft)}",
    ".sk-opt .lbl{font:400 var(--fs-md) var(--font-ui)}",
    ".sk-opt .det{font:300 11.5px var(--font-ui);color:var(--muted)}",
    ".sk-list{display:flex;flex-direction:column;gap:8px}",
    /* captura */
    ".cap-ta{width:100%;min-height:170px;resize:vertical;border:0;background:var(--paper2);color:var(--ink);border-radius:var(--r-lg);padding:14px;font:300 13px/1.6 var(--font-ui);outline:none}",
    ".cap-ta:focus{background:var(--accent-soft)}",
    ".cap-file{display:flex;align-items:center;gap:10px;margin-top:12px;font:300 12.5px var(--font-ui);color:var(--muted)}",
    ".cap-file .fname{color:var(--accent-deep)}",
    ".cap-working{display:flex;align-items:center;gap:9px;font:300 12.5px var(--font-ui);color:var(--muted);margin-top:12px}",
    ".cap-working .sp{width:15px;height:15px;border:0;border-radius:50%;background:conic-gradient(from 0deg,transparent 0deg,var(--accent) 310deg);-webkit-mask:radial-gradient(circle,transparent 4px,#000 4.7px);mask:radial-gradient(circle,transparent 4px,#000 4.7px);animation:spin .8s linear infinite}",
    ".ed-close{border:0;background:var(--paper2);color:var(--muted);border-radius:var(--r-sm);width:28px;height:28px;cursor:pointer;flex:none}",
    ".ed-close:hover{color:var(--ink)}",
  ].join("\n");
  document.head.appendChild(s);
}

/* esqueletos de FORMA — estructura pura, cero contenido de oficio (ORDEN §3) */
function skeletons() {
  return [
    { key: "blank", lbl: trM("met.sk.blank", "En blanco"), det: trM("met.sk.blank_d", "Una fase vacía, todo por escribir."), phases: [trM("met.sk.fase1", "Primera fase")] },
    { key: "iape", lbl: trM("met.sk.iape", "Investigar → Analizar → Producir → Entregar"), det: trM("met.sk.forma_d", "Cuatro fases de forma — sin contenido de oficio."), phases: trM("met.sk.iape", "Investigar → Analizar → Producir → Entregar").split("→").map((x) => x.trim()) },
    { key: "peve", lbl: trM("met.sk.peve", "Preparar → Ejecutar → Verificar → Cerrar"), det: trM("met.sk.forma_d", "Cuatro fases de forma — sin contenido de oficio."), phases: trM("met.sk.peve", "Preparar → Ejecutar → Verificar → Cerrar").split("→").map((x) => x.trim()) },
    { key: "rpre", lbl: trM("met.sk.rpre", "Recolectar → Procesar → Revisar → Entregar"), det: trM("met.sk.forma_d", "Cuatro fases de forma — sin contenido de oficio."), phases: trM("met.sk.rpre", "Recolectar → Procesar → Revisar → Entregar").split("→").map((x) => x.trim()) },
  ];
}

function modal(title, sub, bodyEl, onClose) {
  const scrim = document.createElement("div"); scrim.className = "met-scrim";
  const m = document.createElement("div"); m.className = "met-modal";
  m.innerHTML = "<h3>" + esc(title) + "</h3>" + (sub ? ('<p class="sub">' + esc(sub) + "</p>") : "");
  m.appendChild(bodyEl); scrim.appendChild(m);
  scrim.addEventListener("click", (e) => { if (e.target === scrim) { close(); } });
  function close() { scrim.remove(); if (onClose) onClose(); }
  document.body.appendChild(scrim);
  return { el: m, close };
}

export function mountEditor(cfg) {
  injectCSS();
  const { host, opts = {}, onSaved, onOpenGrafo, onClose, toast } = cfg;
  const say = toast || function () {};

  /* ── estado ── */
  let M = normalizeMethod(cfg.method ? deep(cfg.method) : newMethod(""));
  let phaseOrder = derivePhases(M);
  let savedSnap = cfg.method ? snap() : null;   // null = nunca guardado
  let pro = false; try { pro = localStorage.getItem("met-pro") === "1"; } catch (e) {}
  let tab = "pasos";
  let collapsed = Object.create(null);   // clave = nombre de fase (contenido del usuario) → sin prototipo
  let proposal = null;      // { steps, summary } — diff pendiente de aceptar/rechazar
  let draftBanner = !!opts.draftBanner;
  let destroyed = false;

  function derivePhases(m) {
    const seen = [], has = Object.create(null);
    (m.phases || []).forEach((p) => { const n = String(p); if (!has[n]) { has[n] = 1; seen.push(n); } });
    phasesOf(m).forEach((g) => { if (!has[g.name]) { has[g.name] = 1; seen.push(g.name); } });
    if (!seen.length) seen.push(trM("met.sk.fase1", "Primera fase"));
    return seen;
  }
  function snap() { return JSON.stringify(buildOut()); }
  function buildOut() {
    resort();
    const out = deep(M);
    out.phases = phaseOrder.filter((p) => p !== "");
    return out;
  }
  function dirty() { return savedSnap === null ? (M.steps.length > 0 || !!M.name.trim()) : snap() !== savedSnap; }
  function resort() {
    const idx = {}; phaseOrder.forEach((p, i) => idx[p] = i);
    const known = [], unknown = [];
    M.steps.forEach((s) => { (idx[s.phase] !== undefined ? known : unknown).push(s); });
    known.sort((a, b) => idx[a.phase] - idx[b.phase] || 0);   // sort estable: preserva orden interno
    unknown.forEach((s) => { if (idx[s.phase] === undefined) { idx[s.phase] = phaseOrder.length; phaseOrder.push(s.phase); } });
    M.steps = known.concat(unknown);
  }
  function stepsIn(ph) { return M.steps.filter((s) => s.phase === ph); }

  /* ── mutaciones ── */
  function addStep(ph, text) {
    const st = newStep(text, ph);
    let last = -1;
    M.steps.forEach((s, i) => { if (s.phase === ph) last = i; });
    if (last >= 0) M.steps.splice(last + 1, 0, st);
    else M.steps.push(st);
    resort(); render();
  }
  function delStep(id) { M.steps = M.steps.filter((s) => s.id !== id); render(); }
  function moveStep(id, dir) {
    const i = M.steps.findIndex((s) => s.id === id); if (i < 0) return;
    const s = M.steps[i]; const inPh = stepsIn(s.phase); const pi = inPh.findIndex((x) => x.id === id);
    if (dir < 0 && pi > 0) { const j = M.steps.indexOf(inPh[pi - 1]); M.steps.splice(i, 1); M.steps.splice(j, 0, s); }
    else if (dir > 0 && pi < inPh.length - 1) { const j = M.steps.indexOf(inPh[pi + 1]); M.steps.splice(i, 1); M.steps.splice(j, 0, s); }
    else {
      // frontera de fase → cruza a la fase vecina (arriba: al final; abajo: al inicio)
      const k = phaseOrder.indexOf(s.phase); const nk = k + dir;
      if (nk < 0 || nk >= phaseOrder.length) return;
      s.phase = phaseOrder[nk]; resort();
    }
    render();
  }
  function renamePhase(oldN, newN) {
    if (oldN === newN) return;
    const k = phaseOrder.indexOf(oldN); if (k < 0) return;
    M.steps.forEach((s) => { if (s.phase === oldN) s.phase = newN; });
    // renombrar HACIA una fase existente = FUSIONAR (review: duplicaba la fase en
    // phaseOrder y cada paso se pintaba dos veces con data-id repetido)
    if (phaseOrder.indexOf(newN) >= 0) phaseOrder.splice(k, 1);
    else phaseOrder[k] = newN;
    if (collapsed[oldN]) { collapsed[newN] = true; delete collapsed[oldN]; }
    render();
  }
  function addPhase() {
    if (namedPhases() >= 6) return;
    let n = trM("met.ed.fase_nueva", "Nueva fase"), i = 2;
    while (phaseOrder.indexOf(n) >= 0) n = trM("met.ed.fase_nueva", "Nueva fase") + " " + (i++);
    phaseOrder.push(n); render();
  }
  function delPhase(ph) { if (stepsIn(ph).length) return; phaseOrder = phaseOrder.filter((p) => p !== ph); render(); }
  function namedPhases() { return phaseOrder.filter((p) => p !== "").length; }

  /* aplicar el orden REAL del DOM tras un drag (grupo = fase) */
  function applyDomOrder() {
    const by = Object.create(null); M.steps.forEach((s) => by[s.id] = s);
    const next = [];
    host.querySelectorAll(".ph").forEach((g) => {
      const ph = g.getAttribute("data-phase");
      g.querySelectorAll(".step[data-id]").forEach((r) => {
        const s = by[r.getAttribute("data-id")]; if (s) { s.phase = ph; next.push(s); } });
    });
    if (next.length === M.steps.length) M.steps = next;
  }

  /* ── guardar ── */
  let saving = false;   // guard de vuelo: doble click en Guardar NO crea dos métodos (review)
  async function save() {
    if (saving) return;
    const out = buildOut();
    const v = validateMethod(out);
    if (!v.ok) { say(esc(trM("met.ed.val_err", "Antes de guardar: cada paso necesita texto y el método un nombre."))); markErrors(v.errors); return; }
    // el invariante 4-6 fases (ORDEN §2) también vale para JSON/captura/propuesta,
    // no solo para el botón de nueva fase (review: warnings era código muerto)
    if (v.warnings.indexOf("phases>6") >= 0) { say(esc(trM("met.ed.max_fases", "4–6 fases máximo — el método se lee de un vistazo"))); return; }
    saving = true;
    const btn = host.querySelector("[data-ed-save]"); if (btn) btn.disabled = true;
    try {
      const saved = M.id ? await MetodoAPI.update(M.id, out) : await MetodoAPI.create(out);
      M = normalizeMethod(Object.assign({}, out, saved || {}));
      phaseOrder = derivePhases(M);
      savedSnap = snap(); draftBanner = false;
      render();
      say(esc(trM("met.ed.guardado", "Guardado")) + " ✓");
      if (onSaved) onSaved(deep(M));
    } catch (e) { say(esc(trM("met.ed.err_guardar", "No pude guardar.")) + " · " + esc(e.message)); refreshMeta(); }
    finally { saving = false; }
  }
  function markErrors(errors) {
    errors.forEach((er) => {
      const m = /^step:(\d+):text$/.exec(er);
      if (m) { const s = M.steps[Number(m[1])]; const el = host.querySelector('.step[data-id="' + s.id + '"] textarea'); if (el) el.classList.add("err"); }
      // [sistema] el campo sin borde no puede marcar el error con una LÍNEA: lo marca con
      // el tinte de estado, igual que .err en los pasos. Mismo momento, misma señal.
      if (er === "name") { const el = host.querySelector(".ed-name"); if (el) { el.focus(); el.style.background = "var(--amber-bg)"; } }
    });
  }

  /* ── captura multimodal (§3 "Traer mi proceso") ── */
  function openCapture() {
    const body = document.createElement("div");
    body.innerHTML =
      '<textarea class="cap-ta" data-cap-ta placeholder="' + esc(trM("met.cap.ph", "pega aquí tu proceso, SOP o checklist…")) + '"></textarea>' +
      '<div class="cap-file"><span>' + esc(trM("met.cap.archivo", "o sube un archivo")) + "</span>" +
      '<button class="met-btn sec" data-cap-pick>📄 ' + esc(trM("met.cap.pick", "Word / PDF / imagen")) + "</button>" +
      '<span class="fname" data-cap-name></span>' +
      '<input type="file" hidden data-cap-file accept=".doc,.docx,.pdf,.png,.jpg,.jpeg,.webp,.txt,.md"></div>' +
      '<div class="cap-working" data-cap-working hidden><span class="sp"></span><span>' + esc(trM("met.cap.trabajando", "estructurando tu proceso…")) + "</span></div>" +
      '<div class="foot"><button class="met-btn sec" data-cap-cancel>' + esc(trM("common.cancelar", "Cancelar")) + "</button>" +
      '<button class="met-btn pri" data-cap-go>' + esc(trM("met.cap.estructurar", "Estructurar")) + "</button></div>";
    const md = modal(trM("met.cap.h", "Traer mi proceso"), trM("met.cap.sub", "Pega el texto de tu proceso (o sube un Word, PDF, o una foto de tu checklist). El modelo lo estructura en fases y pasos; tú lo pules."), body, null);
    let file = null;
    body.querySelector("[data-cap-pick]").onclick = () => body.querySelector("[data-cap-file]").click();
    body.querySelector("[data-cap-file]").onchange = (e) => {
      file = e.target.files && e.target.files[0];
      body.querySelector("[data-cap-name]").textContent = file ? file.name : "";
    };
    body.querySelector("[data-cap-cancel]").onclick = () => md.close();
    body.querySelector("[data-cap-go]").onclick = async () => {
      const text = body.querySelector("[data-cap-ta]").value.trim();
      if (!text && !file) return;
      body.querySelector("[data-cap-working]").hidden = false;
      body.querySelector("[data-cap-go]").disabled = true;
      try {
        let payload;
        if (file) {
          const buf = await file.arrayBuffer();
          let bin = ""; const u8 = new Uint8Array(buf);
          for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
          payload = { filename: file.name, mime: file.type || "application/octet-stream", data_b64: btoa(bin) };
          if (text) payload.text = text;
        } else payload = { text };
        const draft = await MetodoAPI.structure(payload);
        md.close();
        M = normalizeMethod(draft); delete M.id;   // borrador NUEVO: se crea al guardar
        phaseOrder = derivePhases(M); savedSnap = null; draftBanner = true;
        render();
      } catch (e) {
        body.querySelector("[data-cap-working]").hidden = true;
        body.querySelector("[data-cap-go]").disabled = false;
        say(esc(trM("met.cap.err", "No pude estructurar eso.")) + " · " + esc(e.message));
      }
    };
  }

  /* ── esqueletos (chooser) ── */
  function openChooser() {
    const body = document.createElement("div");
    const list = document.createElement("div"); list.className = "sk-list";
    skeletons().forEach((sk) => {
      const b = document.createElement("button"); b.className = "sk-opt"; b.setAttribute("data-sk", sk.key);
      b.innerHTML = '<span class="lbl">' + esc(sk.lbl) + '</span><span class="det">' + esc(sk.det) + "</span>";
      b.onclick = () => {
        M = normalizeMethod(newMethod("")); phaseOrder = sk.phases.slice(); savedSnap = null; draftBanner = false;
        md.close(); render();
        const nm = host.querySelector(".ed-name"); if (nm) nm.focus();
      };
      list.appendChild(b);
    });
    body.appendChild(list);
    const md = modal(trM("met.sk.h", "¿Cómo empezamos?"), trM("met.sk.sub", "Elige una forma — la estructura es tuya, el contenido lo escribes tú."), body, null);
  }

  /* ── editar conversando (§3) — diff propuesto → aceptar/rechazar ── */
  async function propose(instruction) {
    const box = host.querySelector("[data-conv]");
    const think = host.querySelector("[data-conv-think]"); if (think) think.hidden = false;
    try {
      const r = await MetodoAPI.proposeEdit(M.id || "nuevo", instruction, buildOut());
      // normaliza la propuesta (ids garantizados, sin null/duplicados) y NUNCA aceptes
      // una respuesta vacía como "borra todo" — eso no es una propuesta, es un fallo (review)
      const steps = normalizeMethod({ steps: r.steps || [] }).steps;
      if (!steps.length) { proposal = null; say(esc(trM("met.conv.err", "No pude proponer ese cambio."))); render(); return; }
      proposal = { steps: steps, summary: r.summary || "" };
      if (!diffRows().length) { proposal = null; say(esc(trM("met.conv.nada", "La propuesta no cambia nada."))); }
    } catch (e) { say(esc(trM("met.conv.err", "No pude proponer ese cambio.")) + " · " + esc(e.message)); }
    if (think) think.hidden = true;
    render();
  }
  function diffRows() {
    if (!proposal) return [];
    const cur = {}, rows = [];
    M.steps.forEach((s) => cur[s.id] = s);
    const seen = {};
    proposal.steps.forEach((p) => {
      seen[p.id] = 1;
      const c = cur[p.id];
      if (!c) rows.push({ k: "add", tx: p.text, ph: p.phase });
      else if (c.text !== p.text || c.phase !== p.phase || !!c.checkpoint !== !!p.checkpoint || (c.executor || null) !== (p.executor || null))
        rows.push({ k: "mod", old: c.text, tx: p.text, ph: p.phase });
    });
    M.steps.forEach((s) => { if (!seen[s.id]) rows.push({ k: "del", tx: s.text, ph: s.phase }); });
    return rows;
  }
  function acceptProposal() {
    if (!proposal) return;
    M.steps = proposal.steps.map((s) => Object.assign(newStep("", ""), s));
    proposal = null;
    phaseOrder = derivePhases(M);
    render();
  }

  /* ── equipar por referencia ── */
  async function equipInto(pid) {
    try { await MetodoAPI.equip(pid, M.id); M.equipped_by = (M.equipped_by || []).concat([{ puppet_id: pid }]); render(); }
    catch (e) { say(esc(e.message)); }
  }
  async function unequipFrom(pid) {
    try { await MetodoAPI.unequip(pid, M.id); M.equipped_by = (M.equipped_by || []).filter((x) => (x.puppet_id || x.id) !== pid); render(); }
    catch (e) { say(esc(e.message)); }
  }

  /* ── drag reorder (pointer) ── */
  let drag = null;
  function wireDrag(row) {
    const grip = row.querySelector(".grip");
    grip.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      drag = { id: row.getAttribute("data-id"), row };
      row.classList.add("dragging");
      const move = (ev) => {
        const el = document.elementFromPoint(ev.clientX, ev.clientY);
        const over = el && el.closest && el.closest(".step[data-id]");
        if (over && over !== row) {
          const r = over.getBoundingClientRect();
          if (ev.clientY < r.top + r.height / 2) over.parentNode.insertBefore(row, over);
          else over.parentNode.insertBefore(row, over.nextSibling);
        } else {
          const g = el && el.closest && el.closest(".ph");
          if (g && !g.contains(row)) {
            const body = g.querySelector(".ph-body");
            const add = body && body.querySelector(".ph-add");
            if (body) body.insertBefore(row, add || null);
          }
        }
      };
      const up = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
        row.classList.remove("dragging");
        drag = null;
        applyDomOrder(); render();
      };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  }

  /* ── render ── */
  function header() {
    const d = document.createElement("div");
    d.innerHTML =
      '<div class="ed-head">' +
      (opts.compact && onClose ? '<button class="ed-close" data-ed-close title="' + esc(trM("met.ed.cerrar", "Cerrar")) + '">✕</button>' : "") +
      '<input class="ed-name" data-ed-name placeholder="' + esc(trM("met.ed.nombre_ph", "Nombre del método")) + '" value="' + esc(M.name) + '">' +
      '<div class="ed-sw" data-ed-sw>' +
      '<button data-sw="simple" class="' + (pro ? "" : "on") + '">' + esc(trM("met.ed.simple", "Simple")) + "</button>" +
      '<button data-sw="pro" class="' + (pro ? "on" : "") + '">' + esc(trM("met.ed.pro", "Pro")) + "</button></div>" +
      (M.id && onOpenGrafo ? ('<button class="met-btn sec" data-ed-grafo>◇ <span>' + esc(trM("met.ver_grafo", "Ver modo workflow")) + "</span></button>") : "") +
      '<button class="met-btn pri" data-ed-save' + (dirty() ? "" : " disabled") + ">" + esc(trM("met.ed.guardar", "Guardar")) + "</button>" +
      "</div>" +
      '<div class="ed-meta"><span>' + namedPhases() + " " + esc(trM("met.fases", "fases")) + " · " + M.steps.length + " " + esc(trM("met.pasos", "pasos")) +
      " · " + M.steps.filter((s) => s.checkpoint).length + " " + esc(trM("met.checkpoints", "checkpoints")) + "</span>" +
      (dirty() ? ('<span class="dirty">● ' + esc(trM("met.ed.dirty", "cambios sin guardar")) + "</span>") : "") + "</div>" +
      (draftBanner ? ('<div class="ed-banner"><b>' + esc(trM("met.cap.draft_h", "Borrador estructurado por el modelo")) + "</b>" + esc(trM("met.cap.draft_p", "Revisa, pule y guarda — los pasos son tuyos.")) + "</div>") : "");
    d.querySelector("[data-ed-name]").addEventListener("input", (e) => { M.name = e.target.value; refreshMeta(); });
    d.querySelector("[data-ed-save]").onclick = save;
    d.querySelectorAll("[data-ed-sw] button").forEach((b) => b.onclick = () => {
      pro = b.getAttribute("data-sw") === "pro"; try { localStorage.setItem("met-pro", pro ? "1" : "0"); } catch (e) {}
      if (!pro) tab = "pasos";
      render();
    });
    const g = d.querySelector("[data-ed-grafo]"); if (g) g.onclick = () => onOpenGrafo(M.id);
    const c = d.querySelector("[data-ed-close]"); if (c) c.onclick = () => { if (!dirty() || confirm(trM("met.ed.dirty_conf", "Tienes cambios sin guardar. ¿Descartarlos?"))) onClose(); };
    return d;
  }
  function refreshMeta() {
    const btn = host.querySelector("[data-ed-save]"); if (btn) btn.disabled = !dirty();
    const meta = host.querySelector(".ed-meta"); if (!meta) return;
    meta.innerHTML = "<span>" + namedPhases() + " " + esc(trM("met.fases", "fases")) + " · " + M.steps.length + " " + esc(trM("met.pasos", "pasos")) +
      " · " + M.steps.filter((s) => s.checkpoint).length + " " + esc(trM("met.checkpoints", "checkpoints")) + "</span>" +
      (dirty() ? ('<span class="dirty">● ' + esc(trM("met.ed.dirty", "cambios sin guardar")) + "</span>") : "");
  }
  /* ══ EL EXECUTOR SE ELIGE, NO SE ESCRIBE (reforma · a) ═══════════════════════════════
   * PIEZAS = los MCPs equipables, cada uno con sus tools. Se carga una vez por pantalla; si
   * el backend no responde, PIEZAS queda vacío y el campo vuelve a ser un input de texto
   * (nunca un select vacío que no deja elegir nada — eso sería una pared). */
  let PIEZAS = [];
  async function cargarPiezas() {
    try {
      const h = {}; const u = currentUser && currentUser();
      if (u && u.session_token) h["Authorization"] = "Bearer " + u.session_token;
      const r = await fetch("/v1/atoms/catalog", { headers: h });
      if (!r.ok) return;
      const d = await r.json();
      const byServer = new Map();
      (d.atoms || []).forEach((a) => {
        if (!a.server) return;
        if (!byServer.has(a.server)) byServer.set(a.server, { server: a.server, label: a.label || a.server, tools: [] });
        const p = byServer.get(a.server);
        (a.tools || []).forEach((t) => { if (p.tools.indexOf(t) === -1) p.tools.push(t); });
      });
      PIEZAS = [...byServer.values()].sort((a, b) => a.server.localeCompare(b.server));
    } catch (e) { PIEZAS = []; }
  }
  /** MIGRACIÓN de executors legados: "get_filings" (nombre suelto de tool) → "sec-edgar#get_filings"
   *  cuando el nombre pertenece a UN solo MCP. Ambiguo o desconocido → se deja como está (el
   *  harness sigue aceptando la forma legada). Devuelve cuántos pasos migró. */
  function migrarExecutors(m) {
    if (!PIEZAS.length || !m || !Array.isArray(m.steps)) return 0;
    const dueño = new Map();   // tool → [servers]
    PIEZAS.forEach((p) => p.tools.forEach((t) => {
      if (!dueño.has(t)) dueño.set(t, []);
      if (dueño.get(t).indexOf(p.server) === -1) dueño.get(t).push(p.server);
    }));
    const servers = new Set(PIEZAS.map((p) => p.server));
    let n = 0;
    m.steps.forEach((s) => {
      const ex = (s.executor || "").trim();
      if (!ex || ex.indexOf("#") >= 0 || servers.has(ex)) return;   // ya canónico o es un MCP entero
      const dueños = dueño.get(ex);
      if (dueños && dueños.length === 1) { s.executor = dueños[0] + "#" + ex; n++; }
    });
    return n;
  }
  function selectExecutorHTML(s) {
    const val = s.executor || "";
    if (!PIEZAS.length) {
      return '<input class="pexe" data-pf="executor" value="' + esc(val) +
        '" placeholder="' + esc(trM("met.ed.exec_ph", "pieza (tool/MCP) — vacío: el modelo decide")) + '">';
    }
    const conocido = !val || val.indexOf("#") >= 0 || PIEZAS.some((p) => p.server === val);
    let h = '<select class="pexe" data-pf="executor">' +
      '<option value=""' + (val ? "" : " selected") + ">" +
      esc(trM("met.ed.exec_libre", "el modelo decide")) + "</option>";
    PIEZAS.forEach((p) => {
      h += '<optgroup label="' + esc(p.label) + '">';
      h += '<option value="' + esc(p.server) + '"' + (val === p.server ? " selected" : "") + ">" +
        esc(trM("met.ed.exec_mcp", "cualquiera de")) + " " + esc(p.server) + "</option>";
      p.tools.forEach((t) => {
        const v = p.server + "#" + t;
        h += '<option value="' + esc(v) + '"' + (val === v ? " selected" : "") + ">" + esc(t) + "</option>";
      });
      h += "</optgroup>";
    });
    // un executor guardado que ya no existe en el catálogo NO se borra en silencio: se
    // conserva como opción propia y se marca, para que se vea que quedó huérfano.
    if (val && !conocido) h += '<option value="' + esc(val) + '" selected>' + esc(val) + " — " + esc(trM("met.ed.exec_huerfano", "ya no está")) + "</option>";
    return h + "</select>";
  }

  function stepRow(s) {
    const r = document.createElement("div"); r.className = "step"; r.setAttribute("data-id", s.id);
    r.innerHTML =
      '<span class="grip" title="' + esc(trM("met.ed.arrastrar", "Arrastra para reordenar")) + '">⠿</span>' +
      '<span class="mv"><button data-mv="-1" title="' + esc(trM("met.ed.subir", "Subir")) + '">▲</button><button data-mv="1" title="' + esc(trM("met.ed.bajar", "Bajar")) + '">▼</button></span>' +
      '<span class="stx"><textarea rows="1" data-stx>' + esc(s.text) + "</textarea>" +
      (pro ? ('<span class="step-pro">' +
        // [reforma · a] el executor referencia MCP→TOOL. Era texto libre: se escribía "excel"
        // y el harness matcheaba por substring contra cualquier tool o server que dijera
        // excel. Ahora se ELIGE: un grupo por MCP, sus tools adentro, valor `server#tool`.
        // Sin catálogo cargado (offline) cae al input de texto, que sigue siendo válido.
        selectExecutorHTML(s) +
        '<input class="pevi" data-pf="evidence_hint" value="' + esc(s.evidence_hint || "") + '" placeholder="' + esc(trM("met.ed.evid_ph", "evidencia esperada")) + '">' +
        '<input class="ptmo" data-pf="timeout" type="number" min="1" value="' + (s.timeout == null ? "" : esc(s.timeout)) + '" placeholder="' + esc(trM("met.ed.timeout_ph", "timeout s")) + '">' +
        '<input class="pret" data-pf="retries" type="number" min="0" value="' + esc(s.retries) + '" placeholder="' + esc(trM("met.ed.retries_ph", "reintentos")) + '" title="' + esc(trM("met.ed.retries_t", "intentos sin evidencia antes de pausar con diagnóstico")) + '">' +
        "</span>") : "") + "</span>" +
      '<button class="ckb' + (s.checkpoint ? " on" : "") + '" data-ck title="' + esc(trM("met.ed.checkpoint_t", "Checkpoint: el proceso te espera aquí — nada sigue sin tu OK")) + '">' +
      (window.AlephIcons ? AlephIcons.icon("lock", { size: 13 }) : "🔒") + "</button>" +
      '<button class="sdel" data-del title="' + esc(trM("met.ed.borrar_paso", "Quitar el paso")) + '">✕</button>';
    const ta = r.querySelector("[data-stx]");
    const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
    ta.addEventListener("input", () => { s.text = ta.value; ta.classList.remove("err"); grow(); refreshMeta(); });
    setTimeout(grow, 0);
    r.querySelector("[data-ck]").onclick = () => { s.checkpoint = !s.checkpoint; r.querySelector("[data-ck]").classList.toggle("on", s.checkpoint); refreshMeta(); };
    r.querySelector("[data-del]").onclick = () => delStep(s.id);
    r.querySelectorAll("[data-mv]").forEach((b) => b.onclick = () => moveStep(s.id, Number(b.getAttribute("data-mv"))));
    r.querySelectorAll("[data-pf]").forEach((inp) => {
      const leer = () => {
        const f = inp.getAttribute("data-pf");
        if (f === "timeout") s.timeout = inp.value === "" ? null : Number(inp.value);
        else if (f === "retries") s.retries = inp.value === "" ? 3 : Number(inp.value);
        else s[f] = inp.value.trim() || null;
        refreshMeta();
      };
      inp.addEventListener("input", leer);
      inp.addEventListener("change", leer);   // <select> del executor
    });
    wireDrag(r);
    return r;
  }
  function phaseGroup(ph) {
    const g = document.createElement("div"); g.className = "ph" + (collapsed[ph] ? " closed" : ""); g.setAttribute("data-phase", ph);
    const steps = stepsIn(ph);
    const h = document.createElement("div"); h.className = "ph-h";
    h.innerHTML = '<button class="chev" data-chev aria-label="' + esc(trM("met.ed.colapsar", "colapsar fase")) + '">▾</button>' +
      '<input data-phname value="' + esc(ph) + '" placeholder="' + esc(trM("met.ed.fase_ph", "nombre de la fase")) + '">' +
      '<span class="cnt">' + steps.length + " " + esc(trM("met.pasos", "pasos")) + "</span>" +
      (steps.length === 0 ? ('<button class="phdel" data-phdel title="' + esc(trM("met.ed.borrar_fase", "Quitar la fase (vacía)")) + '">✕</button>') : "");
    h.querySelector("[data-chev]").onclick = () => { collapsed[ph] = !collapsed[ph]; g.classList.toggle("closed", !!collapsed[ph]); };
    h.querySelector("[data-phname]").addEventListener("change", (e) => renamePhase(ph, e.target.value.trim() || ph));
    const pd = h.querySelector("[data-phdel]"); if (pd) pd.onclick = () => delPhase(ph);
    g.appendChild(h);
    const body = document.createElement("div"); body.className = "ph-body";
    steps.forEach((s) => body.appendChild(stepRow(s)));
    const add = document.createElement("div"); add.className = "ph-add";
    add.innerHTML = '<input data-add placeholder="' + esc(trM("met.ed.paso_ph", "escribe un paso y Enter — ej: «Bajar el informe del mes»")) + '">';
    const ai = add.querySelector("[data-add]");
    ai.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && ai.value.trim()) { addStep(ph, ai.value.trim());
        const ng = host.querySelector('.ph[data-phase="' + CSS.escape(ph) + '"] [data-add]'); if (ng) ng.focus(); }
    });
    body.appendChild(add);
    g.appendChild(body);
    return g;
  }
  // [reforma · l] RETIRADA. Se conserva el cuerpo muerto FUERA del render (nadie la llama) sólo
  // como referencia de qué hacía; el tab que la abría ya no existe.
  function _jsonViewRetirada() {
    const d = document.createElement("div"); d.className = "ed-json";
    d.innerHTML = '<textarea data-json spellcheck="false"></textarea><div class="jerr" data-jerr></div>' +
      '<div class="foot"><button class="met-btn pri" data-japply>' + esc(trM("met.ed.json_aplicar", "Aplicar JSON")) + "</button>" +
      '<button class="met-btn sec" data-jcancel>' + esc(trM("common.cancelar", "Cancelar")) + "</button></div>";
    d.querySelector("[data-json]").value = JSON.stringify(buildOut(), null, 2);
    d.querySelector("[data-jcancel]").onclick = () => { tab = "pasos"; render(); };
    d.querySelector("[data-japply]").onclick = () => {
      let parsed;
      try { parsed = JSON.parse(d.querySelector("[data-json]").value); }
      catch (e) { d.querySelector("[data-jerr]").textContent = trM("met.ed.json_err", "Ese JSON no es un método válido:") + " " + e.message; return; }
      const norm = normalizeMethod(parsed);
      const v = validateMethod(norm);
      if (!v.ok) { d.querySelector("[data-jerr]").textContent = trM("met.ed.json_err", "Ese JSON no es un método válido:") + " " + v.errors.join(", "); return; }
      if (v.warnings.indexOf("phases>6") >= 0) { d.querySelector("[data-jerr]").textContent = trM("met.ed.max_fases", "4–6 fases máximo — el método se lee de un vistazo"); return; }
      M = norm; phaseOrder = derivePhases(M); tab = "pasos"; render();
    };
    return d;
  }
  function convBlock() {
    const d = document.createElement("div"); d.className = "ed-conv"; d.setAttribute("data-conv", "");
    d.innerHTML = '<div class="msec-h">' + esc(trM("met.conv.h_sec", "Editar conversando")) + "</div>" +
      '<div class="row"><input data-conv-in placeholder="' + esc(trM("met.conv.ph", "pídele un cambio — ej: «agrega un paso que valide el RUC antes de enviar»")) + '">' +
      '<button class="met-btn sec" data-conv-go>✨ ' + esc(trM("met.conv.btn", "Proponer")) + "</button></div>" +
      '<div class="thinking" data-conv-think hidden><span class="sp"></span><span>' + esc(trM("met.conv.trabajando", "pensando el cambio…")) + "</span></div>";
    const go = () => { const v = d.querySelector("[data-conv-in]").value.trim(); if (v) propose(v); };
    d.querySelector("[data-conv-go]").onclick = go;
    d.querySelector("[data-conv-in]").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    if (proposal) {
      const rows = diffRows();
      const p = document.createElement("div"); p.className = "ed-diff"; p.setAttribute("data-diff", "");
      p.setAttribute("data-no-tm", "");   // §8: los pasos del diff son CONTENIDO del usuario — la capa TM no los toca
      let h = '<div class="msec-h">' + esc(trM("met.conv.h", "Cambio propuesto")) + "</div>";
      if (proposal.summary) h += '<div class="sum">' + esc(proposal.summary) + "</div>";
      rows.forEach((r) => {
        const tag = r.k === "add" ? trM("met.conv.add", "nuevo") : r.k === "del" ? trM("met.conv.del", "se quita") : trM("met.conv.mod", "cambia");
        h += '<div class="dr ' + r.k + '"><span class="tag">' + esc(tag) + "</span><span>" +
          (r.k === "mod" ? ('<span class="old">' + esc(r.old) + "</span>") : "") +
          '<span class="tx">' + esc(r.tx) + '</span> <span class="phn">· ' + esc(r.ph || "—") + "</span></span></div>";
      });
      h += '<div class="foot" style="display:flex;gap:8px;margin-top:12px">' +
        '<button class="met-btn pri" data-diff-ok>' + esc(trM("met.conv.aceptar", "Aceptar cambios")) + "</button>" +
        '<button class="met-btn sec" data-diff-no>' + esc(trM("met.conv.rechazar", "Rechazar")) + "</button></div>";
      p.innerHTML = h;
      p.querySelector("[data-diff-ok]").onclick = acceptProposal;
      p.querySelector("[data-diff-no]").onclick = () => { proposal = null; render(); };
      d.appendChild(p);
    }
    return d;
  }
  function equipBlock() {
    const d = document.createElement("div"); d.className = "msec ed-equip";
    let h = '<div class="msec-h">' + esc(trM("met.ed.equip_h", "Equipado por (referencia, no copia)")) + '</div><div class="chips" data-eq>';
    const eqs = M.equipped_by || [];
    if (!eqs.length) h += '<span style="font-size:12px;color:var(--faint)">' + esc(trM("met.ed.equip_none", "ningún agente todavía")) + "</span>";
    eqs.forEach((e) => {
      const pid = e.puppet_id || e.id || String(e);
      h += '<span class="ed-chip" data-pid="' + esc(pid) + '">' + esc(e.name || pid.slice(0, 8)) + ' <button data-uneq title="' + esc(trM("met.ed.desequipar", "quitar")) + '">✕</button></span>';
    });
    h += '<select data-eqsel><option value="">' + esc(trM("met.ed.equip_add", "+ equipar en…")) + "</option></select></div>";
    d.innerHTML = h;
    d.querySelectorAll("[data-uneq]").forEach((b) => b.onclick = () => unequipFrom(b.closest("[data-pid]").getAttribute("data-pid")));
    const sel = d.querySelector("[data-eqsel]");
    let loaded = false;
    sel.addEventListener("focus", async () => {
      if (loaded) return; loaded = true;
      try {
        const pups = await MetodoAPI.puppets();
        pups.forEach((p) => {
          const o = document.createElement("option"); o.value = p.id; o.textContent = p.name || p.id.slice(0, 8);
          sel.appendChild(o);
        });
      } catch (e) {}
    });
    sel.addEventListener("change", () => { if (sel.value) { equipInto(sel.value); sel.value = ""; } });
    return d;
  }

  function render() {
    if (destroyed) return;
    resort();
    host.innerHTML = "";
    const root = document.createElement("div"); root.className = "ed" + (opts.compact ? " compact" : "");
    root.appendChild(header());
    // [reforma · l] LA VISTA JSON EDITABLE MURIÓ. Un método es CONFIGURACIÓN: se edita con
    // formulario. Pegar un JSON a mano en un <textarea> sin esquema, sin autocompletado y sin
    // deshacer no es "modo pro" — es la forma más fácil de romper un método guardado. Los pasos,
    // las fases, el executor y los checkpoints tienen todos su control. Cero pérdida de función:
    // el método sigue exportándose e importándose entero por [Exportar]/[Importar].
    {
      phaseOrder.forEach((ph) => root.appendChild(phaseGroup(ph)));
      const ap = document.createElement("div"); ap.className = "ed-addph";
      const maxed = namedPhases() >= 6;
      ap.innerHTML = '<button class="met-btn sec" data-addph' + (maxed ? " disabled" : "") + ">＋ " + esc(trM("met.ed.nueva_fase", "nueva fase")) + "</button>" +
        (maxed ? ('<span class="hint">' + esc(trM("met.ed.max_fases", "4–6 fases máximo — el método se lee de un vistazo")) + "</span>") : "");
      const apb = ap.querySelector("[data-addph]"); if (!maxed) apb.onclick = addPhase;
      root.appendChild(ap);
      if (M.id || savedSnap !== null || M.steps.length) root.appendChild(convBlock());
      if (M.id && !opts.compact) root.appendChild(equipBlock());
    }
    host.appendChild(root);
    if (opts.focusSteps && opts.focusSteps.length) {
      opts.focusSteps.forEach((id) => {
        const r = host.querySelector('.step[data-id="' + CSS.escape(id) + '"]');
        if (r) { r.style.outline = "1px solid var(--accent)"; r.scrollIntoView({ block: "center" }); }
      });
    }
  }

  /* ── arranque ── */
  if (opts.chooser) { render(); openChooser(); }
  else if (opts.capture) { render(); openCapture(); }
  else render();
  // [reforma · a] las piezas llegan por HTTP: se pinta YA (con input de texto) y se
  // re-pinta con el selector cuando el catálogo contesta. Al llegar, los executors
  // legados se migran a `mcp#tool` y se DICE cuántos (nunca en silencio).
  cargarPiezas().then(() => {
    if (destroyed || !PIEZAS.length) return;
    const n = migrarExecutors(M);
    window.__metodoMigracion = { executors: n, piezas: PIEZAS.length };   // hook de verificación
    if (n) console.info(`[método] migré ${n} paso${n === 1 ? "" : "s"} a la referencia MCP→tool`);
    render();
  });

  return {
    destroy() { destroyed = true; },
    isDirty: () => !destroyed && dirty(),
    getMethod: () => buildOut(),
    setMethod(m) { M = normalizeMethod(deep(m)); phaseOrder = derivePhases(M); savedSnap = snap(); render(); },
    save, openCapture, openChooser,
    _propose: propose, _accept: acceptProposal,
  };
}
