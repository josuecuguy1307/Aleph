/* catalogo.js — DE DÓNDE SALE EL CATÁLOGO PÚBLICO, Y CÓMO SE TRAE UNA PIEZA.
 *
 * La sección pública del adaptador, en las mismas cinco capas que el resto:
 *
 *   catalogo.js             LEE + DERIVA · esto: las cuatro llamadas y los modelos
 *   superficie-catalogo.js  PINTA        · funciones puras que devuelven HTML
 *   montaje.js              CONECTA      · nodos, clicks y recarga (la tercera vista)
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ACÁ NO PUEDE PASAR, y la vara lo comprueba:
 *
 *   · NINGÚN TEXTO DE USUARIO. Este archivo produce ESTRUCTURA —`aviso.escriben` es un
 *     booleano, no una frase— y `superficie-catalogo.js` la convierte en palabras. Si acá
 *     se escribiera un rótulo habría dos lugares que dicen lo mismo, y un día dirían cosas
 *     distintas. Es la misma ley que ya rige `fuentes.js`.
 *   · NINGÚN NOMBRE DE CONECTOR. Las 17.000 piezas del registro pasan por las mismas cinco
 *     funciones. Un `if (pieza === "notion")` escala a una y muere en la siguiente.
 *   · NINGÚN PASO INVENTADO. `reducirViaje` traduce EVENTOS REALES del SSE a estados de
 *     paso. Los pasos que el sistema no corre no se dibujan — ver `PASOS_DEL_VIAJE`.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LOS CUATRO ENDPOINTS, Y QUÉ APORTA CADA UNO (medidos sobre main, Obra 4 · M1):
 *
 *   GET  /v1/catalog/search    la LISTA. 17 campos por ítem; el manifest crudo JAMÁS viaja
 *                              en la lista (`referencia_crudo` es un puntero, no el dato).
 *   GET  /v1/catalog/validate  el VEREDICTO al elegir. 200 SIEMPRE —incluso el outage— y
 *                              son DATOS que se leen por campo, no errores.
 *   GET  /v1/catalog/raw       el manifest de UNA pieza. Una llamada, una pieza.
 *   POST /v1/catalog/equip     el VIAJE, por SSE. Exige sesión (sin ella, 401 medido).
 */
import { cabeceras, leerSSE } from "./fuentes.js";

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LAS CARAS DE LA FICHA · CUATRO, no tres.
 *
 * ⚠️ EL DISEÑO DIBUJÓ TRES Y EL ENDPOINT DEVUELVE CUATRO. `validate` tiene un desenlace más
 * que las tres caras del diseño: el registro que no contesta (`verdict:null` +
 * `registry_status:"unreachable"`). Pintarlo como «no se puede» sería el peor bug de esta
 * superficie —decirle a alguien que su conector no existe cuando lo que pasó es que no
 * pudimos preguntar— y el backend lo separa a propósito (T-3). Así que son cuatro.
 * ════════════════════════════════════════════════════════════════════════════════════ */
export const CARA_VERIFICADA = "verificada";
export const CARA_CON_RESERVAS = "con_reservas";
export const CARA_NO_SE_PUEDE = "no_se_puede";
export const CARA_SIN_REGISTRO = "sin_registro";

/** Los CUATRO bordes de la lista. Son CUATRO estados distintos y se ven distinto a propósito:
 *  «todavía no buscaste» ≠ «no pudimos preguntar» ≠ «preguntamos y no existe» ≠ «hay piezas,
 *  las tapa tu filtro».
 *
 * ⚠️ EL CUARTO NO PODÍA REUSAR EL TERCERO. «El registro no conoce esto» ofrece construir un
 * MCP; «tenés un filtro puesto» ofrece quitarlo. Pintarlos igual manda a construir algo que
 * está en pantalla, tapado por un chip. */
export const BORDE_VACIO = "vacio";
export const BORDE_CAIDO = "caido";
export const BORDE_SIN_RESULTADOS = "sin_resultados";
export const BORDE_FILTRO_VACIO = "filtro_vacio";

