/* destinos-del-espacio.js — LOS 11 DESTINOS DE LA CASA, DESDE ADENTRO DE UN WORKSPACE.
 * [convergencia · superficie 8]
 *
 * EL HUECO QUE TAPA, MEDIDO. La barra de un workspace tenía UNA salida: «◂ La Sala». O sea
 * que desde acá adentro los otros diez destinos de la casa —Modelos, Conectores, Historial,
 * Biblioteca, Métodos, Inspección…— costaban DOS saltos: primero a la Sala, después al
 * destino. Y el primero no es gratis: salir apaga el pack.
 *
 * Ahora es UN salto. Lo que NO cambia —y no puede cambiar— es que salir sigue apagando el
 * pack: `salir()` corre también en `pagehide`, así que cualquier navegación lo cierra. Eso
 * es el ciclo de vida del pack (es por visita) y no una limitación de este panel. Lo que se
 * ahorra es el salto de más, no el apagado.
 *
 * POR QUÉ ES UN PANEL DE LA BARRA. Por lo mismo que `conectores-del-espacio.js` lo dice y
 * lo dejó escrito: el lienzo es ENTERO un `iframe` del stack, así que no hay lugar «debajo»
 * que no sea robarle espacio a la pieza ajena. Lo único de la casa acá es la barra de
 * arriba. Este archivo NO reimplementa ese patrón: usa las MISMAS clases
 * (`ws-conect-entrada`, `ws-conect-panel`, `ws-conect-head`) que ya están en
 * `workspace.css`, así que los dos paneles de la barra se ven y se cierran igual.
 *
 * ⚠️ LA LISTA NO ES DE ACÁ. Sale de `window.AlephDestinos`, que publica `nav.js` — la misma
 * tabla que pinta la barra de las otras 17 pantallas. Escribir los once destinos acá habría
 * sido la TERCERA copia, y la segunda ya había derivado hasta enlazar documentación interna
 * (ver el comentario de la tabla en `nav.js`).
 */
(function () {
  "use strict";

  function texto(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function tr(k, fb) {
    try { var v = window.t ? window.t(k) : null; return (v && v !== k) ? v : fb; }
    catch (e) { return fb; }
  }

  window.AlephDestinosDelEspacio = {
    /** @param ws  el id del workspace, sólo para el rótulo de ámbito del panel */
    montar: function (ws) {
      var barra = document.querySelector(".ws-bar");
      var D = window.AlephDestinos;
      // SIN TABLA NO HAY BOTÓN. Un botón que abre un panel vacío es peor que no tenerlo:
      // promete una salida que no existe. Si `nav.js` no cargó, esta pantalla queda
      // exactamente como estaba.
      if (!D || !D.items || !D.items.length) return;
      /* [Finanzas · el nudo de las dos barras] LA BARRA DEJÓ DE SER OBLIGATORIA.
       * Antes esto pedía `.ws-bar` y, sin ella, no montaba NADA — ni panel. Con el shell
       * único la barra de la casa desaparece y el disparador se muda adentro del stack, que
       * pide por mensaje. Así que el PANEL se arma siempre y el BOTÓN sólo si hay dónde
       * ponerlo. La lógica no se toca: se mudó el disparador, no lo que hace. */

      var boton = document.createElement("button");
      boton.type = "button";
      boton.className = "ws-conect-entrada";
      boton.textContent = tr("ws.ir", "Ir a…");
      boton.setAttribute("aria-expanded", "false");
      boton.setAttribute("aria-haspopup", "true");

      var panel = document.createElement("section");
      panel.className = "ws-conect-panel";
      panel.hidden = true;
      panel.setAttribute("aria-label", tr("ws.ir.aria", "Destinos de Aleph"));

      // LA RUTA LA RESUELVE LA TABLA, ENTERA. Escribí primero `"../" + D.href(id)`
      // razonando que el `../` era de acá —esta pantalla vive un nivel más abajo que
      // `design/`— y quedaba `../../Modelos.dc.html`, o sea un destino roto en los seis
      // workspaces. `nav.js` ya calcula ese `../` con su `up`, porque `inApp` incluye
      // `/workspaces/` desde esta misma obra. Lo destapó correr la tabla, no leerla.
      function ruta(id) { return D.href(id); }

      function pintar() {
        var filas = D.items.map(function (it) {
          return '<li class="ws-conect-fila"><a class="ws-destino" href="' + texto(ruta(it.id)) + '">'
            + '<span class="ws-destino-gl" aria-hidden="true">' + it.icon + "</span>"
            + '<span>' + texto(D.etiqueta(it)) + "</span></a></li>";
        }).join("");
        panel.innerHTML =
          '<div class="ws-conect-head"><strong>' + texto(tr("ws.ir.tit", "Ir a…")) + "</strong>"
          + '<span class="ws-conect-ambito">' + texto(String(ws || "").toUpperCase()) + "</span></div>"
          + '<p class="ws-conect-copy">'
          + texto(tr("ws.ir.copy", "Salir cierra este banco de trabajo; al volver, tu hilo sigue donde estaba."))
          + "</p>"
          + '<ul class="ws-conect-lista">' + filas + "</ul>";
      }

      function cerrar() {
        panel.hidden = true;
        boton.setAttribute("aria-expanded", "false");
      }

      /* EL MISMO GESTO, UN SOLO CUERPO. El botón de la barra y el disparador que ahora vive
       * adentro del stack llaman los dos acá: si hubiera dos cuerpos, tarde o temprano uno
       * repintaría y el otro no. */
      function alternar() {
        if (!panel.hidden) return cerrar();
        pintar();                                  // se repinta al abrir: el idioma pudo cambiar
        panel.hidden = false;
        boton.setAttribute("aria-expanded", "true");
      }
      boton.addEventListener("click", alternar);
      /* Publicado para que la cáscara lo llame cuando el stack pida el panel por mensaje.
       * Es EL MISMO `alternar` que aprieta el botón — no una segunda implementación. */
      window.AlephDestinosDelEspacio.alternar = alternar;
      // Escape y click afuera, igual que el panel de Conectores. El `mousedown` global que
      // cerraba antes del click ya nos mordió una vez (obra E de Gate 3): acá se escucha
      // `click`, y el propio panel corta la burbuja.
      panel.addEventListener("click", function (ev) { ev.stopPropagation(); });
      document.addEventListener("click", function (ev) {
        if (panel.hidden) return;
        // Sin barra el botón no está en el documento: `contains` sobre un nodo suelto es
        // false y el panel se cerraría en el mismo click que lo abrió. Por eso se pregunta
        // primero si el botón está puesto.
        var delBoton = boton.isConnected && (ev.target === boton || boton.contains(ev.target));
        if (!delBoton) cerrar();
      });
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && !panel.hidden) { cerrar(); boton.focus(); }
      });

      // ANTES DEL ESTADO, por la misma razón escrita en los otros dos: así el botón no se
      // mueve cuando el pack pasa de «arrancando» a «listo».
      if (barra) {
        var estado = barra.querySelector("#ws-estado");
        if (estado) barra.insertBefore(boton, estado); else barra.appendChild(boton);
      }
      document.body.appendChild(panel);
    },
  };
})();
