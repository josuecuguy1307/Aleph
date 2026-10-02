/* arnes_costura_obra5.mjs — EL ARNÉS DEL FRENTE DE LA OBRA 5 (Gate 3).
 *
 * No es una vara: es el brazo del frente de `platform/assembler/verify_costura_obra5.py`,
 * que es quien afirma. Acá se MIDE y se imprime JSON por stdout; las aserciones viven en la
 * vara, una sola, como manda el método.
 *
 *   node product/app/design/sala/arnes_costura_obra5.mjs
 *
 * ── QUÉ MIDE, Y POR QUÉ ASÍ ─────────────────────────────────────────────────────────
 * WebKit REAL (el motor de WKWebView, el mismo de la .app) contra LA SALA DE ESTE ÁRBOL,
 * servida por un estático propio en puerto EFÍMERO. Se entra por los DOS caminos reales que
 * pintan la línea del turno —el VIVO (`narrateEvent`, el espinazo) y el del RECORD
 * (`lineaDelRecord`, el del STREAM CORTADO, que es el de G-1)— y se lee EL DOM que sale:
 * la clase, el copy y el COLOR COMPUTADO de cada entrada.
 *
 * El color computado es la evidencia que ninguna aserción sobre el código puede dar: el acta
 * dice «ni el verde del éxito ni el rojo del error», y eso se prueba mirando el píxel, no
 * leyendo el CSS. Por eso el arnés devuelve los cuatro colores y la vara exige que sean
 * cuatro DISTINTOS: si dos estados colapsan, el discriminante se cae aunque cada caso pase.
 *
 * CERO RED: todo `/v1/**` se contesta con `{}` desde el interceptor, y el vendor (deep-chat,
 * fuentes, katex) ya vive en el árbol. Puerto efímero pedido al SO — JAMÁS :8377 (la tanda
 * de varas del carril F7) ni :25374 (la .app de persona usuaria).
 */
import http from "node:http";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const DISENO = path.resolve(AQUI, "..");           // product/app/design — la raíz que se sirve

/* playwright vive en el árbol PRINCIPAL del repo: un `git worktree` no duplica node_modules,
 * y una ruta literal de una máquina no sirve en otra (regla del repo). Se resuelve desde git. */
function raizPrincipal() {
  const comun = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"],
                             { cwd: AQUI }).toString().trim();
  return path.dirname(comun);                       // …/<repo>/.git → …/<repo>
}
const _pw = await import(pathToFileURL(
  path.join(raizPrincipal(), "node_modules", "playwright", "index.js")).href);
// playwright es CJS: según cómo lo envuelva node, los named exports quedan arriba o en .default
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

/* Los cuatro casos, con la firma EXACTA que emite la costura (recipe_assembler.py):
 *   V1 :3304 EXECUTE ok        → status ok    · executed true
 *   V2 :3304 EXECUTE con error → status error · executed true  · causa del clasificador
 *   V3 :3104 args inválidos    → status error · executed FALSE · gate_action None
 *   V4 :3304 NO-execute        → type gate_waiting · status gated · executed false */
const T = (n) => ({ call_id: "c" + n, tool: "calc", tool_raw: "sumar_" + n, args: { a: 1 } });
const CASOS = {
  v1_ok:       { ...T(1), type: "tool_call_finished", result: "3", status: "ok",
                 executed: true, gate_action: "execute", gate_decision: "execute" },
  v2_fallo:    { ...T(2), type: "tool_call_finished", result: "[tool error] 502 Bad Gateway",
                 status: "error", executed: true, gate_action: "execute", gate_decision: "execute",
                 causa: "proveedor_caido", origen: "conector", reintentable: true,
                 detalle: "El proveedor devolvió 502." },
  v3_nocorrio: { ...T(3), type: "tool_call_finished", result: "[error: arguments inválidos]",
                 status: "error", executed: false, gate_action: null, gate_decision: null,
                 causa: "argumentos_invalidos", origen: "modelo", reintentable: true,
                 detalle: "El modelo mandó los argumentos mal." },
  v4_held:     { ...T(4), type: "gate_waiting", result: "", status: "gated", executed: false,
                 gate_action: "needs_ok", gate_decision: "needs_ok",
                 causa: "gate_bloqueado", origen: "aleph", reintentable: false,
                 detalle: "Requiere tu OK antes de ejecutar.",
                 gate_ux: { que_va_a_hacer: "mandar un mail" } },
};
/* El MISMO caso por el camino del RECORD (G-1). El record NO lleva `status` —eso es del
 * evento vivo— así que acá el estado sale de `executed` + gate + causa y de nada más. */
const REC = Object.fromEntries(Object.entries(CASOS).map(([k, e]) => [k, {
  tool: e.tool_raw, tool_display: e.tool_raw, server: e.tool, args: e.args, result: e.result,
  gate_action: e.gate_action, gate_decision: e.gate_decision, executed: e.executed,
  ...(e.causa ? { causa: e.causa, origen: e.origen, reintentable: e.reintentable, detalle: e.detalle } : {}),
}]));