/** El orden en que se ofrecen los requisitos. Es el de `REQUISITO()` en la superficie —de
 *  menos a más trabajo para la persona— y no un alfabético que barajaría el criterio. */
export const REQUISITOS = ["click", "llave", "descarga", "ninguno"];

/** Por qué NO se puede: el camino cambia según el motivo, y el motivo es del endpoint. */
export const MOTIVO_IMPOSTOR = "no_es_de_quien_dice_ser";   // verdict confiable + picked ≠ trusted
export const MOTIVO_INEXISTENTE = "el_registro_no_la_conoce"; // verdict "nada"

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS TRES PASOS DEL VIAJE · derivados del SSE, no dibujados.
 *
 * ⚠️ ACÁ HABÍA CINCO EN EL DISEÑO, Y EL SISTEMA CORRE TRES. El mockup pintaba «Resolver ·
 * Conectar · Arrancar · Listar herramientas · Verificar» con un detalle por paso (`1,2 MB ·
 * ok`, `saludo ok · 0,4 s`, `en curso · 12 encontradas`) y un «paso 4 de 5». Medido sobre
 * `catalog_equip_router`: el stream emite SEIS tipos de evento que forman TRES momentos, no
 * declara su plan de antemano —no hay `fila.inicio` como en el checklist del local— y las
 * herramientas llegan TODAS JUNTAS al final, dentro de `mcp.equipado`.
 *
 * Dibujar los cinco sería una animación, no un estado. La ley ya estaba escrita en el
 * archivo que tendría que pintarlos (`superficie.js`): «no se dibujan pasos que no existen:
 * una animación que no corresponde a nada miente con más detalle que un spinner».
 *
 * Lo que SÍ se conserva del diseño es todo lo demás: la lista de verbos con ✓/⏳/○, el
 * detalle a la derecha cuando el evento lo trae, y la detención EN EL PASO CULPABLE con su
 * causa y su botón.
 * ════════════════════════════════════════════════════════════════════════════════════ */
export const PASO_RESOLVER = "resolver";
export const PASO_COMPROBAR = "comprobar";
export const PASO_TRAER = "traer";
export const PASOS_DEL_VIAJE = [PASO_RESOLVER, PASO_COMPROBAR, PASO_TRAER];

/* ── LECTURA ────────────────────────────────────────────────────────────────────────── */

/** BUSCAR EN EL REGISTRO PÚBLICO. Devuelve la respuesta cruda o `null` si el cable falló.
 *
 * `source=registry` a propósito: lo INTERNO ya está en «Tus conectores», y repetirlo acá
 * sería mostrar dos veces la misma pieza en la misma pantalla. */
export async function buscar(q, { limite = 20 } = {}) {
  const url = `/v1/catalog/search?q=${encodeURIComponent(q || "")}` +
              `&source=registry&limit=${encodeURIComponent(limite)}`;
  try {
    const r = await fetch(url, { headers: cabeceras() });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) { return null; }   // falla abierto: el borde «caído» lo dice, no una excepción
}

/** VALIDAR AL ELEGIR. `servidor` es el ítem que el usuario tocó — sin él no hay
 *  anti-impostor, porque no habría con qué comparar el ganador confiable. */
export async function validar(servicio, servidor) {
  const url = `/v1/catalog/validate?service=${encodeURIComponent(servicio || "")}` +
              (servidor ? `&server_name=${encodeURIComponent(servidor)}` : "");
  try {
    const r = await fetch(url, { headers: cabeceras() });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) { return null; }
}

/** EL CRUDO DE **UNA** PIEZA. La lista nunca lo trae; se pide al abrir el [?] de una. */
export async function crudo(catalogId) {
  try {
    const r = await fetch(`/v1/catalog/raw?catalog_id=${encodeURIComponent(catalogId || "")}`,
                          { headers: cabeceras() });
    if (!r.ok) return null;
    return await r.json();
  } catch (_) { return null; }
}

/** «ESTO NO COINCIDE» · el reporte del usuario sobre un match que no es lo que buscaba.
 *
 * Va al mismo endpoint de ingesta que ya re-mide una pieza: avisar es pedir que se vuelva a
 * mirar. No hay endpoint de «reportar» y no se inventa uno — se dispara la re-ingesta de esa
 * query, que es lo que hace que «la próxima búsqueda ya lo sepa». */
