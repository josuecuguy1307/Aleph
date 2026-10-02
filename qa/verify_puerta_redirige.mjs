/* verify_puerta_redirige.mjs — LA VARA DE LA FASE 5: la puerta del stack redirige.
 *
 *   node qa/verify_puerta_redirige.mjs                 (verde/rojo)
 *   node qa/verify_puerta_redirige.mjs --probar-cayendo
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * QUÉ MIDE
 *
 * Corre los DOS archivos de verdad —el panel de la casa y el redirector de Legal— en un DOM
 * stubbeado. No lee su texto: los ejecuta y mira los mensajes que cruzan.
 *
 *  EL PANEL (product/app/design/workspaces/conectores-del-espacio.js)
 *   1 · expone `abrir()` y `cerrar()` — antes la apertura vivía adentro del click
 *   2 · un mensaje del iframe ABRE el panel con su motivo, y el copy explica el porqué
 *   3 · SEGURIDAD · un mensaje de OTRA ventana se ignora. Cualquiera puede postear acá.
 *   4 · SEGURIDAD · el `ws` que reclama el stack SE IGNORA: manda el que sabe la casa.
 *       Si no, un stack abriría los conectores de otro espacio.
 *   5 · un mensaje con forma equivocada se ignora
 *
 *  LEGAL (third_party/dochaus/apps/web/public/aleph-credencial-redirige.js)
 *   6 · un click sobre un `input[type=password]` NO llega al campo y pide Conectores
 *   7 · el bloqueo es en CAPTURA: gana aunque React tenga su propio handler
 *   8 · el campo queda readOnly y con su copy — se ve puerta, no campo roto
 *   9 · SIN PADRE no hace nada: cerrar sin ofrecer la otra puerta es un callejón sin
 *       salida, y no protege de nadie que corra el árbol suelto
 *
 * Las 3 y la 4 son las que importan de verdad: son las que impiden que este puente se
 * convierta en una vía para que un stack mande sobre la casa.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..');
const PANEL = join(RAIZ, 'product/app/design/workspaces/conectores-del-espacio.js');
const LEGAL = join(RAIZ, 'third_party/dochaus/apps/web/public/aleph-credencial-redirige.js');

const F = [], OK = [];
const chequear = (n, c, d = '') => (c ? OK : F).push(n + (!c && d ? ` — ${d}` : ''));

/* ── un DOM mínimo, honesto en lo que esta vara usa ─────────────────────────────────── */
function hacerDom() {
  const oyentes = { doc: {}, win: {} };
  const nodo = (tag) => {
    const n = {
      tagName: (tag || 'div').toUpperCase(), type: '', hidden: false, children: [], dataset: {},
      style: {}, className: '', textContent: '', value: '', placeholder: '', readOnly: false,
      attrs: {}, _html: '',
      setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
      appendChild(c) { this.children.push(c); c.parentElement = this; return c; },
      insertBefore(c) { this.children.push(c); c.parentElement = this; return c; },
      addEventListener(t, f) { (this._ev ||= {})[t] = f; },
      querySelector() { return null; }, querySelectorAll() { return []; },
      closest() { return null; },
      get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; },
    };
    return n;
  };
  const barra = nodo('div');
  const doc = {
    documentElement: nodo('html'), body: nodo('body'), readyState: 'complete',
    createElement: nodo,
    querySelector: (s) => (s === '.ws-bar' ? barra : null),
    querySelectorAll: () => [],
    getElementById: (id) => doc._byId[id] || null,
    // el TERCER argumento se guarda: sin él, «en captura» no se puede medir y la
    // mutación que pasa a burbuja quedaba impune (lo encontró --probar-cayendo).
    addEventListener: (t, f, capt) => { (oyentes.doc[t] ||= []).push({ f, capt: capt === true }); },
    _byId: {},
  };
  const win = {
    document: doc, location: { search: '', href: 'http://casa/' },
    addEventListener: (t, f, capt) => { (oyentes.win[t] ||= []).push({ f, capt: capt === true }); },
    setTimeout, clearTimeout, Promise, URLSearchParams, MutationObserver: class {
      constructor(cb) { this.cb = cb; } observe() {} disconnect() {}
    },
  };
  win.window = win; win.globalThis = win; win.parent = win;
  return { win, doc, barra, oyentes };
}

const espera = () => new Promise((r) => setImmediate(() => setImmediate(r)));

