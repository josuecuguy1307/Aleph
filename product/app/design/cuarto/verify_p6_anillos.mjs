/* verify_p6_anillos.mjs — FIX-P6 · SEPARACIÓN DE ANILLOS EN MÉTRICA DE PANTALLA.
 *
 * Contra el SIDECAR FROZEN propio (WebKit, :8276). El assert es GEOMÉTRICO sobre el dibujo VIVO:
 * cero intersección de anillos en estado estable — Y EN LAS 4 ROTACIONES. Ese "y" es el punto:
 * `rotPt` intercambia los ejes de la anisotropía iso en las rotaciones impares, así que un fix con
 * peso fijo en cell-space pasa a rot 0 y rompe a rot 1. Medir una sola rotación es medir la mitad.
 *
 * QUÉ MIDE, y por qué cada cosa:
 *   §1 · la GEOMETRÍA del anillo sale viva (semiejes leídos, no constantes) y el dibujo no cambió
 *   §2 · CALIBRACIÓN EN ROJO — dos piezas puestas adyacentes A MANO tienen que dar CRUCE. Si el
 *        assert no puede ponerse rojo, es ciego y todos los verdes de abajo no valen nada.
 *   §3 · receta de la CAMINATA (MCPs reales del catálogo, equipados sin coords → balancedFreeCell)
 *   §4 · sintética DENSA (12 piezas) — el frente saturado, donde el score blando de antes cedía
 *   §5 · las 4 ROTACIONES, sin re-ordenar entre medio (rotateBy hace relayout+fitAll y NO re-corre
 *        orderLayout: si la separación no fuese invariante a la rotación, acá amanece cruzado)
 *   §6 · ORDENAR (orderLayout) y otra vez las 4 rotaciones
 *   §7 · el layout NO VIBRA: converge y se queda (celda fija, X fija; sólo respira el bob del idle)
 *   §8 · ZOOM OUT: el anillo NO contra-escala → el solape es invariante al zoom (assert distinto
 *        del de legibilidad, que se mide aparte y en px de pantalla al cam.scale mínimo)
 *   §9 · model.relationships byte-idéntico antes/después de ordenar (la física escribe SÓLO posición)
 *
 * Run (fix):       SIDECAR=http://127.0.0.1:8276 node product/app/design/cuarto/verify_p6_anillos.mjs
 * Run (baseline):  SIDECAR=http://127.0.0.1:8278 SIN_HEALTH=1 SUF=-antes node …   ← tiene que dar ROJO
 *   (el baseline no expone anillosGeom(); la vara cae sola a reconstruir la geometría con API que
 *    SÍ existe en las dos ramas — placedTiles + tileAura(id).r + viewPoint + cam.scale — para que
 *    el rojo del baseline y el verde del fix sean el MISMO número medido de la misma manera.)
 */
import { webkit } from "playwright";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = join(HERE, "screenshots");
const BASE = process.env.SIDECAR || "http://127.0.0.1:8276";
const PAGE = `${BASE}/cuarto/cuarto.pixi.html`;
const SUF = process.env.SUF || "";
const DENSA = Number(process.env.DENSA || 12);

