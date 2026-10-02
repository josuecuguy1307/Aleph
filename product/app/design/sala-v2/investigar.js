/* investigar.js — LA INVESTIGACIÓN A FONDO, EN LA SALA. [Gate 4 · Fase 6 · §6.f]
 *
 * QUÉ HACE. Pide `POST /v1/sala/investigar`, lee el NDJSON que vuelve, y reparte:
 *
 *   {tipo:"abre"}     → el `obra_id`, que es lo que hace posible PARAR
 *   {tipo:"estado"}   → la línea de razonamiento  («planificando → buscando → leyendo 4/20 → sintetizando»)
 *   {tipo:"informe"}  → el texto + las fuentes    (al hilo y al artefacto)
 *   {tipo:"fallo"}    → causa con copy, jamás mudo
 *   {tipo:"cierra"}   → el turno terminó, con su duración
 *
 * ES EL GEMELO DE `buscar-web.js`, y lo que comparten está compartido de verdad: el lector
 * NDJSON y las dos funciones de fuentes se IMPORTAN de allá, no se copian. Eran las tres
 * piezas que iban a divergir.
 *
 * LO QUE ÉSTE TIENE Y AQUÉL NO: **PARAR**, y no es un extra. Una búsqueda web tarda
 * segundos; un deep research corre minutos. `pararInvestigacion()` existe porque un botón
 * que no para es peor que no tenerlo, y el `obra_id` que necesita llega en la PRIMERA
 * línea del stream — antes que ningún estado, o sea antes de que el usuario pueda querer
 * apretarlo.
 *
 * NO SE RE-TRADUCE NADA. Los sobres llegan con su `etapa`, su `estado` y su `texto` ya
 * armados por `platform/sala/research/etapas.py`, que mapea las 38 fases del motor a las
 * 6 etapas gruesas. Mapearlos de nuevo acá sería un TERCER lugar donde vive el mismo
 * contrato.
 */

// LAS TRES PIEZAS COMPARTIDAS, IMPORTADAS Y NO COPIADAS. `lineas()` resuelve el problema
// feo (un chunk de red puede cortar un JSON por la mitad) y `pasaporteDeFuentes` /
// `conFuentesCitadas` son el contrato del pasaporte. Los dos modos producen `{url,titulo}`
// —lo garantiza `_fuentes()` en los dos `servidor.py`— así que es la misma función, no una
// que se le parece.
import { lineas, pasaporteDeFuentes, conFuentesCitadas } from "./buscar-web.js?v=sala-te";

export { lineas, pasaporteDeFuentes, conFuentesCitadas };

/**
 * Corre una investigación larga completa.
 *
 * @param {object} o
 * @param {string} o.consulta
 * @param {function} o.headers        authHeaders() de la Sala
 * @param {function} o.onAbre         {obra_id, espacio} → habilita el botón de parar
 * @param {function} o.onEstado       sobre → pinta la línea de razonamiento
 * @param {function} o.onInforme      {texto, fuentes, etapas, sha256} → hilo + artefacto
 * @param {function} o.onFallo        {causa, copy, detalle, …el sobre si lo trae}
 * @param {string}  [o.modo]          "resumen" (default) | "informe"
 * @param {AbortSignal} [o.signal]
 */
export async function investigarAFondo({ consulta, headers, onAbre, onEstado, onInforme,
                                         onFallo, modo, iteraciones, signal,
                                         puppetId, chatId }) {
  let respuesta;
  try {
    respuesta = await fetch("/v1/sala/investigar", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(headers ? headers({}) : {}) },
      body: JSON.stringify({
        query: consulta, modo: modo || "resumen", iteraciones: iteraciones || null,
        puppet_id: puppetId, chat_id: chatId,
      }),
      signal,
    });
  } catch (e) {
    // Cortar a propósito NO es un fallo que haya que anunciar como tal.
    if (e?.name === "AbortError") return { cancelada: true };
    onFallo?.({ causa: "sin_red", copy: "No se pudo hablar con el motor de investigación." });
    return { error: true };
  }

  if (!respuesta.ok) {
    // LA CAUSA DEL BORDE YA VIAJÓ: no se pisa con una genérica.
    let d = null;
    try { d = (await respuesta.json())?.detail; } catch (_) { /* sin cuerpo */ }
    onFallo?.({
      causa: d?.error || "motor_no_responde",
      copy: d?.copy || "El motor de investigación no contestó.",
      detalle: d?.detail || `HTTP ${respuesta.status}`,
    });
    return { error: true };
  }

  let final = null;
  let obraId = null;
  for await (const ev of lineas(respuesta)) {
    if (ev.tipo === "abre") { obraId = ev.obra_id; onAbre?.(ev); }
    else if (ev.tipo === "estado") onEstado?.(ev);
    else if (ev.tipo === "informe") { final = ev; onInforme?.(ev); }
    else if (ev.tipo === "fallo") onFallo?.(ev);
    // `cierra` no se pinta: la Sala ya sabe que terminó porque el stream terminó. Se lee
    // igual para no tratarlo como una línea desconocida.
  }
  return { final, obraId };
}

/**
 * Le pide al motor que pare la obra en vuelo.
 *
 * DEVUELVE SI HABÍA ALGO QUE PARAR, y esa distinción importa: parar algo que ya terminó no
 * es un error —el usuario aprieta justo cuando llegaba el informe— pero tampoco es lo mismo
 * que haberlo parado. Quien pinta esto tiene que poder decir la verdad de las dos.
 *
 * NO ABORTA EL `fetch`. Cortar el stream del lado del navegador dejaría al motor corriendo
 * y —en las vías con costo— cobrando: sería el «parar» de teatro que `turnos_http.js:13-16`
 * describe. Se le pide al motor que pare, y el motor termina el stream con
 * `fallo · obra_cancelada`, que es lo que el usuario ve.
 */
export async function pararInvestigacion({ obraId, headers }) {
  if (!obraId) return { encontrada: false };
  try {
    const r = await fetch("/v1/sala/investigar/parar", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(headers ? headers({}) : {}) },
      body: JSON.stringify({ obra_id: obraId }),
    });
    if (!r.ok) return { encontrada: false, error: true };
    return await r.json();
  } catch (_) {
    return { encontrada: false, error: true };
  }
}

/**
 * El texto de la línea de razonamiento para un sobre de etapa.
 *
 * El sobre YA trae su `texto` resuelto en castellano (`etapas.py`). Esto sólo le agrega el
 * «N de M» cuando el motor lo dio — y **nunca lo inventa**: si `leidas`/`total` no vinieron,
 * no se pinta un «1 de 1» fabricado. Es la misma disciplina del `pct` que `etapas.py`
 * declara: un dato que no se midió no se rellena.
 */
export function textoDeEtapa(sobre) {
  const base = sobre?.texto || "…";
  const n = sobre?.leidas, m = sobre?.total;
  if (Number.isFinite(n) && Number.isFinite(m) && m > 0) return `${base} (${n} de ${m})`;
  if (Number.isFinite(sobre?.fuentes) && sobre.fuentes > 0) {
    return `${base} · ${sobre.fuentes} fuente${sobre.fuentes === 1 ? "" : "s"}`;
  }
  return base;
}
