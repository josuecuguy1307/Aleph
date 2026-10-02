#!/usr/bin/env node
/**
 * verify_ux_b5_front.mjs — B5 · panel de instrucciones persistentes en la Sala.
 *
 * Backend stubeado (page.route): el panel proyecta el recurso real — lista por scope,
 * alta (POST capturado), propuesta del agente INERTE con «Activar» (PATCH enabled:true
 * capturado = el OK humano), borrar (DELETE capturado). El enforcement/inyección real
 * lo prueba qa/verify_ux_universal.py b5 (runs vivos).
 * Env: SALA_FRONT (default http://127.0.0.1:8098).
 */
import { chromium } from 'playwright';

const FRONT = process.env.SALA_FRONT || 'http://127.0.0.1:8098';
let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = '') {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? ' — ' + detail : ''}`); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  console.log(`verify_ux_b5_front · FRONT=${FRONT}`);
  const ok0 = await fetch(FRONT + '/sala/sala.html').then((r) => r.ok).catch(() => false);
  if (!ok0) { console.log('ROJO — preflight: front caído'); process.exit(1); }

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => {
    sessionStorage.setItem('puppet_user', JSON.stringify({ id: 'u-fx', email: 'fx@x', session_token: 'tok-fx' }));
  });
  const page = await ctx.newPage();

  const calls = [];
  const rows = [
    { id: 'i-1', puppet_id: null, source: 'user', content: 'Tono directo, siempre.', enabled: true, meta: null },
    { id: 'i-2', puppet_id: null, source: 'agent', content: 'usar tono formal siempre', enabled: false, meta: { run_id: 'r-x' } },
  ];
  const j = (r, obj) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
  await page.route('**/v1/instructions*', (r) => {
    const m = r.request().method();
    if (m === 'GET') return j(r, { total: rows.length, usage: { entries: 2, bytes: 60 }, caps: { max_entries: 20, max_bytes: 8192 }, instructions: rows });
    if (m === 'POST') { calls.push({ m, body: JSON.parse(r.request().postData() || '{}') }); return j(r, { id: 'i-new' }); }
    return j(r, {});
  });
  await page.route('**/v1/instructions/**', (r) => {
    const m = r.request().method();
    calls.push({ m, url: r.request().url(), body: m === 'PATCH' ? JSON.parse(r.request().postData() || '{}') : null });
    return j(r, { id: 'i-2', enabled: true, source: 'agent', meta: { approved: true } });
  });
  await page.route('**/v1/chats*', (r) => r.request().method() === 'POST' ? j(r, { id: 'c' }) : j(r, { total: 0, chats: [] }));
  await page.route('**/v1/belts/cards*', (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route('**/v1/users/**', (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route('**/v1/sessions/**', (r) => j(r, { artifacts: [] }));

  await page.goto(FRONT + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(400);

  await page.click('#instrBtn');
  await page.waitForSelector('#instrDrawer.on', { timeout: 5000 });
  await sleep(500);

  const st = await page.evaluate(() => ({
    scopes: [...document.querySelectorAll('#instrList .iscope')].map((s) => s.textContent),
    rows: document.querySelectorAll('#instrList .irow').length,
    propTag: (document.querySelector('#instrList .irow.agent .itag') || {}).textContent || '',
    hasActivate: !!document.querySelector('#instrList .irow.agent .ibtn.ok'),
  }));
  check('B5f.1 panel abre con el scope de cuenta y las filas reales',
    st.scopes.length >= 1 && st.rows === 2, JSON.stringify(st.scopes));
  check('B5f.2 la propuesta del agente se distingue (inerte, «no rige hasta tu OK»)',
    /no rige hasta tu OK/.test(st.propTag) && st.hasActivate, st.propTag);

  // activar la propuesta = PATCH enabled:true (el OK humano)
  await page.click('#instrList .irow.agent .ibtn.ok');
  await sleep(400);
  const patch = calls.find((c) => c.m === 'PATCH');
  check('B5f.3 «Activar» dispara el PATCH enabled:true real',
    patch && patch.url.includes('/v1/instructions/i-2') && patch.body.enabled === true,
    JSON.stringify(patch));

  // alta
  await page.fill('#instrList .iadd textarea', 'Firmá con AXOLOTL.');
  await page.click('#instrList .iadd .ibtn.ok');
  await sleep(400);
  const post = calls.find((c) => c.m === 'POST');
  check('B5f.4 «Agregar» POSTea la instrucción nueva',
    post && post.body.content === 'Firmá con AXOLOTL.', JSON.stringify(post));

  // borrar
  await page.click('#instrList .irow .ibtn.del');
  await sleep(400);
  const del = calls.find((c) => c.m === 'DELETE');
  check('B5f.5 «✕» borra por el DELETE real', !!del, JSON.stringify(del));

  await browser.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
