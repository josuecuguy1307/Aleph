/* piel.js — QUÉ VERSIÓN DE LA PIEL LE MANDA LA CASA A LOS STACKS.
 * [rediseño · fase 1 · cable de seguridad (b) · la mitad de ACÁ]
 *
 * La otra mitad vive en `third_party/<stack>/…/public/aleph-piel.js`, byte-idéntica en los
 * seis. Ésta es la que DECIDE; aquélla la que APLICA.
 *
 * POR QUÉ EXISTE. Todo lo que la fase 3 le pinte a un stack ajeno viaja adentro de un
 * `dist` horneado, así que volver atrás costaría un build por stack (el árbol de Legal solo
 * pesa 1,6 GB adentro de la `.app`). Con este interruptor, apagar el rediseño entero es
 * cambiar una palabra y recargar. La hoja igual viaja: lo que cambia es si se aplica.
 *
 * DE DÓNDE SALE EL VALOR, en este orden y con motivo:
 *
 *   1. `?piel=v2` en la URL de la casa — y se RECUERDA. Es el camino del que está
 *      trabajando en el rediseño: se prende una vez y sigue prendido al navegar entre
 *      pantallas, sin arrastrar la query a mano.
 *   2. `localStorage['aleph-piel']` — lo que se recordó.
 *   3. nada ⇒ **apagado**. El default es el producto como está hoy, que es lo único seguro.
 *
 * ⚠️ `?piel=off` APAGA Y SE ACUERDA DE QUE APAGÓ. Un interruptor que sólo prende no es un
 * interruptor: si la única forma de volver atrás fuera limpiar el `localStorage` a mano, el
 * «apagado instantáneo» sería mentira justo el día que haga falta. Guarda la palabra `off`
 * —no borra la clave— porque con el default por espacio «nada guardado» significa «prendido
 * si a tu espacio le toca», que es lo contrario de lo que se pidió.
 *
 * ⚠️ POR QUÉ `localStorage` Y NO EL ALMACÉN DE AJUSTES. El almacén de la casa
 * (`memoria.py:AJUSTES`) tiene vocabulario CERRADO y resuelve por `(dueño, ámbito)`: meter
 * una clave ahí es declarar un ajuste de producto, con su fila en Settings y su lector. La
 * piel todavía no es un ajuste del usuario — es una palanca de obra. El día que el rediseño
 * se dé por terminado, esta palanca se BORRA; no se promueve a preferencia. Mientras tanto
 * es de instalación a propósito, y eso está bien para lo que es.
 */
