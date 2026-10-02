#!/usr/bin/env node
/**
 * Curador determinista del piso de fábrica. Lo corre una persona.
 *
 * Un array local NO se rankea automáticamente: requiere un archivo de selección
 * explícito `{"oficio":["id-1","id-2"]}`. Así la vara aplica el límite pero no
 * disfraza una heurística de criterio editorial.
 *
 *   node qa/curar_recomendados.mjs \
 *     --input catalog/local.json --seleccion mi-seleccion.json \
 *     --output catalog/recomendados.json
 *   node qa/curar_recomendados.mjs --check
 */
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  hallarTuteo,
  normalizarEntradaCatalogo,
} from "./lib/catalogo_voz.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const KEYS = [
  "id", "nombre", "tipo", "descripcion_1linea", "official",
  "confianza", "checklist", "fuente",
];
const TIPOS = new Set(["remoto", "paquete", "hibrido"]);
const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : fallback;
};
const checking = args.includes("--check");
const inputPath = resolve(ROOT, flag("--input", "catalog/recomendados.json"));
const outputPath = resolve(ROOT, flag("--output", "catalog/recomendados.json"));
const selectionArg = flag("--seleccion", "");

function invariant(cond, message) {
  if (!cond) throw new Error(message);
}

function exactKeys(value, expected, where) {
  invariant(value && typeof value === "object" && !Array.isArray(value), `${where}: debe ser objeto`);
  const got = Object.keys(value).sort();
  const want = [...expected].sort();
  invariant(JSON.stringify(got) === JSON.stringify(want),
    `${where}: claves ${JSON.stringify(got)}; se esperaban ${JSON.stringify(want)}`);
}

export function validarEntrada(entry, where = "entrada") {
  exactKeys(entry, KEYS, where);
  invariant(typeof entry.id === "string" && entry.id.trim(), `${where}.id vacío`);
  const idParts = entry.id.split("/");
  invariant(entry.id === entry.id.trim()
      && entry.id.length <= 256
      && !/[\u0000-\u0020\u007f]/u.test(entry.id)
      && idParts.every((part) => part && part !== "." && part !== ".."),
    `${where}.id no es estable: ${entry.id}`);
  invariant(typeof entry.nombre === "string" && entry.nombre.trim(), `${where}.nombre vacío`);
  invariant(TIPOS.has(entry.tipo), `${where}.tipo inválido: ${entry.tipo}`);
  exactKeys(entry.descripcion_1linea, ["es", "en"], `${where}.descripcion_1linea`);
  invariant(entry.descripcion_1linea.es && entry.descripcion_1linea.en,
    `${where}.descripcion_1linea requiere ES y EN`);
  invariant(typeof entry.official === "boolean", `${where}.official debe ser boolean`);
  invariant(Number.isFinite(entry.confianza) && entry.confianza >= 0 && entry.confianza <= 1,
    `${where}.confianza debe estar entre 0 y 1`);
  exactKeys(entry.checklist, ["es", "en"], `${where}.checklist`);
  invariant(Array.isArray(entry.checklist.es) && entry.checklist.es.length > 0,
    `${where}.checklist.es debe tener pasos`);
  invariant(Array.isArray(entry.checklist.en) && entry.checklist.en.length > 0,
    `${where}.checklist.en debe tener pasos`);
  invariant(entry.checklist.es.every((x) => typeof x === "string" && x.trim()),
    `${where}.checklist.es contiene un paso inválido`);
  invariant(entry.checklist.en.every((x) => typeof x === "string" && x.trim()),
    `${where}.checklist.en contiene un paso inválido`);
  invariant(typeof entry.fuente === "string" && /^https:\/\//u.test(entry.fuente),
    `${where}.fuente debe ser URL https`);
  const tuteo = [
    ...hallarTuteo(entry.descripcion_1linea.es, { instruccion: false }),
    ...entry.checklist.es.flatMap((step) => hallarTuteo(step)),
  ];
  invariant(tuteo.length === 0, `${where}: tuteo residual: ${[...new Set(tuteo)].join(", ")}`);
}

export function validarCatalogo(catalog) {
  invariant(catalog && typeof catalog === "object" && !Array.isArray(catalog),
    "recomendados debe ser objeto oficio -> entradas");
  invariant(Object.keys(catalog).length > 0, "recomendados no puede quedar vacío");
  for (const [oficio, entries] of Object.entries(catalog)) {
    invariant(oficio.trim(), "oficio vacío");
    invariant(Array.isArray(entries), `${oficio}: debe ser array`);
    invariant(entries.length <= 3, `${oficio}: ${entries.length} entradas; máximo 3 por oficio`);
    invariant(entries.length > 0, `${oficio}: no puede quedar vacío`);
    const ids = new Set();
    entries.forEach((entry, i) => {
      validarEntrada(entry, `${oficio}[${i}]`);
      invariant(!ids.has(entry.id), `${oficio}: id repetido ${entry.id}`);
      ids.add(entry.id);
    });
  }
  return catalog;
}

function normalizarCatalogo(catalog) {
  return Object.fromEntries(Object.entries(catalog).map(([oficio, entries]) => [
    oficio.trim(),
    entries.map(normalizarEntradaCatalogo),
  ]));
}

async function main() {
  const raw = JSON.parse(await readFile(inputPath, "utf8"));
  let curated;
  if (Array.isArray(raw)) {
    invariant(selectionArg, "un array local requiere --seleccion (la selección es humana)");
    const selection = JSON.parse(await readFile(resolve(ROOT, selectionArg), "utf8"));
    const byId = new Map(raw.map((entry) => [entry.id, entry]));
    invariant(byId.size === raw.length, "el catálogo local tiene ids repetidos");
    curated = {};
    for (const [oficio, ids] of Object.entries(selection)) {
      invariant(Array.isArray(ids), `${oficio}: la selección debe ser array de ids`);
      invariant(ids.length <= 3, `${oficio}: ${ids.length} elegidos; máximo 3 por oficio`);
      curated[oficio] = ids.map((id) => {
        invariant(byId.has(id), `${oficio}: id ausente del corpus: ${id}`);
        return byId.get(id);
      });
    }
  } else {
    curated = raw;
  }

  const normalized = normalizarCatalogo(curated);
  validarCatalogo(normalized);
  const serialized = `${JSON.stringify(normalized, null, 2)}\n`;
  if (checking) {
    const current = await readFile(inputPath, "utf8");
    invariant(current === serialized, `${inputPath}: no está normalizado o no usa formato canónico`);
  } else {
    await writeFile(outputPath, serialized);
  }
  const total = Object.values(normalized).reduce((sum, entries) => sum + entries.length, 0);
  console.log(`VERDE · ${Object.keys(normalized).length} oficios · ${total} entradas · máximo 3 por oficio`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(`ROJO · ${error.message}`);
    process.exit(1);
  });
}
