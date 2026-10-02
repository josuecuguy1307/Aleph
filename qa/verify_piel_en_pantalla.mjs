#!/usr/bin/env node
/**
 * verify_piel_en_pantalla.mjs — LA PIEL, EN LA CARA REAL DE CADA STACK, Y SUS DOS BRAZOS.
 * [rediseño · fase 3 · opción A]
 *
 * QUÉ MIDE, Y POR QUÉ NO ALCANZA CON MIRAR EL CSS
 * ───────────────────────────────────────────────
 * Que `aleph-piel.css` exista y diga `--dls-surface: var(--al-lienzo)` no prueba NADA: el
 * token puede no existir en ese stack, la hoja puede perder la cascada, el `@font-face`
 * puede apuntar a un woff2 que no está. Lo único que lo prueba es preguntarle al NAVEGADOR
 * qué color computó, sobre la cara HORNEADA del stack.
 *
 * Y se miden LOS DOS BRAZOS, que es lo que hace que el flag sea un interruptor y no un
 * botón:
 *     con `aleph_piel=v2`  → `data-aleph-piel` puesto, `--al-lienzo` resuelto, la letra es Poppins
 *     sin el flag          → nada de eso, y la cara queda EXACTAMENTE como hoy
 *
 * CÓMO, SIN BUILD Y SIN DEPENDENCIAS
 * ──────────────────────────────────
 *   · Se sirve el `dist/` ya horneado de cada stack, con su `public/` como respaldo — que es
 *     exactamente lo que hace su servidor de verdad. Cinco de los seis lo tienen en el árbol.
 *   · ⚠️ LA PÁGINA SE CARGA ADENTRO DE UN `<iframe>`, y no es un detalle: `aleph-piel.js`
 *     abre con la LEY 0 (`if (window.parent === window) return`). Servido al tope, el script
 *     se va por la primera línea y la vara mediría «sin piel» siempre — un verde que no mide
 *     nada. Hay que ponerlo donde de verdad corre.
 *   · La sonda corre en el HIJO (el server la inyecta), manda el resultado por `postMessage`
 *     y el PADRE lo escribe en su `<title>`. Chrome lo devuelve con `--dump-dom`. Cero npm.
 *
 * PROBADA CAYENDO
 *     node qa/verify_piel_en_pantalla.mjs --mutante
 * sirve la hoja vacía y exige que el brazo «con flag» caiga.
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "piel-pantalla-"));
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const MUT = process.argv.includes("--mutante");
const SOLO = (process.argv.find((a) => a.startsWith("--stack=")) || "").split("=")[1];

/** dist ya horneado + public, por stack. `codesign` no tiene dist en el árbol (Electron). */
const STACKS = [
  { ws: "oficina",   label: "Oficina",   dist: "third_party/openwork/apps/app/dist",              pub: "third_party/openwork/apps/app/public" },
  { ws: "finanzas",  label: "Finanzas",  dist: "third_party/vibetrading/frontend/dist",           pub: "third_party/vibetrading/frontend/public" },
  { ws: "legal",     label: "Legal",     dist: "third_party/dochaus/apps/web/dist",               pub: "third_party/dochaus/apps/web/public" },
  { ws: "ciencia",   label: "Ciencia",   dist: "third_party/openscience/frontend/workspace/dist", pub: "third_party/openscience/frontend/workspace/public" },
  /* ⚠️ EDUCACIÓN NO ES UN `dist/`. Next con `output: standalone` deja el HTML renderizado en
   * `.next/server/app/` y los assets en `standalone/public/` + `.next/static` — tres rutas, no
   * una. Modelarlo como los otros cuatro fue mi primer error y la vara declaraba «no hay cara
   * horneada» sobre una cara que existe. Se declara su forma en vez de forzarla. */
  /* Educación se mide contra SU SERVIDOR, no contra archivos. Servir su HTML renderizado
   * como estático no alcanza: es una app de Next que hidrata, y sin su runtime la página
   * queda muda (lo medí: la sonda devolvía `undefined` en todo). Su `standalone/server.js`
   * arranca en menos de un segundo, así que la vara lo levanta y hace de PROXY para poder
   * inyectar la sonda. Es más instrumento, y es el único que puede medirlo de verdad. */
  { ws: "educacion", label: "Educación",
    servidor: { dir: "third_party/deeptutor/web/.next/standalone", puerto: 8879 } },
];

const fallos = [];
const ok = (c, m) => { console.log(`  ${c ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${m}`); if (!c) fallos.push(m); };

