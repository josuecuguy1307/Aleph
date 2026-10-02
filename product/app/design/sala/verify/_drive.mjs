/* _drive.mjs — driver compartido del harness e2e de La Sala.
 *
 * Maneja: usuario QA (register→login idempotente), contexto Playwright con la sesión
 * sembrada en sessionStorage ANTES de que bootee sala.html, envío de prompts por el
 * composer REAL (la UI viva, no atajos), espera de fin de run sin sleeps fijos,
 * intercepción del JSON de /v1/puppets/run (capa motor vs capa UI), consola limpia
 * y screenshots como evidencia.
 *
 * Todo assert de caso vive en el caso; acá solo primitivas honestas. */
import { chromium } from "playwright";
import fs from "node:fs";
import { FRONT, BACK, SALA_URL, QA_EMAIL, QA_PASS, SCREEN_DIR } from "./_env.mjs";

/* ── usuario QA (idempotente) ─────────────────────────────────────────────── */
export async function ensureQaUser() {
  const reg = await fetch(BACK + "/v1/auth/register", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: QA_EMAIL, password: QA_PASS, display_name: "Sala E2E" }),
  });
  if (reg.status === 201) return await reg.json();
  // 409 = ya existe → login real (con contraseña, verifica hash)
  const log = await fetch(BACK + "/v1/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: QA_EMAIL, password: QA_PASS }),
  });
  if (!log.ok) throw new Error("auth QA falló: register=" + reg.status + " login=" + log.status);
  return await log.json();
}

/* ── browser / página ─────────────────────────────────────────────────────── */
export async function launch() {
  return await chromium.launch();   // chromium bundled del node_modules raíz
}

/* Contexto nuevo por caso (Biblioteca limpia: ST.sid vive en sessionStorage por-tab).
 * opts.puppet  → abre sala.html?puppet=ID
 * opts.routes  → [{ url, handler }] instalados ANTES del goto (para stubear /run etc.) */
export async function newSalaPage(browser, user, opts = {}) {
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 860 },
    deviceScaleFactor: 2,
    reducedMotion: "reduce",           // screenshots estables (Ola 3 anima con motion)
  });
  await ctx.addInitScript(([u]) => {
    // corre en TODOS los frames — en el iframe sandbox de la obra (sin allow-same-origin)
    // tocar storage lanza SecurityError; solo el frame top necesita la sesión.
    try {
      if (window.top !== window) return;
      sessionStorage.setItem("puppet_user", JSON.stringify(u));
      localStorage.setItem("aleph-lang", "es");
    } catch (e) { /* frame opaco: nada que sembrar */ }
  }, [user]);

  const page = await ctx.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  for (const r of (opts.routes || [])) await page.route(r.url, r.handler);

  const url = SALA_URL + (opts.puppet ? ("?puppet=" + encodeURIComponent(opts.puppet)) : "");
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#composer", { timeout: 15_000 });
  return { ctx, page, consoleErrors, pageErrors };
}

/* ── correr un prompt por la UI viva ──────────────────────────────────────── */
/* Tipea en #composer, Enter, espera el POST /v1/puppets/run (JSON del motor) y el
 * asentamiento de la UI (#send habilitado + #bbadge oculto + canvas/errcard).
 * Devuelve { out, runStatus } — out=null si el POST nunca ocurrió (p.ej. honesty gate). */
export async function runPrompt(page, prompt, { budget = 240_000, expectRun = true } = {}) {
  const runP = expectRun
    ? page.waitForResponse(
        (r) => r.url().includes("/v1/puppets/run") && !r.url().includes("/stream") && r.request().method() === "POST",
        { timeout: budget },
      ).catch(() => null)
    : Promise.resolve(null);

  await page.fill("#composer", prompt);
  await page.press("#composer", "Enter");

  const resp = await runP;
  let out = null, runStatus = null;
  if (resp) {
    runStatus = resp.status();
    try { out = await resp.json(); } catch { out = null; }
  }
  // asentamiento UI: fin de busy + badge fuera + (obra o error visible)
  await page.waitForFunction(() => {
    const send = document.getElementById("send");
    const badge = document.getElementById("bbadge");
    const canvas = document.getElementById("canvas");
    const settled = send && !send.disabled && (!badge || badge.style.display === "none");
    const painted = (canvas && /sala-/.test(canvas.className)) ||
                    document.querySelector("#chat .errcard") ||
                    document.querySelector("#chat .gate");
    return settled && painted;
  }, { timeout: 30_000 });
  return { out, runStatus };
}

/* ── evidencia ────────────────────────────────────────────────────────────── */
export async function snap(page, name) {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const zone = await page.$(".canvas-zone");
  if (zone) await zone.screenshot({ path: SCREEN_DIR + name + "-obra.png" });
  await page.screenshot({ path: SCREEN_DIR + name + "-full.png", fullPage: false });
}

/* consola: solo se perdona el favicon; una falla de CDN es una falla real de UX. */
export function realConsoleErrors(consoleErrors, pageErrors) {
  const noise = /favicon/i;
  return [...consoleErrors.filter((t) => !noise.test(t)), ...pageErrors];
}

/* ── mini framework de checks (mismo lenguaje ✓/✗ que los verify del repo) ─── */
export function makeChecker(caseName) {
  const results = [];
  return {
    check(name, cond, detail) {
      results.push({ name, ok: !!cond, detail: detail || "" });
      console.log((cond ? "  ✓ " : "  ✗ ") + name + (cond || !detail ? "" : "  → " + detail));
      return !!cond;
    },
    finish() {
      const fails = results.filter((r) => !r.ok);
      console.log((fails.length ? "✗ " : "✓ ") + caseName + " — " + (results.length - fails.length) + "/" + results.length);
      return { case: caseName, pass: !fails.length, checks: results };
    },
  };
}
