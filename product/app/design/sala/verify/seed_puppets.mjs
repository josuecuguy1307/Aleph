/* seed_puppets.mjs — siembra idempotente de los puppets QA del harness.
 *
 * Los casos vivos corren con primary:'brain' (con PUPPET_BRAIN_SHIM=1 en el backend el
 * alias rutea al shim :8923 = Opus real vía cuenta Max, costo cero). fallback:'brain'
 * a propósito: si el shim cae, el run FALLA VISIBLE en vez de degradar a OSS en silencio
 * — esta red de seguridad no quiere greens enmascarados.
 *
 * Recetas = datos apuntando a fixtures del assembler; NINGÚN belt/servidor se edita. */
import fs from "node:fs";
import { BACK, STATE_FILE, GMAIL_DUMMY } from "./_env.mjs";
import { ensureQaUser } from "./_drive.mjs";

/* framings de PRODUCTO (los mismos archivos que consumen los puppets reales del catálogo) */
const REPO = new URL("../../../../../", import.meta.url).pathname;
const framing = (rel) => fs.readFileSync(REPO + "catalog/templates/" + rel, "utf8");
/* receta hero compartida: brain shim (fail-visible), belt de catálogo con SOLO los servers
 * headless del héroe (tool_filters decide qué servers bootean — FreeCAD GUI queda fuera). */
const hero = (name, nicho, beltRef, filters, framingRel, turns) => ({
  schema_version: "v1",
  meta: { name, nicho },
  model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1400, max_turns: turns },
  belt: { belt_ref: beltRef, tool_filters: filters },
  framing: { inline: framing(framingRel) },
  rag: { enabled: false }, keys: {},
  gates: { money_touch: "needs_ok", send: "needs_ok" },
});

