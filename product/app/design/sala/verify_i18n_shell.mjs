/* verify_i18n_shell.mjs — DONE-BAR i18n del SHELL de la Sala (ES + EN, no self-report).
 *
 * Estático y honesto: sirve product/app/design/ por http efímero (listen(0); la raíz
 * DEBE ser design/ para que ../i18n.js resuelva) y monta sala/sala.html DOS veces
 * (ES default · EN vía localStorage aleph-lang antes de cargar). Endurece el verde:
 *   · PARIDAD de diccionario: claves sala.* extraídas del i18n.js REAL — set ES == set EN
 *   · COBERTURA: toda clave usada por sala.html (data-i18n* y trS) existe en el DICT
 *   · cada clave sala.* resuelve en ambos idiomas (t(k) !== k, probado en el browser)
 *   · DOM ES/EN: chrome traducido de verdad (título, Biblioteca/Library, estados, placeholder, tooltips)
 *   · ANTI-LEAK EN (patrón ccd26bb): cero ES visible — acentos/¿¡ + lista de palabras —
 *     excluyendo #alephGreet (ciclo multilingüe intencional; en EN debe ARRANCAR en inglés)
 *   · anti-claves-crudas: ningún "sala.x.y" literal visible en ninguno de los dos idiomas
 * Salida JSON + screenshots shell-es.png / shell-en.png + exit code. Uso: node verify_i18n_shell.mjs */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { chromium } from "playwright";

const DIR = dirname(fileURLToPath(import.meta.url));          // …/sala
/* [H2 · deuda de la Fase 1, cerrada acá] `screenshots/shell-{es,en}.png` están COMMITEADOS
 * y esta vara los reescribía en cada corrida. La Fase 1 no lo vio porque su regresión no
 * corría esta vara — el mismo error de método de siempre: lo que no se corre, no se mide.
 * La captura es evidencia de la corrida → temporal; pisar la del árbol es explícito. */
const CAPTURAS = process.argv.includes("--capturas-al-arbol")
  ? join(DIR, "screenshots") : tmpdir();
const ROOT = resolve(DIR, "..");                              // …/design
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png" };

const result = { ok: false, fails: [] };
const fail = (name, detail) => result.fails.push(name + (detail ? " → " + detail : ""));

// ── 1) paridad + cobertura de claves (contra los archivos REALES, no una lista a mano) ──
const i18nSrc = await readFile(join(ROOT, "i18n.js"), "utf8");
const salaSrc = await readFile(join(DIR, "sala.html"), "utf8");
const grab = (src, re) => { const out = new Set(); let m; while ((m = re.exec(src))) out.add(m[1]); return out; };
const esBlock = i18nSrc.slice(i18nSrc.indexOf("es: {"), i18nSrc.indexOf("en: {"));
const enBlock = i18nSrc.slice(i18nSrc.indexOf("en: {"));
const dictEs = grab(esBlock, /"(sala\.[a-z0-9_.]+)":/g);
const dictEn = grab(enBlock, /"(sala\.[a-z0-9_.]+)":/g);
const usedHtml = grab(salaSrc, /data-i18n(?:-title|-ph)?="(sala\.[a-z0-9_.]+)"/g);
const usedJs = grab(salaSrc, /trS\('(sala\.[a-z0-9_.]+)'/g);
const used = new Set([...usedHtml, ...usedJs]);
result.keys = { dictEs: dictEs.size, dictEn: dictEn.size, used: used.size };
for (const k of dictEs) if (!dictEn.has(k)) fail("clave sin EN", k);
for (const k of dictEn) if (!dictEs.has(k)) fail("clave sin ES", k);
for (const k of used) if (!dictEs.has(k)) fail("clave usada sin entrada en DICT", k);
if (!dictEs.size) fail("cero claves sala.* en i18n.js");
if (used.size < 80) fail("sala.html usa menos claves de las esperadas", String(used.size));

// ── 2) server efímero + browser ──
const server = createServer(async (req, res) => {
  try {
    const p = decodeURIComponent(req.url.split("?")[0]);
    const file = resolve(join(ROOT, p));
    if (!file.startsWith(ROOT)) throw new Error("fuera de raíz");
    const buf = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
    res.end(buf);
  } catch { res.writeHead(404); res.end("nope"); }
});
await new Promise((r) => server.listen(0, r));
const URL_SALA = `http://localhost:${server.address().port}/sala/sala.html`;
const browser = await chromium.launch();
const KEYS = [...dictEs];

async function shoot(lang) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  if (lang !== "es") await page.addInitScript((l) => localStorage.setItem("aleph-lang", l), lang);
  await page.goto(URL_SALA, { waitUntil: "load" });
  await page.waitForTimeout(700); // apply() de data-i18n corre en DOMContentLoaded
  const st = await page.evaluate((keys) => {
    const txt = (sel) => (document.querySelector(sel) || {}).textContent || "";
    const greet = document.getElementById("alephGreet");
    const greetFirst = greet && greet.querySelector(".g") ? greet.querySelector(".g").textContent : "";
    let body = document.body.innerText || "";
    if (greet) body = body.replace(greet.innerText || "", "");
    const unresolved = keys.filter((k) => { const v = window.t ? window.t(k) : k; return !v || v === k; });
    return {
      title: document.title,
      libH: txt(".lib-h"), libEmpty: txt(".lib-empty"), agentSub: txt("#agentSub"),
      canvasSub: txt("#canvasSub"), placeholder: (document.getElementById("composer") || {}).placeholder || "",
      atTitle: (document.getElementById("atBtn") || {}).title || "",
      shareBtn: txt("#shareBtn"), greetFirst, body, unresolved: unresolved.slice(0, 8),
      rawKeys: (body.match(/\bsala\.[a-z0-9_]+(?:\.[a-z0-9_]+)+\b/gi) || []).slice(0, 5),
    };
  }, KEYS);
  await page.screenshot({ path: join(CAPTURAS, `shell-${lang}.png`), fullPage: true });
  await ctx.close();
  return { st, errors: errors.filter((t) => !/favicon/i.test(t)) };
}

