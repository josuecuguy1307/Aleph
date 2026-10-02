/* verify_cuarto_puente.mjs — EL PUENTE DEL CUARTO (Terminal B · §G · §A · §D · §H · §I).
 *
 * WebKit contra el cuarto.pixi.html REAL de este worktree. Los dos módulos de esta terminal
 * (cuarto.hook.js y codigo.js) se INYECTAN en la página, porque cuarto.pixi.html es de otra
 * terminal y no se toca: así se prueba EXACTAMENTE lo que va a pasar cuando C agregue la
 * línea del <script>, sin editarle el archivo.
 *
 * El validador de recetas NO se simula: la ruta se reenvía al sidecar FROZEN instalado
 * (:8226, datadir aislado) para que el veredicto de [Validar] sea el del contrato real.
 *
 * Matriz:
 *   §G  el closet de MCPs tiene SALIDA: ✕ visible · Escape · click afuera (y la cámara vuelve).
 *   §A  [Ver conexión] de una pieza de conexión NAVEGA al Centro, a la fila de esa pieza.
 *   §A  las acciones del semáforo (credencial/configurar) dejan de apilar flujo en el closet
 *       chico y también van al Centro.
 *   §D  [Probar de nuevo] del badge: reintenta UNA vez; si sigue roto MUTA a [Configurar] y navega.
 *   §I  window.AlephConexiones.abrir("context7") → el Centro en esa fila.
 *   §H  tab Código: la receta es EDITABLE con [Validar] de veredicto real (✓ / ✗ con línea y
 *       causa); el handler queda declarado SOLO LECTURA con [Copiar].
 *
 * Run:  node product/app/design/conexiones/verify_cuarto_puente.mjs
 */
import { webkit } from "playwright";
import { spawn, execSync } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";

const HERE = dirname(fileURLToPath(import.meta.url));
const DESIGN = join(HERE, "..");
const REPO = join(DESIGN, "..", "..", "..");
const PORT = Number(process.env.CXP_PORT || 8178);
const FROZEN = process.env.CXP_FROZEN || "http://127.0.0.1:8226";
const APP_SIDECAR = "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let pass = 0, fail = 0; const fails = [];
const ok = (c, m, extra) => {
  if (c) { pass++; console.log("  ✓", m + (extra ? "  — " + extra : "")); }
  else { fail++; fails.push(m); console.log("  ✗", m + (extra ? "  — " + extra : "")); }
};
const J = (o) => JSON.stringify(o);

// ── el motor, controlable (mismo patrón que verify_cuarto_semaforo) ─────────────────
const motorState = {};
const ts = () => Math.floor(Date.now() / 1000);
const motorResult = (tipo, ref, def) => {
  const s = motorState[ref] || { estado: def || "detectado" };
  return { tipo, ref, estado: s.estado, causa: s.estado === "roto" ? (s.causa || "error_upstream") : null,
    evidencia: { motivo: "verify" }, ts: ts(), cacheado: false, fresco: s.estado !== "detectado" };
};

function liberar(puerto) {
  if (puerto === 25374) throw new Error("ese puerto es del humano");
  let pids = [];
  try { pids = execSync(`lsof -nP -tiTCP:${puerto} -sTCP:LISTEN 2>/dev/null || true`).toString().trim().split("\n").filter(Boolean); }
  catch (e) { return true; }
  for (const pid of pids) {
    let cmd = ""; try { cmd = execSync(`ps -o command= -p ${pid} 2>/dev/null || true`).toString(); } catch (e) {}
    if (!/aleph_sidecar|conexiones_sidecar|http.server/.test(cmd)) {
      console.log(`✗ :${puerto} lo tiene un proceso ajeno (pid ${pid}) — no lo toco`); return false;
    }
    try { execSync(`kill -9 ${pid}`); } catch (e) {}
  }
  return true;
}

const DATA = mkdtempSync(join(tmpdir(), "cxp-"));
let procFrozen = null;
async function sano(base, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(base + "/health", { signal: AbortSignal.timeout(2000) }); if (r.ok) return true; } catch {}
    await sleep(700);
  }
  return false;
}

