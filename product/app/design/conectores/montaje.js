/* montaje.js — DONDE EL ADAPTADOR SE ENCUENTRA CON EL DOM. Y nada más.
 *
 * Es la última capa y la más chica a propósito:
 *
 *   fuentes.js    LEE      · una llamada, cero interpretación
 *   widget.js     DERIVA   · el modelo, todo trazado a una fuente
 *   conocimiento  JUZGA    · lo que sabemos de cada tipo de pieza
 *   superficie.js PINTA    · funciones puras que devuelven HTML
 *   montaje.js    CONECTA  · esto: nodos, clicks y recarga
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * LO QUE ACÁ NO PUEDE PASAR, y la vara lo comprueba:
 *
 *   · NINGÚN TEXTO. Si un rótulo se escribe acá, hay dos lugares que dicen lo mismo y un
 *     día dirán cosas distintas. Todo texto sale de `superficie.js`.
 *   · NINGUNA DECISIÓN DE ESTADO. Esta capa no sabe qué es «conectado»: recibe modelos ya
 *     derivados y los pinta. Si empezara a decidir, sería la quinta opinión sobre la misma
 *     pieza.
 *   · NINGÚN NOMBRE DE CONECTOR. Un click es un click para las 42 de hoy y las 17.000 del
 *     catálogo público.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────
 * DELEGACIÓN, NO LISTENERS POR FILA. Un `addEventListener` por card significa re-atarlos en
 * cada render, y perder uno es un botón muerto que nadie nota hasta que un usuario lo
 * aprieta. Con delegación hay UN listener por host y las filas pueden reescribirse enteras
 * sin que nada quede colgando.
 */
import * as F from "./fuentes.js";
import * as S from "./superficie.js";
import * as C from "./catalogo.js";
import * as SC from "./superficie-catalogo.js";
import { montarRecomendados } from "./recomendados.js";

/** LA CUARTA VISTA · su controlador. Se monta desde acá y no desde la pantalla.
 *
 * ⚠️ ANTES SE MONTABA APARTE, con un motivo que yo escribí en `Conectores.dc.html`: «se
 * alimenta de otra cosa, meterla adentro la ataría a un estado que no necesita». La primera
 * mitad es cierta —lee `GET /v1/connectors?workspace=`, no la derivación de fuentes— pero la
 * conclusión no se seguía: `ESTADO.catalogo` ya demuestra que una vista puede vivir acá con
 * SU estado y sólo el suyo. Lo que la excepción produjo fue una vista que se ataba sus
 * propios clicks, leía por su cuenta y guardaba por una puerta distinta a la de la casa.
 * Comparte la máquina de vistas y nada más — igual que antes, pero sin el privilegio. */
let RECO = null;

/** LOS VERBOS QUE ESTA CAPA USA, en un objeto y no importados directo.
 *
 * ⚠️ NO ES CEREMONIA: ES LA COSTURA POR DONDE ENTRA LA VARA. El testigo que importa acá
 * —«al guardar la llave, `verify` corre SOLO»— es una SECUENCIA, y una secuencia no se
 * puede comprobar mirando HTML ni leyendo el código con una expresión regular. Con esto la
 * vara sustituye los dos verbos por espías y comprueba el orden de verdad, sin levantar un
 * navegador (que es lo que hacía que las varas de la superficie vieja se corrieran una vez
 * y se abandonaran).
 *
 * Fuera de la vara nadie lo toca: son las funciones de `fuentes.js`, tal cual.
 */
export const VERBOS = {
  medir: F.medir,
  guardarLlave: F.guardarLlave,
  desconectar: F.desconectar,
  empezarOauth: F.empezarOauth,
  reconectar: F.reconectar,
  sacarLlave: F.sacarLlave,
  reintentarConexion: F.reintentarConexion,
  barrerLocal: F.barrerLocal,
  checklistEnVivo: F.checklistEnVivo,
  cargar: F.cargar,
  // ── los del catálogo público. Entran por la MISMA puerta y por la misma razón: el
  //    testigo que importa acá —«tocar una pieza corre validate», «[Traer] dispara el
  //    stream y la pieza aparece en la aduana»— es una SECUENCIA, y una secuencia no se
  //    comprueba mirando HTML.
  buscarCatalogo: C.buscar,
  validarPieza: C.validar,
  crudoDePieza: C.crudo,
  traerPieza: C.traer,
  noCoincide: C.noCoincide,
};

export const ESTADO = {
  modelos: [],
  vault: {},
  vista: "conectores",  // conectores | llavero | catalogo
  leido: false,
  abierto: null,        // qué panel está desplegado (uno por vez: la pista tiene un foco)
  detalle: null,        // qué [?] está abierto
  q: "",
  // LO INTERNO SE ARREGLA SOLO, PERO UNA VEZ POR CARGA. Sin esto, render → medir → render
  // → medir es un loop que castiga al backend y nunca converge.
  midiendo: new Set(),
  /** LA SECCIÓN PÚBLICA · su propio estado, y sólo el suyo.
   *
   * ⚠️ SEPARADO DEL ESTADO DEL LOCAL A PROPÓSITO. Son dos preguntas distintas —«qué tengo»
   * vs. «qué existe»— y meterlas en los mismos campos es cómo una búsqueda del catálogo
   * terminaría filtrando la lista de tus servicios. `q` filtra lo tuyo; `catalogo.consulta`
   * le pregunta al registro. */
  catalogo: {
    consulta: "",
    // LO QUE LA PERSONA ELIGIÓ VER · array de requisitos. Vacío = todo.
    // ⚠️ NO SE PERSISTE Y NO VIAJA: es una lente sobre lo que ya llegó, no una preferencia.
    // Guardarlo haría que la próxima búsqueda arranque tapada por una decisión de la
    // anterior, y nadie recuerda haber puesto un filtro tres pantallas atrás.
    filtro: [],
    vista: null,        // lo que `modelarBusqueda` devolvió: filas, o uno de los tres bordes
    elegida: null,      // id de la pieza cuya ficha está al lado
    ficha: null,        // el modelo de esa ficha (item + veredicto)
    crudo: null,        // el manifest de ESA pieza, si ya se pidió
    crudoAbierto: false,
    comprobando: null,  // la fila cuya validación está en vuelo (todavía no hay cara)
    viaje: null,        // el estado del viaje mientras una pieza se trae
    llegada: null,      // el acuse de la última que llegó (se va al recargar)
    // GENERACIÓN · toda respuesta vieja se descarta. Sin esto, una búsqueda lenta pisa a
    // una rápida y la lista muestra resultados de una consulta que ya no está escrita.
    gen: 0,
    // ⚠️ EL VIAJE TIENE SU PROPIA GENERACIÓN, Y NO ES UN LUJO. Con una sola, escribir en el
    // buscador mientras una pieza viaja invalidaba el viaje: el stream seguía llegando, el
    // backend terminaba de equipar, y la pantalla no repintaba, no recargaba y no acusaba la
    // llegada. La pieza entraba a tu local y nadie te lo decía. Buscar y traer son dos cosas
    // que pasan a la vez a propósito —el viaje avisa «podés irte a otra pantalla»— así que
    // cancelar una no puede cancelar la otra.
    genViaje: 0,
  },
};

let HOSTS = null;

const $ = (sel, raiz = document) => raiz.querySelector(sel);

function coincide(modelo) {
  const q = ESTADO.q.trim().toLowerCase();
  if (!q) return true;
  return [modelo.nombre, modelo.entityId].join(" ").toLowerCase().includes(q);
}