const LEER = () => {
  const host = document.querySelector("deep-chat");
  const sr = host && host.shadowRoot;
  if (!sr) return [];
  return Array.from(sr.querySelectorAll(".ac-act")).map((el) => {
    const st = el.querySelector(".ac-act-st");
    return {
      clases: Array.from(el.classList),
      titulo: (el.querySelector(".ac-act-tt") || {}).textContent || "",
      estado: st ? st.textContent : "",
      sub: (el.querySelector(".ac-act-sub") || {}).textContent || "",
      pregunta: (el.querySelector(".ac-act-ask") || {}).textContent || "",
      color: st ? getComputedStyle(st).color : "",
      camino: !!el.querySelector(".ac-li-cam"),
    };
  });
};

async function abrir(browser, port) {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
  await pg.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await pg.goto(`http://127.0.0.1:${port}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(
    () => !!window.__salaCostura && !!(document.querySelector("deep-chat") || {}).shadowRoot,
    null, { timeout: 45000 });
  return pg;
}

const salida = { errores_de_pagina: [], vivo: null, record: null, retry: null, estados: null };

const { srv, port } = await servirDiseno();
const browser = await webkit.launch();
try {
  // ── §1 · EL CAMINO VIVO (el espinazo) ─────────────────────────────────────────────
  const pg1 = await abrir(browser, port);
  salida.vivo = await pg1.evaluate(async ({ casos, leer }) => {
    const L = new Function("return (" + leer + ")")();
    const out = {};
    for (const [k, ev] of Object.entries(casos)) {
      window.__salaCostura.evento({ type: "tool_call_started", call_id: ev.call_id,
                                    tool: ev.tool, tool_raw: ev.tool_raw, args: ev.args });
      window.__salaCostura.evento(ev);
    }
    await new Promise((r) => setTimeout(r, 400));   // el chat encola sus escrituras del DOM
    const filas = L();
    Object.keys(casos).forEach((k, i) => { out[k] = filas[i] || null; });
    return out;
  }, { casos: CASOS, leer: LEER.toString() });
  await pg1.close();

  // ── §2 · EL CAMINO DEL RECORD (stream cortado) — el de G-1 ────────────────────────
  const pg2 = await abrir(browser, port);
  salida.record = await pg2.evaluate(async ({ rec, leer }) => {
    const L = new Function("return (" + leer + ")")();
    const n = window.__salaCostura.record({ record: { tool_calls: Object.values(rec) } });
    await new Promise((r) => setTimeout(r, 400));
    const filas = L();
    const out = { entradas: n };
    Object.keys(rec).forEach((k, i) => { out[k] = filas[i] || null; });
    return out;
  }, { rec: REC, leer: LEER.toString() });

  // ── §3 · EL DERIVADOR, incluidos los casos que NADIE emite ────────────────────────
  salida.estados = await pg2.evaluate(() => ({
    ok:            window.__salaCostura.estado({ status: "ok", executed: true }),
    error:         window.__salaCostura.estado({ status: "error", executed: true }),
    nocorrio:      window.__salaCostura.estado({ status: "error", executed: false }),
    gated:         window.__salaCostura.estado({ status: "gated", executed: false }),
    gate_waiting:  window.__salaCostura.estado({ type: "gate_waiting" }),
    record_gate:   window.__salaCostura.estado({ gate_action: "blocked" }),
    record_causa:  window.__salaCostura.estado({ causa: "proveedor_caido" }),
    record_pelado: window.__salaCostura.estado({ result: "algo" }),
    desconocido:   window.__salaCostura.estado({ status: "quien_sabe" }),
    nulo:          window.__salaCostura.estado(null),
  }));

  // ── §4 · EL AUTO-RETRY ────────────────────────────────────────────────────────────
  salida.retry = await pg2.evaluate(() => ({
    mapa: window.__salaCostura.mapa(),
    // el BOOLEANO sellado manda, aunque el nombre no esté en el mapa
    tipada_si:   window.__salaCostura.retry({ causa: "contexto_excedido" },
                                            { causa: { causa: "sesion_perdida", reintentable: true } }),
    tipada_no:   window.__salaCostura.retry({ causa: "timeout" },
                                            { causa: { causa: "key_invalida", reintentable: false } }),
    // sin causa tipada, el espejo del sello
    espejo_si:   window.__salaCostura.retry({ causa: "proveedor_caido" }, null),
    espejo_no:   window.__salaCostura.retry({ causa: "key_invalida" }, null),
    muerta_vieja: window.__salaCostura.retry({ causa: "servidor_caido" }, null),
    muerta_vieja2: window.__salaCostura.retry({ causa: "stream_cortado" }, null),
  }));
  await pg2.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
