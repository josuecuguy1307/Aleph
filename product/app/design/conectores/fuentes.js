/* fuentes.js — DE DÓNDE SACA EL ADAPTADOR LO QUE MUESTRA.
 *
 * Una sola lectura (`GET /v1/conexiones/fuentes`) y un solo lugar donde se arma el modelo
 * que `superficie.js` pinta. Nada más vive acá: ni textos, ni estados, ni decisiones.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * POR QUÉ ESTE ARCHIVO ES CORTO Y TIENE QUE SEGUIR SIÉNDOLO.
 *
 * Este es el archivo que en la versión vieja tenía mil líneas. `conectores.ui.js` mezclaba
 * cuatro trabajos —leer, decidir, pintar y manejar clicks— y por eso arreglar un texto
 * obligaba a tocar la lógica de estado, y arreglar un estado movía un texto sin querer.
 * Acá cada uno vive aparte:
 *
 *   fuentes.js    LEE      · una llamada, cero interpretación
 *   widget.js     DERIVA   · el modelo, todo trazado a una fuente
 *   conocimiento  JUZGA    · lo que sabemos de cada tipo de pieza
 *   superficie.js PINTA    · funciones puras que devuelven HTML
 *   montaje.js    CONECTA  · el DOM y los clicks
 *
 * Si alguna vez este archivo empieza a decidir algo, vuelve el problema entero: habría dos
 * lugares que responden «¿esta pieza está bien?» y tarde o temprano contestarían distinto.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * FALLA ABIERTO, PERO NO MUDO. Si la lectura falla, `leido` es `false` y la superficie lo
 * sabe: muestra lo último que tenía y dice que no pudo actualizar. Lo que NO hace es pintar
 * cuarenta piezas sin ficha como si el catálogo no existiera — eso sería inventar un estado
 * a partir de una lectura que no ocurrió.
 */
import * as W from "./widget.js";
import * as Sem from "../cuarto/cuarto.semaforo.js";

const RUTA = "/v1/conexiones/fuentes";

function sesion() {
  try {
    return (window.AlephSession && AlephSession.get)
      ? AlephSession.get()
      : JSON.parse(sessionStorage.getItem("puppet_user") ||
                   localStorage.getItem("puppet_user") || "null");
  } catch (_) { return null; }
}

export function cabeceras(extra = {}) {
  const h = Object.assign({ Accept: "application/json" }, extra);
  const u = sesion();
  if (u && u.session_token) h.Authorization = "Bearer " + u.session_token;
  return h;
}

/** LOS INSUMOS DE UNA PIEZA · qué cambió, y cuándo, después de la última medición.
 *
 * Es lo que hace posible la ley de la medición rancia: **un veredicto anterior a una llave
 * nueva no manda.** El insumo típico y el que la pidió es la credencial: el usuario pega su
 * llave a las 14:51 y el rojo de las 09:00 —que describía un mundo sin llave— sigue en
 * pantalla como si fuera noticia de hoy.
 *
 * Se arma con las fechas del vault, que por eso viajan en el endpoint. Sin ellas la ley
 * existe y no se aplica nunca, que es peor que no tenerla: parece cubierta.
 */
function insumosDe(entidad, vault, credenciales) {
  const out = [];
  for (const c of credenciales || []) {
    const fila = c.provider && vault[c.provider];
    if (fila && fila.desde) out.push({ que: `llave:${c.provider}`, ts: fila.desde });
  }
  const ref = entidad.credencial_ref;
  if (ref && vault[ref] && vault[ref].desde && !out.some((i) => i.que === `llave:${ref}`))
    out.push({ que: `llave:${ref}`, ts: vault[ref].desde });
  return out;
}

