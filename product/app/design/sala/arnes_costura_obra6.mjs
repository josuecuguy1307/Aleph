/* arnes_costura_obra6.mjs — EL BRAZO DEL FRENTE DE LA OBRA 6 (Gate 3 · memoria perdida).
 *
 * No es una vara: es el brazo de `platform/assembler/verify_costura_obra6.py`, que es quien
 * afirma. Acá se MIDE y se imprime JSON por stdout; las aserciones viven en la vara, una
 * sola, como manda el método.
 *
 *   node product/app/design/sala/arnes_costura_obra6.mjs
 *
 * ── QUÉ MIDE, Y POR QUÉ ASÍ ─────────────────────────────────────────────────────────
 * WebKit REAL (el motor de WKWebView, el mismo de la .app) contra LA SALA DE ESTE ÁRBOL.
 * Se entra por la FUNCIÓN REAL (`window.__salaCerebro.memoria`, el mismo molde que
 * `sustituir` de la obra B) y se lee **el DOM que sale**: cuántas entradas nuevas hay, qué
 * clase tienen y qué dice el copy. Medir el DOM y no el string que devuelve la función es
 * lo que separa «la función corrió» de «la persona lo vio».
 *
 * Y se mide el COLOR COMPUTADO, por la misma razón que la obra 5: el acta dice que esto no
 * es un fallo ni una protección del gate, y eso se prueba mirando el píxel. Si el aviso
 * colapsara con el rojo de un error o con el ámbar del gate, el discriminante se cae aunque
 * cada caso pase por separado.
 *
 * CERO RED: todo `/v1/**` se contesta con `{}` desde el interceptor. Puerto efímero pedido
 * al SO — JAMÁS :8377 ni :25374 (la .app de persona usuaria).
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const DISENO = path.resolve(AQUI, "..");

/* playwright vive en el árbol PRINCIPAL: un `git worktree` no duplica node_modules. */
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

/* El evento tal como sale del SSE (`router.py`, `type:"sesion_perdida"`). Copiado por VALOR
 * a propósito: si el backend cambia la forma, esta vara tiene que enterarse rompiéndose. */
const EVENTO = { type: "sesion_perdida", causa: "sesion_perdida",
                 detalle: "la sesión restaurada del mapa ya no existía", reintentable: true };

/* LEER EL DOM — ATRAVESANDO EL SHADOW ROOT, que es donde vive de verdad.
 *
 * Medido el 2026-08-08: el primer arnés buscaba `.vitals` en el documento plano y no
 * encontraba NADA, ni con el aviso pintado. `aleph-chat.js:570-584` lo mete en el shadow
 * root del componente (`.ac-vitals[data-live="1"]` dentro de `#messages`), así que un
 * `document.querySelector` no lo ve nunca. Un arnés que mira donde no está mide siempre
 * cero y sale verde por el lado equivocado — el verde mentiroso de H4, en versión front. */
const LEER = function () {
  const filas = [];
  const raices = [];
  document.querySelectorAll("*").forEach((n) => { if (n.shadowRoot) raices.push(n.shadowRoot); });
  raices.forEach((sr) => {
    sr.querySelectorAll(".ac-vitals").forEach((n) => {
      const cs = getComputedStyle(n);
      filas.push({ clase: n.className || "", vivo: n.getAttribute("data-live") === "1",
                   texto: (n.textContent || "").trim().slice(0, 240),
                   color: cs.color, fondo: cs.backgroundColor });
    });
  });
  return filas;
};

const salida = { errores_de_pagina: [], v1: null, v2: null, v3: null, v4: null, v5: null };
const { srv, port } = await servirDiseno();
const browser = await webkit.launch();

async function abrir(lang) {
  const pg = await browser.newPage();
  pg.on("pageerror", (e) => { salida.errores_de_pagina.push(String(e).slice(0, 200)); });
  await pg.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  if (lang) await pg.addInitScript((l) => { try { localStorage.setItem("aleph-lang", l); } catch (_) {} }, lang);
  await pg.goto(`http://127.0.0.1:${port}/sala/sala.html`, { waitUntil: "domcontentloaded" });
  await pg.waitForFunction(() => !!window.__salaCerebro, null, { timeout: 45000 });
  // `vitals` ENCOLA hasta que el shadow root existe (`aleph-chat.js:571`, la `q()`), así
  // que disparar antes de que monte mide un DOM que todavía no puede tener el aviso.
  await pg.waitForFunction(() => {
    let hay = false;
    document.querySelectorAll("*").forEach((n) => {
      if (n.shadowRoot && n.shadowRoot.querySelector("#messages")) hay = true;
    });
    return hay;
  }, null, { timeout: 45000 }).catch(() => {});
  return pg;
}

