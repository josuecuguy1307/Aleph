// El SOBRE DE GATE 3, leído.
//
// Aleph emite DOS streams SSE distintos para un mismo turno, y ninguno de los dos habla
// AG-UI. Este archivo es la mitad de LECTURA del adaptador: normaliza los dos sobres a una
// forma común. La mitad de ESCRITURA —la traducción a eventos AG-UI, con su tabla de
// mapeo— vive en `aleph-agent.js`.
//
// EL BACKEND NO CAMBIA. Ni una línea. Todo lo de acá lee lo que Gate 1-3 ya emite hoy.
//
// ── Los dos transportes ──────────────────────────────────────────────────────────────────
//
//  A · CHARLA          POST /v1/puppets/run/stream   → SSE de texto, sin tools, sin gate.
//                      Frames (router.py:2489-2581): token · thinking · turno ·
//                      sesion_perdida · modelo_sustituido · usage · done · error.
//
//  B · OBRA EQUIPADA   POST /v1/puppets/run          → POST bloqueante, devuelve el veredicto.
//                      GET  /v1/spaces/{id}/stream   → SSE del ESPINAZO, en vivo, con las tools.
//                      Frames (platform/flywheel/EVENTS-SCHEMA.md): belt_ready · turn_started ·
//                      tool_call_started · tool_call_finished · gate_waiting · gate_resolved ·
//                      final · closed · artifact_created · equipment_changed.
//
// El `space_id` lo genera el cliente y viaja en el body del run; el espinazo se abre sobre
// ese id (sala.html:2228 y :3669 hacen exactamente esto hoy).
//
// ── Los 6 campos que el pedido llama «el sobre» ──────────────────────────────────────────
// Medido contra el censo (§C.1) y contra el código, no contra la memoria:
//
//   status         ✅ existe        `tool_call_finished.status` ∈ ok | error | gated
//   tool_name      ✅ existe ×3     `tool` (server) · `tool_raw` (crudo) · `tool_name` (expuesto)
//   latency        ⚠️ parcial       `wall_s`, y SÓLO si el assembler lo pudo medir
//   error          ✅ existe        `status:"error"` + la causa tipada (`causa`/`origen`/`reintentable`)
//   connection_id  ❌ NO EXISTE     0 ocurrencias en el átomo. Es un concepto de Smithery
//                                   (`platform/connectors/smithery/connections.py`), no del evento.
//   is_partial     ❌ NO EXISTE     0 ocurrencias en product/ y platform/.
//
// Los dos que no existen NO SE INVENTAN. `connection_id` se deriva de lo que sí hay —el
// server de la tool, que es la marca de la conexión— y queda marcado como derivado.
// `is_partial` se deriva de la posición en el stream (hay `tool_call_started` sin su
// `finished` ⇒ ese tool_call está parcial), que es un hecho observable, no un campo.
// Nada de esto se presenta como si el backend lo emitiera.

/**
 * Los tipos del espinazo.
 *
 * Los 10 primeros son los que declara `platform/flywheel/EVENTS-SCHEMA.md`. Los demás
 * NO están en ese documento y **igual salen por el stream**: se agregaron acá después de
 * mirar un `events.jsonl` real de una corrida (2026-08-08, turno con `calc`), porque una
 * tabla escrita contra el doc y no contra el hecho deja eventos legítimos cayendo en la
 * rama «desconocido» y le llena la pantalla de avisos falsos al usuario.
 *
 * Lo que salió, en orden, en esa corrida:
 *     cost · tool_call_started · cost · tool_call_finished · cost · final · closed
 *
 * Es decir: `cost` es el PRIMER evento del turno —y por eso es el que da el primer signo
 * de vida—, y `belt_ready`/`turn_started` no aparecieron en absoluto. El resto sale de
 * `recipe_assembler.py`, que emite bastante más de lo que `session.py` documenta.
 */
