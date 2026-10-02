/* cuarto.recipe.js — el puente entre la capa de render (Pixi) y la capa de receta.
 *
 * Render layer  : api.placedTiles() → [{id, key, label, category, gridX, gridY, role,
 *                  atom, server, ref, tools, belt_ref, connector}]   (la pieza arrastra su data)
 * Recipe layer  : window.Projection (projection.js) ⇄ puppets.config v1
 *
 * C1: el catálogo es REAL (multi-belt). La pieza colocada YA carga su belt_ref/server/
 * tools/connector, así que tilesToRecipe NO necesita el catálogo: serializa directo.
 * La proyección une los belt_refs[] (composición) y mete las conexiones como BYOK.
 * recipeToTiles SÍ recibe el catálogo real para rehidratar label/tools/zona de una receta.
 */

import { compileModel } from "./cuarto.models.js";
import { applyRecipeControls } from "./cuarto.controls.js";

export const NUCLEO = {
  name: "Mi agente", nicho: "general", descripcion: "",
  model: "opus", gridX: 3, gridY: 1,   // el modelo del agente (picker en el núcleo, gap 1)
  _autonomy: "balanceado",   // A2 · perilla agent-level (manual|balanceado|autonomo); el gate la aplica
  _detail: "normal", _steps: "auto", _maxTurns: 8, _instructions: "",
};

