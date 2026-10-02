#!/usr/bin/env node
/**
 * verify_ux_scrub_front.mjs — regresión FRONT del scrub anti-secreto (review UX-UNIVERSAL).
 *
 *   H6  scrubSecrets de la Sala cubre JWT, password/token etiquetados, Basic/Bearer y
 *       base64url (además de los prefijos conocidos) — y argsSummary scrubbea ANTES de truncar.
 *   H8  el paso del plan (sala.html) y el task del sub-agente (cuarto.pixi.html) — prosa del
 *       modelo, misma clase que turn_text — pasan por un scrub antes de pintarse.
 *
 * Extrae las funciones REALES del HTML enviado (no una copia), las evalúa contra vectores, y
 * verifica el cableado en cada sitio de pintado. Autocontenido (sin server, sin navegador).
 * Corre:  node product/app/design/verify_ux_scrub_front.mjs
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const SALA = fs.readFileSync(path.join(DIR, 'sala', 'sala.html'), 'utf8');
const CUARTO = fs.readFileSync(path.join(DIR, 'cuarto', 'cuarto.pixi.html'), 'utf8');

let PASS = 0, FAIL = 0; const FAILED = [];
function check(name, ok, detail = '') {
  if (ok) { PASS++; console.log(`  PASS  ${name}`); }
  else { FAIL++; FAILED.push(name); console.log(`  FAIL  ${name}${detail ? ' — ' + detail : ''}`); }
}

// Extrae `function NAME(...) { ... }` del fuente por conteo de llaves (los quantifiers de regex
// {6,}/{40,} son pares balanceados → no rompen el conteo). Devuelve la función evaluada.
function extractFn(src, name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  const open = src.indexOf('{', i);
  let depth = 0;
  for (let k = open; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (depth === 0) return eval('(' + src.slice(i, k + 1) + ')'); }
  }
  return null;
}

const scrubSecrets = extractFn(SALA, 'scrubSecrets');
const scrubSec = extractFn(CUARTO, 'scrubSec');
check('SETUP scrubSecrets extraída de sala.html', typeof scrubSecrets === 'function');
check('SETUP scrubSec extraída de cuarto.pixi.html', typeof scrubSec === 'function');

// ── H6 · vectores que ANTES se filtraban ─────────────────────────────────────────
const VEC = [
  ['JWT header+firma', 'sesión eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c', ['eyJhbGci', 'SflKxwRJSMeKKF2QT4']],
  ['password plano', 'password: hunter2', ['hunter2']],
  ['Basic auth <40', 'Authorization: Basic YWRtaW46aHVudGVyMg==', ['YWRtaW46aHVudGVyMg']],
  ['stripe sk_live', 'la key sk_live_4eC39HqLyjWDarjtT1zdp7dc', ['sk_live_4eC39']],
  ['github ghp', 'token ghp_abc123def456ghi789jkl012mno', ['ghp_abc123']],
  ['token etiquetado', 'token = abc123def456ghi789', ['abc123def456ghi789']],
];
for (const [name, input, leaks] of VEC) {
  const out = scrubSecrets(input);
  const leaked = leaks.filter((l) => out.includes(l));
  check(`H6 · scrubSecrets tapa: ${name}`, leaked.length === 0 && out.includes('‹oculto›'), `out=${out}`);
}
// control positivo: prosa normal NO se rompe de más
const prose = 'Voy a resumir el documento sobre finanzas del Q3 en tres puntos claros.';
check('H6 · control: prosa normal queda intacta', scrubSecrets(prose) === prose, scrubSecrets(prose));

// ── H6 · argsSummary scrubbea ANTES de truncar a 60 ──────────────────────────────
const asIdx = SALA.indexOf('function argsSummary');
const asBody = asIdx >= 0 ? SALA.slice(asIdx, asIdx + 700) : '';
const scrubBeforeSlice = asBody.indexOf('scrubSecrets(s)') >= 0
  && asBody.indexOf('scrubSecrets(s)') < asBody.indexOf('s.slice(0,60)');
check('H6 · argsSummary scrubbea cada valor ANTES de truncarlo a 60', scrubBeforeSlice);

// ── H8 · cableado del scrub en las superficies nuevas ────────────────────────────
check('H8 · sala: el paso del plan pinta esc(scrubSecrets(String(p.paso)))',
  SALA.includes('esc(scrubSecrets(String(p.paso)))'));
check('H8 · sala: la vista_previa del gate pasa por scrubSecrets [H5]',
  SALA.includes('esc(scrubSecrets(String(ux.vista_previa)))'));
check('H8 · cuarto: el task del sub-agente pinta escTT(scrubSec(r.task))',
  CUARTO.includes('escTT(scrubSec(r.task))'));

// ── H8 · funcional: un token ecoado en el paso/task se tapa ───────────────────────
const planStep = '1. Autenticarme con el token ghp_abc123def456ghi789jkl012mno';
check('H8 · funcional (sala): token en el paso del plan → ‹oculto›',
  !scrubSecrets(planStep).includes('ghp_abc123'));
const task = 'pagá con el token sk_live_4eC39HqLyjWDarjtT1zdp7dc';
check('H8 · funcional (cuarto): token en el task → ‹oculto›',
  !scrubSec(task).includes('sk_live_4eC39') && scrubSec(task).includes('‹oculto›'));

console.log(`\n${FAIL === 0 ? 'VERDE' : 'ROJO'} — ${PASS} PASS · ${FAIL} FAIL`);
if (FAILED.length) FAILED.forEach((f) => console.log(`  ✗ ${f}`));
process.exit(FAIL === 0 ? 0 : 1);
