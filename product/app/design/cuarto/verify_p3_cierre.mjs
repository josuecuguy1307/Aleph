/* P3-CIERRE · vara geométrica final.
 *
 * Mide contra el frozen de ESTA rama:
 *   1. centros de acciones equidistantes a la pieza y entre vecinos, en cuatro
 *      rotaciones y a 0.5×/1×/2× de cámara (tolerancia screen-space 0.12 px);
 *   2. todo bbox de candado atravesado por el path de su cable pieza→dueño;
 *   3. cero intersección entre bounding boxes VIVOS de labels, con 52 tools desplegadas;
 *
 * Incluye calibración roja del mismo instrumento: desplaza un candado fuera del cable y
 * superpone dos labels. Ambas mediciones tienen que ponerse rojas.
 *
 * Run: SIDECAR=http://127.0.0.1:8303 node product/app/design/cuarto/verify_p3_cierre.mjs
 */
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const BASE = process.env.SIDECAR || "http://127.0.0.1:8303";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const failures = [];
const ok = (condition, label, detail = "") => {
  console.log(`${condition ? "✓" : "✗"} ${label}${detail ? ` — ${detail}` : ""}`);
  if (!condition) failures.push(label);
};
function loadPlaywright() {
  for (const root of [process.env.PLAYWRIGHT_PROJECT, join(HERE, "../../../..")].filter(Boolean)) {
    if (!existsSync(join(root, "node_modules", "playwright", "package.json"))) continue;
    return createRequire(join(root, "package.json"))("playwright");
  }
  throw new Error("Playwright no está disponible; definí PLAYWRIGHT_PROJECT");
}
const { webkit } = loadPlaywright();

try {
  const response = await fetch(`${BASE}/health`);
  if (!response.ok) throw new Error(`health ${response.status}`);
  const health = await response.json();
  console.log(`── frozen ${BASE} · commit ${health.proceso?.commit || "?"}\n`);
} catch (error) {
  console.error(`✗ frozen ausente en ${BASE}: ${error.message}`);
  process.exit(1);
}

const toolNames = (prefix, count) => Array.from({ length: count }, (_, i) => {
  const families = ["fetchOrderBook", "fetchOHLCV", "fetchTickers", "getHistoricalMarketData",
                    "createConfluencePage", "transitionJiraIssue"];
  return `${families[i % families.length]}_${prefix}_${String(i + 1).padStart(2, "0")}`;
});
const SEED = [
  { id: "p3c-ccxt", label: "CCXT", server: "ccxt", atom: "tool", role: "mesa",
    category: "process", tools: toolNames("ccxt", 32), gated: true, gx: 2, gy: 2 },
  { id: "p3c-atlassian", label: "Atlassian", server: "atlassian", atom: "tool", role: "mesa",
    category: "process", tools: toolNames("atlassian", 52), gx: 6, gy: 4 },
];

const arcErrors = (measurement, tolerance = 0.12) => {
  const errors = [];
  const radii = measurement.items.map((item) => Math.hypot(item.x - measurement.cx, item.y - measurement.cy));
  const adjacent = measurement.items.slice(1).map((item, i) =>
    Math.hypot(item.x - measurement.items[i].x, item.y - measurement.items[i].y));
  const spread = (values) => values.length ? Math.max(...values) - Math.min(...values) : Infinity;
  if (measurement.items.length < 4) errors.push(`sólo ${measurement.items.length} acciones`);
  if (spread(radii) > tolerance) errors.push(`pieza→acción spread ${spread(radii).toFixed(2)}px`);
  if (spread(adjacent) > tolerance) errors.push(`acción→acción spread ${spread(adjacent).toFixed(2)}px`);
  const mean = (values) => values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  return {
    errors, radii, adjacent,
    radiusSpread: spread(radii), adjacentSpread: spread(adjacent),
    radiusMean: mean(radii),
    widthMean: mean(measurement.items.map((item) => item.width)),
    heightMean: mean(measurement.items.map((item) => item.height)),
  };
};
const zoomInvariantErrors = (rows, tolerance = 0.12) => {
  const spread = (values) => values.length ? Math.max(...values) - Math.min(...values) : Infinity;
  const radius = spread(rows.map((row) => row.radiusMean));
  const width = spread(rows.map((row) => row.widthMean));
  const height = spread(rows.map((row) => row.heightMean));
  const errors = [];
  if (radius > tolerance) errors.push(`radio ${radius.toFixed(3)}px`);
  if (width > tolerance) errors.push(`ancho ${width.toFixed(3)}px`);
  if (height > tolerance) errors.push(`alto ${height.toFixed(3)}px`);
  return { errors, radius, width, height };
};