export const ESPINAZO = Object.freeze({
  // documentados en EVENTS-SCHEMA.md
  // [OBRA 2] `belt_starting` lo emite `recipe_assembler.py` justo ANTES de arrancar el
  // cinturón: es el primer evento REAL del turno y el que hace existir el espacio (sin él
  // el SSE reintentaba contra un 404 hasta agotar su plazo de 20 s).
  BELT_STARTING: "belt_starting",
  BELT_READY: "belt_ready",
  TURN_STARTED: "turn_started",
  TOOL_CALL_STARTED: "tool_call_started",
  TOOL_CALL_FINISHED: "tool_call_finished",
  GATE_WAITING: "gate_waiting",
  GATE_RESOLVED: "gate_resolved",
  FINAL: "final",
  CLOSED: "closed",
  ARTIFACT_CREATED: "artifact_created",
  EQUIPMENT_CHANGED: "equipment_changed",
  // medidos en el stream, ausentes del documento
  COST: "cost",
  METRIC: "metric",
  NOTICE: "notice",
  TEXT: "text",
  PLAN_DECLARED: "plan_declared",
  SUB_AGENT_STARTED: "sub_agent_started",
  SUB_AGENT_FINISHED: "sub_agent_finished",
  CLIENT_CALL: "client_call",
  LOOP_DETECTED: "loop_detected",
  CONTEXT_COMPACTED: "context_compacted",
  BUDGET_EXHAUSTED: "budget_exhausted",
  BRAIN_WINDOW_EXHAUSTED: "brain_window_exhausted",
  SHARED_BUS_DENIED: "shared_bus_denied",
  DELEGATION_SERIALIZED: "delegation_serialized",
});

/** Los frames de la charla, tal como los emite `router.py:run_puppet_stream`. */
export const CHARLA = Object.freeze({
  TOKEN: "token",
  THINKING: "thinking",
  TURNO: "turno",
  SESION_PERDIDA: "sesion_perdida",
  MODELO_SUSTITUIDO: "modelo_sustituido",
  MODEL_FINAL: "model_final",
  USAGE: "usage",
  DONE: "done",
  ERROR: "error",
});

/**
 * Lector de SSE por líneas.
 *
 * No se usa `EventSource` a propósito, por dos razones medidas: (1) el run de charla es un
 * POST con body, y `EventSource` sólo hace GET; (2) `EventSource` no deja mandar el header
 * `Authorization`, y las dos rutas lo exigen. `fetch` + lector de stream cubre las dos.
 *
 * Corta por `\n\n` (el separador de SSE) y entrega el JSON de cada `data:`. Un frame que no
 * parsea NO se traga en silencio: se entrega a `onMalformed` para que la capa de arriba lo
 * convierta en un fallo visible (ley: fallo visible, jamás mudo).
 */
export async function leerSSE(response, { onFrame, onMalformed, signal }) {
  if (!response.body) throw new Error("respuesta sin cuerpo legible");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const cancelar = () => {
    // `reader.cancel()` devuelve una PROMESA. Un `try/catch` síncrono alrededor no atrapa su
    // rechazo, así que al abortar (cerrar el turno, recargar la pantalla) quedaba un
    // unhandled rejection que en WebKit sale como `pageerror: AbortError`. La vara lo vio
    // en 2 de 3 corridas —intermitente, porque depende de si había una lectura en vuelo— y
    // por eso el `.catch()` va sobre la promesa, no alrededor de la llamada.
    try {
      reader.cancel()?.catch?.(() => {});
    } catch (_) {
      /* el lector ya estaba cerrado */
    }
  };
  if (signal) {
    if (signal.aborted) {
      cancelar();
      return;
    }
    signal.addEventListener("abort", cancelar, { once: true });
  }

  for (;;) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (e) {
      // Cancelación nuestra: no es un error del stream. `AbortError` se chequea además del
      // flag porque en WebKit la excepción llega antes de que `signal.aborted` esté puesto,
      // y sin esto salía como `pageerror` en la consola (lo destapó la vara).
      if (signal?.aborted || (e && e.name === "AbortError")) return;
      throw e;
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });

    let corte;
    while ((corte = buffer.indexOf("\n\n")) !== -1) {
      const bloque = buffer.slice(0, corte);
      buffer = buffer.slice(corte + 2);
      for (const linea of bloque.split("\n")) {
        if (!linea.startsWith("data:")) continue; // `id:` y `event:` no los usa este contrato
        const crudo = linea.slice(5).trim();
        if (!crudo) continue;
        try {
          onFrame(JSON.parse(crudo));
        } catch (e) {
          onMalformed?.(crudo, e);
        }
      }
    }
  }
}

