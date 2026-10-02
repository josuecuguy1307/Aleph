/* verify_sala_viva.mjs — LA SALA VIVA · la vara real.
 *
 * WebKit contra el SIDECAR FROZEN del build instalado. El backend es el REAL (puerto 8201,
 * datadir aislado); el frontend es el REPARADO de este worktree, servido por un estático
 * node que PROXEA /v1 al sidecar. Así se prueba la reparación contra el motor de verdad,
 * no contra un mock.
 *
 * Matriz:
 *   1. El composer se puede USAR (ancho real ≥ mínimo) y acepta teclado.
 *   2. Escribir + enviar → LLEGA AL BACKEND (assert del request real).
 *   3. Cerebro sano (el Claude Code del humano) → run real + model_final correcto.
 *   4. Cerebro roto (CLI ausente · sin sesión · key inválida) → composer SIGUE escribible,
 *      el Send NO queda inerte, y sale causa TIPADA + botón.
 *   5. Lane incluida → se ofrece SÓLO si está viva; si no, se dice la verdad (nunca finge).
 *   6. Plan insuficiente → avisa con opciones ANTES de degradar (no degrada solo).
 *   7. Cero cuelgues: un backend mudo NO deja el composer muerto — corta con causa.
 *
 * Run:  node verify_sala_viva.mjs        (necesita el sidecar frozen en :8201)
 *
 * ── PORTADA A DEEP-CHAT (T7) ────────────────────────────────────────────────────────
 * La franja de conversación de La Sala vive ahora dentro del Shadow DOM de <deep-chat>.
 * `document.getElementById` y `textContent` NO cruzan esa frontera, así que cambia POR
 * DÓNDE se resuelve cada nodo — NO qué se afirma. La matriz de arriba es la misma.
 * El mapeo, uno por uno:
 *
 *   #composer (textarea)        →  #text-input del shadow (contenteditable de deep-chat)
 *   #send (button)              →  el div clickeable que envuelve a #submit-icon
 *   send.disabled               →  el botón NUNCA es disabled (alwaysEnabled). "Turno en
 *                                  vuelo" se lee como antes: el botón pasa a #stop-icon.
 *   send.classList "gated"      →  <deep-chat data-gated="1"> (el mismo estado: apagado
 *                                  pero VIVO — el click entra igual y la Sala contesta).
 *   .chat-scroll .textContent   →  #messages del shadow
 *   document.querySelectorAll   →  window.__salaQA(sel) (resuelve por el shadow root)
 *
 * Los helpers `__salaQ`/`__salaQA` los expone sala.html; no son un atajo del test: son el
 * único acceso posible a un shadow root desde page.evaluate.
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "../../../../qa/lib/frozen_guard.mjs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
// puertos PROPIOS de esta sesión (:8240 estático · :8241 sidecar frozen). No se toca el
// :25374 de la .app de persona usuaria ni el :8201/:8299 de otras corridas en paralelo.
const SIDECAR = process.env.SALA_BASE || "http://127.0.0.1:8241";
const PORT = Number(process.env.VERIFY_PORT || 8240);
const PAGE = `http://127.0.0.1:${PORT}/sala/sala.html`;
const MIN_COMPOSER = 140;

const fails = [];
const ok = (cond, label, extra) => {
  console.log(`${cond ? "✓" : "✗"} ${label}${extra ? "  — " + extra : ""}`);
  if (!cond) fails.push(label);
};

// ── estático (frontend reparado) + proxy /v1 → sidecar FROZEN ────────────────────
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };
const server = http.createServer(async (req, res) => {
  // Reiniciar el sidecar entre bloques aborta sockets en vuelo: sin estos handlers el
  // 'aborted' sube como excepción no capturada y MATA el verify a mitad de matriz
  // (un rojo del banco de pruebas disfrazado de rojo del producto).
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  if (u.pathname.startsWith("/v1/") || u.pathname === "/health") {
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = Buffer.concat(chunks);
    // Sólo cabeceras SEGURAS: reenviar `content-length`/`connection`/`host` del cliente hace
    // que undici y las suyas propias se contradigan y la request se cuelgue — un cuelgue del
    // BANCO DE PRUEBAS que se confunde con uno del producto. (Lo pagué caro: perseguí un
    // "auth/local que no responde" que era este proxy.)
    const fwd = {};
    for (const k of ["authorization", "content-type", "accept"]) if (req.headers[k]) fwd[k] = req.headers[k];
    const up = await fetch(SIDECAR + req.url, {
      method: req.method,
      headers: fwd,
      body: ["GET", "HEAD"].includes(req.method) ? undefined : (body.length ? body : undefined),
      redirect: "manual",
    }).catch((e) => null);
    if (!up) { res.writeHead(502); res.end("sidecar caído"); return; }
    const h = {}; up.headers.forEach((v, k) => { if (!/^(content-encoding|transfer-encoding|connection)$/i.test(k)) h[k] = v; });
    res.writeHead(up.status, h);
    res.end(Buffer.from(await up.arrayBuffer()));
    return;
  }
  try {
    const body = await readFile(join(DESIGN_DIR, decodeURIComponent(u.pathname).replace(/^\//, "")));
    res.writeHead(200, { "Content-Type": MIME[extname(u.pathname)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("clientError", (e, sock) => { try { sock.destroy(); } catch {} });
server.on("error", () => {});
process.on("uncaughtException", (e) => { if (!/aborted|ECONNRESET|EPIPE/i.test(String(e && (e.code || e.message)))) throw e; });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

const SESSION = `try{ sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-ver",session_token:"tok-ver",email:"v@aleph"})); }catch(e){}`;
const pickBrain = (id, mode) => `try{ localStorage.setItem("aleph-active-brain","${id}"); localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"${mode}",id:"${id}",cliModel:""})); }catch(e){}`;

// ── sidecar FROZEN propio: fresco, datadir aislado, y lo matamos al terminar ──────
// Cada corrida arranca uno NUEVO porque el backend se traba en el camino de escritura
// después de un run real (ver DIAGNOSTICO-SALA-MUDA.md §hallazgo-b). Sin esto, la
// segunda mitad de la matriz medía el cuelgue del backend en vez de la reparación.
// [Integración #5] overridable con ALEPH_SIDECAR_BIN. El default sigue siendo la .app
// INSTALADA (criterio de cierre), pero la ola se certifica ANTES de instalar y esta vara
// necesita reiniciar el backend entre fases (freshBackend), o sea que tiene que ser ELLA la
// que lo levante — con SALA_BASE se salta ese reinicio y la segunda mitad mediría otra cosa.
const APP_SIDECAR = process.env.ALEPH_SIDECAR_BIN || "/Applications/Aleph.app/Contents/MacOS/aleph_sidecar";
let sidecarProc = null;
async function healthy(base, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(base + "/health", { signal: AbortSignal.timeout(2000) }); if (r.ok) return true; } catch {}
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}
async function bootSidecar() {
  if (process.env.SALA_BASE) return await healthy(SIDECAR);   // el humano trajo el suyo
  const dir = mkdtempSync(join(tmpdir(), "salaviva-"));
  sidecarProc = spawnFrozen(APP_SIDECAR, ["--port", String(new URL(SIDECAR).port)],
    { env: { ...process.env, ALEPH_DATA_DIR: dir }, stdio: "ignore", detached: true });
  sidecarProc.unref();
  return await healthy(SIDECAR);
}
function killSidecar() {
  try { if (sidecarProc) process.kill(-sidecarProc.pid, "SIGKILL"); } catch {}
  sidecarProc = null;
}
// Backend FRESCO por bloque. No es ceremonia: el sidecar se traba en el camino de ESCRITURA
// después de un run real, y el momento exacto varía — sin esto la matriz sale distinta en cada
// corrida y deja de ser una vara. Cada bloque arranca con backend limpio; el bloque 8 usa a
// propósito el que quedó trabado.
async function freshBackend(label) {
  if (process.env.SALA_BASE) return;            // backend del humano: no lo tocamos
  killSidecar();
  await new Promise((r) => setTimeout(r, 800));
  if (!(await bootSidecar())) { console.log(`✗ no pude levantar el sidecar frozen para ${label}`); process.exit(1); }
}
if (!(await bootSidecar())) { console.log("✗ no pude levantar el sidecar frozen en " + SIDECAR); process.exit(1); }

const browser = await webkit.launch();
async function boot({ seed, routes } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 160)));
  await page.addInitScript(SESSION + (seed || ""));
  if (routes) for (const [pat, fn] of routes) await page.route(pat, fn);
  await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
  // la franja de conversación monta async (bundle + upgrade + render): sin esta espera se
  // mediría un composer que todavía no existe.
  await page.waitForFunction(() => window.__salaQ && window.__salaQ("#text-input"), null, { timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(5200);
  page.__errs = errs;
  return page;
}
const composerState = (page) => page.evaluate(() => {
  const dc = document.getElementById("salaChat");
  const c = window.__salaQ("#text-input");
  const stop = !!window.__salaQ("#stop-icon");
  const wrap = (window.__salaQ("#submit-icon") || {}).parentElement || null;
  const enVuelo = stop || !!(wrap && wrap.getAttribute("aria-busy") === "true");
  const r = c.getBoundingClientRect();
  return { w: Math.round(r.width),
           disabled: c.getAttribute("contenteditable") === "false",
           readOnly: c.getAttribute("contenteditable") === "false",
           // "el Send no queda inerte": con alwaysEnabled el click SIEMPRE entra
           sendDisabled: enVuelo ? true : !!(wrap && wrap.classList.contains("disabled-button")),
           sendGated: dc.getAttribute("data-gated") === "1",
           sendTitle: (window.__salaQ("#submit-icon") || {}).getAttribute
                        ? (window.__salaQ("#submit-icon").parentElement.getAttribute("aria-label") || "") : "" };
});
const cards = (page) => page.evaluate(() => window.__salaQA(".errcard").map((d) => ({
  causa: d.dataset.causa || null,
  titulo: (d.querySelector("b") || {}).textContent || "",
  botones: [...d.querySelectorAll(".acts button")].map((b) => b.textContent),
})));
// escribir / enviar / leer, resueltos por el shadow root
const escribir = async (page, txt) => {
  await page.click("deep-chat >> #text-input");
  await page.keyboard.type(txt, { delay: 6 });
};
const textoComposer = (page) => page.evaluate(() => (window.__salaQ("#text-input") || {}).textContent || "");
const enviar = (page) => page.evaluate(() => {
  const s = window.__salaQ("#submit-icon") || window.__salaQ("#stop-icon");
  if (s && s.parentElement) s.parentElement.click();
});
/* "turno en vuelo" en deep-chat tiene DOS fases, y mirar sólo una miente:
 *   · pedido en curso, sin tokens todavía → el botón entra en LOADING (aria-busy="true")
 *   · llegando tokens                     → el botón pasa a #stop-icon
 * Con sólo #stop-icon, la ventana de "pensando…" se leía como "turno libre" y el bloque
 * salía corriendo antes de que hubiera respuesta (falsos verdes Y falsos rojos). */
