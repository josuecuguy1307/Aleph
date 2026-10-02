/* cuarto.guide.js — EL LOOP del copiloto (cliente) + el DESPACHO de las 16 tools.
 *
 * Arquitectura (Option 1 · paridad-mano literal): el browser corre el loop de tool-calling
 * contra el modelo-guía (brainCall → costura chat en el backend) y EJECUTA cada tool_call
 * llamando el handler del `host` — que ES el mismo camino de código que el mouse del usuario
 * (window.__guideHost, definido en cuarto.pixi.html donde viven say/openInspector/api.*).
 *
 * Este módulo NO toca el DOM del Cuarto: sólo orquesta (loop + whitelist + despacho + historia).
 * Así se testea con un host mock + un brainCall mock, y con el host REAL prueba hand-parity.
 *
 * LÍNEA DE SEGURIDAD (regla 3+4): el whitelist es DEFENSA EN PROFUNDIDAD. El modelo-guía sólo
 * recibe las 16 tools de cuarto.guide.belt.js; si aun así alucina un nombre fuera de esa lista,
 * el despacho lo RECHAZA (no existe → degrada honesto "eso se hace en La Sala"). La ejecución
 * real la enforcea el host (las Puertas ABREN flujos gateados; nunca completan).
 */

import { GUIDE_TOOLS, GUIDE_TOOL_NAMES, guideTools, buildGuideSystem } from "./cuarto.guide.belt.js";
import { OPCIONES_TOOL_NAMES } from "../chat/opciones.js";
import { routeCatalogIntent, catalogQueryFromRequest } from "./cuarto.catalog.tools.js";
import { TOOL_NAME as CONEXION_INLINE } from "../chat/conexion-inline.js";

// [FIX-P7] Las 5 familias de OPCIONES no despachan a un handler de superficie: PINTAN el
// mensaje. Y cierran el turno (ver REGLA DE TURNO abajo).
const OPCIONES = new Set(OPCIONES_TOOL_NAMES);

// tool → (host, args) → resultado. Cada entrada llama UN método del host (el camino manual).
// El mapeo de args es explícito para no pasarle al host basura del modelo.
const DISPATCH = {
  ver_cuarto:             (h, a) => h.verCuarto(),
  inspeccionar_pieza:     (h, a) => h.inspeccionarPieza(a.id),
  estado_conexiones:      (h, a) => h.estadoConexiones(a.id),
  leer_estado:            (h, a) => h.leerEstado(a.id),
  probar_ahora:           (h, a) => h.probarAhora(a.id),
  mover_pieza:            (h, a) => h.moverPieza(a.id, a.gx, a.gy),
  organizar_cuarto:       (h, a) => h.organizar(a.criterio),
  enfocar:                (h, a) => h.enfocar(a),
  senalar:                (h, a) => h.senalar(a.id, a.nota),
  quitar_pieza:           (h, a) => h.quitarPieza(a.id),
  cerrar_inspector:       (h, a) => h.cerrarInspector(),
  buscar_catalogo_local:  (h, a) => h.buscarCatalogoLocal(a.query),
  buscar_registro:        (h, a) => h.buscarRegistro(a.query),
  proponer_pieza:         (h, a) => h.proponerPieza(a.servicio, a.nota),
  equipar_catalogo:       (h, a) => h.equiparCatalogo(a.servicio, a.nota),
  conectar_pieza:         (h, a) => h.conectarPieza(a.id),
  abrir_construccion_mcp: (h, a) => h.abrirConstruccionMcp(a.servicio, a.url),
  elegir_cerebro:         (h, a) => h.elegirCerebro(a.provider),
  gestionar_agente:       (h, a) => h.gestionarAgente(a.accion, a.nombre),
  ir_a_sala:              (h, a) => h.irASala(),
  tour:                   (h, a) => h.tour(a.tema),
  explicar:               (h, a) => h.explicar(a.id),
};

function parseArgs(tc) {
  const raw = tc && tc.function && tc.function.arguments;
  if (raw == null) return {};
  if (typeof raw === "object") return raw;
  try { return JSON.parse(raw); } catch { return {}; }
}

/**
 * createGuide({ host, brainCall, ...callbacks }) → { send, reset, running, snapshotMessages }.
 *
 * @param host       objeto con los handlers declarados (window.__guideHost) — el camino manual.
 * @param brainCall  async ({messages, tools}) → { content, tool_calls, model_final }
 *                   (una VUELTA del modelo-guía; el loop es del cliente, el server es stateless).
 * @param onAssistant (text, {model_final, final}) → pinta el mensaje del guía en el chat.
 * @param onTool      (name, args, key) → el guía va a ejecutar una tool (para narrar).
 * @param onToolResult(name, args, result, key) → EL DESENLACE de esa MISMA tool. `key` es
 *                    el id del tool_call: liga narración y desenlace sin adivinar por orden.
 * @param onClientTool(name,args,prosa) → Promise<resultado seguro>. Rinde una tool P7
 *                    interactiva y resuelve sin credencial para que el loop retome.
 * @param onError     (err) → error de red/modelo.
 * @param onBusy      (bool) → el loop está trabajando.
 * @param lang        "es" | "en".
 * @param maxRounds   tope duro de vueltas (anti-loop).
 * @param toolTimeoutMs plazo por tool (ver GUARD DE PLAZO abajo).
 */
