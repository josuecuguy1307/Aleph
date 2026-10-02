#!/usr/bin/env node
/**
 * verify_sala_instalada.mjs — LA SALA, EN LA .APP INSTALADA, CON LOS DATOS DEL DUEÑO.
 *
 *   ALEPH_VARA_SIDECAR=/Applications/Aleph.app/Contents/MacOS/aleph_sidecar \
 *   ALEPH_DATA_DIR=<copia de los datos> node qa/verify_sala_instalada.mjs
 *
 * Que el arreglo esté ESCRITO y que VIAJE son dos cosas distintas. Acá se abre La Sala del
 * binario instalado, con la preferencia real del dueño (`contextos.sala`), y se mide lo
 * único que importaba: **si el composer deja enviar**.
 *
 * El defecto: la Sala clavaba `{selected:'included'}`, la lane que un build público no
 * trae; `not_configured` → `blockExecution` → el turno no salía, con Codex listo y elegido.
 *
 * NO se manda un turno de verdad: eso gasta tokens del dueño y no hace falta para este
 * testigo. Lo que se mide es el GATE — `window.__salaTurno.canSend`, que es la misma señal
 * que decide si el envío sale. Enviar de verdad es la Sección D de la certificación.
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { createServer as netCreateServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const SIDECAR = (process.env.ALEPH_VARA_SIDECAR || "").trim();
const DATOS = (process.env.ALEPH_DATA_DIR || "").trim();
const TOKEN = (process.env.ALEPH_VARA_TOKEN || "").trim();
const R = {};
const anotar = (n, ok, det = {}) => { R[n] = { ok: !!ok, ...det }; };

function puertoLibre() {
  const srv = netCreateServer();
  return new Promise((res, rej) => {
    srv.once("error", rej);
    srv.listen(0, "127.0.0.1", () => { const p = srv.address().port; srv.close(() => res(p)); });
  });
}

if (!SIDECAR || !DATOS) {
  // [H3+H4] Requisito ausente, NO fallo. Antes salía 1 con el JSON como última línea:
  // se leía como una regresión de la Sala instalada cuando lo único que pasaba es que
  // esta vara no tenía contra qué correr. Un ⏳ no es un ❌ — pero tampoco un ✅, así que
  // la última línea lo dice con todas las letras.
  console.log(JSON.stringify({ sala_instalada: { ok: false, motivo: "faltan ALEPH_VARA_SIDECAR / ALEPH_DATA_DIR" } }));
  console.log("NO CERTIFICA · falta ALEPH_VARA_SIDECAR / ALEPH_DATA_DIR — no se midió nada");
  process.exit(0);
}

const PUERTO = await puertoLibre();
const BASE = `http://127.0.0.1:${PUERTO}`;
// Grupo propio: un PyInstaller *onefile* lanza un hijo, y matar sólo al padre deja el
// puerto tomado y a node sin terminar (ver `verify_pieza_en_el_cuarto_front.mjs`).
const server = spawn(SIDECAR, ["--port", String(PUERTO)], {
  cwd: RAIZ, detached: true, stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATOS,
         PUPPET_SQLITE_PATH: join(DATOS, "aleph.db") },
});
let log = "";
server.stdout.on("data", (d) => { log += d; });
server.stderr.on("data", (d) => { log += d; });
const cerrar = () => {
  try { process.kill(-server.pid, "SIGKILL"); } catch { /* ya murió */ }
  try { server.kill("SIGKILL"); } catch { /* ya murió */ }
};

const arriba = await (async () => {
  for (let i = 0; i < 90; i++) {
    try { if ((await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) })).ok) return true; }
    catch { /* todavía no */ }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
})();
if (!arriba) {
  // Éste SÍ es un fallo: el sidecar existe y no levantó.
  cerrar();
  console.log(JSON.stringify({ sala_instalada: { ok: false, motivo: "el sidecar no levantó", log: log.slice(-300) } }));
  console.log("1 FALLO(S) · el sidecar no levantó");
  process.exit(1);
}