export async function noCoincide(consulta) {
  try {
    const r = await fetch("/v1/catalog/ingest", {
      method: "POST",
      headers: cabeceras({ "Content-Type": "application/json" }),
      body: JSON.stringify({ query: String(consulta || "") }),
    });
    return !!(r && r.ok);
  } catch (_) { return false; }
}

/** TRAER · el viaje, por SSE. `alEvento` recibe los eventos REALES del backend, sin tocar.
 *
 * `traerAsi` es el consentimiento explícito del tercer estado (Obra 3): sólo destraba una
 * pieza encontrada y sin prueba de origen. Un miss o un impostor conservan su camino — el
 * backend lo garantiza, acá sólo se pasa la bandera. */
export async function traer({ servicio, servidor, credencial = null, traerAsi = false,
                              puppetId = null }, alEvento) {
  try {
    const r = await fetch("/v1/catalog/equip", {
      method: "POST",
      headers: cabeceras({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        service: servicio, server_name: servidor || null,
        credential: credencial || null, puppet_id: puppetId || null,
        traer_asi: !!traerAsi,
      }),
    });
    if (!r.ok) {
      // FALLO VISIBLE, JAMÁS MUDO. Un 401/503 no llega como stream: se traduce a un cierre
      // con causa para que el viaje se detenga con nombre en vez de quedarse pensando.
      alEvento({ type: "cerrado", ok: false, encontrado: false,
                 cause: r.status === 401 ? "sin_sesion" : "sin_red", http: r.status });
      return false;
    }
    return await leerSSE(r, alEvento);
  } catch (_) {
    alEvento({ type: "cerrado", ok: false, encontrado: false, cause: "sin_red" });
    return false;
  }
}

/* ── DERIVACIÓN ─────────────────────────────────────────────────────────────────────── */

/** QUÉ AVISA UNA PIEZA · estructura, no frase.
 *
 * `consecuencias` llega en DOS formas del mismo campo y las dos significan cosas opuestas:
 *   · el string `"se_sabra_al_conectar"` — el manifest NO declara herramientas.
 *   · un objeto `{write, send, delete, declaradas[]}` — el manifest SÍ las declara.
 *
 * La distinción importa: «no declara» no es «no hace nada». Es el aviso que el diseño pone
 * en una franja imposible de perder, y por eso se deriva acá una sola vez. */
export function avisoDe(consecuencias) {
  if (consecuencias && typeof consecuencias === "object") {
    const dec = consecuencias.declaradas || [];
    return {
      declara: true,
      escriben: !!consecuencias.write,
      envian: !!consecuencias.send,
      borran: !!consecuencias.delete,
      cuantas: dec.length,
      // ¿hay algo que perder? Es lo que decide si la franja va en ámbar o discreta.
      pesa: !!(consecuencias.write || consecuencias.send || consecuencias.delete),
    };
  }
  return { declara: false, escriben: false, envian: false, borran: false,
           cuantas: 0, pesa: false };
}

/** UN ÍTEM DE `search` → LA FILA QUE LA SUPERFICIE PINTA. Todo derivado, cero decisión. */
export function modelarFila(item) {
  const badge = item.badge || {};
  return {
    id: item.id,
    nombre: item.name || item.id,
    // LA VOZ de la pieza: qué hace, en una línea, dicha por su propio manifest.
    voz: item.description || "",
    servidor: item.server_name || item.id,
    // EL SELLO SALE SÓLO DEL PIN. `verified` ya viene decidido por el backend
    // (`_registry_badge`: sin `pinned_as` no hay ✓, aunque el namespace sea DNS). Acá no se
    // vuelve a decidir: hacerlo sería la segunda opinión sobre la misma pregunta.
    sello: {
      verificado: !!badge.verified,
      etiqueta: badge.label || "",
      publicador: badge.publisher || null,
      espacio: badge.namespace || item.namespace || null,
    },
    // llave | descarga | click | ninguno — derivado por el backend de lo que el manifest
    // declara (headers/env → llave · packages → descarga · remotes → click).
    requisito: item.requisito || "ninguno",
    aviso: avisoDe(item.consecuencias),
    confianza: typeof item.confianza === "number" ? item.confianza : null,
    // SÓLO SI EXISTE. `null` cuando la pieza nunca se ingirió local, y eso es un dato:
    // significa que nunca estuvo en el local de esta persona.
    fechaIngesta: item.fecha_ingesta || null,
    crudoRef: item.referencia_crudo || null,
    fuente: item.source || "registry",
  };
}

