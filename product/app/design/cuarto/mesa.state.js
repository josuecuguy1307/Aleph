/*
 * mesa.state.js — el STORE ÚNICO de una construcción (dos pieles lo leen).
 *
 * Un solo estado observable sobre el stream del space (EventSource GET
 * /v1/spaces/{id}/stream — replay + reconexión gratis). Proyecta los eventos del
 * motor sobre las 6 estaciones (espejo EXACTO de platform/inspection/mesa/proyeccion.py)
 * y acumula el inventario aprovechable. Modo Guiado y Modo Código se suscriben al MISMO
 * estado: el toggle NO cambia el estado, solo qué piel lo renderiza.
 *
 * Vocabulario: construcción / construir. Jamás forja.
 */

export const ESTACIONES = ["encontrarlo", "entrar", "ver", "armar", "probar", "equipar"];

// espejo de proyeccion._EVENTO_ESTACION — un evento del contrato → la estación que alimenta
const EVENTO_ESTACION = {
  "dispatch.iniciado": "encontrarlo", "resolver.buscando": "encontrarlo",
  "resolver.encontrado": "encontrarlo", "resolver.miss": "encontrarlo",
  "dispatch.forjando": "entrar", "forge.iniciado": "entrar", "sesion.ok": "entrar",
  "browser.session.iniciado": "entrar", "browser.fase": "entrar", "sesion.capturada": "entrar",
  "observando": "ver",
  "sintetizando": "armar", "tool.propuesta": "armar",
  "tool.validando": "probar", "tool.validada": "probar", "tool.descartada": "probar",
  "mcp.forjado": "equipar", "mcp.equipado": "equipar", "cerrado": "equipar",
};

export function indiceEstacion(est) {
  const i = ESTACIONES.indexOf(est);
  return i < 0 ? 0 : i + 1;
}

export function estacionDe(tipo) {
  return EVENTO_ESTACION[tipo] || null;
}

// avanza sin retroceder (espejo de proyeccion.avanzar)
export function avanzar(actual, tipo) {
  const destino = estacionDe(tipo);
  if (!destino) return actual;
  if (!actual) return destino;
  return indiceEstacion(destino) >= indiceEstacion(actual) ? destino : actual;
}

// estados de una pieza/estación en la coreografía (vocabulario visual del Cuarto)
export const ESTADO_ESTACION = {
  PENDIENTE: "pendiente",   // fantasma tenue
  ACTIVA: "activa",         // pulso
  LISTA: "lista",           // ✓ teal
  BLOQUEADA: "bloqueada",   // candado + razón (espera humano)
};

export class MesaState {
  constructor({ base = "" } = {}) {
    this.base = base;
    this.reset();
    this._subs = new Set();
  }

  reset() {
    this.construccionId = null;
    this.spaceId = null;
    this.estado = "trabajando";     // trabajando | pausada | terminada
    this.estacion = null;
    this.ok = false;
    this.pregunta = null;           // {pregunta_id, estacion, codigo, pregunta, opciones[]}
    this.convergencia = "";
    this.eventos = [];              // TODOS los eventos del contrato recibidos (para el diff cero-teatro)
    this.inventario = {
      identidad: {}, superficie: [], propuestas: [], validadas: [], descartadas: [],
      belt_ref: null, puppet_id: null, server: null,
    };
    // estado por estación (para el riel)
    this.estados = {};
    for (const e of ESTACIONES) this.estados[e] = ESTADO_ESTACION.PENDIENTE;
    this._es = null;
  }

  subscribe(fn) { this._subs.add(fn); fn(this); return () => this._subs.delete(fn); }
  _notify() { for (const fn of this._subs) { try { fn(this); } catch (e) { /* piel rota no tumba el store */ } } }

  // ── conexión al stream del space ──────────────────────────────────────────
  conectar(spaceId) {
    this.spaceId = spaceId;
    if (this._es) { try { this._es.close(); } catch (e) {} }
    const url = `${this.base}/v1/spaces/${encodeURIComponent(spaceId)}/stream`;
    const es = new EventSource(url);
    this._es = es;
    // el space stream nombra cada frame con event:<type>; escuchamos todos los tipos conocidos.
    const tipos = [
      "construccion.creada", "estacion.cambio", "pregunta.pendiente", "pregunta.respondida",
      "construccion.pausada", "construccion.reanudada", "construccion.borrador",
      "construccion.cerrada", "forge.iniciado", "forge.latido", "sesion.ok", "observando",
      "sintetizando", "tool.propuesta", "tool.validando", "tool.validada", "tool.descartada",
      "mcp.forjado", "mcp.equipado", "cerrado", "error", "dispatch.iniciado",
      "resolver.buscando", "resolver.encontrado", "resolver.miss", "dispatch.forjando",
      "browser.fase", "sesion.capturada",
    ];
    const on = (ev) => {
      let data = {};
      try { data = JSON.parse(ev.data); } catch (e) { return; }
      this._ingerir(ev.type || data.type, data);
    };
    for (const t of tipos) es.addEventListener(t, on);
    es.onerror = () => { /* EventSource reconecta solo con Last-Event-ID; no rompemos el estado */ };
    return es;
  }

  desconectar() { if (this._es) { try { this._es.close(); } catch (e) {} this._es = null; } }

