/* sonda_bundle_deepchat.mjs — LA SONDA DEL BUNDLE (T7 · deep-chat).
 *
 * No mira el árbol de dev: arranca el SIDECAR FROZEN recién construido, con datadir
 * AISLADO, y le PIDE las cosas por HTTP. Lo que se prueba es que el binario que se va a
 * instalar SIRVE la capa de chat — no que el repo la tenga.
 *
 *   1 · deepChat.bundle.js viaja y se sirve, byte-idéntico al vendorizado.
 *   2 · aleph-chat.js (la capa compartida) viaja y se sirve.
 *   3 · sala.html y cuarto.pixi.html EMPAQUETADOS montan la capa.
 *   4 · CERO CDN: ninguna superficie referencia un host externo en sus <script>/<link>.
 *   5 · LOCAL-FIRST: la única llamada externa REAL de deep-chat (Google Fonts) sigue
 *       GUARDADA, y nuestra capa sigue seteando el font-family inline que la apaga.
 *
 * Sobre el punto 5, con precisión (el spike lo midió y conviene no mentirlo): el bundle
 * CONTIENE muchos hostnames — api.openai.com, api.anthropic.com, huggingface.co… — pero
 * son endpoints de integraciones OPT-IN (`directConnection`) que sólo se tocan si se
 * configura ese servicio, más namespaces XML de SVG (www.w3.org, que jamás se fetchean) y
 * links de documentación en console.warn. "Cero URLs externas" en el sentido literal es
 * FALSO y esta sonda no lo afirma: lo que afirma es que ninguna se dispara. El grep de
 * abajo las CLASIFICA, y el que no se dispare ninguna lo prueba el runtime —
 * verify_aleph_chat / verify_sala_deepchat / verify_guia_deepchat corren en WebKit con
 * TODO request no-local abortado y cuentan cero.
 *
 *   node qa/sonda_bundle_deepchat.mjs
 *   ALEPH_SIDECAR_BIN=<ruta> node qa/sonda_bundle_deepchat.mjs
 */
import { spawn } from "node:child_process";
// GUARD _MEI (integración tanda-P): TMPDIR privado por sidecar + barrido en TODA salida.
// El bootloader onefile deja ~170 MB en `_MEI*` si el proceso no cierra limpio; 91 huérfanos
// llenaron el disco el 26-jul. Ver qa/lib/frozen_guard.mjs y qa/verify_frozen_guard.mjs.
import { spawnFrozen, matarFrozen } from "./lib/frozen_guard.mjs";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SIDECAR = process.env.ALEPH_SIDECAR_BIN ||
  join(ROOT, "deploy/fase4/aleph-shell/src-tauri/binaries/aleph_sidecar-aarch64-apple-darwin");