const RECIPES = {
  /* R1-R4 · héroes de nicho (regresión build→use sobre los productores REALES) */
  "qa-hero-fem": hero("QA Hero FEM", "ingenieria",
    "catalog/templates/ingenieria/belt-ingenieria.mcp.json",
    { fem: ["run_fem_analysis"] }, "ingenieria/framing-fem-loop.md", 14),
  "qa-hero-quant": hero("QA Hero Quant", "finanzas",
    "catalog/templates/finanzas/belt-finanzas-markets.mcp.json",
    { backtest: ["backtest_portfolio"] }, "finanzas/framing-backtest-loop.md", 14),
  "qa-hero-elec": hero("QA Hero Electronica", "electronica",
    "catalog/templates/electronica/belt-electronica.mcp.json",
    { spice: ["ac_sweep", "build_filter_schematic", "run_erc"] }, "electronica/framing-bode-loop.md", 14),
  "qa-hero-med": hero("QA Hero Medicina", "medicina",
    "catalog/templates/medicina/belt-medicina.mcp.json",
    { segmentacion: ["windowing", "extract_slice", "segment_structure", "render_volume_3d"] },
    "medicina/framing-medicina-visor.md", 10),
  /* N1 · nicho nuevo ECONOMISTA: serie macro keyless (worldbank) → obra rica linechart. */
  "qa-n1-economista": {
    schema_version: "v1",
    meta: { name: "QA N1 Economista", nicho: "finanzas" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1200, max_turns: 8 },
    belt: { belt_ref: "platform/connectors/finanzas/belt-finanzas-data.mcp.json", tool_filters: { finanzas: ["worldbank_series"] } },
    framing: { inline: "Sos un economista. Cuando el usuario pida una serie macro, traela REAL con worldbank_series (país e indicador correctos); los números salen de la tool, jamás de memoria. La serie se muestra sola como gráfico — NO la transcribas entera; cerrá con 1-2 líneas de lectura económica." },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
  /* N3 · nicho nuevo PROGRAMACIÓN: sandbox real (script_runner, gap B3) → informe con
   * code blocks monoespaciados PLANOS (decisión: sin highlight.js, post-launch). */
  "qa-n3-dev": {
    schema_version: "v1",
    meta: { name: "QA N3 Dev", nicho: "programacion" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1400, max_turns: 8 },
    belt: { belt_ref: "catalog/templates/programacion/belt-programacion.mcp.json", tool_filters: { script_runner: ["run_python", "run_shell"] } },
    framing: { inline: "Sos un desarrollador. Todo código que muestres lo PROBÁS antes en el sandbox (run_python); los outputs que cites salen de la ejecución real, jamás de memoria. Entregá un informe corto con el código en bloques ```python y los resultados observados." },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
  /* M1/M2 · delegación + memoria: padre que SOLO delega en el sub-agente del catálogo. */
  "qa-m-delegador": {
    schema_version: "v1",
    meta: { name: "QA M Delegador v2", nicho: "general" },   // v2: hijo qa-sum-sub (el v1 con research-sub quedó gated)
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1000, max_turns: 8 },
    // belt_ref requerido por el validador; tool_filters vacío = cero servers booteados
    // (el assembler solo bootea claves de tool_filters) → el padre queda sin tools propias.
    // Hijo = qa-sum-sub (run_python auto-ejecuta): research-sub (belt-calc pelado) cae en el
    // fail-closed del enforcer y su tool queda HELD — hijo gated = callejón sin salida (RIEL #1).
    belt: { belt_ref: "platform/assembler/fixtures/belt-calc.mcp.json", agent_refs: ["qa-sum-sub"], tool_filters: {} },
    framing: { inline: "Sos un coordinador. No tenés herramientas propias: para todo cálculo o búsqueda DELEGÁ en tu sub-agente pasándole la tarea CONCRETA y COMPLETA en `task` (incluí todo dato del usuario que el sub-agente necesite: él no ve esta conversación). Presentá el resultado que el sub-agente devuelva, citándolo." },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
  /* N2 · nicho nuevo COWORK: correo en borrador + send-gate (contra el stub GMAIL_API_BASE).
   * El framing NO prohíbe send_email: el enforcement es del GATE, no del prompt — el caso
   * prueba exactamente que send queda HELD aunque el agente lo intente. */
  "qa-n2-ejecutivo": {
    schema_version: "v1",
    meta: { name: "QA N2 Ejecutivo", nicho: "cowork" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1000, max_turns: 8 },
    belt: { belt_ref: "catalog/templates/cowork/belt-cowork-gmail.mcp.json", tool_filters: { gmail: ["create_draft", "send_email"] } },
    framing: { inline: "Sos un asistente ejecutivo. Preparás correos con create_draft (quedan en Borradores de la cuenta). Si el usuario pide ENVIAR, llamá send_email después de crear el borrador — el envío requiere la aprobación explícita del usuario y el sistema la va a pedir solo; no insistas si queda pendiente. Cerrá resumiendo en una frase qué hiciste." },
    rag: { enabled: false },
    keys: { gmail: { byok_ref: "keys:gmail" } },
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
  "qa-sala-brain": {
    schema_version: "v1",
    meta: { name: "QA Sala Brain", nicho: "general" },
    // alias gana en resolve_recipe_model (models.py): con PUPPET_BRAIN_SHIM=1 rutea al shim
    // :8923; primary/base_url solo satisfacen el validador. fallback:'brain' = shim caído
    // → falla VISIBLE, jamás degradación OSS silenciosa enmascarando el green.
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 1400, max_turns: 4 },
    belt: {
      belt_ref: "platform/assembler/fixtures/belt-inline-rich.mcp.json",
      tool_filters: { pysandbox: ["run_python"], datatools: ["write_xlsx", "write_csv"], calc: ["add", "sub", "mul", "div", "pow", "mod"] },
    },
    framing: { inline: "" },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
  "qa-sala-gate": {
    schema_version: "v1",
    meta: { name: "QA Sala Gate", nicho: "general" },
    model: { alias: "brain", primary: "brain", fallback: "brain", base_url: "http://127.0.0.1:8923/v1", temperature: 0.2, max_tokens: 900, max_turns: 4 },
    belt: {
      belt_ref: "platform/assembler/fixtures/belt-gated.mcp.json",
      tool_filters: { broker: ["lookup_price", "place_order", "send_message"] },
    },
    framing: { inline: "" },
    rag: { enabled: false }, keys: {},
    gates: { money_touch: "needs_ok", send: "needs_ok" },
  },
};

export async function seedPuppets() {
  const user = await ensureQaUser();
  const auth = { "Content-Type": "application/json", Authorization: "Bearer " + user.session_token };

  // BYOK dummy del stub de Gmail (idempotente): keys:gmail → GMAIL_TOKEN del server (N2)
  await fetch(BACK + "/v1/keys", {
    method: "POST", headers: auth,
    body: JSON.stringify({ user_id: user.id, provider: "gmail", secret: GMAIL_DUMMY }),
  }).catch(() => {});

  const existing = await fetch(BACK + "/v1/users/" + user.id + "/puppets", { headers: auth })
    .then((r) => (r.ok ? r.json() : { puppets: [] }));
  const byName = {};
  for (const p of (existing.puppets || [])) byName[(p.name || "").trim()] = p;

  const ids = {};
  for (const [key, recipe] of Object.entries(RECIPES)) {
    const name = recipe.meta.name;
    if (byName[name]) { ids[key] = byName[name].id; console.log("  = " + name + " ya existe (" + ids[key] + ")"); continue; }
    const r = await fetch(BACK + "/v1/puppets", {
      method: "POST", headers: auth,
      body: JSON.stringify({ owner_id: user.id, name, nicho: recipe.meta.nicho, config: recipe }),
    });
    if (r.status !== 201) {
      const body = await r.text();
      throw new Error("seed de '" + name + "' rechazado: HTTP " + r.status + " — " + body.slice(0, 500));
    }
    const p = await r.json();
    ids[key] = p.id;
    console.log("  + " + name + " creado (" + p.id + ")");
  }

  const state = { user: { id: user.id, email: user.email, session_token: user.session_token }, puppets: ids, seeded_at: new Date().toISOString() };
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  return state;
}

if (import.meta.url === "file://" + process.argv[1]) {
  seedPuppets().then((s) => console.log("estado → " + STATE_FILE)).catch((e) => { console.error("✗ " + e.message); process.exit(1); });
}
