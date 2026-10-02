/* verify_morph_persistido.mjs — EL MORPH SOBREVIVE, Y NO SE LLEVA PUESTO AL PADRE.
 * [Gate 4 · Fase 4 · obra O4 · 4.1 · hallazgo H1 de la auditoría]
 *
 * QUÉ AFIRMA
 * ----------
 *  A · **El borrador tiene identidad adentro.** Editar adentro de un recinto-agente NO pisa
 *      el borrador del padre. Antes sí: `_foto()` fotografía la colección VIVA de piezas, que
 *      adentro de un hijo es la del hijo, y se guardaba bajo la clave del padre. Medido antes
 *      de arreglarlo: padre `["agtA"]` → tras entrar y mover, `["c-py","intruso"]` en la MISMA
 *      clave. Cerrar y reabrir devolvía el agente equivocado, en silencio.
 *  B · **La ruta del morph se persiste** al entrar y se BORRA al volver a la raíz (una ruta
 *      vacía no es un estado que restaurar).
 *  C · **Se restaura**: recargando la pantalla, el usuario vuelve a donde estaba — y por el
 *      camino real (`enterRecinto` rehidratando por `agent_ref`), no por un atajo del test.
 *  D · **Si el agente ya no está, se dice.** No se baja por un lugar que no existe.
 *
 * LO QUE NO SE PERSISTE, Y POR QUÉ: los frames del motor guardan objetos PIXI vivos (el world
 * del padre, la escena hija). Eso no se serializa ni debería. Lo único que hace falta es la
 * RUTA —por qué agentes bajó el usuario—, porque entrar ya sabe rehidratar solo.
 *
 * PROBADA CAYENDO — CONTRA EL CÓDIGO QUE TENÍA EL DEFECTO
 * -------------------------------------------------------
 * `--caer antes` sirve `cuarto.pixi.html` **tal como estaba antes de esta obra**
 * (`git show HEAD:…`) y corre los MISMOS asserts. No hay una perilla de sabotaje metida en
 * producción: una perilla así se queda para siempre en el código del usuario, y además sólo
 * prueba que la perilla funciona. Esto prueba que la vara habría cazado el defecto real.
 *
 *   node qa/verify_morph_persistido.mjs
 *   node qa/verify_morph_persistido.mjs --caer antes
 */
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { servirCuarto, cuartoListo } from "./lib/servidor_cuarto.mjs";

const CAER = (() => { const i = process.argv.indexOf("--caer"); return i > 0 ? process.argv[i + 1] : ""; })();
const PORT = 8192;
const UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const REF = "catalog/agents/agent-" + UUID + ".config.json";
const USUARIO = { id: "u-vara", session_token: "tok-vara", email: "vara@aleph" };

const fallos = [];
const ok = (c, l, x = "") => { console.log(`${c ? "✓" : "✗"} ${l}${x ? "  " + x : ""}`); if (!c) fallos.push(l); };

/** La receta del HIJO, servida por el stub como la config de su puppet — el mismo camino que
 *  usa `__cuartoFetchChildRecipe` en producción. */
