/* espacios-tabla.js — LOS SEIS ESPACIOS Y SU NOMBRE. Seis strings, cero dependencias.
 *
 * POR QUÉ EXISTE ESTE ARCHIVO. La tabla vivía adentro de `conectores/recomendados.js`, que
 * es donde nació. Ahí estaba bien mientras sus dos lectores fueran del subsistema de
 * conectores. Dejó de estarlo cuando la necesitó el ⚙ de Ajustes, que corre en 26 pantallas:
 * importar `recomendados.js` arrastra `widget.js`, `fuentes.js`, `recomendaciones.js`,
 * `superficie-catalogo.js` y el semáforo del Cuarto —casi mil líneas y una cadena de red—
 * para leer seis strings.
 *
 * Así que la tabla sale a su propia casa y **los llamadores de antes la siguen usando por
 * donde la usaban**: `recomendados.js` la re-exporta y `espacios.js` la re-exporta. Nadie
 * cambia sus imports; lo que cambia es que ahora hay UNA copia y no tres.
 *
 * EL VOCABULARIO, decidido por el dueño (2026-08-18): los rótulos son `GENERAL` y el nombre
 * del espacio A SECAS. No «TODA LA CASA», no «SÓLO <X>». Cierra el empate que
 * `qa/DEUDA-ROTULOS-DE-AMBITO.md` dejó nombrado: dos juegos de rótulos para el mismo
 * concepto, que el usuario leía en la misma sesión.
 *
 * ⚠️ EL ORDEN DE LAS CLAVES ES EL ORDEN DE LA CASA y se usa para pintar los chips. No se
 * alfabetiza: `Object.keys` lo respeta y hay vistas que dependen de que las dos coincidan.
 */

export const ORDEN_ETIQUETA = {
  ciencia: "Ciencia", oficina: "Oficina", legal: "Legal",
  educacion: "Educación", diseno: "Diseño", finanzas: "Finanzas",
};

/** El id que significa «sin filtro». No es un workspace: es su ausencia. */
export const GENERAL = "general";

/** El nombre humano de un espacio; el propio id si no es de los seis.
 *  Es lo que impide que en pantalla se lea `DISENO` o `EDUCACION`. */
export function etiqueta(id) {
  if (!id || id === GENERAL) return "GENERAL";
  if (ORDEN_ETIQUETA[id] && typeof window !== "undefined" && window.AlephI18n) {
    const key = `ws.${id}.nombre`, label = window.AlephI18n.t(key);
    if (label && label !== key) return label;
  }
  return ORDEN_ETIQUETA[id] || id;
}

/** `[{id, label}]` — GENERAL primero, después los seis en el orden de la casa. */
export function espacios() {
  return [{ id: GENERAL, label: "GENERAL" }].concat(
    Object.keys(ORDEN_ETIQUETA).map((id) => ({ id, label: etiqueta(id) })));
}

/* ── LAS SECCIONES DE CADA ESPACIO ─────────────────────────────────────────────────────
 * [integración · el Settings del diseño]
 *
 * DE DÓNDE SALE ESTA TABLA. De `Aleph Settings.dc.html`, artboard 13a, del proyecto de
 * Claude Design del dueño — no de lo que el árbol tenía. El artboard dibuja un solo Settings
 * con GENERAL arriba y DESPUÉS la sección de cada espacio con sus filas, todas a la vez. Lo
 * que había era una tarjeta «Sin ajustes propios» para los cinco espacios de los que no
 * venías, incluidos Legal y Oficina, que SÍ tienen ajustes. Eso era mentira en pantalla.
 *
 * QUÉ HACE CADA FILA, decidido por el dueño: te lleva al espacio, parado en esa superficie.
 * No se reconstruye el panel de otro adentro de la casa —eso es la Ley 6— y no se inventa un
 * contrato nuevo: se usa el ruteo que cada stack YA tiene, y la casa lo manda por la URL del
 * iframe, que es el mismo camino por el que ya viajan el tema, el idioma y el chat.
 *
 *   `ruta`   el stack es un router y la superficie tiene URL propia. Medido:
 *            Finanzas  `router.tsx:52-65`  · Educación  `app/(workspace)` y `app/(utility)`
 *   `panel`  el stack abre su ajuste en un DIÁLOGO, no en una ruta. Es el caso de Ciencia
 *            (`components/dialog-settings.tsx` sobre `settings/registry.ts`), y por eso su
 *            fila manda un id de panel y no un path.
 *
 * ⚠️ LO QUE EL ARTBOARD DIBUJA Y NO ESTÁ, SE DICE, NO SE FINGE. `Permissions` y `Storage`
 * aparecen en las tres secciones del artboard y NINGUNO de los tres stacks tiene una
 * superficie con ese nombre —salvo `permissions` en Ciencia, que sí existe y por eso está—.
 * Una fila que no puede llevarte a ningún lado es la puerta a ningún lado que este rediseño
 * vino a sacar: no se dibujan, y acá queda escrito por qué.
 *
 * ⚠️ LEGAL NO ESTÁ ACÁ Y ESO ES CORRECTO. Sus ajustes son PERILLAS de verdad —Drafting con
 * Postura, Formalidad y Detalle, más Research— y ya viven anidadas adentro de nuestro
 * Settings, que es lo que pide su artboard 38b. Una segunda entrada acá sería el mismo
 * ajuste en dos lugares.
 *
 * ⚠️ OFICINA Y DISEÑO VAN VACÍOS A PROPÓSITO. El artboard 13a dibuja para Oficina la tarjeta
 * punteada con su copy («no agrega nada al bloque general; la sección existe igual para que
 * la página no cambie de forma») y a Diseño no lo dibuja. La sección se pinta igual: es el
 * artboard el que pide que la página no cambie de forma. */
