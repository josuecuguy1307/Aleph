#!/usr/bin/env node
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import {
  deduplicarPasos,
  normalizarEntradaCatalogo,
  normalizarEs,
} from "./lib/catalogo_voz.mjs";
import { validarCatalogo } from "./curar_recomendados.mjs";

let green = 0;
const ok = (label, run) => {
  run();
  green++;
  console.log(`✓ ${label}`);
};

const bundleSpec = await readFile(
  resolve(import.meta.dirname, "../deploy/fase4/aleph_sidecar.spec"),
  "utf8",
);
ok("el catálogo completo viaja como data del bundle", () => {
  assert.match(bundleSpec, /_DATA_DIRS\s*=\s*\["catalog"/u);
});

ok("normaliza tuteo a voseo", () => {
  assert.equal(normalizarEs("Pégala aquí. Después prueba de nuevo."), "Pegá tu llave acá. Después probá de nuevo.");
  assert.equal(normalizarEs("Si quieres, puedes quitarla."), "Si querés, podés quitarla.");
  assert.equal(normalizarEs("Ahora compárteme una página; toca y elige."),
    "Ahora compartime una página; tocá y elegí.");
  assert.equal(normalizarEs("Pedí una llave. genérala y pégala aquí."),
    "Pedí una llave. Generala y pegá tu llave acá.");
});

ok("dedupe semántico de instrucciones equivalentes", () => {
  assert.deepEqual(
    deduplicarPasos(["Pégala aquí.", "Pegá tu llave acá.", "Probá la conexión."], "es"),
    ["Pegá tu llave acá.", "Probá la conexión."],
  );
});

const base = {
  id: "com.stripe/mcp",
  nombre: "MCP Demo",
  tipo: "remoto",
  descripcion_1linea: { es: "Consulta datos públicos.", en: "Queries public data." },
  official: true,
  confianza: 0.93,
  checklist: {
    es: ["Pégala aquí.", "Pegá tu llave acá.", "Probá la conexión."],
    en: ["Paste your key here.", "Paste the key here.", "Test the connection."],
  },
  fuente: "https://example.com/mcp",
};

ok("entrada limpia conserva el schema exacto y deduplica", () => {
  const entry = normalizarEntradaCatalogo(base);
  assert.deepEqual(Object.keys(entry), [
    "id", "nombre", "tipo", "descripcion_1linea", "official",
    "confianza", "checklist", "fuente",
  ]);
  assert.equal(entry.checklist.es.length, 2);
  assert.equal(entry.checklist.en.length, 2);
  validarCatalogo({ pagos: [entry] });
});

ok("la vara rechaza cuatro recomendaciones en un oficio", () => {
  assert.throws(() => validarCatalogo({
    research: [0, 1, 2, 3].map((i) => ({ ...normalizarEntradaCatalogo(base), id: `demo-${i}` })),
  }), /máximo 3 por oficio/u);
});

ok("la vara no disfraza tipos inválidos mediante coerción", () => {
  assert.throws(() => validarCatalogo({
    pagos: [normalizarEntradaCatalogo({ ...base, official: "true" })],
  }), /official debe ser boolean/u);
});

const temp = await mkdtemp(resolve(tmpdir(), "aleph-curador-"));
try {
  const corpusPath = resolve(temp, "local.json");
  const selectionPath = resolve(temp, "selection.json");
  const outputPath = resolve(temp, "recomendados.json");
  const fixtureIds = ["com.stripe/mcp", "demo-1", "demo-2", "demo-3"];
  await writeFile(corpusPath, `${JSON.stringify(
    fixtureIds.map((id) => ({ ...base, id })),
    null, 2,
  )}\n`);
  await writeFile(selectionPath, JSON.stringify({
    research: ["com.stripe/mcp", "demo-1", "demo-2"],
  }));
  const result = spawnSync(process.execPath, [
    resolve(import.meta.dirname, "curar_recomendados.mjs"),
    "--input", corpusPath,
    "--seleccion", selectionPath,
    "--output", outputPath,
  ], { encoding: "utf8" });
  ok("curador CLI aplica selección humana de tres", () => {
    assert.equal(result.status, 0, result.stderr);
  });
  const output = JSON.parse(await readFile(outputPath, "utf8"));
  ok("salida CLI queda bajo el tope y normalizada", () => {
    assert.equal(output.research.length, 3);
    assert.equal(output.research[0].id, "com.stripe/mcp");
    assert.deepEqual(output.research[0].checklist.es,
      ["Pegá tu llave acá.", "Probá la conexión."]);
  });

  const runtimePath = resolve(temp, "runtime-local.json");
  await writeFile(runtimePath, `${JSON.stringify([base], null, 2)}\n`);
  const runtimeSweep = spawnSync(process.execPath, [
    resolve(import.meta.dirname, "normalizar_catalogo_local.mjs"),
    "--local", runtimePath,
  ], { encoding: "utf8" });
  ok("el barrido one-time acepta el catálogo runtime explícito", () => {
    assert.equal(runtimeSweep.status, 0, runtimeSweep.stderr);
  });
  const runtime = JSON.parse(await readFile(runtimePath, "utf8"));
  ok("el catálogo runtime queda voseante y sin pasos repetidos", () => {
    assert.deepEqual(runtime[0].checklist.es,
      ["Pegá tu llave acá.", "Probá la conexión."]);
  });
} finally {
  await rm(temp, { recursive: true, force: true });
}

console.log(`\nVERDE · ${green}/${green} checks`);