/** LA RESPUESTA DE `search` → LO QUE LA LISTA MUESTRA: filas, o UNO de los tres bordes.
 *
 * ⚠️ LOS TRES BORDES SE DISTINGUEN, Y ESA ES LA FUNCIÓN ENTERA. «Todavía no buscaste»,
 * «no pudimos preguntar» y «preguntamos y no existe» se ven iguales si uno los pinta como
 * una lista vacía — y significan cosas opuestas. Decir «no hay resultados» cuando el
 * registro no contestó le miente al usuario diciéndole que su conector no existe. */
export function modelarBusqueda(q, respuesta) {
  const consulta = String(q || "").trim();
  if (!consulta) return { borde: BORDE_VACIO, consulta, filas: [] };
  // Sin respuesta (cable cortado) o el backend diciendo `unreachable`: es lo MISMO hecho
  // desde el punto de vista del usuario —no pudimos preguntar— y se pinta igual.
  if (!respuesta || respuesta.registry_status === "unreachable")
    return {
      borde: BORDE_CAIDO, consulta, filas: [],
      // el aviso que el backend ya escribió, si lo mandó
      notice: (respuesta && respuesta.notice) || null,
    };
  const filas = (respuesta.items || []).map(modelarFila);
  if (!filas.length) return { borde: BORDE_SIN_RESULTADOS, consulta, filas: [] };
  return { borde: null, consulta, filas, total: (respuesta.counts || {}).registry || filas.length };
}

/** LAS OPCIONES DEL FILTRO · el conteo REAL de cada requisito sobre lo que llegó.
 *
 * Devuelve `[{req, cuenta}]` para los cuatro requisitos, en el orden de `REQUISITOS`, con su
 * cuenta medida — **cero incluido**. Ninguna cuenta se inventa y ninguna se esconde.
 *
 * ⚠️ SE DERIVAN DE LAS FILAS QUE LLEGARON, NO DE LAS QUE QUEDAN DESPUÉS DE FILTRAR. Si se
 * contaran sobre el resultado ya filtrado, al elegir «Llave» desaparecerían «Click» y
 * «Descarga» y el usuario quedaría encerrado en su primer filtro, sin forma de sumar el
 * segundo. Los conteos son los del universo completo y no se mueven al filtrar.
 *
 * ⚠️ Y POR QUÉ LOS CUATRO, INCLUSO EN CERO — esto lo decidió la vara, no yo. Mi primera
 * versión ofrecía SÓLO los requisitos presentes, que parece más limpio. Al medirlo apareció
 * que con esa regla **el vacío por filtro es inalcanzable**: si todo chip ofrecido tiene al
 * menos una fila, ninguna combinación puede dar cero, y el cuarto borde era código muerto —
 * un estado escrito que nadie podía ver nunca. «Llave 0» no es un callejón: es el dato de
 * que ninguna de estas piezas pide llave, dicho sin obligar a contarlas una por una.
 */
export function opcionesDeFiltro(filas) {
  const cuenta = new Map(REQUISITOS.map((r) => [r, 0]));
  for (const f of filas || []) {
    const r = REQUISITOS.includes(f.requisito) ? f.requisito : "ninguno";
    cuenta.set(r, cuenta.get(r) + 1);
  }
  return REQUISITOS.map((r) => ({ req: r, cuenta: cuenta.get(r) }));
}

