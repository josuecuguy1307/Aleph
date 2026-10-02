/* linea.js — LA LÍNEA DE RAZONAMIENTO + LOG (FIX-P9).
 *
 * Cuando el agente piensa y trabaja, el chat muestra SU LÍNEA: el hilo colapsable del turno.
 * Razonamiento (si lo hubo) + una entrada por acción REAL, como Claude:
 *
 *     Busco los nombres reales de modelos…
 *     [logo HF]  hub_repo_search "vision GGUF"   ✓ 15 resultados
 *     ─────────────────────────────────────────
 *     (recién entonces, la respuesta)
 *
 * ── LA LEY QUE GOBIERNA ESTE ARCHIVO ────────────────────────────────────────────────
 * TELEMETRÍA REAL, JAMÁS TEATRO. Cada entrada del log nace de un evento REAL del motor:
 * un `tool_call_started` / `tool_call_finished` del espinazo, o el `onTool` / `onToolResult`
 * del loop del Guía. Este módulo NO tiene un solo camino que fabrique una entrada, ni un
 * timer que "simule" progreso, ni un texto de razonamiento por default.
 *
 *   · `pensar(texto)` es la ÚNICA puerta del bloque de razonamiento, y el bloque NO EXISTE
 *     en el DOM hasta que alguien la llama con texto real. Un cerebro que no razona deja
 *     CERO bloque — pensamiento inventado sería una mentira sobre lo que hizo el modelo.
 *   · `accion(...)` es la ÚNICA puerta del log. No hay `accion()` implícita, ni entrada que
 *     nazca de un `say()`, ni relleno cuando el turno no usó herramientas.
 *
 * Por eso la vara puede afirmar, uno a uno, que las entradas del log == los tool_calls de
 * la telemetría: no hay otra fuente posible.
 *
 * ── DÓNDE VIVE ──────────────────────────────────────────────────────────────────────
 * EN el mensaje (deep-chat, vía `addHTML` + `htmlClassUtilities`) — jamás un panel flotante
 * nuevo. El panel de la corrida del sidebar de La Sala es la vista GLOBAL del run; esto es
 * la vista POR TURNO. Misma fuente de eventos, cero duplicación de verdad.
 *
 * ── EL LATIDO ───────────────────────────────────────────────────────────────────────
 * Mientras el turno corre, la cabecera de la línea HOSPEDA los signos vitales (el nodo
 * `.ac-vitals[data-live="1"]` que ya existía, movido adentro). No se pinta un segundo
 * pulso al lado del primero: es el MISMO nodo, con el mismo contrato que mide P10, sólo
 * que mientras hay línea viva vive donde el humano está mirando. Al cerrar, la cabecera
 * pasa a su resumen discreto ("Pensó 12 s · 3 acciones ∨"), COLAPSADO por default.
 *
 * Este módulo es puro: strings, CSS y constructores de HTML. El DOM del chat lo maneja
 * `aleph-chat.js`, que es quien sabe encolar hasta que deep-chat renderizó.
 */

/* ── i18n · ES/EN en lockstep, un solo lugar (misma ley que aleph-chat.js) ────────── */
export const STRINGS = {
  es: {
    "li.pensando": "pensando…",
    "li.trabajando": "trabajando…",
    "li.penso": "Pensó",
    "li.accion_1": "1 acción",
    "li.accion_n": "{n} acciones",
    "li.ver": "ver la línea",
    "li.ocultar": "ocultar la línea",
    "li.razonamiento": "Razonamiento",
    "li.detalle": "detalle",
    "li.ocultar_detalle": "ocultar el detalle",
    "li.args": "Con qué",
    "li.result": "Qué devolvió",
    "li.doing": "en curso",
    "li.done": "listo",
    "li.fail": "no salió",
    "li.cut": "el turno terminó antes de que devolviera resultado",
    "li.sin_desenlace": "sin desenlace",
  },
  en: {
    "li.pensando": "thinking…",
    "li.trabajando": "working…",
    "li.penso": "Thought",
    "li.accion_1": "1 action",
    "li.accion_n": "{n} actions",
    "li.ver": "show the thread",
    "li.ocultar": "hide the thread",
    "li.razonamiento": "Reasoning",
    "li.detalle": "detail",
    "li.ocultar_detalle": "hide the detail",
    "li.args": "With what",
    "li.result": "What it returned",
    "li.doing": "running",
    "li.done": "done",
    "li.fail": "didn't work",
    "li.cut": "the turn ended before it returned a result",
    "li.sin_desenlace": "no outcome",
  },
};

