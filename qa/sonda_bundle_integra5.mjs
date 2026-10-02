/* sonda_bundle_integra5.mjs — LAS SONDAS DEL BUNDLE [Integración #5].
 *
 * No mira el TOC del archivo ni "si el archivo está": arranca el SIDECAR FROZEN recién
 * construido, con datadir AISLADO, y le PIDE las cosas por HTTP. Lo que se prueba es que
 * el binario que se va a instalar sirve la ola entera — no que el árbol de dev la tenga.
 *
 *   1 · deep-chat ≥250px en el sala.html EMPAQUETADO (el composer vive en su Shadow DOM)
 *   2 · el almacén de conexiones de W está VIVO dentro del binario (/health → datos)
 *   3 · Conectores.dc.html + sus módulos vivos viajaron como data (B)
 *   4 · cuarto.pixi.html trae el hook vivo B→C y no resucita el tab Código retirado
 *   5 · la pantalla de Inspección de C viajó (+ el nav con las 3 entradas)
 *   6 · docs/guia viajó · 7 · certifi (TLS real, no un import)
 *   8 · CONDUCTUAL: 200 escrituras seguidas contra el frozen, sin colgarse
 *   9 · CONDUCTUAL: la vara rica corre sobre el frontend servido por ESTE frozen
 *  10 · REGRESIÓN: Ola 1 sigue verde sin importar centro.ui.js
 *
 *   node qa/sonda_bundle_integra5.mjs
 */
