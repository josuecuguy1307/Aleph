/* arnes_costura_obraB.mjs — EL BRAZO DEL FRENTE DE LA OBRA B (Gate 3).
 *
 * No es una vara: es el brazo de `platform/assembler/verify_costura_obraB.py`, que es quien
 * afirma. Acá se MIDE y se imprime JSON por stdout. Mismo método que las obras 5 y A.
 *
 *   node product/app/design/sala/arnes_costura_obraB.mjs
 *
 * ── QUÉ MIDE, Y POR QUÉ ASÍ ─────────────────────────────────────────────────────────
 * El corte 1 vive entero en el frente, así que casi todo lo de esta obra sólo se puede
 * probar EJECUTANDO la Sala. Leer el archivo no alcanza para tres cosas:
 *
 *   · que el cerebro del agente SOBREVIVA a la hidratación — el bug era justamente que
 *     una línea posterior lo pisaba, y eso sólo se ve corriendo las dos en orden;
 *   · que el selector sea EL MISMO widget del Cuarto — se compara el DOM que monta la Sala
 *     contra el que produce `AlephModelSelector.html`, la pieza compartida;
 *   · que sin confirmar NO se escriba — se intercepta el PUT y se cuenta.
 *
 * El `PUT /v1/puppets/{id}/config` se INTERCEPTA (no se manda a ningún backend): la vara
 * mide QUÉ se iba a escribir, que es el contrato, sin tocar una DB real.
 *
 * CERO RED: todo `/v1/**` se contesta desde el interceptor. Puerto EFÍMERO del SO — JAMÁS
 * :8377 (varas de otro carril) ni :25374 (la .app instalada de persona usuaria).
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const DISENO = path.resolve(AQUI, "..");

function raizPrincipal() {
  const comun = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
                             { cwd: AQUI }).toString().trim();
  return path.dirname(comun);
}
const _pw = await import(pathToFileURL(
  path.join(raizPrincipal(), "node_modules", "playwright", "index.js")).href);
const { webkit } = _pw.webkit ? _pw : _pw.default;

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
               ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
               ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
               ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
               ".map": "application/json", ".wasm": "application/wasm" };

function servirDiseno() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const limpio = decodeURIComponent((req.url || "/").split("?")[0]);
      const destino = path.join(DISENO, path.normalize(limpio).replace(/^(\.\.[/\\])+/, ""));
      if (!destino.startsWith(DISENO) || !fs.existsSync(destino) || fs.statSync(destino).isDirectory()) {
        res.writeHead(404).end("no");
        return;
      }
      res.writeHead(200, { "content-type": MIME[path.extname(destino)] || "application/octet-stream" });
      fs.createReadStream(destino).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve({ srv, port: srv.address().port }));
  });
}

/* EL AGENTE DE PRUEBA. Su cerebro es `qwen-local` (Qwen3 8B, ollama) — se elige a propósito
 * uno que NO sea el default del catálogo, para que «sobrevivió» no se pueda confundir con
 * «cayó en el default por casualidad». La receta trae la forma que compila el Cuarto. */
const CEREBRO_DEL_AGENTE = { id: "qwen-local", primary: "qwen3:8b",
                             base_url: "http://127.0.0.1:11434/v1" };
const RECETA = {
  meta: { name: "Agente de la vara" },
  model: { primary: CEREBRO_DEL_AGENTE.primary, base_url: CEREBRO_DEL_AGENTE.base_url,
           alias: "oss-direct", fallback: null, temperature: 0, max_tokens: 700, max_turns: 8 },
  framing: { inline: "" },
};
/* EL SELECTOR DEL SIDECAR dice OTRA cosa. Éste es el pisador: si la obra falla, gana esto. */
const SELECTOR_AJENO = { seleccion_id: "oss", default_id: "oss" };
/* EL CATÁLOGO, SEMBRADO — y por qué: sin backend, `loadModels` devuelve la curada con CERO
 * conectados (medido: `byId` vacío), así que `modelEntry` no resuelve ningún id y `powPick`
 * se va por su early-return. Lo que esta vara mide NO es el catálogo —eso es de F8 y tiene
 * su propia vara— sino el contrato que va DESPUÉS de elegir: confirmar y persistir. Las dos
 * filas son las reales del catálogo curado (`cuarto.models.js:19,23`), copiadas por VALOR. */
const CATALOGO = [
  { id: "qwen-local", label: "Qwen3 8B", model: "qwen3:8b",
    base_url: "http://127.0.0.1:11434/v1", alias: "oss-direct", conectado: true },
  { id: "oss", label: "GPT-OSS 120B", model: "openai/gpt-oss-120b",
    base_url: "https://api.groq.com/openai/v1", alias: "oss", conectado: true },
];

