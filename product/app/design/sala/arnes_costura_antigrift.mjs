/* arnes_costura_antigrift.mjs — EL BRAZO DEL FRENTE DE LA FASE 3 (Gate 3 · anti-grift).
 *
 * No es una vara: es el brazo de `platform/assembler/verify_costura_antigrift.py`, que es
 * quien afirma. Acá se MIDE y se imprime JSON por stdout.
 *
 *   node product/app/design/sala/arnes_costura_antigrift.mjs
 *
 * ── QUÉ MIDE ────────────────────────────────────────────────────────────────────────
 * WebKit real contra la Sala de este árbol. Entra por las funciones REALES
 * (`__salaCerebro.grounding` / `.grift`) con `tool_calls` **como los emite el motor**
 * —copiados por valor de `recipe_assembler.py`— y lee el veredicto.
 *
 * El criterio de los fixtures: cada caso trae los campos que el motor pone de verdad
 * (`executed`, `gate_action`, `gate_decision`, `causa`, `result`), ni más ni menos. Un
 * fixture que simplifica el mundo simplifica el bug afuera — la ley de la casa.
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

/* ══ LOS CASOS, COPIADOS POR VALOR DEL EMISOR ═══════════════════════════════════════
 * Cada uno lleva EXACTAMENTE los campos que `recipe_assembler.py` escribe en
 * `record["tool_calls"]`. Si el motor cambia el contrato, esta vara tiene que romperse,
 * no adaptarse sola. */
const CASOS = {
  // (a) EL CAMINO BUENO: corrió, el gate la dejó, sin causa, resultado legible.
  ok: { tool: "buscar", server: "web", args: {}, result: "3 resultados: …",
        gate_action: "execute", gate_decision: "execute", executed: true },

  // (b) [O2] EL GATE LA DEJÓ CORRER Y LA TOOL FALLÓ. `executed:true`, causa TIPADA.
  //     El criterio viejo (`gate_action==='execute'` + regex) la contaba como evidencia
  //     si su result no empezaba con `[error`.
  fallo_con_causa: { tool: "cobrar", server: "stripe", args: {},
                     result: "upstream 502 — el proveedor no respondió",
                     gate_action: "execute", gate_decision: "execute", executed: true,
                     causa: "error_upstream", origen: "conector", reintentable: true },

  // (c) [O2] NUNCA CORRIÓ — argumentos inválidos. `executed:false`, gate_action null.
  no_corrio: { tool: "enviar", server: "gmail", args: {}, result: "falta el campo `to`",
               gate_action: null, gate_decision: null, executed: false,
               causa: "argumentos_invalidos", origen: "aleph", reintentable: false },

  // (d) [O3 · G-8] EL SCRUBBER FALLÓ Y EL RESULTADO QUEDÓ RETENIDO. Corrió, el gate la
  //     dejó, NO tiene causa (el turno no falló) — y NADIE PUDO LEER el contenido.
  //     Empieza con `[c`, así que el regex `[(error|gate)` no la tocaba.
  scrub_retenido: { tool: "leer_doc", server: "drive", args: {},
                    result: "[contenido retenido por scrub]",
                    gate_action: "execute", gate_decision: "execute", executed: true },

  // (e) el gate la retuvo: propuesta, nunca corrida.
  gateada: { tool: "pagar", server: "stripe", args: {}, result: "[gate:needs_ok]",
             gate_action: "needs_ok", gate_decision: "needs_ok", executed: false },

  // (f) REGISTRO VIEJO, sin `executed`: el respaldo por `gate_action` tiene que seguir
  //     funcionando, o el anti-grift no puede juzgar la historia ya persistida.
  viejo_ok: { tool: "buscar", server: "web", args: {}, result: "ok", gate_action: "execute" },
  viejo_gateada: { tool: "pagar", server: "stripe", args: {}, result: "[gate:needs_ok]",
                   gate_action: "needs_ok" },
};

/* El estado del narrador tal como lo arma `narrateFinal`, para medir `griftVerdict`. */
const N_BASE = { model: "claude-opus-4.8", brainProvider: null, degraded: null,
                 failed: false, ok: true, windowExhausted: false,
                 results: 0, mem: false, shared: false, ragN: 0 };

const salida = { errores_de_pagina: [], grounding: {}, grift: {} };
const { srv, port } = await servirDiseno();
const browser = await webkit.launch();

try {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
  await pg.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await pg.goto(`http://127.0.0.1:${port}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => !!(window.__salaCerebro && window.__salaCerebro.grounding),
                           null, { timeout: 45000 });

  // ── el veredicto de grounding, caso por caso, por la FUNCIÓN REAL ─────────────────
  salida.grounding = await pg.evaluate((casos) => {
    const out = {};
    Object.keys(casos).forEach((k) => { out[k] = window.__salaCerebro.grounding(casos[k]); });
    out.__nulo = window.__salaCerebro.grounding(null);
    return out;
  }, CASOS);

  // ── y el badge entero: un turno cuya ÚNICA "evidencia" es un scrub retenido ───────
  salida.grift = await pg.evaluate((base) => {
    const g = window.__salaCerebro.grift;
    return {
      // 1 tool real → verde
      con_evidencia_real: g(Object.assign({}, base, { results: 1 })),
      // cero evidencia → caveat honesto
      sin_evidencia: g(Object.assign({}, base, { results: 0 })),
      // degradado → jamás verde
      degradado: g(Object.assign({}, base, { results: 1, degraded: { tier: "fallback" } })),
      // la corrida falló → jamás verde
      fallida: g(Object.assign({}, base, { results: 1, ok: false })),
    };
  }, N_BASE);

  await pg.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
