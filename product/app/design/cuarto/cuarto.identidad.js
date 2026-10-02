/* cuarto.identidad.js — IDENTIDAD ÚNICA POR PIEZA en el diorama.
 *
 * LA LEY (sellada el 7-jul, intacta): la etiqueta del diorama es el NOMBRE DEL SERVICIO
 * (server/backed_by titleizado), no la descripción del card. Los nombres propios no se
 * traducen ni se decoran. Este módulo NO cambia esa ley: la completa.
 *
 * EL BUG (caminata): tres piezas CAD en el piso con el mismo logo y casi el mismo nombre —
 * "Cad", "Freecad", "Fem" —, imposible saber cuál equipar o cuál está rota sin abrirlas una
 * por una. Medido en el catálogo REAL (54 átomos, :8275):
 *   · server `freecad` → "Freecad"  (FreeCAD por el puente GUI XML-RPC :9875)
 *   · server `cad`     → "Cad"      (el MISMO FreeCAD, pero headless / freecadcmd)
 *   · server `fem`     → "Fem"      (CalculiX)
 *   `freecad` y `cad` resuelven AMBOS al ícono "box" (cuarto.icons.js) y "Cad" es substring
 *   de "Freecad" → mismo logo + nombre contenido = indistinguibles a simple vista.
 * Y hay colisión EXACTA alcanzable: 4 cards del belt OSINT comparten `backed_by: maritime`
 * → cuatro piezas "Maritime"; ídem `freecad` ×2 cards (cad-freecad + cad-script).
 *
 * LA REGLA GENERAL (no un parche puntual): DOS PIEZAS JAMÁS PUEDEN QUEDAR CON LABEL
 * IDÉNTICO EN EL DIORAMA. Cuando colisionan —o cuando una es CONFUNDIBLE con otra porque su
 * nombre está contenido en el de la vecina— aparece automáticamente un CALIFICADOR corto y
 * honesto, sacado de los datos REALES de la pieza (jamás un "(2)" decorativo):
 *   1. el nombre propio del card (el paréntesis: "Sanciones y PEP (OpenSanctions)" → OpenSanctions)
 *   2. la palabra que de verdad la separa del nombre base ("… (FreeCAD headless)" → headless)
 *   3. la cuenta/conector, cuando ES lo que cambia
 *   4. la primera tool real del MCP
 *   5. el id del card titleizado — real, nunca un contador
 *
 * QUIÉN se califica:
 *   · colisión EXACTA (mismo label base) → se califican TODAS (ninguna es la "verdadera")
 *   · CONFUNDIBLE (un base contenido en otro, p.ej. "Cad" ⊂ "Freecad") → se califica la
 *     CONTENIDA, que es la ambigua; la que ya dice su nombre completo se queda limpia.
 *
 * El label es CORTO; el detalle completo (server, origen/belt, qué la distingue) vive un
 * clic adentro, en el closet de la pieza (`detalleDe`).
 *
 * PURO: sin DOM, sin PIXI, sin red. Se testea headless y lo consume render + inspector.
 */

