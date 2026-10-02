/*
 * mesa.rail.js — EL RIEL de 6 estaciones (el gráfico vivo, común a ambas pieles).
 *
 * Seis nodos conectados que se llenan EN VIVO, con las tools naciendo como mini-piezas
 * colgando de "Armar las herramientas". Se lee el progreso, el atasco (candado) y lo nacido
 * sin leer un log. Iconografía del SET PROPIO (Lucide vendored, lucide-static@1.21.0) — CERO
 * emoji de OS (regla de plataforma). Vocabulario visual del Cuarto: pulso / ✓ teal / candado.
 *
 * El riel es una PROYECCIÓN del store (mesa.state.js): se suscribe y redibuja. No consume el
 * stream ni el motor directamente.
 */
import { ESTACIONES, indiceEstacion, ESTADO_ESTACION } from "./mesa.state.js";

// glifos del set propio (inner SVG de lucide-static@1.21.0). 4 vienen de cuarto.icons.js
// (search/key-round/flask-conical/plug); eye/wrench se vendorizan acá al mismo estilo.
const GLIFO = {
  encontrarlo: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  entrar: '<path d="M2.6 17.4A2 2 0 0 0 2 18.8V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.5a3 3 0 0 0 2.1-.9l.4-.4a6 6 0 1 0-4-4z"/><circle cx="16.5" cy="7.5" r="1"/>',
  ver: '<path d="M2.1 12.3a1 1 0 0 1 0-.7 10.8 10.8 0 0 1 19.9 0 1 1 0 0 1 0 .7 10.8 10.8 0 0 1-19.9 0"/><circle cx="12" cy="12" r="3"/>',
  armar: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  probar: '<path d="M14 2v6a2 2 0 0 0 .2 1l5.5 10a2 2 0 0 1-1.7 3H6a2 2 0 0 1-1.8-3l5.5-10a2 2 0 0 0 .3-1V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
  equipar: '<path d="M12 22v-5"/><path d="M15 8V2"/><path d="M17 8a1 1 0 0 1 1 1v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1z"/><path d="M9 8V2"/>',
};

const ICON_LISTA = '<path d="M20 6 9 17l-5-5"/>';        // check
const ICON_CANDADO = '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>';

function svgIcon(inner, cls) {
  return `<svg class="${cls || ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

// texto humano por estación (window.t si está; fallback ES). NUNCA emoji.
function etiqueta(est) {
  const k = `mesa.est.${est}`;
  if (typeof window !== "undefined" && window.t) { const v = window.t(k); if (v && v !== k) return v; }
  return {
    encontrarlo: "Encontrarlo", entrar: "Entrar", ver: "Ver qué sabe hacer",
    armar: "Armar las herramientas", probar: "Probarlas", equipar: "Equipar",
  }[est];
}

export function mountRail({ host }) {
  const el = document.createElement("div");
  el.className = "mc-rail";
  el.setAttribute("role", "list");
  host.appendChild(el);

  function render(st) {
    const activaIdx = indiceEstacion(st.estacion);
    const nodos = ESTACIONES.map((est) => {
      const estado = st.estados[est] || ESTADO_ESTACION.PENDIENTE;
      let icon = svgIcon(GLIFO[est], "mc-glyph");
      if (estado === ESTADO_ESTACION.LISTA) icon = svgIcon(ICON_LISTA, "mc-glyph");
      else if (estado === ESTADO_ESTACION.BLOQUEADA) icon = svgIcon(ICON_CANDADO, "mc-glyph");
      // mini-piezas de tools colgando de "armar" (abanico de fantasmas)
      let piezas = "";
      if (est === "armar" && st.inventario.propuestas.length) {
        piezas = `<div class="mc-tools">` + st.inventario.propuestas.map((t) => {
          const cls = { validada: "ok", descartada: "no", validando: "run", propuesta: "prop" }[t.estado] || "prop";
          return `<span class="mc-tool mc-tool-${cls}" title="${(t.nombre || "").replace(/"/g, "")}">${(t.nombre || "·")}</span>`;
        }).join("") + `</div>`;
      }
      return `<div class="mc-node mc-${estado}" data-est="${est}" role="listitem" aria-current="${est === st.estacion}">
        <div class="mc-node-ic">${icon}</div>
        <div class="mc-node-lbl" data-i18n="mesa.est.${est}">${etiqueta(est)}</div>
        <div class="mc-node-n">${indiceEstacion(est)}/6</div>
        ${piezas}
      </div>`;
    }).join(`<div class="mc-link" aria-hidden="true"></div>`);
    el.innerHTML = nodos;
    el.dataset.estacion = st.estacion || "";
    el.dataset.estado = st.estado || "";
    el.dataset.activa = String(activaIdx);
  }

  return { el, render };
}
