/* arnes_costura_obraA.mjs — EL BRAZO DEL FRENTE DE LA OBRA A (Gate 3).
 *
 * No es una vara: es el brazo de `platform/assembler/verify_costura_obraA.py`, que es quien
 * afirma. Acá se MIDE y se imprime JSON por stdout. Mismo método que la obra 5.
 *
 *   node product/app/design/sala/arnes_costura_obraA.mjs
 *
 * ── QUÉ MIDE, Y POR QUÉ ASÍ ─────────────────────────────────────────────────────────
 * La obra A toca el lado python (`repair_clasificar`) y el DICCIONARIO ÚNICO
 * (`cuarto.semaforo.js`). Lo del lado python lo afirma la vara leyendo el módulo. Lo del
 * diccionario NO se puede afirmar leyendo el archivo, por dos motivos:
 *
 *   · el copy tiene que salir RESUELTO por `caraDeCausa` —la función real que usan las tres
 *     superficies—, no leído del literal. Una entrada puede existir y aun así salir muda si
 *     el derivador no la alcanza, que es exactamente el fallo que F4b vino a matar.
 *   · `SIN_ALARMA` se DERIVA de `alarma:false` en tiempo de módulo. Que `gate_bloqueado`
 *     haya entrado al conjunto sólo se prueba ejecutándolo.
 *
 * Y el COLOR es la evidencia que ninguna aserción sobre el código puede dar (la lección de
 * la obra 5): el acta dice «ni el verde del éxito ni el rojo del error», y eso se prueba
 * mirando el píxel. Por eso las dos causas se meten por el camino VIVO de la Sala y se lee
 * el color computado del DOM que sale.
 *
 * CERO RED: todo `/v1/**` se contesta con `{}`. Puerto EFÍMERO del SO — JAMÁS :8377 (varas
 * de otro carril) ni :25374 (la .app instalada de persona usuaria).
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const DISENO = path.resolve(AQUI, "..");

/* playwright vive en el árbol PRINCIPAL: un `git worktree` no duplica node_modules. Se
 * resuelve desde git, jamás con una ruta literal de una máquina. */
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

/* Los DOS casos, con la firma EXACTA que emite la costura — copiada de los casos v3 y v4 del
 * arnés de la obra 5, que a su vez salen de `recipe_assembler.py:3104/:3304`. Se reusan tal
 * cual A PROPÓSITO: si la obra A pintara distinto que la obra 5 ante el MISMO evento, eso es
 * justamente la incoherencia que VA3 tiene que atrapar. */
const T = (n) => ({ call_id: "a" + n, tool: "calc", tool_raw: "sumar_" + n, args: { a: 1 } });
const CASOS = {
  argumentos_invalidos: {
    ...T(1), type: "tool_call_finished", result: "[error: arguments inválidos]",
    status: "error", executed: false, gate_action: null, gate_decision: null,
    causa: "argumentos_invalidos", origen: "modelo", reintentable: true,
    detalle: "El modelo mandó los argumentos mal." },
  gate_bloqueado: {
    ...T(2), type: "gate_waiting", result: "", status: "gated", executed: false,
    gate_action: "needs_ok", gate_decision: "needs_ok",
    causa: "gate_bloqueado", origen: "aleph", reintentable: false,
    detalle: "Requiere tu OK antes de ejecutar." },
};

const LEER = () => {
  const host = document.querySelector("deep-chat");
  const sr = host && host.shadowRoot;
  if (!sr) return [];
  return Array.from(sr.querySelectorAll(".ac-act")).map((el) => {
    const st = el.querySelector(".ac-act-st");
    return {
      clases: Array.from(el.classList),
      estado: st ? st.textContent : "",
      sub: (el.querySelector(".ac-act-sub") || {}).textContent || "",
      pregunta: (el.querySelector(".ac-act-ask") || {}).textContent || "",
      color: st ? getComputedStyle(st).color : "",
    };
  });
};

const salida = { errores_de_pagina: [], diccionario: null, pintura: null };
const { srv, port } = await servirDiseno();
const browser = await webkit.launch();
try {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
  await pg.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await pg.goto(`http://127.0.0.1:${port}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(
    () => !!window.__salaCostura && !!(document.querySelector("deep-chat") || {}).shadowRoot,
    null, { timeout: 45000 });

  // ── §1 · EL DICCIONARIO ÚNICO, EJECUTADO ──────────────────────────────────────────
  // Se importa el módulo REAL y se pregunta por la función REAL. Si una causa saliera muda,
  // `caraDeCausa` la devuelve con `desconocida:true` y sin título del diccionario.
  salida.diccionario = await pg.evaluate(async ({ casos }) => {
    const Sem = await import("/cuarto/cuarto.semaforo.js");
    const out = { sin_alarma: Array.from(Sem.SIN_ALARMA).sort(), causas: {} };
    for (const [nombre, ev] of Object.entries(casos)) {
      const f = Sem.caraDeCausa({ causa: ev.causa, detalle: ev.detalle,
                                  reintentable: ev.reintentable });
      out.causas[nombre] = {
        titulo: (f && f.titulo) || "",
        desconocida: !!(f && f.desconocida),
        alarma: f ? f.alarma : null,
        es_alarma: Sem.esAlarma(ev.causa),
        // el literal del diccionario, para poder exigir que el copy sea EL SELLADO
        entrada_es: (Sem.CAUSAS[ev.causa] || {}).es || "",
        entrada_en: (Sem.CAUSAS[ev.causa] || {}).en || "",
        accion: (Sem.CAUSAS[ev.causa] || {}).accion || null,
      };
    }
    return out;
  }, { casos: CASOS });

  // ── §2 · LA PINTURA, POR EL CAMINO VIVO DE LA SALA ────────────────────────────────
  salida.pintura = await pg.evaluate(async ({ casos, leer }) => {
    const L = new Function("return (" + leer + ")")();
    for (const ev of Object.values(casos)) {
      window.__salaCostura.evento({ type: "tool_call_started", call_id: ev.call_id,
                                    tool: ev.tool, tool_raw: ev.tool_raw, args: ev.args });
      window.__salaCostura.evento(ev);
    }
    await new Promise((r) => setTimeout(r, 400));
    const filas = L();
    const out = {};
    Object.keys(casos).forEach((k, i) => { out[k] = filas[i] || null; });
    return out;
  }, { casos: CASOS, leer: LEER.toString() });

  await pg.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
