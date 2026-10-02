#!/usr/bin/env node
/**
 * verify_selector_unico.mjs — EL SELECTOR ES UNO SOLO. [TANDA 1 · obra 1]
 *
 * QUÉ MIDE, y por qué no lo mide la vara de al lado
 * -------------------------------------------------
 * `verify_cerebro_unico_e2e.py` mide la CADENA: puesta la fuente única, ¿los siete
 * contestan ese cerebro? Eso ya daba VERDE antes de esta obra, porque el backend siempre
 * resolvió por `preferencias-v2.default`. Lo que estaba roto era el otro extremo: **el
 * picker no escribía esa fuente**. Escribía `contextos[<superficie>]` (el selector
 * compartido) o `localStorage` por conversación (el chip de la Sala), y ninguno de los dos
 * lo lee nadie en el camino que ejecuta.
 *
 * O sea: la vara E2E no puede dar rojo por este bug. Ésta sí. Es el testigo del ESLABÓN,
 * no el de la cadena.
 *
 * POR QUÉ SIN NAVEGADOR
 * ---------------------
 * `qa/dom_minimo.mjs` explica la política y la mide: en esta máquina playwright no resuelve
 * (`verify_brain_status_shared.mjs` muere con ERR_MODULE_NOT_FOUND — comprobado 2026-08-22,
 * el paquete sólo existe bajo `third_party/vane/node_modules` y ESM no honra `NODE_PATH`).
 * Una vara que no corre no es una vara verde: es silencio.
 *
 * CORRE: `node product/app/design/verify_selector_unico.mjs`
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { instalarDOM, host } from "../../../qa/dom_minimo.mjs";

const DESIGN = path.dirname(fileURLToPath(import.meta.url));
const fails = [];
const ok = (c, label, extra = "") => {
  console.log(`${c ? "  ✓" : "  ✗"} ${label}${!c && extra ? " — " + extra : ""}`);
  if (!c) fails.push(label);
};

// ── EL SIDECAR, FALSO PERO CON LA FORMA REAL ─────────────────────────────────────────
// `slug` y `picker_id` son DOS vocabularios distintos y el bug de esta casa fue tenerlos
// traducidos en dos lugares. El fixture los siembra DISTINTOS a propósito: si la vara los
// sembrara iguales, un cable que manda `picker_id` donde va `slug` pasaría desapercibido.
const CATALOGO = {
  version: 2,
  default: "cli.claude_cli",
  default_id: "claude_cli",
  seleccion: "cli.codex_cli",        // ← el `contextos` VIEJO que había en disco
  seleccion_id: "codex_cli",
  contextos: { sala: "cli.codex_cli", cuarto: "cli.codex_cli" },
  modelos: [
    { slug: "cli.claude_cli", picker_id: "claude_cli", id: "claude_cli", label: "Claude Code",
      familia: "cli", conectado: true, frontier: true, model: "claude-code-cli", base_url: "" },
    { slug: "cli.codex_cli", picker_id: "codex_cli", id: "codex_cli", label: "Codex",
      familia: "cli", conectado: true, frontier: true, model: "codex-cli", base_url: "" },
    { slug: "cli.grok_cli", picker_id: "grok_cli", id: "grok_cli", label: "Grok",
      familia: "cli", conectado: true, frontier: true, model: "grok-cli", base_url: "" },
  ],
};

const puts = [];
const gets = [];

// ⚠️ COPIA PROFUNDA, y no es cosmética: la primera versión de esta vara devolvía el MISMO
// objeto `CATALOGO` en cada GET, así que `selectorPersist` —que refresca los payloads
// cacheados— lo mutaba, y el chequeo final terminaba leyendo su propia escritura en vez del
// fixture. Daba «rojo» por la razón equivocada, que es tan malo como dar verde.
const copia = (o) => JSON.parse(JSON.stringify(o));

function instalarEntorno() {
  instalarDOM();
  globalThis.location = { href: "http://127.0.0.1:8330/sala-v2/sala-v2.html",
                          pathname: "/sala-v2/sala-v2.html", search: "" };
  globalThis.localStorage = {
    _d: Object.create(null),
    getItem(k) { return k in this._d ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
  };
  globalThis.sessionStorage = globalThis.localStorage;
  globalThis.BroadcastChannel = class { constructor() {} postMessage() {} close() {} };
  globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = (o || {}).detail; } };
  globalThis.dispatchEvent = () => true;
  globalThis.addEventListener = () => {};
  globalThis.removeEventListener = () => {};
  globalThis.fetch = async (url, opts) => {
    const u = String(url);
    opts = opts || {};
    if ((opts.method || "GET").toUpperCase() === "PUT") {
      puts.push({ url: u, body: JSON.parse(opts.body || "{}") });
      return { ok: true, status: 200, json: async () => copia(CATALOGO) };
    }
    gets.push(u);
    if (u.indexOf("/v1/modelos/selector") === 0) {
      return { ok: true, status: 200, json: async () => copia(CATALOGO) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
}

async function main() {
  instalarEntorno();

  // `brain-status.js` es un script clásico (IIFE sobre `window`), no un módulo: se evalúa.
  const src = fs.readFileSync(path.join(DESIGN, "brain-status.js"), "utf8");
  globalThis.window = globalThis;
  globalThis.document.currentScript = { src: "http://127.0.0.1:8330/brain-status.js" };
  // eslint-disable-next-line no-new-func
  new Function(src).call(globalThis);

  const B = globalThis.window.AlephBrain;
  ok(!!B, "AlephBrain quedó montado");
  if (!B) return;

  // ── 1 · LA API DEL CEREBRO ÚNICO EXISTE, y la partida por contexto ya no ────────────
  ok(typeof B.elegirCerebro === "function", "AlephBrain.elegirCerebro existe (el escritor único)");
  ok(typeof B.cerebroElegido === "function", "AlephBrain.cerebroElegido existe (el lector único)");
  ok(typeof B.seleccionDeContexto === "undefined",
     "`seleccionDeContexto` ya no se exporta (la distinción por superficie murió)");
  ok(typeof B.conectoresHref === "function", "AlephBrain.conectoresHref existe (el vault)");

  // ── 2 · ELEGIR ESCRIBE `default`, NO `contextos` ────────────────────────────────────
  puts.length = 0;
  await B.elegirCerebro("grok_cli");
  ok(puts.length === 1, "elegir el cerebro hace exactamente UN PUT", `hubo ${puts.length}`);
  const p = puts[0] || { url: "", body: {} };
  ok(p.url.indexOf("/v1/modelos/preferencias") >= 0,
     "el PUT va a /v1/modelos/preferencias", p.url);
  ok(p.body.default === "cli.grok_cli",
     "el PUT escribe `default` con el SLUG (la fuente que los siete leen)",
     JSON.stringify(p.body));
  ok(!("contexto" in p.body) && !("seleccion" in p.body),
     "el PUT ya NO escribe `contexto`/`seleccion` (el almacén que no gobernaba nada)",
     JSON.stringify(p.body));

  // ── 4 · EL VAULT ES CONECTORES ─────────────────────────────────────────────────────
  const href = B.conectoresHref();
  ok(/Conectores\.dc\.html/.test(href), "«＋ Añadir otro modelo» apunta a Conectores", href);
  ok(!/Modelos\.dc\.html/.test(href), "y NO a la pantalla de elegir", href);

  // ── 5 · LA FILA «＋» DICE LO QUE HACE ───────────────────────────────────────────────
  const h = host("t");
  B.modelSelector.render(h, { contexto: "sala", data: CATALOGO, todos: true });
  const html = h.innerHTML;
  ok(/Añadir otro modelo/.test(html), "la fila «＋ Añadir otro modelo» se pinta");
  ok(/data-add="1"/.test(html), "y conserva el gancho `data-add` que ya existía");

  // ── 6 · UNA ELECCIÓN DESPIERTA A TODAS LAS SUPERFICIES ──────────────────────────────
  // Éste es el testigo de «cambio el cerebro en Diseño y cambia en Finanzas», del lado del
  // navegador. Antes `selectorPersist` refrescaba SÓLO los dos payloads del contexto en el
  // que se hizo el click; los demás quedaban cacheados con la elección vieja hasta un F5.
  const marcadaDe = (frag) =>
    (frag.match(/<button[^>]*class="ams-option on"[^>]*data-model="([^"]+)"/) || [])[1] || null;

  // Se cargan DOS payloads bajo claves distintas (dos superficies) y se elige en una sola.
  await B.modelSelector.load("sala", true, true);
  await B.modelSelector.load("cuarto", true, true);
  // ⚠️ `grok_cli` A PROPÓSITO: no es el `default_id` (claude_cli) NI el `seleccion_id`
  // (codex_cli) del fixture. Con `codex_cli` la aserción se cumplía sola —el payload ya
  // venía marcándolo— y el mutante que rompe el refresco de cache seguía dando VERDE.
  await B.elegirCerebro("grok_cli");

  const sala = B.modelSelector.render(host("t"), { contexto: "sala", todos: true }).innerHTML;
  const cuarto = B.modelSelector.render(host("t2"), { contexto: "cuarto", todos: true }).innerHTML;
  ok(marcadaDe(sala) === "grok_cli",
     "la superficie donde se eligió marca el cerebro nuevo", `marcada=${marcadaDe(sala)}`);
  ok(marcadaDe(cuarto) === "grok_cli",
     "la OTRA superficie, cacheada aparte, marca el MISMO cerebro sin recargar",
     `marcada=${marcadaDe(cuarto)}`);

  // ── 7 · NO SE MANDA `contexto` AL SIDECAR ──────────────────────────────────────────
  // VA AL FINAL, y ahí está la lección: puesta antes de la sección 6 esta aserción pasaba
  // SIEMPRE, porque hasta ese punto la única carga era con `contexto = null`. El mutante
  // que devolvía el query al GET la dejaba verde. Una aserción que corre antes de que el
  // disparador exista no mide: calla. Ahora corre después de dos cargas CON contexto.
  const conCtx = gets.filter((u) => u.indexOf("contexto=") >= 0);
  ok(gets.some((u) => u.indexOf("/v1/modelos/selector") >= 0),
     "hubo GETs del selector que auditar", `gets=${gets.length}`);
  ok(conCtx.length === 0, "ningún GET del selector manda `contexto=`", conCtx.join(" "));

  console.log(fails.length ? `\n✗ ${fails.length} fallo(s)` : "\n✓ selector único: todo verde");
  process.exit(fails.length ? 1 : 0);
}

main().catch((e) => { console.error("✗ la vara reventó:", e); process.exit(2); });
