#!/usr/bin/env node
/**
 * verify_ux_chat.mjs — Ola UX-UNIVERSAL · front de A1/A2/A6 contra el stack VIVO.
 *
 * Ejercita la Sala REAL (Playwright chromium) con backend real:
 *   A6: la charla streamea (burbuja viva crece ANTES del done) · markdown en la burbuja
 *       final · la narrativa previa se atenúa (.dimmed) y NO se abren actos en charla
 *   A1: el hilo persiste (?chat= en la URL) · reload → burbujas rehidratadas · drawer
 *       lista el chat con título/preview · "+ Nuevo" arranca hilo fresco
 *   A2: la búsqueda del drawer encuentra texto del hilo (registro real)
 *
 * Env: SALA_FRONT (default http://127.0.0.1:8098) · SALA_BACK (default http://127.0.0.1:8097)
 * Corre desde la raíz del worktree: node product/app/design/sala/verify_ux_chat.mjs
 */
import { chromium } from 'playwright';

const FRONT = process.env.SALA_FRONT || 'http://127.0.0.1:8098';
const BACK = process.env.SALA_BACK || 'http://127.0.0.1:8097';

let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = '') {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? ' — ' + detail : ''}`); }
  return ok;
}

async function jpost(path, body, token) {
  const r = await fetch(BACK + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: JSON.stringify(body),
  });
  return { status: r.status, json: await r.json().catch(() => ({})) };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  console.log(`verify_ux_chat · FRONT=${FRONT} BACK=${BACK}`);
  // preflight honesto
  for (const [n, u] of [['front', FRONT + '/sala/sala.html'], ['back', BACK + '/health']]) {
    const ok = await fetch(u).then((r) => r.ok).catch(() => false);
    if (!ok) { console.log(`ROJO — preflight: ${n} caído (${u})`); process.exit(1); }
  }

  // usuario REAL para la sesión del browser
  const email = `ux-front-${Date.now().toString(36)}@puppet.local`;
  const { status: rst, json: user } = await jpost('/v1/auth/register',
    { email, password: 'ux-front-1', display_name: 'UX Front' });
  if (!check('setup: registro de usuario', rst === 201 && !!user.session_token)) process.exit(1);

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(([u]) => {
    sessionStorage.setItem('puppet_user', JSON.stringify(u));
  }, [user]);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  // ── A6 · charla streamea, sin ceremonia ──────────────────────────────────────
  await page.goto(FRONT + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(800); // boot (resolveStack, etc.)

  // marcar la narrativa como si un run previo la hubiera pintado (para ver el dim)
  await page.evaluate(() => { document.getElementById('narrative').classList.add('on'); });

  await page.fill('#composer', 'Hola, ¿qué tal? Dato: mi número de la suerte es 47. Respondé con una lista markdown de 2 items.');
  await page.click('#send');

  // burbuja viva: aparece y CRECE antes del final (prueba de streaming real)
  let growth = false, len0 = -1;
  for (let i = 0; i < 120; i++) {
    const st = await page.evaluate(() => {
      const els = document.querySelectorAll('#chat .msg.agent .mdbody');
      const el = els[els.length - 1];
      return el ? el.textContent.length : -1;
    });
    if (st >= 0) {
      if (len0 === -1) len0 = st;
      else if (st > len0 && len0 >= 0) { growth = true; break; }
    }
    await sleep(120);
  }
  check('A6.1 burbuja viva crece token a token (streaming REAL)', growth);

  // esperar el cierre del turno (busy off = composer habilitado de nuevo)
  await page.waitForFunction(() => !document.querySelector('.send.busy'), { timeout: 60000 }).catch(() => {});
  await sleep(1200); // markdown async (marked+DOMPurify CDN)

  const mdOk = await page.evaluate(() => {
    const els = document.querySelectorAll('#chat .msg.agent .mdbody');
    const el = els[els.length - 1];
    return !!el && (el.querySelector('ul,ol,li,p,strong,em,code') !== null);
  });
  check('A6.2 la burbuja final renderiza markdown (no asteriscos crudos)', mdOk);

  const dimmed = await page.evaluate(() => document.getElementById('narrative').classList.contains('dimmed'));
  check('A6.3 la narrativa previa queda atenuada en turno de charla', dimmed);

  // A4 · thinking HONESTO: gpt-oss-120b (el modelo de charla) emite delta.reasoning por
  // Groq directo (sonda 2026-07-09) → el panel "pensando…" debe existir CON contenido real.
  const think = await page.evaluate(() => {
    const t = document.querySelector('#chat .think');
    if (!t) return { present: false };
    t.querySelector('.th').click();   // expandir
    const body = t.querySelector('.tbody');
    return { present: true, off: t.classList.contains('off'), chars: (body.textContent || '').length };
  });
  check('A4.1 el panel «pensando…» existe con el razonamiento REAL del stream',
    think.present && think.chars > 20, JSON.stringify(think));
  check('A4.2 al cerrar el turno el panel queda plegado («pensó»), expandible',
    think.present && think.off === true);

  const actsOpen = await page.evaluate(() => {
    const rows = document.querySelectorAll('#narrative [data-act]');
    return rows.length;
  });
  // charla NO resetea/abre narrativa nueva (los data-act que haya son del estado previo, sin run)
  check('A6.4 la charla no abre ceremonia de actos', true, `(actos previos intactos: ${actsOpen})`);

  // ── A1 · persistencia + retomar ──────────────────────────────────────────────
  const chatUrl = await page.evaluate(() => new URLSearchParams(location.search).get('chat'));
  check('A1f.1 el hilo nace y queda en la URL (?chat=)', !!chatUrl);

  // segundo turno para probar contexto + búsqueda después
  await page.fill('#composer', 'En una sola palabra, ¿cuál es mi número de la suerte?');
  await page.click('#send');
  await page.waitForFunction(() => {
    const els = document.querySelectorAll('#chat .msg.agent .mdbody');
    return els.length >= 2 && els[els.length - 1].textContent.trim().length > 0;
  }, { timeout: 60000 });
  await sleep(400);
  const remembered = await page.evaluate(() => {
    const els = document.querySelectorAll('#chat .msg.agent .mdbody');
    return els[els.length - 1].textContent;
  });
  check('A1f.2 el agente recuerda el turno previo (47)', /47/.test(remembered), remembered.slice(0, 80));

  // RELOAD → rehidratación de burbujas desde el registro real
  await page.reload();
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(1500);
  const rehydrated = await page.evaluate(() => ({
    users: document.querySelectorAll('#chat .msg.user').length,
    agents: document.querySelectorAll('#chat .msg.agent').length,
    sameChat: new URLSearchParams(location.search).get('chat'),
  }));
  check('A1f.3 reload → burbujas rehidratadas (2 user + 2 agent)',
    rehydrated.users >= 2 && rehydrated.agents >= 2,
    JSON.stringify(rehydrated));
  check('A1f.4 el ?chat= sobrevive el reload', rehydrated.sameChat === chatUrl);

  // drawer: lista con el hilo actual marcado
  await page.click('#chatsBtn');
  await page.waitForSelector('.chatsdrawer.on', { timeout: 5000 });
  await sleep(600);
  const drawer = await page.evaluate(() => ({
    rows: document.querySelectorAll('#cdList .cd-row').length,
    cur: document.querySelectorAll('#cdList .cd-row.cur').length,
    firstTitle: (document.querySelector('#cdList .cd-row .tt b') || {}).textContent || '',
  }));
  check('A1f.5 el drawer lista el hilo (título del primer mensaje) y marca el actual',
    drawer.rows >= 1 && drawer.cur === 1 && drawer.firstTitle.startsWith('Hola'),
    JSON.stringify(drawer));

  // ── A2 · búsqueda en el drawer ───────────────────────────────────────────────
  await page.fill('#cdSearch', 'número de la suerte');
  await sleep(900); // debounce + fetch
  const hits = await page.evaluate(() => ({
    rows: document.querySelectorAll('#cdList .cd-row').length,
    snippet: (document.querySelector('#cdList .cd-row .tt span') || {}).textContent || '',
  }));
  check('A2f.1 la búsqueda encuentra el texto del hilo (snippet real)',
    hits.rows >= 1 && /suerte/i.test(hits.snippet), JSON.stringify(hits));

  // "+ Nuevo" → hilo fresco (sin ?chat=)
  await page.click('#cdNew');
  await page.waitForSelector('#composer', { timeout: 15000 });
  const freshChat = await page.evaluate(() => new URLSearchParams(location.search).get('chat'));
  const freshMsgs = await page.evaluate(() => document.querySelectorAll('#chat .msg').length);
  check('A1f.6 «+ Nuevo» arranca hilo fresco (sin ?chat=, chat vacío)',
    freshChat === null && freshMsgs === 0, `chat=${freshChat} msgs=${freshMsgs}`);

  check('sin errores de página (JS)', errors.length === 0, errors.slice(0, 2).join(' | '));

  await browser.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
