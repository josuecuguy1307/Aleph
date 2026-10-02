#!/usr/bin/env node
/**
 * verify_sala_cerebro_del_dueno.mjs — LA VARA DE LA PREFERENCIA HUÉRFANA.
 *
 *   node qa/verify_sala_cerebro_del_dueno.mjs
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * EL DEFECTO, MEDIDO EN LA .APP INSTALADA (sidecar d7906120)
 *
 * persona usuaria preguntó «que modelo eres» en la Sala y vio *«El modelo Incluido no está
 * configurado en esta app»* + un 409 detrás. Su lectura —«los proveedores SÍ funcionan y lo
 * que falla es lo que la UI muestra»— era correcta:
 *
 *     GET /v1/brains/status → claude_cli: ready · codex_cli: ready · included: not_configured
 *     modelos/preferencias-v2.json → contextos: { sala: "cli.codex_cli" }
 *
 * O sea: el cerebro que el usuario eligió estaba listo, y la Sala igual bloqueaba el envío.
 *
 * LA CADENA, en tres eslabones:
 *   1. `sala.html` devolvía `{ selected:'included' }` HARD-CODEADO cuando no hay receta.
 *   2. `contextos.sala` —la preferencia guardada— no la leía NADIE: `brain-status.js` la
 *      cacheaba y la palabra no volvía a aparecer en todo `product/app/design`.
 *   3. Y el hard-code no era sólo feo: **esquivaba su propio guard**. `resolve()` sólo corre
 *      `elegirDefault()` —el que elige el primer modelo REALMENTE utilizable— cuando la
 *      selección viene marcada `_tentativo`; nombrar `included` a mano quita esa marca.
 *
 * Resultado: `included` → `not_configured` → `blockExecution` → el turno NO SALE.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ESTA VARA NO HACE: derivar estado. `semaforoDe()` sigue siendo el derivador único
 * y `MV.probar` la puerta única de verificación (sellados en Gate 2). Acá sólo se mide QUÉ
 * LANE ELIGE la Sala — si esa lane sirve o no lo dice `resolve()`, que no se toca.
 *
 * Corre SIN NAVEGADOR, como manda la casa.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { instalarDOM } from "./dom_minimo.mjs";

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = join(RAIZ, "product/app/design");

const FALLOS = [];
const R = {};
const ok = (nombre, cond, det = "") => {
  R[nombre] = !!cond;
  console.log((cond ? "  ✅ " : "  ❌ ") + nombre + (det ? ` · ${det}` : ""));
  if (!cond) FALLOS.push(nombre);
  return !!cond;
};

instalarDOM();
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
globalThis.sessionStorage = globalThis.localStorage;
// `brain-status.js` se sirve como script clásico dentro de una pantalla: resuelve su raíz
// contra `document.currentScript` o `location`. El DOM mínimo no los trae — se declaran acá
// (no en `dom_minimo.mjs`: esto es lo que necesita ESTE archivo, no el doble en general).
// RAÍZ `file://` REAL, y no es un detalle del sandbox: `seleccionDeContexto` traduce con el
// PUENTE de la obra D (`cuarto/cuarto.models.js`) por `import()` dinámico relativo a esta
// raíz. Con una raíz http la vara importaría la nada y mediría el `catch`, no el puente.
globalThis.location = { href: new URL("product/app/design/brain-status.js", "file://" + RAIZ + "/").href,
                        origin: "file://" };
if (!globalThis.document.currentScript) globalThis.document.currentScript = null;
globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(t, o) { this.type = t; Object.assign(this, o || {}); } };
globalThis.addEventListener = globalThis.addEventListener || (() => {});
globalThis.dispatchEvent = globalThis.dispatchEvent || (() => true);

/* ── brain-status.js es un script clásico (IIFE), no un módulo: se evalúa. ───────────── */
const FUENTE = readFileSync(join(D, "brain-status.js"), "utf8");

/** El payload EXACTO que sirve `/v1/modelos/selector?contexto=sala` (centro_modelos.py):
 *  `contextos` con la preferencia del dueño, y el pool con su mapa `slug` ↔ `picker_id`. */
