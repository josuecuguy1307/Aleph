/* verify_sala_deepchat.mjs — LA SALA NUEVA, contra un backend STUB determinista.
 *
 * WebKit real (motor de la .app). Cubre lo que el mandato pide ver funcionando y que NO
 * necesita el motor de verdad: el chrome (chat limpio · obra on-demand · Biblioteca
 * plegada), el composer de deep-chat, streaming incremental, signos vitales, cards de
 * acción con logo, error con [Reintentar], adjunto y logos inline.
 *
 * El backend REAL (sidecar frozen) lo cubre verify_sala_viva.mjs — ésta es la vara del
 * chrome y de la franja de conversación, y corre sin instalar nada.
 *
 *   node product/app/design/sala/verify_sala_deepchat.mjs
 */
import { webkit } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const DESIGN = fileURLToPath(new URL("../", import.meta.url));
const PORT = Number(process.env.VERIFY_PORT || 8242);
const PAGE = `http://127.0.0.1:${PORT}/sala/sala.html`;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
  ".woff2": "font/woff2", ".md": "text/markdown", ".ico": "image/x-icon" };

const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  — " + x : ""}`); if (!c) fails.push(l); };

// ── backend STUB: determinista, sin red, sin sidecar ────────────────────────────────
const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64");
let streamMode = "ok";                       // "ok" | "fail"
const seen = [];
const ragPosts = [];
const json = (res, code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };

const server = http.createServer(async (req, res) => {
  req.on("error", () => {}); res.on("error", () => {});
  const u = new URL(req.url, "http://x");
  const p = u.pathname;
  if (p.startsWith("/v1/") || p === "/health") {
    const chunks = []; for await (const c of req) chunks.push(c);
    const body = Buffer.concat(chunks).toString() || "";
    seen.push(req.method + " " + p);

    if (p === "/v1/brains/status") return json(res, 200, {
      providers: { claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", installed: true } },
      service: { state: "ready", mode: "shared" } });
    if (p === "/v1/icons") return json(res, 200, { known: ["gmail", "stripe", "github"] });
    // PNG 1x1 VÁLIDO: uno truncado dispara el onerror de brandface y el logo degrada a
    // iniciales — daría un rojo que es del stub, no del producto.
    if (p.startsWith("/v1/icons/")) { res.writeHead(200, { "Content-Type": "image/png" }); return res.end(PNG_1x1); }
    if (p === "/v1/classify-turn") return json(res, 200, { turn: "chat" });
    // EL MOTOR DE VERDAD: el chip del cerebro lee de acá, no de un "conectado" declarado.
    if (p === "/v1/motor/estado") return json(res, 200, {
      tipo: "cerebro", ref: "opus", estado: "probado", causa: null,
      evidencia: { detail: "corrió de verdad" }, ts: 1700000000 });
    if (p === "/v1/chats" && req.method === "POST") return json(res, 200, { id: "chat-stub" });
    if (p.startsWith("/v1/chats/")) return json(res, 200, { id: "chat-stub", messages: [] });
    if (p === "/v1/puppets/run/stream") {
      if (streamMode === "fail") return json(res, 401, { detail: { detail: "la key fue rechazada" } });
      res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      const parts = ["Conecté ", "**gmail** ", "y ya ", "puedo ", "leer ", "tu correo."];
      let i = 0;
      const tick = setInterval(() => {
        if (i >= parts.length) {
          clearInterval(tick);
          res.write(`data: ${JSON.stringify({ type: "done", answer: parts.join("") })}\n\n`);
          return res.end();
        }
        res.write(`data: ${JSON.stringify({ type: "token", text: parts[i++] })}\n\n`);
      }, 90);
      return;
    }
    if (p === "/v1/uploads/ingest" || p.startsWith("/v1/uploads")) return json(res, 200, { ok: true, chars: 4210, title: "informe.pdf" });
    // INGESTA REAL de documentos: PDF/Excel/Word entran por acá en base64 y el backend los
    // pasa por markitdown. Se registra el cuerpo para poder AFIRMAR que el PDF llegó entero.
    if (/^\/v1\/users\/[^/]+\/rag\//.test(p) && req.method === "POST") {
      let b = null; try { b = JSON.parse(body); } catch {}
      ragPosts.push({ name: b && b.name, mime: b && b.mime, b64len: (b && b.content_b64 || "").length });
      return json(res, 200, { doc: { name: (b && b.name) || "doc" } });
    }
    return json(res, 200, {});
  }
  try {
    const f = join(DESIGN, decodeURIComponent(p).replace(/^\//, ""));
    const b = await readFile(f);
    res.writeHead(200, { "Content-Type": MIME[extname(f)] || "application/octet-stream" });
    res.end(b);
  } catch { res.writeHead(404); res.end("nf"); }
});
server.on("clientError", (e, s) => { try { s.destroy(); } catch {} });
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

const SESSION = `try{ sessionStorage.setItem("puppet_user", JSON.stringify({id:"u-dc",session_token:"tok-dc",email:"v@aleph"}));
  localStorage.setItem("aleph-active-brain","claude_cli");
  localStorage.setItem("aleph-brain-configuration", JSON.stringify({version:1,mode:"cli",id:"claude_cli",cliModel:""})); }catch(e){}`;

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
const external = [];
await page.route("**/*", (route) => {
  const url = route.request().url();
  if (!url.startsWith(`http://127.0.0.1:${PORT}`) && !url.startsWith("data:") && !url.startsWith("blob:")) {
    external.push(url); return route.abort();
  }
  route.continue();
});
await page.addInitScript(SESSION);
await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForFunction(() => window.__salaChat && window.__salaShadow && window.__salaShadow(), null, { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(2500);

const Q = (sel) => page.evaluate((s) => { const r = window.__salaQ(s); return r ? { txt: (r.textContent || "").trim(), html: r.innerHTML.slice(0, 200) } : null; }, sel);
const N = (sel) => page.evaluate((s) => window.__salaQA(s).length, sel);

console.log("══ VERIFY · LA SALA NUEVA + DEEP CHAT (WebKit → stub determinista) ══\n");

// ── 1 · el chrome: se entra a un chat limpio ─────────────────────────────────────
console.log("── 1 · chat limpio al entrar ──");
ok(await page.evaluate(() => window.__salaArtifactMode() === "0"), "sin artifact, el panel de la obra NO existe");
ok(await page.evaluate(() => !document.querySelector(".canvas-zone").offsetParent), "la zona de la obra no ocupa pantalla");
ok(await page.evaluate(() => window.__salaLibOpen() === false), "la Biblioteca arranca COLAPSADA");
ok(await page.evaluate(() => {
  const s = getComputedStyle(document.getElementById("libPanel"));
  return s.transform !== "none" && s.transform !== "";
}), "…y está fuera de pantalla (plegada tras su logo)");
const hero = await Q(".sala-hero");
ok(!!hero, "la mascota + el saludo están al centro del chat");
ok(!!hero && /Buen|Good|Bon/.test(hero.txt), "el saludo es multilingüe y rota", hero ? JSON.stringify(hero.txt.slice(0, 60)) : "");
ok(await page.evaluate(() => !!document.getElementById("hmenu")), "los botones sueltos viven bajo un logito (⋯)");
ok(await page.evaluate(() => document.getElementById("toolsRow").hidden === true), "＠/🎙/⚡/🛡 arrancan anidados tras ⊕");
ok(external.length === 0, "CERO requests externos", external.join(" · ") || "ninguno");
ok(await page.evaluate(() => window.__alephChatLocalFirst && window.__alephChatLocalFirst.ok === true), "local-first verificado en runtime");

// ── 1b · el chat abre LIMPIO ─────────────────────────────────────────────────────
// [FIX-P7 · aserción INVERTIDA a propósito] Acá se exigían ≥3 chips de arranque. Murieron
// por mandato: mueble fijo al inicio de la pantalla que no nacía de ningún turno. Las
// opciones ahora nacen del CONTENIDO del turno y viajan dentro del mensaje del agente.
const sugs0 = await page.evaluate(() => window.__salaQA(".ac-sug").map((b) => b.textContent));
ok(sugs0.length === 0, "al entrar NO hay chips de arranque: el chat abre limpio", sugs0.join(" / ") || "cero");

// ── 2 · el composer se puede USAR ────────────────────────────────────────────────
console.log("\n── 2 · el composer ──");
const cw = await page.evaluate(() => {
  const i = window.__salaQ("#text-input");
  return i ? Math.round(i.getBoundingClientRect().width) : null;
});
ok(cw >= 140, `el campo de escribir mide ${cw}px`, "el bug viejo lo dejaba en 31px");
await page.click("deep-chat >> #text-input");
await page.keyboard.type("hola sala", { delay: 8 });
ok((await Q("#text-input")).txt === "hola sala", "acepta teclado real");

// ── 3 · signos vitales + streaming ───────────────────────────────────────────────
console.log("\n── 3 · signos vitales + streaming ──");
await page.evaluate(() => window.__salaQ("#submit-icon").parentElement.click());
await page.waitForTimeout(60);
const vit = await Q(".ac-vitals");
ok(!!vit && /pensando|thinking/i.test(vit.txt), "«pensando…» desde el instante del envío", vit ? vit.txt : "no apareció");
const lens = [];
for (let i = 0; i < 12; i++) {
  await page.waitForTimeout(70);
  lens.push(await page.evaluate(() => {
    const m = window.__salaQA(".ai-message-text, .message-bubble");
    return m.length ? (m[m.length - 1].textContent || "").length : 0;
  }));
}
ok(lens.some((v, i) => i > 0 && v > lens[i - 1]), "streaming INCREMENTAL visible", lens.join("→"));
await page.waitForTimeout(1200);
const all = await page.evaluate(() => window.__salaQ("#messages").textContent);
ok(/puedo leer tu correo/.test(all), "la respuesta completa llegó", JSON.stringify(all.slice(-60)));
ok(!/<function|&lt;function/.test(all), "cero <function=…> crudo en la conversación");
ok(await page.evaluate(() => !window.__salaQ('.ac-vitals[data-live="1"]')), "los signos vitales se apagan al responder");
// UN TURNO QUE SALIÓ BIEN NO PUEDE MOSTRAR UN ERROR. deep-chat pinta su propio globo de
// error si el stream se cierra sin un evento válido — mentiría sobre un turno exitoso.
ok(await page.evaluate(() => window.__salaQA(".error-message-text").length === 0),
   "un turno EXITOSO no pinta ningún globo de error",
   String(await page.evaluate(() => window.__salaQA(".error-message-text").length)));
// el globo-placeholder que cierra un turno sin streaming existe para deep-chat, NO para el
// humano: si se viera, sería una burbuja vacía del agente en medio de la conversación.
// La respuesta NO puede escribirse encima de otro mensaje. Pasó: al re-renderizar el globo
// final se buscaba "el último mensaje del agente", y si el globo del stream no existía se
// pisaba el mensaje ANTERIOR con el texto de la respuesta.
// [FIX-P7] El sujeto de esta guardia eran las opciones de arranque, que ya no existen. La
// REGRESIÓN es la misma y sigue viva: ahora el sujeto es el saludo (`.ac-intro`), que es el
// primer mensaje del hilo y el que se pisaba. Si la respuesta lo devora, esto se pone rojo.
ok(await page.evaluate(() => {
     const i = window.__salaQ(".ac-intro");
     return !!i && /Buen|Good|Bon/.test(i.textContent || "");
   }),
   "el saludo SIGUE intacto tras responder (la respuesta no lo pisa)",
   JSON.stringify(await page.evaluate(() => ((window.__salaQ(".ac-intro") || {}).textContent || "").slice(0, 40))));
ok(await page.evaluate(() => !window.__salaQA(".ac-sugs").some((s) => /leer tu correo/.test(s.textContent))),
   "…y ningún chip quedó reescrito con el texto de la respuesta");
ok(await page.evaluate(() => window.__salaQA(".ac-noop").every((n) => {
     const o = n.closest(".outer-message-container");
     return !o || getComputedStyle(o).display === "none";
   })), "el globo-placeholder queda INVISIBLE (no es una burbuja vacía)");
ok(await page.evaluate(() => {
  const i = window.__salaQ("#text-input");
  return i && !i.textContent.trim();
}), "el composer queda libre tras el turno (canal cerrado)");

// ── 4 · logo REAL inline ─────────────────────────────────────────────────────────
console.log("\n── 4 · logos reales ──");
const faces = await N(".ac-md .ac-svc .ac-face img, .ac-md .ac-svc .ac-face");
ok(faces >= 1, "el servicio nombrado en la respuesta trae su logo inline", String(faces));
ok(await page.evaluate(() => {
  const im = window.__salaQ(".ac-svc .ac-face img");
  return !!im && /\/v1\/icons\//.test(im.getAttribute("src") || "");
}), "el logo sale de brandface (/v1/icons/{slug})");

// ── 4b · el chip del cerebro: cara + estado PROBADO (no "conectado" declarado) ────
console.log("\n── 4b · el chip del cerebro ──");
ok(await page.evaluate(() => !!document.querySelector("#agentSub .bface")),
   "el chip del cerebro trae la CARA del proveedor (logo o iniciales+color)");
const sem = await page.evaluate(() => {
  const m = document.querySelector("#brainState .sem-mount");
  const b = m && (m.matches("[data-estado]") ? m : m.querySelector("[data-estado]"));
  return { mount: !!m, txt: m ? m.textContent : "",
           marca: b ? b.getAttribute("data-estado") : null,
           probado: window.__salaBrainProbado || null };
});
ok(sem.mount, "…y el badge del MOTOR DE VERDAD al lado");
ok(sem.probado && sem.probado.estado === "probado",
   "el estado sale del motor (/v1/motor/estado), no de un 'conectado' declarado",
   sem.probado ? sem.probado.estado : "sin lectura");
ok(sem.marca === "probado", "el badge PINTA ese estado (data-estado)", sem.marca + " · " + JSON.stringify(sem.txt.trim().slice(0, 20)));

// ── 4c · ADJUNTO: PDF por el botón de deep-chat → camino de ingesta existente ─────
console.log("\n── 4c · adjunto (PDF → contexto) ──");
{
  // el botón de adjuntar de deep-chat (los 3 caminos comparten el mismo destino)
  const btn = await page.evaluate(() => {
    const b = window.__salaQA(".input-button").find((x) => !x.querySelector("#submit-icon, #stop-icon"));
    if (!b) return null;
    b.setAttribute("data-verify-attach", "1");
    return true;
  });
  ok(!!btn, "el composer tiene botón de adjuntar");
  const PDF = Buffer.from("%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n");
  const [chooser] = await Promise.all([
    page.waitForEvent("filechooser", { timeout: 8000 }).catch(() => null),
    page.evaluate(() => window.__salaQ('[data-verify-attach="1"]').click()),
  ]);
  ok(!!chooser, "el botón abre el selector de archivos real");
  if (chooser) {
    await chooser.setFiles({ name: "informe.pdf", mimeType: "application/pdf", buffer: PDF });
    await page.waitForTimeout(500);
    // el adjunto viaja con el TURNO (deep-chat lo manda como multipart junto al texto)
    await page.click("deep-chat >> #text-input");
    await page.keyboard.type("resumime este pdf", { delay: 6 });
    await page.evaluate(() => window.__salaQ("#submit-icon").parentElement.click());
    await page.waitForTimeout(2500);
  }
  ok(ragPosts.length >= 1, "el PDF LLEGA al camino de ingesta (POST /v1/users/*/rag/*)", JSON.stringify(ragPosts[0] || null));
  ok(!!(ragPosts[0] && ragPosts[0].name === "informe.pdf"), "…con su nombre real");
  ok(!!(ragPosts[0] && ragPosts[0].b64len > 0), "…y su contenido en base64 (markitdown lo convierte server-side)",
     ragPosts[0] ? ragPosts[0].b64len + " chars b64" : "");
  const pill = await page.evaluate(() => [...document.querySelectorAll("#pills .pill b")].map((b) => b.textContent));
  ok(pill.some((x) => /informe\.pdf/.test(x)), "queda enganchado como contexto del run (pill)", pill.join(" / "));
}

// ── 5 · la obra aparece SÓLO al producirla ───────────────────────────────────────
console.log("\n── 5 · la obra on-demand ──");
await page.evaluate(() => {
  // se empuja una obra por el camino real del shell (artCreate + showArtifact)
  window.__salaForceArt && window.__salaForceArt();
});
const artNow = await page.evaluate(() => window.__salaArtifactMode());
ok(artNow === "1", "al haber obra, el panel de la obra APARECE", `data-artifact=${artNow}`);
ok(await page.evaluate(() => !!document.querySelector(".canvas-zone").offsetParent), "…y ocupa su lugar en el layout");
ok(await page.evaluate(() => document.getElementById("libBtn").classList.contains("has")), "el logo de la Biblioteca marca que hay obra (sin abrirse solo)");
ok(await page.evaluate(() => window.__salaLibOpen() === false), "…y la Biblioteca SIGUE colapsada");
await page.click("#libBtn");
await page.waitForTimeout(260);
ok(await page.evaluate(() => window.__salaLibOpen() === true), "se despliega sólo si la piden");
await page.click("#libClose");
await page.waitForTimeout(260);

// ── 6 · error con causa + [Reintentar] ───────────────────────────────────────────
console.log("\n── 6 · error con loop ──");
streamMode = "fail";
await page.click("deep-chat >> #text-input");
await page.keyboard.type("esto falla", { delay: 6 });
await page.evaluate(() => window.__salaQ("#submit-icon").parentElement.click());
await page.waitForTimeout(3000);
const errN = await N(".errcard");
ok(errN >= 1, "sale una card de error", String(errN));
const btns = await page.evaluate(() => window.__salaQA(".errcard .acts button").map((b) => b.textContent.trim()));
ok(btns.some((b) => /Reintentar|Retry/i.test(b)), "la card trae [Reintentar]", btns.join(" / "));
ok(await page.evaluate(() => {
  const i = window.__salaQ("#text-input");
  return i && !i.hasAttribute("disabled");
}), "el composer sigue vivo tras el error");

// ── 7 · oferta CONTEXTUAL: el caso índice de la visión ───────────────────────────
console.log("\n── 7 · oferta contextual (sin modelo de visión) ──");
await page.evaluate(() => window.__salaOfertaVision());
await page.waitForTimeout(400);
const of = await page.evaluate(() => {
  const o = window.__salaQ('.ac-offer[data-offer="vision"]');
  return o ? { txt: o.textContent, botones: [...o.querySelectorAll(".acts button")].map((b) => b.textContent) } : null;
});
ok(!!of, "el «no puedo ver imágenes» trae su oferta ahí mismo");
ok(!!of && of.botones.some((b) => /visi/i.test(b)), "…con [Conectar un modelo de visión]", of ? of.botones.join(" / ") : "");
ok(!!of && /no adivino|visión/i.test(of.txt), "…y dice por qué, sin fingir que puede");

console.log(`\n══ ${fails.length ? "FALLARON " + fails.length : "TODO VERDE"} ══`);
ok(errs.length === 0, "cero errores de página", errs.join(" | "));
fails.forEach((f) => console.log("  ✗ " + f.trim()));
await browser.close();
server.close();
process.exit(fails.length ? 1 : 0);
