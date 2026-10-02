/* fixture_constelacion.mjs — escena de CONSTELACIÓN (capa 3) para ver los cúmulos + las 3 vistas + el
 * brillo por relevancia. NO toca el fixture base (cuarto.scene.json): siembra piezas VIVAS por el api
 * (igual que los verify del recinto), via api.placeTile / api.placeRecinto.
 *
 * Diseñada para que las 3 vistas (doc §6) reagrupen DISTINTO la MISMA data:
 *   · servicio (server||connector): tmdb · exa · gmail · sec_edgar · kb (recinto)   → 5 cúmulos
 *   · funcion  (role):              lee(fuentes) · procesa(mesa) · actua(entrega)    → 3 cúmulos
 *   · relacion (recinto||conexión): agt · cx_tmdb · cx_gmail · sueltas               → 4 cúmulos
 * Y para que el BRILLO por relevancia (C2) tenga señal: un recinto-agente con 2 hijos + 2 conexiones
 * con fan-out (cada una habilita varias tools por server compartido).
 */

export const CONSTELACION_FIXTURE = {
  // recinto-AGENTE (Núcleo adentro) con 2 sub-piezas → relevancia por nº de hijos (C2).
  recintos: [
    { id: "agt", label: "Agente Research", nucleo: true, agent_ref: "a/research", gridX: 0, gridY: 4, w: 2, h: 2,
      children: [
        { id: "a1", key: "a1", label: "buscar_papers", category: "read",    server: "kb" },
        { id: "a2", key: "a2", label: "resumir",       category: "process", server: "kb" },
      ] },
  ],
  // conexiones (atom:"conexion") → su fan-out de tools del mismo server las hace relevantes (C2) y son
  // el hub de la vista "relacion".
  conexiones: [
    { id: "cx_tmdb",  key: "cx_tmdb",  label: "Conexión TMDB",  atom: "conexion", server: "tmdb",      gridX: 6, gridY: 2 },
    { id: "cx_gmail", key: "cx_gmail", label: "Conexión Gmail", atom: "conexion", connector: "gmail",  gridX: 4, gridY: 6 },
  ],
  // tools sueltas repartidas en los 3 roles + 4 server/connector distintos.
  tools: [
    { id: "t_tmdb_r", key: "t_tmdb_r", label: "buscar_película",  category: "read",    server: "tmdb",      gridX: 5, gridY: 2 },
    { id: "t_tmdb_p", key: "t_tmdb_p", label: "detalle_película", category: "process", server: "tmdb",      gridX: 5, gridY: 3 },
    { id: "t_exa_p",  key: "t_exa_p",  label: "buscar_web",       category: "process", server: "exa",       gridX: 2, gridY: 2 },
    { id: "t_edgar_r",key: "t_edgar_r",label: "leer_10K",         category: "read",    server: "sec_edgar", gridX: 6, gridY: 5 },
    { id: "t_gmail_p",key: "t_gmail_p",label: "armar_borrador",   category: "process", connector: "gmail",  gridX: 3, gridY: 6 },
    { id: "t_gmail_w",key: "t_gmail_w",label: "enviar_correo",    category: "write",   connector: "gmail",  gridX: 3, gridY: 5 },
  ],
};

/* Builder IN-PAGE (self-contained; se invoca con page.evaluate(buildConstelacion, CONSTELACION_FIXTURE)).
 * Limpia la escena y siembra recintos → conexiones → tools, en ese orden (determinístico). Devuelve el
 * conteo de piezas colocadas (recinto cuenta como 1 + sus hijos). */
export function buildConstelacion(fx) {
  const c = window.__cuarto;
  c.placedTiles().forEach((t) => c.removeTile(t.id));
  for (const r of fx.recintos) c.placeRecinto(r, r.children);
  for (const cx of fx.conexiones) c.placeTile(cx, cx.gridX, cx.gridY);
  for (const t of fx.tools) c.placeTile(t, t.gridX, t.gridY);
  return c.placedTiles().length;
}