try {
  // ── V1 · LA CAUSA LLEGA A LA SUPERFICIE, EN DOM REAL ────────────────────────────────
  const pg = await abrir(null);
  salida.v1 = await pg.evaluate(async ({ ev, leer }) => {
    const L = new Function("return (" + leer + ")")();
    const antes = L().length;
    window.__salaCerebro.memoria(ev);
    await new Promise((r) => setTimeout(r, 400));
    const filas = L();
    return { antes, despues: filas.length, nuevas: filas.slice(antes), todas: filas };
  }, { ev: EVENTO, leer: LEER.toString() });

  // ── V2 · UNA SOLA VEZ POR SESIÓN AFECTADA ───────────────────────────────────────────
  // El guard NO está en el front a propósito (vive en `cli_brain/server.py:111`). Lo que
  // esta medición prueba es que el front no INVENTA repeticiones: un turno = un aviso.
  // Que el backend no vuelva a emitirlo lo mide la vara del lado Python.
  salida.v2 = await pg.evaluate(async ({ ev, leer }) => {
    const L = new Function("return (" + leer + ")")();
    const base = L().length;
    // el "segundo turno": la Sala NO recibe otro evento porque el backend no lo manda
    await new Promise((r) => setTimeout(r, 300));
    return { sin_evento_nuevo: L().length - base };
  }, { ev: EVENTO, leer: LEER.toString() });

  // ── V3 · EL CAMINO NORMAL: CERO AVISO ───────────────────────────────────────────────
  const pg3 = await abrir(null);
  salida.v3 = await pg3.evaluate(async ({ leer }) => {
    const L = new Function("return (" + leer + ")")();
    const antes = L().length;
    await new Promise((r) => setTimeout(r, 400));
    return { antes, despues: L().length };
  }, { leer: LEER.toString() });

  // ── V4 · NO COLAPSA CON LOS ESTADOS DE LA OBRA 5 ────────────────────────────────────
  //
  // ══ EL HALLAZGO, Y POR QUÉ EL DISCRIMINANTE NO ES EL COLOR ════════════════════════
  // Primera medición: el aviso sale `rgb(160,160,166)` — **exactamente el gris de
  // `nocorrio`** de la obra 5 (`REPORTE-GATE3-OBRA5.md` §: nocorrio = rgb(160,160,166)).
  // Por color pelado, colapsa.
  //
  // Y NO se toca, por dos razones medidas:
  //   · el acta de esta obra dice «cero paleta nueva», y el gris es EL color de `vitals`
  //     — el mismo que ya usa `modelo_sustituido` (obra B) y `turno_detenido`. Pintarlo
  //     distinto sería inventar una paleta para un solo aviso;
  //   · no son el mismo elemento ni el mismo lugar. `.ac-vitals` es la línea de estado
  //     DEL TURNO; `.ac-act.nocorrio` es una fila de ACCIÓN dentro de la costura. Nunca
  //     aparecen como dos filas hermanas que haya que distinguir entre sí.
  //
  // El discriminante REAL es si el aviso entra por la maquinaria de estados de la
  // costura. Si llevara una clase `.ac-act.*`, ahí sí sería indistinguible de un fallo.
  // Eso es lo que se mide: la clase del nodo, y que el derivador de la costura no le dé
  // ninguno de los tres estados.
  salida.v4 = await pg3.evaluate(async ({ ev }) => {
    const S = window.__salaCostura;
    // El semáforo es un MÓDULO ES, no un global: `window.__salaSemaforo` no existe y el
    // primer arnés midió `null` sin que nada estuviera mal. Se importa por su URL real,
    // que es el mismo diccionario único que consume la Sala.
    let Sem = null;
    try { Sem = await import("../cuarto/cuarto.semaforo.js"); } catch (_) { Sem = null; }
    const cara = Sem && Sem.caraDeCausa
      ? Sem.caraDeCausa({ causa: "sesion_perdida", detalle: "", reintentable: true }) : null;
    window.__salaCerebro.memoria(ev);
    await new Promise((r) => setTimeout(r, 400));
    // el nodo REAL del aviso, con TODAS sus clases
    let nodo = null;
    document.querySelectorAll("*").forEach((n) => {
      if (n.shadowRoot) {
        const v = n.shadowRoot.querySelector(".ac-vitals");
        if (v) nodo = { clase: v.className, color: getComputedStyle(v).color };
      }
    });
    return {
      hay_costura: !!S,
      fail:     S ? S.estado({ status: "error", executed: true }) : null,
      nocorrio: S ? S.estado({ status: "error", executed: false }) : null,
      held:     S ? S.estado({ type: "gate_waiting" }) : null,
      cara_sesion_perdida: cara,
      alarma: cara ? cara.alarma : null,
      // el copy del diccionario, en los DOS idiomas — para que V5 pueda afirmar que el
      // texto que se ve sale de acá y no de una cadena escrita a mano en la Sala
      dic: Sem && Sem.CAUSAS ? Sem.CAUSAS["sesion_perdida"] : null,
      // EL DISCRIMINANTE: el nodo del aviso y si lleva clases de la costura
      nodo_aviso: nodo,
      lleva_clase_de_estado: nodo ? /\bac-act\b|\bdone\b|\bfail\b|\bnocorrio\b|\bheld\b/.test(nodo.clase) : null,
    };
  }, { ev: EVENTO });

  // ── V5 · i18n EN LOS DOS IDIOMAS ────────────────────────────────────────────────────
  const idiomas = {};
  for (const lang of ["es", "en"]) {
    const p = await abrir(lang);
    idiomas[lang] = await p.evaluate(async ({ ev, leer, l }) => {
      const L = new Function("return (" + leer + ")")();
      try { if (window.setLang) window.setLang(l); } catch (_) {}
      await new Promise((r) => setTimeout(r, 200));
      const antes = L().length;
      window.__salaCerebro.memoria(ev);
      await new Promise((r) => setTimeout(r, 400));
      return {
        nuevas: L().slice(antes).map((f) => f.texto),
        clave_titulo: window.t ? window.t("sala.sesion.perdida") : null,
        clave_cuerpo: window.t ? window.t("sala.sesion.sinmemoria") : null,
      };
    }, { ev: EVENTO, leer: LEER.toString(), l: lang });
    await p.close();
  }
  salida.v5 = idiomas;

  await pg.close();
  await pg3.close();
} finally {
  await browser.close();
  srv.close();
}
process.stdout.write(JSON.stringify(salida, null, 2));