let browser;
try {
  /* ── el estado REAL de los cerebros, del binario instalado ─────────────────────────── */
  const brains = await (await fetch(`${BASE}/v1/brains/status`)).json();
  const prov = brains.providers || {};
  anotar("0_los_cli_estan_listos",
    (prov.claude_cli || {}).state === "ready" || (prov.codex_cli || {}).state === "ready",
    { claude_cli: (prov.claude_cli || {}).state, codex_cli: (prov.codex_cli || {}).state,
      included: (prov.included || {}).state });

  browser = await chromium.launch();
  const ctx = await browser.newContext();
  if (TOKEN) {
    await ctx.addInitScript((t) => {
      const u = { id: "x", session_token: t };
      try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
      try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
    }, TOKEN);
  }
  const page = await ctx.newPage();
  const errores = [];
  page.on("pageerror", (e) => errores.push(String(e).slice(0, 140)));
  await page.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded", timeout: 90000 });

  // El gate del composer se publica en `window.__salaTurno` (hook que la Sala ya tenía).
  await page.waitForFunction("!!window.__salaTurno", { timeout: 90000 }).catch(() => {});
  // El estado del cerebro se resuelve async; se espera a que DEJE de estar «revisando».
  await page.waitForFunction(
    () => window.__salaTurno && window.__salaTurno.estado !== "checking",
    { timeout: 30000 }).catch(() => {});

  const diag = await page.evaluate(() => {
    const sd = window.__salaSliceD ? window.__salaSliceD.state() : null;
    const chip = document.getElementById("brainState");
    return { controlsReady: sd ? sd.ready : "sin __salaSliceD",
             chipTexto: chip ? (chip.textContent || "").trim().slice(0, 90) : null,
             errcards: [...document.querySelectorAll(".errcard b")].map((b) => b.textContent).slice(0, 3) };
  });
  console.error("[diag] " + JSON.stringify(diag));

  const visto = await page.evaluate(() => {
    const t = window.__salaTurno || {};
    const card = document.querySelector(".errcard");
    return {
      canSend: t.canSend, estado: t.estado, busy: t.busy,
      // el chip del cerebro: qué lane muestra la pantalla
      chip: (document.querySelector("#brainChip, [data-brain-chip], .brainchip") || {}).textContent || null,
      bloqueo: card ? (card.querySelector("b") || {}).textContent || null : null,
    };
  });

  // ⚠️ EL TESTIGO QUE DECIDE. Antes: `canSend === false` con Codex listo, y la card de
  // «El modelo Incluido no está configurado».
  anotar("1_el_composer_deja_enviar", visto.canSend === true, visto);
  anotar("2_no_hay_bloqueo_de_la_lane_incluida",
    !visto.bloqueo || !/Incluido/i.test(visto.bloqueo), { bloqueo: visto.bloqueo });
  anotar("3_la_superficie_no_tira_errores", errores.length === 0, { errores: errores.slice(0, 3) });
} catch (e) {
  anotar("sala_instalada", false, { excepcion: String(e).slice(0, 300) });
} finally {
  if (browser) await browser.close().catch(() => {});
  cerrar();
}

console.log(JSON.stringify(R));

// ══ [H4d · barrido del verde mentiroso] ESTA VARA NO PODÍA FALLAR ═══════════════════
// Acá decía `process.exit(0)` a secas. `anotar()` guardaba los `ok:false` en `R` —incluido
// el del `catch`, que atrapa una excepción de la corrida entera— y la vara salía CERO
// igual. Nadie parsea su JSON (grep sobre el árbol: cero consumidores), así que el exit
// code era su único veredicto y siempre decía que sí.
// Y la distinción que el `exit(0)` pelado tampoco hacía: «no se pudo medir» NO es
// «falló». Sin `ALEPH_VARA_SIDECAR`/`ALEPH_DATA_DIR` esta vara no tiene contra qué correr
// — eso es un requisito ausente, y ponerlo rojo enseñaría a ignorar sus rojos. Sale 0,
// pero la última línea DICE que no certificó: un ⏳ no es un ✅.
const rojas = Object.entries(R).filter(([, v]) => v && v.ok === false && !v.motivo).map(([n]) => n);
const grises = Object.entries(R).filter(([, v]) => v && v.ok === false && v.motivo).map(([n]) => n);
console.log(
  rojas.length ? `${rojas.length} FALLO(S) · ${rojas.join(", ")}`
  : grises.length ? `NO CERTIFICA · ${grises.length} sin medir por requisito ausente · ${grises.join(", ")}`
  : `TODO VERDE · ${Object.keys(R).length} chequeo(s)`);
process.exit(rojas.length ? 1 : 0);
