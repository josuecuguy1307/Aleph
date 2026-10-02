#!/usr/bin/env node
/**
 * verify_frame_oficina.mjs — EL FRAME DE OFICINA, MEDIDO EN LA CARA HORNEADA Y EN LOS DOS BRAZOS.
 * [el frame · Oficina]
 *
 * QUÉ MIDE, Y POR QUÉ NO ALCANZA CON LEER EL TSX
 * ──────────────────────────────────────────────
 * Que `composer.tsx` diga `rounded-[22px]` no prueba que la caja mida 22: la clase puede no
 * compilarse, la regla puede perder la cascada contra un `!important` del stack, el token
 * puede no existir. Y que `aleph-piel.css` declare `--sidebar-width: 260px` NO alcanzó: el
 * provider de shadcn lo escribe INLINE y el inline gana. Eso se descubrió preguntándole al
 * navegador, no leyendo la hoja. Esta vara pregunta.
 *
 * SE MIDEN LOS DOS BRAZOS, que es lo que convierte al flag en un interruptor:
 *     con `aleph_piel=v2`  → la barra del diseño entera y la barrita al mockup
 *     sin el flag          → «New task · Search sessions · WORKSPACES · Run task», la cara de siempre
 * Un brazo solo no prueba nada: si la vara midiera únicamente el prendido, no distinguiría
 * «el frame funciona» de «el frame se dibuja siempre», que es un defecto.
 *
 * ⚠️ ADENTRO DE UN `<iframe>`, Y NO ES UN DETALLE. `aleph-frame.tsx` abre con
 * `piel === "v2" && window.parent !== window`. Servida al tope, la app cree que NO está
 * adentro de Aleph y la vara mediría «sin frame» en los dos brazos: un verde que no mide nada.
 *
 * ⚠️ Y EL PADRE CONTESTA LOS MENSAJES DE LA CÁSCARA. El pie pregunta `aleph-pie-censo?` y
 * `aleph-identidad?` y dibuja con lo que le contesten. Un padre mudo dejaría el pie con un
 * solo ítem y sin cuenta, y la vara declararía roto algo que está bien. El `__marco` de acá
 * contesta lo mismo que contesta `product/app/design/workspaces/oficina.html`.
 *
 * PROBADA CAYENDO
 *     node qa/verify_frame_oficina.mjs --mutante
 * sirve `aleph-piel.css` vacía y exige que el brazo «con flag» caiga.
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST = path.join(RAIZ, "third_party/openwork/apps/app/dist");
const PUB = path.join(RAIZ, "third_party/openwork/apps/app/public");
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "frame-oficina-"));
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const MUT = process.argv.includes("--mutante");

const fallos = [];
const ok = (c, m) => { console.log(`  ${c ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m"} ${m}`); if (!c) fallos.push(m); };

const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png",
  ".svg": "image/svg+xml", ".woff2": "font/woff2", ".ico": "image/x-icon", ".map": "application/json" };

/* La sonda. Devuelve lo que el navegador COMPUTÓ. Espera 1,6 s porque el pie se dibuja recién
 * cuando el padre contesta el censo, y eso es un viaje de ida y vuelta después del montaje. */
