/* buscar-web.js — LA BÚSQUEDA WEB, EN LA SALA. [Gate 4 · Fase 6 · §6.a.bis]
 *
 * QUÉ HACE. Pide `POST /v1/sala/buscar`, lee el NDJSON que vuelve, y reparte:
 *
 *   {tipo:"estado"}     → la línea de razonamiento    («buscando → 81 resultados → …»)
 *   {tipo:"respuesta"}  → el texto + las fuentes      (al hilo y al artefacto)
 *   {tipo:"fallo"}      → causa con copy, jamás mudo
 *
 * LA CARA DE VANE NO SE MONTA, y esto es lo que lo hace cierto: el motor vive en un
 * puerto interno del pack, nadie navega ahí, y lo único que cruza es este NDJSON. La
 * cara es la Sala.
 *
 * NO SE RE-TRADUCE NADA. Los sobres llegan con su `etapa`, su `estado` y su `texto` ya
 * armados por `platform/sala/busqueda/etapas.py`. Mapearlos de nuevo acá sería un TERCER
 * lugar donde vive el mismo contrato —ya son dos y están declarados como tales— y cada
 * copia es una oportunidad de que diverjan.
 */

/** Lee un `Response` NDJSON y entrega objeto por objeto, a medida que llegan. */
export async function* lineas(respuesta) {
  const lector = respuesta.body?.getReader?.();
  if (!lector) return;
  const dec = new TextDecoder();
  let resto = "";
  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    resto += dec.decode(value, { stream: true });
    const partes = resto.split("\n");
    // LA ÚLTIMA SE GUARDA SIN PARSEAR, y no es un detalle: un chunk de red puede cortar
    // una línea JSON por la mitad. Parsearla entera cada vez tiraría eventos válidos.
    resto = partes.pop() || "";
    for (const l of partes) {
      const t = l.trim();
      if (!t) continue;
      try { yield JSON.parse(t); } catch (_) { /* línea rota: no tumba el turno */ }
    }
  }
  const cola = resto.trim();
  if (cola) { try { yield JSON.parse(cola); } catch (_) { /* ídem */ } }
}

/**
 * Corre una búsqueda web completa.
 *
 * @param {object} o
 * @param {string} o.consulta
 * @param {function} o.headers          authHeaders() de la Sala
 * @param {function} o.onEstado         sobre → pinta la línea de razonamiento
 * @param {function} o.onRespuesta      {texto, fuentes, sha256} → hilo + artefacto
 * @param {function} o.onFallo          {causa, copy, detalle}
 * @param {AbortSignal} [o.signal]
 */
export async function buscarEnLaWeb({ consulta, headers, onEstado, onRespuesta,
                                      onFallo, signal, puppetId, chatId }) {
  let respuesta;
  try {
    respuesta = await fetch("/v1/sala/buscar", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(headers ? headers({}) : {}) },
      body: JSON.stringify({ query: consulta, puppet_id: puppetId, chat_id: chatId }),
      signal,
    });
  } catch (e) {
    // Cortar a propósito NO es un fallo que haya que anunciar como tal.
    if (e?.name === "AbortError") return { cancelada: true };
    onFallo?.({ causa: "sin_red", copy: "No se pudo hablar con el buscador." });
    return { error: true };
  }

  if (!respuesta.ok) {
    // LA CAUSA DEL BORDE YA VIAJÓ: no se pisa con una genérica.
    let d = null;
    try { d = (await respuesta.json())?.detail; } catch (_) { /* sin cuerpo */ }
    onFallo?.({
      causa: d?.error || "motor_no_responde",
      copy: d?.copy || "El buscador no contestó.",
      detalle: d?.detail || `HTTP ${respuesta.status}`,
    });
    return { error: true };
  }

  let final = null;
  for await (const ev of lineas(respuesta)) {
    if (ev.tipo === "estado") onEstado?.(ev);
    else if (ev.tipo === "respuesta") { final = ev; onRespuesta?.(ev); }
    else if (ev.tipo === "fallo") onFallo?.(ev);
  }
  return { final };
}