try {
  // ── ES (default) ──
  const es = await shoot("es");
  result.es = { ...es.st, body: undefined };
  if (es.st.title !== "Sala de uso · Aleph") fail("ES: título", es.st.title);
  if (es.st.libH !== "Biblioteca") fail("ES: lib-h", es.st.libH);
  if (es.st.agentSub !== "listo para una tarea") fail("ES: agentSub", es.st.agentSub);
  if (!/^Asígnale una tarea/.test(es.st.placeholder)) fail("ES: placeholder", es.st.placeholder);
  if (es.st.unresolved.length) fail("ES: claves sin resolver", es.st.unresolved.join(","));
  if (es.st.rawKeys.length) fail("ES: claves crudas visibles", es.st.rawKeys.join(","));
  if (es.errors.length) fail("ES: errores de consola", es.errors[0]);

  // ── EN ──
  const en = await shoot("en");
  result.en = { ...en.st, body: undefined };
  if (en.st.title !== "Workroom · Aleph") fail("EN: título", en.st.title);
  if (en.st.libH !== "Library") fail("EN: lib-h", en.st.libH);
  if (!/^Nothing here yet/.test(en.st.libEmpty)) fail("EN: lib vacío", en.st.libEmpty);
  if (en.st.agentSub !== "ready for a task") fail("EN: agentSub", en.st.agentSub);
  if (en.st.canvasSub !== "what your agent produces, here") fail("EN: canvasSub", en.st.canvasSub);
  if (!/^Give it a task/.test(en.st.placeholder)) fail("EN: placeholder", en.st.placeholder);
  if (en.st.atTitle !== "Attach your files and connectors (@)") fail("EN: tooltip @", en.st.atTitle);
  if (!/My screen/.test(en.st.shareBtn)) fail("EN: shareBtn", en.st.shareBtn);
  if (!/^(Good morning|Good afternoon|Good evening)$/.test(en.st.greetFirst)) fail("EN: greet no arranca en inglés", en.st.greetFirst);
  if (en.st.unresolved.length) fail("EN: claves sin resolver", en.st.unresolved.join(","));
  if (en.st.rawKeys.length) fail("EN: claves crudas visibles", en.st.rawKeys.join(","));
  // ANTI-LEAK: cero ES visible en EN (acentos/¿¡ + palabras ES; greet ya excluido)
  const accents = en.st.body.match(/[áéíóúñÁÉÍÓÚÑ¿¡]/g) || [];
  if (accents.length) fail("EN: caracteres ES visibles", JSON.stringify(accents.slice(0, 8)) + " en: " + en.st.body.split("\n").filter((l) => /[áéíóúñÁÉÍÓÚÑ¿¡]/.test(l)).slice(0, 3).join(" | "));
  const esWords = en.st.body.match(/\b(obra|tarea|agente|Biblioteca|archivo|pantalla|armando|Enviar|Descargar|Revertir|Cargando|conectar)\b/g) || [];
  if (esWords.length) fail("EN: palabras ES visibles", esWords.slice(0, 8).join(","));
  if (en.errors.length) fail("EN: errores de consola", en.errors[0]);
} catch (e) {
  fail("excepción", String(e));
}

result.pass = result.fails.length === 0;
console.log(JSON.stringify(result, null, 2));
await browser.close();
server.close();
process.exit(result.pass ? 0 : 1);
