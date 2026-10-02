#!/usr/bin/env node
/* Focused, read-only regression checks for the Settings danger-zone copy. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const file = path.join(root, "product/app/design/Settings.dc.html");
const html = fs.readFileSync(file, "utf8");
const failures = [];
const ok = (condition, message) => {
  console.log(`${condition ? "✓" : "✗"} ${message}`);
  if (!condition) failures.push(message);
};

const dangerStart = html.indexOf("Zona de peligro");
const danger = dangerStart >= 0 ? html.slice(dangerStart) : "";
const mountStart = html.indexOf("componentDidMount()");
const mountEnd = html.indexOf("componentWillUnmount()");
const mount = mountStart >= 0 && mountEnd > mountStart ? html.slice(mountStart, mountEnd) : "";

ok(html.includes("Borrar transcripciones CLI generadas por Aleph"),
   "CLI transcript control names Aleph-generated transcripts explicitly");
ok(html.includes("Esto elimina únicamente las transcripciones CLI creadas por Aleph."),
   "CLI scope explanation says only Aleph-created transcripts are removed");
ok(html.includes("No elimina tus chats, memoria ni otros datos de Aleph."),
   "CLI explanation says chats, memory, and other Aleph data remain");
ok(!html.includes("Borrar las que generó Aleph"), "old ambiguous CLI label is gone");

ok(danger.includes("Eliminar cuenta") && danger.includes("Próximamente"),
   "account deletion is visibly marked as unavailable");
ok(!danger.includes("Borrar mi cuenta") && !danger.includes("Borrar para siempre"),
   "stub account deletion labels and irreversible claim are gone");
ok(!danger.includes("askDelete") && !danger.includes("doDelete") && !danger.includes("confirmText"),
   "account deletion has no confirmation modal or no-op handler");

ok(html.includes("Olvidar"), "per-memory control remains present");
ok(html.includes("AlephSession.clear"), "logout control remains wired");
ok(html.includes("askTx") && html.includes("doTx") && html.includes("cancelTx"),
   "CLI danger-zone flow remains wired to its existing endpoint");
ok(!/method\s*:\s*['\"]DELETE['\"]/.test(mount) && !/transcripts\/borrar/.test(mount),
   "opening Settings has no destructive request in componentDidMount");

if (failures.length) {
  console.error(`\n${failures.length} focused Settings checks failed.`);
  process.exit(1);
}
console.log("\nAll focused Settings cleanup checks passed.");
