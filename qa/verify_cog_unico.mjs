/* verify_cog_unico.mjs — LA VARA DEL ⚙ ÚNICO. [Convergencia · superficie 3 · fase 3]
 *
 *   node qa/verify_cog_unico.mjs            ·   node qa/verify_cog_unico.mjs --probar-cayendo
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * Corre `ajustes.js` DE VERDAD en un DOM stubbeado. Mide comportamiento, no texto.
 *
 *  1 · UN SOLO ⚙, y uno solo aunque se monte dos veces
 *  2 · ES OVERLAY, NO NAVEGACIÓN — abrir no toca `location`. Es la promesa entera de esta
 *      fase: entrar a Ajustes desde un workspace no puede apagar el lienzo.
 *  3 · LOS DOS RÓTULOS de Oficina aparecen DENTRO de un workspace…
 *  4 · …y NO aparecen fuera: un selector de ámbito con un solo ámbito es ruido
 *  5 · NINGÚN PANEL ES UNA PERILLA PINTADA — todos tienen `aplicar`. Es la regla que esta
 *      superficie selló en la fase 0, aplicada a sí misma
 *  6 · elegir un valor lo APLICA y lo GUARDA (PUT con ámbito y clave correctos)
 *  7 · `tamano_texto` cambia de verdad la raíz — si no, sería otra perilla pintada
 *  8 · el idioma SE ESCONDE donde no hay motor de idioma (medido: los 6 workspaces cargan
 *      `theme.js` y no `i18n.js`, así que ahí `window.t` no existe)
 *  9 · el link a `Settings.dc.html` sobrevive: hay links viejos apuntando ahí
 * 10 · Escape y el fondo cierran
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
// La tabla se importa DE VERDAD: es un módulo sin dependencias, así que acá sí corre.
import { etiqueta, GENERAL, ORDEN_ETIQUETA } from '../product/app/design/espacios-tabla.js';

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(RAIZ, 'product/app/design/ajustes.js');

const F = [], OK = [];
const chequear = (n, c, d = '') => (c ? OK : F).push(n + (!c && d ? ` — ${d}` : ''));

function correr(src, { path = '/Home.dc.html', conI18n = true, guardado = {}, conBarra = false,
                       noFloat = false } = {}) {
  const puts = [], oyentes = {};
  const nodo = (tag) => {
    const n = {
      tagName: (tag || 'div').toUpperCase(), id: '', type: '', hidden: false, className: '',
      textContent: '', style: {}, attrs: {}, children: [], _html: '', dataset: {},
      setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
      removeAttribute(k) { delete this.attrs[k]; },
      appendChild(c) { this.children.push(c); c.parentElement = this; if (c.id) doc._byId[c.id] = c; return c; },
      addEventListener(t, f) { (this._ev ||= {})[t] = f; },
      get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; },
    };
    return n;
  };
  const barra = nodo('div');
  barra.className = 'ws-bar';
  const estado = nodo('div'); estado.id = 'ws-estado';
  barra.querySelector = (s) => (s === '#ws-estado' ? estado : null);
  barra.insertBefore = function (c, ref) {
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, c);
    c.parentElement = this; if (c.id) doc._byId[c.id] = c; return c;
  };
  const doc = {
    _byId: {}, readyState: 'complete',
    documentElement: nodo('html'), head: nodo('head'), body: nodo('body'),
    createElement: nodo,
    getElementById: (id) => doc._byId[id] || null,
    querySelector: (s) => ((conBarra && s === '.ws-bar') ? barra : null),
    addEventListener: (t, f) => { (oyentes[t] ||= []).push(f); },
  };
  barra.appendChild(estado);   // después de `doc`: appendChild lo referencia
  const win = {
    document: doc, location: { pathname: path, href: 'http://casa' + path },
    setTimeout, Promise, encodeURIComponent, JSON,
    AlephTheme: { _v: 'dark', get() { return this._v; }, set(v) { this._v = v; } },
    fetch: (url, opt = {}) => {
      if ((opt.method || 'GET') === 'PUT') { puts.push({ url, body: JSON.parse(opt.body), opt }); return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }); }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ajustes: guardado }) });
    },
  };
  if (noFloat) win.ALEPH_THEME_NOFLOAT = true;
  if (conI18n) win.AlephI18n = { _l: 'es', lang() { return this._l; }, setLang(v) { this._l = v; } };
  win.window = win; win.globalThis = win;
  win.addEventListener = () => {};
  vm.createContext(win);
  new vm.Script(src, { filename: 'ajustes.js' }).runInContext(win);
  return { win, doc, puts, oyentes,
           cog: () => doc._byId['aleph-cog'],
           caja: () => doc._byId['aleph-ajustes'],
           hoja: () => (doc._byId['aleph-ajustes'] || { children: [] }).children[0],
           barra };
}

function medir(src) {
  // 1 · un solo ⚙
  const A = correr(src);
  chequear('1 · monta un ⚙', !!A.cog(), 'no apareció #aleph-cog');
  const antes = A.doc.body.children.length;
  A.win.AlephAjustes.montar();
  chequear('1 · y no monta un segundo', A.doc.body.children.length === antes,
           `body pasó de ${antes} a ${A.doc.body.children.length}`);

  // 5 · ningún panel sin aplicar — la regla de la fase 0 aplicada a sí misma
  const paneles = A.win.AlephAjustes.paneles;
  chequear('5 · todos los paneles tienen aplicar()',
           paneles.length > 0 && paneles.every((p) => typeof p.aplicar === 'function'),
           paneles.filter((p) => typeof p.aplicar !== 'function').map((p) => p.id).join(','));
  chequear('5 · y todos declaran su clave del almacén',
           paneles.every((p) => typeof p.clave === 'string' && p.clave));

  // 2 · overlay, no navegación
  const hrefAntes = A.win.location.href, pathAntes = A.win.location.pathname;
  A.cog()._ev.click();
  chequear('2 · abrir NO toca location',
           A.win.location.href === hrefAntes && A.win.location.pathname === pathAntes);
  chequear('2 · y el overlay queda visible', A.caja() && A.caja().hidden === false);

  const html = () => A.hoja().innerHTML;
  // 4 · fuera de un workspace no hay selector de ámbito
  chequear('4 · fuera del workspace NO hay rótulos de ámbito',
           !/TODA LA CASA/.test(html()), html().slice(0, 90));
  // 9 · el link viejo sobrevive
  chequear('9 · sigue enlazando Settings.dc.html', /Settings\.dc\.html/.test(html()));
  // 8 · con i18n, el idioma se ofrece
  chequear('8 · con motor de idioma, el control se ofrece', /Idioma/.test(html()));

  // 3 · dentro de un workspace: los dos rótulos
  const W = correr(src, { path: '/workspaces/ciencia.html' });
  W.cog()._ev.click();
  const hw = W.hoja().innerHTML;
  chequear('3 · dentro del workspace el primer rótulo es GENERAL', />GENERAL</.test(hw), hw.slice(0, 140));
  chequear('3 · y el segundo NO lleva «SÓLO» ni «TODA LA CASA»',
           !/SÓLO/.test(hw) && !/TODA LA CASA/.test(hw), hw.slice(0, 200));

  /* 12 · EL RÓTULO SALE DE `etiqueta()`, NO DEL ID CRUDO.
   * El defecto era `ws.toUpperCase()`: en pantalla decía `DISENO` y `EDUCACION`, sin la ñ y
   * sin la tilde. Acá el discriminante es fino y a propósito: en este stub el `import()`
   * dinámico no corre, así que `etiqueta()` cae a devolver el id TAL CUAL —minúscula—.
   * Si alguien volviera a poner `toUpperCase()`, saldría `CIENCIA`. O sea: ver `ciencia` en
   * minúscula PRUEBA que el rótulo pasó por `etiqueta()` y no por el id mayusculizado. */
  chequear('12 · el rótulo pasa por etiqueta(), no por el id mayusculizado',
           /data-ambito="ciencia"[^>]*>ciencia</.test(hw), hw.slice(0, 220));

  /* 12·bis · Y LA TABLA, MEDIDA DE VERDAD. Lo anterior prueba el CAMINO; esto prueba el
   * DESTINO. Sin las dos mitades, el camino podría llevar a una tabla equivocada. */
  chequear('12 · la tabla escribe Diseño con ñ', etiqueta('diseno') === 'Diseño', etiqueta('diseno'));
  chequear('12 · y Educación con tilde', etiqueta('educacion') === 'Educación', etiqueta('educacion'));
  chequear('12 · sin espacio, GENERAL', etiqueta(null) === 'GENERAL' && etiqueta(GENERAL) === 'GENERAL');
  chequear('12 · y están los seis', Object.keys(ORDEN_ETIQUETA).length === 6,
           Object.keys(ORDEN_ETIQUETA).join(','));

  /* 11 · EL ⚙ DENTRO DEL WORKSPACE — el caso que esta fase existe para arreglar, y el que
   * la vara NO medía: los 6 workspaces declaran `ALEPH_THEME_NOFLOAT` y tienen `.ws-bar`.
   * Colgar el montaje de esa bandera dejaba el ⚙ invisible justo ahí. Lo destapó la
   * pantalla, no esta vara — por eso ahora está acá. */
  const B = correr(src, { path: '/workspaces/ciencia.html', conBarra: true, noFloat: true });
  chequear('11 · con NOFLOAT y barra, el ⚙ igual se monta', !!B.cog(),
           'ALEPH_THEME_NOFLOAT lo dejó sin montar');
  chequear('11 · y va DENTRO de la barra, no flotando',
           B.barra.children.includes(B.cog()), 'quedó fuera de .ws-bar');
  chequear('11 · ANTES del estado, para que no se mueva cuando el estado crece',
           B.barra.children.indexOf(B.cog()) < B.barra.children.findIndex((c) => c.id === 'ws-estado'),
           `orden: ${B.barra.children.map((c) => c.id || c.className).join(' · ')}`);

  // 8 · sin motor de idioma, el control no se dibuja
  const S = correr(src, { path: '/workspaces/ciencia.html', conI18n: false });
  S.cog()._ev.click();
  chequear('8 · sin motor de idioma, el control NO se dibuja',
           !/Idioma/.test(S.hoja().innerHTML));

  // 6 y 7 · elegir aplica y guarda
  const raiz = A.doc.documentElement;
  const btn = { getAttribute: (k) => (k === 'data-valor' ? 'grande' : null),
                parentElement: { getAttribute: () => 'tamano_texto' },
                closest: (s) => (s === '.aj-ops button' ? btn : null) };
  // Un panel sin `aplicar` no sólo falla la 5: también revienta el click. Se atrapa y se
  // registra en la MISMA familia, en vez de dejar que aborte la vara entera — un crash no
  // es una medición.
  try {
    A.caja()._ev.click({ target: { closest: (s) => (s === '.aj-ops button' ? btn : null) }, });
  } catch (e) { chequear('5 · elegir no revienta (el panel tiene aplicar)', false, e.message); }
  chequear('7 · tamaño grande escala la RAÍZ', raiz.style.fontSize === '112.5%',
           `fontSize=${raiz.style.fontSize}`);
  chequear('7 · y lo deja declarado en el DOM', raiz.getAttribute('data-aleph-texto') === 'grande');
  const put = A.puts[A.puts.length - 1];
  chequear('6 · y lo guarda con un PUT', !!put && put.url === '/v1/preferencias', JSON.stringify(put && put.url));
  chequear('6 · con la clave correcta', put && put.body.cambios.tamano_texto === 'grande',
           JSON.stringify(put && put.body));
  chequear('6 · y con keepalive', put && put.opt.keepalive === true);

  // 10 · cerrar
  A.caja()._ev.click({ target: { closest: () => null }, });   // clic adentro, no cierra
  chequear('10 · un clic adentro NO cierra', A.caja().hidden === false);
  A.caja()._ev.click({ target: A.caja(), });                   // clic en el fondo
  chequear('10 · el fondo cierra', A.caja().hidden === true);
  A.win.AlephAjustes.abrir();
  (A.oyentes.keydown || []).forEach((f) => f({ key: 'Escape' }));
  chequear('10 · Escape cierra', A.caja().hidden === true);
}