/** LA VISTA, FILTRADA · una vista NUEVA, con el rastro de lo que el filtro tapó.
 *
 * ⚠️ EL FILTRO SE APLICA ACÁ Y NO AL PINTAR. Si filtrara el render, la única forma de medirlo
 * sería contar `<li>` en un DOM y no habría manera de distinguir «filtró bien» de «pintó de
 * menos». Además el conteo de la cabecera y la lista salen del MISMO objeto: no puede haber
 * dos cuentas de lo mismo, que es el bug que el resumen y las cards ya pagaron una vez.
 *
 * `total` es cuántas llegaron y `filtrado` dice si hay algo puesto — con eso la cabecera
 * puede decir «2 de 4» en vez de «2 encontradas», que sería cierto y engañoso a la vez.
 */
export function aplicarFiltro(vista, filtro) {
  const v = vista || { borde: BORDE_VACIO, consulta: "", filas: [] };
  const activos = (filtro || []).filter((r) => REQUISITOS.includes(r));
  const todas = v.filas || [];
  // Los bordes son estados de la BÚSQUEDA, anteriores al filtro: no hay nada que tapar.
  if (v.borde || !todas.length)
    return { ...v, opciones: [], filtro: [], filtrado: false, total: todas.length };
  const opciones = opcionesDeFiltro(todas);
  if (!activos.length)
    return { ...v, opciones, filtro: [], filtrado: false, total: todas.length };
  const filas = todas.filter((f) => activos.includes(
    REQUISITOS.includes(f.requisito) ? f.requisito : "ninguno"));
  return {
    ...v,
    filas,
    opciones,
    filtro: activos,
    filtrado: true,
    total: todas.length,
    // el cuarto borde SÓLO lo puede levantar el filtro, y sólo si había piezas que tapar
    borde: filas.length ? null : BORDE_FILTRO_VACIO,
  };
}

/** ¿SIGUE EN PANTALLA LA PIEZA ELEGIDA? · para que la ficha no quede huérfana.
 *
 * Decisión declarada: la ficha se CIERRA si el filtro sacó su pieza de la lista, y se
 * conserva si sigue visible. Una ficha al lado de una lista que no la contiene no se puede
 * volver a abrir ni se entiende de dónde salió; cerrarla es reversible —se quita el filtro y
 * se toca de nuevo—. El VIAJE en curso es otra cosa y no se toca. */
export function siguenVisibles(vistaFiltrada, id) {
  if (!id) return true;
  return (vistaFiltrada.filas || []).some((f) => f.id === id);
}

/** FILA + VEREDICTO → LA FICHA. Acá se decide CUÁL DE LAS CUATRO CARAS, y sólo acá.
 *
 * Recibe la FILA ya derivada, no el ítem del endpoint: la ficha es la misma pieza que la
 * lista está mostrando, y derivarla dos veces desde el crudo abriría la puerta a que la
 * fila y su ficha dijeran cosas distintas de lo mismo.
 *
 * El mapa completo, contra los desenlaces reales de `validate`:
 *
 *   registry_status unreachable         → sin_registro   (no pudimos preguntar · ↻)
 *   picked_is_trusted false + hay buena → no_se_puede    (impostor · el camino es la buena)
 *   confiable                           → verificada     ([Traer])
 *   dudoso                              → con_reservas   ([Traer así])
 *   nada                                → no_se_puede    (construir un MCP)
 *
 * ⚠️ «ELEGISTE OTRA QUE LA OFICIAL» ES SU PROPIA CARA, ANTES QUE EL VEREDICTO. Antes colgaba
 * de `confiable`, porque la identidad de la pieza salía de re-descubrir el servicio y el
 * impostor llegaba con el veredicto del ganador legítimo. Desde que el backend resuelve la
 * pieza QUE SE TOCÓ, un impostor es `dudoso` —la pieza existe, pero no es la oficial— y
 * dejarlo colgado ahí habría perdido la advertencia justo en el caso para el que existe.
 *
 * ⚠️ Y NO ALCANZA CON `picked_is_trusted === false`: hace falta SABER CUÁL ES LA BUENA. Esa
 * cara existe para ofrecer [Traer esta] sobre la oficial; sin una que ofrecer sería un
 * callejón —«no se puede», sin salida y sin motivo— peor que la reserva que reemplaza. Es la
 * misma pieza que `confiable` de acá abajo, calculada una sola vez.
 */
