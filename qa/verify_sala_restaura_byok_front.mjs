/* verify_sala_restaura_byok_front.mjs — el navegador de la vara. La corre
 * `qa/verify_sala_restaura_byok.py`; imprime una línea JSON con los testigos. No se invoca
 * suelta: la vara es una sola, como manda la casa.
 *
 * EL TESTIGO ES LA RECETA EFECTIVA, no el DOM: `window.__salaCerebro.aCorrer()` es lo que la
 * Sala va a mandar a correr —el final de la cadena del frente— y lo dejó ahí la obra B justo
 * para que una vara entre por el camino real en vez de rearmar la lógica y medir su espejo.
 *
 * MODOS (`ALEPH_VARA_MODO`):
 *   positivo      — el árbol tal cual está
 *   negativo      — se sirve la Sala con el código VIEJO en el lugar del nuevo, para probar
 *                   que este testigo CAE con el bug puesto. Se hace con `page.route()`: el
 *                   archivo del repo no se toca, así que un corte no deja el árbol sucio.
 *   discriminante — mismo árbol, fixture con un CLI elegido
 */
import { spawn } from "node:child_process";
import { createServer as netCreateServer } from "node:net";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import("playwright");

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
// [H5b] `join(RAIZ, "product/backend/.venv/…")` afirmaba que la vara corre desde el árbol
// PRINCIPAL: el venv es local y no viaja a un worktree. Medido el 2026-08-08: verde en
// aleph-base, y acá se anotaba `ok:false · "sin venv del backend"` — que se lee como un
// fallo del producto y era un intérprete que no estaba donde la vara creía.
const { pythonDelBackend } = await import(join(RAIZ, "qa", "lib", "node_deps.mjs"));
const PY = pythonDelBackend(RAIZ);
const MODO = process.env.ALEPH_VARA_MODO || "positivo";
const R = {};
const anotar = (n, ok, detalle) => { R[n] = { ok, detalle }; };

/** UN PUERTO LIBRE, PEDIDO AL SISTEMA. Con uno fijo, un sidecar huérfano de una corrida
 *  anterior contesta el /health y se mide un proceso cuyo fixture ya se borró. */
function puertoLibre() {
  const srv = netCreateServer();
  return new Promise((resolve, reject) => {
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => { const p = srv.address().port; srv.close(() => resolve(p)); });
  });
}
const PUERTO = Number(process.env.ALEPH_VARA_PORT || await puertoLibre());
const BASE = `http://127.0.0.1:${PUERTO}`;

if (!existsSync(PY)) {
  console.log(JSON.stringify({ "1_positivo": { ok: false, detalle: "sin venv del backend" } }));
  process.exit(1);
}

/* ── el backend REAL contra el fixture ──────────────────────────────────────────────── */
const CONGELADO = (process.env.ALEPH_VARA_SIDECAR || "").trim();
const ARRANQUE = CONGELADO
  ? [CONGELADO, ["--port", String(PUERTO)]]
  : [PY, [join(RAIZ, "deploy/fase4/sidecar_serve.py"), "--port", String(PUERTO)]];
const server = spawn(ARRANQUE[0], ARRANQUE[1], {
  cwd: RAIZ,
  env: {
    ...process.env,
    ALEPH_DATA_DIR: process.env.ALEPH_DATA_DIR || "",
    PYTHONPATH: [join(RAIZ, "product/backend"), join(RAIZ, "platform"), process.env.PYTHONPATH || ""]
      .filter(Boolean).join(":"),
  },
  stdio: ["ignore", "pipe", "pipe"],
  // GRUPO PROPIO: un PyInstaller onefile lanza un HIJO; matar sólo al padre deja el puerto
  // tomado y node sin terminar.
  detached: true,
});
server.stdout.on("data", () => {});
server.stderr.on("data", () => {});
const cerrar = () => { try { process.kill(-server.pid, "SIGKILL"); } catch (_) { /* ya murió */ } };
process.on("exit", cerrar);