const MUTACIONES = [
  ['el ⚙ se monta dos veces',        'if (document.getElementById("aleph-cog")) return;', '', '1 ·'],
  ['un panel pierde su aplicar',     'aplicar: function (v) {\n        var esc =', 'noAplicar: function (v) {\n        var esc =', '5 ·'],
  ['el tamaño deja de escalar',      'document.documentElement.style.fontSize = esc;', ';', '7 ·'],
  // ⚠️ los anclas apuntan al HTML, no al string suelto: los rótulos aparecen ANTES en el
  // docstring del archivo, y `replace` toma la primera ocurrencia — una mutación pegaba en
  // un comentario y pasaba impune. Lo encontró --probar-cayendo.
  ['el rótulo GENERAL desaparece',   '>GENERAL</button>', '>ALCANCE</button>', '3 ·'],
  ['el rótulo vuelve al id crudo',   'etiqueta(ws) + "</button>"', 'ws.toUpperCase() + "</button>"', '12 ·'],
  ['el idioma se dibuja sin motor',  'disponible: function () { return !!window.AlephI18n; },', '', '8 ·'],
  ['el ⚙ se cuelga de NOFLOAT',      'if (window.ALEPH_AJUSTES_OFF) return;\n    if (document.getElementById("aleph-cog")) return;',
                                     'if (window.ALEPH_THEME_NOFLOAT) return;\n    if (document.getElementById("aleph-cog")) return;', '11 ·'],
  ['el ⚙ va al final de la barra',   'if (estado) barra.insertBefore(b, estado); else barra.appendChild(b);',
                                     'barra.appendChild(b);', '11 ·'],
  ['el PUT pierde keepalive',        'keepalive: true, body: JSON.stringify(cuerpo)', 'body: JSON.stringify(cuerpo)', '6 ·'],
];