export const SECCIONES = {
  ciencia: [
    { id: "skills",      rotulo: "Skills",       panel: "skills" },
    { id: "specialists", rotulo: "Specialists",  panel: "specialists" },
    { id: "compute",     rotulo: "Compute",      panel: "compute" },
    { id: "sandbox",     rotulo: "Sandbox",      panel: "sandbox" },
    { id: "permissions", rotulo: "Permissions",  panel: "permissions" },
  ],
  educacion: [
    { id: "knowledge", rotulo: "Knowledge Base",  ruta: "/knowledge" },
    { id: "cowriter",  rotulo: "Co-Writer",       ruta: "/co-writer" },
    { id: "space",     rotulo: "Learning Space",  ruta: "/space" },
  ],
  oficina: [],
  finanzas: [
    { id: "agent",       rotulo: "Agent",              ruta: "/agent" },
    { id: "runtime",     rotulo: "Runtime",            ruta: "/runtime" },
    { id: "scheduled",   rotulo: "Scheduled",          ruta: "/scheduled" },
    { id: "reports",     rotulo: "Reports",            ruta: "/reports" },
    { id: "alphazoo",    rotulo: "Alpha Zoo",          ruta: "/alpha-zoo" },
    { id: "correlation", rotulo: "Correlation Matrix", ruta: "/correlation" },
  ],
  /* ⚠️ LEGAL ES EL CASO RARO Y POR ESO SUS FILAS APUNTAN ACÁ ADENTRO. Sus ajustes NO son
   * superficies de su stack: son PERILLAS de verdad, del almacén de la casa, y ya se dibujan
   * anidadas —Drafting con Postura, Formalidad y Detalle, más Research— tal como pide su
   * artboard 38b. Pero ese bloque sólo se arma cuando venís DE Legal, así que abriendo Ajustes
   * desde el riel su grupo caía en la tarjeta «Sin ajustes propios»: mentira en pantalla, y es
   * lo que el dueño vio.
   * Estas dos filas te llevan a su sección, abierta. `aqui` significa «no salgas de Ajustes,
   * cambiá el ámbito» — es la misma pantalla, no el workspace. */
  legal: [
    { id: "drafting", rotulo: "Drafting", aqui: "?espacio=legal" },
    { id: "research", rotulo: "Research", aqui: "?espacio=legal" },
  ],
  diseno: [],
};

/** Las secciones de un espacio, o `[]` si no tiene. Nunca `undefined`: quien pinta no
 *  tiene que preguntar dos veces. */
export function secciones(ws) {
  return (SECCIONES[ws] || []).map(sec => {
    const key = `set.section.${ws}.${sec.id}`;
    const t = typeof window !== "undefined" && window.AlephI18n && window.AlephI18n.t;
    const label = t ? t(key) : "";
    return { ...sec, rotulo: label && label !== key ? label : sec.rotulo };
  });
}

/** El destino de una fila, como la casa lo manda en la URL del workspace.
 *  Devuelve `""` cuando la fila no lleva a ningún lado — que hoy no pasa, porque las que no
 *  tienen destino no entran en la tabla. */
export function destinoDeSeccion(sec) {
  if (!sec) return "";
  if (sec.ruta)  return "ir=" + encodeURIComponent(sec.ruta);
  if (sec.panel) return "panel=" + encodeURIComponent(sec.panel);
  return "";
}

/** El `href` completo de una fila. Dos formas, y la de `aqui` no sale de Ajustes. */
export function hrefDeSeccion(ws, sec) {
  if (sec && sec.aqui) return "Settings.dc.html" + sec.aqui;
  var d = destinoDeSeccion(sec);
  return "workspaces/" + ws + ".html" + (d ? "?" + d : "");
}