const fails = [];
const ok = (c, label, extra) => {
  console.log(`${c ? "✓" : "✗"} ${label}${extra != null && extra !== "" ? "  — " + extra : ""}`);
  if (!c) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (process.env.SIN_HEALTH !== "1") {
  try {
    const r = await fetch(BASE + "/health");
    if (!r.ok) throw new Error("health " + r.status);
    const j = await r.json();
    console.log(`── sidecar frozen ${BASE} vivo — commit ${j.proceso?.commit} build ${j.proceso?.build}\n`);
  } catch (e) {
    console.log(`✗ el sidecar ${BASE} no responde (${e.message})`);
    process.exit(1);
  }
} else {
  console.log(`── ${BASE} (sin /health: modo baseline)\n`);
}

// ══ LA MEDICIÓN — se inyecta en la página ═══════════════════════════════════════════════════════
// PRIMARIA: api.anillosGeom() → centro y semiejes del anillo TAL COMO ESTÁ DIBUJADO, en px de
// mundo, ya escalados por el transform real de la pieza (bob del idle, lift, escala de nacimiento).
// FALLBACK (sólo baseline, que no la tiene): se reconstruye con API que existe en las dos ramas —
// centro = viewPoint(gx,gy) + (0,−6)·camScale · a = tileAura(id).r · 0.78 · camScale · b = a·0.62.
// El fallback mide la BASE DE CELDA (el objetivo del settle) en vez del pixel vivo: para comparar
// layouts es la misma cosa, y es lo único medible en las dos ramas con el mismo instrumento.
const GEOM = () => {
  const C = window.__cuarto;
  if (typeof C.anillosGeom === "function") return { via: "vivo", G: C.anillosGeom() };
  const k = C.cam.state.scale;
  const G = C.placedTiles().map((t) => {
    const an = C.tileAnillo(t.id), au = C.tileAura(t.id);
    if (!an || !an.visible || !au || !au.r) return null;
    const p = C.viewPoint(t.gridX, t.gridY), a = au.r * 0.78 * k;
    return { id: t.id, gx: t.gridX, gy: t.gridY, k, cx: p.x, cy: p.y - 6 * k, a, b: a * 0.62 };
  }).filter(Boolean);
  return { via: "reconstruido", G };
};
// Dos elipses HOMOTÉTICAS (mismo achatado) → su suma de Minkowski es la elipse de semiejes sumados:
// sep = |Δ| en esa métrica. 1 = TANGENTES · <1 = SE CRUZAN · >1 = aire. Test exacto, no una cota.
const CRUCES = () => {
  const { via, G } = (0, eval)("(" + window.__P6_GEOM + ")")();
  let peor = Infinity, par = null, cruces = 0, lista = [];
  for (let i = 0; i < G.length; i++) for (let j = i + 1; j < G.length; j++) {
    const A = G[i].a + G[j].a, B = G[i].b + G[j].b;
    const s = Math.hypot((G[i].cx - G[j].cx) / A, (G[i].cy - G[j].cy) / B);
    if (s < 1) { cruces++; lista.push(`${G[i].id}@${G[i].gx},${G[i].gy} ↔ ${G[j].id}@${G[j].gx},${G[j].gy} (sep ${s.toFixed(3)})`); }
    if (s < peor) { peor = s; par = `${G[i].id}@${G[i].gx},${G[i].gy} ↔ ${G[j].id}@${G[j].gx},${G[j].gy}`; }
  }
  return { via, n: G.length, peor: G.length > 1 ? peor : Infinity, cruces, par, lista,
           celdas: G.map((g) => `${g.gx},${g.gy}`).join(" ") };
};

const browser = await webkit.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errores = [];
page.on("pageerror", (e) => errores.push(String(e)));
const shot = async (name) => {
  const el = await page.$("#cuarto");
  const p = join(SHOTS, name.replace(/\.png$/, "") + SUF + ".png");
  if (el) await el.screenshot({ path: p }); else await page.screenshot({ path: p });
  return p;
};

try {
  await page.goto(PAGE, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !!window.__cuarto, null, { timeout: 45000 });
  await page.waitForFunction(() => !!window.__catalog, null, { timeout: 45000 }).catch(() => {});
  await sleep(1200);
  await page.evaluate((src) => { window.__P6_GEOM = src; }, GEOM.toString());
  ok(errores.length === 0, "la página carga sin errores de JS", errores.slice(0, 2).join(" | "));

  const limpiar = () => page.evaluate(() => {
    const C = window.__cuarto;
    C.placedTiles().forEach((t) => C.removeTile(t.id));
    C.cam.reset();
  });
  const medir = async (etiqueta, mudo) => {
    const o = await page.evaluate(CRUCES);
    if (!mudo) console.log(`   ${etiqueta.padEnd(30)} n=${String(o.n).padStart(2)}  peorSep=${o.peor === null || !isFinite(o.peor) ? "—" : o.peor.toFixed(3)}  cruces=${o.cruces}`);
    return o;
  };
  const las4Rotaciones = async (titulo) => {
    const res = [];
    for (let r = 0; r < 4; r++) {
      if (r) { await page.evaluate(() => window.__cuarto.cam.rotateBy(1)); await sleep(800); }
      res.push(await medir(`${titulo} · rot ${r}`));
    }
    await page.evaluate(() => window.__cuarto.cam.reset()); await sleep(700);
    return res;
  };

  // ══ §1 · LA GEOMETRÍA DEL ANILLO SALE VIVA, Y EL DIBUJO NO CAMBIÓ ═════════════════════════════
  console.log("\n§1 · el anillo: geometría VIVA (semiejes leídos, no constantes) y dibujo intacto");
  await page.evaluate(() => {
    const C = window.__cuarto;
    C.placeTile({ id: "p6-geo", key: "p6-geo", label: "geo", category: "read", atom: "tool", server: "geo", tools: ["a", "b", "c"] });
  });
  await sleep(900);
  const g1 = await page.evaluate(() => {
    const C = window.__cuarto, au = C.tileAura("p6-geo"), an = C.tileAnillo("p6-geo");
    const geo = typeof C.anillosGeom === "function" ? (C.anillosGeom().find((x) => x.id === "p6-geo") || null) : null;
    return { auraR: au && au.r, anillo: an, geo };
  });
  ok(!!g1.auraR && g1.auraR !== 34, "el radio del anillo sale de los BOUNDS VIVOS del sprite, no del fallback 34",
     `_auraR = ${g1.auraR}`);
  if (g1.geo) {
    const a = g1.geo.a / g1.geo.k, b = g1.geo.b / g1.geo.k;
    ok(Math.abs(a - g1.auraR * 0.78) < 1e-6 && Math.abs(b - a * 0.62) < 1e-6,
       "el dibujo NO cambió: a = _auraR·0.78 y b = a·0.62, byte por byte como antes del fix",
       `a=${a.toFixed(2)} b=${b.toFixed(2)} (esperado ${(g1.auraR * 0.78).toFixed(2)} / ${(g1.auraR * 0.78 * 0.62).toFixed(2)})`);
  } else {
    console.log("   (baseline: sin anillosGeom() — se mide con el reconstruido)");
  }
  ok(g1.anillo && g1.anillo.visible && g1.anillo.tools === 3, "la firma del anillo queda igual {tools,color,visible}", JSON.stringify(g1.anillo));
  await limpiar(); await sleep(500);

  // ══ §2 · CALIBRACIÓN EN ROJO — el assert TIENE que poder ver un cruce ═════════════════════════
  // Dos piezas con celda EXPLÍCITA (placeTile con coords no pasa por balancedFreeCell: lo manual
  // manda, por diseño). Son 4-conexas → cruce geométrico garantizado. Si acá sale 0, la vara es
  // ciega y todo lo verde de abajo es decorado.
  console.log("\n§2 · calibración EN ROJO (dos piezas 4-conexas puestas a mano)");
  await page.evaluate(() => {
    const C = window.__cuarto, n = C.cam.state, y = 3;
    C.placeTile({ id: "p6-cal-a", key: "a", label: "a", category: "read", atom: "tool", server: "a", tools: ["t"] }, 2, y);
    C.placeTile({ id: "p6-cal-b", key: "b", label: "b", category: "read", atom: "tool", server: "b", tools: ["t"] }, 3, y);
    void n;
  });
  await sleep(1100);
  const cal = await medir("adyacentes a mano");
  ok(cal.n === 2 && cal.cruces === 1, "el assert VE el cruce cuando lo hay (si no, la vara es ciega)",
     `n=${cal.n} cruces=${cal.cruces} peor=${isFinite(cal.peor) ? cal.peor.toFixed(3) : "—"}`);
  await shot("p6-anillos-cruce-calibracion.png");
  await limpiar(); await sleep(500);

  // ══ §3 · RECETA DE LA CAMINATA — MCPs REALES del catálogo, equipados sin coords ═══════════════
  console.log("\n§3 · receta de la caminata (MCPs reales, sin coords → balancedFreeCell)");
  const receta = await page.evaluate(async () => {
    const C = window.__cuarto, cat = window.__catalog || {};
    const conTools = (cat.entries || []).filter((e) => (e.tools || []).length)
      .sort((a, b) => String(a.mcp).localeCompare(String(b.mcp))).slice(0, 6);   // determinístico
    const puestas = conTools.map((e, i) => C.placeTile(Object.assign({}, e, { id: "p6-cam-" + i })));
    window.__sync && window.__sync(); window.__renderPieces && window.__renderPieces();
    await new Promise((r) => setTimeout(r, 1800));
    return { pedidas: conTools.map((e) => e.mcp), puestas: puestas.filter(Boolean).length };
  });
  ok(receta.puestas >= 5, "la receta de la caminata entra en el Cuarto", `${receta.puestas} piezas · ${receta.pedidas.join(", ")}`);
  await sleep(600);
  const r3 = await las4Rotaciones("caminata · al NACER");
  ok(r3.every((x) => x.cruces === 0), "CAMINATA · cero intersección de anillos EN LAS 4 ROTACIONES",
     r3.map((x, i) => `rot${i}:${x.cruces}`).join(" ") + " · peor=" + Math.min(...r3.map((x) => x.peor)).toFixed(3));
  await shot("p6-anillos-caminata.png");
  await limpiar(); await sleep(600);

  // ══ §4-§6 · SINTÉTICA DENSA · NACER · 4 ROTACIONES · ORDENAR · 4 ROTACIONES ══════════════════
  console.log(`\n§4 · sintética densa (${DENSA} piezas con tools — el frente saturado)`);
  await page.evaluate(async (NP) => {
    const C = window.__cuarto;
    for (let i = 0; i < NP; i++)
      C.placeTile({ id: "p6-d-" + i, key: "p6-d-" + i, label: "pieza " + i, atom: "tool",
                    category: ["read", "process", "write"][i % 3], server: "srv" + i, tools: ["t1", "t2"] });
    await new Promise((r) => setTimeout(r, 2000));
  }, DENSA);
  const d0 = await medir("densa · al nacer · rot 0");
  ok(d0.n === DENSA, `las ${DENSA} piezas nacieron con anillo`, `n=${d0.n} · celdas: ${d0.celdas}`);
  await shot("p6-anillos-densa-nacer.png");

  console.log("\n§5 · las 4 rotaciones SIN re-ordenar (rotateBy no re-corre orderLayout)");
  const r5 = await las4Rotaciones("densa · al NACER");
  ok(r5.every((x) => x.cruces === 0), "DENSA/NACER · cero intersección EN LAS 4 ROTACIONES — rotar no reintroduce el cruce",
     r5.map((x, i) => `rot${i}:${x.cruces}`).join(" ") + " · peor=" + Math.min(...r5.map((x) => x.peor)).toFixed(3));

  console.log("\n§6 · ORDENAR (orderLayout) y otra vez las 4 rotaciones");
  const relAntes = await page.evaluate(() => JSON.stringify(window.__cuarto.relations()));
  const ord = await page.evaluate(() => window.__cuarto.order());
  await sleep(2000);
  const relDespues = await page.evaluate(() => JSON.stringify(window.__cuarto.relations()));
  console.log(`   order() → ${JSON.stringify(ord)}`);
  const r6 = await las4Rotaciones("densa · tras ORDENAR");
  ok(r6.every((x) => x.cruces === 0), "DENSA/ORDENAR · cero intersección EN LAS 4 ROTACIONES",
     r6.map((x, i) => `rot${i}:${x.cruces}`).join(" ") + " · peor=" + Math.min(...r6.map((x) => x.peor)).toFixed(3));
  ok(relAntes === relDespues, "§9 · model.relationships byte-idéntico: la física escribe SÓLO posición",
     `${relAntes.length} chars`);
  await shot("p6-anillos-densa-ordenada.png");

  // ══ §7 · EL LAYOUT NO VIBRA ══════════════════════════════════════════════════════════════════
  // La pieza RESPIRA por diseño (tickTile: c.y = baseY − settle·(3 + 1.6·sin t) → 3.2 px de bob) y
  // ESCALA con glow/relevancia. Vibrar es otra cosa: cambiar de celda, o que la X (que la manda el
  // settle, no el bob) no pare quieta. Se muestrea 1.2 s DESPUÉS de que el settle terminó.
  console.log("\n§7 · el layout converge y se queda quieto (celda fija · X fija · sólo respira)");
  const muestras = [], detalle = [];
  for (let i = 0; i < 8; i++) {                       // ~1.6 s repartidos: media vuelta del bob (T≈3.1 s)
    muestras.push(await page.evaluate(CRUCES));
    detalle.push(await page.evaluate(() => (0, eval)("(" + window.__P6_GEOM + ")")().G.map((g) => ({ id: g.id, gx: g.gx, gy: g.gy, cx: g.cx, cy: g.cy }))));
    await sleep(200);
  }
  const celdasIguales = muestras.every((m) => m.celdas === muestras[0].celdas);
  ok(celdasIguales, "ninguna pieza cambia de celda entre muestras (cero churn de layout)", muestras[0].celdas);
  const porId = new Map();
  detalle.flat().forEach((d) => { const a = porId.get(d.id) || []; a.push(d); porId.set(d.id, a); });
  let dxMax = 0, dyMax = 0;
  for (const arr of porId.values()) {
    dxMax = Math.max(dxMax, Math.max(...arr.map((a) => a.cx)) - Math.min(...arr.map((a) => a.cx)));
    dyMax = Math.max(dyMax, Math.max(...arr.map((a) => a.cy)) - Math.min(...arr.map((a) => a.cy)));
  }
  ok(dxMax < 0.5, "la X está QUIETA (la manda el settle, no el bob) → el settle convergió", `ΔxMax = ${dxMax.toFixed(3)} px`);
  ok(dyMax < 6, "la Y sólo RESPIRA dentro del bob del idle (≈3.2 px), no deriva", `ΔyMax = ${dyMax.toFixed(3)} px`);
  ok(muestras.every((m) => m.cruces === 0), "y cero cruce en TODAS las muestras del estado estable",
     muestras.map((m) => m.cruces).join(""));

  // ══ §8 · ZOOM OUT ════════════════════════════════════════════════════════════════════════════
  // El anillo es hijo de n.gfx y NO contra-escala (a diferencia del chip, que hace scale.set(1/cam.scale)).
  // Consecuencia: sus semiejes en px de MUNDO no dependen del zoom → anillo y separación escalan
  // juntos → el solape es INVARIANTE al zoom. Eso es un assert; la legibilidad es OTRO, y se mide
  // en px de PANTALLA al cam.scale mínimo (0.42, zoomAt:1668). No se dan por probados el uno con el otro.
  console.log("\n§8 · zoom out: el anillo no contra-escala → solape invariante · legibilidad medida aparte");
  // ⚠ MEDIDA DEPENDIENTE DEL INSTRUMENTO. anillosGeom() devuelve px de MUNDO (el zoom no entra);
  // el fallback del baseline devuelve px de PANTALLA (ya multiplicados por cam.scale). Los dos
  // asserts de abajo comparan px de mundo contra px de pantalla, así que SÓLO tienen sentido con la
  // medición viva. Con el fallback se REPORTAN los números y se dice que no se asertan — mentir
  // acá sería peor que no medir: darían rojo por el instrumento, no por el árbol.
  const via = (await page.evaluate(CRUCES)).via;
  const leerA = () => page.evaluate(() => { const G = (0, eval)("(" + window.__P6_GEOM + ")")().G; return { a: G[0] && G[0].a, escala: window.__cuarto.cam.state.scale }; });
  // La separación VIVA respira: el bob del idle mueve el centro 3.2 px, así que dos muestras sueltas
  // difieren por FASE, no por zoom. Se compara el PEOR de una tanda en cada zoom — que además es el
  // número que importa (el momento de máxima cercanía dentro del ciclo de respiración).
  const peorDeTanda = async () => {
    let p = Infinity, c = 0;
    for (let i = 0; i < 6; i++) { const m = await page.evaluate(CRUCES); p = Math.min(p, m.peor); c += m.cruces; await sleep(200); }
    return { peor: p, cruces: c };
  };
  const zAntes = await leerA();
  // La geometría viva incluye el bob del idle. Medir antes y 900 ms después comparaba dos
  // fases distintas del bob además del zoom y podía titular rojo por ~0.002 sobre la tolerancia.
  // zoomAt() es síncrono: tomamos ambas separaciones en el MISMO tick; así §8 aísla el zoom.
  const { antes: sAntes, despues: sDespues } = await page.evaluate((crucesSrc) => {
    const medir = (0, eval)("(" + crucesSrc + ")");
    const antes = medir();
    for (let i = 0; i < 20; i++) window.__cuarto.cam.zoomAt(0.7);
    return { antes, despues: medir() };
  }, CRUCES.toString());
  const zDespues = await leerA();
  ok(Math.abs(zDespues.escala - 0.42) < 1e-6, "la cámara llegó al zoom MÍNIMO (0.42)", `cam.scale = ${zDespues.escala}`);
  ok(Math.abs(sAntes.peor - sDespues.peor) < 0.02 && sDespues.cruces === 0,
     "el solape es INVARIANTE al zoom: misma separación, cero cruce, en el zoom mínimo",
     `peorSep ${sAntes.peor.toFixed(3)} → ${sDespues.peor.toFixed(3)} · cruces=${sDespues.cruces}`);
  const legible = await page.evaluate((via) => {
    const C = window.__cuarto, k = C.cam.state.scale, G = (0, eval)("(" + window.__P6_GEOM + ")")().G;
    const esc = via === "vivo" ? k : 1;                     // el fallback ya viene en px de pantalla
    return { aPx: Math.min(...G.map((g) => g.a)) * esc, bPx: Math.min(...G.map((g) => g.b)) * esc,
             pastillaPx: 6.4 * k, fuentePx: 9 * k };
  }, via);
  if (via === "vivo") {
    ok(Math.abs(zAntes.a - zDespues.a) < 0.01, "el anillo NO contra-escala: sus semiejes de MUNDO no dependen del zoom",
       `a(mundo) ${zAntes.a?.toFixed(2)} → ${zDespues.a?.toFixed(2)}`);
    ok(legible.bPx >= 6, "al zoom mínimo el aro sigue siendo un aro legible (semieje menor ≥ 6 px de pantalla)",
       `aro ${legible.aPx.toFixed(1)}×${legible.bPx.toFixed(1)} px · pastilla r=${legible.pastillaPx.toFixed(1)} px · número ${legible.fuentePx.toFixed(1)} px`);
  } else {
    console.log(`   (medición reconstruida: no se asertan los dos de arriba — a ${zAntes.a?.toFixed(2)} → ${zDespues.a?.toFixed(2)} px de PANTALLA;`
              + ` aro ${legible.aPx.toFixed(1)}×${legible.bPx.toFixed(1)} px · pastilla r=${legible.pastillaPx.toFixed(1)} px · número ${legible.fuentePx.toFixed(1)} px)`);
  }
  await shot("p6-anillos-zoom-minimo.png");

  ok(errores.length === 0, "cero errores de JS en toda la corrida", errores.slice(0, 3).join(" | "));
} catch (e) {
  ok(false, "la vara corrió entera", String(e && e.message));
} finally {
  await browser.close();
}

console.log(`\n${fails.length ? "✗" : "✓"} ${fails.length ? fails.length + " FALLO(S)" : "TODO VERDE"}`);
if (fails.length) { fails.forEach((f) => console.log("   · " + f)); process.exit(1); }
