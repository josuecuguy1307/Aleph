/**
 * qa/lib/frozen_guard.mjs — GUARD DE HIGIENE PARA VARAS QUE LEVANTAN EL SIDECAR FROZEN.
 *
 * ── EL PROBLEMA (medido, no supuesto) ────────────────────────────────────────
 * El sidecar frozen es un binario PyInstaller **onefile**: al arrancar se descomprime
 * entero (~170 MB) en un directorio `_MEIxxxxxx` dentro del temp del sistema, y lo
 * borra al salir LIMPIO. Una vara que muere por excepción, por timeout, o que mata al
 * hijo con SIGKILL, deja ese directorio ahí para siempre.
 *
 * El 2026-07-26 eso llenó el disco: **91 `_MEI*` huérfanos ≈ 15 GB**, `/` al 100 %, y
 * varas cayendo por no poder escribir un log (FIX-P7 §7·7). No fue culpa de una sesión:
 * es basura acumulada por TODAS las que corren varas frozen. Va a volver a pasar.
 *
 * ── LA CURA ──────────────────────────────────────────────────────────────────
 * NO se adivina cuál `_MEI` es nuestro (adivinar significaría borrar el de una sesión
 * hermana que está corriendo — el mismo pecado que `liberarPuerto()` matando sidecars
 * ajenos por nombre de binario). Se le da al hijo **su propio TMPDIR**: el bootloader
 * de PyInstaller respeta `TMPDIR`, así que el `_MEI` nace DENTRO de una carpeta que es
 * nuestra por construcción. Al terminar se borra esa carpeta entera.
 *
 * Se limpia en TODAS las salidas: normal, `process.exit()`, excepción no atrapada,
 * promesa sin catch, SIGINT y SIGTERM. Un `finally` en la vara no alcanza — el modo de
 * fallo que generó los 91 huérfanos es justamente el que salta el `finally`.
 *
 * ── USO — una línea por vara ─────────────────────────────────────────────────
 *   -  import { spawn } from "node:child_process";
 *   +  import { spawnFrozen as spawn } from "<…>/qa/lib/frozen_guard.mjs";
 *
 * Es drop-in: misma firma, devuelve el mismo ChildProcess. Lo que agrega es el TMPDIR
 * privado y el barrido al salir. `matarFrozen(proc)` está para el caso en que la vara
 * quiera reapear ANTES del final (bootear/matar en ciclo, como `verify_kit_default`).
 *
 * `barrerHuerfanos()` es la red de atrás: barre `_MEI*` viejos del temp del sistema
 * SALTEANDO los que tenga tomados un proceso vivo (`lsof`). Nunca toca uno en uso.
 */

import { spawn as _spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, readdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** procesos vivos que levantamos, con su TMPDIR privado */
const VIVOS = new Map();       // pid → { proc, dir, detached }
let _handlersPuestos = false;

function _rm(dir) {
  if (!dir) return;
  try { rmSync(dir, { recursive: true, force: true }); } catch {}
}

function _matar(entry) {
  const { proc } = entry;
  // ⚠ EL BOOTLOADER DE PYINSTALLER FORKEA. `proc.pid` es el bootloader; el sidecar de
  // verdad es su HIJO. `proc.kill()` mata al padre y deja al hijo corriendo, con el
  // puerto tomado y su `_MEI` en uso — es exactamente por qué los huérfanos aparecen.
  // Medido por qa/verify_frozen_guard.mjs §3. Por eso spawnFrozen fuerza `detached` y
  // acá se mata el GRUPO ENTERO. (P2 llegó a la misma conclusión por otro camino:
  // «matar el $! del shell NO lo reapea».)
  try { if (proc.pid) process.kill(-proc.pid, "SIGKILL"); } catch {}
  try { proc.kill("SIGKILL"); } catch {}
}

/** Mata TODO lo que levantamos y borra sus TMPDIR. Idempotente. */
export function limpiarTodo() {
  for (const [pid, entry] of VIVOS) {
    _matar(entry);
    _rm(entry.dir);
    VIVOS.delete(pid);
  }
}

function _ponerHandlers() {
  if (_handlersPuestos) return;
  _handlersPuestos = true;
  // 'exit' cubre el retorno normal Y process.exit(n) — el camino de casi todas las
  // varas, que salen con exit(1) al primer rojo sin pasar por ningún finally.
  process.on("exit", limpiarTodo);
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => { limpiarTodo(); process.exit(130); });
  }
  process.on("uncaughtException", (e) => {
    limpiarTodo();
    console.error(e);
    process.exit(1);
  });
  process.on("unhandledRejection", (e) => {
    limpiarTodo();
    console.error(e);
    process.exit(1);
  });
}

