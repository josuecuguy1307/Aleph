/* verify_prefs_siguen_a_la_cuenta.mjs — LA VARA DE LA FASE 1b.
 * [Convergencia · superficie 3 · fase 1b]
 *
 *   node qa/verify_prefs_siguen_a_la_cuenta.mjs
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * QUÉ MIDE Y CÓMO
 *
 * Corre `theme.js` DE VERDAD —el archivo del árbol, sin copiar ni reescribir su lógica—
 * dentro de un DOM mínimo stubbeado. No mira el texto del archivo: mira lo que el archivo
 * HACE. Un grep habría dicho «sí, dice keepalive» sin enterarse de si el PUT sale.
 *
 *   1 · SIN FLASH             `data-theme` queda puesto ANTES de que ninguna promesa
 *                             corra. Es la garantía que esta fase NO podía romper.
 *   2 · WRITE-THROUGH         `set('light')` manda un PUT con `{cambios:{tema:'light'}}`.
 *   3 · KEEPALIVE             ese PUT lleva `keepalive:true`. Sin eso el idioma se pierde
 *                             al recargar, y sólo se nota cambiando de máquina.
 *   4 · ADOPTAR NO ES ELEGIR  lo que llega del servidor se aplica y NO rebota como PUT.
 *                             Sin el guard, cada arranque escribiría lo que acaba de leer.
 *   5 · EL 401 NO PISA NADA   sin sesión la caché local sobrevive; un ajuste que no se
 *                             pudo traer no se reemplaza por el default.
 *   6 · SIN RED TAMPOCO       un fetch que revienta no tumba la pantalla ni borra el tema.
 *
 * PROBADA CAYENDO: `--probar-cayendo` aplica cuatro mutaciones al FUENTE en memoria y
 * verifica que cada una rojee la aserción que le toca. Sin eso no sabría si mide.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..');
const FUENTE = join(RAIZ, 'product/app/design/theme.js');

function correr(src, { respuesta = { ajustes: { tema: 'dark', idioma: 'es' } }, ok = true,
                       revienta = false, cache = 'dark' } = {}) {
  const puts = [], gets = [], html = { attrs: {} };
  const store = { 'aleph-theme': cache };
  const pendientes = [];
  const ctx = {
    localStorage: { getItem: k => (k in store ? store[k] : null),
                    setItem: (k, v) => { store[k] = v; } },
    matchMedia: () => ({ matches: true, addEventListener() {}, addListener() {} }),
    document: {
      readyState: 'complete',
      documentElement: { setAttribute: (k, v) => { html.attrs[k] = v; } },
      body: null,
      addEventListener() {}, createElement: () => ({ setAttribute() {}, style: {} }),
      getElementById: () => null,
    },
    CustomEvent: class { constructor(n, o) { this.type = n; Object.assign(this, o); } },
    fetch: (url, opt = {}) => {
      const m = (opt.method || 'GET').toUpperCase();
      (m === 'PUT' ? puts : gets).push({ url, opt });
      if (revienta) { const p = Promise.reject(new Error('sin red')); pendientes.push(p.catch(() => {})); return p; }
      const p = Promise.resolve({ ok, json: () => Promise.resolve(respuesta) });
      pendientes.push(p); return p;
    },
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  ctx.window.addEventListener = () => {};
  ctx.window.dispatchEvent = () => true;
  vm.createContext(ctx);
  const antesDeAwait = { ...html.attrs };            // foto ANTES de que corra una promesa
  new vm.Script(src, { filename: 'theme.js' }).runInContext(ctx);
  const trasCarga = { ...html.attrs };
  return { ctx, puts, gets, html, store, antesDeAwait, trasCarga,
           asentar: async () => { await Promise.allSettled(pendientes); await new Promise(r => setImmediate(r)); } };
}

const F = [], OK = [];
const chequear = (n, c, d = '') => (c ? OK : F).push(n + (!c && d ? ` — ${d}` : ''));

async function medir(src) {
  // 1 · sin flash: el atributo está puesto apenas termina de correr el script, sincrónico
  {
    const r = correr(src, { cache: 'light' });
    chequear('1 · data-theme puesto sincrónicamente', r.trasCarga['data-theme'] === 'light',
             JSON.stringify(r.trasCarga));
    chequear('1 · y sale de la CACHÉ local, no del servidor',
             r.trasCarga['data-theme-mode'] === 'light');
  }
  // 2 y 3 · write-through con keepalive
  {
    const r = correr(src);
    await r.asentar();
    const antes = r.puts.length;
    r.ctx.window.AlephTheme.set('light');
    const nuevos = r.puts.slice(antes);
    chequear('2 · set() manda UN PUT', nuevos.length === 1, `mandó ${nuevos.length}`);
    const cuerpo = nuevos[0] ? JSON.parse(nuevos[0].opt.body) : {};
    chequear('2 · con el ajuste correcto', cuerpo?.cambios?.tema === 'light',
             JSON.stringify(cuerpo));
    chequear('3 · y con keepalive', nuevos[0]?.opt?.keepalive === true,
             JSON.stringify(nuevos[0]?.opt?.keepalive));
    chequear('2 · y la caché local quedó igual', r.store['aleph-theme'] === 'light');
  }
  // 4 · adoptar no rebota
  {
    const r = correr(src, { cache: 'dark', respuesta: { ajustes: { tema: 'light', idioma: 'es' } } });
    await r.asentar();
    chequear('4 · lo del servidor se APLICA', r.html.attrs['data-theme-mode'] === 'light',
             JSON.stringify(r.html.attrs));
    chequear('4 · y NO rebota como PUT', r.puts.length === 0, `salieron ${r.puts.length} PUT`);
  }
  // 5 · el 401 no pisa
  {
    const r = correr(src, { cache: 'light', ok: false });
    await r.asentar();
    chequear('5 · sin sesión la caché sobrevive', r.store['aleph-theme'] === 'light',
             r.store['aleph-theme']);
    chequear('5 · y el tema aplicado no se movió', r.html.attrs['data-theme-mode'] === 'light');
  }
  // 6 · sin red
  {
    const r = correr(src, { cache: 'light', revienta: true });
    await r.asentar();
    chequear('6 · un fetch roto no borra el tema', r.html.attrs['data-theme-mode'] === 'light');
  }
}

const MUTACIONES = [
  ['el sincronizador pisa antes del paint', "applyDom(); // síncrono", "// applyDom();", '1 ·'],
  ['el write-through se cae',               "guardar('tema', m);", "/*guardar*/", '2 ·'],
  ['keepalive se va',                       "keepalive: true,", "",               '3 ·'],
  ['el guard de adopción se va',            "if (adoptando) return;", "if (false) return;", '4 ·'],
];

