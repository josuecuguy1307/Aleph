/* ============================================================================
 * sonda_vocabulario.mjs — mide los DOS registros de render SIN navegador.
 * [Gate 4 · Fase 2 · obra 2.3]
 *
 * Los dos registros son JS; la vara del vocabulario es Python. En vez de leer los
 * archivos con un regex —que mide intenciones, no hechos— esta sonda los IMPORTA
 * en node con un shim mínimo de DOM y reporta lo que hacen de verdad: qué tipos
 * cubre cada uno, y a qué renderer despacha cada nombre/alias.
 *
 * El shim NO dibuja nada: `createElement` devuelve un objeto que anota sus
 * atributos. Alcanza porque `render()` estampa `data-artifact-type` ANTES de
 * llamar al renderer — la decisión de despacho, que es lo que se mide acá. Los
 * píxeles los mide la vara de navegador, contra la .app instalada.
 *
 *   node qa/lib/sonda_vocabulario.mjs <repo-root> ['["doc","table",…]']  → JSON
 * ========================================================================== */
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const ROOT = process.argv[2];
if (!ROOT) { console.error("uso: sonda_vocabulario.mjs <repo-root> [probesJSON]"); process.exit(2); }
const PROBES = process.argv[3] ? JSON.parse(process.argv[3]) : [];

/* ── shim de DOM mínimo (no dibuja: anota) ─────────────────────────────────── */
function fakeEl() {
  const el = {
    __attrs: {}, className: "", innerHTML: "", style: {}, children: [],
    setAttribute(k, v) { this.__attrs[k] = String(v); },
    getAttribute(k) { return this.__attrs[k]; },
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeAttribute() {},
    remove() {},
  };
  return el;
}
globalThis.window = globalThis;
globalThis.document = {
  currentScript: null,
  head: fakeEl(), body: fakeEl(),
  createElement: () => fakeEl(),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
};

const url = (rel) => pathToFileURL(join(ROOT, rel)).href;

const AR = await import(url("product/app/design/render/render.js"));
await import(url("product/app/design/render/sala-render.js"));      // IIFE → window.SalaRender
const SR = window.SalaRender;
const VOCAB = window.AlephVocabulary;

/* ── despacho REAL, tipo por tipo ──────────────────────────────────────────── */
function alephDispatch(t) {
  try { return AR.render(t, { content: "x" }).__attrs["data-artifact-type"] || null; }
  catch (e) { return "ERROR:" + (e && e.message); }
}

const out = {
  vocabulary: {
    schema_version: VOCAB.SCHEMA_VERSION,
    canonical: VOCAB.CANONICAL,
    aliases: VOCAB.ALIASES,
    advisory_fields: VOCAB.ADVISORY_FIELDS,
    producible: VOCAB.producibleByLlm(),
    rich: VOCAB.richCapture(),
  },
  aleph: AR.coverage(),
  sala: SR.coverage(),
  dispatch: {},          // nombre → { aleph: <renderer>, sala: <renderer> }
};

const names = [...new Set([...VOCAB.CANONICAL, ...Object.keys(VOCAB.ALIASES), ...PROBES])];
for (const n of names) {
  out.dispatch[n] = { aleph: alephDispatch(n), sala: SR.resolveType(n) };
}

console.log(JSON.stringify(out));
