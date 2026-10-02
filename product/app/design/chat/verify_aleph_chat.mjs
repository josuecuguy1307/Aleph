/* verify_aleph_chat.mjs — LA VARA DE LA CAPA COMPARTIDA (aleph-chat.js).
 *
 * WebKit real (mismo motor que WKWebView / la .app Tauri) contra un estático sobre design/,
 * con TODO request no-local ABORTADO: si la capa filtra una llamada externa, se ve acá.
 * No necesita backend — ejercita la capa, no el motor (eso lo cubre verify_sala_deepchat).
 *
 *   node product/app/design/chat/verify_aleph_chat.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = fileURLToPath(new URL("../", import.meta.url));
const SMOKE = fileURLToPath(new URL("./fixtures/verify_page.html", import.meta.url));
const PORT = 8244;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png" };

const srv = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  try {
    const p = u.pathname === "/" ? SMOKE : join(DESIGN, decodeURIComponent(u.pathname).replace(/^\//, ""));
    const b = await readFile(p);
    res.writeHead(200, { "Content-Type": MIME[extname(p)] || "application/octet-stream" });
    res.end(b);
  } catch { res.writeHead(404); res.end("nf"); }
});
await new Promise((r) => srv.listen(PORT, "127.0.0.1", r));

const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  — " + x : ""}`); if (!c) fails.push(l); };

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
const external = [];
await page.route("**/*", (route) => {
  const u = route.request().url();
  if (!/^http:\/\/127\.0\.0\.1:8244/.test(u) && !u.startsWith("data:") && !u.startsWith("blob:")) { external.push(u); return route.abort(); }
  route.continue();
});
await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 20000 }).catch(() => {});

// 1 · el componente montó con shadow root
const base = await page.evaluate(() => {
  const el = document.querySelector("deep-chat");
  return { has: !!el, shadow: !!(el && el.shadowRoot), font: el && el.getAttribute("style") };
});
ok(base.has && base.shadow, "deep-chat monta con Shadow DOM en WebKit");
ok(/font-family/.test(base.font || ""), "font-family inline presente (apaga Google Fonts)", base.font);
ok(external.length === 0, "CERO requests externos", external.join(" · ") || "ninguno");
ok(await page.evaluate(() => window.__alephChatLocalFirst && window.__alephChatLocalFirst.ok === true), "assertLocalFirst() = ok");

// 2 · el input es container-relative y usable
await page.waitForFunction(() => {
  const el = document.querySelector("deep-chat");
  return !!(el && el.shadowRoot && el.shadowRoot.querySelector("#text-input"));
}, null, { timeout: 15000 });
const inp = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const ti = sr.querySelector("#text-input");
  const r = ti && ti.getBoundingClientRect();
  return { w: r ? Math.round(r.width) : null, editable: ti && ti.getAttribute("contenteditable") };
});
ok(inp.w >= 140, `el input mide ${inp.w}px en un contenedor de 360px`);
ok(inp.editable === "true", "el input es editable");

// 3 · escribir + enviar → llega el turno + streaming incremental
await page.click("deep-chat >> #text-input").catch(async () => {
  await page.evaluate(() => document.querySelector("deep-chat").shadowRoot.querySelector("#text-input").focus());
});
await page.keyboard.type("hola sala", { delay: 10 });
const typed = await page.evaluate(() => document.querySelector("deep-chat").shadowRoot.querySelector("#text-input").textContent);
ok(typed.includes("hola sala"), "acepta teclado real", JSON.stringify(typed));

// "pensando…" debe aparecer al instante del envío
await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  sr.querySelector("#submit-icon").parentElement.click();
});
await page.waitForTimeout(40);
const vitalsSeen = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const v = sr.querySelector(".ac-vitals");
  return v ? v.textContent.trim() : null;
});
ok(!!vitalsSeen && /pensando/i.test(vitalsSeen), "«pensando…» aparece desde el instante del envío", JSON.stringify(vitalsSeen));

const turn = await page.evaluate(() => window.__turn);
ok(turn && turn.text === "hola sala", "el turno llega a onSubmit con el texto", JSON.stringify(turn && turn.text));

// streaming: muestreo del largo
const lens = [];
for (let i = 0; i < 14; i++) {
  await page.waitForTimeout(45);
  lens.push(await page.evaluate(() => {
    const sr = document.querySelector("deep-chat").shadowRoot;
    const ms = sr.querySelectorAll(".ai-message-text, .message-bubble");
    return ms.length ? (ms[ms.length - 1].textContent || "").length : 0;
  }));
}
const grew = lens.some((v, i) => i > 0 && v > lens[i - 1]);
ok(grew, "streaming INCREMENTAL visible", lens.join("→"));
await page.waitForTimeout(400);
const finalTxt = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  return (sr.querySelector("#messages").textContent || "");
});
ok(/llega en chunks/.test(finalTxt), "el texto completo llegó", JSON.stringify(finalTxt.slice(-60)));
ok(!(await page.evaluate(() => !!document.querySelector("deep-chat").shadowRoot.querySelector('.ac-vitals[data-live="1"]'))), "los signos vitales se apagan al llegar la respuesta");

