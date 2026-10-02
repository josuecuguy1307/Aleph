/* fixture_slots.mjs — escena mínima para los SLOTS (§8 del Cuarto). NO toca el fixture base
 * (cuarto.scene.json): siembra unas pocas piezas VIVAS por el api (igual que los verify del recinto /
 * constelación), via api.placeTile con celdas explícitas. Sirve para que:
 *   · balancedFreeCell tenga señal (hay piezas → el hueco balanceado NO es trivial);
 *   · el piso esté poblado (las capturas del grid que respira se leen);
 *   · queden celdas libres para arrastrar (probar el ghost fluido + el foco per-celda).
 * Las 4 aserciones del verify (0 adders · placeTile sin coords → balancedFreeCell · ghost interpola ·
 * floor-tint sube en modo-colocar) corren SOBRE esta escena.
 */

export const SLOTS_FIXTURE = {
  tools: [
    { id: "sf_r", key: "sf_r", label: "buscar_dato",   category: "read",    server: "tmdb",     gridX: 2, gridY: 2 },
    { id: "sf_p", key: "sf_p", label: "transformar",   category: "process", server: "tmdb",     gridX: 3, gridY: 2 },
    { id: "sf_w", key: "sf_w", label: "enviar",        category: "write",   connector: "gmail", gridX: 2, gridY: 4 },
    { id: "sf_x", key: "sf_x", label: "leer_web",      category: "read",    server: "exa",      gridX: 4, gridY: 3 },
  ],
};

/* Builder IN-PAGE (self-contained; se invoca con page.evaluate(buildSlots, SLOTS_FIXTURE)). Limpia la
 * escena y siembra las tools en celdas explícitas (determinístico). Devuelve el conteo colocado. */
export function buildSlots(fx) {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const t of fx.tools) c.placeTile(t, t.gridX, t.gridY);
  return c.placedTiles().length;
}
