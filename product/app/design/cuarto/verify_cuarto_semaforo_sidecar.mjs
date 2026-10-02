/* verify_cuarto_semaforo_sidecar.mjs — SEMÁFORO contra el SIDECAR REAL (CUARTO HONESTO · T2 · §3).
 *
 * A diferencia de verify_cuarto_semaforo.mjs (stubs), acá las llamadas del cliente al Motor de Verdad
 * (/v1/motor/estado + /v1/motor/probar) se PROXEAN al sidecar REAL (uvicorn montando build_motor_router,
 * cero stubs). Prueba que el cliente del semáforo habla el contrato REAL del motor T1 y que la UI pinta
 * el estado VERIFICADO que devuelve el motor de verdad (no un stub).
 *
 * Requiere el sidecar corriendo (lo levanta el runner):
 *   PYTHONPATH=product/backend python3 -m uvicorn motor_sidecar:app --port 8188
 * Correr: MOTOR_SIDECAR=http://127.0.0.1:8188 node .../verify_cuarto_semaforo_sidecar.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.FRONT_PORT || 8178);
const SIDECAR = process.env.MOTOR_SIDECAR || "http://127.0.0.1:8188";
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const J = (o) => JSON.stringify(o);

let pass = 0, fail = 0; const fails = [];
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; fails.push(m); console.log("  ✗", m); } };

// sanity: el sidecar real está vivo
try {
  // [P1A] /health responde {status:"ok",…} — nunca tuvo un campo `ok`, así que este guard
  // salía por process.exit(2) contra CUALQUIER sidecar y la vara no llegaba a medir nada.
  const h = await fetch(SIDECAR + "/health").then((r) => r.json());
  if (!h || h.status !== "ok") throw new Error("health no ok: " + JSON.stringify(h && h.status));
} catch (e) {
  console.error(`❌ sidecar REAL no responde en ${SIDECAR} — levantalo primero. (${e.message})`);
  process.exit(2);
}

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
let browser;
try {
  await sleep(900);
  browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  const jsErrors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) jsErrors.push(m.text()); });
  page.on("pageerror", (e) => jsErrors.push(String(e)));

  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ atoms: [], total: 0 }) }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ providers: {} }) }));
  await page.route("**/v1/cuarto/guide", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ content: "(stub)", tool_calls: [] }) }));
  // ── EL MOTOR: PROXY al sidecar REAL (sin stub) ──────────────────────────────────
  await page.route("**/v1/motor/**", async (route) => {
    const req = route.request(); const u = new URL(req.url());
    const target = SIDECAR + u.pathname + u.search;
    try {
      // [P1A] el proxy TIENE que reenviar el Authorization: POST /v1/motor/probar es
      // owner-gated. Sin esto el sidecar contestaba 401 y las cuatro aserciones de estado
      // medían «sin sesión», no el motor.
      const h = { "Content-Type": "application/json", "Accept": "application/json" };
      const auth = (req.headers() || {}).authorization;
      if (auth) h["Authorization"] = auth;
      const resp = await fetch(target, { method: req.method(), headers: h,
        body: req.method() === "POST" ? (req.postData() || "{}") : undefined });
      route.fulfill({ status: resp.status, contentType: "application/json", body: await resp.text() });
    } catch (e) { route.fulfill({ status: 502, contentType: "application/json", body: J({ detail: String(e) }) }); }
  });

  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.CuartoSemaforo && window.__cuarto, null, { timeout: 15000 });
  await sleep(400);
  // [P1A] sesión REAL por el mismo mecanismo del producto (device user). El `page.route`
  // de arriba stubea todo /v1/** con "[]", así que se pide al sidecar directo y se guarda
  // donde el semáforo la lee (_sessAuth → puppet_user).
  {
    const u = await fetch(SIDECAR + "/v1/auth/local", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: "{}" }).then((r) => r.json()).catch(() => null);
    if (u && u.session_token) await page.evaluate((usr) => {
      sessionStorage.setItem("puppet_user", JSON.stringify(usr));
      localStorage.setItem("puppet_user", JSON.stringify(usr));
    }, u);
    else console.log("  ⚠ sin sesión local: las pruebas del motor van a medir 401");
  }

  console.log(`\n§ contra sidecar REAL (${SIDECAR})`);

  // 1 · el cliente habla el contrato REAL: probar cli claude_cli → verde REAL (detección de sesión)
  const real = await page.evaluate(async () => {
    const S = window.CuartoSemaforo;
    return {
      cli: await S.probar("cli", "claude_cli"),
      cliBad: await S.probar("cli", "zzz-inexistente-xyz"),
      key: await S.probar("key", "GROQ"),
      det: await S.leerEstado("cerebro", "zzz-uncached"),
    };
  });
  const cinco = ["probado", "detectado", "roto", "no_configurado", "premium"];
  ok(cinco.includes(real.cli.estado), `probar(cli,claude_cli) → estado real tipado: ${real.cli.estado}`);
  ok(real.cli.estado === "probado", `CLI real con sesión → 🟢 probado (verde REAL del motor, no stub)`);
  ok(real.cliBad.estado === "no_configurado", `probar(cli,zzz) → no_configurado (provider desconocido, real)`);
  ok(real.key.estado === "no_configurado", `probar(key,GROQ) sin key → no_configurado honesto`);
  ok(real.det.estado === "detectado", `leerEstado(cerebro,zzz) uncached → detectado (barato)`);
  ok(typeof real.cli.ts === "number" && "evidencia" in real.cli, `contrato: {estado,causa,evidencia,ts} presente`);

  // 2 · la UI pinta el estado REAL: badge de prueba desde S.probar real
  const painted = await page.evaluate(async () => {
    const S = window.CuartoSemaforo, el = document.createElement("div"); document.body.appendChild(el);
    const res = await S.probar("cli", "claude_cli");
    S.pintarBadge(el, res, {});
    return { estado: el.getAttribute("data-estado"), luz: (el.querySelector(".sem-luz") || {}).textContent };
  });
  ok(painted.estado === "probado" && painted.luz === "🟢", `la UI pinta 🟢 desde el motor REAL`);

  console.log("");
  ok(jsErrors.length === 0, `0 errores JS de consola${jsErrors.length ? " — " + jsErrors.slice(0, 3).join(" | ") : ""}`);

} catch (e) {
  console.error("HARNESS ERROR:", e && e.stack || e);
  fail++; fails.push("harness crash: " + (e && e.message || e));
} finally {
  try { if (browser) await browser.close(); } catch (e) {}
  try { server.kill(); } catch (e) {}
}

console.log(`\n${fail === 0 ? "✅ VERDE (sidecar real)" : "❌ ROJO"} — ${pass} ok / ${fail} fail`);
if (fails.length) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗", f)); }
process.exit(fail === 0 ? 0 : 1);