const PORT = Number(process.env.SONDA_PORT || 8243);
const BASE = `http://127.0.0.1:${PORT}`;
const DATADIR = mkdtempSync(join(tmpdir(), "sonda-dc-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const fails = [];
const ok = (c, l, x) => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  — " + x : ""}`); if (!c) fails.push(l); };
const sha = (b) => createHash("sha256").update(b).digest("hex");

if (!existsSync(SIDECAR)) { console.log(`✗ no existe el sidecar frozen: ${SIDECAR}`); process.exit(1); }
console.log(`── sidecar FROZEN ${SIDECAR}\n── datadir aislado ${DATADIR}\n`);

const proc = spawnFrozen(SIDECAR, ["--port", String(PORT)], {
  env: { ...process.env, ALEPH_ROLE: "client", ALEPH_DATA_DIR: DATADIR },
  stdio: ["ignore", "pipe", "pipe"],
});
let salida = "";
proc.stdout.on("data", (d) => (salida += d));
proc.stderr.on("data", (d) => (salida += d));

let vivo = false;
for (let i = 0; i < 140; i++) {
  try { const r = await fetch(BASE + "/health"); if (r.ok) { vivo = true; break; } } catch {}
  await sleep(500);
}
ok(vivo, "el sidecar frozen arranca y contesta /health", vivo ? "" : salida.slice(-500));
if (!vivo) { proc.kill(); process.exit(1); }

const get = async (p) => {
  const r = await fetch(BASE + p);
  return { status: r.status, buf: Buffer.from(await r.arrayBuffer()) };
};

try {
  // ── 1 · el bundle viaja, y es EL MISMO ──────────────────────────────────────────
  const b = await get("/vendor/deepChat.bundle.js");
  ok(b.status === 200, "deepChat.bundle.js se sirve desde el binario", `HTTP ${b.status}`);
  const local = readFileSync(join(ROOT, "product/app/design/vendor/deepChat.bundle.js"));
  ok(b.status === 200 && sha(b.buf) === sha(local),
     "…y es byte-idéntico al vendorizado (el que certificó el spike)",
     `${b.buf.length} bytes · sha ${sha(b.buf).slice(0, 12)}`);
  const lic = await get("/vendor/deep-chat.LICENSE");
  ok(lic.status === 200, "la licencia MIT viaja con él");

  // ── 2 · la capa compartida viaja ────────────────────────────────────────────────
  const layer = await get("/chat/aleph-chat.js");
  ok(layer.status === 200, "aleph-chat.js (la capa compartida) se sirve", `HTTP ${layer.status}`);
  const layerTxt = layer.buf.toString();
  ok(/font-family/.test(layerTxt) && /FONT_STACK/.test(layerTxt),
     "…y sigue seteando el font-family inline (lo que apaga Google Fonts)");
  ok(/assertLocalFirst/.test(layerTxt), "…y sigue trayendo la verificación de local-first en runtime");

  // ── 3 · las dos superficies EMPAQUETADAS montan la capa ─────────────────────────
  const sala = (await get("/sala/sala.html")).buf.toString();
  ok(/chat\/aleph-chat\.js/.test(sala), "el sala.html empaquetado importa la capa compartida");
  ok(/id="chatBody"/.test(sala), "…y trae el punto de montaje de la conversación");
  const cuarto = (await get("/cuarto/cuarto.pixi.html")).buf.toString();
  ok(/chat\/aleph-chat\.js/.test(cuarto), "el cuarto.pixi.html empaquetado importa la capa compartida");
  ok(/id="copBody"/.test(cuarto), "…y trae el punto de montaje del Guía");

  // ── 4 · CERO CDN en nuestras superficies ────────────────────────────────────────
  const cdn = (html, quien) => {
    const refs = [...html.matchAll(/(?:src|href)\s*=\s*["']([^"']+)["']/gi)].map((m) => m[1]);
    return refs.filter((u) => /^(https?:)?\/\//i.test(u) && !/^https?:\/\/(127\.0\.0\.1|localhost)/i.test(u));
  };
  const cSala = cdn(sala), cCuarto = cdn(cuarto);
  ok(cSala.length === 0, "sala.html no referencia NINGÚN host externo", cSala.join(" · ") || "ninguno");
  ok(cCuarto.length === 0, "cuarto.pixi.html no referencia NINGÚN host externo", cCuarto.join(" · ") || "ninguno");

  // ── 5 · LOCAL-FIRST: la guarda de Google Fonts sigue en pie ─────────────────────
  const bt = b.buf.toString();
  ok(/fonts\.googleapis\.com/.test(bt), "el bundle SÍ trae la URL de Google Fonts (no se oculta el hecho)");
  ok(/DEFAULT_INTER_STACK|attemptAppendStyleSheetToHead/.test(bt),
     "…pero la inyección sigue GUARDADA por el fontFamily (por eso el inline la apaga)");
  ok(!/sendBeacon|gtag\(|mixpanel|posthog|segment\.com/.test(bt),
     "cero telemetría / analytics en el bundle");

  /* CLASIFICACIÓN EXPLÍCITA de los hosts que viven dentro del bundle.
   *
   * Es a propósito una lista y no un regex laxo: así, el día que se suba de versión el
   * bundle, cualquier host NUEVO cae en "sin clasificar" y esta sonda se pone roja. Ése es
   * el punto — que un host nuevo no entre en silencio. El veredicto de que ninguno se
   * dispara es de RUNTIME (las varas WebKit con todo request no-local abortado); acá sólo
   * se audita qué hay adentro. */
  // se clasifica por DOMINIO, no por prefijo: api-inference.huggingface.co y
  // dashboard.cohere.ai son el mismo proveedor que api.huggingface / cohere.
  const OPT_IN = /(openai|anthropic|groq|huggingface|cohere|mistral|deepseek|stability|together|assemblyai|openrouter|perplexity|minimax|minimaxi|moonshot|dify|bigmodel|alibabacloud|aliyuncs|microsofttranslator|cognitive|azure)\.|(^|\.)x\.ai$|^aistudio\.google\.com$/;
  const NAMESPACE = /(w3\.org|inkscape|sodipodi|purl\.org|creativecommons)/;
  const DOCS = /(deepchat\.dev|learn\.microsoft\.com|docs\.|github\.com|githubusercontent|aka\.ms|www\.assemblyai|www\.perplexity|www\.minimaxi|www\.alibabacloud|googleapis\.com)/;

  const hosts = [...new Set([...bt.matchAll(/https?:\/\/([a-z0-9.-]+\.[a-z]{2,})/gi)].map((m) => m[1].toLowerCase()))];
  const ns = hosts.filter((h) => NAMESPACE.test(h));
  const docs = hosts.filter((h) => !ns.includes(h) && DOCS.test(h));
  const optIn = hosts.filter((h) => !ns.includes(h) && !docs.includes(h) && OPT_IN.test(h));
  const otros = hosts.filter((h) => !optIn.includes(h) && !ns.includes(h) && !docs.includes(h));
  console.log(`\n  hosts dentro del bundle (${hosts.length}): ${optIn.length} endpoints opt-in · ${ns.length} namespaces XML · ${docs.length} links de doc · ${otros.length} sin clasificar`);
  if (otros.length) console.log("    sin clasificar: " + otros.join(" · "));
  ok(otros.length === 0,
     "todo host del bundle queda CLASIFICADO (endpoint opt-in · namespace XML · link de doc)",
     otros.join(" · ") || `${hosts.length} hosts, ninguno suelto`);
  console.log("  · que NINGUNO se dispare lo prueban las varas de runtime (WebKit, todo request\n    no-local abortado): verify_aleph_chat · verify_sala_deepchat · verify_guia_deepchat.");
} finally {
  proc.kill();
}

console.log(`\n══ ${fails.length ? "FALLARON " + fails.length : "TODO VERDE"} ══`);
fails.forEach((f) => console.log("  ✗ " + f));
process.exit(fails.length ? 1 : 0);