async function esperarVivo(ms = 60000) {
  const hasta = Date.now() + ms;
  while (Date.now() < hasta) {
    try {
      const r = await fetch(`${BASE}/health`);
      if (r.ok) return true;
    } catch (_) { /* todavía no */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

/* EL CÓDIGO VIEJO, TAL CUAL ESTABA. Se usa SÓLO en modo negativo. Vive acá y no en el
 * archivo del producto: si el negativo editara el repo, un corte lo dejaría con el bug
 * puesto. */
const NUEVO_MARCA = "var puente=_modelsApi&&_modelsApi.curadoDesdeFila";
const VIEJO = `
      elegido=vivo.id;
      ST.power=elegido; ST.controls.model=elegido;
      ST.controls.cliModel=''; ST.controls.effort=''; ST.byok=null;
      return true;
    }`;

let browser;
try {
  if (!await esperarVivo()) {
    anotar("0_el_backend_arranca", false, "el sidecar no respondió /health");
    throw new Error("sidecar muerto");
  }
  browser = await chromium.launch();
  const ctx = await browser.newContext();
  // LA SESIÓN Y EL DUEÑO VIAJAN. Con un `user_id` inventado, `/v1/users/<id>/keys` da 403
  // (el cierre de la fuga entre cuentas, funcionando) y la Sala no llega a armar el turno:
  // la vara mediría su propio error y se lo cobraría al producto.
  await ctx.addInitScript(([t, uid]) => {
    const u = { id: uid, session_token: t };
    try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
    try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (_) { /* ignorado */ }
  }, [process.env.ALEPH_VARA_TOKEN || "", process.env.ALEPH_VARA_OWNER || ""]);

  const page = await ctx.newPage();

  if (MODO === "negativo") {
    await page.route("**/sala/sala.html", async (route) => {
      const resp = await route.fetch();
      let html = await resp.text();
      const i = html.indexOf(NUEVO_MARCA);
      if (i < 0) { await route.fulfill({ response: resp }); return; }
      // Se reemplaza desde la marca hasta el cierre de la función por el cuerpo VIEJO.
      const fin = html.indexOf("\n  }", i);
      html = html.slice(0, i) + VIEJO + html.slice(fin + 4);
      await route.fulfill({ response: resp, body: html });
    });
  }

  await page.goto(`${BASE}/sala/sala.html`, { waitUntil: "domcontentloaded", timeout: 90000 });
  // Se espera LA CONDICIÓN, no un reloj: que el hook exista y que los modelos hayan cargado.
  await page.waitForFunction(
    "!!(window.__salaCerebro && window.__salaCerebro.selector && window.__salaCerebro.selector())",
    { timeout: 60000 },
  ).catch(() => {});

  const m = await page.evaluate(() => {
    const h = window.__salaCerebro;
    const sel = (() => { try { return h.selector(); } catch (_) { return null; } })();
    const receta = (() => { try { const r = h.aCorrer(); return r && r.model; } catch (_) { return null; } })();
    const power = (() => { try { return h.power(); } catch (_) { return null; } })();
    return { power, receta, seleccion: sel && sel.seleccion, seleccion_id: sel && sel.seleccion_id };
  });

  /* LA FILA QUE EL SIDECAR ENTREGÓ — el testigo se compara CONTRA ELLA, no contra un
   * literal escrito acá. Un literal mediría que el fixture no cambió, no que la traducción
   * conserva lo que el backend mandó. */
  const fila = await page.evaluate(async () => {
    const u = JSON.parse(sessionStorage.getItem("puppet_user") || "{}");
    const r = await fetch("/v1/modelos/selector?contexto=sala",
      { headers: { Authorization: "Bearer " + (u.session_token || "") } });
    const j = await r.json();
    const s = (j.modelos || []).find((x) => x.slug === j.seleccion) || null;
    return s && { slug: s.slug, model: s.model, base_url: s.base_url, byok_ref: s.byok_ref,
                  brain_provider: s.brain_provider, picker_id: s.picker_id };
  });

  if (MODO === "discriminante") {
    anotar("3a_un_cli_no_se_vuelve_byok", m.power !== "tuapi" && m.power === "claude_cli",
           { power: m.power, seleccion: m.seleccion });
    anotar("3b_la_receta_no_es_byok", !!m.receta && m.receta.alias !== "byok",
           { alias: m.receta && m.receta.alias, primary: m.receta && m.receta.primary });
  } else {
    anotar("1a_power_es_tuapi", m.power === "tuapi", m.power);
    anotar("1b_la_receta_lleva_el_modelo",
      !!(m.receta && m.receta.primary && m.receta.base_url),
      { primary: m.receta && m.receta.primary, base_url: m.receta && m.receta.base_url });
    // Y son LOS MISMOS que entregó el sidecar: que estén llenos no alcanza si son otros.
    anotar("1c_es_el_modelo_que_entrego_el_sidecar",
      !!(fila && m.receta && m.receta.primary === fila.model && m.receta.base_url === fila.base_url),
      { receta: m.receta && m.receta.primary, fila: fila && fila.model });
    anotar("1d_la_seleccion_es_la_persistida", m.seleccion === "api.openrouter",
      { seleccion: m.seleccion, seleccion_id: m.seleccion_id });
  }
} catch (e) {
  anotar(MODO === "discriminante" ? "3_discriminante" : "1_positivo", false, String(e).slice(0, 300));
} finally {
  if (browser) await browser.close().catch(() => {});
  cerrar();
}

console.log(JSON.stringify(R));
