/*
 * mesa.codigo.js — MODO CÓDIGO (el dev). Las MISMAS estaciones, artefactos en su forma real.
 *
 *  · Tabla de la superficie descubierta (endpoints/operaciones).
 *  · El spec de cada tool en un EDITOR editable con DIFF de las ediciones humanas.
 *  · CONSOLA de prueba por tool con request/response reales.
 *  · Re-correr desde cualquier estación (retomar, no desde cero).
 *
 * El toggle Guiado↔Código NO cambia el estado — mismo store, dos renders. Si el editor-con-diff
 * o la consola-por-tool no llegan verdes en algún entorno, degradan a visor read-only + nota
 * honesta (jamás se fingen). Vocabulario: construir. Jamás forja.
 */

function t(k, fb) {
  if (typeof window !== "undefined" && window.t) { const v = window.t(k); if (v && v !== k) return v; }
  return fb;
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// spec editable de una tool (forma del candado: name/endpoint/method/kind/x-sample-call)
function specDe(tl) {
  return {
    name: tl.nombre, endpoint: tl.endpoint || "", method: tl.method || "GET",
    kind: tl.kind || "read",
    input_schema: (tl.params && Object.keys(tl.params).length) ? tl.params
      : { type: "object", "x-sample-call": { path_params: {}, query: {} } },
    description: tl.description || "",
  };
}

export function mountCodigo({ host, state }) {
  const el = document.createElement("div");
  el.className = "mc-codigo";
  host.appendChild(el);

  // ediciones humanas por tool (para el diff) — clave = nombre original
  const editado = {};   // nombre → texto del editor
  const original = {};  // nombre → texto original (JSON)

  function render(st) {
    const inv = st.inventario;
    const partes = [];

    // ── superficie descubierta ────────────────────────────────────────────
    partes.push(`<section class="mc-c-card"><h4>${t("mesa.c.superficie", "Superficie descubierta")}</h4>
      ${inv.superficie.length ? `<table class="mc-tbl"><thead><tr><th>${t("mesa.c.endpoint", "endpoint")}</th></tr></thead>
        <tbody>${inv.superficie.map((s) => `<tr><td><code>${esc(s)}</code></td></tr>`).join("")}</tbody></table>`
        : `<p class="mc-empty">${t("mesa.c.aunno", "aún no hay superficie observada")}</p>`}
    </section>`);

    // ── tools: editor con diff + consola ──────────────────────────────────
    partes.push(`<section class="mc-c-card"><h4>${t("mesa.c.tools", "Herramientas")} <span class="mc-c-hint">(${t("mesa.c.editable", "edita el spec y re-valida con el candado")})</span></h4>
      <div class="mc-c-tools">${inv.propuestas.map((tl, i) => {
        const spec = specDe(tl);
        const txt = JSON.stringify(spec, null, 2);
        if (!(tl.nombre in original)) original[tl.nombre] = txt;
        const cur = editado[tl.nombre] != null ? editado[tl.nombre] : txt;
        const dirty = cur.trim() !== original[tl.nombre].trim();
        const badge = tl.estado === "validada" ? '<span class="mc-c-ok">200 OK</span>'
          : tl.estado === "descartada" ? `<span class="mc-c-no">${esc(tl.motivo || "rechazada")}</span>`
          : tl.estado === "validando" ? '<span class="mc-c-run">validando…</span>' : '<span class="mc-c-prop">propuesta</span>';
        return `<div class="mc-c-tool ${dirty ? "mc-dirty" : ""}" data-name="${esc(tl.nombre)}">
          <div class="mc-c-tool-head"><code>${esc(tl.method || "GET")} ${esc(tl.endpoint || "")}</code> ${badge}${dirty ? `<span class="mc-c-diff">${t("mesa.c.editado", "editado")}</span>` : ""}</div>
          <textarea class="mc-c-editor" data-name="${esc(tl.nombre)}" spellcheck="false">${esc(cur)}</textarea>
          <div class="mc-c-actions">
            <button class="mc-btn mc-c-validar" data-name="${esc(tl.nombre)}">${t("mesa.c.validar", "Validar")}</button>
            <button class="mc-btn mc-c-probar" data-name="${esc(tl.nombre)}">${t("mesa.c.probar", "Probar")}</button>
            ${dirty ? `<button class="mc-btn mc-c-revert" data-name="${esc(tl.nombre)}">${t("mesa.c.revert", "Revertir")}</button>` : ""}
          </div>
          <pre class="mc-c-consola" data-name="${esc(tl.nombre)}" hidden></pre>
        </div>`;
      }).join("") || `<p class="mc-empty">${t("mesa.c.aunnotools", "aún no hay herramientas propuestas")}</p>`}</div>
    </section>`);

    // ── re-correr desde estación / equipar ────────────────────────────────
    partes.push(`<section class="mc-c-card mc-c-run-row">
      <button class="mc-btn" data-act="retomar">${t("mesa.c.recorrer", "Re-correr desde")} «${esc(st.estacion || "inicio")}»</button>
      ${inv.belt_ref ? `<button class="mc-btn mc-btn-eq" data-act="equipar">${t("mesa.c.equipar", "Equipar")} (${esc(inv.validadas.length)})</button>` : ""}
      <span class="mc-c-conv">${esc(st.convergencia || "")}</span>
    </section>`);

    el.innerHTML = partes.join("");
    // re-aplicar el texto editado a los textareas (innerHTML los reseteó)
    for (const ta of el.querySelectorAll(".mc-c-editor")) {
      const n = ta.dataset.name; if (editado[n] != null) ta.value = editado[n];
    }
  }

  el.addEventListener("input", (e) => {
    const ta = e.target.closest(".mc-c-editor");
    if (ta) { editado[ta.dataset.name] = ta.value; markDirty(ta); }
  });

  function markDirty(ta) {
    const n = ta.dataset.name;
    const tool = ta.closest(".mc-c-tool");
    const dirty = (editado[n] || "").trim() !== (original[n] || "").trim();
    if (tool) tool.classList.toggle("mc-dirty", dirty);
  }

  el.addEventListener("click", async (e) => {
    const val = e.target.closest(".mc-c-validar");
    if (val) return onValidar(val.dataset.name);
    const prb = e.target.closest(".mc-c-probar");
    if (prb) return onProbar(prb.dataset.name);
    const rev = e.target.closest(".mc-c-revert");
    if (rev) { delete editado[rev.dataset.name]; render(state); return; }
    const ret = e.target.closest('[data-act="retomar"]');
    if (ret) { await state.retomar(); return; }
    const eq = e.target.closest('[data-act="equipar"]');
    if (eq) { await state.equipar(); return; }
  });

  function specDeName(name) {
    const txt = editado[name] != null ? editado[name] : original[name];
    try { return JSON.parse(txt); } catch (e) { return null; }
  }

  async function onValidar(name) {
    const consola = el.querySelector(`.mc-c-consola[data-name="${cssq(name)}"]`);
    const spec = specDeName(name);
    if (!spec) { if (consola) { consola.hidden = false; consola.textContent = "JSON inválido en el editor"; } return; }
    const r = await state.validarTools([spec]);
    if (consola) {
      consola.hidden = false;
      const b = r.body || {};
      const ver = (b.verificadas || []).map((v) => `✓ ${v.nombre} · ${v.verified_by} (${v.fuerza})`);
      const des = (b.descartadas || []).map((f) => `✗ ${f.nombre} · ${f.motivo} → ${f.move}`);
      consola.textContent = [...ver, ...des].join("\n") || JSON.stringify(b, null, 2);
    }
  }

  async function onProbar(name) {
    const consola = el.querySelector(`.mc-c-consola[data-name="${cssq(name)}"]`);
    const spec = specDeName(name);
    if (!spec) return;
    const r = await state.probarTool(spec, {}, false);   // dry-run primero (previsualiza)
    if (consola) {
      consola.hidden = false;
      const b = r.body || {};
      if (b.gated) consola.textContent = `✗ ${t("mesa.c.gated", "escribe → gateada, no se ejecuta")}\n` + JSON.stringify(b.request, null, 2);
      else if (b.dry_run) consola.textContent = `${t("mesa.c.dryrun", "dry-run (request armada)")}\n` + JSON.stringify(b.request, null, 2) +
        `\n\n[${t("mesa.c.ejecutar", "ejecuta para pegar el GET real")}]`;
      else consola.textContent = JSON.stringify(b, null, 2);
      // ofrecer ejecutar el read real
      if (b.dry_run && spec.kind === "read") {
        const go = document.createElement("button"); go.className = "mc-btn mc-c-exec";
        go.textContent = t("mesa.c.ejecutar", "Ejecutar de verdad");
        go.onclick = async () => {
          const rr = await state.probarTool(spec, {}, true);
          consola.textContent = JSON.stringify(rr.body, null, 2);
        };
        consola.after(go);
      }
    }
  }

  const unsub = state.subscribe(render);
  return { el, render, destroy: () => { unsub(); el.remove(); } };
}

function cssq(s) { return String(s).replace(/["\\]/g, "\\$&"); }
