/* verify_brain_selector.mjs — done-bar FRONT del selector de cerebro BYO-CLI (D3):
 *   (a) detección real → card "Mi Claude Code" VIVA (ready) con chip honesto
 *   (b) card "Mi Codex" APAGADA con razón (no_auth) — 🔒 aria-disabled + title + guía única
 *   (c) los estados NO se contagian (uno vivo + otro apagado A LA VEZ)
 *   (d) click en la card apagada NO selecciona; click en la viva → recipe.model.brain_provider
 *   (e) persistencia: la elección viaja a la receta (primary/base_url/alias/brain_provider,
 *       fallback null) y el id humano queda en canvas.nucleos[0].model (round-trip)
 *   (f) detección CAÍDA → "no pude verificar" SIN candado (la honestidad se difiere al run,
 *       jamás se finge un listo)
 *   (g) 0 errores JS
 * Puerto :8156. Sin backend (stub /v1/**).   Run: node verify_brain_selector.mjs */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const DESIGN_DIR = join(HERE, "..");
const PORT = 8156;
const PAGE = `http://localhost:${PORT}/cuarto/cuarto.pixi.html`;
const fails = [];
const ok = (c, label, extra) => { console.log(`${c ? "✓" : "✗"} ${label}${(!c && extra) ? "  · " + extra : ""}`); if (!c) fails.push(label); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STATUS_MIXED = {
  service: { state: "ready", mode: "managed", managed: true, detail: "servicio CLI administrado por Aleph" },
  providers: {
    included: { provider: "included", state: "ready", detail: "ruta incluida saludable" },
    claude_cli: { provider: "claude_cli", state: "ready", detail: "sesión activa (max)", binary: "/x/claude", checked_at: 1, extra: { authMethod: "claude.ai", subscriptionType: "max" } },
    codex_cli: { provider: "codex_cli", state: "no_auth", detail: "instalado pero sin sesión — corré `codex login`", binary: "/x/codex", checked_at: 1, extra: {} },
  },
};

const server = spawn("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: DESIGN_DIR, stdio: "ignore" });
await sleep(700);
const browser = await chromium.launch();
try {
  // ══ ESCENARIO 1 · estados mixtos (claude ready · codex no_auth) ══
  const page = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|favicon|net::ERR/i.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/v1/brains/status**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(STATUS_MIXED) }));
  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForFunction(() => window.__cuarto && window.__models && window.__openInspector, null, { timeout: 12000 });

  // (a)+(b)+(c) — la lista anotada por la detección real (módulo)
  const ann = await page.evaluate(() => {
    const by = window.__models.byId;
    return {
      opus: { locked: !!by.opus.locked, need: by.opus.need, base: by.opus.base_url, avail: by.opus.avail },
      claude: { locked: !!by.claude_cli.locked, avail: by.claude_cli.avail },
      codex: { locked: !!by.codex_cli.locked, avail: by.codex_cli.avail, reason: by.codex_cli.lockReason || "" },
    };
  });
  ok(!ann.opus.locked && ann.opus.need === "included" && /openrouter\.ai/.test(ann.opus.base) && !/8923/.test(ann.opus.base),
     "(0) Opus usa la ruta productiva incluida/hosted, nunca el shim dev :8923", JSON.stringify(ann.opus));
  ok(!ann.claude.locked && ann.claude.avail.kind === "ok" && /max/.test(ann.claude.avail.text),
     "(a) Mi Claude Code VIVO con chip honesto ('listo · plan max')", JSON.stringify(ann.claude));
  ok(ann.codex.locked && ann.codex.avail.kind === "lock" && /codex login/.test(ann.codex.reason),
     "(b) Mi Codex APAGADO con razón honesta + guía (`codex login`)", JSON.stringify(ann.codex));
  ok(!ann.claude.locked && ann.codex.locked, "(c) estados INDEPENDIENTES a la vez (sin contagio)");

  // DOM del picker: abrir el inspector del Núcleo
  await page.evaluate(() => window.__openInspector(window.__cuarto.nucleoData()));
  await sleep(200);
  const dom = await page.evaluate(() => {
    const cl = document.querySelector('#d-opts .modelcard[data-model="claude_cli"]');
    const cx = document.querySelector('#d-opts .modelcard[data-model="codex_cli"]');
    return {
      claude: cl ? { lock: cl.classList.contains("lock"), aria: cl.getAttribute("aria-disabled") } : null,
      codex: cx ? { lock: cx.classList.contains("lock"), aria: cx.getAttribute("aria-disabled"), title: cx.getAttribute("title") || "" } : null,
    };
  });
  ok(dom.claude && !dom.claude.lock, "(a-dom) card Mi Claude Code sin candado", JSON.stringify(dom.claude));
  ok(dom.codex && dom.codex.lock && dom.codex.aria === "true" && /codex login/.test(dom.codex.title),
     "(b-dom) card Mi Codex con 🔒 + aria-disabled + title con la razón", JSON.stringify(dom.codex));

  // (d) click en la APAGADA → NO selecciona + guía única; click en la VIVA → selecciona.
  // (click por DOM: la sección del picker puede estar plegada; el handler es el contrato)
  await page.evaluate(() => document.querySelector('#d-opts .modelcard[data-model="codex_cli"]').click());
  await sleep(120);
  const afterLocked = await page.evaluate(() => ({
    model: window.__cuarto.nucleoData().model || null,
    on: !!document.querySelector('#d-opts .modelcard[data-model="codex_cli"].on'),
    status: (document.getElementById("status") || {}).textContent || "",
  }));
  ok(afterLocked.model !== "codex_cli" && !afterLocked.on, "(d) click en la apagada NO selecciona", JSON.stringify(afterLocked.model));
  ok(/no está listo/.test(afterLocked.status), "(d) la guía honesta se empuja al status", afterLocked.status.slice(0, 80));

  // OLA 4 · §4 · MED#9 (relocado del panel al inspector, que es la ÚNICA casa del cerebro de agentes tras
  // el dedup): cambiar el cerebro en la card RESETEA el sub-modelo por-provider (_cliModel). Sembramos un
  // pedido stale ('sonnet') antes del click; debe quedar en undefined (no arrastrar 'sonnet' a otro provider).
  await page.evaluate(() => { window.__cuarto.nucleoData()._cliModel = "sonnet"; });
  await page.evaluate(() => document.querySelector('#d-opts .modelcard[data-model="claude_cli"]').click());
  await sleep(120);
  const chosen = await page.evaluate(async () => {
    const d = window.__cuarto.nucleoData();
    const { tilesToRecipe } = await import("./cuarto.recipe.js");
    const r = tilesToRecipe(window.__cuarto.placedTiles(), d);
    return { model: d.model, cli: d._cliModel, m: r.model, canvasModel: ((r.canvas || {}).nucleos || [{}])[0].model };
  });
  ok(chosen.model === "claude_cli", "(d) click en la viva → d.model = claude_cli");
  ok(chosen.cli === undefined, "(d·MED#9) cambiar el cerebro en el inspector RESETEA el sub-modelo (_cliModel) — no arrastra 'sonnet' a otro provider");
  ok(chosen.m && chosen.m.brain_provider === "claude_cli" && chosen.m.primary === "claude-code-cli"
     && /8926/.test(chosen.m.base_url) && chosen.m.alias === "claude_cli" && chosen.m.fallback === null,
     "(e) receta: brain_provider + primary + :8926 + alias + fallback null", JSON.stringify(chosen.m));
  ok(chosen.canvasModel === "claude_cli", "(e) round-trip: canvas.nucleos[0].model = claude_cli", String(chosen.canvasModel));
  ok(errors.length === 0, "(g) 0 errores JS", errors.slice(0, 2).join(" | "));
  await page.close();

  // ══ ESCENARIO 2 · detección CAÍDA → honesto sin candado ══
  const p2 = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  const errs2 = [];
  p2.on("pageerror", (e) => errs2.push(String(e)));
  await p2.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await p2.route("**/v1/brains/status**", (r) => r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
  await p2.goto(PAGE, { waitUntil: "load" });
  await p2.waitForFunction(() => window.__cuarto && window.__models, null, { timeout: 12000 });
  const down = await p2.evaluate(() => {
    const by = window.__models.byId;
    return { cl: { locked: !!by.claude_cli.locked, text: by.claude_cli.avail.text },
             cx: { locked: !!by.codex_cli.locked, text: by.codex_cli.avail.text } };
  });
  ok(!down.cl.locked && !down.cx.locked && /no pude verificar/.test(down.cl.text) && /no pude verificar/.test(down.cx.text),
     "(f) detección caída → 'no pude verificar' SIN candado (jamás finge, jamás bloquea de más)",
     JSON.stringify(down));
  ok(errs2.length === 0, "(g2) 0 errores JS con la detección caída", errs2.slice(0, 2).join(" | "));
  await p2.close();

  // ══ ESCENARIO 3 · auth CLI vivo, listener administrado caído → ambas cards bloqueadas ══
  const p3 = await browser.newPage({ viewport: { width: 1400, height: 860 } });
  await p3.route("**/v1/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await p3.route("**/v1/brains/status**", (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      service: { state: "unavailable", mode: "failed", detail: "puerto ocupado" },
      providers: {
        included: { state: "ready", detail: "ruta incluida saludable" },
        claude_cli: { state: "ready", detail: "sesión activa" },
        codex_cli: { state: "ready", detail: "sesión activa" },
      },
    }),
  }));
  await p3.goto(PAGE, { waitUntil: "load" });
  await p3.waitForFunction(() => window.__cuarto && window.__models, null, { timeout: 12000 });
  const serviceDown = await p3.evaluate(() => {
    const by = window.__models.byId;
    return {
      cl: { locked: !!by.claude_cli.locked, reason: by.claude_cli.lockReason || "" },
      cx: { locked: !!by.codex_cli.locked, reason: by.codex_cli.lockReason || "" },
    };
  });
  ok(serviceDown.cl.locked && serviceDown.cx.locked
     && /ocupado/.test(serviceDown.cl.reason) && /ocupado/.test(serviceDown.cx.reason),
     "(h) auth CLI no finge disponibilidad cuando el listener :8926 está caído", JSON.stringify(serviceDown));
  await p3.close();
} finally {
  await browser.close();
  server.kill();
}
console.log(fails.length ? `\n✗ ${fails.length} falla(s)` : "\n✓ verify_brain_selector: TODO VERDE");
process.exit(fails.length ? 1 : 0);