/** placed render tiles → recipe v1 (config), via Projection.canvasToRecipe. */
export function tilesToRecipe(placed, nucleo = NUCLEO) {
  const blocks = (placed || []).map((t) => ({
    id: t.id,
    atom: t.atom || "tool",
    card_id: t.key || t.id,
    label: t.label,
    ref: t.ref || t.server || null,
    tools: t.tools || [],
    zone: t.role || t.zone || "mesa",
    belt_ref: t.belt_ref || null,
    connector: t.connector || null,
    // [reforma · a] un MCP plegado puede necesitar MÁS DE UNA cuenta (maritime: GFW +
    // OpenSanctions). Sin esto, plegar perdía la segunda credencial en silencio.
    connectors: (t.connectors && t.connectors.length) ? t.connectors.slice() : undefined,
    service: t.service || undefined,
    diorama_symbol: t.diorama_symbol || "generico",
    servers: (t.servers && t.servers.length)
      ? t.servers.map((server) => JSON.parse(JSON.stringify(server))) : undefined,
    belt_refs: (t.belt_refs && t.belt_refs.length) ? t.belt_refs.slice() : undefined,
    credential: t.credential ? JSON.parse(JSON.stringify(t.credential)) : undefined,
    gridX: t.gridX, gridY: t.gridY,
    // AGENTE ANIDADO (paso 5): una pieza-agente arrastra su ref + el marcador de Núcleo desde
    // el tile. Para un tile-tool normal ambos quedan undefined → la proyección no cambia.
    agent_ref: t.agent_ref || null, nucleo: t.nucleo,
    child_model: t.child_model || undefined,   // 2c · el modelo propio elegido en el mini-Aleph
    sharesMemory: t.sharesMemory,   // STEP 2·B2 · membresía del bus de memoria compartida (línea teal; undefined = conectado)
  }));
  const links = blocks.map((b) => ({ from: b.id, to: "nucleo" }));
  let recipe = window.Projection.canvasToRecipe({ nucleo, blocks, links });

  // C4: las perillas de las piezas COMPILAN a la receta (mismo delta que Chat/Código).
  // Autonomía → gates (válidos: 'off' | 'needs_ok'). Sólo cuenta lo que TOCA el mundo.
  const world = (placed || []).filter((t) => t.role === "entrega" || t.atom === "conexion");
  const anyWorld = world.length > 0;
  const wantsGate = world.some((t) => (t._autonomy || "ok") !== "auto" || t.gated);
  recipe.gates = anyWorld && !wantsGate
    ? { money_touch: "off", send: "off" }
    : { money_touch: "needs_ok", send: "needs_ok" };
  // Perillas AGENT-LEVEL desde el NÚCLEO (gap 1 + 4): modelo · detalle/instrucciones → framing ·
  // pasos → max_turns.
  // Slice D: Cuarto y Sala pliegan las mismas perillas en el mismo contrato. El metadata
  // del núcleo permite reabrir Detalle/Pasos/instrucciones sin parseos destructivos.
  recipe = applyRecipeControls(recipe, {
    model: nucleo.model || "opus",
    cliModel: nucleo._cliModel || "",
    effort: nucleo._effort || "",
    byok: nucleo._byok || null,
    detail: nucleo._detail || "normal",
    instructions: nucleo._instructions || "",
    steps: nucleo._steps || "auto",
    maxTurns: nucleo._maxTurns || 8,
  });
  const maxTurns = recipe.model.max_turns;
  // OLA 4 · §2/§3 · SLOT del modelo ECONÓMICO de los workers (recipe.model.workers). Sólo si el
  // usuario eligió uno; si no, se OMITE → el backend HEREDA el principal (resolve_workers_model → None)
  // y la receta queda byte-idéntica a hoy. compileModel da la forma plana que lee resolve_workers_model.
  if (nucleo._workersModel) recipe.model.workers = compileModel(nucleo._workersModel, { max_turns: 2, max_tokens: 700 });
  // Step 2 · C1 · RECONCILIACIÓN de los DOS escritores de rag.enabled. Antes esta línea PISABA
  // recipe.rag con `!!nucleo._memory` (la perilla de memoria del Núcleo), después de que
  // projection.canvasToRecipe ya lo hubiera puesto en `!!hasContexto` (la PIEZA Conocimiento):
  // dos verdades en conflicto, y el clobber ganaba → la pieza Conocimiento se ignoraba.
  // AHORA la PIEZA Conocimiento (átomo contexto) es el ÚNICO driver de RAG (projection lo dejó
  // correcto, con mode/dir intactos). La perilla de memoria del Núcleo es A3 puro (memoria entre
  // corridas, server-side por puppet_id) y NO toca recipe.rag. No re-escribimos recipe.rag acá.
  // A2 · AUTONOMÍA agent-level (perilla del Núcleo → candado del gate en el runtime). Valores
  // 'manual'|'balanceado'|'autonomo' (distinto del per-pieza auto/ok/stop, y del gates{off|needs_ok}
  // binario de arriba, que es UX display). El gate decide auto/hold por clase; el piso money no baja.
  // COERCIÓN (review A2): si el chat del Núcleo dejó un valor del namespace per-pieza (auto/ok/stop)
  // u otra basura en _autonomy, cae a 'balanceado' — jamás serializamos un valor inválido que el
  // validador rebotaría con 422 al Guardar/Correr. Frontera dura, robusta ante cómo se corrompió.
  const _AUT_OK = { manual: 1, balanceado: 1, autonomo: 1 };
  recipe.autonomy = _AUT_OK[nucleo._autonomy] ? nucleo._autonomy : "balanceado";
  // ORDEN 6 · HERENCIA · el selector del panel escribe la POLÍTICA que el executor ya lee en el
  // A3-read (recipe.memory.inherit). Sólo la tocamos si el usuario eligió una política EXPLÍCITA
  // ('skill_only'); el default ('todo') OMITE la llave → None = continuación (recall decide), y la
  // receta queda byte-idéntica a hoy. NO pisa un bus compartido que la proyección ya haya puesto
  // (shared+ref conviven con inherit): mergeamos sobre recipe.memory en vez de reemplazarlo.
  if (nucleo._inherit) {
    recipe.memory = Object.assign({}, recipe.memory, { inherit: nucleo._inherit });
  }
  // ticket 4 · TOGGLE "conoce tu cuenta" → recipe.memory.account_read. Sólo escribimos la llave si
  // el usuario APAGÓ la lectura (account_read:false); el default SÍ la OMITE → receta byte-idéntica.
  // Merge sobre recipe.memory (convive con inherit/shared que la proyección ya haya puesto).
  if (nucleo._accountRead === false) {
    recipe.memory = Object.assign({}, recipe.memory, { account_read: false });
  }
  // 2c · modelo propio por sub-agente: recompilar cada child_model con el compilador REAL del
  // Cuarto (compileModel; la proyección puso un placeholder de su tabla reducida). El alias viaja
  // junto al cfg para que la rehidratación recupere la elección humana.
  if (recipe.belt && recipe.belt.agent_policy && recipe.belt.agent_policy.child_models) {
    const cm = recipe.belt.agent_policy.child_models;
    (placed || []).forEach((t) => {
      if (!t.child_model || !(t.agent_ref || t.ref)) return;
      const slug = String(t.agent_ref || t.ref).split("/").pop().replace(/\.config\.json$|\.json$/, "");
      if (cm[slug]) cm[slug] = Object.assign(compileModel(t.child_model, { max_turns: maxTurns }), { alias: t.child_model });
    });
  }
  // MULTIAGENTE F2 · el modo se DECLARA; nunca se deduce del dibujo. Los cables
  // que el usuario trazó viajan por el campo que consume el motor sellado. Si el
  // motor los derivó y el usuario no dibujó ninguno, `_agentLinks` queda vacío y
  // se omite para conservar esa distinción en `plan.cables_derivados`.
  if (nucleo._multiModo) recipe.modo = nucleo._multiModo;
  if (Array.isArray(nucleo._agentLinks) && nucleo._agentLinks.length) {
    recipe.belt = recipe.belt || {};
    recipe.belt.agent_links = nucleo._agentLinks.map((c) => ({
      from: c.from, to: c.to, tipo: c.tipo || "entregar",
    }));
  }
  return recipe;
}