// 3b · opciones por default presentes desde el arranque
const sugs = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  return [...sr.querySelectorAll(".ac-sug")].map((b) => b.textContent);
});
ok(sugs.length >= 2, "opciones por default al entrar (no un campo vacío mudo)", sugs.join(" / "));

// 4 · card de ACCIÓN (tool_call) con logo
await page.evaluate(() => window.__action());
const act = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const a = sr.querySelector(".ac-act");
  return a ? { txt: a.textContent.trim(), face: !!a.querySelector(".ac-face") } : null;
});
ok(!!act && /Leyendo tu correo/.test(act.txt), "tool_call se ve como card de ACCIÓN", act && act.txt);
ok(!!act && act.face, "la card trae el logo real del servicio");
ok(!/<function/.test(finalTxt) && !/&lt;function/.test(finalTxt), "cero <function=…> crudo");

// 5 · errcard con causa tipada + [Reintentar] que dispara
await page.evaluate(() => window.__err());
const errInfo = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const d = sr.querySelector(".errcard");
  return d ? { causa: d.dataset.causa, botones: [...d.querySelectorAll(".acts button")].map((b) => b.textContent), auto: !!d.querySelector(".ac-auto") } : null;
});
ok(!!errInfo && errInfo.causa === "cli_no_logueado", "errcard con causa TIPADA", errInfo && errInfo.causa);
ok(!!errInfo && errInfo.botones.length >= 2, "la errcard trae camino (botones)", errInfo && errInfo.botones.join(" / "));
ok(!!errInfo && errInfo.auto, "declara el reintento automático");
await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  sr.querySelectorAll(".errcard .acts button")[0].click();
});
await page.waitForTimeout(120);
ok(await page.evaluate(() => window.__retried === true), "el [Reintentar] DISPARA el handler (htmlClassUtilities)");

// 6 · oferta contextual
await page.evaluate(() => window.__offer());
await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  sr.querySelector('.ac-offer[data-offer="vision"] .acts button').click();
});
await page.waitForTimeout(120);
ok(await page.evaluate(() => window.__offered === true), "la oferta contextual ofrece camino clickeable");

// 7 · slot(): nodo REAL con handler imperativo vivo
await page.evaluate(() => window.__slot());
await page.waitForTimeout(120);
const slotOk = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const d = sr.querySelector('.errcard[data-causa="slot_vivo"]');
  if (!d) return { found: false };
  d.querySelector("button").click();
  return { found: true, clicked: window.__slotClicked === true, txt: d.querySelector("button").textContent };
});
ok(slotOk.found, "slot(): el nodo real entra a la conversación");
ok(slotOk.clicked, "slot(): el handler IMPERATIVO sigue vivo tras mudarse al shadow DOM", slotOk.txt);

// 8 · logos inline en prosa + markdown
await page.evaluate(() => window.__say());
await page.waitForTimeout(300);
const said = await page.evaluate(() => {
  const sr = document.querySelector("deep-chat").shadowRoot;
  const md = sr.querySelectorAll(".ac-md");
  const last = md[md.length - 1];
  return last ? { faces: last.querySelectorAll(".ac-svc .ac-face").length, strong: !!last.querySelector("strong,b"), code: !!last.querySelector("code") } : null;
});
ok(!!said && said.faces >= 1, "logo REAL inline cuando la prosa nombra un servicio", said && String(said.faces));
ok(!!said && said.code, "markdown renderizado dentro del shadow (code)");

// 9 · Send apagado-pero-VIVO
await page.evaluate(() => window.__gated(true));
const gatedInfo = await page.evaluate(() => {
  const el = document.querySelector("deep-chat");
  const s = el.shadowRoot.querySelector("#submit-icon");
  const wrap = s.parentElement;
  const cs = getComputedStyle(s);
  return { attr: el.getAttribute("data-gated"), opacity: cs.opacity,
           disabled: wrap.classList.contains("disabled-button") };
});
ok(gatedInfo.attr === "1" && Number(gatedInfo.opacity) < 1, "gated ⇒ el Send se VE apagado", `opacity=${gatedInfo.opacity}`);
ok(gatedInfo.disabled === false, "…pero NO está disabled (el click entra igual)");

ok(errs.length === 0, "cero errores de página", errs.join(" | "));
console.log(`\n══ ${fails.length ? "FALLARON " + fails.length : "TODO VERDE"} ══`);
fails.forEach((f) => console.log("  ✗ " + f));
await browser.close();
srv.close();
process.exit(fails.length ? 1 : 0);