const SONDA = `<script>window.addEventListener("load",function(){setTimeout(function(){
  try{
    var d=document, g=function(e){return e?getComputedStyle(e):null;}, q=function(s){return d.querySelector(s);};
    var w=function(e){return e?Math.round(e.getBoundingClientRect().width):0;};
    var txt=function(s){var e=q(s);return e?(e.textContent||"").trim():"";};
    var barra=q('[data-sidebar="sidebar"]'), caja=q(".aleph-composer");
    var clip=q(".aleph-composer-clip"), pal=q(".aleph-composer-palitos"), env=q(".aleph-composer-enviar");
    var pie=q(".aleph-frame-pie"), sal=q(".aleph-hero-saludo");
    var r={
      piel: d.documentElement.getAttribute("data-aleph-piel")||"",
      nativo: d.documentElement.getAttribute("data-aleph-frame-nativo")||"",
      anchoBarra: w(barra),
      marca: txt(".aleph-frame-wordmark"), espacio: txt(".aleph-frame-espacio"),
      inicio: txt(".aleph-frame-inicio"),
      pieItems: pie ? [].slice.call(pie.querySelectorAll(".aleph-frame-pie-item")).map(function(b){return (b.textContent||"").trim();}) : [],
      cuenta: txt(".aleph-frame-cuenta-nom"),
      cuentaLinea: txt(".aleph-frame-cuenta-rol"),
      acciones: !!q(".aleph-frame-acciones"),
      flechasSueltas: !!q('[aria-label="Conversation history controls"]'),
      flechasVivas: [].slice.call(d.querySelectorAll("[data-conversation-history-control]")).length,
      colapsar: !!q(".aleph-frame-colapsar"),
      /* los rótulos del bloque estándar, tal como salen en pantalla */
      rotulos: [].slice.call(d.querySelectorAll('[data-sidebar="sidebar"] button, [data-sidebar="sidebar"] a'))
        .map(function(b){return (b.textContent||"").trim();}).filter(Boolean).slice(0,12),
      grupos: [].slice.call(d.querySelectorAll('[data-sidebar="sidebar"] span'))
        .map(function(s){return (s.textContent||"").trim();}).filter(function(t){return /^(RECENT SESSIONS|Workspaces)$/.test(t);}),
      /* la barrita */
      caja: caja ? { w:w(caja), radio:g(caja).borderRadius, bg:g(caja).backgroundColor } : null,
      clip: clip ? { w:w(clip), radio:g(clip).borderRadius } : null,
      palitos: pal ? { w:w(pal), radio:g(pal).borderRadius, bg:g(pal).backgroundColor, color:g(pal).color } : null,
      enviar: env ? { w:w(env), radio:g(env).borderRadius, rotulo:(env.textContent||"").trim(), aria:env.getAttribute("aria-label")||"" } : null,
      enviarViejo: (function(){ var b=[].slice.call(d.querySelectorAll("button")).filter(function(x){return /Run task/.test(x.textContent||"");}); return b.length; })(),
      pista: txt(".aleph-composer-pista"),
      ph: (function(){ var e=q(".aleph-composer-ph")||q('[class*="pointer-events-none"][class*="absolute"]'); return e?{f:g(e).fontSize+"/"+g(e).fontWeight, color:g(e).color}:null; })(),
      saludo: sal ? { txt:(sal.textContent||"").trim(), peso:g(sal).fontWeight, size:g(sal).fontSize } : null,
      sugerencias: [].slice.call(d.querySelectorAll("button")).filter(function(b){return /Summarize my week|Clean up a spreadsheet/.test(b.textContent||"");}).length,
      enchufe: !!q(".aleph-composer") && !q(".aleph-composer-palitos"),
      fondoBarra: barra ? g(barra).backgroundColor : "", fondoLienzo: getComputedStyle(d.body).backgroundColor
    };
    /* ── PLEGAR Y VOLVER, MEDIDO DESPUÉS DE LA TRANSICIÓN ──────────────────────────────
     * ⚠️ ACÁ NO HAY UN RIEL DE 48 px. La barra de este stack es collapsible="offcanvas"
     * (app-sidebar.tsx:1104): plegar no la encoge, la SACA. Así que lo que hay que medir no
     * es «los textos se esconden» —eso es de un plegado tipo icon, que este stack no usa—
     * sino que (a) la barra se va de verdad y (b) queda una forma VISIBLE de traerla de
     * vuelta. Si no queda, el usuario pierde la barra y sólo la recupera con un atajo que
     * nadie le dijo.
     * Se espera 700 ms: el plegado es una transicion de 200 ms y medir a mitad devuelve
     * numeros imposibles. */
    var trig = q(".aleph-frame-colapsar");
    if (!trig) { r.plegada = {err:"no hay colapsar en la cabecera"}; parent.postMessage({t:"sonda",r:r},"*"); return; }
    trig.click();
    setTimeout(function(){
      try{
        var raiz = q('[data-slot="sidebar"]');
        var visible = function(sel){
          var e=q(sel); if(!e) return false;
          var b=e.getBoundingClientRect();
          return b.width>0 && b.height>0 && g(e).visibility!=="hidden" && b.right>0 && b.left<innerWidth;
        };
        r.plegada = {
          estado: raiz ? raiz.getAttribute("data-state") : "",
          modo: raiz ? raiz.getAttribute("data-collapsible") : "",
          vuelta: {
            trigger: visible('[data-slot="sidebar-trigger"], button[data-sidebar="trigger"]'),
            riel: visible('[data-sidebar="rail"], [data-slot="sidebar-rail"]')
          }
        };
      }catch(e){ r.plegada = {err:String(e)}; }
      parent.postMessage({t:"sonda",r:r},"*");
    }, 700);
  }catch(e){ parent.postMessage({t:"sonda",r:{err:String(e)+" @ "+(e.stack||"").split("\\n")[1]}},"*"); }
},1600);});<\/script>`;

