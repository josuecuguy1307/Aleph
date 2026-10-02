/* arnes_costura_obraD.mjs — EL BRAZO DEL FRENTE DE LA OBRA D (Gate 3).
 *
 * Brazo de `platform/assembler/verify_costura_obraD.py`, que es quien afirma.
 *
 *   node product/app/design/sala/arnes_costura_obraD.mjs
 *
 * ══ LO QUE ESTE ARNÉS HACE DISTINTO, Y ES TODO EL PUNTO ═══════════════════════════════
 * **SIEMBRA LOS DOS ESPACIOS DE ID POR SEPARADO**, como producción:
 *
 *   · del lado del WIDGET  → filas con `picker_id` del sidecar: `opus` · `claude_cli` ·
 *                            `api:anthropic` (las 8 filas `api:*` NO existen del otro lado)
 *   · del lado de la RECETA → el catálogo CURADO de `cuarto.models.js`: `opus` · `oss` ·
 *                            `qwen-local` · `claude_cli` · `byok` …
 *
 * El arnés de la obra B sembraba LOS MISMOS IDS EN LOS DOS LADOS y por eso sus VB1/VB3/VB4
 * pasaron con el bug vivo: fabricaba un mundo donde la traducción no hacía falta. Un fixture
 * que hace coincidir los dos espacios no vale — es la lección de esta obra, y está acá
 * escrita para que nadie la deshaga «simplificando» el fixture.
 *
 * El `PUT /v1/puppets/{id}/config` se INTERCEPTA: se mide QUÉ se iba a escribir, sin DB.
 * CERO RED. Puerto EFÍMERO. JAMÁS :8377 ni :25374.
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
        res.writeHead(404).end("no"); return;
      }
      res.writeHead(200, { "content-type": MIME[path.extname(destino)] || "application/octet-stream" });
      fs.createReadStream(destino).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve({ srv, port: srv.address().port }));
  });
}

/* ── ESPACIO A · EL WIDGET. `picker_id` reales, copiados de `centro_modelos.py:184`. ── */
const FILAS = [
  { slug: "cli.claude_cli", picker_id: "claude_cli", familia: "cli", label: "Mi Claude Code",
    model: "claude-code-cli", base_url: "http://127.0.0.1:8926/v1",
    brain_provider: "claude_cli", estado: "probado", conectado: true, default: true },
  { slug: "api.anthropic", picker_id: "api:anthropic", familia: "api", label: "Anthropic",
    model: "claude-opus-4-8", base_url: "https://api.anthropic.com/v1",
    byok_ref: "keys:anthropic", estado: "probado", conectado: true },
  { slug: "incluido.cognicion", picker_id: "opus", familia: "incluido", label: "Opus 4.8",
    model: "anthropic/claude-opus-4.8", base_url: "https://openrouter.ai/api/v1",
    alias: "brain", estado: "probado", conectado: true },
];
/* El sidecar dice que «en uso» está claude_cli. ES EL PISADOR: si algo vuelve a leer de acá
 * en vez de la receta, la vara cae. */
const SELECTOR = { version: 2, default: "cli.claude_cli", default_id: "claude_cli",
                   seleccion_id: "claude_cli", modelos: FILAS };

/* ── ESPACIO B · LA RECETA. El agente está equipado con Qwen local: un id CURADO que NO
 *    está en las filas del widget, y distinto de lo que dice el sidecar. ── */
const RECETA = {
  meta: { name: "Agente de la vara D" },
  model: { primary: "qwen3:8b", base_url: "http://127.0.0.1:11434/v1", alias: "oss-direct",
           fallback: null, temperature: 0, max_tokens: 700, max_turns: 8 },
  framing: { inline: "" },
};

