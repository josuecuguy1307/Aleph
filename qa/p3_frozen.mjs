/* p3_frozen.mjs — levanta el SIDECAR FROZEN de esta rama en :8273 y lo deja vivo.
 * El frozen sirve SU PROPIA copia de design/ desde _MEIPASS: medir contra el árbol de git
 * sería medir otro producto. Puerto propio; JAMÁS :25374 (esa es la .app de persona usuaria).
 * Run:  node qa/p3_frozen.mjs           (queda en primer plano; Ctrl-C / SIGTERM lo baja)
 */
import net from "node:net";
import path from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawnFrozen } from "./lib/frozen_guard.mjs";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const PORT = Number(process.env.P3_PORT || 8273);
if (PORT === 25374) { console.error("✗ 25374 es la .app de persona usuaria"); process.exit(2); }
const SIDECAR = process.env.ALEPH_SIDECAR_BIN || "/tmp/p3-dist/aleph_sidecar";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await new Promise((res, rej) => {
  const p = net.createConnection({ port: PORT, host: "127.0.0.1" });
  p.on("connect", () => { p.destroy(); rej(new Error(`:${PORT} ocupado — esta sonda mide su árbol o no mide nada`)); });
  p.on("error", () => res());
});

const DATA = mkdtempSync(path.join(tmpdir(), "p3-frozen-"));
const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  stdio: "inherit",
  env: { ...process.env, ALEPH_DATA_DIR: DATA, ALEPH_ROLE: "client", ALEPH_BUILD: "public" },
});
let vivo = false;
for (let i = 0; i < 180 && !vivo; i++) {
  await sleep(500);
  try { vivo = (await fetch(`http://127.0.0.1:${PORT}/health`)).ok; } catch {}
}
console.log(vivo ? `✓ FROZEN vivo en http://127.0.0.1:${PORT} (datadir ${DATA})`
                 : `✗ el frozen no levantó en :${PORT}`);
if (!vivo) process.exit(1);
await new Promise(() => {});   // queda vivo hasta que lo bajen (el guard limpia su _MEI)
