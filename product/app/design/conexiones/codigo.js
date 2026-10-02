/* codigo.js — EL TAB «CÓDIGO» DEJA DE SER AMBIGUO (Terminal B · §H).
 *
 * AUDITORÍA (lo que el tab muestra HOY, leído de cuarto.pixi.html · loadCode):
 *   1. Núcleo        → «Receta · núcleo (live)»  = JSON {meta, model, framing} armado en el
 *                      cliente con tilesToRecipe. Refleja perillas vivas.
 *   2. Pieza con MCP → «Receta · esta pieza (live)» (pieceSlice) + «Handler MCP (read-only)»
 *                      traído de GET /v1/tools/{ref}/handler.
 *   3. Pieza nacida de inspección (sin ref) → «Handler (read-only)» SINTETIZADO en el
 *                      cliente por synthHandler(): una PLANTILLA en Python, no el código que
 *                      corre. Era lo más engañoso del tab: parecía fuente real.
 *
 * ¿HAY CAMINO BACKEND?
 *   · RECETA  → SÍ: POST /v1/recipes/validate (recipe_validator, contrato taller↔assembler)
 *               devuelve {valid, errors[], warnings[], effective_gates}. Veredicto REAL.
 *   · HANDLER → NO: el tools router es explícitamente READ-ONLY (sólo GET
 *               /v1/tools/{ref}/handler; no hay PUT/POST/PATCH). No existe forma de aplicar
 *               una edición de handler, y fabricar una sería mentir.
 *
 * LO QUE ESTE MÓDULO HACE (aditivo, sin tocar cuarto.pixi.html):
 *   · RECETA  → EDITABLE + [Validar] con veredicto real: ✓ válida (con warnings y los gates
 *               que Security va a hacer cumplir igual) · ✗ error CON LÍNEA y causa. Valida la
 *               receta COMPLETA con la edición aplicada — no un fragmento suelto, que daría
 *               un rojo falso. [Aplicar] aparece SÓLO si el Cuarto expone el gancho (contrato
 *               abajo); si no está, se dice, no se finge un botón muerto.
 *   · HANDLER → cartel «SOLO LECTURA» visible + [Copiar]. El sintetizado además se declara
 *               plantilla, no fuente.
 *
 * CONTRATO PARA LA TERMINAL C (opcional, sólo para [Aplicar]):
 *     window.__cuartoAplicarReceta = (receta) => boolean|Promise<boolean>
 *   — o escuchar `cuarto:codigo-aplicar` (detail={receta, clase, pieza}) y llamar
 *     preventDefault() para declarar que lo aplicó. Sin ninguno de los dos, este módulo NO
 *     muestra [Aplicar]: prefiere no ofrecer un camino que no existe.
 *
 * Enganche: una línea en cuarto.pixi.html →
 *     <script type="module" src="../conexiones/codigo.js"></script>
 */
import { tilesToRecipe } from "../cuarto/cuarto.recipe.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// El validador está detrás de la sesión (CONTRACT-AUTH-v2). auth.js ya parchea window.fetch
// en las pantallas que lo cargan, pero este módulo se monta por fuera: manda el Bearer él
// mismo para no depender de dónde lo enganchen. Mismo patrón que cuarto.semaforo.js.
function _conSesion(h) {
  h = h || {};
  try {
    const u = (window.AlephSession && window.AlephSession.get)
      ? window.AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") || localStorage.getItem("puppet_user") || "null");
    if (u && u.session_token && !h["Authorization"]) h["Authorization"] = "Bearer " + u.session_token;
  } catch (e) { /* sin sesión: el backend contesta 401 y lo decimos tal cual */ }
  return h;
}

