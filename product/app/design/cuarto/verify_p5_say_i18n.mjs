/* verify_p5_say_i18n.mjs — FIX-P5 · i18n de TODA la superficie de say().
 *
 * EL BUG: `say()` escribe HTML con el nombre de la pieza en <b>. El navegador parte eso en
 * varios NODOS DE TEXTO y la capa TM indexa POR NODO — así que la frase le llega hecha
 * pedacitos ("sumé", "con", "zona", "— no se ejecutó") que no son claves del diccionario.
 * Bajo EN, el mensaje se quedaba en español. Medido antes del fix: 7 de 58 fragmentos
 * traducían; 51 no.
 *
 * POR QUÉ NO SE ARREGLÓ METIENDO LOS PEDACITOS EN EL TM GLOBAL: el TM se aplica a TODO nodo
 * de texto de la app. "zona", "pieza", "con", "abre" como claves globales traducirían texto
 * suelto de cualquier otra pantalla. El fix es un diccionario de ALCANCE ACOTADO (#status),
 * vía AlephI18n.trWith.
 *
 * LO QUE SE MIDE — las 104 llamadas a say() se extraen DEL FUENTE (no una lista escrita a
 * mano, que se desactualiza en silencio) y se renderizan por el say() REAL:
 *   (1) censo: cuántas llamadas y cuántos fragmentos de nodo de texto hay
 *   (2) COBERTURA: cada fragmento tiene clave o regla — cero fragmentos huérfanos
 *   (3) RESIDUO: renderizado en EN, cero español en #status  ← el assert que importa
 *   (4) ES intacto: en español el mensaje es exactamente el del fuente (no se rompió nada)
 *   (5) LOCKSTEP: todo mensaje con contenido traducible cambia entre ES y EN
 *   (6) el diccionario acotado NO se filtra al TM global (una "zona" suelta sigue en español)
 *   (7) 0 errores JS
 *
 * Puerto :8275. Run: node verify_p5_say_i18n.mjs
 */
import { chromium, webkit } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PAGE_SRC = join(HERE, "cuarto.pixi.html");
// El puerto es de la SESIÓN, no de la vara: cada integración corre en el suyo (:25374 es la
// .app de persona usuaria y jamás se toca). 8275 queda de default por compatibilidad con P5.
const PORT = Number(process.env.PORT || 8275);
if (PORT === 25374) { console.error("✗ :25374 es la .app de persona usuaria — jamás."); process.exit(2); }
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
let motor = "";
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${extra ? "  · " + extra : ""}`); if (!c) fails.push(`${motor} · ${label}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Palabras que DELATAN español sin ambigüedad. Se evitan las que son iguales en inglés
 *  ("total", "chat", "no") y los nombres propios. Si una de éstas sobrevive en EN, hay hueco. */
const ES_RESIDUO = /\b(sumé|equipé|quité|propuse|propongo|colocaste|cancelaste|desacoplaste|rehidraté|guardado|corrió|abro|abre|suelta|zona|pieza|piezas|hueco|llave|cuenta|catálogo|Cuarto|Núcleo|ejecutó|quedó|retenida|listo|puesto|modelo|receta|conexión|credencial|forjé|forjar|reintenta|encontré|pude|está|desde|donde|dejaste|posición|activa|activas|reales|sigue|clickea|confirma|espera|vuelve|toca|entra|adentro|ahora|nada|ciegas|crearía|ciclo|contiene|coloqué|indirectamente|directa|agente|arma|guarda|mundo|hondo|niveles|delegación|archivo|elige|pega|texto|borrado|vacié|mismo|otro)\b/i;

/** Extrae el literal de cada say( del FUENTE — el censo se saca del código, no de una lista
 *  escrita a mano. Cubre las DOS formas: plantilla `…${}…` y literal con comillas "…"/'…'
 *  (la vara destapó 9 say("…") en español que un extractor sólo-plantillas no veía). */