const src = readFileSync(FUENTE, 'utf8');
if (process.argv.includes('--probar-cayendo')) {
  console.log('— probando la vara cayendo: 4 mutaciones —\n');
  let malas = 0;
  for (const [nombre, viejo, nuevo, espera] of MUTACIONES) {
    if (!src.includes(viejo)) { console.log(`   ⚠ «${nombre}»: el ancla ya no existe`); malas++; continue; }
    F.length = 0; OK.length = 0;
    try { await medir(src.replace(viejo, nuevo)); }
    catch (e) { F.push(`${espera} la mutación reventó: ${e.message}`); }
    const cayo = F.filter(f => f.startsWith(espera));
    if (cayo.length) console.log(`   ✓ «${nombre}» → rojea ${espera} (${cayo.length})`);
    else { console.log(`   ✗ «${nombre}» → NO rojeó ${espera}. La vara no mide esa familia.`); malas++; }
  }
  console.log();
  console.log(malas ? `✗ la vara NO está probada: ${malas}/${MUTACIONES.length} impunes`
                    : `✓ la vara cae con las ${MUTACIONES.length} mutaciones — puede dar rojo`);
  process.exit(malas ? 1 : 0);
}

await medir(src);
console.log(`— ${OK.length + F.length} aserciones —`);
if (F.length) { console.log(`\n✗ ROJO · ${F.length}:\n`); F.forEach(f => console.log(`   ✗ ${f}`)); process.exit(1); }
OK.forEach(o => console.log(`   ✓ ${o}`));
console.log(`\n✓ VERDE · ${OK.length}/${OK.length} — el ajuste sigue a la cuenta, y el arranque no parpadea`);