/**
 * `connection_id` DERIVADO. El evento del átomo no lo trae (medido: 0 ocurrencias).
 *
 * Lo más cercano que sí existe y sí identifica a quién se le está hablando es el nombre del
 * server MCP (`evt.tool`, que el assembler llama «clave de marca»). Se devuelve marcado como
 * derivado para que ninguna superficie lo confunda con un id real del backend: si mañana el
 * átomo gana un `connection_id` de verdad, este helper es el único lugar que cambia.
 */
export function connectionIdDerivado(evt) {
  const server = evt?.tool || evt?.server || null;
  if (!server) return null;
  return { valor: String(server), derivado_de: "tool_call_finished.tool (nombre del server MCP)" };
}

/**
 * `latency` HONESTA. `wall_s` sólo viaja si el assembler lo pudo medir; su propio executor
 * lo declara: «latency_ms queda None (el assembler no emite latencias por paso hoy)»
 * (`executor.py:531,546`). Devolver 0 en vez de null sería fabricar una medición.
 */
export function latenciaMs(evt) {
  if (typeof evt?.wall_s === "number" && Number.isFinite(evt.wall_s)) {
    return Math.round(evt.wall_s * 1000);
  }
  return null;
}

/**
 * La CAUSA TIPADA de Gate 2/3, extraída sin re-derivarla.
 *
 * REGLA SELLADA del repo: ninguna causa llega a una superficie sin copy. Acá NO se traduce
 * ni se inventa texto: se extrae el objeto tal cual y se marca si vino vacío, para que la
 * capa de UI use el catálogo de copy que ya existe (`causas-catalogo.js`) y no una cadena
 * fabricada en el borde.
 */
export function causaDe(evt) {
  if (!evt) return null;
  const cruda = evt.causa ?? evt.causa_origen ?? evt.record?.causa ?? evt.error?.causa ??
    evt.detail?.causa ?? null;
  if (!cruda && !evt.origen && evt.reintentable === undefined) return null;
  // ⚠️ LA CAUSA VIAJA EN DOS FORMAS Y NO SON INTERCAMBIABLES.
  // El espinazo manda la CLAVE suelta (`causa: "sin_red"`); la charla RAW manda el OBJETO
  // entero (`causa: {causa, detalle, estado, reintentable, retry_after_s}`). «Extraer tal
  // cual» servía para la primera y para la segunda dejaba un objeto donde la UI espera una
  // clave. MEDIDO el 2026-08-12: con la ventana de Codex agotada, la Sala pintaba
  // `[object Object] · sin copy propia todavía` — el backend mandaba «Se agotó tu ventana
  // de uso del CLI» y la pantalla lo convertía en eso. Se normaliza acá, una vez, para los
  // seis llamantes.
  const esObjeto = !!cruda && typeof cruda === "object";
  return {
    causa: esObjeto ? cruda.causa ?? null : cruda ?? null,
    // EL TEXTO QUE EL BACKEND YA ESCRIBIÓ. Es mejor copy que cualquiera que inventemos en
    // el borde —está escrito donde la causa nace— y viaja listo. La UI lo prefiere sobre
    // el catálogo; el catálogo queda para las causas que llegan sin él.
    detalle: esObjeto ? cruda.detalle ?? null : null,
    runtime_state: esObjeto
      ? cruda.runtime_state ?? cruda.evidencia?.runtime_state ?? null
      : evt.runtime_state ?? null,
    quota_availability: esObjeto
      ? cruda.quota_availability ?? cruda.evidencia?.quota_availability ?? null
      : evt.quota_availability ?? null,
    evidencia: esObjeto && cruda.evidencia && typeof cruda.evidencia === "object"
      ? cruda.evidencia : null,
    provider_rate_limit_event: esObjeto
      ? cruda.provider_rate_limit_event ?? cruda.evidencia?.provider_event ?? null
      : evt.provider_rate_limit_event ?? null,
    origen: evt.origen ?? null,
    reintentable: esObjeto && cruda.reintentable != null
      ? cruda.reintentable
      : evt.reintentable ?? null,
    vencio_el_reloj: evt.vencio_el_reloj ?? null,
    timeout_s: esObjeto
      ? cruda.retry_after_s ?? evt.retry_after_s ?? evt.timeout_s ?? null
      : evt.retry_after_s ?? evt.timeout_s ?? null,
    reset_hint: esObjeto ? cruda.reset_hint ?? evt.reset_hint ?? null : evt.reset_hint ?? null,
  };
}

