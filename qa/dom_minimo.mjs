/* dom_minimo.mjs — EL DOM MÁS CHICO QUE ALCANZA PARA PROBAR UN CLICK.
 *
 * ⚠️ POR QUÉ EXISTE, Y POR QUÉ NO ES UN NAVEGADOR.
 *
 * La casa ya decidió que sus varas de superficie corren SIN navegador, y la razón está
 * escrita en `verify_superficie_montada.mjs`: «una vara que necesita un navegador se corre
 * una vez y se abandona — están todas en el árbol, todas verdes de hace semanas, ninguna
 * corriendo». Medido en esta máquina el 2026-08-05: playwright no está instalado, no hay
 * `node_modules/playwright` ni `~/.cache/ms-playwright`, y `qa/correr_varas.py` sólo
 * recolecta `verify_*.py` — así que ninguna vara `.mjs` de navegador corre hoy.
 *
 * Pero un testigo de ALCANZABILIDAD —«el flujo existe POR CLICKS, no sólo renderiza»— no se
 * puede escribir sin un DOM: hay que apretar algo y ver qué verbo corre. Este archivo es
 * exactamente eso y nada más: los nodos, el `innerHTML`, la delegación de eventos y los
 * selectores que `montaje.js` usa de verdad.
 *
 * LO QUE **NO** ES: no es jsdom, no implementa layout, ni CSS, ni foco, ni formularios. Si
 * una vara futura necesita algo de eso, la respuesta no es agrandar esto hasta que sea un
 * navegador malo — es levantar uno de verdad para ESE testigo.
 */

const VACIOS = new Set(["input", "br", "img", "hr", "meta", "link"]);

class Nodo {
  constructor(tag, attrs = {}) {
    this.tag = String(tag || "").toLowerCase();
    this.attrs = attrs;
    this.hijos = [];
    this.padre = null;
    this.oyentes = {};
    this.texto = "";
    this._value = attrs.value || "";
  }

