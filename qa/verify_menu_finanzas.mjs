/**
 * VARA · EL MENÚ «+» DE FINANZAS — la deuda de la fase 4.4
 * [rediseño · fase 5 · obra 5.0]
 *
 * QUÉ PRUEBA, y por qué así:
 *
 * El dueño decidió (opción 3) que los cuatro ítems del mockup 35b se quedan tal como están
 * dibujados, y que los dos que llaman TOOLS —`Check connector` y `Analyze connector
 * portfolio`— NO manden el turno solos: el click ESCRIBE LA FRASE en el composer y el humano
 * aprieta enviar. La regla de la fase 4 sigue mandando: «leer el efecto en el DESTINO FINAL,
 * no en el toggle ni en el archivo intermedio». Acá el destino final es el `<textarea>` del
 * composer de vibetrading y la RED: si el turno salió, sale un `fetch`.
 *
 * ══ ACTUALIZADA 2026-09-09 · EL CONTRATO CAMBIÓ DE LUGAR, Y LA VARA MEDÍA EL VIEJO ══
 *
 * Esta vara nació midiendo un PUENTE: `aleph-piel.js` interceptaba el click desde afuera de
 * React con `preventDefault`/`stopPropagation` y escribía la frase él. Hoy eso ya no gobierna:
 * el dueño autorizó abrir el cuerpo y **el handler vive en `Composer.tsx`** — los dos ítems de
 * tool hacen `setInput(FRASE)` + `focus()` y NO mandan el turno. Dos consecuencias que ponían
 * esta vara en rojo sin que nada estuviera roto:
 *
 *   · `Upload PDF document` SALIÓ DEL MENÚ. El artboard de Finanzas dibuja DOS símbolos: el
 *     clip (adjuntar, y nada más) y los dos palitos (el resto). Así que el menú tiene CUATRO
 *     ítems y UN separador, no cinco y dos — y el quinto no se perdió: es un botón propio.
 *     Se mide que esté AFUERA, que es el contrato nuevo, no que no esté.
 *   · EL FLAG YA NO PARTE EL COMPORTAMIENTO. Como el cambio es del componente y no de la piel,
 *     los dos ítems escriben la frase con el frame puesto Y apagado. El arco viejo pedía que
 *     sin flag saliera el turno: eso probaba que el puente era lo que cambiaba. Hoy probaría
 *     lo contrario de lo que el dueño pidió.
 *
 * ⚠️ POR QUÉ SIGUE CLICKEANDO DE VERDAD. Que un `onClick` diga `setInput` no prueba que la
 * frase llegue al textarea ni que no salga un turno: eso depende del render, del estado y de
 * quién más escucha. Se clickea en Chrome sobre el `dist` HORNEADO y se mira el textarea y la
 * red — el destino final, no el archivo intermedio.
 *
 * ⚠️ POR QUÉ ADENTRO DE UN IFRAME. `aleph-piel.js` arranca con la LEY 0 (`window.parent ===
 * window` ⇒ return). Servido suelto no hace NADA y la vara mediría «no hay puente» siempre,
 * en verde y en rojo. El molde del marco + buzón es el de `verify_piel_en_pantalla.mjs`.
 *
 * ⚠️ MEDIDO: el `dist` de vibetrading RENDERIZA EL COMPOSER SIN BACKEND (sonda del 2026-09-07:
 * el disparador aparece a los 500 ms, con 1 textarea y `data-aleph-piel=v2`). Por eso la vara
 * es hermética: `--host-resolver-rules` corta todo lo que no sea 127.0.0.1, y el único
 * `fetch` que aparece es el que dispara el turno — que es justo la señal que buscamos.
 *
 * LOS ARCOS:
 *   A · estructura — los CUATRO ítems del menú en su orden, UN separador, y el clip como
 *       botón PROPIO fuera del menú (es marcado de ellos + el corte que hizo el artboard: si
 *       esto se mueve, hay que volver a medir todo lo de abajo)
 *   B · los dos de UI abren su panel (`Research Goal` y `Agent Swarm`) — con flag y sin flag,
 *       porque no los tocamos y tienen que quedar idénticos
 *   C · los dos de tool: dejan la frase EXACTA en el composer y CERO fetch, con flag y sin
 *       flag — el handler es del componente, así que no depende de la piel
 *   D · sin deriva — las dos frases de `aleph-piel.js` son las constantes de `Composer.tsx`,
 *       y los diez rótulos son los de sus cinco locales
 *   E · CONTROL POSITIVO — se escribe a mano y se aprieta enviar: TIENE que haber fetch.
 *       Sin este arco, el `fetch === 0` de C pasaría igual con el contador roto, y una vara
 *       que no puede ver un turno no puede afirmar que no hubo turno.
 *
 * EL MUTANTE (`--mutante`): ya no hay puente al que sacarle el corte, así que muta lo que hoy
 * SÍ gobierna — se sirve el bundle con la frase de `check` cambiada. C tiene que caer por
 * «la frase quedó ENTERA». Una vara que no puede dar rojo no mide nada.
 */
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const RAIZ = path.resolve(new URL(".", import.meta.url).pathname, "..");
const DIST = path.join(RAIZ, "third_party/vibetrading/frontend/dist");
const FUENTE = path.join(RAIZ, "third_party/vibetrading/frontend/public/aleph-piel.js");
const COMPOSER = path.join(RAIZ, "third_party/vibetrading/frontend/src/components/chat/Composer.tsx");
const LOCALES = path.join(RAIZ, "third_party/vibetrading/frontend/src/i18n/locales");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const MUT = process.argv.includes("--mutante");
const TMP = process.env.TMPDIR || "/tmp";
const MIME = { ".html": "text/html;charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2",
  ".woff": "font/woff", ".ttf": "font/ttf", ".ico": "image/x-icon", ".map": "application/json" };

