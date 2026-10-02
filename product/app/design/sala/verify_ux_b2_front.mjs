#!/usr/bin/env node
/**
 * verify_ux_b2_front.mjs — B2 · PLAN + CHECKLIST del run en el acto Brief (Sala).
 *
 * La checklist se marca SOLO con eventos reales del espinazo — este harness lo prueba
 * con un espinazo SSE guionado (patrón 4a: server local + delays reales):
 *   · plan_declared → checklist visible bajo el Brief (pasos ○)
 *   · tool_call_finished(run_python) → SOLO ese paso pasa a ✓
 *   · gate_waiting(write_xlsx) → ese paso queda ⏸ «espera tu OK» (NO se marca hecho)
 *   · paso con tool que JAMÁS dispara → queda ○ aunque el run cierre (honesto)
 *   · paso sin tool → ✓ recién con el closed OK real
 *   · run SIN plan_declared → SIN checklist (colapso honesto)
 *
 * Corre: node product/app/design/sala/verify_ux_b2_front.mjs (autocontenido, sin stack)
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

const PLAN_STEPS = [
  { n: 1, paso: 'Calcular el resultado con Python', tool: 'run_python' },
  { n: 2, paso: 'Escribir la planilla', tool: 'write_xlsx' },
  { n: 3, paso: 'Redactar la conclusión', tool: null },
  { n: 4, paso: 'Paso fantasma (su tool jamás corre)', tool: 'nunca_corre' },
];

const SPINE = {
  plan: (res) => {
    res.write(frame(1, 'plan_declared', { kind: 'plan', steps: PLAN_STEPS, turn: 1 }));
    setTimeout(() => res.write(frame(2, 'tool_call_finished',
      { kind: 'tool_call', tool: 'pysandbox', tool_raw: 'run_python', args: {}, result: '42', status: 'ok', gate_action: 'execute', turn: 1 })), 400);
    setTimeout(() => res.write(frame(3, 'gate_waiting',
      { kind: 'tool_call', tool: 'datatools', tool_raw: 'write_xlsx', args: {}, gate_action: 'needs_ok', turn: 2 })), 700);
    setTimeout(() => {
      res.write(frame(4, 'final', { ok: true, run_id: 'r-b2', model_final: 'claude-code-opus-4.8', degraded: null, answer: 'listo: 42' }));
      res.write(frame(5, 'closed', { ok: true, run_id: 'r-b2', model_final: 'claude-code-opus-4.8', degraded: null, held_actions: [{ approval_id: 'ap-b2', server: 'datatools', tool: 'write_xlsx', level: 'confirma-siempre', action_class: 'write-world' }] }));
      res.end();
    }, 1600);
  },
  noplan: (res) => {
    res.write(frame(1, 'tool_call_finished',
      { kind: 'tool_call', tool: 'pysandbox', tool_raw: 'run_python', args: {}, result: '7', status: 'ok', gate_action: 'execute', turn: 1 }));
    setTimeout(() => {
      res.write(frame(2, 'final', { ok: true, run_id: 'r-np', model_final: 'claude-code-opus-4.8', degraded: null, answer: 'directo: 7' }));
      res.write(frame(3, 'closed', { ok: true, run_id: 'r-np', model_final: 'claude-code-opus-4.8', degraded: null, held_actions: [] }));
      res.end();
    }, 500);
  },
};

function serve() {
  const state = { scenario: 'plan' };
  const srv = http.createServer((req, r) => {
    const u = new URL(req.url, 'http://x');
    if (/\/v1\/spaces\/[^/]+\/stream$/.test(u.pathname)) {
      r.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' });
      (SPINE[state.scenario] || SPINE.plan)(r);
      return;
    }
    const p = path.join(DESIGN, decodeURIComponent(u.pathname));
    if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { 'Content-Type': MIME[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(r);
  });
  return new Promise((res) => srv.listen(0, '127.0.0.1', () => res({ srv, state })));
}

function terminalOut(withPlan) {
  return {
    ok: true, answer: 'listo: 42', run_id: 'r-b2', held_actions: [],
    record: { tool_calls: [], gate_decisions: [], model_route: [], model_final: 'claude-code-opus-4.8',
              degraded: null, ...(withPlan ? { plan: PLAN_STEPS } : {}) },
  };
}

(async () => {
  const { srv, state } = await serve();
  const BASE = `http://127.0.0.1:${srv.address().port}`;
  console.log(`verify_ux_b2_front · ${BASE}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  await ctx.addInitScript(() => {
    sessionStorage.setItem('puppet_user', JSON.stringify({ id: 'u-fx', email: 'fx@x', session_token: 'tok-fx' }));
  });
  const page = await ctx.newPage();
  const j = (r, obj) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(obj) });
  await page.route('**/v1/classify-turn', (r) => j(r, { turn: 'build' }));
  await page.route('**/v1/artifacts/classify-action', (r) => j(r, { action: 'new' }));
  await page.route('**/v1/puppets/run', async (r) => { await sleep(2200); return j(r, terminalOut(state.scenario === 'plan')); });
  await page.route('**/v1/chats*', (r) => r.request().method() === 'POST' ? j(r, { id: 'chat-fx', title: '' }) : j(r, { total: 0, chats: [] }));
  await page.route('**/v1/chats/**', (r) => j(r, { id: 'chat-fx', messages: [] }));
  await page.route('**/v1/belts/cards*', (r) => j(r, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route('**/v1/users/**', (r) => j(r, { puppets: [], keys: [], docs: [] }));
  await page.route('**/v1/sessions/**', (r) => j(r, { artifacts: [] }));
  await page.route('**/v1/obra-caption', (r) => j(r, {}));

  const planState = () => page.evaluate(() => {
    const steps = [...document.querySelectorAll('#narrative .nplan-step')];
    return { n: steps.length, cls: steps.map((s) => s.className.replace('nplan-step', '').trim() || 'pend'),
             txt: steps.map((s) => s.textContent) };
  });

  // ── escenario 1: plan declarado → checklist honesta ──────────────────────────
  await page.goto(BASE + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(400);
  await page.fill('#composer', 'arma la planilla con el cálculo');
  await page.click('#send');

  // t≈300ms: el plan llegó, nada ejecutó aún → 4 pasos, todos pendientes
  await sleep(300);
  let st = await planState();
  check('B2f.1 plan_declared → checklist visible (4 pasos, todos ○)',
    st.n === 4 && st.cls.every((c) => c === 'pend'), JSON.stringify(st.cls));

  // t≈550ms: run_python ejecutó → SOLO el paso 1 ✓
  await sleep(280);
  st = await planState();
  check('B2f.2 tool_call_finished marca SOLO su paso (1✓, resto ○)',
    st.cls[0] === 'done' && st.cls[1] === 'pend' && st.cls[2] === 'pend' && st.cls[3] === 'pend',
    JSON.stringify(st.cls));

  // t≈900ms: write_xlsx quedó retenida → paso 2 ⏸ espera tu OK (NO hecho)
  await sleep(350);
  st = await planState();
  check('B2f.3 gate_waiting → su paso queda «espera tu OK» (jamás ✓)',
    st.cls[1] === 'held' && /espera tu OK/.test(st.txt[1]), JSON.stringify(st.cls));
  check('B2f.4 mid-run: el paso sin tool sigue pendiente (no se adelanta)',
    st.cls[2] === 'pend', st.cls[2]);

  // cierre: paso sin tool ✓ con el closed OK; el fantasma sigue ○; el retenido sigue ⏸
  await page.waitForFunction(() => !document.querySelector('.send.busy'), { timeout: 30000 }).catch(() => {});
  await sleep(2600);
  st = await planState();
  check('B2f.5 closed OK → el paso sin tool se marca (✓)', st.cls[2] === 'done', JSON.stringify(st.cls));
  check('B2f.6 paso cuya tool JAMÁS corrió queda pendiente (cero teatro)',
    st.cls[3] === 'pend', st.cls[3]);
  check('B2f.7 el paso retenido NO se marca hecho al cerrar', st.cls[1] === 'held', st.cls[1]);

  // ── escenario 2: sin plan → sin checklist ─────────────────────────────────────
  state.scenario = 'noplan';
  await page.goto(BASE + '/sala/sala.html');
  await page.waitForSelector('#composer', { timeout: 15000 });
  await sleep(400);
  await page.fill('#composer', 'calcula 7');
  await page.click('#send');
  await page.waitForFunction(() => !document.querySelector('.send.busy'), { timeout: 30000 }).catch(() => {});
  await sleep(2600);
  st = await planState();
  const narrOn = await page.evaluate(() => document.getElementById('narrative').classList.contains('on'));
  check('B2f.8 run SIN plan → SIN checklist (colapso honesto, narrativa intacta)',
    st.n === 0 && narrOn, `steps=${st.n} narr=${narrOn}`);

  await browser.close(); srv.close();
  console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
  if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
  process.exit(FAIL === 0 ? 0 : 1);
})().catch((e) => { console.log('ROJO — excepción:', e); process.exit(1); });