/* El PADRE: el buzón de la sonda MÁS las dos respuestas que da la cáscara de verdad. */
const MARCO = (q) => `<title>esperando</title>
<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>
<script>
addEventListener("message",function(e){
  var d=e.data||{};
  if(d.t==="sonda"){ document.title=JSON.stringify(d.r); return; }
  var f=document.querySelector("iframe");
  if(!f||e.source!==f.contentWindow) return;
  if(d.type==="aleph-pie-censo?"){
    f.contentWindow.postMessage({type:"aleph-pie-censo",botones:[
      {id:"destinos",rotulo:"Ir a…"},{id:"conectores",rotulo:"Conectores"}]},"*");
  }
  if(d.type==="aleph-identidad?"){
    f.contentWindow.postMessage({type:"aleph-identidad",nombre:"Renata O.",linea:"renata@aleph.app"},"*");
  }
});
</script>
<iframe src="/?${q}"></iframe>`;

function servidor(puerto) {
  return new Promise((res) => {
    const srv = createServer((req, rq) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/__marco") {
        rq.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        return rq.end(MARCO(req.url.split("?")[1] || ""));
      }
      if (MUT && p === "/aleph-piel.css") {
        rq.writeHead(200, { "content-type": "text/css" });
        return rq.end("/* MUTADO */");
      }
      if (p === "/") p = "/index.html";
      let abs = path.join(DIST, p);
      if (!fs.existsSync(abs) || fs.statSync(abs).isDirectory()) abs = path.join(PUB, p);
      if (!fs.existsSync(abs)) abs = path.join(DIST, "index.html");
      const ext = path.extname(abs);
      if (ext === ".html") {
        let html = fs.readFileSync(abs, "utf8");
        const i = html.search(/<\/head>/i);
        html = i >= 0 ? html.slice(0, i) + SONDA + html.slice(i) : SONDA + html;
        rq.writeHead(200, { "content-type": MIME[ext], "cache-control": "no-store" });
        return rq.end(html);
      }
      rq.writeHead(200, { "content-type": MIME[ext] || "application/octet-stream", "cache-control": "no-store" });
      fs.createReadStream(abs).pipe(rq);
    });
    srv.listen(puerto, "127.0.0.1", () => res(srv));
  });
}

function chrome(url, png) {
  return new Promise((res, rej) => {
    const args = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
      "--window-size=1280,840", "--virtual-time-budget=12000",
      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--dump-dom"];
    if (png) args.push(`--screenshot=${png}`);
    args.push(url);
    const err = fs.openSync(path.join(TMP, "chrome.err"), "a");
    let out = "";
    const p = spawn(CHROME, args, { stdio: ["ignore", "pipe", err] });
    p.stdout.on("data", (d) => { out += d; });
    const reloj = setTimeout(() => { try { p.kill("SIGKILL"); } catch (_) {} }, 70000);
    p.on("close", () => { clearTimeout(reloj); try { fs.closeSync(err); } catch (_) {} res(out); });
    p.on("error", rej);
  });
}