const enVuelo = (page) => page.evaluate(() => {
  if (window.__salaQ("#stop-icon")) return true;
  const w = (window.__salaQ("#submit-icon") || {}).parentElement;
  return !!(w && w.getAttribute("aria-busy") === "true");
});
const nMsgs = (page) => page.evaluate(() => window.__salaQA(".outer-message-container").length);
const chatTexto = (page) => page.evaluate(() => (window.__salaQ("#messages") || {}).textContent || "");

console.log("══ VERIFY · LA SALA VIVA (WebKit → estático reparado → sidecar FROZEN :8201) ══\n");

// ── 1 · el composer se puede USAR ────────────────────────────────────────────────
console.log("── 1 · el composer se puede usar ──");
await freshBackend("bloque");
{
  const page = await boot();
  const st = await composerState(page);
  ok(st.w >= MIN_COMPOSER, `el campo de escribir mide ${st.w}px (mínimo ${MIN_COMPOSER})`, "antes: 31px");
  ok(!st.disabled && !st.readOnly, "el textarea no está disabled ni readonly");
  await escribir(page, "hola sala");
  ok((await textoComposer(page)) === "hola sala", "acepta teclado real");
  await page.close();
}

// ── 4 · cerebro ROTO → nunca mudo, causa tipada + botón ──────────────────────────
console.log("\n── 4 · cerebro roto → el composer NUNCA queda mudo ──");
await freshBackend("bloque");
const rotos = [
  ["CLI ausente", "claude_cli", "cli", { providers: { claude_cli: { provider: "claude_cli", state: "not_installed", detail: "No encontré el CLI en esta máquina.", installed: false } }, service: { state: "ready", mode: "shared" } }, "cli_no_instalado"],
  ["CLI sin sesión", "claude_cli", "cli", { providers: { claude_cli: { provider: "claude_cli", state: "no_auth", detail: "instalado pero sin sesión", installed: true } }, service: { state: "ready", mode: "shared" } }, "cli_no_logueado"],
  ["servicio local caído", "claude_cli", "cli", { providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", installed: true } }, service: { state: "unavailable", mode: "failed", detail: "el listener local no está vivo" } }, "cli_interactivo_colgado"],
  ["lane incluida sin llave", "included", "included", { providers: { included: { provider: "included", state: "not_configured", detail: "no hay llave de cognición configurada para la lane incluida" } }, service: { state: "ready", mode: "shared" } }, "key_ausente"],
];
for (const [nombre, id, mode, payload, causaEsperada] of rotos) {
  const page = await boot({
    seed: pickBrain(id, mode),
    routes: [["**/v1/brains/status", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) })]],
  });
  const st = await composerState(page);
  await escribir(page, "probando cerebro roto");
  const escribio = (await textoComposer(page)) === "probando cerebro roto";
  await enviar(page);                  // si estuviera `disabled` esto colgaría → el click DEBE entrar
  await page.waitForTimeout(1400);
  const cs = await cards(page);
  // deep-chat vacía el campo al enviar; La Sala se lo DEVUELVE al bloquear (mismo invariante:
  // no se pierde lo que el humano escribió).
  const texto = await textoComposer(page);
  console.log(`  · ${nombre}:`);
  ok(escribio, "    el composer SIGUE escribible", `${st.w}px`);
  ok(st.sendDisabled === false, "    el Send NO queda inerte (disabled=false)");
  ok(st.sendGated === true, "    …pero se ve apagado (.gated) — estado honesto");
  ok(cs.length === 1 && cs[0].causa === causaEsperada, `    causa TIPADA = ${causaEsperada}`, cs[0] ? cs[0].causa : "sin card");
  ok(!!cs[0] && cs[0].botones.length > 0, "    la card trae CAMINO (botones)", cs[0] ? cs[0].botones.join(" / ") : "");
  ok(texto === "probando cerebro roto", "    no se pierde lo que el humano escribió");
  await page.close();
}

