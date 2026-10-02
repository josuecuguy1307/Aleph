/* verify_finding4_autonomy.mjs — cierra el FINDING #4 del review adversarial A2:
 * la colisión de namespaces de _autonomy en el Núcleo. Dos capas:
 *   (1) COERCIÓN (recipe.js): un nucleo._autonomy corrupto (auto/ok/stop/basura) → 'balanceado'
 *       al serializar → JAMÁS se guarda un recipe.autonomy inválido → cero 422 al Guardar.
 *   (2) RAÍZ (applyChatEdit): el chat del Núcleo mapea al namespace agent-level
 *       (manual|balanceado|autonomo) y NUNCA escribe el per-pieza (auto|ok|stop). "cauto con el
 *       dinero" (el placeholder) ya NO dispara 'auto' (usa \bauto).
 * Corre las funciones REALES del worktree en el navegador (hooks __recipeMod / __applyChatEdit).
 * Run:  BACKEND=http://127.0.0.1:8090 FRONT_PORT=8102 node verify_finding4_autonomy.mjs
 */
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const WORKTREE = join(HERE, "..", "..", "..", "..");
const BACKEND = process.env.BACKEND || "http://127.0.0.1:8090";
const FRONT_PORT = Number(process.env.FRONT_PORT || 8102);
const BASE = `http://127.0.0.1:${FRONT_PORT}`;
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;

const log = (...a) => console.log(...a);
const fails = [];
const ok = (cond, label, extra) => { log(`${cond ? "✓" : "✗"} ${label}${extra ? "  " + extra : ""}`); if (!cond) fails.push(label); };
async function up(url) { try { const r = await fetch(url, { signal: AbortSignal.timeout(3000) }); return r.ok; } catch { return false; } }

if (!(await up(`${BACKEND}/health`))) { console.error(`FALTA: backend ${BACKEND}/health caído.`); process.exit(3); }

// sesión (la página gatea auth para init __cuarto)
const email = `f4-gate-${Date.now()}@aleph.test`;
const sess = await (await fetch(`${BACKEND}/v1/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, display_name: "F4 Gate" }),
})).json().catch(() => null);
if (!sess || !sess.id) { console.error("FALTA: sesión", sess); process.exit(3); }

const front = spawn("python3", ["product/app/serve.py"], {
  cwd: WORKTREE, stdio: "ignore",
  env: { ...process.env, ALEPH_FRONT_PORT: String(FRONT_PORT), ALEPH_BACKEND: BACKEND },
});
process.on("exit", () => { try { front.kill("SIGTERM"); } catch {} });
await new Promise((r) => setTimeout(r, 1000));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1320, height: 880 } });
const cerr = [];
page.on("console", (m) => { if (m.type() === "error") cerr.push(m.text()); });
page.on("pageerror", (e) => cerr.push(String(e)));
await page.addInitScript((s) => { try { sessionStorage.setItem("puppet_user", JSON.stringify(s)); } catch (e) {} },
  { id: sess.id, session_token: sess.session_token, email });

try {
  await page.goto(PAGE, { waitUntil: "load" });
  // esperar a que el init ASYNC termine (catálogo cargado) — así fullToolsOf (const, línea ~1194,
  // tras un await de catálogo) ya está inicializado antes de invocar applyChatEdit por el hook.
  await page.waitForFunction(() => window.__cuarto && window.__recipeMod && window.__applyChatEdit &&
    window.Projection && window.__atoms && window.__atoms.list && window.__atoms.list.length, null, { timeout: 20000 });

  // ── (1) COERCIÓN · un _autonomy corrupto NUNCA sale como recipe.autonomy inválido ──
  const coer = await page.evaluate(() => {
    const VALID = { manual: 1, balanceado: 1, autonomo: 1 };
    const nuc = window.__cuarto.nucleoData();
    const out = {};
    for (const bad of ["auto", "ok", "stop", "", "xyz", undefined, null]) {
      nuc._autonomy = bad;
      const r = window.__recipeMod.tilesToRecipe(window.__cuarto.placedTiles(), nuc);
      out[String(bad)] = r.autonomy;
    }
    // y un valor VÁLIDO se preserva tal cual
    nuc._autonomy = "autonomo";
    out.valid_autonomo = window.__recipeMod.tilesToRecipe(window.__cuarto.placedTiles(), nuc).autonomy;
    nuc._autonomy = "balanceado";
    return out;
  });
  const allValid = Object.entries(coer).every(([k, v]) => ["manual", "balanceado", "autonomo"].includes(v));
  ok(allValid, "COERCIÓN · todo _autonomy corrupto (auto/ok/stop/basura/undefined) → recipe.autonomy válido", JSON.stringify(coer));
  ok(coer.auto === "balanceado" && coer.ok === "balanceado" && coer.stop === "balanceado",
     "COERCIÓN · el per-pieza (auto/ok/stop) del namespace equivocado cae a 'balanceado'", `auto=${coer.auto} ok=${coer.ok} stop=${coer.stop}`);
  ok(coer.valid_autonomo === "autonomo", "COERCIÓN · un valor VÁLIDO se preserva (no lo pisa)", `→ ${coer.valid_autonomo}`);

  // ── (2) RAÍZ · el chat del Núcleo mapea al namespace agent-level, nunca al per-pieza ──
  const chat = await page.evaluate(() => {
    const nuc = window.__cuarto.nucleoData();
    const run = (text) => { nuc._autonomy = "balanceado"; window.__applyChatEdit(nuc, text); return nuc._autonomy; };
    return {
      cauto: run("que sea más cauto con el dinero"),   // el PLACEHOLDER — NO debe volverse 'auto'
      auto: run("quiero que actúe en auto"),
      autonomo: run("que sea autónomo"),
      frena: run("frená siempre antes de actuar"),
      pide: run("pedí ok siempre"),
      balance: run("dejalo balanceado"),
    };
  });
  const VALID = ["manual", "balanceado", "autonomo"];
  const noPerPieza = Object.values(chat).every((v) => VALID.includes(v));
  ok(noPerPieza, "RAÍZ · NINGÚN chat del Núcleo deja un valor per-pieza (auto/ok/stop) en _autonomy", JSON.stringify(chat));
  ok(chat.cauto !== "auto" && VALID.includes(chat.cauto), "RAÍZ · 'cauto con el dinero' (placeholder) NO dispara 'auto' (\\bauto)", `→ ${chat.cauto}`);
  ok(chat.auto === "autonomo", "RAÍZ · 'actúe en auto' → autonomo", `→ ${chat.auto}`);
  ok(chat.frena === "manual" && chat.pide === "manual", "RAÍZ · 'frená/pedí ok' → manual", `frena=${chat.frena} pide=${chat.pide}`);
  ok(chat.balance === "balanceado", "RAÍZ · 'balanceado' → balanceado", `→ ${chat.balance}`);

  ok(cerr.length === 0, "0 errores de consola", cerr.slice(0, 2).join(" | "));
} catch (e) {
  ok(false, "excepción en el probe", String(e));
} finally {
  await browser.close();
}

log("");
if (fails.length) { console.error(`✗ FINDING #4 ROJO — ${fails.length} fallas`); process.exit(1); }
log("✓ FINDING #4 VERDE — colisión de namespace de autonomía cerrada (coerción + raíz)");
