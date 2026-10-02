/*
 * verify_mesa_front.mjs — harness FRONT de la Mesa (Playwright, front-only, sin backend).
 *
 * Sirve el front del worktree en un puerto propio y maneja el STORE real (mesa.state.js) con
 * una secuencia de eventos CANÓNICA (la que emite el motor), sin tocar la red. Cubre:
 *   #1 run sintético: el riel y los chips muestran SOLO lo emitido (diff evento↔dibujo).
 *   #2 pregunta temprana: aparece la carta con 2-3 opciones; caso claro → NO aparece (anti-fatiga).
 *   #5 paridad de modos: el toggle Guiado↔Código no altera el estado ni pierde eventos.
 *   #7 cero emoji de OS en la superficie nueva (grep de pictogramas).
 *
 * Puerto propio (8932); jamás :8080/:8091/:8097/:8923. Corre: node verify_mesa_front.mjs
 */
import { chromium } from "playwright";
import { createServer } from "http";
import { readFile, readdir } from "fs/promises";
import { existsSync } from "fs";
import { extname, join } from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";

const __dir = dirname(fileURLToPath(import.meta.url));
const DESIGN = join(__dir, "..");           // product/app/design
const PORT = Number(process.env.MESA_FRONT_PORT || 8932);

let PASS = 0, FAIL = 0;
const check = (name, ok, extra = "") => {
  console.log(`  ${ok ? "✓" : "✗"} ${name}${extra ? " — " + extra : ""}`);
  ok ? PASS++ : FAIL++;
};

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".svg": "image/svg+xml" };