/**
 * Las fuentes, como las guarda el pasaporte del artefacto.
 *
 * NO SE INVENTA NINGUNA y no se deduce del texto: son exactamente las que el motor emitió
 * (`etapas.py:_fuentes()` las normaliza a `{url, titulo}` deduplicando por URL). Si la
 * respuesta menciona algo sin fuente, cruza sin fuente y se ve — mismo criterio que el
 * `never_filled` de `platform/artifacts/bridge.py`.
 */
export function pasaporteDeFuentes(fuentes) {
  return (fuentes || [])
    .filter((f) => f && typeof f.url === "string" && f.url)
    .map((f) => ({ url: f.url, titulo: f.titulo || "" }));
}

/**
 * LOS DOCUMENTOS EN QUE SE APOYÓ EL TURNO. [T2.4 · «de dónde salió esto»]
 *
 * Hermano de `pasaporteDeFuentes`, y vive acá por eso: es el MISMO gesto de honestidad
 * —decir de dónde salió la respuesta— sólo que la fuente es el Conocimiento del usuario y
 * no la web. Un segundo render habría sido una segunda opinión sobre el mismo problema.
 *
 * LA DIFERENCIA QUE NO SE PUEDE DISIMULAR: una fuente web tiene URL y se puede linkear; un
 * apunte de RAG es un tag `documento#chunk` que estampó el indexador
 * (`recipe_assembler._rag_wrap`, `{n_chunks, provenance:[...]}`). NO hay a dónde ir. Por eso
 * esto NO fabrica links —inventar un href a un documento local sería un botón falso, que es
 * justo lo que la regla de `caminoDe` prohíbe— y lista el documento con su fragmento.
 *
 * Se separa `documento` de `#fragmento` porque el mismo documento suele aportar varios
 * chunks: repetir el nombre cinco veces es ruido, no procedencia.
 */
export function pasaporteDeDocumentos(provenance) {
  const porDoc = new Map();
  for (const tag of provenance || []) {
    if (typeof tag !== "string" || !tag.trim()) continue;
    const i = tag.lastIndexOf("#");
    const doc = (i > 0 ? tag.slice(0, i) : tag).trim();
    const frag = i > 0 ? tag.slice(i + 1).trim() : "";
    if (!doc) continue;
    if (!porDoc.has(doc)) porDoc.set(doc, []);
    if (frag && !porDoc.get(doc).includes(frag)) porDoc.get(doc).push(frag);
  }
  return [...porDoc.entries()].map(([documento, fragmentos]) => ({ documento, fragmentos }));
}

/**
 * El markdown de la bibliografía de documentos. Sin apuntes ⇒ devuelve el texto intacto:
 * un turno que no se apoyó en el Conocimiento no lleva una sección vacía diciéndolo.
 */
export function conDocumentosCitados(texto, provenance, tituloSeccion) {
  const ds = pasaporteDeDocumentos(provenance);
  if (!ds.length) return texto || "";
  const lista = ds.map((d, i) => {
    const frags = d.fragmentos.length ? ` — fragmento${d.fragmentos.length > 1 ? "s" : ""} ${d.fragmentos.join(", ")}` : "";
    return `${i + 1}. ${d.documento}${frags}`;
  }).join("\n");
  return `${texto || ""}\n\n### ${tituloSeccion || "De tus documentos"}\n\n${lista}\n`;
}

/** El markdown que va al hilo y al artefacto: la respuesta y su bibliografía. */
export function conFuentesCitadas(texto, fuentes, tituloSeccion) {
  const fs = pasaporteDeFuentes(fuentes);
  if (!fs.length) return texto || "";
  const lista = fs.map((f, i) => `${i + 1}. [${f.titulo || f.url}](${f.url})`).join("\n");
  return `${texto || ""}\n\n### ${tituloSeccion || "Fuentes"}\n\n${lista}\n`;
}