const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
  ".ttf": "font/ttf", ".ico": "image/x-icon", ".map": "application/json", ".webp": "image/webp" };

/** La sonda: corre en el HIJO y contesta lo que el navegador COMPUTÓ, no lo que el CSS dice. */
const SONDA = `<script>window.addEventListener("load",function(){setTimeout(function(){
  try{
    var cs=getComputedStyle(document.documentElement);
    var r={ piel: document.documentElement.getAttribute("data-aleph-piel")||"",
            esquema: document.documentElement.getAttribute("data-aleph-scheme")||"",
            lienzo: (cs.getPropertyValue("--al-lienzo")||"").trim(),
            tinta: (cs.getPropertyValue("--al-tinta")||"").trim(),
            familia: (getComputedStyle(document.body).fontFamily||"").split(",")[0].replace(/["']/g,""),
            fondo: getComputedStyle(document.body).backgroundColor,
            fondoRaiz: getComputedStyle(document.documentElement).backgroundColor,
            cabecera: !!document.querySelector(".aleph-piel-cabecera"),
            url: location.href.slice(-90), corrio: !!window.__alephPielCorrio };
    parent.postMessage({t:"sonda",r:r},"*");
  }catch(e){ parent.postMessage({t:"sonda",r:{err:String(e)}},"*"); }
},900);});<\/script>`;

/** Levanta el `server.js` del stack y espera a que conteste. Devuelve el proceso. */
function levantarStack(stack) {
  return new Promise((res, rej) => {
    const p = spawn("node", ["server.js"], {
      cwd: path.join(RAIZ, stack.servidor.dir),
      env: { ...process.env, PORT: String(stack.servidor.puerto), HOSTNAME: "127.0.0.1" },
      stdio: "ignore",
    });
    let n = 0;
    const tic = setInterval(() => {
      fetch(`http://127.0.0.1:${stack.servidor.puerto}/`).then(() => { clearInterval(tic); res(p); })
        .catch(() => { if (++n > 40) { clearInterval(tic); try { p.kill("SIGKILL"); } catch (_) {} rej(new Error("el server del stack no levantó")); } });
    }, 250);
  });
}

function servidor(stack, puerto) {
  // Modo PROXY: el stack sirve su propia app y esta vara sólo se mete en el medio para
  // inyectar la sonda en el HTML. Es lo mismo que hace con los archivos, un piso más abajo.
  if (stack.servidor) {
    return new Promise((res) => {
      const srv = createServer(async (req, rq) => {
        if (req.url.startsWith("/__marco")) {
          rq.writeHead(200, { "content-type": "text/html; charset=utf-8" });
          const q = req.url.split("?")[1] || "";
          return rq.end(`<title>esperando</title><style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>`
            + `<script>addEventListener("message",function(e){if(e.data&&e.data.t==="sonda")document.title=JSON.stringify(e.data.r);});</script>`
            + `<iframe src="/?${q}"></iframe>`);
        }
        try {
          const r = await fetch(`http://127.0.0.1:${stack.servidor.puerto}${req.url}`, { redirect: "manual" });
          const ct = r.headers.get("content-type") || "";
          if (MUT && req.url.startsWith("/aleph-piel.css")) {
            rq.writeHead(200, { "content-type": "text/css" }); return rq.end("/* MUTADO */");
          }
          if (ct.includes("text/html")) {
            let html = await r.text();
            const i = html.search(/<\/head>/i);
            html = i >= 0 ? html.slice(0, i) + SONDA + html.slice(i) : SONDA + html;
            rq.writeHead(r.status, { "content-type": ct, "cache-control": "no-store" });
            return rq.end(html);
          }
          const buf = Buffer.from(await r.arrayBuffer());
          rq.writeHead(r.status, { "content-type": ct || "application/octet-stream", "cache-control": "no-store" });
          return rq.end(buf);
        } catch (e) { rq.writeHead(502); rq.end(String(e)); }
      });
      srv.listen(puerto, "127.0.0.1", () => res(srv));
    });
  }
  const DIST = path.join(RAIZ, stack.dist), PUB = path.join(RAIZ, stack.pub);
  return new Promise((res) => {
    const srv = createServer((req, rq) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/__marco") {                       // el PADRE: sólo un iframe y un buzón
        rq.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        const q = req.url.split("?")[1] || "";
        return rq.end(`<title>esperando</title><style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>`
          + `<script>addEventListener("message",function(e){if(e.data&&e.data.t==="sonda")document.title=JSON.stringify(e.data.r);});</script>`
          + `<iframe src="/?${q}"></iframe>`);
      }
      if (p === "/") p = "/index.html";
      // Las reescrituras que el stack necesita (Next sirve `/_next/static` desde otra raíz).
      let abs = null;
      for (const [pre, raiz] of (stack.extra || [])) {
        if (p.startsWith(pre)) { abs = path.join(RAIZ, raiz, p.slice(pre.length)); break; }
      }
      if (!abs) abs = path.join(DIST, p);
      if (!fs.existsSync(abs) || fs.statSync(abs).isDirectory()) abs = path.join(PUB, p);
      // Una SPA sirve su index para cualquier ruta; acá alcanza con el index.
      if (!fs.existsSync(abs)) abs = path.join(DIST, "index.html");
      const ext = path.extname(abs);
      if (ext === ".html") {
        let html = fs.readFileSync(abs, "utf8");
        const i = html.search(/<\/head>/i);
        html = i >= 0 ? html.slice(0, i) + SONDA + html.slice(i) : SONDA + html;
        rq.writeHead(200, { "content-type": MIME[ext], "cache-control": "no-store" });
        return rq.end(html);
      }
      if (MUT && p === "/aleph-piel.css") {          // la mutación: la hoja, vacía
        rq.writeHead(200, { "content-type": "text/css" });
        return rq.end("/* MUTADO */");
      }
      rq.writeHead(200, { "content-type": MIME[ext] || "application/octet-stream", "cache-control": "no-store" });
      fs.createReadStream(abs).pipe(rq);
    });
    srv.listen(puerto, "127.0.0.1", () => res(srv));
  });
}

