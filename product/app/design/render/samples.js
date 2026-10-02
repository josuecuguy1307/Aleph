/* ============================================================================
 * samples.js — PAYLOADS DE EJEMPLO REALES, uno por artifactType (DONE-BAR de T3).
 * Reusable por la demo y por los tests de T1/T2. Los datos 3D/campo/dicom se
 * GENERAN (geometría/campo/phantom reales), no son imágenes pegadas.
 * ========================================================================== */

// ── cubo ASCII STL real (12 facetas) para `cad` ─────────────────────────────
function cubeSTL(s) {
  s = s || 1;
  var v = [[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0], [0, 0, s], [s, 0, s], [s, s, s], [0, s, s]];
  // caras como pares de triángulos + normal
  var faces = [
    [[0, 1, 2], [0, 2, 3], [0, 0, -1]],   // bottom
    [[4, 6, 5], [4, 7, 6], [0, 0, 1]],    // top
    [[0, 5, 1], [0, 4, 5], [0, -1, 0]],   // front
    [[3, 2, 6], [3, 6, 7], [0, 1, 0]],    // back
    [[0, 7, 4], [0, 3, 7], [-1, 0, 0]],   // left
    [[1, 5, 6], [1, 6, 2], [1, 0, 0]],    // right
  ];
  var out = "solid cube\n";
  faces.forEach(function (f) {
    var n = f[2];
    [f[0], f[1]].forEach(function (tri) {
      out += "  facet normal " + n.join(" ") + "\n    outer loop\n";
      tri.forEach(function (idx) { out += "      vertex " + v[idx].join(" ") + "\n"; });
      out += "    endloop\n  endfacet\n";
    });
  });
  return out + "endsolid cube\n";
}

// ── campo escalar gaussiano (OpenFOAM-style) para `fieldplot` ───────────────
function gaussField(nx, ny) {
  var vals = [];
  for (var y = 0; y < ny; y++) for (var x = 0; x < nx; x++) {
    var u = (x / (nx - 1) - 0.5) * 2, w = (y / (ny - 1) - 0.5) * 2;
    var g1 = Math.exp(-((u - 0.35) * (u - 0.35) + (w - 0.2) * (w - 0.2)) / 0.12);
    var g2 = 0.6 * Math.exp(-((u + 0.4) * (u + 0.4) + (w + 0.45) * (w + 0.45)) / 0.07);
    vals.push((g1 + g2) * 320 + 295);   // ~295–650 K, parecido a un campo de temperatura
  }
  return { nx: nx, ny: ny, values: vals, unit: "K" };
}

// ── OHLC sintético (random-walk determinístico) para el fence candlestick ───
function genOHLC(n) {
  var labels = [], ohlc = [], px = 42;
  for (var i = 0; i < n; i++) {
    var drift = Math.sin(i * 0.55) * 1.6 + Math.cos(i * 1.7) * 0.9;
    var o = Math.round(px * 100) / 100;
    var c = Math.round((px + drift) * 100) / 100;
    var h = Math.round((Math.max(o, c) + 0.8 + Math.abs(Math.sin(i * 2.1))) * 100) / 100;
    var l = Math.round((Math.min(o, c) - 0.8 - Math.abs(Math.cos(i * 1.3))) * 100) / 100;
    labels.push("d" + (i + 1)); ohlc.push([o, h, l, c]); px = c;
  }
  return { labels: labels, ohlc: ohlc };
}

// ── campo FEM (von Mises) escalado a un pico dado, para `convergence` ───────
// Reusa la forma del gaussiano pero en MPa y con el máximo clavado en `peak`:
// así cada iteración del loop trae SU campo (rojo sobre el límite → verde bajo él).
function femField(nx, ny, peak) {
  var g = gaussField(nx, ny), lo = 295, hi = 650;   // rango del gaussiano base
  var vals = g.values.map(function (v) { return Math.round(((v - lo) / (hi - lo)) * peak * 100) / 100; });
  return { nx: nx, ny: ny, values: vals, min: 0, max: peak, unit: "MPa", interpolate: true };
}

// ── phantom de tomografía para `dicom` (pixeles reales, no imagen) ──────────
function phantom(n) {
  var data = new Float32Array(n * n);
  function ell(cx, cy, rx, ry, val) {
    for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) {
      var u = (x / n - cx) / rx, w = (y / n - cy) / ry;
      if (u * u + w * w <= 1) data[y * n + x] += val;
    }
  }
  ell(0.5, 0.5, 0.42, 0.5, 900);   // cráneo
  ell(0.5, 0.52, 0.36, 0.44, -350); // modelo
  ell(0.40, 0.42, 0.09, 0.13, 180);
  ell(0.62, 0.42, 0.09, 0.13, 180);
  ell(0.5, 0.66, 0.16, 0.10, -120);
  return { width: n, height: n, data: data, wc: 480, ww: 720 };
}