function visibles() {
  return ESTADO.modelos.filter(coincide);
}

/** LAS DOS LISTAS · el local y la aduana, del MISMO array de modelos.
 *
 * ⚠️ NO SON DOS FUENTES. Es una sola lista partida por `pertenencia.local`, que el
 * adaptador ya calculó. Si cada vista consultara por su cuenta «¿ésta es mía?», una pieza
 * podría aparecer en las dos o en ninguna — y el contador de una contaría lo de la otra,
 * que es el bug que el resumen y las cards ya pagaron una vez.
 */
function partir(items) {
  const local = [], aduana = [];
  for (const m of items) ((m.pertenencia || {}).local ? local : aduana).push(m);
  return { local, aduana };
}

function modeloDe(entityId) {
  return ESTADO.modelos.find((m) => m.entityId === entityId) || null;
}

/** PINTAR · el resumen y la lista salen de la MISMA lista de modelos, en la misma pasada.
 *  Que el conteo coincida con las cards no es una regla que alguien tenga que respetar:
 *  es que no hay dos fuentes de las que puedan salir números distintos. */
function pintar() {
  // Sin nodos no hay nada que pintar, y no es un error: es lo que pasa cuando la vara
  // ejercita un verbo sin haber montado una pantalla. Un `recargar()` que reviente acá
  // haría imposible probar el trámite sin un navegador — que es justo lo que se evitó.
  if (!HOSTS) return;
  const items = visibles();
  const { local, aduana } = partir(items);
  // EL CONTADOR DEL LOCAL CUENTA SOLO COMPLETAS. Dejó de decir 42 cuando no hay 42 usables:
  // dice la verdad, que es lo único que un contador puede aportar.
  const { local: todasLocal } = partir(ESTADO.modelos);
  if (HOSTS.resumen) HOSTS.resumen.innerHTML = S.pintarResumen(todasLocal);
  if (HOSTS.conteo) HOSTS.conteo.textContent = String(local.length);
  if (HOSTS.aduana) {
    // LA MISMA CUENTA para el render, el contador y el `hidden`. `piezasDeAduana` es la
    // única que decide qué se muestra; contar acá por separado es cómo la sección quedaba
    // visible, diciendo 1, y vacía adentro.
    const visibles = S.piezasDeAduana(aduana);
    HOSTS.aduana.innerHTML = !ESTADO.leido ? "" : S.pintarAduana(aduana);
    if (HOSTS.conteoAduana) HOSTS.conteoAduana.textContent = String(visibles.length);
    if (HOSTS.seccionAduana) HOSTS.seccionAduana.hidden = !ESTADO.leido || !visibles.length;
  }
  pintarVista();
  if (HOSTS.llavero) {
    HOSTS.llavero.innerHTML = !ESTADO.leido
      ? S.pintarSinLectura()
      : S.pintarLlavero(ESTADO.vault, ESTADO.modelos);
    if (HOSTS.conteoLlavero)
      HOSTS.conteoLlavero.textContent = String(Object.keys(ESTADO.vault).length);
  }
  if (!HOSTS.lista) return;

  HOSTS.lista.innerHTML =
    !ESTADO.leido ? S.pintarSinLectura()
    : !local.length ? S.pintarVacio()
    : local.map((m) => S.pintarCard(m)).join("");

  // Lo desplegado sobrevive al repintado. Si no, guardar una llave cerraría el panel en el
  // que se está trabajando — y el usuario tendría que volver a abrirlo para ver qué pasó.
  if (ESTADO.abierto) desplegar(ESTADO.abierto, "panel", true);
  if (ESTADO.detalle) desplegar(ESTADO.detalle, "detalle", true);
  if (window.AlephDS) {
    try {
      const t = HOSTS.lista.closest("[data-ds-track]");
      if (t) { AlephDS.init(document); AlephDS.refresh(t); }
    } catch (_) { /* el sistema de diseño no puede tumbar la lista */ }
  }
}

/** CORRER EL CHECKLIST VIVO · los verbos completándose adentro de la card.
 *
 * ⚠️ SE ABRE EL PANEL PRIMERO. Un checklist que corre en una fila plegada es un spinner con
 * más pasos: el usuario ve que algo tarda y no ve qué. Apretar [Reintentar] despliega la
 * fila, y ahí se pinta la secuencia.
 *
 * EL REDUCTOR TIENE UNA SOLA REGLA PROPIA, y es la que hace honesto el resultado: **después
 * de un verbo roto, los siguientes vuelven a «no corrió»**. El backend, cuando se le vence
 * el plazo, emite un resultado por cada verbo restante; pintarlos como si hubieran corrido
 * borraría justo el dato que hace útil al checklist —hasta dónde se llegó— y dejaría un
 * rojo repartido entre cuatro líneas en vez de uno con nombre.
 */
async function correrChecklist(entityId, disparar) {
  const modelo = modeloDe(entityId);
  if (!modelo || !modelo.slug) {
    // Sin slug no hay checklist que pedir. NO se inventa uno: se corre el verbo igual y la
    // fila se repinta al terminar — peor experiencia, cero mentira.
    await disparar();
    return recargar();
  }
  desplegar(entityId, "panel", true);
  const host = () => $(`[data-checklist="${CSS.escape(entityId)}"]`, document);
  const estado = { verbos: [] };
  const repintar = () => { const h = host(); if (h) h.innerHTML = S.pintarChecklist(estado); };

  const alEvento = (ev) => {
    if (ev.type === "fila.inicio") {
      // La secuencia ENTERA antes de correr nada: el usuario ve qué va a pasar, no sólo
      // qué pasó. Es la diferencia entre un plan y un registro.
      estado.verbos = (ev.requisitos || []).map((r) => ({ ...r, estado: "pendiente" }));
    } else if (ev.type === "requisito.probando") {
      const v = estado.verbos.find((x) => x.id === ev.id);
      if (v) v.estado = "probando";
    } else if (ev.type === "requisito.resultado") {
      const i = estado.verbos.findIndex((x) => x.id === ev.id);
      if (i >= 0) {
        const yaRoto = estado.verbos.slice(0, i).some((x) => x.estado === "roto");
        estado.verbos[i] = { ...estado.verbos[i], estado: yaRoto ? "pendiente" : ev.estado,
                             causa: ev.causa || null };
      }
    }
    repintar();
  };

  try { await VERBOS.checklistEnVivo(modelo.slug, alEvento); }
  catch (_) { /* si el cable se corta, la recarga de abajo dice la verdad igual */ }
  // Y el verbo que el usuario pidió, DESPUÉS de mirar: el checklist observa, no reemplaza.
  await disparar();
  return recargar();
}

/** Desplegar el panel o el [?] de una fila. Uno por vez: la pista tiene un solo foco. */
function desplegar(entityId, cual, forzar) {
  // El panel puede estar en el local o en la aduana: se busca en las dos. Una pieza que se
  // promueve mientras su panel está abierto cambia de lista, y buscar sólo en una dejaría
  // el trámite abierto apuntando a un nodo que ya no existe.
  const host = $(`[data-panel="${CSS.escape(entityId)}"]`, HOSTS.lista) ||
               (HOSTS.aduana && $(`[data-panel="${CSS.escape(entityId)}"]`, HOSTS.aduana));
  const modelo = modeloDe(entityId);
  if (!host || !modelo) return;
  const ya = (cual === "panel" ? ESTADO.abierto : ESTADO.detalle) === entityId;
  if (ya && !forzar) {
    host.hidden = true; host.innerHTML = "";
    if (cual === "panel") ESTADO.abierto = null; else ESTADO.detalle = null;
    return;
  }
  ESTADO.abierto = cual === "panel" ? entityId : null;
  ESTADO.detalle = cual === "detalle" ? entityId : null;
  host.innerHTML = cual === "panel" ? S.pintarPanel(modelo) : S.pintarDetalle(modelo);
  host.hidden = false;
  // El chevron dice si la fila está abierta. Sin esto un lector de pantalla anuncia
  // «contraído» sobre una fila desplegada.
  const q = $(`[data-detalle="${CSS.escape(entityId)}"]`, HOSTS.lista);
  if (q) q.setAttribute("aria-expanded", String(cual === "detalle"));
}

