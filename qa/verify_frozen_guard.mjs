#!/usr/bin/env node
/**
 * qa/verify_frozen_guard.mjs — la vara del guard de `_MEI`.
 *
 * Prueba lo único que importa del guard: que una vara frozen ya NO puede dejar basura
 * en el temp del sistema, ni siquiera cuando muere por el camino que salta los
 * `finally` (SIGKILL, `process.exit()` a la primera aserción roja).
 *
 * Con CALIBRACIÓN EN ROJO: el bloque 3 levanta el MISMO binario con el `spawn` pelado
 * de node y lo mata a lo bestia — y EXIGE que quede un huérfano. Si no queda, el guard
 * no está tapando nada y esta vara lo dice en vez de firmar un verde decorativo.
 *
 *   node qa/verify_frozen_guard.mjs
 *   FROZEN=/ruta/al/aleph_sidecar node qa/verify_frozen_guard.mjs
 *
 * Puerto: 8291-8293 (propio de la tanda P). Datadir SIEMPRE aislado.
 */

import { spawn as spawnPelado, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnFrozen, matarFrozen, barrerHuerfanos } from "./lib/frozen_guard.mjs";

const AQUI = dirname(fileURLToPath(import.meta.url));
const RAIZ = join(AQUI, "..");
const FROZEN = process.env.FROZEN ||
  join(RAIZ, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");

const fails = [];
const ok = (c, l, x = "") => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  — " + x : ""}`); if (!c) fails.push(l); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const meiDelSistema = () => new Set(readdirSync(tmpdir()).filter((n) => n.startsWith("_MEI")));

/**
 * Mata lo que escucha en `port` SÓLO si su comando es el binario que esta vara levantó.
 * Nunca un proceso ajeno: el nombre `aleph_sidecar` es idéntico en todos los worktrees
 * y un `pkill` por nombre barre el trabajo de una sesión hermana (gotcha de FIX-P2 §13.2).
 */
function reaparPorPuerto(port) {
  const r = spawnSync("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"], { encoding: "utf8" });
  for (const pid of (r.stdout || "").split("\n").map((s) => s.trim()).filter(Boolean)) {
    const cmd = spawnSync("ps", ["-o", "command=", "-p", pid], { encoding: "utf8" }).stdout || "";
    if (cmd.includes(FROZEN) || cmd.includes("aleph_sidecar")) {
      try { process.kill(Number(pid), "SIGKILL"); } catch {}
    }
  }
}

async function vivo(port, tries = 90) {
  for (let i = 0; i < tries; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(2000) }); if (r.ok) return true; } catch {}
    await sleep(500);
  }
  return false;
}

if (!existsSync(FROZEN)) {
  console.log(`✗ no existe el sidecar frozen: ${FROZEN}`);
  console.log("  (construilo con build_app.sh, o pasá FROZEN=/ruta)");
  process.exit(1);
}
console.log(`── frozen ${FROZEN}\n`);

// ── 0 · PRECONDICIÓN: los puertos son MÍOS ────────────────────────────────────
// La lección de `581aa1c`: un veredicto firmado sobre el árbol/proceso de otra sesión
// es peor que no tener veredicto. Si :8291-8294 están tomados, esta vara mediría un
// sidecar ajeno (pasó en su primera corrida: los sobrevivientes de la vuelta anterior
// contestaban /health y la vara los tomó por suyos). No se mata a nadie: se para.
{
  const tomados = [8291, 8292, 8293, 8294].filter((p) => {
    const r = spawnSync("lsof", ["-nP", `-iTCP:${p}`, "-sTCP:LISTEN", "-t"], { encoding: "utf8" });
    return !!(r.stdout || "").trim();
  });
  if (tomados.length) {
    console.log(`✗ puertos tomados: ${tomados.join(", ")} — no mido sobre procesos ajenos.`);
    console.log("  liberalos (o mirá quién es con: lsof -nP -iTCP:8291 -sTCP:LISTEN) y repetí.");
    process.exit(2);
  }
}

