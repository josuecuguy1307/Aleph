/* verify_step5_p10_paywall.mjs — el 402 SE VE. Step 5 · Casa 1 · P10.
 *
 * Llave A (frontend) del muro: hasta ahora los muros negaban bien server-side pero
 * el front no manejaba el 402 — el usuario free recibía un error mudo. Esto verifica
 * en un browser REAL que la card aparece, que dice el copy DEL SERVIDOR (no uno
 * inventado en el front) y que no rompe al llamador.
 *
 *   node qa/verify_step5_p10_paywall.mjs        (requiere stack en :8161/:8155)
 *
 * Corre sobre el Cuarto CANÓNICO (cuarto/cuarto.pixi.html), que es el que redirige
 * /Cuarto.dc.html y donde se golpea el muro de construcción de verdad. Esa pantalla
 * NO carga auth.js (hace su propio Bearer), así que de paso prueba que el paywall
 * funciona SOLO, sin depender de él.
 */
import { chromium } from 'playwright';

const FRONT = process.env.P10_FRONT || 'http://127.0.0.1:8161';
let ok = 0, fail = 0;
const check = (label, cond, detail = '') => {
  if (cond) { ok++; console.log(`  ✓ ${label}`); }
  else { fail++; console.log(`  ✗ ${label}  ${detail}`); }
};

const browser = await chromium.launch();
const page = await browser.newPage();
const errores = [];
page.on('pageerror', e => errores.push(String(e)));

try {
  await page.goto(`${FRONT}/cuarto/cuarto.pixi.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  check('paywall.js cargó', await page.evaluate(() => !!window.__alephPaywall));
  check('funciona SIN auth.js (esta pantalla no lo carga): el interceptor es autónomo',
        await page.evaluate(() => !!window.__alephPaywall && !window.__alephAuthWrapped));

  // ── El caso real: un 402 de un muro de verdad dispara la card ──────────────
  const COPY_SERVIDOR = 'Construir un conector NUEVO';
  const r = await page.evaluate(async () => {
    const resp = await fetch('/v1/inspect/forge', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: 'https://example.com', forma: 'abierto' })
    });
    let body = null;
    try { body = await resp.json(); } catch (e) { /* */ }
    return { status: resp.status, leyoElCuerpo: body !== null };
  });
  check('el muro respondió 402', r.status === 402, `dio ${r.status}`);
  check('EL LLAMADOR PUDO LEER EL CUERPO (el interceptor no se lo tragó)',
        r.leyoElCuerpo, 'el clone() no funcionó: se consumió el stream');

  await page.waitForTimeout(700);
  const card = await page.$('.aleph-paywall');
  check('la card de upsell APARECIÓ (ya no es un error mudo)', !!card);

  if (card) {
    const texto = await page.textContent('.aleph-paywall');
    check('muestra el copy DEL SERVIDOR (no uno inventado en el front)',
          texto.includes(COPY_SERVIDOR),
          `no encontré «${COPY_SERVIDOR}» en: ${texto.slice(0, 160)}`);
    check('ofrece la salida (mejorar el plan)', /Mejorar mi plan|Upgrade/.test(texto));
    check('ofrece salir sin pagar (no es un callejón)', /Ahora no|Not now/.test(texto));
    check('tranquiliza sobre lo ejecutado', /nada se ejecutó|no se perdió|nothing was executed|is safe/i.test(texto));

    await page.screenshot({ path: 'reports/step5/p10-paywall-402.png' });

    // se puede cerrar
    await page.click('.aleph-pw-no');
    await page.waitForTimeout(300);
    check('se cierra con "Ahora no"', !(await page.$('.aleph-paywall')));
  }

  // ── Anti-spam: varios 402 en paralelo no apilan cards ─────────────────────
  await page.evaluate(async () => {
    const uno = () => fetch('/v1/inspect/forge', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: 'https://example.com', forma: 'abierto' })
    }).catch(() => {});
    await Promise.all([uno(), uno(), uno(), uno()]);
  });
  await page.waitForTimeout(900);
  const cuantas = (await page.$$('.aleph-paywall')).length;
  check('4 muros golpeados a la vez → UNA sola card', cuantas <= 1, `hubo ${cuantas}`);

  // ── Un 200 normal NO dispara nada ──────────────────────────────────────────
  await page.evaluate(() => fetch('/health').catch(() => {}));
  await page.waitForTimeout(400);
  const tras200 = (await page.$$('.aleph-paywall')).length;
  check('una respuesta normal no dispara la card', tras200 <= 1);

  check('cero errores de JS en la página', errores.length === 0, errores.join(' | '));

} finally {
  await browser.close();
}

console.log(`\n${ok}/${ok + fail} verdes`);
process.exit(fail ? 1 : 0);