/** RECARGAR · una sola lectura, y todo se vuelve a derivar de cero.
 *
 * No hay actualización incremental a propósito. Parchear una card en el lugar exige saber
 * qué cambió, y esa cuenta es donde nacían los estados imposibles de la superficie vieja
 * (un header viejo sobreviviendo a una credencial nueva). Volver a leer y volver a derivar
 * es más lento en microsegundos e imposible de desincronizar.
 */
export async function recargar() {
  const r = await VERBOS.cargar();
  ESTADO.modelos = r.modelos;
  ESTADO.vault = r.vault || {};
  ESTADO.leido = r.leido;
  pintar();
  medirLoQueFalta();
  return r;
}

/** Las TRES vistas de la pantalla. Conectores es qué tenés; Llavero es con qué se
 *  autentican; Catálogo público es qué existe. Son tres preguntas distintas y por eso son
 *  tres vistas, no tres columnas — y las tres viven en la MISMA pantalla, no en páginas
 *  paralelas que se pierden de vista una a la otra. */
function pintarVista() {
  const v = ESTADO.vista;
  if (HOSTS.panelConectores) HOSTS.panelConectores.hidden = v !== "conectores";
  if (HOSTS.panelLlavero) HOSTS.panelLlavero.hidden = v !== "llavero";
  if (HOSTS.panelCatalogo) HOSTS.panelCatalogo.hidden = v !== "catalogo";
  // [F3] La cuarta: «qué le sirve a este espacio». Se agrega acá y no en un segundo
  // conmutador porque dos máquinas de vistas sobre los mismos paneles terminan dejando dos
  // visibles a la vez — y el que gana depende del orden de los listeners.
  if (HOSTS.panelReco) HOSTS.panelReco.hidden = v !== "recomendados";
  if (HOSTS.tabConectores)
    HOSTS.tabConectores.setAttribute("aria-selected", String(v === "conectores"));
  if (HOSTS.tabLlavero)
    HOSTS.tabLlavero.setAttribute("aria-selected", String(v === "llavero"));
  if (HOSTS.tabReco)
    HOSTS.tabReco.setAttribute("aria-selected", String(v === "recomendados"));
  // La franja de tabs y la cabecera del local no pintan en el catálogo: ahí la pantalla es
  // la sección, con su propio «← Tus conectores» para volver.
  if (HOSTS.tabs) HOSTS.tabs.hidden = v === "catalogo";
  if (HOSTS.cabecera) HOSTS.cabecera.hidden = v === "catalogo";
  if (v === "catalogo") pintarCatalogo();
}

/** LA SECCIÓN, PINTADA · el acuse de llegada arriba, la lista a la izquierda, y a la
 *  derecha la ficha o el viaje de la pieza elegida.
 *
 * Una sola pasada, igual que el resto: no hay actualización incremental porque parchear
 * exige saber qué cambió, y esa cuenta es donde nacen los estados imposibles. */
function pintarCatalogo() {
  if (!HOSTS || !HOSTS.catalogoLista) return;
  const cat = ESTADO.catalogo;
  const vista = cat.vista || { borde: C.BORDE_VACIO, consulta: "", filas: [] };

  if (HOSTS.catalogoLlegada) {
    // ⚠️ EL AVISO CHICO NO CONVIVE CON EL DESENLACE. Los dos cuentan el mismo hecho —«arXiv
    // ya está lista»— y tenerlos juntos en la pantalla es la duplicación de siempre: dos
    // textos para una cosa, que un día dirán cosas distintas. Mientras el viaje terminado
    // está abierto habla ÉL, que además dice dónde quedó y ofrece el camino; el aviso queda
    // como el RASTRO que sobrevive cuando el usuario cierra.
    const acusar = cat.llegada && !cat.viaje;
    HOSTS.catalogoLlegada.innerHTML = acusar ? SC.pintarLlegada(cat.llegada) : "";
    HOSTS.catalogoLlegada.hidden = !acusar;
  }

  // EL CONTEO DE LO TUYO sale de la MISMA lista de modelos que pinta el resumen. Si el
  // registro se cae, la frase «tus N piezas siguen funcionando» tiene que decir la verdad;
  // sin lectura no se inventa un número.
  const conectadas = ESTADO.leido
    ? ESTADO.modelos.filter((m) => (m.veredicto || {}).estado === "conectado" && !m.apagada).length
    : null;

  // EL FILTRO SE APLICA ACÁ, sobre lo que ya llegó. No pide nada, no guarda nada: es una
  // lente. La cabecera y la lista salen del MISMO objeto, así que no puede haber dos cuentas.
  const conFiltro = C.aplicarFiltro(vista, cat.filtro);
  HOSTS.catalogoLista.innerHTML = SC.pintarLista({ ...conFiltro, elegida: cat.elegida },
                                                 { conectadas });

  if (HOSTS.catalogoFicha) {
    // EL VIAJE REEMPLAZA A LA FICHA MIENTRAS DURA. No conviven: mostrar el botón [Traer]
    // debajo de un viaje en curso invita a apretarlo dos veces.
    HOSTS.catalogoFicha.innerHTML =
      cat.viaje ? SC.pintarViaje(cat.viaje, { nombre: (cat.ficha || cat.comprobando || {}).nombre || "" })
      : cat.ficha ? SC.pintarFicha(cat.ficha, { crudo: cat.crudo, crudoAbierto: cat.crudoAbierto })
      : cat.comprobando ? SC.pintarComprobando(cat.comprobando)
      : "";
    HOSTS.catalogoFicha.hidden = !(cat.viaje || cat.ficha || cat.comprobando);
  }
  if (HOSTS.catalogoVista)
    HOSTS.catalogoVista.dataset.conFicha =
      String(!!(cat.viaje || cat.ficha || cat.comprobando));
}

/** BUSCAR EN EL REGISTRO · una consulta, una generación, y lo viejo se descarta. */
async function buscarEnCatalogo(consulta) {
  const cat = ESTADO.catalogo;
  cat.consulta = String(consulta || "");
  const gen = ++cat.gen;
  // Al cambiar la búsqueda, la ficha abierta deja de tener sentido: pertenece a la lista
  // anterior. Un viaje en curso NO se toca — el usuario puede seguir escribiendo mientras
  // una pieza viaja, y cortarlo por eso sería perder el trabajo hecho.
  cat.elegida = null; cat.ficha = null; cat.crudo = null; cat.crudoAbierto = false;
  // El filtro corre la misma suerte, y por la misma razón: sus conteos y sus opciones se
  // derivaron de la lista anterior. Sobrevivir a la búsqueda lo volvería una preferencia
  // —lo que esta obra tiene prohibido— y haría que la próxima consulta arranque tapada por
  // una decisión que nadie recuerda haber tomado.
  cat.filtro = [];
  if (!cat.consulta.trim()) {
    cat.vista = C.modelarBusqueda("", null);
    return pintarCatalogo();
  }
  const r = await VERBOS.buscarCatalogo(cat.consulta);
  if (gen !== cat.gen) return;                 // llegó tarde: la consulta ya es otra
  cat.vista = C.modelarBusqueda(cat.consulta, r);
  pintarCatalogo();
}

