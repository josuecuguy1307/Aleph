/* verify_cuarto_modelos.mjs — VARA · EL CEREBRO DEL AGENTE EN EL CUARTO (F7 · obra B).
 *
 * LOS TRES BUGS QUE ESTA VARA EXISTE PARA IMPEDIR, los tres medidos el 2026-08-06 sobre la
 * app instalada (`~/Desktop/AUDITORIA-PLATAFORMA-MODELOS.md` §3):
 *
 *   1. **la llave se tiraba a la basura** — `saveKey()` no tenía NINGÚN fetch: escribía el
 *      id en un array local (`keyedModels`) y el modelo quedaba «configurado». Censo de las
 *      1.270 recetas reales de la DB: **cero** con un modelo BYOK de API.
 *   2. **catálogo propio de 12 modelos** hardcodeado, desincronizado de la fuente: ofrecía
 *      `o3-mini`, `gpt-4o-mini`, `claude-haiku`… que `centro_modelos.HOSTEADOS` ni declara.
 *   3. **cero semáforo**: `grep -c "brains/status|modelos/selector|modelos/v2|cuarto.models"
 *      Cuarto.dc.html` → **0**. Se elegía el cerebro a ciegas.
 *
 * Y el cuarto, que salió al medir: la receta no llevaba `byok_ref`, así que el turno salía
 * SIN credencial y el 401 se leía «el proveedor rechazó la credencial».
 *
 * Sirve la UI de fuente con un sidecar-fixture propio; no toca el sidecar del humano.
 *
 *     node qa/verify_cuarto_modelos.mjs
 */
import http from "node:http";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";

import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const DESIGN = join(ROOT, "product", "app", "design");
// El diccionario ÚNICO, importado de verdad: las aserciones de copy se derivan de él.
const SEM = await import(join(DESIGN, "cuarto", "cuarto.semaforo.js"));
const PORT = 8399;
let keyPosts = [];
const SELECTOR = {
  version: 2, default: "cli.claude_cli", default_id: "claude_cli", seleccion_id: "claude_cli",
  modelos: [
    { slug: "cli.claude_cli", picker_id: "claude_cli", familia: "cli", label: "Claude Code",
      sub: "Tu suscripción", model: "claude-code-cli", base_url: "http://127.0.0.1:8926/v1",
      brain_provider: "claude_cli", estado: "probado", conectado: true, default: true },
    { slug: "api.anthropic", picker_id: "api:anthropic", familia: "api", label: "Anthropic",
      sub: "Claude con tu propia llave", model: "claude-opus-4-8",
      base_url: "https://api.anthropic.com/v1", byok_ref: "keys:anthropic",
      estado: "no_configurado", hay_llave: false, conectado: false },
    { slug: "api.openrouter", picker_id: "api:openrouter", familia: "api", label: "OpenRouter",
      sub: "Un montón de modelos", model: "openai/gpt-4o", base_url: "https://openrouter.ai/api/v1",
      byok_ref: "keys:openrouter", estado: "roto", causa: "key_invalida", hay_llave: true,
      conectado: false },
  ],
};
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };
const srv = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  const J = (o, c = 200) => { res.writeHead(c, { "Content-Type": "application/json" }); res.end(JSON.stringify(o)); };
  /* ⚠️ EL FIXTURE TIENE QUE DISCRIMINAR `todos`, o no mide nada.
   *
   * Medido al calibrar (2026-08-06): con este endpoint devolviendo SIEMPRE la lista
   * completa, se podía sacar `todos:true` de la pantalla canónica y las 13 aserciones
   * seguían VERDES. Un fixture que contesta lo mismo a las dos preguntas no puede cazar
   * una diferencia entre las dos preguntas — es el mismo defecto que la obra 4 de F7 le
   * encontró a `verify_modelos_v2` (su stub decía `probado` a cualquier llave).
   *
   * El backend real filtra igual: `selector_modelos` deja pasar
   * `todos or conectado or slug == default` (centro_modelos.py). */
  if (u.pathname === "/v1/modelos/selector") {
    const todos = u.searchParams.get("todos") === "1";
    return J({ ...SELECTOR, modelos: SELECTOR.modelos.filter((m) =>
      todos || m.conectado === true || m.slug === SELECTOR.default) });
  }
  if (u.pathname === "/v1/conexiones/key" && req.method === "POST") {
    let b = ""; for await (const c of req) b += c;
    const { provider, secret } = JSON.parse(b || "{}");
    keyPosts.push({ provider, secret });
    if (!/^sk-/.test(secret))
      return J({ ok: false, estado: "roto", causa: "key_invalida", guardada: false,
                 mensaje: `${provider} rechazó la llave (401): no sirve. No la guardé.` }, 200);
    SELECTOR.modelos[1] = { ...SELECTOR.modelos[1], estado: "probado", hay_llave: true, conectado: true };
    return J({ ok: true, estado: "probado", guardada: true, mensaje: `${provider} aceptó tu llave.` });
  }
  if (u.pathname === "/v1/modelos/preferencias" && req.method === "PUT") {
    let b = ""; for await (const c of req) b += c;
    const { contexto, seleccion } = JSON.parse(b || "{}");
    SELECTOR.seleccion = seleccion;
    SELECTOR.seleccion_id = (SELECTOR.modelos.find((m) => m.slug === seleccion) || {}).picker_id;
    return J({ contextos: { [contexto]: seleccion } });
  }
  if (u.pathname === "/v1/brains/status")
    return J({ providers: { claude_cli: { state: "ready" } }, service: { state: "ready" } });
  if (u.pathname.startsWith("/v1/")) return J({});
  const rel = decodeURIComponent(u.pathname).replace(/^\/+/, "") || "Cuarto.dc.html";
  try {
    const body = await readFile(join(DESIGN, rel));
    res.writeHead(200, { "Content-Type": MIME[extname(rel)] || "application/octet-stream" });
    res.end(body);
  } catch { res.writeHead(404); res.end("no"); }
});
await new Promise((r) => srv.listen(PORT, "127.0.0.1", r));