const CSS = `
.cxc-barra{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:6px 0 2px}
.cxc-tag{font-size:10px;font-weight:500;letter-spacing:.05em;text-transform:uppercase;
  border-radius:var(--r-xs);padding:2px 6px;border:1px solid currentColor}
.cxc-tag.ro{color:#9aa0b5}
.cxc-tag.ed{color:#8e8bf5}
.cxc-b{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.05);color:inherit;
  border-radius:var(--r-xs);padding:4px 9px;font:inherit;font-size:11.5px;font-weight:500;cursor:pointer}
.cxc-b:hover{border-color:#8e8bf5}
.cxc-b.pri{background:#8e8bf5;border-color:#8e8bf5;color:var(--on-accent)}
.cxc-b:disabled{opacity:.55;cursor:progress}
.cxc-ed{width:100%;min-height:150px;max-height:340px;font-family:var(--font-mono);
  font-size:11.5px;line-height:1.5;color:#dcd8ff;background:#0f1020;border:1px solid #3c3d5c;
  border-radius:var(--r-sm);padding:9px 10px;outline:none;resize:vertical;tab-size:2;white-space:pre}
.cxc-ed:focus{border-color:#8e8bf5}
.cxc-ed.mal{border-color:#f49a9a}
.cxc-msg{margin-top:6px;font-size:11.5px;line-height:1.5;border-radius:var(--r-xs);padding:7px 9px;display:none}
.cxc-msg.on{display:block}
.cxc-msg.ok{color:#7be0a8;background:rgba(123,224,168,.10);border:1px solid rgba(123,224,168,.35)}
.cxc-msg.bad{color:#f49a9a;background:rgba(244,154,154,.10);border:1px solid rgba(244,154,154,.35)}
.cxc-msg.warn{color:#e7c06a;background:rgba(231,192,106,.10);border:1px solid rgba(231,192,106,.35)}
.cxc-msg ul{margin:5px 0 0;padding-left:17px}
.cxc-msg .ln{font-family:var(--font-mono);opacity:.85}
.cxc-nota{font-size:11px;color:#8a8fa5;margin-top:5px;line-height:1.5}
html[data-theme="light"] .cxc-ed{background:#f1eefc;color:#3a3170;border-color:#d7d3ec}
html[data-theme="light"] .cxc-b{border-color:#d7d3ec;background:#fff}
`;

function inyectar() {
  if (document.getElementById("cxc-css")) return;
  const s = document.createElement("style"); s.id = "cxc-css"; s.textContent = CSS;
  (document.head || document.documentElement).appendChild(s);
}

// ── ¿el Cuarto ofrece dónde APLICAR? Si no, no inventamos el botón. ──────────────────
function hayGanchoAplicar() {
  if (typeof window.__cuartoAplicarReceta === "function") return true;
  return !!window.__cuartoAplicaCodigo;   // bandera que puede levantar quien escuche el evento
}

async function aplicar(receta, clase, pieza) {
  if (typeof window.__cuartoAplicarReceta === "function") {
    return !!(await window.__cuartoAplicarReceta(receta, { clase, pieza }));
  }
  const ev = new CustomEvent("cuarto:codigo-aplicar",
    { detail: { receta, clase, pieza }, cancelable: true, bubbles: true });
  const noCancelado = window.dispatchEvent(ev);
  return !noCancelado;   // preventDefault() del oyente = "yo lo apliqué"
}

// ── receta viva completa (la MISMA que arma el Cuarto para guardar/correr) ───────────
function recetaViva() {
  const C = window.__cuarto;
  if (!C || !C.placedTiles || !C.nucleoData) return null;
  try { return tilesToRecipe(C.placedTiles(), C.nucleoData()); } catch (e) { return null; }
}

/** Mete la edición en la receta COMPLETA. Validar un fragmento suelto contra el validador
 *  de recetas daría un rojo falso ("meta requerido") que no es culpa de lo que editaste. */
function mezclar(full, slice, clase) {
  const out = JSON.parse(JSON.stringify(full || {}));
  if (clase === "nucleo") {
    ["meta", "model", "framing"].forEach((k) => { if (k in slice) out[k] = slice[k]; });
    return { receta: out, ignorados: Object.keys(slice).filter((k) => ["meta", "model", "framing"].indexOf(k) < 0) };
  }
  out.belt = out.belt || {};
  const ignorados = [];
  Object.keys(slice).forEach((k) => {
    if (k === "tool_filters") out.belt.tool_filters = Object.assign({}, out.belt.tool_filters || {}, slice.tool_filters || {});
    else if (k === "belt_ref" && slice.belt_ref) {
      const refs = new Set(out.belt.belt_refs || []); refs.add(slice.belt_ref);
      out.belt.belt_refs = [...refs];
    } else if (k === "gate" && slice.gate) {
      out.gates = Object.assign({}, out.gates || {}, { send: slice.gate, money_touch: slice.gate });
    } else if (k === "zona") { /* la zona es del lienzo, no del contrato de receta */ }
    else ignorados.push(k);
  });
  return { receta: out, ignorados };
}