/** ELEGIR UNA PIEZA · corre `validate` y pinta la ficha con la cara que le tocó.
 *
 * ⚠️ EL VEREDICTO SE CORRE AL ELEGIR, NO AL BUSCAR. Validar las veinte filas de una
 * búsqueda son veinte viajes al registro por cada tecla — y diecinueve de ellos sobre
 * piezas que nadie va a mirar. El resolver dejó de adivinar en la sombra justamente para
 * correr acá: cuando hay una decisión que tomar. */
async function elegirPieza(id, { servidor = null } = {}) {
  const cat = ESTADO.catalogo;
  const fila = (cat.vista && cat.vista.filas || []).find((f) => f.id === id);
  if (!fila) return;
  const gen = ++cat.gen;
  // El panel deja de mostrar el viaje —el usuario pidió mirar otra pieza— pero el viaje NO
  // se cancela: `genViaje` queda igual, así que termina, recarga y su llegada se acusa en la
  // franja de arriba. Es lo que la pantalla le prometió: «podés irte, seguimos igual».
  cat.elegida = id; cat.crudo = null; cat.crudoAbierto = false; cat.viaje = null;
  // ⚠️ NO SE PINTA UNA FICHA PROVISORIA. La cara de una ficha SALE del veredicto, y sin
  // veredicto la única cara posible sería «no pudimos comprobarla» — un rojo que parpadea
  // durante medio segundo y que no describe nada. Se pinta que se está comprobando, que es
  // exactamente lo que está pasando, y el click igual se siente porque la fila queda
  // marcada al instante.
  cat.ficha = null; cat.comprobando = fila;
  pintarCatalogo();

  // LO QUE VIAJA ES LA PIEZA + LA INTENCIÓN, en ese orden de importancia. `fila.servidor` es
  // el id de la pieza en el registro: ésa es su identidad y el backend la resuelve por ahí.
  // `cat.consulta` es lo que la persona TECLEÓ, y sirve para una sola cosa —el anti-impostor
  // «buscaste X, elegiste Y»—, nunca para decidir de quién es la pieza.
  //
  // ⚠️ ACÁ IBA `fila.nombre`, que es el TÍTULO que el publicador escribió («CreativeScope —
  // Mobile Game Ad Creative Intelligence»). El registro indexa nombres, no títulos: la ficha
  // le preguntaba por una cadena que el registro no conoce y contestaba «no conozco este
  // servicio» sobre una pieza que la lista de al lado estaba mostrando entera.
  const veredicto = await VERBOS.validarPieza(cat.consulta,
                                              servidor || fila.servidor);
  if (gen !== cat.gen) return;
  cat.comprobando = null;
  cat.ficha = C.modelarFicha(fila, veredicto, { ahora: new Date().toISOString() });
  // EL CRUDO SE PIDE SOLO CUANDO LA FICHA VA A ABRIRLO SOLA. Pedirlo siempre sería una
  // llamada más por pieza mirada, y el manifest de una pieza con sello no aporta nada que
  // el resumen no diga.
  if (cat.ficha.crudoAuto && fila.crudoRef) await pedirCrudo(id, gen);
  pintarCatalogo();
}

/** El ítem crudo del que salió la fila. La fila YA es el modelo derivado; para re-modelarla
 *  con el veredicto hace falta la forma del endpoint, y guardarla es más barato y más
 *  honesto que reconstruirla al revés desde el modelo. */
function _item(fila) { return fila.__item || fila; }

async function pedirCrudo(id, gen) {
  const cat = ESTADO.catalogo;
  const r = await VERBOS.crudoDePieza(id);
  if (gen != null && gen !== cat.gen) return;
  cat.crudo = r ? r.manifest : null;
}

/** EL VIAJE · [Traer] dispara el stream y los pasos se pintan con los EVENTOS REALES.
 *
 * ⚠️ EL VIAJE ES OBSERVACIÓN, NO SUSTITUCIÓN. Los tres pasos son la lectura del stream; lo
 * que decide si la pieza quedó lista o quedó En preparación es `pertenencia()` sobre la
 * fila que el equip escribió — la MISMA función que clasifica a las 41. Por eso al terminar
 * se RECARGA y se deja hablar al clasificador, en vez de que esta capa opine.
 *
 * `gen` corta el pintado si el usuario cancela o se va a otra pieza: el stream puede seguir
 * llegando, pero deja de tener dónde pintarse.
 */
async function correrViaje({ servicio, servidor, credencial = null, traerAsi = false }) {
  const cat = ESTADO.catalogo;
  const gen = ++cat.genViaje;
  const viaje = C.viajeInicial();
  // EL NOMBRE SE CAPTURA AL SALIR, no al llegar. Mientras la pieza viaja, el usuario puede
  // tocar otra fila —el viaje sigue, se lo prometimos— y para entonces `cat.ficha` es otra.
  // Leer el nombre al final anunciaría la llegada de la pieza equivocada.
  const nombre = (cat.ficha || {}).nombre || servidor || servicio || "";
  cat.viaje = viaje;
  pintarCatalogo();

  await VERBOS.traerPieza({ servicio, servidor, credencial, traerAsi }, (ev) => {
    if (gen !== cat.genViaje) return;
    C.reducirViaje(viaje, ev);
    pintarCatalogo();
  });
  if (gen !== cat.genViaje) return viaje;

  if (!C.hayQueRecargar(viaje)) {
    // El viaje se detuvo. NO se recarga ni se limpia nada: el paso culpable, su causa y su
    // botón son lo único que queda en pantalla, y borrarlos sería tragarse el fallo.
    pintarCatalogo();
    return viaje;
  }

  // LLEGÓ. Se relee todo y el clasificador dice dónde quedó la pieza. `barrerLocal` corre
  // igual que al equipar desde cualquier otra puerta: es el mismo verbo de §7.
  const r = await recargar();
  if (gen !== cat.genViaje) return viaje;
  // ¿ATERRIZÓ EN EL LOCAL O EN LA ADUANA? Sale de `pertenencia()`, no de esta capa. Si la
  // pieza no aparece todavía en los modelos, se dice lo conservador —llegó— sin afirmar que
  // está lista, que es lo único que no podemos saber sin la fila.
  const suya = (r.modelos || []).find((m) => m.entityId === viaje.servidor ||
                                             m.nombre === viaje.servidor);
  const escala = suya ? !((suya.pertenencia || {}).local) : viaje.reserva != null;
  // ⚠️ EL VIAJE YA NO SE CIERRA SOLO. Acá había un `cat.viaje = null`: el panel desaparecía
  // en el mismo instante en que la pieza llegaba, y lo único que quedaba era el aviso chico
  // de arriba. El usuario probaba y no sabía si había entrado. El fallo, en cambio, se
  // quedaba en pantalla con su causa y su botón — la asimetría era el defecto.
  // Ahora el éxito termina como el fallo: se queda, dice dónde quedó la pieza, ofrece el
  // camino, y lo cierra el usuario.
  viaje.aterrizaje = {
    nombre,
    entityId: (suya && suya.entityId) || viaje.servidor || null,
    escala,
    // LO QUE FALTA sale de `pertenencia()`, la MISMA función que clasifica a las 41. Esta
    // capa no opina sobre el pendiente: lo transporta.
    faltan: ((suya || {}).pertenencia || {}).faltan || [],
  };
  cat.llegada = { nombre, escala, pasos: viaje.pasos.length };
  pintarCatalogo();
  return viaje;
}