/** NOMBRE de servicio titleizado — la MISMA función que ya usaba el diorama (ley 7-jul). */
export const svcName = (s) => (s || "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/** label BASE de una pieza: el nombre del servicio; sin server (Memoria/Núcleo) cae a su label. */
export function baseLabel(p) {
  if (!p) return "";
  return svcName(p.server || p.ref || p.mcp || "") || p.label || p.id || "Tool";
}

const _norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
/** palabras significativas de un texto (sin conectores del español, que no identifican nada). */
const _STOP = new Set(["de", "del", "la", "el", "los", "las", "y", "e", "o", "u", "en", "con", "para",
  "por", "a", "al", "un", "una", "the", "of", "and", "or", "for", "to", "in"]);
const _words = (s) => String(s || "").split(/[^\p{L}\p{N}+.#]+/u).filter((w) => w && !_STOP.has(w.toLowerCase()));

/** el nombre propio entre paréntesis, si el card lo trae: "Sanciones y PEP (OpenSanctions)" → "OpenSanctions".
 *  Se exige una MAYÚSCULA: "(pago)" es una aclaración, no el nombre de nada — ese cae a la regla (4). */
function _parentetico(txt) {
  const m = /\(([^)]{2,40})\)\s*$/.exec(String(txt || "").trim());
  const v = m ? m[1].trim() : "";
  return /[A-ZÁÉÍÓÚÑ]/.test(v) ? v : "";
}

/** el calificador es CORTO: hasta 3 palabras y ~22 caracteres. El detalle vive un clic adentro. */
const _corto = (ws) => {
  const out = [];
  for (const w of ws.slice(0, 3)) {
    if (out.length && out.join(" ").length + 1 + w.length > 22) break;
    out.push(w);
  }
  return out.join(" ");
};

/** El card que representa a la pieza (una pieza = un MCP; puede traer varios cards plegados). */
function _cardDe(p) {
  const cards = (p && p.cards) || [];
  return cards.length ? cards[0] : null;
}

/** CALIFICADOR: lo corto y honesto que de verdad separa a esta pieza de su homónima.
 *  `base` = el label base ya calculado (para no repetir palabras que ya están en él). */
export function calificadorDe(p, base) {
  if (!p) return "";
  const b = _norm(base);
  const card = _cardDe(p);
  const cardLabel = (card && card.label) || (p.cardCount === 1 ? p.label : "") || "";

  // (1) nombre propio del card, si no repite el nombre base
  const par = _parentetico(cardLabel || p.label);
  if (par) {
    const ws = _words(par);
    // (2) si el paréntesis ARRANCA con el nombre base ("FreeCAD headless" vs base "Cad"),
    //     lo que separa es lo que sobra: quedarse con eso y no repetir.
    const sobra = ws.filter((w) => _norm(w) !== b && !_norm(w).includes(b) && !b.includes(_norm(w)));
    if (sobra.length && sobra.length < ws.length) return _corto(sobra);
    if (ws.length && _norm(par) !== b) return _corto(ws);
  }

  // (3) la cuenta/conector, cuando es lo que cambia
  if (p.connector && _norm(p.connector) !== b) return svcName(p.connector);

  // (4) del label del card, las palabras que NO están en el nombre base
  const propias = _words(cardLabel).filter((w) => {
    const n = _norm(w);
    return n && n !== b && !n.includes(b) && !b.includes(n);
  });
  if (propias.length) return _corto(propias);

  // (5) la primera tool REAL del MCP
  const t = (p.tools || [])[0];
  if (t && _norm(t) !== b) return String(t).replace(/[_-]+/g, " ");

  // (6) el id del card — real, nunca un contador
  const id = (card && card.id) || p.id || "";
  if (id && _norm(id) !== b) return svcName(id);
  return "";
}

/** ¿`a` es CONFUNDIBLE con `b`? — su nombre está contenido en el del otro ("Cad" ⊂ "Freecad").
 *  Se exige ≥3 caracteres para no disparar con siglas de 1-2 letras. */
export function esConfundible(a, b) {
  const x = _norm(a), y = _norm(b);
  if (!x || !y || x === y) return false;
  if (x.length < 3 || y.length < 3) return false;
  return x.includes(y) || y.includes(x);
}

/** IDENTIDAD del piso completo.
 *  Entrada: array de `data` de piezas colocadas (cada una con {id, server, label, cards, tools…}).
 *  Salida: Map id → { base, calificador, label, confundible, colision }.
 *  INVARIANTE: dos entradas JAMÁS comparten `label`. */
export function identidadDe(piezas) {
  const list = (piezas || []).filter(Boolean);
  const out = new Map();
  const bases = list.map((p) => ({ p, base: baseLabel(p) }));

  // (a) colisión EXACTA de base → se califican TODAS
  const porBase = new Map();
  bases.forEach((e) => { const k = _norm(e.base); if (!porBase.has(k)) porBase.set(k, []); porBase.get(k).push(e); });

  // (b) CONFUNDIBLE: base contenida en la de otra pieza de base distinta → se califica la CONTENIDA
  const contenida = new Set();
  for (let i = 0; i < bases.length; i++) {
    for (let j = 0; j < bases.length; j++) {
      if (i === j) continue;
      const a = bases[i].base, b = bases[j].base;
      if (_norm(a) === _norm(b)) continue;          // eso es colisión exacta, ya cubierta en (a)
      if (esConfundible(a, b) && _norm(a).length <= _norm(b).length) contenida.add(bases[i].p.id);
    }
  }

  bases.forEach((e) => {
    const grupo = porBase.get(_norm(e.base)) || [];
    const colision = grupo.length > 1;
    const confundible = contenida.has(e.p.id);
    let calificador = "";
    if (colision || confundible) calificador = calificadorDe(e.p, e.base);
    out.set(e.p.id, { base: e.base, calificador, confundible, colision,
                      label: calificador ? `${e.base} · ${calificador}` : e.base });
  });

  // (c) RED DE SEGURIDAD — la regla es DURA: si tras calificar dos siguen idénticas (dos cards
  //     sin nada propio que las separe), se desempata con el id REAL de la pieza. Nunca "(2)".
  const vistos = new Map();
  out.forEach((v, id) => {
    const k = _norm(v.label);
    if (!vistos.has(k)) { vistos.set(k, id); return; }
    const extra = svcName(String(id).replace(/^.*?[:#]/, "")) || String(id);
    v.calificador = v.calificador ? `${v.calificador} · ${extra}` : extra;
    v.label = `${v.base} · ${v.calificador}`;
  });
  return out;
}

/** DETALLE completo de la pieza — lo que vive un clic adentro (closet/inspector), no en el label. */
export function detalleDe(p, ident) {
  if (!p) return null;
  const id = ident || { base: baseLabel(p), calificador: "", label: baseLabel(p) };
  const card = _cardDe(p);
  const belt = p.belt_ref || (card && card.belt_ref) || null;
  return {
    label: id.label,
    servidor: p.server || p.ref || p.mcp || null,       // el MCP real que la respalda
    origen: belt,                                        // de qué belt salió (archivo real)
    distingue: id.calificador || null,                   // QUÉ la separa de su homónima (vacío = es única)
    porQue: id.colision ? "otra pieza del piso usa el MISMO servidor"
          : id.confundible ? "otra pieza del piso tiene un nombre que la contiene"
          : null,
    card: card ? { id: card.id, label: card.label, sub: card.sub } : null,
    tools: (p.tools || []).slice(),
    cuenta: p.connector || null,
  };
}

if (typeof window !== "undefined") {
  window.CuartoIdentidad = { svcName, baseLabel, calificadorDe, esConfundible, identidadDe, detalleDe };
}