// ── 1 · el `_MEI` nace DENTRO del TMPDIR privado ──────────────────────────────
console.log("§1 · contención: el _MEI no toca el temp del sistema");
const base1 = meiDelSistema();
const dd1 = mkdtempSync(join(tmpdir(), "fg-dd-"));
const p1 = spawnFrozen(FROZEN, ["--port", "8291"], {
  stdio: "ignore", env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: dd1 },
});
const up1 = await vivo(8291);
ok(up1, "el sidecar frozen levanta bajo el guard");
const dentro = existsSync(p1.__meiDir) ? readdirSync(p1.__meiDir).filter((n) => n.startsWith("_MEI")) : [];
ok(dentro.length === 1, "su _MEI nace DENTRO del TMPDIR privado", dentro.join(",") || "(ninguno)");
const nuevos1 = [...meiDelSistema()].filter((n) => !base1.has(n));
ok(nuevos1.length === 0, "y CERO _MEI nuevos en el temp del sistema", nuevos1.join(",") || "ok");

// ── 2 · al matarlo, la carpeta entera desaparece ──────────────────────────────
console.log("\n§2 · barrido: matarFrozen se lleva el TMPDIR entero");
const dirP1 = p1.__meiDir;
matarFrozen(p1);
await sleep(2000);
ok(!existsSync(dirP1), "el TMPDIR privado ya no existe", dirP1);
// LO QUE DE VERDAD IMPORTA: que el sidecar esté MUERTO, no sólo su bootloader. Si el
// fork interno sobreviviera, el puerto seguiría contestando.
const sigue1 = await (async () => { try { const r = await fetch("http://127.0.0.1:8291/health", { signal: AbortSignal.timeout(1500) }); return r.ok; } catch { return false; } })();
ok(!sigue1, "el sidecar REAL murió (no sólo el bootloader): :8291 no contesta");
const nuevos2 = [...meiDelSistema()].filter((n) => !base1.has(n));
ok(nuevos2.length === 0, "y sigue sin haber huérfanos en el temp del sistema", nuevos2.join(",") || "ok");
rmSync(dd1, { recursive: true, force: true });

// ── 3 · CALIBRACIÓN EN ROJO ──────────────────────────────────────────────────
// El mismo binario, levantado con el `spawn` pelado y matado con SIGKILL: TIENE que
// dejar un huérfano. Si no lo deja, el guard no está tapando ningún agujero real y
// los §1/§2 son verdes decorativos.
console.log("\n§3 · CALIBRACIÓN: sin el guard, el huérfano APARECE");
const base3 = meiDelSistema();
const dd3 = mkdtempSync(join(tmpdir(), "fg-dd-"));
const p3 = spawnPelado(FROZEN, ["--port", "8292"], {
  stdio: "ignore", env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: dd3 },
});
const up3 = await vivo(8292);
ok(up3, "el sidecar pelado levanta");
try { p3.kill("SIGKILL"); } catch {}
await sleep(2000);
const huerfanos = [...meiDelSistema()].filter((n) => !base3.has(n));
ok(huerfanos.length >= 1,
  "CALIBRACIÓN: el spawn PELADO + SIGKILL deja _MEI huérfano (el bug que el guard tapa)",
  huerfanos.join(",") || "NINGUNO — la vara sería ciega");
// Y la SEGUNDA mitad del bug, que es la que engaña: matar el `proc` de node mata al
// BOOTLOADER, no al sidecar. El fork interno sigue sirviendo el puerto.
const sobrevive3 = await (async () => { try { const r = await fetch("http://127.0.0.1:8292/health", { signal: AbortSignal.timeout(1500) }); return r.ok; } catch { return false; } })();
ok(sobrevive3, "CALIBRACIÓN: y el sidecar SOBREVIVE al kill del bootloader (:8292 sigue vivo)");
// se lo reapea por puerto — y SÓLO si es este binario, jamás un proceso ajeno
reaparPorPuerto(8292);
await sleep(2000);