/** UNA PIEZA → EL MODELO QUE LA SUPERFICIE PINTA. Todo derivado, cero decisión acá. */
export function modelarEntidad(entityId, entidad, comunes) {
  const { vault, alias } = comunes;
  const cx = (entidad.medicion || {}).conexion || {};
  const belt = entidad.belt || null;

  // QUÉ CREDENCIALES PIDE, resueltas a su provider — para saber qué buscar en el vault y
  // qué fechas cuentan como insumo. Lo responde el conocimiento, no este archivo.
  const credenciales = W.credencialDe({
    ficha: entidad.ficha, servidorBelt: belt, medicion: entidad.medicion,
    vault: Object.keys(vault), entityId, alias,
  }).credenciales;

  const modelo = W.derivar({
    entityId,
    ficha: entidad.ficha || null,
    servidorBelt: belt,
    medicion: entidad.medicion || null,
    credencialRef: entidad.credencial_ref || null,
    // EL VAULT como lista de PROVIDERS. Nunca llegan valores: el endpoint no los manda.
    vault: Object.keys(vault),
    alias,
    insumos: insumosDe(entidad, vault, credenciales),
    envDeclarado: entidad.env_declarado || null,
    scopesConcedidos: entidad.scopes_concedidos || [],
    clasificacion: entidad.clasificacion || null,
    tuvoVerdePrevio: !!entidad.tuvo_verde_previo,
    estuvoCompleta: !!entidad.estuvo_completa,
    // EL BOTÓN SALE DE REPAIR, siempre. `caminoDe` es el diccionario único causa→acción que
    // ya usan el Cuarto, el chat y el preflight. Que la superficie de conectores tuviera el
    // suyo era como se llegaba a dos botones distintos para la misma falla.
    camino: Sem.caminoDe({ estado: cx.estado, causa: cx.causa }),
  });

  modelo.nombre = entidad.nombre || entityId;
  modelo.slug = entidad.slug || null;
  // La reserva no cambia el veredicto ni la pertenencia: viaja como un eje independiente.
  // El panel la muestra bajo el mismo [?] que la evidencia de la medición.
  modelo.reserva = entidad.reserva || null;
  // LA LÁPIDA · el permiso del usuario, que manda sobre la medición. Una pieza apagada no
  // va a correr aunque el registro la haya medido viva, y pintarla verde sería mentir sobre
  // lo único que importa: si va a estar cuando el agente la use.
  modelo.apagada = entidad.habilitado === false;
  return modelo;
}

/** LA LECTURA. Una llamada, y el modelo de toda la pantalla. */
export async function cargar() {
  let datos = null;
  try {
    const r = await fetch(RUTA, { headers: cabeceras() });
    if (r.ok) datos = await r.json();
  } catch (_) { /* falla abierto: se reporta con `leido`, no con una excepción */ }

  if (!datos || !datos.leido)
    return { modelos: [], leido: false, vault: {}, alias: {} };

  const comunes = { vault: datos.vault || {}, alias: datos.alias || {} };
  const modelos = Object.entries(datos.entidades || {})
    .map(([id, e]) => modelarEntidad(id, e, comunes))
    // EL ORDEN: primero lo que necesita algo del usuario, después lo que anda. Es el único
    // criterio que le sirve a alguien que abre esta pantalla — y no es una decisión sobre
    // el estado, es una sobre el orden de lectura.
    .sort((a, b) => peso(b) - peso(a) || String(a.nombre).localeCompare(String(b.nombre)));

  return { modelos, leido: true, ...comunes };
}