/** CAMBIÓ EL FILTRO · repintar, y que la ficha no quede huérfana.
 *
 * ⚠️ LA DECISIÓN, DECLARADA: si el filtro sacó de la lista la pieza que estaba abierta, la
 * ficha SE CIERRA. Una ficha al lado de una lista que no la contiene no se puede volver a
 * abrir y no se entiende de dónde salió; cerrarla es reversible —se quita el filtro y se
 * toca de nuevo—. Si la pieza sigue visible, la ficha se conserva entera: filtrar no es
 * motivo para perder un veredicto que ya se pagó con una llamada al registro.
 *
 * EL VIAJE NO SE TOCA, igual que al escribir en el buscador: la pieza sigue viajando y su
 * llegada se acusa igual. Eso ya se le prometió al usuario y un chip no lo revoca.
 */
function sincronizarFicha() {
  const cat = ESTADO.catalogo;
  if (cat.elegida) {
    const visible = C.siguenVisibles(C.aplicarFiltro(cat.vista, cat.filtro), cat.elegida);
    if (!visible) { cat.elegida = null; cat.ficha = null; cat.crudo = null; cat.crudoAbierto = false; }
  }
  return pintarCatalogo();
}

/** SEÑALAR UNA PIEZA · que al llegar a la lista se vea CUÁL es, sin buscarla.
 *
 * ⚠️ ES LA MITAD QUE FALTABA DEL CAMINO. Un botón que sólo navega deja al usuario frente a
 * la misma lista de siempre teniendo que adivinar cuál de las cuarenta es la que acaba de
 * traer — que es exactamente el problema que el botón venía a resolver.
 *
 * Se marca la FILA (el `<li>` que contiene su panel: la misma ancla que ya usa `desplegar`,
 * y sirve igual en el local y en la aduana), se la trae a la vista y se le abre el panel
 * cuando tiene un trámite pendiente. La marca es TRANSITORIA —se va sola— porque es un
 * acuse, no un estado: una pieza señalada para siempre se vería distinta de las 41.
 */
export function senalarPieza(entityId) {
  if (!entityId) return;
  // El repintado de la lista es asíncrono respecto de `irA`; se busca en el frame siguiente.
  // `requestAnimationFrame` con respaldo a `setTimeout`: la sección se verifica SIN navegador
  // (ley de la casa — una vara que necesita browser se corre una vez y se abandona) y ahí no
  // existe. Sin el respaldo, señalar reventaba fuera de un navegador real.
  const enElProximoFrame = typeof requestAnimationFrame === "function"
    ? requestAnimationFrame : (fn) => setTimeout(fn, 0);
  enElProximoFrame(() => {
    const host = $(`[data-panel="${CSS.escape(entityId)}"]`, HOSTS.lista) ||
                 (HOSTS.aduana && $(`[data-panel="${CSS.escape(entityId)}"]`, HOSTS.aduana));
    const fila = host && host.closest("li");
    if (!fila) return;   // fallo mudo NO: si no está, no se inventa una marca en otra fila
    fila.setAttribute("data-senalada", "true");
    // TRAERLA A LA VISTA · señalar una fila que quedó fuera de la pantalla no señala nada.
    // Guardado porque no todo host tiene `scrollIntoView` (el DOM mínimo de la vara no), y
    // porque no poder desplazar jamás puede tumbar el acuse: la marca ya está puesta.
    try { fila.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) { /* la marca alcanza */ }
    // El panel se abre SOLO si la pieza tiene algo pendiente: para una que ya está lista,
    // desplegarle el trámite sería ofrecerle trabajo a quien no lo tiene.
    const m = modeloDe(entityId);
    if (m && !((m.pertenencia || {}).local)) desplegar(entityId, "panel", true);
    setTimeout(() => fila.removeAttribute("data-senalada"), 2600);
  });
}

/* ── LOS CLICKS DE LA SECCIÓN · uno por acción, ninguno con un nombre de pieza adentro ── */

async function alClickCatalogo(ev) {
  const t = ev.target.closest("button, a");
  if (!t) return;
  const d = t.dataset || {};
  const cat = ESTADO.catalogo;
  const ficha = cat.ficha;

  if (d.volverConectores) { ev.preventDefault(); return irA("conectores"); }
  // ── EL FILTRO · una lente sobre lo que ya llegó ────────────────────────────────────
  // NO dispara búsqueda: no toca `cat.gen` ni llama a `buscarEnCatalogo`. Repinta, y ya.
  if (d.filtro) {
    ev.preventDefault();
    const r = d.filtro;
    cat.filtro = cat.filtro.includes(r)
      ? cat.filtro.filter((x) => x !== r)   // multi-selección: suma y resta, no reemplaza
      : cat.filtro.concat([r]);
    return sincronizarFicha();
  }
  if (d.filtroLimpiar) {
    ev.preventDefault();
    cat.filtro = [];
    return sincronizarFicha();
  }

  if (d.elegir) { ev.preventDefault(); return elegirPieza(d.elegir); }

  if (d.reintentarBusqueda) {
    ev.preventDefault();
    return conBoton(t, () => buscarEnCatalogo(cat.consulta));
  }
  if (d.revalidar) { ev.preventDefault(); return conBoton(t, () => elegirPieza(d.revalidar)); }

  // EL [?] · pide el crudo de UNA pieza la primera vez y lo pliega después. Nunca de la
  // lista entera: el manifest de veinte piezas para mirar una es la llamada que el endpoint
  // se negó a servir a propósito.
  if (d.crudo) {
    ev.preventDefault();
    cat.crudoAbierto = !cat.crudoAbierto;
    if (cat.crudoAbierto && !cat.crudo) await pedirCrudo(d.crudo, null);
    return pintarCatalogo();
  }
  if (d.noCoincide) {
    ev.preventDefault();
    return conBoton(t, async () => { await VERBOS.noCoincide(cat.consulta); });
  }

  // CONSTRUIR · el camino cuando la pieza no existe. Es la otra mitad del negocio y vive en
  // su propia pantalla; acá sólo se abre la puerta.
  if (d.construir) { ev.preventDefault(); location.href = "inspeccion/inspeccion.html"; return; }

  if (d.cancelarViaje) {
    ev.preventDefault();
    // CANCELAR NO DEJA NADA A MEDIAS, y no porque esta capa limpie: el equip no persiste
    // hasta que la curación pasa. Acá sólo se deja de mirar — y se deja de mirar EL VIAJE,
    // no la búsqueda, que sigue donde estaba.
    cat.genViaje++; cat.viaje = null;
    return pintarCatalogo();
  }

  // CERRAR EL VIAJE TERMINADO · distinto de Cancelar, que aborta uno en curso. Este sólo
  // guarda el acuse: la pieza ya está donde tiene que estar y el usuario decide cuándo
  // dejar de mirarlo. No toca `genViaje` — no hay nada que abortar.
  if (d.cerrarViaje) {
    ev.preventDefault();
    cat.viaje = null;
    return pintarCatalogo();
  }

  // VER LA PIEZA · el camino del éxito. Navega a la lista donde quedó y la SEÑALA: llevar a
  // una lista de cuarenta filas sin decir cuál es la nueva es no llevar a ningún lado.
  if (d.verPieza) {
    ev.preventDefault();
    cat.viaje = null;                 // el viaje cumplió: el usuario se va con su pieza
    ESTADO.senalada = d.verPieza;
    irA("conectores");
    return senalarPieza(d.verPieza);
  }

  if (d.traer) {
    ev.preventDefault();
    if (!ficha) return;
    return conBoton(t, () => correrViaje({
      servicio: cat.consulta, servidor: ficha.servidor,
      traerAsi: d.asi === "true",
    }));
  }
  if (d.traerAsi) {
    ev.preventDefault();
    if (!ficha) return;
    return conBoton(t, () => correrViaje({
      servicio: cat.consulta, servidor: ficha.servidor, traerAsi: true,
    }));
  }
  if (d.traerLaBuena) {
    ev.preventDefault();
    if (!ficha) return;
    // LA VERIFICADA, no la que estaba elegida. Es el punto entero de esta salida: el
    // servidor que se manda es el que el registro señaló como oficial.
    return conBoton(t, () => correrViaje({
      servicio: cat.consulta, servidor: d.traerLaBuena,
    }));
  }
  if (d.reintentarViaje) {
    ev.preventDefault();
    if (!ficha) return;
    return conBoton(t, () => correrViaje({
      servicio: cat.consulta, servidor: ficha.servidor,
      traerAsi: ficha.cara === C.CARA_CON_RESERVAS,
    }));
  }
  if (d.traerConLlave) {
    ev.preventDefault();
    if (!ficha) return;
    const campo = t.closest(".cat-llave") &&
                  t.closest(".cat-llave").querySelector('input[name="cat-llave"]');
    const valor = campo ? String(campo.value || "").trim() : "";
    if (!valor) return;
    if (campo) campo.value = "";
    return conBoton(t, () => correrViaje({
      servicio: cat.consulta, servidor: ficha.servidor, credencial: valor,
    }));
  }
}