/* ── el panel ────────────────────────────────────────────────────────────────────────── */
function cargarPanel(src) {
  const { win, doc, oyentes } = hacerDom();
  // el iframe de la casa, con su ventana propia
  const frameWin = { esElIframe: true };
  const frame = { contentWindow: frameWin };
  doc._byId['ws-frame'] = frame;
  // los símbolos que el módulo importa: se stubean para poder EJECUTARLO, no para simularlo
  const cabecera = `
    var pintarFilaReco=function(c,o){return "<li>"+(c.connector||"")+"</li>";};
    var esc=function(s){return String(s==null?"":s);};
    var estadoDe=function(){return {txt:"Listo"};};
    var estado=estadoDe;
    var selloDe=function(){return "";};
    var capacidad=function(x){return x||"";};
    var traerRecomendados=function(){return Promise.resolve({connectors:[{connector:"exa",tiene_llave:false,auth_method:"api_key",workspaces:["legal"]}]});};
    var traerFuentesPorEspacio=function(){return Promise.resolve({legal:[]});};
    var AlephSession={ensureLocal:function(){return Promise.resolve({id:"u1"});}};
  `;
  const cuerpo = src.replace(/^import .*$/gm, '');
  vm.createContext(win);
  new vm.Script(cabecera + cuerpo, { filename: 'panel.js' }).runInContext(win);
  win.AlephConectoresDelEspacio.montar('legal', () => ({ id: 'u1' }));
  return { win, doc, oyentes, frameWin,
           mensaje: (data, source) => (oyentes.win.message || []).forEach((o) => o.f({ data, source })) };
}

async function medirPanel(src) {
  const M = cargarPanel(src);
  const API = M.win.AlephConectoresDelEspacio;
  chequear('1 · el panel expone abrir()', typeof API.abrir === 'function');
  chequear('1 · y cerrar()', typeof API.cerrar === 'function');

  const panel = M.doc.body.children.find((c) => c.className === 'ws-conect-panel');
  chequear('1 · el panel nace cerrado', panel && panel.hidden === true);

  // 3 · SEGURIDAD: otra ventana
  M.mensaje({ aleph: 'conectores' }, { esOtraVentana: true });
  await espera();
  chequear('3 · un mensaje de OTRA ventana se ignora', panel.hidden === true,
           'el panel se abrió con un mensaje ajeno');

  // 5 · forma equivocada, desde el iframe legítimo
  M.mensaje({ aleph: 'otra-cosa' }, M.frameWin);
  M.mensaje(null, M.frameWin);
  await espera();
  chequear('5 · un mensaje con forma equivocada se ignora', panel.hidden === true);

  // 2 · el mensaje bueno
  M.mensaje({ aleph: 'conectores' }, M.frameWin);
  await espera();
  chequear('2 · el mensaje del iframe ABRE el panel', panel.hidden === false);
  chequear('2 · y el panel dice POR QUÉ se abrió',
           /ws-conect-motivo/.test(panel.innerHTML), panel.innerHTML.slice(0, 80));
  chequear('2 · el copy nombra el vault de la casa',
           /se guardan <strong>acá<\/strong>/.test(panel.innerHTML));

  // 4 · SEGURIDAD: el ws reclamado por el stack no manda.
  // ⚠️ PANEL NUEVO A PROPÓSITO. Reusar el de arriba no medía nada: `abrir()` no repinta si
  // el motivo no cambió —y ya era "credencial"—, así que el `innerHTML` seguía siendo el
  // viejo y la aserción pasaba sola. Lo encontró `--probar-cayendo`.
  const M2 = cargarPanel(src);
  M2.mensaje({ aleph: 'conectores', ws: 'finanzas' }, M2.frameWin);
  await espera();
  const panel2 = M2.doc.body.children.find((c) => c.className === 'ws-conect-panel');
  chequear('4 · el ws que reclama el stack se IGNORA',
           /LEGAL/.test(panel2.innerHTML) && !/FINANZAS/.test(panel2.innerHTML),
           'el panel obedeció el ws del mensaje');
}

/* ── Legal ───────────────────────────────────────────────────────────────────────────── */
function correrLegal(src, { conPadre = true } = {}) {
  const { win, doc, oyentes } = hacerDom();
  const posteados = [];
  if (conPadre) win.parent = { postMessage: (m) => posteados.push(m) };
  const campo = doc.createElement('input');
  campo.type = 'password';
  const label = doc.createElement('label');
  label.appendChild(campo);
  doc.querySelectorAll = (s) => (s === 'input[type="password"]' ? [campo] : []);
  vm.createContext(win);
  new vm.Script(src, { filename: 'legal.js' }).runInContext(win);
  return { win, doc, oyentes, posteados, campo, label };
}