// ── línea + causa: lo que hace que un error sea accionable y no un párrafo ───────────
function lineaDeJSON(txt, pos) {
  const antes = txt.slice(0, Math.max(0, pos));
  const linea = antes.split("\n").length;
  const col = pos - antes.lastIndexOf("\n");
  return { linea, col };
}

/** Índice del primer carácter estructuralmente imposible de un JSON, o -1.
 *  Existe porque los motores NO coinciden: V8 dice "at position N" y WebKit sólo
 *  "Unexpected token '…'". Sin posición no hay línea, y sin línea el error no es
 *  accionable — que es exactamente lo que estamos matando. Escáner propio, determinista. */
function posErrorJSON(t) {
  const pila = [];
  let i = 0, esperando = "valor";
  const blancos = () => { while (i < t.length && /\s/.test(t[i])) i++; };
  const leerString = () => {
    if (t[i] !== '"') return false;
    i++;
    while (i < t.length) {
      if (t[i] === "\\") { i += 2; continue; }
      if (t[i] === '"') { i++; return true; }
      i++;
    }
    return false;   // string sin cerrar
  };
  const leerLiteral = () => {
    const m = /^(true|false|null|-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?)/.exec(t.slice(i));
    if (!m) return false;
    i += m[0].length;
    return true;
  };
  for (let guarda = 0; guarda < 200000; guarda++) {
    blancos();
    if (i >= t.length) return esperando === "fin" ? -1 : Math.max(0, t.length - 1);
    const c = t[i];
    if (esperando === "valor" || esperando === "valor-o-cierre") {
      if (c === "]" && esperando === "valor-o-cierre" && pila[pila.length - 1] === "arr") {
        pila.pop(); i++; esperando = pila.length ? "coma-o-cierre" : "fin"; continue;
      }
      if (c === "{") { pila.push("obj"); i++; esperando = "clave-o-cierre"; continue; }
      if (c === "[") { pila.push("arr"); i++; esperando = "valor-o-cierre"; continue; }
      if (c === '"') { const inicio = i; if (!leerString()) return inicio; esperando = pila.length ? "coma-o-cierre" : "fin"; continue; }
      if (leerLiteral()) { esperando = pila.length ? "coma-o-cierre" : "fin"; continue; }
      return i;
    }
    if (esperando === "clave-o-cierre" || esperando === "clave") {
      if (c === "}" && esperando === "clave-o-cierre" && pila[pila.length - 1] === "obj") {
        pila.pop(); i++; esperando = pila.length ? "coma-o-cierre" : "fin"; continue;
      }
      const inicio = i;
      if (c !== '"') return i;
      if (!leerString()) return inicio;
      esperando = "dos-puntos"; continue;
    }
    if (esperando === "dos-puntos") {
      if (c !== ":") return i;
      i++; esperando = "valor"; continue;
    }
    if (esperando === "coma-o-cierre") {
      if (c === ",") {
        i++; esperando = pila[pila.length - 1] === "obj" ? "clave" : "valor"; continue;
      }
      if (c === "}" && pila[pila.length - 1] === "obj") { pila.pop(); i++; esperando = pila.length ? "coma-o-cierre" : "fin"; continue; }
      if (c === "]" && pila[pila.length - 1] === "arr") { pila.pop(); i++; esperando = pila.length ? "coma-o-cierre" : "fin"; continue; }
      return i;
    }
    if (esperando === "fin") return i;   // basura después del valor raíz
  }
  return -1;
}

function lineaDeRuta(txt, mensaje) {
  const m = String(mensaje || "").match(/([a-z_][a-z0-9_]*(?:\.[a-z0-9_\[\]]+)+|^[a-z_][a-z0-9_]*)/i);
  if (!m) return null;
  const hoja = m[1].split(".").pop().replace(/\[.*\]$/, "");
  const lineas = txt.split("\n");
  for (let i = 0; i < lineas.length; i++) {
    if (lineas[i].indexOf('"' + hoja + '"') >= 0) return i + 1;
  }
  return null;
}