const salida = { errores_de_pagina: [], vb1: null, vb2: null, vb3: null, vb4: null, vb5: null };
const { srv, port } = await servirDiseno();
const browser = await webkit.launch();

async function abrir() {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
  // Todo /v1/** contesta desde acá. Los PUT de config se REGISTRAN: son el contrato de O3.
  await pg.route("**/v1/**", async (r) => {
    const req = r.request();
    if (req.method() === "PUT" && /\/v1\/puppets\/[^/]+\/config/.test(req.url())) {
      await pg.evaluate((b) => { (window.__puts = window.__puts || []).push(JSON.parse(b)); },
                        req.postData() || "{}");
      return r.fulfill({ status: 200, contentType: "application/json", body: '{"ok":true}' });
    }
    return r.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await pg.goto(`http://127.0.0.1:${port}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => !!window.__salaCerebro && !!window.__models_listo_o_no,
                           null, { timeout: 45000 }).catch(() => {});
  await pg.waitForFunction(() => !!window.__salaCerebro, null, { timeout: 45000 });
  // el catálogo de modelos se carga solo; se espera a que `modelEntry` pueda resolver ids
  await pg.waitForFunction(() => !!(window.AlephModelSelector), null, { timeout: 45000 });
  // el catálogo por el camino REAL: sin backend cae a la lista curada, que es lo que corre
  // en la vara. Sin esto `modelEntry` devuelve null y `powPick` se va por el early-return.
  await pg.evaluate(() => window.__salaCerebro.cargar());
  await pg.waitForFunction(() => !!(window.__salaCerebro.selector) , null, { timeout: 45000 });
  return pg;
}

/** Siembra el selector del sidecar con una elección DISTINTA a la del agente. */
const SEMBRAR = (sel, cat) => {
  window.__puts = [];
  window.__salaCerebro.sembrarModelos(cat, sel);
};

try {
  // ══ VB1 · el cerebro del agente sobrevive a la hidratación ═══════════════════════
  const pg = await abrir();
  salida.vb1 = await pg.evaluate(async ({ receta, sel, cat, sembrar, esperado }) => {
    new Function("sel", "cat", "return (" + sembrar + ")(sel, cat)")(sel, cat);
    const power = window.__salaCerebro.hidratar(receta, "pup-vara-1");
    await new Promise((r) => setTimeout(r, 150));
    const aCorrer = window.__salaCerebro.aCorrer();
    return {
      manda: window.__salaCerebro.manda(),
      power: window.__salaCerebro.power(),
      power_tras_hidratar: power,
      primary_a_correr: aCorrer && aCorrer.model && aCorrer.model.primary,
      base_url_a_correr: aCorrer && aCorrer.model && aCorrer.model.base_url,
      esperado,
      selector_decia: (window.__salaCerebro.selector() || {}).seleccion_id || null,
    };
  }, { receta: RECETA, sel: SELECTOR_AJENO, cat: CATALOGO, sembrar: SEMBRAR.toString(),
       esperado: CEREBRO_DEL_AGENTE.primary });

  // ══ VB2 · el selector de la Sala es EL MISMO widget del Cuarto ═══════════════════
  salida.vb2 = await pg.evaluate(async () => {
    window.__salaCerebro.abrir();
    await new Promise((r) => setTimeout(r, 250));
    const host = document.getElementById("salaModelSelector");
    const dom = host ? host.innerHTML : "";
    // el MISMO componente, invocado a mano con los mismos datos: si la Sala montara un
    // control propio, estas dos cadenas no se parecerían en nada.
    const api = window.AlephModelSelector;
    const propio = api && api.html
      ? api.html({ contexto: "sala", data: (window.__salaCerebro.selector() || {}),
                   modelos: [], todos: true })
      : "";
    const clasesDe = (s) => Array.from(new Set((s.match(/class="([^"]+)"/g) || [])
      .flatMap((m) => m.slice(7, -1).split(/\s+/)))).sort();
    const cSala = clasesDe(dom), cWidget = clasesDe(propio);
    return {
      montado: !!host && dom.length > 0,
      clases_sala: cSala,
      clases_widget: cWidget,
      // ¿el DOM de la Sala está hecho de las clases del widget compartido?
      comunes: cWidget.filter((c) => cSala.includes(c)),
      solo_en_sala: cSala.filter((c) => !cWidget.includes(c)),
      tiene_marca_ams: /ams|modelo/i.test(dom),
    };
  });

  // ══ VB4 · sin confirmar NO se escribe ════════════════════════════════════════════
  salida.vb4 = await pg.evaluate(async () => {
    window.__puts = [];
    window.__salaCerebro.abrir();
    await new Promise((r) => setTimeout(r, 200));
    window.__salaCerebro.elegir("oss");                 // elegir, y NO confirmar
    await new Promise((r) => setTimeout(r, 200));
    const pop = document.getElementById("sbpModeloWidget");
    const botones = pop ? Array.from(pop.querySelectorAll(".power-seg button")).map((b) => b.textContent) : [];
    const sinConfirmar = { puts: (window.__puts || []).length,
                           power: window.__salaCerebro.power(),
                           receta_primary: (window.__salaCerebro.receta() || {}).model.primary,
                           pide_confirmacion: botones.length === 2, botones };
    // ahora se CANCELA: tampoco escribe, y el cerebro queda como estaba
    const cancelar = pop && Array.from(pop.querySelectorAll(".power-seg button"))
      .find((b) => /dejarlo|leave/i.test(b.textContent));
    if (cancelar) cancelar.click();
    await new Promise((r) => setTimeout(r, 150));
    sinConfirmar.puts_tras_cancelar = (window.__puts || []).length;
    sinConfirmar.receta_tras_cancelar = (window.__salaCerebro.receta() || {}).model.primary;
    return sinConfirmar;
  });

  // ══ VB3 · confirmar → escribe en la MISMA fuente → el Cuarto lo lee ══════════════
  salida.vb3 = await pg.evaluate(async () => {
    window.__puts = [];
    window.__salaCerebro.abrir();
    await new Promise((r) => setTimeout(r, 200));
    window.__salaCerebro.elegir("oss");                 // el nuevo cerebro: Y
    await new Promise((r) => setTimeout(r, 200));
    const pop = document.getElementById("sbpModeloWidget");
    const ok = pop && Array.from(pop.querySelectorAll(".power-seg button"))
      .find((b) => /cambiar|change/i.test(b.textContent));
    if (ok) ok.click();
    await new Promise((r) => setTimeout(r, 400));
    const puts = window.__puts || [];
    const cfg = puts.length ? puts[puts.length - 1].config : null;
    // EL VIAJE COMPLETO: lo que se persistió se le da a leer al Cuarto, con SU función.
    const Mod = await import("/cuarto/cuarto.models.js");
    return {
      puts: puts.length,
      endpoint_correcto: true,
      primary_persistido: cfg && cfg.model && cfg.model.primary,
      // `modelIdForRecipe` es LA función con la que el núcleo del Cuarto lee una receta
      id_que_leeria_el_cuarto: cfg ? Mod.modelIdForRecipe(cfg) : null,
      power_en_sala: window.__salaCerebro.power(),
      receta_en_memoria: (window.__salaCerebro.receta() || {}).model.primary,
    };
  });

  // ══ VB5 · chat SIN agente: el selector sigue funcionando ═════════════════════════
  salida.vb5 = await pg.evaluate(async ({ sel, cat, sembrar }) => {
    new Function("sel", "cat", "return (" + sembrar + ")(sel, cat)")(sel, cat);
    window.__salaCerebro.hidratar(null, null);          // sin agente
    await new Promise((r) => setTimeout(r, 150));
    const manda = window.__salaCerebro.manda();
    window.__puts = [];
    window.__salaCerebro.elegir("oss");                 // directo, sin confirmación
    await new Promise((r) => setTimeout(r, 250));
    return { manda, puts: (window.__puts || []).length,
             power: window.__salaCerebro.power(),
             pop_abierto: !!(document.getElementById("powpop") || {}).classList?.contains("on") };
  }, { sel: SELECTOR_AJENO, cat: CATALOGO, sembrar: SEMBRAR.toString() });

  // ══ VB7 · el aviso de sustitución en el DOM, y NO en rojo ════════════════════════
  salida.vb7 = await pg.evaluate(async () => {
    const antes = document.querySelectorAll("deep-chat") ? 1 : 0;
    window.__salaCerebro.sustituir({ causa: "modelo_sustituido", pedido: "qwen3:8b",
                                     usado: "openai/gpt-oss-20b", causa_origen: "proveedor_caido" });
    await new Promise((r) => setTimeout(r, 350));
    const host = document.querySelector("deep-chat");
    const sr = host && host.shadowRoot;
    const txt = sr ? (sr.textContent || "") : "";
    const rojos = sr ? sr.querySelectorAll(".ac-act.fail, .errcard").length : -1;
    return { antes, texto_tiene_aviso: /respaldo|backup/i.test(txt),
             menciona_pedido: /qwen/i.test(txt), menciona_usado: /gpt-oss|oss/i.test(txt),
             menciona_causa: /proveedor|provider/i.test(txt), cards_rojas: rojos };
  });

  await pg.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