async function sonda(puerto, conFlag, png) {
  const q = "aleph_ws=oficina&aleph_label=Oficina&aleph_scheme=light&aleph_embed=1"
          + (conFlag ? "&aleph_piel=v2" : "");
  const dom = await chrome(`http://127.0.0.1:${puerto}/__marco?${q}`, png);
  const m = dom.match(/<title>([\s\S]*?)<\/title>/i);
  if (!m) return { err: "sin title — la sonda no contestó" };
  try { return JSON.parse(m[1].replace(/&quot;/g, '"')); } catch (e) { return { err: m[1].slice(0, 200) }; }
}

/* ── arranque ─────────────────────────────────────────────────────────────────────────── */
if (!fs.existsSync(CHROME)) { console.error(`✗ no está Chrome en ${CHROME} — esto es rojo, no salteado`); process.exit(2); }
if (!fs.existsSync(path.join(DIST, "index.html"))) {
  /* Sin cara horneada esto NO ES MEDIBLE, y no es rojo: una vara que siempre es roja se
   * ignora igual que una que siempre es verde. */
  console.log("~ [no medible] no hay dist horneado en third_party/openwork/apps/app/dist — corré `pnpm build` en third_party/openwork");
  process.exit(3);
}

const SALIDA = path.join(RAIZ, "qa/visual/frame-oficina");
fs.mkdirSync(SALIDA, { recursive: true });
const puerto = 8940 + (process.pid % 50);
const srv = await servidor(puerto);
console.log(`\n══ EL FRAME DE OFICINA · dist horneado · ${MUT ? "MUTANTE (la hoja, vacía)" : "normal"} ══`);

const con = await sonda(puerto, true, path.join(SALIDA, "con-flag.png"));
const sin = await sonda(puerto, false, path.join(SALIDA, "sin-flag.png"));
srv.close();

if (con.err) { console.log(`  ✗ la sonda del brazo CON flag falló: ${con.err}`); fallos.push("sonda con flag"); }
if (sin.err) { console.log(`  ✗ la sonda del brazo SIN flag falló: ${sin.err}`); fallos.push("sonda sin flag"); }