/** CAMBIAR DE VISTA · la única puerta, para que entrar por el botón y entrar por la URL
 *  hagan exactamente lo mismo. */
export function irA(vista) {
  ESTADO.vista = vista;
  pintar();
}

/** QUÉ PIEZAS DEPENDEN DE UNA CREDENCIAL. Se deriva de lo que cada belt declara leer, que
 *  es exactamente lo que el assembler resuelve al inyectar: si esta cuenta fuera otra,
 *  sacar una llave dejaría rota una pieza que no estaba en la advertencia. */
function impactoDe(provider) {
  return Array.from(new Set(ESTADO.modelos
    .filter((m) => ((m.conocimiento || {}).credenciales || [])
      .some((c) => c.provider === provider))
    .map((m) => m.nombre || m.entityId)));
}

async function alClickLlavero(ev) {
  const t = ev.target.closest("button");
  if (!t) return;
  const d = t.dataset || {};
  const host = (p) => $(`[data-confirmar="${CSS.escape(p)}"]`, HOSTS.llavero);

  // PRIMER CLICK: SÓLO EL IMPACTO. Ninguna mutación ocurre acá — el usuario ve qué se
  // rompe antes de decidir, que es la mitad que convierte un botón peligroso en una
  // decisión informada.
  if (d.sacar) {
    ev.preventDefault();
    const h = host(d.sacar);
    if (h) { h.innerHTML = S.pintarConfirmarSacar(d.sacar, impactoDe(d.sacar)); h.hidden = false; }
    return;
  }
  if (d.sacarNo) {
    ev.preventDefault();
    const h = host(d.sacarNo);
    if (h) { h.hidden = true; h.innerHTML = ""; }
    return;
  }
  if (d.sacarOk) {
    ev.preventDefault();
    return conBoton(t, async () => {
      await VERBOS.sacarLlave(d.sacarOk);
      // Y SE VUELVE A DERIVAR TODO. Sacar una llave cambia el veredicto de cada pieza que
      // la usaba, y esas piezas están en la otra vista: parchear sólo el llavero dejaría
      // media pantalla mintiendo hasta la próxima carga.
      ESTADO.midiendo.clear();
      await recargar();
    });
  }
}

/** LO INTERNO SE ARREGLA SOLO.
 *
 * Las piezas que el sistema todavía no midió —o cuyo veredicto una regla marcó para
 * re-medir— NO generan un botón. Generan trabajo NUESTRO: se dispara la medición en
 * background y, cuando vuelve, la card pinta el resultado real. El usuario no se entera de
 * que faltaba medir; se entera del resultado.
 *
 * Tres cuidados, los tres por un modo de fallo concreto:
 *   · UNA VEZ POR CARGA (`midiendo`): si no, es un loop que nunca converge;
 *   · SILENCIOSO: si la medición falla, la card queda como estaba. Un error de NUESTRA
 *     medición no puede convertirse en un rojo sobre la conexión del usuario;
 *   · SIN BLOQUEAR: no se espera. La pantalla ya está pintada con lo último que se sabe.
 */
function medirLoQueFalta() {
  const pendientes = ESTADO.modelos
    .filter((m) => !m.apagada && F.hayQueMedir(m) && !ESTADO.midiendo.has(m.entityId));
  if (!pendientes.length) return;
  for (const m of pendientes) ESTADO.midiendo.add(m.entityId);
  Promise.all(pendientes.map((m) => VERBOS.medir(m.entityId)))
    .then((res) => { if (res.some(Boolean)) recargarSilencioso(); })
    .catch(() => { /* silencioso a propósito: ver docstring */ });
}

/** Recarga que NO vuelve a disparar mediciones: evita el loop que `midiendo` ya acota, y
 *  lo evita por construcción en vez de por contador. */