(function (root) {
  "use strict";
  var CLAVE = "aleph-piel";
  var VALIDA = /^v[0-9]+$/;

  /** Qué espacio es esta pantalla, si es la de un workspace. Sale del `<html data-aleph-ws>`
   *  que las seis pantallas escriben, y si no, del nombre del archivo. Nunca adivina: sin
   *  ninguna de las dos señales devuelve vacío y manda sólo la palanca manual.
   *
   *  ⚠️ POR QUÉ HACE FALTA. `version()` y `query()` reciben el espacio de quien las llama, y
   *  hay llamadas viejas que no se lo pasan. Sin esto, ésas caen a «apagado» aunque el
   *  espacio esté en la tabla — un default por espacio que depende de que nadie se olvide de
   *  un argumento no es un default. */
  function espacioDeLaPantalla() {
    try {
      var marcado = document.documentElement.getAttribute("data-aleph-ws");
      if (marcado) return marcado;
      var m = /\/workspaces\/([a-z]+)\.html/i.exec(location.pathname || "");
      return m ? m[1].toLowerCase() : "";
    } catch (e) { return ""; }
  }

  function guardado() {
    try { return localStorage.getItem(CLAVE) || ""; } catch (e) { return ""; }
  }

  /* ── EL DEFAULT ES POR ESPACIO, Y ESO ES LO QUE CAMBIÓ ────────────────────────────
   * Antes el default era uno solo —apagado— y la única forma de encender era `?piel=v2`,
   * que se recuerda en `localStorage`. Eso tiene un agujero que costó una tanda entera:
   * quien verifica en un navegador con la query puesta ve el frame, y la `.app` —que tiene
   * su propio `localStorage`, vacío— lo tiene apagado. Se certificó una pantalla que el
   * usuario no estaba viendo.
   *
   * Ahora cada espacio trae su propio default. Se enciende ESPACIO POR ESPACIO, a medida que
   * su fase se termina y se revisa, en vez de prender los seis de una: Ciencia, por ejemplo,
   * tiene la hoja de piel pero NO tiene el shell (`aleph-frame`), así que encenderla hoy le
   * daría media cara. La palanca manual sigue mandando por encima de la tabla —`?piel=v2`
   * enciende cualquiera, `?piel=off` apaga todo— porque sirve para mirar lo que todavía no
   * está listo. */
  var POR_ESPACIO = {
    finanzas: "v2",   // fase FINANZAS · shell, barrita, pantallas sueltas y Settings, revisados
    oficina:  "v2",   // fase OFICINA  · shell (riel borrado), barrita al mockup y saludo, medidos
    diseno:   "v2",   /* fase DISEÑO · la barra horizontal pasó al riel (`AlephRail.tsx`), las
     * tres pastillas se cayeron —idioma y tema a Appearance, con el idioma CRUZANDO por
     * `?aleph_lang`— y la barrita quedó a la pieza 07. Medido en el lienzo real a 1440, con
     * el frame puesto: riel de 260 en #f7f6f4 con hairline #e8e6e2, filas en 10/22, grupo
     * DISEÑO en mono con tracking .11em, activo en tarjeta blanca e índigo, pie con Settings
     * y la cuenta; la barrita en radio 22 con clip y dos palitos de 34/10, enviar en círculo
     * negro de 38 y la línea «Enter para enviar». Oscuro medido: todo por token, cero hex. */
    /* fase CIENCIA · el shell ya no falta: `openscience` no tenía `aleph-frame` —era el único
     * de los seis— y esta fase lo escribió (`frontend/workspace/src/pages/aleph-frame.tsx`).
     * Medido contra el artboard 3a en el dist de dev: barra de 260 en #f7f6f4 sobre lienzo
     * #f4f3f1, el bloque estándar, Terminal y Compute promovidos, el pie con la cuenta, sin
     * barra de arriba y sin tira de tabs; la barrita con clip, dos palitos, chip y enviar en
     * sus medidas. Vara: `e2e/aleph-frame.spec.ts`, 7 casos, y mide las dos caras.
     * ⚠️ FALTA LA CERTIFICACIÓN CONTRA LA `.app` INSTALADA. Este commit va SEPARADO justamente
     * para eso: si el dueño prefiere esperar al build, se descarta este commit y el resto de
     * la fase entra igual. */
    ciencia:  "v2",
    /* fase EDUCACIÓN · su fase entró en `ecb70f4f` (19:55) y fase LEGAL en `a6385a65` (20:44).
     * La línea que decía «educacion · legal: pendientes» la escribió Diseño a las 20:34 —o sea
     * ANTES de que Legal entrara— y nadie volvió a tocarla: los dos espacios quedaron con la
     * cara vieja de default teniendo su frame entero en el árbol. Es exactamente el agujero
     * que el comentario de arriba describe, en su otra dirección: el default no se enciende
     * solo, y una fase que termina y no vuelve acá no llega al usuario.
     * Contado sobre el árbol antes de prenderlos, los dos tienen las cinco piezas:
     * `AlephFrameHeader`, `AlephFrameFooter`, `aleph-go-home`, `aleph-open-settings` y —desde
     * la sesión de integración— el censo del pie y la fila de la cuenta. */
    educacion: "v2",
    legal:     "v2",
  };

  /** La versión de piel vigente para un espacio: `"v2"` o `""` (apagada).
   *  @param ws  el id del workspace. Sin id, sólo cuenta la palanca manual. */
  function version(ws) {
    var q = "";
    try { q = new URLSearchParams(location.search).get("piel") || ""; } catch (e) {}
    /* ⚠️ APAGAR ES GUARDAR «off», NO BORRAR LA CLAVE. Con el default apagado, borrar
     * alcanzaba: sin nada guardado, la piel quedaba apagada. Con el default POR ESPACIO ya
     * no: al no quedar nada, la recarga siguiente vuelve a caer en `POR_ESPACIO[ws]` y el
     * espacio se PRENDE SOLO otra vez. El apagado de emergencia duraba una pantalla, justo
     * el día que haga falta apagar. Lo encontró la sesión del frame de Oficina, que llegó a
     * este mismo archivo por su lado; el arreglo es suyo. */
    if (q === "off" || q === "0") {
      try { localStorage.setItem(CLAVE, "off"); } catch (e) {}
      return "";
    }
    if (VALIDA.test(q)) {
      try { localStorage.setItem(CLAVE, q); } catch (e) {}
      return q;
    }
    var g = guardado();
    if (g === "off") return "";
    if (VALIDA.test(g)) return g;
    var esp = ws || espacioDeLaPantalla();
    return (esp && POR_ESPACIO[esp]) || "";
  }

  /** El pedazo de query para el `<iframe>` de un workspace. Vacío cuando está apagada:
   *  mandar `aleph_piel=` vacío obligaría al otro lado a distinguir «vacío» de «ausente»,
   *  y son la misma cosa. */
  function query(ws) {
    var v = version(ws);
    return v ? "&aleph_piel=" + encodeURIComponent(v) : "";
  }

  try { root.AlephPiel = { version: version, query: query, CLAVE: CLAVE, POR_ESPACIO: POR_ESPACIO }; } catch (e) {}
})(typeof window !== "undefined" ? window : globalThis);