  /* ── atributos ─────────────────────────────────────────────────────────────── */
  getAttribute(n) { return Object.prototype.hasOwnProperty.call(this.attrs, n) ? this.attrs[n] : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  // Faltaba, y no era un lujo: hay marcas TRANSITORIAS —la pieza señalada al llegar del
  // catálogo— que se ponen y se sacan. Sin esto, el código real reventaba en la vara por
  // una carencia del doble, que es un rojo que no habla de la superficie.
  removeAttribute(n) { delete this.attrs[n]; }
  hasAttribute(n) { return Object.prototype.hasOwnProperty.call(this.attrs, n); }

  /** `dataset` en camelCase, como el de verdad: `data-no-coincide` → `noCoincide`. Es lo que
   *  `montaje.js` lee, así que si esta traducción fuera distinta la vara probaría otra cosa. */
  get dataset() {
    const d = {};
    for (const [k, v] of Object.entries(this.attrs))
      if (k.startsWith("data-"))
        d[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
    return d;
  }

  get classList() {
    const cs = String(this.attrs.class || "").split(/\s+/).filter(Boolean);
    return { contains: (c) => cs.includes(c), toggle: () => {}, add: () => {}, remove: () => {} };
  }

  get hidden() { return this.attrs.hidden === "" || this.attrs.hidden === "true" || this._hidden === true; }
  set hidden(v) { this._hidden = !!v; if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }

  get value() { return this._value; }
  set value(v) { this._value = String(v); }

  get textContent() {
    return this.texto + this.hijos.map((h) => (h instanceof Nodo ? h.textContent : String(h))).join("");
  }
  set textContent(v) { this.hijos = []; this.texto = String(v); }

  /* ── el árbol ──────────────────────────────────────────────────────────────── */
  get innerHTML() { return this._html || ""; }
  set innerHTML(html) {
    this._html = String(html == null ? "" : html);
    this.hijos = parsear(this._html, this);
  }
  appendChild(n) { n.padre = this; this.hijos.push(n); return n; }

  /** Todos los descendientes, en orden de documento. */
  *descendientes() {
    for (const h of this.hijos) { if (h instanceof Nodo) { yield h; yield* h.descendientes(); } }
  }

  /* ── selectores ────────────────────────────────────────────────────────────── */
  matches(selector) {
    return String(selector).split(",").map((s) => s.trim()).filter(Boolean)
      .some((s) => _matchSimple(this, s));
  }
  querySelector(sel) { for (const n of this.descendientes()) if (n.matches(sel)) return n; return null; }
  querySelectorAll(sel) { return Array.from(this.descendientes()).filter((n) => n.matches(sel)); }
  closest(sel) {
    let n = this;
    while (n) { if (n instanceof Nodo && n.matches(sel)) return n; n = n.padre; }
    return null;
  }

  /* ── eventos ───────────────────────────────────────────────────────────────── */
  addEventListener(tipo, fn) { (this.oyentes[tipo] = this.oyentes[tipo] || []).push(fn); }

  /** BURBUJEA, y eso es el punto entero: `montaje.js` usa UN listener por host y delega.
   *  Un dispatch que no burbujeara probaría un mecanismo que la pantalla no usa. */
  async dispatchEvent(ev) {
    ev.target = ev.target || this;
    ev.preventDefault = () => { ev.defaultPrevented = true; };
    let n = this;
    while (n) {
      for (const fn of (n.oyentes[ev.type] || [])) await fn(ev);
      n = n.padre;
    }
    return !ev.defaultPrevented;
  }

  /** Apretar esto de verdad: el mismo evento que dispararía un dedo. */
  click() { return this.dispatchEvent({ type: "click" }); }
}

/** ¿Este nodo matchea un selector SIMPLE (sin combinadores)? Soporta lo que la sección usa:
 *  `tag`, `.clase`, `#id`, `[attr]`, `[attr="valor"]`, y sus concatenaciones. */
function _matchSimple(n, sel) {
  const partes = sel.match(/^[a-zA-Z][\w-]*|\.[\w-]+|#[\w-]+|\[[^\]]+\]/g);
  if (!partes) return false;
  // el selector tiene que consumirse entero: si sobra texto, no es un selector que
  // entendamos, y devolver `true` por la parte que sí entendimos sería un falso verde.
  if (partes.join("") !== sel.replace(/\s+/g, "")) return false;
  for (const p of partes) {
    if (p.startsWith(".")) { if (!n.classList.contains(p.slice(1))) return false; }
    else if (p.startsWith("#")) { if (n.attrs.id !== p.slice(1)) return false; }
    else if (p.startsWith("[")) {
      const m = p.slice(1, -1).match(/^([\w-]+)(?:=["']?(.*?)["']?)?$/);
      if (!m) return false;
      if (!n.hasAttribute(m[1])) return false;
      if (m[2] !== undefined && n.getAttribute(m[1]) !== m[2]) return false;
    } else if (n.tag !== p.toLowerCase()) return false;
  }
  return true;
}

/** El parser. Tag-soup a propósito: la superficie emite HTML que ella misma escribe, así que
 *  no hay que tolerar basura — sólo hay que leerlo bien. */
function parsear(html, padre) {
  const raiz = [];
  // ⚠️ EL PADRE DE LOS NODOS DE PRIMER NIVEL ES EL HOST, y no es un detalle: sin esto el
  // burbujeo se corta en la raíz del fragmento y NUNCA llega al listener delegado del host
  // — que es justamente el mecanismo que estas varas existen para probar. Un click se
  // dispararía, no fallaría nada, y el testigo pasaría sin medir.
  const pila = [{ nodo: padre, hijos: raiz }];
  const re = /<\/?([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:=(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>/g;
  let pos = 0, m;
  const texto = (t) => {
    if (!t) return;
    const cima = pila[pila.length - 1];
    // el texto suelto del primer nivel no tiene dónde vivir: lo absorbe el host, igual que
    // en un DOM de verdad quedaría como nodo de texto suyo.
    if (cima.nodo && cima.nodo !== padre) cima.nodo.texto += t;
  };
  while ((m = re.exec(html))) {
    texto(html.slice(pos, m.index));
    pos = re.lastIndex;
    const [todo, tag, crudo, cierraSolo] = m;
    const nombre = tag.toLowerCase();
    if (todo.startsWith("</")) {
      // cierra: se desapila hasta el tag correspondiente (o no se hace nada si no está)
      for (let i = pila.length - 1; i > 0; i--) {
        if (pila[i].nodo.tag === nombre) { pila.length = i; break; }
      }
      continue;
    }
    const attrs = {};
    for (const a of crudo.matchAll(/([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g))
      attrs[a[1]] = a[2] !== undefined ? a[3] !== undefined ? a[3] : a[2]
                  : a[3] !== undefined ? a[3] : (a[4] !== undefined ? a[4] : "");
    const n = new Nodo(nombre, attrs);
    const cima = pila[pila.length - 1];
    n.padre = cima.nodo;
    cima.hijos.push(n);
    if (!cierraSolo && !VACIOS.has(nombre)) pila.push({ nodo: n, hijos: n.hijos });
  }
  texto(html.slice(pos));
  return raiz;
}

/** Monta un documento vacío en los globales, para que los módulos de la casa lo encuentren
 *  donde lo buscan. Devuelve `document` y una función para crear nodos sueltos. */
export function instalarDOM() {
  const doc = new Nodo("#document");
  doc.head = doc.appendChild(new Nodo("head"));
  doc.body = doc.appendChild(new Nodo("body"));
  doc.createElement = (t) => new Nodo(t);
  doc.getElementById = (id) => doc.querySelector(`#${id}`);
  doc.documentElement = doc;

  const win = {
    addEventListener: () => {},
    scrollX: 0, scrollY: 0, innerWidth: 1280,
    location: { search: "", href: "" },
  };
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.CSS = { escape: (s) => String(s).replace(/["\\\]]/g, "\\$&") };
  return { doc, win, Nodo };
}

/** Un host suelto: el nodo que la pantalla le pasaría a `montar()`. */
export function host(id) {
  const n = new Nodo("div", { id });
  document.body.appendChild(n);
  return n;
}

export { Nodo };
