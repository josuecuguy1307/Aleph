#!/usr/bin/env node
/**
 * verify_acct_toast_6b.mjs — TICKET 6b · toast in-run de PROPUESTA DE CUENTA en La Sala.
 *
 * El run ya devuelve out.account_proposed={id,content} cuando el agente aprendió un hecho
 * sobre el usuario (backend lo dejó INERTE). El front debe:
 *   · pintar un toast "Aprendí algo sobre vos" con el contenido (esc + scrub de secretos)
 *   · Guardar → POST /v1/account/proposals/{id}/confirm con Bearer
 *   · Descartar → DELETE /v1/account/proposals/{id} con Bearer
 *   · NO montarse si account_proposed es null (cap lleno / recortado)
 *   · 0 errores JS
 *
 * Self-contained (patrón verify_ux_b4_front): server local sirve el design + stubea /v1.
 * Corre: node product/app/design/sala/verify_acct_toast_6b.mjs
 */
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { chromium } from 'playwright';

const DESIGN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml' };

let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = '') {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? ' — ' + detail : ''}`); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// el hecho propuesto por el agente lleva un secreto ecoado (el modelo lo produjo) → debe scrubbearse.
const SECRET = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc';
const PROP_CONTENT = 'Trabaja en finanzas y prefiere reportes cortos (su token era ' + SECRET + ').';
const PROP_ID = 'prop-6b-001';

function serve() {
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, 'http://x');
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, '127.0.0.1', () => res(srv)));
}

async function runCase(page, { proposed, authHeaderSeen }) {
  const calls = { confirm: [], del: [] };
  await page.route('**/v1/account/proposals/*/confirm', (r) => {
    calls.confirm.push({ url: r.request().url(), auth: r.request().headers()['authorization'] || null });
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
  await page.route('**/v1/account/proposals/*', (r) => {
    if (r.request().method() === 'DELETE') {
      calls.del.push({ url: r.request().url(), auth: r.request().headers()['authorization'] || null });
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    }
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 0, proposals: [] }) });
  });
  await page.route('**/v1/puppets/run', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, answer: 'Listo, armé lo que pediste.', run_id: 'r-6b',
      account_proposed: proposed,
      outputs_captured: [], held_actions: [],
      record: { tool_calls: [], gate_decisions: [], model_final: 'claude-code-opus-4.8', degraded: null } }) }));
  return calls;
}

(async () => {
  const srv = await serve();
  const BASE = `http://127.0.0.1:${srv.address().port}`;
  console.log(`verify_acct_toast_6b · ${BASE}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => {
    sessionStorage.setItem('puppet_user', JSON.stringify({ id: 'u-fx', email: 'fx@x', session_token: 'tok-6b' }));
  });
  const page = await ctx.newPage();
  const jsErrors = [];
  page.on('pageerror', (e) => jsErrors.push(String(e)));

  const j = (r, obj) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
  await page.route('**/v1/classify-turn', (r) => j(r, { turn: 'build' }));
  await page.route('**/v1/artifacts/classify-action', (r) => j(r, { action: 'new' }));
  await page.route('**/v1/chats*', (r) => r.request().method() === 'POST' ? j(r, { id: 'chat-fx', title: '' }) : j(r, { total: 0, chats: [] }));
  await page.route('**/v1/chats/**', (r) => j(r, { id: 'chat-fx', messages: [] }));
  await page.route('**/v1/belts/cards*', (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route('**/v1/users/**', (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route('**/v1/sessions/**', (r) => j(r, { artifacts: [] }));
  await page.route('**/v1/spaces/*/stream', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.route('**/v1/obra-caption', (r) => j(r, {}));

  // ── CASO A · Guardar ──
  let calls = await runCase(page, { proposed: { id: PROP_ID, content: PROP_CONTENT } });
  await page.goto(BASE + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(400);
  await page.fill('#composer', 'arma un resumen de mis finanzas');
  await page.click('#send');
  await page.waitForSelector('#chat .acct', { timeout: 12000 });
  await sleep(300);
  let toast = await page.evaluate(() => (document.querySelector('#chat .acct') || {}).textContent || '');
  check('A.1 el toast aparece con el título de aprendizaje', /Aprend/.test(toast));
  check('A.2 muestra el contenido propuesto', /finanzas/.test(toast) && /reportes cortos/.test(toast));
  check('A.3 el secreto ecoado queda SCRUBBEADO (nunca en claro)',
    !toast.includes('sk_live_4eC39') && !toast.includes(SECRET), toast.slice(0, 160));
  check('A.4 dos botones Guardar/Descartar', /Guardar/.test(toast) && /Descartar/.test(toast));
  await page.click('#chat .acct .acts .ok');
  await sleep(500);
  check('A.5 Guardar → POST /confirm con Bearer',
    calls.confirm.length === 1 && calls.confirm[0].url.includes('/v1/account/proposals/' + PROP_ID + '/confirm')
    && calls.confirm[0].auth === 'Bearer tok-6b', JSON.stringify(calls.confirm));
  check('A.6 tras guardar, el toast confirma "Guardado"',
    /Guardado/.test(await page.evaluate(() => (document.querySelector('#chat .acct') || {}).textContent || '')));
  check('A.7 NO se llamó DELETE al guardar', calls.del.length === 0);

  // ── CASO B · Descartar (run nuevo, otra propuesta) ──
  await page.unroute('**/v1/puppets/run');
  await page.unroute('**/v1/account/proposals/*/confirm');
  await page.unroute('**/v1/account/proposals/*');
  const PROP_ID2 = 'prop-6b-002';
  calls = await runCase(page, { proposed: { id: PROP_ID2, content: 'Vive en Quito.' } });
  await page.fill('#composer', 'otra tarea cualquiera');
  await page.click('#send');
  await page.waitForFunction((oldTxt) => {
    const els = [...document.querySelectorAll('#chat .acct')];
    return els.some((e) => /Quito/.test(e.textContent));
  }, PROP_CONTENT, { timeout: 12000 });
  await sleep(200);
  const secondToast = await page.evaluateHandle(() =>
    [...document.querySelectorAll('#chat .acct')].reverse().find((e) => /Quito/.test(e.textContent)));
  await secondToast.asElement().$('.acts .no').then((b) => b.click());
  await sleep(500);
  check('B.1 Descartar → DELETE /proposals/{id} con Bearer',
    calls.del.length === 1 && calls.del[0].url.endsWith('/v1/account/proposals/' + PROP_ID2)
    && calls.del[0].auth === 'Bearer tok-6b', JSON.stringify(calls.del));
  check('B.2 NO se llamó confirm al descartar', calls.confirm.length === 0);

  // ── CASO C · account_proposed null → sin toast ──
  await page.unroute('**/v1/puppets/run');
  await page.unroute('**/v1/account/proposals/*/confirm');
  await page.unroute('**/v1/account/proposals/*');
  const before = await page.evaluate(() => document.querySelectorAll('#chat .acct').length);
  await runCase(page, { proposed: null });
  await page.fill('#composer', 'una tarea sin aprendizaje');
  await page.click('#send');
  await sleep(1500);
  const after = await page.evaluate(() => document.querySelectorAll('#chat .acct').length);
  check('C.1 account_proposed=null → NO monta toast nuevo', after === before, `before=${before} after=${after}`);

  // ── CASO E · review F9 · confirm devuelve 404 (ya resuelta en el panel) → estado NEUTRAL, no "Guardado" ──
  await page.unroute('**/v1/puppets/run');
  await page.unroute('**/v1/account/proposals/*/confirm');
  await page.unroute('**/v1/account/proposals/*');
  const PROP_ID3 = 'prop-6b-003';
  const calls404 = { confirm: [] };
  await page.route('**/v1/account/proposals/*/confirm', (r) => {
    calls404.confirm.push(r.request().url());
    return r.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'not found' }) });
  });
  await page.route('**/v1/account/proposals/*', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 0, proposals: [] }) }));
  await page.route('**/v1/puppets/run', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, answer: 'ok', run_id: 'r-6b-e', account_proposed: { id: PROP_ID3, content: 'Le gusta el mate.' },
      outputs_captured: [], held_actions: [], record: { tool_calls: [], gate_decisions: [], model_final: 'x', degraded: null } }) }));
  await page.fill('#composer', 'tarea que aprende algo ya resuelto en el panel');
  await page.click('#send');
  await page.waitForFunction(() => [...document.querySelectorAll('#chat .acct')].some((e) => /mate/.test(e.textContent)), null, { timeout: 12000 });
  await sleep(200);
  const thirdToast = await page.evaluateHandle(() => [...document.querySelectorAll('#chat .acct')].reverse().find((e) => /mate/.test(e.textContent)));
  await thirdToast.asElement().$('.acts .ok').then((b) => b.click());
  await sleep(500);
  const txt404 = await thirdToast.asElement().evaluate((e) => e.textContent);
  check('E.1 confirm 404 → NO afirma "Guardado" (estado de privacidad falso)', !/Guardado/.test(txt404), txt404.slice(0, 120));
  check('E.2 confirm 404 → muestra "Ya resuelta" neutral', /Ya resuelta|resolviste/.test(txt404), txt404.slice(0, 120));
  check('E.3 el confirm 404 SÍ se intentó (una vez)', calls404.confirm.length === 1, String(calls404.confirm.length));

  check('D.1 cero errores JS en toda la corrida', jsErrors.length === 0, jsErrors.join(' | '));

  await browser.close(); srv.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