const salida = { errores_de_pagina: [], vd1: null, vd2: null, vd3: null, vd4: null, vd5: null, click_real: null };
const { srv, port } = await servirDiseno();
const browser = await webkit.launch();
try {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
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
  await pg.waitForFunction(() => !!window.__salaCerebro && !!window.AlephModelSelector,
                           null, { timeout: 45000 });

  const leerFilas = () => {
    const p = document.getElementById("sbpModeloWidget");
    return [...(p ? p.querySelectorAll(".ams-option[data-model]") : [])].map((x) => ({
      id: x.dataset.model,
      nombre: (x.querySelector(".ams-name") || {}).textContent || "",
      accion: (x.querySelector(".ams-use") || {}).textContent || "",
      marcada: x.classList.contains("on"),
    }));
  };

  // ══ VD1 + VD4 · el panel monta el widget, y muestra lo que el agente tiene equipado ══
  salida.vd1 = await pg.evaluate(async ({ filas, sel, receta, leer }) => {
    const L = new Function("return (" + leer + ")")();
    await window.__salaCerebro.cargar();
    window.__salaCerebro.sembrarModelos(
      // el catálogo CURADO del lado de la receta — ids de otro espacio, a propósito
      [{ id: "qwen-local", label: "Qwen3 8B", model: "qwen3:8b",
         base_url: "http://127.0.0.1:11434/v1", conectado: true },
       { id: "claude_cli", label: "Mi Claude Code", model: "claude-code-cli",
         base_url: "http://127.0.0.1:8926/v1", brainProvider: "claude_cli", conectado: true },
       { id: "opus", label: "Opus 4.8", model: "anthropic/claude-opus-4.8",
         base_url: "https://openrouter.ai/api/v1", conectado: true }],
      sel);
    window.__salaCerebro.hidratar(receta, "pup-vara-d");
    window.__salaCerebro.abrir();
    await new Promise((r) => setTimeout(r, 300));
    const f = L();
    const Sel = window.AlephModelSelector;
    return {
      // VD1 · COMPORTAMIENTO, no nombre de clase: el host contiene EXACTAMENTE las filas que
      // el componente compartido produce con estos datos, cada una con su acción.
      filas: f,
      ids_del_widget: f.map((x) => x.id),
      ids_esperados: filas.map((x) => x.picker_id),
      tiene_api: f.some((x) => String(x.id).startsWith("api:")),
      es_el_componente: typeof Sel.render === "function" && typeof Sel.html === "function",
      // VD4 · el agente corre qwen3:8b, que NO está en las filas → NINGUNA marcada.
      marcadas: f.filter((x) => x.marcada).map((x) => x.id),
      sidecar_decia: sel.seleccion_id,
      corre: (window.__salaCerebro.aCorrer() || {}).model?.primary,
    };
  }, { filas: FILAS, sel: SELECTOR, receta: RECETA, leer: leerFilas.toString() });

  // ══ VD3 · «En uso» sale de lo que EJECUTA: equipar opus y ver que se marca opus ══
  salida.vd3 = await pg.evaluate(async ({ sel, leer }) => {
    const L = new Function("return (" + leer + ")")();
    window.__salaCerebro.hidratar({ model: { primary: "anthropic/claude-opus-4.8",
      base_url: "https://openrouter.ai/api/v1", alias: "brain" } }, "pup-vara-d");
    window.__salaCerebro.abrir(); await new Promise((r) => setTimeout(r, 300));
    const f = L();
    return { marcadas: f.filter((x) => x.marcada).map((x) => x.id),
             en_uso: f.filter((x) => /en uso/i.test(x.accion)).map((x) => x.id),
             sidecar_decia: sel.seleccion_id,
             corre: (window.__salaCerebro.aCorrer() || {}).model?.primary };
  }, { sel: SELECTOR, leer: leerFilas.toString() });

  // ══ VD2 + VD5 · click en una fila `api:*` → confirmar → PUT → la receta queda en BYOK ══
  /* ⚠️ EL CLICK ES REAL, CON PUNTERO, Y ESO NO ES UN DETALLE. La versión anterior de esta
   * vara llamaba al seam `elegir()` y pasaba con el bug VIVO: un `mousedown` global cerraba
   * el panel antes de que el `click` aterrizara (`sala.html:2991`), y ni el seam ni un
   * `.click()` programático disparan `mousedown`. Sólo un puntero de verdad lo destapa.
   * Si alguien "simplifica" esto a `elegir()`, el bug vuelve invisible. */
  const abrirYClickear = async (pickerId) => {
    await pg.evaluate(() => window.__salaCerebro.abrir());
    await pg.waitForTimeout(250);
    const fila = pg.locator(`#sbpModeloWidget .ams-option[data-model="${pickerId}"]`);
    const encontrada = await fila.count();
    if (encontrada) await fila.click();          // ← puntero real: mousedown + mouseup + click
    await pg.waitForTimeout(300);
    return encontrada;
  };
  salida.click_real = { filas_encontradas: await abrirYClickear(FILAS[1].picker_id),
                        panel_sobrevive: await pg.evaluate(() =>
                          !!document.getElementById("sbpModeloWidget")
                          && !(document.getElementById("sbPanel") || {}).hidden),
                        confirma: await pg.evaluate(() =>
                          [...document.querySelectorAll("#sbpModeloWidget .power-seg button")]
                            .map((b) => b.textContent)) };

  // ══ VD2 · TODO CON PUNTERO REAL: elegir, no confirmar, confirmar, y medir el PUT ══
  const sinConfirmar = await pg.evaluate(() => ({
    puts: (window.__puts || []).length,
    pide: document.querySelectorAll("#sbpModeloWidget .power-seg button").length === 2,
    botones: [...document.querySelectorAll("#sbpModeloWidget .power-seg button")].map((b) => b.textContent),
    receta: (window.__salaCerebro.receta() || {}).model.primary,
  }));
  const btnOk = pg.locator("#sbpModeloWidget .power-seg button", { hasText: /Cambiar el agente/i });
  if (await btnOk.count()) await btnOk.first().click();     // ← confirmar, también con puntero
  await pg.waitForTimeout(500);
  salida.vd2 = await pg.evaluate(async ({ sel, cat, leer }) => {
    const L = new Function("return (" + leer + ")")();
    const puts = window.__puts || [];
    const cfg = puts.length ? puts[puts.length - 1].config : null;
    const Mod = await import("/cuarto/cuarto.models.js");
    /* Al confirmar, `refreshBrainState()` recarga el catálogo del backend — que acá contesta
     * `{}` y deja `ST.models` vacío. En producción el sidecar devuelve las MISMAS filas, así
     * que se re-siembran: sin esto no se estaría midiendo la marca, sino el stub vacío. */
    window.__salaCerebro.sembrarModelos(cat, sel);
    window.__salaCerebro.abrir();
    await new Promise((r) => setTimeout(r, 300));
    return {
      puts: puts.length,
      persistido: cfg && cfg.model ? { primary: cfg.model.primary, base_url: cfg.model.base_url,
                                       byok_ref: cfg.model.byok_ref } : null,
      id_que_leeria_el_cuarto: cfg ? Mod.modelIdForRecipe(cfg) : null,
      corre_despues: (window.__salaCerebro.aCorrer() || {}).model?.primary,
      marcadas_despues: L().filter((x) => x.marcada).map((x) => x.id),
    };
  }, { sel: SELECTOR, leer: leerFilas.toString(),
       cat: [{ id: "qwen-local", label: "Qwen3 8B", model: "qwen3:8b", base_url: "http://127.0.0.1:11434/v1", conectado: true },
             { id: "claude_cli", label: "Mi Claude Code", model: "claude-code-cli", base_url: "http://127.0.0.1:8926/v1", brainProvider: "claude_cli", conectado: true },
             { id: "opus", label: "Opus 4.8", model: "anthropic/claude-opus-4.8", base_url: "https://openrouter.ai/api/v1", conectado: true }] });
  salida.vd2.sinConfirmar = sinConfirmar;

  // ══ VD-puente · las dos direcciones, contra el módulo REAL ══
  salida.vd5 = await pg.evaluate(async ({ filas }) => {
    const Mod = await import("/cuarto/cuarto.models.js");
    const cat = [{ id: "opus", model: "anthropic/claude-opus-4.8", base_url: "https://openrouter.ai/api/v1" },
                 { id: "claude_cli", brainProvider: "claude_cli" }];
    return {
      api: Mod.curadoDesdeFila(filas[1], cat),
      cli: Mod.curadoDesdeFila(filas[0], cat),
      incluido: Mod.curadoDesdeFila(filas[2], cat),
      desconocida: Mod.curadoDesdeFila({ picker_id: "quien:sabe", model: "x", base_url: "y" }, cat),
      vuelta_byok: Mod.filaDesdeReceta({ primary: "claude-opus-4-8", byok_ref: "keys:anthropic" }, filas),
      vuelta_cli: Mod.filaDesdeReceta({ primary: "claude-code-cli", brain_provider: "claude_cli" }, filas),
      vuelta_modelo: Mod.filaDesdeReceta({ primary: "anthropic/claude-opus-4.8",
                                           base_url: "https://openrouter.ai/api/v1" }, filas),
      vuelta_ninguna: Mod.filaDesdeReceta({ primary: "qwen3:8b",
                                            base_url: "http://127.0.0.1:11434/v1" }, filas),
    };
  }, { filas: FILAS });

  await pg.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