function chrome(url, dump, png) {
  return new Promise((res, rej) => {
    const args = ["--headless=new", "--disable-gpu", "--hide-scrollbars",
      "--force-device-scale-factor=1", "--window-size=1280,840", "--virtual-time-budget=9000",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"];
    if (png) args.push(`--screenshot=${png}`);
    if (dump) args.push("--dump-dom");
    args.push(url);
    const err = fs.openSync(path.join(TMP, "chrome.err"), "a");
    let out = "";
    const p = spawn(CHROME, args, { stdio: ["ignore", "pipe", err] });
    p.stdout.on("data", (d) => { out += d; });
    const reloj = setTimeout(() => { try { p.kill("SIGKILL"); } catch (_) {} }, 60000);
    p.on("close", () => { clearTimeout(reloj); try { fs.closeSync(err); } catch (_) {} res(out); });
    p.on("error", rej);
  });
}

async function sonda(puerto, stack, conFlag, png) {
  const q = `aleph_ws=${stack.ws}&aleph_label=${encodeURIComponent(stack.label)}&aleph_scheme=light`
          + (conFlag ? "&aleph_piel=v2" : "");
  const dom = await chrome(`http://127.0.0.1:${puerto}/__marco?${q}`, true, png);
  const m = dom.match(/<title>([\s\S]*?)<\/title>/i);
  if (!m) return { err: "sin title" };
  try { return JSON.parse(m[1].replace(/&quot;/g, '"')); } catch (e) { return { err: m[1].slice(0, 120) }; }
}

if (!fs.existsSync(CHROME)) { console.error(`✗ no está Chrome en ${CHROME} — esto es rojo, no salteado`); process.exit(2); }
const SALIDA = path.join(RAIZ, "qa/visual/stacks");
fs.mkdirSync(SALIDA, { recursive: true });

let puerto = 8830 + (process.pid % 120);
for (const st of STACKS) {
  if (SOLO && st.ws !== SOLO) continue;
  if (!st.servidor && !fs.existsSync(path.join(RAIZ, st.dist, "index.html"))) {
    console.log(`\n── ${st.label} ──\n  ~ [no medible] no hay dist horneado en el árbol (${st.dist}) — pide build`);
    continue;
  }
  if (st.servidor && !fs.existsSync(path.join(RAIZ, st.servidor.dir, "server.js"))) {
    console.log(`\n── ${st.label} ──\n  ~ [no medible] no hay standalone horneado (${st.servidor.dir}) — pide build`);
    continue;
  }
  console.log(`\n── ${st.label} · ${(st.dist || st.servidor.dir).replace("third_party/", "")} ──`);
  /* ⚠️ SI LA CARA HORNEADA ES VIEJA, ESTO NO ES MEDIBLE — Y NO ES ROJO.
   * `aleph-piel.js` entra por una línea del `index.html`, y esa línea la puso la fase 1: un
   * `dist` anterior no la tiene y la piel NO PUEDE aplicarse. Reportarlo como falla sería
   * culpar a la piel de un build que no corrió, y una vara que siempre es roja se ignora
   * igual que una que siempre es verde. `verify_piel_viajo.py` es la que lleva esa cuenta. */
  {
    const idx = st.servidor
      ? path.join(RAIZ, "third_party/deeptutor/web/.next/standalone/.next/server/app/index.html")
      : path.join(RAIZ, st.dist, "index.html");
    if (fs.existsSync(idx) && !fs.readFileSync(idx, "utf8").includes("aleph-piel.js")) {
      console.log("  ~ [no medible] la cara horneada es anterior al enganche de la fase 1 — pide build");
      continue;
    }
  }
  let hijo = null;
  if (st.servidor) { try { hijo = await levantarStack(st); } catch (e) { console.log(`  ~ [no medible] ${e.message}`); continue; } }
  const srv = await servidor(st, puerto);
  try {
    const con = await sonda(puerto, st, true,  path.join(SALIDA, `${st.ws}.con-piel.png`));
    if (process.env.VERBOSE) console.log("    sonda(con):", JSON.stringify(con));
    const sin = await sonda(puerto, st, false, path.join(SALIDA, `${st.ws}.sin-piel.png`));
    ok(con.piel === "v2", `CON flag · el documento queda marcado (data-aleph-piel="${con.piel}")`);
    ok(con.lienzo === "#f4f3f1", `CON flag · el navegador COMPUTA --al-lienzo = ${con.lienzo || "(vacío)"}`);
    ok(con.tinta === "#1c1c1a", `CON flag · …y --al-tinta = ${con.tinta || "(vacío)"}`);
    ok(con.familia === "Poppins", `CON flag · la letra del body es ${con.familia || "(nada)"}`);
    ok(con.esquema === "light", `CON flag · el esquema de la casa llegó (data-aleph-scheme="${con.esquema}")`);
    /* ⚠️ [fase 5 · 5.2] EL ASERTO QUE FALTABA, Y LA SONDA YA TRAÍA EL DATO.
     * Esta vara daba 35/35 en verde con la piel de FINANZAS ROTA: medía que el navegador
     * COMPUTA `--al-lienzo`, que es nuestro token, y nunca que ese token LLEGUE A PINTAR
     * algo. Son dos cosas distintas y la diferencia la vio la pantalla: vibetrading usa el
     * shadcn VIEJO (`--background: 240 5% 96%`, triplete pelado, su Tailwind compila
     * `hsl(var(--background))`), así que nuestro hex producía `hsl(#f4f3f1)` —inválido— y
     * TODA su capa semántica caía a transparente sin un error en consola. El sidebar se
     * fundía con el lienzo y la píldora del ítem activo desaparecía.
     * `fondo` estaba en la sonda desde la fase 3, recogido y tirado. Ahora se mide. */
    const pinta = (v) => v && v !== "rgba(0, 0, 0, 0)" && v !== "transparent";
    const efectivo = pinta(con.fondo) ? con.fondo : con.fondoRaiz;
    ok(efectivo === "rgb(244, 243, 241)",
      `CON flag · el token PINTA de verdad — el fondo efectivo de la página es ${efectivo || "(nada)"}`);
    ok(efectivo !== (pinta(sin.fondo) ? sin.fondo : sin.fondoRaiz),
      `CON flag · …y es distinto del suyo (${(pinta(sin.fondo) ? sin.fondo : sin.fondoRaiz) || "(nada)"}) — la piel cambió la superficie, no sólo la variable`);
    ok(sin.piel === "" && sin.lienzo === "", `SIN flag · ni marca ni tokens — la cara queda como hoy`);
    ok(sin.familia !== "Poppins", `SIN flag · la letra sigue siendo la suya (${sin.familia || "?"})`);
  } finally { srv.close(); if (hijo) { try { hijo.kill("SIGKILL"); } catch (_) {} } }
  puerto++;
}

console.log("");
if (MUT) {
  if (!fallos.length) { console.log("\x1b[31m✗ LA VARA ESTÁ ROTA\x1b[0m: con la hoja vacía no cayó nada."); process.exit(1); }
  console.log(`\x1b[32m✓ la vara puede dar rojo\x1b[0m: ${fallos.length} afirmaciones cayeron con la hoja vaciada.`); process.exit(0);
}
if (fallos.length) { console.log(`\x1b[31m✗ ${fallos.length} rojas\x1b[0m · las capturas quedaron en qa/visual/stacks/`); process.exit(1); }
console.log(`\x1b[32m✓ la piel se computa en la cara real, y sin el flag no toca nada\x1b[0m · capturas en qa/visual/stacks/`);
process.exit(0);
