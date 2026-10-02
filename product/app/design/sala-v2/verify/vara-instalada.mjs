/* vara-instalada.mjs — LA VARA FINAL, CONTRA LA `.app` INSTALADA.
 *
 * Levanta el sidecar QUE ESTÁ ADENTRO de `/Applications/Aleph.app` —el binario congelado
 * que se distribuye, no el árbol de trabajo— y corre contra él la matriz completa de la
 * fase. El frontend que se mide es el que viaja dentro de ese binario (`_MEIPASS`), no el
 * del worktree: eso es lo que hace que esta vara valga más que las otras tres.
 *
 * DATADIR AISLADO A PROPÓSITO. Se mide el BINARIO instalado, no los datos de persona usuaria. Con su
 * datadir real, la vara le crearía cuentas, hilos y runs de prueba en la DB que usa todos
 * los días — y ya hay precedente en el repo de una vara que escribía en la `aleph.db` real.
 * El binario es el sujeto; el datadir es decorado.
 *
 * Corre TRES cosas:
 *   A · el arranque en frío   — abrir y escribir SIN nada configurado (el caso que persona usuaria
 *                               pidió medir acá y no en el preview).
 *   B · vara.mjs              — turno real · ≤5 s · estados · tool real · anti-grift · restaurar.
 *   C · vara-gate.mjs         — la tarjeta de consentimiento con un gate de verdad.
 *
 * Uso:  node product/app/design/sala-v2/verify/vara-instalada.mjs
 */
import { webkit } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const APP = process.env.ALEPH_APP || "/Applications/Aleph.app";
const SIDECAR = join(APP, "Contents/MacOS/aleph_sidecar");
const PORT = Number(process.env.ALEPH_PORT || 8330); // el rango estable del shell: 8330-8333
const BRAIN = process.env.BRAIN || "http://127.0.0.1:8927/v1";

if (!existsSync(SIDECAR)) {
  console.error(`✗ no existe ${SIDECAR}`);
  process.exit(1);
}

const fails = [];
const ok = (n, d) => console.log(`  ✅ ${n}${d ? " — " + d : ""}`);
const bad = (n, d) => {
  fails.push(`${n}${d ? " — " + d : ""}`);
  console.log(`  ❌ ${n}${d ? " — " + d : ""}`);
};

// ── identidad de lo que estamos midiendo ─────────────────────────────────────────────
const sha = spawnSync("shasum", ["-a", "256", SIDECAR], { encoding: "utf8" }).stdout.trim().slice(0, 16);
console.log(`\n· sujeto: ${SIDECAR}`);
console.log(`· sha256 del sidecar: ${sha}…`);

// ── arranque del binario congelado ───────────────────────────────────────────────────
// TMPDIR propio: el bootloader onefile de PyInstaller deja ~170 MB en `_MEI*` si el proceso
// no cierra limpio. 91 huérfanos llenaron el disco el 26-jul; por eso el repo tiene
// `qa/lib/frozen_guard.mjs`. Acá se aísla y se barre al final.
const MEI = mkdtempSync(join(tmpdir(), "f1-mei-"));
const DATA = mkdtempSync(join(tmpdir(), "f1-inst-data-"));
const hijo = spawn(SIDECAR, ["--port", String(PORT)], {
  env: {
    ...process.env,
    TMPDIR: MEI,
    ALEPH_DATA_DIR: DATA,
    ALEPH_ENV: "dev",
    PUPPET_ALLOW_PASSWORD_AUTH: "1",
    PUPPET_ALLOW_ANON_V1: "1",
  },
  detached: true,
  stdio: ["ignore", "pipe", "pipe"],
});
let log = "";
hijo.stdout.on("data", (b) => (log += b));
hijo.stderr.on("data", (b) => (log += b));

const BASE = `http://127.0.0.1:${PORT}`;
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

function matar() {
  // El onefile lanza un HIJO: matar sólo al padre deja el proceso real vivo y el puerto
  // tomado. Se mata el GRUPO (pid negativo), que es la lección de `frozen_guard.mjs`.
  try {
    process.kill(-hijo.pid, "SIGTERM");
  } catch (_) {
    /* ya murió */
  }
  try {
    rmSync(MEI, { recursive: true, force: true });
    rmSync(DATA, { recursive: true, force: true });
  } catch (_) {
    /* nada que barrer */
  }
}
process.on("exit", matar);