let fallas = 0, pasos = 0;
const ok = (c, q, det) => { pasos++; if (c) console.log(`  ✓ ${q}`); else { fallas++; console.log(`  ✗ ${q}${det ? `  → ${det}` : ""}`); } };

/* ── La sonda: corre en el HIJO. Abre el menú, clickea UN ítem y contesta qué pasó. ────── */
const SONDA = (idx) => `<script>
window.__f=[];(function(){var f=window.fetch;window.fetch=function(){try{window.__f.push(String((arguments[0]&&arguments[0].url)||arguments[0]))}catch(e){}return f.apply(this,arguments)};})();
function esperar(c,ms,cb){var t0=Date.now();var t=setInterval(function(){if(c()||Date.now()-t0>ms){clearInterval(t);cb()}},100)}
function disp(){return document.querySelector('[aria-controls="agent-more-options-menu"]')}
function items(){return document.querySelectorAll('#agent-more-options-menu [role="menuitem"]')}
function clipAfuera(){/* el botón de adjuntar, que el artboard sacó del menú */
 var bs=[].slice.call(document.querySelectorAll("form button"));
 var c=bs.filter(function(x){var l=(x.getAttribute("aria-label")||x.title||"");return /upload|adjunt|pdf/i.test(l)});
 return c.length===1 && c[0].getAttribute("role")!=="menuitem";}
function estado(){var ta=document.querySelector("textarea");var b=(document.body.innerText||"").replace(/\\s+/g," ");
 return {val:ta?ta.value:null, ph:ta?ta.getAttribute("placeholder"):null,
   menu:!!document.querySelector("#agent-more-options-menu"), fetch:window.__f.length,
   goal:b.indexOf("New Research Goal")>=0, swarm:b.indexOf("Agent Swarm")>=0};}
window.addEventListener("load",function(){
 esperar(disp,12000,function(){
  var r={piel:document.documentElement.getAttribute("data-aleph-piel")||""};
  if(!disp()){r.err="nunca apareció el disparador";return parent.postMessage({t:"sonda",r:r},"*")}
  r.clip=clipAfuera();
  if(${idx}===-1){/* E · CONTROL POSITIVO: escribir a mano y enviar. Si esto no produce un
     fetch, el contador no sirve y el «cero fetch» de C no afirma nada. */
   var ta=document.querySelector("textarea");
   var set=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,"value").set;
   set.call(ta,"hola"); ta.dispatchEvent(new Event("input",{bubbles:true}));
   window.__f=[];
   setTimeout(function(){
    var env=document.querySelector('form button[type="submit"]');
    if(env) env.click(); else { var f=document.querySelector("form"); if(f) f.requestSubmit&&f.requestSubmit(); }
    setTimeout(function(){ r.d=estado(); parent.postMessage({t:"sonda",r:r},"*"); },1800);
   },300);
   return;
  }
  disp().click();
  esperar(function(){return document.querySelector("#agent-more-options-menu")},4000,function(){
   var its=items();
   r.rotulos=[].map.call(its,function(b){return (b.textContent||"").replace(/\\s+/g," ").trim()});
   r.unMenu=r.rotulos.length===[].slice.call(document.querySelectorAll('[role="menuitem"]')).length;
   r.seps=document.querySelectorAll("#agent-more-options-menu .border-t").length;
   if(!its[${idx}]){r.err="no hay item "+${idx};return parent.postMessage({t:"sonda",r:r},"*")}
   r.clickeado=(its[${idx}].textContent||"").trim();
   window.__f=[]; its[${idx}].click();
   setTimeout(function(){ r.d=estado(); parent.postMessage({t:"sonda",r:r},"*"); },1500);
  });
 });
});
</script>`;