const lockErrors = (locks) => locks.flatMap((lock) => {
  if (!lock || !lock.bbox || !Array.isArray(lock.cable)) return ["candado sin bbox/path declarado"];
  const b = lock.bbox;
  const crosses = lock.cable.some((p) =>
    p.x >= b.left && p.x <= b.right && p.y >= b.top && p.y <= b.bottom);
  return crosses && lock.dCable <= 1.5 ? [] :
    [`${lock.id || "?"}: bbox no tocado por cable (d=${Number(lock.dCable).toFixed(2)}px)`];
});

const labelOverlaps = (boxes, epsilon = 0.25) => {
  const overlaps = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const dx = Math.min(boxes[i].right, boxes[j].right) - Math.max(boxes[i].left, boxes[j].left);
    const dy = Math.min(boxes[i].bottom, boxes[j].bottom) - Math.max(boxes[i].top, boxes[j].top);
    if (dx > epsilon && dy > epsilon)
      overlaps.push(`${boxes[i].tool} ↔ ${boxes[j].tool} (${dx.toFixed(1)}×${dy.toFixed(1)}px)`);
  }
  return overlaps;
};

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const runtimeErrors = [];
page.on("pageerror", (error) => runtimeErrors.push(String(error)));
page.on("console", (message) => {
  if (message.type() === "error" && !/Failed to load resource|401/.test(message.text()))
    runtimeErrors.push(message.text());
});

