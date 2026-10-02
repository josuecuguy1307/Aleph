/* cuarto.manual.js — LA REVISIÓN ANTES DE EQUIPAR (Ola 2 · 2d, reformada en identidad visual 6/6).
 *
 * Mismo principio que el gate de F5: lo automático corre solo, el humano decide SÓLO en el punto que
 * importa. Antes los puntos eran DOS y vivían detrás de un interruptor —el "Modo técnico", default
 * OFF— y ahí estaban los dos defectos: el que no sabía que el modo existía no vio nunca la revisión,
 * y el que sí sabía tenía que encender un modo ANTES de que hubiera algo que revisar. El modo era la
 * barrera, no la información. Se cierra igual para los dos: **el modo muere, la revisión queda
 * SIEMPRE VISIBLE**.
 *
 *   ÚNICO PUNTO · REVISAR ANTES DE EQUIPAR  (en mcp.forjado, frontera 1-B)
 *     Antes de equipar, un panel muestra las TOOLS REALES del emit (cero placeholders) con una
 *     casilla cada una, TODAS MARCADAS. El default es un solo toque en [Continuar] → se equipa
 *     exactamente lo forjado, byte-idéntico al viejo flujo automático: la revisión no bloquea, sólo
 *     deja de esconderse. Destildar es opcional; lo destildado no entra al MCP sellado.
 *
 * QUÉ SE FUE, Y POR QUÉ NO SE PIERDE NADA:
 *   · El toggle "Modo técnico" (`manualBtn`) y su estado ON/OFF.
 *   · El punto 1, "descartar una propuesta ANTES de validar": pedía decidir a mitad de vuelo, sobre
 *     fantasmas que todavía no se sabía si iban a validar. La MISMA decisión —qué queda adentro—
 *     se toma acá, mejor informada, sobre las tools que de verdad sobrevivieron. Y el detalle crudo
 *     de qué se propuso y qué validó el motor no se perdió: sigue entero en la EVIDENCIA
 *     (`</>` · cuarto.evidence.js), que es donde vive el detalle técnico desde 2e.
 *
 * INVARIANTES (lo que el módulo NO hace):
 *   · NO muta el modelo de relaciones del Cuarto (F2) ni el contrato de eventos: la revisión sólo
 *     MODULA qué `tools[]` lleva la pieza que `equipForgedMcp` (1-B, intacta) materializa.
 *   · NO toca la coreografía base (1-A) ni el equip base (1-B): los EXTIENDE por el único gancho que
 *     `inspectAndEquip` invoca (`reviewBeforeSeal`).
 *
 * Verificación (scripted, sin humano): `configure({...})` deja pre-decididos los destildes y el sello
 * para que un Playwright maneje los MISMOS caminos del código sin carrera de tiempos (patrón seed_*).
 */

const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/**
 * Crea la capa de revisión. Devuelve un objeto con:
 *   · controllerForRun()  — lo consume inspectAndEquip por el param `manual`. SIEMPRE devuelve
 *                           controlador: no hay modo previo que encender.
 *   · configure(cfg)      — perillas de verificación (scripted).
 *   · lastRun()           — resumen de la última revisión (para asserts). null si no hubo ninguna.
 *
 * @param {Document} [opts.doc]
 * @param {function} [opts.onState]
 */