let vivo = false;
for (let i = 0; i < 90; i++) {
  await dormir(1000);
  try {
    const r = await fetch(BASE + "/health", { signal: AbortSignal.timeout(3000) });
    if (r.ok) {
      vivo = true;
      break;
    }
  } catch (_) {
    /* todavía arrancando */
  }
}
if (!vivo) {
  console.error("✗ el sidecar instalado no levantó en 90 s\n" + log.slice(-2000));
  matar();
  process.exit(1);
}
const salud = await (await fetch(BASE + "/health")).json();
console.log(`· vivo en :${PORT} · build=${salud?.proceso?.build} · frozen`);
console.log(`· el frontend sale de: ${(log.match(/\[serving\] frontend montado desde (\S+)/) || [])[1] || "?"}\n`);

// ── A · ARRANQUE EN FRÍO ─────────────────────────────────────────────────────────────
console.log("A · abrir y escribir SIN nada configurado");
{
  const b = await webkit.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 840 } });
  const errs = [];
  p.on("pageerror", (e) => errs.push(String(e && e.message)));

  const C = { email: `frio-${Date.now()}@example.com`, password: "frio-2026" };
  let U = null;
  for (const r of ["/v1/auth/register", "/v1/auth/login"]) {
    const x = await fetch(BASE + r, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(C),
    });
    if (x.ok) {
      const j = await x.json().catch(() => null);
      if (j?.session_token) {
        U = j;
        break;
      }
    }
  }
  if (U) await p.addInitScript((u) => localStorage.setItem("puppet_user", JSON.stringify(u)), U);
  await p.goto(`${BASE}/sala-v2/sala-v2.html?v2=1`, { waitUntil: "load" });
  const monto = await p.waitForSelector(".sv-composer textarea", { timeout: 25000 }).then(() => true).catch(() => false);
  monto ? ok("la pantalla monta desde el binario congelado") : bad("no montó desde el congelado");

  if (monto) {
    await p.evaluate(() => {
      window.__c = [];
      window.__salaV2.onEventoEspia = (e) => window.__c.push(e.type);
    });
    const caja = await p.$(".sv-composer textarea");
    await caja.click();
    await p.keyboard.type("Hola, decime en una frase qué podés hacer.");
    await p.keyboard.press("Enter");
    await p
      .waitForFunction(() => (window.__c || []).some((t) => t === "RUN_FINISHED" || t === "RUN_ERROR"), {
        timeout: 90000,
        polling: 200,
      })
      .catch(() => {});
    await p.waitForTimeout(800);

    const r = await p.evaluate(() => ({
      eventos: window.__c || [],
      texto: document.querySelector(".sv-thread")?.innerText || "",
      error: document.querySelector(".sv-error")?.innerText || "",
      aviso: document.querySelector(".sv-aviso")?.innerText || "",
    }));
    const murio = r.eventos.includes("RUN_ERROR");
    const dijoAlgo = Boolean(r.error || r.aviso) || /\S/.test(r.texto.replace(/Hola, decime[^\n]*/, ""));

    console.log(`     eventos: ${r.eventos.join(" ")}`);
    console.log(`     lo que ve el usuario: ${JSON.stringify(r.texto.slice(0, 200))}`);
    if (!murio) {
      ok("el turno en frío ANDA (hay cerebro por defecto)");
    } else if (dijoAlgo) {
      ok("el turno en frío falla, pero LO DICE", (r.error || r.aviso).slice(0, 120));
    } else {
      // Éste es el bug que persona usuaria mandó medir acá y no en el preview.
      bad("BUG REAL: el turno falla y la pantalla queda MUDA", "RUN_ERROR sin una palabra en la UI");
    }
  }
  errs.length ? bad(`${errs.length} pageerror en frío`, errs[0]) : ok("cero pageerror en frío");
  await b.close();
}

// ── B y C · las varas de la fase, contra el congelado ────────────────────────────────
console.log("\nB y C · la matriz de la fase, contra el binario instalado\n");
for (const v of ["vara.mjs", "vara-gate.mjs"]) {
  const r = spawnSync("node", [join(import.meta.dirname, v)], {
    encoding: "utf8",
    env: { ...process.env, BASE, BRAIN },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const salida = (r.stdout || "") + (r.stderr || "");
  console.log(salida.replace(/^/gm, "  "));
  if (r.status !== 0) fails.push(`${v} dio rojo`);
}

matar();
console.log("\n" + "═".repeat(64));
console.log(`VARA SOBRE LA INSTALADA · sidecar ${sha}…`);
if (fails.length) {
  console.log(`${fails.length} ROJAS`);
  for (const f of fails) console.log("  · " + f);
  process.exit(1);
}
console.log("todo verde");