  // ── ingesta de un evento (la ÚNICA mutación de estado) ────────────────────
  _ingerir(tipo, data) {
    if (!tipo) return;
    this.eventos.push({ tipo, data });

    // meta de la Mesa
    if (tipo === "construccion.creada") { this.construccionId = data.construccion_id || this.construccionId; }
    else if (tipo === "estacion.cambio") { this._entrar(data.estacion); }
    else if (tipo === "pregunta.pendiente") { this.pregunta = data; this.estado = "pausada";
      if (data.estacion) this.estados[data.estacion] = ESTADO_ESTACION.BLOQUEADA; }
    else if (tipo === "pregunta.respondida") { this.pregunta = null; }
    else if (tipo === "construccion.pausada") { this.estado = "pausada"; }
    else if (tipo === "construccion.reanudada") { this.estado = "trabajando"; this.pregunta = null;
      if (this.estacion) this.estados[this.estacion] = ESTADO_ESTACION.ACTIVA; }
    else if (tipo === "construccion.cerrada") { this.estado = "terminada"; this.ok = !!data.ok;
      this.convergencia = (data.resultado || {}).convergencia || this.convergencia;
      if (this.ok && this.estacion) this.estados["equipar"] = ESTADO_ESTACION.LISTA; }
    else if (tipo === "cerrado") { this.convergencia = data.convergence || this.convergencia; }

    // proyección estación + inventario desde el contrato del motor
    const destino = avanzar(this.estacion, tipo);
    if (destino && destino !== this.estacion) this._entrar(destino);
    this._absorber(tipo, data);
    this._notify();
  }

  _entrar(est) {
    if (!est) return;
    // marca las anteriores como listas, la actual como activa
    const idx = indiceEstacion(est);
    for (const e of ESTACIONES) {
      const ei = indiceEstacion(e);
      if (ei < idx && this.estados[e] !== ESTADO_ESTACION.BLOQUEADA) this.estados[e] = ESTADO_ESTACION.LISTA;
    }
    if (this.estados[est] !== ESTADO_ESTACION.BLOQUEADA) this.estados[est] = ESTADO_ESTACION.ACTIVA;
    this.estacion = est;
  }

  _absorber(tipo, d) {
    const inv = this.inventario;
    if (tipo === "sesion.ok") { inv.identidad.auth_form = d.auth_form || inv.identidad.auth_form; }
    else if (tipo === "resolver.encontrado" || tipo === "dispatch.iniciado") {
      if (d.service) inv.identidad.service = d.service;
      if (d.server_name) inv.identidad.server = d.server_name; }
    else if (tipo === "observando") {
      for (const ep of (d.new_confirmed || [])) if (!inv.superficie.includes(ep)) inv.superficie.push(ep); }
    else if (tipo === "tool.propuesta") {
      inv.propuestas.push({ nombre: d.nombre, endpoint: d.endpoint, method: d.method,
        kind: d.kind, params: d.params || {}, description: d.description, estado: "propuesta" }); }
    else if (tipo === "tool.validando") { this._marcarTool(d.nombre, "validando", { request: d.request }); }
    else if (tipo === "tool.validada") {
      this._marcarTool(d.nombre, "validada", { verified_by: d.verified_by, status: d.status, payload: d.payload });
      if (!inv.validadas.find(v => v.nombre === d.nombre))
        inv.validadas.push({ nombre: d.nombre, verified_by: d.verified_by, status: d.status,
          fuerte: String(d.verified_by || "").startsWith("200") }); }
    else if (tipo === "tool.descartada") {
      this._marcarTool(d.nombre, "descartada", { motivo: d.motivo, move: d.move });
      inv.descartadas.push({ nombre: d.nombre, motivo: d.motivo, clase: d.clase, move: d.move }); }
    else if (tipo === "mcp.forjado" || tipo === "mcp.equipado") {
      inv.belt_ref = d.belt_ref || inv.belt_ref; inv.puppet_id = d.puppet_id || inv.puppet_id;
      inv.server = d.server || d.server_name || inv.server; }
  }

  _marcarTool(nombre, estado, extra) {
    const t = this.inventario.propuestas.find(p => p.nombre === nombre);
    if (t) Object.assign(t, { estado }, extra || {});
    else this.inventario.propuestas.push(Object.assign({ nombre, estado }, extra || {}));
  }

  // ── controles (POST) — cada uno una decisión REAL del pipeline ─────────────
  async _post(path, body) {
    const r = await fetch(`${this.base}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let j = {}; try { j = await r.json(); } catch (e) {}
    return { status: r.status, ok: r.ok, body: j };
  }

  static async crear(base, pedido) {
    const st = new MesaState({ base });
    const r = await st._post("/v1/construcciones", pedido);
    if (r.ok) { st.construccionId = r.body.construccion_id; st.conectar(r.body.space_id); }
    return { st, resp: r };
  }

  responder(opcion, aporte) { return this._post(`/v1/construcciones/${this.construccionId}/respuesta`, { opcion, aporte }); }
  aportar(a) { return this._post(`/v1/construcciones/${this.construccionId}/aportar`, a); }
  redirigir(alcance) { return this._post(`/v1/construcciones/${this.construccionId}/redirigir`, { alcance }); }
  credencial(cred) { return this._post(`/v1/construcciones/${this.construccionId}/credencial`, { cred }); }
  retomar(session_key) { return this._post(`/v1/construcciones/${this.construccionId}/retomar`, { session_key }); }
  validarTools(tools, forma, cred) { return this._post(`/v1/construcciones/${this.construccionId}/tools/validar`, { tools, forma, cred }); }
  probarTool(tool, args, execute, forma, cred) { return this._post(`/v1/construcciones/${this.construccionId}/tools/probar`, { tool, args, execute, forma, cred }); }
  equipar(keep) { return this._post(`/v1/construcciones/${this.construccionId}/equipar`, { keep }); }
  cancelar() { return fetch(`${this.base}/v1/construcciones/${this.construccionId}`, { method: "DELETE" }).then(r => r.json()); }
}
