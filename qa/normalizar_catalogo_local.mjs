#!/usr/bin/env node
/**
 * Barrido one-time de voz del catálogo histórico.
 *
 *   node qa/normalizar_catalogo_local.mjs
 *   node qa/normalizar_catalogo_local.mjs --check
 *   node qa/normalizar_catalogo_local.mjs --local /ruta/runtime/catalog/local.json
 */
import { readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  hallarTuteo,
  normalizarEntradaCatalogo,
  normalizarOnboarding,
} from "./lib/catalogo_voz.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const ONBOARDING = resolve(ROOT, "catalog/connectors/onboarding");
const ARGS = process.argv.slice(2);
const CHECK = ARGS.includes("--check");
const flag = (name, fallback = "") => {
  const i = ARGS.indexOf(name);
  return i >= 0 ? ARGS[i + 1] : fallback;
};
const RUNTIME_LOCAL = flag("--local", process.env.ALEPH_LOCAL_CATALOG_PATH || "");
let changed = 0;
let failed = 0;

function productStrings(manifest) {
  const values = [];
  const take = (v) => typeof v === "string" && values.push(v);
  ["capability_line", "trust_line", "restricted_fallback", "unverified_line",
    "share_instruction"].forEach((k) => take(manifest[k]));
  (manifest.steps || []).forEach((s) => take(s?.txt));
  (manifest.permissions || []).forEach(take);
  Object.values(manifest.errors || {}).forEach(take);
  (manifest.credential_fields || []).forEach((f) => { take(f?.label); take(f?.shape); });
  return values;
}

for (const name of (await readdir(ONBOARDING)).filter((n) => n.endsWith(".json")).sort()) {
  const path = resolve(ONBOARDING, name);
  const original = JSON.parse(await readFile(path, "utf8"));
  const normalized = normalizarOnboarding(original);
  const before = `${JSON.stringify(original, null, 2)}\n`;
  const after = `${JSON.stringify(normalized, null, 2)}\n`;
  const tuteo = productStrings(normalized).flatMap(hallarTuteo);
  if (tuteo.length) {
    failed++;
    console.error(`✗ ${name}: tuteo residual: ${[...new Set(tuteo)].join(", ")}`);
  }
  if (before !== after) {
    changed++;
    if (!CHECK) await writeFile(path, after);
    else console.error(`✗ ${name}: falta aplicar el barrido`);
  }
}

const localPaths = new Set([resolve(ROOT, "catalog/local.json")]);
if (RUNTIME_LOCAL) localPaths.add(resolve(RUNTIME_LOCAL));
for (const localPath of localPaths) {
  try {
    const local = JSON.parse(await readFile(localPath, "utf8"));
    if (!Array.isArray(local)) throw new Error(`${localPath}: debe ser un array`);
    const normalized = local.map(normalizarEntradaCatalogo);
    const before = `${JSON.stringify(local, null, 2)}\n`;
    const after = `${JSON.stringify(normalized, null, 2)}\n`;
    if (before !== after) {
      changed++;
      if (!CHECK) await writeFile(localPath, after);
      else console.error(`✗ ${localPath}: falta aplicar el barrido`);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    if (RUNTIME_LOCAL && localPath === resolve(RUNTIME_LOCAL)) throw error;
  }
}

if (failed || (CHECK && changed)) {
  console.error(`\nROJO · ${failed} archivo(s) con voz inválida · ${changed} pendiente(s)`);
  process.exit(1);
}
console.log(`VERDE · ${changed} archivo(s) normalizado(s) · español voseante · inglés limpio`);