function payload({ pref, enElPool = true }) {
  // ⚠️ FILAS COPIADAS DE LA MEDICIÓN, no inventadas. La primera versión traía sólo `slug` y
  // `picker_id`, y con eso `curadoDesdeFila` devolvía `null` para la vía de API — no porque
  // el puente fallara, sino porque el fixture no se parecía a lo que el backend sirve. Un
  // fixture que no coincide con la realidad es una vara que mide ficción. Estos campos
  // salen de `GET /v1/modelos/selector?contexto=sala&todos=1` contra el sidecar real:
  // `byok_ref` es lo que hace traducible una vía de API, y `brain_provider` una de CLI.
  const modelos = [
    { slug: "cli.claude_cli", picker_id: "claude_cli", conectado: true,
      brain_provider: "claude_cli", model: "claude-code-cli",
      base_url: "http://127.0.0.1:8926/v1" },
    { slug: "cli.codex_cli", picker_id: "codex_cli", conectado: true,
      brain_provider: "codex_cli", model: "codex-cli",
      base_url: "http://127.0.0.1:8926/v1" },
    { slug: "api.openrouter", picker_id: "api:openrouter", conectado: true,
      byok_ref: "keys:openrouter", model: "openai/gpt-4o",
      base_url: "https://openrouter.ai/api/v1" },
  ];
  return {
    version: 2, contexto: "sala",
    contextos: pref ? { sala: pref, cuarto: pref } : {},
    modelos: enElPool ? modelos : [],
    default: "api.groq", seleccion: pref || null,
  };
}

/** Monta `brain-status.js` con el selector servido por un fixture. Devuelve `AlephBrain`. */
function montar(pl) {
  globalThis.window = globalThis.window || globalThis;
  delete window.AlephBrain;
  globalThis.fetch = async (url) => {
    if (String(url).indexOf("/v1/modelos/selector") >= 0)
      return { ok: true, status: 200, json: async () => pl };
    return { ok: true, status: 200, json: async () => ({}) };
  };
  // eslint-disable-next-line no-new-func
  new Function(FUENTE)();
  return window.AlephBrain;
}

console.log("\n══ LA SALA USA EL CEREBRO QUE EL DUEÑO ELIGIÓ ══\n");

/* ══ 1 · LA PREFERENCIA SE EXPONE Y SE RESUELVE ═══════════════════════════════════════ */
console.log("1 · brain-status expone la preferencia");
{
  const B = montar(payload({ pref: "cli.codex_cli" }));
  ok("1_la_puerta_existe", typeof B.seleccionDeContexto === "function");
  const sel = await B.seleccionDeContexto("sala");
  ok("1_resuelve_la_preferencia_del_dueno",
    !!sel && sel.active === "codex_cli" && sel.id === "codex_cli",
    JSON.stringify(sel));

  // ⚠️ DISCRIMINANTE. Con OTRA preferencia tiene que dar OTRO cerebro. Sin esto, `1_` se
  // cumpliría con una función que devuelve `codex_cli` siempre — que es leer cualquier cosa.
  const B2 = montar(payload({ pref: "cli.claude_cli" }));
  const sel2 = await B2.seleccionDeContexto("sala");
  ok("1_discriminante_con_claude_resuelve_claude",
    !!sel2 && sel2.active === "claude_cli", JSON.stringify(sel2));

  // …y una preferencia de API resuelve BYOK con su proveedor, por el mismo mapa del pool.
  const B3 = montar(payload({ pref: "api.openrouter" }));
  const sel3 = await B3.seleccionDeContexto("sala");
  ok("1_una_api_resuelve_byok_con_su_proveedor",
    !!sel3 && sel3.active === "byok" && sel3.provider === "openrouter", JSON.stringify(sel3));
}

/* ══ 2 · LOS NEGATIVOS ════════════════════════════════════════════════════════════════ */
console.log("\n2 · los negativos");
{
  // NEGATIVO 1 · SIN preferencia guardada → `null`, no un cerebro inventado. `null` es la
  // respuesta correcta: deja que `elegirDefault()` elija el primero utilizable.
  const B = montar(payload({ pref: null }));
  ok("2_negativo_sin_preferencia_no_inventa", (await B.seleccionDeContexto("sala")) === null);

  // NEGATIVO 2 · la preferencia existe pero su modelo YA NO ESTÁ en el pool (se cayó) →
  // tampoco se fuerza: `null`, y elige el default. Devolver un cerebro muerto sería peor
  // que no devolver nada.
  const B2 = montar(payload({ pref: "cli.codex_cli", enElPool: false }));
  ok("2_negativo_una_preferencia_muerta_no_se_fuerza",
    (await B2.seleccionDeContexto("sala")) === null);

  // NEGATIVO 3 · un contexto que nadie configuró no hereda el de al lado.
  const B3 = montar(payload({ pref: "cli.codex_cli" }));
  ok("2_negativo_otro_contexto_no_hereda", (await B3.seleccionDeContexto("guia")) === null);
}