// ── esquemático SVG (representativo de un export KiCad) para `schematic` ────
var SCHEMATIC_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 200" font-family="monospace" font-size="9">' +
  '<rect x="0" y="0" width="360" height="200" fill="#fffdf5"/>' +
  '<g stroke="#1a3d1a" stroke-width="1.6" fill="none">' +
  '<line x1="40" y1="60" x2="40" y2="140"/>' +              // batería rail izq
  '<line x1="30" y1="70" x2="50" y2="70"/><line x1="34" y1="78" x2="46" y2="78"/>' +
  '<line x1="30" y1="86" x2="50" y2="86"/><line x1="36" y1="94" x2="44" y2="94"/>' +
  '<line x1="40" y1="60" x2="140" y2="60"/>' +              // top wire
  '<path d="M140 60 l6 -8 l12 16 l12 -16 l12 16 l12 -16 l6 8" />' + // resistor zigzag
  '<line x1="206" y1="60" x2="300" y2="60"/>' +
  '<circle cx="300" cy="92" r="14"/>' +                    // LED body
  '<path d="M293 86 l14 12 M307 86 l0 12 M293 86 l0 12 M311 80 l5 -5 M305 84 l5 -5" stroke="#1a3d1a"/>' +
  '<line x1="300" y1="60" x2="300" y2="78"/>' +
  '<line x1="300" y1="106" x2="300" y2="140"/>' +
  '<line x1="40" y1="140" x2="300" y2="140"/>' +           // ground wire
  '</g>' +
  '<g fill="#1a3d1a">' +
  '<text x="150" y="48">R1 330Ω</text>' +
  '<text x="318" y="95">D1</text>' +
  '<text x="14" y="108">9V</text>' +
  '<text x="150" y="158">GND</text>' +
  '</g></svg>';

// ── mesh 3D de demo para `volume3d`: una esfera UV (verts Float32 + faces Uint32 → base64).
// Sintético, como el cubo de `cad` o el phantom de `dicom`; la anatomía REAL la genera el
// server (marching cubes sobre la máscara del CT). El renderer no distingue: necesita verts+faces.
function _b64FromBytes(u8) {
  var s = ""; for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
  return (typeof btoa !== "undefined") ? btoa(s) : Buffer.from(u8).toString("base64");
}
function demoVolumeMesh(seg) {
  seg = seg || 28;
  var verts = [], faces = [], row = seg + 1, i, j;
  for (i = 0; i <= seg; i++) {
    var phi = (i / seg) * Math.PI;
    for (j = 0; j <= seg; j++) {
      var th = (j / seg) * 2 * Math.PI;
      verts.push(Math.sin(phi) * Math.cos(th), Math.cos(phi), Math.sin(phi) * Math.sin(th));
    }
  }
  for (i = 0; i < seg; i++) for (j = 0; j < seg; j++) {
    var a = i * row + j, b = a + row;
    faces.push(a, b, a + 1, a + 1, b, b + 1);
  }
  var vf = new Float32Array(verts), ff = new Uint32Array(faces);
  return {
    vertices_b64: _b64FromBytes(new Uint8Array(vf.buffer)),
    faces_b64: _b64FromBytes(new Uint8Array(ff.buffer)),
    n_vertices: vf.length / 3, n_triangles: ff.length / 3,
  };
}