async function recargarSilencioso() {
  const r = await VERBOS.cargar();
  ESTADO.modelos = r.modelos;
  ESTADO.vault = r.vault || {};
  ESTADO.leido = r.leido;
  pintar();
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * LOS CLICKS · uno por acción, todos delegados, ninguno con un nombre de conector adentro.
 * ════════════════════════════════════════════════════════════════════════════════════ */

async function conBoton(boton, trabajo) {
  // Un botón que no cambia al apretarlo se ve como uno que no funcionó, y el usuario lo
  // aprieta otra vez. Se deshabilita mientras dura y vuelve solo — incluso si el trabajo
  // revienta, que es justo cuando más importa que el botón vuelva.
  const antes = boton.textContent;
  boton.disabled = true;
  boton.dataset.trabajando = "true";
  try { return await trabajo(); }
  finally {
    boton.disabled = false;
    delete boton.dataset.trabajando;
    boton.textContent = antes;
  }
}

async function alClick(ev) {
  const t = ev.target.closest("button, a");
  if (!t) return;
  const d = t.dataset || {};

  // ABRIR LA FILA · el [?] es el gesto uniforme, y está en TODA card. Es el camino a las
  // acciones operativas: sin él, [Desconectar] y [Rotar llave] existían en el código y
  // ningún click de la app instalada llegaba a ellos.
  if (d.detalle) { ev.preventDefault(); return desplegar(d.detalle, "detalle"); }

  // TODA ACCIÓN DE LA CARD ABRE EL PANEL. El botón de repair dice CUÁL es la salida; el
  // trámite ocurre inline, donde el usuario está. No hay modal que tape la lista ni
  // pantalla a la que navegar y de la que volver — que era el wizard, y por eso murió.
  if (d.accion && d.entity) { ev.preventDefault(); return desplegar(d.entity, "panel"); }

  // ══ EL ÚNICO BOTÓN DE UNA CARD ROJA ══════════════════════════════════════════════
  //
  // Relanza el ciclo completo y la card se repinta con EL RESULTADO REAL — verde, amarillo
  // o el mismo rojo. Que pueda volver el mismo rojo no es un fallo del botón: es la
  // respuesta honesta, y el [?] dice qué se intentó. Lo que no puede pasar es que no pase
  // nada, y por eso se recarga siempre, incluso cuando el reintento falló.
  if (d.reintentar) {
    ev.preventDefault();
    return conBoton(t, () => correrChecklist(d.reintentar, async () => {
      // Se limpia la marca de «ya lo estoy midiendo»: el usuario pidió una medición nueva
      // y el acumulador de la carga no puede tragársela.
      ESTADO.midiendo.delete(d.reintentar);
      await VERBOS.reintentarConexion(d.reintentar);
    }));
  }

  // [Rotar llave] · el mismo campo inline de siempre. Rotar ES pegar otra llave: darle un
  // flujo propio sería construir por segunda vez algo que ya existe.
  if (d.rotar) { ev.preventDefault(); return desplegar(d.rotar, "panel"); }

  if (d.reconectar) {
    ev.preventDefault();
    return conBoton(t, () => correrChecklist(d.reconectar, async () => {
      await VERBOS.reconectar(d.reconectar);
      ESTADO.midiendo.delete(d.reconectar);
    }));
  }

  if (!d.entity) return;
  const entity = d.entity;

  if (t.classList.contains("cx-guardar")) {
    ev.preventDefault();
    // [Guardar y probar] también muestra los verbos: «y probar» es una promesa, y una
    // promesa que ocurre detrás de un spinner mudo no se puede distinguir de una que no
    // ocurrió. Se guarda primero (sin eso no hay nada que probar) y después se mira.
    return conBoton(t, async () => {
      await guardarSolo(entity, t);
      return correrChecklist(entity, async () => {
        ESTADO.midiendo.delete(entity);
        await VERBOS.medir(entity);
      });
    });
  }
  if (t.classList.contains("cx-verificar")) {
    ev.preventDefault();
    // [Ya lo instalé · verificar] es el ÚNICO botón que dispara una medición a pedido, y es
    // legítimo: sólo el usuario sabe cuándo terminó de instalar. Todo lo demás lo mide el
    // sistema solo.
    return conBoton(t, async () => {
      ESTADO.midiendo.delete(entity);
      await VERBOS.medir(entity);
      await recargar();
    });
  }
  if (t.classList.contains("cx-autorizar")) {
    ev.preventDefault();
    // OAuth sale del navegador y vuelve: el consentimiento pasa en el sitio del proveedor, y
    // así tiene que ser. Lo que cambia es que la URL se PIDE — esta línea hacía
    // `location.href` a una ruta POST y mandaba a un 404. Ver `fuentes.empezarOauth`.
    return conBoton(t, async () => {
      const r = await VERBOS.empezarOauth(entity);
      if (r.url) { location.href = r.url; return; }
      // FALLO VISIBLE, JAMÁS MUDO: si no hay URL hay motivo, y el motivo se muestra.
      alert(r.motivo || `No se pudo iniciar la autorización (HTTP ${r.http}).`);
    });
  }
  if (t.classList.contains("cx-desconectar")) {
    ev.preventDefault();
    return conBoton(t, async () => {
      await VERBOS.desconectar(entity);
      await recargar();
    });
  }
}

/** GUARDAR Y PROBAR · un solo botón para las dos cosas, y por eso se llama así.
 *
 * ⚠️ EL BUG QUE LO PIDIÓ: el usuario pegaba la llave, la guardaba, y arriba seguía diciendo
 * lo de antes. `verify` corre acá mismo, sin que nadie lo apriete, y el modelo se vuelve a
 * derivar entero. Un header viejo sobreviviendo a una credencial nueva es imposible: no hay
 * header cacheado que pueda sobrevivir a nada.
 */
export async function guardar(entity, boton) {
  await guardarSolo(entity, boton);
  ESTADO.midiendo.delete(entity);
  await VERBOS.medir(entity);
  return recargar();
}

/** Sólo la mitad de GUARDAR. Separada para que el checklist pueda mirar la mitad de PROBAR
 *  —que es la que tarda y la que puede fallar— sin volver a guardar la llave. */
export async function guardarSolo(entity, boton) {
  const panel = boton.closest(".cx-panel");
  const modelo = modeloDe(entity);
  if (!panel || !modelo) return;

  // BAJO QUÉ PROVIDER SE GUARDA lo dice el adaptador, no esta capa: sale de resolver la
  // variable que el belt declara contra los alias del catálogo. Guardarla bajo el nombre de
  // la entidad es lo que hacía que el assembler después no la encontrara.
  const credenciales = (modelo.conocimiento || {}).credenciales || [];
  const inputs = Array.from(panel.querySelectorAll('input[name]'));
  let alguna = false;
  for (const input of inputs) {
    const valor = String(input.value || "").trim();
    if (!valor) continue;
    const cred = credenciales.find((c) => c.variable === input.name) || credenciales[0];
    const provider = (cred && cred.provider) || entity;
    const r = await VERBOS.guardarLlave(provider, valor);
    alguna = alguna || !!(r && (r.guardada || r.ok));
    input.value = "";
  }
  return alguna;
}

/** EL CSS DEL PANEL, UNA VEZ POR DOCUMENTO. Viaja con la superficie porque el panel se abre
 *  en más de una pantalla; si cada una trajera su copia, el mismo panel se vería distinto
 *  según desde dónde se lo abriera. */
export function inyectarCSS(doc = document) {
  if (doc.getElementById("cx-superficie-css")) return;
  const el = doc.createElement("style");
  el.id = "cx-superficie-css";
  // El del panel y el de la sección viajan juntos y por el mismo motivo: los dos se pintan
  // en más de una pantalla, y una copia por pantalla es cómo la misma cosa termina
  // viéndose distinta según desde dónde se la abra.
  el.textContent = S.CSS_PANEL + SC.CSS_CATALOGO;
  (doc.head || doc.documentElement).appendChild(el);
}

/** ABRIR EL PANEL ANCLADO A UN BOTÓN · la superficie del adaptador, fuera de su pantalla.
 *
 * ⚠️ ESTA FUNCIÓN ES «EL ADAPTADOR EN TODAS LAS SUPERFICIES», hecha código. El Cuarto tenía
 * su propia puerta a la reparación —`cuarto.semaforo.abrirWorkflow`, que cargaba el wizard
 * de 2873 líneas— y por eso una pieza rota se veía y se arreglaba distinto según desde
 * dónde la miraras. Ahora esa puerta llega acá: **la misma pieza, el mismo panel, los
 * mismos pasos derivados**, esté donde esté el usuario.
 *
 * Y sigue sin sacar a nadie de donde está, que era la única virtud del wizard: el panel
 * flota junto al botón que lo abrió. Lo único que todavía saca del Cuarto es OAuth, porque
 * el consentimiento ocurre en el sitio del proveedor y así tiene que ser.
 */
export async function abrirAnclado({ entityId, ancla }) {
  if (!entityId) return false;
  inyectarCSS();
  if (!ESTADO.modelos.length) {
    const r = await VERBOS.cargar();
    ESTADO.modelos = r.modelos; ESTADO.vault = r.vault || {}; ESTADO.leido = r.leido;
  }
  const modelo = modeloDe(entityId);
  // FALLO HONESTO: sin modelo no se abre un panel vacío. El caller (el Cuarto) tiene su
  // camino viejo para ese caso, y un panel en blanco sería peor que no abrirlo.
  if (!modelo) return false;

  cerrarAnclado();
  const caja = document.createElement("div");
  caja.className = "cx-anclado";
  caja.dataset.entity = entityId;
  caja.innerHTML = S.pintarAnclado(modelo);
  document.body.appendChild(caja);

  const r = ancla && ancla.getBoundingClientRect ? ancla.getBoundingClientRect() : null;
  if (r) {
    caja.style.top = `${window.scrollY + r.bottom + 8}px`;
    caja.style.left = `${Math.max(8, Math.min(window.scrollX + r.left,
      window.scrollX + window.innerWidth - caja.offsetWidth - 8))}px`;
  } else {
    caja.style.top = `${window.scrollY + 80}px`;
    caja.style.left = "50%";
    caja.style.transform = "translateX(-50%)";
  }
  // LOS MISMOS HANDLERS. No hay una segunda tabla de clicks para el panel anclado: si la
  // hubiera, [Guardar y probar] podría hacer una cosa en Conectores y otra en el Cuarto.
  caja.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-cerrar-anclado]")) { ev.preventDefault(); return cerrarAnclado(); }
    return alClick(ev);
  });
  return true;
}