/** Separa el texto humano de la evidencia cruda al cerrar un run fallido. */
export function falloDeRun(evt) {
  if (!evt) return null;
  const error = evt.error && typeof evt.error === "object" ? evt.error : null;
  const candidatos = [
    typeof evt.error === "string" ? evt.error : null,
    error?.message,
    typeof evt.detail === "string" ? evt.detail : null,
    typeof evt.message === "string" ? evt.message : null,
  ].filter(Boolean).map(String);
  const pareceErrorCrudo = (texto) => {
    const limpio = texto.trim();
    const json = limpio.replace(/^HTTP\s+\d{3}\s*:\s*/i, "");
    if (!json.startsWith("{") && !json.startsWith("[")) return false;
    try {
      const valor = JSON.parse(json);
      return !!valor && typeof valor === "object";
    }
    catch (_) { return false; }
  };
  const diagnostico = evt.diagnostic ?? candidatos.find(pareceErrorCrudo) ?? null;
  const causa = causaDe(evt);
  const mensaje = causa?.detalle || candidatos.find((texto) => !pareceErrorCrudo(texto)) ||
    "el run falló";
  return {
    mensaje: String(mensaje),
    diagnostico: diagnostico && diagnostico !== mensaje ? String(diagnostico) : null,
    causa,
    runtime_state: causa?.runtime_state ?? evt.runtime_state ?? null,
    quota_availability: causa?.quota_availability ?? evt.quota_availability ?? "unknown",
    provider_rate_limit_event: causa?.provider_rate_limit_event ?? null,
  };
}

/**
 * El nombre de la tool que se le muestra a una persona.
 *
 * El átomo trae TRES nombres y no son intercambiables (§C.1): `tool` es el server,
 * `tool_raw` el nombre crudo adentro de ese server, `tool_name` el que ve el modelo. Para
 * el hilo se arma «server · herramienta», que es lo que una persona necesita para decidir
 * en la tarjeta de consentimiento: dónde y qué.
 */
export function nombreVisible(evt) {
  const server = evt?.tool || "";
  const fn = evt?.tool_raw || evt?.tool_name || "";
  if (server && fn && server !== fn) return `${server} · ${fn}`;
  return fn || server || "herramienta";
}

/**
 * El nombre del SUB-AGENTE que se le muestra a una persona.
 *
 * Del más humano al más técnico: `meta_name` es como el dueño llamó al agente en su
 * receta, `slug` es su id, `tool` es la función con que el padre lo invocó. Nunca «?».
 *
 * Existe porque el adaptador leía `e.name ?? e.agent` y el espinazo NO MANDA NINGUNO:
 * emite `tool · tool_raw · slug · meta_name · depth · parent_run_id · task · turn`
 * (`recipe_assembler.py:3641`). Medido: todo sub-agente se llamaba `subagente:?`.
 */
export function nombreDeAgente(evt) {
  return evt?.meta_name || evt?.slug || evt?.tool || "sub-agente";
}

/**
 * La CLAVE del sub-agente, que NO es su nombre — y separarlas no es purismo.
 *
 * `paso()`/`pasoFin()` casan por string: si la clave del cierre no es idéntica a la de la
 * apertura, el paso queda abierto para siempre. Y el espinazo manda `meta_name` **sólo en
 * el `started`** (medido: las claves del `finished` son tool · tool_raw · slug · result ·
 * status · child_ok · held · depth · parent_run_id · turn). Usar el nombre visible de clave
 * abría `subagente:Investigador de mercado` y cerraba `subagente:investigador`: dos strings
 * distintos, cierre que nunca llega, círculo girando para siempre.
 *
 * `slug` está en los dos eventos y es lo que el propio backend declara como «la clave con
 * que el front matchea» (`recipe_assembler.py:3632`).
 */
export function claveDeAgente(evt) {
  return evt?.slug || evt?.tool || "sub-agente";
}
