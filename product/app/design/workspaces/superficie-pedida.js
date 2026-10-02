/* superficie-pedida.js — «ABRIME EL ESPACIO PARADO EN ESTA SUPERFICIE». UNO PARA LAS SEIS.
 * [integración · el Settings del diseño]
 *
 * POR QUÉ EXISTE. `Aleph Settings.dc.html` (artboard 13a) dibuja cada espacio con sus filas
 * —Skills, Agent, Knowledge Base…— y el dueño decidió qué hacen: te llevan al espacio, parado
 * en esa superficie. No se reconstruye el panel de otro adentro de la casa (Ley 6) y no se
 * inventa un contrato nuevo: se usa el ruteo que cada stack YA tiene, y el destino viaja por
 * la URL del iframe, que es el mismo camino por el que ya van el tema, el idioma y el chat.
 *
 * DOS FORMAS, PORQUE LOS STACKS NO SON IGUALES — medido, no supuesto:
 *
 *   `?ir=/agent`      el stack es un router y la superficie tiene URL propia. Se le cuelga al
 *                     origen y listo. Finanzas (`router.tsx:52-65`) y Educación (`app/…`).
 *   `?panel=skills`   el stack abre su ajuste en un DIÁLOGO, no en una ruta: Ciencia, con
 *                     `dialog-settings.tsx` sobre `settings/registry.ts`. Ahí no hay path que
 *                     colgar, así que viaja como `aleph_panel` y lo lee el stack.
 *
 * ⚠️ LO QUE LLEGA POR LA URL ES UN DATO, NO UNA ORDEN. La ruta se acota a `/[a-z0-9/-]` y el
 * panel a `[a-z-]`: sin eso, un `?ir=//otro-host` convertiría esta línea en un redirector
 * abierto hacia adentro del iframe. Cualquier cosa que no encaje se descarta y el espacio
 * abre en su raíz, que es lo que hacía antes de que este archivo existiera.
 */
(function () {
  "use strict";

  function param(k) {
    try { return new URLSearchParams(location.search).get(k) || ""; } catch (e) { return ""; }
  }

  window.AlephSuperficie = {
    /** El path a colgarle al origen del stack, o `"/"` si no se pidió ninguno. */
    ruta: function () {
      var v = param("ir");
      return /^\/[a-z0-9][a-z0-9/-]*$/i.test(v) && v.indexOf("//") < 0 ? v : "/";
    },
    /** El pedazo de query del panel, o `""`. Va con `&` porque siempre se suma a un `?…`. */
    panel: function () {
      var v = param("panel");
      return /^[a-z][a-z-]*$/i.test(v) ? "&aleph_panel=" + encodeURIComponent(v) : "";
    },
  };
})();