/** GUARDAR-POSICIÓN · captura la posición (gridX,gridY) de cada pieza colocada en una lista
 *  PLANA y la mete en recipe.canvas.layout. ADITIVO: vive en el bloque `canvas` (presentación
 *  pura — el motor la ignora, La Sala no la lee, y el validador la PERMITE: `canvas` está en
 *  _ALLOWED_TOP_KEYS y NO inspecciona su interior). Una receta v1 sin esto sigue válida; un
 *  consumidor viejo la ignora. `placed` = api.placedTiles(). NO inventa: sólo serializa lo
 *  que el render ya sabe (mismo gridX/gridY que canvas.blocks, pero explícito y plano). */
export function attachLayout(recipe, placed) {
  recipe = recipe || {};
  recipe.canvas = recipe.canvas || {};
  recipe.canvas.layout = (placed || [])
    .filter((t) => t && t.id != null && t.gridX != null && t.gridY != null)
    .map((t) => ({ id: t.id, gridX: t.gridX, gridY: t.gridY }));
  return recipe;
}

/** CARGAR-POSICIÓN · re-aplica el `layout` guardado sobre los tiles rehidratados: cada pieza
 *  cae donde el usuario la dejó (gridX/gridY del layout) EN VEZ del auto-layout. Compat hacia
 *  atrás: un agente viejo SIN layout (o un tile sin entrada en él) conserva el gridX/gridY que
 *  ya traía de la receta (canvas.blocks); si tampoco trae, el caller cae al auto-layout de
 *  placeTile (gridX/gridY null → balancedFreeCell). NUNCA inventa una posición. */
export function applyLayout(tiles, layout) {
  if (!Array.isArray(layout) || !layout.length) return tiles || [];
  const byId = {};
  layout.forEach((p) => { if (p && p.id != null) byId[p.id] = p; });
  return (tiles || []).map((t) => {
    const p = byId[t.id];
    return p ? { ...t, gridX: p.gridX, gridY: p.gridY } : t;
  });
}

/** recipe v1 (config) → render tiles, via Projection.recipeToCanvas (rehidratar).
 *  `catalog` = lista normalizada de loadAtoms() (para reconstruir label/tools/zona). */
export function recipeToTiles(recipe, catalog = [], agents = []) {
  const st = window.Projection.recipeToCanvas(recipe, catalog, agents);
  // [reforma · a] MIGRACIÓN al modelo por-MCP, al REHIDRATAR (no hay migración de archivos:
  // los agentes guardados viven en la DB del usuario). Dos bloques del mismo server —una card
  // por grupo de tools, p.ej. cad-freecad + cad-script— eran dos piezas idénticas en el piso;
  // ahora son UNA con la unión de sus tools. Las nativas se retiran del piso. El resto del
  // canvas queda intacto, así que guardar/cargar sigue funcionando con recetas viejas.
  const mig = (window.CuartoCatalogo && window.CuartoCatalogo.migrarBloquesAMcp)
    ? window.CuartoCatalogo.migrarBloquesAMcp(st.blocks || [])
    : { blocks: st.blocks || [], plegados: 0, nativas: 0 };
  // hook de verificación / reporte: cuántas piezas se plegaron y cuántas se volvieron nativas
  try { window.__ultimaMigracion = { plegados: mig.plegados, nativas: mig.nativas }; } catch (e) {}
  return (mig.blocks || [])
    .filter((b) => b.gridX != null && b.gridY != null)
    .map((b) => ({
      id: b.id, key: b.card_id, label: b.label,
      category: b.category || "process",
      gridX: b.gridX, gridY: b.gridY, role: b.zone,
      atom: b.atom, server: b.ref, ref: b.ref, tools: b.tools,
      belt_ref: b.belt_ref, connector: b.connector, connectors: b.connectors,
      service: b.service, servers: b.servers, belt_refs: b.belt_refs,
      diorama_symbol: b.diorama_symbol || "generico",
      credential: b.credential,
      // AGENTE ANIDADO (paso 5): una pieza-agente rehidrata con su ref + Núcleo (undefined en tools).
      agent_ref: b.agent_ref, nucleo: b.nucleo,
      sharesMemory: b.sharesMemory,   // STEP 2·B2 · membresía del bus (undefined = conectado por default)
    }));
}