if (!con.err) {
  console.log("\n── brazo CON `aleph_piel=v2` ──");
  ok(con.piel === "v2", `la hoja se aplicó (data-aleph-piel = ${JSON.stringify(con.piel)})`);
  ok(con.nativo === "1", "el frame nativo se montó y apaga la inyección");
  ok(con.anchoBarra === 260, `la barra mide 260 px (medido: ${con.anchoBarra})`);
  ok(con.marca === "Aleph", `la marca dice «Aleph» (${JSON.stringify(con.marca)})`);
  ok(con.espacio === "Oficina", `el espacio dice «Oficina» (${JSON.stringify(con.espacio)})`);
  ok(/Inicio/.test(con.inicio), `«‹ Inicio» está (${JSON.stringify(con.inicio)})`);
  ok(con.rotulos.some((r) => /^New chat/.test(r)), "el rótulo es «New chat», no «New task»");
  ok(con.rotulos.some((r) => /^Search/.test(r) && !/sessions/.test(r)), "el rótulo es «Search», no «Search sessions»");
  ok(con.rotulos.some((r) => /^Library/.test(r)), "«Library» está");
  ok(con.grupos.some((g) => g === "RECENT SESSIONS"), `el grupo es «RECENT SESSIONS» (${JSON.stringify(con.grupos)})`);
  ok(!con.grupos.some((g) => g === "Workspaces"), "el rótulo viejo del grupo ya no se dibuja");

  console.log("  — el pie, con lo que la cáscara contestó —");
  ok(con.pieItems.some((t) => /Settings/.test(t)), `«⚙ Settings» está (${JSON.stringify(con.pieItems)})`);
  ok(con.pieItems.some((t) => /Ir a/.test(t)), "«Ir a…» recuperó su disparador (era el defecto nº12)");
  ok(con.pieItems.some((t) => /Conectores/.test(t)), "«Conectores» recuperó su disparador");
  ok(con.cuenta === "Renata O.", `la cuenta es la que contestó ALEPH (${JSON.stringify(con.cuenta)})`);
  ok(con.cuentaLinea === "renata@aleph.app", `y su línea (${JSON.stringify(con.cuentaLinea)})`);

  console.log("  — la cabecera —");
  ok(con.acciones, "la fila de la marca tiene su bloque de acciones");
  ok(con.colapsar, "el colapsar del mockup está en la cabecera");
  ok(!con.flechasSueltas, "la segunda barra de ← → arriba del sidebar ya no está");
  ok(con.flechasVivas === 2, `y las dos flechas SIGUEN VIVAS, mudadas (medido: ${con.flechasVivas})`);

  console.log("  — la barrita (piezas 07 y 09) —");
  ok(con.caja && con.caja.radio === "22px", `la caja tiene radio 22 (${con.caja && con.caja.radio})`);
  ok(con.clip && con.clip.w === 34 && con.clip.radio === "10px", `el clip mide 34 y radio 10 (${JSON.stringify(con.clip)})`);
  ok(con.palitos && con.palitos.w === 34 && con.palitos.radio === "10px", `los dos palitos miden 34 y radio 10 (${JSON.stringify(con.palitos && { w: con.palitos.w, radio: con.palitos.radio })})`);
  ok(con.palitos && con.palitos.bg === "rgb(236, 234, 253)", `los dos palitos van sobre lavanda #eceafd (${con.palitos && con.palitos.bg})`);
  ok(con.palitos && con.palitos.color === "rgb(71, 71, 201)", `y su trazo es el indigo #4747c9 (${con.palitos && con.palitos.color})`);
  ok(!con.enchufe, "el ENCHUFE se fue: el símbolo son los dos palitos");
  ok(con.enviar && con.enviar.w === 38 && con.enviar.radio === "999px", `el enviar es un círculo de 38 (${JSON.stringify(con.enviar && { w: con.enviar.w, radio: con.enviar.radio })})`);
  ok(con.enviar && con.enviar.rotulo === "", "el enviar no lleva rótulo en el píxel");
  ok(con.enviar && /.+/.test(con.enviar.aria), `pero SÍ lo lleva para un lector de pantalla (${JSON.stringify(con.enviar && con.enviar.aria)})`);
  ok(con.enviarViejo === 0, "y no quedó ningún botón «Run task» con rótulo");
  ok(/Enter/.test(con.pista) && /Shift/.test(con.pista), `la pista del atajo está (${JSON.stringify(con.pista)})`);
  ok(con.ph && con.ph.f === "15px/300", `el placeholder es 15px peso 300 (${con.ph && con.ph.f})`);
  ok(con.ph && con.ph.color === "rgb(107, 107, 100)", `y va en el gris de etiqueta, opaco (${con.ph && con.ph.color})`);

  console.log("  — el saludo (pieza 03 · 5a) —");
  ok(!!con.saludo, "el saludo del estándar se pinta");
  ok(con.saludo && con.saludo.peso === "200", `en peso 200, el único texto en 200 (${con.saludo && con.saludo.peso})`);
  ok(con.saludo && con.saludo.size === "52px", `y en 52 px (${con.saludo && con.saludo.size})`);
  ok(con.sugerencias === 0, `las cuatro sugerencias no se dibujan (medido: ${con.sugerencias})`);

  console.log("  — plegar y volver (la barra es offcanvas, no icon) —");
  const pl = con.plegada || {};
  ok(!pl.err, `el colapsar responde (${pl.err || "ok"})`);
  ok(pl.modo === "offcanvas", `el modo de plegado es offcanvas, no icon (${pl.modo})`);
    ok(pl.estado === "collapsed", `la barra queda plegada (state=${pl.estado})`);
  /* ⚠️ LA GEOMETRÍA NO SE MIDE ACÁ, Y NO ES PEREZA. Chrome corre con --virtual-time-budget,
   * que adelanta los timers pero deja la transición de CSS avanzando por frames: cualquier
   * espera devuelve números de mitad de camino (medido: el lienzo en x=260 con la barra ya
   * plegada, y la captura del final mostrándola ida). Esperar por frames tampoco cerró: el
   * navegador se va antes. Lo que el instrumento SÍ puede afirmar sin mentir es el estado y
   * la afordancia; la geometría la prueba `qa/visual/frame-oficina/con-flag.png`, que se saca
   * al final y muestra el lienzo entero con el disparador arriba a la izquierda. Es la regla
   * de la casa: cuando la vara no puede, la mira la pantalla — y se dice cuál de las dos
   * está midiendo. */
  /* LA QUE IMPORTA. Al apagar el colapsar de la barra de arriba —porque el frame dibuja el
   * suyo— me quedaba SIN forma visible de traer la barra de vuelta: siendo offcanvas, el mío
   * se va con ella. Acá se exige que quede al menos una. */
  ok(!!(pl.vuelta && (pl.vuelta.trigger || pl.vuelta.riel)),
     `queda una forma VISIBLE de traerla de vuelta (trigger:${pl.vuelta && pl.vuelta.trigger} · riel:${pl.vuelta && pl.vuelta.riel})`);

  console.log("  — la alarma heredada de Finanzas, medida acá —");
  ok(con.fondoBarra === "rgb(247, 246, 244)", `la barra es #f7f6f4, no un gris lavado (${con.fondoBarra})`);
  ok(con.fondoLienzo === "rgb(244, 243, 241)", `y el lienzo es #f4f3f1 (${con.fondoLienzo})`);
}