// ── 4 · el barrido NO toca un `_MEI` EN USO ──────────────────────────────────
// Lo más peligroso de un barredor es que borre el trabajo de una sesión hermana. Se
// levanta uno pelado y VIVO, y se exige que el barrido lo saltee.
console.log("\n§4 · el barrido respeta lo que está EN USO");
const dd4 = mkdtempSync(join(tmpdir(), "fg-dd-"));
const p4 = spawnPelado(FROZEN, ["--port", "8293"], {
  stdio: "ignore", env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: dd4 },
});
const up4 = await vivo(8293);
ok(up4, "hay un sidecar VIVO (simula la sesión hermana)");
const vivos = [...meiDelSistema()].filter((n) => !base3.has(n) && !huerfanos.includes(n));
const res4 = barrerHuerfanos(0);   // edad 0: agresivo a propósito, sólo lo protege lsof
ok(!res4.motivo, "el barrido pudo correr (lsof usable)", res4.motivo || JSON.stringify(res4));
const sobreviven = vivos.filter((n) => existsSync(join(tmpdir(), n)));
ok(vivos.length === 0 || sobreviven.length === vivos.length,
  "el _MEI del sidecar VIVO sobrevive al barrido", `vivos=${vivos.join(",") || "-"} sobreviven=${sobreviven.join(",") || "-"}`);
const huerfBarridos = huerfanos.filter((n) => !existsSync(join(tmpdir(), n)));
ok(huerfBarridos.length === huerfanos.length,
  "y el huérfano del §3 SÍ se barrió", `${huerfBarridos.length}/${huerfanos.length}`);
try { p4.kill("SIGKILL"); } catch {}
reaparPorPuerto(8293);
await sleep(1500);

// ── 5 · el camino que salta el finally ───────────────────────────────────────
// El modo de fallo que generó los 91 huérfanos: la vara sale con process.exit(1) a la
// primera aserción roja, sin pasar por ningún `finally`. El guard cuelga de 'exit'.
console.log("\n§5 · process.exit() sin finally: el guard igual barre");
const hijo = join(tmpdir(), `fg-hijo-${Date.now()}.mjs`);
writeFileSync(hijo, `
import { spawnFrozen } from ${JSON.stringify(join(AQUI, "lib/frozen_guard.mjs"))};
import { mkdtempSync } from "node:fs"; import { tmpdir } from "node:os"; import { join } from "node:path";
const p = spawnFrozen(${JSON.stringify(FROZEN)}, ["--port","8294"], {
  stdio:"ignore", env:{...process.env, ALEPH_ROLE:"client", ALEPH_DATA_DIR: mkdtempSync(join(tmpdir(),"fg-dd-"))} });
console.log(p.__meiDir);
setTimeout(() => process.exit(1), 9000);   // ← muere sin finally, como una vara en rojo
`);
const salida = await new Promise((res) => {
  const c = spawnPelado(process.execPath, [hijo], { stdio: ["ignore", "pipe", "ignore"] });
  let s = ""; c.stdout.on("data", (d) => (s += d)); c.on("exit", () => res(s.trim()));
});
await sleep(1500);
ok(!!salida, "el hijo reportó su TMPDIR privado", salida || "(vacío)");
ok(salida && !existsSync(salida), "el TMPDIR se barrió aunque el hijo salió por process.exit(1)", salida);
rmSync(hijo, { force: true });
for (const d of [dd3, dd4]) rmSync(d, { recursive: true, force: true });

console.log(`\n${fails.length === 0 ? "✅ VERDE" : "❌ ROJO"} · ${fails.length} fallos`);
if (fails.length) fails.forEach((f) => console.log("   ✗ " + f));
process.exit(fails.length ? 1 : 0);
