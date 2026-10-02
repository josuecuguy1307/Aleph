import fs from "node:fs";
import path from "node:path";

function listJsonFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function flattenKeys(obj, prefix = "") {
  const keys = [];
  if (!obj || typeof obj !== "object") return keys;
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) keys.push(...flattenKeys(v, next));
    else keys.push(next);
  }
  return keys;
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll("\\", "/");
}

const webRoot = path.resolve(process.cwd());
const localesRoot = path.join(webRoot, "locales");
const enRoot = path.join(localesRoot, "en");
const zhRoot = path.join(localesRoot, "zh");
const esRoot = path.join(localesRoot, "es");

if (!fs.existsSync(enRoot) || !fs.existsSync(zhRoot) || !fs.existsSync(esRoot)) {
  console.error(`[i18n:parity] Missing locales roots: ${enRoot}, ${zhRoot}, or ${esRoot}`);
  process.exit(2);
}

const enFiles = listJsonFiles(enRoot).map((p) => toRel(p, enRoot)).sort();
const zhFiles = listJsonFiles(zhRoot).map((p) => toRel(p, zhRoot)).sort();
const esFiles = listJsonFiles(esRoot).map((p) => toRel(p, esRoot)).sort();

const missingInZh = enFiles.filter((f) => !zhFiles.includes(f));
const extraInZh = zhFiles.filter((f) => !enFiles.includes(f));
const missingInEs = enFiles.filter((f) => !esFiles.includes(f));
const extraInEs = esFiles.filter((f) => !enFiles.includes(f));

let ok = true;
if (missingInZh.length) {
  ok = false;
  console.error("[i18n:parity] Missing zh files:");
  for (const f of missingInZh) console.error(`- ${f}`);
}
if (extraInZh.length) {
  ok = false;
  console.error("[i18n:parity] Extra zh files:");
  for (const f of extraInZh) console.error(`- ${f}`);
}
if (missingInEs.length) {
  ok = false;
  console.error("[i18n:parity] Missing es files:");
  for (const f of missingInEs) console.error(`- ${f}`);
}
if (extraInEs.length) {
  ok = false;
  console.error("[i18n:parity] Extra es files:");
  for (const f of extraInEs) console.error(`- ${f}`);
}

for (const rel of enFiles) {
  if (!zhFiles.includes(rel)) continue;
  const enPath = path.join(enRoot, rel);
  const zhPath = path.join(zhRoot, rel);
  const esPath = path.join(esRoot, rel);
  const enJson = loadJson(enPath);
  const zhJson = loadJson(zhPath);
  const esJson = loadJson(esPath);
  const enKeys = new Set(flattenKeys(enJson));
  const zhKeys = new Set(flattenKeys(zhJson));
  const esKeys = new Set(flattenKeys(esJson));

  const missingKeys = [...enKeys].filter((k) => !zhKeys.has(k)).sort();
  const extraKeys = [...zhKeys].filter((k) => !enKeys.has(k)).sort();
  const missingEsKeys = [...enKeys].filter((k) => !esKeys.has(k)).sort();
  const extraEsKeys = [...esKeys].filter((k) => !enKeys.has(k)).sort();

  if (missingKeys.length || extraKeys.length) {
    ok = false;
    console.error(`[i18n:parity] Key mismatch in ${rel}`);
    if (missingKeys.length) {
      console.error("  Missing zh keys:");
      for (const k of missingKeys) console.error(`  - ${k}`);
    }
    if (extraKeys.length) {
      console.error("  Extra zh keys:");
      for (const k of extraKeys) console.error(`  - ${k}`);
    }
  }
  if (missingEsKeys.length || extraEsKeys.length) {
    ok = false;
    console.error(`[i18n:parity] Key mismatch in es/${rel}`);
    for (const k of missingEsKeys) console.error(`  Missing es: ${k}`);
    for (const k of extraEsKeys) console.error(`  Extra es: ${k}`);
  }
}

if (!ok) process.exit(1);
console.log("[i18n:parity] OK");