import { webkit } from "playwright";
import { spawn, spawnSync, execSync } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const PORT = Number(process.env.SONDA_PORT || 8271);
const BASE = `http://127.0.0.1:${PORT}`;
const DATADIR = mkdtempSync(join(tmpdir(), "sonda5-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  — " + extra : ""}`); if (!c) fails.push(label); };

if (!existsSync(SIDECAR)) { console.log(`✗ no existe el sidecar frozen: ${SIDECAR}`); process.exit(1); }

console.log(`── sidecar FROZEN ${SIDECAR}\n── datadir aislado ${DATADIR}\n`);
const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  stdio: ["ignore", "pipe", "pipe"],
});
let salida = "";
proc.stdout.on("data", (d) => (salida += d));
proc.stderr.on("data", (d) => (salida += d));

// esperar el boot (hasta 60 s: el onefile descomprime en el primer arranque)
let vivo = false, health = null;
for (let i = 0; i < 120; i++) {
  try { const r = await fetch(BASE + "/health"); if (r.ok) { health = await r.json(); vivo = true; break; } } catch {}
  await sleep(500);
}
ok(vivo, "el sidecar frozen arranca y contesta /health", vivo ? `build=${health.proceso?.build}` : salida.slice(-400));
if (!vivo) { proc.kill(); process.exit(1); }

const get = async (p) => { const r = await fetch(BASE + p); return { status: r.status, body: r.ok ? await r.text() : "" }; };

try {
  // ── 2 · el almacén de W, VIVO dentro del binario ────────────────────────────────────
  // No se prueba "el archivo sqlite_db viajó" sino que el ALMACÉN está funcionando: el
  // watchdog sólo puede reportar `conexiones_libres` si `_LIBRES` existe y `conectar()`
  // está prestando de ahí. Si el binario tuviera el sqlite_db viejo, esta clave no sale.
  ok(!!health.datos, "2 · el camino de datos se REPORTA (watchdog de W en el binario)", JSON.stringify(health.datos));
  ok(health.datos && health.datos.estado === "ok" && typeof health.datos.conexiones_libres === "number",
     "2 · el ALMACÉN de conexiones está vivo (conexiones_libres es un número)", JSON.stringify(health.datos));

  // ── 3 · lo de B viajó como data ─────────────────────────────────────────────────────
  const cx = await get("/Conectores.dc.html");
  ok(cx.status === 200 && /Lo que tenés|localPopulation/i.test(cx.body),
     "3 · Conectores.dc.html se sirve del binario", `HTTP ${cx.status}`);
  // [ADAPTADOR 2026-08-04] `conectores.ui.js` se demolió. Lo que tiene que viajar ahora son
  // las cuatro piezas del adaptador — y las CUATRO, porque si falta una la pantalla queda en
  // blanco con un 404 mudo en la consola, que es justo lo que esta sonda existe para agarrar.
  for (const [f, marca] of [["montaje.js", /montar|recargar/], ["superficie.js", /pintarCard/],
                            ["widget.js", /derivar/], ["conocimiento.js", /REGLAS/],
                            ["fuentes.js", /conexiones\/fuentes/]]) {
    const r = await get("/conectores/" + f);
    ok(r.status === 200 && marca.test(r.body), `3 · conectores/${f} viajó`,
       `HTTP ${r.status} · ${r.body.length}B`);
  }
  const uiVieja = await get("/conectores/conectores.ui.js");
  ok(uiVieja.status === 404, "3 · conectores.ui.js no viaja: quedó demolido",
     `HTTP ${uiVieja.status}`);
  for (const f of ["cuarto.hook.js", "centro.api.js"]) {
    const r = await get("/conexiones/" + f);
    ok(r.status === 200 && r.body.length > 500, `3 · conexiones/${f} viajó`, `HTTP ${r.status} · ${r.body.length}B`);
  }
  const muerto = await get("/conexiones/centro.ui.js");
  ok(muerto.status === 404, "3 · centro.ui.js no viaja: quedó muerto", `HTTP ${muerto.status}`);

  // ── 4 · el contrato B→C, en el archivo EMPAQUETADO ──────────────────────────────────
  const pixi = await get("/cuarto/cuarto.pixi.html");
  ok(pixi.status === 200, "4 · cuarto.pixi.html se sirve del binario", `HTTP ${pixi.status}`);
  ok(/<script type="module" src="\.\.\/conexiones\/cuarto\.hook\.js"><\/script>/.test(pixi.body),
     "4 · trae el <script> de conexiones/cuarto.hook.js");
  ok(!/<script type="module" src="\.\.\/conexiones\/codigo\.js"><\/script>/.test(pixi.body),
     "4 · el tab Código retirado no vuelve a inyectarse");
  // el botón del punto 34, dentro del widget de controles
  ok(/id="slotsBtn"/.test(pixi.body) && pixi.body.indexOf('id="slotsBtn"') > pixi.body.indexOf('id="camBody"'),
     "4 · el botón «＋ Casillas» viaja DENTRO del widget ⊙ (punto 34)");

  // ── 5 · la pantalla de C + el nav de los tres ───────────────────────────────────────
  const insp = await get("/inspeccion/inspeccion.html");
  ok(insp.status === 200 && /Inspecci/i.test(insp.body), "5 · inspeccion/inspeccion.html viajó (C)", `HTTP ${insp.status}`);
  const nav = await get("/nav.js");
  ok(nav.status === 200 && /Conectores\.dc\.html/.test(nav.body) &&
     /inspeccion\/inspeccion\.html/.test(nav.body),
     "5 · el nav empaquetado entra directo a Conectores e Inspección");

  // ── 6 · docs/guia — NO se sirve por HTTP: lo LEE el Guía del disco (poder SABE, T5) ──
  // Por eso la sonda no pide una URL: mira el _MEIPASS del proceso frozen que está corriendo,
  // que es lo que `aleph_paths.resource_root()` devuelve adentro del bundle. Y comprueba
  // ADEMÁS que la ruta vieja (`_REPO = parents[4]`) NO los encuentra — que era el bug: los MD
  // viajaban y el Guía igual se quedaba sin base de conocimiento, en silencio.
  const meipass = (() => {
    try {
      const dirs = execSync(`ls -dt /var/folders/*/*/T/_MEI* 2>/dev/null || true`, { shell: "/bin/bash" })
        .toString().trim().split("\n").filter(Boolean);
      return dirs.find((d) => existsSync(join(d, "docs", "guia"))) || dirs[0] || null;
    } catch { return null; }
  })();
  const mds = ["cuarto.es.md", "cuarto.en.md", "cerebros.es.md", "sala.es.md", "piezas.es.md",
               "conectar.es.md", "memoria.es.md"];
  const faltan = meipass ? mds.filter((m) => !existsSync(join(meipass, "docs", "guia", m))) : mds;
  ok(!!meipass && faltan.length === 0, "6 · docs/guia viajó al binario (los MD del poder SABE)",
     meipass ? `${meipass}/docs/guia · faltan: ${faltan.length}` : "no encontré el _MEIPASS del proceso");
  if (meipass) {
    // la ruta VIEJA, para dejar constancia de por qué el fix hacía falta
    const rota = join(meipass, "..", "..");
    ok(!existsSync(join(rota, "docs", "guia")),
       "6 · (constancia) la ruta vieja `parents[4]` NO los encontraba — de ahí el fix a resource_root()");
  }

  // ── 7 · certifi — TLS REAL, no un import ────────────────────────────────────────────
  const tls = await fetch(BASE + "/v1/motor/estado?tipo=key&ref=groq", { headers: { accept: "application/json" } })
    .then((r) => r.json()).catch((e) => ({ error: String(e) }));
  const txt = JSON.stringify(tls);
  ok(!/CERTIFICATE_VERIFY_FAILED|SSLCertVerificationError|unable to get local issuer/i.test(txt),
     "7 · certifi: una salida TLS real no falla por cadena de certificados", txt.slice(0, 120));

  // ── 1 · la franja deep-chat (dueña del composer) ≥250px en el bundle ─────────────────
  const browser = await webkit.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  await page.goto(BASE + "/sala/sala.html", { waitUntil: "load" });
  await page.waitForSelector("#chatBody deep-chat", { state: "visible", timeout: 15000 });
  const comp = await page.evaluate(() => {
    const c = document.querySelector("#chatBody deep-chat");
    if (!c) return { falta: true };
    const r = c.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), visible: r.width > 0 && r.height > 0,
             shadow: !!c.shadowRoot };
  });
  ok(!comp.falta && comp.visible && comp.shadow && comp.w >= 250,
     `1 · deep-chat (dueño del composer) mide ${comp.w}px en el bundle`, "mínimo 250px");
  await page.screenshot({ path: join(ROOT, "reports/step5/sonda-bundle-composer.png") });
  await browser.close();

  // ── 8 · CONDUCTUAL · 200 escrituras seguidas sin colgarse ───────────────────────────
  // Es la prueba de que el arreglo de W viaja: con el patrón viejo (open/close por
  // operación) el proceso se traba en el mutex del VFS y deja de contestar PARA SIEMPRE.
  console.log("\n── 8 · 200 escrituras seguidas contra el frozen ──");
  const t0 = Date.now();
  let okN = 0, err = 0, colgadas = 0;
  for (let i = 0; i < 200; i++) {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 10000);          // sin plazo, un cuelgue se ve como "lento"
    try {
      const r = await fetch(BASE + "/v1/auth/local", {
        method: "POST", signal: ctl.signal,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ device_id: `sonda5-${i}` }),
      });
      if (r.ok) okN++; else err++;
      await r.text();
    } catch (e) { if (String(e).includes("abort")) colgadas++; else err++; }
    finally { clearTimeout(to); }
  }
  const ms = Date.now() - t0;
  ok(colgadas === 0, `8 · 200 escrituras seguidas: 0 COLGADAS`, `ok=${okN} err=${err} colgadas=${colgadas} · ${ms}ms`);
  ok(okN === 200, "8 · las 200 respondieron 200", `ok=${okN}/200`);

  // y DESPUÉS sigue vivo (el deadlock es permanente: si sobrevivió acá, no se trabó)
  const post = await fetch(BASE + "/health").then((r) => r.json()).catch(() => null);
  ok(post && post.datos && post.datos.estado === "ok",
     "8 · tras las 200, el camino de datos SIGUE sano (no quedó trabado)", JSON.stringify(post && post.datos));

  // ── 9 · la sección rica, ejercida DESDE el frontend que viajó en el onefile ─────────
  console.log("\n── 9 · Conectores rica contra el frontend frozen ──");
  const ricaRun = spawnSync(process.execPath,
    [join(ROOT, "product/app/design/conectores/verify_conectores_rica.mjs")], {
      cwd: ROOT, stdio: "inherit", timeout: 120000,
      env: { ...process.env, SIDECAR: BASE },
    });
  ok(ricaRun.status === 0,
     "9 · Conectores rica pasa completa contra ESTE frozen",
     `exit=${ricaRun.status}${ricaRun.signal ? " signal=" + ricaRun.signal : ""}`);

  // ── 10 · la vara que retenía centro.ui.js, ahora contra la superficie nueva ─────────
  console.log("\n── 10 · Ola 1 sin centro.ui.js ──");
  const ola1Run = spawnSync(process.execPath,
    [join(ROOT, "product/app/design/cuarto/verify_reforma_ola1.mjs")], {
      cwd: ROOT, stdio: "inherit", timeout: 180000,
      env: { ...process.env, SIDECAR: BASE },
    });
  ok(ola1Run.status === 0,
     "10 · verify_reforma_ola1 queda verde con centro.ui.js muerto",
     `exit=${ola1Run.status}${ola1Run.signal ? " signal=" + ola1Run.signal : ""}`);
} catch (e) {
  ok(false, "la sonda corrió sin excepción", String(e && e.message || e));
} finally {
  proc.kill();
}

console.log(`\n${fails.length === 0 ? "VERDE" : "ROJO"} · ${fails.length} fallo(s)`);
if (fails.length) { fails.forEach((f) => console.log("  ✗ " + f)); process.exit(1); }