function servidor(puerto, idx) {
  return new Promise((res) => {
    const srv = createServer((req, rq) => {
      let p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/__marco") {
        const q = req.url.split("?")[1] || "";
        rq.writeHead(200, { "content-type": "text/html;charset=utf-8" });
        return rq.end(`<title>esperando</title><style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>`
          + `<script>addEventListener("message",function(e){if(e.data&&e.data.t==="sonda")document.title=JSON.stringify(e.data.r);});</script>`
          + `<iframe src="/?${q}"></iframe>`);
      }
      if (p === "/") p = "/index.html";
      /* LA MUTACIÓN, MUDADA A DONDE HOY VIVE EL CONTRATO. Antes se le sacaba el corte al
       * puente de `aleph-piel.js`; ese puente ya no gobierna —el handler es de
       * `Composer.tsx`— así que sacarle el corte no haría caer nada, y un mutante que no
       * mata es peor que ninguno. Ahora se muta la FRASE dentro del bundle horneado: el
       * texto sobrevive a la minificación, así que se puede tocar sin depender de nombres
       * de variable. C tiene que caer por «la frase quedó ENTERA».
       * Se sirve mutado en vez de tocar el árbol: un mutante que edita el árbol se olvida
       * de revertir alguna vez. */
      if (MUT && path.extname(p) === ".js" && fs.existsSync(path.join(DIST, p))) {
        let js = fs.readFileSync(path.join(DIST, p), "utf8");
        const frase = frasesDeLaFuente().check;
        if (frase && js.includes(frase)) {
          js = js.split(frase).join("MUTADO — esta frase no es la de la fuente");
          rq.writeHead(200, { "content-type": "text/javascript", "cache-control": "no-store" });
          return rq.end(js);
        }
      }
      let abs = path.join(DIST, p);
      if (!fs.existsSync(abs) || fs.statSync(abs).isDirectory()) abs = path.join(DIST, "index.html");
      const ext = path.extname(abs);
      if (ext === ".html") {
        let h = fs.readFileSync(abs, "utf8");
        const i = h.search(/<\/head>/i);
        h = i >= 0 ? h.slice(0, i) + SONDA(idx) + h.slice(i) : SONDA(idx) + h;
        rq.writeHead(200, { "content-type": MIME[ext], "cache-control": "no-store" });
        return rq.end(h);
      }
      rq.writeHead(200, { "content-type": MIME[ext] || "application/octet-stream", "cache-control": "no-store" });
      fs.createReadStream(abs).pipe(rq);
    });
    srv.listen(puerto, "127.0.0.1", () => res(srv));
  });
}

function chrome(url) {
  return new Promise((res, rej) => {
    /* Hermético a propósito: sin esto la página espera logos externos hasta el SIGKILL.
     * Lo pagamos en la fase 1 y está anotado en `vara_visual.mjs`. */
    const args = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,900",
      "--virtual-time-budget=25000", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
      "--dump-dom", url];
    const err = fs.openSync(path.join(TMP, "vara-menu-finanzas.err"), "a");
    let out = "";
    const p = spawn(CHROME, args, { stdio: ["ignore", "pipe", err] });
    p.stdout.on("data", (d) => { out += d; });
    const reloj = setTimeout(() => { try { p.kill("SIGKILL"); } catch (_) {} }, 70000);
    p.on("close", () => { clearTimeout(reloj); try { fs.closeSync(err); } catch (_) {} res(out); });
    p.on("error", rej);
  });
}