const CONFIG_HIJO = {
  canvas: {
    nucleos: [{ id: "n1", name: "hijo-a", model: "vara/cerebro", gridX: 3, gridY: 1 }],
    blocks: [{ id: "c-py", atom: "tool", card_id: "python", ref: "python", label: "Py",
               tools: [], zone: "mesa", gridX: 4, gridY: 3 }],
    links: [],
  },
  belt: { agent_refs: [], belt_refs: [] },
};

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sustituir = {};
if (CAER === "antes") {
  // El archivo de ANTES de esta obra, sacado de git. Si el `HEAD` ya la tuviera adentro, la
  // falsificación no probaría nada — por eso se comprueba que el contenido NO traiga la marca
  // de la obra antes de creerle.
  const viejo = execFileSync("git", ["show", "HEAD:product/app/design/cuarto/cuarto.pixi.html"],
                             { cwd: RAIZ, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (viejo.includes("__cuartoRestaurarMorph")) {
    console.error("✗ el HEAD ya trae la obra: esta falsificación no probaría nada");
    process.exit(2);
  }
  sustituir["/cuarto/cuarto.pixi.html"] = viejo;
}

const srv = await servirCuarto({
  puerto: PORT,
  sustituir,
  rutas: { [`/v1/users/${USUARIO.id}/puppets`]: () => ({ puppets: [{ id: UUID, name: "hijo-a", config: CONFIG_HIJO }] }) },
});
const nav = await chromium.launch();
const ctx = await nav.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.addInitScript((u) => {
  try { localStorage.setItem("puppet_user", JSON.stringify(u)); } catch (e) { /* sin storage no hay sesión */ }
}, USUARIO);

const page = await ctx.newPage();
const errores = [];
page.on("pageerror", (e) => errores.push(String(e).slice(0, 120)));

try {
  await page.goto(`http://127.0.0.1:${PORT}/cuarto/cuarto.pixi.html`, { waitUntil: "load" });
  await cuartoListo(page);
  await page.waitForTimeout(1500);

  // ── SEMBRAR LA RAÍZ: un recinto-AGENTE con su `agent_ref` ──────────────────────────
  const sembrado = await page.evaluate(async (ref) => {
    const c = window.__cuarto;
    c.placedTiles().forEach((t) => c.removeTile(t.id));
    c.placeRecinto({ id: "agtA", nucleo: true, agent_ref: ref, gridX: 2, gridY: 2, w: 2, h: 2 },
      [{ id: "a1", key: "a1", label: "A1", category: "read" }]);
    window.__autoguardar();
    await new Promise((r) => setTimeout(r, 400));
    const bloques = ((window.__draft?.recipe?.canvas?.blocks) || []).map((b) => b.id).sort();
    return { piezas: c.placedTiles().map((t) => t.id).sort(), draft: bloques };
  }, REF);
  ok(sembrado.piezas.join() === "agtA", "la raíz tiene su recinto-agente", sembrado.piezas.join());
  ok(sembrado.draft.join() === "agtA", "y su borrador dice exactamente eso", sembrado.draft.join());

  // ── A · ENTRAR, TOCAR ADENTRO, Y QUE EL PADRE NO SE ENTERE ─────────────────────────
  const dentro = await page.evaluate(async () => {
    const c = window.__cuarto;
    const en = await c.enter("agtA");
    c.placeTile({ id: "intruso", key: "intruso", label: "Intruso", category: "process" }, 6, 6);
    window.__autoguardar();
    await new Promise((r) => setTimeout(r, 400));
    const claves = Object.keys(localStorage).filter((k) => k.startsWith("aleph:cuarto:"));
    const leer = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
    const bl = (f) => ((f?.recipe?.canvas?.blocks) || []).map((b) => b.id).sort();
    const draftRaiz = claves.filter((k) => k.startsWith("aleph:cuarto:draft:") && !k.includes("hijo:"))[0];
    const draftHijo = claves.filter((k) => k.startsWith("aleph:cuarto:draft:hijo:"))[0];
    return {
      en, depth: c.fractal().depth,
      piezasHijo: c.placedTiles().map((t) => t.id).sort(),
      claves,
      draftRaiz: draftRaiz ? bl(leer(draftRaiz)) : null,
      draftHijo: draftHijo ? bl(leer(draftHijo)) : null,
      identidadHijo: draftHijo ? { depth: leer(draftHijo).depth, agentRef: leer(draftHijo).agentRef } : null,
      morph: leer("aleph:cuarto:morph:nuevo"),
    };
  });
  ok(dentro.en?.ok === true && dentro.depth === 1, "se entró al recinto-agente", JSON.stringify(dentro.en));
  ok(dentro.piezasHijo.includes("intruso"),
     "adentro se puede trabajar (el arreglo NO le quita capacidades al usuario)");
  ok(dentro.draftRaiz && dentro.draftRaiz.join() === "agtA",
     "EL BORRADOR DEL PADRE SIGUE INTACTO", `dice ${JSON.stringify(dentro.draftRaiz)}`);
  ok(dentro.draftHijo && dentro.draftHijo.includes("intruso"),
     "y lo del hijo se guardó, en SU propia clave", `dice ${JSON.stringify(dentro.draftHijo)}`);
  ok(dentro.identidadHijo && dentro.identidadHijo.depth === 1 && dentro.identidadHijo.agentRef === REF,
     "con la identidad ADENTRO de la foto, no sólo en su clave",
     JSON.stringify(dentro.identidadHijo));

  // ── B · LA RUTA DEL MORPH ──────────────────────────────────────────────────────────
  ok(dentro.morph && Array.isArray(dentro.morph.ruta) && dentro.morph.ruta.length === 1
     && dentro.morph.ruta[0].agentRef === REF,
     "la ruta del morph quedó persistida, con el agente adentro",
     JSON.stringify(dentro.morph?.ruta));

  const alSalir = await page.evaluate(async () => {
    window.__cuarto.exit();
    await new Promise((r) => setTimeout(r, 400));
    return { morph: localStorage.getItem("aleph:cuarto:morph:nuevo"), depth: window.__cuarto.fractal().depth };
  });
  ok(alSalir.depth === 0 && alSalir.morph === null,
     "volver a la raíz BORRA la ruta: un «ya salí» no es un estado que restaurar");

  // ── C · SE RESTAURA AL RECARGAR ────────────────────────────────────────────────────
  await page.evaluate(async () => {
    await window.__cuarto.enter("agtA");
    await new Promise((r) => setTimeout(r, 400));
  });
  await page.reload({ waitUntil: "load" });
  await cuartoListo(page);
  await page.waitForFunction(() => window.__morphRestaurado !== undefined, null, { timeout: 25000 })
    .catch(() => {});
  const tras = await page.evaluate(() => ({
    r: window.__morphRestaurado, depth: window.__cuarto.fractal().depth,
    piezas: window.__cuarto.placedTiles().map((t) => t.id).sort(),
  }));
  ok(tras.r && tras.r.restaurado === 1 && tras.depth === 1,
     "AL RECARGAR, el usuario vuelve donde estaba", JSON.stringify(tras.r));
  ok(tras.piezas.includes("c-py"),
     "y adentro está la receta del hijo, traída por `agent_ref` como en producción",
     JSON.stringify(tras.piezas));

  // ── D · SI EL AGENTE YA NO ESTÁ, SE DICE ───────────────────────────────────────────
  const huerfano = await page.evaluate(async () => {
    const c = window.__cuarto;
    c.exit();
    await new Promise((r) => setTimeout(r, 300));
    await c.enter("agtA");
    await new Promise((r) => setTimeout(r, 300));
    c.exit();                                   // vuelve a la raíz con la ruta ya guardada…
    await new Promise((r) => setTimeout(r, 300));
    // …se re-siembra la ruta a mano y se le saca el recinto de abajo
    localStorage.setItem("aleph:cuarto:morph:nuevo", JSON.stringify({
      v: 1, ts: Date.now(), pid: null,
      ruta: [{ agentRef: "catalog/agents/agent-no-existe.config.json", label: "fantasma" }],
    }));
    return await window.__cuartoRestaurarMorph();
  });
  ok(huerfano.restaurado === 0 && huerfano.motivo === "agente_ausente",
     "un agente que ya no está para la restauración CON CAUSA, no baja a ciegas",
     JSON.stringify(huerfano));

  ok(errores.length === 0, "cero errores JS de página", errores.slice(0, 2).join(" | "));
} finally {
  await nav.close();
  await srv.cerrar();
}

console.log(fallos.length ? `\nROJAS: ${fallos.join(", ")}` : "\nVERDE");
process.exit(fallos.length ? 1 : 0);