export function createGuide({ host, brainCall, onAssistant, onTool, onToolResult, onClientTool, onError, onBusy, lang = "es", mode = "delegar", buildContext = null, maxRounds = 12, toolTimeoutMs = 25000 }) {
  let _mode = mode;
  let system = buildGuideSystem(lang, { mode: _mode });
  let messages = [{ role: "system", content: system }];
  let running = false;

  async function send(userText) {
    if (running) return null;
    const text = String(userText == null ? "" : userText).trim();
    if (!text) return null;
    running = true; if (onBusy) onBusy(true);
    // T5 · refresca el system con el ESTADO VIVO (receta + modelo) antes del turno (MD §6: contexto =
    // docs/guia [inyectado en backend] + semáforo [leer_estado/probar_ahora] + receta). Uno solo, siempre fresco.
    if (buildContext) { let ctx = null; try { ctx = await buildContext(); } catch (e) {} messages[0] = { role: "system", content: system + (ctx ? "\n\n" + ctx : "") }; }
    messages.push({ role: "user", content: text });
    let last = null;
    try {
      // DOS CATÁLOGOS · routing determinista antes del modelo. No depende de que el cerebro
      // interprete bien «ya tengo»: una señal local nunca puede terminar en la red. La llamada
      // sintética usa el MISMO transcript/dispatch que una tool_call del cerebro, así el resultado
      // vuelve al Guía para que lo narre. Si falta la fuente, la pregunta estructurada CIERRA el
      // turno con las dos opciones exactas; el tap vuelve como un mensaje humano nuevo.
      const catalogRoute = routeCatalogIntent(text);
      if (catalogRoute === "ambiguous") {
        const name = "preguntar_opciones";
        const args = {
          mensaje: lang === "en" ? "Where should I look?" : "¿Dónde quieres que busque?",
          preguntas: [{
            pregunta: lang === "en" ? "Which source?" : "¿En cuál de los dos?",
            tipo: "single",
            opciones: lang === "en"
              ? [{ label: "My catalog", valor: `Search my catalog · ${text}` }, { label: "The registry", valor: `Search the registry · ${text}` }]
              : [{ label: "Mi catálogo", valor: `Busca en mi catálogo · ${text}` }, { label: "El registro", valor: `Busca en el registro · ${text}` }],
          }],
        };
        const key = "catalog-route:options";
        messages.push({ role: "assistant", content: "", tool_calls: [
          { id: key, type: "function", function: { name, arguments: JSON.stringify(args) } },
        ] });
        let result;
        try { result = host.opciones ? host.opciones(name, args, "") : { ok: false, error: "esta superficie no sabe pintar opciones" }; }
        catch (e) { result = { ok: false, error: String((e && e.message) || e) }; }
        if (result && result.ok) result = { ok: true, mostrado: true, esperando_al_humano: true };
        if (onToolResult) onToolResult(name, args, result, key);
        messages.push({ role: "tool", tool_call_id: key, name, content: safeJson(result) });
        return { content: "", tool_calls: [], catalog_route: "ambiguous" };
      }
      if (catalogRoute === "local" || catalogRoute === "registry") {
        const name = catalogRoute === "local" ? "buscar_catalogo_local" : "buscar_registro";
        const args = { query: catalogQueryFromRequest(text, catalogRoute) };
        const key = "catalog-route:" + catalogRoute;
        messages.push({ role: "assistant", content: "", tool_calls: [
          { id: key, type: "function", function: { name, arguments: JSON.stringify(args) } },
        ] });
        if (onTool) onTool(name, args, key);
        let result;
        try {
          result = await conPlazo(DISPATCH[name](host, args), toolTimeoutMs, name, lang);
          if (result == null) result = { ok: true };
        } catch (e) { result = { ok: false, error: String((e && e.message) || e) }; }
        if (onToolResult) onToolResult(name, args, result, key);
        messages.push({ role: "tool", tool_call_id: key, name, content: safeJson(result) });
      }
      for (let round = 0; round < maxRounds; round++) {
        const res = await brainCall({ messages, tools: guideTools(lang) });
        last = res;
        const calls = (res && res.tool_calls) || [];
        const asst = { role: "assistant", content: (res && res.content) || "" };
        if (calls.length) asst.tool_calls = calls;
        messages.push(asst);
        const isFinal = !calls.length;
        if (res && res.content && onAssistant) onAssistant(res.content, { model_final: res.model_final, final: isFinal });
        if (isFinal) return res;   // el modelo cerró con texto → fin del turno

        // [FIX-P7] REGLA DE TURNO: si en esta vuelta se emitieron OPCIONES, el turno del
        // modelo TERMINÓ. No sigue escribiendo debajo de su propia pregunta ni se contesta
        // solo: la pelota es del humano. El resultado de la tool igual se empuja al
        // transcript (la API exige un `tool` por cada `tool_call`), pero el loop CORTA.
        // Cuando el humano toca, su label entra como MENSAJE DE USUARIO en el turno
        // siguiente — no como tool result. Para el modelo, el humano simplemente contestó.
        let cierraTurno = false;

        // ── EJECUTAR cada tool_call EN EL BROWSER (paridad-mano literal) ──
        for (const tc of calls) {
          const name = tc && tc.function && tc.function.name;
          const args = parseArgs(tc);
          const key = tc.id || (name + ":" + round);
          let result;
          if (name === CONEXION_INLINE) {
            /* CONEXIÓN INLINE no es una Mano: es una tool DEL CLIENTE, y cae bajo la MISMA
             * REGLA DE TURNO que las opciones — pintado el trámite, la pelota es del humano.
             *
             * La primera versión de esto ESPERABA el resultado del widget dentro del loop.
             * Se veía bien en el caso feliz y era un cuelgue en el caso real: un OAuth que
             * la persona abandona, o un formulario que deja abierto para escribir otra cosa,
             * dejaba el `await` colgado PARA SIEMPRE y el Guía mudo. Es exactamente el
             * defecto que FIX-P10 §1 cerró con el GUARD DE PLAZO, reabierto por otra puerta.
             *
             * Ahora el turno CIERRA acá y el desenlace vuelve como un turno nuevo (el host
             * lo empuja cuando el humano termina) — el mismo mecanismo que ya usa La Sala.
             * Para la persona no cambia nada: la conversación sigue sola, sin recargar. Lo
             * que cambia es que ya no existe un estado en el que el Guía pueda quedar mudo. */
            let pintado = null;
            try {
              pintado = onClientTool
                ? await onClientTool(name, args, (res && res.content) || "")
                : { ok: false, error: "esta superficie no sabe rendir conexión inline" };
            } catch (e) {
              pintado = { ok: false, error: String((e && e.message) || e) };
            }
            if (pintado && pintado.ok) {
              cierraTurno = true;
              result = { ok: true, mostrado: true, esperando_al_humano: true, credencial_en_chat: false,
                nota: "El trámite de conexión ya está en pantalla. El turno TERMINÓ: no se escribe debajo ni se da la conexión por hecha. Cuando la persona lo complete, su resultado llega como un mensaje nuevo." };
            } else {
              result = Object.assign({ ok: false, credencial_en_chat: false,
                nota: "Hay que corregir los argumentos y reintentar, o seguir en prosa." }, pintado || {});
            }
            if (onToolResult) onToolResult(name, args, result, key);
          } else if (OPCIONES.has(name)) {
            // No es una Mano: es la FORMA del mensaje. La pinta el host con la capa
            // transversal (opciones.js), que valida contra el schema. Si no cumple, el
            // error vuelve al modelo para que corrija — jamás se traga en silencio.
            // NO se narra con una card de ACCIÓN: las opciones SON el mensaje, y anunciar
            // "estoy preguntando" arriba de la pregunta es ruido, no información.
            let pintado = null;
            try { pintado = host.opciones ? host.opciones(name, args, (res && res.content) || "") : { ok: false, error: "esta superficie no sabe pintar opciones" }; }
            catch (e) { pintado = { ok: false, error: String((e && e.message) || e) }; }
            if (pintado && pintado.ok) {
              cierraTurno = true;
              result = { ok: true, mostrado: true, esperando_al_humano: true,
                nota: "Las opciones ya están en pantalla. El turno TERMINÓ: no se escribe debajo de la propia pregunta ni se contesta solo. La respuesta del humano llega como un mensaje suyo." };
            } else {
              result = { ok: false, error: (pintado && pintado.error) || "no pude pintar las opciones",
                nota: "Hay que corregir los argumentos y reintentar, o seguir en prosa." };
            }
            if (onToolResult) onToolResult(name, args, result, key);
          } else if ((catalogRoute === "local" || catalogRoute === "registry")
                     && (name === "buscar_catalogo_local" || name === "buscar_registro")
                     && name !== (catalogRoute === "local" ? "buscar_catalogo_local" : "buscar_registro")) {
            // La fuente inequívoca queda CERRADA para todo el turno, no sólo para la primera
            // llamada. Aunque el modelo intente saltar al otro catálogo después de leer el
            // resultado, el host prohibido no se toca.
            result = { ok: false, error: catalogRoute === "local"
              ? "Este pedido es sobre el catálogo local; no se consulta el registro."
              : "Este pedido es sobre el registro; no se sustituye por el catálogo local." };
            if (onToolResult) onToolResult(name, args, result, key);
          } else if (!name || !GUIDE_TOOL_NAMES.includes(name) || !DISPATCH[name]) {
            // WHITELIST (regla 4): fuera de las tools declaradas → no existe para el guía.
            result = { ok: false, error: `El guía no tiene la herramienta «${name || "?"}». Sólo puede mirar y mover el Cuarto y abrir flujos; para actuar sobre el mundo (enviar, pagar, ejecutar), el usuario va a La Sala.` };
            // la card no se abre para una tool que no existe, pero el desenlace SÍ viaja:
            // el host decide si la narra (hoy la pinta como acción fallida si la abrió).
            if (onToolResult) onToolResult(name, args, result, key);
          } else {
            if (onTool) onTool(name, args, key);
            try {
              // [FIX-P10 §1] GUARD DE PLAZO. Un handler del host que no resuelve NUNCA
              // (un fetch sin timeout contra un registro que no contesta — el caso real
              // de `buscar_catalogo`) dejaba el `await` colgado para siempre: el loop no
              // avanzaba, la card se quedaba "en curso" y el turno no terminaba jamás.
              // Acá el turno SIEMPRE sigue: a los `toolTimeoutMs` la tool se da por
              // vencida con CAUSA Y CAMINO, el modelo recibe ese resultado y decide.
              // (No se cancela el trabajo del host: no todos los handlers son abortables.
              // Lo que se corta es LA ESPERA, que es lo que cuelga la conversación.)
              result = await conPlazo(DISPATCH[name](host, args), toolTimeoutMs, name, lang);
              if (result == null) result = { ok: true };
            } catch (e) {
              result = { ok: false, error: String((e && e.message) || e) };
            }
            if (onToolResult) onToolResult(name, args, result, key);
          }
          messages.push({ role: "tool", tool_call_id: key, name, content: safeJson(result) });
        }
        if (cierraTurno) return res;   // REGLA DE TURNO · la pelota es del humano
      }
      // agotó las vueltas — honesto, no fabrica un cierre
      if (onAssistant) onAssistant(lang === "en"
        ? "(I hit my step limit for this turn — tell me if you want me to keep going.)"
        : "(llegué al máximo de pasos por turno — hay que avisar si conviene seguir.)", { final: true });
      return last;
    } catch (e) {
      if (onError) onError(e);
      return null;
    } finally {
      running = false; if (onBusy) onBusy(false);
    }
  }

  function reset() { messages = [{ role: "system", content: system }]; }
  function setLang(l) { lang = l; system = buildGuideSystem(l, { mode: _mode }); if (messages.length && messages[0].role === "system") messages[0].content = system; }
  function setMode(m) { _mode = m || "delegar"; system = buildGuideSystem(lang, { mode: _mode }); if (messages.length && messages[0].role === "system") messages[0].content = system; }

  return {
    send, reset, setLang, setMode,
    get running() { return running; },
    get mode() { return _mode; },
    snapshotMessages: () => messages.map((m) => ({ ...m })),
    get tools() { return guideTools(lang); },
  };
}

