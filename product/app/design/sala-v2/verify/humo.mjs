/* humo.mjs — ¿la pantalla ARRANCA?
 *
 * La vara chica que va antes de la grande. Sirve `design/` como estáticos, abre
 * `sala-v2.html` en WebKit y mide TRES cosas que, si fallan, hacen que todo lo demás sea
 * ruido:
 *
 *   1. El bundle vendorizado que sirve el servidor es EXACTAMENTE el que produjo el build
 *      (sha384 contra `assistant-ui.bundle.js.sri`). Sin esto, medir la pantalla es medir
 *      un artefacto desconocido.
 *   2. La pantalla monta: cero errores de consola, cero `pageerror`, y el árbol de React
 *      llegó al DOM (hilo + composer + menú lateral).
 *   3. El composer es USABLE de verdad (ancho real ≥ mínimo, acepta teclado). Es el defecto
 *      que ya mordió una vez en la Sala vieja y por el que existe `verify_sala_viva.mjs`.
 *
 * No toca el backend: acá no hay turno. El turno es la vara de la fase.
 *
 * Run:  node product/app/design/sala-v2/verify/humo.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { join, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN = join(HERE, "..", "..");
const PORT = Number(process.env.HUMO_PORT || 8244);
const PAGE = `http://127.0.0.1:${PORT}/sala-v2/sala-v2.html`;
const MIN_COMPOSER = 140;

const fails = [];
const ok = (n) => console.log(`  ✅ ${n}`);
const bad = (n, d) => {
  fails.push(`${n}${d ? " — " + d : ""}`);
  console.log(`  ❌ ${n}${d ? " — " + d : ""}`);
};

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  // normalize + prefijo: sin esto un `..%2f` sale del árbol servido.
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, "");
  const file = join(DESIGN, rel);
  if (!file.startsWith(DESIGN)) {
    res.writeHead(403).end("no");
    return;
  }
  try {
    const body = await readFile(file);
    res.writeHead(200, { "Content-Type": MIME[extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404).end("404 " + rel);
  }
});

await new Promise((r) => server.listen(PORT, "127.0.0.1", r));
console.log(`\n· estático en :${PORT}\n`);

// ── 1 · el bundle servido == el bundle construido ────────────────────────────────────
console.log("1 · el bundle es el que se construyó");
{
  const bytes = readFileSync(join(DESIGN, "sala-v2/vendor/assistant-ui.bundle.js"));
  const esperado = readFileSync(join(DESIGN, "sala-v2/vendor/assistant-ui.bundle.js.sri"), "utf8").trim();
  const real = "sha384-" + crypto.createHash("sha384").update(bytes).digest("base64");
  if (real === esperado) ok(`sha384 coincide (${bytes.length} bytes)`);
  else bad("sha384 NO coincide", `esperado ${esperado} · real ${real}`);
}

// ── 2 y 3 · monta y se puede usar ────────────────────────────────────────────────────
const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 840 } });
const consola = [];
const errores = [];
page.on("console", (m) => {
  if (m.type() === "error") consola.push(m.text());
});
page.on("pageerror", (e) => errores.push(String(e && e.message)));

console.log("\n2 · la pantalla monta");
await page.goto(PAGE, { waitUntil: "load" });
// El árbol de React monta después del `load` (los ESM se resuelven en cadena).
await page.waitForSelector(".sv-composer textarea", { timeout: 15000 }).catch(() => {});

const tiene = async (sel) => (await page.$(sel)) !== null;
(await tiene(".sv-spine")) ? ok("el menú lateral está") : bad("no montó el menú lateral");
(await tiene(".sv-main")) ? ok("el hilo está") : bad("no montó el hilo");
(await tiene(".sv-composer")) ? ok("el composer está") : bad("no montó el composer");

// Los hilos viven DENTRO de La Sala (1.5): la lista tiene que existir aunque esté vacía.
(await tiene(".sv-hilos")) ? ok("los hilos viven adentro de La Sala") : bad("no está la lista de hilos");
// [cosecha de Gate 4 · Fase 3] LA SECCIÓN DE WORKSPACES: o hay filas, o NO EXISTE.
// Antes esto exigía que el estado vacío estuviera pintado (`.sv-ws-vacia`). Un encabezado
// «Workspaces» sobre un texto que explica que no hay ninguno le enseña al usuario una
// categoría vacía y le pide que la entienda: eso es catálogo, que es lo que la ley de
// producto 6 prohíbe. Hoy no hay ningún stack heredado adentro, así que lo correcto es
// que no haya nada — y este assert cae si vuelve a aparecer el estado vacío.
{
  const filas = await tiene(".sv-link[href*='workspace']");
  const vacia = await tiene(".sv-ws-vacia");
  if (filas && !vacia) ok("la sección de workspaces tiene filas");
  else if (!filas && !vacia) ok("cero workspaces elegibles ⇒ la sección NO se dibuja");
  else bad("la sección de workspaces pinta un estado vacío en vez de no existir");
}

if (!errores.length) ok("cero pageerror");
else bad(`${errores.length} pageerror`, errores.slice(0, 3).join(" | "));

// Un 404 de un estático que la página necesita sale por consola como error de red; se
// distingue del ruido de favicon.
const duros = consola.filter((t) => !/favicon|Failed to load resource.*favicon/i.test(t));
if (!duros.length) ok("cero errores de consola");
else bad(`${duros.length} errores de consola`, duros.slice(0, 3).join(" | "));

console.log("\n3 · el composer se puede usar");
const caja = await page.$(".sv-composer textarea");
if (!caja) bad("no hay textarea");
else {
  const bb = await caja.boundingBox();
  if (bb && bb.width >= MIN_COMPOSER) ok(`ancho real ${Math.round(bb.width)}px (≥ ${MIN_COMPOSER})`);
  else bad("composer estrangulado", `ancho ${bb ? Math.round(bb.width) : "sin caja"}px`);

  await caja.click();
  await page.keyboard.type("hola");
  const v = await caja.inputValue().catch(() => "");
  v.includes("hola") ? ok("acepta teclado") : bad("no acepta teclado", `valor="${v}"`);

  // El botón de enviar tiene que existir y NO estar inerte con texto adentro.
  const send = await page.$(".sv-enviar");
  if (!send) bad("no hay botón de enviar");
  else {
    const dis = await send.isDisabled().catch(() => false);
    dis ? bad("el enviar quedó inerte con texto escrito") : ok("el enviar está vivo");
  }
}

await browser.close();
server.close();

console.log("\n" + "─".repeat(58));
if (fails.length) {
  console.log(`HUMO: ${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("HUMO: todo verde");
