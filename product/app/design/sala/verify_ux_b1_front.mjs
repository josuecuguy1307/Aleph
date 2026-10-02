#!/usr/bin/env node
/**
 * verify_ux_b1_front.mjs — B1 · el selector de autonomía de la Sala ALTERA el run real.
 *
 * Playwright sobre la Sala real con backend stubeado (page.route): prueba el CONTRATO
 * front→backend — el selector escribe body.autonomy en el POST del turno siguiente,
 * el copy honesto está SIEMPRE pegado al selector, y la elección persiste (localStorage
 * por composición). El enforcement real del gate lo prueba qa/verify_ux_universal.py b1
 * (runs vivos). Env: SALA_FRONT (default http://127.0.0.1:8098).
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
  console.log(`verify_ux_b1_front · FRONT=${FRONT}`);
  const ok0 = await fetch(FRONT + '/sala/sala.html').then((r) => r.ok).catch(() => false);
  if (!ok0) { console.log('ROJO — preflight: front caído'); process.exit(1); }

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => {
    sessionStorage.setItem('puppet_user', JSON.stringify(
      { id: 'u-fx', email: 'fx@x', session_token: 'tok-fx' }));
  });
  const page = await ctx.newPage();

  const captured = [];   // bodies de POST /v1/puppets/run
  const j = (r, obj) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
  await page.route('**/v1/classify-turn', (r) => j(r, { turn: 'build' }));
  await page.route('**/v1/artifacts/classify-action', (r) => j(r, { action: 'new' }));
  await page.route('**/v1/puppets/run', (r) => {
    captured.push(JSON.parse(r.request().postData() || '{}'));
    return j(r, { ok: true, answer: 'hecho', run_id: 'r-fx', held_actions: [],
                  record: { tool_calls: [], gate_decisions: [], model_route: [], model_final: 'x' } });
  });
  await page.route('**/v1/spaces/**', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: '' }));
  await page.route('**/v1/chats*', (r) => r.request().method() === 'POST'
    ? j(r, { id: 'chat-fx', puppet_id: null, title: '' }) : j(r, { total: 0, chats: [] }));
  await page.route('**/v1/chats/**', (r) => j(r, { id: 'chat-fx', messages: [] }));
  await page.route('**/v1/belts/cards*', (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route('**/v1/users/**', (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route('**/v1/sessions/**', (r) => j(r, { artifacts: [] }));
  await page.route('**/v1/obra-caption', (r) => j(r, {}));

  await page.goto(FRONT + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(500);

  // el popover: dos modos con copy honesto SIEMPRE pegado
  await page.click('#autBtn');
  const pop = await page.evaluate(() => {
    const p = document.getElementById('autpop');
    return { on: p.classList.contains('on'), text: p.textContent,
             items: p.querySelectorAll('.it').length };
  });
  check('B1f.1 selector: dos modos visibles', pop.on && pop.items === 2, `items=${pop.items}`);
  check('B1f.2 copy honesto pegado al selector (pisos en ambos modos)',
    /SIEMPRE preguntan/.test(pop.text) && /dos modos/i.test(pop.text));
  check('B1f.3 sin modo «autonomo» en la Sala (send jamás auto-pasa desde acá)',
    !/aut[oó]nomo/i.test(pop.text.replace('Autonomía', '')));

  // elegir «Confirmá cada acción» → persiste + el turno siguiente lo lleva al run REAL
  await page.evaluate(() => {
    [...document.querySelectorAll('#autpop .it')].find((b) => /Confirm/i.test(b.textContent)).click();
  });
  const stored = await page.evaluate(() => localStorage.getItem('aleph-aut-general'));
  check('B1f.4 la elección persiste por composición (localStorage)', stored === 'manual', String(stored));

  await page.fill('#composer', 'arma un informe de prueba');
  await page.click('#send');
  await page.waitForFunction(() => !document.querySelector('.send.busy'), { timeout: 20000 }).catch(() => {});
  await sleep(600);
  check('B1f.5 el turno siguiente lleva autonomy=manual en el POST real',
    captured.length >= 1 && captured[captured.length - 1].autonomy === 'manual',
    JSON.stringify(captured[captured.length - 1] || {}).slice(0, 120));

  // reload → sigue manual (persistido); cambiar a Autonomía → el próximo turno cambia
  await page.reload();
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(500);
  const afterReload = await page.evaluate(() => ({
    on: document.getElementById('autBtn').classList.contains('on'),
    stored: localStorage.getItem('aleph-aut-general'),
  }));
  check('B1f.6 reload → el modo persiste y el botón lo refleja',
    afterReload.on && afterReload.stored === 'manual', JSON.stringify(afterReload));

  await page.click('#autBtn');
  await page.evaluate(() => {
    [...document.querySelectorAll('#autpop .it')].find((b) => !/Confirm/i.test(b.textContent)).click();
  });
  await page.fill('#composer', 'arma otro informe');
  await page.click('#send');
  await page.waitForFunction(() => !document.querySelector('.send.busy'), { timeout: 20000 }).catch(() => {});
  await sleep(600);
  check('B1f.7 cambiar el selector re-configura la perilla del turno siguiente',
    captured.length >= 2 && captured[captured.length - 1].autonomy === 'balanceado',
    JSON.stringify((captured[captured.length - 1] || {}).autonomy));

  await browser.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