function safeJson(v) {
  try { return JSON.stringify(v); } catch { return JSON.stringify({ ok: false, error: "resultado no serializable" }); }
}

/** conPlazo(p, ms, name, lang) — la espera tiene techo. Nunca rechaza: resuelve con un
 *  resultado TIPADO (causa + camino) que el modelo puede leer y contarle al humano. */
function conPlazo(p, ms, name, lang) {
  if (!ms || ms <= 0) return Promise.resolve(p);
  return new Promise((resolve) => {
    let listo = false;
    const t = setTimeout(() => {
      if (listo) return;
      listo = true;
      resolve({
        ok: false,
        timeout_ms: ms,
        error: lang === "en"
          ? `«${name}» took too long (over ${Math.round(ms / 1000)}s) and I stopped waiting.`
          : `«${name}» tardó demasiado (más de ${Math.round(ms / 1000)}s) y corté la espera.`,
        camino: lang === "en"
          ? "Say what didn't come back and offer to retry, or take another route."
          : "Hay que decir qué fue lo que no volvió y ofrecer reintentar, o tomar otro camino.",
      });
    }, ms);
    Promise.resolve(p).then(
      (v) => { if (listo) return; listo = true; clearTimeout(t); resolve(v); },
      (e) => { if (listo) return; listo = true; clearTimeout(t); resolve({ ok: false, error: String((e && e.message) || e) }); },
    );
  });
}