function medirLegal(src) {
  const L = correrLegal(src);
  const handlers = L.oyentes.doc;
  chequear('7 · hay handler de pointerdown', !!handlers.pointerdown);
  chequear('7 · y también en focusin y keydown', !!handlers.focusin && !!handlers.keydown);
  // LO QUE DE VERDAD PROTEGE: que corra ANTES que el de React. Un handler en burbuja llega
  // tarde — el campo ya recibió el evento.
  chequear('7 · y TODOS están en CAPTURA',
           ['pointerdown', 'mousedown', 'focusin', 'keydown']
             .every((t) => (handlers[t] || []).length && handlers[t].every((o) => o.capt === true)),
           JSON.stringify(Object.fromEntries(Object.entries(handlers).map(([k, v]) => [k, v.map((o) => o.capt)]))));

  let prevenido = false, propagado = true;
  const ev = { target: L.campo, preventDefault: () => { prevenido = true; },
               stopPropagation: () => { propagado = false; } };
  (handlers.pointerdown || []).forEach((o) => o.f(ev));
  chequear('6 · el click NO llega al campo', prevenido, 'no se llamó preventDefault');
  chequear('6 · y no sigue propagando', !propagado);
  chequear('6 · y pide Conectores a la casa',
           L.posteados.length === 1 && L.posteados[0].aleph === 'conectores',
           JSON.stringify(L.posteados));
  chequear('4 · Legal NO manda su ws (que la casa lo ignore no es excusa)',
           L.posteados[0] && L.posteados[0].ws === undefined, JSON.stringify(L.posteados[0]));

  chequear('8 · el campo queda readOnly', L.campo.readOnly === true);
  chequear('8 · con copy que explica dónde va', /Aleph/.test(L.campo.placeholder), L.campo.placeholder);
  chequear('8 · y se agrega la puerta visible',
           L.label.children.some((c) => c.className === 'aleph-credencial-cta'));

  // 9 · sin padre
  const S = correrLegal(src, { conPadre: false });
  chequear('9 · sin padre no toca nada', S.campo.readOnly === false && !S.oyentes.doc.pointerdown,
           'neutralizó el campo sin tener a dónde redirigir');
}

const srcPanel = readFileSync(PANEL, 'utf8');
const srcLegal = readFileSync(LEGAL, 'utf8');

const MUTACIONES = [
  ['el panel confía en cualquier ventana', PANEL, 'ev.source !== frame.contentWindow', 'false', '3 ·'],
  ['el panel obedece el ws del stack',     PANEL, "abrir(\"credencial\")", 'abrir("credencial"), (ws = d.ws || ws)', '4 ·'],
  ['el copy del porqué se va',             PANEL, 'motivo === "credencial"', 'false', '2 ·'],
  ['Legal deja de prevenir',               LEGAL, 'ev.preventDefault();', ';', '6 ·'],
  ['Legal escucha en burbuja, no captura', LEGAL, '}, true);   // ←', '}, false); // ←', '7 ·'],
];

if (process.argv.includes('--probar-cayendo')) {
  console.log('— probando la vara cayendo: 5 mutaciones —\n');
  let malas = 0;
  for (const [nombre, archivo, viejo, nuevo, espera_] of MUTACIONES) {
    const base = archivo === PANEL ? srcPanel : srcLegal;
    if (!base.includes(viejo)) { console.log(`   ⚠ «${nombre}»: el ancla ya no existe`); malas++; continue; }
    F.length = 0; OK.length = 0;
    const mut = base.replace(viejo, nuevo);
    try {
      if (archivo === PANEL) await medirPanel(mut); else medirLegal(mut);
    } catch (e) { F.push(`${espera_} la mutación reventó: ${e.message}`); }
    const cayo = F.filter((f) => f.startsWith(espera_));
    if (cayo.length) console.log(`   ✓ «${nombre}» → rojea ${espera_} (${cayo.length})`);
    else { console.log(`   ✗ «${nombre}» → NO rojeó ${espera_}. La vara no mide esa familia.`); malas++; }
  }
  console.log();
  console.log(malas ? `✗ la vara NO está probada: ${malas}/${MUTACIONES.length} impunes`
                    : `✓ la vara cae con las ${MUTACIONES.length} mutaciones — puede dar rojo`);
  process.exit(malas ? 1 : 0);
}

await medirPanel(srcPanel);
medirLegal(srcLegal);
console.log(`— ${OK.length + F.length} aserciones —`);
if (F.length) { console.log(`\n✗ ROJO · ${F.length}:\n`); F.forEach((f) => console.log(`   ✗ ${f}`)); process.exit(1); }
OK.forEach((o) => console.log(`   ✓ ${o}`));
console.log(`\n✓ VERDE · ${OK.length}/${OK.length} — la puerta del stack lleva al vault de la casa`);
