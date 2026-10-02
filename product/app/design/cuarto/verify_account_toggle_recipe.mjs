/* TICKET 4 · compilación del toggle "conoce tu cuenta" → recipe.memory.account_read.
 * Puro (sin browser): importa tilesToRecipe del módulo real y verifica la simetría con el
 * round-trip (la misma llave que loadPuppet rehidrata a nucleo._accountRead).
 * Run: node product/app/design/cuarto/verify_account_toggle_recipe.mjs
 */
// stub del entorno browser: tilesToRecipe delega la base a window.Projection.canvasToRecipe;
// devolvemos una receta base mínima y dejamos que la capa del toggle (lo que probamos) la mute.
globalThis.window = {
  Projection: {
    canvasToRecipe: ({ nucleo }) => ({
      schema_version: "v1", meta: {}, model: {}, belt: {}, framing: {}, rag: {}, keys: {}, gates: {},
    }),
  },
  __models: { list: [] },
};

const { tilesToRecipe, NUCLEO } = await import("./cuarto.recipe.js");

let P = 0, F = 0; const FAIL = [];
const ok = (c, name, extra = "") => { c ? P++ : (F++, FAIL.push(name)); console.log(`${c ? "✓" : "✗"} ${name}${c ? "" : "  · " + extra}`); };

// una pieza mínima (un átomo cualquiera) para que la receta se arme
const tile = { id: "t1", role: "tool", server: "calc", tool: "add", label: "Sumar" };
const nuc = (over) => Object.assign({}, NUCLEO, over);

// 1 · DEFAULT (sin tocar el toggle) → NO escribe account_read (receta byte-idéntica)
const rDef = tilesToRecipe([tile], nuc({}));
ok(!(rDef.memory && "account_read" in rDef.memory),
   "default omite memory.account_read (byte-idéntico)", JSON.stringify(rDef.memory || {}));

// 2 · toggle en 'sí' explícito (_accountRead === undefined) → tampoco escribe (default = SÍ)
const rYes = tilesToRecipe([tile], nuc({ _accountRead: undefined }));
ok(!(rYes.memory && "account_read" in rYes.memory),
   "SÍ explícito (undefined) tampoco escribe la llave", JSON.stringify(rYes.memory || {}));

// 3 · toggle en 'no' (_accountRead === false) → escribe account_read:false
const rNo = tilesToRecipe([tile], nuc({ _accountRead: false }));
ok(rNo.memory && rNo.memory.account_read === false,
   "NO la conoce → recipe.memory.account_read === false", JSON.stringify(rNo.memory || {}));

// 4 · convive con inherit (no se pisan)
const rBoth = tilesToRecipe([tile], nuc({ _accountRead: false, _inherit: "skill_only" }));
ok(rBoth.memory && rBoth.memory.account_read === false && rBoth.memory.inherit === "skill_only",
   "account_read convive con inherit sin pisarse", JSON.stringify(rBoth.memory || {}));

// 5 · round-trip: la llave que produce compilar es la que loadPuppet lee (misma convención)
//     (loadPuppet: nd._accountRead = recipe.memory.account_read === false ? false : undefined)
const roundtrip = (recipe) => (recipe.memory && recipe.memory.account_read === false) ? false : undefined;
ok(roundtrip(rNo) === false, "round-trip de 'no' → _accountRead false");
ok(roundtrip(rDef) === undefined, "round-trip de default → _accountRead undefined (SÍ)");

console.log(`\n${F === 0 ? "VERDE" : "ROJO"} — ${P} PASS · ${F} FAIL`);
if (FAIL.length) FAIL.forEach((f) => console.log(`  ✗ ${f}`));
process.exit(F === 0 ? 0 : 1);