export function cerrarAnclado() {
  for (const el of document.querySelectorAll(".cx-anclado")) el.remove();
}

/** MONTAR · engancha la superficie a los nodos que le da la pantalla. */
export async function montar(hosts) {
  HOSTS = hosts;
  inyectarCSS();
  if (HOSTS.recoFilas && HOSTS.recoSelector) {
    RECO = montarRecomendados({
      selector: HOSTS.recoSelector, filas: HOSTS.recoFilas,
      conteo: HOSTS.recoConteo, ambito: HOSTS.recoAmbito,
      listaAFilas: HOSTS.listaAFilas, listaAConteo: HOSTS.listaAConteo,
      aviso: HOSTS.recoAviso,
    });
  }
  if (HOSTS.lista) HOSTS.lista.addEventListener("click", alClick);
  if (HOSTS.aduana) HOSTS.aduana.addEventListener("click", alClick);
  if (HOSTS.llavero) HOSTS.llavero.addEventListener("click", alClickLlavero);
  for (const [tab, vista] of [[HOSTS.tabConectores, "conectores"],
                              [HOSTS.tabReco, "recomendados"],
                              [HOSTS.tabLlavero, "llavero"]])
    if (tab) tab.addEventListener("click", () => irA(vista));
  // LA CUARTA VISTA SE PINTA AL ABRIRSE, no al montarse: su lista cuesta dos llamadas y
  // pagarlas en el arranque es cobrarle a todos los que nunca abren esa pestaña.
  if (RECO && HOSTS.tabReco) HOSTS.tabReco.addEventListener("click", () => RECO.ir());
  // Y LA SESIÓN, que es local-first: `ensureLocal()` pide `POST /v1/auth/local` (identidad de
  // ESTE equipo, sin cuenta y sin red externa). Sin esto `tiene_llave` viaja en `null` para
  // siempre y el botón de poner la llave no aparece nunca.
  if (RECO) {
    (async () => {
      let u = null;
      try {
        const A = window.AlephSession;
        u = (A && A.ensureLocal) ? await A.ensureLocal() : (A && A.get ? A.get() : null);
      } catch (_) { u = null; }
      RECO.sesion(u);
    })();
  }
  // ── LA SECCIÓN PÚBLICA ────────────────────────────────────────────────────────────
  // La entrada es UN CLICK desde «Tus conectores», y la salida es el «←» de la sección.
  // Nada de esto navega: es la misma pantalla cambiando de vista, así que volver no pierde
  // ni la búsqueda ni el viaje en curso.
  if (HOSTS.entradaCatalogo)
    HOSTS.entradaCatalogo.addEventListener("click", (ev) => { ev.preventDefault(); irA("catalogo"); });
  if (HOSTS.panelCatalogo) HOSTS.panelCatalogo.addEventListener("click", alClickCatalogo);
  // ── LA CUARTA VISTA · sus clicks se atan ACÁ, como los de las otras tres ────────────
  // La vista de Recomendados se ataba sola: tenía sus propios `addEventListener` adentro.
  // Cumplía la delegación (uno por host) pero en el piso equivocado — dos lugares que
  // deciden qué hace un click es cómo el mismo botón termina haciendo cosas distintas
  // según qué archivo se tocó último. Ella dice QUÉ pasa; acá se dice DÓNDE se escucha.
  if (RECO && HOSTS.recoFilas) {
    HOSTS.recoFilas.addEventListener("click", RECO.alClick);
    HOSTS.recoFilas.addEventListener("submit", RECO.alSubmit);
  }
  if (RECO && HOSTS.recoSelector)
    HOSTS.recoSelector.addEventListener("change", RECO.alCambiarEspacio);
  if (HOSTS.catalogoBuscador) {
    let temporizador = null;
    HOSTS.catalogoBuscador.addEventListener("input", () => {
      const v = HOSTS.catalogoBuscador.value;
      // DEBOUNCE, porque cada tecla es un viaje al registro público. Sin esto, escribir
      // «notion» son seis búsquedas de las que cinco se descartan — y seis veces que
      // martillamos un servicio que no es nuestro.
      if (temporizador) clearTimeout(temporizador);
      temporizador = setTimeout(() => buscarEnCatalogo(v), 300);
    });
  }
  if (HOSTS.buscador) {
    try { ESTADO.q = new URLSearchParams(location.search).get("q") || ""; } catch (_) {}
    HOSTS.buscador.value = ESTADO.q;
    HOSTS.buscador.addEventListener("input", () => {
      ESTADO.q = HOSTS.buscador.value;
      pintar();
    });
  }
  // El idioma y las marcas repintan: son piel, no estado. Repintar es barato porque los
  // modelos ya están derivados — no se vuelve a leer nada.
  window.addEventListener("aleph:lang", pintar);
  window.addEventListener("aleph:brands", pintar);
  pintar();
  const r = await recargar();
  // §7 · LA PERTENENCIA CADUCA. Se pinta primero con lo último que se sabe —abrir no puede
  // esperar 42 spawns— y el barrido corre por detrás; cuando vuelve, la pantalla se repinta
  // con la verdad re-medida. Es el mismo verbo que dispara el sidecar al arrancar.
  VERBOS.barrerLocal().then((ok) => { if (ok) recargarSilencioso(); }).catch(() => {});
  return r;
}

if (typeof window !== "undefined") {
  // La puerta para la vara y para el resto de la casa. Cero estado propio adentro: son
  // punteros a lo mismo que usa la pantalla, así que no puede desincronizarse.
  window.__conectores = {
    ESTADO, recargar, montar, irA,
    modelos: () => ESTADO.modelos,
    abrir: (id) => desplegar(id, "panel", true),
    // LA PUERTA DE LA SECCIÓN, para el resto de la casa. El Cuarto la usa para mandar a
    // alguien al catálogo con una búsqueda ya escrita, en vez de tener su propio panel.
    catalogo: (consulta) => {
      irA("catalogo");
      if (HOSTS && HOSTS.catalogoBuscador) HOSTS.catalogoBuscador.value = consulta || "";
      return buscarEnCatalogo(consulta || "");
    },
  };
}