async function validar(txt, clase, pieza) {
  let slice;
  try { slice = JSON.parse(txt); }
  catch (e) {
    const m = String(e.message).match(/position\s+(\d+)/i);
    const pos = m ? Number(m[1]) : posErrorJSON(txt);
    const donde = pos >= 0 ? lineaDeJSON(txt, pos) : null;
    return { ok: false, sintaxis: true,
             errores: [{ msg: "JSON inválido: " + e.message, linea: donde ? donde.linea : null,
                         col: donde ? donde.col : null }] };
  }
  const full = recetaViva();
  if (!full) return { ok: false, errores: [{ msg: "no pude leer la receta viva del Cuarto", linea: null }] };
  const { receta, ignorados } = mezclar(full, slice, clase);
  let d;
  try {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), 20000);
    try {
      const r = await fetch("/v1/recipes/validate", {
        method: "POST", signal: c.signal,
        headers: _conSesion({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify({ recipe: receta }),
      });
      if (!r.ok) return { ok: false, errores: [{ msg: "el validador respondió " + r.status, linea: null }] };
      d = await r.json();
    } finally { clearTimeout(t); }
  } catch (e) {
    return { ok: false, errores: [{ msg: "no llegué al validador: " + (e && e.message || e), linea: null }] };
  }
  return {
    ok: !!d.valid, receta, ignorados,
    errores: (d.errors || []).map((msg) => ({ msg, linea: lineaDeRuta(txt, msg) })),
    warnings: d.warnings || [],
    gates: d.effective_gates || null,
  };
}

// ── el upgrade del bloque ─────────────────────────────────────────────────────────────
function claseDelBloque(hdrTxt) {
  const t = (hdrTxt || "").toLowerCase();
  if (t.indexOf("receta") < 0) return null;
  return t.indexOf("núcleo") >= 0 || t.indexOf("nucleo") >= 0 ? "nucleo" : "pieza";
}