export function createManualLayer({ doc = (typeof document !== "undefined" ? document : null), onState = () => {} } = {}) {
  const $ = (id) => (doc ? doc.getElementById(id) : null);

  let cfg = { dropAtSeal: null, dropAtSealIndex: null, autoSeal: false };
  let run = null;     // estado de la revisión en curso
  let _last = null;   // resumen de la última revisión (verificación)

  function configure(c = {}) { cfg = { ...cfg, ...c }; return cfg; }

  // ── EL PANEL · revisar antes de equipar ────────────────────────────────────────────
  function openSeal(forjado) {
    return new Promise((resolve) => {
      // las tools REALES del emit, cero placeholders. Todas marcadas: el default es no perder nada.
      const surviving = (forjado.tools || []).slice();
      run = { surviving, keep: new Set(surviving), sealResolve: resolve, server: forjado.server || "" };
      _last = { surviving: surviving.slice(), kept: surviving.slice(), sealed: false, cancelled: false };
      showSealPanel(forjado);
      if (cfg.autoSeal) {
        // VERIFICACIÓN: aplica los destildes configurados sobre el panel REAL ya pintado y sella.
        if (cfg.dropAtSealIndex != null && surviving[cfg.dropAtSealIndex]) toggleSealTool(surviving[cfg.dropAtSealIndex]);
        if (cfg.dropAtSeal && run.keep.has(cfg.dropAtSeal)) toggleSealTool(cfg.dropAtSeal);
        setTimeout(() => sealConfirm(), 0);   // microtask: deja pintar las filas reales antes de resolver
      }
    });
  }
  function showSealPanel(forjado) {
    const p = $("msealbar"); if (!p) { return; }
    p.hidden = false;
    // [T6 §10] el detalle crudo YA NO vive plegado acá: es explicación, y la explicación vive en
    // docs/guia detrás del [?] (#msealWhy → piezas#revisar). Lo que queda en pantalla es ESTADO:
    // de qué servidor salieron estas tools. Eso sí es operativo, y por eso está a la vista.
    const src = $("msealSrc"); if (src) src.textContent = forjado.server || "MCP";
    renderSealRows();
  }
  function hideSealPanel() { const p = $("msealbar"); if (p) p.hidden = true; }
  function renderSealRows() {
    const host = $("msealList"); if (!host || !run) return;
    const cnt = $("msealCount");
    if (cnt) cnt.textContent = `${run.keep.size}/${run.surviving.length}`;
    host.innerHTML = "";
    for (const name of run.surviving) {
      const on = run.keep.has(name);
      const row = doc.createElement("label");
      row.className = "srow" + (on ? "" : " off");
      row.dataset.name = name;
      row.innerHTML =
        `<input type="checkbox" class="schk" ${on ? "checked" : ""} />` +
        `<span class="sname">${esc(name)}</span>`;
      host.appendChild(row);
    }
    const ok = $("msealConfirm");
    if (ok) ok.disabled = run.keep.size === 0;   // sin tools marcadas no hay nada que equipar
  }
  function toggleSealTool(name) {
    if (!run || !run.surviving.includes(name)) return;
    run.keep.has(name) ? run.keep.delete(name) : run.keep.add(name);
    _last = { ...(_last || {}), kept: [...run.keep] };
    renderSealRows();
  }
  function sealConfirm() {
    if (!run || !run.sealResolve) return;
    if (run.keep.size === 0) return;             // candado: no equipar vacío
    const keep = new Set(run.keep);
    const resolve = run.sealResolve; run.sealResolve = null;
    hideSealPanel();
    _last = { ...(_last || {}), sealed: true, kept: [...keep], surviving: run.surviving.slice() };
    resolve({ keep, drop: new Set(run.surviving.filter((t) => !keep.has(t))) });
  }
  function sealCancel() {
    if (!run || !run.sealResolve) return;
    const resolve = run.sealResolve; run.sealResolve = null;
    hideSealPanel();
    _last = { ...(_last || {}), sealed: false, cancelled: true };
    resolve(null);
  }

  // delegación de clicks en el panel (sobrevive re-render del innerHTML)
  if (doc) {
    const sl = $("msealList");
    if (sl) sl.addEventListener("change", (e) => {
      const row = e.target.closest(".srow"); if (!row) return;
      toggleSealTool(row.dataset.name);
    });
    const ok = $("msealConfirm"); if (ok) ok.addEventListener("click", sealConfirm);
    const no = $("msealCancel"); if (no) no.addEventListener("click", sealCancel);
    // [T6 §10] el "?" ya no lo cablea este módulo: #msealWhy es un [?] estándar (data-guia) y lo
    // atiende el listener delegado ÚNICO de cuarto.ayuda.js. Un solo patrón, un solo handler.
  }

  // ── EL CONTROLADOR — lo consume inspectAndEquip por el param `manual` ───────────────
  function controllerForRun() {
    run = null; _last = null;
    return {
      reviewBeforeSeal: (forjado) => openSeal(forjado),
      cleanup: () => { hideSealPanel(); run = null; },
    };
  }

  return {
    configure, controllerForRun,
    lastRun: () => _last,
    // expuestos para deep-link / verificación de la UI real
    _toggleSealTool: toggleSealTool, _sealConfirm: sealConfirm, _sealCancel: sealCancel,
    // VERIFICACIÓN ÚNICAMENTE: pinta el panel con un forjado de mentira para poder MEDIRLO
    // (contraste, idioma, tooltips) sin una forja real de 2 minutos. No resuelve nada ni equipa.
    _showForVerify: (forjado) => { openSeal(forjado || { server: "", tools: [] }); },
  };
}
