/* verify_tarjeta_y_canvas.mjs — LA TARJETA EN EL HILO, Y EL CANVAS QUE EMERGE.
 * [Gate 4 · Fase 4 · obra O6b · 4.3 · B10 · ley 6 · LEY 15]
 *
 * QUÉ AFIRMA
 * ----------
 *  A · **Una obra nueva NO abre el canvas.** Nace una TARJETA en el hilo, con su preview.
 *  B · **EL HILO NO SE MUEVE** cuando eso pasa. Se mide en PÍXELES: la caja del composer
 *      antes y después de que nazca la obra. Es el defecto exacto que Fase 1 pagó («una
 *      columna que va y viene mueve el chat de lugar a mitad de una conversación») y la
 *      única razón por la que la tercera columna estaba siempre puesta.
 *  C · **Tap → crece**: el canvas se abre y muestra ESA obra. El movimiento es consecuencia
 *      del gesto del usuario, que es lo que la regla de Fase 1 nunca prohibió.
 *  D · **Lo que se abre, se cierra** (B10), y el estado sobrevive a una recarga.
 *  E · **La tarjeta ofrece el workspace que el APLICADOR resolvió** (O5), con su copy — no
 *      con una opinión propia de la tarjeta.
 *  F · **LEY 15**: todo esto sin un solo agente. La obra se crea con el sid de la sesión y
 *      la tarjeta nunca pregunta por un puppet.
 *
 * CÓMO SE MIDE
 * ------------
 * Contra el producto: backend real, La Sala real, navegador real. La obra se crea por el
 * MISMO borde de escritura que usa un turno (`POST /v1/sessions/{sid}/artifacts`) y la
 * pantalla la recibe por su propio seam — no se pinta un DOM a mano.
 *
 * PROBADA CAYENDO
 * ---------------
 *   --caer abre-solo  → la obra abre el canvas al nacer (lo que hacía antes de O6b): cae B,
 *                       porque el hilo se corre de lugar.
 *
 *   node qa/verify_tarjeta_y_canvas.mjs
 */
import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CAPS = path.join(RAIZ, "qa/screenshots");
const CAER = (() => { const i = process.argv.indexOf("--caer"); return i > 0 ? process.argv[i + 1] : ""; })();
// El modo va EN EL NOMBRE de la captura. Sin esto el sabotaje pisa la captura de la
// corrida limpia y uno termina MIRANDO el caso equivocado — me pasó al revisar ésta.
const SUF = CAER ? `-caer-${CAER}` : "";

const fallos = [];
const ok = (c, l, x = "") => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  " + x : ""}`); if (!c) fallos.push(l); };

const libre = () => new Promise((r) => {
  const s = net.createServer();
  s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); });
});

function pythonDelBackend() {
  for (const c of [path.join(RAIZ, "product/backend/.venv/bin/python")]) {
    if (fs.existsSync(c)) return c;
  }
  console.error("✗ no encontré el venv del backend"); process.exit(2);
}

const DATOS = fs.mkdtempSync(path.join(os.tmpdir(), "f4-tarjeta-"));
const PUERTO = await libre();
const BASE = `http://127.0.0.1:${PUERTO}`;
fs.mkdirSync(CAPS, { recursive: true });

const backend = spawn(pythonDelBackend(),
  ["-m", "uvicorn", "app.main:app", "--app-dir", path.join(RAIZ, "product/backend"),
   "--host", "127.0.0.1", "--port", String(PUERTO)],
  { stdio: "ignore", detached: true,
    env: { ...process.env, ALEPH_DATA_DIR: DATOS, ALEPH_ROLE: "client", ALEPH_ENV: "dev",
           PUPPET_ALLOW_PASSWORD_AUTH: "1", PUPPET_ALLOW_ANON_V1: "1" } });

let arriba = false;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  try { if ((await fetch(BASE + "/health")).ok) { arriba = true; break; } } catch { /* aún no */ }
}
ok(arriba, "el backend real está en pie", BASE);

