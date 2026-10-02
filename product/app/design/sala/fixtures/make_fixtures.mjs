/* make_fixtures.mjs — genera los fixtures de obra rica ESPEJO de los productores reales.
 * Cada forma copia el contrato del server que la emite (fem_server.py:167-194,
 * backtest_server.py:226-262, precio_server.py:369-381, segmentacion_server.py:467-536).
 * Correr una vez y commitear el output: `node make_fixtures.mjs` (regenera en el mismo dir). */
import fs from "node:fs";
const DIR = new URL(".", import.meta.url).pathname;

/* campo gaussiano nx×ny escalado a [lo,hi] — mismo espíritu que gaussField de samples.js */
function gauss(nx, ny, lo, hi) {
  const v = [];
  for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
    const dx = (x - nx * 0.6) / (nx * 0.28), dy = (y - ny * 0.45) / (ny * 0.3);
    v.push(Math.round((lo + (hi - lo) * Math.exp(-(dx * dx + dy * dy))) * 100) / 100);
  }
  return v;
}
const grid = (nx, ny, lo, hi, unit) => ({ nx, ny, values: gauss(nx, ny, lo, hi), min: lo, max: hi, unit, interpolate: true });

/* fem: von Mises baja 420→180 contra límite 250 (FALLA→PASA, rojo→verde) */
fs.writeFileSync(DIR + "fem.convergence.json", JSON.stringify({
  type: "convergence", title: "Convergencia FEM (fixture)",
  metric: { name: "von Mises", unit: "MPa", goal: "min" }, limit: 250,
  iterations: [
    { n: 1, value: 420, passed: false, grid: grid(24, 12, 12, 420, "MPa") },
    { n: 2, value: 291, passed: false, grid: grid(24, 12, 11, 291, "MPa") },
    { n: 3, value: 180, passed: true,  grid: grid(24, 12, 9, 180, "MPa") },
  ],
}, null, 1));

/* quant: Sharpe sube 0.62→1.31 contra objetivo 1.2 (goal max) con curva de equity */
const curve = (drift, vol, n = 120) => {
  let v = 1, out = [];
  for (let i = 0; i < n; i++) { v *= 1 + drift + vol * Math.sin(i * 0.7 + drift * 90) * 0.6; out.push(Math.round(v * 1000) / 1000); }
  return out;
};
fs.writeFileSync(DIR + "quant.convergence.json", JSON.stringify({
  type: "convergence", title: "Backtest de cartera (fixture)",
  metric: { name: "Sharpe", unit: "", goal: "max", limit: 1.2 }, limit: 1.2,
  iterations: [
    { n: 1, value: 0.62, passed: false, curve: curve(0.0006, 0.004) },
    { n: 2, value: 0.97, passed: false, curve: curve(0.0011, 0.003) },
    { n: 3, value: 1.31, passed: true,  curve: curve(0.0016, 0.002) },
  ],
}, null, 1));

/* finanzas: serie temporal del worldbank (finanzas_data_server._worldbank_series →
 * *.linechart.json en PUPPET_WORKDIR) — labels=años, series con los valores REALES */
fs.writeFileSync(DIR + "finanzas.linechart.json", JSON.stringify({
  type: "linechart", title: "PIB (US$ a precios actuales) — Ecuador (fixture)",
  labels: ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
  series: [{ name: "PIB (US$ a precios actuales)",
             data: [104295862352, 107562008367, 108108429407, 99291223662, 106165866471, 115049476370, 118844928707] }],
  source: "World Bank Open Data — NY.GDP.MKTP.CD, Ecuador (fixture)",
}, null, 1));

/* fem fieldplot suelto (sin iteraciones) — el OTRO tipo que el filtro de hoy acepta */
fs.writeFileSync(DIR + "fem.fieldplot.json", JSON.stringify({
  type: "fieldplot", title: "von Mises (fixture)", slice: "z=0",
  grid: grid(32, 16, 8, 310, "MPa"), limit: 250,
}, null, 1));

/* electrónica: BOM planilla con precios — HOY se dropea (el bug a probar) */
fs.writeFileSync(DIR + "electronica.planilla.json", JSON.stringify({
  type: "planilla", title: "BOM del filtro RC (fixture)", source: "digikey",
  cols: ["Ref", "Parte", "Valor", "Precio USD"],
  rows: [["R1", "RC0805FR-0710KL", "10 kΩ", "0.10"], ["C1", "CL21B104KBCNNNC", "100 nF", "0.15"],
         ["U1", "MCP6001T-I/OT", "op-amp", "0.42"], ["J1", "PJ-102A", "jack", "0.65"]],
}, null, 1));

/* medicina: volumen 3D — tetraedro mínimo verts Float32 + faces Uint32 en base64 */
const verts = new Float32Array([0, 0, 0, 40, 0, 0, 20, 34, 0, 20, 12, 32]);
const faces = new Uint32Array([0, 1, 2, 0, 1, 3, 1, 2, 3, 0, 2, 3]);
const b64 = (ta) => Buffer.from(ta.buffer).toString("base64");
fs.writeFileSync(DIR + "medicina.volume3d.json", JSON.stringify({
  type: "volume3d", structure: "pulmon", structure_label: "Pulmón (fixture)",
  title: "Volumen segmentado (fixture)", color: [122, 199, 156],
  n_vertices: 4, n_triangles: 4, vertices_b64: b64(verts), faces_b64: b64(faces),
  source: "fixture",
}, null, 1));

/* medicina: CT slice como imagen data-uri (PNG real 4×4 gris, magic bytes válidos) */
const png4 = "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAFklEQVR4nGP8//8/AzGAiShVoxqxAQCFJgMB4/rq3AAAAABJRU5ErkJggg==";
fs.writeFileSync(DIR + "medicina.imagen.json", JSON.stringify({
  type: "imagen", title: "CT slice (fixture)", alt: "corte axial (fixture)",
  content: "data:image/png;base64," + png4,
}, null, 1));

console.log("fixtures regenerados en " + DIR);