// ── 5 · lane incluida: se ofrece SÓLO si está viva ───────────────────────────────
console.log("\n── 5 · fallback a la lane incluida (honesto) ──");
await freshBackend("bloque");
{
  // (a) cerebro SANO (pasa el gate) cuyo RUN falla + lane VIVA → el relevo se ofrece
  const viva = { providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", installed: true },
                              included: { provider: "included", state: "ready", detail: "lane incluida configurada" } },
                 service: { state: "ready", mode: "shared" } };
  const page = await boot({ seed: pickBrain("claude_cli", "cli"),
    routes: [["**/v1/brains/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(viva) })],
             ["**/v1/puppets/run**", (r) => r.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: { detail: "la key fue rechazada" } }) })]] });
  await escribir(page, "dale");
  await enviar(page); await page.waitForTimeout(1500);
  const cs = await cards(page);
  const ofrece = cs.some((c) => c.botones.some((b) => /Incluido/i.test(b)));
  ok(ofrece, "con la lane VIVA se ofrece el relevo explícito", cs[0] ? cs[0].botones.join(" / ") : "sin card");
  await page.close();
}
{
  // (b) lane CAÍDA (el caso REAL de esta build) → jamás se ofrece un relevo que no existe
  const muerta = { providers: { claude_cli: { provider: "claude_cli", state: "no_auth", detail: "instalado pero sin sesión", installed: true },
                                included: { provider: "included", state: "not_configured", detail: "no hay llave de cognición configurada para la lane incluida" } },
                   service: { state: "ready", mode: "shared" } };
  const page = await boot({ seed: pickBrain("claude_cli", "cli"),
    routes: [["**/v1/brains/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(muerta) })]] });
  await escribir(page, "dale");
  await enviar(page); await page.waitForTimeout(1200);
  const cs = await cards(page);
  const ofrece = cs.some((c) => c.botones.some((b) => /Incluido/i.test(b)));
  ok(!ofrece, "con la lane CAÍDA no se promete un relevo inexistente", cs[0] ? cs[0].botones.join(" / ") : "");
  await page.close();
}

// ── 6 · plan insuficiente → consentimiento ANTES de degradar ─────────────────────
console.log("\n── 6 · plan insuficiente → avisa antes de degradar ──");
await freshBackend("bloque");
{
  const sano = { providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", installed: true } }, service: { state: "ready", mode: "shared" } };
  const page = await boot({ seed: pickBrain("claude_cli", "cli"),
    routes: [["**/v1/brains/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(sano) })],
             ["**/v1/puppets/run**", (r) => r.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: { detail: "tu plan no alcanza para Opus" } }) })]] });
  const antes = await page.evaluate(() => { try { return localStorage.getItem("aleph-brain-configuration"); } catch (e) { return null; } });
  await escribir(page, "hace algo grande");
  await enviar(page); await page.waitForTimeout(1800);
  const cs = await cards(page);
  const despues = await page.evaluate(() => { try { return localStorage.getItem("aleph-brain-configuration"); } catch (e) { return null; } });
  ok(cs.some((c) => c.causa === "plan_insuficiente"), "causa TIPADA = plan_insuficiente", cs[0] ? cs[0].causa : "sin card");
  ok(cs.some((c) => c.botones.length >= 2), "ofrece OPCIONES (no degrada solo)", cs[0] ? cs[0].botones.join(" / ") : "");
  ok(antes === despues, "NO cambió el cerebro sin permiso (anti-degradación silenciosa)");
  await page.close();
}

// ── 7 · cero cuelgues: backend mudo ⇒ el composer no queda muerto ────────────────
console.log("\n── 7 · cero cuelgues (backend mudo) ──");
await freshBackend("bloque");
{
  const sano = { providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", installed: true } }, service: { state: "ready", mode: "shared" } };
  const page = await boot({ seed: pickBrain("claude_cli", "cli"),
    routes: [["**/v1/brains/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(sano) })],
             // el HANG real: nunca se contesta (ni headers ni body)
             ["**/v1/classify-turn", () => {}],
             ["**/v1/puppets/run**", () => {}]] });
  await page.evaluate(() => { window.API_TIMEOUT_TEST = true; });
  await escribir(page, "esto se cuelga");
  await enviar(page);
  // MISMA afirmación, otro signo: deep-chat no deshabilita el botón, lo pone en loading /
  // stop. El invariante es el que importa — no se puede disparar un segundo turno encima.
  let vuelo = false;
  for (let i = 0; i < 20; i++) { if (await enVuelo(page)) { vuelo = true; break; } await page.waitForTimeout(250); }
  ok(vuelo === true, "durante el turno el Send queda tomado (loading/STOP)");
  // el plazo de api() es 30s: esperamos a que corte y suelte el composer
  let soltado = false;
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(4000);
    if (!(await enVuelo(page))) { soltado = true; break; }
  }
  ok(soltado, "el backend mudo NO deja el composer muerto: corta y lo suelta");
  const chat = await chatTexto(page);
  ok(/cort|tard|respond|conexi/i.test(chat), "y DICE qué pasó (no falla en silencio)", JSON.stringify(chat.slice(-90)));
  await page.close();
}

// ── 2+3 · cerebro sano → llega al backend y CORRE de verdad ──────────────────────
console.log("\n── 2+3 · cerebro sano (Claude Code del humano) → run real ──");
await freshBackend("bloque");
{
  const page = await boot({ seed: pickBrain("claude_cli", "cli") });
  const st = await composerState(page);
  ok(st.sendDisabled === false, "el Send está habilitado con cerebro sano");
  const hits = [];
  page.on("request", (r) => { if (/\/v1\/(puppets\/run|chats|classify-turn)/.test(r.url())) hits.push(r.method() + " " + new URL(r.url()).pathname); });
  // BASE: la conversación ya arranca con el saludo + las opciones, así que "n >= 2" ya no
  // significa "hubo turno". Se cuentan los mensajes NUEVOS desde el envío.
  const base = await nMsgs(page);
  await escribir(page, "cuanto es 2+2? responde solo el numero");
  await enviar(page);
  let answered = null;
  for (let i = 0; i < 40; i++) {
    await page.waitForTimeout(3000);
    const s = await page.evaluate((b) => {
      const box = window.__salaQ("#messages");
      const w = (window.__salaQ("#submit-icon") || {}).parentElement;
      return { n: box ? box.querySelectorAll(".outer-message-container").length - b : 0,
               txt: box ? box.textContent : "",
               busy: !!window.__salaQ("#stop-icon") || !!(w && w.getAttribute("aria-busy") === "true") };
    }, base);
    if (s.n >= 2 && !s.busy) { answered = s; break; }   // burbuja del humano + respuesta
  }
  ok(hits.some((h) => h.includes("/v1/puppets/run")), "el envío LLEGA al backend (request real)", hits.join(" · ") || "ninguno");
  ok(!!answered, "el turno CIERRA (no queda colgado en trabajando…)");
  ok(!!answered && /4/.test(answered.txt), "el agente respondió de verdad", answered ? JSON.stringify(answered.txt.slice(-60)) : "");
  // UN TURNO QUE SALIÓ BIEN NO PUEDE MOSTRAR UN ERROR. deep-chat pinta su propio globo si
  // el stream se cierra sin un evento válido: mentiría sobre un turno exitoso.
  const errBurbujas = await page.evaluate(() => window.__salaQA(".error-message-text").length);
  ok(errBurbujas === 0, "…y el turno exitoso no pinta ningún globo de error", String(errBurbujas));
  const after = await composerState(page);
  ok(after.sendDisabled === false, "tras el turno el Send vuelve a estar vivo");
  ok(page.__errs.length === 0, "cero errores de página", page.__errs.join(" | "));
  await page.close();
}

// ── 8 · (opcional) contra un sidecar REALMENTE trabado ──────────────────────────
// WEDGED_BASE=http://127.0.0.1:PUERTO apunta a un sidecar cuyo camino de ESCRITURA
// quedó colgado de verdad (ver DIAGNOSTICO-SALA-MUDA.md §hallazgo). Es la prueba más
// honesta que hay: no simula el cuelgue, lo usa. La Sala tiene que seguir usable.
const WEDGED = process.env.WEDGED_BASE || SIDECAR;
if (WEDGED) {
  console.log("\n── 8 · contra un sidecar REALMENTE trabado ──");
  const W = WEDGED;
  const wsrv = http.createServer(async (req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname.startsWith("/v1/") || u.pathname === "/health") {
      const ch = []; for await (const c of req) ch.push(c);
      const bb = Buffer.concat(ch);
      const fwd = {}; for (const k of ["authorization", "content-type", "accept"]) if (req.headers[k]) fwd[k] = req.headers[k];
      const up = await fetch(W + req.url, { method: req.method, headers: fwd, body: ["GET", "HEAD"].includes(req.method) ? undefined : (bb.length ? bb : undefined) }).catch(() => null);
      if (!up) { res.writeHead(502); res.end("x"); return; }
      const h = {}; up.headers.forEach((v, k) => { if (!/^(content-encoding|transfer-encoding|connection)$/i.test(k)) h[k] = v; });
      res.writeHead(up.status, h); res.end(Buffer.from(await up.arrayBuffer())); return;
    }
    try { const b = await readFile(join(DESIGN_DIR, decodeURIComponent(u.pathname).replace(/^\//, ""))); res.writeHead(200, { "Content-Type": MIME[extname(u.pathname)] || "application/octet-stream" }); res.end(b); }
    catch { res.writeHead(404); res.end("nf"); }
  });
  await new Promise((r) => wsrv.listen(8239, "127.0.0.1", r));
  // ¿de verdad está trabado? Se PRUEBA el camino de escritura antes de afirmar nada: si el
  // backend responde, este bloque no aplica y se dice — un verde por coincidencia (el regex
  // pegando contra la respuesta REAL del agente) sería peor que no correrlo.
  const trabado = await (async () => {
    try { await fetch(W + "/v1/auth/local", { method: "POST", signal: AbortSignal.timeout(8000) }); return false; }
    catch { return true; }
  })();
  if (!trabado) {
    console.log("· omitido: el backend NO quedó trabado en esta corrida (camino de escritura sano).");
    console.log("  para forzarlo: WEDGED_BASE=<sidecar trabado> node verify_sala_viva.mjs");
    wsrv.close();
  } else {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(SESSION + pickBrain("claude_cli", "cli"));
  await page.goto(`http://127.0.0.1:8239/sala/sala.html`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForFunction(() => window.__salaQ && window.__salaQ("#text-input"), null, { timeout: 25000 }).catch(() => {});
  await page.waitForTimeout(5200);
  const st = await composerState(page);
  ok(st.w >= MIN_COMPOSER, `el campo sigue usable (${st.w}px) con el backend trabado`);
  await escribir(page, "con el backend trabado");
  ok((await textoComposer(page)) === "con el backend trabado", "se puede escribir igual");
  await enviar(page);
  let soltado = false;
  for (let i = 0; i < 16; i++) {
    await page.waitForTimeout(4000);
    if (!(await enVuelo(page))) { soltado = true; break; }
  }
  ok(soltado, "el turno TERMINA (no queda colgado para siempre) pese al backend trabado");
  const chat = await chatTexto(page);
  // el texto EXACTO del guardián de arranque — no un regex laxo que cualquier respuesta cumple
  ok(/no pude ni empezar el turno|corté la espera/i.test(chat), "y explica qué pasó", JSON.stringify(chat.slice(-90)));
  await page.close(); wsrv.close();
  }
}

console.log(`\n══ ${fails.length ? "FALLARON " + fails.length : "TODO VERDE"} ══`);
if (fails.length) fails.forEach((f) => console.log("  ✗ " + f.trim()));
await browser.close();
server.close();
killSidecar();
process.exit(fails.length ? 1 : 0);
