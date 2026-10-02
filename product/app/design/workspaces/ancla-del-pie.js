/* ancla-del-pie.js — EL PIE DE LA CASA SOBREVIVE AL RIEL. EN LAS SEIS, CON UN SOLO CUERPO.
 * [rediseño · integración y cierre]
 *
 * POR QUÉ EXISTE. El diseño pide UNA barra de 260 y había dos: `aside.ws-riel` de la casa y
 * la del stack adentro del iframe. Las seis tandas resolvieron el nudo por separado y salieron
 * TRES respuestas distintas, medidas sobre main:
 *
 *   Oficina    borra el riel, pero MUDA el pie primero a un ancla headless   → funciona
 *   Educación  esconde el riel con CSS y deja el nodo                        → dos barras, una invisible
 *   Legal      idem                                                          → idem
 *   Ciencia    borra el riel A SECAS                                         → el pie se va con él
 *   Finanzas   borró el markup entero                                        → nunca hubo pie
 *   Diseño     idem                                                          → idem
 *
 * Y las cuatro últimas comparten una consecuencia que ninguna vara vio: `ajustes.js`,
 * `destinos-del-espacio.js` («Ir a…») y `conectores-del-espacio.js` («Conectores») se montan
 * solos buscando `.ws-bar`. Sin ese nodo no montan su BOTÓN — y el censo del pie, que le
 * contesta al stack qué existe para poder ofrecerlo, contesta una lista vacía. Los dos
 * botones quedan inalcanzables, en silencio. El comentario de `ciencia.html` llegó a decir
 * que los botones quedaban «en el ancla headless»: el ancla no existía en esa página.
 *
 * QUÉ HACE. Garantiza el ancla, con las dos entradas que el árbol tiene de verdad:
 *   · si el pie de la casa EXISTE (el riel está en el markup), lo MUEVE — el nodo, no una
 *     copia: `appendChild` mueve, y con él viajan handler, estado y panel de cada módulo.
 *   · si NO existe (la página ya borró el markup), lo CREA vacío: los módulos hacen
 *     `insertBefore(boton, estado)` sólo `if (estado)`, y si no hay estado hacen `appendChild`.
 * Después, y recién después, borra el riel. Nunca al revés.
 *
 * ⚠️ TIENE QUE CORRER ANTES QUE LOS TRES MÓDULOS, que se cargan al final del documento. Por
 * eso se llama desde el script inline de arriba de cada página y no desde un `DOMContentLoaded`:
 * si corriera después, los módulos ya habrían buscado `.ws-bar` en un documento sin ella.
 *
 * ⚠️ Y NO SE ESCONDE CON `display:none`: la regla `.ws-anclas` de `workspace.css` lo saca de
 * pantalla con `left:-10000px` justamente para que un módulo que mida su botón no lea ceros.
 */
(function () {
  "use strict";

  window.AlephAnclaDelPie = {
    /** @param ws  el id del espacio. Devuelve true si el frame está prendido y se ancló. */
    montar: function (ws) {
      try {
        if (!window.AlephPiel || window.AlephPiel.version(ws) !== "v2") return false;
        /* La marca de la raíz se pone igual: la regla de `workspace.css` es el respaldo para
         * el instante entre que la raíz se marca y este cuerpo termina. */
        document.documentElement.setAttribute("data-aleph-frame", "v2");

        var riel = document.querySelector("aside.ws-riel");
        var pie = document.querySelector(".ws-pie.ws-bar");
        if (!pie) {
          pie = document.createElement("div");
          pie.className = "ws-pie ws-bar";
          /* SIN `#ws-estado` inventado. El estado es del riel y las páginas que lo borraron
           * ya decidieron no tenerlo; los módulos anclan en él sólo `if (estado)`. Crear uno
           * acá le devolvería un destino a un texto que su página dio por muerto. */
        }

        var anclas = document.querySelector(".ws-anclas");
        if (!anclas) {
          anclas = document.createElement("div");
          anclas.className = "ws-anclas";
          anclas.setAttribute("aria-hidden", "true");
          document.body.insertBefore(anclas, document.body.firstChild);
        }
        anclas.appendChild(pie);   /* MUEVE el nodo si ya existía; lo cuelga si es nuevo */

        if (riel) riel.remove();   /* y recién ahora el riel deja de existir */
        return true;
      } catch (e) { return false; }
    },
  };
})();
