/* verify_cliente_offline.mjs — el cliente renderiza SIN INTERNET.
 *
 * Casa 2 · F1. El arranque del runtime dependía de bajar React de unpkg
 * (`loadReactUmd().then(init)`): sin red, `init()` nunca corría y la pantalla quedaba EN
 * BLANCO — ni el template crudo se veía, porque hideRawTemplate() ya lo había ocultado.
 * Medido antes del fix: Auth.dc.html renderizaba UN carácter.
 *
 * Esto NO se verifica leyendo el código. Se sirve design/ por HTTP (que es el transporte
 * real: Tauri + sidecar sirven por loopback, no file://) y se ABORTA todo host externo.
 * Si una pantalla renderiza, es porque no necesitó la red.
 *
 *   node qa/verify_cliente_offline.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const DESIGN = path.join(ROOT, "product/app/design") + "/";
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
               ".css": "text/css", ".json": "application/json", ".png": "image/png",
               ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff" };

// Las 11 que montan el runtime dc (las que dependían de React). Conectar/resolver/dispatch
// quedan fuera a propósito: son HTML plano, nunca dependieron de esto.
const PANTALLAS = ["Home.dc.html", "Auth.dc.html", "Landing.dc.html", "Settings.dc.html",
                   "Onboarding.dc.html", "Ayuda.dc.html", "Biblioteca.dc.html",
                   "Historial.dc.html", "Estados.dc.html", "Cuarto.dc.html",
                   "OutputCard.dc.html"];
// LA ASERCIÓN: cada pantalla tiene que rendir OFFLINE LO MISMO que online. No un umbral
// de caracteres — probé con uno fijo y dio un falso rojo en OutputCard.dc.html, que es un
// fragmento de componente (una card con 5 controles, 33 chars) y renderiza idéntico en
// ambos casos. "Igual que con red" es la propiedad que de verdad importa y no hay que
// calibrarla por pantalla.
const TOLERANCIA = 0.98;   // ≥98% del texto visible que rinde con red

// El servidor lleva la cuenta de lo que REALMENTE sirvió. Es la única señal sin
// ambigüedad sobre las fuentes: medirlas desde la página no distingue "no declara
// ninguna" de "las declara y todas dieron 404" — probado, y por eso este contador existe.
let servidos = [];
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(new URL(q.url, "http://x").pathname);
  const p = path.join(DESIGN, rel);
  if (!p.startsWith(DESIGN) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) {
    servidos.push({ rel, status: 404 });
    r.writeHead(404); r.end(); return;
  }
  servidos.push({ rel, status: 200 });
  r.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(r);
});
await new Promise((res) => srv.listen(0, "127.0.0.1", res));
const base = "http://127.0.0.1:" + srv.address().port;

const browser = await chromium.launch();
let ok = 0, fail = 0;
const externos = new Set();

async function medir(f, { offline }) {
  servidos = [];
  const ctx = await browser.newContext();
  // sesión: sin esto el auth-gate redirige a Auth y se mide la pantalla equivocada
  await ctx.addInitScript(() => {
    try { sessionStorage.setItem("puppet_user", JSON.stringify(
      { id: "6b558dd2-f315-4f56-b476-b16b4804f7fe", session_token: "probe" })); } catch {}
  });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e).split("\n")[0].slice(0, 70)));
  if (offline) {
    await page.route("**/*", (route) => {
      const u = route.request().url();
      if (u.startsWith(base)) return route.continue();
      externos.add(new URL(u).host);
      return route.abort();                     // SIN RED. Nada de afuera entra.
    });
  }
  let r = { chars: 0, nodos: 0 };
  try {
    await page.goto(`${base}/${f}`, { waitUntil: "load", timeout: 25000 });
    await page.waitForTimeout(3500);
    // [F1.b] Las fuentes se comprueban DESCARGADAS, no "el link apunta a local": un
    // @font-face roto falla en silencio (el browser cae a una de sistema y nadie se entera).
    //
    // NO se usa document.fonts.check(): da false cuando la fuente está declarada pero
    // todavía no bajada (cargan perezosamente, sólo si el texto las usa), y da TRUE cuando
    // no hay ningún @font-face — porque el texto igual se puede rendir con una de sistema.
    // O sea contesta lo contrario de lo que hace falta saber.
    //
    // fonts.load() FUERZA la descarga y devuelve las FontFace que matchean; el `status` de
    // cada una es el veredicto. Sin reglas declaradas → 0 matches → "n/a", que no es un
    // fallo (OutputCard es un fragmento y no trae bloque de fuentes).
    r = await page.evaluate(async () => {
      const fam = ['16px Spectral', '16px "Hanken Grotesk"'];
      let caras = [];
      for (const f of fam) { try { caras = caras.concat(await document.fonts.load(f)); } catch {} }
      return {
        chars: (document.body.innerText || "").trim().length,
        nodos: document.body.querySelectorAll("*").length,
        fuentes: caras.length === 0 ? "n/a"
               : (caras.every((c) => c.status === "loaded") ? "ok" : "FALLAN"),
      };
    });
  } catch (e) {
    r.error = String(e).split("\n")[0].slice(0, 60);
  }
  await ctx.close();
  const css = servidos.filter((s) => s.rel.endsWith("fonts.css"));
  const w2ok = servidos.filter((s) => s.rel.endsWith(".woff2") && s.status === 200);
  // 404 que importan = ASSETS del artefacto (js/css/fuentes/imágenes). Las rutas /v1,
  // /catalog y /health son llamadas al BACKEND, que en esta sonda no existe: dan 404 por
  // diseño y no significan que falte nada del paquete. Contarlas ponía en rojo 4 pantallas
  // por un backend ausente, que es justo lo que esta prueba NO está midiendo.
  const esApi = (r) => /^\/(v1|catalog|health)(\/|$)/.test(r);
  const w404 = servidos.filter((s) => s.status === 404 && !esApi(s.rel));
  // n/a SÓLO si la página no pidió el css de fuentes. Si lo pidió, exige woff2 servidos.
  const fuentes = css.length === 0 ? "n/a" : (w2ok.length > 0 ? `ok(${w2ok.length})` : "FALLAN");
  return { ...r, fuentes, faltantes: w404.map((s) => s.rel), errs: [...new Set(errs)] };
}

for (const f of PANTALLAS) {
  const con = await medir(f, { offline: false });
  const sin = await medir(f, { offline: true });
  const ratio = con.chars > 0 ? sin.chars / con.chars : (sin.chars === 0 ? 1 : 0);
  const paso = !sin.error && ratio >= TOLERANCIA && sin.fuentes !== "FALLAN"
                && sin.faltantes.length === 0;
  paso ? ok++ : fail++;
  console.log(`  ${paso ? "\u2713" : "\u2717"} ${f.padEnd(22)} con red:${String(con.chars).padStart(6)}  sin red:${String(sin.chars).padStart(6)}  (${Math.round(ratio * 100)}%)  fuentes:${sin.fuentes}` +
              (sin.faltantes.length ? `  \u00b7 404 local: ${sin.faltantes.slice(0,2).join(", ")}` : "") +
              (sin.errs.length ? `  \u00b7 ${sin.errs.slice(0, 1).join("")}` : "") +
              (sin.error ? `  \u00b7 ${sin.error}` : ""));
}

await browser.close();
srv.close();

console.log(`\n  hosts externos que se intentaron alcanzar: ${[...externos].join(", ") || "NINGUNO"}`);
console.log(`\n${ok}/${ok + fail} pantallas renderizan sin internet`);
process.exit(fail ? 1 : 0);