const src = readFileSync(SRC, 'utf8');
if (process.argv.includes('--probar-cayendo')) {
  console.log(`— probando la vara cayendo: ${MUTACIONES.length} mutaciones —\n`);
  let malas = 0;
  for (const [nombre, viejo, nuevo, espera] of MUTACIONES) {
    if (!src.includes(viejo)) { console.log(`   ⚠ «${nombre}»: el ancla ya no existe`); malas++; continue; }
    F.length = 0; OK.length = 0;
    try { medir(src.replace(viejo, nuevo)); }
    // ⚠️ UN CRASH NO ES UNA CAÍDA. Si la vara revienta, TODAS las mutaciones parecerían
    // caer y el `--probar-cayendo` daría verde sin medir nada. Se marca aparte.
    catch (e) { console.log(`   ✗ «${nombre}» → la VARA reventó: ${e.message}`); malas++; continue; }
    const cayo = F.filter((f) => f.startsWith(espera));
    if (cayo.length) console.log(`   ✓ «${nombre}» → rojea ${espera} (${cayo.length})`);
    else { console.log(`   ✗ «${nombre}» → NO rojeó ${espera}. La vara no mide esa familia.`); malas++; }
  }
  console.log();
  console.log(malas ? `✗ la vara NO está probada: ${malas}/${MUTACIONES.length} impunes`
                    : `✓ la vara cae con las ${MUTACIONES.length} mutaciones — puede dar rojo`);
  process.exit(malas ? 1 : 0);
}

medir(src);
console.log(`— ${OK.length + F.length} aserciones —`);
if (F.length) { console.log(`\n✗ ROJO · ${F.length}:\n`); F.forEach((f) => console.log(`   ✗ ${f}`)); process.exit(1); }
OK.forEach((o) => console.log(`   ✓ ${o}`));
console.log(`\n✓ VERDE · ${OK.length}/${OK.length} — un solo ⚙, overlay, rótulos GENERAL/<espacio> y sin perillas pintadas`);