async function correr(puerto, idx, conFlag) {
  const srv = await servidor(puerto, idx);
  try {
    const q = `aleph_ws=finanzas&aleph_label=Finanzas&aleph_scheme=light` + (conFlag ? "&aleph_piel=v2" : "");
    const dom = await chrome(`http://127.0.0.1:${puerto}/__marco?${q}`);
    const m = dom.match(/<title>([\s\S]*?)<\/title>/i);
    if (!m) return { err: "sin title" };
    try { return JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&")); }
    catch (e) { return { err: m[1].slice(0, 160) }; }
  } finally { srv.close(); }
}

/* ── D · SIN DERIVA (estático, y va primero porque es barato) ─────────────────────────── */
function frasesDeLaFuente() {
  const js = fs.readFileSync(FUENTE, "utf8");
  const out = {};
  for (const id of ["check", "portfolio"]) {
    const m = js.match(new RegExp(`id:\\s*"${id}"[\\s\\S]*?frase:\\s*"((?:[^"\\\\]|\\\\.)*)"`));
    out[id] = m ? m[1] : null;
    const r = js.match(new RegExp(`id:\\s*"${id}"[\\s\\S]*?rotulos:\\s*\\[([^\\]]*)\\]`));
    out[id + "_rotulos"] = r ? r[1].split(",").map((s) => s.trim().replace(/^"|"$/g, "")) : [];
  }
  return out;
}

function sinDeriva() {
  console.log("\nD · sin deriva — nuestras copias contra las suyas");
  const f = frasesDeLaFuente();
  const tsx = fs.readFileSync(COMPOSER, "utf8");
  for (const [id, cte] of [["check", "CONNECTOR_CHECK_PROMPT"], ["portfolio", "CONNECTOR_PORTFOLIO_PROMPT"]]) {
    const m = tsx.match(new RegExp(`const ${cte}\\s*=\\s*\\n?\\s*"((?:[^"\\\\]|\\\\.)*)"`));
    const suya = m ? m[1] : null;
    ok(suya !== null && suya === f[id], `la frase de «${id}» es ${cte} de Composer.tsx`,
      suya === null ? "no encontré la constante en su archivo" : `nuestra=${JSON.stringify((f[id] || "").slice(0, 40))} suya=${JSON.stringify(suya.slice(0, 40))}`);
  }
  const claves = { check: "checkConnector", portfolio: "analyzePortfolio" };
  for (const id of ["check", "portfolio"]) {
    const suyos = [];
    for (const l of fs.readdirSync(LOCALES).filter((n) => n.endsWith(".json") && n !== "tsconfig.json")) {
      const j = JSON.parse(fs.readFileSync(path.join(LOCALES, l), "utf8"));
      const v = j && j.agent && j.agent[claves[id]];
      if (v) suyos.push(v);
    }
    const nuestros = f[id + "_rotulos"];
    const faltan = suyos.filter((s) => nuestros.indexOf(s) === -1);
    ok(suyos.length >= 5 && faltan.length === 0,
      `los ${suyos.length} rótulos de «${id}» están en la tabla`, faltan.length ? `faltan: ${JSON.stringify(faltan)}` : `sólo encontré ${suyos.length} locales`);
  }
}

/* ── Main ───────────────────────────────────────────────────────────────────────────────── */
if (!fs.existsSync(CHROME)) { console.error(`✗ no está Chrome en ${CHROME} — esto es rojo, no salteado`); process.exit(2); }
if (!fs.existsSync(path.join(DIST, "index.html"))) { console.error(`✗ falta el dist horneado de Finanzas: ${DIST}`); process.exit(2); }
if (!fs.existsSync(path.join(DIST, "aleph-piel.js"))) { console.error(`✗ el dist no lleva aleph-piel.js — la piel no viajó`); process.exit(2); }

console.log(`VARA · el menú «+» de Finanzas${MUT ? "   [MUTANTE: el puente sin su corte]" : ""}`);
sinDeriva();

/* CUATRO, no cinco: `Upload PDF document` salió del menú y es el clip, botón propio. El
   artboard de Finanzas dibuja dos símbolos —clip y dos palitos— y esto es ese corte. */
const ORDEN = ["Research Goal", "Agent Swarm", "Check connector", "Analyze connector portfolio"];
const FRASES = frasesDeLaFuente();
let puerto = 8840 + (process.pid % 100);

console.log("\nA · estructura — cuatro ítems en el menú, y el clip como botón propio");
const est = await correr(puerto++, 0, true);
ok(!est.err, "la página abrió y el menú desplegó", est.err);
ok(JSON.stringify(est.rotulos) === JSON.stringify(ORDEN), "los cuatro ítems, en el orden del mockup 35b", JSON.stringify(est.rotulos));
ok(est.unMenu === true, "no hay menuitems fuera de #agent-more-options-menu");
ok(est.seps === 1, "un separador — el que separa los de UI de los de tool", `hay ${est.seps}`);
/* El quinto no se perdió: se mide que esté AFUERA. Si mañana vuelve al menú, esto cae. */
ok(est.clip === true, "adjuntar quedó como botón propio, fuera del menú", `clip=${est.clip}`);

console.log("\nB · los dos de UI abren su panel — y con el flag apagado, igual");
for (const conFlag of [true, false]) {
  /* Índices corridos en uno: al salir `Upload PDF document` del menú, `Research Goal` pasó
     a ser el 0 y `Agent Swarm` el 1. */
  const g = await correr(puerto++, 0, conFlag);
  ok(g.d && g.d.ph === "Describe the research goal to attach to this session" && g.d.goal === true,
    `Research Goal abre su panel  [flag ${conFlag ? "v2" : "OFF"}]`, JSON.stringify(g.d && g.d.ph));
  const s = await correr(puerto++, 1, conFlag);
  ok(s.d && s.d.swarm === true && s.d.menu === false,
    `Agent Swarm abre su panel  [flag ${conFlag ? "v2" : "OFF"}]`, JSON.stringify(s.d));
}

/* ⚠️ EL FLAG NO PARTE ESTE COMPORTAMIENTO, Y ÉSA ES LA NOVEDAD. El handler dejó de vivir en
   la piel y vive en `Composer.tsx`, así que la frase se escribe con el frame puesto y con el
   frame apagado. El arco viejo pedía que SIN flag saliera el turno —eso probaba que el puente
   era lo que cambiaba—; hoy exigiría lo contrario de lo que el dueño autorizó. Se mide que
   los dos caminos coincidan, que es la afirmación fuerte: no hay una piel escondiendo nada. */
console.log("\nC · los dos de tool — DEJAN LA FRASE y no mandan turno, con flag y sin flag");
for (const [idx, id] of [[2, "check"], [3, "portfolio"]]) {
  for (const conFlag of [true, false]) {
    const r = await correr(puerto++, idx, conFlag);
    const et = conFlag ? "v2" : "OFF";
    ok(r.piel === (conFlag ? "v2" : ""), `[${id}] el flag quedó en ${et}`, r.piel);
    ok(r.d && r.d.val === FRASES[id], `[${id}] la frase quedó ENTERA en el composer  [${et}]`,
      JSON.stringify((r.d && r.d.val || "").slice(0, 60)));
    ok(r.d && r.d.fetch === 0, `[${id}] NO salió el turno (cero fetch)  [${et}]`, `hubo ${r.d && r.d.fetch}`);
    ok(r.d && r.d.menu === false, `[${id}] el menú se cerró igual  [${et}]`);
  }
}

/* E · EL CONTROL POSITIVO. Sin esto, «cero fetch» pasaría igual con el contador roto: la
   vara no podría distinguir «no salió el turno» de «no sé mirar la red». */
console.log("\nE · control positivo — escribir a mano y enviar TIENE que producir un turno");
const env = await correr(puerto++, -1, true);
ok(env.d && env.d.fetch > 0, "el instrumento ve un turno cuando de verdad hay uno", `hubo ${env.d && env.d.fetch}`);

console.log(`\n${fallas === 0 ? "✓ VERDE" : "✗ ROJO"} — ${pasos - fallas}/${pasos} pasos`);
process.exit(fallas === 0 ? 0 : 1);
