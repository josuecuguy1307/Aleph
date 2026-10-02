/* verify_modelos.mjs — entrada CANÓNICA de Modelos.
 *
 * MODELOS V2 reemplazó la UI de cards/grupos de FIX-P8 por BUSCAR vs CONFIGURAR.
 * La vara histórica sigue preservada en `verify_modelos_p8_legacy.mjs`, pero ya no mide
 * el contrato vivo. Este entrypoint ejecuta la vara V2 asignada a :8306 y propaga su exit.
 *
 * Run: node product/app/design/modelos/verify_modelos.mjs
 */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const varaV2 = fileURLToPath(new URL("../../../../qa/verify_modelos_v2.mjs", import.meta.url));
const child = spawnSync(process.execPath, [varaV2, ...process.argv.slice(2)], {
  cwd: fileURLToPath(new URL("../../../../", import.meta.url)),
  env: { ...process.env, MODELOS_V2_PORT: "8306" },
  stdio: "inherit",
});

if (child.error) {
  console.error("✗ no pude ejecutar la vara canónica de Modelos V2:", child.error.message);
  process.exit(2);
}
if (child.signal) {
  console.error(`✗ la vara de Modelos V2 terminó por señal ${child.signal}`);
  process.exit(130);
}
process.exit(child.status == null ? 2 : child.status);
