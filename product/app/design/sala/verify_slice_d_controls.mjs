/* Slice D browser regression: saved controls, real request bodies, SSE reasoning honesty,
 * Cuarto save/reopen, and responsive Effort/Detail/Pasos layout. */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const DESIGN = new URL("..", import.meta.url).pathname;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };
const PID = "slice-d-agent";
const failures = [];
const ok = (value, label, detail = "") => {
  console.log(`${value ? "  ✓" : "  ✗"} ${label}${!value && detail ? ` -> ${detail}` : ""}`);
  if (!value) failures.push(label);
};

const RECIPE = {
  schema_version: "v1",
  meta: { name: "Agente Slice D", nicho: "auditoría", descripcion: "fixture", output_type: "informe" },
  model: {
    primary: "claude-code-cli", fallback: null, base_url: "http://127.0.0.1:8926/v1",
    temperature: 0, max_tokens: 700, max_turns: 16, alias: "claude_cli",
    brain_provider: "claude_cli", cli_model: "sonnet", effort: "high",
  },
  belt: { belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json", tool_filters: { calc: ["add"] } },
  framing: { inline: "Responde con detalle y pasos explícitos. Mantén citas verificables." },
  rag: { enabled: false }, keys: {},
  gates: { money_touch: "needs_ok", send: "needs_ok" },
  canvas: {
    nucleos: [{ model: "claude_cli", detail: "detallado", steps: "full", instructions: "Mantén citas verificables." }],
    blocks: [], links: [], layout: [],
  },
};

function serve() {
  const server = http.createServer((req, response) => {
    const url = new URL(req.url, "http://local");
    if (/favicon|apple-touch-icon/i.test(url.pathname)) { response.writeHead(204); response.end(); return; }
    const file = path.join(DESIGN, decodeURIComponent(url.pathname));
    if (!file.startsWith(DESIGN) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      response.writeHead(404); response.end(); return;
    }
    response.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(response);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

async function wire(page, streamState) {
  const json = (route, value) => route.fulfill({ json: value });
  await page.route("**/v1/**", (route) => json(route, {}));
  await page.route("**/v1/icons**", (route) => json(route, { known: [] }));
  await page.route("**/v1/belts/cards**", (route) => json(route, { cards: [], total: 0, servers_real: [], dropped: [] }));
  await page.route("**/v1/users/u1/puppets", (route) => json(route, {
    puppets: [{ id: PID, name: "Agente Slice D", nicho: "auditoría", config: structuredClone(RECIPE) }],
  }));
  await page.route("**/v1/users/u1/keys", (route) => json(route, { keys: [] }));
  /* [GATE 3 · obra C] EL SELECTOR DE MODELOS V2. El fixture no lo stubeaba y quedó viejo
   * desde F8, cuando el picker pasó a leer de `/v1/modelos/selector` en vez de derivar de
   * `brains/status`. Sin esto el catálogo llega VACÍO y el selector no puede pintar nada —
   * por eso «el catálogo autoritativo del Cuarto» venía fallando en main. La forma es la
   * real, copiada de `qa/verify_cuarto_modelos.mjs:33`. */
  await page.route("**/v1/modelos/selector*", (route) => {
    const todos = new URL(route.request().url()).searchParams.get("todos") === "1";
    const modelos = [
      { slug: "cli.claude_cli", picker_id: "claude_cli", familia: "cli", label: "Mi Claude Code",
        sub: "Tu suscripción", model: "claude-code-cli", base_url: "http://127.0.0.1:8926/v1",
        brain_provider: "claude_cli", estado: "probado", conectado: true, default: true },
      { slug: "cli.codex_cli", picker_id: "codex_cli", familia: "cli", label: "Mi Codex",
        sub: "Tu suscripción", model: "codex-cli", base_url: "http://127.0.0.1:8926/v1",
        brain_provider: "codex_cli", estado: "probado", conectado: true },
    ];
    return json(route, { version: 2, default: "cli.claude_cli", default_id: "claude_cli",
      seleccion_id: "claude_cli",
      modelos: modelos.filter((m) => todos || m.conectado === true || m.default === true) });
  });
  await page.route("**/v1/brains/status**", (route) => json(route, {
    service: { state: "ready", mode: "managed", managed: true },
    providers: {
      included: { state: "ready", detail: "ruta incluida saludable" },
      claude_cli: { state: "ready", detail: "sesión activa", extra: { subscriptionType: "max" } },
      codex_cli: { state: "ready", detail: "sesión activa", extra: { subscriptionType: "plus" } },
    },
  }));
  await page.route("**/v1/puppets/run/stream", async (route) => {
    streamState.bodies.push(route.request().postDataJSON());
    const frames = streamState.withThinking
      ? [{ type: "thinking", text: "frame real" }, { type: "token", text: "hola" }]
      : [{ type: "token", text: "hola" }];
    frames.push({ type: "done", answer: "hola" });
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(""),
    });
  });
}

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
try {
  console.log("══ Sala: saved controls and request contract ══");
  const streamState = { withThinking: false, bodies: [] };
  const context = await browser.newContext({ viewport: { width: 1280, height: 840 }, reducedMotion: "reduce" });
  await context.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "token-u1" }));
    localStorage.setItem("aleph-lang", "es");
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => { if (message.type() === "error" && !/favicon|Failed to load resource/i.test(message.text())) errors.push(message.text()); });
  await wire(page, streamState);
  await page.goto(`${base}/sala/sala.html?puppet=${PID}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__salaSliceD?.state().ready && window.__salaSliceD.state().power === "claude_cli", null, { timeout: 15000 });

  const loaded = await page.evaluate(() => window.__salaSliceD.state());
  ok(loaded.controls.cliModel === "sonnet" && loaded.controls.effort === "high", "saved CLI submodel and effort reopen");
  ok(loaded.controls.detail === "detallado" && loaded.controls.steps === "full" && loaded.controls.maxTurns === 16, "saved Detail and Pasos reopen");
  ok(loaded.controls.instructions === "Mantén citas verificables.", "custom framing reopens separately from Detail");

  /* [GATE 3 · obra C] EL ⚡ SE ELIMINÓ. El modelo se cambia en el panel lateral «Modelo»
   * (debajo de «Chats»), con el MISMO widget del núcleo del Cuarto, y ese panel muestra
   * SÓLO la selección de modelo.
   *
   * Detalle, Pasos, sub-modelo y esfuerzo pasaron a ser CONFIGURACIÓN INTERNA: ya no tienen
   * control en la Sala, pero siguen hidratándose de la receta y viajando en cada run. Eso
   * NO se dejó de medir — se mide donde de verdad importa, que es el body que sale
   * (`buildBody` y los `streamState.bodies`, más abajo), no un texto en un popup. */
  await page.evaluate(() => window.__salaSliceD.open());
  const popText = await page.locator("#sbpModeloWidget").innerText();
  ok(/Mi Claude Code/.test(popText) && /Mi Codex/.test(popText), "el panel usa el catálogo CLI autoritativo del Cuarto");
  ok(!/DeepSeek/.test(popText), "el catálogo duplicado y legado de la Sala sigue muerto");
  ok(!/Detalle/.test(popText) && !/Pasos/.test(popText),
    "el panel muestra SÓLO la selección de modelo (Detalle y Pasos son internos, sin UI)");

  const viewports = [[1280, 840], [1024, 840], [800, 840], [600, 840]];
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => window.__salaSliceD.open());
    const layout = await page.evaluate(() => {
      const panel = document.getElementById("sbPanel");
      const w = document.getElementById("sbpModeloWidget");
      const rect = panel.getBoundingClientRect();
      const wRect = w.getBoundingClientRect();
      return {
        rect: { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom },
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        widgetVisible: wRect.height > 12 && wRect.top >= rect.top - 1,
        widgetOverflow: w.scrollWidth > w.clientWidth + 1,
      };
    });
    ok(!layout.horizontalOverflow && !layout.widgetOverflow, `Sala ${width}x${height}: sin desborde horizontal`, JSON.stringify(layout));
    ok(layout.rect.left >= 0 && layout.rect.right <= width + 1 && layout.rect.top >= 0 && layout.rect.bottom <= height + 1,
      `Sala ${width}x${height}: el panel queda dentro del viewport`, JSON.stringify(layout.rect));
    ok(layout.widgetVisible, `Sala ${width}x${height}: el selector de modelo se ve`);
  }
  await page.screenshot({ path: "/tmp/aleph-slice-d-sala-600.png", fullPage: true });

  const body = await page.evaluate(() => {
    window.__salaSliceD.set({ power: "codex_cli", cliModel: "gpt-5.1-codex-max", effort: "max", detail: "breve", steps: "1" });
    return window.__salaSliceD.buildBody("audita esto");
  });
  ok(body.puppet_id === PID && body.recipe, "saved-agent run keeps puppet identity and sends a session recipe clone");
  ok(body.recipe.model.primary === "codex-cli" && body.recipe.model.brain_provider === "codex_cli", "selected model reaches full-run body");
  ok(body.recipe.model.cli_model === "gpt-5.1-codex-max" && body.recipe.model.effort === "max", "CLI submodel and effort reach full-run body");
  ok(body.recipe.model.max_turns === 2, "Pasos reaches full-run max_turns");
  /* [GATE 3 · obra C] `startsWith`, no `===`, y es un arreglo de la ASERCIÓN, no del código.
   * Fijaba igualdad exacta contra el framing, pero `applyRunControls` le anexa la doctrina de
   * opciones por turno (`conDoctrinaOpciones`) desde una obra posterior. La aserción quedó
   * vieja y NADIE SE ENTERÓ porque esta vara crasheaba doce líneas más arriba —en el
   * `.power-note` del panel del ⚡— y nunca llegaba hasta acá. Lo que la línea afirma es lo
   * del nombre: que el Detalle cambia el framing SIN comerse las instrucciones del usuario. */
  ok(body.recipe.framing.inline.startsWith("Responde breve y directo. Mantén citas verificables."),
    "Detail changes framing without losing custom instructions", JSON.stringify({ salio: body.recipe.framing.inline.slice(0, 80) }));
  ok(RECIPE.model.primary === "claude-code-cli" && RECIPE.model.max_turns === 16, "session controls do not mutate the saved recipe");

  const noThinking = await page.evaluate(async (requestBody) => {
    const thinks = [], chunks = [];
    const answer = await window.__salaSliceD.streamBody(requestBody, (text) => chunks.push(text), (text) => thinks.push(text));
    return { answer, thinks, chunks };
  }, body);
  ok(noThinking.answer === "hola" && noThinking.thinks.length === 0, "token-only stream never fabricates a reasoning frame");
  streamState.withThinking = true;
  const realThinking = await page.evaluate(async (requestBody) => {
    const thinks = [];
    await window.__salaSliceD.streamBody(requestBody, () => {}, (text) => thinks.push(text));
    return thinks;
  }, body);
  ok(realThinking.length === 1 && realThinking[0] === "frame real", "genuine reasoning SSE frame is preserved exactly");
  ok(streamState.bodies.every((item) => item.recipe.model.max_turns === 2 && item.recipe.model.cli_model === "gpt-5.1-codex-max" && item.recipe.model.effort === "max"),
    "streaming requests carry model, CLI submodel, effort, framing, and turn limit");
  ok(errors.length === 0, "Sala console is clean", errors.slice(0, 3).join(" | "));
  await context.close();

  console.log("══ Cuarto: recipe save/reopen and Effort layout ══");
  const cuartoContext = await browser.newContext({ viewport: { width: 800, height: 840 }, reducedMotion: "reduce" });
  await cuartoContext.addInitScript(() => {
    sessionStorage.setItem("puppet_user", JSON.stringify({ id: "u1", session_token: "token-u1" }));
    localStorage.setItem("aleph-lang", "es");
  });
  const cuarto = await cuartoContext.newPage();
  const cuartoErrors = [];
  cuarto.on("pageerror", (error) => cuartoErrors.push(String(error)));
  await wire(cuarto, { withThinking: false, bodies: [] });
  await cuarto.goto(`${base}/cuarto/cuarto.pixi.html?puppet=${PID}`, { waitUntil: "load" });
  await cuarto.waitForFunction(() => window.__loadedPuppet?.id === "slice-d-agent" && window.__recipeMod && window.__models, null, { timeout: 15000 });
  const roundTrip = await cuarto.evaluate(() => {
    const nucleus = window.__cuarto.nucleoData();
    const recipe = window.__recipeMod.tilesToRecipe(window.__cuarto.placedTiles(), nucleus);
    return { nucleus: JSON.parse(JSON.stringify(nucleus)), recipe };
  });
  ok(roundTrip.nucleus.model === "claude_cli" && roundTrip.nucleus._cliModel === "sonnet" && roundTrip.nucleus._effort === "high", "Cuarto reopens model, submodel, and effort");
  ok(roundTrip.nucleus._detail === "detallado" && roundTrip.nucleus._steps === "full" && roundTrip.nucleus._maxTurns === 16, "Cuarto reopens Detail and Pasos");
  ok(roundTrip.nucleus._instructions === "Mantén citas verificables.", "Cuarto reopens custom framing");
  ok(roundTrip.recipe.model.cli_model === "sonnet" && roundTrip.recipe.model.effort === "high" && roundTrip.recipe.model.max_turns === 16, "Cuarto save round-trip preserves runtime controls");
  ok(roundTrip.recipe.framing.inline === RECIPE.framing.inline, "Cuarto save round-trip preserves exact framing");

  await cuarto.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await cuarto.locator('button.tab[data-d="opts"]').click();
  /* [GATE 3 · obra C] ABRIR LA SECCIÓN «Modelo» ANTES DE MIRARLA. `osec` pinta acordeones
   * CERRADOS por default (`cuarto.pixi.html:4816`), así que `#effortSel` existe pero está
   * oculto y `waitForSelector` —que espera VISIBLE— se colgaba 30 s. No es ablandar la
   * aserción: es hacer lo que hace un usuario, que es abrir la sección. Esto nunca se había
   * notado porque la vara moría en la sección de la Sala y jamás llegaba hasta acá. */
  const secModelo = cuarto.locator('.osec.brain.closed .osec-h');
  if (await secModelo.count()) await secModelo.first().click();
  await cuarto.waitForSelector("#effortSel");
  const effortLayout = await cuarto.evaluate(() => {
    const note = document.querySelector("#effortSel + .ro");
    const panel = document.getElementById("inspector");
    return {
      note: !!note,
      noteOverflow: note ? note.scrollWidth > note.clientWidth + 1 : true,
      noteHeight: note ? note.getBoundingClientRect().height : 0,
      panelOverflow: panel ? panel.scrollWidth > panel.clientWidth + 1 : true,
    };
  });
  ok(effortLayout.note && !effortLayout.noteOverflow && !effortLayout.panelOverflow && effortLayout.noteHeight > 20,
    "Cuarto Effort explanation wraps without colliding", JSON.stringify(effortLayout));
  ok(cuartoErrors.length === 0, "Cuarto console is clean", cuartoErrors.slice(0, 3).join(" | "));
  await cuarto.screenshot({ path: "/tmp/aleph-slice-d-cuarto-800.png", fullPage: true });
  await cuartoContext.close();
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

console.log(failures.length ? `\n✗ ${failures.length} Slice D failure(s)` : "\n✓ verify_slice_d_controls: all green");
process.exit(failures.length ? 1 : 0);