function literales(src) {
  const out = [];
  const re = /\bsay\(/g; let m;
  while ((m = re.exec(src))) {
    let i = m.index + m[0].length;
    while (i < src.length && /\s/.test(src[i])) i++;
    const q = src[i];
    if (q !== "`" && q !== '"' && q !== "'") continue;    // say(variable) → no hay literal que auditar
    let j = i + 1, depth = 0, buf = "";
    while (j < src.length) {
      const c = src[j];
      if (c === "\\") { buf += c + src[j + 1]; j += 2; continue; }
      if (q === "`" && c === "$" && src[j + 1] === "{") { depth++; buf += "${"; j += 2; continue; }
      if (depth > 0) { if (c === "{") depth++; if (c === "}") { depth--; buf += "}"; j++; continue; } buf += c; j++; continue; }
      if (c === q) break;
      buf += c; j++;
    }
    out.push({ line: src.slice(0, m.index).split("\n").length, tpl: buf });
  }
  return out;
}

/** Instancia una plantilla con valores realistas. Heurística medida contra el fuente: si el
 *  ${} viene pegado a una letra es un sufijo de plural (`pieza${n===1?"":"s"}`) → "s";
 *  si no, es un valor con nombre propio → "Freecad". */
function instanciar(tpl) {
  let out = "", i = 0;
  while (i < tpl.length) {
    if (tpl[i] === "$" && tpl[i + 1] === "{") {
      let d = 1, j = i + 2;
      while (j < tpl.length && d > 0) { if (tpl[j] === "{") d++; if (tpl[j] === "}") d--; j++; }
      // Si la expresión trae un FALLBACK en español (`x || "el catálogo"`), se inyecta ESE —
      // el español también viaja dentro de los valores, no sólo en los fragmentos literales.
      // Sin esto la vara era ciega a toda una clase (lo destapó una captura de pantalla).
      const expr = tpl.slice(i + 2, j - 1);
      const fb = /\|\|\s*["']([a-záéíóúñ][^"']{2,40})["']/.exec(expr);
      const prev = out.slice(-1);
      out += fb ? fb[1] : (/[A-Za-zÁÉÍÓÚÑáéíóúñ]/.test(prev) ? "s" : "«V»");
      i = j; continue;
    }
    out += tpl[i]; i++;
  }
  return out;
}

const SRC = readFileSync(PAGE_SRC, "utf8");
const TPLS = literales(SRC);
const MENSAJES = [...new Map(TPLS.map((t) => [instanciar(t.tpl), t.line])).entries()]
  .map(([html, line]) => ({ html, line }));

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(800);
// GUARDA DE PUERTO: :8275 no se libera al instante entre varas (la anterior deja el socket
// colgando) y el http.server nuevo falla al bindear EN SILENCIO → la página carga vacía y la
// vara da ROJO por un motivo que no es el producto. Se espera a que SIRVA de verdad, y si no
// sirve se dice, en vez de medir la nada.
{
  let vivo = false;
  for (let i = 0; i < 25 && !vivo; i++) {
    try { const r = await fetch(PAGE, { method: "GET" }); vivo = r.ok; } catch (e) {}
    if (!vivo) await sleep(400);
  }
  if (!vivo) { console.error(`FALTA: :${PORT} no sirve ${PAGE} — ¿otra vara todavía lo tiene?`); server.kill(); process.exit(2); }
}
const ENGINES = [["webkit", webkit], ["chromium", chromium]];
for (const [_motor, tipo] of ENGINES) {
motor = _motor;
console.log(`\n──────── motor: ${motor} ────────`);
const browser = await tipo.launch();
try {
  const errors = [];
  const abrir = async (lang) => {
    const ctx = await browser.newContext({ viewport: { width: 1300, height: 860 } });
    await ctx.addInitScript((L) => { try { localStorage.setItem("aleph-lang", L); localStorage.setItem("aleph-theme", "dark"); } catch (e) {} }, lang);
    const page = await ctx.newPage();
    page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => window.__sayTM && window.AlephI18n, null, { timeout: 15000 });
    await sleep(600);
    return page;
  };

  // ── (1) CENSO desde el fuente ──
  ok(TPLS.length >= 70 && MENSAJES.length >= 60, "(1) censo de say() extraído del fuente (plantilla + comillas)",
     `${TPLS.length} llamadas · ${MENSAJES.length} mensajes únicos`);

  const en = await abrir("en");

  // ── (2) COBERTURA: cero fragmentos de nodo de texto sin clave ni regla ──
  await en.evaluate((src) => { window.__ES_RESIDUO_SRC = src; }, ES_RESIDUO.source);
  const cov = await en.evaluate((msgs) => {
    const { dict, rules } = window.__sayTM;
    const host = document.createElement("div"); document.body.appendChild(host);
    // GOTCHA: la sonda del TM global va en OTRO host. Appendear al mismo árbol que recorre el
    // TreeWalker lo hace walkearse a sí mismo → loop infinito (WebKit se comió 3 GB midiendo esto).
    const probe = document.createElement("div"); document.body.appendChild(probe);
    const huerfanos = [];
    const ES = new RegExp(window.__ES_RESIDUO_SRC, "i");   // "contiene español" = hay algo que traducir
    const PUNT = /^[\s·—:,.()\/<>✓↻⌂]*$/;              // puntuación pura: nada que traducir
    msgs.forEach((m) => {
      host.innerHTML = m.html;
      const w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, null); let n;
      while ((n = w.nextNode())) {
        const k = String(n.nodeValue).trim().replace(/\s+/g, " ");
        if (!k || PUNT.test(k)) continue;
        const sinValor = k.replace(/«V»/g, "").replace(/\s+/g, " ").trim();
        if (!sinValor || PUNT.test(sinValor)) continue;              // sólo el valor inyectado
        const tieneClave = Object.prototype.hasOwnProperty.call(dict, k);
        const tieneRegla = rules.some((r) => r.re.test(k));
        // el TM GLOBAL ya cubre varias frases ENTERAS de say(); eso también es cobertura.
        const p2 = document.createElement("p"); p2.textContent = k; probe.appendChild(p2);
        window.AlephI18n.tr(p2);
        const global = p2.textContent !== k;
        if (!tieneClave && !tieneRegla && !global && ES.test(k)) huerfanos.push({ k, line: m.line });
      }
    });
    host.remove(); probe.remove();
    return huerfanos;
  }, MENSAJES);
  ok(cov.length === 0, "(2) COBERTURA · cero fragmentos huérfanos",
     cov.length ? JSON.stringify(cov.slice(0, 6)) : `todos los fragmentos con clave o regla`);

  // ── (3) RESIDUO · renderizado por el say() REAL en EN, cero español ──
  // se usa el say() REAL y se espera un tick: la capa TM global corre por MutationObserver
  // (asíncrono). Sin la espera se mediría sólo el diccionario acotado y las frases enteras
  // que ya cubría el TM global saldrían como falso rojo.
  // GOTCHA: la propia página llama say() de forma asíncrona (fetch que resuelve) y PISA
  // #status a mitad del barrido — se leería el mensaje de otro. Se detecta comparando el
  // ESQUELETO DE TAGS: traducir sólo cambia nodos de texto, nunca la estructura; si el
  // esqueleto cambió, escribió alguien más y se reintenta.
  await en.addScriptTag({ content: `window.__esqueleto = (h) => String(h).replace(/>[^<]*</g, "><").trim();
    window.__leerSay = async (html) => {
      const el = document.getElementById("status");
      for (let i = 0; i < 4; i++) {
        el.innerHTML = html; window.__say(html);
        const mio = window.__esqueleto(el.innerHTML);
        await new Promise((r) => setTimeout(r, 0));
        if (window.__esqueleto(el.innerHTML) === mio) return el.textContent.replace(/\\s+/g, " ").trim();
      }
      return el.textContent.replace(/\\s+/g, " ").trim();
    };` });
  const render = await en.evaluate(async (msgs) => {
    const out = [];
    for (const m of msgs) out.push({ line: m.line, txt: await window.__leerSay(m.html) });
    return out;
  }, MENSAJES);
  const conEspanol = render.filter((r) => ES_RESIDUO.test(r.txt));
  ok(conEspanol.length === 0, "(3) RESIDUO · cero español en #status bajo EN",
     conEspanol.length ? JSON.stringify(conEspanol.slice(0, 5)) : `${render.length} mensajes limpios`);

  // ── (4)+(5) ES intacto y LOCKSTEP ──
  const es = await abrir("es");
  await es.addScriptTag({ content: `window.__esqueleto = (h) => String(h).replace(/>[^<]*</g, "><").trim();
    window.__leerSay = async (html) => {
      const el = document.getElementById("status");
      for (let i = 0; i < 4; i++) {
        el.innerHTML = html; window.__say(html);
        const mio = window.__esqueleto(el.innerHTML);
        await new Promise((r) => setTimeout(r, 0));
        if (window.__esqueleto(el.innerHTML) === mio) return el.textContent.replace(/\\s+/g, " ").trim();
      }
      return el.textContent.replace(/\\s+/g, " ").trim();
    };` });
  const renderEs = await es.evaluate(async (msgs) => {
    const out = [];
    for (const m of msgs) out.push({ line: m.line, txt: await window.__leerSay(m.html) });
    return out;
  }, MENSAJES);
  const esperado = await es.evaluate((msgs) => msgs.map((m) => {
    const d = document.createElement("div"); d.innerHTML = m.html;
    return d.textContent.replace(/\s+/g, " ").trim();
  }), MENSAJES);
  const rotos = renderEs.filter((r, i) => r.txt !== esperado[i]);
  ok(rotos.length === 0, "(4) ES intacto · el mensaje es exactamente el del fuente",
     rotos.length ? JSON.stringify(rotos.slice(0, 3)) : `${renderEs.length} mensajes sin tocar`);

  // NEUTROS: mensajes que en EN se escriben IGUAL que en ES — no hay nada que traducir. Se
  // declaran uno por uno a propósito: una heurística acá escondería huecos reales.
  const NEUTRO = [/^chat · /];
  const traducible = (t) => {
    const crudo = String(t).trim();
    if (NEUTRO.some((re) => re.test(crudo))) return false;   // se testea CRUDO: quitar «V» primero
    const limpio = crudo.replace(/«V»/g, "").trim();          // rompía el ancla del patrón
    return /[a-záéíóúñ]{3}/i.test(limpio.replace(/[·—:,.()\/<>✓↻⌂\s]/g, ""));
  };
  const sinCambio = render.filter((r, i) => r.txt === renderEs[i].txt).filter((r) => traducible(r.txt));
  ok(sinCambio.length === 0, "(5) LOCKSTEP · todo mensaje traducible cambia entre ES y EN",
     sinCambio.length ? JSON.stringify(sinCambio.slice(0, 5)) : `${render.length} mensajes en lockstep`);

  // ── (6) el diccionario acotado NO se filtra al TM global ──
  const fuga = await en.evaluate(() => {
    const d = document.createElement("div");
    d.innerHTML = '<p>zona</p><p>pieza</p><p>con</p><p>abre</p>';
    document.body.appendChild(d);
    window.AlephI18n.tr(d);                                   // el TM GLOBAL, no el de say()
    const out = [...d.querySelectorAll("p")].map((p) => p.textContent);
    d.remove(); return out;
  });
  ok(JSON.stringify(fuga) === JSON.stringify(["zona", "pieza", "con", "abre"]),
     "(6) el vocabulario de say() NO contamina el TM global", JSON.stringify(fuga));

  ok(errors.length === 0, "(7) 0 errores JS", errors.slice(0, 2).join(" ; "));

  await en.evaluate(() => { const el = document.getElementById("status");
    el.innerHTML = 'sumé <b>Freecad</b> desde el catálogo — ya está en El Cuarto';
    window.AlephI18n.trWith(el, window.__sayTM.dict, window.__sayTM.rules); });
  await sleep(150);
  await en.screenshot({ path: join(HERE, "screenshots", `p5-say-en-${motor}.png`) });
} catch (e) {
  console.error("HARNESS ERROR:", e); fails.push(`${motor} · harness: ${e && e.message ? e.message : String(e)}`);
} finally { await browser.close(); }
}
server.kill();

console.log("");
if (fails.length === 0) { console.log("RESULTADO: VERDE — say() traducido en toda su superficie (cobertura total · cero residuo ES · ES intacto · lockstep · sin fuga al TM global)"); process.exit(0); }
console.log(`RESULTADO: ROJO (${fails.length})`); fails.forEach((f) => console.log(" - " + f)); process.exit(1);
