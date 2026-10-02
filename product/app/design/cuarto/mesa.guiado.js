/*
 * mesa.guiado.js — MODO GUIADO (la persona que no codea).
 *
 * Resultados naciendo EN VIVO por estación: carta de identidad del software → cómo se entra →
 * capacidades como chips ("puede leer X") → tools con nombre humano + qué-hace → ✓/✗ por tool →
 * la pieza aterrizando. Las PREGUNTAS TEMPRANAS aparecen como una carta con 2-3 opciones reales;
 * la pregunta JAMÁS pide la credencial en el chat (la opción abre el flujo por su canal).
 *
 * Cuatro gestos humanos siempre disponibles: Responder · Aportar · Redirigir · Tomar el mando.
 * Cada control es una decisión REAL del pipeline; ninguno decorativo.
 *
 * Vocabulario: construir / construcción. Jamás forja.
 */

function t(k, fb) {
  if (typeof window !== "undefined" && window.t) { const v = window.t(k); if (v && v !== k) return v; }
  return fb;
}
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function mountGuiado({ host, state }) {
  const el = document.createElement("div");
  el.className = "mc-guiado";
  host.appendChild(el);

  function render(st) {
    const inv = st.inventario;
    const partes = [];

    // ── carta de identidad ────────────────────────────────────────────────
    const idn = inv.identidad || {};
    partes.push(`<section class="mc-card mc-id">
      <h3>${t("mesa.g.software", "El software")}</h3>
      <div class="mc-id-row"><b>${esc(inv.server || idn.service || st.construccionId || "—")}</b></div>
      ${idn.auth_form ? `<div class="mc-sub">${t("mesa.g.entra", "Se entra con")}: ${esc(idn.auth_form)}</div>` : ""}
    </section>`);

    // ── capacidades (superficie) como chips ───────────────────────────────
    if (inv.superficie.length) {
      partes.push(`<section class="mc-card"><h3>${t("mesa.g.sabe", "Qué sabe hacer")}</h3>
        <div class="mc-chips">${inv.superficie.slice(0, 12).map((s) => `<span class="mc-chip">${esc(s)}</span>`).join("")}</div>
      </section>`);
    }

    // ── tools con nombre humano + ✓/✗ ─────────────────────────────────────
    if (inv.propuestas.length) {
      partes.push(`<section class="mc-card"><h3>${t("mesa.g.tools", "Las herramientas")}</h3>
        <ul class="mc-toollist">${inv.propuestas.map((tl) => {
          const st2 = tl.estado || "propuesta";
          const marca = st2 === "validada" ? '<span class="mc-ok">✓</span>'
            : st2 === "descartada" ? '<span class="mc-no">✗</span>'
            : st2 === "validando" ? '<span class="mc-run">·</span>' : '<span class="mc-prop">◦</span>';
          const nota = st2 === "descartada" ? ` <em class="mc-motivo">${esc(tl.motivo || "")}</em>`
            : st2 === "validada" && !String(tl.verified_by || "").startsWith("200")
              ? ` <em class="mc-flojo">${t("mesa.g.declarado", "verificada por forma")}</em>` : "";
          return `<li class="mc-tl mc-tl-${st2}">${marca} <b>${esc(tl.nombre)}</b> <span class="mc-tl-desc">${esc(tl.description || tl.endpoint || "")}</span>${nota}</li>`;
        }).join("")}</ul>
      </section>`);
    }

    // ── la pieza aterrizando ──────────────────────────────────────────────
    if (inv.belt_ref) {
      partes.push(`<section class="mc-card mc-equipada"><h3>${t("mesa.g.lista", "Tu pieza está lista")}</h3>
        <div class="mc-sub">${esc(inv.validadas.length)} ${t("mesa.g.herramientas", "herramientas verificadas")} · ${esc(inv.server || "")}</div>
        <button class="mc-btn mc-btn-eq" data-act="equipar">${t("mesa.g.equipar", "Equipar en mi agente")}</button>
      </section>`);
    }

    // ── pregunta temprana (carta con opciones) ────────────────────────────
    if (st.pregunta) {
      const p = st.pregunta;
      partes.push(`<section class="mc-card mc-pregunta" data-codigo="${esc(p.codigo)}">
        <div class="mc-preg-badge">${t("mesa.g.pregunta", "Una pregunta")}</div>
        <h3>${esc(p.pregunta)}</h3>
        <div class="mc-opts">${(p.opciones || []).map((o) => `
          <button class="mc-opt" data-opt="${esc(o.id)}" data-abre="${esc(o.abre || "")}">
            <span class="mc-opt-lbl">${esc(o.label)}</span>
            ${o.detalle ? `<span class="mc-opt-det">${esc(o.detalle)}</span>` : ""}
          </button>`).join("")}</div>
        <div class="mc-preg-input" hidden></div>
      </section>`);
    }

    // ── gestos siempre disponibles ────────────────────────────────────────
    partes.push(`<section class="mc-gestos">
      <button class="mc-gesto" data-gesto="aportar">${t("mesa.gesto.aportar", "Aportar")}</button>
      <button class="mc-gesto" data-gesto="redirigir">${t("mesa.gesto.redirigir", "Solo una parte")}</button>
      <button class="mc-gesto" data-gesto="mando">${t("mesa.gesto.mando", "Tomar el mando")}</button>
      <span class="mc-estado-lbl" data-estado="${esc(st.estado)}">${esc(st.estado)}</span>
    </section>`);

    el.innerHTML = partes.join("");
  }

  // ── interacción ──────────────────────────────────────────────────────────
  el.addEventListener("click", async (e) => {
    const opt = e.target.closest(".mc-opt");
    if (opt) return onOpcion(opt);
    const eq = e.target.closest('[data-act="equipar"]');
    if (eq) { await state.equipar(); return; }
    const gesto = e.target.closest(".mc-gesto");
    if (gesto) return onGesto(gesto.dataset.gesto);
  });

  async function onOpcion(btn) {
    const opt = btn.dataset.opt;
    const abre = btn.dataset.abre;
    const card = btn.closest(".mc-pregunta");
    const zona = card && card.querySelector(".mc-preg-input");
    if (abre === "credencial") {
      // la credencial va por SU canal (POST /credencial), no al chat.
      return pedirEnLinea(zona, t("mesa.g.pegacred", "Pega tu clave (va cifrada al vault, no al chat)"), async (val) => {
        await state.responder(opt);           // fija la forma
        await state.credencial(val);          // carga la cred por su canal → arranca sola
      }, { password: true });
    }
    if (abre === "docs") {
      return pedirEnLinea(zona, t("mesa.g.pegadocs", "Pega la URL de la doc o de la API"), async (val) => {
        await state.responder(opt, opt === "aportar-url" ? { url: val, docs_url: val } : { docs_url: val });
      });
    }
    if (abre === "ejemplo") {
      return pedirEnLinea(zona, t("mesa.g.pegaej", "Un endpoint que sabes que anda (ej: /movie/550)"), async (val) => {
        await state.responder(opt, { ejemplo: { endpoint: val, method: "GET", kind: "read" } });
      });
    }
    if (abre === "browser") {
      // el flujo browser (2FA humano) se dispara en el front del Cuarto; acá dejamos el hilo listo.
      await state.responder(opt);
      if (zona) { zona.hidden = false; zona.innerHTML = `<p class="mc-note">${t("mesa.g.browser", "Abre la ventana para entrar; cuando termines, pega tu session_key.")}</p>`; }
      return;
    }
    await state.responder(opt);
  }

  function pedirEnLinea(zona, label, onSubmit, { password } = {}) {
    if (!zona) return;
    zona.hidden = false;
    zona.innerHTML = `<label class="mc-inline"><span>${esc(label)}</span>
      <input type="${password ? "password" : "text"}" class="mc-inline-in" autocomplete="off"/>
      <button class="mc-btn mc-inline-go">${t("mesa.g.enviar", "Enviar")}</button></label>`;
    const inp = zona.querySelector(".mc-inline-in");
    const go = zona.querySelector(".mc-inline-go");
    const submit = async () => { const v = (inp.value || "").trim(); if (!v) return; go.disabled = true; await onSubmit(v); };
    go.addEventListener("click", submit);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    inp.focus();
  }

  function onGesto(g) {
    if (g === "aportar") {
      const zona = document.createElement("div"); zona.className = "mc-card mc-gesto-in"; el.prepend(zona);
      return pedirEnLinea(zona, t("mesa.g.aportarq", "Pega una URL de docs o un ejemplo de llamada"), async (v) => {
        if (/^https?:/i.test(v)) await state.aportar({ docs_url: v });
        else await state.aportar({ ejemplo: { endpoint: v, method: "GET", kind: "read" } });
        zona.remove();
      });
    }
    if (g === "redirigir") {
      const zona = document.createElement("div"); zona.className = "mc-card mc-gesto-in"; el.prepend(zona);
      return pedirEnLinea(zona, t("mesa.g.redirigirq", "¿Qué parte quieres? (ej: solo reportes)"), async (v) => {
        await state.redirigir(v); zona.remove();
      });
    }
    if (g === "mando") {
      // "Tomar el mando" → cambia a Modo Código (misma estado, otra piel).
      window.dispatchEvent(new CustomEvent("mesa:modo", { detail: { modo: "codigo" } }));
    }
  }

  const unsub = state.subscribe(render);
  return { el, render, destroy: () => { unsub(); el.remove(); } };
}