if (!process.env.CXP_FROZEN) liberar(Number(new URL(FROZEN).port));
liberar(PORT);
if (!process.env.CXP_FROZEN) {
  procFrozen = spawnFrozen(APP_SIDECAR, ["--port", String(new URL(FROZEN).port)],
    { env: { ...process.env, ALEPH_DATA_DIR: DATA }, stdio: "ignore", detached: true });
  procFrozen.unref();
}
const hayValidador = await sano(FROZEN);
if (!hayValidador) console.log("⚠ sin sidecar frozen: [Validar] se mide contra un veredicto simulado, no el real");

// El validador vive detrás de la sesión (CONTRACT-AUTH-v2): sin Bearer devuelve 401 y el
// "veredicto" sería el del portero, no el del contrato. Mintamos una sesión REAL en el frozen.
let SESION = null;
if (hayValidador) {
  const r = await fetch(FROZEN + "/v1/auth/local", { method: "POST" }).catch(() => null);
  SESION = r && r.ok ? await r.json().catch(() => null) : null;
  if (!SESION) console.log("⚠ el frozen no minta sesión: [Validar] va a medir un 401, no el contrato");
}

const estatico = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"],
  { cwd: DESIGN, stdio: "ignore" });

let browser;
try {
  await sleep(1200);
  browser = await webkit.launch();
  const page = await (await browser.newContext()).newPage();
  if (SESION) await page.addInitScript((u) => {
    try { sessionStorage.setItem("puppet_user", JSON.stringify(u)); localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) {}
  }, SESION);
  const jsErrors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) jsErrors.push(m.text()); });
  page.on("pageerror", (e) => jsErrors.push(String(e)));

  // ── rutas: todo stub salvo el validador de recetas, que va al backend REAL ──────
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/atoms/catalog**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: J({ atoms: [], total: 0 }) }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ providers: { claude_cli: { state: "ready", extra: { subscriptionType: "max" } }, codex_cli: { state: "no_auth" } } }) }));
  await page.route("**/v1/tools/**", (r) => r.fulfill({ status: 200, contentType: "application/json",
    body: J({ code: "def buscar(q):\n    return http('/search', q)\n", language: "python", belt_ref: "belts/demo.mcp.json" }) }));
  await page.route("**/v1/motor/estado**", (r) => {
    const u = new URL(r.request().url());
    r.fulfill({ status: 200, contentType: "application/json", body: J(motorResult(u.searchParams.get("tipo"), u.searchParams.get("ref"))) });
  });
  await page.route("**/v1/motor/probar", (r) => {
    let b = {}; try { b = JSON.parse(r.request().postData() || "{}"); } catch (e) {}
    r.fulfill({ status: 200, contentType: "application/json", body: J(motorResult(b.tipo, b.ref, "probado")) });
  });
  await page.route("**/v1/recipes/validate", async (r) => {
    if (!hayValidador) {
      return r.fulfill({ status: 200, contentType: "application/json",
        body: J({ valid: false, errors: ["meta.name requerido (string no vacío)"], warnings: [], effective_gates: {} }) });
    }
    const h = { "Content-Type": "application/json" };
    const auth = r.request().headers()["authorization"];
    if (auth) h["Authorization"] = auth;
    const up = await fetch(FROZEN + "/v1/recipes/validate", {
      method: "POST", headers: h, body: r.request().postData() || "{}",
    }).catch(() => null);
    if (!up) return r.fulfill({ status: 502, body: "sin validador" });
    r.fulfill({ status: up.status, contentType: "application/json", body: await up.text() });
  });
  // [cierre de Conexiones] El Centro murió: el puente ya NO manda a Conexiones.dc.html
  // sino al destino final — Modelos (cognición) o Conectores (lo que HACE). Se interceptan
  // los dos para LEER a dónde nos manda, igual que antes. La ruta vieja queda como red de
  // seguridad y tiene su propia aserción en qa/verify_t7_cierres.mjs §3.
  const navegaciones = [];
  await page.route(/\/(Modelos|Conectar|Conexiones)\.dc\.html/, (r) => {
    navegaciones.push(r.request().url());
    r.fulfill({ status: 200, contentType: "text/html", body: "<html><body id='centro-stub'>centro</body></html>" });
  });

  // El Cuarto + los DOS módulos de esta terminal inyectados (lo que C va a cablear con UNA
  // línea de <script>). Se re-monta después de cada navegación al Centro: irse de la página
  // es justamente lo que estamos midiendo, y el documento viejo se muere.
  async function montarCuarto() {
    await page.goto(PAGE, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.CuartoSemaforo && window.__cuarto && window.__semHooks, null, { timeout: 20000 });
    await sleep(600);
    await page.addScriptTag({ url: "/conexiones/cuarto.hook.js", type: "module" });
    await page.addScriptTag({ url: "/conexiones/codigo.js", type: "module" });
    await page.waitForFunction(() => !!window.AlephConexiones && !!window.AlephCodigo, null, { timeout: 15000 });
    await sleep(700);
  }
  await montarCuarto();

  console.log("\n§0 · el puente monta con UNA línea de <script>");
  ok(await page.evaluate(() => !!window.AlephConexiones), "window.AlephConexiones presente");
  ok(await page.evaluate(() => !!window.AlephCodigo), "window.AlephCodigo presente");
  ok(jsErrors.length === 0, "cero errores de JS al inyectarlos", jsErrors.slice(0, 2).join(" | "));

  // ══ §G · el closet de MCPs tiene SALIDA ═════════════════════════════════════════
  console.log("\n§G · el closet de MCPs (paleta) ahora se puede CERRAR");
  // ⚠️ REALINEADO AL CONTRATO DE C [Integración #5]. Esta vara se escribió contra el
  // cuarto.pixi.html de ANTES de "Cuarto limpio": ＋ Equipar era un pill suelto de la barra
  // y se clickeaba directo. C hizo la BARRA DE 3 — en #topright sólo quedan visibles
  // [← Salir] · [▶ Run] · [⋯] — y ＋ Equipar pasó a vivir DENTRO de #metaMenu
  // (role="menuitem", oculto hasta abrir el menú). O sea que el camino de USUARIO ahora es
  // ⋯ → ＋ Equipar, y eso es lo que la vara tiene que recorrer; es el mismo camino que usa
  // la propia vara de C (qa/verify_cuarto_limpio.mjs).
  //
  // El PRODUCTO no necesitó cambio: `cuarto.hook.js::cerrarPaleta()` cierra con un
  // `b.click()` PROGRAMÁTICO, que dispara el handler aunque el botón esté oculto — por eso
  // ✕ / Escape / click-afuera siguen funcionando igual (lo prueban los asserts de abajo).
  const abrirCloset = async () => {
    const yaAbierto = await page.evaluate(() => {
      const p = document.getElementById("palette");
      return !!p && p.classList.contains("open");
    });
    if (yaAbierto) return;
    await page.click("#metaBtn"); await sleep(200);   // ⋯ · la barra de 3 de C
    await page.click("#equipBtn"); await sleep(350);
  };
  const abierto = () => page.evaluate(() => document.getElementById("palette").classList.contains("open"));
  const insetIzq = () => page.evaluate(() => {
    try { return window.__cuarto.cam.insets ? window.__cuarto.cam.insets().leftPx : null; } catch (e) { return null; }
  });

  await abrirCloset();
  ok(await abierto(), "el closet abre con su botón (como siempre)");
  ok(await page.isVisible("#palClose"), "hay una ✕ VISIBLE dentro del closet");
  await page.click("#palClose"); await sleep(350);
  ok(!(await abierto()), "la ✕ lo cierra");

  await abrirCloset();
  await page.keyboard.press("Escape"); await sleep(350);
  ok(!(await abierto()), "Escape lo cierra");

  await abrirCloset();
  const antes = await insetIzq();
  await page.mouse.click(1000, 500); await sleep(400);
  ok(!(await abierto()), "un click AFUERA lo cierra");
  const despues = await insetIzq();
  ok(antes === null || despues === 0 || despues === null,
    "y la cámara del diorama vuelve a su lugar (se reusa el toggle original)", `insets ${antes}→${despues}`);
  await abrirCloset();
  // el toggle original sigue siendo el que cierra. Va PROGRAMÁTICO a propósito: es
  // exactamente lo que hace `cerrarPaleta()` del hook (`b.click()`), y prueba que ese camino
  // sigue vivo aunque C haya metido el botón dentro del menú ⋯ (con el closet abierto, el
  // menú ya se cerró: un click de usuario ahí no llegaría, y no es lo que el hook hace).
  await page.evaluate(() => document.getElementById("equipBtn").click()); await sleep(300);
  ok(!(await abierto()), "el botón de siempre sigue cerrándolo (nada se rompió)");

  // ══ §A · [Ver conexión] de una pieza de CONEXIÓN navega al Centro ═══════════════
  console.log("\n§A · el closet deja de apilar el flujo: [Ver conexión] LLEVA al Centro");
  navegaciones.length = 0;
  await page.evaluate(() => {
    window.__openInspector({ id: "p-zotero", atom: "conexion", label: "Zotero",
      connector: "zotero", server: "zotero", role: "fuentes" });
  });
  await sleep(500);
  const rotulo = await page.textContent("#iprimary");
  ok(/Ver conexión/.test(rotulo), "el botón primario dice a dónde te lleva", rotulo.trim());
  await page.click("#iprimary");
  await sleep(600);
  ok(navegaciones.length === 1, "navegó a donde se arregla (una sola vez)", navegaciones[0] || "sin navegación");
  // zotero es un MCP: se conecta en CONECTORES, y `?c=` abre su wizard — el deep-link por
  // fila no se perdió al morir el Centro, cambió de pantalla.
  ok(/Conectar\.dc\.html/.test(navegaciones[0] || "") && /c=zotero/.test(navegaciones[0] || ""),
     "…a la FILA de esa pieza (deep-link por conector)", navegaciones[0] || "");
  ok(/return=/.test(navegaciones[0] || ""), "…y con el camino de vuelta al Cuarto");

  // ══ §A/§D · el semáforo: credencial/configurar y [Probar de nuevo] que muta ════
  console.log("\n§D · [Probar de nuevo] reintenta UNA vez y después LLEVA");
  await montarCuarto();          // volvemos del Centro: el documento anterior ya no existe
  motorState["zotero"] = { estado: "roto", causa: "falta_key" };
  navegaciones.length = 0;
  const badge = await page.evaluate(async () => {
    const S = window.CuartoSemaforo;
    const el = document.createElement("div");
    el.id = "badge-prueba";
    // encima del escenario: el diorama ocupa toda la pantalla y se comería el click
    el.style.cssText = "position:fixed;top:6px;left:6px;z-index:99999;background:#111";
    document.body.appendChild(el);
    const res = await S.leerEstado("key", "zotero");
    S.pintarBadge(el, res, { ctx: { conector: "zotero", pieceId: "p-zotero" },
      onProbar: () => S.probar("key", "zotero") });
    const b = el.querySelector(".sem-accion");
    return { texto: b ? b.textContent : null, accion: b ? b.dataset.accion : null };
  });
  ok(badge.accion === "credencial", "un roto por falta de llave ofrece su botón", badge.texto);
  // el motor sigue devolviendo ROTO también al PROBAR → el reintento no arregla nada
  motorState["zotero"] = { estado: "roto", causa: "falta_key" };
  await page.evaluate(() => {
    const el = document.getElementById("badge-prueba");
    // forzamos el camino de REINTENTO pintando un roto cuya acción es reintentar
    const S = window.CuartoSemaforo;
    S.pintarBadge(el, { tipo: "key", ref: "zotero", estado: "roto", causa: "sin_red", evidencia: {} },
      { ctx: { conector: "zotero" }, onProbar: () => S.probar("key", "zotero") });
  });
  const antesTexto = await page.textContent("#badge-prueba .sem-accion");
  // [Integración C1 · P3 §2] La acción interna sigue siendo `reintentar`; el rótulo visible
  // único es «Probar de nuevo».
  ok(/Probar de nuevo/.test(antesTexto), "primero dice [Probar de nuevo]", antesTexto.trim());
  await page.click("#badge-prueba .sem-accion");
  await sleep(1200);
  const mutado = await page.evaluate(() => {
    const b = document.querySelector("#badge-prueba .sem-accion");
    return b ? { texto: b.textContent, accion: b.dataset.accion, mutado: b.dataset.mutado } : null;
  });
  ok(!!mutado && mutado.mutado === "1", "reintentó y sigue roto → el botón MUTÓ", mutado ? mutado.texto : "");
  ok(!!mutado && /Configurar/.test(mutado.texto), "…ahora dice [Configurar]", mutado ? mutado.texto : "");
  await page.click("#badge-prueba .sem-accion");
  await sleep(900);
  // [FIX-P1B · §1] Esto exigía una NAVEGACIÓN a la fila del catálogo. Aterrizar en algún
  // lado era lo correcto de esa aserción; irse del Cuarto era lo incorrecto — la regla de R
  // dice que sólo se sale si el trámite necesita navegador. El botón mutado ahora abre EL
  // WORKFLOW de esa conexión ahí mismo, y el workflow SABE de qué pieza habla.
  const trasMutado = await page.evaluate(() => {
    const w = document.querySelector(".wz");
    return { hayWorkflow: !!w, tipo: w ? w.dataset.tipo : null,
             titulo: w ? (w.querySelector(".wz-tit") || {}).textContent || "" : "" };
  });
  ok(trasMutado.hayWorkflow, "…y ABRE EL WORKFLOW de esa conexión, sin sacarte de donde estabas",
     `${trasMutado.tipo} · ${trasMutado.titulo}`);
  ok(/zotero/i.test(trasMutado.titulo), "…y el workflow es el de ESA pieza", trasMutado.titulo);
  ok(navegaciones.length === 0, "CALIBRACIÓN: cero navegaciones (antes acá se perdía la página)",
     navegaciones.join(" | ") || "ninguna");
  await page.evaluate(() => { const W = window.AlephWizard; if (W) W.cerrar(); });

  // ══ §I · el atajo del Guía ══════════════════════════════════════════════════════
  console.log("\n§I · el gancho para el Guía");
  await montarCuarto();          // se remonta igual: el resto de la sección lo espera limpio
  const url = await page.evaluate(() => window.AlephConexiones.url("context7"));
  ok(/Conectar\.dc\.html\?/.test(url) && /c=context7/.test(url), "abrir('context7') apunta a su fila", url);

  // ══ §H · [REESCRITA · reforma·l] EL TAB CÓDIGO YA NO EXISTE ════════════════════
  // Esta sección medía el tab «Código» que Terminal B desambiguó: receta EDITABLE con
  // [Validar] + handler declarado solo-lectura. La reforma retira ese tab entero por la
  // regla de plataforma **código → VS Code · configuración → formulario**: nadie edita
  // código en un popup de 280px sin resaltado, sin buscar y sin deshacer.
  //
  // Lo que se mide ahora es el contrato NUEVO, y es más exigente en lo que importaba:
  //   · el tab no está (ni el suyo ni el gancho __cuartoAplicarReceta que pedía)
  //   · el JSON del handler bajó a DETALLE TÉCNICO, plegado, declarado como evidencia
  //   · un fetch fallido YA NO se pinta como si fuera el contenido del handler
  //   · hay un botón que abre el archivo REAL en VS Code, con el path a la vista
  console.log("\n§H · el código se abre en VS Code; el handler baja a evidencia declarada");
  const sinTab = await page.evaluate(() => ({
    tabCodigo: !!document.querySelector('#inspector .tab[data-d="code"]'),
    panelCodigo: !!document.getElementById("d-code"),
    gancho: typeof window.__cuartoAplicarReceta,
    tabs: [...document.querySelectorAll("#inspector .tab")].map((t) => t.dataset.d),
  }));
  ok(!sinTab.tabCodigo && !sinTab.panelCodigo, "el tab Código murió (botón y panel)", sinTab.tabs.join("·"));
  ok(sinTab.gancho === "undefined", "y NO se construyó window.__cuartoAplicarReceta", sinTab.gancho);
  ok(JSON.stringify(sinTab.tabs) === JSON.stringify(["chat", "opts", "viz"]),
    "quedan Chat · Opciones · Salida", sinTab.tabs.join("·"));

  // DETALLE TÉCNICO sobre una pieza MCP: plegado, y con desenlace nombrado
  await page.evaluate(() => {
    window.__openInspector({ id: "p-mcp", atom: "tool", label: "Buscador", server: "demo",
      ref: "demo", role: "fuentes", tools: ["buscar"] });
  });
  await sleep(400);
  const plegado = await page.evaluate(() => {
    document.querySelector('#inspector .tab[data-d="viz"]').click();
    const dt = document.querySelector("#d-viz details.dt");
    return { existe: !!dt, abierto: !!(dt && dt.open), rotulo: dt ? dt.querySelector("summary").textContent : "" };
  });
  ok(plegado.existe && !plegado.abierto, "el detalle técnico existe y nace PLEGADO (§8.3)", plegado.rotulo);
  await page.evaluate(() => document.querySelector("#d-viz details.dt > summary").click());
  await page.waitForFunction(() => {
    const b = document.querySelector("#d-viz details.dt > div");
    return b && !/leyendo el handler/.test(b.textContent);
  }, null, { timeout: 20000 }).catch(() => {});
  const det = await page.evaluate(() => {
    const b = document.querySelector("#d-viz details.dt > div");
    return { txt: (b && b.textContent) || "", mal: !!(b && b.querySelector(".dt-mal")),
             abrir: !!(b && b.querySelector("[data-abrir]")),
             rotuloAbrir: (b && b.querySelector("[data-abrir]") || {}).textContent || "",
             path: (b && b.querySelector(".dt-path") || {}).textContent || "" };
  });
  ok(/Handler/.test(det.txt) && !det.mal, "con handler real, se muestra declarado como evidencia",
    (det.txt.match(/Handler[^\n]{0,40}/) || [""])[0]);
  ok(det.abrir && /VS Code/.test(det.rotuloAbrir), "hay botón al editor de verdad", det.rotuloAbrir.trim());
  ok(!!det.path, "…con el path VISIBLE debajo (se sabe qué archivo se abre)", det.path);

  // EL FALLO: el backend responde 404 → antes ese JSON se pintaba dentro del <pre> con el
  // título «Handler MCP», o sea el error se leía como si fuera el contenido. Ahora se nombra.
  await page.route("**/v1/tools/**", (r) => r.fulfill({ status: 404, contentType: "application/json",
    body: J({ detail: { error: "server_not_found", detail: "no encuentro el server 'demo'" } }) }));
  await page.evaluate(() => {
    const b = document.querySelector("#d-viz details.dt > div");
    window.__detalleTecnico(window.__cuarto ? { id: "p-mcp", atom: "tool", label: "Buscador", server: "demo", ref: "demo", role: "fuentes", tools: ["buscar"] } : null, b);
  });
  await page.waitForFunction(() => {
    const b = document.querySelector("#d-viz details.dt > div");
    return b && !/leyendo el handler/.test(b.textContent);
  }, null, { timeout: 20000 }).catch(() => {});
  const fallo = await page.evaluate(() => {
    const b = document.querySelector("#d-viz details.dt > div");
    return { mal: !!(b && b.querySelector(".dt-mal")), txt: (b && b.textContent) || "",
             volcado: !!(b && [...b.querySelectorAll("pre.code")].some((x) => /server_not_found/.test(x.textContent))) };
  });
  ok(fallo.mal && /No pude leer el handler/.test(fallo.txt),
    "un handler que no se puede leer se DICE (con su HTTP)", (fallo.txt.match(/No pude[^·]*·[^R]*/) || [""])[0].trim());
  ok(!fallo.volcado, "…y el error NO se vuelca dentro del <pre> como si fuera contenido");
  // Este camino recarga el panel; P3 lo nombra por lo que realmente hace.
  ok(/Volver a cargar/.test(fallo.txt), "…y trae [Volver a cargar] (§8.1: ningún final es una pared)");

  ok(jsErrors.length === 0, "cero errores JS en toda la corrida", jsErrors.slice(0, 2).join(" | "));
} finally {
  if (browser) await browser.close();
  try { estatico.kill("SIGKILL"); } catch (e) {}
  try { if (procFrozen) process.kill(-procFrozen.pid, "SIGKILL"); } catch (e) {}
}

console.log(`\n${fail === 0 ? "✅ VERDE" : "❌ ROJO"} — ${pass} ok / ${fail} fail`);
if (fail) console.log("  " + fails.join("\n  "));
process.exit(fail ? 1 : 0);