if (!sin.err) {
  console.log("\n── brazo SIN flag · la cara de siempre ──");
  ok(sin.piel === "", "la hoja NO se aplica");
  ok(sin.nativo === "", "el frame nativo NO se monta");
  ok(!sin.saludo, "no hay saludo del estándar");
  ok(sin.sugerencias > 0, `las sugerencias siguen ahí (medido: ${sin.sugerencias})`);
  ok(sin.enviarViejo > 0, "el enviar vuelve a ser la píldora «Run task» con rótulo");
  ok(sin.pista === "", "no hay pista del atajo");
  ok(sin.pieItems.length === 0, "no hay pie de Aleph");
  ok(sin.flechasSueltas, "las ← → vuelven a su franja de siempre");
  /* ⚠️ EL DOM DICE «Workspaces», NO «WORKSPACES». La clave `workspace_list.title` vale
   * "Workspaces" y son las MAYÚSCULAS DEL CSS las que lo suben; `textContent` devuelve el
   * texto sin transformar. Escrito con la mayúscula, este assert salía rojo con el código
   * bien: era la vara la que estaba mal, no la barra. */
  ok(sin.grupos.some((g) => g === "Workspaces"), `el grupo vuelve a su rótulo de siempre (${JSON.stringify(sin.grupos)})`);
  ok(sin.rotulos.some((r) => /New task/.test(r)), "y el rótulo vuelve a ser «New task»");
}

console.log(`\ncapturas: ${SALIDA}`);
if (MUT) {
  console.log(fallos.length
    ? `\n\x1b[32m✓ MUTANTE: la vara CAE cuando la hoja está vacía (${fallos.length} rojas). Mide algo.\x1b[0m`
    : `\n\x1b[31m✗ MUTANTE: la vara sigue VERDE con la hoja vacía. No mide nada.\x1b[0m`);
  process.exit(fallos.length ? 0 : 1);
}
console.log(fallos.length ? `\n\x1b[31m✗ ${fallos.length} rojas\x1b[0m` : `\n\x1b[32m✓ todo verde\x1b[0m`);
process.exit(fallos.length ? 1 : 0);
