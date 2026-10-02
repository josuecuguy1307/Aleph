/* verify_v2_front_auth.mjs — la pantalla de identidad de v2, en un browser real.
 *
 * Verifica los TRES métodos que el launch expone y, sobre todo, que el magic-link NO
 * tenga botón: sigue existiendo en Supabase, pero sin dominio propio el correo no es
 * fiable y un botón que falla es peor que uno que no está (CONTRACT-AUTH-v2 §3).
 *
 *   node qa/verify_v2_front_auth.mjs
 */
import { chromium } from 'playwright';

const FRONT = process.env.V2_FRONT || 'http://127.0.0.1:8162';
let ok = 0, fail = 0;
const check = (l, c, d = '') => { c ? (ok++, console.log(`  ✓ ${l}`)) : (fail++, console.log(`  ✗ ${l}  ${d}`)); };

const browser = await chromium.launch();
const page = await browser.newPage();
const errores = [];
page.on('pageerror', e => errores.push(String(e).slice(0, 120)));

try {
  await page.goto(`${FRONT}/Auth.dc.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1800);

  // ── la capa de identidad cargó ────────────────────────────────────────────
  check('el SDK de Supabase cargó (vendorizado, sin CDN)',
        await page.evaluate(() => !!window.supabase && !!window.supabase.createClient));
  check('supabase-auth.js expone window.alephAuth',
        await page.evaluate(() => !!window.alephAuth));
  check('la config pública está presente',
        await page.evaluate(() => !!(window.ALEPH_SUPABASE || {}).url));
  check('el cliente se puede construir (url + anonKey válidas)',
        await page.evaluate(() => window.alephAuth.disponible() === true));
  check('auth.js sigue vivo (la costura del Bearer no se pisó)',
        await page.evaluate(() => !!window.__alephAuthWrapped));

  // ── los TRES métodos visibles ─────────────────────────────────────────────
  const texto = await page.textContent('body');
  check('hay botón de Google', /Google/i.test(texto));
  check('hay botón de GitHub', /GitHub/i.test(texto));
  // El email+password se RETIRÓ: era la puerta del pre-hijacking (register no verifica
  // el email). Con sólo OAuth —que verifica de su lado— la clase de ataque desaparece.
  check('NO hay campo de email (el vector de pre-hijacking ya no se ofrece)',
        !(await page.$('input[type="email"]')));
  check('NO hay campo de contraseña', !(await page.$('input[type="password"]')));

  // ── y el magic-link NO se ofrece ──────────────────────────────────────────
  check('NO hay botón de magic-link (existe en Supabase, sin botón acá)',
        !/link m[áa]gico|magic link|sin contrase/i.test(texto),
        'aparece una entrada de magic-link que no funcionaría');

  // La captura va ACÁ, ANTES del click: el abort() del OAuth deja la página en un
  // chrome-error, y una captura posterior sale EN BLANCO. Pasó — los asserts daban
  // verde y la evidencia visual no mostraba nada.
  await page.screenshot({ path: 'reports/step5/v2-auth-screen.png' });

  // ── el botón de Google dispara el OAuth de verdad ─────────────────────────
  // No completamos el login (necesita cuenta Google real): verificamos que INTENTA
  // ir al authorize de Supabase con el provider correcto. Un botón que no navega es
  // exactamente el "botón que falla" que queremos evitar.
  // OJO: el abort() produce una navegación a chrome-error. Si el listener de
  // framenavigated escribiera en la MISMA variable, pisaría la URL capturada y el
  // test diría que falló algo que funcionó. Variables separadas a propósito.
  let destino = null;
  await page.route('**/auth/v1/authorize**', route => {
    destino = route.request().url();
    route.abort();
  });
  const botones = await page.$$('button');
  for (const b of botones) {
    const t = (await b.textContent()) || '';
    if (/Google/i.test(t)) { await b.click().catch(() => {}); break; }
  }
  await page.waitForTimeout(2500);
  check('el botón de Google navega al authorize de Supabase',
        !!destino && /\/auth\/v1\/authorize/.test(destino), `destino=${destino}`);
  check('  → con provider=google', !!destino && /provider=google/.test(destino));
  check('  → y con redirect_to propio', !!destino && /redirect_to=/.test(destino));
  if (destino) console.log(`      ${decodeURIComponent(destino).slice(0, 130)}`);

  check('cero errores de JS', errores.length === 0, errores.join(' | '));

} finally {
  await browser.close();
}

console.log(`\n${ok}/${ok + fail} verdes`);
process.exit(fail ? 1 : 0);