const nav = await chromium.launch();
try {
  if (!arriba) throw new Error("sin backend");
  const ctx = await nav.newContext({ viewport: { width: 1440, height: 900 } });
  const pg = await ctx.newPage();
  const errores = [];
  pg.on("console", (m) => { if (m.type() === "error") errores.push(m.text().slice(0, 140)); });
  await pg.goto(`${BASE}/sala-v2/sala-v2.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => window.__salaV2 && document.querySelector(".sv-main"),
                           null, { timeout: 30000 });
  await pg.waitForTimeout(1500);

  const raiz = pg.locator("#sv-root");
  ok((await raiz.getAttribute("data-canvas")) !== "abierto",
     "al abrir La Sala el canvas NO ocupa media pantalla", await raiz.getAttribute("data-canvas") || "");

  // ── B · LA MEDIDA QUE IMPORTA: dónde está el hilo ANTES ────────────────────────────
  const caja = async (sel) => {
    const el = pg.locator(sel).first();
    await el.scrollIntoViewIfNeeded().catch(() => {});
    return await el.boundingBox();
  };
  const antes = await caja(".sv-main");
  ok(!!antes, "el hilo está en pantalla", JSON.stringify(antes));

  // ── NACE UNA OBRA, POR EL BORDE DE ESCRITURA REAL ──────────────────────────────────
  // Se crea con el MISMO endpoint que usa un turno y se le avisa a la pantalla por su
  // seam: lo que se mide es la reacción del producto, no un DOM pintado a mano.
  const obra = await pg.evaluate(async (caer) => {
    const sid = window.__salaV2.SID || (window.__salaV2.sid && window.__salaV2.sid());
    const r = await fetch(`/v1/sessions/${encodeURIComponent(sid)}/artifacts`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: "Informe de la vara", type: "informe",
        content: "# Secuencias\n\nTP53 · P04637 · 393 aa. Esto es el preview.",
        provenance: { produced_by: "run" },
      }),
    });
    const a = await r.json();
    const art = a.artifact || a;
    window.__salaV2.anunciarObra(art);
    // EL SABOTAJE SE ARMA DESDE AFUERA, con seams de producción: abrir la obra apenas nace
    // es exactamente lo que hacía el código anterior a O6b (`setObraId` + `setObraActiva`).
    // Así no queda una perilla de sabotaje adentro del código del usuario, que se quedaría
    // para siempre y además sólo probaría que la perilla anda.
    if (caer === "abre-solo") window.__salaV2.abrirObra(art.id);
    return art;
  }, CAER);
  await pg.waitForTimeout(900);

  const despues = await caja(".sv-main");
  ok(antes && despues && Math.abs(antes.x - despues.x) < 1 && Math.abs(antes.width - despues.width) < 1,
     "EL HILO NO SE MOVIÓ cuando nació la obra",
     `x ${antes?.x}→${despues?.x} · ancho ${antes?.width}→${despues?.width}`);

  // ── A · LA TARJETA ─────────────────────────────────────────────────────────────────
  const tarjeta = pg.locator(".sv-tarjeta-obra").first();
  ok(await tarjeta.count() > 0, "la obra se anunció con una TARJETA en el hilo");
  const textoTarjeta = (await tarjeta.innerText().catch(() => "")).replace(/\s+/g, " ");
  ok(/informe/i.test(textoTarjeta), "que dice de qué tipo es", textoTarjeta.slice(0, 60));
  ok(/preview/i.test(textoTarjeta),
     "y trae un preview de lo que la obra DICE (recortado, no inventado)",
     textoTarjeta.slice(0, 90));
  ok((await raiz.getAttribute("data-canvas")) !== "abierto" || CAER === "abre-solo",
     "y el canvas SIGUE cerrado: la obra se anuncia, no se impone");

  await pg.screenshot({ path: path.join(CAPS, `tarjeta-en-el-hilo${SUF}.png`) });

  // ── E · EL DESTINO LO RESOLVIÓ EL APLICADOR ────────────────────────────────────────
  const destino = await pg.evaluate(async () => {
    const r = await fetch("/v1/workspaces/destino?tipo=informe");
    return r.ok ? r.json() : null;
  });
  const ofrece = await pg.locator(".sv-tarjeta-btn--ws").count();
  ok(destino !== null, "el aplicador contesta para este tipo", JSON.stringify(destino?.motivo));
  ok(Boolean(destino?.destino) === (ofrece > 0),
     "la tarjeta ofrece el workspace SÓLO si el aplicador resolvió uno — no opina por su cuenta",
     `aplicador=${destino?.destino || "—"} · botón=${ofrece}`);

  // ── C · TAP → CRECE ────────────────────────────────────────────────────────────────
  await pg.locator(".sv-tarjeta-btn").first().click();
  await pg.waitForTimeout(900);
  ok((await raiz.getAttribute("data-canvas")) === "abierto",
     "TAP EN LA TARJETA → el canvas emerge");
  const enCanvas = (await pg.locator(".sv-canvas").innerText().catch(() => "")).replace(/\s+/g, " ");
  ok(/Informe de la vara/.test(enCanvas), "y muestra ESA obra", enCanvas.slice(0, 70));
  await pg.screenshot({ path: path.join(CAPS, `canvas-emergido${SUF}.png`) });

  // ── D · SE CIERRA, Y EL ESTADO SOBREVIVE ───────────────────────────────────────────
  await pg.locator('[data-testid="sv-cerrar-canvas"]').click();
  await pg.waitForTimeout(600);
  ok((await raiz.getAttribute("data-canvas")) !== "abierto", "lo que se abre, se cierra (B10)");
  await pg.locator(".sv-tarjeta-btn").first().click();
  await pg.waitForTimeout(600);
  await pg.reload({ waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => window.__salaV2 && document.querySelector(".sv-main"),
                           null, { timeout: 30000 });
  await pg.waitForTimeout(1200);
  ok((await pg.locator("#sv-root").getAttribute("data-canvas")) === "abierto",
     "y el panel abierto sigue abierto tras recargar: es una preferencia, no un parpadeo");

  ok(errores.length === 0, "cero errores de consola", errores.slice(0, 2).join(" | "));
} finally {
  await nav.close();
  try { process.kill(-backend.pid, "SIGTERM"); } catch { /* ya no está */ }
  spawnSync("pkill", ["-f", `ALEPH_DATA_DIR=${DATOS}`]);
  fs.rmSync(DATOS, { recursive: true, force: true });
}

console.log(`\ncapturas: ${CAPS}`);
console.log(fallos.length ? `\nROJAS: ${fallos.join(", ")}` : "\nVERDE");
process.exit(fallos.length ? 1 : 0);