try {
  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__cuarto && window.__openAbanico,
                             null, { timeout: 60000 });
  await sleep(1200);
  await page.evaluate((seed) => {
    const C = window.__cuarto;
    C.placedTiles().forEach((tile) => C.removeTile(tile.id));
    seed.forEach((piece) => C.placeTile(piece, piece.gx, piece.gy));
    C.cam.reset();
    C.setModo("trabajo", { focus: "atlassian" });
    window.__sync && window.__sync();
  }, SEED);
  await sleep(1600);
  ok(runtimeErrors.length === 0, "la página carga sin errores JS", runtimeErrors.slice(0, 2).join(" | "));

  console.log("\n§1 · arco: screen-space a 0.5×/1×/2×, cuatro rotaciones");
  const rotations = [];
  for (let rotation = 0; rotation < 4; rotation++) {
    if (rotation) {
      await page.evaluate(() => window.__cuarto.cam.rotateBy(1));
      await sleep(900);
    }
    for (const zoom of [0.5, 1, 2]) {
      await page.evaluate((target) => {
        window.__closeAbanico && window.__closeAbanico();
        const C = window.__cuarto, current = C.cam.state.scale;
        C.cam.zoomAt(target / current, 8, 8);
        window.__openAbanico(C.pieceData("p3c-ccxt"));
      }, zoom);
      await sleep(500);
      const measurement = await page.evaluate(() => {
        const anchor = document.getElementById("abanico").getBoundingClientRect();
        return {
          cx: anchor.left, cy: anchor.top,
          items: [...document.querySelectorAll("#abActs .ab-act")].map((button) => {
            const box = button.getBoundingClientRect();
            return {
              act: button.dataset.act,
              x: box.left + box.width / 2, y: box.top + box.height / 2,
              width: box.width, height: box.height,
            };
          }),
        };
      });
      const result = arcErrors(measurement);
      rotations.push({ rotation, zoom, ...result });
      ok(result.errors.length === 0, `rot${rotation} · ${zoom}×: equidistancia fija`,
         `spread ${result.radiusSpread.toFixed(3)}px / ${result.adjacentSpread.toFixed(3)}px`);
      if (zoom === 1) {
        const shot = join(SHOTS, `p3-cierre-rot${rotation}.png`);
        await page.screenshot({ path: shot });
        console.log(`  → screenshots/p3-cierre-rot${rotation}.png`);
      }
    }
  }
  const invariantRows = [];
  for (let rotation = 0; rotation < 4; rotation++) {
    const result = zoomInvariantErrors(rotations.filter((row) => row.rotation === rotation));
    invariantRows.push(result);
    ok(result.errors.length === 0, `rot${rotation}: tamaño fijo entre 0.5×/1×/2×`,
       result.errors.join(" · ") || `Δr=${result.radius.toFixed(3)}px`);
  }
  ok(rotations.every((result) => result.errors.length === 0) &&
     invariantRows.every((result) => result.errors.length === 0),
     "objetivo rotacional+zoom: cero fallos en las doce mediciones",
     rotations.map((result) => `r${result.rotation}@${result.zoom}:${result.errors.length}`).join(" "));

  // CALIBRACIÓN ROJA: conectar por un instante la escala del arco a la cámara.
  // La equidistancia interna sigue siendo perfecta, así que sólo el assert
  // zoom-invariante puede detectar esta regresión.
  const scalableRows = [];
  for (const zoom of [0.5, 2]) {
    const measurement = await page.evaluate((target) => {
      const C = window.__cuarto, current = C.cam.state.scale;
      C.cam.zoomAt(target / current, 8, 8);
      const host = document.getElementById("abActs");
      host.style.transformOrigin = "0 0";
      host.style.transform = `scale(${target})`;
      window.__openAbanico(C.pieceData("p3c-ccxt"));
      const anchor = document.getElementById("abanico").getBoundingClientRect();
      return {
        cx: anchor.left, cy: anchor.top,
        items: [...document.querySelectorAll("#abActs .ab-act")].map((button) => {
          const box = button.getBoundingClientRect();
          return {
            x: box.left + box.width / 2, y: box.top + box.height / 2,
            width: box.width, height: box.height,
          };
        }),
      };
    }, zoom);
    scalableRows.push(arcErrors(measurement));
  }
  await page.evaluate(() => {
    const host = document.getElementById("abActs");
    host.style.removeProperty("transform");
    host.style.removeProperty("transform-origin");
  });
  const scalableFailure = zoomInvariantErrors(scalableRows);
  ok(scalableFailure.errors.length > 0,
     "CALIBRACIÓN ROJA · hacer el arco escalable rompe la vara zoom-invariante",
     scalableFailure.errors.join(" · "));

  console.log("\n§2 · candado: bbox atravesado por el cable de la pieza a su dueño");
  const locks = await page.evaluate(() => {
    const C = window.__cuarto;
    return C.candados().map((id) => ({ id, ...C.candado(id) }));
  });
  const lockFailures = lockErrors(locks);
  ok(locks.length >= 1, "hay al menos un candado de carga", `n=${locks.length}`);
  ok(lockFailures.length === 0, "cero candados sin cable", lockFailures.join(" | ") || "todos atravesados");
  ok(locks.every((lock) => lock.duenoId), "cada ancla declara un dueño", locks.map((l) => `${l.id}→${l.duenoId}`).join(" "));

  // CALIBRACIÓN ROJA: la misma API devuelve por un instante el bbox 90px fuera del path.
  const floating = await page.evaluate(() => {
    const C = window.__cuarto, real = C.candado;
    C.candado = (id) => {
      const lock = real(id);
      if (!lock) return lock;
      return { ...lock, dCable: 90, bbox: { left: lock.bbox.left + 90, right: lock.bbox.right + 90,
                                            top: lock.bbox.top, bottom: lock.bbox.bottom } };
    };
    const result = C.candados().map((id) => ({ id, ...C.candado(id) }));
    C.candado = real;
    return result;
  });
  ok(lockErrors(floating).length > 0, "CALIBRACIÓN ROJA · un candado flotante hace fallar la vara",
     lockErrors(floating)[0] || "");

  console.log("\n§3 · labels: CCXT y Atlassian-clase, bounding boxes vivos");
  const labelsPorCaso = {};
  for (const caso of [{ server: "ccxt", n: 32 }, { server: "atlassian", n: 52 }]) {
    await page.evaluate((server) => {
      window.__closeAbanico && window.__closeAbanico();
      window.__cuarto.setModo("trabajo", { focus: server });
    }, caso.server);
    await sleep(900);
    const labels = await page.evaluate(() => window.__cuarto.toolLabelBoxes());
    const overlaps = labelOverlaps(labels);
    labelsPorCaso[caso.server] = labels;
    ok(labels.length === caso.n, `${caso.server}: se desplegaron ${caso.n} tools`, `n=${labels.length}`);
    ok(overlaps.length === 0, `${caso.server}: cero overlap de etiquetas`,
       overlaps.slice(0, 3).join(" | ") || "0 pares");
  }

  // CALIBRACIÓN ROJA: superpone exactamente dos cajas y vuelve a pasar el mismo detector.
  const overlapped = labelsPorCaso.atlassian.map((box) => ({ ...box }));
  if (overlapped.length > 1) {
    overlapped[1].left = overlapped[0].left; overlapped[1].right = overlapped[0].right;
    overlapped[1].top = overlapped[0].top; overlapped[1].bottom = overlapped[0].bottom;
  }
  ok(labelOverlaps(overlapped).length > 0,
     "CALIBRACIÓN ROJA · dos etiquetas forzadas al mismo bbox hacen fallar la vara",
     labelOverlaps(overlapped)[0] || "");

} finally {
  await browser.close();
}

console.log(`\n${failures.length ? `P3-CIERRE ROJO · ${failures.length} fallo(s)` : "P3-CIERRE VERDE"}`);
if (failures.length) {
  failures.forEach((failure) => console.log(`  - ${failure}`));
  process.exit(1);
}