function serve() {
  return new Promise((resolve) => {
    const srv = createServer(async (req, res) => {
      try {
        let p = decodeURIComponent(req.url.split("?")[0]);
        if (p === "/") p = "/cuarto/mesa.html";
        const full = join(DESIGN, p.replace(/^\//, ""));
        if (!existsSync(full)) { res.writeHead(404); res.end("nope"); return; }
        const body = await readFile(full);
        res.writeHead(200, { "Content-Type": MIME[extname(full)] || "application/octet-stream" });
        res.end(body);
      } catch (e) { res.writeHead(500); res.end(String(e)); }
    });
    srv.listen(PORT, "127.0.0.1", () => resolve(srv));
  });
}

// secuencia CANÓNICA de eventos del contrato (la que el motor emite en un run feliz)
const SECUENCIA = [
  ["construccion.creada", { construccion_id: "mc-test", service: "tmdb" }],
  ["sesion.ok", { auth_form: "token_query", key_fingerprint: "sha256:ab…1234", validated_by: "/configuration", validate_status: 200 }],
  ["observando", { url: "http://x", round: 1, new_confirmed: ["/movie/{id}", "/search/movie"] }],
  ["sintetizando", { round: 1, cerebro: "alias:oss" }],
  ["tool.propuesta", { nombre: "get_movie", endpoint: "/movie/{id}", method: "GET", kind: "read", description: "una película por id" }],
  ["tool.propuesta", { nombre: "search_movie", endpoint: "/search/movie", method: "GET", kind: "read", description: "buscar películas" }],
  ["tool.validando", { nombre: "get_movie", round: 1, request: { method: "GET", endpoint: "/movie/{id}" } }],
  ["tool.validada", { nombre: "get_movie", status: 200, verified_by: "200-OK+schema-match", payload: "{...}" }],
  ["tool.validando", { nombre: "search_movie", round: 1, request: { method: "GET", endpoint: "/search/movie" } }],
  ["tool.descartada", { nombre: "search_movie", motivo: "HTTP 404 en /search/movie", clase: "NOT_FOUND", move: "drop" }],
  ["mcp.forjado", { server: "forged-tmdb", belt_ref: "belt-tmdb", tools: ["get_movie"], puppet_id: "pup-1" }],
  ["construccion.cerrada", { ok: true, resultado: { tools_validadas: 1, belt_ref: "belt-tmdb", convergencia: "convergió" } }],
];

async function main() {
  console.log("=".repeat(68));
  console.log("VERIFY · Mesa de Construcción — front (Playwright, front-only)");
  console.log("=".repeat(68));
  const srv = await serve();
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errores = [];
  page.on("pageerror", (e) => errores.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errores.push(m.text()); });

  await page.goto(`http://127.0.0.1:${PORT}/cuarto/mesa.html`, { waitUntil: "networkidle" });
  check("mesa.html carga sin errores de consola", errores.length === 0, errores.slice(0, 2).join(" | "));

  // ── #1 · run sintético (diff evento↔dibujo) ────────────────────────────────
  console.log("[#1] run sintético — el riel y los chips muestran SOLO lo emitido");
  await page.evaluate((seq) => {
    const st = window.__mesa.state;
    for (const [tipo, data] of seq) st._ingerir(tipo, data);
  }, SECUENCIA);
  await page.waitForTimeout(120);

  const railSeq = await page.evaluate(() => {
    return [...document.querySelectorAll(".mc-node")].map((n) => ({
      est: n.dataset.est, clase: [...n.classList].find((c) => c.startsWith("mc-") && c !== "mc-node"),
    }));
  });
  const activaEquipar = railSeq.find((n) => n.est === "equipar");
  check("las 6 estaciones existen en el riel", railSeq.length === 6, railSeq.map((r) => r.est).join(","));
  check("estación 'equipar' quedó lista al cerrar", activaEquipar && (activaEquipar.clase === "mc-lista" || activaEquipar.clase === "mc-activa"), activaEquipar && activaEquipar.clase);

  const chips = await page.evaluate(() => {
    const nodos = [...document.querySelectorAll(".mc-node")].find((n) => n.dataset.est === "armar");
    const tools = nodos ? [...nodos.querySelectorAll(".mc-tool")] : [];
    return {
      total: tools.length,
      ok: tools.filter((t) => t.classList.contains("mc-tool-ok")).length,
      no: tools.filter((t) => t.classList.contains("mc-tool-no")).length,
    };
  });
  // emitimos 2 propuestas, 1 validada, 1 descartada → exactamente eso, cero fabricado
  check("chips de tools = exactamente las emitidas (2 propuestas)", chips.total === 2, JSON.stringify(chips));
  check("1 tool ✓ (validada) y 1 ✗ (descartada), cero teatro", chips.ok === 1 && chips.no === 1, JSON.stringify(chips));

  // el store guardó SOLO los eventos que le mandamos (más los meta) — diff exacto
  const nEventos = await page.evaluate(() => window.__mesa.state.eventos.length);
  check("el store no fabricó eventos (diff exacto)", nEventos === SECUENCIA.length, `${nEventos} vs ${SECUENCIA.length}`);

  // ── #2 · pregunta temprana (ambos sentidos) ────────────────────────────────
  console.log("[#2] pregunta temprana — aparece con opciones; caso claro NO aparece");
  await page.evaluate(() => window.__mesa.state.reset && (window.__mesa.state.eventos = []));
  await page.reload({ waitUntil: "networkidle" });
  await page.evaluate(() => {
    const st = window.__mesa.state;
    st._ingerir("construccion.creada", { construccion_id: "mc-q" });
    st._ingerir("pregunta.pendiente", { pregunta_id: "mc-q:P3", estacion: "entrar", codigo: "P3",
      pregunta: "¿Cómo se entra a este servicio?",
      opciones: [
        { id: "token", label: "Con una clave", detalle: "te la pido por su canal", abre: "credencial" },
        { id: "login", label: "Usuario y contraseña", abre: "credencial" },
        { id: "abierto", label: "Es abierto", detalle: "sin credencial" },
      ] });
  });
  await page.waitForTimeout(100);
  const preg = await page.evaluate(() => {
    const card = document.querySelector(".mc-pregunta");
    if (!card) return null;
    return {
      codigo: card.dataset.codigo,
      opts: [...card.querySelectorAll(".mc-opt")].map((o) => ({ opt: o.dataset.opt, abre: o.dataset.abre })),
    };
  });
  check("aparece la carta de pregunta con su código", preg && preg.codigo === "P3");
  check("2-3 opciones reales", preg && preg.opts.length === 3, preg && JSON.stringify(preg.opts.map((o) => o.opt)));
  check("la pregunta NO pide la cred en el chat (abre=credencial)", preg && preg.opts.some((o) => o.abre === "credencial"));

  // caso CLARO: una secuencia sin pregunta → NO hay carta de pregunta (anti-fatiga)
  await page.reload({ waitUntil: "networkidle" });
  await page.evaluate(() => {
    const st = window.__mesa.state;
    st._ingerir("construccion.creada", { construccion_id: "mc-clear" });
    st._ingerir("sesion.ok", { auth_form: "token_query" });
    st._ingerir("observando", { new_confirmed: ["/x"] });
  });
  await page.waitForTimeout(80);
  const sinPreg = await page.evaluate(() => !document.querySelector(".mc-pregunta"));
  check("caso claro NO muestra pregunta (anti-fatiga)", sinPreg);

  // ── #5 · paridad de modos ───────────────────────────────────────────────────
  console.log("[#5] paridad de modos — toggle no altera estado ni pierde eventos");
  await page.reload({ waitUntil: "networkidle" });
  await page.evaluate((seq) => { const st = window.__mesa.state; for (const [t, d] of seq) st._ingerir(t, d); }, SECUENCIA);
  await page.waitForTimeout(100);
  const antes = await page.evaluate(() => ({
    cid: window.__mesa.state.construccionId, ev: window.__mesa.state.eventos.length,
    val: window.__mesa.state.inventario.validadas.length,
    modo: window.__mesa.modo,
    toolsGuiado: document.querySelectorAll(".mc-guiado .mc-tl").length,
  }));
  await page.evaluate(() => window.__mesa.setModo("codigo"));
  await page.waitForTimeout(100);
  const despues = await page.evaluate(() => ({
    cid: window.__mesa.state.construccionId, ev: window.__mesa.state.eventos.length,
    val: window.__mesa.state.inventario.validadas.length,
    modo: window.__mesa.modo,
    toolsCodigo: document.querySelectorAll(".mc-codigo .mc-c-tool").length,
  }));
  check("el estado NO cambia al togglear (mismo cid + #eventos)",
    antes.cid === despues.cid && antes.ev === despues.ev, `${antes.ev} vs ${despues.ev}`);
  check("mismo inventario en las dos pieles (validadas)", antes.val === despues.val);
  check("Modo Código renderiza las MISMAS tools (paridad)", despues.toolsCodigo === antes.toolsGuiado,
    `guiado ${antes.toolsGuiado} vs codigo ${despues.toolsCodigo}`);
  check("el toggle cambió la piel (guiado→codigo)", antes.modo === "guiado" && despues.modo === "codigo");

  await browser.close();
  srv.close();

  // ── #7 · cero emoji de OS en la superficie nueva ────────────────────────────
  console.log("[#7] cero emoji de OS en la superficie nueva");
  // OS color-emoji: planos suplementarios (1F000+), banderas, el selector de presentación
  // emoji FE0F, y un puñado de emoji BMP (✅❌⛔⭐❤). NO flagea las marcas TIPOGRÁFICAS que el
  // Cuarto ya usa (✓ ✗ ✦ ⚠ ◦ · … — –), que no son pictogramas de OS.
  const EMOJI = /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{2705}\u{274C}\u{26D4}\u{2B50}\u{2764}\u{1F512}]/u;
  const archivos = ["mesa.html", "mesa.state.js", "mesa.rail.js", "mesa.guiado.js", "mesa.codigo.js"];
  let emojiEncontrado = [];
  for (const f of archivos) {
    const txt = await readFile(join(__dir, f), "utf8");
    txt.split("\n").forEach((ln, i) => { if (EMOJI.test(ln)) emojiEncontrado.push(`${f}:${i + 1}`); });
  }
  check("cero emoji de OS en mesa.* (front)", emojiEncontrado.length === 0, emojiEncontrado.join(", "));

  console.log("-".repeat(68));
  console.log(`RESULTADO: ${PASS} ✓ · ${FAIL} ✗`);
  process.exit(FAIL === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(2); });