// [H5] `createRequire(<raíz>/package.json)` resolvía sólo en el árbol principal: desde un
// worktree daba ERR_MODULE_NOT_FOUND —un stack de Node, no un veredicto— porque
// `node_modules` no está en git. `requerir` prueba el árbol propio y después el principal.
const { requerir } = await import(join(ROOT, "qa", "lib", "node_deps.mjs"));
const { webkit } = requerir("playwright");
const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e.message || e)));
await page.addInitScript(() => sessionStorage.setItem("puppet_user",
  JSON.stringify({ id: "vara", session_token: "tok" })));

let fallos = 0;
const ok = (c, n, x = "") => { console.log(`${c ? "✓" : "✗"} ${n}${x ? " · " + String(x).slice(0, 150) : ""}`); if (!c) fallos++; };

await page.goto(`http://127.0.0.1:${PORT}/Cuarto.dc.html`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2500);

const abrir = async () => {
  const b = page.locator("text=/Cerebro|Modelo|GPT-OSS|Claude Code|Cognición/i").first();
  await b.click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(600);
};
await abrir();
const txt = await page.locator("body").innerText();

ok(!/GPT-OSS 120B|o3-mini|gpt-4o-mini|Llama 3\.3 70B/.test(txt),
   "★ el catálogo hardcodeado de 12 modelos YA NO aparece", txt.match(/o3-mini|GPT-OSS 120B/g));
ok(/Claude Code/.test(txt), "★ y sí aparece lo que devolvió el selector (Claude Code)");
ok(/Anthropic/.test(txt), "…y Anthropic, que NO está conectado (todos=1 lo trae igual)");
ok(/falta tu llave|sin configurar|listo|key|Llave/i.test(txt),
   "★ las filas muestran ESTADO, no sólo el nombre");

/* ══ LA LLAVE TIENE QUE SALIR DE LA PÁGINA ═══════════════════════════════════════════ */
const filaAnthropic = page.locator("button", { hasText: "Anthropic" }).first();
await filaAnthropic.click({ timeout: 5000 }).catch(() => {});
await page.waitForTimeout(400);
const campo = page.locator('input[type="password"]').first();
ok(await campo.isVisible().catch(() => false),
   "★ elegir un proveedor sin llave abre el campo (no lo deja elegido a ciegas)");

await campo.fill("basura-que-no-es-una-llave");
await page.locator("text=Guardar y probar").first().click();
await page.waitForTimeout(900);
ok(keyPosts.length === 1 && keyPosts[0].provider === "anthropic",
   "★★ LA LLAVE SALE DE LA PÁGINA — POST /v1/conexiones/key con el provider derivado del slug",
   JSON.stringify(keyPosts.map(k => k.provider)));
const tras = await page.locator("body").innerText();
ok(/no sirve|rechaz/i.test(tras),
   "★ y una llave rechazada SE DICE, con las palabras del backend");