/**
 * Drop-in de `child_process.spawn` para el sidecar frozen.
 * Le da TMPDIR propio (⇒ el `_MEI` cae adentro) y lo barre al salir.
 */
export function spawnFrozen(cmd, args = [], opts = {}) {
  _ponerHandlers();
  const dir = mkdtempSync(join(tmpdir(), "aleph-mei-"));
  const env = { ...(opts.env || process.env), TMPDIR: dir, TEMP: dir, TMP: dir };
  // `detached: true` NO es para desatender el proceso: es para que el bootloader sea
  // LÍDER DE SU GRUPO y el fork interno caiga en el mismo grupo. Sin eso no hay forma
  // de reapear al sidecar de verdad (ver _matar). No se hace `unref()` a propósito.
  const proc = _spawn(cmd, args, { ...opts, env, detached: true });
  proc.__meiDir = dir;
  if (proc.pid) VIVOS.set(proc.pid, { proc, dir, detached: true });
  // si muere solo, igual barremos su carpeta (no esperamos al final de la vara)
  proc.once("exit", () => {
    const e = VIVOS.get(proc.pid);
    if (e) { _rm(e.dir); VIVOS.delete(proc.pid); }
  });
  return proc;
}

/** Reapea uno ANTES del final de la vara (ciclos bootear/matar). */
export function matarFrozen(proc) {
  if (!proc || !proc.pid) return;
  const entry = VIVOS.get(proc.pid) || { proc, dir: proc.__meiDir, detached: false };
  _matar(entry);
  _rm(entry.dir);
  VIVOS.delete(proc.pid);
}

/**
 * Red de atrás: barre `_MEI*` HUÉRFANOS del temp del sistema.
 * NUNCA toca uno que un proceso vivo tenga abierto — se comprueba con `lsof`. Un
 * barrido que mata trabajo ajeno es peor que el disco lleno.
 * @param {number} minEdadMin no tocar los creados hace menos de N minutos (default 10)
 */
export function barrerHuerfanos(minEdadMin = 10) {
  const base = tmpdir();
  const enUso = new Set();
  // GOTCHA: `lsof` sale con status 1 cuando NO pudo stat-ear algún path (pasa siempre
  // en el temp del sistema, hay dirs de otros usuarios). Eso NO es "lsof no está": la
  // salida es válida. Tratarlo como error dejaba el barrido siempre en 0.
  const r = spawnSync("lsof", ["-n", "-w", "-Fn", "+D", base], {
    encoding: "utf8", timeout: 120000, maxBuffer: 64 * 1024 * 1024,
  });
  if (r.error || (r.status !== 0 && r.status !== 1) || typeof r.stdout !== "string") {
    // SIN evidencia de qué está en uso NO se borra nada. Fallo visible, jamás mudo.
    return { barridos: 0, saltados: 0, motivo: `lsof inutilizable (status=${r.status}) — no se barre a ciegas` };
  }
  for (const m of r.stdout.matchAll(/_MEI[A-Za-z0-9]+/g)) enUso.add(m[0]);
  let barridos = 0, saltados = 0;
  const corte = Date.now() - minEdadMin * 60_000;
  let entradas = [];
  try { entradas = readdirSync(base).filter((n) => n.startsWith("_MEI")); } catch { return { barridos, saltados }; }
  for (const n of entradas) {
    const p = join(base, n);
    if (enUso.has(n)) { saltados++; continue; }
    try { if (statSync(p).mtimeMs > corte) { saltados++; continue; } } catch { continue; }
    if (!existsSync(p)) continue;
    _rm(p);
    barridos++;
  }
  return { barridos, saltados };
}

export default { spawnFrozen, matarFrozen, limpiarTodo, barrerHuerfanos };