export function modelarFicha(fila, validacion, { ahora = null } = {}) {
  const v = validacion || {};
  const caido = !validacion || v.registry_status === "unreachable";
  // LA PIEZA BUENA, cuando el registro sabe cuál es. `trusted_server` primero, y el orden
  // importa: desde que el backend resuelve LA PIEZA TOCADA, `server_name` es la que el
  // usuario eligió —que en el caso del impostor es justamente la mala—. El fallback conserva
  // el camino de descubrimiento puro (sin `server_name`), donde el ganador sí es la buena.
  const laBuena = v.trusted_server || v.server_name || null;

  let cara, motivo = null;
  if (caido) cara = CARA_SIN_REGISTRO;
  else if (v.picked_is_trusted === false && laBuena) cara = CARA_NO_SE_PUEDE;
  else if (v.verdict === "confiable") cara = CARA_VERIFICADA;
  else if (v.verdict === "dudoso") cara = CARA_CON_RESERVAS;
  else cara = CARA_NO_SE_PUEDE;

  if (cara === CARA_NO_SE_PUEDE)
    motivo = v.picked_is_trusted === false ? MOTIVO_IMPOSTOR : MOTIVO_INEXISTENTE;

  return {
    ...fila,
    cara,
    motivo,
    // El mensaje YA VIENE ESCRITO por el backend, en el idioma de la casa, y es el mismo
    // que consumen las demás superficies. Reescribirlo acá sería una segunda voz para el
    // mismo veredicto.
    mensaje: v.message || null,
    // QUÉ NO SE PUDO CONFIRMAR — medido, no adjetivado. Es la línea del diseño 04.
    razon: v.reason || null,
    // LA PIEZA BUENA, cuando el registro sabe cuál es. El diseño la ofrece con [Traer esta];
    // su ficha completa (requisito, confianza, aviso) hay que buscarla — `validate` sólo da
    // el nombre. Quien pinta decide si la muestra con lo que tiene o pide la ficha.
    confiable: laBuena,
    // ¿PODEMOS CONSTRUIRLO? Sólo cuando el registro contestó y no conoce el servicio: un
    // impostor no habilita construcción, porque la pieza buena SÍ existe.
    sePuedeConstruir: !caido && v.verdict === "nada",
    reintentar: !!(caido || v.retry),
    // EL [?] SE ABRE SOLO CUANDO NO PODEMOS RESPONDER POR LA PIEZA. Se deriva del sello —el
    // único campo que dice si alguien probó de quién es— y no de un umbral de confianza
    // escrito acá: un número mágico en el front se desincroniza del backend que lo calibra,
    // y este mismo repo ya pagó esa deuda una vez.
    crudoAuto: !fila.sello.verificado,
    // CUÁNDO SE COMPROBÓ. `validate` no devuelve timestamp — es el momento de ESTA llamada,
    // y por eso lo pone quien llama. Un veredicto sin su cuándo es afirmar de memoria.
    comprobadoTs: ahora || null,
  };
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * EL VIAJE · eventos reales → estados de paso.
 *
 * La ÚNICA regla propia del reductor es la que hereda del checklist del local, y es la que
 * hace honesto el resultado: **después de un paso roto, los siguientes vuelven a
 * «pendiente»**. Pintarlos de cualquier otra forma borraría el dato que hace útil al viaje
 * —hasta dónde se llegó— y repartiría un rojo entre tres líneas en vez de uno con nombre.
 * ════════════════════════════════════════════════════════════════════════════════════ */

export function viajeInicial() {
  return {
    pasos: PASOS_DEL_VIAJE.map((id) => ({ id, estado: "pendiente", detalle: null })),
    cerrado: false, ok: false, causa: null, causaLiteral: null,
    servidor: null, siguiente: null, reserva: null, herramientas: [],
    // `escala` = la pieza entró al local pero le falta algo tuyo → aterriza En preparación.
    escala: false,
  };
}

const _marcar = (estado, id, cual, detalle) => {
  const i = estado.pasos.findIndex((p) => p.id === id);
  if (i < 0) return;
  const yaRoto = estado.pasos.slice(0, i).some((p) => p.estado === "roto");
  estado.pasos[i] = { ...estado.pasos[i], estado: yaRoto ? "pendiente" : cual,
                      detalle: detalle == null ? estado.pasos[i].detalle : detalle };
};

/** UN EVENTO DEL SSE → EL NUEVO ESTADO DEL VIAJE. Mutador, y devuelve el mismo objeto para
 *  que quien pinta no tenga que acordarse de reasignar. */
export function reducirViaje(estado, ev) {
  const t = ev && ev.type;
  if (t === "dispatch.iniciado") {
    estado.servidor = ev.server_name || null;
  } else if (t === "resolver.buscando") {
    _marcar(estado, PASO_RESOLVER, "probando", null);
  } else if (t === "resolver.encontrado" || t === "resolver.con_reservas") {
    // el detalle a la derecha es el NOMBRE REAL que el registro resolvió, no una frase
    _marcar(estado, PASO_RESOLVER, "hecho", ev.server_name || null);
    estado.servidor = ev.server_name || estado.servidor;
    if (t === "resolver.con_reservas") estado.reserva = { texto: ev.reason || null };
  } else if (t === "resolver.registry_down") {
    _marcar(estado, PASO_RESOLVER, "roto", null);
  } else if (t === "resolver.miss") {
    _marcar(estado, PASO_RESOLVER, "roto", null);
  } else if (t === "curacion.probando") {
    _marcar(estado, PASO_COMPROBAR, "probando", null);
  } else if (t === "curacion.rechazo") {
    _marcar(estado, PASO_COMPROBAR, "roto", null);
  } else if (t === "curacion.necesita_credencial") {
    // NO es un fallo del sistema: la pieza pide TU llave para poder comprobarse. Se detiene
    // en el paso, con su camino propio — pegar la llave y volver a intentar.
    _marcar(estado, PASO_COMPROBAR, "roto", null);
  } else if (t === "mcp.equipado") {
    const tools = ev.tools || [];
    estado.herramientas = tools;
    // LAS HERRAMIENTAS LLEGAN TODAS JUNTAS ACÁ, y por eso el detalle de «comprobar» se
    // escribe en este evento y no en uno propio: no existe un evento por herramienta.
    _marcar(estado, PASO_COMPROBAR, "hecho", { herramientas: tools.length });
    _marcar(estado, PASO_TRAER, "probando", null);
    if (ev.reserva) estado.reserva = ev.reserva;
  } else if (t === "cerrado") {
    estado.cerrado = true;
    estado.ok = !!ev.ok;
    estado.causa = ev.cause || null;
    estado.causaLiteral = ev.cause_literal || null;
    estado.siguiente = ev.next || null;
    if (ev.server) estado.servidor = ev.server;
    if (ev.ok) _marcar(estado, PASO_TRAER, "hecho", null);
    else {
      // Un cierre en rojo sin paso roto (p. ej. un 401 traducido) tiene que romper ALGO:
      // un viaje que se cierra mal con los tres pasos en gris no dice dónde se cortó.
      if (!estado.pasos.some((p) => p.estado === "roto"))
        _marcar(estado, estado.pasos.find((p) => p.estado === "probando")
                       ? estado.pasos.find((p) => p.estado === "probando").id
                       : PASO_RESOLVER, "roto", null);
      _marcar(estado, PASO_TRAER, "pendiente", null);
    }
  }
  return estado;
}

/** ¿LA PIEZA QUE LLEGÓ NECESITA ALGO TUYO?
 *
 * ⚠️ NO SE DECIDE ACÁ, Y ESO ES LO IMPORTANTE. El viaje termina en `mcp.equipado` y quién
 * dice si la pieza quedó lista o quedó En preparación es `pertenencia()`, sobre la fila que
 * el equip escribió — la MISMA función que clasifica a las demás. Esta función sólo
 * pregunta «¿ya se puede releer?», para que el montaje recargue y deje que el clasificador
 * hable. Un segundo juez acá sería la contradicción que todo el adaptador existe para no
 * volver a tener. */
export function hayQueRecargar(estado) {
  return !!(estado && estado.cerrado && estado.ok);
}