export const SAMPLES = {
  informe: {
    type: "informe",
    title: "Resumen trimestral · ventas",
    content:
      "## Ventas Q2 2026\n\nEl **margen bruto** subió a **42 %** [1], impulsado por el canal directo.\n" +
      "La ecuación de contribución usada fue $m = \\frac{p - c_v}{p}$ por unidad.\n\n" +
      "| Mes | Ingreso | Crecimiento |\n|---|---|---|\n| Abril | 10.2k | +8 % |\n| Mayo | 25.1k | +146 % |\n| Junio | 30.4k | +21 % |\n\n" +
      "```chart\n{\"type\":\"bar\",\"title\":\"Ventas mensuales (k USD)\",\"labels\":[\"Abr\",\"May\",\"Jun\"],\"series\":[{\"name\":\"Ingreso\",\"data\":[10.2,25.1,30.4]}]}\n```\n\n" +
      "```chart\n{\"type\":\"area\",\"title\":\"Margen acumulado (k USD)\",\"labels\":[\"Abr\",\"May\",\"Jun\"],\"series\":[{\"name\":\"Margen\",\"data\":[4.3,10.5,12.8]}]}\n```\n\n" +
      "```chart\n{\"type\":\"scatter\",\"title\":\"Precio vs unidades\",\"series\":[{\"name\":\"SKUs\",\"points\":[[9.9,120],[14.5,96],[19.9,64],[24.9,51],[29.9,33],[34.9,21]]}]}\n```\n\n" +
      "```chart\n" + JSON.stringify(Object.assign({ type: "candlestick", title: "Precio de la acción (30d, demo)" }, genOHLC(30))) + "\n```\n\n" +
      "> Próximo paso: sostener el canal directo en Q3 [1].",
    citations: [{ id: 1, label: "Reporte interno de finanzas, jun 2026", url: "https://example.com/fin-q2" }],
  },

  planilla: {
    type: "planilla",
    title: "PIB de Alemania",
    cols: ["Año", "PIB (USD MM)", "Crecimiento %"],
    rows: [
      ["2020", 99290, -7.8],
      ["2021", 106166, 4.2],
      ["2022", 115049, 6.2],
      ["2023", 118845, 3.3],
    ],
  },

  web: {
    type: "web",
    title: "Landing café",
    content:
      '<!doctype html><html><head><meta charset="utf-8"><style>' +
      'body{margin:0;font-family:system-ui;background:linear-gradient(135deg,#3a2a1e,#6b4b32);color:#f3e9dc;height:100vh;display:grid;place-content:center;text-align:center}' +
      'h1{font-size:42px;margin:0}button{margin-top:18px;padding:11px 22px;border:none;border-radius:30px;background:#e8b15a;color:#2a1d11;font-weight:500;cursor:pointer}' +
      '</style></head><body><div><h1>Café Aleph ☕</h1><p>Tostado de origen, recién hecho.</p>' +
      '<button onclick="this.textContent=\'¡Pedido! ✓\'">Pedir ahora</button></div></body></html>',
  },

  // [2.3] `documento` = el nombre canónico del vocabulario (antes la llave era el
  // alias `doc`; el demo itera TYPES, que ahora son las llaves de los renderers).
  documento: {
    type: "documento",
    title: "Carta de bienvenida",
    content:
      "**Estimado/a cliente:**\n\nNos complace darle la bienvenida a **Aleph**. A partir de hoy, su agente " +
      "equipado queda a su disposición para acompañarle en cada tarea.\n\n" +
      "En los próximos días recibirá una guía breve para sacarle el máximo provecho. Ante cualquier consulta, " +
      "basta con responder a este mensaje.\n\nCon aprecio,\n\n*El equipo de Aleph*",
  },

  cad: {
    type: "cad",
    title: "Pieza de prueba (cubo)",
    format: "stl",
    content: cubeSTL(20),
  },

  schematic: {
    type: "schematic",
    title: "LED con resistencia limitadora",
    content: SCHEMATIC_SVG,
  },

  fieldplot: Object.assign({ type: "fieldplot", title: "Campo de temperatura (corte)" },
    { grid: gaussField(64, 64) }),

  dicom: {
    type: "dicom",
    title: "TC craneal (phantom)",
    meta: { PatientName: "ANÓNIMO^DEMO", PatientID: "PH-0001", Modality: "CT", StudyDate: "2026-06-21", SeriesDescription: "AXIAL HEAD", SliceThickness: 1.0, InstitutionName: "Aleph Demo" },
    pixels: phantom(180),
  },

  volume3d: Object.assign(
    { type: "volume3d", title: "Volumen 3D (demo · esfera)", structure: "bone", color: [230, 225, 205] },
    demoVolumeMesh()),

  // espejo del contrato de los loops reales (fem_server/backtest_server): metric+limit
  // + iterations con grid por paso → FALLA (rojo) → PASA (verde), stepping/autoplay.
  convergence: {
    type: "convergence",
    title: "Loop FEM · von Mises vs límite (demo)",
    metric: { name: "von Mises", unit: "MPa", goal: "min" },
    limit: 250,
    autoplay: false,   // el demo/verify stepea determinístico vía _convShow
    iterations: [
      { n: 1, value: 420, passed: false, grid: femField(48, 24, 420) },
      { n: 2, value: 291, passed: false, grid: femField(48, 24, 291) },
      { n: 3, value: 180, passed: true,  grid: femField(48, 24, 180) },
    ],
  },

  // espejo del contrato del productor worldbank (finanzas_data_server → *.linechart.json)
  linechart: {
    type: "linechart",
    title: "PIB (US$ corrientes) — Ecuador",
    labels: ["2017", "2018", "2019", "2020", "2021", "2022", "2023"],
    series: [{ name: "PIB (US$ MM)", data: [104296, 107562, 108108, 99291, 106166, 115049, 118845] }],
    source: "World Bank Open Data — NY.GDP.MKTP.CD (demo)",
  },
};

if (typeof window !== "undefined") window.AlephRenderSamples = SAMPLES;
export default SAMPLES;