export function T(lang, key) {
  const tbl = STRINGS[lang] || STRINGS.es;
  return tbl[key] != null ? tbl[key] : (STRINGS.es[key] != null ? STRINGS.es[key] : key);
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Duración humana. Bajo el segundo NO se redondea a "0 s" (diría que no pensó). */
export function dur(ms, lang) {
  const s = Math.max(0, Number(ms) || 0) / 1000;
  if (s < 1) return (lang === "en" ? "<1s" : "<1 s");
  if (s < 60) return (s < 10 ? s.toFixed(1) : String(Math.round(s))).replace(".0", "") + (lang === "en" ? "s" : " s");
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m + (lang === "en" ? "m" : " min") + (r ? " " + r + (lang === "en" ? "s" : " s") : "");
}

/** El RESUMEN de la cabecera cerrada. Honesto por construcción:
 *  · hubo razonamiento  → "Pensó 12 s · 3 acciones"
 *  · NO hubo            → "3 acciones · 12 s"   (jamás afirma que pensó)
 *  · ni una ni otra     → ""  (y entonces la línea entera no se pinta)
 */
export function resumen(o, lang) {
  o = o || {};
  const n = Number(o.acciones) || 0;
  const t = dur(o.ms, lang);
  const acc = n === 1 ? T(lang, "li.accion_1") : T(lang, "li.accion_n").replace("{n}", String(n));
  if (o.razono && n) return T(lang, "li.penso") + " " + t + " · " + acc;
  if (o.razono) return T(lang, "li.penso") + " " + t;
  if (n) return acc + " · " + t;
  return "";
}

/* ── CSS · viaja al SHADOW ROOT por auxiliaryStyle (lo concatena aleph-chat.js) ──────
 * Vars de tema con fallback: las custom properties SÍ cruzan el shadow boundary, así que
 * claro/oscuro sigue mandando y no hay un solo hex de un tema hardcodeado. */
export const CSS = `
  .ac-linea{margin:3px 0;font-size:12px;color:var(--muted,#A89C8B)}
  .ac-li-head{display:flex;align-items:center;gap:7px;width:100%;text-align:left;
    background:none;border:none;font:inherit;color:var(--faint,#897F70);cursor:pointer;
    padding:3px 0;line-height:1.4;border-radius:7px}
  .ac-li-head:hover{color:var(--ink,#F3ECE0)}
  .ac-li-head .ac-li-res{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .ac-li-head .ac-li-chev{flex:none;font-size:10px;opacity:.75;transition:transform .15s ease}
  .ac-linea[data-open="1"] .ac-li-head .ac-li-chev{transform:rotate(180deg)}
  /* mientras la línea VIVE, su cabecera hospeda los signos vitales: un solo latido */
  .ac-linea[data-viva="1"] .ac-li-head{cursor:default}
  .ac-linea[data-viva="1"] .ac-li-head .ac-vitals{flex:1;min-width:0;padding:0}
  .ac-linea[data-viva="1"] .ac-li-res{display:none}
  .ac-linea:not([data-viva="1"]) .ac-li-head .ac-vitals{display:none}
  .ac-li-body{margin-top:4px;border-left:2px solid var(--line2,#4A433A);padding:2px 0 2px 11px;
    display:flex;flex-direction:column;gap:6px}
  .ac-linea:not([data-open="1"]) .ac-li-body{display:none}

  /* RAZONAMIENTO — SÓLO existe si el cerebro lo emitió (jamás se fabrica) */
  .ac-li-piensa{white-space:pre-wrap;font-size:11.5px;line-height:1.5;color:var(--muted,#A89C8B);
    max-height:220px;overflow:auto}
  .ac-li-piensa b{display:block;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;
    color:var(--faint,#897F70);font-weight:500;margin-bottom:3px}

  /* UNA ENTRADA POR ACCIÓN REAL.
   *
   * La entrada ES la card .ac-act de siempre — misma clase, mismo data-act-id, mismo
   * .ac-act-st, mismo cerrarAct(). Eso NO es pereza: es que el desenlace de una acción
   * tiene UN solo camino en todo el producto (§P10: toda card cierra, ✓ o ✗ con causa). Lo
   * único que cambia adentro de la línea es la FORMA: deja de ser una cajita suelta y se
   * lee como una fila del log. Una clase nueva habría creado un segundo contrato de cierre
   * —y con él, el segundo lugar donde una acción se queda girando para siempre. */
  .ac-li-log{display:flex;flex-direction:column;gap:4px}
  .ac-li-log .ac-act{border:none;background:none;border-radius:0;padding:1px 0;margin:0;
    align-items:baseline;font-size:11.5px;gap:7px}
  .ac-li-log .ac-act .ac-face{align-self:center}
  .ac-li-log .ac-act .ac-act-tt{font-weight:500;white-space:normal;overflow:visible;text-overflow:clip}
  .ac-li-log .ac-act .ac-act-sub{display:inline;margin-left:6px;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;word-break:break-word}
  .ac-li-log .ac-act .ac-act-st{border:none;padding:0;font-size:10.5px;white-space:nowrap}
  .ac-li-log .ac-act.fail{border:none}
  .ac-li-log .ac-act.fail .ac-act-tt{color:#E58A8A}
  .ac-li-more{flex:none;border:none;background:none;font:inherit;font-size:10.5px;
    color:var(--faint,#897F70);cursor:pointer;padding:0;text-decoration:underline;
    text-underline-offset:2px}
  .ac-li-more:hover{color:var(--accent-deep,#B4B1FF)}
  /* el CAMINO de una acción fallida: el botón sale de caminoDe, jamás se escribe a mano */
  .ac-li-cam{border:1px solid var(--line2,#4A433A);background:none;color:var(--accent-deep,#B4B1FF);
    border-radius:7px;padding:1px 8px;font:inherit;font-size:10.5px;font-weight:500;cursor:pointer;
    flex:none}
  .ac-li-cam:hover{border-color:var(--accent,#8B5CF6)}
  .ac-li-det{margin:0 0 3px 21px;font-size:10.5px;line-height:1.5;color:var(--muted,#A89C8B);
    border-left:1px dashed var(--line2,#4A433A);padding-left:9px;white-space:pre-wrap;
    word-break:break-word;max-height:190px;overflow:auto}
  .ac-li-det[hidden]{display:none}
  .ac-li-det b{display:block;color:var(--faint,#897F70);font-weight:500;margin:3px 0 1px}
  .ac-li-det b:first-child{margin-top:0}
`;

/* ── constructores de HTML ─────────────────────────────────────────────────────────
 * `faceHTML` se inyecta (lo trae aleph-chat.js) para que este módulo no dependa de
 * brandface directamente: logo REAL del servicio, y si el manifest no lo conoce, las
 * iniciales deterministas de serviceFace. Jamás un cuadradito vacío. */

/** El esqueleto de la línea. Nace VIVA y COLAPSADA. */
export function lineaHTML(id, lang) {
  return (
    '<div class="ac-linea ac-li" data-linea="' + esc(id) + '" data-viva="1" data-open="0">' +
      '<button type="button" class="ac-li-head" data-li-act="head" aria-expanded="false" ' +
        'title="' + esc(T(lang, "li.ver")) + '">' +
        '<span class="ac-li-res"></span>' +
        '<span class="ac-li-chev" aria-hidden="true">∨</span>' +
      "</button>" +
      '<div class="ac-li-body"><div class="ac-li-log"></div></div>' +
    "</div>"
  );
}

/** El bloque de razonamiento. SÓLO se construye cuando ya hay texto real. */
export function razonHTML(lang) {
  return '<div class="ac-li-piensa"><b>' + esc(T(lang, "li.razonamiento")) + "</b><span></span></div>";
}

/** El botón que despliega el detalle de UNA entrada + su contenedor plegado.
 *  Los dos cuelgan del delegado de la raíz (`ac-li`), así que funcionan aunque la entrada
 *  se haya agregado mucho después de que deep-chat renderizó el mensaje. */
export function detalleSlotHTML(id, lang) {
  return {
    boton: '<button type="button" class="ac-li-more" data-li-act="det" data-e="' + esc(id) + '">' +
           esc(T(lang, "li.detalle")) + "</button>",
    caja: '<div class="ac-li-det" data-det="' + esc(id) + '" hidden></div>',
  };
}

/** El detalle PLEGADO de una entrada: con qué se llamó y qué devolvió. Texto, no JSON crudo
 *  sin formato — y siempre acotado (un result de 200 KB no entra a una burbuja de chat). */
export function detalleHTML(o, lang) {
  o = o || {};
  const trozo = (v, lim) => {
    let t;
    if (v == null) return "";
    if (typeof v === "string") t = v;
    else { try { t = JSON.stringify(v, null, 1); } catch (e) { t = String(v); } }
    t = t.trim();
    return t.length > lim ? t.slice(0, lim - 1) + "…" : t;
  };
  const a = trozo(o.args, 700), r = trozo(o.result, 1400);
  let h = "";
  if (a) h += "<b>" + esc(T(lang, "li.args")) + "</b>" + esc(a);
  if (r) h += "<b>" + esc(T(lang, "li.result")) + "</b>" + esc(r);
  return h;
}

export default { STRINGS, T, esc, dur, resumen, CSS, lineaHTML, razonHTML, detalleSlotHTML, detalleHTML };