function upgradeRecipe(pre, clase) {
  const original = pre.textContent;
  const box = document.createElement("div");
  box.className = "cxc-caja";
  const puedeAplicar = hayGanchoAplicar();
  box.innerHTML =
    `<div class="cxc-barra"><span class="cxc-tag ed">editable</span>
       <button type="button" class="cxc-b pri" data-a="validar">Validar</button>
       ${puedeAplicar ? '<button type="button" class="cxc-b" data-a="aplicar" disabled>Aplicar</button>' : ""}
       <button type="button" class="cxc-b" data-a="revertir">Revertir</button>
       <button type="button" class="cxc-b" data-a="copiar">Copiar</button></div>
     <textarea class="cxc-ed" spellcheck="false" aria-label="Receta editable"></textarea>
     <div class="cxc-msg"></div>
     ${puedeAplicar ? "" : '<div class="cxc-nota">Puedes editar y <b>validar</b> con el validador real. <b>Aplicar</b> no está disponible en esta pantalla: el Cuarto todavía no expone el gancho para escribir la receta desde aquí.</div>'}`;
  const ta = box.querySelector("textarea");
  ta.value = original;
  const msg = box.querySelector(".cxc-msg");
  const bAplicar = box.querySelector('[data-a="aplicar"]');
  let ultima = null;

  const decir = (kind, html) => { msg.className = "cxc-msg on " + kind; msg.innerHTML = html; };

  box.querySelector('[data-a="validar"]').onclick = async (e) => {
    const b = e.currentTarget; b.disabled = true;
    decir("warn", "validando contra el contrato real…");
    const v = await validar(ta.value, clase);
    b.disabled = false;
    ta.classList.toggle("mal", !v.ok);
    if (bAplicar) bAplicar.disabled = !v.ok;
    ultima = v.ok ? v.receta : null;
    if (v.ok) {
      const w = (v.warnings || []).length
        ? `<ul>${v.warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
      const g = v.gates ? `<div class="cxc-nota">Gates que Security hace cumplir igual: ${esc(JSON.stringify(v.gates))}</div>` : "";
      const ig = (v.ignorados || []).length
        ? `<div class="cxc-nota">Campos que no son parte del contrato de receta y no se validaron: ${esc(v.ignorados.join(", "))}</div>` : "";
      decir("ok", "✓ receta válida" + (w ? " · con avisos:" + w : "") + g + ig);
    } else {
      decir("bad", "✗ " + (v.sintaxis ? "no es JSON válido" : "el validador la rechazó") +
        `<ul>${v.errores.map((x) => `<li>${x.linea ? `<span class="ln">línea ${x.linea}${x.col ? ":" + x.col : ""}</span> — ` : ""}${esc(x.msg)}</li>`).join("")}</ul>`);
      if (v.errores[0] && v.errores[0].linea) irALinea(ta, v.errores[0].linea);
    }
  };
  if (bAplicar) bAplicar.onclick = async (e) => {
    const b = e.currentTarget; b.disabled = true;
    const hecho = await aplicar(ultima, clase);
    b.disabled = false;
    decir(hecho ? "ok" : "bad", hecho ? "✓ aplicado al Cuarto" :
      "✗ nadie aplicó el cambio (el gancho respondió que no). La receta ES válida: el problema es el aplicado.");
  };
  box.querySelector('[data-a="revertir"]').onclick = () => {
    ta.value = original; ta.classList.remove("mal"); msg.className = "cxc-msg";
    if (bAplicar) bAplicar.disabled = true;
  };
  box.querySelector('[data-a="copiar"]').onclick = (e) => copiar(ta.value, e.currentTarget);
  pre.replaceWith(box);
}

function irALinea(ta, linea) {
  try {
    const lineas = ta.value.split("\n");
    let pos = 0;
    for (let i = 0; i < linea - 1 && i < lineas.length; i++) pos += lineas[i].length + 1;
    ta.focus();
    ta.setSelectionRange(pos, pos + (lineas[linea - 1] || "").length);
  } catch (e) { /* seleccionar es un lujo; el mensaje ya trae la línea */ }
}

function upgradeReadOnly(pre, sintetizado) {
  const barra = document.createElement("div");
  barra.className = "cxc-barra";
  barra.innerHTML = `<span class="cxc-tag ro">solo lectura</span>
    <button type="button" class="cxc-b">Copiar</button>
    ${sintetizado ? '<span class="cxc-nota" style="margin:0">plantilla generada por la inspección — no es el código que corre</span>'
                  : '<span class="cxc-nota" style="margin:0">no hay forma de aplicar cambios aquí: el handler es de sólo lectura en el backend</span>'}`;
  barra.querySelector("button").onclick = (e) => copiar(pre.textContent, e.currentTarget);
  pre.parentNode.insertBefore(barra, pre);
  pre.setAttribute("data-cxc", "ro");
}

async function copiar(txt, btn) {
  let ok = false;
  try { await navigator.clipboard.writeText(txt); ok = true; }
  catch (e) {
    try {
      const ta = document.createElement("textarea");
      ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); ok = document.execCommand("copy"); ta.remove();
    } catch (e2) { ok = false; }
  }
  if (btn) { const a = btn.textContent; btn.textContent = ok ? "✓ copiado" : "cópialo a mano"; setTimeout(() => (btn.textContent = a), 1600); }
}

// ── el observador: cada vez que el tab Código se re-rinde, lo mejoramos ──────────────
export function mejorar(host) {
  host = host || $("d-code");
  if (!host) return 0;
  inyectar();
  let n = 0;
  [...host.querySelectorAll("pre.code")].forEach((pre) => {
    if (pre.dataset.cxc) return;
    pre.dataset.cxc = "1";
    const hdr = pre.previousElementSibling;
    const txt = hdr ? hdr.textContent : "";
    const clase = claseDelBloque(txt);
    if (clase) { upgradeRecipe(pre, clase); n++; return; }
    const sintetizado = /handler \(read-only\)/i.test(txt) || /sintetizad/i.test((pre.nextElementSibling || {}).textContent || "");
    upgradeReadOnly(pre, sintetizado);
    n++;
  });
  return n;
}

function arrancar() {
  const host = $("d-code");
  if (!host) { setTimeout(arrancar, 300); return; }
  inyectar();
  mejorar(host);
  try {
    new MutationObserver(() => mejorar(host)).observe(host, { childList: true, subtree: true });
  } catch (e) { /* sin observer: se mejora al montar y al re-entrar por mejorar() */ }
}

if (typeof window !== "undefined") {
  window.AlephCodigo = { mejorar, validar, recetaViva };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arrancar);
  else arrancar();
}

export default { mejorar, validar, recetaViva };