function peso(m) {
  const v = m.veredicto || {};
  if (v.estado === "esperando") return 2;
  if (v.estado === "bloqueado") return 1;
  return 0;
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS VERBOS · lo único que esta capa ESCRIBE.
 *
 * Cada uno es un verbo del sistema, no una acción inventada por la pantalla. La regla que
 * los ordena es la ley: **lo interno se arregla solo**. `medir` lo dispara la superficie
 * sin que nadie lo pida; `guardarLlave` y `autorizar` son los únicos con parte del usuario.
 * ════════════════════════════════════════════════════════════════════════════════════ */

/** verify · LO INTERNO SE ARREGLA SOLO. Silencioso y sin bloquear: si falla, la card queda
 *  como estaba. Un error de NUESTRA medición no puede convertirse en un rojo sobre la
 *  conexión del usuario. */
export async function medir(entityId) {
  try {
    const r = await fetch("/v1/motor/probar", {
      method: "POST",
      headers: cabeceras({ "Content-Type": "application/json" }),
      body: JSON.stringify({ tipo: "mcp", ref: entityId }),
    });
    return !!(r && r.ok);
  } catch (_) { return false; }
}

/** EL ÚNICO BOTÓN DE UNA CARD ROJA · relanza el ciclo COMPLETO sobre una pieza.
 *
 * ⚠️ NO ES `medir()`. Ese verbo produce el veredicto del MOTOR; las dos columnas que esta
 * superficie lee —`conexion` y `credencial`— las escribe `verificar_uno`, que arranca el
 * server de verdad, elige tools, prueba la conexión y corre la prueba DOBLE de credencial.
 * Un [Reintentar conexión] cableado al otro repintaría la card con el mismo estado y se
 * vería roto sin estarlo.
 *
 * Y repair viaja debajo: el auto-ajuste de versión se dispara solo durante el arranque, sin
 * botón y sin pedirle permiso a nadie, porque la receta es territorio de Aleph.
 */
export async function reintentarConexion(entityId) {
  try {
    const r = await fetch(`/v1/conexiones/${encodeURIComponent(entityId)}/reintentar`,
      { method: "POST", headers: cabeceras() });
    if (!r.ok) return false;
    const j = await r.json().catch(() => ({}));
    return !!j.ok;
  } catch (_) { return false; }
}

/** authorize · el ÚNICO verbo con parte del usuario. Pega la llave, se valida en vivo y
 *  queda guardada cifrada; el `verify` que sigue lo dispara el llamador, no el usuario.
 *
 *  ⚠️ `secret` ACEPTA UN OBJETO, y no es un capricho: hay conectores curados que piden más
 *  de un campo (`jupyter` pide url, token y notebook). El otro camino los serializaba a JSON
 *  —`connectors_router.py:459`— antes de guardarlos, así que serializar igual acá no inventa
 *  un formato nuevo: usa EL MISMO que ya está en el vault de quien los conectó por ahí.
 *
 *  ⚠️ `base_es_validador` DICE DE QUÉ DIRECCIÓN SE TRATA. Para un proveedor de modelos con
 *  base propia, esa dirección ES donde se valida. Para un conector del catálogo con
 *  `needs_base_url` —canvas, moodle, jupyter— es EL DOMINIO DEL USUARIO, y validarlo como si
 *  fuera una API de modelos deja la llave sin guardar (medido: `proveedor_caido`).
 *
 *  ⚠️ Y `base_url` viaja porque LA RUTA YA LO ACEPTA (`centro_conexiones.py:2216`, que se lo
 *  pasa a `agregar_key`). Era el verbo el que lo dejaba afuera, y por eso los tres conectores
 *  con dirección propia —canvas, moodle, jupyter— no tenían cómo entrar por esta puerta. Se
 *  COMPLETA el verbo; no se abre un segundo camino, que es exactamente el error que esta
 *  reparación viene a deshacer. */
export async function guardarLlave(provider, secret,
                                   { base_url = null, guardar_igual = false,
                                     base_es_validador = true } = {}) {
  const valor = (secret && typeof secret === "object") ? JSON.stringify(secret) : secret;
  const r = await fetch("/v1/conexiones/key", {
    method: "POST",
    headers: cabeceras({ "Content-Type": "application/json" }),
    body: JSON.stringify({ provider, secret: valor, base_url, guardar_igual,
                           base_es_validador }),
  });
  return await r.json();
}

/** OAUTH · empezar el trámite. Devuelve `{url}` para salir al proveedor, o el motivo.
 *
 * ⚠️ ES UN POST, Y LA SUPERFICIE LO LLAMABA CON UN GET. `montaje.js` hacía
 * `location.href = /v1/connectors/<id>/oauth/start`, y esa ruta está declarada
 * `@router.post` — o sea que el botón [Autorizar] mandaba a un **404**. Medido:
 *   GET  → 404 · POST sin sesión → 401 no_session · POST con sesión → 200 {state, message}
 * Y el docstring de la ruta lo dice: «inicia OAuth y devuelve URL + estado observable».
 *
 * El consentimiento sigue pasando en el sitio del proveedor —eso no cambia y es lo correcto—
 * pero antes hay que PEDIR la URL, no adivinarla. Si no viene, viene el motivo: hoy una app
 * sin registrar contesta «requiere la app OAuth (…_CLIENT_ID/SECRET en env)», y decirlo es
 * mejor que mandar a un redirect que no existe. */
export async function empezarOauth(entityId) {
  const r = await fetch(`/v1/connectors/${encodeURIComponent(entityId)}/oauth/start`,
    { method: "POST", headers: cabeceras({ "Content-Type": "application/json" }) });
  const j = await r.json().catch(() => null);
  return { http: r.status, url: (j && (j.url || j.authorize_url || j.redirect)) || null,
           motivo: (j && (j.message || (j.detail && (j.detail.detail || j.detail.error)))) || null };
}

/** disconnect · la lápida. Apaga la conexión Y DEJA LA LLAVE: volver es un click. */
export async function desconectar(entityId) {
  const r = await fetch(`/v1/conexiones/${encodeURIComponent(entityId)}/desconectar`,
    { method: "POST", headers: cabeceras() });
  return r.ok;
}

export async function reconectar(entityId) {
  const r = await fetch(`/v1/conexiones/${encodeURIComponent(entityId)}/reconectar`,
    { method: "POST", headers: cabeceras() });
  return r.ok;
}

/** LA OTRA ACCIÓN, la de seguridad: BORRAR la llave. Es distinta de desconectar y por eso
 *  está separada — una es operativa y reversible con un click, la otra cuesta volver a
 *  conseguir la credencial. Fundirlas obligaría a pagar el precio de la segunda cada vez
 *  que se quiere la primera. */
export async function sacarLlave(provider) {
  const r = await fetch(`/v1/conexiones/key/${encodeURIComponent(provider)}`,
    { method: "DELETE", headers: cabeceras() });
  if (!r.ok) return false;
  const j = await r.json().catch(() => ({}));
  return !!j.deleted;
}

/** ¿HAY QUE MEDIR ESTA PIEZA, SIN MOLESTAR A NADIE?
 *
 * Dos preguntas, y las dos son nuestras:
 *   · `necesitaMedicionInterna` — el canal está y falta ejercitarlo, o la llave está y
 *     falta probarla. Es la regla que ya usaban las cards viejas.
 *   · las notas del conocimiento — una regla dijo «esto se re-mide solo»: un veredicto sin
 *     fecha, una causa temporal, un primer boot en frío. Antes de la tabla, esas piezas
 *     quedaban en rojo hasta que alguien las tocara a mano.
 */
export function hayQueMedir(modelo) {
  const m = modelo.evidencia || {};
  const cr = (modelo.credencial || {});
  if (Sem.necesitaMedicionInterna({ estado: m.estado },
                                  { estado: cr.medida })) return true;
  // ⚠️ LA MEDICIÓN RANCIA ES UN GATILLO, NO UNA ETIQUETA (acta §7.c). `medicionRancia()`
  // existía y sólo servía para no pintar un rojo viejo: la pieza quedaba diciendo
  // «midiendo» y nadie medía. Ahora dispara la medición — que es lo que la palabra
  // prometía desde el principio.
  if ((modelo.veredicto || {}).rancia) return true;
  return ((modelo.veredicto || {}).notas || [])
    .some((n) => n.que === "verify_pendiente");
}

/** EL CHECKLIST VIVO · los verbos completándose, uno por uno, en la card.
 *
 * ⚠️ NO ES TELEMETRÍA NUEVA. `POST /v1/conexiones/checklist` ya existe y ya emite la
 * secuencia entera por SSE: `fila.inicio` trae los verbos ANTES de correr ninguno,
 * `requisito.probando` dice cuál está corriendo, `requisito.resultado` trae su veredicto
 * con causa tipada, y `fila.cerrada` cierra. Lo único que faltaba era mirarlo.
 *
 * Y LOS VERBOS SON LOS REALES, no una secuencia inventada para la pantalla:
 *   spec → handshake → tools → credencial
 * con los títulos que el backend ya escribió en el idioma del usuario. Dibujar seis pasos
 * donde el sistema corre cuatro sería una animación, no un estado — y una animación que no
 * corresponde a nada es peor que un spinner: miente con más detalle.
 *
 * El spinner mudo era el problema: [Reintentar] se apretaba y no pasaba nada visible hasta
 * que la card cambiaba (o no). Ahora se ve QUÉ está pasando y, si falla, EN QUÉ VERBO.
 */
export async function checklistEnVivo(slug, alEvento) {
  const r = await fetch("/v1/conexiones/checklist", {
    method: "POST",
    headers: cabeceras({ "Content-Type": "application/json" }),
    body: JSON.stringify({ slugs: [slug] }),
  });
  return leerSSE(r, alEvento);
}

/** EL LECTOR DE SSE · uno solo para toda la casa.
 *
 * ⚠️ ESTÁ EXPORTADO PORQUE HAY DOS STREAMS, NO PORQUE SOBRE. El checklist de una pieza del
 * local (`/v1/conexiones/checklist`) y el viaje de una pieza que se trae del catálogo
 * público (`/v1/catalog/equip`) son cables distintos con vocabularios distintos — pero el
 * PARSEO es idéntico, y un segundo parser es un segundo lugar donde volver a equivocarse
 * con el corte de los chunks.
 *
 * El corte por `\n\n` y el resto guardado en el buffer no son ceremonia: un chunk puede
 * partir un evento al medio, y parsear lo que llegó a medias es exactamente cómo se pierde
 * el evento que trae la causa — el único que hace útil al stream cuando algo falla.
 */
export async function leerSSE(r, alEvento) {
  if (!r || !r.ok || !r.body) return false;
  const lector = r.body.getReader();
  const dec = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    buffer += dec.decode(value, { stream: true });
    let corte;
    while ((corte = buffer.indexOf("\n\n")) >= 0) {
      const bloque = buffer.slice(0, corte);
      buffer = buffer.slice(corte + 2);
      for (const linea of bloque.split("\n")) {
        if (!linea.startsWith("data:")) continue;
        try { alEvento(JSON.parse(linea.slice(5).trim())); }
        catch (_) { /* un evento ilegible no puede cortar el stream */ }
      }
    }
  }
  return true;
}

/** §7 · EL BARRIDO DEL LOCAL · verde viejo no existe.
 *
 * Los tres momentos del acta pegan contra el mismo verbo: al arrancar Aleph (lo dispara el
 * sidecar en su lifespan), al equipar una pieza, y cuando la superficie ve que la pertenencia
 * puede haber caducado. Uno solo, así «volver a mirar» significa lo mismo en los tres.
 */
export async function barrerLocal() {
  try {
    const r = await fetch("/v1/conexiones/barrer",
      { method: "POST", headers: cabeceras() });
    if (!r.ok) return false;
    const j = await r.json().catch(() => ({}));
    return !!j.ok;
  } catch (_) { return false; }
}