await campo.fill("sk-ant-vara-000000000000");
await page.locator("text=Guardar y probar").first().click();
await page.waitForTimeout(1200);
ok(keyPosts.length === 2 && /^sk-ant-/.test(keyPosts[1].secret),
   "★ y una llave buena también viaja (el flujo no se quedó tildado en el error)");

ok(errores.length === 0, "cero errores JS en el taller", errores.join(" | "));

/* ══ Y LA RECETA LLEVA `byok_ref` ════════════════════════════════════════════════════
 * Se lee del ARCHIVO: es la única forma de comprobar la forma de la receta sin lanzar un
 * agente de verdad. Sin `byok_ref`, el turno sale sin credencial (medido). */
const fuente = await readFile(join(DESIGN, "Cuarto.dc.html"), "utf8");
ok(/byok_ref: selModel\.byok_ref/.test(fuente),
   "★ la receta que sale del Cuarto lleva `model.byok_ref` — sin él el turno va sin llave");
const sinComentarios = fuente
  .replace(/\/\*[\s\S]*?\*\//g, "")      // bloques
  .replace(/^\s*\/\/.*$/gm, "")           // línea completa
  .replace(/<!--[\s\S]*?-->/g, "");        // HTML
ok(!/keyedModels/.test(sinComentarios),
   "★ y `keyedModels` (el array local donde la llave moría) ya no existe en el CÓDIGO",
   (sinComentarios.match(/.{0,60}keyedModels.{0,40}/) || [])[0]);

/* ══════════════════════════════════════════════════════════════════════════════════════
 * §2 · LA PANTALLA CANÓNICA — `cuarto/cuarto.pixi.html`  [F7·C]
 *
 * ⚠️ POR QUÉ ESTA SECCIÓN EXISTE. Todo lo de arriba mide `Cuarto.dc.html`, y
 * `main.py:1102` REDIRIGE `/Cuarto.dc.html` → `/cuarto/cuarto.pixi.html` desde el
 * 2026-07-22 (`669fc73`): el builder viejo sólo se alcanza con `?builder=legacy`. O sea que
 * la obra B arregló la pantalla de atrás, y esta vara la estaba cuidando MUY bien mientras
 * la que el usuario abre no tenía a nadie mirándola.
 *
 * Va acá y no en un archivo nuevo a propósito: es la MISMA obra, el MISMO fixture y las
 * MISMAS aserciones sobre otra superficie. Multiplicar varas fue justo lo que dejó a esta
 * pantalla sin guard.
 * ════════════════════════════════════════════════════════════════════════════════════ */
SELECTOR.modelos[1] = { ...SELECTOR.modelos[1], estado: "no_configurado", hay_llave: false, conectado: false };
SELECTOR.seleccion_id = "claude_cli";
keyPosts = [];
errores.length = 0;

await page.goto(`http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(6000);
await page.evaluate(() => {
  window.__openInspector(window.__cuarto.nucleoData());
  if (window.__setInspectorExpanded) window.__setInspectorExpanded(true);
});
await page.waitForTimeout(1500);

const pxFilas = await page.evaluate(() =>
  Array.from(document.querySelectorAll(".ams-option[data-model]")).map((b) => ({
    id: b.dataset.model,
    meta: (b.querySelector(".ams-meta") || {}).textContent || "",
    accion: (b.querySelector(".ams-use") || {}).textContent || "",
    keyProv: b.dataset.keyProvider || "",
  })));
const px = (id) => pxFilas.find((f) => f.id === id) || {};

ok(pxFilas.length === 3,
   "★ [canónica] el picker ofrece TAMBIÉN lo no configurado — sin eso no hay dónde poner la llave",
   JSON.stringify(pxFilas.map((f) => f.id)));
ok(/Sin configurar/.test(px("api:anthropic").meta || ""),
   "★ [canónica] y cada fila dice su ESTADO con el copy del diccionario único",
   px("api:anthropic").meta);
ok(!/no_configurado|key_invalida|falta_key/.test(pxFilas.map((f) => f.meta).join(" ")),
   "★ [canónica] JAMÁS el nombre técnico de la causa en la cara (regla sellada)",
   pxFilas.map((f) => f.meta).join(" | "));
// ⚠️ SE DERIVA DEL DICCIONARIO, NO SE HARDCODEA. Esta aserción decía `/no sirve|llave/i`,
// o sea la frase de ese día — y el 2026-08-07 persona usuaria selló «Credencial inválida» y la vara
// se habría puesto roja por un cambio de copy CORRECTO. Una vara que hay que editar cada
// vez que se sella una palabra enseña a editarla sin mirar. Lo que esta línea tiene que
// afirmar es «la fila dice LO QUE EL DICCIONARIO DICE», no un texto en particular.
ok((px("api:openrouter").meta || "").includes(SEM.CAUSAS.key_invalida.es),
   `★ [canónica] una llave rechazada se dice con el copy del diccionario («${SEM.CAUSAS.key_invalida.es}»), no «no disponible»`,
   px("api:openrouter").meta);
ok(px("api:anthropic").keyProv === "anthropic",
   "★ [canónica] el provider del trámite sale de `byok_ref` (dato del backend), no del nombre");
ok(!/Usar este modelo/.test(px("api:anthropic").accion || ""),
   "★ [canónica] un modelo sin llave NO ofrece «usar»: ofrece su trámite", px("api:anthropic").accion);

const pxRechazo = await page.evaluate(async () => {
  const b = document.querySelector('.ams-option[data-key-provider="anthropic"]');
  if (!b) return { abierto: false };
  b.click();
  await new Promise((r) => setTimeout(r, 300));
  const caja = document.querySelector(".ams-keybox:not([hidden])");
  if (!caja) return { abierto: false };
  const inp = caja.querySelector(".ams-keyin");
  inp.value = "basura-que-no-es-una-llave";
  caja.querySelector(".ams-keysave").click();
  await new Promise((r) => setTimeout(r, 900));
  const msg = caja.querySelector(".ams-keymsg");
  return { abierto: true, msg: (msg || {}).textContent || "", cls: (msg || {}).className || "",
           elegido: window.__cuarto.nucleoData().model };
});
ok(pxRechazo.abierto,
   "★ [canónica] elegir un modelo sin llave ABRE EL CAMPO, no lo deja elegido a ciegas");
ok(keyPosts.length === 1 && keyPosts[0].provider === "anthropic",
   "★★ [canónica] LA LLAVE SALE DE LA PÁGINA — POST /v1/conexiones/key",
   JSON.stringify(keyPosts.map((k) => k.provider)));
ok(/no sirve|rechaz/i.test(pxRechazo.msg) && /mal/.test(pxRechazo.cls),
   "★ [canónica] y el rechazo se dice con las palabras del backend", pxRechazo.msg);
ok(pxRechazo.elegido !== "api:anthropic",
   "★ [canónica] una llave rechazada NO deja el modelo elegido", pxRechazo.elegido);

const pxBuena = await page.evaluate(async () => {
  const caja = document.querySelector(".ams-keybox:not([hidden])");
  caja.querySelector(".ams-keyin").value = "sk-ant-vara-000000000000";
  caja.querySelector(".ams-keysave").click();
  await new Promise((r) => setTimeout(r, 2500));
  return { elegido: window.__cuarto.nucleoData().model,
           receta: ((window.__lastRecipe || {}).model || {}) };
});
ok(pxBuena.elegido === "api:anthropic",
   "★★ [canónica] una llave VALIDADA deja el modelo elegido — por la puerta de `persist`",
   pxBuena.elegido);
ok(/keys:anthropic/.test(JSON.stringify(pxBuena.receta)) || pxBuena.receta.byok_ref === "keys:anthropic",
   "★ [canónica] y la receta lleva `model.byok_ref` — sin él el turno va sin credencial",
   JSON.stringify(pxBuena.receta));

/* Y EL POOL DE LA SALA NO SE CONTAMINA. Son dos payloads del mismo endpoint y comparten
 * cache: si el taller pide `todos` y la Sala lee después, la Sala no puede empezar a
 * ofrecer modelos sin llave sólo porque alguien pasó por el taller. */
const pools = await page.evaluate(async () => {
  const pool = await window.AlephModelSelector.load("sala", true, false);
  const todo = await window.AlephModelSelector.load("sala", true, true);
  return { pool: window.AlephModelSelector.options({ contexto: "sala", data: pool }).map((m) => m.id),
           todos: window.AlephModelSelector.options({ contexto: "sala", data: todo, todos: true }).map((m) => m.id) };
});
ok(!pools.pool.includes("api:openrouter") && pools.todos.includes("api:openrouter"),
   "★★ [canónica] el POOL de la Sala sigue siendo el pool: el catálogo del taller no lo contamina",
   "pool=" + JSON.stringify(pools.pool) + " todos=" + JSON.stringify(pools.todos));

ok(errores.length === 0, "cero errores JS en la pantalla canónica", errores.join(" | "));

console.log(fallos ? `\n✗ CUARTO: ${fallos} falla(s)` : "\n✓ CUARTO · todo verde");
await browser.close(); srv.close();
process.exit(fallos ? 1 : 0);