/* ══ 3 · LA SALA · EL HARD-CODE SE FUE Y EL GUARD VUELVE A CORRER ═════════════════════ */
console.log("\n3 · la Sala ya no clava «included»");
{
  const sala = readFileSync(join(D, "sala/sala.html"), "utf8");
  // Se mira el RETURN, no cualquier mención: el comentario que explica por qué se fue cita
  // el código viejo a propósito, y un grep grueso lo leía como si el bug siguiera ahí. Un
  // testigo que no distingue el código de su explicación acusa a la documentación.
  ok("3_el_hardcode_murio", !/return\s*\{\s*selected\s*:\s*['"]included['"]\s*\}/.test(sala));
  ok("3_la_sala_consume_la_preferencia",
    sala.indexOf("seleccionDeContexto('sala')") >= 0
    && sala.indexOf("_salaSeleccion ? { selected:_salaSeleccion } : {}") >= 0);
  // …y la carga ANTES de resolver: si resolviera primero, pintaría un cerebro ajeno y se
  // corregiría después — un parpadeo que se lee como que la Sala cambió de opinión sola.
  const iCarga = sala.indexOf("cargarSeleccionDeSala()");
  const iResolve = sala.indexOf("AlephBrain.resolve(Object.assign({refresh:true}");
  ok("3_la_carga_va_antes_de_resolver", iCarga > 0 && iResolve > 0 && iCarga < iResolve,
    `carga@${iCarga} resolve@${iResolve}`);

  // ⚠️ EL TESTIGO QUE EXPLICA POR QUÉ ERA UN BUG Y NO UN DEFAULT FEO: sin selección
  // explícita, `normalizeSelected` marca `_tentativo`, y ESA marca es la que habilita
  // `elegirDefault()`. El hard-code la borraba.
  const B = montar(payload({ pref: null }));
  const tentativo = B.normalizeSelected(undefined, {});
  ok("3_sin_seleccion_queda_tentativo_y_elige_el_default",
    !!tentativo && tentativo._tentativo === true, JSON.stringify(tentativo));
  const explicito = B.normalizeSelected("included", {});
  ok("3_negativo_nombrar_included_a_mano_esquivaba_el_guard",
    !!explicito && explicito.active === "included" && !explicito._tentativo,
    "una selección explícita NO lleva `_tentativo` — por eso el hard-code saltaba elegirDefault");
}

/* ══ 4 · GUARD · NO SE TOCÓ LO SELLADO POR GATE 2 ═════════════════════════════════════ */
console.log("\n4 · guard · el vocabulario sellado sigue intacto");
{
  const B = montar(payload({ pref: "cli.codex_cli" }));
  ok("4_semaforoDe_sigue_siendo_del_widget",
    FUENTE.indexOf("function semaforoDe") < 0,
    "brain-status no define un derivador propio: el único vive en modelos.widget.js");
  ok("4_no_se_agrego_diccionario_de_causas",
    typeof B.CAT_DE_CAUSA === "object" && B.CAT_DE_CAUSA !== null);
  ok("4_la_puerta_nueva_no_deriva_estado",
    !/estado|semaforo|probar/i.test(
      FUENTE.slice(FUENTE.indexOf("async function seleccionDeContexto"),
                   FUENTE.indexOf("async function seleccionDeContexto") + 1400)),
    "seleccionDeContexto responde QUÉ eligió el dueño, no si sirve");
}

console.log("\n" + "═".repeat(78));
console.log("MEDIDO=" + JSON.stringify(R));
if (FALLOS.length) {
  console.log(`❌ ${FALLOS.length} FALLO(S): ${FALLOS.join(", ")}`);
  process.exit(1);
}
console.log(`✅ verify_sala_cerebro_del_dueno: ${Object.keys(R).length}/${Object.keys(R).length} TODO VERDE`);
// SALIDA EXPLÍCITA. `brain-status.js` se monta como en una pantalla de verdad y deja sus
// temporizadores vivos, así que node no termina solo: en verde la vara se colgaba hasta el
// timeout de quien la corre, y un verde que nunca vuelve se lee como un cuelgue. El camino
// rojo ya salía por `exit(1)` — sin esto, sólo el fracaso terminaba.
process.exit(0);
