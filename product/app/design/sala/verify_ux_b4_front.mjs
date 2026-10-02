#!/usr/bin/env node
/**
 * verify_ux_b4_front.mjs — B4 · la card del gate explica «voy a hacer X porque Y, tocando Z».
 *
 * Espinazo SSE guionado (patrón 4a): gate_waiting llega con turn_text (la intención REAL
 * del turno), args (el efecto) y gate_ux (clase/nivel/perilla). La card debe:
 *   · pintar «Por qué:» desde turn_text (dato real; sin dato → sin línea)
 *   · pintar «Tocando:» desde los args reales — con secretos SCRUBBEADOS (‹oculto›)
 *   · mostrar los chips clase/nivel/perilla que ya viajaban sin pintarse
 *   · aprobar → POST /v1/runs/{id}/approve REAL con approval_id
 *
 * Corre: node product/app/design/sala/verify_ux_b4_front.mjs (autocontenido)
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
const frame = (id, type, payload) =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(Object.assign({ type }, payload))}\n\n`;

// [H6] el turn_text lleva un JWT ecoado — el front debe scrubbearlo al pintar «Por qué:»
const JWT = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
const TURN_TEXT = 'Voy a crear la planilla trimestral con los totales que calculamos, para que la descargues (uso la sesión ' + JWT + ').';
const SECRET = 'sk_test_51JmuyCLkdIwHu7ix0123456789abcdef';
// [H5] la vista_previa incrusta contenido crudo de los args server-side (body del mensaje):
// acá un Stripe live-key, que la card DEBE tapar en «Detalle:» igual que en «Tocando:».
const PREVIEW_SECRET = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc';
const GATE_UX = {
  que_va_a_hacer: 'guardar un archivo nuevo en tu espacio', donde_afecta: 'tu carpeta de resultados',
  vista_previa: 'Le va a mandar a «contador@x.com»:\n\nAdjunto la API key ' + PREVIEW_SECRET + ' para el cierre.',
  requiere_ok: true, boton_ok: 'OK, hacelo',
  boton_cancelar: 'No, cancelá', nivel: 'confirma-siempre', leyenda: 'esta acción escribe',
  accion_clase: 'write-world', autonomia: 'balanceado',
};

function spine(res) {
  res.write(frame(1, 'gate_waiting', {
    kind: 'tool_call', tool: 'datatools', tool_raw: 'write_xlsx',
    args: { path: 'trimestre.xlsx', api_key: SECRET, rows: [[1, 2, 3]] },
    gate_action: 'needs_ok', turn: 1, gate_ux: GATE_UX, turn_text: TURN_TEXT,
  }));
  setTimeout(() => {
    res.write(frame(2, 'closed', {
      ok: true, run_id: 'r-b4', model_final: 'claude-code-opus-4.8', degraded: null,
      held_actions: [{ approval_id: 'ap-b4', server: 'datatools', tool: 'write_xlsx',
                       level: 'confirma-siempre', action_class: 'write-world', ux: GATE_UX }],
    }));
    res.end();
  }, 900);
}

function serve() {
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, 'http://x');
    if (/\/v1\/spaces\/[^/]+\/stream$/.test(u.pathname)) {
      r.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' });
      spine(r); return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, '127.0.0.1', () => res(srv)));
}

(async () => {
  const srv = await serve();
  const BASE = `http://127.0.0.1:${srv.address().port}`;
  console.log(`verify_ux_b4_front · ${BASE}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => {
    sessionStorage.setItem('puppet_user', JSON.stringify({ id: 'u-fx', email: 'fx@x', session_token: 'tok-fx' }));
  });
  const page = await ctx.newPage();
  const approves = [];
  const j = (r, obj) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
  await page.route('**/v1/classify-turn', (r) => j(r, { turn: 'build' }));
  await page.route('**/v1/artifacts/classify-action', (r) => j(r, { action: 'new' }));
  await page.route('**/v1/runs/*/approve', (r) => {
    approves.push({ url: r.request().url(), body: JSON.parse(r.request().postData() || '{}') });
    return j(r, { found: true, executed: true, status: 'executed', result: 'archivo creado' });
  });
  await page.route('**/v1/puppets/run', async (r) => {
    await sleep(1800);
    return j(r, { ok: true, answer: 'quedó retenida — esperando tu OK', run_id: 'r-b4',
                  held_actions: [{ approval_id: 'ap-b4', server: 'datatools', tool: 'write_xlsx',
                                   level: 'confirma-siempre', args: {}, turn_text: TURN_TEXT, ux: GATE_UX }],
                  record: { tool_calls: [], gate_decisions: [], model_route: [], model_final: 'claude-code-opus-4.8', degraded: null } });
  });
  await page.route('**/v1/chats*', (r) => r.request().method() === 'POST' ? j(r, { id: 'chat-fx', title: '' }) : j(r, { total: 0, chats: [] }));
  await page.route('**/v1/chats/**', (r) => j(r, { id: 'chat-fx', messages: [] }));
  await page.route('**/v1/belts/cards*', (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route('**/v1/users/**', (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route('**/v1/sessions/**', (r) => j(r, { artifacts: [] }));
  await page.route('**/v1/obra-caption', (r) => j(r, {}));

  await page.goto(BASE + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(400);
  await page.fill('#composer', 'arma la planilla trimestral');
  await page.click('#send');

  // freeze: la card llega con el gate_waiting (aún sin approval_id)
  await page.waitForSelector('#chat .gate', { timeout: 10000 });
  await sleep(300);
  let card = await page.evaluate(() => (document.querySelector('#chat .gate') || {}).textContent || '');
  check('B4f.1 «Por qué:» pinta la intención REAL del turno',
    /Por qué:/.test(card) && /planilla trimestral con los totales/.test(card));
  check('B4f.2 «Tocando:» pinta los args reales (path + rows)',
    /Tocando:/.test(card) && /trimestre\.xlsx/.test(card));
  check('B4f.3 el secreto en args queda SCRUBBEADO (‹oculto›, jamás el valor)',
    !card.includes('sk_test_51') && /‹oculto›/.test(card), card.slice(0, 160));
  // [H5] «Detalle:» (vista_previa) incrusta el body crudo del mensaje → un Stripe live-key
  // NUNCA debe verse en claro (antes se pintaba con esc() sin scrubSecrets).
  check('B4f.6 [H5] el secreto en la vista_previa («Detalle:») queda SCRUBBEADO',
    /Detalle:/.test(card) && !card.includes('sk_live_4eC39') && !card.includes(PREVIEW_SECRET),
    card.slice(0, 220));
  // [H6] el turn_text lleva un JWT ecoado → «Por qué:» debe taparlo (base64url/header <40
  // que el catch-all clásico no cubría).
  check('B4f.7 [H6] el JWT ecoado en turn_text queda SCRUBBEADO en «Por qué:»',
    !card.includes('eyJhbGci') && !card.includes('SflKxwRJSMeKKF2QT4'), card.slice(0, 220));
  const chips = await page.evaluate(() => [...document.querySelectorAll('#chat .gate .gchip')].map((c) => c.textContent));
  check('B4f.4 chips clase/nivel/perilla visibles',
    chips.includes('write-world') && chips.includes('confirma-siempre') && chips.includes('balanceado'),
    JSON.stringify(chips));

  // operable con el closed → aprobar dispara el /approve real
  await page.waitForFunction(() => {
    const b = document.querySelector('#chat .gate .acts .ok');
    return b && !b.disabled;
  }, { timeout: 15000 });
  await page.click('#chat .gate .acts .ok');
  await sleep(600);
  check('B4f.5 aprobar → POST /v1/runs/{id}/approve con approval_id + ok:true',
    approves.length === 1 && approves[0].url.includes('/v1/runs/r-b4/approve')
    && approves[0].body.approval_id === 'ap-b4' && approves[0].body.ok === true,
    JSON.stringify(approves));

  await browser.close(); srv.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
