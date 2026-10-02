/* verify_cuarto_semaforo.mjs — HARNESS del SEMÁFORO (CUARTO HONESTO · T2 · §3).
 *
 * Front-only (patrón verify_cuarto_guide): http.server propio + page.route stub del Motor de
 * Verdad (/v1/motor/estado + /v1/motor/probar) con estados CONTROLABLES por ref. Prueba que la
 * UI pinta los 5 estados de §1 y que cada no-verde trae su botón-workflow, en las 6 superficies:
 *   0. smoke: monta + CuartoSemaforo presente + CSS inyectado.
 *   1. los 5 estados → badge correcto (emoji, clase, data-estado, botón).
 *   2. botonDe: el workflow exacto por estado/causa (§3).
 *   3. contrato: leerEstado (GET) + probar (POST) hablan el shape del motor real.
 *   4. cards de Conectar (paleta): badge §1 honesto no-verde derivado de metadata.
 *   5. selector de cerebro + chip del Guía: estado VERIFICADO por el motor (no "el binario existe").
 *   6. piezas del diorama (canvas) + lista: glifo/badge desde el motor; [Probar] → verde real.
 *   7. botón Ejecutar: deshabilitado + lista clickeable cuando una precondición está incumplida.
 *
 * Correr: node product/app/design/cuarto/verify_cuarto_semaforo.mjs   (necesita node_modules symlink)
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = Number(process.env.FRONT_PORT || 8177);   // libre · ≠ verify_cuarto_guide (:8162)
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let pass = 0, fail = 0; const fails = [];
const ok = (c, m) => { if (c) { pass++; console.log("  ✓", m); } else { fail++; fails.push(m); console.log("  ✗", m); } };
const J = (o) => JSON.stringify(o);

// ── estado del motor CONTROLABLE por ref (vive en Node; la route lo lee en vivo) ──
const motorState = {};   // ref → { estado, causa? }
const ts = () => Math.floor(Date.now() / 1000);
const motorResult = (tipo, ref, forceDefault) => {
  const s = motorState[ref] || { estado: forceDefault || "detectado" };
  return { tipo, ref, estado: s.estado, causa: s.estado === "roto" ? (s.causa || "error_upstream") : null,
    evidencia: { model_final: "stub", motivo: "verify" }, ts: ts(), cacheado: false, fresco: s.estado !== "detectado" };
};

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
let browser;
try {
  await sleep(900);
  browser = await chromium.launch();
  const page = await (await browser.newContext()).newPage();
  const jsErrors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) jsErrors.push(m.text()); });
  page.on("pageerror", (e) => jsErrors.push(String(e)));

  // ── ROUTES · catch-all PRIMERO, específicas después (gana la última registrada) ──
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ atoms: [], total: 0 }) }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ providers: { claude_cli: { state: "ready", extra: { subscriptionType: "max" } }, codex_cli: { state: "no_auth" } } }) }));
  await page.route("**/v1/cuarto/guide", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ content: "(stub)", tool_calls: [], model_final: "stub" }) }));
  // EL MOTOR — controlado por motorState
  await page.route("**/v1/motor/estado**", (r) => {
    const u = new URL(r.request().url());
    r.fulfill({ status: 200, contentType: "application/json", body: J(motorResult(u.searchParams.get("tipo"), u.searchParams.get("ref"))) });
  });
  await page.route("**/v1/motor/probar", (r) => {
    let b = {}; try { b = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
    // POST /probar = acción explícita → si no hay estado seteado, default PROBADO (verde tras probar).
    r.fulfill({ status: 200, contentType: "application/json", body: J(motorResult(b.tipo, b.ref, "probado")) });
  });

  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.CuartoSemaforo && window.__cuarto && window.__semHooks, null, { timeout: 15000 });
  await sleep(500);

  // ══ 0 · SMOKE ══════════════════════════════════════════════════════════════════
  console.log("\n§0 · smoke");
  const smoke = await page.evaluate(() => ({
    api: !!window.CuartoSemaforo, css: !!document.getElementById("cuarto-semaforo-css"),
    estados: Object.keys((window.CuartoSemaforo || {}).ESTADOS || {}).sort().join(","),
  }));
  ok(smoke.api, "CuartoSemaforo global presente");
  ok(smoke.css, "CSS del semáforo inyectado (#cuarto-semaforo-css)");
  ok(smoke.estados === "detectado,no_configurado,premium,probado,roto", `los 5 estados de §1: ${smoke.estados}`);

  // ══ 1 · LOS 5 ESTADOS → BADGE ══════════════════════════════════════════════════
  console.log("\n§1 · los 5 estados pintan");
  const cinco = await page.evaluate(() => {
    const S = window.CuartoSemaforo;
    const casos = [
      { estado: "probado", ts: Math.floor(Date.now() / 1000) - 120 },
      { estado: "detectado" },
      { estado: "roto", causa: "falta_key" },
      { estado: "no_configurado" },
      { estado: "premium" },
    ];
    return casos.map((res) => {
      const el = document.createElement("div");
      S.pintarBadge(el, Object.assign({ tipo: "mcp", ref: "x", evidencia: {} }, res), {});
      const btn = el.querySelector(".sem-accion");
      return { estado: el.getAttribute("data-estado"), luz: (el.querySelector(".sem-luz") || {}).textContent,
        cls: el.className, sub: (el.querySelector(".sem-sub") || {}).textContent || "",
        boton: btn ? btn.textContent : null, accion: btn ? btn.dataset.accion : null };
    });
  });
  const byEstado = Object.fromEntries(cinco.map((c) => [c.estado, c]));
  ok(byEstado.probado && byEstado.probado.luz === "🟢" && /sem-verde/.test(byEstado.probado.cls) && /hace 2 min/.test(byEstado.probado.sub), "🟢 probado — verde + 'probado hace 2 min' + sin botón forzado");
  ok(byEstado.probado && byEstado.probado.boton === null, "🟢 probado no fuerza botón");
  ok(byEstado.detectado && byEstado.detectado.luz === "🟡" && byEstado.detectado.accion === "probar" && /Probar ahora/.test(byEstado.detectado.boton), "🟡 detectado — amber + [Probar ahora]");
  // [FIX-P1B · §7] el rótulo pasó de «Poner la key» a «Poner la llave»: la tabla es ley y
  // la ley dice que en la UI no hay vocabulario de máquina. La ACCIÓN (credencial) no
  // cambió — es el contrato con las 6 superficies; lo que cambió es la palabra que se lee.
  ok(byEstado.roto && byEstado.roto.luz === "🔴" && byEstado.roto.accion === "credencial" && /llave/i.test(byEstado.roto.boton), "🔴 roto/falta_key — rojo + [Poner la llave]");
  ok(byEstado.no_configurado && byEstado.no_configurado.luz === "⚪" && byEstado.no_configurado.accion === "configurar", "⚪ no_configurado — [Configurar]");
  ok(byEstado.premium && byEstado.premium.luz === "🔒" && byEstado.premium.accion === "premium", "🔒 premium — [Ver premium]");

  // ══ 2 · botonDe → workflow exacto (§3) ══════════════════════════════════════════
  console.log("\n§2 · el botón-workflow por causa");
  const workflows = await page.evaluate(() => {
    const S = window.CuartoSemaforo, mk = (estado, causa) => S.botonDe({ estado, causa }) || {};
    return {
      sinRed: mk("roto", "sin_red").accion, cli: mk("roto", "cli_no_instalado").accion,
      login: mk("roto", "sin_sesion").accion, timeout: mk("roto", "timeout").accion,
      upstream: mk("roto", "error_upstream").accion, key: mk("roto", "falta_key").accion,
    };
  });
  ok(workflows.key === "credencial", "falta_key → credencial");
  ok(workflows.cli === "instalar", "cli_no_instalado → instalar");
  ok(workflows.login === "login", "sin_sesion → login");
  ok(workflows.sinRed === "reintentar" && workflows.timeout === "reintentar" && workflows.upstream === "reintentar", "sin_red/timeout/error_upstream → reintentar");

  // ══ 3 · CONTRATO leerEstado (GET) + probar (POST) ═══════════════════════════════
  console.log("\n§3 · contrato contra el motor (stub)");
  motorState["svcRoto"] = { estado: "roto", causa: "falta_key" };
  const contrato = await page.evaluate(async () => {
    const S = window.CuartoSemaforo;
    const g = await S.leerEstado("mcp", "svcRoto");
    const p = await S.probar("cerebro", "brainX");   // sin estado seteado → default probado
    return { g, p };
  });
  ok(contrato.g && contrato.g.estado === "roto" && contrato.g.causa === "falta_key", "leerEstado devuelve {estado:roto, causa:falta_key}");
  ok(contrato.p && contrato.p.estado === "probado" && contrato.p.tipo === "cerebro", "probar devuelve {estado:probado} tipado");

  // ══ 4 · CARDS DE CONECTAR (paleta) ══════════════════════════════════════════════
  console.log("\n§4 · cards de Conectar (paleta)");
  const paleta = await page.evaluate(() => {
    window.__buildPalette([
      { key: "k1", label: "Tool libre", category: "process", atom: "tool", auth: "keyless", catalogKind: "public_mcp", armario: "apps", zone: "mesa" },
      { key: "k2", label: "Conector con llave", category: "read", atom: "conexion", auth: "token", catalogKind: "account_connector", armario: "apps", zone: "fuentes" },
    ]);
    const chips = [...document.querySelectorAll("#paletteList .chip")];
    return chips.map((c) => { const b = c.querySelector(".sem-badge"); return { label: (c.querySelector(".t") || {}).textContent || "", estado: b ? b.getAttribute("data-estado") : null, luz: b ? (b.querySelector(".sem-luz") || {}).textContent : null }; });
  });
  const libre = paleta.find((p) => /libre/i.test(p.label)), conKey = paleta.find((p) => /llave/i.test(p.label));
  ok(libre && libre.estado === "detectado" && libre.luz === "🟡", "card keyless → 🟡 detectado (sin probar)");
  ok(conKey && conKey.estado === "no_configurado" && conKey.luz === "⚪", "card con llave → ⚪ no_configurado (necesita llave)");
  ok(paleta.every((p) => p.estado !== "probado"), "ninguna card muestra 🟢 sin evidencia del motor");

  // ══ 5 · SELECTOR DE CEREBRO + CHIP DEL GUÍA ═════════════════════════════════════
  console.log("\n§5 · cerebro del agente + del Guía (verificado por el motor)");
  const cerebro = await page.evaluate(async () => {
    const nuc = window.__cuarto.nucleoData();
    window.__openInspector(nuc);
    await new Promise((r) => setTimeout(r, 300));
    const mount = document.getElementById("brainSemMount");   // el mount SE CONVIERTE en el badge
    const guia = document.getElementById("guideSemMount");
    return { hayBadge: !!(mount && mount.classList.contains("sem-badge")), estado: mount ? mount.getAttribute("data-estado") : null,
      tieneBoton: !!(mount && mount.querySelector(".sem-accion")), guiaBadge: !!(guia && guia.classList.contains("sem-badge")) };
  });
  ok(cerebro.hayBadge, "el selector de cerebro pinta el semáforo del cerebro activo (#brainSemMount)");
  ok(cerebro.estado === "detectado" && cerebro.tieneBoton, "cerebro sin probar → 🟡 + [Probar ahora] (no verde por 'existe')");
  ok(cerebro.guiaBadge, "el chip del Guía muestra el estado de su cerebro (#guideSemMount)");
  // click [Probar ahora] del cerebro → el motor (stub) responde probado → verde
  const probado = await page.evaluate(async () => {
    const btn = document.querySelector("#brainSemMount .sem-accion"); if (!btn) return { ok: false };
    btn.click();
    for (let i = 0; i < 40; i++) { await new Promise((r) => setTimeout(r, 50)); const b = document.getElementById("brainSemMount"); if (b && b.getAttribute("data-estado") === "probado") return { ok: true }; }
    return { ok: false, got: (document.getElementById("brainSemMount") || {}).getAttribute("data-estado") };
  });
  ok(probado.ok, "[Probar ahora] del cerebro → 🟢 probado tras el ping real (motor)");

  /* ══ 6 · PIEZAS DEL DIORAMA (canvas) + EL PIE DE SU ARCO ═════════════════════════
   * [FIX-P3 · §7] LA FILA MURIÓ: «el estado → el anillo». Las dos superficies que dicen el
   * estado de una pieza son ahora el ANILLO del diorama (tileVerdad) y la LÍNEA AL PIE de su
   * arco. Se miden las dos, y se exige que digan LO MISMO — que es más estricto que lo de
   * antes: la fila y el anillo se leían por separado y podían discrepar sin que nadie lo
   * notara. Además el pie tiene que nombrar la CAUSA, no sólo el color. */
  console.log("\n§6 · piezas del diorama + el pie de su arco");
  motorState["mcpRoto"] = { estado: "roto", causa: "sin_red" };
  const pieza = await page.evaluate(async () => {
    // pieza MCP rota (server=mcpRoto) + pieza tool sin probar
    window.__cuarto.placeTile({ id: "pz-roto", atom: "tool", category: "process", label: "MCP roto", server: "mcpRoto", belt_ref: "mcpRoto", tools: ["t"] });
    await new Promise((r) => setTimeout(r, 600));
    window.__openAbanico(window.__cuarto.pieceData("pz-roto"));
    await new Promise((r) => setTimeout(r, 250));
    const pie = window.__abanicoEstado();
    const canvas = window.__cuarto.tileVerdadState ? window.__cuarto.tileVerdadState("pz-roto") : null;
    try { window.__closeAbanico(); } catch (e) {}
    return { pie, canvas };
  });
  ok(pieza.pie && pieza.pie.estado === "roto", "el pie del arco de la pieza dice 🔴 roto desde el motor", JSON.stringify(pieza.pie));
  ok(pieza.pie && /conexi/i.test(pieza.pie.txt || ""), "…y NOMBRA la causa, no sólo el color", pieza.pie && pieza.pie.txt);
  ok(pieza.pie && pieza.pie.ayuda, "…con su [?] al lado (§10: la UI opera, docs/guia explica)");
  ok(pieza.canvas && pieza.canvas.estado === "roto" && typeof pieza.canvas.color === "number", "el glifo del canvas (tileVerdad) refleja el estado del motor");
  ok(pieza.pie && pieza.canvas && pieza.pie.estado === pieza.canvas.estado, "el anillo y el pie del arco dicen EL MISMO estado", `${pieza.pie && pieza.pie.estado} ↔ ${pieza.canvas && pieza.canvas.estado}`);

  // ══ 7 · BADGE DE LISTO-PARA-LA-SALA · precondiciones ════════════════════════════
  // ⚠️ REALINEADO [Cuarto entrega, no corre]. Antes esto probaba "el botón Ejecutar queda
  // DESHABILITADO": ese botón ya no existe — correr es de La Sala. El preflight no se borró,
  // cambió de trabajo: avisa ANTES de entregar, con una línea y UN botón que lleva al arreglo.
  // Lo que se prueba ahora es eso, que es más fuerte: no basta con frenar, hay que dar el paso.
  console.log("\n§7 · el badge dice qué falta y ofrece el arreglo");
  const run = await page.evaluate(async () => {
    await window.__preflight();
    await new Promise((r) => setTimeout(r, 150));
    const box = document.getElementById("listo");
    const btn = document.getElementById("listoBtn");
    const pf = document.getElementById("preflight");
    const rows = [...document.querySelectorAll("#preflightList .pf-row")];
    const fixes = rows.map((r) => { const b = r.querySelector(".pf-fix"); return b ? b.dataset.accion : null; }).filter(Boolean);
    return { estado: box.dataset.estado, texto: document.getElementById("listoTxt").textContent.trim(),
             cta: btn.textContent.trim(), ctaVisible: !btn.hidden,
             pfShown: !pf.hidden, filas: rows.length, fixes };
  });
  ok(run.estado === "roto", "con una precondición rota el badge lo DICE", `estado=${run.estado}`);
  ok(run.texto.length > 0 && run.texto.split("\n").length === 1, "…en UNA línea", `"${run.texto}"`);
  ok(run.ctaVisible && run.cta.length > 0, "…y SIEMPRE con un botón (nunca el dato solo)", `[${run.cta}]`);
  ok(run.pfShown && run.filas >= 1, "el detalle se abre con la lista de qué falta");
  ok(run.fixes.length >= 1, `cada ítem trae su botón-workflow (${run.fixes.join(",")})`);
  // arreglo REAL vía el motor: la pieza pasa a probado → el badge deja de estar en rojo
  motorState["mcpRoto"] = { estado: "probado" };
  const habilitado = await page.evaluate(async () => {
    for (let i = 0; i < 60; i++) {
      await window.__preflight();
      await new Promise((r) => setTimeout(r, 60));
      const e = document.getElementById("listo").dataset.estado;
      if (e !== "roto") return { ok: true, estado: e, cta: document.getElementById("listoBtn").textContent.trim() };
    }
    return { ok: false };
  });
  ok(habilitado.ok, `tras arreglar la precondición (motor → probado), el badge SALE de rojo`,
     `estado=${habilitado.estado} cta=[${habilitado.cta}]`);

  // ── JS errors ────────────────────────────────────────────────────────────────
  console.log("");
  ok(jsErrors.length === 0, `0 errores JS de consola${jsErrors.length ? " — " + jsErrors.slice(0, 4).join(" | ") : ""}`);

} catch (e) {
  console.error("HARNESS ERROR:", e && e.stack || e);
  fail++; fails.push("harness crash: " + (e && e.message || e));
} finally {
  try { if (browser) await browser.close(); } catch (e) {}
  try { server.kill(); } catch (e) {}
}

console.log(`\n${fail === 0 ? "✅ VERDE" : "❌ ROJO"} — ${pass} ok / ${fail} fail`);
if (fails.length) { console.log("FALLAS:"); fails.forEach((f) => console.log("  ✗", f)); }
process.exit(fail === 0 ? 0 : 1);
